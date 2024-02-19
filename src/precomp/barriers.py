"""Implements Glass and Grating."""
from __future__ import annotations

from typing import Callable, Dict, Final, Iterator, List, Mapping, Set, Tuple
from typing_extensions import Literal, Self, Sequence, TypeAlias, override

from collections import defaultdict
from enum import Enum, Flag, auto as enum_auto
import math

from srctools import EmptyMapping, Keyvalues
from srctools.math import AnyMatrix, to_matrix, FrozenMatrix, Vec, FrozenVec, Angle, Matrix
from srctools.vmf import VMF, Solid, Entity
import srctools.logger
import attrs

from plane import Plane
from precomp import instanceLocs, options, template_brush, conditions, collisions
from precomp.grid_optim import optimise as grid_optimise
from transtoken import TransToken
import consts
import user_errors
import utils


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME: str | None = None
STRAIGHT_LEN: Final = 64  # Length of the brush for straight frame sections.
HoleTemplate: TypeAlias = Tuple[List[Solid], List[collisions.BBox]]
TRANS_VARIABLE = TransToken.untranslated('"<var>{value}</var>"')


class FrameOrient(Enum):
    """The kind of frame orientation."""
    HORIZ = "horizontal"
    VERT = "vertical"


class Border(Flag):
    """Indicates which sides still need frames generated."""
    NONE = 0
    # We need a straight section on this side.
    STRAIGHT_N = enum_auto()
    STRAIGHT_S = enum_auto()
    STRAIGHT_E = enum_auto()
    STRAIGHT_W = enum_auto()
    # A convex corner is present, so the straight sections need to be shorter.
    CORNER_NW = enum_auto()
    CORNER_NE = enum_auto()
    CORNER_SW = enum_auto()
    CORNER_SE = enum_auto()

# IDs for the default barrier definitions. These are detected by the generated brushes, not
# from the instance (since that's the same for both).
GLASS_ID: Final = utils.parse_obj_id('VALVE_GLASS')
GRATE_ID: Final = utils.parse_obj_id('VALVE_GRATING')

ORIENT_E: Final = FrozenMatrix.from_yaw(0)
ORIENT_N: Final = FrozenMatrix.from_yaw(90)
ORIENT_W: Final = FrozenMatrix.from_yaw(180)
ORIENT_S: Final = FrozenMatrix.from_yaw(270)

ORIENTS = {
    Vec.T: FrozenMatrix.from_angle(180, 0, 0),
    Vec.B: FrozenMatrix.from_angle(0, 0, 0),
    Vec.N: FrozenMatrix.from_angle(90, 270, 0),
    Vec.S: FrozenMatrix.from_angle(90, 90, 0),
    Vec.E: FrozenMatrix.from_angle(90, 180, 0),
    Vec.W: FrozenMatrix.from_angle(90, 0, 0),
}

# Direction -> border value for that side.
NORMAL_TO_BORDER: Dict[Tuple[Literal[-1, 0, +1], Literal[-1, 0, +1]], Border] = {
    (0, +1): Border.STRAIGHT_N,
    (0, -1): Border.STRAIGHT_S,
    (+1, 0): Border.STRAIGHT_W,
    (-1, 0): Border.STRAIGHT_E,
}


FULL_SQUARE: Final[Sequence[Tuple[int, int]]] = [
    (u, v)
    for u in [-48, -16, +16, +48]
    for v in [-48, -16, +16, +48]
]
LARGE_DISALLOWED: Sequence[FrozenVec] = [
    FrozenVec(-128, 0, 0),
    FrozenVec(+128, 0, 0),
    FrozenVec(0, -128, 0),
    FrozenVec(0, +128, 0),
]


@attrs.frozen(eq=False, kw_only=True)
class HoleConfig:
    """Configuration for how to create a hole for a specific barrier."""
    id: utils.ObjectID
    radius: float  # Used for P1 floor beams.
    # Geo used to create the brush face.
    template: HoleTemplate
    instance: str

    @classmethod
    def parse(cls, kv: Keyvalues) -> HoleConfig:
        """Parse a configuration from a KV block."""
        conf_id = utils.parse_obj_id(kv.real_name)
        radius = kv.float('diameter') / 2
        instance = kv['instance', '']

        template = template_solids_and_coll(kv['template'])
        if 'templateDiagonal' in kv:
            return LargeHoleConfig(
                id=conf_id,
                instance=instance,
                radius=radius,
                template=template,

                template_diagonal=template_solids_and_coll(kv['templatediagonal']),
                template_square=template_solids_and_coll(kv['templatesquare']),
            )
        else:
            return HoleConfig(
                id=conf_id,
                instance=instance,
                radius=radius,
                template=template,
            )


@attrs.frozen(eq=False, kw_only=True, repr=False)
class LargeHoleConfig(HoleConfig):
    """Large holes are currently rather hardcoded."""
    template_diagonal: HoleTemplate  # Two holes diagonally overlapping.
    # If the corner is present, place it as part of the hole to simplify brushwork.
    template_square: HoleTemplate


@attrs.frozen(eq=False, repr=False)
class HoleType:
    """A type of hole."""
    id: utils.ObjectID
    footprint: Sequence[FrozenVec]  # Offsets occupied by the hole.
    variants: Mapping[utils.ObjectID, HoleConfig]
    is_large: bool

    @classmethod
    def parse(cls, kv: Keyvalues) -> HoleType:
        """Parse hole types from keyvalues data."""
        hole_id = utils.parse_obj_id(kv.real_name)

        # Use a template to make it easy to specify these.
        temp_id, visgroups = template_brush.parse_temp_name(kv['footprint'])
        footprint = [
            tilesetter.offset.freeze()
            for tilesetter in template_brush.get_template(temp_id).tile_setters
            if tilesetter.visgroups.issubset(visgroups)
        ]

        variants = {}
        for var_block in kv.find_children('Variants'):
            hole_conf = HoleConfig.parse(var_block)
            variants[hole_conf.id] = hole_conf
        variant_types = {type(conf) for conf in variants.values()}
        if len(variant_types) > 1:
            raise ValueError(
                f'Hole "{hole_id}" has both small and large variants, this must be consistent!'
            )

        return cls(hole_id, footprint, variants, LargeHoleConfig in variant_types)

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.id!r}, variants={sorted(self.variants)}>'


@attrs.define(eq=False, kw_only=True)
class Hole:
    """A hole item placed in the map."""
    inst: Entity
    type: HoleType
    variant: HoleConfig
    plane: utils.SliceKey
    orient: FrozenMatrix
    origin: Vec
    # If true, we found a matching barrier this was inserted into.
    inserted: bool = False
    # The U/V position in the plane.
    plane_pos: tuple[float, float] = attrs.field(init=False)

    def __attrs_post_init__(self) -> None:
        pos = self.plane.world_to_plane(self.origin)
        self.plane_pos = pos.x, pos.y


