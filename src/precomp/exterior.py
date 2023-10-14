import srctools.logger
from srctools import VMF, Vec

import consts
import precomp.options
import precomp.pathing
from precomp.brushLoc import POS
from precomp.corridor import Info as CorrInfo


LOGGER = srctools.logger.get_logger(__name__)

EX_SIZE_MAX = Vec(69, 69, 69)*128
EX_SIZE_MIN = Vec(32, 32, 32)*128

def make_exterior(vmf: VMF, coll, info: CorrInfo) -> None:
    """Generate the exterior of the map: pits, catwalks, tubes, etc."""
    if not precomp.options.get(bool, 'extend_chamber'):
        return None

    # Make the box that contains the map
    outer_bounds = make_exterior_shell(vmf)

    # Move Elevators to valid location if possible and then generate elevator shell
    place_entrance_exit(vmf, info, outer_bounds)

    # Open Walls and add square beams

    # Add exterior decoration

def make_exterior_shell(vmf : VMF):
    """Make the shell around the map"""
    # Generate our walls
    # All these variables should be controlled by the style package
    size_pad = Vec(16, 16, 16)*128

    pos_min,pos_max = Vec.bbox(POS.min, POS.max)
    bbox_origin = (POS.min + POS.max) / 2
    bbox_lower, bbox_upper = Vec.bbox(
        -max(EX_SIZE_MIN / 2, min(EX_SIZE_MAX / 2, -(pos_min - bbox_origin) + size_pad)),
        max(EX_SIZE_MIN / 2, min(EX_SIZE_MAX / 2, (pos_max - bbox_origin) + size_pad))
    )

    outer_bounds = Vec.bbox(bbox_lower + bbox_origin, bbox_upper + bbox_origin)

    for solid in vmf.make_hollow(*outer_bounds, 16, consts.Tools.NODRAW, consts.Tools.BLACK):
        vmf.add_brush(solid)

    return outer_bounds

    # vmf.add_brush(vmf.make_prism(pos_min, pos_max, consts.Tools.SKIP).solid)

def place_entrance_exit(vmf: VMF, info: CorrInfo, bounds):
    """Place the map entrance and exit"""
    precomp.pathing.test(vmf, info, bounds)
