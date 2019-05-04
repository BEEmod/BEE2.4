from typing import Tuple, Dict, Optional, Iterable, List
from enum import Enum

import conditions
import srctools.logger
import vbsp
import template_brush
from srctools import Property, Entity, VMF, Vec, NoKeyError
from srctools.vmf import make_overlay, Side
import comp_consts as const

COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.sendtor')


class SignType(Enum):
    """Types of signage placement."""
    DEFAULT = SQUARE = 'square'  # 1:1 size
    TALL = 'tall'  # Half-wide
    WIDE = 'wide'  # Half-height

SIZES: Dict[SignType, Tuple[int, int]] = {
    SignType.DEFAULT: (32, 32),
    SignType.TALL: (16, 32),
    SignType.WIDE: (32, 16),
}


class Sign:
    """A sign that can be placed."""
    def __init__(
        self,
        world: str,
        overlay: str,
        sign_type: SignType=SignType.DEFAULT,
    ) -> None:
        self.world = world
        self.overlay = overlay
        self.primary: Optional['Sign'] = None
        self.secondary: Optional['Sign'] = None
        self.type = sign_type

    @classmethod
    def parse(cls, prop: Property) -> 'Sign':
        return cls(
            prop['world', ''],
            prop['overlay', ''],
            SignType(prop['type', 'square']),
        )


SIGNAGES: Dict[str, Sign] = {}

# Special connection signage type.
CONN_SIGNAGES: Dict[str, Sign] = {
    str(time): Sign('', f'<overlay.{sign}>')
    for time, sign in
    zip(range(3, 31), [
        'square',
        'cross',
        'dot',
        'moon',
        'slash',
        'triangle',
        'sine',
        'star',
        'circle',
        'wavy',
    ])
}


def load_signs(conf: Property) -> None:
    """Load in the signage data."""
    for prop in conf.find_children('Signage'):
        SIGNAGES[prop.name] = sign = Sign.parse(prop)
        try:
            prim = prop.find_key('primary')
        except NoKeyError:
            pass
        else:
            sign.primary = Sign.parse(prim)
        try:
            sec = prop.find_key('secondary')
        except NoKeyError:
            pass
        else:
            sign.secondary = Sign.parse(sec)
    if 'arrow' not in SIGNAGES:
        LOGGER.warning('No ARROW signage type!')


@conditions.make_result('SignageItem')
def res_signage(vmf: VMF, inst: Entity, res: Property):
    """Implement the Signage item."""
    sign: Optional[Sign]
    try:
        sign = (
            CONN_SIGNAGES if
            res.bool('connection')
            else SIGNAGES
        )[inst.fixup[const.FixupVars.TIM_DELAY]]
    except KeyError:
        # Blank sign
        sign = None

    has_arrow = inst.fixup.bool(const.FixupVars.ST_ENABLED)

    sign_prim: Optional[Sign]
    sign_sec: Optional[Sign]

    if has_arrow:
        sign_prim = sign
        sign_sec = SIGNAGES['arrow']
    elif sign is not None:
        sign_prim = sign.primary or sign
        sign_sec = sign.secondary or None
    else:
        # Neither sign or arrow, delete this.
        inst.remove()
        return

    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])

    normal = Vec(z=-1).rotate(*angles)
    forward = Vec(x=-1).rotate(*angles)

    prim_pos = Vec(0, -16, -64)
    sec_pos = Vec(0, 16, -64)

    prim_pos.localise(origin, angles)
    sec_pos.localise(origin, angles)

    template_id = res['template_id', '']

    face: Side

    if template_id:
        brush_faces: List[Side] = []
        if sign_prim and sign_sec:
            visgroup = ['primary', 'secondary']
        elif sign_prim:
            visgroup = ['primary']
        else:
            visgroup = ['secondary']
        template = template_brush.import_template(
            template_id,
            origin,
            angles,
            force_type=template_brush.TEMP_TYPES.detail,
            additional_visgroups=visgroup,
        )

        for face in template.detail.sides():
            if face.normal() == normal:
                brush_faces.append(face)
    else:
        # Direct on the surface.
        block_center = origin // 128 * 128 + (64, 64, 64)
        try:
            face = conditions.SOLIDS[
                (block_center + 64*normal).as_tuple()
            ].face
        except KeyError:
            LOGGER.warning(
                "Can't place signage at ({}) in ({}) direction!",
                block_center,
                normal,
            )
            return
        brush_faces = [face]

    if inst.fixup.bool(const.FixupVars.ST_REVERSED):
        # Flip around.
        forward = -forward
        prim_pos, sec_pos = sec_pos, prim_pos

    if sign_prim is not None:
        place_sign(
            vmf,
            brush_faces,
            sign_prim,
            prim_pos,
            normal,
            forward,
            rotate=True,
        )

    if sign_sec is not None:
        if has_arrow and res.bool('arrowDown'):
            # Arrow texture points down, need to flip it.
            forward = -forward
        place_sign(
            vmf,
            brush_faces,
            sign_sec,
            sec_pos,
            normal,
            forward,
            rotate=not has_arrow,
        )


def place_sign(
    vmf: VMF,
    faces: Iterable[Side],
    sign: Sign,
    pos: Vec,
    normal: Vec,
    forward: Vec,
    rotate: bool=True,
) -> None:
    """Place the sign into the map."""

    if rotate and normal.z == 0:
        # On the wall, point upward.
        forward = Vec(0, 0, 1)

    texture = sign.overlay
    if texture.startswith('<') and texture.endswith('>'):
        texture = vbsp.get_tex(texture[1:-1])

    width, height = SIZES[sign.type]
    over = make_overlay(
        vmf,
        -normal,
        pos,
        uax=-width * Vec.cross(normal, forward).norm(),
        vax=-height * forward,
        material=texture,
        surfaces=faces,
    )

    over['startu'] = '1'
    over['endu'] = '0'

    vbsp.IGNORED_OVERLAYS.add(over)
