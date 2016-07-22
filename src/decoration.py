"""Randomly decorates unused blocks with props and missing tiles.

"""
from collections import defaultdict
from enum import Enum

from brushLoc import Block, POS
from srctools import Property, Vec, EmptyMapping
from srctools.vmf import Entity, EntityFixup
from conditions import make_result, meta_cond
import utils

from typing import (
    Union, Callable,
    Tuple, NamedTuple, List, Dict, Set
)

LOGGER = utils.getLogger(__name__, 'cond.deco')

Prop = NamedTuple('Prop', [
    ('model', str),
    ('skin', int),
    ('offset', Vec),
])

Instance = NamedTuple('Instance', [
    ('filename', str),
    ('offset', Vec),
    ('fixups', EntityFixup),
])

# Locations of marker points: origin -> set(normals)
MARKER_LOCS = defaultdict(set)  # type: Dict[Tuple[float, float, float], Set[Tuple[float, float, float]]]

# Name -> extra distance in each direction.
MARKER_SIZES = {
    '1x1': 0,
    '3x3': 1,
    '5x5': 2,
}

# Strings to combinations of blocks. Either a Block, tuple, or callable.
OCCUPY_TYPES = {
    'VOID': Block.VOID,
    # Pits are also empty...
    'AIR': (Block.AIR, Block.PIT_TOP, Block.PIT_MID),
    'SOLID': Block.SOLID,
    'EMBED': Block.EMBED,

    'GOO_FLOOR': (Block.GOO_BOTTOM, Block.GOO_SINGLE),
    'GOO_SURFACE': (Block.GOO_TOP, Block.GOO_SINGLE),

    'PIT_BOTTOM': (Block.PIT_BOTTOM, Block.PIT_SINGLE),
    'PIT_TOP': (Block.PIT_TOP, Block.PIT_SINGLE),

    'GOO': Block.is_goo,
    'BLOCK': Block.is_solid,
    'PIT': Block.is_pit,
}


def valid_pos(
    pos: Block,
    occu_type: Union[Block, Tuple[Block], property, Callable[[Block], bool]]
) -> bool:
    """Checks if a OCCUPY_TYPE is valid for a position."""
    if isinstance(occu_type, Block):
        return pos is occu_type
    elif isinstance(occu_type, tuple):
        return pos in occu_type
    elif isinstance(occu_type, property):
        return occu_type.fget(pos)
    else:
        return occu_type(pos)

# Convert each value to a set of matching block types.
# It's frozen so we can put these in dict keys.
OCCUPY_TYPES = {
    name: frozenset({
        block for block in Block
        if valid_pos(block, occu_type)
    }) for name, occu_type in
    OCCUPY_TYPES.items()
}

LOGGER.info(OCCUPY_TYPES)


class ORIENT(Enum):
    """Orientation types."""
    FLOOR = 'FLOOR'
    CEILING = 'CEILING'
    WALLS = 'WALLS'

DECORATIONS = []  # type: List[Decoration]


class Decoration:
    """Represents one decoration type."""
    def __init__(
        self,
        name,
        orient,
        rotation_interval=0,
        side_off=0,
        norm_off=-64,
        locs=EmptyMapping,
        props=(),
        instances=(),
    ):
        self.name = name
        self.orient = orient
        self.rotation = rotation_interval
        self.side_off = side_off
        self.norm_off = norm_off
        self.locs = dict(locs)
        self.props = list(props)
        self.instances = list(instances)

    @classmethod
    def parse(cls, props: Property):
        """Parse the property block for a decoration."""

        try:
            orient = ORIENT(props['orient', ''].upper())
        except ValueError:
            orient = ORIENT.FLOOR

        models = []
        instances = []
        locs = {}

        for model in props.find_all('Prop'):
            models.append(Prop(
                model['model'],
                model.int('skin', 0),
                model.vec('offset'),
            ))

        for inst in props.find_all('Instance'):
            fixups = EntityFixup()
            for fixup in inst.find_all('Fixup'):
                for var in fixup:
                    fixups[var.real_name] = var.value
            instances.append(Instance(
                inst['file', ''],
                inst.vec('offset'),
                fixups,
            ))

        for loc_block in props.find_all('RequiredSpace'):
            for pos in loc_block:
                try:
                    value = OCCUPY_TYPES[pos.name.upper()]
                except KeyError:
                    continue
                LOGGER.info('Req-Space: {!r} -> {}', pos, value)
                if pos.has_children():
                    bbox_min, bbox_max = Vec.bbox(
                        pos.vec('Pos1'),
                        pos.vec('Pos2'),
                    )
                    for x in range(int(bbox_min.x), int(bbox_max.x) + 1):
                        for y in range(int(bbox_min.y), int(bbox_max.y) + 1):
                            for z in range(int(bbox_min.z), int(bbox_max.z) + 1):
                                locs[x, y, z] = value
                else:
                    # One location
                    locs[Vec.from_str(pos.value).as_tuple()] = value

        if not locs:
            # By default, we want the square to be air, and the floor to be solid.
            locs[0, 0, 0] = OCCUPY_TYPES['AIR']
            locs[0, 0, -1] = OCCUPY_TYPES['BLOCK']

        return cls(
            props.real_name,
            orient,
            props.float('rotation', 0),
            props.float('side_off', 0),
            # Default to place things at the surface
            props.float('norm_off', -64),
            locs,
            models,
            instances,
        )

    def __str__(self):
        return (
            '<Deco: {orient}, {rotation} deg, +-'
            '({side}, {side}, {norm})>: \n{props}\n{inst}'.format(
                orient=self.orient,
                rotation=self.rotation,
                side=self.side_off,
                norm=self.norm_off,
                props=self.props,
                inst=self.instances
            )
        )


@make_result('DecorationMarker')
def res_deco_marker(inst: Entity, res: Property):
    """Identify this as a decoration marker. This removes the instance."""
    try:
        off = MARKER_SIZES[res.value]
    except KeyError:
        LOGGER.error('Invalid marker size: {}', res.value)
        return

    angles = Vec.from_str(inst['angles'])
    origin = Vec.from_str(inst['origin']) // 128

    normal = Vec(0, 0, 1).rotate(*angles).as_tuple()

    for x, y in utils.iter_grid(off + 1, off + 1, -off, -off):
        pos = (origin + Vec(x, y, 0).rotate(*angles)).as_tuple()
        # Ignore markers positioned inside walls and in void.
        if POS[pos].traversable:
            MARKER_LOCS[pos].add(normal)

    inst.remove()


def load_deco():
    DECORATIONS.clear()
    with open('bee2/decoration.cfg') as f:
        props = Property.parse(f)
    for deco_block in props.find_all('Decorations'):
        for deco in deco_block:
            DECORATIONS.append(Decoration.parse(deco))
    LOGGER.info('Loaded decoration data..')


@meta_cond(priority=300, only_once=True)
def place_decorations(_):
    """Place decorations into the map."""
    LOGGER.info(
        'Placing decorations ({} marked spots), {} possible decorations.',
        len(MARKER_LOCS),
        len(DECORATIONS),
    )
    if not MARKER_LOCS or not DECORATIONS:
        return

    # First, we want to figure out all unique placement shapes for items.
    placement = defaultdict(list)
    for deco in DECORATIONS:
        shape = frozenset({
            (x, y, z, block)
            for (x, y, z), block in
            deco.locs.items()
        })
        placement[shape].append(deco)

