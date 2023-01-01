"""Test item default configs."""
import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element, Attribute, ValueType

from config.item_defaults import ItemDefault, LEGACY
from . import isolate_conf
import editoritems_props
from editoritems import ItemPropKind


def test_parse_legacy() -> None:
    """Test the legacy config file names."""
    with isolate_conf(LEGACY):
        LEGACY['ITEM_PISTON_PLATFORM'] = {
            "sel_version": "VER_GLASSY",
            "prop_bottomlevel": "0",
            "prop_toplevel": "1",
            "prop_startup": "0",
            "prop_autodrop": "1",
            "prop_weirdprop": '45',
        }
        LEGACY['ITEM_BLANK'] = {}
        LEGACY['ITEM_VARIANT_ONLY'] = {
            'sel_version': 'VER_WORLDPORTAL',
        }
        LEGACY['ITEM_OBSERVATION_ROOM'] = {
            'sel_version': 'VER_WORLDPORTAL',
            'prop_startreversed': '1',
        }

        new_conf = ItemDefault.parse_legacy(Keyvalues('', []))
        assert new_conf == {
            'ITEM_PISTON_PLATFORM': ItemDefault('VER_GLASSY', {
                editoritems_props.prop_pist_lower: '0',
                editoritems_props.prop_pist_upper: '1',
                editoritems_props.prop_pist_start_up: '0',
                editoritems_props.prop_auto_drop: '1',
                ItemPropKind.unknown('weirdprop'): '45',
            }),
            'ITEM_BLANK': ItemDefault('VER_DEFAULT', {}),
            'ITEM_VARIANT_ONLY': ItemDefault('VER_WORLDPORTAL', {}),
            'ITEM_OBSERVATION_ROOM': ItemDefault('VER_WORLDPORTAL', {
                editoritems_props.prop_start_reversed: '1',
            })
        }


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 data."""
    assert ItemDefault.parse_kv1(Keyvalues('', []), 1) == ItemDefault('VER_DEFAULT', {})

    assert ItemDefault.parse_kv1(Keyvalues('', [
        Keyvalues('Version', 'SELECTED_VER'),
        Keyvalues('Properties', [
            Keyvalues('StartEnabled', '1'),
            Keyvalues('AngledpANElAnimation', 'ramp_45_deg_open'),
            Keyvalues('SomeUnknownProp', 'hello world'),
        ]),
    ]), 1) == ItemDefault('SELECTED_VER', {
        editoritems_props.prop_start_enabled: '1',
        editoritems_props.prop_angled_panel_anim: 'ramp_45_deg_open',
        ItemPropKind.unknown('SomeUnknownProp'): 'hello world',
    })

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        ItemDefault.parse_kv1(Keyvalues('', []), 2)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 data."""
    conf = ItemDefault('SELECTED_VER', {
        editoritems_props.prop_start_enabled: '1',
        editoritems_props.prop_angled_panel_anim: 'ramp_60_deg_open',
        ItemPropKind.unknown('SomeUnknownProp'): 'hello world',
    }).export_kv1()
    assert len(conf) == 2
    assert conf['version'] == 'SELECTED_VER'
    props = conf.find_key('properties')
    assert len(props) == 3
    # Ensure case is correct.
    assert props.find_key('StartEnabled').real_name == 'StartEnabled'
    assert props.find_key('StartEnabled').value == '1'

    assert props.find_key('AngledPanelAnimation').real_name == 'AngledPanelAnimation'
    assert props.find_key('AngledPanelAnimation').value == 'ramp_60_deg_open'

    assert props.find_key('SomeUnknownProp').real_name == 'SomeUnknownProp'
    assert props.find_key('SomeUnknownProp').value == 'hello world'


def test_parse_dmx() -> None:
    """Test parsing DMX configs."""
    elem = Element('LastSelected', 'DMElement')
    elem['version'] = 'SELECTED_VER'
    elem['properties'] = props = Element('Properties', 'DMElement')
    props['StartEnabled'] = '1'
    props['AngledpANElAnimation'] = 'ramp_45_deg_open'
    props['SomeUnknownProp'] = 'hello world'

    assert ItemDefault.parse_dmx(elem, 1) == ItemDefault('SELECTED_VER', {
        editoritems_props.prop_start_enabled: '1',
        editoritems_props.prop_angled_panel_anim: 'ramp_45_deg_open',
        ItemPropKind.unknown('SomeUnknownProp'): 'hello world',
    })

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        ItemDefault.parse_dmx(elem, 2)


def test_export_dmx() -> None:
    """Test exporting DMX configs."""
    elem = ItemDefault('SELECTED_VER', {
        editoritems_props.prop_start_enabled: '1',
        editoritems_props.prop_angled_panel_anim: 'ramp_60_deg_open',
        ItemPropKind.unknown('SomeUnknownProp'): 'hello world',
    }).export_dmx()
    assert len(elem) == 2

    assert elem['version'].val_string == 'SELECTED_VER'
    props = elem['properties'].val_elem
    assert len(props) == 3

    assert props['StartEnabled'].name == 'StartEnabled'
    assert props['StartEnabled'].type is ValueType.STRING
    assert props['StartEnabled'].val_string == '1'

    assert props['AngledPanelAnimation'].name == 'AngledPanelAnimation'
    assert props['AngledPanelAnimation'].type is ValueType.STRING
    assert props['AngledPanelAnimation'].val_string == 'ramp_60_deg_open'

    assert props['SomeUnknownProp'].name == 'SomeUnknownProp'
    assert props['SomeUnknownProp'].type is ValueType.STRING
    assert props['SomeUnknownProp'].val_string == 'hello world'
