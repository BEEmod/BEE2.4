"""Conditions for randomising instances."""
import functools
import random
from typing import Callable

from srctools import Property, Vec, Entity, Angle
from precomp import conditions
import srctools

from precomp.conditions import (
    Condition, RES_EXHAUSTED,
    set_random_seed, make_flag, make_result,
)

COND_MOD_NAME = 'Randomisation'


@make_flag('random')
def flag_random(res: Property) -> Callable[[Entity], bool]:
    """Randomly is either true or false."""
    if res.has_children():
        chance = res['chance', '100']
        seed = 'a' + res['seed', '']
    else:
        chance = res.value
        seed = 'a'

    # Allow ending with '%' sign
    chance = srctools.conv_int(chance.rstrip('%'), 100)

    def rand_func(inst: Entity) -> bool:
        """Apply the random chance."""
        set_random_seed(inst, seed)
        return random.randrange(100) < chance
    return rand_func


@make_result('random')
def res_random(res: Property) -> Callable[[Entity], None]:
    """Randomly choose one of the sub-results to execute.

    The `chance` value defines the percentage chance for any result to be
    chosen. `weights` defines the weighting for each result. Both are
    comma-separated, matching up with the results following. Wrap a set of
    results in a `group` property block to treat them as a single result to be
    executed in order.
    """
    weight_str = ''
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
            weight_str = prop.value
        elif prop.name == 'seed':
            seed = 'b' + prop.value
        else:
            results.append(prop)

    if not results:
        # Does nothing
        return lambda e: None

    weights_list = conditions.weighted_random(len(results), weight_str)

    # Note: We can't delete 'global' results, instead replace by 'dummy'
    # results that don't execute.
    # Otherwise the chances would be messed up.
    def apply_random(inst: Entity) -> None:
        """Pick a random result and run it."""
        set_random_seed(inst, seed)
        if random.randrange(100) > chance:
            return

        ind = random.choice(weights_list)
        choice = results[ind]
        if choice.name == 'nop':
            pass
        elif choice.name == 'group':
            for sub_res in choice:
                if Condition.test_result(
                    inst,
                    sub_res,
                ) is RES_EXHAUSTED:
                    sub_res.name = 'nop'
                    sub_res.value = ''
        else:
            if Condition.test_result(
                inst,
                choice,
            ) is RES_EXHAUSTED:
                choice.name = 'nop'
                choice.value = ''
    return apply_random


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
def res_rand_num(res: Property) -> Callable[[Entity], None]:
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

    if is_float:
        func = functools.partial(random.uniform, min_val, max_val)
    else:
        func = functools.partial(random.randint, min_val, max_val)

    def randomise(inst: Entity) -> None:
        """Apply the random number."""
        set_random_seed(inst, seed)
        inst.fixup[var] = str(func())
    return randomise


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


@make_result('randomShift')
def res_rand_inst_shift(res: Property) -> Callable[[Entity], None]:
    """Randomly shift a instance by the given amounts.

    The positions are local to the instance.
    """
    min_x = res.float('min_x')
    max_x = res.float('max_x')
    min_y = res.float('min_y')
    max_y = res.float('max_y')
    min_z = res.float('min_z')
    max_z = res.float('max_z')

    seed = 'f' + res['seed', 'randomshift']

    def shift_ent(inst: Entity) -> None:
        """Randomly shift the instance."""
        set_random_seed(inst, seed)
        pos = Vec(
            random.uniform(min_x, max_x),
            random.uniform(min_y, max_y),
            random.uniform(min_z, max_z),
        )
        pos.localise(Vec.from_str(inst['origin']), Angle.from_str(inst['angles']))
        inst['origin'] = pos
    return shift_ent
