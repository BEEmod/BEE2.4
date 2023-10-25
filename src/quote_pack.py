"""Data structures for quote packs."""
import enum
from typing import List

import attrs
from srctools import Keyvalues, Vec
from typing_extensions import assert_never

import utils
from transtoken import TransToken


@utils.freeze_enum_props
class CharKind(enum.Flag):
    """The categories lines can be applicable to."""
    # These 4 are exclusive, the other 4 are not.
    CHELL = enum.auto()
    BENDY = enum.auto()
    ATLAS = enum.auto()
    PBODY = enum.auto()

    SP = enum.auto()
    COOP = enum.auto()
    HUMAN = CHELL | BENDY
    ROBOT = ATLAS | PBODY | COOP

    ANY = CHELL | BENDY | ATLAS | PBODY | SP | COOP | HUMAN | ROBOT

    @property
    def tooltip(self) -> TransToken:
        """Tooltip to display for this character."""
        if self is CharKind.SP:
            return TransToken.ui('Singleplayer')
        elif self is CharKind.COOP:
            return TransToken.ui('Cooperative')
        elif self is CharKind.ATLAS:
            return TransToken.ui('ATLAS (SP/Coop)')
        elif self is CharKind.PBODY:
            return TransToken.ui('P-Body (SP/Coop)')
        elif self is CharKind.BENDY:
            return TransToken.ui('Bendy')
        elif self is CharKind.CHELL:
            return TransToken.ui('Chell')
        elif self is CharKind.HUMAN:
            return TransToken.ui('Human characters (Bendy and Chell)')
        elif self is CharKind.ROBOT:
            return TransToken.ui('AI characters (ATLAS, P-Body, or Coop)')
        elif self is CharKind.ANY:
            return TransToken.ui('Always applicable')
        else:
            assert_never(self)


line_kinds = {
    'line': CharKind.ANY,
    'line_sp': CharKind.SP,
    'line_coop': CharKind.COOP,
    'line_atlas': CharKind.ATLAS,
    'line_pbody': CharKind.PBODY,
    'line_bendy': CharKind.BENDY,
    'line_chell': CharKind.CHELL,
    'line_human': CharKind.HUMAN,
    'line_robot': CharKind.ROBOT,
}


@attrs.frozen
class QuoteEvent:
    """Defines instances that should be placed if prerequisites """
    id: str
    file: str


@attrs.frozen
class Line:
    """A single group of lines that can be played."""
    id: str
    name: TransToken
    transcript: TransToken

    only_once: bool
    atomic: bool

    choreo_name: str
    choreo_bullseyes: List[str]
    wave: str
    scenes: List[str]


@attrs.frozen
class MidChamber:
    """Midchamber voicelines."""
    name: str
    flags: List[Keyvalues]
    lines: List[Line]

@attrs.frozen
class Quote:
    """A category of quotes that may be enabled or disabled."""
    attrs: set[str]
    priority: int
    name: str
    lines: List[str]


@attrs.frozen
class Group:
    """The set of quotes for either Singleplayer or Coop."""
    name: TransToken
    desc: TransToken
    choreo_name: str
    choreo_loc: Vec

    quotes: List[Quote]
