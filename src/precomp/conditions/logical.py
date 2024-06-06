"""Logical tests used to combine others (AND, OR, NOT, etc)."""
from enum import Enum

from srctools import Entity, Keyvalues, logger

from quote_pack import QuoteInfo
from precomp.collisions import Collisions
from precomp.rand import seed
from precomp import conditions


COND_MOD_NAME = 'Logic'
LOGGER = logger.get_logger(__name__, alias='cond.logical')


@conditions.make_test('AND')
def check_and(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    kv: Keyvalues,
) -> conditions.TestCallable:
    """The AND group evaluates True if all subtests are True."""
    children = [conditions.Test.parse_kv(sub_test) for sub_test in kv]
    def test(inst: Entity) -> bool:
        for i, sub_test in enumerate(children):
            if not sub_test.test(coll, info, voice, inst, can_skip=i == 0):
                return False
        return True
    return test


@conditions.make_test('OR')
def check_or(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    kv: Keyvalues,
) -> conditions.TestCallable:
    """The OR group evaluates True if any subtests are True."""
    children = [conditions.Test.parse_kv(sub_test) for sub_test in kv]
    def test(inst: Entity) -> bool:
        satisfiable = False
        for sub_test in children:
            try:
                res = sub_test.test(coll, info, voice, inst, can_skip=True)
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
    return test


@conditions.make_test('NOT')
def check_not(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    kv: Keyvalues,
) -> conditions.TestCallable:
    """The NOT group inverts the value of it's one subtest.

    Alternatively, simply prefix any test with `!` (`"!instance"`).
    """
    try:
        [child] = kv
    except ValueError:
        return lambda inst: False

    sub_test = conditions.Test.parse_kv(child)

    def test(inst: Entity) -> bool:
        return not sub_test.test(coll, info, voice, inst)
    return test


@conditions.make_test('XOR')
def check_xor(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> conditions.TestCallable:
    """The XOR group returns True if the number of true subtests is odd."""
    children = [conditions.Test.parse_kv(sub_test) for sub_test in kv]
    def test(inst: Entity) -> bool:
        return sum([sub_test.test(coll, info, voice, inst) for sub_test in children]) % 2 == 1
    return test


@conditions.make_test('NOR')
def check_nor(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> conditions.TestCallable:
    """The NOR group evaluates True if any subtests are False."""
    children = [conditions.Test.parse_kv(sub_test) for sub_test in kv]
    def test(inst: Entity) -> bool:
        for sub_test in children:
            if sub_test.test(coll, info, voice, inst):
                return True
        return False
    return test


@conditions.make_test('NAND')
def check_nand(
    coll: Collisions, info: conditions.MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> conditions.TestCallable:
    """The NAND group evaluates True if all subtests are False."""
    children = [conditions.Test.parse_kv(sub_test) for sub_test in kv]
    def test(inst: Entity) -> bool:
        for sub_test in children:
            if not sub_test.test(coll, info, voice, inst):
                return True
        return False
    return test


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
    default: list[conditions.Result] = []
    rand_seed = ''
    for kv in res:
        if kv.has_children():
            if kv.name == '<default>':
                for res in kv:
                    default.append(conditions.Result.parse_kv(res))
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

    conf_cases: list[tuple[conditions.Test | None, list[conditions.Result]]] = []
    for case in raw_cases:
        # In random mode, this can be None to always succeed.
        if method is not SwitchType.RANDOM or case.name:
            test = conditions.Test.parse_kv(Keyvalues(test_name, case.real_name))
        else:
            test = None
        case_res = [
            conditions.Result.parse_kv(res)
            for res in case
        ]
        conf_cases.append((test, case_res))

    def apply_switch(inst: Entity) -> None:
        """Execute a switch."""
        if method is SwitchType.RANDOM:
            cases = conf_cases.copy()
            seed(b'switch', rand_seed, inst).shuffle(cases)
        else:  # Won't change.
            cases = conf_cases

        run_default = True
        for test, results in cases:
            # If not set, always succeed for the random situation.
            if test is not None and not test.test(coll, info, voice, inst):
                continue
            for sub_res in results:
                sub_res.execute(coll, info, voice, inst)
            run_default = False
            if method is not SwitchType.ALL:
                # All does them all, otherwise we quit now.
                break
        if run_default:
            for sub_res in default:
                sub_res.execute(coll, info, voice, inst)
    return apply_switch
