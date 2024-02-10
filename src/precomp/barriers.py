"""Implements Glass and Grating."""
from __future__ import annotations

from typing import Callable, Dict, Final, Iterator, List, Mapping, Set, Tuple

from typing_extensions import Literal, Self, Sequence

from collections import defaultdict
from enum import Enum, Flag, auto as enum_auto

from srctools import EmptyMapping, Keyvalues
from srctools.math import AnyMatrix, to_matrix, FrozenMatrix, Vec, FrozenVec, Angle, Matrix
from srctools.vmf import VMF, Solid, Entity
import srctools.logger
import attrs

from plane import Plane
from precomp import instanceLocs, texturing, options, template_brush, conditions, collisions
from precomp.grid_optim import optimise as grid_optimise
import consts
import user_errors
import utils


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME: str | None = None
STRAIGHT_LEN: Final = 64


class HoleType(Enum):
    """Type of hole cut into the barrier."""
    SMALL = 'small'  # 1x1 hole (portal)
    LARGE = 'large'  # 3x3 hole (funnel)


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
FOOTPRINTS: Final[Mapping[HoleType, Sequence[Tuple[int, int]]]] = {
    HoleType.SMALL: [
        (u, v)
        for u in [-16, +16]
        for v in [-16, +16]
    ],
    # The large barrier excludes the corners.
    HoleType.LARGE: [
        (u, v)
        for u in [-80, -48, -16, +16, +48, +80]
        for v in [-80, -48, -16, +16, +48, +80]
        if abs(u) != 80 or abs(v) != 80
    ]
}
LARGE_DISALLOWED: Sequence[FrozenVec] = [
    FrozenVec(-128, 0, 0),
    FrozenVec(+128, 0, 0),
    FrozenVec(0, -128, 0),
    FrozenVec(0, +128, 0),
]


@attrs.define(eq=False)
class Hole:
    """A hole item placed in the map."""
    inst: Entity
    type: HoleType
    plane: utils.SliceKey
    origin: Vec
    # If true, we found a matching barrier this was inserted into.
    inserted: bool = False


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
            hint_thick=kv.float('hint_thick'),
            coll_thick=kv.float('coll_thick', 4.0),
            mergeable=kv.bool('mergeable'),
        )


@attrs.define(eq=False)
class Barrier:
    """A glass/grating item."""
    name: str
    type: BarrierType
    instances: List[Entity] = attrs.Factory(list)

    def __eq__(self, other: object) -> bool:
        """Two barriers are equal if they are the same, or if mergable and share the type."""
        if isinstance(other, Barrier):
            if self.name == other.name:
                return True
            if self.type is other.type and self.type.mergeable:
                return True
            return False
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

    def place(self, vmf: VMF, slice_key: utils.SliceKey, u: float, v: float, angles: AnyMatrix) -> None:
        """Place the segment at the specified location."""
        rotation = to_matrix(angles) @ slice_key.orient
        origin = slice_key.plane_to_world(u, v) + self.offset @ rotation
        self._place(
            vmf, origin, self.orient @ rotation,
        )

    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix) -> None:
        """Place the segment at the specified location."""
        raise NotImplementedError


@attrs.frozen(eq=False, kw_only=True)
class SegmentProp(Segment):
    """A model, placed with an optional offset."""
    model: str

    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix) -> None:
        """Place the segment at the specified location."""
        vmf.create_ent(
            'prop_static',
            origin=origin,
            angles=angles,
            model=self.model,
            skin=0,
            solid=6,
            # TODO lighting origins?
        )


@attrs.frozen(eq=False, kw_only=True)
class SegmentBrush(Segment):
    """A template brush, placed with an optional offset."""
    brush: template_brush.Template

    def _place(self, vmf: VMF, origin: Vec, angles: FrozenMatrix) -> None:
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

    if GLASS_ID not in BARRIER_TYPES:
        LOGGER.warning('No definition for {}!', GLASS_ID)
        # Hardcoded basic definition.
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
        # Hardcoded basic definition.
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


