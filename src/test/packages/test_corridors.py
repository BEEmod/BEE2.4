import pytest
from packages.corridor import parse_specifier
from consts import CorrOrient, CorrDir, GameMode


@pytest.mark.parametrize('text, mode, direction, orient', [
    ('sp_entry', GameMode.SP, CorrDir.ENTRY, CorrOrient.HORIZ),
    ('exit_sp', GameMode.SP, CorrDir.EXIT, CorrOrient.HORIZ),
    ('sp_entry_horiz', GameMode.SP, CorrDir.ENTRY, CorrOrient.HORIZ),
    ('exit_flat_coop', GameMode.COOP, CorrDir.EXIT, CorrOrient.HORIZ),
    ('coop_entry_up', GameMode.COOP, CorrDir.ENTRY, CorrOrient.UP),
    ('sp_down_exit', GameMode.SP, CorrDir.EXIT, CorrOrient.DOWN),
    ('coop_exit', GameMode.COOP, CorrDir.EXIT, CorrOrient.HORIZ),
    ('entry_sp_down', GameMode.SP, CorrDir.ENTRY, CorrOrient.DOWN),
])
def test_specifier_parse(
    text: str,
    mode: GameMode,
    direction: CorrDir,
    orient: CorrOrient,
) -> None:
    assert parse_specifier(text) == (mode, direction, orient)
    # Check case-insensitivity.
    assert parse_specifier(text.swapcase()) == (mode, direction, orient)


@pytest.mark.parametrize('text', [
    # Missing required values
    '',
    'sp_up',
    'exit_horiz',
    # Duplicate definitions
    'coop_up_sp',
    'sp_horiz_entry_horiz',
    'coop_sp_exit',
    'entry_coop_exit',
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
