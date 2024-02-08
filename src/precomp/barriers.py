"""Implements Glass and Grating."""
from __future__ import annotations

from typing import Callable, Dict, Final, Iterator, List, Set, Tuple
from typing_extensions import Literal, Self, Sequence

from collections import defaultdict
from enum import Enum, Flag, auto as enum_auto

from srctools import FrozenMatrix, Vec, FrozenVec, Keyvalues, Angle, Matrix
from srctools.vmf import VMF, Solid, Entity, EntityGroup
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

ORIENTS = {
    Vec.T: FrozenMatrix.from_angle(180, 0, 0),
    Vec.B: FrozenMatrix.from_angle(0, 0, 0),
    Vec.N: FrozenMatrix.from_angle(90, 270, 0),
    Vec.S: FrozenMatrix.from_angle(90, 90, 0),
    Vec.E: FrozenMatrix.from_angle(90, 180, 0),
    Vec.W: FrozenMatrix.from_angle(90, 0, 0),
}


FULL_SQUARE: Final[Sequence[Tuple[int, int]]] = [
    (u, v)
    for u in [-48, -16, +16, +48]
    for v in [-48, -16, +16, +48]
]
BARRIER_FOOTPRINT_SMALL: Final[Sequence[Tuple[int, int]]] = [
    (u, v)
    for u in [-16, +16]
    for v in [-16, +16]
]
# The large barrier excludes the corners.
BARRIER_FOOTPRINT_LARGE: Final[Sequence[Tuple[int, int]]] = [
    (u, v)
    for u in [-80, -48, -16, +16, +48, +80]
    for v in [-80, -48, -16, +16, +48, +80]
    if abs(u) != 80 or abs(v) != 80
]


@attrs.frozen(eq=False, kw_only=True)
class Barrier:
    """Type of barrier."""
    id: utils.ObjectID | utils.SpecialID
    voice_attr: str = ''
    frames: Sequence[FrameType] = ()
    error_disp: user_errors.Kind | None = None
    face_temp: template_brush.ScalingTemplate = template_brush.ScalingTemplate.world()
    contents: collisions.CollideType = collisions.CollideType.SOLID
    use_floorbeams: bool = False

    tex_player_clip: str | None = None


# Special barrier representing the lack of one.
BARRIER_EMPTY = Barrier(id=utils.ID_EMPTY)


@attrs.frozen(eq=False, kw_only=True)
class FrameType:
    """Configuration for a type of barrier frame."""
    convex_corner_inst: str | None = None

    @classmethod
    def parse(cls, kv: Keyvalues) -> Self:
        """Parse from keyvalues configuration."""
        return cls()


# Planar slice -> plane of barriers.
# The plane is specified as the edge of the voxel.
BARRIERS: dict[utils.SliceKey, Plane[Barrier]] = defaultdict(lambda: Plane(default=BARRIER_EMPTY))
# (origin, normal) -> hole
HOLES: dict[tuple[FrozenVec, FrozenVec], HoleType] = {}
FRAME_TYPES: Dict[utils.ObjectID, Dict[FrameOrient, FrameType]] = {}


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


