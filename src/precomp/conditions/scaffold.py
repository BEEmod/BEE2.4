"""The result used to generate unstationary scaffolds."""
from __future__ import annotations
from enum import Enum
from typing import Optional, Callable
import math
import attr

from srctools import Property, VMF, Entity
import srctools.logger

from precomp import instanceLocs, item_chain, conditions


COND_MOD_NAME = None
LOGGER = srctools.logger.get_logger(__name__, alias='cond.scaffold')


class LinkType(Enum):
    """Type of node."""
    START = 'start'
    MID = 'mid'
    END = 'end'


@attr.define
class ScaffoldConf:
    """Configuration for scaffolds."""
    logic_start: Optional[str]
    logic_mid: Optional[str]
    logic_end: Optional[str]

    logic_start_rev: Optional[str]
    logic_mid_rev: Optional[str]
    logic_end_rev: Optional[str]

    # Specially rotated to face the next track!
    inst_end: Optional[str]
    # If it's allowed to point any direction, not just 90 degrees.
    free_rotation: bool


def resolve_optional(prop: Property, key: str) -> str:
    """Resolve the given instance, or return '' if not defined."""
    try:
        file = prop[key]
    except LookupError:
        return ''
    return instanceLocs.resolve_one(file) or ''

# Store the nodes for scaffold items so we can join them up later.
SCAFFOLD_GROUPS: dict[str, list[item_chain.Node[ScaffoldConf]]] = {}


@conditions.make_result('UnstScaffold')
def res_unst_scaffold(res: Property) -> Callable[[Entity], None]:
    """Marks the current instance as a scaffold, making it capable of being
    linked together.

    Must be done before priority level -300. Parameters:
    * Group: Should be set to a unique name. All calls with this name can be
      linked together.
    * StartLogic/MidLogic/EndLogic: These instances will be overlaid on the
      instance, depending on whether it starts/ends or is in the middle of the
      path.
    """
    try:
        group = res['group'].casefold()
    except LookupError:
        # No group defined, make it specific to this result.
        group = format(id(res), '016X')

    try:
        group_list = SCAFFOLD_GROUPS[group]
    except KeyError:
        group_list = SCAFFOLD_GROUPS[group] = []

    log_start = resolve_optional(res, 'startlogic')
    log_end = resolve_optional(res, 'endLogic')
    log_mid = resolve_optional(res, 'midLogic')
    conf = ScaffoldConf(
        logic_start=log_start,
        logic_mid=log_mid,
        logic_end=log_end,

        logic_start_rev=resolve_optional(res, 'StartLogicRev') or log_start,
        logic_mid_rev=resolve_optional(res, 'EndLogicRev') or log_mid,
        logic_end_rev=resolve_optional(res, 'EndLogicRev') or log_end,

        # Specially rotated to face the next track!
        inst_end=resolve_optional(res, 'endInst'),
        # If it's allowed to point any direction, not just 90 degrees.
        free_rotation=res.bool('free_rotate_end'),
    )

    def applier(inst: Entity) -> None:
        """Store off this instance for later linkage."""
        group_list.append(item_chain.Node.from_inst(inst, conf))
    return applier


@conditions.meta_cond(-300)
def link_scaffolds(vmf: VMF) -> None:
    """Take the defined scaffolds, and link them together."""
    if SCAFFOLD_GROUPS:
        for name, group in SCAFFOLD_GROUPS.items():
            LOGGER.info('Running Scaffold Generator {} ...', name)
            link_scaffold(vmf, group)

        LOGGER.info('Finished Scaffold generation!')


def link_scaffold(vmf: VMF, group: list[item_chain.Node[ScaffoldConf]]) -> None:
    """Link together a single scaffold group."""
    chains = item_chain.chain(group, allow_loop=False)
    for group_counter, node_list in enumerate(chains):
        # Set all the instances and properties
        start_inst = node_list[0].item.inst

        should_reverse = srctools.conv_bool(start_inst.fixup['$start_reversed'])

        # Now set each instance in the chain, including first and last
        for index, node in enumerate(node_list):
            conf: ScaffoldConf = node.conf
            is_floor = node.orient.up().z > 0.99

            if node.prev is None:
                link_type = LinkType.START
                if node.next is None:
                    # No connections in either direction, just skip.
                    continue
            elif node.next is None:
                link_type = LinkType.END
            else:
                link_type = LinkType.MID

            # Add values indicating the group, position, and next item.
            node.inst.fixup['$group'] = group_counter
            node.inst.fixup['$ind'] = index
            if node.next is not None:
                node.inst.fixup['$next'] = index + 1
            node.inst.fixup['$type'] = link_type.value

            # Special case - change to an instance for the ends, pointing
            # in the direction of the connected track. This would be the
            # endcap model.
            if (
                is_floor and
                link_type is not LinkType.MID and
                conf.inst_end
            ):
                if link_type is LinkType.START:
                    other_node = node.next
                else:
                    other_node = node.prev

                assert other_node is not None  # Otherwise link type would be wrong...
                link_dir = other_node.pos - node.pos

                # Compute the horizontal gradient (z / xy dist).
                # Don't use endcap if rising more than ~45 degrees, or lowering
                # more than ~12 degrees.
                horiz_dist = math.sqrt(link_dir.x ** 2 + link_dir.y ** 2)
                if horiz_dist != 0 and -0.15 <= (link_dir.z / horiz_dist) <= 1:
                    link_ang = math.degrees(math.atan2(link_dir.y, link_dir.x))
                    if not conf.free_rotation:
                        # Round to nearest 90 degrees
                        # Add 45 so the switchover point is at the diagonals
                        link_ang = (link_ang + 45) // 90 * 90
                    node.inst['file'] = conf.inst_end
                    node.inst['angles'] = '0 {:.0f} 0'.format(link_ang)
                    # Don't place the offset instance, this replaces that!

            inst_logic = vmf.create_ent(
                classname='func_instance',
                targetname=node.inst['targetname'],
                file=getattr(
                    conf,
                    'logic_' + link_type.value + (
                        '_rev' if
                        should_reverse
                        else ''
                    ),
                    '',
                ),
                origin=node.pos,
                angles=node.inst['angles'],
            )
            inst_logic.fixup.update(node.inst.fixup)
