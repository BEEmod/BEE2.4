"""Conditions for randomising instances."""
from typing import Callable

from srctools import Keyvalues, Vec, Entity, Angle
import srctools

from precomp import collisions, conditions, rand
from precomp.conditions import Condition, RES_EXHAUSTED, make_flag, make_result, MapInfo

COND_MOD_NAME = 'Randomisation'


@make_flag('random')
def flag_random(res: Keyvalues) -> Callable[[Entity], bool]:
    """Randomly is either true or false."""
    if res.has_children():
        chance_str = res['chance', '100']
        seed = res['seed', '']
    else:
        chance_str = res.value
        seed = ''

    # Allow ending with '%' sign
    chance = srctools.conv_int(chance_str.rstrip('%'), 100)

    def rand_func(inst: Entity) -> bool:
        """Apply the random chance."""
        return rand.seed(b'rand_flag', inst, seed).randrange(100) < chance
    return rand_func


@make_result('random')
def res_random(coll: collisions.Collisions, info: MapInfo, res: Keyvalues) -> conditions.ResultCallable:
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
    seed = ''
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

    weights_list = rand.parse_weights(len(results), weight_str)

    # Note: We can't delete 'global' results, instead replace by 'dummy'
    # results that don't execute.
    # Otherwise the chances would be messed up.
    def apply_random(inst: Entity) -> None:
        """Pick a random result and run it."""
        rng = rand.seed(b'rand_res', inst, seed)
        if rng.randrange(100) > chance:
            return

        ind = rng.choice(weights_list)
        choice = results[ind]
        if choice.name == 'nop':
            pass
        elif choice.name == 'group':
            for sub_res in choice:
                if Condition.test_result(coll, info, inst, sub_res) is RES_EXHAUSTED:
                    sub_res.name = 'nop'
                    sub_res.value = ''
        else:
            if Condition.test_result(coll, info, inst, choice) is RES_EXHAUSTED:
                choice.name = 'nop'
                choice.value = ''
    return apply_random


@make_result('variant')
def res_add_variant(res: Keyvalues) -> Callable[[Entity], None]:
    """This allows using a random instance from a weighted group.

    A suffix will be added in the form `_var4`.
    Two or three properties should be given:

    - `Number`: The number of random instances.
    - `Weights`: A comma-separated list of weights for each instance.
    - `seed`: Optional seed to disambiuate multiple options.

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
        weighting = rand.parse_weights(count, res['weights', ''])
        seed = res['seed', '']
    else:
        try:
            count = int(res.value)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid variant count {res.value!r}!')
        else:
            weighting = list(range(count))
        seed = res.value

    def apply_variant(inst: Entity) -> None:
        """Apply the variant."""
        rng = rand.seed(b'variant', inst, seed)
        conditions.add_suffix(inst, f"_var{rng.choice(weighting) + 1}")
    return apply_variant


@make_result('RandomNum')
def res_rand_num(inst: Entity, res: Keyvalues) -> None:
    """Generate a random number and save in a fixup value.

    Parameters:

    - `decimal`: If true, the value will contain decimals, otherwise it is integer only.
    - `ResultVar` is the `$fixup` variable the result will be saved in.
    - `seed`: If this is set, it will be used to keep the value constant across map recompiles.
       This should be unique to this use of `RandomVec`.
    - `min`, `max` etc: These are used to define the range to generate (inclusive). If the min
       and max are equal that number will always be used instead.
    """
    var = res['resultvar', '$random']
    rng = rand.seed(b'rand_num', inst, res['seed', ''])

    if res.bool('decimal'):
        max_float = res.float('max', 1.0)
        min_float = res.float('min', 0.0)
        if min_float == max_float:
            inst.fixup[var] = min_float
        else:
            inst.fixup[var] = rng.uniform(min_float, max_float)
    else:
        max_int = res.int('max', 1)
        min_int = res.int('min', 0)
        if min_int == max_int:
            inst.fixup[var] = min_int
        else:
            inst.fixup[var] = rng.randint(min_int, max_int)


@make_result('RandomVec')
def res_rand_vec(inst: Entity, res: Keyvalues) -> None:
    """A variant of `RandomNum` which generates a random vector instead.

    Parameters:

    - `decimal`: If true, the value will contain decimals, otherwise it is integer only.
    - `ResultVar` is the `$fixup` variable the result will be saved in.
    - `seed`: If this is set, it will be used to keep the value constant across map recompiles.
       This should be unique to this use of `RandomVec`.
    - `min_x`, `max_y` etc: These are used to define the range to generate (inclusive). If the min
       and max are equal that number will always be used instead.
    """
    var = res['resultvar', '$random']
    rng = rand.seed(b'rand_vec', inst, res['seed', ''])

    value = Vec()
    if res.bool('decimal'):
        for axis in 'xyz':
            max_float = res.float('max_' + axis, 0.0)
            min_float = res.float('min_' + axis, 0.0)
            if min_float == max_float:
                value[axis] = min_float
            else:
                value[axis] = rng.uniform(min_float, max_float)
    else:
        for axis in 'xyz':
            max_int = res.int('max_' + axis, 0)
            min_int = res.int('min_' + axis, 0)
            if min_int == max_int:
                value[axis] = min_int
            else:
                value[axis] = rng.randint(min_int, max_int)

    inst.fixup[var] = value


@make_result('randomShift')
def res_rand_inst_shift(res: Keyvalues) -> Callable[[Entity], None]:
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
        rng = rand.seed(b'rand_shift', inst, seed)
        pos = Vec(
            rng.uniform(min_x, max_x),
            rng.uniform(min_y, max_y),
            rng.uniform(min_z, max_z),
        )
        pos.localise(Vec.from_str(inst['origin']), Angle.from_str(inst['angles']))
        inst['origin'] = pos
    return shift_ent
