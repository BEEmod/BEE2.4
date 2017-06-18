"""Conditions related to specific kinds of entities."""
import random
from collections import defaultdict

import conditions
import srctools
import template_brush
import utils
from conditions import (
    make_result, make_result_setup,
    SOLIDS
)
from template_brush import TEMP_TYPES
from srctools import Property, Vec, VMF, Entity

COND_MOD_NAME = 'Entities'

LOGGER = utils.getLogger(__name__, alias='cond.entities')


@make_result_setup('TemplateOverlay')
def res_import_template_setup(res: Property):
    temp_id = res['id'].casefold()

    face = Vec.from_str(res['face_pos', '0 0 -64'])
    norm = Vec.from_str(res['normal', '0 0 1'])

    replace_tex = defaultdict(list)
    for prop in res.find_key('replace', []):
        replace_tex[prop.name].append(prop.value)

    offset = Vec.from_str(res['offset', '0 0 0'])

    return (
        temp_id,
        dict(replace_tex),
        face,
        norm,
        offset,
    )


@make_result('TemplateOverlay')
def res_insert_overlay(inst: Entity, res: Property):
    """Use a template to insert one or more overlays on a surface.

    Options:
        - ID: The template ID. Brushes will be ignored.
        - Replace: old -> new material replacements
        - Face_pos: The offset of the brush face.
        - Normal: The direction of the brush face.
        - Offset: An offset to move the overlays by.
    """
    (
        temp_id,
        replace,
        face,
        norm,
        offset,
    ) = res.value

    if temp_id[:1] == '$':
        temp_id = inst.fixup[temp_id]

    origin = Vec.from_str(inst['origin'])  # type: Vec
    angles = Vec.from_str(inst['angles', '0 0 0'])

    face_pos = Vec(face).rotate(*angles)
    face_pos += origin
    normal = Vec(norm).rotate(*angles)

    # Don't make offset change the face_pos value..
    origin += offset.copy().rotate_by_str(
        inst['angles', '0 0 0']
    )

    for axis, norm in enumerate(normal):
        # Align to the center of the block grid. The normal direction is
        # already correct.
        if norm == 0:
            face_pos[axis] = face_pos[axis] // 128 * 128 + 64

    try:
        face_id = SOLIDS[face_pos.as_tuple()].face.id
    except KeyError:
        LOGGER.warning(
            'Overlay brush position is not valid: {}',
            face_pos,
        )
        return

    temp = template_brush.import_template(
        temp_id,
        origin,
        angles,
        targetname=inst['targetname', ''],
        force_type=TEMP_TYPES.detail,
    )

    for over in temp.overlay:  # type: Entity
        random.seed('TEMP_OVERLAY_' + over['basisorigin'])
        mat = random.choice(replace.get(
            over['material'],
            (over['material'], ),
        ))
        if mat[:1] == '$':
            mat = inst.fixup[mat]
        if mat.startswith('<') or mat.endswith('>'):
            # Lookup in the style data.
            import vbsp
            LOGGER.info('Tex: {}', vbsp.settings['textures'].keys())
            mat = vbsp.get_tex(mat[1:-1])
        over['material'] = mat
        over['sides'] = str(face_id)

    # Wipe the brushes from the map.
    if temp.detail is not None:
        temp.detail.remove()
        LOGGER.info(
            'Overlay template "{}" could set keep_brushes=0.',
            temp_id,
        )


@make_result('createEntity')
def res_create_entity(vmf: VMF, inst: Entity, res: Property):
    """Create an entity.

    'keys' and 'localkeys' defines the new keyvalues used.
    'Origin' will be used to offset the given amount from the current location.
    """

    origin = Vec.from_str(inst['origin'])

    new_ent = vmf.create_ent(
        # Ensure there's a classname, just in case.
        classname='info_null'
    )

    conditions.set_ent_keys(new_ent, inst, res)

    origin += Vec.from_str(new_ent['origin']).rotate_by_str(inst['angles'])

    new_ent['origin'] = origin
    new_ent['angles'] = inst['angles']


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
def res_water_splash(inst: Entity, res: Property):
    """Creates splashes when something goes in and out of water.

    Arguments:
        - parent: The name of the parent entity.
        - name: The name given to the env_splash.
        - scale: The size of the effect (8 by default).
        - position: The offset position to place the entity.
        - position2: The offset to which the entity will move.
        - type: Use certain fixup values to calculate pos2 instead:
           'piston_1/2/3/4': Use $bottom_level and $top_level as offsets.
           'track_platform': Use $travel_direction, $travel_distance, etc.
        - fast_check: Check faster for movement. Needed for items which
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
    ) = res.value  # type: str, str, float, Vec, str, str

    pos1 = pos1.copy()  # type: Vec
    splash_pos = pos1.copy()  # type: Vec

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

    conditions.VMF.create_ent(
        classname='env_beam',
        targetname=conditions.local_name(inst, name + '_pos'),
        origin=str(pos1),
        targetpoint=str(pos2),
    )

    # Since it's a straight line and you can't go through walls,
    # if pos1 and pos2 aren't in goo we aren't ever in goo.

    check_pos = [pos1, pos2]

    if pos1.z < origin.z:
        # If embedding in the floor, the positions can both be below the
        # actual surface. In that case check the origin too.
        check_pos.append(Vec(pos1.x, pos1.y, origin.z))

    for pos in check_pos:
        grid_pos = pos // 128 * 128  # type: Vec
        grid_pos += (64, 64, 64)
        try:
            surf = conditions.GOO_LOCS[grid_pos.as_tuple()]
        except KeyError:
            continue
        break
    else:
        return  # Not in goo at all

    if pos1.z == pos2.z:
        # Flat - this won't do anything...
        return

    water_pos = surf.get_origin()

    # Check if both positions are above or below the water..
    # that means it won't ever trigger.
    LOGGER.info('pos1: {}, pos2: {}, water_pos: {}', pos1.z, pos2.z, water_pos.z)
    if max(pos1.z, pos2.z) < water_pos.z - 8:
        return
    if min(pos1.z, pos2.z) > water_pos.z + 8:
        return

    import vbsp

    # Pass along the water_pos encoded into the targetname.
    # Restrict the number of characters to allow direct slicing
    # in the script.
    enc_data = '_{:09.3f}{}'.format(
        water_pos.z + 12,
        'f' if fast_check else 's',
    )

    conditions.VMF.create_ent(
        classname='env_splash',
        targetname=conditions.local_name(inst, name) + enc_data,
        parentname=conditions.local_name(inst, parent),
        origin=splash_pos + (0, 0, 16),
        scale=scale,
        vscripts='BEE2/water_splash.nut',
        thinkfunction='Think',
        spawnflags='1',  # Trace downward to water surface.
    )

    vbsp.PACK_FILES.add('scripts/vscripts/BEE2/water_splash.nut')


@make_result('FunnelLight')
def res_make_funnel_light(inst: Entity):
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
