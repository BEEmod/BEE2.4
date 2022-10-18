"""Results for custom fizzlers."""
from srctools import Property, Entity, Vec, VMF, Matrix
import srctools.logger

from precomp.instanceLocs import resolve_one
from precomp import conditions, connections, fizzler


COND_MOD_NAME = 'Fizzlers'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.fizzler')


@conditions.make_flag('FizzlerType')
def flag_fizz_type(inst: Entity, flag: Property):
    """Check if a fizzler is the specified type name."""
    try:
        fizz = fizzler.FIZZLERS[inst['targetname']]
    except KeyError:
        return False
    return fizz.fizz_type.id.casefold() == flag.value.casefold()


@conditions.make_result('ChangeFizzlerType')
def res_change_fizzler_type(inst: Entity, res: Property):
    """Change the type of the fizzler. Only valid when run on the base instance."""
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


@conditions.make_result('ReshapeFizzler')
def res_reshape_fizzler(vmf: VMF, shape_inst: Entity, res: Property):
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

        fizz.emitters.clear()  # Remove old positions.
        fizz.up_axis = up_axis
        fizz.base_inst['origin'] = shape_inst['origin']
        fizz.base_inst['angles'] = shape_inst['angles']
        break
    else:
        # No fizzler, so generate a default.
        # We create the fizzler instance, Fizzler object, and Item object
        # matching it.
        # This is hardcoded to use regular Emancipation Fields.
        base_inst = conditions.add_inst(
            vmf,
            targetname=shape_name,
            origin=shape_inst['origin'],
            angles=shape_inst['angles'],
            file=resolve_one('<ITEM_BARRIER_HAZARD:fizz_base>'),
        )
        base_inst.fixup.update(shape_inst.fixup)
        fizz = fizzler.FIZZLERS[shape_name] = fizzler.Fizzler(
            fizzler.FIZZ_TYPES['VALVE_MATERIAL_EMANCIPATION_GRID'],
            up_axis,
            base_inst,
            [],
        )
        fizz_item = connections.Item(
            base_inst,
            connections.ITEM_TYPES['item_barrier_hazard'],
            ant_floor_style=shape_item.ant_floor_style,
            ant_wall_style=shape_item.ant_wall_style,
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

    fizz.has_cust_position = True
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
