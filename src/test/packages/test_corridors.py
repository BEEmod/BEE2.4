import pytest

from corridor import Direction, GameMode, Orient
from packages.corridor import parse_specifier, parse_corr_kind


@pytest.mark.parametrize('text, mode, direction, orient', [
    ('sp_entry', GameMode.SP, Direction.ENTRY, None),
    ('exit_sp', GameMode.SP, Direction.EXIT, None),
    ('sp_entry_horiz', GameMode.SP, Direction.ENTRY, Orient.HORIZ),
    ('exit_flat_coop', GameMode.COOP, Direction.EXIT, Orient.HORIZ),
    ('coop_eNTry_up', GameMode.COOP, Direction.ENTRY, Orient.UP),
    ('sp_down_exit', GameMode.SP, Direction.EXIT, Orient.DOWN),
    ('coop_exit', GameMode.COOP, Direction.EXIT, None),
    ('entry_sp_down', GameMode.SP, Direction.ENTRY, Orient.DOWN),
    ('', None, None, None),
    ('sp', GameMode.SP, None, None),
    ('coop', GameMode.COOP, None, None),
    ('entry', None, Direction.ENTRY, None),
    ('exit', None, Direction.EXIT, None),
    ('horiz', None, None, Orient.HORIZ),
    ('up', None, None, Orient.UP),
    ('down', None, None, Orient.DOWN),
])
def test_specifier_parse(
    text: str,
    mode: GameMode,
    direction: Direction,
    orient: Orient,
) -> None:
    """Test parsing any kind of specifier."""
    assert parse_specifier(text) == (mode, direction, orient)
    # Check case-insensitivity.
    assert parse_specifier(text.swapcase()) == (mode, direction, orient)
    if None not in (mode, direction, orient):
        # Also a corridor kind.
        assert parse_corr_kind(text) == (mode, direction, orient)


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
    assert parse_corr_kind('sp_Entry') == (GameMode.SP, Direction.ENTRY, Orient.HORIZ)
    assert parse_corr_kind('exit_Coop') == (GameMode.COOP, Direction.EXIT, Orient.HORIZ)


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
