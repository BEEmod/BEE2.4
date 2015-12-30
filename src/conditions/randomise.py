"""Conditions for randomising instances."""
import random

from property_parser import Property
from conditions import (
    Condition, make_result, make_result_setup, RES_EXHAUSTED,
)
import conditions
import utils

@make_result_setup('random')
def res_random_setup(res):
    weight = ''
    results = []
    chance = 100
    seed = ''
    for prop in res:
        if prop.name == 'chance':
            # Allow ending with '%' sign
            chance = utils.conv_int(
                prop.value.rstrip('%'),
                chance,
            )
        elif prop.name == 'weights':
            weight = prop.value
        elif prop.name == 'seed':
            seed = prop.value
        else:
            results.append(prop)

    if not results:
        return None  # Invalid!

    weight = conditions.weighted_random(len(results), weight)

    # We also need to execute result setups on all child properties!
    for prop in results[:]:
        if prop.name == 'group':
            for sub_prop in prop.value[:]:
                Condition.setup_result(prop.value, sub_prop)
        else:
            Condition.setup_result(results, prop)

    return seed, chance, weight, results


@make_result('random')
def res_random(inst, res):
    """Randomly choose one of the sub-results to execute.

    The "chance" value defines the percentage chance for any result to be
    chosen. "weights" defines the weighting for each result. Wrap a set of
    results in a "group" property block to treat them as a single result to be
    executed in order.
    """
    # Note: 'global' results like "Has" won't delete themselves!
    # Instead they're replaced by 'dummy' results that don't execute.
    # Otherwise the chances would be messed up.
    seed, chance, weight, results = res.value
    random.seed('random_case_{}:{}_{}_{}'.format(
        seed,
        inst['targetname', ''],
        inst['origin'],
        inst['angles'],
    ))
    if random.randrange(100) > chance:
        return

    ind = random.choice(weight)
    choice = results[ind]  # type: Property
    if choice.name == 'group':
        for sub_res in choice.value:
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


@make_result_setup('variant')
def res_add_variant_setup(res):
    count = utils.conv_int(res['Number', ''], None)
    if count:
        return conditions.weighted_random(
            count,
            res['weights', ''],
        )
    else:
        return None


@make_result('variant')
def res_add_variant(inst, res):
    """This allows using a random instance from a weighted group.

    A suffix will be added in the form "_var4".
    Two properties should be given:
        Number: The number of random instances.
        Weights: A comma-separated list of weights for each instance.
    Any variant has a chance of weight/sum(weights) of being chosen:
    A weight of "2, 1, 1" means the first instance has a 2/4 chance of
    being chosen, and the other 2 have a 1/4 chance of being chosen.
    The chosen variant depends on the position, direction and name of
    the instance.
    """
    import vbsp
    if inst['targetname', ''] == '':
        # some instances don't get names, so use the global
        # seed instead for stuff like elevators.
        random.seed(vbsp.MAP_RAND_SEED + inst['origin'] + inst['angles'])
    else:
        # We still need to use angles and origin, since things like
        # fizzlers might not get unique names.
        random.seed(inst['targetname'] + inst['origin'] + inst['angles'])
    conditions.add_suffix(inst, "_var" + str(random.choice(res.value) + 1))

    
@make_result('RandomNum')
def res_rand_num(inst, res):
    """Generate a random number and save in a fixup value.

    If 'decimal' is true, the value will contain decimals. 'max' and 'min' are
    inclusive. 'ResultVar' is the variable the result will be saved in.
    If 'seed' is set, it will be used to keep the value constant across
    map recompiles. This should be unique.
    """
    is_float = utils.conv_bool(res['decimal'])
    max_val = utils.conv_float(res['max', 1.0])
    min_val = utils.conv_float(res['min', 0.0])
    var = res['resultvar', '$random']
    seed = res['seed', 'random']

    random.seed(inst['origin'] + inst['angles'] + 'random_' + seed)

    if is_float:
        func = random.uniform
    else:
        func = random.randint

    inst.fixup[var] = str(func(min_val, max_val))


@make_result('RandomVec')
def res_rand_vec(inst, res):
    """A modification to RandomNum which generates a random vector instead.

    'decimal', 'seed' and 'ResultVar' work like RandomNum. min/max x/y/z
    are for each section. If the min and max are equal that number will be used
    instead.
    """
    is_float = utils.conv_bool(res['decimal'])
    var = res['resultvar', '$random']
    seed = res['seed', 'random']

    random.seed(inst['origin'] + inst['angles'] + 'random_' + seed)

    if is_float:
        func = random.uniform
    else:
        func = random.randint

    value = Vec()

    for axis in 'xyz':
        max_val = utils.conv_float(res['max_' + axis, 0.0])
        min_val = utils.conv_float(res['min_' + axis, 0.0])
        if min_val == max_val:
            value[axis] = min_val
        else:
            value[axis] = func(min_val, max_val)

    inst.fixup[var] = value.join(' ')