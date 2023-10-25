"""Data structures for quote packs."""
import enum
from collections.abc import Iterator
from typing import Iterable, List, Set

import attrs
from srctools import Keyvalues, Vec, logger
from typing_extensions import Self, assert_never

import utils
from transtoken import TransToken


LOGGER = logger.get_logger(__name__)
TRANS_QUOTE = TransToken.untranslated('"{line}"')
TRANS_QUOTE_ACT = TransToken.untranslated(': "{line}"')


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


@attrs.frozen(kw_only=True)
class Line:
    """A single group of lines that can be played."""
    id: str
    kind: CharKind
    name: TransToken
    transcript: List[tuple[str, str]]

    only_once: bool
    atomic: bool

    choreo_name: str
    bullseyes: List[str]
    sounds: List[str]
    scenes: List[str]
    set_stylevars: Set[str]

    @classmethod
    def parse(cls, kv: Keyvalues, pak_id: str) -> Self:
        """Parse from the keyvalues data."""
        try:
            kind = line_kinds[kv.name]
        except KeyError:
            LOGGER.warning('Invalid Quote Pack line kind "{}"', kv.real_name)
            kind = CharKind.ANY

        try:
            quote_id = kv['id']
        except LookupError:
            quote_id = kv['name', '']
            LOGGER.warning(
                'Quote Pack has no specific ID for "{}"!',
                quote_id,
            )
        disp_name = TransToken.parse(pak_id, kv['name', ''])
        transcript = list(cls._parse_transcript(pak_id, kv.find_all('trans')))
        only_once = kv.bool('onlyonce')
        atomic = kv.bool('atomic')
        caption_name = kv['cc_emit', '']
        # todo: Old EndCommand syntax, defined for the whole line.
        stylevars = {
            child.value.casefold()
            for child in kv.find_all('setstylevar')
        }
        # Files have these double-nested, but that's rather pointless.
        scenes = [
            filename
            for child in kv.find_all('choreo')
            for filename in child.as_array()
        ]
        sounds = [child.value for child in kv.find_all('snd')]
        bullseyes = [child.value for child in kv.find_all('bullseye')]

        return cls(
            id=quote_id,
            kind=kind,
            name=disp_name,
            transcript=transcript,
            only_once=kv.bool('onlyonce'),
            atomic=atomic,
            choreo_name=kv['choreo_name', ''],
            set_stylevars=stylevars,
            scenes=scenes,
            sounds=sounds,
            bullseyes=bullseyes,
        )

    @classmethod
    def _parse_transcript(cls, pak_id: str, kvs: Iterable[Keyvalues]) -> Iterator[tuple[str, str]]:
        for child in kvs:
            if ':' in child.value:
                name, trans = child.value.split(':', 1)
                yield name.rstrip(), TRANS_QUOTE_ACT.format(
                    line=TransToken.parse(pak_id, trans.lstrip())
                )
            else:
                yield '', TRANS_QUOTE.format(
                    line=TransToken.parse(pak_id, child.value)
                )


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


@attrs.frozen(kw_only=True)
class Group:
    """The set of quotes for either Singleplayer or Coop."""
    name: TransToken
    desc: TransToken
    choreo_name: str
    choreo_loc: Vec
    choreo_use_dings: bool

    quotes: List[Quote]
