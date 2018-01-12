"""Implements Glass and Grating."""
from enum import Enum
from typing import Dict, Tuple, List, Set, Callable, Iterable

from collections import defaultdict

from grid_optim import optimise as grid_optimise
import template_brush
import vbsp_options
from srctools import VMF, Vec, Solid, Side, Property, Entity
import utils
import comp_consts as consts
from instanceLocs import resolve_one
from conditions import make_result

LOGGER = utils.getLogger(__name__)


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
BARRIERS = {}  # type: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], BarrierType]

HOLES = {}  # type: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], HoleType]


def get_pos_norm(origin: Vec):
    """From the origin, get the grid position and normal."""
    grid_pos = origin // 128 * 128 + (64, 64, 64)
    return grid_pos.as_tuple(), (origin - grid_pos).norm().as_tuple()


def parse_map(vmf: VMF, has_attr: Dict[str, bool], pack_list: Set[str]):
    """Remove instances from the map, and store off the positions."""
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

    if vbsp_options.get(str, 'glass_pack') and has_attr['glass']:
        pack_list.add(vbsp_options.get(str, 'glass_pack').casefold())


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

    normal = Vec(z=-1).rotate_by_str(inst['angles'])
    origin = Vec.from_str(inst['origin']) // 128 * 128 + 64

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


