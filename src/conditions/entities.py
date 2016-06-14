"""Conditions related to specific kinds of entities."""
import random
from collections import defaultdict

import conditions
import srctools
import utils
from conditions import (
    make_result, make_result_setup,
    TEMP_TYPES, SOLIDS
)
from srctools import Property, Vec, Entity


LOGGER = utils.getLogger(__name__, alias='cond.scaffold')


@make_result_setup('TemplateOverlay')
def res_import_template_setup(res):
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

    temp = conditions.import_template(
        temp_id,
        origin,
        angles,
        targetname=inst['targetname', ''],
        force_type=TEMP_TYPES.detail,
    )

    for over in temp.overlay:  # type: VLib.Entity
        random.seed('TEMP_OVERLAY_' + over['basisorigin'])
        mat = random.choice(replace.get(
            over['material'],
            (over['material'], ),
        ))
        if mat[:1] == '$':
            mat = inst.fixup[mat]
        over['material'] = mat
        over['sides'] = str(face_id)

    # Wipe the brushes from the map.
    if temp.detail is not None:
        temp.detail.remove()
        LOGGER.info(
            'Overlay template "{}" could set keep_brushes=0.',
            temp_id,
        )


@make_result_setup('WaterSplash')
def res_water_splash_setup(res: Property):
    parent = res['parent']
    name = res['name']
    scale = srctools.conv_float(res['scale', ''], 8.0)
    pos1 = Vec.from_str(res['position', ''])
    lin_off = res['door_dist', '']
    lin_angles = res['door_angles', '']
    pos2 = res['position2', '']

    if lin_angles and lin_off:
        pos2 = lin_angles
    else:
        lin_off = None

    return name, parent, scale, pos1, lin_off, pos2


@make_result('WaterSplash')
def res_water_splash(inst: Entity, res: Property):
    """Creates splashes when something goes in and out of water.

    Arguments:
        - parent: The name of the parent entity.
        - name: The name given to the env_splash.
        - scale: The size of the effect (8 by default).
        - position: The offset position to place the entity.
        - position2: The offset to which the entity will move. Set to
            '<piston_1/2/3/4>' to use $bottom_level and $top_level as offsets.
        - door_dist: Overrides position2 if set. The distance for a door/movelinear.
        - door_angles: required for door_dist. The absolute direction the door
          moves in.
    """
    (
        name,
        parent,
        scale,
        pos1,
        lin_off,
        pos2,
    ) = res.value  # type: str, str, float, Vec, Optional[str], str
    pos1 = pos1.copy()

    # Movelinear mode - offset by the given position and angles.
    if lin_off is not None:
        lin_off = srctools.conv_int(
            conditions.resolve_value(inst, lin_off),
            1
        )
        pos2 = Vec(x=lin_off).rotate_by_str(
            conditions.resolve_value(inst, pos2),
        )
        pos2 += pos1
    else:
        # Directly from the given value.
        pos2 = Vec.from_str(conditions.resolve_value(inst, pos2))

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])
    pos1.localise(origin, angles)
    pos2.localise(origin, angles)

    conditions.VMF.create_ent(
        classname='env_beam',
        targetname=conditions.local_name(inst, 'pos1'),
        origin=str(pos1),
        targetpoint=str(pos2),
    )

    # Since it's a straight line and you can't go through walls,
    # if pos1 and pos2 aren't in goo we aren't ever in goo.

    grid_pos1 = pos1 // 128 * 128  # type: Vec
    grid_pos1 += (64, 64, 64)
    grid_pos2 = pos2 // 128 * 128  # type: Vec
    grid_pos2 += (64, 64, 64)

    try:
        surf = conditions.GOO_LOCS[grid_pos1.as_tuple()]
    except KeyError:
        try:
            surf = conditions.GOO_LOCS[grid_pos2.as_tuple()]
        except KeyError:
            return
            # Not in goo at all

    if pos1.z == pos2.z:
        # Flat - this won't do anything...
        return

    water_pos = surf.get_origin()

    import vbsp

    conditions.VMF.create_ent(
        classname='env_splash',
        # Pass along the water_pos encoded into the targetname.
        targetname=conditions.local_name(inst, name + "_" + str(water_pos.z)),
        parentname=conditions.local_name(inst, parent),
        origin=pos1 + (0, 0, 16),
        scale=scale,
        vscripts='BEE2/water_splash.nut',
        thinkfunction='Think',
        spawnflags='1',  # Trace downward to water surface.
    )

    vbsp.PACK_FILES.add('scripts/vscripts/BEE2/water_splash.nut')