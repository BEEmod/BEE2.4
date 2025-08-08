"""Items dealing with antlines - Antline Corners and Antlasers."""
from typing import Literal, assert_never

from collections.abc import Callable
from enum import Enum

import attrs
import srctools.logger
from srctools import FrozenVec, VMF, Keyvalues, Output, Vec, Entity, Matrix, FrozenMatrix

from precomp import instanceLocs, connections, conditions, antlines
import user_errors


COND_MOD_NAME: str | None = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.antlines')

# Antlasers have their own visuals, so they need an item to stay.
CONFIG_ANTLASER = connections.Config(
    connections.ID_ANTLASER,
    input_type=connections.InputType.OR,
    output_act=(None, 'OnUser2'),
    output_deact=(None, 'OnUser1'),
)
# But antline corners just place antlines, and can collapse into other items.
CONFIG_ANTLINE = connections.Config(
    '<ANTLINE>',
    input_type=connections.InputType.OR_LOGIC,
)

# Preconfigured format strings for all the names we generate. Centralises the naming format.
NAME_SPR: Callable[[str, int | Literal['*']], str] = '{}-fx_sp_{}'.format
NAME_BEAM_LOW: Callable[[str, int], str] = '{}-fx_b_low_{}'.format
NAME_BEAM_CONN: Callable[[str, int], str] = '{}-fx_b_conn_{}'.format
NAME_ALL_FX: Callable[[str], str] = '{}-fx_*'.format
NAME_ALL_BEAM: Callable[[str], str] = '{}-fx_b_*'.format
NAME_CABLE: Callable[[str, int], str] = '{}-cab_{}'.format
NAME_MODEL: Callable[[str], str] = '{}-mdl'.format


# The configuration for each timer delay value. This starts at delay=3.
# Vecs are corners, and define the offset in the model. The y-off/matrix tuple is a checkmark.
TIMER_VALUES: list[FrozenVec | tuple[float, FrozenMatrix]] = [
    FrozenVec(8.0, 56.0, -64.0),
    FrozenVec(8.0, 40.0, -64.0),
    FrozenVec(8.0, 24.0, -64.0),
    FrozenVec(8.0, 8.0, -64.0),
    FrozenVec(-8.0, 56.0, -64.0),
    FrozenVec(-8.0, 40.0, -64.0),
    FrozenVec(-8.0, 24.0, -64.0),
    FrozenVec(-8.0, 8.0, -64.0),
    (16.0, FrozenMatrix.from_yaw(180)),
    (16.0, FrozenMatrix.from_yaw(270)),
    (16.0, FrozenMatrix.from_yaw(0)),
    (16.0, FrozenMatrix.from_yaw(90)),
    (48.0, FrozenMatrix.from_yaw(180)),
    (48.0, FrozenMatrix.from_yaw(270)),
    (48.0, FrozenMatrix.from_yaw(0)),
    (48.0, FrozenMatrix.from_yaw(90)),
]


class NodeType(Enum):
    """Handle the types of item."""
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
    def from_node(points: dict[Node, Entity | str], node: Node) -> tuple['RopeState', Entity | str]:
        """Compute the state and ent/name from the points data."""
        try:
            ent = points[node]
        except KeyError:
            return RopeState.NONE, ''
        if isinstance(ent, str):
            return RopeState.LINKED, ent
        else:
            return RopeState.UNLINKED, ent


def make_dummy_conn_item(orig_item: connections.Item, pos: Vec, conf: connections.Config) -> connections.Item:
    """Create a logic item for the antline group."""
    # Create a comp_relay to attach I/O to.
    logic_ent = orig_item.inst.map.create_ent(
        'comp_relay',
        origin=pos,
        targetname=orig_item.name,
        # Must be != to be enabled.
        ctrl_type='1',
        ctrl_value='0',
    )

    # Create the item for the entire group of markers.
    item = connections.Item(
        logic_ent, conf,
        ind_style=orig_item.ind_style,
    )
    connections.ITEMS[item.name] = item
    return item


class Group:
    """Represents a group of markers."""
    type: NodeType
    item: connections.Item
    nodes: list[Node]
    # We use a frozenset here to ensure we don't double-up the links -
    # users might accidentally do that.
    links: set[frozenset[Node]]
    # For antline corners, each endpoint + normal -> the segment
    ant_seg: dict[tuple[FrozenVec, FrozenVec], antlines.Segment]

    def __init__(self, start: Node, typ: NodeType) -> None:
        self.type = typ  # Antlaser or corner?
        self.nodes = [start]
        self.links = set()
        self.ant_seg = {}

        # The corners have an origin on the floor whereas lasers are normal.
        if typ is NodeType.CORNER:
            logic_pos = start.pos + 8 * start.orient.up()
            logic_conf = CONFIG_ANTLINE
        else:
            logic_pos = start.pos - 56 * start.orient.up()
            logic_conf = CONFIG_ANTLASER

        self.item = make_dummy_conn_item(start.item, logic_pos, logic_conf)

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
        norm_key = seg.normal.freeze()
        k1 = pos1.freeze(), norm_key
        k2 = pos2.freeze(), norm_key
        if k1 in self.ant_seg:
            LOGGER.warning('Antline segment overlap: {}', k1)
        if k2 in self.ant_seg:
            LOGGER.warning('Antline segment overlap: {}', k2)
        self.ant_seg[k1] = seg
        self.ant_seg[k2] = seg

    def rem_ant_straight(self, norm: FrozenVec, endpoint: Vec) -> Vec:
        """Remove an antline segment with this enpoint, and return its other.

        This is used for merging corners. We already checked it's valid.
        """
        seg = self.ant_seg.pop((endpoint.freeze(), norm))
        if seg.start == endpoint:
            del self.ant_seg[seg.end.freeze(), norm]
            return seg.end
        elif seg.end == endpoint:
            del self.ant_seg[seg.start.freeze(), norm]
            return seg.start
        else:
            raise ValueError(f'Antline {seg} has no endpoint {endpoint}!')