def parse_map(vmf: VMF, info: conditions.MapInfo) -> None:
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


def test_hole_spot(origin: FrozenVec, plane: utils.SliceKey, hole_type: HoleType) -> Literal['noglass', 'valid', 'nospace']:
    """Check if the given position is valid for holes.

    We need to check that it's actually placed on glass/grating, and that
    all the parts are the same. Otherwise, it'd collide with the borders. This returns:

    * 'valid' if the position is valid.
    * 'noglass' if the centerpoint isn't glass/grating.
    * 'nospace' if no adjacient panel is present.
    """
    center = plane.world_to_plane(origin)
    barrier_plane = BARRIERS[plane]

    center_type = barrier_plane[center.x // 32, center.y // 32]
    if center_type is BARRIER_EMPTY:
        return 'noglass'

    # The corners don't matter, but all 4 neighbours must be there.
    for u_off, v_off in FOOTPRINTS[hole_type]:
        pos = plane.plane_to_world(center.x + u_off, center.y + v_off)
        off_type = barrier_plane[(center.x + u_off) // 32, (center.y + v_off) // 32]
        if off_type is BARRIER_EMPTY:
            # No side
            LOGGER.warning('No offset barrier at {}, {}', pos, plane)
            return 'nospace'
        if off_type != center_type:
            # Different type.
            LOGGER.warning('Wrong barrier type at {}, {}: {} != {}', pos, plane, off_type, center_type)
            return 'nospace'

    # In each direction, make sure a large hole isn't present.
    if hole_type is HoleType.LARGE:
        for offset in LARGE_DISALLOWED:
            side_pos = plane.plane_to_world(*offset).freeze()
            if HOLES[plane].get(side_pos) is HoleType.LARGE:
                # TODO: Draw this other hole as well?
                return 'nospace'
    return 'valid'


@conditions.make_result('GlassHole')
def res_glass_hole(inst: Entity, res: Keyvalues) -> None:
    """Add Glass/grating holes. The value should be 'large' or 'small'."""
    hole_type = HoleType(res.value)

    normal: FrozenVec = FrozenVec(z=-1) @ Angle.from_str(inst['angles'])
    origin: FrozenVec = FrozenVec.from_str(inst['origin']) // 128 * 128 + 64
    origin += 64 * normal
    slice_key = utils.SliceKey(normal, origin)

    first_placement = test_hole_spot(origin, slice_key, hole_type)
    if first_placement == 'valid':
        sel_plane = slice_key
    else:
        # Test the opposite side of the glass too.
        slice_key = utils.SliceKey(-normal, origin)

        sec_placement = test_hole_spot(origin, slice_key, hole_type)
        if sec_placement == 'valid':
            sel_plane = slice_key
        else:
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_FOOTPRINT
                if first_placement == 'nospace' or sec_placement == 'nospace' else
                user_errors.TOK_BARRIER_HOLE_MISPLACED,
                barrier_hole=user_errors.BarrierHole(
                    pos=user_errors.to_threespace(origin + 64 * normal),
                    axis=normal.axis(),
                    large=hole_type is HoleType.LARGE,
                    small=hole_type is HoleType.SMALL,
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
                large=hole_type is HoleType.LARGE or existing is HoleType.LARGE,
                small=hole_type is HoleType.SMALL or existing is HoleType.SMALL,
                footprint=False,
            ),
        )
    HOLES[sel_plane][origin] = Hole(inst, hole_type, sel_plane, origin.thaw())
    inst['origin'] = origin - 64 * normal
    inst['angles'] = (-sel_plane.normal).to_angle()


def template_solids_and_coll(
    template: template_brush.Template | None, visgroup: str,
) -> tuple[list[Solid], list[collisions.BBox]]:
    """Retrieve the brushes and collision boxes for the specified visgroup."""
    if template is None:
        return [], []
    else:
        groups = {visgroup, ''}
        return template.visgrouped_solids(visgroup), [
            coll.bbox for coll in template.collisions
            if coll.visgroups.issubset(groups)
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

    debug_skin = {
        GLASS_ID: 5,
        GRATE_ID: 0,
    }
    add_debug = conditions.fetch_debug_visgroup(vmf, 'Barriers')
    debug_id = 0
    for plane_slice, plane in BARRIERS.items():
        frame_orient = FrameOrient.HORIZ if abs(plane_slice.normal.z) < 0.5 else FrameOrient.VERT
        for barrier, group_plane in find_plane_groups(plane):
            borders = calc_borders(group_plane)

            debug_id += 1
            for (u, v) in group_plane:
                add_debug(
                    'bee2_template_tilesetter',
                    origin=plane_slice.plane_to_world(32 * u + 16, 32 * v + 16, 2),
                    angles=plane_slice.orient,
                    skin=debug_skin[barrier.type.id],
                    targetname=f'barrier_{debug_id}',
                    comment=f'Border: {borders[u, v]}, u={u}, v={v}',
                )

            if barrier.type.hint_thick > 0:
                add_hints(vmf, plane_slice, group_plane, barrier.type.hint_thick)

            for (u, v) in group_plane:
                place_concave_corner(vmf, barrier, plane_slice, borders, frame_orient, u, v, ORIENT_W, +1, +1)
                place_concave_corner(vmf, barrier, plane_slice, borders, frame_orient, u, v, ORIENT_S, -1, +1)
                place_concave_corner(vmf, barrier, plane_slice, borders, frame_orient, u, v, ORIENT_E, -1, -1)
                place_concave_corner(vmf, barrier, plane_slice, borders, frame_orient, u, v, ORIENT_N, +1, -1)

            for (u, v), border in borders.items():
                if Border.STRAIGHT_N in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, u, v,
                        Border.STRAIGHT_N, ORIENT_E, 'x', False,
                        Border.CORNER_NE, Border.CORNER_NW,
                        0, 32,
                    )
                if Border.STRAIGHT_S in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, u, v,
                        Border.STRAIGHT_S, ORIENT_W, 'x', True,
                        Border.CORNER_SE, Border.CORNER_SW,
                        0, 0,
                    )
                if Border.STRAIGHT_E in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, u, v,
                        Border.STRAIGHT_E, ORIENT_N, 'y', False,
                        Border.CORNER_SE, Border.CORNER_NE,
                        0, 0,
                    )
                if Border.STRAIGHT_W in border:
                    place_straight_run(
                        vmf, barrier, plane_slice, borders, u, v,
                        Border.STRAIGHT_W, ORIENT_S, 'y', True,
                        Border.CORNER_SW, Border.CORNER_NW,
                        32, 0,
                    )

                if Border.CORNER_NW in border:
                    place_convex_corner(vmf, barrier, plane_slice, ORIENT_W, u + 1, v + 1)
                if Border.CORNER_NE in border:
                    place_convex_corner(vmf, barrier, plane_slice, ORIENT_S, u, v + 1)
                if Border.CORNER_SE in border:
                    place_convex_corner(vmf, barrier, plane_slice, ORIENT_E, u, v)
                if Border.CORNER_SW in border:
                    place_convex_corner(vmf, barrier, plane_slice, ORIENT_N, u + 1, v)

            for min_u, min_v, max_u, max_v, _ in grid_optimise(group_plane):
                place_prism_brushes(vmf, barrier, plane_slice, min_u, min_v, max_u, max_v)


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


