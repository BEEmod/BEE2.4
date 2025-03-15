"""Test the localisation system."""
from srctools import EmptyMapping

from transtoken import TransToken, NS_GAME, NS_UI, NS_UNTRANSLATED
import utils


def token_constructor() -> None:
    """Test the constructors work as expected."""
    tok = TransToken(
        utils.obj_id("SOME_pACKAGE"),
        utils.obj_id("ORIG_PACK"),
        "Style: {style}", {"style": "Clean"},
    )
    assert tok.namespace == "SOME_PACKAGE"
    assert tok.orig_pack == "ORIG_PACK"
    assert tok.token == "Style: {style}"
    assert tok.parameters == {"style": "Clean"}

    # If not provided, it uses the singleton object.
    tok = TransToken(utils.obj_id("PACK"), utils.obj_id("PACK"), "No Parameters", {})
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
    pack = utils.obj_id("SOME_PACKAGE")
    owner = utils.obj_id("OWNER")

    assert TransToken.parse(pack, "Regular text") == TransToken(
        pack, pack, "Regular text", EmptyMapping
    )

    assert TransToken.parse(owner, "[[SOME_packAGE]] The Blah device\n") == TransToken(
        pack, owner, "The Blah device\n", EmptyMapping
    )

    # Blank = no translation.
    assert TransToken.parse(owner, "[[]] The Blah device\n") == TransToken(
        NS_UNTRANSLATED, owner, "The Blah device\n", EmptyMapping
    )

    # Invalid -> treated as if no syntax is involved.
    assert TransToken.parse(owner, "[[PACKAGE The Blah device\n") == TransToken(
        owner, owner, "[[PACKAGE The Blah device\n", EmptyMapping
    )
