"""Results for custom fizzlers."""
from srctools import Keyvalues, Entity, Vec, VMF, Matrix
import attrs
import srctools.logger

import consts
import user_errors
import utils
from precomp.instanceLocs import resolve_one
from precomp import conditions, connections, fizzler


COND_MOD_NAME = 'Fizzlers'
LOGGER = srctools.logger.get_logger(__name__, alias='cond.fizzler')
EMANCIPATION_GRID = utils.obj_id('VALVE_MATERIAL_EMANCIPATION_GRID')


@conditions.make_test('FizzlerType')
def test_fizz_type(kv: Keyvalues) -> conditions.TestCallable:
    """Check if a fizzler is the specified type name."""
    fizz_id = utils.obj_id(kv.value, 'fizzler')

    def test(inst: Entity) -> bool:
        """Do the check."""
        try:
            fizz = fizzler.FIZZLERS[inst['targetname']]
        except KeyError:
            return False
        return fizz.fizz_type.id == fizz_id

    return test


@conditions.make_result('ChangeFizzlerType', valid_before=conditions.MetaCond.Fizzler)
def res_change_fizzler_type(res: Keyvalues) -> conditions.ResultCallable:
    """Change the type of the fizzler. Only valid when run on the base instance."""
    try:
        fizz_type = fizzler.FIZZ_TYPES[utils.obj_id(res.value, 'fizzler')]
    except KeyError:
        raise user_errors.UserError(user_errors.TOK_UNKNOWN_ID.format(
            kind='Fizzler',
            id=res.value,
        )) from None

    def convert(inst: Entity) -> None:
        """Modify the specified fizzler."""
        fizz_name = inst['targetname']
        try:
            fizzler.FIZZLERS[fizz_name].fizz_type = fizz_type
        except KeyError:
            raise user_errors.UserError(user_errors.TOK_WRONG_ITEM_TYPE.format(
                item=fizz_name,
                kind='Fizzler',
                inst=inst['file'],
            )) from None

    return convert


@conditions.make_result(
    'ReshapeFizzler',
    valid_before=[conditions.MetaCond.Fizzler, conditions.MetaCond.Connections],
)
def res_reshape_fizzler(vmf: VMF, shape_inst: Entity, res: Keyvalues) -> None:
    """Convert a fizzler connected via the output to a new shape.

    This allows for different placing of fizzler items.

    * Each `segment` parameter should be a `x y z;x y z` pair of positions
    that represent the ends of the fizzler.
    * `up_axis` should be set to a normal vector pointing in the new 'upward'
    direction.
    * If none are connected, a regular fizzler will be synthesized.

    The following fixup vars will be set to allow the shape to match the fizzler:

    * `$uses_nodraw` will be 1 if the fizzler nodraws surfaces behind it.
    """
    shape_name = shape_inst['targetname']
    shape_item = connections.ITEMS.pop(shape_name)

    shape_orient = Matrix.from_angstr(shape_inst['angles'])
    up_axis: Vec = round(res.vec('up_axis') @ shape_orient, 6)

    for conn in shape_item.outputs:
        fizz_item = conn.to_item
        try:
            fizz = fizzler.FIZZLERS[fizz_item.name]
        except KeyError:
            continue
        # Detach this connection and remove traces of it.
        conn.remove()

        if fizz.has_cust_position:
            # This fizzler was already moved. We need to make a clone.
            fizz_base = fizz.base_inst.copy()
            vmf.add_ent(fizz_base)
            fizz_base['targetname'] = shape_name
            old_fizz_item = fizz_item
            fizz = fizzler.FIZZLERS[shape_name] = attrs.evolve(
                fizz,
                base_inst=fizz_base,
                emitters=[],
                up_axis=up_axis,
                has_cust_position=True,
            )
            fizz_item = old_fizz_item.clone(fizz_base, shape_name)
            for fizz_conn in old_fizz_item.inputs:
                connections.Connection(
                    to_item=fizz_item,
                    from_item=fizz_conn.from_item,
                    conn_type=fizz_conn.type,
                ).add()
        else:
            # Move the current fizzler.
            fizz.emitters.clear()  # Remove old positions.
            fizz.up_axis = up_axis
            fizz.has_cust_position = True
        fizz.base_inst['origin'] = shape_inst['origin']
        fizz.base_inst['angles'] = shape_inst['angles']
        break
    else:
        # No fizzler, so generate a default.
        # We create the fizzler instance, Fizzler object, and Item object
        # matching it.
        # This is hardcoded to use regular Emancipation Fields.
        fizz_base = conditions.add_inst(
            vmf,
            targetname=shape_name,
            origin=shape_inst['origin'],
            angles=shape_inst['angles'],
            file=resolve_one('<ITEM_BARRIER_HAZARD:fizz_base>', error=True),
        )
        fizz_base.fixup.update(shape_inst.fixup)
        fizz = fizzler.FIZZLERS[shape_name] = fizzler.Fizzler(
            fizz_type=fizzler.FIZZ_TYPES[EMANCIPATION_GRID],
            up_axis=up_axis,
            base_inst=fizz_base,
            emitters=[],
            has_cust_position=True,
        )
        fizz_item = connections.Item(
            fizz_base,
            connections.ITEM_TYPES[consts.DefaultItems.fizzler.id],
            ind_style=shape_item.ind_style,
        )
        connections.ITEMS[shape_name] = fizz_item

    # Transfer the input/outputs from us to the fizzler.
    for inp in list(shape_item.inputs):
        inp.to_item = fizz_item
    for conn in list(shape_item.outputs):
        conn.from_item = fizz_item

    # If the fizzler has no outputs, then strip out antlines. Otherwise,
    # they need to be transferred across, so we can't tell safely.
    if fizz_item.output_act() is None and fizz_item.output_deact() is None:
        shape_item.delete_antlines()
    else:
        shape_item.transfer_antlines(fizz_item)

    fizz_base = fizz.base_inst
    fizz_base['origin'] = shape_inst['origin']
    origin = Vec.from_str(shape_inst['origin'])

    # Since the fizzler is moved elsewhere, it's the responsibility of
    # the new item to have holes.
    fizz.embedded = False
    # Tell the instance whether it needs to do so.
    shape_inst.fixup['$uses_nodraw'] = fizz.fizz_type.nodraw_behind

    for seg_prop in res.find_all('Segment'):
        vec1, vec2 = seg_prop.value.split(';')
        seg_min_max = Vec.bbox(
            Vec.from_str(vec1) @ shape_orient + origin,
            Vec.from_str(vec2) @ shape_orient + origin,
        )
        fizz.emitters.append(seg_min_max)
