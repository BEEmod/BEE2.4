"""Handles user errors found, displaying a friendly interface to the user."""
from typing import Iterable

import consts
from srctools import Vec, VMF
import utils

ERROR_TEMPLATE = '''\
<!DOCTYPE html>
<html>
<head>
  <title>BEEmod Compilation Error</title>
  <style>
  body {
    background: #fff;
    color: #000;
  }
  </style>
</head>
<body>
%MSG%
</body>
</html>
'''


class UserError(BaseException):
    """Special exception used to indicate a error in item placement, etc.

    This will result in the compile switching to compile a map which displays
    a HTML page to the user via the Steam Overlay.
    """
    def __init__(self, message: str, *args: object, points: Iterable[Vec]=()) -> None:
        """Specify the info to show to the user.

        * message is a str.format string, using args as the parameters.
        * points is a list of offending map locations, which will be placed
          in a copy of the map for the user to see.
        """
        self.message = message.format(*args)
        self.points = list(points)

    def __str__(self) -> str:
        return 'Error message: ' + self.message

    def make_map(self) -> VMF:
        """Generate a map which triggers the error each time.

        This map is as simple as possible to make compile time quick.
        """
        with utils.COMPILE_USER_ERROR_PAGE.open('w') as f:
            f.write(ERROR_TEMPLATE.replace('%MSG%', self.message))
        vmf = VMF()
        vmf.map_ver = 1
        vmf.spawn['skyname'] = 'sky_black_nofog'
        vmf.spawn['detailmaterial'] = "detail/detailsprites"
        vmf.spawn['detailvbsp'] = "detail.vbsp"
        vmf.spawn['maxblobcount'] = "250"
        vmf.spawn['paintinmap'] = "0"

        vmf.add_brushes(vmf.make_hollow(
            Vec(),
            Vec(128, 128, 128),
            thick=32,
            mat=consts.Tools.NODRAW,
            inner_mat=consts.Tools.BLACK,
        ))
        # Ensure we have at least one lightmapped surface,
        # so VRAD computes lights.
        roof_detail = vmf.make_prism(
            Vec(48, 48, 120),
            Vec(80, 80, 124)
        )
        roof_detail.top.mat = consts.BlackPan.BLACK_FLOOR
        roof_detail.top.scale = 64
        vmf.create_ent('func_detail').solids.append(roof_detail.solid)

        # VScript displays the webpage, then kicks you back to the editor
        # if the map is swapped back to.
        vmf.create_ent(
            'info_player_start',
            origin="64 64 1",
            angles="0 0 0",
            vscripts='BEE2/compile_error.nut',
            thinkfunction='Think',
        )
        # We need a light, so the map compiles lights and doesn't turn on
        # mat_fullbright.
        vmf.create_ent(
            'light',
            origin="64 64 64",
            angles="0 0 0",
            spawnflags="0",
            _light="255 255 255 200",
            _lightHDR="-1 -1 -1 -1",
            _lightscaleHDR="1",
            _constant_attn="0",
            _quadratic_attn="1",
            _linear_attn="1",
        )
        return vmf
