"""Test parsing last-selected configuration."""
from srctools import Keyvalues
from srctools.dmx import Element, ValueType
import pytest

from config.last_sel import LastSelected
from config import UnknownVersion
import utils


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
        'music_base': LastSelected(utils.obj_id('PRO_BEEPS')),
        'music_tbeam': LastSelected(utils.obj_id('VALVE_SAW_DEER')),
        'music_speed': LastSelected(utils.obj_id('MEL_SYSTEM_CORRUPTION_ALT')),
        'music_bounce': LastSelected(utils.ID_NONE),
        'game': LastSelected(utils.obj_id('Portal 2')),
        'styles': LastSelected(utils.obj_id('BEE2_1950s')),
        'skyboxes': LastSelected(utils.obj_id('SKY_BLACK')),
        'voicelines': LastSelected(utils.ID_NONE),
        'elevators': LastSelected(utils.obj_id('VALVE_BOTS_LOAD')),
    }


def test_parse_invalid_version() -> None:
    """Check invalid versions raise errors."""
    with pytest.raises(UnknownVersion):
        LastSelected.parse_kv1(Keyvalues.root(), 2)

    with pytest.raises(UnknownVersion):
        LastSelected.parse_dmx(Element('LastSelected', 'DMConfig'), 2)


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    res = LastSelected.parse_kv1(Keyvalues('', 'SOME_ID_value'), 1)
    assert res == LastSelected(utils.special_id('Some_ID_value'))
    res = LastSelected.parse_kv1(Keyvalues('', '<NonE>'), 1)
    assert res == LastSelected(utils.ID_NONE)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 data."""
    some_id = utils.special_id('Some_ID')
    assert LastSelected(some_id).export_kv1().value == some_id
    assert LastSelected(utils.ID_NONE).export_kv1().value == utils.ID_NONE


def test_parse_dmx() -> None:
    """Test parsing DMX configs."""
    elem = Element('LastSelected', 'DMElement')
    elem['selected'] = 'SomeIDValue'
    assert LastSelected.parse_dmx(elem, 1) == LastSelected(utils.special_id('SomeIDValue'))

    elem['selected_none'] = True
    # The legacy selected-none option overrides regular selection.
    assert LastSelected.parse_dmx(elem, 1) == LastSelected(utils.ID_NONE)


def test_export_dmx() -> None:
    """Test exporting DMX configs."""
    some_id = utils.obj_id('SomeValueWITHCasing')
    elem = LastSelected(some_id).export_dmx()
    assert len(elem) == 2
    assert elem['selected'].type is ValueType.STRING
    assert elem['selected'].val_string == some_id

    elem = LastSelected(utils.ID_NONE).export_dmx()
    assert len(elem) == 2
    assert elem['selected'].type is ValueType.STRING
    assert elem['selected'].val_string == utils.ID_NONE