def parse_map(vmf: VMF, info: conditions.MapInfo) -> None:
    """Find all glass/grating in the map.

    This removes the per-tile instances, and all original brushwork.
    The frames are updated with a fixup var, as appropriate.
    """
    frame_inst = instanceLocs.resolve_filter('[glass_frames]', silent=True)
    segment_inst = instanceLocs.resolve_filter('[glass_128]', silent=True)

    glass = Barrier(
        id=GLASS_ID,
        voice_attr='glass',
        face_temp=template_brush.get_scaling_template(options.GLASS_TEMPLATE()),
        tex_player_clip=consts.Tools.PLAYER_CLIP_GLASS,
    )
    grating = Barrier(
        id=GRATE_ID,
        voice_attr='grating',
        face_temp=template_brush.get_scaling_template(options.GRATING_TEMPLATE()),
        tex_player_clip=consts.Tools.PLAYER_CLIP_GRATE,
    )

    for entities, material, barrier in [
        (vmf.by_class['func_detail'], consts.Special.GLASS, glass),
        (vmf.by_class['func_brush'], consts.Special.GRATING, grating),
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
                plane_slice = utils.SliceKey(norm, center)
                local = plane_slice.world_to_plane(center)

                # Now set each 32-grid cell to be the barrier. Since this is square the orientation
                # doesn't matter.
                for u_off, v_off in FULL_SQUARE:
                    BARRIERS[plane_slice][
                        (local.x + u_off) // 32,
                        (local.y + v_off) // 32,
                    ] = barrier
                break  # Don't check the remaining faces.

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        if not filename:
            continue
        if filename in segment_inst:
            # The vanilla segment instance is the same for glass/grating. Look up the barriers
            # here, so we can mark them with a fixup. At this point all barrier definitions are
            # whole voxel, so it doesn't matter which we pick.
            center = Vec.from_str(inst['origin']) // 128 * 128 + (64, 64, 64)
            norm = Vec(x=-1) @ Angle.from_str(inst['angles'])
            center += 64 * norm
            plane_slice = utils.SliceKey(norm, center)
            local = plane_slice.world_to_plane(center)
            try:
                barrier = BARRIERS[plane_slice][local.x // 32, local.y // 32]
            except KeyError:
                LOGGER.warning('No glass/grating for frame at {}, {}?', center, norm)
            else:
                if barrier is glass:
                    inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = 'glass'
                elif barrier is grating:
                    inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = 'grate'
                else:
                    # vmf.create_ent('info_particle_system', orign=center, angles=inst['angles'])
                    LOGGER.warning(
                        'No glass/grating for frame at {}, {} = {}, {}? - got {}',
                        center, norm, plane_slice, local / 32, barrier,
                    )
        if filename in frame_inst:  # Frames are useless, we'll make our own.
            inst.remove()


def test_hole_spot(origin: FrozenVec, normal: FrozenVec, hole_type: HoleType) -> Literal['noglass', 'valid', 'nospace']:
    """Check if the given position is valid for holes.

    We need to check that it's actually placed on glass/grating, and that
    all the parts are the same. Otherwise, it'd collide with the borders. This returns:

    * 'valid' if the position is valid.
    * 'noglass' if the centerpoint isn't glass/grating.
    * 'nospace' if no adjacient panel is present.
    """
    try:
        center_type = BARRIERS[origin, normal]
    except KeyError:
        return 'noglass'

    if hole_type is HoleType.SMALL:
        return 'valid'

    u, v = Vec.INV_AXIS[normal.axis()]
    # The corners don't matter, but all 4 neighbours must be there.
    for u_off, v_off in [
        (-128, 0),
        (0, -128),
        (128, 0),
        (0, 128),
    ]:
        pos = origin + FrozenVec.with_axes(u, u_off, v, v_off)
        try:
            off_type = BARRIERS[pos, normal]
        except KeyError:
            # No side
            LOGGER.warning('No offset barrier at {}, {}', pos, normal)
            return 'nospace'
        if off_type is not center_type:
            # Different type.
            LOGGER.warning('Wrong barrier type at {}, {}', pos, normal)
            return 'nospace'
        # Also check if a large hole is here, we'll collide.
        if HOLES.get((pos, normal)) is HoleType.LARGE:
            # TODO: Draw this other hole as well?
            return 'nospace'
    return 'valid'


@conditions.make_result('GlassHole')
def res_glass_hole(inst: Entity, res: Keyvalues) -> None:
    """Add Glass/grating holes. The value should be 'large' or 'small'."""
    hole_type = HoleType(res.value)

    normal: FrozenVec = round(FrozenVec(z=-1) @ Angle.from_str(inst['angles']), 6)
    origin: FrozenVec = FrozenVec.from_str(inst['origin']) // 128 * 128 + 64

    first_placement = test_hole_spot(origin, normal, hole_type)
    if first_placement == 'valid':
        sel_origin = origin
        sel_normal = normal
    else:
        # Test the opposite side of the glass too.
        inv_origin = origin + 128 * normal
        inv_normal = -normal

        sec_placement = test_hole_spot(inv_origin, inv_normal, hole_type)
        if sec_placement == 'valid':
            sel_origin = inv_origin
            sel_normal = inv_normal
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
    key = (sel_origin, sel_normal)
    if key in HOLES:
        raise user_errors.UserError(
            user_errors.TOK_BARRIER_HOLE_FOOTPRINT,
            points=[sel_origin + 64 * sel_normal],
            barrier_hole=user_errors.BarrierHole(
                pos=user_errors.to_threespace(sel_origin + 64 * sel_normal),
                axis=sel_normal.axis(),
                large=hole_type is HoleType.LARGE or HOLES[key] is HoleType.LARGE,
                small=hole_type is HoleType.SMALL or HOLES[key] is HoleType.SMALL,
                footprint=False,
            ),
        )
    HOLES[key] = hole_type
    inst['origin'] = sel_origin
    inst['angles'] = sel_normal.to_angle()


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
    debug_skin = {
        GLASS_ID: 5,
        GRATE_ID: 0,
    }
    add_debug = conditions.fetch_debug_visgroup(vmf, 'Barriers')
    debug_id = 0
    for plane_slice, plane in BARRIERS.items():
        for barrier, group_plane in find_plane_groups(plane):
            debug_id += 1
            for (u, v) in group_plane:
                add_debug(
                    'bee2_template_tilesetter',
                    origin=plane_slice.plane_to_world(32 * u + 16, 32 * v + 16),
                    angles=plane_slice.orient,
                    skin=debug_skin[barrier.id],
                    targetname=f'barrier_{debug_id}',
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
        while stack:
            x, y = pos = stack.pop()
            if completed[pos] or (value := plane[pos]) != cmp_value:
                continue
            completed[pos] = True
            group[pos] = value  # Preserve identity.
            stack |= {
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            }
        LOGGER.info('Group: {} = {}',  cmp_value, list(group))
        yield cmp_value, group


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

    # Valve doesn't implement convex corners, we'll do it ourselves.
    convex_corner_left = instanceLocs.resolve_one('[glass_left_convex_corner]', error=False)
    convex_corner_right = instanceLocs.resolve_one('[glass_right_convex_corner]', error=False)
    convex_corners: List[Tuple[FrozenMatrix, str, float]] = [
        (orient, filename, side)
        # We don't include 90 and 270, the other filename covers those.
        # Freeze to ensure this is constant.
        for orient in map(FrozenMatrix.from_yaw, [0.0, 180.0])
        for (filename, side) in [
            (convex_corner_left, -128.0),
            (convex_corner_right, +128.0),
        ]
        if filename
    ]

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

    # Group the positions by planes in each orientation.
    # This makes them 2D grids which we can optimise.
    # (normal_dist, positive_axis, type) -> Plane(type)
    slices: dict[tuple[FrozenVec, bool], Plane[Barrier]] = defaultdict(lambda: Plane(default=BARRIER_EMPTY))
    # We have this on the 32-grid to allow us to cut squares for holes.
    for (origin, normal), barr_type in BARRIERS.items():
        norm_axis = normal.axis()
        u, v = origin.other_axes(norm_axis)
        # Distance from origin to this plane.
        norm_pos = FrozenVec.with_axes(norm_axis, origin)
        slice_plane = slices[norm_pos, normal[norm_axis] > 0]
        for u_off, v_off in FULL_SQUARE:
            slice_plane[(u + u_off) // 32, (v + v_off) // 32] = barr_type

        # Also go place convex corners.
        for orient, filename, corner_side in convex_corners:
            orient @= ORIENTS[normal]
            # The convex corner is on the +X side, then +/-Y depending on the filename.
            # If the diagonal neighbour does not match, we need a corner instance.
            side_1 = orient.forward(128.0)
            side_2 = orient.left(corner_side)
            if (
                BARRIERS.get((origin + side_1, normal)) is barr_type and
                BARRIERS.get((origin + side_2, normal)) is barr_type and
                BARRIERS.get((origin + side_1 + side_2, normal)) is not barr_type
            ):
                conditions.add_inst(
                    vmf,
                    targetname='barrier',
                    file=filename,
                    origin=origin,
                    angles=orient,
                ).make_unique()

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
        offsets: Sequence[Tuple[int, int]]
        if hole_type is HoleType.LARGE:
            offsets = BARRIER_FOOTPRINT_LARGE
        else:
            offsets = BARRIER_FOOTPRINT_SMALL
        bad_locs: List[Vec] = []
        for u_off, v_off in offsets:
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
