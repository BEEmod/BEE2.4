"""3D pathfinding system"""
import functools
from enum import Enum, auto
from typing import Iterable

import astar
import attrs
from srctools import Angle, FrozenMatrix, FrozenVec, Matrix, VMF, Vec

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
    
    
class Kind(Enum):
    STRAIGHT = auto()
    CORNER_LEFT = auto()
    CORNER_RIGHT = auto()
    STAIR_UP = auto()
    STAIR_DN = auto()

PROPS = {
    Kind.STRAIGHT: ('models/props_bts/hanging_walkway_128a.mdl', FrozenVec(0, 0, -64), 90),
    Kind.CORNER_LEFT: ('models/props_bts/hanging_walkway_l.mdl', FrozenVec(0, 0, -64), 0),
    Kind.CORNER_RIGHT: ('models/props_bts/hanging_walkway_l.mdl', FrozenVec(0, 0, -64), 90),
    Kind.STAIR_UP: ('models/bee2/catwalk/factory_hanging_stairs_128_extended.mdl', FrozenVec(-64, 0, -128), 270),
    Kind.STAIR_DN: ('models/bee2/catwalk/factory_hanging_stairs_128_extended.mdl', FrozenVec(-64, 0, 0), 90),
}


@attrs.frozen
class CatwalkNode:
    pos: FrozenVec
    yaw: Yaw
    trace: Kind = attrs.field(eq=False, hash=False)

    @property
    def orient(self) -> FrozenMatrix:
        """Rotate around this yaw."""
        return self.yaw.orient

    def local(self, x: int, y: int, z: int) -> FrozenVec:
        return FrozenVec(x, y, z) @ self.yaw.orient + self.pos


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
        point_1 = Vec(-4, -2, 0) @ node.yaw.orient + node.pos
        point_2 = Vec(0, 2, 0) @ node.yaw.orient + node.pos
        for pos in Vec.iter_grid(*Vec.bbox(point_1, point_2), 1):
            if not is_empty(pos.x, pos.y):
                return False
        return True

    def neighbours(node: CatwalkNode) -> Iterable[CatwalkNode]:
        forward = node.local(1, 0, 0)
        if POS[forward] is Block.VOID:
            yield CatwalkNode(forward, node.yaw, Kind.STRAIGHT)
            yield CatwalkNode(forward, node.yaw.left, Kind.CORNER_LEFT)
            yield CatwalkNode(forward, node.yaw.right, Kind.CORNER_RIGHT)
            if POS[node.local(2, 0, 0)] is Block.VOID:
                if POS[node.local(2, 0, 1)] is Block.VOID:
                    yield CatwalkNode(node.local(2, 0, 1), node.yaw, Kind.STAIR_UP)
                if POS[node.local(2, 0, -1)] is Block.VOID:
                    yield CatwalkNode(node.local(2, 0, -1), node.yaw, Kind.STAIR_DN)

    def distance(node1: CatwalkNode, node2: CatwalkNode) -> float:
        return (node1.pos - node2.pos).mag_sq()

    start_node = CatwalkNode(start.freeze(), yaw, Kind.STRAIGHT)
    end_node = CatwalkNode(FrozenVec(40, 4, 12), Yaw.EAST, Kind.STRAIGHT)
    path = [start_node, *neighbours(start_node), end_node]
    
    path = astar.find_path(
        start_node, end_node,
        neighbors_fnct=neighbours,
        distance_between_fnct=distance,
        heuristic_cost_estimate_fnct=distance,
        is_goal_reached_fnct=reached_goal,
    )
    for node in path:
        mdl, off, yaw_val = PROPS[node.trace]
        ang = node.yaw.orient.to_angle()
        ang.yaw += yaw_val
        vmf.create_ent(
            'prop_static',
            origin=grid_to_world(node.pos.thaw()) + (off @ node.orient),
            model=mdl,
            angles=ang,
        )
        # vmf.create_ent(
        #     'info_particle_system',
        #     origin=grid_to_world(node.pos.thaw()),
        #     angles=node.yaw.orient.to_angle(),
        # )
