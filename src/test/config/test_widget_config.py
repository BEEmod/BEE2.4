"""Test ConfigGroup stored state."""
import pytest
from srctools import Keyvalues
from srctools.dmx import Attribute, Element, ValueType

from config.widgets import TIMER_STR_INF, TimerNum, WidgetConfig


# Sample set of timer delays.
TIMER_DICT = {
    TIMER_STR_INF: "1",
    TimerNum("3"): "180",
    TimerNum("4"): "240",
    TimerNum("5"): "300",
    TimerNum("6"): "360",
    TimerNum("7"): "420",
    TimerNum("8"): "480",
    TimerNum("9"): "540",
    TimerNum("10"): "600",
    TimerNum("11"): "660",
    TimerNum("12"): "720",
    TimerNum("13"): "780",
    TimerNum("14"): "840",
    TimerNum("15"): "900",
    TimerNum("16"): "960",
    TimerNum("17"): "1020",
    TimerNum("18"): "1080",
    TimerNum("19"): "1140",
    TimerNum("20"): "1200",
    TimerNum("21"): "1260",
    TimerNum("22"): "1320",
    TimerNum("23"): "1380",
    TimerNum("24"): "1440",
    TimerNum("25"): "1500",
    TimerNum("26"): "1560",
    TimerNum("27"): "1620",
    TimerNum("28"): "1680",
    TimerNum("29"): "1740",
    TimerNum("30"): "1791",
}
TIMER_BLOCK = Keyvalues('timervalue', [
    Keyvalues(num, value)
    for num, value in TIMER_DICT.items()
])


def test_parse_legacy() -> None:
    """Test parsing the older config version."""
    kv = Keyvalues('ItemVar', [
        Keyvalues('VALVE_TEST_ELEM', [
            Keyvalues('LaserCollision', '1'),
            Keyvalues('FunnelSpeed', '250'),
        ]),
        Keyvalues('BEE_NEUROTOXIN', [TIMER_BLOCK.copy()]),
    ])
    res = WidgetConfig.parse_legacy(kv)
    assert res == {
        'VALVE_TEST_ELEM:LaserCollision': WidgetConfig('1'),
        'VALVE_TEST_ELEM:FunnelSpeed': WidgetConfig('250'),
        'BEE_NEUROTOXIN:timervalue': WidgetConfig(TIMER_DICT.copy()),
    }



def test_parse_invalid_versions() -> None:
    """Test errors are raised for invalid versions."""
    kv = Keyvalues('WidgetConfig', [])
    elem = Element('WidgetConfig', 'DMEConfig')

    with pytest.raises(AssertionError):
        WidgetConfig.parse_kv1(kv, 2)

    with pytest.raises(AssertionError):
        WidgetConfig.parse_dmx(elem, 2)


def test_parse_kv1_singular() -> None:
    """Test parsing keyvalues1 data, with a singular value."""
    res = WidgetConfig.parse_kv1(Keyvalues('ItemVar', 'testValue'), 1)
    assert res == WidgetConfig('testValue')


def test_export_kv1_singular() -> None:
    """Test producing new keyvalues1 data, with a singular value."""
    kv = WidgetConfig('testValue').export_kv1()
    assert kv.value == 'testValue'


def test_parse_kv1_timer() -> None:
    """Test parsing keyvalues1 data, with a timer value."""
    res = WidgetConfig.parse_kv1(TIMER_BLOCK.copy(), 1)
    assert res == WidgetConfig(TIMER_DICT.copy())


def test_export_kv1_timer() -> None:
    """Test producing new keyvalues1 data, with a timer value."""
    kv = WidgetConfig(TIMER_DICT.copy()).export_kv1()
    assert len(kv) == 29
    for num, value in TIMER_DICT.items():
        assert kv[num] == value, f'kv[{num!r}]'


def test_parse_dmx_singular() -> None:
    """Test parsing DMX data, with a singular value."""
    elem = Element('WidgetConfig', 'DMEConfig')
    elem['value'] = Attribute.string('value', 'testValue')
    assert WidgetConfig.parse_dmx(elem, 1) == WidgetConfig('testValue')


def test_export_dmx_singular() -> None:
    """Test constructing DMX configs, with a singular value."""
    elem = WidgetConfig('testValue').export_dmx()
    assert len(elem) == 2
    assert elem['value'].type is ValueType.STRING
    assert elem['value'].val_string == 'testValue'


def test_parse_dmx_timer() -> None:
    """Test parsing DMX data, with a timer value."""
    elem = Element('WidgetConfig', 'DMEConfig')
    for num, value in TIMER_DICT.items():
        elem[f'tim_{num}'] = Attribute.string(f'tim_{num}', value)

    assert WidgetConfig.parse_dmx(elem, 1) == WidgetConfig(TIMER_DICT.copy())


def test_export_dmx_timer() -> None:
    """Test constructing DMX configs, with a timer value."""
    elem = WidgetConfig(TIMER_DICT.copy()).export_dmx()
    assert len(elem) == 29 + 1  # Also name.
    for num, value in TIMER_DICT.items():
        attr = elem[f'tim_{num}']
        assert attr.type is ValueType.STRING
        assert attr.val_string == value
