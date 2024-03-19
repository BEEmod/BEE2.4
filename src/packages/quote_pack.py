from typing import List, Set, Iterator

from app.errors import AppError
from quote_pack import Line, Quote, QuoteEvent, Group, QuoteInfo, Response, Monitor, RESPONSE_NAMES
from transtoken import TransToken, TransTokenSource
from packages import PackagesSet, PakObject, set_cond_source, ParseData, get_config, SelitemData
from srctools import Angle, Keyvalues, NoKeyError, logger
import srctools


LOGGER = logger.get_logger('packages.quote_pack')


class QuotePack(PakObject, needs_foreground=True, style_suggest_key='quote'):
    """Adds lists of voice lines which are automatically chosen."""
    def __init__(
        self,
        quote_id: str,
        selitem_data: SelitemData,
        config: Keyvalues,
        *,
        data: QuoteInfo,
    ) -> None:
        self.id = quote_id
        self.selitem_data = selitem_data
        self.config = config
        set_cond_source(config, f'QuotePack <{quote_id}>')
        self.data = data

    @classmethod
    async def parse(cls, data: ParseData) -> 'QuotePack':
        """Parse a voice line definition."""
        selitem_data = SelitemData.parse(data.info, data.pak_id)
        chars = {
            char.strip()
            for char in
            data.info['characters', ''].split(',')
            if char.strip()
        }

        # For Cave Johnson voicelines, this indicates what skin to use on the
        # portrait.
        port_skin = srctools.conv_int(data.info['caveSkin', ''], None)

        try:
            monitor_data = data.info.find_key('monitor')
        except NoKeyError:
            monitor = None
        else:
            monitor = Monitor(
                studio=monitor_data['studio'],
                studio_actor=monitor_data['studio_actor', ''],
                interrupt=monitor_data.float('interrupt_chance', 0),
                cam_loc=monitor_data.vec('Cam_loc'),
                cam_angle=Angle(monitor_data.vec('cam_angles')),
                turret_hate=monitor_data.bool('TurretShoot'),
            )

        config = await get_config(
            data.info,
            'voice',
            pak_id=data.pak_id,
            prop_name='file',
        )()

        try:
            quotes_kv = config.find_key('Quotes')
        except NoKeyError:
            raise AppError(TransToken.ui(
                'No "Quotes" key in config for quote pack {id}!'
            ).format(id=data.id)) from None
        else:
            del config['Quotes']
        if 'Quotes' in config:
            raise AppError(TransToken.ui(
                'Multiple "Quotes" keys found in config for quote pack {id}!'
            ).format(id=data.id))

        base_inst = quotes_kv['base', '']
        position = quotes_kv.vec('quote_loc', -10_000.0, 0.0, 0.0)
        use_dings = quotes_kv.bool('use_dings')
        use_microphones = quotes_kv.bool('UseMicrophones')
        global_bullseye = quotes_kv['bullseye', '']
        groups: dict[str, Group] = {}
        events: dict[str, QuoteEvent] = {}
        responses: dict[Response, List[Line]] = {}
        midchamber: list[Quote] = []

        for group_kv in quotes_kv.find_all('Group'):
            group = Group.parse(data.pak_id, group_kv)
            if group.id in groups:
                groups[group.id] += group
            else:
                groups[group.id] = group

        with logger.context('Midchamber'):
            for mid_kv in quotes_kv.find_all('Midchamber', 'Quote'):
                midchamber.append(Quote.parse(data.pak_id, mid_kv, True))

        for event_kv in quotes_kv.find_all('QuoteEvents', 'Event'):
            event = QuoteEvent.parse(event_kv)
            if event.id in events:
                LOGGER.warning(
                    'Duplicate QuoteEvent "{}" for quote pack {}',
                    event.id, data.id
                )
            events[event.id] = event

        response_dings = use_dings

        for resp_kv in quotes_kv.find_children('CoopResponses'):
            try:
                resp = RESPONSE_NAMES[resp_kv.name]
            except KeyError:
                raise AppError(TransToken.ui(
                    'Invalid response kind "{name}" in config for quote pack {id}!'
                ).format(name=resp_kv.real_name, id=data.id)) from None
            response_dings = resp_kv.bool('use_dings', response_dings)

            lines = responses.setdefault(resp, [])
            with logger.context(repr(resp)):
                for line_kv in resp_kv:
                    lines.append(Line.parse(data.pak_id, line_kv, False))

        return cls(
            data.id,
            selitem_data,
            config,
            data=QuoteInfo(
                id=data.id,
                base_inst=base_inst,
                position=position,
                use_dings=use_dings,
                use_microphones=use_microphones,
                global_bullseye=global_bullseye,
                groups=groups,
                events=events,
                midchamber=midchamber,
                response_use_dings=response_dings,
                responses=responses,

                chars=chars,
                cave_skin=port_skin,
                monitor=monitor,
            ),
        )

    def add_over(self, override: 'QuotePack') -> None:
        """Add the additional lines to ourselves."""
        self.selitem_data += override.selitem_data
        self.config += override.config
        self.data.midchamber += override.data.midchamber
        for group in override.data.groups.values():
            if group.id in self.data.groups:
                self.data.groups[group.id] += group
            else:
                self.data.groups[group.id] = group

        for resp, lines in override.data.responses.items():
            try:
                self.data.responses[resp] += lines
            except KeyError:
                self.data.responses[resp] = lines

        if self.data.cave_skin is None:
            self.data.cave_skin = override.data.cave_skin

        if self.data.monitor is None:
            self.data.monitor = override.data.monitor

        if overlap := self.data.events.keys() & override.data.events.keys():
            LOGGER.warning(
                'Duplicate event IDs for quote pack {}: {}',
                self.id, sorted(overlap),
            )
        self.data.events |= override.data.events

    def __repr__(self) -> str:
        return '<Voice:' + self.id + '>'

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Verify no quote packs have duplicate IDs."""
        # TODO rewrite!

        def iter_lines(conf: Keyvalues) -> Iterator[Keyvalues]:
            """Iterate over the varios line blocks."""
            yield from conf.find_all("Quotes", "Group", "Quote", "Line")

            yield from conf.find_all("Quotes", "Midchamber", "Quote", "Line")

            for group in conf.find_children("Quotes", "CoopResponses"):
                if group.has_children():
                    yield from group

        for voice in packset.all_obj(cls):
            used: Set[str] = set()
            for quote in iter_lines(voice.config):
                try:
                    quote_id = quote['id']
                except LookupError:
                    quote_id = quote['name', '']
                    LOGGER.warning(
                        'Quote Pack "{}" has no specific ID for "{}"!',
                        voice.id, quote_id,
                    )
                if quote_id in used:
                    LOGGER.warning(
                        'Quote Pack "{}" has duplicate '
                        'voice ID "{}"!', voice.id, quote_id,
                    )
                used.add(quote_id)

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield all translation tokens in this voice pack."""
        yield from self.selitem_data.iter_trans_tokens(f'voiceline/{self.id}')
        for group in self.data.groups.values():
            yield group.name, f'voiceline/{self.id}/{group.id}.name'
            yield group.desc, f'voiceline/{self.id}/{group.id}.desc'
            for quote in group.quotes:
                yield from quote.iter_trans_tokens(f'voiceline/{self.id}/{group.id}')
        for resp, lines in self.data.responses.items():
            for line in lines:
                yield from line.iter_trans_tokens(f'voiceline/{self.id}/responses')
        for quote in self.data.midchamber:
            yield from quote.iter_trans_tokens(f'voiceline/{self.id}/midchamber/{quote.name.token}')