@attrs.frozen(eq=False, kw_only=True)
class BarrierType:
    """Type of barrier."""
    id: utils.ObjectID | utils.SpecialID
    frames: Mapping[FrameOrient, Sequence[FrameType]] = attrs.field(default=dict.fromkeys(FrameOrient, ()), repr=False)
    error_disp: user_errors.Kind | None = None
    brushes: Sequence[Brush] = ()
    contents: collisions.CollideType = collisions.CollideType.SOLID
    floorbeam_temp: template_brush.Template | None = None
    coll_thick: float = 4.0
    hint_thick: float = 0.0
    # If set, the brushes for this item can be combined with others of the same type.
    mergeable: bool = False
    # Hole variants valid for this kind of barrier.
    hole_variants: Sequence[utils.ObjectID] = ()

    @classmethod
    def parse(cls, kv: Keyvalues) -> BarrierType:
        """Parse from keyvalues files."""
        frames: Dict[FrameOrient, List[FrameType]] = {orient: [] for orient in FrameOrient}
        error_disp: user_errors.Kind | None = None
        brushes: List[Brush] = []

        for sub_kv in kv.find_all('Frame'):
            frame_id = utils.parse_obj_id(sub_kv.value)
            try:
                frame_map = FRAME_TYPES[frame_id]
            except KeyError:
                LOGGER.warning('No barrier frame named "{}"!', frame_id)
            else:
                for orient, frame in frame_map.items():
                    frames[orient].append(frame)

        for sub_kv in kv.find_all('Brush'):
            brushes.append(Brush.parse(sub_kv))

        hole_variants = [
            utils.parse_obj_id(sub_kv.value)
            for sub_kv in kv.find_all('HoleVariant')
        ]

        if 'error_tex' in kv:
            error_tex = kv['error_tex'].casefold()
            if error_tex in user_errors.TEX_SET:
                error_disp = error_tex  # type: ignore

        if floorbeam_temp_id := kv['template_floorbeam', '']:
            floorbeam_temp = template_brush.get_template(floorbeam_temp_id)
        else:
            floorbeam_temp = None

        contents = collisions.CollideType.parse(kv['contents', 'solid'])

        return BarrierType(
            id=utils.parse_obj_id(kv.real_name),
            frames=frames,
            error_disp=error_disp,
            brushes=brushes,
            contents=contents,
            floorbeam_temp=floorbeam_temp,
            hole_variants=hole_variants,
            hint_thick=kv.float('hint_thick'),
            coll_thick=kv.float('coll_thick', 4.0),
            mergeable=kv.bool('mergeable'),
        )


@attrs.define(eq=False)
class Barrier:
    """A glass/grating item.

    BARRIER_EMPTY is unique, but others may not be if created dynamically!
    """
    name: str
    type: BarrierType
    instances: List[Entity] = attrs.Factory(list)

    def __eq__(self, other: object) -> bool:
        """Two barriers are equal if are for the same instance or if mergable. The type must always match."""
        if isinstance(other, Barrier):
            if self.type is not other.type:
                return False
            return self.type.mergeable or self.name == other.name
        return NotImplemented


@attrs.frozen(eq=False, kw_only=True)
class Brush:
    """Configuration for a brush generated for a barrier."""
    offset: float
    thickness: float

    face_temp: template_brush.ScalingTemplate
    material: str = ''  # If set, override face_temp.
    # Texture the whole thing with the face.
    is_tool: bool = False
    # If vertical, use the original player clip and func-detail. Otherwise, add it inside this one.
    static_player_clip: bool = False

    keyvalues: Mapping[str, str] = EmptyMapping

    @classmethod
    def parse(cls, kv: Keyvalues) -> Brush:
        """Parse from keyvalues files."""
        material = kv['material', '']
        if face_temp_id := kv['template', '']:
            face_temp = template_brush.get_scaling_template(face_temp_id)
        else:
            face_temp = template_brush.ScalingTemplate.world(material or 'tools/toolsskip')

        thickness = kv.float('thickness', 4.0)
        if thickness <= 0:
            raise ValueError('Brushes must have thickness!')

        ent_kvs = {}
        for child in kv.find_children('keys'):
            ent_kvs[child.name] = child.value

        return cls(
            offset=kv.float('offset'),
            thickness=thickness,
            face_temp=face_temp,
            material=material,
            is_tool=kv.bool('tooltexture'),
            static_player_clip=kv.bool('staticplayerclip'),
            keyvalues=ent_kvs,
        )

    def generate(
        self, vmf: VMF,
        plane_slice: utils.SliceKey,
        solid_func: Callable[[float, float], List[Solid]],
    ) -> None:
        """Generate this brush."""
        ent = vmf.create_ent('func_detail')
        ent.solids = solid_func(self.offset, self.offset + self.thickness)
        ent.update(self.keyvalues)
        if ent['classname'] != 'func_detail':
            ent['origin'] = ent.get_origin()

        for face in ent.sides():
            if abs(face.normal().dot(plane_slice.normal)) > 0.99:
                face.mat = self.material
                self.face_temp.apply(face, change_mat=not self.material)
            elif self.is_tool:
                face.mat = self.material or consts.Tools.NODRAW
            else:
                face.mat = consts.Tools.NODRAW

        if self.static_player_clip:
            if abs(plane_slice.normal.z) > 0.5:
                ent['classname'] = 'func_brush'
                ent['solidbsp'] = '1'
                # Create an additional clip to block through portals.
                clip_ent = vmf.create_ent('func_detail')
                # Shrink by a unit, but if this is already smaller, then just halve.
                shrink = min(self.thickness / 2.0, 1.0) / 2.0
                clip_ent.solids = solid_func(self.offset + shrink, self.offset + self.thickness - shrink)
                for face in clip_ent.sides():
                    face.mat = consts.Tools.PLAYER_CLIP
            else:
                # Vertical, just make it a detail brush.
                ent['classname'] = 'func_detail'
                for face in ent.sides():
                    face.mat = consts.Tools.PLAYER_CLIP


