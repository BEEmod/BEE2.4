"""Implements the ability to recolor cubes."""
from conditions import make_result, make_flag, add_suffix
from srctools import Vec, Entity, Property

import utils
import vbsp

LOGGER = utils.getLogger(__name__, alias='cond.color_cubes')

# The colours used, indexed by timer delay - 3.
# Don't use max/min exactly, this helps make it look a bit more natural.
L, M, H = 25, 128, 230
COLORS = [
    (L, L, H),
    (H, L, L),
    (L, H, L),
    (H, H, L),
    (H, L, H),
    (L, H, H),

    (64, 64, 64),
    (M, M, M),
    (192, 192, 192),
    (H, H, H),

    (L, L, M),
    (L, M, L),

    (L, M, M),
    (L, M, H),
    (L, H, M),
    (M, L, L),
    (M, L, M),
    (M, L, H),
    (M, M, L),
    (M, M, H),
    (M, H, L),
    (M, H, M),
    (M, H, H),
    (H, L, M),
    (H, M, L),
    (H, M, M),
    (H, M, H),
    (H, H, M),
]
del L, M, H

COLOR_POS = {}


@make_result('_CubeColoriser')
def res_cube_coloriser(inst: Entity, res: Property):
    """Allows recoloring cubes placed at a position."""
    origin = Vec.from_str(inst['origin'])
    timer_delay = inst.fixup.int('$timer_delay')
    if 3 <= timer_delay <= 30:
        COLOR_POS[origin.as_tuple()] = COLORS[timer_delay]
    else:
        LOGGER.warning('Unknown timer value "{}"!', timer_delay)
    inst.remove()


@make_flag('ColoredCube')
def res_colored_cube(inst: Entity):
    """Allows coloring a cube or dropper.

    If this block contains a coloriser, this sets $cube_color to the correct
    color. The flag value is True if the cube is coloured.
    """
    origin = Vec.from_str(inst['origin'])
    LOGGER.info('Pos: {}\n\n, {}->{}', COLOR_POS, origin, COLOR_POS.get(origin.as_tuple()))
    try:
        color = COLOR_POS[origin.as_tuple()]
    except KeyError:
        return False
    inst.fixup['$cube_color'] = '{} {} {}'.format(*color)
    return True


if __name__ == '__main__':
    # Dump colours as HTML
    TD_TMP = '''<html>
    <td style="background-color: rgb({r}, {g}, {b})">{i} = ({r}, {g}, {b})</td>
    </tr>'''
    with open('out.htm', 'w') as f:
        f.write('<html>\n<body>\n<table>\n')
        for i, (r, g, b) in enumerate(COLORS, start=3):
            f.write(TD_TMP.format(i=i, r=r, g=g, b=b))
        f.write('</table>\n</body>\n</html>')