def make_barriers(vmf: VMF, get_tex: Callable[[str], str]):
    """Make barrier entities. get_tex is vbsp.get_tex."""
    glass_temp = template_brush.get_scaling_template(
        vbsp_options.get(str, "glass_template")
    )
    grate_temp = template_brush.get_scaling_template(
        vbsp_options.get(str, "grating_template")
    )
    # Avoid error without this package.
    if HOLES:
        # Grab the template solids we need.
        hole_temp = template_brush.get_template(
            vbsp_options.get(str, 'glass_hole_temp')
        )
        hole_world, hole_detail, _ = hole_temp.visgrouped({'small'})
        hole_temp_small = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_temp.visgrouped({'large'})
        hole_temp_large = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_temp.visgrouped({'large_corner'})
        hole_temp_corner = hole_world + hole_detail
    else:
        hole_temp_small = hole_temp_large = hole_temp_corner = None

    floorbeam_temp = vbsp_options.get(str, 'glass_floorbeam_temp')

    if vbsp_options.get_itemconf('BEE_PELLET:PelletGrating', False):
        # Merge together these existing filters in global_pti_ents
        vmf.create_ent(
            origin=vbsp_options.get(Vec, 'global_pti_ents_loc'),
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
            origin=vbsp_options.get(Vec, 'global_pti_ents_loc'),
            targetname='@grating_filter',
            classname='filter_activator_class',
            negated=1,
            filterclass='prop_paint_bomb',
        )

    # Group the positions by planes in each orientation.
    # This makes them 2D grids which we can optimise.
    # (normal_dist, positive_axis, type) -> [(x, y)]
    slices = defaultdict(set)  # type: Dict[Tuple[Tuple[float, float, float], bool, BarrierType], Set[Tuple[float, float]]]
    # We have this on the 32-grid so we can cut squares for holes.

    for (origin, normal), barr_type in BARRIERS.items():
        origin = Vec(origin)
        normal = Vec(normal)
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
                slice_plane.add((
                    (u + u_off) // 32,
                    (v + v_off) // 32,
                ))

    # Remove pane sections where the holes are. We then generate those with
    # templates for slanted parts.
    for (origin, normal), hole_type in HOLES.items():
        barr_type = BARRIERS[origin, normal]

        origin = Vec(origin)
        normal = Vec(normal)
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
            hole_temp = hole_temp_large.copy()
        else:
            offsets = (-16, 16)
            hole_temp = hole_temp_small.copy()
        for u_off in offsets:
            for v_off in offsets:
                # Skip the corners on large holes.
                # Those aren't actually used, so skip them. That way
                # we can have them diagonally or  without glass in the corner.
                if u_off in (-80, 80) and v_off in (-80, 80):
                    continue

                slice_plane.discard((
                    (u + u_off) // 32,
                    (v + v_off) // 32,
                ))

        # Now generate the curved brushwork.

        if barr_type is BarrierType.GLASS:
            front_temp = glass_temp
            front_mat = get_tex('special.glass')
        elif barr_type is BarrierType.GRATING:
            front_temp = grate_temp
            front_mat = get_tex('special.grating')
        else:
            raise NotImplementedError

        angles = normal.to_angle(0)
        # Angle corresponding to the brush, for the corners.
        angle_list = [angles] * len(hole_temp)

        # This is a tricky bit. Two large templates would collide
        # diagonally,
        # so chop off the corners, then put them back only if there's not
        # one diagonally.
        if hole_type is HoleType.LARGE:
            for roll in (0, 90, 180, 270):
                corn_angles = angles.copy()
                corn_angles.z = roll
                hole_off = origin + Vec(y=128, z=128).rotate(*corn_angles)
                diag_type = HOLES.get(
                    (hole_off.as_tuple(), normal.as_tuple()),
                    None,
                )
                if diag_type is not HoleType.LARGE:
                    hole_temp += hole_temp_corner
                    angle_list += [corn_angles] * len(hole_temp_corner)

        def solid_pane_func(off1, off2, mat):
            """Given the two thicknesses, produce the curved hole from the template."""
            off_min = min(off1, off2)
            off_max = max(off1, off2)
            new_brushes = [
                brush.copy(map=vmf)
                for brush in hole_temp
            ]

            for brush, br_angles in zip(new_brushes, angle_list):
                for face in brush.sides:
                    face.mat = mat
                    f_norm = face.normal()
                    if f_norm.x == 1:
                        face.translate(Vec(x=4 - off_max))
                        # face.mat = 'min'
                    elif f_norm.x == -1:
                        face.translate(Vec(x=-4 - off_min))
                        # face.mat = 'max'
                    face.localise(origin, br_angles)
            return new_brushes

        make_glass_grating(
            vmf,
            origin,
            normal,
            barr_type,
            front_temp,
            front_mat,
            solid_pane_func,
        )

    for (plane_pos, is_pos, barr_type), pos_slice in slices.items():
        plane_pos = Vec(plane_pos)
        norm_axis = plane_pos.axis()
        normal = Vec.with_axes(norm_axis, 1 if is_pos else -1)

        if barr_type is BarrierType.GLASS:
            front_temp = glass_temp
            front_mat = get_tex('special.glass')
        elif barr_type is BarrierType.GRATING:
            front_temp = grate_temp
            front_mat = get_tex('special.grating')
        else:
            raise NotImplementedError

        u_axis, v_axis = Vec.INV_AXIS[norm_axis]

        for min_u, min_v, max_u, max_v in grid_optimise(dict.fromkeys(pos_slice, True)):
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

            def solid_pane_func(pos1, pos2, mat):
                """Make the solid brush."""
                return [vmf.make_prism(
                    pos_min + normal * (64.0 - pos1),
                    pos_max + normal * (64.0 - pos2),
                    mat=mat,
                ).solid]

            make_glass_grating(
                vmf,
                (pos_min + pos_max)/2,
                normal,
                barr_type,
                front_temp,
                front_mat,
                solid_pane_func,
            )

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
    front_mat: str,
    solid_func: Callable[[float, float, str], List[Solid]],
):
    """Make all the brushes needed for glass/grating.

    solid_func() is called with two offsets from the voxel edge, and returns a
    matching list of solids. This allows doing holes and normal panes with the
    same function.
    """

    if barr_type is BarrierType.GLASS:
        main_ent = vmf.create_ent('func_detail')
        player_clip_mat = consts.Tools.PLAYER_CLIP_GLASS
    else:
        player_clip_mat = consts.Tools.PLAYER_CLIP_GRATE
        main_ent = vmf.create_ent(
            'func_brush',
            renderfx=14,  # Constant Glow
            solidity=1,  # Never solid
        )
    # The actual glass/grating brush - 0.5-1 units back from the surface.
    main_ent.solids = solid_func(0.5, 1, consts.Tools.NODRAW)

    abs_norm = abs(normal)
    for face in main_ent.sides():
        f_normal = face.normal()
        if abs(f_normal) == abs_norm:
            face.mat = front_mat
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

    separation = vbsp_options.get(int, 'glass_floorbeam_sep') + 1
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

                # Now merge the two lists. We then need to update all dict locs
                # to point to the new list.

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
        LOGGER.info('Size = {}', dimensions)

        # Our beams align to the smallest axis.
        if dimensions.y > dimensions.x:
            beam_ax = 'x'
            side_ax = 'y'
            rot = Vec(0, 0, 0)
        else:
            beam_ax = 'y'
            side_ax = 'x'
            rot = Vec(0, 90, 0)

        # Build min, max tuples for each axis in the other direction.
        # This tells us where the beams will be.
        beams = {}  # type: Dict[int, Tuple[int, int]]

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

                new_beam = beam_template.copy(map=vmf)
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
        hole_size_large = vbsp_options.get(float, 'glass_hole_size_large') / 2
        hole_size_small = vbsp_options.get(float, 'glass_hole_size_small') / 2

        # Extract normal from the z-axis.
        grid_height = min_pos.z // 128 * 128 + 64
        if grid_height < min_pos.z:
            normal = (0, 0, 1)
        else:
            normal = (0, 0, -1)
        import vbsp
        for pos in min_pos.iter_line(max_pos, 128):
            vbsp.VMF.create_ent(
                'info_particle_system',
                origin=Vec(pos.x, pos.y, grid_height),
                angles=Vec(normal).to_angle(),
            )
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