@attrs.frozen(eq=False, kw_only=True)
class Segment:
    """Either a model or brush template, placed with an optional offset."""
    orient: FrozenMatrix = FrozenMatrix()
    offset: FrozenVec = FrozenVec()

    @classmethod
    def parse(cls, kv: Keyvalues) -> SegmentBrush | SegmentProp:
        """Parse from keyvalues configuration."""
        orient = FrozenMatrix.from_angstr(kv['angles', '0 0 0'])
        offset = FrozenVec.from_str(kv['offset', '0 0 0'])

        if 'model' in kv:
            return SegmentProp(
                model=kv['model'],
                orient=orient,
                offset=offset,
            )
        else:
            return SegmentBrush(
                brush=template_brush.get_template(kv['template']),
                orient=orient,
                offset=offset,
            )

    def place(
        self, vmf: VMF, slice_key: utils.SliceKey, lighting_origin: str,
        u: float, v: float, angles: AnyMatrix,
    ) -> None:
        """Place the segment at the specified location."""
        rotation = to_matrix(angles) @ slice_key.orient
        origin = slice_key.plane_to_world(u, v) + self.offset @ rotation
        self._place(
            vmf, origin, self.orient @ rotation, lighting_origin,
        )

    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix, lighting_origin: str) -> None:
        """Place the segment at the specified location."""
        raise NotImplementedError


@attrs.frozen(eq=False, kw_only=True)
class SegmentProp(Segment):
    """A model, placed with an optional offset."""
    model: str

    @override
    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix, lighting_origin: str) -> None:
        """Place the segment at the specified location."""
        vmf.create_ent(
            'prop_static',
            origin=origin,
            angles=angles,
            model=self.model,
            skin=0,
            solid=6,
            lightingorigin=lighting_origin,
        )


@attrs.frozen(eq=False, kw_only=True)
class SegmentBrush(Segment):
    """A template brush, placed with an optional offset."""
    brush: template_brush.Template

    @override
    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix, lighting_origin: str) -> None:
        """Place the segment at the specified location."""
        temp = template_brush.import_template(
            vmf,
            self.brush,
            origin, angles,
            force_type=template_brush.TEMP_TYPES.detail,
        )

    def place_sized(
        self,
        vmf: VMF, slice_key: utils.SliceKey,
        u: float, v: float,
        orient: FrozenMatrix,
        direction: Vec,
        length: float,
    ) -> None:
        """Place this template, but resize it to match the specified length."""
        rotation = orient @ slice_key.orient
        origin = slice_key.plane_to_world(u, v) + self.offset @ rotation
        temp = template_brush.import_template(
            vmf,
            self.brush,
            origin,
            self.orient @ rotation,
            force_type=template_brush.TEMP_TYPES.detail,
        )
        if temp.detail is None:
            return  # No brushes?
        diff = direction * (length - STRAIGHT_LEN)
        for face in temp.detail.sides():
            if face.normal().dot(direction) < -0.99:
                face.translate(diff)


@attrs.frozen(eq=False, kw_only=True)
class FrameType:
    """Configuration for a type of barrier frame."""
    # Brushes can be resized, props need to be pieced together.
    seg_straight_brush: Sequence[SegmentBrush] = ()
    seg_straight_prop: Mapping[int, Sequence[SegmentProp]] = EmptyMapping
    seg_straight_fitter: Callable[[int], Sequence[int]] = lambda x: ()

    seg_corner: Sequence[Segment] = ()
    seg_concave_corner: Sequence[Segment] = ()
    corner_size_horiz: int = 4
    corner_size_vert: int = 4

    @classmethod
    def parse(cls, kv: Keyvalues) -> Self:
        """Parse from keyvalues configuration."""
        seg_straight_brush = []
        seg_straight_prop: Dict[int, List[SegmentProp]] = defaultdict(list)
        seg_corner = []
        seg_concave_corner = []

        for block in kv.find_all('straight'):
            segment = Segment.parse(block)
            if isinstance(segment, SegmentProp):
                size = block.int('length')
                if size <= 0:
                    raise ValueError('Straight prop sections must have a size defined!')
                seg_straight_prop[size].append(segment)
            else:
                seg_straight_brush.append(segment)

        corner_size_horiz = kv.int('cornerSize', 4)
        corner_size_vert = kv.int('cornerVertSize', corner_size_horiz)

        for block in kv.find_all('corner'):
            seg_corner.append(Segment.parse(block))
        for block in kv.find_all('concavecorner'):
            seg_concave_corner.append(Segment.parse(block))

        return cls(
            seg_straight_brush=seg_straight_brush,
            seg_straight_prop=dict(seg_straight_prop),
            seg_straight_fitter=utils.get_piece_fitter(list(seg_straight_prop)),
            seg_corner=seg_corner,
            seg_concave_corner=seg_concave_corner,
            corner_size_horiz=corner_size_horiz,
            corner_size_vert=corner_size_vert,
        )


# Special barrier representing the lack of one.
BARRIER_EMPTY_TYPE = BarrierType(id=utils.ID_EMPTY, mergeable=True)
BARRIER_EMPTY = Barrier('', BARRIER_EMPTY_TYPE)
# Planar slice -> plane of barriers.
# The plane is specified as the edge of the voxel.
BARRIERS: dict[utils.SliceKey, Plane[Barrier]] = defaultdict(lambda: Plane(default=BARRIER_EMPTY))
BARRIERS_BY_NAME: dict[str, Barrier] = {}
# plane -> {position -> hole}
HOLES: dict[utils.SliceKey, dict[FrozenVec, Hole]] = defaultdict(dict)

HOLE_TYPES: Dict[utils.ObjectID, HoleType] = {}
FRAME_TYPES: Dict[utils.ObjectID, Dict[FrameOrient, FrameType]] = {}
BARRIER_TYPES: Dict[utils.ObjectID | utils.SpecialID, BarrierType] = {}


def parse_conf(kv: Keyvalues) -> None:
    """Parse frame configurations."""
    FRAME_TYPES.clear()
    for block in kv.find_children('BarrierFrames'):
        frame_id = utils.parse_obj_id(block.real_name)
        if 'horiz' in block and 'vert' in block:
            horiz_conf = FrameType.parse(block.find_key('horiz'))
            vert_conf = FrameType.parse(block.find_key('vert'))
        else:
            horiz_conf = vert_conf = FrameType.parse(block)
        FRAME_TYPES[frame_id] = {
            FrameOrient.HORIZ: horiz_conf,
            FrameOrient.VERT: vert_conf,
        }
    for block in kv.find_children('Barriers'):
        barrier = BarrierType.parse(block)
        BARRIER_TYPES[barrier.id] = barrier

    for block in kv.find_children('BarrierHoles'):
        hole = HoleType.parse(block)
        HOLE_TYPES[hole.id] = hole

    # Make sure a basic map sorta works even without the new configuration.
    if GLASS_ID not in BARRIER_TYPES:
        LOGGER.warning('No definition for {}!', GLASS_ID)
        BARRIER_TYPES[GLASS_ID] = BarrierType(
            id=GLASS_ID,
            contents=collisions.CollideType.GLASS,
            error_disp='glass',
            brushes=[
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Special.GLASS),
                    offset=0.5,
                    thickness=1.0,
                    keyvalues={'classname': 'func_detail'},
                ),
            ],
        )

    if GRATE_ID not in BARRIER_TYPES:
        LOGGER.warning('No definition for {}!', GRATE_ID)
        BARRIER_TYPES[GRATE_ID] = BarrierType(
            id=GRATE_ID,
            contents=collisions.CollideType.GRATING,
            error_disp='grating',
            brushes=[
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Special.GRATING),
                    offset=0.5,
                    thickness=1.0,
                    keyvalues={
                        'classname': 'func_brush',
                        'renderfx': '14', # Constant Glow
                        'solidity': '1',  # Never Solid
                    },
                ),
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Tools.PLAYER_CLIP),
                    offset=0,
                    thickness=4.0,
                    is_tool=True,
                    keyvalues={'classname': 'func_detail'},
                ),
                Brush(
                    face_temp=template_brush.ScalingTemplate.world(consts.Tools.TRIGGER),
                    offset=0,
                    thickness=4.0,
                    is_tool=True,
                    keyvalues={
                        'classname': 'func_clip_vphysics',
                        'filtername': '@grating_filter',
                    },
                ),
            ],
        )


