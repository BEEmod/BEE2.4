"""Test parsing corridor configurations."""
import pytest
from srctools import Keyvalues
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
    assert len(elem) == 3
    assert list(elem['selected'].iter_string()) == CORR_SEL
    assert list(elem['unselected'].iter_string()) == CORR_UNSEL


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('orient', Orient)
@pytest.mark.parametrize('direction', Direction)
def test_ui_parse_kv1(mode: GameMode, orient: Orient, direction: Direction) -> None:
    """Test parsing keyvalues1 UI state."""
    kv = Keyvalues('Corridor', [
        Keyvalues('mode', mode.value),
        Keyvalues('orient', orient.value),
        Keyvalues('direction', direction.value),
        Keyvalues('width', '272'),
        Keyvalues('height', '849'),
    ])
    assert UIState.parse_kv1(kv, 1) == UIState(
        last_mode=mode, last_orient=orient, last_direction=direction,
        width=272, height=849,
    )

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        UIState.parse_kv1(kv, 2)


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('orient', Orient)
@pytest.mark.parametrize('direction', Direction)
def test_ui_export_kv1(mode: GameMode, orient: Orient, direction: Direction) -> None:
    """Test exporting keyvalues1 UI state."""
    kv = UIState(
        last_mode=mode, last_orient=orient, last_direction=direction,
        width=272, height=849,
    ).export_kv1()
    assert len(kv) == 5
    assert kv['mode'] == mode.value
    assert kv['orient'] == orient.value
    assert kv['width'] == '272'
    assert kv['height'] == '849'


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('orient', Orient)
@pytest.mark.parametrize('direction', Direction)
def test_ui_parse_dmx(mode: GameMode, orient: Orient, direction: Direction) -> None:
    """Test parsing dmx UI state."""
    elem = Element('UIState', 'DMEElement')
    elem['mode'] = mode.value
    elem['orient'] = orient.value
    elem['direction'] = direction.value
    elem['width'] = 272
    elem['height'] = 849

    assert UIState.parse_dmx(elem, 1) == UIState(
        last_mode=mode, last_orient=orient, last_direction=direction,
        width=272, height=849,
    )

    with pytest.raises(AssertionError):  # Check version 2 is not allowed.
        UIState.parse_dmx(elem, 2)


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('orient', Orient)
@pytest.mark.parametrize('direction', Direction)
def test_ui_export_dmx(mode: GameMode, orient: Orient, direction: Direction) -> None:
    """Test exporting dmx UI state."""
    elem = UIState(
        last_mode=mode, last_orient=orient, last_direction=direction,
        width=272, height=849,
    ).export_dmx()
    assert len(elem) == 6
    assert elem['mode'].val_string == mode.value
    assert elem['orient'].val_string == orient.value
    assert elem['width'].val_int == 272
    assert elem['height'].val_int == 849
