"""Implements Glass and Grating."""
from enum import Enum
from typing import Dict, Tuple, List, Set, Callable

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

    if test_hole_spot(normal, origin, hole_type):
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
        hole_temp = template_brush.get_template(
            vbsp_options.get(str, 'glass_hole_temp')
        )
        hole_world, hole_detail, _ = hole_temp.visgrouped({'small'})
        hole_temp_small = hole_world + hole_detail
        hole_world, hole_detail, _ = hole_temp.visgrouped({'large'})
        hole_temp_large = hole_world + hole_detail
    else:
        hole_temp_small = hole_temp_large = None

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

    # # This needs to be a func_brush, otherwise the clip texture data will be
    # # merged with other clips.
    # glass_clip_ent = vmf.create_ent(classname='func_brush', solidbsp=1)

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
            hole_temp = hole_temp_large
        else:
            offsets = (-16, 16)
            hole_temp = hole_temp_small
        for u_off in offsets:
            for v_off in offsets:
                slice_plane.remove((
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

        def solid_pane_func(off1, off2, mat):
            angles = normal.to_angle()
            off_min = min(off1, off2)
            off_max = max(off1, off2)
            new_brushes = [
                brush.copy(map=vmf)
                for brush in hole_temp
            ]
            for brush in new_brushes:
                for face in brush.sides:
                    face.mat = mat
                    f_norm = face.normal()
                    if f_norm.x == 1:
                        face.translate(Vec(x=4 - off_max))
                        # face.mat = 'min'
                    elif f_norm.x == -1:
                        face.translate(Vec(x=-4 - off_min))
                        # face.mat = 'max'
                    face.localise(origin, angles)
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
        add_glass_floorbeams(floorbeam_temp)
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


def add_glass_floorbeams(temp_name):
    """Add beams to separate large glass panels.

    The texture is assumed to match plasticwall004a's shape.
    """
    template = template_brush.get_template(temp_name)

    separation = vbsp_options.get(int, 'glass_floorbeam_sep') + 1
    separation *= 128

    # First we want to find all the groups of contiguous glass sections.
    # This is a mapping from some glass piece to its group list.
    groups = {}

    for origin, normal, barr_type in BARRIERS.items():
        if barr_type is not BarrierType.GLASS:
            continue

        pos = origin + normal * 62

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

        if dimensions.y > dimensions.x:
            axis = 'y'
            rot = Vec(0, 0, 0)
        else:
            axis = 'x'
            rot = Vec(0, 90, 0)

        # Add 128 so the first pos isn't a beam.
        offset = bbox_min[axis] + 128

        for pos in group:
            # Every 'sep' positions..
            if (pos[axis] - offset) % separation == 0:
                template_brush.import_template(
                    template,
                    pos,
                    rot,
                    force_type=template_brush.TEMP_TYPES.detail,
                    add_to_map=True,
                )
