"""Logical tests used to combine others (AND, OR, NOT, etc)."""
from precomp.collisions import Collisions
from precomp.conditions import make_test, check_test, MapInfo, Unsatisfiable
from srctools import Entity, Keyvalues

from quote_pack import QuoteInfo


COND_MOD_NAME = 'Logic'


@make_test('AND')
def check_and(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The AND group evaluates True if all subtests are True."""
    for i, sub_test in enumerate(kv):
        if not check_test(sub_test, coll, info, voice, inst, can_skip=i == 0):
            return False
    return True


@make_test('OR')
def check_or(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The OR group evaluates True if any subtests are True."""
    satisfiable = False
    for sub_test in kv:
        try:
            res = check_test(sub_test, coll, info, voice, inst, can_skip=True)
        except Unsatisfiable:
            pass
        else:
            satisfiable = True
            if res:
                return True
    if not satisfiable:
        # All raised, we raise too.
        raise Unsatisfiable
    return False


@make_test('NOT')
def check_not(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NOT group inverts the value of it's one subtest.

    Alternatively, simply prefix any test with `!` (`"!instance"`).
    """
    try:
        [subtest] = kv
    except ValueError:
        return False
    return not check_test(subtest, coll, info, voice, inst)


@make_test('XOR')
def check_xor(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The XOR group returns True if the number of true subtests is odd."""
    return sum([check_test(sub_test, coll, info, voice, inst) for sub_test in kv]) % 2 == 1


@make_test('NOR')
def check_nor(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NOR group evaluates True if any subtests are False."""
    for sub_test in kv:
        if check_test(sub_test, coll, info, voice, inst):
            return True
    return False


@make_test('NAND')
def chec_nand(
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, kv: Keyvalues,
) -> bool:
    """The NAND group evaluates True if all subtests are False."""
    for sub_test in kv:
        if not check_test(sub_test, coll, info, voice, inst):
            return True
    return False
