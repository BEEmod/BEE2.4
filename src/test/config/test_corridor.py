"""Test parsing corridor configurations."""
import pytest
from srctools import Keyvalues
from srctools.dmx import Element

from config.corridors import Direction, GameMode, Orient, Config, UIState

# Two sets of sample instance names, for testing parsing - in V1 and V2 formats.
CORR_ENABLED = {
    'instances/bee2/some_selected_1.vmf': True,
    'instances/bee2/some_selected_2.vmf': True,
    'instances/bee2/some_selected_3.vmf': True,
    'instances/bee2/some_unsel_1.vmf': False,
    'instances/bee2/some_unsel_2.vmf': False,
}
CORR_SEL = [inst for inst, enabled in CORR_ENABLED.items() if enabled]
CORR_UNSEL = [inst for inst, enabled in CORR_ENABLED.items() if not enabled]


def test_conf_parse_v3() -> None:
    """Version 3 is not supported."""
    with pytest.raises(ValueError):  # Check version 3 is not allowed.
        Config.parse_kv1(Keyvalues.root(), 3)

    with pytest.raises(ValueError):  # Check version 3 is not allowed.
        Config.parse_dmx(Element('Config', 'DMConfig'), 3)


def test_conf_parse_v1_kv1() -> None:
    """Test parsing keyvalues1 configs, in version 1 format."""
    kv = Keyvalues.root(
        Keyvalues('Corridors', [
            Keyvalues('selected', 'instances/bee2/some_selected_1.vmf'),
            Keyvalues('unselected', 'instances/bee2/some_unsel_1.vmf'),
            Keyvalues('unselected', 'instances/bee2/some_unsel_2.vmf'),
            Keyvalues('selected', 'instances/bee2/some_selected_2.vmf'),
            Keyvalues('selected', 'instances/bee2/some_selected_3.vmf'),
        ])
    )
    assert Config.parse_kv1(kv, 1) == Config(CORR_ENABLED.copy())


def test_conf_parse_v2_kv1() -> None:
    """Test parsing keyvalues1 configs, in version 2 format."""
    kv = Keyvalues.root(
        Keyvalues('instances/bee2/some_selected_1.vmf', '1'),
        Keyvalues('instances/bee2/some_unsel_1.vmf', '0'),
        Keyvalues('instances/bee2/some_unsel_2.vmf', '0'),
        Keyvalues('instances/bee2/some_selected_2.vmf', '1'),
        Keyvalues('instances/bee2/some_selected_3.vmf', '1'),
    )
    assert Config.parse_kv1(kv, 2) == Config(CORR_ENABLED.copy())


def test_conf_export_kv1() -> None:
    """Test exporting keyvalues1 configs."""
    kv = Config(CORR_ENABLED.copy()).export_kv1()

    assert len(kv) == 5

    # We don't care how they are interspersed, but order matters.
    selected = []
    unselected = []
    for child in kv:
        if child.value == '1':
            selected.append(child.real_name)
        elif child.value == '0':
            unselected.append(child.real_name)

    assert selected == CORR_SEL
    assert unselected == CORR_UNSEL


def test_conf_parse_v1_dmx() -> None:
    """Test parsing dmx configs, in version 1 format."""
    elem = Element('CorrConfig', 'DMElement')
    elem['selected'] = CORR_SEL
    elem['unselected'] = CORR_UNSEL

    assert Config.parse_dmx(elem, 1) == Config(CORR_ENABLED.copy())


def test_conf_parse_v2_dmx() -> None:
    """Test parsing dmx configs, in version 2 format."""
    elem = Element('CorrConfig', 'DMElement')
    elem['instances/bee2/some_selected_1.vmf'] = True
    elem['instances/bee2/some_unsel_1.vmf'] = False
    elem['instances/bee2/some_unsel_2.vmf'] = False
    elem['instances/bee2/some_selected_2.vmf'] = True
    elem['instances/bee2/some_selected_3.vmf'] = True

    assert Config.parse_dmx(elem, 2) == Config(CORR_ENABLED.copy())


def test_conf_export_dmx() -> None:
    """Test exporting DMX configs."""
    elem = Config(CORR_ENABLED.copy()).export_dmx()
    elem.pop('name')
    assert len(elem) == 5
    assert [
        (attr.name, attr._value)
        for attr in elem.values()
    ] == list(CORR_ENABLED.items())


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
