"""The result used to generate unstationary scaffolds."""
from __future__ import annotations
from enum import Enum
from typing import Optional, Iterator
import math
import attr

from srctools import Vec, Property
from srctools.vmf import VMF, Entity
import srctools.logger

from precomp import instanceLocs, item_chain
from precomp.conditions import make_result, make_result_setup, RES_EXHAUSTED


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
    # If set, adjusts the offset appropriately
    is_piston: bool
    rotate_logic: bool
    off_floor: Vec
    off_wall: Vec

    logic_start: Optional[str]
    logic_end: Optional[str]
    logic_mid: Optional[str]

    logic_start_rev: Optional[str]
    logic_end_rev: Optional[str]
    logic_mid_rev: Optional[str]

    inst_wall: Optional[str]
    inst_floor: Optional[str]
    inst_offset: Optional[str]
    # Specially rotated to face the next track!
    inst_end: Optional[str]
    # If it's allowed to point any direction, not just 90 degrees.
    free_rotation: bool


def scaff_scan(inst_list: dict[str, Entity], start_ent: Entity) -> Iterator[Entity]:
    """Given the start item and instance list, follow the programmed path."""
    cur_ent = start_ent
    while True:
        yield cur_ent
        cur_ent = inst_list.get(cur_ent['next'], None)
        if cur_ent is None:
            return


def get_config(node: item_chain.Node[ScaffoldConf]) -> tuple[bool, Vec]:
    """Compute the config values for a node."""

    is_floor = node.orient.up().z > 0.99
    # Find the offset used for the platform.
    offset = Vec(node.conf.off_floor if is_floor else node.conf.off_wall)
    if node.conf.is_piston:
        # Adjust based on the piston position
        offset.z += 128 * srctools.conv_int(
            node.inst.fixup[
                '$top_level' if
                node.inst.fixup['$start_up'] == '1'
                else '$bottom_level'
            ]
        )
    offset.localise(Vec.from_str(node.inst['origin']), node.orient)
    return is_floor, offset


def resolve_optional(prop: Property, key: str) -> Optional[str]:
    """Resolve the given instance, or return None if not defined."""
    try:
        file = prop[key]
    except LookupError:
        return None
    return instanceLocs.resolve_one(file)


# The name we give to instances and other parts.
SCAFF_PATTERN = '{name}_group{group}_part{index}'

# Store the configs for scaffold items so we can
# join them up later
# group -> inst -> config
SCAFFOLD_CONFIGS: dict[str, dict[str, ScaffoldConf]] = {}


@make_result_setup('UnstScaffold')
def res_unst_scaffold_setup(res: Property):
    group = res['group', 'DEFAULT_GROUP'].casefold()

    try:
        targ_inst = SCAFFOLD_CONFIGS[group]
    except KeyError:
        targ_inst = SCAFFOLD_CONFIGS[group] = {}

    for block in res.find_all("Instance"):
        log_start = resolve_optional(block, 'startlogic')
        log_end = resolve_optional(block, 'endLogic')
        log_mid = resolve_optional(block, 'midLogic')
        conf = ScaffoldConf(
            is_piston=srctools.conv_bool(block['isPiston', '0']),
            rotate_logic=srctools.conv_bool(block['AlterAng', '1'], True),
            off_floor=Vec.from_str(block['FloorOff', '0 0 0']),
            off_wall=Vec.from_str(block['WallOff', '0 0 0']),

            logic_start=log_start,
            logic_mid=log_mid,
            logic_end=log_end,

            logic_start_rev=resolve_optional(block, 'StartLogicRev') or log_start,
            logic_mid_rev=resolve_optional(block, 'EndLogicRev') or log_mid,
            logic_end_rev=resolve_optional(block, 'EndLogicRev') or log_end,

            inst_wall=resolve_optional(block, 'wallInst'),
            inst_floor=resolve_optional(block, 'floorInst'),

            inst_offset=resolve_optional(block, 'offsetInst'),
            # Specially rotated to face the next track!
            inst_end=resolve_optional(block, 'endInst'),
            # If it's allowed to point any direction, not just 90 degrees.
            free_rotation=block.bool('free_rotate_end'),
        )
        for inst in instanceLocs.resolve(block['file']):
            targ_inst[inst] = conf

    return group  # We look up the group name to find the values.


