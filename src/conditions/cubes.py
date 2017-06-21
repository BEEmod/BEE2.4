"""Implement cubes and droppers."""
from enum import Enum
from typing import Dict, Optional, List, Union, Tuple

import brushLoc
from conditions import meta_cond, make_result, make_flag
from instanceLocs import resolve as resolve_inst, resolve_one
from srctools import Property, NoKeyError, VMF, Entity, Vec, Output
import utils

LOGGER = utils.getLogger(__name__, 'cond.cubes')

COND_MOD_NAME = 'Cubes/Droppers'

# All the cube types we have loaded
CUBE_TYPES = {}  # type: Dict[str, CubeType]
# All the cubes/droppers
CUBES = []  # type: List[CubeData]

# The IDs for the default cube types, matched to the $cube_type value.
VALVE_CUBE_IDS = {
    0: 'VALVE_CUBE_STANDARD',
    1: 'VALVE_CUBE_COMPANION',
    2: 'VALVE_CUBE_REFLECTION',
    3: 'VALVE_CUBE_SPHERE',
    6: 'VALVE_CUBE_FRANKEN',
}


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

class CubeOutputs(Enum):
    """Inputs/outputs for cubes which can be configured."""
    # !self is replaced by the cube ent
    SPAWN = 'OnSpawn'  # When created - !self replaced by cube.
    FIZZLED = 'OnFizzle'  # When dissolved...
    DROP_START = 'OnStartDrop'  # When starting to drop.
    DROP_DONE = 'OnFinishedDrop'  # When totally out of the dropper.


class CubeType:
    """A type of cube that can be spawned from droppers."""
    def __init__(
        self,
        id: str,
        cube_type: CubeEntType,
        has_name: str,
        cube_item_id: Optional[str],
        model: Optional[str],
        model_color: Optional[str],
        pack: Union[str, List[str]],
        pack_color: Union[str, List[str]],
        base_offset: float,
        outputs: Dict[CubeOutputs, List[Output]],
    ):
        self.id = id
        # If set, the custom item representing this item ID.
        self.item_id = cube_item_id

        # Suffix for voice attributes.
        self.has_name = has_name.casefold()
        # Basic type - the kind of cube entity to use.
        self.type = cube_type

        # Special cased, these don't link upwards.
        self.is_valve_cube = id in VALVE_CUBE_IDS.values()

        # Models for normal and colorized versions.
        # If set it swaps to that model.
        self.model = model
        self.model_color = model_color

        # List of files, or a str packlist ID.
        self.pack = pack
        self.pack_color = pack_color

        # Distance from model origin to the 'floor'.
        self.base_offset = base_offset

        # Configurable outputs for the cube/dropper.
        self.outputs = outputs

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

        outputs = {}

        for out_type in CubeOutputs:
            outputs[out_type] = out_list = []
            for prop in info.find_all(out_type.value):
                out_list.append(Output.parse(prop))

        return CubeType(
            cube_id,
            cube_type,
            info['hasName'],
            cube_item_id,
            cust_model,
            cust_model_color,
            packlist,
            packlist_color,
            info.float('offset', 20),
            outputs,
        )


class CubeData:
    """Represents a single cube/dropper pair."""
    def __init__(
        self,
        type: CubeType,
        dropper: Optional[Entity],
        cube: Optional[Entity],
        tint: Tuple[int, int, int]=None,
    ):
        self.type = type
        self.dropper = dropper
        self.cube = cube
        self.tint = tint  # If set, Colorizer color to use.

    def __repr__(self):
        drop = cube = ''
        if self.dropper:
            drop = self.dropper['targetname']
        if self.cube:
            cube = self.cube['targetname']
        return '<CubeData "{}" {!r} -> {!r}>'.format(
            self.type.id, drop, cube,
        )


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
    for cube_id in VALVE_CUBE_IDS.values():
        if cube_id not in CUBE_TYPES:
            raise Exception('Cube type "{}" is missing!'.format(cube_id))


@make_flag('CubeType')
def flag_cube_type(inst: Entity, res: Property):
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

    valve_dropper = resolve_one('<ITEM_DROPPER_CUBE>', error=True)

    # Origin -> instances
    dropper_pos = {}  # type: Dict[Tuple[float, float, float], Entity]
    # Timer value -> instances if not 0.
    dropper_timer = {}  # type: Dict[int, Entity]
    # Instance -> has a cube linked to this yet?
    used_droppers = {}  # type: Dict[Entity, bool]

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
            used_droppers[inst] = False
        else:
            try:
                cube_type = inst_to_type[filename]
            except KeyError:
                # Not a cube of any kind!
                continue
            else:
                # A dropperless cube.
                cubes.append((inst, cube_type))

    # Now link and match up all the cubes.
    for cube, cube_type in cubes:
        # First look for a timer value, for linking cubes specifically.
        timer = cube.fixup.int('$timer_delay', 0)
        # Infinite and 3 (default) are treated as off.
        if 3 < timer <= 30:
            try:
                dropper = dropper_timer[timer]
            except KeyError:
                raise ValueError(
                    'Unknown cube "linkage" value ({}) in cube!\n'
                    'A cube has a timer set which doesn\'t match '
                    'any droppers.'.format(timer)
                ) from None
            if used_droppers[dropper]:
                raise ValueError(
                    'Dropper tried to link to two cubes! (timer={})'.format(
                        timer
                    )) from None
            used_droppers[dropper] = True

            CUBES.append(CubeData(cube_type, dropper, cube))
            continue

        # Next try to link to a dropper on the ceiling.
        # We don't do this for Valve cubes, since those
        # already can set their types.
        if not cube_type.is_valve_cube:
            ceil_pos = brushLoc.POS.raycast_world(
                Vec.from_str(cube['origin']),
                direction=(0, 0, 1),
            )
            try:
                dropper = dropper_pos[ceil_pos]
            except KeyError:
                pass  # Drop out of if
            else:
                if used_droppers[dropper]:
                    raise ValueError(
                        'Dropper above custom cube is already'
                        ' linked!\n'
                        'Cube type: {}'.format(cube_type.id)
                    ) from None
                used_droppers[dropper] = True
                CUBES.append(CubeData(cube_type, dropper, cube))
                continue

        # Otherwise, both cases fail - the cube is dropperless.
        CUBES.append(CubeData(cube_type, cube=cube, dropper=None))

    # Now cubes are done, loop through the remaining droppers and assign
    # Valve cube types to those.
    for dropper, is_used in used_droppers.items():
        if is_used:
            continue
        cube_type_num = dropper.fixup.int('$cube_type')
        try:
            cube_type = CUBE_TYPES[VALVE_CUBE_IDS[cube_type_num]]
        except KeyError:
            raise ValueError('Bad cube type "{}"!'.format(
                dropper.fixup['$cube_type']
            )) from None
        CUBES.append(CubeData(cube_type, dropper=dropper, cube=None))

    # Setup Voice 'Has' attrs.
    from vbsp import settings
    voice_attr = settings['has_attr']  # type: Dict[str, bool]

    for data in CUBES:
        has_name = data.type.has_name
        voice_attr['cube'] = True
        voice_attr['cube' + has_name] = True
        if data.dropper:
            voice_attr['cubedropper'] = True
            voice_attr['cubedropper' + has_name] = True
        else:
            voice_attr['cubedropperless' + has_name] = True


@meta_cond(priority=750, only_once=True)
def generate_cubes(vmf: VMF):
    """After other conditions are run, generate cubes."""
    pass