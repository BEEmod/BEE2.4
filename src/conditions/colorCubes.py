"""Implements the ability to recolor cubes."""
from conditions import make_result, make_flag, add_suffix
from srctools import Vec, Entity, parse_vec_str

import utils
import brushLoc

COND_MOD_NAME = None

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

    (L, L, L),
    (M, M, M),
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
    (32, 192, 32),
]
del L, M, H

# Origin -> the color at a position
COLOR_POS = {}
# For cube droppers, there's a cube item as well as the dropper.
# This is a the ceiling opposite to colorisers on the floor, so
# placing it on the cube will color the dropper.
COLOR_SEC_POS = {}


@make_result('_CubeColoriser')
def res_cube_coloriser(inst: Entity):
    """Allows recoloring cubes placed at a position."""
    origin = Vec.from_str(inst['origin'])
    # Provided from the timer value directly.
    timer_delay = inst.fixup.int('$timer_delay')

    # Provided from item config panel
    color_override = parse_vec_str(inst.fixup['$color'])

    if color_override != (0, 0, 0):
        color = COLOR_POS[origin.as_tuple()] = color_override
    elif 3 <= timer_delay <= 30:
        color = COLOR_POS[origin.as_tuple()] = COLORS[timer_delay - 3]
    else:
        LOGGER.warning('Unknown timer value "{}"!', timer_delay)
        color = None
    inst.remove()

    # If pointing up, copy the value to the ceiling, so droppers
    # can find a coloriser placed on the illusory cube item under them.
    if Vec(z=1).rotate_by_str(inst['angles']) == (0, 0, 1) and color is not None:
        pos = brushLoc.POS.raycast_world(
            origin,
            direction=(0, 0, 1),
        )
        COLOR_SEC_POS[pos.as_tuple()] = color


@make_flag('ColoredCube')
def res_colored_cube(inst: Entity):
    """Allows coloring a cube or dropper.

    If this block contains a coloriser, this sets $cube_color to the correct
    color. The flag value is True if the cube is coloured.
    """
    origin = Vec.from_str(inst['origin'])
    try:
        color = COLOR_POS[origin.as_tuple()]
    except KeyError:
        try:
            color = COLOR_SEC_POS[origin.as_tuple()]
        except KeyError:
            return False
    inst.fixup['$cube_color'] = '{} {} {}'.format(*color)
    return True


if __name__ == '__main__':
    # Dump colours as HTML
    TD_TMP = '''
    <td style="background-color: rgb({r}, {g}, {b})">{i} = ({r}, {g}, {b})</td>
    </tr>'''
    with open('out.htm', 'w') as f:
        f.write('<html>\n<body>\n<table>\n')
        for i, (r, g, b) in enumerate(COLORS, start=3):
            f.write(TD_TMP.format(i=i, r=r, g=g, b=b))
        f.write('</table>\n</body>\n</html>')
