"""3D pathfinding system"""
import functools
from enum import Enum
from typing import Iterable

import astar
import attrs
from srctools import FrozenMatrix, FrozenVec, Matrix, VMF, Vec

import utils
from precomp.corridor import Info as CorrInfo
from .brushLoc import Block, grid_to_world, world_to_grid, POS


@utils.freeze_enum_props
class Yaw(Enum):
    EAST = 0
    NORTH = 90
    WEST = 180
    SOUTH = 270

    @property
    def orient(self) -> FrozenMatrix:
        """Rotate around this yaw."""
        return FrozenMatrix.from_yaw(self.value)

    @property
    def left(self) -> 'Yaw':
        return Yaw((self.value - 90) % 360)

    @property
    def right(self) -> 'Yaw':
        return Yaw((self.value + 90) % 360)


@attrs.frozen
class CatwalkNode:
    pos: FrozenVec
    yaw: Yaw


def test(vmf: VMF, info: CorrInfo):
    entry_pos = Vec.from_str(info.inst_entry['origin'])
    entry_orient = Matrix.from_angstr(info.inst_entry['angles'])
    start = world_to_grid(Vec(-640, 0, 0) @ entry_orient + entry_pos)
    yaw = Yaw(round(entry_orient.to_angle().yaw)).right.right

    @functools.cache
    def is_empty(x: int, y: int) -> bool:
        for z in range(26):
            if POS[x, y, z] is not Block.VOID:
                return False
        return True

    def reached_goal(node: CatwalkNode, goal: CatwalkNode) -> bool:
        if node == goal:
            return True
        # point_1 = Vec(-4, -2, 0) @ node.yaw.orient + node.pos
        # point_2 = Vec(0, 2, 0) @ node.yaw.orient + node.pos
        point_1 = node.pos + Vec(1, 1, 0)
        point_2 = node.pos - Vec(1, 1, 0)
        for pos in Vec.iter_grid(*Vec.bbox(point_1, point_2), 1):
            if not is_empty(pos.x, pos.y):
                return False
        return True

    def neighbours(node: CatwalkNode) -> Iterable[CatwalkNode]:
        forward = FrozenVec(1, 0, 0) @ node.yaw.orient + node.pos
        if POS[forward] is Block.VOID:
            yield CatwalkNode(forward, node.yaw)
            yield CatwalkNode(forward, node.yaw.left)
            yield CatwalkNode(forward, node.yaw.right)

    def distance(node1: CatwalkNode, node2: CatwalkNode) -> float:
        return (node1.pos - node2.pos).mag_sq()

    start_node = CatwalkNode(start.freeze(), yaw)
    end_node = CatwalkNode(FrozenVec(-20, 8, start.z), Yaw.WEST)
    path = [start_node, *neighbours(start_node), end_node]
    
    path = astar.find_path(
        start_node, end_node,
        neighbors_fnct=neighbours,
        distance_between_fnct=distance,
        heuristic_cost_estimate_fnct=distance,
        is_goal_reached_fnct=reached_goal,
    )
    for node in path:
        vmf.create_ent(
            'info_particle_system',
            origin=grid_to_world(node.pos.thaw()),
            angles=node.yaw.orient.to_angle(),
        )
