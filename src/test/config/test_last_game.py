"""Test the last-selected game config option."""
import uuid

from srctools import Keyvalues
from srctools.dmx import Element
import pytest

from config import UnknownVersion
from config.last_sel import LastGame

# Keep the UUIDs consistent.
NS = uuid.UUID('19fe3db1-bf0b-47e0-bdf5-25296bcf1018')
GAME_1 = uuid.uuid5(NS, 'alpha')
GAME_2 = uuid.uuid5(NS, 'beta')
GAME_3 = uuid.uuid5(NS, 'gamma')
GAME_4 = uuid.uuid5(NS, 'delta')


def test_parse_invalid_version() -> None:
    """Check invalid versions raise errors."""
    with pytest.raises(UnknownVersion):
        LastGame.parse_kv1(Keyvalues.root(), 2)

    with pytest.raises(UnknownVersion):
        LastGame.parse_dmx(Element('LastGame', 'DMConfig'), 2)


def test_parse_kv1() -> None:
    """Test parsing keyvalues1 state."""
    GAME_1 = uuid.uuid4()
    last = LastGame.parse_kv1(Keyvalues('LastGame', [
        Keyvalues('uuid', GAME_1.hex),
    ]), 1)
    assert last.uuid == GAME_1

    with pytest.raises(ValueError, match='UUID'):
        LastGame.parse_kv1(Keyvalues('LastGame', [
            Keyvalues('uuid', 'notauuid'),
        ]), 1)


def test_export_kv1() -> None:
    """Test exporting keyvalues1 state."""
    kv = LastGame(GAME_2).export_kv1()
    assert len(kv) == 1
    assert kv['uuid'] == GAME_2.hex


def test_parse_dmx() -> None:
    """Test parsing DMX state."""
    elem = Element('LastGame', 'DMConfig')
    elem['uuid'] = GAME_3.bytes
    last = LastGame.parse_dmx(elem, 1)
    assert last.uuid == GAME_3


def test_export_dmx() -> None:
    """Test exporting DMX state."""
    elem = LastGame(GAME_4).export_dmx()
    assert len(elem) == 2  # + name
    assert elem['uuid'].val_bytes == GAME_4.bytes
