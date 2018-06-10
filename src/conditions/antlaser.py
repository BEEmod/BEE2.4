"""Implement Konclan's AntLaser item.
"""
from typing import Dict, List, Tuple, Set, Optional, Callable

import conditions
import instanceLocs
import utils
from conditions import make_result
import connections
from connections import Item
from srctools import VMF, Property, Output, Vec


COND_MOD_NAME = None

LOGGER = utils.getLogger(__name__, alias='cond.antlaser')

AntLaserType = connections.ItemType(
    '<AntLaser>',
    input_type=connections.InputType.OR,
    output_act=(None, 'OnUser2'),
    output_deact=(None, 'OnUser1'),
)

NAME_SPR = '{}-sprite_{}'.format  # type: Callable[[str, int], str]
NAME_BEAM_LOW = '{}-beam_low_{}'.format  # type: Callable[[str, int], str]
NAME_BEAM_CONN = '{}-beam_conn_{}'.format  # type: Callable[[str, int], str]


class Group:
    """Represents a group of markers."""
    def __init__(self, start: Item):
        self.nodes = [start]  # type: List[Item]
        self.links = set()  # type: Set[Tuple[Item, Item]]
        # Create the item for the entire group of markers.
        logic_ent = start.inst.map.create_ent(
            'info_target',
            origin=start.inst['origin'],
            targetname=start.name,
        )
        self.item = Item(
            logic_ent,
            AntLaserType,
            start.ant_floor_style,
            start.ant_wall_style,
        )
        connections.ITEMS[self.item.name] = self.item


@make_result('AntLaser')
def res_antlaser(vmf: VMF, res: Property):
    """The condition to generate AntLasers.

    This is executed once to modify all instances.
    """
    conf_inst = instanceLocs.resolve(res['instance'])
    conf_glow_height = Vec(z=res.float('GlowHeight', 48) - 64)
    conf_las_start = Vec(z=res.float('LasStart') - 64)
    # Grab a copy of the beam spawnflags so we can set our own options.
    conf_beam_flags = res.find_key('BeamKeys', []).int('spawnflags')
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
    conf_outputs = [
        Output.parse(prop)
        for prop in res
        if prop.name in ('onenabled', 'ondisabled')
    ]

    # Find all the markers.
    nodes = {}  # type: Dict[str, Item]

    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in conf_inst:
            continue
        name = inst['targetname']
        try:
            # Remove the item - it's no longer going to exist after
            # we're done.
            nodes[name] = connections.ITEMS.pop(name)
        except KeyError:
            raise ValueError('No item for "{}"?'.format(name)) from None

    # Now find every connected group, recording inputs, outputs and links.
    todo = set(nodes.values())

    groups = []  # type: List[Group]

    # Node -> is grouped already.
    node_pairing = dict.fromkeys(nodes.values(), False)

    while todo:
        start = todo.pop()
        # Synthesise the Item used for logic.
        # We use a random info_target to manage the IO data.
        group = Group(start)
        groups.append(group)
        for node in group.nodes:
            # If this node has no non-node outputs, destroy the antlines.
            has_output = False
            node_pairing[node] = True

            for conn in list(node.outputs):
                neighbour = conn.to_item
                todo.discard(neighbour)
                pair_state = node_pairing.get(neighbour, None)
                if pair_state is None:
                    # Not a node, a target of our logic.
                    conn.from_item = group.item
                    has_output = True
                    continue
                elif pair_state is False:
                    # Another node.
                    group.nodes.append(neighbour)
                # else: True, node already added.

                # For nodes, connect link.
                conn.remove()
                group.links.add((node, neighbour))

            # If we have a real output, we need to transfer it.
            # Otherwise we can just destroy it.
            if has_output:
                group.item.antlines.update(node.antlines)
                group.item.ind_panels.update(node.ind_panels)
                group.item.shape_signs.extend(node.shape_signs)
            else:
                node.delete_antlines()

            # Do the same for inputs, so we can catch that.
            for conn in list(node.inputs):
                neighbour = conn.from_item
                todo.discard(neighbour)
                pair_state = node_pairing.get(neighbour, None)
                if pair_state is None:
                    # Not a node, an input to the group.
                    conn.to_item = group.item
                    continue
                elif pair_state is False:
                    # Another node.
                    group.nodes.append(neighbour)
                # else: True, node already added.

                # For nodes, connect link.
                conn.remove()
                group.links.add((neighbour, node))

    # Now every node is in a group. Generate the actual entities.
    for group in groups:
        # We generate two ent types. For each marker, we add a sprite
        # and a beam pointing at it. Then for each connection
        # another beam.

        # Choose a random antlaser name to use for our group.
        base_name = group.nodes[0].name

        out_enable = [Output('', '', 'FireUser2')]
        out_disable = [Output('', '', 'FireUser1')]
        for output in conf_outputs:
            if output.output.casefold() == 'onenabled':
                out_enable.append(output.copy())
            else:
                out_disable.append(output.copy())

        group.item.enable_cmd = tuple(out_enable)
        group.item.disable_cmd = tuple(out_disable)

        # Node -> index for targetnames.
        indexes = {}  # type: Dict[Item, int]

        for i, node in enumerate(group.nodes, start=1):
            indexes[node] = i
            node.name = base_name

            # First add the sprite at the right height.
            sprite_pos = conf_glow_height.copy()
            sprite_pos.localise(
                Vec.from_str(node.inst['origin']),
                Vec.from_str(node.inst['angles']),
            )
            sprite = vmf.create_ent('env_sprite')
            conditions.set_ent_keys(sprite, node.inst, res, 'GlowKeys')
            sprite['origin'] = sprite_pos
            sprite['targetname'] = NAME_SPR(base_name, i)

            # Now the beam going from below up to the sprite.
            beam_pos = conf_las_start.copy()
            beam_pos.localise(
                Vec.from_str(node.inst['origin']),
                Vec.from_str(node.inst['angles']),
            )
            beam = vmf.create_ent('env_beam')
            conditions.set_ent_keys(beam, node.inst, res, 'BeamKeys')
            beam['origin'] = beam_pos
            beam['targetname'] = NAME_BEAM_LOW(base_name, i)
            beam['LightningStart'] = beam['targetname']
            beam['LightningEnd'] = NAME_SPR(base_name, i)
            beam['spawnflags'] = conf_beam_flags | 128  # Shade Start

        for i, (node1, node2) in enumerate(group.links):
            beam = vmf.create_ent('env_beam')
            conditions.set_ent_keys(beam, node1.inst, res, 'BeamKeys')
            beam['origin'] = node1.inst['origin']
            beam['targetname'] = NAME_BEAM_CONN(base_name, i)
            beam['LightningStart'] = NAME_SPR(base_name, indexes[node1])
            beam['LightningEnd'] = NAME_SPR(base_name, indexes[node2])
            beam['spawnflags'] = conf_beam_flags

    return conditions.RES_EXHAUSTED
