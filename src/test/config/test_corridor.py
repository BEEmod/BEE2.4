"""Test parsing corridor configurations."""
from typing import Mapping

import pytest
from srctools import Keyvalues
from srctools.dmx import Element

from config.corridors import Config, Options, UIState
from config import UnknownVersion
import utils
from corridor import Attachment, Direction, GameMode, Orient


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
# Sample data for corridor options. Make sure to copy to ensure the class can't accidentally modify!
OPTION_SAMPLE: Mapping[utils.ObjectID, utils.SpecialID] = {
    utils.obj_id('direction_Entry'): utils.obj_id('up'),
    utils.obj_id('temperature'): utils.obj_id('freezing'),
    utils.obj_id('side'): utils.obj_id('left'),
    utils.obj_id('suprises'): utils.ID_RANDOM,
}

ORIENT_COMBOS = [
    (Direction.ENTRY, Orient.HORIZONTAL, Attachment.HORIZONTAL),
    (Direction.ENTRY, Orient.UP, Attachment.FLOOR),
    (Direction.ENTRY, Orient.DOWN, Attachment.CEILING),
    (Direction.ENTRY, Orient.HORIZONTAL, Attachment.HORIZONTAL),
    (Direction.EXIT, Orient.UP, Attachment.CEILING),
    (Direction.EXIT, Orient.DOWN, Attachment.FLOOR),
]


def test_conf_parse_v3() -> None:
    """Version 3 is not supported."""
    with pytest.raises(UnknownVersion):  # Check version 3 is not allowed.
        Config.parse_kv1(Keyvalues.root(), 3)

    with pytest.raises(UnknownVersion):  # Check version 3 is not allowed.
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


def test_options_parse_v2() -> None:
    """Version 2 is not supported."""
    with pytest.raises(UnknownVersion):
        Options.parse_kv1(Keyvalues.root(), 2)

    with pytest.raises(UnknownVersion):
        Options.parse_dmx(Element('CorridorOptions', 'DMConfig'), 2)


def test_parse_v1_kv1() -> None:
    """Test parsing keyvalues1 configs, in version 1 format."""
    kv = Keyvalues.root(
        Keyvalues('direction_entry', 'up'),
        Keyvalues('temperature', 'freezing'),
        Keyvalues('side', 'left'),
        Keyvalues('suprises', '<ranDOM>'),
    )
    assert Options.parse_kv1(kv, 1) == Options(dict(OPTION_SAMPLE))


def test_export_kv1() -> None:
    """Test exporting keyvalues1 configs."""
    result = Options(dict(OPTION_SAMPLE)).export_kv1()
    assert len(result) == 4
    assert result['direction_entry'] == 'UP'
    assert result['temperature'] == 'FREEZING'
    assert result['sIDe'] == 'LEFT'
    assert result['suprises'] == utils.ID_RANDOM


def test_parse_v1_dmx() -> None:
    """Test parsing DMX configs, in version 1 format."""
    elem = Element('CorrOpts', 'DMElement')
    elem['directION_entry'] = 'up'
    elem['tempERAture'] = 'freezing'
    elem['sIDe'] = 'left'
    elem['suprises'] = '<ranDOM>'

    assert Options.parse_dmx(elem, 1) == Options(dict(OPTION_SAMPLE))


def test_export_dmx() -> None:
    """Test exporting DMX configs."""
    result = Options(dict(OPTION_SAMPLE)).export_dmx()
    result.pop('name')
    assert len(result) == 4
    assert result['direction_entry'].name == 'DIRECTION_ENTRY'
    assert result['direction_entry']._value == 'UP'

    assert result['temperature'].name == 'TEMPERATURE'
    assert result['temperature']._value == 'FREEZING'

    assert result['side'].name == 'SIDE'
    assert result['side']._value == 'LEFT'

    assert result['suprises'].name == 'SUPRISES'
    assert result['suprises']._value == utils.ID_RANDOM


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('attach', Attachment)
@pytest.mark.parametrize('direction', Direction)
def test_ui_parse_kv1(mode: GameMode, attach: Attachment, direction: Direction) -> None:
    """Test parsing keyvalues1 UI state."""
    kv = Keyvalues('Corridor', [
        Keyvalues('mode', mode.value),
        Keyvalues('attach', attach.value),
        Keyvalues('direction', direction.value),
        Keyvalues('width', '272'),
        Keyvalues('height', '849'),
    ])
    assert UIState.parse_kv1(kv, 1) == UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    )


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('direction, orient, attach', ORIENT_COMBOS)
def test_ui_parse_kv1_orient(
    mode: GameMode,
    direction: Direction, orient: Orient,
    attach: Attachment,
) -> None:
    """Test parsing old orient keys."""
    kv = Keyvalues('Corridor', [
        Keyvalues('mode', mode.value),
        Keyvalues('direction', direction.value),
        Keyvalues('orient', orient.value),
        Keyvalues('width', '272'),
        Keyvalues('height', '849'),
    ])
    assert UIState.parse_kv1(kv, 1) == UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    )


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('attach', Attachment)
@pytest.mark.parametrize('direction', Direction)
def test_ui_export_kv1(mode: GameMode, attach: Attachment, direction: Direction) -> None:
    """Test exporting keyvalues1 UI state."""
    kv = UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    ).export_kv1()
    assert len(kv) == 5
    assert kv['mode'] == mode.value
    assert kv['attach'] == attach.value
    assert kv['width'] == '272'
    assert kv['height'] == '849'


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('attach', Attachment)
@pytest.mark.parametrize('direction', Direction)
def test_ui_parse_dmx(mode: GameMode, attach: Attachment, direction: Direction) -> None:
    """Test parsing dmx UI state."""
    elem = Element('UIState', 'DMEElement')
    elem['mode'] = mode.value
    elem['attach'] = attach.value
    elem['direction'] = direction.value
    elem['width'] = 272
    elem['height'] = 849

    assert UIState.parse_dmx(elem, 1) == UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    )


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('direction, orient, attach', ORIENT_COMBOS)
def test_ui_parse_dmx_orient(
    mode: GameMode,
    direction: Direction, orient: Orient,
    attach: Attachment,
) -> None:
    """Test parsing old orient keys."""
    elem = Element('UIState', 'DMEElement')
    elem['mode'] = mode.value
    elem['orient'] = orient.value
    elem['direction'] = direction.value
    elem['width'] = 272
    elem['height'] = 849
    assert UIState.parse_dmx(elem, 1) == UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    )


@pytest.mark.parametrize('mode', GameMode)
@pytest.mark.parametrize('attach', Attachment)
@pytest.mark.parametrize('direction', Direction)
def test_ui_export_dmx(mode: GameMode, attach: Attachment, direction: Direction) -> None:
    """Test exporting dmx UI state."""
    elem = UIState(
        last_mode=mode, last_attach=attach, last_direction=direction,
        width=272, height=849,
    ).export_dmx()
    assert len(elem) == 6
    assert elem['mode'].val_string == mode.value
    assert elem['attach'].val_string == attach.value
    assert elem['width'].val_int == 272
    assert elem['height'].val_int == 849
