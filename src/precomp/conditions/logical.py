"""Logical flags used to combine others (AND, OR, NOT, etc)."""
from precomp.collisions import Collisions
from precomp.conditions import make_flag, check_flag, MapInfo, Unsatisfiable
from srctools import Entity, Keyvalues


COND_MOD_NAME = 'Logic'


@make_flag('AND')
def flag_and(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The AND group evaluates True if all sub-flags are True."""
    for i, sub_flag in enumerate(flag):
        if not check_flag(sub_flag, coll, info, inst, can_skip=i == 0):
            return False
    return True


@make_flag('OR')
def flag_or(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The OR group evaluates True if any sub-flags are True."""
    satisfiable = False
    for sub_flag in flag:
        try:
            res = check_flag(sub_flag, coll, info, inst, can_skip=True)
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


@make_flag('NOT')
def flag_not(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The NOT group inverts the value of it's one sub-flag."""
    try:
        [subflag] = flag
    except ValueError:
        return False
    return not check_flag(subflag, coll, info, inst)


@make_flag('XOR')
def flag_xor(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The XOR group returns True if the number of true sub-flags is odd."""
    return sum([check_flag(sub_flag, coll, info, inst) for sub_flag in flag]) % 2 == 1


@make_flag('NOR')
def flag_nor(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The NOR group evaluates True if any sub-flags are False."""
    for sub_flag in flag:
        if check_flag(sub_flag, coll, info, inst):
            return True
    return False


@make_flag('NAND')
def flag_nand(inst: Entity, coll: Collisions, info: MapInfo, flag: Keyvalues) -> bool:
    """The NAND group evaluates True if all sub-flags are False."""
    for sub_flag in flag:
        if not check_flag(sub_flag, coll, info, inst):
            return True
    return False
