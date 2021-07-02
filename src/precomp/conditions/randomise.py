"""Conditions for randomising instances."""
import random
from typing import List

from srctools import Property, Vec, Entity, VMF
from precomp import conditions
import srctools

from precomp.conditions import (
    Condition, make_flag, make_result, make_result_setup, RES_EXHAUSTED,
    set_random_seed,
)

COND_MOD_NAME = 'Randomisation'


@make_flag('random')
def flag_random(inst: Entity, res: Property) -> bool:
    """Randomly is either true or false."""
    if res.has_children():
        chance = res['chance', '100']
        seed = 'a' + res['seed', '']
    else:
        chance = res.value
        seed = 'a'

    # Allow ending with '%' sign
    chance = srctools.conv_int(chance.rstrip('%'), 100)

    set_random_seed(inst, seed)
    return random.randrange(100) < chance


@make_result_setup('random')
def res_random_setup(vmf: VMF, res: Property) -> object:
    weight = ''
    results = []
    chance = 100
    seed = 'b'
    for prop in res:
        if prop.name == 'chance':
            # Allow ending with '%' sign
            chance = srctools.conv_int(
                prop.value.rstrip('%'),
                chance,
            )
        elif prop.name == 'weights':
            weight = prop.value
        elif prop.name == 'seed':
            seed = 'b' + prop.value
        else:
            results.append(prop)

    if not results:
        return None  # Invalid!

    weight = conditions.weighted_random(len(results), weight)

    return seed, chance, weight, results


@make_result('random')
def res_random(inst: Entity, res: Property) -> None:
    """Randomly choose one of the sub-results to execute.

    The `chance` value defines the percentage chance for any result to be
    chosen. `weights` defines the weighting for each result. Both are
    comma-separated, matching up with the results following. Wrap a set of
    results in a `group` property block to treat them as a single result to be
    executed in order.
    """
    # Note: 'global' results like "Has" won't delete themselves!
    # Instead they're replaced by 'dummy' results that don't execute.
    # Otherwise the chances would be messed up.
    seed, chance, weight, results = res.value  # type: str, float, List[int], List[Property]

    set_random_seed(inst, seed)
    if random.randrange(100) > chance:
        return

    ind = random.choice(weight)
    choice = results[ind]
    if choice.name == 'nop':
        pass
    elif choice.name == 'group':
        for sub_res in choice:
            should_del = Condition.test_result(
                inst,
                sub_res,
            )
            if should_del is RES_EXHAUSTED:
                # This Result doesn't do anything!
                sub_res.name = 'nop'
                sub_res.value = None
    else:
        should_del = Condition.test_result(
            inst,
            choice,
        )
        if should_del is RES_EXHAUSTED:
            choice.name = 'nop'
            choice.value = None


@make_result('variant')
def res_add_variant(res: Property):
    """This allows using a random instance from a weighted group.

    A suffix will be added in the form `_var4`.
    Two properties should be given:

    - `Number`: The number of random instances.
    - `Weights`: A comma-separated list of weights for each instance.

    Any variant has a chance of weight/sum(weights) of being chosen:
    A weight of `2, 1, 1` means the first instance has a 2/4 chance of
    being chosen, and the other 2 have a 1/4 chance of being chosen.
    The chosen variant depends on the position, direction and name of
    the instance.

    Alternatively, you can use `"variant" "number"` to choose from
    equally-weighted options.
    """
    if res.has_children():
        count_val = res['Number']  # or raise an error
        try:
            count = int(count_val)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid variant count {count_val}!')
        weighting = conditions.weighted_random(
            count,
            res['weights', ''],
        )
    else:
        try:
            count = int(res.value)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid variant count {res.value!r}!')
        else:
            weighting = list(range(count))

    def apply_variant(inst: Entity) -> None:
        """Apply the variant."""
        set_random_seed(inst, 'variant')
        conditions.add_suffix(inst, f"_var{str(random.choice(weighting) + 1)}")
    return apply_variant


@make_result('RandomNum')
def res_rand_num(inst: Entity, res: Property) -> None:
    """Generate a random number and save in a fixup value.

    If 'decimal' is true, the value will contain decimals. 'max' and 'min' are
    inclusive. 'ResultVar' is the variable the result will be saved in.
    If 'seed' is set, it will be used to keep the value constant across
    map recompiles. This should be unique.
    """
    is_float = srctools.conv_bool(res['decimal'])
    max_val = srctools.conv_float(res['max', 1.0])
    min_val = srctools.conv_float(res['min', 0.0])
    var = res['resultvar', '$random']
    seed = 'd' + res['seed', 'random']

    set_random_seed(inst, seed)

    if is_float:
        func = random.uniform
    else:
        func = random.randint

    inst.fixup[var] = str(func(min_val, max_val))


@make_result('RandomVec')
def res_rand_vec(inst: Entity, res: Property) -> None:
    """A modification to RandomNum which generates a random vector instead.

    `decimal`, `seed` and `ResultVar` work like RandomNum. `min_x`, `max_y` etc
    are used to define the boundaries. If the min and max are equal that number
    will be always used instead.
    """
    is_float = srctools.conv_bool(res['decimal'])
    var = res['resultvar', '$random']

    set_random_seed(inst, 'e' + res['seed', 'random'])

    if is_float:
        func = random.uniform
    else:
        func = random.randint

    value = Vec()

    for axis in 'xyz':
        max_val = srctools.conv_float(res['max_' + axis, 0.0])
        min_val = srctools.conv_float(res['min_' + axis, 0.0])
        if min_val == max_val:
            value[axis] = min_val
        else:
            value[axis] = func(min_val, max_val)

    inst.fixup[var] = value.join(' ')


@make_result_setup('randomShift')
def res_rand_inst_shift_setup(res: Property) -> tuple:
    min_x = res.float('min_x')
    max_x = res.float('max_x')
    min_y = res.float('min_y')
    max_y = res.float('max_y')
    min_z = res.float('min_z')
    max_z = res.float('max_z')

    return (
        min_x, max_x,
        min_y, max_y,
        min_z, max_z,
        'f' + res['seed', 'randomshift']
    )


@make_result('randomShift')
def res_rand_inst_shift(inst: Entity, res: Property) -> None:
    """Randomly shift a instance by the given amounts.

    The positions are local to the instance.
    """
    (
        min_x, max_x,
        min_y, max_y,
        min_z, max_z,
        seed,
    ) = res.value  # type: float, float, float, float, float, float, str

    set_random_seed(inst, seed)

    offset = Vec(
        random.uniform(min_x, max_x),
        random.uniform(min_y, max_y),
        random.uniform(min_z, max_z),
    ).rotate_by_str(inst['angles'])

    origin = Vec.from_str(inst['origin'])
    origin += offset
    inst['origin'] = origin
