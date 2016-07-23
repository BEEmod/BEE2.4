"""Randomly decorates unused blocks with props and missing tiles.

"""
from collections import defaultdict
from enum import Enum
import random

from brushLoc import Block, POS, grid_to_world
from srctools import Property, Vec, EmptyMapping, conv_int
from srctools.vmf import Entity, EntityFixup
from conditions import make_result, meta_cond
import utils

from typing import (
    Union, Callable,
    Tuple, NamedTuple, List, Dict, Set
)


LOGGER = utils.getLogger(__name__, 'cond.deco')

SETTINGS = {
    # Percent of positions that will get decorations..
    'percent_deco': 75,
    'deco_variance': 10,  # +- this quantity.
}

Prop = NamedTuple('Prop', [
    ('model', str),
    ('skin', int),
    ('offset', Vec),
    ('no_shadows', bool),
])

Instance = NamedTuple('Instance', [
    ('filename', str),
    ('offset', Vec),
    ('fixups', EntityFixup),
])

NoPortalVolume = NamedTuple('NoPortalVolume', [
    ('pos1', Vec),
    ('pos2', Vec),
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

class ROT_TYPES:
    PITCH = 'x'
    YAW = 'y'
    ROLL = 'z'
    NONE = ''

DECORATIONS = []  # type: List[Decoration]


class Decoration:
    """Represents one decoration type."""
    def __init__(
        self,
        name,
        orient,
        rotation: Vec=(0, 0, 0),
        block_others=False,
        side_off=0,
        norm_off=-64,
        rot_off=(0, 0, 0),
        locs=EmptyMapping,
        props=(),
        instances=(),
        noport=(),
    ):
        # We don't flip the rotation, so this gets used in the wrong direction.
        if orient is ORIENT.CEILING:
            norm_off = -norm_off

        self.name = name
        self.orient = orient
        self.rotation = Vec(rotation)
        self.block_others = block_others
        self.side_off = side_off
        self.norm_off = norm_off
        self.rot_off = Vec(rot_off)
        self.locs = dict(locs)
        self.props = list(props)  # type: List[Prop]
        self.noport = list(noport)  # type: List[NoPortalVolume]
        self.instances = list(instances)  # type: List[Instance]

    @classmethod
    def parse(cls, props: Property):
        """Parse the property block for a decoration."""

        try:
            orient = ORIENT(props['orient', ''].upper())
        except ValueError:
            orient = ORIENT.FLOOR

        models = []
        instances = []
        noportal_volumes = []
        locs = {}

        for model in props.find_all('Prop'):
            models.append(Prop(
                model['model'],
                model.int('skin', 0),
                model.vec('offset'),
                model.bool('no_shadows'),
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

        for noport in props.find_all('NoPortal'):
            noportal_volumes.append(NoPortalVolume(
                noport.vec('pos1'),
                noport.vec('pos2'),
            ))

        for loc_block in props.find_all('RequiredSpace'):
            for pos in loc_block:
                try:
                    value = OCCUPY_TYPES[pos.name.upper()]
                except KeyError:
                    continue
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
            props.vec('Rotation'),
            props.bool('BlocksOthers'),
            props.float('sideOff', 0),
            # Default to place things at the surface
            props.float('normOff', -64),
            props.vec('rotOff'),
            locs,
            models,
            instances,
            noportal_volumes,
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

    def place(self, marker_pos: Vec, rot_angles: Vec):
        """Place a decoration at this position, and return all occupied locations."""
        from vbsp import VMF

        world_pos = Vec(grid_to_world(marker_pos))
        offset = Vec(
            random.uniform(-self.side_off, +self.side_off),
            random.uniform(-self.side_off, +self.side_off),
            self.norm_off,
        ).rotate(*rot_angles)

        rand_angles = Vec(rot_angles)

        # Randomise rotation as desired...
        for axis, dist in zip('xyz', self.rotation):
            if dist == 0:
                continue
            elif dist == 180:
                rand_angles[axis] += random.choice((0, 180)) % 360
            else:
                rand_angles[axis] += random.uniform(-dist, dist)

                rand_angles[axis] %= 360

        # First rotate around the given offset..
        origin = Vec(-self.rot_off).rotate(*rand_angles) + self.rot_off
        origin += offset + world_pos

        for prop in self.props:
            VMF.create_ent(
                classname='prop_static',
                origin=origin + Vec(prop.offset).rotate(*rand_angles),
                angles=rand_angles,
                model=prop.model,
                skin=prop.skin,
                disableshadows=int(prop.no_shadows),
            )

        for pos1, pos2 in self.noport:
            # noportal_volumes use the bounding box, so just use that for the shape.

            # All combinations of the positions -> the corners of the brush.
            corners = [
                Vec(pos1.x, pos1.y, pos1.z),
                Vec(pos2.x, pos1.y, pos1.z),
                Vec(pos1.x, pos2.y, pos1.z),
                Vec(pos2.x, pos2.y, pos1.z),
                Vec(pos1.x, pos1.y, pos2.z),
                Vec(pos2.x, pos1.y, pos2.z),
                Vec(pos1.x, pos2.y, pos2.z),
                Vec(pos2.x, pos2.y, pos2.z),
            ]
            for v in corners:
                v.localise(origin, rand_angles)
            noport = VMF.create_ent(classname='func_noportal_volume')
            pos1, pos2 = Vec.bbox(corners)
            noport.solids.append(VMF.make_prism(
                pos1,
                pos2,
                mat='tools/toolsinvisible',
            ).solid)

        # Return the positions we used so we can invalidate them for others.
        return [
            (marker_pos + Vec(loc).rotate(*rot_angles)).as_tuple()
            for loc in self.locs
        ]


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
            if deco.has_children():
                DECORATIONS.append(Decoration.parse(deco))
            elif deco.name == 'percent':
                SETTINGS['percent_deco'] = conv_int(deco.value.rstrip('%'), 60)
            elif deco.name == 'variance':
                SETTINGS['deco_variance'] = conv_int(deco.value, 0)
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
    placement = defaultdict(lambda: defaultdict(list))
    for deco in DECORATIONS:
        shape = frozenset(deco.locs.items())
        placement[deco.orient][shape].append(deco)

    # Now figure out what can fit in each position...
    poss_deco = []

    for marker_pos, normals in MARKER_LOCS.items():
        if (0, 0, 1) in normals:
            for yaw in range(0, 360, 90):
                add_poss_deco(
                    poss_deco,
                    marker_pos,
                    placement,
                    ORIENT.FLOOR,
                    Vec(0, yaw, 0),
                )
        if (0, 0, -1) in normals:
            for yaw in range(0, 360, 90):
                add_poss_deco(
                    poss_deco,
                    marker_pos,
                    placement,
                    ORIENT.CEILING,
                    Vec(0, yaw, 0),
                )

    deco_quant = (
        SETTINGS['percent_deco'] / 100 * len(MARKER_LOCS) +
        random.randint(-SETTINGS['deco_variance'], SETTINGS['deco_variance'])
    )

    LOGGER.info('{}/{} possible positions...', deco_quant, len(poss_deco))

    random.shuffle(poss_deco)

    used_locs = set()
    block_locs = set()

    added_count = 0

    # Start adding decorations...
    while poss_deco and added_count < deco_quant:
        (pos, deco, angles) = poss_deco.pop()

        if deco.block_others:
            blacklist = used_locs
        else:
            blacklist = block_locs

        if not check_placement(deco.locs.items(), pos, angles, blacklist):
            continue  # Already occupied by another decoration..

        occu_locs = deco.place(pos, angles)
        if deco.block_others:
            blacklist.update(occu_locs)
        used_locs.update(occu_locs)
        added_count += 1


def add_poss_deco(
    poss_deco,
    marker_pos,
    placement,
    orientation,
    rot_angles: Vec,
):
    """Check to see if decorations fit here, and add them to the list."""
    marker_pos = Vec(marker_pos)
    for shape, deco in placement[orientation].items():
        if check_placement(shape, marker_pos, rot_angles):
            poss_deco.extend((marker_pos, dec, rot_angles) for dec in deco)


def check_placement(shape, marker_pos: Vec, rot_angles: Vec, blacklist=()):
    """Check if a placement shape can fit here."""
    for pos, occu_type in shape:
        block_pos = (Vec(pos).rotate(*rot_angles) + marker_pos).as_tuple()
        if block_pos in blacklist or POS[block_pos] not in occu_type:
            break
    else:
        return True
    return False