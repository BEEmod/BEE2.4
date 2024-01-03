"""Implement special support """
from __future__ import annotations
from collections import defaultdict

from srctools import VMF, Entity, Keyvalues, Matrix, Output, Vec
import srctools.logger

from precomp import conditions, connections
from precomp.lazy_value import LazyValue
from transtoken import TransToken
import user_errors


COND_MOD_NAME: str | None = None
LOGGER = srctools.logger.get_logger(__name__, alias='cond.sendtor')

# Laser instance -> offset, normal
SENDTOR_TARGETS: dict[str, tuple[Vec, Vec]] = {}
# Laser instance -> relays created.
SENDTOR_RELAYS: dict[str, list[Entity]] = defaultdict(list)

TOK_SENDTOR_BAD_OUTPUT = TransToken.parse('HMW_SENDIFICATOR', 'BAD_OUTPUT_ITEM')


@conditions.make_result('SendificatorLaser')
def res_sendificator_laser(res: Keyvalues) -> conditions.ResultCallable:
    """Record the position of the target for Sendificator Lasers."""
    offset = LazyValue.parse(res['offset', '']).as_vec()
    normal = LazyValue.parse(res['direction', '']).as_vec(0, 0, 1)

    def set_laser(inst: Entity) -> None:
        """Store off the target position."""
        SENDTOR_TARGETS[inst['targetname']] = offset(inst), normal(inst)
    return set_laser


@conditions.make_result('Sendificator')
def res_sendificator(vmf: VMF, inst: Entity) -> None:
    """Implement Sendificators."""
    # For our version, we know which Sendificator connects to what laser,
    # so we can couple the logic together (avoiding `@sendtor_mutex`).

    sendtor_name = inst['targetname']
    sendtor = connections.ITEMS[sendtor_name]

    sendtor.enable_cmd += (Output(
        '',
        f'@{sendtor_name}_las_relay_*',
        'Trigger',
        delay=0.01,
    ), )

    for ind, conn in enumerate(list(sendtor.outputs), start=1):
        las_item = conn.to_item
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

        relay_name = f'@{sendtor_name}_las_relay_{ind}'

        relay = vmf.create_ent(
            'logic_relay',
            targetname=relay_name,
            origin=targ_offset,
            angles=targ_normal.to_angle(),
        )
        relay.add_out(
            Output('OnTrigger', '!self', 'RunScriptCode', '::sendtor_source <- self;'),
            Output('OnTrigger', '@sendtor_fire', 'Trigger'),
        )
        if not las_item.inputs:
            # No other inputs, make it on always. PeTI automatically turns
            # it off when inputs are connected, which is annoying.
            las_item.inst.fixup['$start_enabled'] = '1'
            is_on = True
            # If any other relays were made before, set them off too.
            for relay in SENDTOR_RELAYS[las_item.name]:
                relay['StartDisabled'] = False
        else:
            is_on = las_item.inst.fixup.bool('$start_enabled')

        relay['StartDisabled'] = not is_on
        SENDTOR_RELAYS[las_item.name].append(relay)
        las_item.enable_cmd += (Output('', relay_name, 'Enable'),)
        las_item.disable_cmd += (Output('', relay_name, 'Disable'),)
