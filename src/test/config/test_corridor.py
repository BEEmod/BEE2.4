"""Test parsing corridor configurations."""
import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element, Attribute, ValueType

from config.corridors import Direction, GameMode, Orient, Config, UIState

# Two sets of sample instance names, for testing parsing.
CORR_SEL = [
    'instances/bee2/some_selected_1.vmf',
    'instances/bee2/some_selected_2.vmf',
    'instances/bee2/some_selected_3.vmf'
]
CORR_UNSEL = [
    'instances/bee2/some_unsel_1.vmf',
    'instances/bee2/some_unsel_2.vmf',
]


def test_conf_parse_kv1() -> None:
    """Test parsing keyvalues1 configs."""
    kv = Keyvalues.root(
        Keyvalues('Corridors', [
            Keyvalues('selected', 'instances/bee2/some_selected_1.vmf'),
            Keyvalues('unselected', 'instances/bee2/some_unsel_1.vmf'),
            Keyvalues('unselected', 'instances/bee2/some_unsel_2.vmf'),
            Keyvalues('selected', 'instances/bee2/some_selected_2.vmf'),
            Keyvalues('selected', 'instances/bee2/some_selected_3.vmf'),
        ])
    )
    assert Config.parse_kv1(kv, 1) == Config(selected=CORR_SEL, unselected=CORR_UNSEL)

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        Config.parse_kv1(kv, 2)


def test_conf_export_kv1() -> None:
    """Test exporting keyvalues1 configs."""
    kv = Config(selected=CORR_SEL, unselected=CORR_UNSEL).export_kv1()

    assert len(kv) == 1
    corr = kv.find_key('Corridors')
    assert len(corr) == 5

    # We don't care how these are interspersed.
    selected = [prop.value for prop in corr.find_all('selected')]
    unselected = [prop.value for prop in corr.find_all('unselected')]

    assert selected == CORR_SEL
    assert unselected == CORR_UNSEL


def test_conf_parse_dmx() -> None:
    """Test parsing dmx configs."""
    elem = Element('CorrConfig', 'DMElement')
    elem['selected'] = CORR_SEL
    elem['unselected'] = CORR_UNSEL

    assert Config.parse_dmx(elem, 1) == Config(selected=CORR_SEL, unselected=CORR_UNSEL)


def test_conf_export_dmx() -> None:
    """Test exporting DMX configs."""
    elem = Config(selected=CORR_SEL, unselected=CORR_UNSEL).export_dmx()
    assert len(elem) == 2
    assert list(elem['selected'].iter_string()) == CORR_SEL
    assert list(elem['unselected'].iter_string()) == CORR_UNSEL
