"""Items dealing with antlines - Antline Corners and Antlasers."""
from __future__ import annotations
from enum import Enum
from typing import Callable, Union
import attrs

from precomp import instanceLocs, connections, conditions, antlines
import srctools.logger
from precomp.conditions import make_result
from srctools import VMF, Keyvalues, Output, Vec, Entity, Matrix


COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.antlines')

# Antlasers have their own visuals, so they need an item to stay.
CONFIG_ANTLASER = connections.Config(
    '<ANTLASER>',
    input_type=connections.InputType.OR,
    output_act=(None, 'OnUser2'),
    output_deact=(None, 'OnUser1'),
)
# But antline corners just place antlines, and can collapse into other items.
CONFIG_ANTLINE = connections.Config(
    '<ANTLINE>',
    input_type=connections.InputType.OR_LOGIC,
)

NAME_SPR: Callable[[str, int], str] = '{}-fx_sp_{}'.format
NAME_BEAM_LOW: Callable[[str, int], str] = '{}-fx_b_low_{}'.format
NAME_BEAM_CONN: Callable[[str, int], str] = '{}-fx_b_conn_{}'.format
NAME_CABLE: Callable[[str, int], str] = '{}-cab_{}'.format


# The corner offset in the model for each timer delay value. This starts at delay=3.
CORNER_POS = [
    Vec(8.0, 56.0, -64.0),
    Vec(8.0, 40.0, -64.0),
    Vec(8.0, 24.0, -64.0),
    Vec(8.0, 8.0, -64.0),
    Vec(-8.0, 56.0, -64.0),
    Vec(-8.0, 40.0, -64.0),
    Vec(-8.0, 24.0, -64.0),
    Vec(-8.0, 8.0, -64.0),
]


class NodeType(Enum):
    """Handle our two types of item."""
    CORNER = 'corner'
    LASER = 'laser'


@attrs.define(eq=False)
class Node:
    """A node placed in the map."""
    type: NodeType
    inst: Entity
    item: connections.Item
    pos: Vec
    orient: Matrix
    # Group has been found yet for this node?
    is_grouped: bool = False
    # Track if an input was set, to force a corner overlay.
    had_input: bool = False

    @property
    def on_floor(self) -> bool:
        """Check if this node is on the floor."""
        return self.orient.up().z > 0.9


class RopeState(Enum):
    """Used to link up ropes."""
    NONE = 'none'  # No rope here.
    UNLINKED = 'unlinked'  # Rope ent, with no target.
    LINKED = 'linked'  # Rope ent, with target already.

    @staticmethod
    def from_node(
        points: dict[Node, Union[Entity, str]],
        node: Node,
    ) -> tuple[RopeState, Union[Entity, str]]:
        """Compute the state and ent/name from the points data."""
        try:
            ent = points[node]
        except KeyError:
            return RopeState.NONE, ''
        if isinstance(ent, str):
            return RopeState.LINKED, ent
        else:
            return RopeState.UNLINKED, ent


