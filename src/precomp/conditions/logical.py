"""Logical tests used to combine others (AND, OR, NOT, etc)."""
from enum import Enum

from srctools import Entity, Keyvalues, logger

from quote_pack import QuoteInfo
from precomp.collisions import Collisions
from precomp import conditions


COND_MOD_NAME = 'Logic'
LOGGER = logger.get_logger(__name__, alias='cond.logical')


@conditions.make_test('AND')
def check_and(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The AND group evaluates True if all subtests are True."""
    for i, sub_test in enumerate(kv):
        if not conditions.check_test(sub_test, coll, info, voice, inst, can_skip=i == 0):
            return False
    return True


@conditions.make_test('OR')
def check_or(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The OR group evaluates True if any subtests are True."""
    satisfiable = False
    for sub_test in kv:
        try:
            res = conditions.check_test(sub_test, coll, info, voice, inst, can_skip=True)
        except conditions.Unsatisfiable:
            pass
        else:
            satisfiable = True
            if res:
                return True
    if not satisfiable:
        # All raised, we raise too.
        raise conditions.Unsatisfiable
    return False


@conditions.make_test('NOT')
def check_not(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NOT group inverts the value of it's one subtest.

    Alternatively, simply prefix any test with `!` (`"!instance"`).
    """
    try:
        [subtest] = kv
    except ValueError:
        return False
    return not conditions.check_test(subtest, coll, info, voice, inst)


@conditions.make_test('XOR')
def check_xor(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The XOR group returns True if the number of true subtests is odd."""
    return sum([conditions.check_test(sub_test, coll, info, voice, inst) for sub_test in kv]) % 2 == 1


@conditions.make_test('NOR')
def check_nor(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NOR group evaluates True if any subtests are False."""
    for sub_test in kv:
        if conditions.check_test(sub_test, coll, info, voice, inst):
            return True
    return False


@conditions.make_test('NAND')
def chec_nand(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NAND group evaluates True if all subtests are False."""
    for sub_test in kv:
        if not conditions.check_test(sub_test, coll, info, voice, inst):
            return True
    return False


@conditions.make_result('condition')
def res_sub_condition(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    res: Keyvalues,
) -> conditions.ResultCallable:
    """Check a different condition if the outer block is true."""
    cond = conditions.Condition.parse(res, toplevel=False)

    def test_cond(inst: Entity) -> None:
        """For child conditions, we need to check every time."""
        try:
            cond.test(coll, info, voice, inst)
        except conditions.Unsatisfiable:
            pass
    return test_cond


class SwitchType(Enum):
    """The methods useable for switch options."""
    FIRST = 'first'  # choose the first match
    LAST = 'last'  # choose the last match
    RANDOM = 'random'  # Randomly choose
    ALL = 'all'  # Run all matching commands


@conditions.make_result('switch')
def res_switch(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    res: Keyvalues,
) -> conditions.ResultCallable:
    """Run the same test multiple times with different arguments.

    * `method` is the way the search is done - `first`, `last`, `random`, or `all`.
    * `test` is the name of the test. (`flag` is accepted for backwards compatibility.)
    * `seed` sets the randomisation seed for this block, for the random mode.

    Each keyvalues group is a case to check - the Keyvalues name is the test
    argument, and the contents are the results to execute in that case.
    The special group `"<default>"` is only run if no other test is valid.
    For `random` mode, you can omit the test to choose from all objects. In
    this case the test arguments are ignored.
    """
    test_name = ''
    method = SwitchType.FIRST
    raw_cases: list[Keyvalues] = []
    default: list[Keyvalues] = []
    rand_seed = ''
    for kv in res:
        if kv.has_children():
            if kv.name == '<default>':
                default.extend(kv)
            else:
                raw_cases.append(kv)
        else:
            if kv.name == 'test':
                test_name = kv.value
                continue
            if kv.name == 'flag':
                LOGGER.warning('Switch uses deprecated field "flag", this has been renamed to "test".')
                test_name = kv.value
                continue
            if kv.name == 'method':
                try:
                    method = SwitchType(kv.value.casefold())
                except ValueError:
                    pass
            elif kv.name == 'seed':
                rand_seed = kv.value

    if method is SwitchType.LAST:
        raw_cases.reverse()

    conf_cases: list[tuple[Keyvalues, list[Keyvalues]]] = [
        (Keyvalues(test_name, case.real_name), list(case))
        for case in raw_cases
    ]

    def apply_switch(inst: Entity) -> None:
        """Execute a switch."""
        if method is SwitchType.RANDOM:
            cases = conf_cases.copy()
            conditions.rand.seed(b'switch', rand_seed, inst).shuffle(cases)
        else:  # Won't change.
            cases = conf_cases

        run_default = True
        for test, results in cases:
            # If not set, always succeed for the random situation.
            if test.real_name and not conditions.check_test(test, coll, info, voice, inst):
                continue
            for sub_res in results:
                conditions.Condition.test_result(coll, info, voice, inst, sub_res)
            run_default = False
            if method is not SwitchType.ALL:
                # All does them all, otherwise we quit now.
                break
        if run_default:
            for sub_res in default:
                conditions.Condition.test_result(coll, info, voice, inst, sub_res)
    return apply_switch
