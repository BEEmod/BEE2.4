"""Implements a condition which allows linking items into a sequence."""
from __future__ import annotations
from typing import Optional, Callable
from enum import Enum
import math

import attrs
from srctools import Property, VMF, Entity
import srctools.logger

from precomp import instanceLocs, item_chain, conditions


COND_MOD_NAME = 'Item Linkage'
LOGGER = srctools.logger.get_logger(__name__, alias='cond.linkedItem')


class AntlineHandling(Enum):
    """How to handle antlines."""
    REMOVE = 'remove'
    KEEP = 'keep'
    MOVE = 'move'


@attrs.define
class Config:
    """Configuration for linked items."""
    group: str  # For reporting.
    logic_start: Optional[str]
    logic_mid: Optional[str]
    logic_end: Optional[str]
    logic_loop: Optional[str]

    antline: AntlineHandling
    allow_loop: bool
    transfer_io: bool

    # Special feature for unstationary scaffolds. This is rotated to face
    # the next track!
    scaff_endcap: Optional[str]
    # If it's allowed to point any direction, not just 90 degrees.
    scaff_endcap_free_rot: bool


def resolve_optional(prop: Property, key: str) -> str:
    """Resolve the given instance, or return '' if not defined."""
    try:
        file = prop[key]
    except LookupError:
        return ''
    return instanceLocs.resolve_one(file, error=False) or ''

# Store the nodes for items so we can join them up later.
ITEMS_TO_LINK: dict[str, list[item_chain.Node[Config]]] = {}


@conditions.make_result('LinkedItem')
def res_linked_item(res: Property) -> Callable[[Entity], None]:
    """Marks the current instance for linkage together into a chain.

    At priority level -300, the sequence of similarly-marked items this links
    to is grouped together, and given fixup values to allow linking them.

    Every instance has `$type` set to `loop`, `start`, `mid` or `end` depending on its role.
    For each group of linked items, `$group` is set to a unique number. Then for each item, `$ind`
    is set to a unique index (starting at 1), and if it is not an endpoint `$next` is set to the
    index of the next item. This should be used by naming items `@itemtype_track_$group_$ind`, and
    then connecting that to `@itemtype_track_$group_$next`. See the Unstationary Scaffold package
    for an example usage.

    Parameters:
    * Group: Should be set to a unique name. All calls with this name can be
      linked together. If not used, only this specific result call will link.
    * AllowLoop: If true, allow constructing a loop of items. In this situation, the
      indexes will start at some item at random, and proceed around. The last will then
      link to the first.
    * TransferIO: If true (default), all inputs and outputs are transferred to the first
      item (index = 1). This instance can then forward the results to the other items in the group.
    * StartLogic/MidLogic/EndLogic/LoopLogic: These instances will be overlaid on the
      instance, depending on whether it starts/ends or is in the middle of the
      path. If the item loops, all use LoopLogic.
    * Antlines: Controls what happens to antlines linking between the items.
      If one of the items outputs to a non-linked item, those antlines must be
      kept. Three behaviours are available:
      * `remove` (default): Completely remove the antlines.
      * `keep`: Leave them untouched.
      * `move`: Move them all to the first item.
    * EndcapInst: Special instance for Unstationary Scaffolds. If the item is
      facing upwards, and is the end for a mostly horizontal beam it is switched
      to this instance, and rotated to face towards the previous track.
    * endcap_free_rotate: If true, the endcap can point in any angle, otherwise
      it points in the nearest 90 degree angle.
    """
    try:
        group = res['group'].casefold()
    except LookupError:
        # No group defined, make it specific to this result.
        group = format(id(res), '016X')

    try:
        group_list = ITEMS_TO_LINK[group]
    except KeyError:
        group_list = ITEMS_TO_LINK[group] = []

    antline_str = res['antlines', res['antline', 'remove']]
    try:
        antline = AntlineHandling(antline_str.casefold())
    except ValueError:
        raise ValueError(
            f'Unknown antline behaviour "{antline_str}" '
            f'(accepted: {", ".join(AntlineHandling)})'
        ) from None

    conf = Config(
        group=group,
        logic_start=resolve_optional(res, 'startlogic'),
        logic_mid=resolve_optional(res, 'midLogic'),
        logic_end=resolve_optional(res, 'endLogic'),
        logic_loop=resolve_optional(res, 'loopLogic'),
        allow_loop=res.bool('allowLoop'),
        transfer_io=res.bool('transferIO', True),
        antline=antline,
        scaff_endcap=resolve_optional(res, 'EndcapInst'),
        scaff_endcap_free_rot=res.bool('endcap_free_rotate'),
    )

    def applier(inst: Entity) -> None:
        """Store off this instance for later linkage."""
        group_list.append(item_chain.Node.from_inst(inst, conf))
    return applier


