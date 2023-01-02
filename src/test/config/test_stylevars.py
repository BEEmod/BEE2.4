"""Test parsing behaviour of stylevars."""
import pytest
from srctools import Keyvalues
from srctools.dmx import Element, Attribute

from config.stylevar import State


def test_parse_legacy() -> None:
    """Test parsing the older config version."""
    kv = Keyvalues('Config', [
        Keyvalues('Stylevar', [
            Keyvalues('EnabledVar', '1'),
            Keyvalues('DisabledVar', '0'),
        ]),
        Keyvalues('SomethingElse', [
            Keyvalues('bool', '0')
        ]),
    ])
    res = State.parse_legacy(kv)
    assert res == {
        'EnabledVar': State(True),
        'DisabledVar': State(False),
    }


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    assert State.parse_kv1(Keyvalues('StyleState', '0'), 1) == State(False)
    assert State.parse_kv1(Keyvalues('StyleState', '1'), 1) == State(True)

    with pytest.raises(AssertionError):  # No future versions allowed.
        State.parse_kv1(Keyvalues('StyleState', '0'), 2)


def test_export_kv1() -> None:
    """Test producing new keyvalues1 data."""
    kv = State(False).export_kv1()
    assert kv.value == '0'

    kv = State(True).export_kv1()
    assert kv.value == '1'


@pytest.mark.parametrize('value', [False, True])
def test_parse_dmx(value: bool) -> None:
    """Test parsing DMX data."""
    elem = Element('ConfData', 'DMEConfig')
    elem['value'] = Attribute.bool('value', value)
    assert State.parse_dmx(elem, 1) == State(value)

    with pytest.raises(AssertionError):  # No future versions allowed.
        State.parse_dmx(elem, 2)


@pytest.mark.parametrize('value', [False, True])
def test_export_dmx(value: bool) -> None:
    """Test constructing DMX configs."""
    elem = State(value).export_dmx()
    assert len(elem) == 2
    assert elem['value'].val_bool is value
