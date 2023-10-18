import srctools.logger
from srctools import VMF, Vec, FrozenVec, Angle, Matrix

import consts
import precomp.options
import precomp.pathing
from precomp.pathing import NodeKind, GenericNode
from precomp.brushLoc import POS, world_to_grid, grid_to_world, Block
from precomp.corridor import Info as CorrInfo


LOGGER = srctools.logger.get_logger(__name__)

EX_SIZE_MAX = Vec(69, 69, 69)*128
EX_SIZE_MIN = Vec(32, 32, 32)*128

CATWALKS = [
    NodeKind(name= 'STRAIGHT', end_pos= FrozenVec(1, 0, 0)),
    NodeKind(name='CORNER_LEFT', end_pos= FrozenVec(1, 0, 0), angle= Angle(0, -90, 0)),
    NodeKind(name='CORNER_RIGHT', end_pos= FrozenVec(1, 0, 0), angle= Angle(0, 90, 0)),
    NodeKind(name='STAIR_UP', end_pos= FrozenVec(2, 0, 1)),
    NodeKind(name='STAIR_DN', end_pos= FrozenVec(2, 0, -1)),
]

def make_exterior(vmf: VMF, coll, info: CorrInfo) -> None:
    """Generate the exterior of the map: pits, catwalks, tubes, etc."""
    # if not precomp.options.get(bool, 'extend_chamber'):
    #     return None

    # Make the box that contains the map
    map_bounds = make_exterior_shell(vmf)

    # Move Elevators to valid location if possible and then generate elevator shell
    place_entrance_exit(info, map_bounds)

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

    map_bounds = Vec.bbox(bbox_lower + bbox_origin, bbox_upper + bbox_origin)

    for solid in vmf.make_hollow(*map_bounds, 16, consts.Tools.NODRAW, consts.Tools.BLACK):
        vmf.add_brush(solid)

    return map_bounds

    # vmf.add_brush(vmf.make_prism(pos_min, pos_max, consts.Tools.SKIP).solid)

def place_entrance_exit(info: CorrInfo, map_bounds):

    entry_pos = Vec.from_str(info.inst_entry['origin'])
    entry_orient = Matrix.from_angstr(info.inst_entry['angles'])

    start_pos = world_to_grid(Vec(-640, 0, 0) @ entry_orient + entry_pos)
    start_angle = Angle(0, round(entry_orient.to_angle().yaw + 180) % 360, 0)

    end_pos = FrozenVec(0, 27, start_pos.z)
    end_angle = Angle(0, 0, 0)

    start_node = GenericNode( start_pos, start_angle, CATWALKS[0])
    end_node = GenericNode( end_pos, end_angle, CATWALKS[0])

    blockers = [
        Block.VOID
    ]

    """Place the map entrance and exit"""
    path = precomp.pathing.test(start_node, end_node, CATWALKS, info, map_bounds, blockers)
    for node in path:
        # mdl, off, yaw_val = CATWALKS[node.trace]
        # ang = node.yaw.orient.to_angle()
        # ang.yaw += yaw_val
        VMF.create_ent(
            'info_particle_system',
            origin=grid_to_world(node.pos.thaw()),
            angles=node.orient.to_angle(),
            targetname = str(node.trace.name)
        )

    return