def place_prism_brushes(
    vmf: VMF, barrier: Barrier, plane_slice: utils.SliceKey,
    min_u: int, min_v: int, max_u: int, max_v: int,
) -> None:
    """Place brushes in these coordinates."""
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
                32. * u + 16. * off_u + 16.0,
                32. * v + 16. * off_v + 16.0,
                orient,
            )


def place_straight_run(
    vmf: VMF,
    barrier: Barrier,
    slice_key: utils.SliceKey,
    borders: Plane[Border],
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
                        vmf, slice_key,
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
    orient: FrozenMatrix,
    u: float,
    v: float,
) -> None:
    """Try to place a convex corner here."""
    for frame in barrier.type.frames[FrameOrient.HORIZ]:
        for seg in frame.seg_corner:
            seg.place(vmf, slice_key, 32.0 * u, 32.0 * v, orient)


def old_generation(vmf: VMF, coll: collisions.Collisions) -> None:
    # Avoid error without this package.
    hole_temp_id = options.GLASS_HOLE_TEMP()
    if HOLES and hole_temp_id is not None:
        # Grab the template solids we need.
        hole_combined_temp = template_brush.get_template(hole_temp_id)
    else:
        hole_combined_temp = None

    hole_temp_small = template_solids_and_coll(hole_combined_temp, 'small')
    hole_temp_lrg_diag = template_solids_and_coll(hole_combined_temp, 'large_diagonal')
    hole_temp_lrg_cutout = template_solids_and_coll(hole_combined_temp, 'large_cutout')
    hole_temp_lrg_square = template_solids_and_coll(hole_combined_temp, 'large_square')

    floorbeam_temp = options.GLASS_FLOORBEAM_TEMP()

    # Group the positions by planes in each orientation.
    # This makes them 2D grids which we can optimise.
    # (normal_dist, positive_axis, type) -> Plane(type)
    slices: dict[tuple[FrozenVec, bool], Plane[Barrier]] = defaultdict(lambda: Plane(default=BARRIER_EMPTY))

    # Compute contiguous sections of any barrier type, then place hint brushes to ensure sorting
    # is done correctly.
    for (plane_pos, is_pos), pos_slice in slices.items():
        norm_axis = plane_pos.axis()
        normal = FrozenVec.with_axes(norm_axis, 1 if is_pos else -1)

        u_axis, v_axis = Vec.INV_AXIS[norm_axis]
        is_present = Plane.fromkeys(pos_slice, True)
        for min_u, min_v, max_u, max_v, _ in grid_optimise(is_present):
            # These are two points in the origin plane, at the borders.
            pos_min = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, min_u * 32,
                v_axis, min_v * 32,
            )
            pos_max = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, max_u * 32 + 32,
                v_axis, max_v * 32 + 32,
            )
            hint = vmf.make_prism(
                pos_min + normal * 64,
                pos_max + normal * 60,
                mat=consts.Tools.SKIP,
            ).solid
            for side in hint:
                if abs(Vec.dot(side.normal(), normal)) > 0.99:
                    side.mat = consts.Tools.HINT
            vmf.add_brush(hint)

    # Remove pane sections where the holes are. We then generate those with
    # templates for slanted parts.
    for (origin, normal), hole_type in HOLES.items():
        barrier = BARRIERS[origin, normal]
        norm_axis = normal.axis()
        u, v = origin.other_axes(norm_axis)
        norm_pos = FrozenVec.with_axes(norm_axis, origin)
        slice_plane = slices[norm_pos, normal[norm_axis] > 0]
        bad_locs: List[Vec] = []
        for u_off, v_off in FOOTPRINTS[hole_type]:
            # Remove these squares, but keep them in the Plane,
            # so we can check if there was glass there.
            uv = (int((u + u_off) // 32), int((v + v_off) // 32))
            if uv in slice_plane:
                slice_plane[uv] = BARRIER_EMPTY
            else:
                u_ax, v_ax = Vec.INV_AXIS[norm_axis]
                bad_locs.append(Vec.with_axes(
                    norm_axis, norm_pos,
                        u_ax, u + u_off,
                        v_ax, v + v_off,
                    ))
        if bad_locs:
            raise user_errors.UserError(
                user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
                points=bad_locs,
                barrier_hole={
                    'pos': user_errors.to_threespace(origin + 64 * normal),
                    'axis': norm_axis,
                    'large': hole_type is HoleType.LARGE,
                    'small': hole_type is HoleType.SMALL,
                    'footprint': True,
                }
            )

        angles = normal.to_angle()
        hole_temp: list[tuple[list[Solid], list[collisions.BBox], Matrix]] = []

        # This is a tricky bit. Two large templates would collide
        # diagonally, and we allow the corner glass to not be present since
        # the hole doesn't actually use that 32x32 segment.
        # So we need to determine which of 3 templates to use.
        corn_angles = angles.copy()
        if hole_type is HoleType.LARGE:
            for corn_angles.roll in (0, 90, 180, 270):
                corn_mat = Matrix.from_angle(corn_angles)

                corn_dir = FrozenVec(y=1, z=1) @ corn_angles
                hole_off = origin + 128 * corn_dir
                diag_type = HOLES.get((hole_off, normal), None)
                corner_pos = origin + 80 * corn_dir
                corn_u, corn_v = corner_pos.other_axes(norm_axis)
                corn_u = int(corn_u // 32)
                corn_v = int(corn_v // 32)

                if diag_type is HoleType.LARGE:
                    # There's another large template to this direction.
                    # Just have 1 generate both combined, so the brushes can
                    # be more optimal. To pick, arbitrarily make the upper one
                    # be in charge.
                    if corn_v > v // 32:
                        hole_temp.append(hole_temp_lrg_diag + (corn_mat, ))
                    continue
                # This bit of the glass is present, so include it in our brush, then clear.
                if (corn_u, corn_v) in slice_plane:
                    hole_temp.append(hole_temp_lrg_square + (corn_mat, ))
                else:
                    hole_temp.append(hole_temp_lrg_cutout + (corn_mat, ))

        else:
            hole_temp.append(hole_temp_small + (Matrix.from_angle(angles), ))

        for _, bbox_list, matrix in hole_temp:
            # Place the collisions.
            for bbox in bbox_list:
                bbox = bbox @ matrix + origin
                coll.add(bbox.with_attrs(name=str(barrier.id), contents=barrier.contents))

        def solid_pane_func(off1: float, off2: float, mat: str) -> list[Solid]:
            """Given the two thicknesses, produce the curved hole from the template."""
            off_min = 64 - max(off1, off2)
            off_max = 64 - min(off1, off2)
            new_brushes = []
            for brushes, _, matrix in hole_temp:
                for orig_brush in brushes:
                    brush = orig_brush.copy(vmf_file=vmf)
                    new_brushes.append(brush)
                    for face in brush.sides:
                        face.mat = mat
                        for point in face.planes:
                            if point.x > 64:
                                point.x = off_max
                            else:
                                point.x = off_min
                        face.localise(origin, matrix)
                        # Increase precision, these are small detail brushes.
                        face.lightmap = 8
            return new_brushes

        make_glass_grating(
            vmf,
            origin,
            normal,
            barrier,
            solid_pane_func,
        )

    for (plane_pos, is_pos), pos_slice in slices.items():
        norm_axis = plane_pos.axis()
        normal = FrozenVec.with_axes(norm_axis, 1 if is_pos else -1)

        u_axis, v_axis = Vec.INV_AXIS[norm_axis]

        for min_u, min_v, max_u, max_v, barrier in grid_optimise(pos_slice):
            if barrier is BARRIER_EMPTY:  # Hole placed here and overwrote the glass/grating.
                continue
            # These are two points in the origin plane, at the borders.
            pos_min = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, min_u * 32,
                v_axis, min_v * 32,
            )
            pos_max = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, max_u * 32 + 32,
                v_axis, max_v * 32 + 32,
            )
            coll.add(collisions.BBox(
                pos_min + normal * 64.0,
                pos_max + normal * 60.0,
                name=barrier.id,
                contents=barrier.contents,
            ))

            def solid_pane_func(off1: float, off2: float, mat: str) -> list[Solid]:
                """Make the solid brush."""
                return [vmf.make_prism(
                    pos_min + normal * (64.0 - off1),
                    pos_max + normal * (64.0 - off2),
                    mat=mat,
                ).solid]

            make_glass_grating(
                vmf,
                (pos_min + pos_max)/2 + 63 * normal,
                normal,
                barrier,
                solid_pane_func,
            )

    if floorbeam_temp:
        LOGGER.info('Adding Glass floor beams...')
        add_glass_floorbeams(vmf, floorbeam_temp)
        LOGGER.info('Done!')


def make_glass_grating(
    vmf: VMF,
    ent_pos: Vec | FrozenVec,
    normal: Vec | FrozenVec,
    barrier: Barrier,
    solid_func: Callable[[float, float, str], list[Solid]],
) -> None:
    """Make all the brushes needed for glass/grating.

    solid_func() is called with two offsets from the voxel edge, and returns a
    matching list of solids. This allows doing holes and normal panes with the
    same function.
    """
    # TODO: Make this all configurable
    if barrier.id == GLASS_ID:
        main_ent = vmf.create_ent('func_detail')
        tex_cat = 'glass'
    else:
        main_ent = vmf.create_ent(
            'func_brush',
            renderfx=14,  # Constant Glow
            solidity=1,  # Never solid
            origin=ent_pos,
        )
        tex_cat = 'grating'

    # The actual glass/grating brush - 0.5-1.5 units back from the surface.
    main_ent.solids = solid_func(0.5, 1.5, consts.Tools.NODRAW)

    for face in main_ent.sides():
        if abs(Vec.dot(normal, face.normal())) > 0.99:
            texturing.apply(texturing.GenCat.SPECIAL, face, tex_cat)
            barrier.face_temp.apply(face, change_mat=False)

    if barrier.tex_player_clip is not None:
        if abs(normal.z) < 0.125:
            # If vertical, we don't care about footsteps.
            # So just use 'normal' clips.
            player_clip = vmf.create_ent('func_detail')
            player_clip_mat = consts.Tools.PLAYER_CLIP
        else:
            # This needs to be a func_brush, otherwise the clip texture data
            # will be merged with other clips.
            player_clip = vmf.create_ent(
                'func_brush',
                solidbsp=1,
                origin=ent_pos,
            )
            # We also need a func_detail clip, which functions on portals.
            # Make it thinner, so it doesn't impact footsteps.
            player_thin_clip = vmf.create_ent('func_detail')
            player_thin_clip.solids = solid_func(0.5, 3.5, consts.Tools.PLAYER_CLIP)

        player_clip.solids = solid_func(0, 4, barrier.tex_player_clip)

    if barrier.id == GRATE_ID:
        # Add the VPhysics clip.
        phys_clip = vmf.create_ent(
            'func_clip_vphysics',
            filtername='@grating_filter',
            origin=ent_pos,
            StartDisabled=0,
        )
        phys_clip.solids = solid_func(0, 2, consts.Tools.TRIGGER)


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

    # Inset in 4 units from each end to not overlap with the frames.
    start_pos = min_pos - Vec.with_axes(axis, 60)
    if HOLES:
        hole_size_large = options.GLASS_HOLE_SIZE_LARGE() / 2
        hole_size_small = options.GLASS_HOLE_SIZE_SMALL() / 2

        # Extract normal from the z-axis.
        grid_height = min_pos.z // 128 * 128 + 64
        if grid_height < min_pos.z:
            normal = FrozenVec(z=+1)
        else:
            normal = FrozenVec(z=-1)
        for pos in min_pos.iter_line(max_pos, 128):
            try:
                hole_type = HOLES[FrozenVec(pos.x, pos.y, grid_height), normal]
            except KeyError:
                continue
            else:
                if hole_type is HoleType.SMALL:
                    size = hole_size_small
                elif hole_type is HoleType.LARGE:
                    size = hole_size_large
                else:
                    raise AssertionError(hole_type)

                yield start_pos, pos - Vec.with_axes(axis, size)
                start_pos = pos + Vec.with_axes(axis, size)

    # Last segment, or all if no holes.
    yield start_pos, max_pos + Vec.with_axes(axis, 60)
