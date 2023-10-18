"""3D pathfinding system"""
import functools
import math
from enum import Enum, auto
from typing import Iterable, Union, ClassVar, Any

import astar
import attrs
from srctools import Angle, FrozenMatrix, FrozenVec, Matrix, VMF, Vec, logger, FrozenAngle

import utils
from precomp.corridor import Info as CorrInfo
from .brushLoc import Block, grid_to_world, world_to_grid, POS

LOGGER = logger.get_logger(__name__)

# @utils.freeze_enum_props
# class Yaw(Enum):
#     EAST = 0
#     NORTH = 90
#     WEST = 180
#     SOUTH = 270
#
#     @property
#     def orient(self) -> FrozenMatrix:
#         """Rotate around this yaw."""
#         return FrozenMatrix.from_yaw(self.value)
#
#     @property
#     def left(self) -> 'Yaw':
#         return Yaw((self.value - 90) % 360)
#
#     @property
#     def right(self) -> 'Yaw':
#         return Yaw((self.value + 90) % 360)

class NodeKind:
    def __init__(self, name: str, end_pos: Union[Vec, FrozenVec], instance =  None, angle = None, bbox = None, cost = None):
        self.name = name
        self.end_pos = end_pos
        self.instance = instance if instance is not None else ""
        self.angle = angle if angle is not None else Angle(0, 0, 0)
        self.bbox = Vec.iter_grid(bbox.bbox_min, bbox.bbox_max).append(end_pos) if bbox is not None else end_pos
        self.cost = cost if cost is not None else 0

    @property
    def orient(self) -> FrozenMatrix:
        """Rotate around this yaw."""
        return FrozenMatrix.from_angle(self.angle)


# PROPS = {
#     Kind.STRAIGHT: ('models/props_bts/hanging_walkway_128a.mdl', FrozenVec(0, 0, -64), 90),
#     Kind.CORNER_LEFT: ('models/props_bts/hanging_walkway_l.mdl', FrozenVec(0, 0, -64), 0),
#     Kind.CORNER_RIGHT: ('models/props_bts/hanging_walkway_l.mdl', FrozenVec(0, 0, -64), 90),
#     Kind.STAIR_UP: ('models/bee2/catwalk/factory_hanging_stairs_128_extended.mdl', FrozenVec(-64, 0, -128), 270),
#     Kind.STAIR_DN: ('models/bee2/catwalk/overgrown/hanging_stair_128.mdl', FrozenVec(-64, 0, 0), 90),
# }

# @attrs.frozen
# class CatwalkNode:
#     pos: FrozenVec
#     yaw: Yaw
#     trace: Kind
#
#     @property
#     def orient(self) -> FrozenMatrix:
#         """Rotate around this yaw."""
#         return self.yaw.orient
#
#     def local(self, x: int, y: int, z: int) -> FrozenVec:
#         return round(FrozenVec(x, y, z) @ self.yaw.orient + self.pos)

@attrs.frozen
class GenericNode:
    pos: Union[Vec, FrozenVec]
    ang: Union[Angle, FrozenAngle]
    trace: NodeKind

    @property
    def orient(self) -> FrozenMatrix:
        """Rotate around this yaw."""
        return FrozenMatrix.from_angle(self.ang)

    def local(self, p: Union[Vec, FrozenVec]) -> FrozenVec:
        return round(p @ self.orient + self.pos)

# checked_blocks = []
# not_void = []

# def debug_block(vec : Vec, group : list):
#     if not vec in group:
#         group.append(vec)

