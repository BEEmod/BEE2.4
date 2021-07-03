"""Conditions related to specific kinds of entities."""
import random
from collections import defaultdict
from typing import List, Dict, Tuple

from srctools import Property, Vec, VMF, Entity, Angle
import srctools.logger

from precomp import tiling, texturing, template_brush, conditions
from precomp.brushLoc import POS as BLOCK_POS
from precomp.conditions import make_result, make_result_setup
from precomp.template_brush import TEMP_TYPES

COND_MOD_NAME = 'Entities'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.entities')


@make_result('TemplateOverlay')
def res_insert_overlay(vmf: VMF, res: Property):
    """Use a template to insert one or more overlays on a surface.

    Options:

    - ID: The template ID. Brushes will be ignored.
    - Replace: old -> new material replacements.
    - Face_pos: The offset of the brush face.
    - Normal: The direction of the brush face.
    - Offset: An offset to move the overlays by.
    """
    orig_temp_id = res['id'].casefold()

    face_str = res['face_pos', '0 0 -64']
    orig_norm = Vec.from_str(res['normal', '0 0 1'])

    replace_tex: dict[str, list[str]] = {}
    for prop in res.find_key('replace', []):
        replace_tex.setdefault(prop.name.replace('\\', '/'), []).append(prop.value)

    offset = Vec.from_str(res['offset', '0 0 0'])

    def insert_over(inst: Entity) -> None:
        """Apply the result."""
        temp_id = inst.fixup.substitute(orig_temp_id)

        origin = Vec.from_str(inst['origin'])
        angles = Angle.from_str(inst['angles', '0 0 0'])

        face_pos = conditions.resolve_offset(inst, face_str)
        normal = orig_norm @ angles

        # Don't make offset change the face_pos value..
        origin += offset @ angles

        for axis, norm in enumerate(normal):
            # Align to the center of the block grid. The normal direction is
            # already correct.
            if norm == 0:
                face_pos[axis] = face_pos[axis] // 128 * 128 + 64

        # Shift so that the user perceives the position as the pos of the face
        # itself.
        face_pos -= 64 * normal

        try:
            tiledef = tiling.TILES[face_pos.as_tuple(), normal.as_tuple()]
        except KeyError:
            LOGGER.warning(
                'Overlay brush position is not valid: {}',
                face_pos,
            )
            return

        temp = template_brush.import_template(
            vmf,
            temp_id,
            origin,
            angles,
            targetname=inst['targetname', ''],
            force_type=TEMP_TYPES.detail,
        )

        for over in temp.overlay:  # type: Entity
            random.seed('TEMP_OVERLAY_' + over['basisorigin'])
            mat = over['material']
            try:
                mat = random.choice(replace_tex[mat.casefold().replace('\\', '/')])
            except KeyError:
                pass

            if mat[:1] == '$':
                mat = inst.fixup[mat]
            if mat.startswith('<') or mat.endswith('>'):
                # Lookup in the texture data.
                gen, mat = texturing.parse_name(mat[1:-1])
                mat = gen.get(Vec.from_str(over['basisorigin']), mat)
            over['material'] = mat
            tiledef.bind_overlay(over)

        # Wipe the brushes from the map.
        if temp.detail is not None:
            temp.detail.remove()
            LOGGER.info(
                'Overlay template "{}" could set keep_brushes=0.',
                temp_id,
            )
    return insert_over


@make_result('createEntity')
def res_create_entity(vmf: VMF, inst: Entity, res: Property):
    """Create an entity.

    * `keys` and `localkeys` defines the new keyvalues used.
    * `origin` and `angles` are local to the instance.
    """

    origin = Vec.from_str(inst['origin'])
    orient = Angle.from_str(inst['angles'])

    new_ent = vmf.create_ent(
        # Ensure there's these critical values.
        classname='info_null',
        origin='0 0 0',
        angles='0 0 0',
    )

    conditions.set_ent_keys(new_ent, inst, res)

    new_ent['origin'] = Vec.from_str(new_ent['origin']) @ orient + origin
    new_ent['angles'] = Angle.from_str(new_ent['angles']) @ orient


@make_result_setup('WaterSplash')
def res_water_splash_setup(res: Property):
    parent = res['parent']
    name = res['name']
    scale = srctools.conv_float(res['scale', ''], 8.0)
    pos1 = Vec.from_str(res['position', ''])
    calc_type = res['type', '']
    pos2 = res['position2', '']
    fast_check = srctools.conv_bool(res['fast_check', ''])

    return name, parent, scale, pos1, pos2, calc_type, fast_check