class Group:
    """Represents a group of markers."""
    def __init__(self, start: Node, typ: NodeType) -> None:
        self.type = typ  # Antlaser or corner?
        self.nodes: list[Node] = [start]
        # We use a frozenset here to ensure we don't double-up the links -
        # users might accidentally do that.
        self.links: set[frozenset[Node]] = set()

        # For antline corners, each endpoint + normal -> the segment
        self.ant_seg: dict[tuple[
            tuple[float, float, float],
            tuple[float, float, float],
        ], antlines.Segment] = {}

        # Create a comp_relay to attach I/O to.
        # The corners have an origin on the floor whereas lasers are normal.
        if typ is NodeType.CORNER:
            logic_pos = start.pos + 8 * start.orient.up()
            logic_conf = CONFIG_ANTLINE
        else:
            logic_pos = start.pos - 56 * start.orient.up()
            logic_conf = CONFIG_ANTLASER
        logic_ent = start.inst.map.create_ent(
            'comp_relay',
            origin=logic_pos,
            targetname=start.item.name,
            # Must be != to be enabled.
            ctrl_type='1',
            ctrl_value='0',
        )

        # Create the item for the entire group of markers.
        self.item = connections.Item(
            logic_ent, logic_conf,
            ind_style=start.item.ind_style,
        )
        connections.ITEMS[self.item.name] = self.item

    def add_ant_straight(self, normal: Vec, pos1: Vec, pos2: Vec) -> None:
        """Add a segment going from point 1 to 2."""
        if pos1 == pos2:
            # Zero long, just skip placing.
            # This occurs if placed right on the edge as we wrap around a voxel
            # corner.
            return

        seg = antlines.Segment(
            antlines.SegType.STRAIGHT,
            round(normal, 3),
            pos1, pos2,
        )
        norm_key = seg.normal.as_tuple()
        k1 = pos1.as_tuple(), norm_key
        k2 = pos2.as_tuple(), norm_key
        if k1 in self.ant_seg:
            LOGGER.warning('Antline segment overlap: {}', k1)
        if k2 in self.ant_seg:
            LOGGER.warning('Antline segment overlap: {}', k2)
        self.ant_seg[k1] = seg
        self.ant_seg[k2] = seg

    def rem_ant_straight(self, norm: tuple[float, float, float], endpoint: Vec) -> Vec:
        """Remove an antline segment with this enpoint, and return its other.

        This is used for merging corners. We already checked it's valid.
        """
        seg = self.ant_seg.pop((endpoint.as_tuple(), norm))
        if seg.start == endpoint:
            del self.ant_seg[seg.end.as_tuple(), norm]
            return seg.end
        elif seg.end == endpoint:
            del self.ant_seg[seg.start.as_tuple(), norm]
            return seg.start
        else:
            raise ValueError(f'Antline {seg} has no endpoint {endpoint}!')


