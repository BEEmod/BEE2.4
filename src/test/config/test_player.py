"""Test player model configuration."""
import pytest
from srctools import Keyvalues
from srctools.dmx import Attribute, Element

import config
from config.player import AvailablePlayer, ExportPlayer
from quote_pack import LineCriteria


def test_available_parse() -> None:
    """Test parsing available models"""
    assert AvailablePlayer.parse_kv1(Keyvalues('', 'Chell'), 1) == AvailablePlayer('Chell')

    elem = Element('AvailablePlayer', 'DMElement')
    assert AvailablePlayer.parse_dmx(elem, 1) == AvailablePlayer('')
    elem['disp_name'] = 'ATlas'
    assert AvailablePlayer.parse_dmx(elem, 1) == AvailablePlayer('ATlas')

    with pytest.raises(config.UnknownVersion):
        AvailablePlayer.parse_kv1(Keyvalues('', 'hi'), 2)
    with pytest.raises(config.UnknownVersion):
        AvailablePlayer.parse_dmx(elem,  2)


def test_available_export() -> None:
    """Test exporting available models."""
    kv = AvailablePlayer('P-Body').export_kv1()
    assert kv.value == 'P-Body'

    elem = AvailablePlayer('Bendy').export_dmx()
    assert len(elem) == 2
    assert elem['disp_name'].val_string == 'Bendy'


def test_exported_parse_kv1() -> None:
    """Test parsing exported players in KV1."""
    assert ExportPlayer.parse_kv1(Keyvalues('', []), 1) == ExportPlayer()

    assert ExportPlayer.parse_kv1(Keyvalues('', [
        Keyvalues('model', 'player/CHELL/player'),
        Keyvalues('pgun_skin', '48'),
        Keyvalues('voice_robot', '0'),
        Keyvalues('voice_chell', '1'),
    ]), 1) == ExportPlayer(
        model='player/CHELL/player',
        pgun_skin=48,
        voice_options={
            LineCriteria.CHELL: True,
            LineCriteria.ROBOT: False,

            LineCriteria.ATLAS: False,
            LineCriteria.PBODY: False,
            LineCriteria.BENDY: False,
            LineCriteria.HUMAN: False,
        }
    )


def test_exported_parse_dmx() -> None:
    """Test parsing exported players in DMX."""
    elem = Element('ExportPlayer', 'DMConfig')
    elem['model'] = 'player/eggbot/EGGbot_cage'
    elem['pgun_skin'] = 1
    elem['voice_pbody'] = True
    elem['voice_robot'] = True
    elem['voice_atlas'] = False
    assert ExportPlayer.parse_dmx(elem, 1) == ExportPlayer(
        model='player/eggbot/EGGbot_cage',
        pgun_skin=1,
        voice_options={
            LineCriteria.ATLAS: False,
            LineCriteria.PBODY: True,
            LineCriteria.ROBOT: True,

            LineCriteria.CHELL: False,
            LineCriteria.BENDY: False,
            LineCriteria.HUMAN: False,
        }
    )


def test_exported_parse_invalid_version() -> None:
    """Version 2 is not supported."""
    with pytest.raises(config.UnknownVersion):
        ExportPlayer.parse_kv1(Keyvalues.root(), 2)

    with pytest.raises(config.UnknownVersion):
        ExportPlayer.parse_dmx(Element('ExportPlayer', 'DMConfig'), 2)


def test_exported_export_kv1() -> None:
    """Test producing exported players in KV1."""
    result = ExportPlayer(
        model='npcs/TURret/turret',
        pgun_skin=2,
        voice_options={
            LineCriteria.CHELL: False,
            LineCriteria.BENDY: True,
            LineCriteria.ATLAS: False,
            LineCriteria.PBODY: True,
            LineCriteria.ROBOT: True,
            LineCriteria.HUMAN: False,
        }
    ).export_kv1()
    assert len(result) == 8
    assert result['model'] == 'npcs/TURret/turret'
    assert result['pgun_skin'] == '2'
    assert result['voice_chell'] == '0'
    assert result['voice_bendy'] == '1'
    assert result['voice_atlas'] == '0'
    assert result.find_key('voice_pbody') == Keyvalues('voice_pbody', '1')  # Case check.
    assert result['voice_robot'] == '1'
    assert result['voice_human'] == '0'


def test_exported_export_dmx() -> None:
    """Test producing exported players in DMX."""
    result = ExportPlayer(
        model='npcs/TURret/turret',
        pgun_skin=2,
        voice_options={
            LineCriteria.CHELL: False,
            LineCriteria.BENDY: True,
            LineCriteria.ATLAS: False,
            LineCriteria.PBODY: True,
            LineCriteria.ROBOT: True,
            LineCriteria.HUMAN: False,
        }
    ).export_dmx()
    assert len(result) == 9
    assert result['model'] == Attribute.string('model', 'npcs/TURret/turret')
    assert result['pgun_skin'] == Attribute.int('pgun_skin', 2)
    assert result['voice_chell'] == Attribute.bool('voice_chell', False)
    assert result['voice_bendy'] == Attribute.bool('voice_bendy', True)
    assert result['voice_bendy'].name == 'voice_bendy'
    assert result['voice_atlas'] == Attribute.bool('voice_atlas', False)
    assert result['voice_pbody'] == Attribute.bool('voice_pbody', True)
    assert result['voice_robot'] == Attribute.bool('voice_robot', True)
    assert result['voice_human'] == Attribute.bool('voice_human', False)
