"""Implements Glass and Grating."""
from collections import defaultdict
from enum import Enum
from typing import Dict, Tuple, List, Callable

from precomp import (
    texturing, options, packing,
    template_brush,
)
import consts
import srctools.logger
from precomp.conditions import make_result
from precomp.grid_optim import optimise as grid_optimise
from precomp.instanceLocs import resolve_one, resolve
from srctools import VMF, Vec, Solid, Property, Entity, Angle, Matrix


LOGGER = srctools.logger.get_logger(__name__)


COND_MOD_NAME = None


class BarrierType(Enum):
    """Type of barrier."""
    GLASS = 'glass'
    GRATING = 'grating'


class HoleType(Enum):
    """Type of hole cut into the barrier."""
    SMALL = 'small'  # 1x1 hole (portal)
    LARGE = 'large'  # 3x3 hole (funnel)

# (origin, normal) -> BarrierType
BARRIERS: Dict[
    Tuple[Tuple[float, float, float], Tuple[float, float, float]],
    BarrierType,
] = {}
HOLES: Dict[
    Tuple[Tuple[float, float, float], Tuple[float, float, float]],
    HoleType,
] = {}


def get_pos_norm(origin: Vec) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """From the origin, get the grid position and normal."""
    grid_pos = origin // 128 * 128 + (64, 64, 64)
    return grid_pos.as_tuple(), (origin - grid_pos).norm().as_tuple()


def parse_map(vmf: VMF, has_attr: Dict[str, bool]) -> None:
    """Find all glass/grating in the map.

    This removes the per-tile instances, and all original brushwork.
    The frames are updated with a fixup var, as appropriate.
    """
    frame_inst = resolve('[glass_frames]', silent=True)
    glass_inst = resolve_one('[glass_128]')

    pos = None
    for brush_ent in vmf.by_class['func_detail']:
        is_glass = False
        for face in brush_ent.sides():
            if face.mat == consts.Special.GLASS:
                has_attr['glass'] = True
                pos = face.get_origin()
                is_glass = True
                break
        if is_glass:
            brush_ent.remove()
            BARRIERS[get_pos_norm(pos)] = BarrierType.GLASS

    for brush_ent in vmf.by_class['func_brush']:
        is_grating = False
        for face in brush_ent.sides():
            if face.mat == consts.Special.GRATING:
                has_attr['grating'] = True
                pos = face.get_origin()
                is_grating = True
                break
        if is_grating:
            brush_ent.remove()
            BARRIERS[get_pos_norm(pos)] = BarrierType.GRATING

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        if filename == glass_inst:
            inst.remove()
        elif filename in frame_inst:
            # Add a fixup to allow distinguishing the type.
            pos = Vec.from_str(inst['origin']) // 128 * 128 + (64, 64, 64)
            norm = Vec(z=-1) @ Angle.from_str(inst['angles'])
            try:
                inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = BARRIERS[pos.as_tuple(), norm.as_tuple()].value
            except KeyError:
                LOGGER.warning('No glass/grating for frame at {}, {}?', pos, norm)

    if options.get(str, 'glass_pack') and has_attr['glass']:
        packing.pack_list(vmf, options.get(str, 'glass_pack'))


def test_hole_spot(origin: Vec, normal: Vec, hole_type: HoleType):
    """Check if the given position is valid for holes.

    We need to check that it's actually placed on glass/grating, and that
    all the parts are the same. Otherwise it'd collide with the borders.
    """

    try:
        center_type = BARRIERS[origin.as_tuple(), normal.as_tuple()]
    except KeyError:
        LOGGER.warning('No center barrier at {}, {}', origin, normal)
        return False

    if hole_type is HoleType.SMALL:
        return True

    u, v = Vec.INV_AXIS[normal.axis()]
    # The corners don't matter, but all 4 neighbours must be there.
    for u_off, v_off in [
        (-128, 0),
        (0, -128),
        (128, 0),
        (0, 128),
    ]:
        pos = origin + Vec.with_axes(u, u_off, v, v_off)
        try:
            off_type = BARRIERS[pos.as_tuple(), normal.as_tuple()]
        except KeyError:
            # No side
            LOGGER.warning('No offset barrier at {}, {}', pos, normal)
            return False
        if off_type is not center_type:
            # Different type.
            LOGGER.warning('Wrong barrier type at {}, {}', pos, normal)
            return False
    return True


