"""Test the lazy value behaviour."""
import pytest
from srctools import VMF

from precomp.lazy_value import Value, ConstValue, InstValue, UnaryMapValue


def test_parse() -> None:
    """Test parsing values."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$var'] = 'value'

    const_val = Value.parse('some constant')
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 'some constant'
    assert const_val(ent) == 'some constant'

    inst_val = Value.parse('some $var')
    assert isinstance(inst_val, InstValue)
    assert inst_val.variable == 'some $var'
    assert inst_val(ent) == 'some value'

    missing = Value.parse('$missing = ')
    with pytest.raises(KeyError):
        missing(ent)


def test_map_int() -> None:
    """Test mapping to an int."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$value'] = '42'

    const_val = Value.parse('42').as_int(86)
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 42
    assert const_val(ent) == 42

    inst_val = Value.parse('$value').as_int(45)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 42

    inst_val = Value.parse('$missing', '').as_int(12)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 12


def test_map_float() -> None:
    """Test mapping to a float."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$value'] = '3.14'

    const_val = Value.parse('3.24').as_float(18.92)
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 3.24
    assert const_val(ent) == 3.24

    inst_val = Value.parse('$value').as_float(82.9)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 3.14

    inst_val = Value.parse('$missing', '').as_float(98.72)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 98.72
