"""The result used to generate unstationary scaffolds."""
import math
from typing import Tuple

from enum import Enum

import instanceLocs
import item_chain
import srctools.logger
from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
)
from srctools import Vec, Property, VMF


class LinkType(Enum):
    """Type of node."""
    START = 'start'
    MID = 'mid'
    END = 'end'


COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.scaffold')


def scaff_scan(inst_list, start_ent):
    """Given the start item and instance list, follow the programmed path."""
    cur_ent = start_ent
    while True:
        yield cur_ent
        cur_ent = inst_list.get(cur_ent['next'], None)
        if cur_ent is None:
            return


def get_config(
    node: item_chain.Node,
) -> Tuple[str, Vec]:
    """Compute the config values for a node."""

    orient = (
        'floor' if
        Vec(0, 0, 1).rotate_by_str(node.inst['angles']) == (0, 0, 1)
        else 'wall'
    )
    # Find the offset used for the platform.
    offset = (node.conf['off_' + orient]).copy()  # type: Vec
    if node.conf['is_piston']:
        # Adjust based on the piston position
        offset.z += 128 * srctools.conv_int(
            node.inst.fixup[
                '$top_level' if
                node.inst.fixup[
                    '$start_up'] == '1'
                else '$bottom_level'
            ]
        )
    offset.rotate_by_str(node.inst['angles'])
    offset += Vec.from_str(node.inst['origin'])
    return orient, offset

# The name we give to instances and other parts.
SCAFF_PATTERN = '{name}_group{group}_part{index}'

# Store the configs for scaffold items so we can
# join them up later
SCAFFOLD_CONFIGS = {}


@make_result_setup('UnstScaffold')
def res_unst_scaffold_setup(res: Property):
    group = res['group', 'DEFAULT_GROUP']

    if group not in SCAFFOLD_CONFIGS:
        # Store our values in the CONFIGS dictionary
        targ_inst, links = SCAFFOLD_CONFIGS[group] = {}, {}
    else:
        # Grab the already-filled values, and add to them
        targ_inst, links = SCAFFOLD_CONFIGS[group]

    for block in res.find_all("Instance"):
        conf = {
            # If set, adjusts the offset appropriately
            'is_piston': srctools.conv_bool(block['isPiston', '0']),
            'rotate_logic': srctools.conv_bool(block['AlterAng', '1'], True),
            'off_floor': Vec.from_str(block['FloorOff', '0 0 0']),
            'off_wall': Vec.from_str(block['WallOff', '0 0 0']),

            'logic_start': block['startlogic', ''],
            'logic_end': block['endLogic', ''],
            'logic_mid': block['midLogic', ''],

            'logic_start_rev': block['StartLogicRev', None],
            'logic_end_rev': block['EndLogicRev', None],
            'logic_mid_rev': block['EndLogicRev', None],

            'inst_wall': block['wallInst', ''],
            'inst_floor': block['floorInst', ''],
            'inst_offset': block['offsetInst', None],
            # Specially rotated to face the next track!
            'inst_end': block['endInst', None],
        }
        for logic_type in ('logic_start', 'logic_mid', 'logic_end'):
            if conf[logic_type + '_rev'] is None:
                conf[logic_type + '_rev'] = conf[logic_type]

        for inst in instanceLocs.resolve(block['file']):
            targ_inst[inst] = conf

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

    return group  # We look up the group name to find the values.


@make_result('UnstScaffold')
def res_unst_scaffold(vmf: VMF, res: Property):
    """The condition to generate Unstationary Scaffolds.

    This is executed once to modify all instances.
    """
    # The instance types we're modifying
    if res.value not in SCAFFOLD_CONFIGS:
        # We've already executed this config group
        return RES_EXHAUSTED

    LOGGER.info(
        'Running Scaffold Generator ({})...',
        res.value
    )
    inst_to_config, LINKS = SCAFFOLD_CONFIGS[res.value]
    del SCAFFOLD_CONFIGS[res.value]  # Don't let this run twice

    chains = item_chain.chain(vmf, inst_to_config.keys(), allow_loop=False)

    # We need to make the link entities unique for each scaffold set,
    # otherwise the AllVar property won't work.

    for group_counter, node_list in enumerate(chains):
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
            if new_file != '':
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
                # If
                horiz_dist = math.sqrt(link_dir.x ** 2 + link_dir.y ** 2)
                if horiz_dist != 0 and -0.15 <= (link_dir.z / horiz_dist) <= 1:
                    link_ang = math.degrees(
                        math.atan2(link_dir.y, link_dir.x)
                    )
                    # Round to nearest 90 degrees
                    # Add 45 so the switchover point is at the diagonals
                    link_ang = (link_ang + 45) // 90 * 90
                    vmf.create_ent(
                        classname='func_instance',
                        targetname=node.inst['targetname'],
                        file=conf['inst_end'],
                        origin=offset,
                        angles='0 {:.0f} 0'.format(link_ang),
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

    LOGGER.info('Finished Scaffold generation!')
    return RES_EXHAUSTED