@make_result('WaterSplash')
def res_water_splash(vmf: VMF, inst: Entity, res: Property) -> None:
    """Creates splashes when something goes in and out of water.

    Arguments:

    - `parent`: The name of the parent entity.
    - `name`: The name given to the env_splash.
    - `scale`: The size of the effect (8 by default).
    - `position`: The offset position to place the entity.
    - `position2`: The offset to which the entity will move.
    - `type`: Use certain fixup values to calculate pos2 instead:
       `piston_1`/`2`/`3`/`4`: Use `$bottom_level` and `$top_level` as offsets.
       `track_platform`: Use `$travel_direction`, `$travel_distance`, etc.
    - `fast_check`: Check faster for movement. Needed for items which
      move quickly.
    """
    (
        name,
        parent,
        scale,
        pos1,
        pos2,
        calc_type,
        fast_check,
    ) = res.value  # type: str, str, float, Vec, Vec, str, str

    pos1 = pos1.copy()
    splash_pos = pos1.copy()

    if calc_type == 'track_platform':
        lin_off = srctools.conv_int(inst.fixup['$travel_distance'])
        travel_ang = inst.fixup['$travel_direction']
        start_pos = srctools.conv_float(inst.fixup['$starting_position'])
        if start_pos:
            start_pos = round(start_pos * lin_off)
            pos1 += Vec(x=-start_pos).rotate_by_str(travel_ang)

        pos2 = Vec(x=lin_off).rotate_by_str(travel_ang)
        pos2 += pos1
    elif calc_type.startswith('piston'):
        # Use piston-platform offsetting.
        # The number is the highest offset to move to.
        max_pist = srctools.conv_int(calc_type.split('_', 2)[1], 4)
        bottom_pos = srctools.conv_int(inst.fixup['$bottom_level'])
        top_pos = min(srctools.conv_int(inst.fixup['$top_level']), max_pist)

        pos2 = pos1.copy()
        pos1 += Vec(z=128 * bottom_pos)
        pos2 += Vec(z=128 * top_pos)
        LOGGER.info('Bottom: {}, top: {}', bottom_pos, top_pos)
    else:
        # Directly from the given value.
        pos2 = Vec.from_str(conditions.resolve_value(inst, pos2))

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])
    splash_pos.localise(origin, angles)
    pos1.localise(origin, angles)
    pos2.localise(origin, angles)

    # Since it's a straight line and you can't go through walls,
    # if pos1 and pos2 aren't in goo we aren't ever in goo.

    check_pos = [pos1, pos2]

    if pos1.z < origin.z:
        # If embedding in the floor, the positions can both be below the
        # actual surface. In that case check the origin too.
        check_pos.append(Vec(pos1.x, pos1.y, origin.z))

    if pos1.z == pos2.z:
        # Flat - this won't do anything...
        return

    for pos in check_pos:
        grid_pos = pos // 128 * 128
        grid_pos += (64, 64, 64)

        block = BLOCK_POS['world': pos]
        if block.is_goo:
            break
    else:
        return  # Not in goo at all

    water_pos = grid_pos + (0, 0, 32)

    # Check if both positions are above or below the water..
    # that means it won't ever trigger.
    if max(pos1.z, pos2.z) < water_pos.z - 8:
        return
    if min(pos1.z, pos2.z) > water_pos.z + 8:
        return

    # Pass along the water_pos encoded into the targetname.
    # Restrict the number of characters to allow direct slicing
    # in the script.
    enc_data = '_{:09.3f}{}'.format(
        water_pos.z + 12,
        'f' if fast_check else 's',
    )

    vmf.create_ent(
        classname='env_splash',
        targetname=conditions.local_name(inst, name) + enc_data,
        parentname=conditions.local_name(inst, parent),
        origin=splash_pos + (0, 0, 16),
        scale=scale,
        vscripts='BEE2/water_splash.nut',
        thinkfunction='Think',
        spawnflags='1',  # Trace downward to water surface.
    )


@make_result('FunnelLight')
def res_make_funnel_light(inst: Entity) -> None:
    """Place a light for Funnel items."""
    oran_on = inst.fixup.bool('$start_reversed')
    need_blue = need_oran = False
    name = ''
    if inst.fixup['$connectioncount_polarity'] != '0':
        import vbsp
        if not vbsp.settings['style_vars']['funnelallowswitchedlights']:
            # Allow disabling adding switchable lights.
            return
        name = conditions.local_name(inst, 'light')
        need_blue = need_oran = True
    else:
        if oran_on:
            need_oran = True
        else:
            need_blue = True

    loc = Vec(0, 0, -56)
    loc.localise(Vec.from_str(inst['origin']), Vec.from_str(inst['angles']))

    if need_blue:
        inst.map.create_ent(
            classname='light',
            targetname=name + '_b' if name else '',
            spawnflags=int(oran_on),  # 1 = Initially Dark
            origin=loc,
            _light='50 120 250 50',
            _lightHDR='-1 -1 -1 1',
            _lightscaleHDR=2,
            _fifty_percent_distance=48,
            _zero_percent_distance=96,
            _hardfalloff=1,
            _distance=0,
            style=0,
        )
    if need_oran:
        inst.map.create_ent(
            classname='light',
            targetname=name + '_o' if name else '',
            spawnflags=int(not oran_on),
            origin=loc,
            _light='250 120 50 50',
            _lightHDR='-1 -1 -1 1',
            _lightscaleHDR=2,
            _fifty_percent_distance=48,
            _zero_percent_distance=96,
            _hardfalloff=1,
            _distance=0,
            style=0,
        )