@make_result('GlassHole')
def res_glass_hole(inst: Entity, res: Property):
    """Add Glass/grating holes. The value should be 'large' or 'small'."""
    hole_type = HoleType(res.value)

    normal: Vec = round(Vec(z=-1) @ Angle.from_str(inst['angles']), 6)
    origin: Vec = Vec.from_str(inst['origin']) // 128 * 128 + 64

    if test_hole_spot(origin, normal, hole_type):
        HOLES[origin.as_tuple(), normal.as_tuple()] = hole_type
        inst['origin'] = origin
        inst['angles'] = normal.to_angle()
        return

    # Test the opposite side of the glass too.

    inv_origin = origin + 128 * normal
    inv_normal = -normal

    if test_hole_spot(inv_origin, inv_normal, hole_type):
        HOLES[inv_origin.as_tuple(), inv_normal.as_tuple()] = hole_type
        inst['origin'] = inv_origin
        inst['angles'] = inv_normal.to_angle()
    else:
        # Remove the instance, so this does nothing.
        inst.remove()


def make_barriers(vmf: VMF):
    """Make barrier entities. get_tex is vbsp.get_tex."""
    glass_temp = template_brush.get_scaling_template(
        options.get(str, "glass_template")
    )
    grate_temp = template_brush.get_scaling_template(
        options.get(str, "grating_template")
    )
    hole_temp_small: List[Solid]
    hole_temp_lrg_diag: List[Solid]
    hole_temp_lrg_cutout: List[Solid]
    hole_temp_lrg_square: List[Solid]

    # Avoid error without this package.
    if HOLES:
        # Grab the template solids we need.
        hole_combined_temp = template_brush.get_template(
            options.get(str, 'glass_hole_temp')
        )
        hole_world, hole_detail, _ = hole_combined_temp.visgrouped({'small'})
        hole_temp_small = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_combined_temp.visgrouped({'large_diagonal'})
        hole_temp_lrg_diag = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_combined_temp.visgrouped({'large_cutout'})
        hole_temp_lrg_cutout = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_combined_temp.visgrouped({'large_square'})
        hole_temp_lrg_square = hole_world + hole_detail
    else:
        hole_temp_small = hole_temp_lrg_diag = hole_temp_lrg_cutout = hole_temp_lrg_square = []

    floorbeam_temp = options.get(str, 'glass_floorbeam_temp')

    if options.get_itemconf('BEE_PELLET:PelletGrating', False):
        # Merge together these existing filters in global_pti_ents
        vmf.create_ent(
            origin=options.get(Vec, 'global_pti_ents_loc'),
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
            origin=options.get(Vec, 'global_pti_ents_loc'),
            targetname='@grating_filter',
            classname='filter_activator_class',
            negated=1,
            filterclass='prop_paint_bomb',
        )

    # Group the positions by planes in each orientation.
    # This makes them 2D grids which we can optimise.
    # (normal_dist, positive_axis, type) -> [(x, y)]
    slices: Dict[
        Tuple[Tuple[float, float, float], bool, BarrierType],
        Dict[Tuple[int, int], False]
    ] = defaultdict(dict)
    # We have this on the 32-grid so we can cut squares for holes.

    for (origin_tup, normal_tup), barr_type in BARRIERS.items():
        origin = Vec(origin_tup)
        normal = Vec(normal_tup)
        norm_axis = normal.axis()
        u, v = origin.other_axes(norm_axis)
        norm_pos = Vec.with_axes(norm_axis, origin)
        slice_plane = slices[
            norm_pos.as_tuple(),  # distance from origin to this plane.
            normal[norm_axis] > 0,
            barr_type,
        ]
        for u_off in [-48, -16, 16, 48]:
            for v_off in [-48, -16, 16, 48]:
                slice_plane[
                    int((u + u_off) // 32),
                    int((v + v_off) // 32),
                ] = True

    # Remove pane sections where the holes are. We then generate those with
    # templates for slanted parts.
    for (origin_tup, norm_tup), hole_type in HOLES.items():
        barr_type = BARRIERS[origin_tup, norm_tup]

        origin = Vec(origin_tup)
        normal = Vec(norm_tup)
        norm_axis = normal.axis()
        u, v = origin.other_axes(norm_axis)
        norm_pos = Vec.with_axes(norm_axis, origin)
        slice_plane = slices[
            norm_pos.as_tuple(),
            normal[norm_axis] > 0,
            barr_type,
        ]
        if hole_type is HoleType.LARGE:
            offsets = (-80, -48, -16, 16, 48, 80)
        else:
            offsets = (-16, 16)
        for u_off in offsets:
            for v_off in offsets:
                # Remove these squares, but keep them in the dict
                # so we can check if there was glass there.
                uv = (
                    int((u + u_off) // 32),
                    int((v + v_off) // 32),
                )
                if uv in slice_plane:
                    slice_plane[uv] = False
                # These have to be present, except for the corners
                # on the large hole.
                elif abs(u_off) != 80 or abs(v_off) != 80:
                    u_ax, v_ax = Vec.INV_AXIS[norm_axis]
                    LOGGER.warning(
                        'Hole tried to remove missing tile at ({})?',
                        Vec.with_axes(norm_axis, norm_pos, u_ax, u + u_off, v_ax, v + v_off),
                    )

        # Now generate the curved brushwork.

        if barr_type is BarrierType.GLASS:
            front_temp = glass_temp
        elif barr_type is BarrierType.GRATING:
            front_temp = grate_temp
        else:
            raise NotImplementedError

        angles = normal.to_angle()
        hole_temp: List[Tuple[List[Solid], Matrix]] = []

        # This is a tricky bit. Two large templates would collide
        # diagonally, and we allow the corner glass to not be present since
        # the hole doesn't actually use that 32x32 segment.
        # So we need to determine which of 3 templates to use.
        corn_angles = angles.copy()
        if hole_type is HoleType.LARGE:
            for corn_angles.roll in (0, 90, 180, 270):
                corn_mat = Matrix.from_angle(corn_angles)

                corn_dir = Vec(y=1, z=1) @ corn_angles
                hole_off = origin + 128 * corn_dir
                diag_type = HOLES.get(
                    (hole_off.as_tuple(), normal.as_tuple()),
                    None,
                )
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
                        hole_temp.append((hole_temp_lrg_diag, corn_mat))
                    continue
                if (corn_u, corn_v) in slice_plane:
                    hole_temp.append((hole_temp_lrg_square, corn_mat))
                else:
                    hole_temp.append((hole_temp_lrg_cutout, corn_mat))

        else:
            hole_temp.append((hole_temp_small, Matrix.from_angle(angles)))

        def solid_pane_func(off1: float, off2: float, mat: str) -> List[Solid]:
            """Given the two thicknesses, produce the curved hole from the template."""
            off_min = 64 - max(off1, off2)
            off_max = 64 - min(off1, off2)
            new_brushes = []
            for brushes, matrix in hole_temp:
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
            barr_type,
            front_temp,
            solid_pane_func,
        )

    for (plane_pos, is_pos, barr_type), pos_slice in slices.items():
        plane_pos = Vec(plane_pos)
        norm_axis = plane_pos.axis()
        normal = Vec.with_axes(norm_axis, 1 if is_pos else -1)

        if barr_type is BarrierType.GLASS:
            front_temp = glass_temp
        elif barr_type is BarrierType.GRATING:
            front_temp = grate_temp
        else:
            raise NotImplementedError

        u_axis, v_axis = Vec.INV_AXIS[norm_axis]

        for min_u, min_v, max_u, max_v in grid_optimise(pos_slice):
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

            def solid_pane_func(pos1: float, pos2: float, mat: str) -> List[Solid]:
                """Make the solid brush."""
                return [vmf.make_prism(
                    pos_min + normal * (64.0 - pos1),
                    pos_max + normal * (64.0 - pos2),
                    mat=mat,
                ).solid]

            make_glass_grating(
                vmf,
                (pos_min + pos_max)/2 + 63 * normal,
                normal,
                barr_type,
                front_temp,
                solid_pane_func,
            )
            # Generate hint brushes, to ensure sorting is done correctly.
            [hint] = solid_pane_func(0, 4.0, consts.Tools.SKIP)
            for side in hint:
                if abs(Vec.dot(side.normal(), normal)) > 0.99:
                    side.mat = consts.Tools.HINT
            vmf.add_brush(hint)

    if floorbeam_temp:
        LOGGER.info('Adding Glass floor beams...')
        add_glass_floorbeams(vmf, floorbeam_temp)
        LOGGER.info('Done!')


def make_glass_grating(
    vmf: VMF,
    ent_pos: Vec,
    normal: Vec,
    barr_type: BarrierType,
    front_temp: template_brush.ScalingTemplate,
    solid_func: Callable[[float, float, str], List[Solid]],
):
    """Make all the brushes needed for glass/grating.

    solid_func() is called with two offsets from the voxel edge, and returns a
    matching list of solids. This allows doing holes and normal panes with the
    same function.
    barrier_type is either 'glass' or 'grating'.
    """

    if barr_type is BarrierType.GLASS:
        main_ent = vmf.create_ent('func_detail')
        player_clip_mat = consts.Tools.PLAYER_CLIP_GLASS
        tex_cat = 'glass'
    else:
        player_clip_mat = consts.Tools.PLAYER_CLIP_GRATE
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
            front_temp.apply(face, change_mat=False)

    if normal.z == 0:
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

    player_clip.solids = solid_func(0, 4, player_clip_mat)

    if barr_type is BarrierType.GRATING:
        # Add the VPhysics clip.
        phys_clip = vmf.create_ent(
            'func_clip_vphysics',
            filtername='@grating_filter',
            origin=ent_pos,
            StartDisabled=0,
        )
        phys_clip.solids = solid_func(0, 2, consts.Tools.TRIGGER)


def add_glass_floorbeams(vmf: VMF, temp_name: str):
    """Add beams to separate large glass panels.

    The texture is assumed to match plasticwall004a's shape.
    """
    template = template_brush.get_template(temp_name)
    temp_world, temp_detail, temp_over = template.visgrouped()
    try:
        [beam_template] = temp_world + temp_detail  # type: Solid
    except ValueError:
        raise ValueError('Bad Glass Floorbeam template!')

    # Grab the 'end' side, which we move around.
    for side in beam_template.sides:
        if side.normal() == (-1, 0, 0):
            beam_end_face = side
            break
    else:
        raise ValueError('Not aligned to world...')

    separation = options.get(int, 'glass_floorbeam_sep') + 1
    separation *= 128

    # First we want to find all the groups of contiguous glass sections.
    # This is a mapping from some glass piece to its group list.
    groups = {}

    for (origin, normal), barr_type in BARRIERS.items():
        # Grating doesn't use it.
        if barr_type is not BarrierType.GLASS:
            continue

        normal = Vec(normal)

        if not normal.z:
            # Not walls.
            continue

        pos = Vec(origin) + normal * 62

        groups[pos.as_tuple()] = [pos]

    # Loop over every pos and check in the +x/y directions for another glass
    # piece. If there, merge the two lists and set every pos in the group to
    # point to the new list.
    # Once done, every unique list = a group.

    for pos_tup in groups.keys():
        pos = Vec(pos_tup)
        for off in ((128, 0, 0), (0, 128, 0)):
            neighbour = (pos + off).as_tuple()
            if neighbour in groups:
                our_group = groups[pos_tup]
                neigh_group = groups[neighbour]
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
                    groups[pos.as_tuple()] = large_group

    # Remove duplicates objects by using the ID as key..
    groups = list({
        id(group): group
        for group in groups.values()
    }.values())

    # Side -> u, v or None

    for group in groups:
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
                min_pos, max_pos = beams[side_off]
            except KeyError:
                beams[side_off] = beam_off, beam_off
            else:
                beams[side_off] = min(min_pos, beam_off), max(max_pos, beam_off)

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


def beam_hole_split(axis: str, min_pos: Vec, max_pos: Vec):
    """Break up floor beams to fit around holes."""

    # Go along the shape. For each point, check if a hole is present,
    # and split at that.
    # Our positions are centered, but we return ones at the ends.

    # Inset in 4 units from each end to not overlap with the frames.
    start_pos = min_pos - Vec.with_axes(axis, 60)
    if HOLES:
        hole_size_large = options.get(float, 'glass_hole_size_large') / 2
        hole_size_small = options.get(float, 'glass_hole_size_small') / 2

        # Extract normal from the z-axis.
        grid_height = min_pos.z // 128 * 128 + 64
        if grid_height < min_pos.z:
            normal = (0, 0, 1)
        else:
            normal = (0, 0, -1)
        for pos in min_pos.iter_line(max_pos, 128):
            try:
                hole_type = HOLES[(pos.x, pos.y, grid_height), normal]
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
