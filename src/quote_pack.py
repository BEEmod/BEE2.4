"""Data structures for quote packs."""
import enum
from collections.abc import Iterator
from typing import Dict, Iterable, List, Mapping, Optional, Set

import attrs
from srctools import Angle, Keyvalues, Vec, conv_int, logger
from typing_extensions import Self, assert_never

import utils
from transtoken import TransToken, TransTokenSource


LOGGER = logger.get_logger(__name__)
TRANS_QUOTE = TransToken.untranslated('"{line}"')
TRANS_QUOTE_ACT = TransToken.untranslated(': "{line}"')
TRANS_NO_NAME = TransToken.ui('No Name!')


@utils.freeze_enum_props
class LineCriteria(enum.Enum):
    """Criteria to determine if a line is applicable."""
    # Which player model is selected.
    CHELL = enum.auto()
    BENDY = enum.auto()
    ATLAS = enum.auto()
    PBODY = enum.auto()

    # The current game mode
    SP = enum.auto()
    COOP = enum.auto()
    # Combinations of the above.
    HUMAN = enum.auto()  # Chell | Bendy
    ROBOT = enum.auto()  # Coop | ATLAS | P-Body

    @property
    def tooltip(self) -> TransToken:
        """Tooltip to display for this character."""
        if self is LineCriteria.SP:
            return TransToken.ui('Singleplayer')
        elif self is LineCriteria.COOP:
            return TransToken.ui('Cooperative')
        elif self is LineCriteria.ATLAS:
            return TransToken.ui('ATLAS (SP/Coop)')
        elif self is LineCriteria.PBODY:
            return TransToken.ui('P-Body (SP/Coop)')
        elif self is LineCriteria.BENDY:
            return TransToken.ui('Bendy')
        elif self is LineCriteria.CHELL:
            return TransToken.ui('Chell')
        elif self is LineCriteria.HUMAN:
            return TransToken.ui('Human characters (Bendy and Chell)')
        elif self is LineCriteria.ROBOT:
            return TransToken.ui('AI characters (ATLAS, P-Body, or Coop)')
        else:
            assert_never(self)


@utils.freeze_enum_props
class Response(enum.Enum):
    """Kinds of coop response."""
    DEATH_GENERIC = enum.auto()
    DEATH_GOO = enum.auto()
    DEATH_TURRET = enum.auto()
    DEATH_CRUSH = enum.auto()
    DEATH_LASERFIELD = enum.auto()

    # TODO: Fill in other "animations" for these.
    GESTURE_GENERIC = enum.auto()
    GESTURE_CAMERA = enum.auto()

    @property
    def is_death(self) -> bool:
        return self.name.startswith('DEATH')

    @property
    def is_gesture(self) -> bool:
        """Is this a response to doing a gesture"""
        return self.name.startswith('GESTURE')

    @property
    def title(self) -> TransToken:
        """Return the title text for the group."""
        if self is Response.DEATH_GENERIC:
            return TransToken.ui('Death - Generic')
        elif self is Response.DEATH_GOO:
            return TransToken.ui('Death - Toxic Goo')
        elif self is Response.DEATH_TURRET:
            return TransToken.ui('Death - Turrets')
        elif self is Response.DEATH_CRUSH:
            return TransToken.ui('Death - Crusher')
        elif self is Response.DEATH_LASERFIELD:
            return TransToken.ui('Death - LaserField')
        elif self is Response.GESTURE_GENERIC:
            return TransToken.ui('Gesture - Generic')
        elif self is Response.GESTURE_CAMERA:
            return TransToken.ui('Gesture - Camera')
        else:
            assert_never(self)

RESPONSE_NAMES: Mapping[str, Response] = {
    resp.name.lower(): resp
    for resp in Response
} | {
    # Legacy names accepted in earlier versions. Only maybe used in UCPs?
    'taunt_generic': Response.GESTURE_GENERIC,
    'camera_generic': Response.GESTURE_CAMERA,
}


@attrs.frozen
class QuoteEvent:
    """Defines instances that should be placed if prerequisites """
    id: str
    file: str

    @classmethod
    def parse(cls, kv: Keyvalues) -> Self:
        """Parse from the keyvalues data."""
        return cls(
            id=kv['id'],
            file=kv['file'],
        )


