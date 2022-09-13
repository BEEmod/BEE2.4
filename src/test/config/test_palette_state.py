import uuid

import pytest
from srctools import Property as Keyvalues
from srctools.dmx import Element

from config.palette import PaletteState
from consts import UUID_PORTAL2, UUID_EXPORT
from . import isolate_gen_opts, GEN_OPTS


def test_parse_legacy(isolate_gen_opts) -> None:
    """Test parsing out palette state from the legacy config."""
    state_dict = PaletteState.parse_legacy(Keyvalues('Config', []))
    assert len(state_dict) == 1
    state = state_dict['']
    assert state.selected == UUID_PORTAL2
    assert state.save_settings is False
    assert state.hidden_defaults == frozenset()

    some_uuid = uuid.uuid4()
    GEN_OPTS['Last_Selected']['palette_uuid'] = some_uuid.hex
    GEN_OPTS['General']['palette_save_settings'] = '1'

    state_dict = PaletteState.parse_legacy(Keyvalues('Config', []))
    assert len(state_dict) == 1
    state = state_dict['']
    assert state.selected == some_uuid
    assert state.save_settings is True
    assert state.hidden_defaults == frozenset()


@pytest.mark.parametrize('save', [0, 1])
def test_parse_kv1(save: int) -> None:
    """Test parsing keyvalues1 state."""
    some_uuid = uuid.uuid4()
    another_uuid = uuid.uuid4()
    kv = Keyvalues('Palette', [
        Keyvalues('selected', some_uuid.hex),
        Keyvalues('hidden', another_uuid.hex),
        Keyvalues('hidden', UUID_EXPORT.hex),
        Keyvalues('hidden', UUID_PORTAL2.hex),
        Keyvalues('save_settings', str(save)),
    ])
    state = PaletteState.parse_kv1(kv, 1)

    assert state.selected == some_uuid
    assert state.save_settings is bool(save)
    # The "Portal 2" is not allowed here, so it should be stripped.
    assert another_uuid in state.hidden_defaults
    assert UUID_EXPORT in state.hidden_defaults
    assert UUID_PORTAL2 not in state.hidden_defaults


@pytest.mark.parametrize('save', [0, 1])
def test_export_kv1(save: int) -> None:
    """Test exporting keyvalues1 state."""
    some_uuid = uuid.uuid4()
    another_uuid = uuid.uuid4()

    state = PaletteState(
        selected=some_uuid,
        hidden_defaults=frozenset({
            another_uuid, UUID_EXPORT,
        }),
        save_settings=bool(save),
    )
    kv = state.export_kv1()
    assert len(kv) == 4
    assert kv['selected'] == some_uuid.hex
    assert kv['save_settings'] == str(save)
    hiddens = {
        prop.value for prop in kv.find_all('hidden')
    }
    assert hiddens == {another_uuid.hex, UUID_EXPORT.hex}


@pytest.mark.parametrize('save', [False, True])
def test_parse_dmx(save: bool) -> None:
    """Test parsing DMX state."""
    some_uuid = uuid.uuid4()
    another_uuid = uuid.uuid4()

    elem = Element('PaletteState', 'DMConfig')
    elem['selected'] = some_uuid.bytes
    elem['save_settings'] = save
    elem['hidden'] = [
        another_uuid.bytes,
        UUID_EXPORT.bytes,
        UUID_PORTAL2.bytes,
    ]
    state = PaletteState.parse_dmx(elem, 1)

    assert state.selected == some_uuid
    assert state.save_settings is bool(save)
    # The "Portal 2" is not allowed here, so it should be stripped.
    assert another_uuid in state.hidden_defaults
    assert UUID_EXPORT in state.hidden_defaults
    assert UUID_PORTAL2 not in state.hidden_defaults


@pytest.mark.parametrize('save', [False, True])
def test_export_dmx(save: bool) -> None:
    """Test exporting DMX state."""
    some_uuid = uuid.uuid4()
    another_uuid = uuid.uuid4()

    state = PaletteState(
        selected=some_uuid,
        hidden_defaults=frozenset({
            another_uuid, UUID_EXPORT,
        }),
        save_settings=bool(save),
    )
    elem = state.export_dmx()
    assert len(elem) == 3
    assert elem['selected'].val_bytes == some_uuid.bytes
    assert elem['save_settings'].val_bool is save
    hiddens = set(elem['hidden'].iter_binary())
    assert hiddens == {another_uuid.bytes, UUID_EXPORT.bytes}
