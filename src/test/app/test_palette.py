"""Test palette saving and loading."""
from __future__ import annotations

from srctools import Keyvalues
import pytest

from app.paletteLoader import Palette
from transtoken import TransToken


def make_pos_block(pos: str, item_id: str, subtype: str) -> Keyvalues:
    """Make a block for the new positions definition."""
    return Keyvalues(pos, [
        Keyvalues('id', item_id),
        Keyvalues('subtype', subtype),
    ])


# Version 2 and 3 positions block.
pos_block = [
    make_pos_block('0 0', "ITEM_BUTTON_PEDESTAL", "0"),
    make_pos_block('1 0', "ITEM_BUTTON_FLOOR", "0"),
    make_pos_block('2 0', "ITEM_BUTTON_FLOOR", "1"),
    make_pos_block('3 0', "ITEM_BUTTON_FLOOR", "2"),

    make_pos_block('0 1', "ITEM_CUBE", "0"),
    make_pos_block('1 1', "ITEM_CUBE", "1"),
    make_pos_block('2 1', "ITEM_CUBE", "3"),
    make_pos_block('3 1', "ITEM_CUBE", "4"),

    make_pos_block('0 2', "ITEM_TBEAM", "0"),
    make_pos_block('1 2', "ITEM_CATAPULT", "0"),
    make_pos_block('2 2', "ITEM_LIGHT_BRIDGE", "0"),
    make_pos_block('3 2', "ITEM_PANEL_STAIRS", "0"),

    make_pos_block('0 3', "ITEM_BARRIER_HAZARD", "0"),
    make_pos_block('1 3', "ITEM_BARRIER", "0"),
    make_pos_block('2 3', "ITEM_PISTON_PLATFORM", "0"),
    make_pos_block('3 3', "ITEM_RAIL_PLATFORM", "0"),

    make_pos_block('0 4', "ITEM_LASER_EMITTER_CENTER", "0"),
    make_pos_block('1 4', "ITEM_LASER_CATCHER_CENTER", "0"),
    make_pos_block('2 4', "ITEM_LASER_RELAY_CENTER", "0"),
    make_pos_block('3 4', "ITEM_CUBE", "2"),

    make_pos_block('0 5', "ITEM_PANEL_CLEAR", "0"),
    make_pos_block('1 5', "ITEM_PANEL_ANGLED", "0"),
    make_pos_block('2 5', "ITEM_PANEL_FLIP", "0"),
    make_pos_block('3 5', "ITEM_SECONDARY_OBSERVATION_ROOM", "0"),

    make_pos_block('0 6', "ITEM_BARRIER_HAZARD", "1"),
    make_pos_block('1 6', "ITEM_TURRET", "0"),
    make_pos_block('2 6', "ITEM_GOO", "0"),
    make_pos_block('3 6', "ITEM_LIGHT_PANEL", "0"),

    make_pos_block('0 7', "ITEM_PAINT_SPLAT", "0"),
    make_pos_block('1 7', "ITEM_PAINT_SPLAT", "1"),
    make_pos_block('2 7', "ITEM_PAINT_SPLAT", "2"),
    make_pos_block('3 7', "ITEM_PAINT_SPLAT", "3"),
]


def check_palette(pal: Palette) -> None:
    """Check this palette matches the expected definition."""
    assert pal.name == TransToken.untranslated('Test Palette')
    assert pal.uuid.hex == 'c510aee8759e4b61871d233806b5e73a'

    assert len(pal.items) == 32

    assert pal.items[0, 0] == ("ITEM_BUTTON_PEDESTAL", 0)
    assert pal.items[1, 0] == ("ITEM_BUTTON_FLOOR", 0)
    assert pal.items[2, 0] == ("ITEM_BUTTON_FLOOR", 1)
    assert pal.items[3, 0] == ("ITEM_BUTTON_FLOOR", 2)

    assert pal.items[0, 1] == ("ITEM_CUBE", 0)
    assert pal.items[1, 1] == ("ITEM_CUBE", 1)
    assert pal.items[2, 1] == ("ITEM_CUBE", 3)
    assert pal.items[3, 1] == ("ITEM_CUBE", 4)

    assert pal.items[0, 2] == ("ITEM_TBEAM", 0)
    assert pal.items[1, 2] == ("ITEM_CATAPULT", 0)
    assert pal.items[2, 2] == ("ITEM_LIGHT_BRIDGE", 0)
    assert pal.items[3, 2] == ("ITEM_PANEL_STAIRS", 0)

    assert pal.items[0, 3] == ("ITEM_BARRIER_HAZARD", 0)
    assert pal.items[1, 3] == ("ITEM_BARRIER", 0)
    assert pal.items[2, 3] == ("ITEM_PISTON_PLATFORM", 0)
    assert pal.items[3, 3] == ("ITEM_RAIL_PLATFORM", 0)

    assert pal.items[0, 4] == ("ITEM_LASER_EMITTER_CENTER", 0)
    assert pal.items[1, 4] == ("ITEM_LASER_CATCHER_CENTER", 0)
    assert pal.items[2, 4] == ("ITEM_LASER_RELAY_CENTER", 0)
    assert pal.items[3, 4] == ("ITEM_CUBE", 2)

    assert pal.items[0, 5] == ("ITEM_PANEL_CLEAR", 0)
    assert pal.items[1, 5] == ("ITEM_PANEL_ANGLED", 0)
    assert pal.items[2, 5] == ("ITEM_PANEL_FLIP", 0)
    assert pal.items[3, 5] == ("ITEM_SECONDARY_OBSERVATION_ROOM", 0)

    assert pal.items[0, 6] == ("ITEM_BARRIER_HAZARD", 1)
    assert pal.items[1, 6] == ("ITEM_TURRET", 0)
    assert pal.items[2, 6] == ("ITEM_GOO", 0)
    assert pal.items[3, 6] == ("ITEM_LIGHT_PANEL", 0)

    assert pal.items[0, 7] == ("ITEM_PAINT_SPLAT", 0)
    assert pal.items[1, 7] == ("ITEM_PAINT_SPLAT", 1)
    assert pal.items[2, 7] == ("ITEM_PAINT_SPLAT", 2)
    assert pal.items[3, 7] == ("ITEM_PAINT_SPLAT", 3)