@attrs.frozen(kw_only=True)
class Line:
    """A single group of lines that can be played."""
    id: str
    criterion: Set[LineCriteria]
    name: TransToken
    transcript: List[tuple[str, TransToken]]

    only_once: bool
    atomic: bool

    choreo_name: str
    bullseyes: List[str]
    sounds: List[str]
    scenes: List[str]
    set_stylevars: Set[str]

    @classmethod
    def parse(cls, pak_id: str, kv: Keyvalues) -> Self:
        """Parse from the keyvalues data.

        The keyvalue should have its name start with "line".
        """
        criterion: Set[LineCriteria] = set()
        criteria_parts = kv.name.split('_')
        assert criteria_parts[0] == 'line'
        for part in criteria_parts[1:]:
            try:
                criterion.add(LineCriteria[part.upper()])
            except KeyError:
                LOGGER.warning('Invalid Quote Pack line criteria name "{}"', part)

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
            criterion=criterion,
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
    def _parse_transcript(cls, pak_id: str, kvs: Iterable[Keyvalues]) -> Iterator[tuple[str, TransToken]]:
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

    def iter_trans_tokens(self, path: str) -> Iterator[TransTokenSource]:
        """Yield all translatable tokens for this line."""
        yield self.name, path + '.name'
        for i, (actor, line) in enumerate(self.transcript, 1):
            yield line, f'{path}.transcript_{i}'


@attrs.frozen
class Quote:
    """A category of quotes that may be enabled or disabled."""
    tests: list[Keyvalues]
    priority: int
    name: TransToken
    lines: List[Line]

    @classmethod
    def parse(cls, pak_id: str, kv: Keyvalues) -> Self:
        """Parse from the keyvalues data."""
        lines: List[Line] = []
        tests: List[Keyvalues] = []
        priority = 0
        name: TransToken = TransToken.BLANK
        for child in kv:
            if child.name.startswith('line'):
                lines.append(Line.parse(pak_id, child))
            elif child.name == 'priority':
                priority = conv_int(child.value)
            elif child.name == 'name':
                name = TransToken.parse(pak_id, child.value)
            else:
                tests.append(child)
        return cls(tests, priority, name, lines)

    def iter_trans_tokens(self, path: str) -> Iterator[TransTokenSource]:
        """Yield all translatable tokens for this quote."""
        yield self.name, path + '.name'
        for i, line in enumerate(self.lines, 1):
            yield from line.iter_trans_tokens(f'{path}/{line.id}')


@attrs.frozen(kw_only=True)
class Group:
    """The set of quotes for either Singleplayer or Coop."""
    id: str
    name: TransToken
    desc: TransToken
    choreo_name: str
    choreo_loc: Optional[Vec]
    choreo_use_dings: bool

    quotes: List[Quote]

    @classmethod
    def parse(cls, pak_id: str, kv: Keyvalues) -> Self:
        """Parse from the keyvalues data."""
        choreo_name = kv['Choreo_Name', '@choreo']
        use_dings = kv.bool('use_dings', True)

        name_raw = kv['name']
        try:
            name = TransToken.parse(pak_id, name_raw)
        except LookupError:
            name = TRANS_NO_NAME

        group_id = kv['id', name_raw].upper()
        desc = TransToken.parse(pak_id, kv['desc', ''])

        try:
            choreo_loc = Vec.from_str(kv['choreo_loc'])
        except LookupError:
            choreo_loc = None

        quotes = [
            Quote.parse(pak_id, child)
            for child in kv.find_all('Quote')
        ]

        return cls(
            id=group_id,
            name=name,
            desc=desc,
            choreo_name=choreo_name,
            choreo_use_dings=use_dings,
            choreo_loc=choreo_loc,
            quotes=quotes,
        )

    def __iadd__(self, other: Self) -> Self:
        """Merge two group definitions into one."""
        return attrs.evolve(self, quotes=self.quotes + other.quotes)


@attrs.frozen(kw_only=True)
class Monitor:
    """Options required for displaying the character in the monitor screen."""
    studio: str
    studio_actor: str
    cam_loc: Vec
    turret_hate: bool
    interrupt: float
    cam_angle: Angle


@attrs.frozen(kw_only=True)
class ExportedQuote:
    """The data that is saved for the compiler to use."""
    id: str
    cave_skin: Optional[int]
    use_dings: bool
    use_microphone: bool
    global_bullseye: str
    chars: Set[str]
    base_inst: str
    position: Vec

    groups: Dict[str, Group]
    events: Dict[str, QuoteEvent]
    responses: Dict[Response, List[Line]]
    midchamber: List[Quote]
    monitor: Optional[Monitor]