def test(start_node: GenericNode, end_node: GenericNode, node_types: list, info: CorrInfo, bounds: Vec.bbox, blockers: list):
    @functools.cache
    def is_empty(x: int, y: int) -> bool:
        for z in range(26):
            if POS[x, y, z] is not Block.VOID:
                return False
        return True

    @functools.cache
    def in_inner_bounds(vec: Vec) -> bool:
        size_pad = Vec(3, 3, 3)*128
        pos_min, pos_max = (Vec.bbox(POS.min - size_pad, POS.max + size_pad))
        if Vec(vec.x, vec.y, 0).in_bbox(pos_min, pos_max):
            return True

    def reached_goal(node: GenericNode, goal: GenericNode) -> bool:
        # point = Vec(1, 0, 0) @ node.yaw.orient + node.pos(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]if 0 <= nx < self.width and 0 <= ny < self.height and self.lines[ny][nx] == ' ']
        # debug_block(grid_to_world(point), checked_blocks)

        # if node == goal:
        #     return True

        # point_1 = Vec(-4, -2, 0) @ node.yaw.orient + node.pos
        # point_2 = Vec(0, 2, 0) @ node.yaw.orient + node.pos
        # for pos in Vec.iter_grid(*Vec.bbox(point_1, point_2), 1):
        #     if not is_empty(pos.x, pos.y):
        #         return False

        return node == goal
        # return True

    def neighbours(cur_node: GenericNode) -> Iterable[GenericNode]:
        next_pos = cur_node.trace.end_pos @ cur_node.orient + cur_node.pos
        if not POS[next_pos] in blockers:
            for node_type in node_types:
                for pos in node_type.bbox:
                    if not POS[pos] in blockers:
                        yield GenericNode(cur_node.local(node_type.end_pos), cur_node.ang, node_type)


        # debug_block(grid_to_world(cur_node.pos), checked_blocks)
        # forward = cur_node.local(1, 0, 0)
        # if POS[forward] is Block.VOID and grid_to_world(forward).in_bbox(*bounds):
        #     yield CatwalkNode(forward, cur_node.yaw, Kind.STRAIGHT)
        #     yield CatwalkNode(forward, cur_node.yaw.left, Kind.CORNER_LEFT)
        #     yield CatwalkNode(forward, cur_node.yaw.right, Kind.CORNER_RIGHT)
        #     if POS[cur_node.local(2, 0, 0)] is Block.VOID:
        #         if POS[cur_node.local(2, 0, 1)] is Block.VOID:
        #             yield CatwalkNode(cur_node.local(2, 0, 1), cur_node.yaw, Kind.STAIR_UP)
        #         if POS[cur_node.local(2, 0, -1)] is Block.VOID:
        #             yield CatwalkNode(cur_node.local(2, 0, -1), cur_node.yaw, Kind.STAIR_DN)

    # def distance(node1: CatwalkNode, node2: CatwalkNode) -> float:
    #     return 8 * (node1.pos - node2.pos).mag()
    #
    # def cost(node1: CatwalkNode, node2: CatwalkNode) -> float:
    #     dist = (node1.pos - node2.pos).mag()
    #     if node1.trace.is_stair and node2.trace.is_stair and node1.trace is not node2.trace:
    #         return dist * 4
    #     if node2.trace.is_stair:
    #         return dist * 2
    #     return dist

    def heuristic_cost_estimate(n1: GenericNode, n2: GenericNode) -> float:
        """computes the cost of the path"""
        dist = distance_between(n1, n2)
        cost = dist
        # if n1.trace.is_stair and n2.trace.is_stair and n1.trace is not n2.trace:
        #     cost += 40
        # keeps making unnecessary stairs
        # elif n1.trace.is_stair and n2.trace == Kind.CORNER_RIGHT or n1.trace == Kind.CORNER_RIGHT and n2.trace.is_stair:
        #     cost += 5
        # elif n2.trace.is_stair:
        #     cost += 20
        # elif n2.trace.is_corner:
        #     cost += 100
        # if in_inner_bounds(grid_to_world(n2.pos)):
        #     cost += cost*2
        return cost

    def distance_between(n1: GenericNode, n2: GenericNode) -> float:
        """computes the distance between neighbors"""
        return 8 * (n1.pos - n2.pos).mag()

    # start_node = CatwalkNode(start.freeze(), yaw, Kind.STRAIGHT)
    # end_node = CatwalkNode(FrozenVec(0, 20, start_node.pos.z), Yaw.EAST, Kind.STRAIGHT)

    # vmf.create_ent(
    #     'info_particle_system',
    #     origin=grid_to_world(start_node.pos.thaw()),
    #     angles=start_node.yaw.orient.to_angle(),
    # )
    # vmf.create_ent(
    #     'info_particle_system',
    #     origin=grid_to_world(end_node.pos.thaw()),
    #     angles=end_node.yaw.orient.to_angle(),
    # )

    path = astar.find_path(
        start_node, end_node,
        neighbors_fnct=neighbours,
        distance_between_fnct=heuristic_cost_estimate,
        heuristic_cost_estimate_fnct=distance_between,
        is_goal_reached_fnct=reached_goal,
    )

    if path is not None:
        return path
        # for node in path:
        #     mdl, off, yaw_val = PROPS[node.trace]
        #     ang = node.yaw.orient.to_angle()
        #     ang.yaw += yaw_val
            # vmf.create_ent(
            #     'prop_static',
            #     origin=grid_to_world(node.pos.thaw()) + (off @ node.orient),
            #     model=mdl,
            #     angles=ang,
            # )
            # vmf.create_ent(
            #     'info_particle_system',
            #     origin=grid_to_world(node.pos.thaw()),
            #     angles=node.yaw.orient.to_angle(),
            #     targetname = str(node.trace)
            # )
        # for point in checked_blocks:
        #     vmf.create_ent(
        #          'info_target',
        #          origin=point,
        #     )
        # for point in not_void:
        #     vmf.create_ent(
        #          'info_hint',
        #          origin=point,
        #     )
    else:
        LOGGER.warning('Path failed to generate!')