def parse_map(vmf: VMF) -> None:
    """Find all glass/grating in the map.

    This removes the per-tile instances, and all original brushwork.
    The frames are updated with a fixup var, as appropriate.
    """
    frame_inst = instanceLocs.resolve_filter('[glass_frames]', silent=True)
    segment_inst = instanceLocs.resolve_filter('[glass_128]', silent=True)

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        if not filename:
            continue
        if filename in segment_inst:
            # The vanilla segment instance is the same for glass/grating, so we don't know which
            # is which. Fill in a barrier, but don't give it a type yet.
            # Look up the barriers
            center = Vec.from_str(inst['origin']) // 128 * 128 + (64, 64, 64)
            norm = Vec(x=1) @ Angle.from_str(inst['angles'])
            center -= 64 * norm
            plane_slice = utils.SliceKey(norm, center)
            local = plane_slice.world_to_plane(center)

            inst_name = inst['targetname']

            try:
                barrier = BARRIERS_BY_NAME[inst_name]
            except KeyError:
                barrier = BARRIERS_BY_NAME[inst_name] = Barrier(inst_name, BARRIER_EMPTY_TYPE)
            barrier.instances.append(inst)

            # Now set each 32-grid cell to be the barrier. Since this is square the orientation
            # doesn't matter.
            for u_off, v_off in FULL_SQUARE:
                BARRIERS[plane_slice][
                    (local.x + u_off) // 32,
                    (local.y + v_off) // 32,
                ] = barrier

        if filename in frame_inst:  # Frames are useless, we'll make our own.
            inst.remove()

    for entities, material, barrier_type, fixup_value in [
        (vmf.by_class['func_detail'], consts.Special.GLASS, BARRIER_TYPES[GLASS_ID], 'glass'),
        (vmf.by_class['func_brush'], consts.Special.GRATING, BARRIER_TYPES[GRATE_ID], 'grating'),
    ]:
        for brush_ent in entities:
            for face in brush_ent.sides():
                if face.mat != material:
                    continue  # Side face.
                # We found the face for a barrier brush. This could be either facing
                # into or out of the voxel - compute the grid center to disambiguate.
                brush_ent.remove()
                origin = face.get_origin()
                center = origin // 128 * 128 + (64, 64, 64)
                norm = (origin - center).norm()

                # Offset to be the voxel side, not center.
                center += 64 * norm
                plane_slice = utils.SliceKey(-norm, center)
                local = plane_slice.world_to_plane(center)

                # Figure out the instance this matches from above.
                # At this point all barrier definitions are whole voxel, so it doesn't matter which we pick.
                try:
                    barrier = BARRIERS[plane_slice][local.x // 32, local.y // 32]
                except KeyError:
                    LOGGER.warning('glass/grating at {}, {} has no corresponding instance?', center, norm)
                    break  # Don't check remaining faces.

                if barrier.type is BARRIER_EMPTY_TYPE:
                    # Not yet filled in, now we can set it. Also set a fixup so conditions can
                    # identify the barrier.
                    barrier.type = barrier_type
                    for inst in barrier.instances:
                        inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = fixup_value
                elif barrier_type is not barrier_type:
                    LOGGER.warning(
                        'Barrier at {}, {} is both glass and grating simultaneously?',
                        center, norm, plane_slice,
                    )

                break  # Don't check the remaining faces.

    # Now, go back over the items to check they all have been matched up.
    for barrier in list(BARRIERS_BY_NAME.values()):
        if barrier.type is BARRIER_EMPTY_TYPE:
            LOGGER.warning('Barrier "{}" has no associated brushes??', barrier.name)
            # Discard.
            del BARRIERS_BY_NAME[barrier.name]
            for inst in barrier.instances:
                inst.remove()

    # Discard original lighting origins.
    for ent in vmf.by_class['info_lighting']:
        ent.remove()


def test_hole_spot(
    origin: FrozenVec,
    plane: utils.SliceKey,
    orient: FrozenMatrix,
    hole_type: HoleType,
) -> HoleConfig | None:
    """Check if the given position is valid for holes.

    We need to check that it's actually placed on glass/grating, and that
    all the parts are the same. Otherwise, it'd collide with the borders.

    This returns the variant located, or None if no barrier was found at all. In that case we want
    to try the opposite orientation.
    """
    center = plane.world_to_plane(origin)
    barrier_plane = BARRIERS[plane]

    barrier = barrier_plane[center.x // 32, center.y // 32]
    if barrier is BARRIER_EMPTY:
        # Try the other orientation.
        return None

    error_hole = user_errors.BarrierHole(
        pos=user_errors.to_threespace(origin + orient.up(64)),
        axis=orient.up().axis(),
        # TODO: Handle hole rendering better, user-specifiable?
        large=hole_type.is_large,
        small=not hole_type.is_large,
        footprint=True,
    )

    for variant_ids in barrier.type.hole_variants:
        try:
            variant = hole_type.variants[variant_ids]
            break
        except KeyError:
            pass
    else:
        if len(barrier.type.hole_variants) == 0:
            # Entirely disallowed for this barrier type.
            message = user_errors.TOK_BARRIER_HOLE_DISALLOWED.format(
                barrier=barrier.type.id,
                hole=hole_type.id,
            )
        else:
            message = user_errors.TOK_BARRIER_HOLE_NOVARIANT.format(
                barrier=barrier.type.id,
                hole=hole_type.id,
                types_barrier=TransToken.list_and([
                    TRANS_VARIABLE.format(value=variant)
                    for variant in barrier.type.hole_variants
                ]),
                types_hole=TransToken.list_or([
                    TRANS_VARIABLE.format(value=variant)
                    for variant in hole_type.variants.keys()
                ], sort=True),
            )
        raise user_errors.UserError(message, barrier_hole=error_hole)

    for offset in hole_type.footprint:
        pos = offset @ orient + origin
        local = plane.world_to_plane(pos)
        off_type = barrier_plane[local.x // 32, local.y // 32]
        if off_type != barrier:
            # Different type.
            LOGGER.warning(
                'Wrong barrier type at {}, {}: {} (expected {})',
                pos, plane, off_type, barrier,
            )
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_FOOTPRINT.format(hole=hole_type.id),
                barrier_hole=error_hole,
            )

    # In each direction, make sure a large hole isn't present.
    if isinstance(variant, LargeHoleConfig):
        for offset in LARGE_DISALLOWED:
            side_pos = plane.plane_to_world(*offset).freeze()
            try:
                other_hole = HOLES[plane][side_pos]
            except KeyError:
                pass
            else:
                if isinstance(other_hole.variant, LargeHoleConfig):
                    # TODO: Draw the other hole as well?
                    raise user_errors.UserError(
                        user_errors.TOK_BARRIER_HOLE_FOOTPRINT.format(hole=hole_type.id),
                        barrier_hole=error_hole,
                    )
    return variant


@conditions.make_result('GlassHole')
def res_glass_hole(inst: Entity, res: Keyvalues) -> None:
    """Add Glass/grating holes. The value should be 'large' or 'small'."""
    hole_type = HOLE_TYPES[utils.parse_obj_id(res.value)]

    orient = FrozenMatrix.from_angstr(inst['angles'])
    origin: FrozenVec = FrozenVec.from_str(inst['origin']) // 128 * 128 + 64
    origin += orient.up(-64.0)
    slice_key = utils.SliceKey(orient.up(-1.0), origin)

    first_variant = test_hole_spot(origin, slice_key, orient, hole_type)
    if first_variant is not None:
        sel_plane = slice_key
        sel_orient = orient
        sel_variant = first_variant
    else:
        # Test the opposite side of the glass too.
        alt_orient = FrozenMatrix.from_roll(180) @ orient
        slice_key = utils.SliceKey(alt_orient.up(-1.0), origin)

        sec_variant = test_hole_spot(origin, slice_key, alt_orient, hole_type)
        if sec_variant is not None:
            sel_orient = alt_orient
            sel_plane = slice_key
            sel_variant = sec_variant
            inst['angles'] = sel_orient.to_angle()
        else:
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_MISPLACED.format(hole=hole_type.id),
                barrier_hole=user_errors.BarrierHole(
                    pos=user_errors.to_threespace(origin + orient.up(64)),
                    axis=orient.up().axis(),
                    # TODO: Handle hole rendering better, user-specifiable?
                    large=hole_type.is_large,
                    small=not hole_type.is_large,
                    footprint=True,
                )
            )
    # Place it, or error if there's already one here.
    try:
        existing = HOLES[sel_plane][origin]
    except KeyError:
        pass
    else:
        raise user_errors.UserError(
            user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
            points=[origin],
            barrier_hole=user_errors.BarrierHole(
                pos=user_errors.to_threespace(origin),
                axis=sel_plane.normal.axis(),
                large=isinstance(sel_variant, LargeHoleConfig) or isinstance(existing.variant, LargeHoleConfig),
                small=not isinstance(hole_type, LargeHoleConfig) or not isinstance(existing.variant, LargeHoleConfig),
                footprint=False,
            ),
        )
    HOLES[sel_plane][origin] = Hole(
        inst=inst,
        type=hole_type,
        variant=sel_variant,
        plane=sel_plane,
        orient=sel_orient,
        origin=origin.thaw(),
    )
    inst['origin'] = origin
    inst.fixup['$variant'] = sel_variant.id
    if sel_variant.instance:
        inst['file'] = sel_variant.instance


def template_solids_and_coll(template_id: str) -> HoleTemplate:
    """Retrieve the brushes and collision boxes for the specified visgroup."""
    temp_id, visgroups = template_brush.parse_temp_name(template_id)
    visgroups.add('')
    template = template_brush.get_template(temp_id)
    return template.visgrouped_solids(visgroups), [
        coll.bbox for coll in template.collisions
        if coll.visgroups.issubset(visgroups)
    ]

@conditions.meta_cond(150)
def make_barriers(vmf: VMF, coll: collisions.Collisions) -> None:
    """Make barrier entities."""
    LOGGER.info('Generating barriers (glass/grating)...')

    if options.get_itemconf('BEE_PELLET:PelletGrating', False):
        # Merge together these existing filters in global_pti_ents
        vmf.create_ent(
            origin=options.GLOBAL_PTI_ENTS_LOC(),
            targetname='@grating_filter',
            classname='filter_multi',
            filtertype=0,
            negated=0,
            filter01='@not_pellet',
            filter02='@not_paint_bomb',
        )
    else:
        # Just skip paint bombs.
        vmf.create_ent(
            origin=options.GLOBAL_PTI_ENTS_LOC(),
            targetname='@grating_filter',
            classname='filter_activator_class',
            negated=1,
            filterclass='prop_paint_bomb',
        )

    debug_skin: dict[utils.ObjectID | utils.SpecialID, int] = {
        GLASS_ID: 5,
        GRATE_ID: 0,
    }
    add_debug = conditions.fetch_debug_visgroup(vmf, 'Barriers')
    group_id = 0
    for plane_slice, plane in BARRIERS.items():
        frame_orient = FrameOrient.HORIZ if abs(plane_slice.normal.z) < 0.5 else FrameOrient.VERT
        hole_plane = HOLES[plane_slice]
        for barrier, group_plane in find_plane_groups(plane):
            group_id += 1

            borders = calc_borders(group_plane)

            if barrier.type.hint_thick > 0:
                # Do this before holes, so we cover those with the hint.
                add_hints(vmf, plane_slice, group_plane, barrier.type.hint_thick)

            for hole in hole_plane.values():
                if not hole.inserted:
                    try_place_hole(vmf, group_plane, barrier, hole)

            for (u, v) in group_plane:
                add_debug(
                    'bee2_template_tilesetter',
                    origin=plane_slice.plane_to_world(32 * u + 16, 32 * v + 16, 2),
                    angles=plane_slice.orient,
                    skin=debug_skin.get(barrier.type.id, 1),
                    targetname=f'barrier_{group_id}',
                    comment=f'Border: {borders[u, v]}, u={u}, v={v}',
                )

            lighting_origin = place_lighting_origin(vmf, barrier, plane_slice, group_plane)

            for (u, v) in group_plane:
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders, frame_orient,
                    u, v, ORIENT_W, +1, +1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders, frame_orient,
                    u, v, ORIENT_S, -1, +1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders, frame_orient,
                    u, v, ORIENT_E, -1, -1,
                )
                place_concave_corner(
                    vmf, barrier, lighting_origin, plane_slice, borders, frame_orient,
                    u, v, ORIENT_N, +1, -1,
                )

            for (u, v), border in borders.items():
                if Border.STRAIGHT_N in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_N, ORIENT_E, 'x', False,
                        Border.CORNER_NE, Border.CORNER_NW,
                        0, 32,
                    )
                if Border.STRAIGHT_S in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_S, ORIENT_W, 'x', True,
                        Border.CORNER_SE, Border.CORNER_SW,
                        0, 0,
                    )
                if Border.STRAIGHT_E in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_E, ORIENT_N, 'y', False,
                        Border.CORNER_SE, Border.CORNER_NE,
                        0, 0,
                    )
                if Border.STRAIGHT_W in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, lighting_origin, u, v,
                        Border.STRAIGHT_W, ORIENT_S, 'y', True,
                        Border.CORNER_SW, Border.CORNER_NW,
                        32, 0,
                    )

                if Border.CORNER_NW in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_W, u + 1, v + 1,
                    )
                if Border.CORNER_NE in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_S, u, v + 1,
                    )
                if Border.CORNER_SE in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_E, u, v,
                    )
                if Border.CORNER_SW in border:
                    place_convex_corner(
                        vmf, barrier, plane_slice, lighting_origin,
                        ORIENT_N, u + 1, v,
                    )

            for min_u, min_v, max_u, max_v, sub_barrier in grid_optimise(group_plane):
                if sub_barrier is BARRIER_EMPTY:
                    continue
                place_planar_brushes(vmf, barrier, plane_slice, min_u, min_v, max_u, max_v)

    for hole_plane in HOLES.values():
        for hole in hole_plane.values():
            if not hole.inserted:
                raise user_errors.UserError(
                    user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
                    barrier_hole={
                        'pos': user_errors.to_threespace(hole.origin),
                        'axis': hole.plane.normal.axis(),
                        'large': hole.type.is_large,
                        'small': not hole.type.is_large,
                        'footprint': True,
                    }
                )