@make_result('UnstScaffold')
def res_unst_scaffold(vmf: VMF, res: Property):
    """The condition to generate Unstationary Scaffolds.

    This is executed once to modify all instances.
    """
    # The instance types we're modifying
    # TODO: Broken with the new just-in-time setup calls.
    if res.value not in SCAFFOLD_CONFIGS:
        # We've already executed this config group
        return RES_EXHAUSTED

    LOGGER.info('Running Scaffold Generator ({})...', res.value)
    inst_to_config = SCAFFOLD_CONFIGS[res.value]
    del SCAFFOLD_CONFIGS[res.value]  # Don't let this run twice

    chains = item_chain.chain(vmf, inst_to_config, allow_loop=False)

    # We need to make the link entities unique for each scaffold set,
    # otherwise the AllVar property won't work.

    for group_counter, node_list in enumerate(chains):
        # Set all the instances and properties
        start_inst = node_list[0].item.inst

        should_reverse = srctools.conv_bool(start_inst.fixup['$start_reversed'])

        # Now set each instance in the chain, including first and last
        for index, node in enumerate(node_list):
            conf = node.conf
            is_floor, offset = get_config(node)

            # Add the link-values.
            node.inst.fixup['$group'] = group_counter
            node.inst.fixup['$ind'] = index
            node.inst.fixup['$next'] = index + 1

            new_file = conf.inst_floor if is_floor else conf.inst_wall
            if new_file:
                node.inst['file'] = new_file

            if node.prev is None:
                link_type = LinkType.START
                if node.next is None:
                    # No connections in either direction, just skip.
                    # Generate the piston tip if we would have.
                    if conf.inst_offset is not None:
                        inst_offset = vmf.create_ent(
                            classname='func_instance',
                            targetname=node.inst['targetname'],
                            file=conf.inst_offset,
                            origin=offset,
                            angles=node.inst['angles'],
                        )
                        inst_offset.fixup.update(node.inst.fixup)
                    continue
            elif node.next is None:
                link_type = LinkType.END
            else:
                link_type = LinkType.MID

            # Special case - add an extra instance for the ends, pointing
            # in the direction
            # of the connected track. This would be the endcap
            # model.
            placed_endcap = False
            if (
                is_floor and
                link_type is not LinkType.MID and
                conf.inst_end is not None
            ):
                if link_type is LinkType.START:
                    other_node = node.next
                else:
                    other_node = node.prev

                other_offset = get_config(other_node)[1]
                link_dir = other_offset - offset

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
                    inst_end = vmf.create_ent(
                        classname='func_instance',
                        targetname=node.inst['targetname'],
                        file=conf.inst_end,
                        origin=offset,
                        angles='0 {:.0f} 0'.format(link_ang),
                    )
                    inst_end.fixup.update(node.inst.fixup)
                    # Don't place the offset instance, this replaces that!
                    placed_endcap = True

            if not placed_endcap and conf.inst_offset is not None:
                # Add an additional rotated entity at the offset.
                # This is useful for the piston item.
                vmf.create_ent(
                    classname='func_instance',
                    targetname=node.inst['targetname'],
                    file=conf.inst_offset,
                    origin=offset,
                    angles=node.inst['angles'],
                )

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
                origin=offset,
                angles='0 0 0' if conf.rotate_logic else node.inst['angles'],
            )
            inst_logic.fixup.update(node.inst.fixup)

    LOGGER.info('Finished Scaffold generation!')
    return RES_EXHAUSTED
