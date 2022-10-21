"""Test the localisation system."""
import pytest

from srctools import EmptyMapping
from localisation import TransToken, NS_GAME, NS_UI, NS_UNTRANSLATED


def token_constructor() -> None:
    """Test the constructors work as expected."""
    tok = TransToken("SOME_PACKAGE", "style.clean", "Clean Style", {"style": "Clean"})
    assert tok.namespace == "SOME_PACKAGE"
    assert tok.token == "style.clean"
    assert tok.default == "Clean Style"
    assert tok.parameters == {"style": "Clean"}

    # If not provided, it uses the singleton object.
    tok = TransToken("PACK", "no.params", "No Parameters", {})
    assert tok.parameters is EmptyMapping

    tok = TransToken.from_valve('PORTAL2_PuzzleEditor_Palette_sphere')
    assert tok.namespace == NS_GAME
    assert tok.token == 'PORTAL2_PuzzleEditor_Palette_sphere'
    assert tok.default == 'PORTAL2_PuzzleEditor_Palette_sphere'

    tok = TransToken.ui('menu.saveas', 'Save As')
    assert tok.namespace == NS_UI
    assert tok.token == 'menu.saveas'
    assert tok.default == 'Save As'


def test_token_parse() -> None:
    """Test that the parsing code works correctly."""
    assert TransToken.parse("Regular text", "SOME_PACKAGE") == TransToken.untranslated("Regular text")

    assert TransToken.parse(
        "[PACKAGE:item.blah] The Blah device\n", "OWNER"
    ) == TransToken("PACKAGE", "item.blah", "The Blah device\n")

    assert TransToken.parse(
        "[item.turret]Sentry Turret\n", "OWNER"
    ) == TransToken("OWNER", "item.turret", "Sentry Turret")