def find_plane_groups(plane: Plane[Barrier]) -> Iterator[Tuple[Barrier, Plane[Barrier]]]:
    """Yield sub-graphs of a barrier plane, containing contiguous barriers."""
    stack: Set[Tuple[int, int]] = set()
    completed: Plane[bool] = Plane.fromkeys(plane, False)
    for start, cmp_value in plane.items():
        if completed[start] or cmp_value is BARRIER_EMPTY:
            continue
        group: Plane[Barrier] = Plane()
        stack.add(start)
        mergeable = cmp_value.type.mergeable
        while stack:
            x, y = pos = stack.pop()
            if completed[pos]:
                continue
            value = plane[pos]
            if value == cmp_value or (mergeable and value.type is cmp_value.type):
                completed[pos] = True
                group[pos] = value
                stack |= {
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                }
        yield cmp_value, group


def calc_borders(plane: Plane[Barrier]) -> Plane[Border]:
    """Calculate which borders are required for each section of this plane."""
    borders = Plane(default=Border.NONE)
    for (x, y) in plane:
        border = Border.NONE
        if north := (x, y + 1) not in plane:
            border |= Border.STRAIGHT_N
        if south := (x, y - 1) not in plane:
            border |= Border.STRAIGHT_S
        if east := (x - 1, y) not in plane:
            border |= Border.STRAIGHT_E
        if west := (x + 1, y) not in plane:
            border |= Border.STRAIGHT_W
        if north and east:
            border |= Border.CORNER_NE
        if north and west:
            border |= Border.CORNER_NW
        if south and east:
            border |= Border.CORNER_SE
        if south and west:
            border |= Border.CORNER_SW
        if border is not Border.NONE:
            borders[x, y] = border
    return borders


