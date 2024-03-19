"""Original result used to generate unstationary scaffolds, kept for backwards compatibility."""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any, Union
from enum import Enum
import math

from srctools import Vec, Keyvalues, VMF
import srctools.logger

from precomp import instanceLocs, item_chain, conditions


class LinkType(Enum):
    """Type of node."""
    START = 'start'
    MID = 'mid'
    END = 'end'


COND_MOD_NAME: str | None = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond._scaffold_compat')


def get_config(
    node: item_chain.Node,
) -> Tuple[str, Vec]:
    """Compute the config values for a node."""

    orient = ('floor' if abs(node.orient.up().z) > 0.9 else 'wall')
    # Find the offset used for the platform.
    offset: Vec = (node.conf['off_' + orient]).copy()
    if node.conf['is_piston']:
        # Adjust based on the piston position
        offset.z += 128 * srctools.conv_int(
            node.inst.fixup[
                '$top_level' if
                node.inst.fixup['$start_up'] == '1'
                else '$bottom_level'
            ]
        )
    offset = offset @ node.orient + node.pos
    return orient, offset


def resolve_optional(kv: Keyvalues, key: str) -> Optional[str]:
    """Resolve the given instance, or return None if not defined."""
    try:
        file = kv[key]
    except LookupError:
        return None
    return instanceLocs.resolve_one(file, error=False)


# The name we give to instances and other parts.
SCAFF_PATTERN = '{name}_group{group}_part{index}'

# Store the configs for scaffold items, so we can join them up later
SCAFFOLD_CONFIGS: Dict[str, Tuple[
    Dict[str, Dict[str, Union[bool, str, Vec, None]]],
    Dict[str, Dict[str, Optional[str]]],
]] = {}


@conditions.make_result('UnstScaffold', valid_before=conditions.MetaCond.ScaffoldLinkOld)
def res_old_unst_scaffold(res: Keyvalues) -> None:
    """The pre-2.4.40 version of the condition used to generate Unstationary Scaffolds.

    This has since been swapped to use the LinkedItems result, but this is kept for package
    compatiblity.
    """
    group = res['group', 'DEFAULT_GROUP']

    if group not in SCAFFOLD_CONFIGS:
        # Store our values in the CONFIGS dictionary
        targ_inst, links = SCAFFOLD_CONFIGS[group] = {}, {}
    else:
        # Grab the already-filled values, and add to them
        targ_inst, links = SCAFFOLD_CONFIGS[group]

    for block in res.find_all("Instance"):
        conf: Dict[str, Union[bool, str, Vec, None]] = {
            # If set, adjusts the offset appropriately
            'is_piston': srctools.conv_bool(block['isPiston', '0']),
            'rotate_logic': srctools.conv_bool(block['AlterAng', '1'], True),
            'off_floor': Vec.from_str(block['FloorOff', '0 0 0']),
            'off_wall': Vec.from_str(block['WallOff', '0 0 0']),

            'logic_start': resolve_optional(block, 'startlogic'),
            'logic_end': resolve_optional(block, 'endLogic'),
            'logic_mid': resolve_optional(block, 'midLogic'),

            'logic_start_rev': resolve_optional(block, 'StartLogicRev'),
            'logic_end_rev': resolve_optional(block, 'EndLogicRev'),
            'logic_mid_rev': resolve_optional(block, 'EndLogicRev'),

            'inst_wall': resolve_optional(block, 'wallInst'),
            'inst_floor': resolve_optional(block, 'floorInst'),
            'inst_offset': resolve_optional(block, 'offsetInst'),
            # Specially rotated to face the next track!
            'inst_end': resolve_optional(block, 'endInst'),
            # If it's allowed to point any direction, not just 90 degrees.
            'free_rotation': block.bool('free_rotate_end'),
        }
        for logic_type in ('logic_start', 'logic_mid', 'logic_end'):
            if conf[logic_type + '_rev'] is None:
                conf[logic_type + '_rev'] = conf[logic_type]

        targ_inst.update(
            dict.fromkeys(instanceLocs.resolve_filter(block['file']), conf)
        )

    # We need to provide vars to link the tracks and beams.
    for block in res.find_all('LinkEnt'):
        # The name for this set of entities.
        # It must be a '@' name, or the name will be fixed-up incorrectly!
        loc_name = block['name']
        if not loc_name.startswith('@'):
            loc_name = '@' + loc_name
        links[block['nameVar']] = {
            'name': loc_name,
            # The next entity (not set in end logic)
            'next': block['nextVar'],
            # A '*' name to reference all the ents (set on the start logic)
            'all': block['allVar', None],
        }
    LOGGER.warning(
        'Running legacy scaffold generator for "{}"!'
        'Items should now use the generic LinkedItem config, update your packages!',
        res.value,
    )


