"""Test the localisation system."""
from srctools import EmptyMapping
from app.localisation import TransToken, NS_GAME, NS_UI, NS_UNTRANSLATED


def token_constructor() -> None:
    """Test the constructors work as expected."""
    tok = TransToken("SOME_PACKAGE", "ORIG_PACK", "Style: {style}", {"style": "Clean"})
    assert tok.namespace == "SOME_PACKAGE"
    assert tok.orig_pack == "ORIG_PACK"
    assert tok.token == "Style: {style}"
    assert tok.parameters == {"style": "Clean"}

    # If not provided, it uses the singleton object.
    tok = TransToken("PACK", "PACK", "No Parameters", {})
    assert tok.parameters is EmptyMapping

    tok = TransToken.from_valve('PORTAL2_PuzzleEditor_Palette_sphere')
    assert tok.namespace == NS_GAME
    assert tok.orig_pack == NS_GAME
    assert tok.token == 'PORTAL2_PuzzleEditor_Palette_sphere'

    tok = TransToken.ui('Save As')
    assert tok.namespace == NS_UI
    assert tok.orig_pack == NS_UI
    assert tok.token == 'Save As'


def test_token_parse() -> None:
    """Test that the parsing code works correctly."""
    assert TransToken.parse("SOME_PACKAGE", "Regular text") == TransToken("SOME_PACKAGE", "SOME_PACKAGE", "Regular text", EmptyMapping)

    assert TransToken.parse("OWNER", "[[PACKAGE]] The Blah device\n") == TransToken("PACKAGE", "OWNER", "The Blah device\n", EmptyMapping)

    # Blank = no translation.
    assert TransToken.parse("OWNER", "[[]] The Blah device\n") == TransToken(NS_UNTRANSLATED, "OWNER", "The Blah device\n", EmptyMapping)

    # Invalid -> treated as if no syntax is involved.
    assert TransToken.parse("OWNER", "[[PACKAGE The Blah device\n") == TransToken("OWNER", "OWNER", "[[PACKAGE The Blah device\n", EmptyMapping)