def add_hints(vmf: VMF, plane_slice: utils.SliceKey, plane: Plane[Barrier], thick: float) -> None:
    """Surround the barrier with hints, to assist with translucency sorting.

    This can't be done with Brush{} definitions because this should not be cut by holes.
    """
    for min_u, min_v, max_u, max_v, _ in grid_optimise(plane):
        hint = vmf.make_prism(
            plane_slice.plane_to_world(32.0 * min_u, 32.0 * min_v),
            plane_slice.plane_to_world(32.0 * max_u + 32.0, 32.0 * max_v + 32.0, thick),
            mat=consts.Tools.SKIP,
        )
        norm = plane_slice.normal.thaw()
        hint[norm].mat = consts.Tools.HINT
        hint[-norm].mat = consts.Tools.HINT
        vmf.add_brush(hint.solid)


def place_lighting_origin(
    vmf: VMF, barrier: Barrier,
    plane_slice: utils.SliceKey,
    group_plane: Plane[Barrier],
) -> str:
    """Create a lighting origin for a barrier's frame. This should be placed roughly in the centre."""
    # First, calculate the average UV position, then find the tile that's closest to that.
    # This way something like an L-shaped piece of glass doesn't put the origin in the void.
    count = avg_u = avg_v = 0
    for u, v in group_plane:
        avg_u += u
        avg_v += v
        count += 1

    avg_pos = (avg_u / count, avg_v / count)

    best_u, best_v = min(group_plane, key=lambda uv: math.dist(uv, avg_pos))
    name = conditions.local_name(barrier.instances[0], 'lighting')
    vmf.create_ent(
        'info_lighting',
        origin=plane_slice.plane_to_world(
            best_u * 32 + 16.0,
            best_v * 32 + 16.0,
            barrier.type.coll_thick / 2,
        ),
        targetname=name,
    )
    return name


def place_planar_brushes(
    vmf: VMF, barrier: Barrier, plane_slice: utils.SliceKey,
    min_u: int, min_v: int, max_u: int, max_v: int,
) -> None:
    """Place brushes to fill these tiles."""
    def solid_func(z1: float, z2: float) -> List[Solid]:
        """Generate prism brushes."""
        prism = vmf.make_prism(
            plane_slice.plane_to_world(32.0 * min_u, 32.0 * min_v, z1),
            plane_slice.plane_to_world(32.0 * max_u + 32.0, 32.0 * max_v + 32.0, z2),
        )
        return [prism.solid]

    for brush in barrier.type.brushes:
        brush.generate(vmf, plane_slice, solid_func)


