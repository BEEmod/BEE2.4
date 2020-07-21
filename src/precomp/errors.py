"""Handles user errors found, displaying a friendly interface to the user."""
from typing import Iterable

import consts
from srctools import Vec, VMF
import utils

ERROR_PAGE = utils.conf_location('error.html')

ERROR_TEMPLATE = '''\
<!DOCTYPE html>
<html>
<head>
  <title>BEEmod Compilation Error</title>
  <style>
  body {
    background: #000;
    color: #fff;
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
        with ERROR_PAGE.open('w') as f:
            f.write(ERROR_TEMPLATE.replace('%MSG', self.message))
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
        # Drop lightmap size, might make it a teeny bit faster.
        for side in vmf.iter_wfaces():
            side.lightmap = 128

        # VScript displays the webpage, then kicks you back to the editor
        # if the map is swapped back to.
        vmf.create_ent(
            'info_player_start',
            origin="64 64 1",
            vscripts='BEE2/compile_error.nut',
            thinkfunction='Think',
        )
        vmf.create_ent(
            'light',
            origin="64 64 64",
            angles="0 0 0",
            spawnflags="0",
            _light="255 255 255 20",
            _lightHDR="-1 -1 -1 -1",
            _lightscaleHDR="1",
            _constant_attn="0",
            _quadratic_attn="1",
            _linear_attn="1",
        )
        return vmf
