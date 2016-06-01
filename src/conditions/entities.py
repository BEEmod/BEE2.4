"""Conditions related to specific kinds of entities."""
import random
from collections import defaultdict

import conditions
import utils
import vmfLib as VLib
from srctools import Property, Vec

from conditions import (
    make_result, make_result_setup,
    TEMP_TYPES, SOLIDS
)


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
def res_insert_overlay(inst: VLib.Entity, res: Property):
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
