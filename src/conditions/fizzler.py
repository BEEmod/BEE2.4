"""Results for custom fizzlers."""
import utils
from conditions import make_result, remove_ant_toggle
import connections
from srctools import Property, Entity, Vec, VMF
import fizzler

COND_MOD_NAME = 'Fizzlers'

LOGGER = utils.getLogger(__name__, alias='cond.fizzler')


@make_result('ChangeFizzlerType')
def res_change_fizzler_type(inst: Entity, res: Property):
    """Change the type of a fizzler. Only valid when run on the base instance."""
    fizz_name = inst['targetname']
    try:
        fizz = fizzler.FIZZLERS[fizz_name]
    except KeyError:
        LOGGER.warning('ChangeFizzlerType not run on a fizzler ("{}")!', fizz_name)
        return

    try:
        fizz.fizz_type = fizzler.FIZZ_TYPES[res.value]
    except KeyError:
        raise ValueError('Invalid fizzler type "{}"!', res.value)


@make_result('ReshapeFizzler')
def res_reshape_fizzler(vmf: VMF, shape_inst: Entity, res: Property):
    """Convert a fizzler connected via the output to a new shape.

    This allows for different placing of fizzler items.
    Each `segment` parameter should be a `x y z;x y z` pair of positions
    that represent the ends of the fizzler.
    `up_axis` should be set to a normal vector pointing in the new 'upward'
    direction.
    `default` is the ID of a fizzler type which should be used if no outputs
    are fired.
    """
    shape_name = shape_inst['targetname']
    shape_item = connections.ITEMS[shape_name]

    for conn in shape_item.outputs:
        fizz_name = conn.inp.name
        try:
            fizz = fizzler.FIZZLERS[fizz_name]
        except KeyError:
            LOGGER.warning('Reshaping fizzler with non-fizzler output! Ignoring!')
            continue
        break
    else:
        # No fizzler - create one.
        conn = None
        fizz_type = fizzler.FIZZ_TYPES[res['default']]
        base_inst = vmf.create_ent(
            targetname=shape_name,
            classname='func_instance',
            origin=shape_inst['origin'],
            file=fizz_type.inst[fizzler.FizzInst.BASE][0],
        )
        base_inst.fixup.update(shape_inst.fixup)
        fizz = fizzler.FIZZLERS[shape_name] = fizzler.Fizzler(
            fizz_type,
            Vec(),
            base_inst,
            [],
        )

    # Detach this connection and remove traces of it.
    if conn:
        conn.remove()
        if shape_item.ind_toggle:
            remove_ant_toggle(shape_item.ind_toggle)

    fizz_base = fizz.base_inst
    fizz_base['origin'] = shape_inst['origin']
    origin = Vec.from_str(shape_inst['origin'])

    shape_angles = Vec.from_str(shape_inst['angles'])

    fizz.up_axis = res.vec('up_axis').rotate(*shape_angles)
    fizz.emitters.clear()

    # Since the fizzler is moved elsewhere, it's the responsibility of
    # the new item to have holes.
    fizz.embedded = False

    for seg_prop in res.find_all('Segment'):
        vec1, vec2 = seg_prop.value.split(';')
        seg_min_max = Vec.bbox(
            Vec.from_str(vec1).rotate(*shape_angles) + origin,
            Vec.from_str(vec2).rotate(*shape_angles) + origin,
        )
        fizz.emitters.append(seg_min_max)
