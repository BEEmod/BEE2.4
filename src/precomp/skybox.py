import srctools.logger
from srctools import VMF, Vec

import consts
import precomp.options
from precomp.brushLoc import POS

LOGGER = srctools.logger.get_logger(__name__)

def generate(vmf : VMF, coll):
    # Generate our walls
    if not precomp.options.get(bool, 'extend_chamber'):
        return None

    size_max = Vec(8832, 8832, 8832)
    size_pad = Vec(2048, 2048, 128)

    bbox_origin = (POS.min + POS.max) / 2
    bbox_lower = min(-(size_max/2), (POS.min - bbox_origin) - size_pad) + bbox_origin
    bbox_upper = min(size_max/2, (POS.max - bbox_origin) + size_pad) + bbox_origin

    for solid in vmf.make_hollow(bbox_lower, bbox_upper, 16, consts.Tools.NODRAW, consts.Tools.BLACK):
        vmf.add_brush(solid)