@conditions.MetaCond.ScaffoldLinkOld.register
def legacy_scaffold_link(vmf: VMF) -> None:
    """Apply the legacy scaffold logic."""
    if not SCAFFOLD_CONFIGS:
        return

    for inst_to_config, LINKS in SCAFFOLD_CONFIGS.values():
        # Don't bother typechecking this dict, legacy code.
        nodes: List[item_chain.Node[Dict[str, Any]]] = []
        for inst in vmf.by_class['func_instance']:
            try:
                conf = inst_to_config[inst['file'].casefold()]
            except KeyError:
                continue
            else:
                nodes.append(item_chain.Node.from_inst(inst, conf))

        # We need to make the link entities unique for each scaffold set,
        # otherwise the AllVar property won't work.
        for group_counter, node_list in enumerate(item_chain.chain(nodes, allow_loop=False)):
            # Set all the instances and properties
            start_inst = node_list[0].item.inst
            for vals in LINKS.values():
                if vals['all'] is not None:
                    start_inst.fixup[vals['all']] = SCAFF_PATTERN.format(
                        name=vals['name'],
                        group=group_counter,
                        index='*',
                    )

            should_reverse = srctools.conv_bool(start_inst.fixup['$start_reversed'])

            # Stash this off to start, so we can find this after items are processed
            # and the instance names change.
            for node in node_list:
                node.conf = inst_to_config[node.inst['file'].casefold()]

            # Now set each instance in the chain, including first and last
            for index, node in enumerate(node_list):
                conf = node.conf
                orient, offset = get_config(node)

                new_file = conf.get('inst_' + orient, '')
                if new_file:
                    node.inst['file'] = new_file

                if node.prev is None:
                    link_type = LinkType.START
                    if node.next is None:
                        # No connections in either direction, just skip.
                        # Generate the piston tip if we would have.
                        if conf['inst_offset'] is not None:
                            vmf.create_ent(
                                classname='func_instance',
                                targetname=node.inst['targetname'],
                                file=conf['inst_offset'],
                                origin=offset,
                                angles=node.inst['angles'],
                            )
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
                    orient == 'floor' and
                    link_type is not LinkType.MID and
                    conf['inst_end'] is not None
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
                        link_ang = math.degrees(
                            math.atan2(link_dir.y, link_dir.x)
                        )
                        if not conf['free_rotation']:
                            # Round to nearest 90 degrees
                            # Add 45 so the switchover point is at the diagonals
                            link_ang = (link_ang + 45) // 90 * 90
                        vmf.create_ent(
                            classname='func_instance',
                            targetname=node.inst['targetname'],
                            file=conf['inst_end'],
                            origin=offset,
                            angles=f'0 {link_ang:.0f} 0',
                        )
                        # Don't place the offset instance, this replaces that!
                        placed_endcap = True

                if not placed_endcap and conf['inst_offset'] is not None:
                    # Add an additional rotated entity at the offset.
                    # This is useful for the piston item.
                    vmf.create_ent(
                        classname='func_instance',
                        targetname=node.inst['targetname'],
                        file=conf['inst_offset'],
                        origin=offset,
                        angles=node.inst['angles'],
                    )

                logic_inst = vmf.create_ent(
                    classname='func_instance',
                    targetname=node.inst['targetname'],
                    file=conf.get(
                        'logic_' + link_type.value + (
                            '_rev' if
                            should_reverse
                            else ''
                            ),
                        '',
                    ),
                    origin=offset,
                    angles=(
                        '0 0 0' if
                        conf['rotate_logic']
                        else node.inst['angles']
                    ),
                )

                # Add the link-values
                for linkVar, link in LINKS.items():
                    node.inst.fixup[linkVar] = SCAFF_PATTERN.format(
                        name=link['name'],
                        group=group_counter,
                        index=index,
                    )
                    if node.next is not None:
                        node.inst.fixup[link['next']] = SCAFF_PATTERN.format(
                            name=link['name'],
                            group=group_counter,
                            index=index + 1,
                        )

                for key, val in node.inst.fixup.items():
                    # Copy over fixup values
                    logic_inst.fixup[key] = val

        LOGGER.info('Finished legacy Scaffold generation!')
