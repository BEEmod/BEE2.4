"""Randomly decorates unused blocks with props and missing tiles.

"""
from enum import Enum

import utils
from brushLoc import Block, POS
from srctools import Property, Vec, EmptyMapping
from srctools.vmf import Entity, EntityFixup

from typing import Union, Tuple, Callable, NamedTuple

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
    occu_type: Union[Block, Tuple[Block], Callable[[Block], bool]]
) -> bool:
    """Checks if a OCCUPY_TYPE is valid for a position."""
    if occu_type is pos:
        return True
    elif isinstance(occu_type, tuple):
        return pos in occu_type
    else:
        return occu_type(pos)


class ORIENT(Enum):
    """Orientation types."""
    FLOOR = 'FLOOR'
    CEILING = 'CEILING'
    WALLS = 'WALLS'

DECORATIONS = []

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

        LOGGER.info('"{}": {}', name, vars(self))

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
                if pos.has_children():
                    bbox_min, bbox_max = Vec.bbox(
                        pos.vec('Pos1'),
                        pos.vec('Pos2'),
                    )
                    for x in range(int(bbox_min.x), int(bbox_max.x)):
                        for y in range(int(bbox_min.y), int(bbox_max.y)):
                            for z in range(int(bbox_min.z), int(bbox_max.z)):
                                locs[x, y, z] = pos.name
                else:
                    # One location
                    locs[Vec.from_str(pos.value).as_tuple()] = pos.name

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


def load_deco():
    DECORATIONS.clear()
    with open('bee2/decoration.cfg') as f:
        props = Property.parse(f)
    for deco_block in props.find_all('Decoration'):
        for deco in deco_block:
            DECORATIONS.append(Decoration.parse(deco))
    LOGGER.info('Loaded decoration data..')