def place_concave_corner(
    vmf: VMF,
    barrier: Barrier,
    lighting_origin: str,
    slice_key: utils.SliceKey,
    borders: Plane[Border],
    frame_orient: FrameOrient,
    u: int,
    v: int,
    orient: FrozenMatrix,
    off_u: Literal[-1, +1],
    off_v: Literal[-1, +1],
) -> None:
    """Check if a concave corner needs to be placed at this offset."""
    if (
        NORMAL_TO_BORDER[off_u, 0] not in borders[u, v + off_v] or
        NORMAL_TO_BORDER[0, off_v] not in borders[u + off_u, v]
    ):
        return  # No convex corner required.
    for frame in barrier.type.frames[frame_orient]:
        for seg in frame.seg_concave_corner:
            seg.place(
                vmf, slice_key,
                lighting_origin,
                32. * u + 16. * off_u + 16.0,
                32. * v + 16. * off_v + 16.0,
                orient,
            )


def try_place_hole(vmf: VMF, plane: Plane[Barrier], barrier: Barrier, hole: Hole) -> None:
    """Try and place a hole in the barrier."""
    # First check if the footprint is present. If not, we're some other piece of glass.
    for offset in hole.type.footprint:
        local = hole.plane.world_to_plane(hole.origin + offset @ hole.orient)
        if (local.x // 32, local.y // 32) not in plane:
            return

    # Found, we're generating this.
    hole.inserted = True

    hole_temp: list[tuple[list[Solid], list[collisions.BBox], Matrix | FrozenMatrix]] = []
    hole_plane = HOLES[hole.plane]

    # This is a tricky bit. Two large templates would collide
    # diagonally, and we allow the corner glass to not be present since
    # the hole doesn't actually use that 32x32 segment.
    # So we need to determine which of 3 templates to use.
    if isinstance(hole.variant, LargeHoleConfig):
        for yaw in (0, 90, 180, 270):
            corn_mat = Matrix.from_yaw(yaw) @ hole.plane.orient

            corn_dir = Vec(x=1, y=1) @ corn_mat
            hole_off = hole.origin + 128 * corn_dir
            diag_hole = hole_plane.get(hole_off.freeze())
            corner_pos = hole.plane.world_to_plane(hole.origin + 80 * corn_dir)
            corn_u = corner_pos.x // 32
            corn_v = corner_pos.y // 32

            if diag_hole is not None and isinstance(diag_hole.variant, LargeHoleConfig):
                # There's another large template to this direction.
                # Just have 1 generate both combined, so the brushes can
                # be more optimal. To pick, arbitrarily make the upper one
                # be in charge.
                if corn_v > (hole.plane_pos[1] // 32):
                    hole_temp.append(hole.variant.template_diagonal + (corn_mat, ))
                continue
            # This bit of the glass is present, so include it in our brush, then clear.
            if (corn_u, corn_v) in plane:
                hole_temp.append(hole.variant.template_square + (corn_mat, ))
                plane[corn_u, corn_v] = BARRIER_EMPTY
            else:
                hole_temp.append(hole.variant.template + (corn_mat, ))

    else:
        hole_temp.append(hole.variant.template + (hole.plane.orient, ))

    # for _, bbox_list, matrix in hole_temp:
    #     # Place the collisions.
    #     for bbox in bbox_list:
    #         bbox = bbox @ matrix + origin
    #         coll.add(bbox.with_attrs(name=str(barrier.id), contents=barrier.type.contents))

    for offset in hole.type.footprint:
        local = hole.plane.world_to_plane(hole.origin + offset @ hole.orient)
        # This is in the plane still, but marked as blank. That way diagonally overlapping holes
        # still work.
        plane[local.x // 32, local.y // 32] = BARRIER_EMPTY

    hole_origin_cell = hole.origin

    def hole_brush_func(off1: float, off2: float) -> list[Solid]:
        """Given the two thicknesses, produce the curved hole from the template."""
        off_min = min(off1, off2)
        off_max = max(off1, off2)
        new_brushes = []
        for brushes, _, matrix in hole_temp:
            for orig_brush in brushes:
                brush = orig_brush.copy(vmf_file=vmf)
                new_brushes.append(brush)
                for face in brush.sides:
                    for point in face.planes:
                        if point.z > 0:
                            point.z = off_max
                        else:
                            point.z = off_min
                    face.localise(hole_origin_cell, matrix)
                    # Increase precision, these are small detail brushes.
                    face.lightmap = 8
        return new_brushes

    for brush in barrier.type.brushes:
        brush.generate(vmf, hole.plane, hole_brush_func)



def place_straight_run(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    borders: Plane[Border],
    lighting_origin: str,
    start_u: int,
    start_v: int,
    straight: Border,
    orient: FrozenMatrix,
    axis: Literal['x', 'y'],
    backwards: bool,
    corner_start: Border,
    corner_end: Border,
    pos_u: Literal[0, 32],
    pos_v: Literal[0, 32],
) -> None:
    """Place a straight edge side, going as far as possible.

    Parameters:
        * vmf: The map.
        * barrier: The barrier to generate frames for.
        * slice_key: Orientation of the plane.
        * borders: Computed border shapes that are yet to be placed.
        * lighting_origin: Name of the info_lighting entity to use.
        * start_u: Starting cell with this straight type.
        * start_v: ^^^^
        * straight: The kind of border we're placing.
        * orient: Rotation to apply to the straight pieces so that they fit.
        * axis: The direction to move to continue this straight piece into another cell.
        * backwards: If set, offset each piece to the end of its section instead of the start.
        * corner_start: The corner which this could connect to on the start cell.
          If present, offset forwards.
        * corner_end: The corner which this could connect to on the end cell.
          If present, offset backwards.
        * pos_u: Offset the placed straight sections by this many units at the end.
        * pos_v: ^^^^
    """
    end_u, end_v = start_u, start_v
    total_dist = 32
    if axis == 'x':
        off_u, off_v = 1, 0
    else:
        off_u, off_v = 0, 1
    direction = Vec(off_u, off_v) @ slice_key.orient
    if backwards:
        direction = -direction
    frame_orient = FrameOrient.HORIZ if abs(direction.z) < 0.5 else FrameOrient.VERT

    while straight in borders[end_u + off_u, end_v + off_v]:
        total_dist += 32
        end_u += off_u
        end_v += off_v
    for frame in barrier.type.frames[frame_orient]:
        start_off = 0
        frame_length = total_dist
        # If corners are present, shrink the straight piece inwards to not overlap.
        if corner_start in borders[start_u, start_v]:
            start_off += frame.corner_size_horiz
            frame_length -= frame.corner_size_horiz
        if corner_end in borders[end_u, end_v]:
            frame_length -= frame.corner_size_horiz

        if frame.seg_straight_prop:
            off = start_off
            for size in frame.seg_straight_fitter(frame_length):
                # If backwards, advance before placing.
                if backwards:
                    off += size

                for piece in frame.seg_straight_prop[size]:
                    piece.place(
                        vmf, slice_key, lighting_origin,
                        32. * start_u + off_u * off + pos_u,
                        32. * start_v + off_v * off + pos_v,
                        orient,
                    )

                if not backwards:
                    off += size

        off = frame_length if backwards else start_off
        for brush_seg in frame.seg_straight_brush:
            brush_seg.place_sized(
                vmf, slice_key,
                32.0 * start_u + off_u * off + pos_u,
                32.0 * start_v + off_v * off + pos_v,
                orient, direction, frame_length,
            )
    # Only one of these has an actual length.
    for u in range(start_u, end_u + 1):
        for v in range(start_v, end_v + 1):
            borders[u, v] &= ~straight


def place_convex_corner(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    lighting_origin: str,
    orient: FrozenMatrix,
    u: float,
    v: float,
) -> None:
    """Try to place a convex corner here."""
    for frame in barrier.type.frames[FrameOrient.HORIZ]:
        for seg in frame.seg_corner:
            seg.place(vmf, slice_key, lighting_origin, 32.0 * u, 32.0 * v, orient)


def add_glass_floorbeams(vmf: VMF, temp_name: str) -> None:
    """Add beams to separate large glass panels.

    The texture is assumed to match plasticwall004a's shape.
    """
    # TODO: Move floorbeams configuration to each barrier.
    template = template_brush.get_template(temp_name)
    beam_template: Solid
    try:
        [beam_template] = template.visgrouped_solids()
    except ValueError as exc:
        raise user_errors.UserError(user_errors.TOK_GLASS_FLOORBEAM_TEMPLATE) from ValueError(
            f'Floorbeam template {temp_name} has multiple/zero solids!'
        ).with_traceback(exc.__traceback__)

    # Grab the 'end' side, which we move around.
    for side in beam_template.sides:
        if side.normal() == (-1, 0, 0):
            beam_end_face = side
            break
    else:
        raise user_errors.UserError(user_errors.TOK_GLASS_FLOORBEAM_TEMPLATE)

    separation = options.GLASS_FLOORBEAM_SEP() + 1
    separation *= 128

    # First we want to find all the groups of contiguous glass sections.
    # This is a mapping from some glass piece to its group list.
    groups: dict[tuple[Barrier, FrozenVec], list[FrozenVec]] = {}

    for (origin, normal), barrier in BARRIERS.items():
        # Grating doesn't use it.
        if not barrier.use_floorbeams:
            continue

        if abs(normal.z) < 0.125:
            # Not walls.
            continue

        pos = FrozenVec(origin) + normal * 62

        groups[barrier, pos] = [pos]

    # Loop over every pos and check in the +x/y directions for another glass
    # piece. If there, merge the two lists and set every pos in the group to
    # point to the new list.
    # Once done, every unique list = a group.

    for barrier, pos in groups.keys():
        for off in ((128, 0, 0), (0, 128, 0)):
            neighbour = pos + off
            if (barrier, neighbour) in groups:
                our_group = groups[barrier, pos]
                neigh_group = groups[barrier, neighbour]
                if our_group is neigh_group:
                    continue

                # Now merge the two lists. We then need to update all dict
                # locations to point to the new list.
                if len(neigh_group) > len(our_group):
                    small_group, large_group = our_group, neigh_group
                else:
                    small_group, large_group = neigh_group, our_group

                large_group.extend(small_group)
                for pos in small_group:
                    groups[barrier, pos] = large_group

    # Remove duplicate objects by using the ID as key.
    group_list = list({
        id(group): (barrier, group)
        for (barrier, _), group in groups.items()
    }.values())

    # Side -> u, v or None

    for barrier, group in group_list:
        bbox_min, bbox_max = Vec.bbox(group)
        dimensions = bbox_max - bbox_min

        # Our beams align to the smallest axis.
        if dimensions.y > dimensions.x:
            beam_ax = 'x'
            side_ax = 'y'
            rot = Matrix()
        else:
            beam_ax = 'y'
            side_ax = 'x'
            rot = Matrix.from_yaw(90)

        # Build min, max tuples for each axis in the other direction.
        # This tells us where the beams will be.
        beams: dict[float, tuple[float, float]] = {}

        # Add 128 so the first pos isn't a beam.
        offset = bbox_min[side_ax] + 128

        for pos in group:
            side_off = pos[side_ax]
            beam_off = pos[beam_ax]
            # Skip over non-'sep' positions..
            if (side_off - offset) % separation != 0:
                continue

            try:
                min_off, max_off = beams[side_off]
            except KeyError:
                beams[side_off] = beam_off, beam_off
            else:
                beams[side_off] = min(min_off, beam_off), max(max_off, beam_off)

        detail = vmf.create_ent('func_detail')

        for side_off, (min_off, max_off) in beams.items():
            for min_pos, max_pos in beam_hole_split(
                beam_ax,
                Vec.with_axes(side_ax, side_off, beam_ax, min_off, 'z', bbox_min),
                Vec.with_axes(side_ax, side_off, beam_ax, max_off, 'z', bbox_min),
            ):

                if min_pos[beam_ax] >= max_pos[beam_ax]:
                    raise ValueError(min_pos, max_pos, beam_ax)

                # Make the beam.
                # Grab the end face and snap to the length we want.
                beam_end_off = max_pos[beam_ax] - min_pos[beam_ax]
                assert beam_end_off > 0, beam_end_off
                for plane in beam_end_face.planes:
                    plane.x = beam_end_off

                new_beam = beam_template.copy(vmf_file=vmf)
                new_beam.localise(min_pos, rot)
                detail.solids.append(new_beam)


def beam_hole_split(axis: str, min_pos: Vec, max_pos: Vec) -> Iterator[tuple[Vec, Vec]]:
    """Break up floor beams to fit around holes."""

    # Go along the shape. For each point, check if a hole is present,
    # and split at that.
    # Our positions are centered, but we return ones at the ends.
    # TODO: Need to make sure all these points actually have this barrier.

    # Inset in 4 units from each end to not overlap with the frames.
    start_pos = min_pos - Vec.with_axes(axis, 60)
    if HOLES:
        # Extract normal from the z-axis.
        grid_height = min_pos.z // 128 * 128 + 64
        if grid_height < min_pos.z:
            normal = FrozenVec(z=+1)
        else:
            normal = FrozenVec(z=-1)
        for pos in min_pos.iter_line(max_pos, 128):
            try:
                hole: Hole = HOLES[FrozenVec(pos.x, pos.y, grid_height), normal]
            except KeyError:
                continue
            else:
                yield start_pos, pos - Vec.with_axes(axis, hole.variant.radius)
                start_pos = pos + Vec.with_axes(axis, hole.variant.radius)

    # Last segment, or all if no holes.
    yield start_pos, max_pos + Vec.with_axes(axis, 60)
