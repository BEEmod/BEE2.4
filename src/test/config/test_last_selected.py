"""Test parsing last-selected configuration."""
import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element, Attribute, ValueType

from config.last_sel import LastSelected


def test_parse_legacy() -> None:
    """Test the legacy config file names."""
    old_conf = Keyvalues.root(
        Keyvalues('LastSelected', [
            Keyvalues('Music_Base', 'PRO_BEEPS'),
            Keyvalues('Music_Tbeam', 'VALVE_SAW_DEER'),
            Keyvalues('Music_Bounce', '<NONE>'),
            Keyvalues('Music_Speed', 'MEL_SYSTEM_CORRUPTION_ALT'),
            Keyvalues('Style', 'BEE2_1950s'),
            Keyvalues('Skybox', 'SKY_BLACK'),
            Keyvalues('Game', 'Portal 2'),
            Keyvalues('Voice', '<NOnE>'),
            Keyvalues('Elevator', 'VALVE_BOTS_LOAD'),
        ]),
    )
    new_conf = LastSelected.parse_legacy(old_conf)
    assert new_conf == {
        'music_base': LastSelected('PRO_BEEPS'),
        'music_tbeam': LastSelected('VALVE_SAW_DEER'),
        'music_speed': LastSelected('MEL_SYSTEM_CORRUPTION_ALT'),
        'music_bounce': LastSelected(None),
        'game': LastSelected('Portal 2'),
        'styles': LastSelected('BEE2_1950s'),
        'skyboxes': LastSelected('SKY_BLACK'),
        'voicelines': LastSelected(None),
        'elevators': LastSelected('VALVE_BOTS_LOAD'),
    }


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    assert LastSelected.parse_kv1(Keyvalues('', 'SOME_ID_value'), 1) == LastSelected('SOME_ID_value')
    assert LastSelected.parse_kv1(Keyvalues('', '<NonE>'), 1) == LastSelected(None)

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        LastSelected.parse_kv1(Keyvalues('LastSelected', 'TEST'), 2)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 data."""
    assert LastSelected('Some_ID').export_kv1().value == 'Some_ID'
    assert LastSelected(None).export_kv1().value == '<NONE>'


def test_parse_dmx() -> None:
    """Test parsing DMX configs."""
    elem = Element('LastSelected', 'DMElement')
    elem['selected'] = 'SomeIDValue'
    assert LastSelected.parse_dmx(elem, 1) == LastSelected('SomeIDValue')

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        LastSelected.parse_dmx(elem, 2)

    elem['selected_none'] = True
    # Selected-none overrides regular selection.
    assert LastSelected.parse_dmx(elem, 1) == LastSelected(None)

    with pytest.raises(AssertionError):
        LastSelected.parse_dmx(elem, 2)


def test_export_dmx() -> None:
    """Test exporting DMX configs."""
    elem = LastSelected('SomeValueWITHCasing').export_dmx()
    assert len(elem) == 1
    assert elem['selected'].type is ValueType.STRING
    assert elem['selected'].val_string == 'SomeValueWITHCasing'

    elem = LastSelected(None).export_dmx()
    assert len(elem) == 1
    assert elem['selected_none'].type is ValueType.BOOL
    assert elem['selected_none'].val_bool is True