@make_result('AntLaser')
def res_antlaser(vmf: VMF, res: Keyvalues) -> object:
    """The condition to generate AntLasers and Antline Corners.

    This is executed once to modify all instances.
    """
    conf_inst_corner = instanceLocs.resolve_filter('<item_bee2_antline_corner>', silent=True)
    conf_inst_laser = instanceLocs.resolve_filter(res['instance'])
    conf_glow_height = Vec(z=res.float('GlowHeight', 48) - 64)
    conf_las_start = Vec(z=res.float('LasStart') - 64)
    conf_rope_off = res.vec('RopePos')
    conf_toggle_targ = res['toggleTarg', '']

    beam_conf = res.find_key('BeamKeys', or_blank=True)
    glow_conf = res.find_key('GlowKeys', or_blank=True)
    cable_conf = res.find_key('CableKeys', or_blank=True)

    if beam_conf:
        # Grab a copy of the beam spawnflags, so we can set our own options.
        conf_beam_flags = beam_conf.int('spawnflags')
        # Mask out certain flags.
        conf_beam_flags &= (
            0
            | 1  # Start On
            | 2  # Toggle
            | 4  # Random Strike
            | 8  # Ring
            | 16  # StartSparks
            | 32  # EndSparks
            | 64  # Decal End
            #| 128  # Shade Start
            #| 256  # Shade End
            #| 512  # Taper Out
        )
    else:
        conf_beam_flags = 0

    conf_outputs = [
        Output.parse(kv)
        for kv in res
        if kv.name in ('onenabled', 'ondisabled')
    ]

    # Find all the markers.
    nodes: dict[str, Node] = {}

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        name = inst['targetname']
        if filename in conf_inst_laser:
            node_type = NodeType.LASER
        elif filename in conf_inst_corner:
            node_type = NodeType.CORNER
        else:
            continue

        try:
            # Remove the item - it's no longer going to exist after
            # we're done.
            item = connections.ITEMS.pop(name)
        except KeyError:
            raise ValueError(f'No item for "{name}"?') from None
        pos = Vec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])
        if node_type is NodeType.CORNER:
            timer_delay = item.inst.fixup.int('$timer_delay')
            # We treat inf, 1, 2 and 3 as the same, to get around the 1 and 2 not
            # being selectable issue.
            pos = CORNER_POS[max(0, timer_delay - 3) % 8] @ orient + pos
        nodes[name] = Node(node_type, inst, item, pos, orient)

    if not nodes:
        # None at all.
        return conditions.RES_EXHAUSTED

    # Now find every connected group, recording inputs, outputs and links.
    todo = set(nodes.values())

    groups: list[Group] = []

    while todo:
        start = todo.pop()
        # Synthesise the Item used for logic.
        # We use a random info_target to manage the IO data.
        group = Group(start, start.type)
        groups.append(group)
        for node in group.nodes:
            # If this node has no non-node outputs, destroy the antlines.
            has_output = False
            node.is_grouped = True

            for conn in list(node.item.outputs):
                neighbour = conn.to_item
                neigh_node = nodes.get(neighbour.name, None)
                todo.discard(neigh_node)
                if neigh_node is None or neigh_node.type is not node.type:
                    # Not a node or different item type, it must therefore
                    # be a target of our logic.
                    conn.from_item = group.item
                    has_output = True
                    continue
                elif not neigh_node.is_grouped:
                    # Another node.
                    group.nodes.append(neigh_node)
                # else: True, node already added.

                # For nodes, connect link.
                conn.remove()
                group.links.add(frozenset({node, neigh_node}))

            # If we have a real output, we need to transfer it.
            # Otherwise, we can just destroy it.
            if has_output:
                node.item.transfer_antlines(group.item)
            else:
                node.item.delete_antlines()

            # Do the same for inputs, so we can catch that.
            for conn in list(node.item.inputs):
                neighbour = conn.from_item
                neigh_node = nodes.get(neighbour.name, None)
                todo.discard(neigh_node)
                if neigh_node is None or neigh_node.type is not node.type:
                    # Not a node or different item type, it must therefore
                    # be a target of our logic.
                    conn.to_item = group.item
                    node.had_input = True
                    continue
                elif not neigh_node.is_grouped:
                    # Another node.
                    group.nodes.append(neigh_node)
                # else: True, node already added.

                # For nodes, connect link.
                conn.remove()
                group.links.add(frozenset({neigh_node, node}))

    # Now every node is in a group. Generate the actual entities.
    for group in groups:
        # We generate two ent types. For each marker, we add a sprite
        # and a beam pointing at it. Then for each connection
        # another beam.

        # Choose a random item name to use for our group.
        base_name = group.nodes[0].item.name

        out_enable = [Output('', '', 'FireUser2')]
        out_disable = [Output('', '', 'FireUser1')]
        if group.type is NodeType.LASER:
            for output in conf_outputs:
                if output.output.casefold() == 'onenabled':
                    out_enable.append(output.copy())
                else:
                    out_disable.append(output.copy())

        group.item.enable_cmd = tuple(out_enable)
        group.item.disable_cmd = tuple(out_disable)

        if group.type is NodeType.LASER and conf_toggle_targ:
            # Make the group info_target into a texturetoggle.
            toggle = group.item.inst
            toggle['classname'] = 'env_texturetoggle'
            toggle['target'] = conditions.local_name(group.nodes[0].inst, conf_toggle_targ)

        # Node -> index for targetnames.
        indexes: dict[Node, int] = {}

        # For antline corners, the antline segments.
        segments: list[antlines.Segment] = []

        # frozenset[Node] unpacking isn't clear.
        node_a: Node
        node_b: Node

        if group.type is NodeType.CORNER:
            for node_a, node_b in group.links:
                # Place a straight antline between each connected node.
                # If on the same plane, we only need one. If not, we need to
                # do one for each plane it's in.
                offset = node_b.pos - node_a.pos
                up_a = node_a.orient.up()
                up_b = node_b.orient.up()
                plane_a = Vec.dot(node_a.pos, up_a)
                plane_b = Vec.dot(node_b.pos, up_b)
                if Vec.dot(up_a, up_b) > 0.9:
                    if abs(plane_a - plane_b) > 1e-6:
                        LOGGER.warning(
                            'Antline corners "{}" - "{}" '
                            'are on different planes',
                            node_a.item.name, node_b.item.name,
                        )
                        continue
                    u = node_a.orient.left()
                    v = node_a.orient.forward()
                    # Which are we aligned to?
                    if abs(Vec.dot(offset, u)) < 1e-6 or abs(Vec.dot(offset, v)) < 1e-6:
                        forward = offset.norm()
                        group.add_ant_straight(
                            up_a,
                            node_a.pos + 8.0 * forward,
                            node_b.pos - 8.0 * forward,
                        )
                    else:
                        LOGGER.warning(
                            'Antline corners "{}" - "{}" '
                            'are not directly aligned',
                            node_a.item.name, node_b.item.name,
                        )
                else:
                    # We expect them be aligned to each other.
                    side = Vec.cross(up_a, up_b)
                    if abs(Vec.dot(side, offset)) < 1e-6:
                        mid1 = node_a.pos + Vec.dot(offset, up_b) * up_b
                        mid2 = node_b.pos - Vec.dot(offset, up_a) * up_a
                        if mid1 != mid2:
                            LOGGER.warning(
                                'Midpoint mismatch: {} != {} for "{}" - "{}"',
                                mid1, mid2,
                                node_a.item.name, node_b.item.name,
                            )
                        group.add_ant_straight(
                            up_a,
                            node_a.pos + 8.0 * (mid1 - node_a.pos).norm(),
                            mid1,
                        )
                        group.add_ant_straight(
                            up_b,
                            node_b.pos + 8.0 * (mid2 - node_b.pos).norm(),
                            mid2,
                        )

        # For cables, it's a bit trickier than the beams.
        # The cable ent itself is the one which decides what it links to,
        # so we need to potentially make endpoint cables at locations with
        # only "incoming" lines.
        # So this dict is either a targetname to indicate cables with an
        # outgoing connection, or the entity for endpoints without an outgoing
        # connection.
        cable_points: dict[Node, Union[Entity, str]] = {}

        for i, node in enumerate(group.nodes, start=1):
            indexes[node] = i
            node.item.name = base_name

            if group.type is NodeType.CORNER:
                node.inst.remove()
                # Figure out whether we want a corner at this point, or
                # just a regular dot. If a non-node input was provided it's
                # always a corner. Otherwise, it's one if there's an L, T or X
                # junction.
                use_corner = True
                norm = node.orient.up().as_tuple()
                if not node.had_input:
                    neighbors = [
                        mag * direction for direction in [
                            node.orient.forward(),
                            node.orient.left(),
                        ] for mag in [-8.0, 8.0]
                        if ((node.pos + mag * direction).as_tuple(), norm) in group.ant_seg
                    ]
                    if len(neighbors) == 2:
                        [off1, off2] = neighbors
                        if Vec.dot(off1, off2) < -0.99:
                            # ---o---, merge together. The endpoints we want
                            # are the other ends of the two segments.
                            group.add_ant_straight(
                                node.orient.up(),
                                group.rem_ant_straight(norm, node.pos + off1),
                                group.rem_ant_straight(norm, node.pos + off2),
                            )
                            use_corner = False
                    elif len(neighbors) == 1:
                        # o-----, merge.
                        [offset] = neighbors
                        group.add_ant_straight(
                            node.orient.up(),
                            group.rem_ant_straight(norm, node.pos + offset),
                            node.pos - offset,
                        )
                        use_corner = False
                if use_corner:
                    segments.append(antlines.Segment(
                        antlines.SegType.CORNER,
                        round(node.orient.up(), 3),
                        Vec(node.pos),
                        Vec(node.pos),
                    ))
            elif group.type is NodeType.LASER:
                sprite_pos = node.pos + conf_glow_height @ node.orient

                if glow_conf:
                    # First add the sprite at the right height.
                    sprite = vmf.create_ent('env_sprite')
                    for kv in glow_conf:
                        sprite[kv.name] = node.inst.fixup.substitute(kv.value)

                    sprite['origin'] = sprite_pos
                    sprite['targetname'] = NAME_SPR(base_name, i)
                elif beam_conf:
                    # If beams but not sprites, we need a target.
                    vmf.create_ent(
                        'info_target',
                        origin=sprite_pos,
                        targetname=NAME_SPR(base_name, i),
                    )

                if beam_conf:
                    # Now the beam going from below up to the sprite.
                    beam_pos = node.pos + conf_las_start @ node.orient
                    beam = vmf.create_ent('env_beam')
                    for kv in beam_conf:
                        beam[kv.name] = node.inst.fixup.substitute(kv.value)

                    beam['origin'] = beam['targetpoint'] = beam_pos
                    beam['targetname'] = NAME_BEAM_LOW(base_name, i)
                    beam['LightningStart'] = beam['targetname']
                    beam['LightningEnd'] = NAME_SPR(base_name, i)
                    beam['spawnflags'] = conf_beam_flags | 128  # Shade Start

        segments += set(group.ant_seg.values())
        if group.type is NodeType.CORNER and segments:
            group.item.antlines.add(antlines.Antline(group.item.name + '_antline', segments))

        if group.type is NodeType.LASER and beam_conf:
            for i, (node_a, node_b) in enumerate(group.links):
                beam = vmf.create_ent('env_beam')
                conditions.set_ent_keys(beam, node_a.inst, res, 'BeamKeys')
                beam['origin'] = beam['targetpoint'] = node_a.pos
                beam['targetname'] = NAME_BEAM_CONN(base_name, i)
                beam['LightningStart'] = NAME_SPR(base_name, indexes[node_a])
                beam['LightningEnd'] = NAME_SPR(base_name, indexes[node_b])
                beam['spawnflags'] = conf_beam_flags

        if group.type is NodeType.LASER and cable_conf:
            build_cables(
                vmf,
                group,
                cable_points,
                base_name,
                beam_conf,
                conf_rope_off,
            )

    return conditions.RES_EXHAUSTED