@conditions.make_result('AntLaser', valid_before=conditions.MetaCond.Connections)
def res_antlaser(vmf: VMF, res: Keyvalues) -> object:
    """The condition to generate AntLasers and Antline Corners.

    This is executed once to modify all instances.
    Parameters are all for antlasers, the corner follows the style definition:
    * GlowKeys: Keyvalues for a glow env_sprite generated at each node. If absent, none are added.
    * GlowHeight: Distance above the floor to generate the glow sprite, if present.
    * BeamKeys: Keyvalues for the env_beams generated to connect nodes. If absent, none are added.
    * LasStart: Distance above the floor to position each beam, if present.
    * CableKeys: Keyvalues for the move_ropes generated to connect nodes. If absent, none are added.
    * RopePos: Instance-local offset for each rope.
    * on_state, off_state: Antline states (except for tex_frame), used to specify the default behaviours.

    In the instance, the emitter model must be named `mdl`, and have `$skin`/`$skinset` fixups.
    """
    # The original antline corner item, which only allows corners and loops values.
    conf_inst_ant_legacy = instanceLocs.resolve_filter('<item_bee2_antline_corner>', silent=True)
    # The new item, which produces corners and checkmarks, with additional indexes reserved.
    conf_inst_antline = instanceLocs.resolve_filter('<item_bee2_antline>', silent=True)
    conf_inst_laser = instanceLocs.resolve_filter(res['instance'])
    conf_glow_height = Vec(z=res.float('GlowHeight', 48) - 64)
    conf_las_start = Vec(z=res.float('LasStart') - 64)
    conf_rope_off = res.vec('RopePos')

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
            # 128 - Shade Start
            # 256 - Shade End
            # 512 - Taper Out
        )
    else:
        conf_beam_flags = 0

    # State configurations used when no custom ones are defined.
    # Initial state (off) must be first!
    default_off_state = attrs.evolve(
        antlines.State.parse(res.find_block('off_state')),
        name='off_rl',
    )
    default_states = [default_off_state, attrs.evolve(
            antlines.State.parse(res.find_block('on_state')),
            name='on_rl',
        )
    ]
    # Find all the markers.
    nodes: dict[str, Node] = {}
    checkmarks: dict[connections.Item, Entity] = {}

    for inst in vmf.by_class['func_instance']:
        filename = inst['file'].casefold()
        name = inst['targetname']
        if filename in conf_inst_laser:
            node_type = NodeType.LASER
            legacy = False
        elif filename in conf_inst_ant_legacy:
            node_type = NodeType.CORNER
            legacy = True
        elif filename in conf_inst_antline:
            node_type = NodeType.CORNER
            legacy = False
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
            # We treat inf, 1, 2 and 3 as the same, to get around the 1 and 2 not
            # being selectable issue.
            timer_delay = item.inst.fixup.int('$timer_delay')
            timer_ind = max(0, timer_delay - 3)
            if legacy:
                # Only the corners are available, the rest loop.
                timer_ind %= 8
            try:
                timer_val = TIMER_VALUES[timer_ind]
            except IndexError:
                raise user_errors.UserError(
                    user_errors.TOK_ANTLINE_INVALID_TIMER.format(value=timer_delay),
                    points=[(point @ orient + pos) for point in TIMER_VALUES if isinstance(point, FrozenVec)],
                ) from None
            match timer_val:
                case FrozenVec() as ant_pos:
                    # Antline Corner
                    pos = (ant_pos @ orient + pos).thaw()
                case (float() as check_off, FrozenMatrix() as check_orient):
                    # Checkmark. Reposition, we only need a Y-offset.
                    # The connections module will set the filename later.
                    inst['origin'] = orient.left(check_off) + pos
                    inst['angles'] = (check_orient @ orient).to_angle()
                    checkmarks[item] = inst
                    continue
                case never:
                    assert_never(never)
        nodes[name] = Node(node_type, inst, item, pos, orient)

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
                if neigh_node is not None:
                    todo.discard(neigh_node)
                if neigh_node is None or neigh_node.type is not node.type:
                    # Not a node or different item type, it must therefore
                    # be a target of our logic. Reconnect, and preserve antlines
                    # if it's not a checkmark
                    conn.from_item = group.item
                    if neighbour not in checkmarks:
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
                if neigh_node is not None:
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

    # Setup each checkmark. If they have exactly 1 input, we move them into the caller so they
    # inherit timer values. Otherwise, they become an OR gate with a dummy item. Either way,
    # all the inputs and outputs need to be moved off the old item.
    for item, inst in checkmarks.items():
        try:
            [conn] = item.inputs
        except ValueError:
            logic_item = make_dummy_conn_item(item, Vec.from_str(inst['origin']), CONFIG_ANTLINE)
            inst['targetname'] += '_panel'
            logic_item.ind_panels.add(inst)
            for conn in list(item.inputs):
                conn.to_item = logic_item
        else:
            logic_item = conn.from_item
            logic_item.ind_panels.add(inst)
            conn.remove()
            LOGGER.debug('Transferring antline panel {} -> item {}', inst, logic_item)
        for conn in list(item.outputs):
            conn.from_item = logic_item

    # Now every node is in a group. Generate the actual entities.
    for group in groups:
        # We generate two ent types. For each marker, we add a sprite
        # and a beam pointing at it. Then for each connection
        # another beam.

        # Choose a random item name to use for our group.
        base_name = group.nodes[0].item.name

        inp_styles = {conn.from_item.ind_style for conn in group.item.inputs}
        if len(inp_styles) == 1:  # Common style, switch to that.
            [group.item.ind_style] = inp_styles

        states = group.item.ind_style.states or default_states
        initial_state = group.item.ind_style.initial_state

        # These trigger the output when we activate.
        out_enable = [Output('', '', 'FireUser2')]
        out_disable = [Output('', '', 'FireUser1')]
        if states is default_states:
            # Add in outputs to trigger default states.
            out_enable.append(Output('', 'on_rl', 'Trigger'))
            out_disable.append(Output('', 'off_rl', 'Trigger'))
            inp_items = {group.item}
            initial_state = default_off_state
        else:
            inp_items = {
                conn.from_item for conn in group.item.inputs
            }
            assert initial_state is not None, "No initial state defined but states defined??"
            # Single item with custom antlines, transfer it there so that handles them.
            # Sorta a hack, but we only change indicators if the input is also common.
            if len(inp_items) == 1:
                [inp_item] = inp_items
                group.item.transfer_antlines(inp_item)

        group.item.enable_cmd = tuple(out_enable)
        group.item.disable_cmd = tuple(out_disable)

        if group.type is NodeType.LASER:
            skinset = set()
            for state in states:
                state_out = [
                    Output('OnTrigger', NAME_MODEL(base_name), 'Skin', state.antlaser_skin),
                ]
                skinset.add(str(state.antlaser_skin))
                # We have both and they're set to the same value, can fire all at once.
                if beam_conf and glow_conf and state.beam_colour == state.glow_colour:
                    state_out.append(Output(
                        'OnTrigger', NAME_ALL_FX(base_name),
                        'Color', state.beam_colour,
                    ))
                else:
                    if beam_conf:
                        state_out.append(Output(
                            'OnTrigger', NAME_ALL_BEAM(base_name),
                            'Color', state.beam_colour,
                        ))
                    if glow_conf:
                        state_out.append(Output(
                            'OnTrigger', NAME_SPR(base_name, '*'),
                            'Color', state.beam_colour,
                        ))
                for item in inp_items:
                    relay = item.get_ind_state_relay(state.name)
                    for out in state_out:
                        relay.add_out(out.copy())

            model_name = group.item.ind_style.antlaser_model
            if model_name:
                vmf.create_ent(
                    'comp_kv_setter',
                    origin=group.nodes[0].inst['origin'],
                    target=NAME_MODEL(base_name),
                    mode='kv',
                    kv_name='model',
                    kv_value_global=model_name,
                )
            skinset_str = ' '.join(sorted(skinset))
            for node in group.nodes:
                # Skinset must be second, otherwise skin will substitute first.
                node.inst.fixup['$skin'] = initial_state.antlaser_skin
                node.inst.fixup['$skinset'] = skinset_str

        # For corners, states are applied during regular connection generation.

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
        cable_points: dict[Node, Entity | str] = {}

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
                norm = node.orient.up().freeze()
                if not node.had_input:
                    neighbors = [
                        mag * direction for direction in [
                            node.orient.forward(),
                            node.orient.left(),
                        ] for mag in [-8.0, 8.0]
                        if ((node.pos + mag * direction).freeze(), norm) in group.ant_seg
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
                    if initial_state.glow_colour:
                        sprite['rendercolor'] = initial_state.glow_colour

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
                    if initial_state.beam_colour:
                        beam['rendercolor'] = initial_state.glow_colour

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
                if initial_state.beam_colour:
                    beam['rendercolor'] = initial_state.glow_colour

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
    cable_points: dict[Node, Entity | str],
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
    name_b: str
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
