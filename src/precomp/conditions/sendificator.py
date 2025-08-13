"""Implement special support """
from __future__ import annotations
from collections import defaultdict

from srctools import VMF, Entity, Keyvalues, Matrix, Output, Vec
import srctools.logger

import utils
from precomp import conditions, connections
from precomp.lazy_value import LazyValue
from transtoken import TransToken
import user_errors


COND_MOD_NAME: str | None = None
LOGGER = srctools.logger.get_logger(__name__, alias='cond.sendtor')

# Laser instance -> offset, normal
SENDTOR_TARGETS: dict[str, tuple[Vec, Vec]] = {}
# Laser instance -> branches created.
SENDTOR_BRANCHES: dict[str, list[Entity]] = defaultdict(list)

TOK_SENDTOR_BAD_OUTPUT = TransToken.parse(utils.obj_id('HMW_SENDIFICATOR'), 'BAD_OUTPUT_ITEM')
# Indicator relay name which triggers the fail FX.
FAIL_IND_RL = 'set_indicator_fail_rl'

# Doesn't actually require connections, but it needs to be before Sendificator.
@conditions.make_result('SendificatorLaser', valid_before=conditions.MetaCond.Connections)
def res_sendificator_laser(res: Keyvalues) -> conditions.ResultCallable:
    """Record the position of the target for Sendificator Lasers."""
    offset = LazyValue.parse(res['offset', '']).as_vec()
    normal = LazyValue.parse(res['direction', '']).as_vec(0, 0, 1)

    def set_laser(inst: Entity) -> None:
        """Store off the target position."""
        SENDTOR_TARGETS[inst['targetname']] = offset(inst), normal(inst)
    return set_laser


@conditions.make_result('Sendificator', valid_before=conditions.MetaCond.Connections)
def res_sendificator(vmf: VMF, inst: Entity) -> None:
    """Implement Sendificators."""
    # For our version, we know which Sendificator connects to what laser,
    # so we can couple the logic together (avoiding `@sendtor_mutex`).

    # If all attached lasers are present, we also need the logic to trigger the fail indicator.

    sendtor_name = inst['targetname']
    sendtor_pos = inst['origin']
    sendtor = connections.ITEMS[sendtor_name]
    branches = []
    any_on = False

    outputs = list(sendtor.walk_nonlogic_outputs(ignore_antlaser=True))
    for ind, (logic, conn) in enumerate(outputs, start=1):
        las_item = conn.to_item
        for gate in logic:
            if gate.is_logic:
                connections.collapse_item(gate)
        conn.remove()
        try:
            targ_offset, targ_normal = SENDTOR_TARGETS[las_item.name]
        except KeyError:
            raise user_errors.UserError(
                TOK_SENDTOR_BAD_OUTPUT.format(out_item=las_item.name),
                voxels=[Vec.from_str(sendtor.inst['origin'])],
                points=[Vec.from_str(las_item.inst['origin'])],
            ) from None

        orient = Matrix.from_angstr(las_item.inst['angles'])

        targ_offset =  Vec.from_str(las_item.inst['origin']) + targ_offset @ orient
        targ_normal = targ_normal @ orient

        branch_name = f'@{sendtor_name}_branch_las_{ind}'
        # These are logic ents, but their location is still valid. So we can just use them as
        # targets.
        branch = vmf.create_ent(
            'logic_branch',
            targetname=branch_name,
            origin=targ_offset,
            angles=targ_normal.to_angle(),
        )
        branch.add_out(
            Output('OnTrue', '!self', 'RunScriptCode', '::sendtor_source <- self;'),
            Output('OnTrue', '@sendtor_fire', 'Trigger'),
        )
        if not las_item.inputs:
            # No other inputs, make it on always. PeTI automatically turns
            # it off when inputs are connected, which is annoying.
            las_item.inst.fixup['$start_enabled'] = '1'
            is_on = True
            # If any other branches were made before, set them on too.
            for branch in SENDTOR_BRANCHES[las_item.name]:
                branch['initalvalue'] = '1'
        else:
            is_on = las_item.inst.fixup.bool('$start_enabled')

        branch['initalvalue'] = is_on
        any_on |= is_on
        branches.append(branch)
        SENDTOR_BRANCHES[las_item.name].append(branch)
        las_item.enable_cmd += (Output('', branch_name, 'SetValue', '1'),)
        las_item.disable_cmd += (Output('', branch_name, 'SetValue', '0'),)

    # Now generate the triggering logic.
    match branches:
        case []:
            # Never going to work, just always fail.
            sendtor.enable_cmd += (Output('', FAIL_IND_RL, 'Trigger'), )
        case [branch]:
            # Can just trigger the one branch.
            sendtor.enable_cmd += (Output('', branch,'Test', delay=0.01), )
            branch.add_out(Output('OnFalse', f'{sendtor_name}-{FAIL_IND_RL}', 'Trigger'))
        case _:
            # We need a listener to detect when all lasers are off.
            sendtor.enable_cmd += (Output(
                '',
                # This matches the laser branches plus the fail branch.
                f'@{sendtor_name}_branch_*',
                'Test',
                delay=0.01,
            ),)

            fail_branch = f'@{sendtor_name}_branch_fail'
            vmf.create_ent(
                'logic_branch',
                targetname=fail_branch,
                origin=sendtor_pos,
                initialvalue=not any_on,
            ).add_out(Output('OnTrue', f'{sendtor_name}-{FAIL_IND_RL}', 'Trigger'))
            vmf.create_ent(
                'logic_branch_listener',
                targetname=f'{sendtor_name}_las_listener',
                # Only matches the laser branches.
                branch01=f'@{sendtor_name}_branch_las_*',
                origin=sendtor_pos,
            ).add_out(
                Output('OnAllTrue', fail_branch, 'SetValue', '0'),
                Output('OnMixed', fail_branch, 'SetValue', '0'),
                Output('OnAllFalse', fail_branch, 'SetValue', '1'),
            )
