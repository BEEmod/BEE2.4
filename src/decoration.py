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
    # 'SOLID': Block.SOLID,
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
        chance=100,
        rotation: Vec=(0, 0, 0),
        block_others=False,
        side_off=0,
        vert_off=0,
        norm_off=-64,
        rot_off=(0, 0, 0),
        occu_locs=(),
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
        self.chance = chance
        self.rotation = Vec(rotation)
        self.block_others = block_others
        self.side_off = side_off
        self.norm_off = norm_off
        self.vert_off = vert_off
        self.rot_off = Vec(rot_off)
        self.occu_locs = set(occu_locs)
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
        occu_space = set()

        for model in props.find_all('Prop'):
            models.append(Prop(
                model['model'],
                model.int('skin', 0),
                model.vec('offset'),
                model.bool('NoShadow'),
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
                    for x, y, z in Vec.iter_grid(bbox_min, bbox_max):
                        locs[x, y, z] = value
                else:
                    # One location
                    locs[Vec.from_str(pos.value).as_tuple()] = value

        for loc_block in props.find_all('OccupiedVoxels'):
            for pos in loc_block:
                if pos.has_children():
                    bbox_min, bbox_max = Vec.bbox(
                        pos.vec('Pos1'),
                        pos.vec('Pos2'),
                    )
                    for sub_loc in Vec.iter_grid(bbox_min, bbox_max):
                        occu_space.add(sub_loc.as_tuple())
                else:
                    # One location
                    occu_space.add(Vec.from_str(pos.value).as_tuple())

        if not locs:
            # By default, we want the square to be air, and the floor to be solid.
            locs[0, 0, 0] = OCCUPY_TYPES['AIR']
            locs[0, 0, -1] = OCCUPY_TYPES['BLOCK']

        if not occu_space:
            # We default to occupying the center block only.
            occu_space = {(0, 0, 0)}

        return cls(
            props.real_name,
            orient,
            props.int('Chance', 100),
            props.vec('Rotation'),
            props.bool('BlocksOthers'),
            props.float('sideOff', 0),
            props.float('vertOff', 0),
            # Default to place things at the surface
            props.float('normOff', -64),
            props.vec('rotOff'),
            occu_space,
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

    def place(self, marker_pos: Vec, rot_angles: Vec, blocked_pos: Set[tuple]) -> int:
        """Try to place a decoration at this position, and return the number actually placed."""

        occu_pos = []
        for pos in self.occu_locs:
            pos = Vec(pos)
            pos.localise(marker_pos, rot_angles)
            occu_pos.append(pos.as_tuple())

        # Ensure we don't overlap another decoration, or place one outside
        # the markers.
        for pos in occu_pos:
            if pos in blocked_pos or pos not in MARKER_LOCS:
                return 0

        from vbsp import VMF

        world_pos = Vec(grid_to_world(marker_pos))
        if self.orient is ORIENT.WALLS:
            offset = Vec(
                self.norm_off,
                random.uniform(-self.side_off, +self.side_off),
                random.uniform(-self.vert_off, +self.vert_off),
            ).rotate(*rot_angles)
        else:
            offset = Vec(
                random.uniform(-self.side_off, +self.side_off),
                random.uniform(-self.side_off, +self.side_off),
                self.norm_off + random.uniform(-self.vert_off, +self.vert_off),
            ).rotate(*rot_angles)

        rand_angles = Vec(rot_angles)

        # Randomise rotation as desired...
        for axis, dist in zip('xyz', self.rotation):
            if dist == 0:
                continue
            elif dist == 180:
                rand_angles[axis] += random.choice((0, 180))
            elif dist == 90:
                rand_angles[axis] += random.randrange(0, 360, 90)
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

        if self.block_others:
            blocked_pos.update(occu_pos)

        return 1


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
    poss_deco = defaultdict(list)

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

        if (1, 0, 0) in normals:
            add_poss_deco(
                poss_deco,
                marker_pos,
                placement,
                ORIENT.WALLS,
                Vec(0, 0, 0),
            )
        if (-1, 0, 0) in normals:
            add_poss_deco(
                poss_deco,
                marker_pos,
                placement,
                ORIENT.WALLS,
                Vec(0, 180, 0),
            )
        if (0, 1, 0) in normals:
            add_poss_deco(
                poss_deco,
                marker_pos,
                placement,
                ORIENT.WALLS,
                Vec(0, 270, 0),
            )
        if (0, -1, 0) in normals:
            add_poss_deco(
                poss_deco,
                marker_pos,
                placement,
                ORIENT.WALLS,
                Vec(0, 90, 0),
            )

    deco_quant = (
        SETTINGS['percent_deco'] / 100 * len(poss_deco) +
        random.randint(-SETTINGS['deco_variance'], SETTINGS['deco_variance'])
    )

    LOGGER.info('{}/{} possible positions...', deco_quant, len(poss_deco))

    block_locs = set()

    added_count = 0

    # Start adding decorations...
    while poss_deco and added_count < deco_quant:
        pos, decorations = poss_deco.popitem()
        if not decorations:
            continue

        pos = Vec(pos)

        # Add a random number of decorations to this location.
        random.shuffle(decorations)
        decorations = decorations[:random.randrange(len(decorations))]

        for deco, angles in decorations:
            added_count += deco.place(pos, angles, block_locs)


def add_poss_deco(
    poss_deco: Dict[Tuple[int, int, int], List[Tuple[Decoration, Vec]]],
    marker_pos,
    placement,
    orientation,
    rot_angles: Vec,
):
    """Check to see if decorations fit here, and add them to the list."""
    marker_pos = Vec(marker_pos)
    for shape, decorations in placement[orientation].items():
        if check_placement(shape, marker_pos, rot_angles):
            for deco in decorations:
                if random.randrange(100) > deco.chance:
                    continue

                poss_deco[marker_pos.as_tuple()].append(
                    (deco, rot_angles),
                )


def check_placement(shape, marker_pos: Vec, rot_angles: Vec):
    """Check if a placement shape can fit here."""
    for pos, occu_type in shape:
        block_pos = (Vec(pos).rotate(*rot_angles) + marker_pos).as_tuple()
        if POS[block_pos] not in occu_type:
            break
    else:
        return True
    return False
