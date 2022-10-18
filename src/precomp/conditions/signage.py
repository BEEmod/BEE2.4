"""Implements the customisable Signage item."""
from typing import Tuple, Dict, Optional, Iterable, List
from enum import Enum

import srctools.logger
from precomp import tiling, texturing, template_brush, conditions
import consts
from srctools import Property, Entity, VMF, Vec, NoKeyError, Matrix
from srctools.vmf import make_overlay, Side
import vbsp


COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.signage')


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
        )[inst.fixup[consts.FixupVars.TIM_DELAY]]
    except KeyError:
        # Blank sign
        sign = None

    has_arrow = inst.fixup.bool(consts.FixupVars.ST_ENABLED)
    make_4x4 = res.bool('set4x4tile')

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
    orient = Matrix.from_angstr(inst['angles'])

    normal = -orient.up()
    forward = -orient.forward()

    prim_pos = Vec(0, -16, -64) @ orient + origin
    sec_pos = Vec(0, +16, -64) @ orient + origin

    template_id = res['template_id', '']

    if inst.fixup.bool(consts.FixupVars.ST_REVERSED):
        # Flip around.
        forward = -forward
        prim_visgroup = 'secondary'
        sec_visgroup = 'primary'
        prim_pos, sec_pos = sec_pos, prim_pos
    else:
        prim_visgroup = 'primary'
        sec_visgroup = 'secondary'

    if sign_prim and sign_sec:
        inst['file'] = fname = res['large_clip', '']
        inst['origin'] = (prim_pos + sec_pos) / 2
    else:
        inst['file'] = fname = res['small_clip', '']
        inst['origin'] = prim_pos if sign_prim else sec_pos
    conditions.ALL_INST.add(fname.casefold())

    brush_faces: List[Side] = []
    tiledef: Optional[tiling.TileDef] = None

    if template_id:
        if sign_prim and sign_sec:
            visgroup = [prim_visgroup, sec_visgroup]
        elif sign_prim:
            visgroup = [prim_visgroup]
        else:
            visgroup = [sec_visgroup]
        template = template_brush.import_template(
            vmf,
            template_id,
            origin,
            orient,
            force_type=template_brush.TEMP_TYPES.detail,
            additional_visgroups=visgroup,
        )

        for face in template.detail.sides():
            if face.normal() == normal:
                brush_faces.append(face)
    else:
        # Direct on the surface.
        # Find the grid pos first.
        grid_pos = (origin // 128) * 128 + 64
        try:
            tiledef = tiling.TILES[(grid_pos + 128 * normal).as_tuple(), (-normal).as_tuple()]
        except KeyError:
            LOGGER.warning(
                "Can't place signage at ({}) in ({}) direction!",
                origin,
                normal,
                exc_info=True,
            )
            return

    if sign_prim is not None:
        over = place_sign(
            vmf,
            brush_faces,
            sign_prim,
            prim_pos,
            normal,
            forward,
            rotate=True,
        )

        if tiledef is not None:
            tiledef.bind_overlay(over)
        if make_4x4:
            try:
                tile, u, v = tiling.find_tile(prim_pos, -normal)
            except KeyError:
                pass
            else:
                tile[u, v] = tile[u, v].as_4x4

    if sign_sec is not None:
        if has_arrow and res.bool('arrowDown'):
            # Arrow texture points down, need to flip it.
            forward = -forward

        over = place_sign(
            vmf,
            brush_faces,
            sign_sec,
            sec_pos,
            normal,
            forward,
            rotate=not has_arrow,
        )

        if tiledef is not None:
            tiledef.bind_overlay(over)
        if make_4x4:
            try:
                tile, u, v = tiling.find_tile(sec_pos, -normal)
            except KeyError:
                pass
            else:
                tile[u, v] = tile[u, v].as_4x4


def place_sign(
    vmf: VMF,
    faces: Iterable[Side],
    sign: Sign,
    pos: Vec,
    normal: Vec,
    forward: Vec,
    rotate: bool=True,
) -> Entity:
    """Place the sign into the map."""
    if rotate and abs(normal.z) < 0.1:
        # On the wall, point upward.
        forward = Vec(0, 0, 1)

    texture = sign.overlay
    if texture.startswith('<') and texture.endswith('>'):
        gen, tex_name = texturing.parse_name(texture[1:-1])
        texture = gen.get(pos, tex_name)

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
    vbsp.IGNORED_OVERLAYS.add(over)

    over['startu'] = '1'
    over['endu'] = '0'

    return over
