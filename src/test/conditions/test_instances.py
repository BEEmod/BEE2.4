"""Test the instances tests/results."""
from srctools import Keyvalues, VMF

from precomp.conditions import instances as inst_mod


def test_instvar() -> None:
    """Test the InstVar test."""
    inst = VMF().create_ent('func_instance')
    inst.fixup['$fortytwo'] = '42.0'
    inst.fixup['ten_half'] = '10.50'
    inst.fixup['$exists'] = 'real'
    inst.fixup['$truth'] = 'true'
    inst.fixup['$two'] = '2'
    inst.fixup['$blank'] = ''
    inst.fixup['$zero'] = '0'
    inst.fixup['$spaced'] = 'spaced value'

    assert inst_mod.test_instvar(inst, Keyvalues('', '$exists == real'))
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$fortytwo > 80'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$fortytwo = $fortytwo'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$fortytwo > $ten_half'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '45 >= $fortytwo'))
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$fortytwo < 30'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '1 != $two'))
    # Check we use decimal compares, precision is ignored.
    assert inst_mod.test_instvar(inst, Keyvalues('', '1.9999999999999999999999999 =/= $two'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '30 => $ten_half'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '10.5 => $ten_half'))
    # Special cases - one value = boolean, two = either blank val-2 or assume equality.
    assert inst_mod.test_instvar(inst, Keyvalues('', '$truth'))
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$zero'))
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$exists =='))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$blank =='))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$missing =='))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$two 2'))
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$two 8'))

    # The full three-value setup allows spaces in value B.
    assert not inst_mod.test_instvar(inst, Keyvalues('', '$spaced == spaced'))
    assert inst_mod.test_instvar(inst, Keyvalues('', '$spaced == spaced value'))
