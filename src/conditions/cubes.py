"""Implement cubes and droppers."""
import weakref
from enum import Enum
from typing import Dict, Optional, List, Union, Tuple

import brushLoc
import instance_traits
from conditions import meta_cond, make_result, make_flag
from instanceLocs import resolve as resolve_inst, resolve_one
from srctools import Property, NoKeyError, VMF, Entity, Vec
import utils

LOGGER = utils.getLogger(__name__, 'cond.cubes')

# All the cube types we have loaded
CUBE_TYPES = {}  # type: Dict[str, CubeType]
# Maps instances of cubes to the CubeData for them.
CUBES = weakref.WeakKeyDictionary()  # type: Dict[Entity, CubeData]

# The IDs for the default cube types in order.
VALVE_CUBE_IDS = [
    'VALVE_CUBE_STANDARD',
    'VALVE_CUBE_COMPANION',
    'VALVE_CUBE_REFLECTION',
    'VALVE_CUBE_SPHERE',
    'VALVE_CUBE_FRANKEN',  # type = 7, not 5.
]


class CubeEntType(Enum):
    """Cube types, as set on prop_weighted_cube.

    This is used to set behaviour and gel skins for items.
    """
    norm = 'WEIGHTED'
    comp = 'COMPANION'
    reflect = 'REFLECTION'
    sphere = 'SPHERE'
    antique = 'ANTIQUE'
    franken = 'FRANKEN'  # prop_monster_box


class CubeType:
    """A type of cube that can be spawned from droppers."""
    def __init__(
        self,
        id: str,
        cube_type: CubeEntType,
        cube_item_id: Optional[str],
        model: Optional[str],
        model_color: Optional[str],
        pack: Union[str, List[str]],
        pack_color: Union[str, List[str]],
        base_offset: float,
    ):
        self.id = id
        # If set, the custom item representing this item ID.
        self.item_id = cube_item_id
        # Basic type - the kind of cube entity to use.
        self.type = cube_type

        # Special cased, these don't link upwards.
        self.is_valve_cube = id in VALVE_CUBE_IDS

        # Models for normal and colorized versions.
        # If set it swaps to that model.
        self.model = model
        self.model_color = model_color

        # List of files, or a str packlist ID.
        self.pack = pack
        self.pack_color = pack_color

        # Distance from model origin to the 'floor'.
        self.base_offset = base_offset

    @classmethod
    def parse(cls, info: Property):
        """Parse from vbsp_config."""
        cube_id = info['id'].upper()

        cube_item_id = info['itemid', ''].upper() or None

        packlist = info.find_key('Pack', '')
        if packlist.has_children():
            # Each file individually
            packlist = [
                prop.value for prop in packlist
            ]
        else:
            # One value - packlist ID
            packlist = packlist.value

        packlist_color = info.find_key('PackColor', '')
        if packlist_color.has_children():
            packlist_color = [
                prop.value for prop in packlist_color
            ]
        else:
            packlist_color = packlist_color.value

        try:
            cube_type = CubeEntType(info['cubetype'].upper())
        except ValueError:
            raise ValueError('Bad cube type "{}" for {}'.format(
                info['cubetype'], cube_id)
            ) from None
        except NoKeyError:
            raise ValueError('No cube type for "{}"!'.format(cube_id)) from None

        if cube_type is CubeEntType.franken:
            # Frankenturrets can't swap their model.
            cust_model = cust_model_color = None
        else:
            cust_model = info['model', None]
            cust_model_color = info['modelColor', None]

        return CubeType(
            cube_id,
            cube_type,
            cube_item_id,
            cust_model,
            cust_model_color,
            packlist,
            packlist_color,
            info.float('offset', 20),
        )


class CubeData:
    """Represents a single cube/dropper pair."""
    def __init__(
        self,
        type: CubeType,
        dropper: Optional[Entity],
        cube: Optional[Entity],
        tint: Optional[Tuple[int, int, int]],
    ):
        self.type = type
        self.dropper = dropper
        self.cube = cube
        self.tint = tint # If set, Colorizer color to use.


def parse_cubes(conf: Property):
    """Parse the config file for cube info."""
    for cube_conf in conf.find_all('DropperItems', 'Cube'):
        cube = CubeType.parse(cube_conf)

        if cube.id in CUBE_TYPES:
            raise ValueError('Duplicate cube ID "{}"'.format(cube.id))

        CUBE_TYPES[cube.id] = cube

    LOGGER.info('Parsed {} cube types.', len(CUBE_TYPES))

    # Check we have the Valve cube definitions - if we don't, something's
    # wrong.
    for cube_id in VALVE_CUBE_IDS:
        if cube_id not in CUBE_TYPES:
            raise Exception('Cube type "{}" is missing!'.format(cube_id))


@make_flag('CubeType')
def cube_type(inst: Entity, res: Property):
    """Check if an instance is/should be a cube.

    This is only valid on ITEM_BOX_DROPPER, ITEM_CUBE, and items marked as
    a custom dropperless cube.
    The value should be the ID of a cube type, or <any>/<none>.
    """
    try:
        data = inst.bee2_cube_data  # type: CubeData
    except AttributeError:
        return res.value.casefold() == '<none>'

    if res.value.casefold() == '<any>':
        return True

    return data.type.id == res.value.upper()


@meta_cond(priority=-1000, only_once=True)
def link_cubes(vmf: VMF):
    """Determine the cubes set based on instance settings.

    This sets data, but doesn't implement the changes.
    """
    # Dropperless cube -> cubetype value.
    inst_to_type = {}  # type: Dict[str, CubeType]

    for cube_type in CUBE_TYPES.values():
        if not cube_type.item_id:
            continue
        for inst in resolve_inst(cube_type.item_id):
            inst_to_type[inst] = cube_type

    valve_dropper = resolve_one('<ITEM_CUBE_DROPPER>', error=True)

    # Origin -> instances
    dropper_pos = {}
    # Timer value -> instances if not 0.
    dropper_timer = {}

    # Cube items.
    cubes = []  # type: List[Tuple[Entity, CubeType]]

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()

        # A dropper.
        if filename == valve_dropper:
            timer = inst.fixup.int('$timer_delay', 0)
            # Infinite and 3 (default) are treated as off.
            if 3 < timer <= 30:
                if timer in dropper_timer:
                    raise ValueError(
                        'Two droppers with the same '
                        'timer value: ' + str(timer)
                    )
                dropper_timer[timer] = inst
            # For setup later.
            dropper_pos[Vec.from_str(inst['origin']).as_tuple()] = inst
        else:
            try:
                cube_type = inst_to_type[filename]
            except KeyError:
                # Not a cube of any kind!
                continue
            else:
                # A dropperless cube.
                cubes.append((inst, cube_type))

    for cube, cube_type in cubes:

        if not cube_type.is_valve_cube:
            # Find a potential dropper on the ceiling.
            # We don't do this for Valve cubes, since those
            # already can set their types.

            ceil_pos = brushLoc.POS.raycast_world(
                Vec.from_str(cube['origin']),
                direction=(0, 0, 1),
            )
