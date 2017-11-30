"""The result used to generate unstationary scaffolds."""
import math
from enum import Enum

import instanceLocs
import item_chain
import srctools
import utils
import vbsp
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

LOGGER = utils.getLogger(__name__, alias='cond.scaffold')


def scaff_scan(inst_list, start_ent):
    """Given the start item and instance list, follow the programmed path."""
    cur_ent = start_ent
    while True:
        yield cur_ent
        cur_ent = inst_list.get(cur_ent['next'], None)
        if cur_ent is None:
            return

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
    TARG_INST, LINKS = SCAFFOLD_CONFIGS[res.value]
    del SCAFFOLD_CONFIGS[res.value]  # Don't let this run twice

    chains = item_chain.chain(vmf, TARG_INST.keys(), allow_loop=False)

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

        # Now set each instance in the chain, including first and last
        for index, node in enumerate(node_list):
            conf = TARG_INST[node.inst['file'].casefold()]
            orient = (
                'floor' if
                Vec(0, 0, 1).rotate_by_str(node.inst['angles']) == (0, 0, 1)
                else 'wall'
            )

            # Find the offset used for the logic ents
            offset = (conf['off_' + orient]).copy()
            if conf['is_piston']:
                # Adjust based on the piston position
                offset.z += 128 * srctools.conv_int(node.inst.fixup[
                    '$top_level' if
                    node.inst.fixup['$start_up'] == '1'
                    else '$bottom_level'
                ])
            offset.rotate_by_str(node.inst['angles'])
            offset += Vec.from_str(node.inst['origin'])

            if node.prev is None:
                link_type = LinkType.START
            elif node.next is None:
                link_type = LinkType.END
            else:
                link_type = LinkType.MID

            if (
                orient == 'floor' and
                link_type is not LinkType.MID and
                conf['inst_end'] is not None
            ):
                # Add an extra instance pointing in the direction
                # of the connected track. This would be the endcap
                # model.
                if link_type is LinkType.START:
                    other_inst = node.next.inst
                else:
                    other_inst = node.prev.inst

                other_pos = Vec.from_str(other_inst['origin'])
                our_pos = Vec.from_str(node.inst['origin'])
                link_dir = other_pos - our_pos
                link_ang = math.degrees(
                    math.atan2(link_dir.y, link_dir.x)
                )
                # Round to nearest 90 degrees
                # Add 45 so the switchover point is at the diagonals
                link_ang = (link_ang + 45) // 90 * 90
                vbsp.VMF.create_ent(
                    classname='func_instance',
                    targetname=node.inst['targetname'],
                    file=conf['inst_end'],
                    origin=offset,
                    angles='0 {:.0f} 0'.format(link_ang),
                )
                # Don't place the offset instance, this replaces that!
            elif conf['inst_offset'] is not None:
                # Add an additional rotated entity at the offset.
                # This is useful for the piston item.
                vbsp.VMF.create_ent(
                    classname='func_instance',
                    targetname=node.inst['targetname'],
                    file=conf['inst_offset'],
                    origin=offset,
                    angles=node.inst['angles'],
                )

            logic_inst = vbsp.VMF.create_ent(
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
            for key, val in node.inst.fixup.items():
                # Copy over fixup values
                logic_inst.fixup[key] = val

            # Add the link-values
            for linkVar, link in LINKS.items():
                logic_inst.fixup[linkVar] = SCAFF_PATTERN.format(
                    name=link['name'],
                    group=group_counter,
                    index=index,
                )
                if node.next is not None:
                    logic_inst.fixup[link['next']] = SCAFF_PATTERN.format(
                        name=link['name'],
                        group=group_counter,
                        index=index + 1,
                    )

            new_file = conf.get('inst_' + orient, '')
            if new_file != '':
                node.inst['file'] = new_file

    LOGGER.info('Finished Scaffold generation!')
    return RES_EXHAUSTED
