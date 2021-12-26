"""Logical flags used to combine others (AND, OR, NOT, etc)."""
from precomp.collisions import Collisions
from precomp.conditions import make_flag, check_flag
from srctools import Entity, Property, VMF


COND_MOD_NAME = 'Logic'


@make_flag('AND')
def flag_and(inst: Entity, coll: Collisions, flag: Property):
    """The AND group evaluates True if all sub-flags are True."""
    for i, sub_flag in enumerate(flag):
        if not check_flag(sub_flag, coll, inst, can_skip=i == 0):
            return False
    return True


@make_flag('OR')
def flag_or(inst: Entity, coll: Collisions, flag: Property):
    """The OR group evaluates True if any sub-flags are True."""
    for sub_flag in flag:
        if check_flag(sub_flag, coll, inst):
            return True
    return False


@make_flag('NOT')
def flag_not(inst: Entity, coll: Collisions, flag: Property):
    """The NOT group inverts the value of it's one sub-flag."""
    try:
        [subflag] = flag
    except ValueError:
        return False
    return not check_flag(subflag, coll, inst)


@make_flag('XOR')
def flag_xor(inst: Entity, coll: Collisions, flag:Property):
    """The XOR group returns True if the number of true sub-flags is odd."""
    return sum([check_flag(sub_flag, coll, inst) for sub_flag in flag]) % 2 == 1


@make_flag('NOR')
def flag_nor(inst: Entity, coll: Collisions, flag: Property) -> bool:
    """The NOR group evaluates True if any sub-flags are False."""
    for sub_flag in flag:
        if check_flag(sub_flag, coll, inst):
            return True
    return False


@make_flag('NAND')
def flag_nand(inst: Entity, coll: Collisions, flag: Property) -> bool:
    """The NAND group evaluates True if all sub-flags are False."""
    for sub_flag in flag:
        if not check_flag(sub_flag, coll, inst):
            return True
    return False