@conditions.meta_cond(-300)
def link_items(vmf: VMF) -> None:
    """Take the defined linked items, and actually link them together."""
    for name, group in ITEMS_TO_LINK.items():
        LOGGER.info('Linking {} items...', name)
        link_item(vmf, group)


def link_item(vmf: VMF, group: list[item_chain.Node[Config]]) -> None:
    """Link together a single group of items."""
    chains = item_chain.chain(group, allow_loop=True)
    for group_counter, node_list in enumerate(chains):
        is_looped = False
        if node_list[0].prev is not None:  # It's looped, check if it's allowed.
            if not all(node.conf.allow_loop for node in node_list):
                LOGGER.warning('- Group is looped, but this is not allowed! Arbitarily breaking.')
                node_list[0].prev = node_list[-1].next = None
            else:
                is_looped = True
        for index, node in enumerate(node_list):
            conf = node.conf
            is_floor = node.orient.up().z > 0.99

            if node.next is None and node.prev is None:
                # No connections in either direction, just skip.
                continue

            # We can't touch antlines if the item has regular outputs.
            if not node.item.outputs:
                if conf.antline is AntlineHandling.REMOVE:
                    node.item.delete_antlines()
                elif conf.antline is AntlineHandling.MOVE:
                    if index != 0:
                        node.item.transfer_antlines(node_list[0].item)
                elif conf.antline is AntlineHandling.KEEP:
                    pass
                else:
                    raise AssertionError(conf.antline)

            # Transfer inputs and outputs to the first.
            if index != 0 and conf.transfer_io:
                for conn in list(node.item.outputs):
                    conn.from_item = node_list[0].item
                for conn in list(node.item.inputs):
                    conn.to_item = node_list[0].item

            # If start/end, the other node.
            other_node: Optional[item_chain.Node[Config]] = None
            if is_looped:
                node.inst.fixup['$type'] = 'loop'
                logic_fname = conf.logic_loop
            elif node.prev is None:
                node.inst.fixup['$type'] = 'start'
                logic_fname = conf.logic_start
                other_node = node.next
            elif node.next is None:
                node.inst.fixup['$type'] = 'end'
                logic_fname = conf.logic_end
                other_node = node.prev
            else:
                node.inst.fixup['$type'] = 'mid'
                logic_fname = conf.logic_mid

            # Add values indicating the group, position, and next item.
            node.inst.fixup['$group'] = group_counter
            node.inst.fixup['$ind'] = index
            if node.next is not None:
                # If looped, it might have to wrap around.
                if node.next is node_list[0]:
                    node.inst.fixup['$next'] = '0'
                else:
                    node.inst.fixup['$next'] = index + 1

            if logic_fname:
                inst_logic = conditions.add_inst(
                    vmf,
                    targetname=node.inst['targetname'],
                    file=logic_fname,
                    origin=node.pos,
                    angles=node.inst['angles'],
                )
                inst_logic.fixup.update(node.inst.fixup)

            # Special case for Unstationary Scaffolds - change to an instance
            # for the ends, pointing in the direction of the connected track.
            if other_node is not None and is_floor and conf.scaff_endcap:
                link_dir = other_node.pos - node.pos

                # Compute the horizontal gradient (z / xy dist).
                # Don't use endcap if rising more than ~45 degrees, or lowering
                # more than ~12 degrees.
                horiz_dist = math.sqrt(link_dir.x ** 2 + link_dir.y ** 2)
                if horiz_dist != 0 and -0.15 <= (link_dir.z / horiz_dist) <= 1:
                    link_ang = math.degrees(math.atan2(link_dir.y, link_dir.x))
                    if not conf.scaff_endcap_free_rot:
                        # Round to nearest 90 degrees
                        # Add 45 so the switchover point is at the diagonals
                        link_ang = (link_ang + 45) // 90 * 90
                    node.inst['file'] = conf.scaff_endcap
                    conditions.ALL_INST.add(conf.scaff_endcap.casefold())
                    node.inst['angles'] = '0 {:.0f} 0'.format(link_ang)