@pytest.mark.parametrize('set_version', [False, True], ids=['blank', 'v1'])
def test_palette_load_v1(set_version: bool) -> None:
    """Test loading version 1 of the palette format."""
    kv = Keyvalues('Palette', [
        Keyvalues('Name', 'Test Palette'),
        Keyvalues('UUID', 'c510aee8759e4b61871d233806b5e73a'),
        Keyvalues('Items', [
            Keyvalues("ITEM_BUTTON_PEDESTAL", "0"),
            Keyvalues("ITEM_BUTTON_FLOOR", "0"),
            Keyvalues("ITEM_BUTTON_FLOOR", "1"),
            Keyvalues("ITEM_BUTTON_FLOOR", "2"),

            Keyvalues("ITEM_CUBE", "0"),
            Keyvalues("ITEM_CUBE", "1"),
            Keyvalues("ITEM_CUBE", "3"),
            Keyvalues("ITEM_CUBE", "4"),

            Keyvalues("ITEM_TBEAM", "0"),
            Keyvalues("ITEM_CATAPULT", "0"),
            Keyvalues("ITEM_LIGHT_BRIDGE", "0"),
            Keyvalues("ITEM_PANEL_STAIRS", "0"),

            Keyvalues("ITEM_BARRIER_HAZARD", "0"),
            Keyvalues("ITEM_BARRIER", "0"),
            Keyvalues("ITEM_PISTON_PLATFORM", "0"),
            Keyvalues("ITEM_RAIL_PLATFORM", "0"),

            Keyvalues("ITEM_LASER_EMITTER_CENTER", "0"),
            Keyvalues("ITEM_LASER_CATCHER_CENTER", "0"),
            Keyvalues("ITEM_LASER_RELAY_CENTER", "0"),
            Keyvalues("ITEM_CUBE", "2"),

            Keyvalues("ITEM_PANEL_CLEAR", "0"),
            Keyvalues("ITEM_PANEL_ANGLED", "0"),
            Keyvalues("ITEM_PANEL_FLIP", "0"),
            Keyvalues("ITEM_SECONDARY_OBSERVATION_ROOM", "0"),

            Keyvalues("ITEM_BARRIER_HAZARD", "1"),
            Keyvalues("ITEM_TURRET", "0"),
            Keyvalues("ITEM_GOO", "0"),
            Keyvalues("ITEM_LIGHT_PANEL", "0"),

            Keyvalues("ITEM_PAINT_SPLAT", "0"),
            Keyvalues("ITEM_PAINT_SPLAT", "1"),
            Keyvalues("ITEM_PAINT_SPLAT", "2"),
            Keyvalues("ITEM_PAINT_SPLAT", "3"),
        ]),
    ])
    if set_version:
        kv['version'] = '1'

    pal, upgrade = Palette.parse(kv, 'test_file.vdf')
    assert upgrade is True
    check_palette(pal)
    assert pal.group == ''
    assert not pal.readonly
    assert pal.settings is None


def test_palette_load_v2() -> None:
    """Test loading version 2 of the palette format."""
    kv = Keyvalues('Palette', [
        Keyvalues('Version', '2'),
        Keyvalues('Name', 'Test Palette'),
        Keyvalues('UUID', 'c510aee8759e4b61871d233806b5e73a'),
        Keyvalues('Items', pos_block).copy(),
    ])
    pal, upgrade = Palette.parse(kv, 'test_file.vdf')
    assert upgrade is True
    check_palette(pal)
    assert pal.group == ''
    assert not pal.readonly
    assert pal.settings is None


def test_palette_load_v3() -> None:
    """Test loading version 2 of the palette format."""
    kv = Keyvalues('Palette', [
        Keyvalues('Version', '3'),
        Keyvalues('Name', 'Test Palette'),
        Keyvalues('UUID', 'c510aee8759e4b61871d233806b5e73a'),
        Keyvalues('Positions', pos_block).copy(),
        Keyvalues('Items', [
            # These should be ignored.
            Keyvalues('ITEM_INVALID_OLD_BLOCK', '3'),
        ])
    ])
    pal, upgrade = Palette.parse(kv, 'test_file.vdf')
    assert upgrade is False
    check_palette(pal)
    assert pal.group == ''
    assert not pal.readonly
    assert pal.settings is None