def build_cables(
    vmf: VMF,
    group: Group,
    cable_points: dict[Node, Union[Entity, str]],
    base_name: str,
    beam_conf: Keyvalues,
    conf_rope_off: Vec,
) -> None:
    """Place Old-Aperture style cabling."""
    # We have a couple different situations to deal with here.
    # Either end could Not exist, be Unlinked, or be Linked = 8 combos.
    # We may want to flip to ensure we always are connecting A to B.
    # AB |
    # NN | Make 2 new ones, one is an endpoint.
    # NU | Flip, do UN.
    # NL | Make A, link A to B. Both are linked.
    # UN | Make B, link A to B. B is unlinked.
    # UU | Link A to B, A is now linked, B is unlinked.
    # UL | Link A to B. Both are linked.
    # LN | Flip, do NL.
    # LU | Flip, do UL
    # LL | Make A, link A to B. Both are linked.
    rope_ind = 0  # Uniqueness value.
    node_a: Node
    node_b: Node
    rope_a: Entity
    rope_b: Entity
    for node_a, node_b in group.links:
        state_a, ent_a = RopeState.from_node(cable_points, node_a)
        state_b, ent_b = RopeState.from_node(cable_points, node_b)

        if (state_a is RopeState.LINKED
            or (state_a is RopeState.NONE and
                state_b is RopeState.UNLINKED)):
            # Flip these, handle the opposite order.
            state_a, state_b = state_b, state_a
            ent_a, ent_b = ent_b, ent_a
            node_a, node_b = node_b, node_a

        pos_a = node_a.pos + conf_rope_off @ node_a.orient
        pos_b = node_b.pos + conf_rope_off @ node_b.orient

        # Need to make the A rope if we don't have one that's unlinked.
        if state_a is not RopeState.UNLINKED:
            rope_a = vmf.create_ent('move_rope')
            for kv in beam_conf:
                rope_a[kv.name] = node_a.inst.fixup.substitute(kv.value)
            rope_a['origin'] = pos_a
            rope_ind += 1
            rope_a['targetname'] = NAME_CABLE(base_name, rope_ind)
        else:
            # It is unlinked, so it's the rope to use.
            assert isinstance(ent_a, Entity)
            rope_a = ent_a

        # Only need to make the B rope if it doesn't have one.
        if state_b is RopeState.NONE:
            rope_b = vmf.create_ent('move_rope')
            for kv in beam_conf:
                rope_b[kv.name] = node_b.inst.fixup.substitute(kv.value)
            rope_b['origin'] = pos_b
            rope_ind += 1
            name_b = rope_b['targetname'] = NAME_CABLE(base_name, rope_ind)

            cable_points[node_b] = rope_b  # Someone can use this.
        elif state_b is RopeState.UNLINKED:
            # Both must be unlinked, we aren't using this link though.
            assert isinstance(ent_b, Entity)
            name_b = ent_b['targetname']
        else:  # Linked, we just have the name.
            name_b = ent_b['targetname'] if isinstance(ent_b, Entity) else ent_b

        # By here, rope_a should be an unlinked rope,
        # and name_b should be a name to link to.
        rope_a['nextkey'] = name_b

        # Figure out how much slack to give.
        # If on floor, we need to be taut to have clearance.
        if node_a.on_floor or node_b.on_floor:
            rope_a['slack'] = 60
        else:
            rope_a['slack'] = 125

        # We're always linking A to B, so A is always linked!
        if state_a is not RopeState.LINKED:
            cable_points[node_a] = rope_a['targetname']
