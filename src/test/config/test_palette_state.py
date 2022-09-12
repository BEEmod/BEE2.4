import uuid

import pytest
from srctools import Property as Keyvalues

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
    print(kv)
    assert hiddens == {another_uuid.hex, UUID_EXPORT.hex}
