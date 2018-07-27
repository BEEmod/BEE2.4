from typing import Tuple, Dict

import conditions
import connections
import srctools.logger
from srctools import Property, Entity, VMF, Vec, Output

COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.sendtor')

# Laser name -> offset, normal
SENDTOR_TARGETS = {}  # type: Dict[str, Tuple[Vec, Vec]]


@conditions.make_result_setup('SendificatorLaser')
def res_sendificator_laser_setup(res: Property):
    return (
        res.vec('offset'),
        res.vec('direction', 0, 0, 1)
    )


@conditions.make_result('SendificatorLaser')
def res_sendificator_laser(inst: Entity, res: Property):
    """Record the position of the target for Sendificator Lasers."""
    SENDTOR_TARGETS[inst['targetname']] = res.value


@conditions.make_result('Sendificator')
def res_sendificator(vmf: VMF, inst: Entity):
    """Implement Sendificators."""
    # For our version, we know which sendtor connects to what laser,
    # so we can couple the logic together (avoiding @sendtor_mutex).

    sendtor_name = inst['targetname']
    sendtor = connections.ITEMS[sendtor_name]

    sendtor.enable_cmd += (Output(
        '',
        '@{}_las_relay_*'.format(sendtor_name),
        'Trigger',
        delay=0.01,
    ), )

    for ind, conn in enumerate(list(sendtor.outputs), start=1):
        las_item = conn.to_item
        conn.remove()
        try:
            targ_offset, targ_normal = SENDTOR_TARGETS[las_item.name]
        except KeyError:
            LOGGER.warning('"{}" is not a Sendificator target!', las_item.name)
            continue

        angles = Vec.from_str(las_item.inst['angles'])

        targ_offset = targ_offset.copy()
        targ_normal = targ_normal.copy().rotate(*angles)

        targ_offset.localise(
            Vec.from_str(las_item.inst['origin']),
            angles,
        )

        relay_name = '@{}_las_relay_{}'.format(sendtor_name, ind)

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
        else:
            is_on = las_item.inst.fixup.bool('$start_enabled')

        relay['StartDisabled'] = not is_on
        las_item.enable_cmd += (Output('', relay_name, 'Enable'),)
        las_item.disable_cmd += (Output('', relay_name, 'Disable'),)
        LOGGER.info('Relay: {}', relay)
