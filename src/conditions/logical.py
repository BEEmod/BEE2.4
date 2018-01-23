"""Logical flags used to combine others (AND, OR, NOT, etc)."""

from conditions import make_flag, check_flag
from srctools import Entity, Property

COND_MOD_NAME = 'Logic'


@make_flag('AND')
def flag_and(inst: Entity, flag: Property):
    """The AND group evaluates True if all sub-flags are True."""
    for sub_flag in flag:
        if not check_flag(sub_flag, inst):
            return False
    return True


@make_flag('OR')
def flag_or(inst: Entity, flag: Property):
    """The OR group evaluates True if any sub-flags are True."""
    for sub_flag in flag:
        if check_flag(sub_flag, inst):
            return True
    return False


@make_flag('NOT')
def flag_not(inst: Entity, flag: Property):
    """The NOT group inverts the value of it's one sub-flag."""
    if len(flag.value) == 1:
        return not check_flag(flag[0], inst)
    return False


@make_flag('XOR')
def flag_xor(inst: Entity, flag:Property):
    """The XOR group returns True if the number of true sub-flags is odd."""
    return sum([check_flag(sub_flag, inst) for sub_flag in flag]) % 2 == 1


@make_flag('NOR')
def flag_nor(inst: Entity, flag: Property):
    """The NOR group evaluates True if any sub-flags are False."""
    return not flag_or(inst, flag)


@make_flag('NAND')
def flag_nand(inst: Entity, flag: Property):
    """The NAND group evaluates True if all sub-flags are False."""
    return not flag_and(inst, flag)
