"""The result used to generate unstationary scaffolds."""
import math

from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
)
import instanceLocs
from srctools import Vec, Property
import srctools
import conditions
import utils
import vbsp

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
def res_unst_scaffold(res: Property):
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
    del SCAFFOLD_CONFIGS[res.value] # Don't let this run twice

    instances = {}
    # Find all the instances we're wanting to change, and map them to
    # targetnames
    for ent in vbsp.VMF.by_class['func_instance']:
        file = ent['file'].casefold()
        targ = ent['targetname']
        if file not in TARG_INST:
            continue
        config = TARG_INST[file]
        next_inst = set(
            out.target
            for out in
            ent.outputs
        )
        # Destroy these outputs, they're useless now!
        ent.outputs.clear()
        instances[targ] = {
            'ent': ent,
            'conf': config,
            'next': next_inst,
            'prev': None,
        }

    # Now link each instance to its in and outputs
    for targ, inst in instances.items():
        scaff_targs = 0
        for ent_targ in inst['next']:
            if ent_targ in instances:
                instances[ent_targ]['prev'] = targ
                inst['next'] = ent_targ
                scaff_targs += 1
            else:
                # If it's not a scaffold, it's probably an indicator_toggle.
                # We want to remove any them as well as the assoicated
                # antlines!
                for toggle in vbsp.VMF.by_target[ent_targ]:
                    conditions.remove_ant_toggle(toggle)
        if scaff_targs > 1:
            raise Exception('A scaffold item has multiple destinations!')
        elif scaff_targs == 0:
            inst['next'] = None  # End instance

    starting_inst = []
    # We need to find the start instances, so we can set everything up
    for inst in instances.values():
        if inst['prev'] is None and inst['next'] is None:
            # Static item!
            continue
        elif inst['prev'] is None:
            starting_inst.append(inst)

    # We need to make the link entities unique for each scaffold set,
    # otherwise the AllVar property won't work.
    group_counter = 0

    # Set all the instances and properties
    for start_inst in starting_inst:
        group_counter += 1
        ent = start_inst['ent']
        for vals in LINKS.values():
            if vals['all'] is not None:
                ent.fixup[vals['all']] = SCAFF_PATTERN.format(
                    name=vals['name'],
                    group=group_counter,
                    index='*',
                )

        should_reverse = srctools.conv_bool(ent.fixup['$start_reversed'])

        # Now set each instance in the chain, including first and last
        for index, inst in enumerate(scaff_scan(instances, start_inst)):
            ent, conf = inst['ent'], inst['conf']
            orient = (
                'floor' if
                Vec(0, 0, 1).rotate_by_str(ent['angles']) == (0, 0, 1)
                else 'wall'
            )

            # Find the offset used for the logic ents
            offset = (conf['off_' + orient]).copy()
            if conf['is_piston']:
                # Adjust based on the piston position
                offset.z += 128 * srctools.conv_int(ent.fixup[
                    '$top_level' if
                    ent.fixup['$start_up'] == '1'
                    else '$bottom_level'
                ])
            offset.rotate_by_str(ent['angles'])
            offset += Vec.from_str(ent['origin'])

            if inst['prev'] is None:
                link_type = 'start'
            elif inst['next'] is None:
                link_type = 'end'
            else:
                link_type = 'mid'

            if (
                    orient == 'floor' and
                    link_type != 'mid' and
                    conf['inst_end'] is not None
                    ):
                # Add an extra instance pointing in the direction
                # of the connected track. This would be the endcap
                # model.
                other_ent = instances[inst[
                    'next' if link_type == 'start' else 'prev'
                ]]['ent']

                other_pos = Vec.from_str(other_ent['origin'])
                our_pos = Vec.from_str(ent['origin'])
                link_dir = other_pos - our_pos
                link_ang = math.degrees(
                    math.atan2(link_dir.y, link_dir.x)
                )
                # Round to nearest 90 degrees
                # Add 45 so the switchover point is at the diagonals
                link_ang = (link_ang + 45) // 90 * 90
                vbsp.VMF.create_ent(
                    classname='func_instance',
                    targetname=ent['targetname'],
                    file=conf['inst_end'],
                    origin=offset.join(' '),
                    angles='0 {:.0f} 0'.format(link_ang),
                )
                # Don't place the offset instance, this replaces that!
            elif conf['inst_offset'] is not None:
                # Add an additional rotated entity at the offset.
                # This is useful for the piston item.
                vbsp.VMF.create_ent(
                    classname='func_instance',
                    targetname=ent['targetname'],
                    file=conf['inst_offset'],
                    origin=offset.join(' '),
                    angles=ent['angles'],
                )

            logic_inst = vbsp.VMF.create_ent(
                classname='func_instance',
                targetname=ent['targetname'],
                file=conf.get(
                    'logic_' + link_type + (
                        '_rev' if
                        should_reverse
                        else ''
                        ),
                    '',
                ),
                origin=offset.join(' '),
                angles=(
                    '0 0 0' if
                    conf['rotate_logic']
                    else ent['angles']
                ),
            )
            for key, val in ent.fixup.items():
                # Copy over fixup values
                logic_inst.fixup[key] = val

            # Add the link-values
            for linkVar, link in LINKS.items():
                logic_inst.fixup[linkVar] = SCAFF_PATTERN.format(
                    name=link['name'],
                    group=group_counter,
                    index=index,
                )
                if inst['next'] is not None:
                    logic_inst.fixup[link['next']] = SCAFF_PATTERN.format(
                        name=link['name'],
                        group=group_counter,
                        index=index + 1,
                    )

            new_file = conf.get('inst_' + orient, '')
            if new_file != '':
                ent['file'] = new_file

    LOGGER.info('Finished Scaffold generation!')
    return RES_EXHAUSTED
