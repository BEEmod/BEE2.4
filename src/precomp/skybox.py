import srctools.logger
from srctools import VMF, Vec

import consts
import precomp.options
from precomp.brushLoc import POS

LOGGER = srctools.logger.get_logger(__name__)

EX_SIZE_MAX = Vec(8832, 8832, 8832)
EX_SIZE_MIN = Vec(5632, 5632, 5632)

def make_skybox(vmf : VMF, coll):
    if not precomp.options.get(bool, 'extend_chamber'):
        return None

    # Make the box that contains the map
    make_skybox_shell(vmf)

    # Move Elevators to valid location if possible and then generate elevator shell

    # Open Walls and add square beams

    # Add exterior decoration

def make_skybox_shell(vmf : VMF):
    # Generate our walls
    size_pad = Vec(2048, 2048, 128)

    pos_min,pos_max = Vec.bbox(POS.min, POS.max)
    bbox_origin = (POS.min + POS.max) / 2
    bbox_lower, bbox_upper = Vec.bbox(
        -max(EX_SIZE_MIN / 2, min(EX_SIZE_MAX / 2, -(pos_min - bbox_origin) + size_pad)),
        max(EX_SIZE_MIN / 2, min(EX_SIZE_MAX / 2, (pos_max - bbox_origin) + size_pad))
    )

    for solid in vmf.make_hollow(bbox_lower + bbox_origin, bbox_upper + bbox_origin, 16, consts.Tools.NODRAW, consts.Tools.BLACK):
        vmf.add_brush(solid)

    # vmf.add_brush(vmf.make_prism(pos_min, pos_max, consts.Tools.SKIP).solid)