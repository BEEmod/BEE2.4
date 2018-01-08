"""Implements Glass and Grating."""
from enum import Enum
from typing import Dict, Tuple, List, Set, Callable

from collections import defaultdict

from grid_optim import optimise as grid_optimise
import template_brush
import vbsp_options
from srctools import VMF, Vec, Solid, Side
import utils
import comp_consts as consts
from instanceLocs import resolve_one, resolve as resolve_inst

LOGGER = utils.getLogger(__name__)


class BarrierType(Enum):
    """Type of barrier."""
    GLASS = 'glass'
    GRATING = 'grating'
    BLACK_WALL = 'black_wall'
    WHITE_WALL = 'white_wall'

# (origin, normal) -> BarrierType
BARRIERS = {}  # type: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], BarrierType]


def get_pos_norm(origin: Vec):
    """From the origin, get the grid position and normal."""
    grid_pos = origin // 128 * 128 + (64, 64, 64)
    return grid_pos.as_tuple(), (origin - grid_pos).norm().as_tuple()


def parse_map(vmf: VMF, has_attr: Dict[str, bool], pack_list: Set[str]):
    """Remove instances from the map, and store off the positions."""
    glass_inst = resolve_one('[glass_128]')
    # wall_inst = resolve_inst('<ITEM_BEE2_QUART_WALL>')

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


def make_barriers(vmf: VMF, get_tex: Callable[[str], str]):
    """Make barrier entities. get_tex is vbsp.get_tex."""
    glass_temp = template_brush.get_scaling_template(
        vbsp_options.get(str, "glass_template")
    )
    grate_temp = template_brush.get_scaling_template(
        vbsp_options.get(str, "grating_template")
    )

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
    slices = defaultdict(list)  # type: Dict[Tuple[Tuple[float, float, float], bool, BarrierType], List[Tuple[int, int]]]

    for (origin, normal), barr_type in BARRIERS.items():
        origin = Vec(origin)
        normal = Vec(normal)
        norm_axis = normal.axis()
        u, v = origin.other_axes(norm_axis)
        norm_pos = Vec.with_axes(norm_axis, origin)
        slices[
            norm_pos.as_tuple(),  # distance from origin to this plane.
            normal[norm_axis] > 0,
            barr_type,
        ].append((u // 128, v // 128))

    for (plane_pos, is_pos, barr_type), pos_slice in slices.items():
        plane_pos = Vec(plane_pos)
        norm_axis = plane_pos.axis()
        normal = Vec.with_axes(norm_axis, 1 if is_pos else -1)

        if barr_type is BarrierType.GLASS:
            front_temp = glass_temp
            front_mat = get_tex('special.glass')
            player_clip_mat = consts.Tools.PLAYER_CLIP_GLASS
        elif barr_type is BarrierType.GRATING:
            front_temp = grate_temp
            front_mat = get_tex('special.grating')
            player_clip_mat = consts.Tools.PLAYER_CLIP_GRATE
        else:
            raise NotImplementedError

        u_axis, v_axis = Vec.INV_AXIS[norm_axis]
        for min_u, min_v, max_u, max_v in grid_optimise(dict.fromkeys(pos_slice, True)):
            # These are two points in the origin plane, at the borders.
            pos_min = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, min_u * 128,
                v_axis, min_v * 128,
            )
            pos_max = Vec.with_axes(
                norm_axis, plane_pos,
                u_axis, max_u * 128 + 128,
                v_axis, max_v * 128 + 128,
            )

            # The actual glass/grating brush - 0.5-1 units back from the surface.
            solid = vmf.make_prism(
                pos_min + normal * 63,
                pos_max + normal * 63.5,
                mat=consts.Tools.NODRAW,
            ).solid

            set_frontback_tex(solid, normal, front_mat, front_temp)

            if barr_type is BarrierType.GLASS:
                main_ent = vmf.create_ent('func_detail')
            else:
                main_ent = vmf.create_ent(
                    'func_brush',
                    renderfx=14,  # Constant Glow
                    solidity=1,   # Never solid
                )
            main_ent.solids.append(solid)

            if normal.z == 0:
                # If vertical, we don't care about footsteps.
                # So just use 'normal' clips.
                player_clip = vmf.create_ent('func_detail')
                player_clip_mat = consts.Tools.PLAYER_CLIP
            else:
                player_clip = vmf.create_ent(
                    'func_brush',
                    solidbsp=1,
                    origin=pos_min,
                )
                # We also need a func_detail clip, which functions on portals.
                # Make it thinner, so it doesn't impact footsteps.
                player_thin_clip = vmf.create_ent('func_detail')
                bbox_min, bbox_max = Vec.bbox(
                    pos_min + normal * 60,
                    pos_max + normal * 64,
                )
                player_thin_clip.solids.append(vmf.make_prism(
                    bbox_min + 0.5, bbox_max - 0.5,
                    mat=consts.Tools.PLAYER_CLIP,
                ).solid)
            player_clip.solids.append(vmf.make_prism(
                pos_min + normal * 60,
                pos_max + normal * 64,
                mat=player_clip_mat,
            ).solid)

            if barr_type is BarrierType.GRATING:
                # Add the VPhysics clip.
                phys_clip = vmf.create_ent(
                    'func_clip_vphysics',
                    filtername='@grating_filter',
                    origin=pos_min,
                    StartDisabled=0,
                )
                phys_clip.solids.append(vmf.make_prism(
                    pos_min + normal * 62,
                    pos_max + normal * 64,
                    mat=consts.Tools.TRIGGER,
                ).solid)

    if floorbeam_temp:
        LOGGER.info('Adding Glass floor beams...')
        add_glass_floorbeams(floorbeam_temp)
        LOGGER.info('Done!')


def set_frontback_tex(
    brush: Solid,
    normal: Vec,
    mat: str,
    temp: template_brush.ScalingTemplate=None,
):
    """Apply textures to the front and back of a brush."""
    normal = abs(normal)

    for face in brush.sides:
        f_normal = face.normal()
        if abs(f_normal) == normal:
            face.mat = mat
            if temp is not None:
                temp.apply(face, change_mat=False)


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
