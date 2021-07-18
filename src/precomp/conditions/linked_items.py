"""Implements a condition which allows linking items into a sequence."""
from __future__ import annotations
from typing import Optional, Callable
import math
import attr

from srctools import Property, VMF, Entity
import srctools.logger

from precomp import instanceLocs, item_chain, conditions


COND_MOD_NAME = 'Item Linkage'
LOGGER = srctools.logger.get_logger(__name__, alias='cond.linkedItem')


@attr.define
class Config:
    """Configuration for linked items."""
    logic_start: Optional[str]
    logic_mid: Optional[str]
    logic_end: Optional[str]

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
    return instanceLocs.resolve_one(file) or ''

# Store the nodes for items so we can join them up later.
ITEMS_TO_LINK: dict[str, list[item_chain.Node[Config]]] = {}


@conditions.make_result('LinkedItem')
def res_linked_item(res: Property) -> Callable[[Entity], None]:
    """Marks the current instance for linkage with similar items for linkage.

    At priority level -300, the sequence of similarly-marked items this links
    to is grouped together, and given fixup values to allow linking them.

    Parameters:
    * Group: Should be set to a unique name. All calls with this name can be
      linked together. If not used, only this specific result call will link.
    * StartLogic/MidLogic/EndLogic: These instances will be overlaid on the
      instance, depending on whether it starts/ends or is in the middle of the
      path.
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

    conf = Config(
        logic_start=resolve_optional(res, 'startlogic'),
        logic_mid=resolve_optional(res, 'midLogic'),
        logic_end=resolve_optional(res, 'endLogic'),

        # Specially rotated to face the next track!
        scaff_endcap=resolve_optional(res, 'EndcapInst'),
        # If it's allowed to point any direction, not just 90 degrees.
        scaff_endcap_free_rot=res.bool('endcap_free_rotate'),
    )

    def applier(inst: Entity) -> None:
        """Store off this instance for later linkage."""
        group_list.append(item_chain.Node.from_inst(inst, conf))
    return applier


@conditions.meta_cond(-300)
def link_items(vmf: VMF) -> None:
    """Take the defined linked items, and actually link them together."""
    if ITEMS_TO_LINK:
        for name, group in ITEMS_TO_LINK.items():
            LOGGER.info('Linking {} items...', name)
            link_item(vmf, group)


def link_item(vmf: VMF, group: list[item_chain.Node[Config]]) -> None:
    """Link together a single group of items."""
    chains = item_chain.chain(group, allow_loop=False)
    for group_counter, node_list in enumerate(chains):
        for index, node in enumerate(node_list):
            conf = node.conf
            is_floor = node.orient.up().z > 0.99

            if node.next is None and node.prev is None:
                # No connections in either direction, just skip.
                continue

            # If start/end, the other node.
            other_node: Optional[item_chain.Node[Config]] = None
            if node.prev is None:
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
                node.inst.fixup['$next'] = index + 1

            if logic_fname:
                inst_logic = vmf.create_ent(
                    classname='func_instance',
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
                    node.inst['angles'] = '0 {:.0f} 0'.format(link_ang)
