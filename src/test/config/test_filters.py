"""Test the filtering configuration."""
from srctools import Keyvalues
from srctools.dmx import Element, ValueType
import pytest

from config.filters import FilterConf


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 state."""
    conf = FilterConf.parse_kv1(
        Keyvalues('', [
            Keyvalues('compress', '1')
        ]),
        1,
    )
    assert conf.compress is True

    conf = FilterConf.parse_kv1(
        Keyvalues('', [
            Keyvalues('compress', '0')
        ]),
        1,
    )
    assert conf.compress is False

    conf = FilterConf.parse_kv1(
        Keyvalues('', []),
        1,
    )
    assert conf.compress is False

    with pytest.raises(AssertionError):
        FilterConf.parse_kv1(Keyvalues('', []), 2)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 state."""
    state = FilterConf(compress=False)
    kv = state.export_kv1()
    assert len(kv) == 1
    assert kv['compress'] == '0'

    state = FilterConf(compress=True)
    kv = state.export_kv1()
    assert len(kv) == 1
    assert kv['compress'] == '1'


def test_parse_dmx() -> None:
    """Test parsing DMX state."""
    elem = Element('ItemFilters', 'DMElement')

    conf = FilterConf.parse_dmx(elem, 1)
    assert conf.compress is False

    elem['compress'] = '1'

    conf = FilterConf.parse_dmx(elem, 1)
    assert conf.compress is True

    elem['compress'] = '0'

    conf = FilterConf.parse_dmx(elem, 1)
    assert conf.compress is False

    with pytest.raises(AssertionError):
        FilterConf.parse_dmx(elem, 2)


def test_export_dmx() -> None:
    """Test exporting DMX state."""
    state = FilterConf(compress=False)
    elem = state.export_dmx()
    assert len(elem) == 2
    assert elem['compress'].type is ValueType.BOOL
    assert elem['compress'].val_bool is False

    state = FilterConf(compress=True)
    elem = state.export_dmx()
    assert len(elem) == 2
    assert elem['compress'].type is ValueType.BOOL
    assert elem['compress'].val_bool is True
