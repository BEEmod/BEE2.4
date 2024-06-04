"""Test parsing behaviour of stylevars."""
from srctools import Keyvalues
from srctools.dmx import Attribute, Element
import pytest

from config.stylevar import State
from config import UnknownVersion


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


def test_parse_invalid_version() -> None:
    """Check invalid versions raise errors."""
    with pytest.raises(UnknownVersion):
        State.parse_kv1(Keyvalues.root(), 2)

    with pytest.raises(UnknownVersion):
        State.parse_dmx(Element('StyleState', 'DMConfig'), 2)


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    assert State.parse_kv1(Keyvalues('StyleState', '0'), 1) == State(False)
    assert State.parse_kv1(Keyvalues('StyleState', '1'), 1) == State(True)


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


@pytest.mark.parametrize('value', [False, True])
def test_export_dmx(value: bool) -> None:
    """Test constructing DMX configs."""
    elem = State(value).export_dmx()
    assert len(elem) == 2
    assert elem['value'].val_bool is value
