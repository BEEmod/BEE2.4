import pytest

from corridor import Attachment, Direction, GameMode
from packages.corridor import parse_specifier, parse_corr_kind


@pytest.mark.parametrize('text, mode, direction, attach', [
    ('sp_entry', GameMode.SP, Direction.ENTRY, None),
    ('exit_sp', GameMode.SP, Direction.EXIT, None),
    ('sp_entry_horiz', GameMode.SP, Direction.ENTRY, Attachment.HORIZ),
    ('exit_flat_coop', GameMode.COOP, Direction.EXIT, Attachment.HORIZ),
    ('coop_eNTry_floor', GameMode.COOP, Direction.ENTRY, Attachment.FLOOR),
    ('sp_down_exit', GameMode.SP, Direction.EXIT, Attachment.FLOOR),
    ('coop_exit', GameMode.COOP, Direction.EXIT, None),
    ('entry_sp_down', GameMode.SP, Direction.ENTRY, Attachment.CEILING),
    ('', None, None, None),
    ('sp', GameMode.SP, None, None),
    ('coop', GameMode.COOP, None, None),
    ('entry', None, Direction.ENTRY, None),
    ('exIt', None, Direction.EXIT, None),
    ('hoRiz', None, None, Attachment.HORIZ),
    ('flAt', None, None, Attachment.HORIZ),
    ('flOor', None, None, Attachment.FLOOR),
    ('ceIl', None, None, Attachment.CEILING),
    ('cEiling', None, None, Attachment.CEILING),
    ('up', None, None, Attachment.CEILING),
    ('doWn', None, None, Attachment.FLOOR),
    ('entry_up', None, Direction.ENTRY, Attachment.FLOOR),
    ('entry_down', None, Direction.ENTRY, Attachment.CEILING),
    ('exit_up', None, Direction.EXIT, Attachment.CEILING),
    ('exit_down', None, Direction.EXIT, Attachment.FLOOR),
    ('entry_floor', None, Direction.ENTRY, Attachment.FLOOR),
    ('entry_ceil', None, Direction.ENTRY, Attachment.CEILING),
    ('floor_exit', None, Direction.EXIT, Attachment.FLOOR),
    ('exit_ceil', None, Direction.EXIT, Attachment.CEILING),
])
def test_specifier_parse(
    text: str,
    mode: GameMode,
    direction: Direction,
    attach: Attachment,
) -> None:
    """Test parsing any kind of specifier."""
    assert parse_specifier(text) == (mode, direction, attach)
    # Check case-insensitivity.
    assert parse_specifier(text.swapcase()) == (mode, direction, attach)
    if None not in (mode, direction, attach):
        # Also a corridor kind.
        assert parse_corr_kind(text) == (mode, direction, attach)


@pytest.mark.parametrize('text', [
    # Duplicate definitions
    'coop_up_sp',
    'sp_horiz_entry_horiz',
    'coop_sp_exit',
    'entry_coop_exit',
    'entry_entry_coop',
    # Invalid keywords
    'exit,coop',
    'unknown',
    'blah',
])
def test_specifier_fail(text: str) -> None:
    """Ensure invalid values don't succeed."""
    try:
        result = parse_specifier(text)
    except ValueError:
        pass
    else:
        pytest.fail(f'Got: {result!r}')

    # Applied to corridor kinds as well.
    try:
        result = parse_corr_kind(text)
    except ValueError:
        pass
    else:
        pytest.fail(f'Got: {result!r}')


def test_corr_kind_parse() -> None:
    """Test some specifics for a single kind."""
    # If unset horizontal is implied.
    assert parse_corr_kind('sp_Entry') == (GameMode.SP, Direction.ENTRY, Attachment.HORIZ)
    assert parse_corr_kind('exit_Coop') == (GameMode.COOP, Direction.EXIT, Attachment.HORIZ)


@pytest.mark.parametrize('text', [
    '',
    'sp_up',
    'exit_horiz',
    'sp',
    'horiz',
    'exit',
])
def test_corr_kind_fail(text: str) -> None:
    """Corridor kinds specifically do not allow mode/direction to be unspecified."""
    try:
        result = parse_corr_kind(text)
    except ValueError:
        pass
    else:
        pytest.fail(f'Got: {result!r}')
