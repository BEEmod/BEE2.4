"""Test the lazy value behaviour."""
from typing import Any


from collections.abc import Callable

from srctools import VMF
import pytest

from precomp.lazy_value import LazyValue, ConstValue, InstValue, UnaryMapValue


def test_parse() -> None:
    """Test parsing values."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$var'] = 'value'

    const_val = LazyValue.parse('some constant')
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 'some constant'
    assert const_val(ent) == 'some constant'

    inst_val = LazyValue.parse('some $var')
    assert isinstance(inst_val, InstValue)
    assert inst_val.variable == 'some $var'
    assert inst_val(ent) == 'some value'

    missing = LazyValue.parse('$missing = ')
    with pytest.raises(KeyError):
        missing(ent)


def test_map_int() -> None:
    """Test mapping to an int."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$value'] = '42'

    const_val = LazyValue.parse('42').as_int(86)
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 42
    assert const_val(ent) == 42

    inst_val = LazyValue.parse('$value').as_int(45)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 42

    inst_val = LazyValue.parse('$missing', '').as_int(12)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 12


def test_map_float() -> None:
    """Test mapping to a float."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$value'] = '6.14'

    const_val = LazyValue.parse('3.24').as_float(18.92)
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 3.24
    assert const_val(ent) == 3.24

    inst_val = LazyValue.parse('$value').as_float(82.9)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 6.14

    inst_val = LazyValue.parse('$missing', '').as_float(98.72)
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 98.72


@pytest.mark.parametrize('func', [
    LazyValue.as_obj_id, LazyValue.as_obj_id_optional,
    LazyValue.as_special_id, LazyValue.as_special_id_optional
])
def test_map_ids(func: Callable[[LazyValue[str], str], LazyValue[Any]]) -> None:
    """Test mapping to object IDs."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$object'] = 'barrierHaz_ard'
    ent.fixup['$special'] = '<inHERit>'
    ent.fixup['$empty'] = ''

    const_val = func(LazyValue.parse('someID'), 'ID')
    assert isinstance(const_val, ConstValue)
    assert const_val.value == 'SOMEID'
    assert const_val(ent) == 'SOMEID'

    inst_val = func(LazyValue.parse('$object'), 'ID')
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == 'BARRIERHAZ_ARD'


@pytest.mark.parametrize('func', [
    LazyValue.as_obj_id_optional, LazyValue.as_special_id_optional
])
def test_map_id_optional(func: Callable[[LazyValue[str], str], LazyValue[Any]]) -> None:
    """Test mapping to optional object IDs."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$empty'] = ''

    const_val = LazyValue.parse('').as_obj_id_optional('ID')
    assert isinstance(const_val, ConstValue)
    assert const_val.value == ''
    assert const_val(ent) == ''

    inst_val = LazyValue.parse('$empty').as_obj_id_optional('ID')
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == ''

    with pytest.raises(ValueError, match=r"IDs may not be blank."):
        LazyValue.parse('').as_obj_id('No blanks')

    inst_val = LazyValue.parse('$empty').as_obj_id('Deferred raise')
    with pytest.raises(ValueError, match=r"IDs may not be blank."):
        inst_val(ent)


@pytest.mark.parametrize('func', [
    LazyValue.as_special_id, LazyValue.as_special_id_optional
])
def test_map_special_ids(func: Callable[[LazyValue[str], str], LazyValue[Any]]) -> None:
    """Test mapping to special IDs."""
    ent = VMF().create_ent('func_instance')
    ent.fixup['$special'] = '<inHERit>'

    const_val = func(LazyValue.parse('<speCial>'), 'ID')
    assert isinstance(const_val, ConstValue)
    assert const_val.value == '<SPECIAL>'
    assert const_val(ent) == '<SPECIAL>'

    inst_val = func(LazyValue.parse('$special'), 'ID')
    assert isinstance(inst_val, UnaryMapValue)
    assert inst_val(ent) == '<INHERIT>'

    with pytest.raises(ValueError, match=r"IDs may not start/end with brackets."):
        LazyValue.parse('<NONE>').as_obj_id('Invalid')
    with pytest.raises(ValueError, match=r"IDs may not start/end with brackets."):
        LazyValue.parse('<NONE>').as_obj_id_optional('Invalid')
