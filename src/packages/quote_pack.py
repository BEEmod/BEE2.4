from __future__ import annotations
from typing import Final

from collections.abc import Iterator

from srctools import Keyvalues, NoKeyError, logger
import srctools

from packages import (
    AttrMap, ExportKey, PackagesSet, ParseData, SelitemData, SelPakObject,
    get_config, set_cond_source,
)
from quote_pack import (
    RESPONSE_NAMES, Group, Line, Monitor, Quote, QuoteEvent, QuoteInfo,
    Response,
)
from transtoken import AppError, TransToken, TransTokenSource
import utils


LOGGER = logger.get_logger('packages.quote_pack')
NONE_SELECTOR_ATTRS: AttrMap = {
    'CHAR': [TransToken.ui('<Multiverse Cave only>')],
}


class QuotePack(SelPakObject, needs_foreground=True, style_suggest_key='quote'):
    """Adds lists of voice lines which are automatically chosen."""
    export_info: Final[ExportKey[utils.SpecialID]] = ExportKey()

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
    async def parse(cls, data: ParseData) -> QuotePack:
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
            monitor = Monitor.parse(monitor_data)

        # Parse immediately.
        config = await (await get_config(
            data.packset,
            data.info,
            'voice',
            pak_id=data.pak_id,
            prop_name='file',
        ))()

        try:
            quotes_kv = config.find_key('Quotes')
        except NoKeyError:
            raise AppError(TransToken.untranslated(
                'No "Quotes" key in config for quote pack {id}!'
            ).format(id=data.id)) from None
        else:
            del config['Quotes']
        if 'Quotes' in config:
            raise AppError(TransToken.untranslated(
                'Multiple "Quotes" keys found in config for quote pack {id}!'
            ).format(id=data.id))

        base_inst = quotes_kv['base', '']
        position = quotes_kv.vec('quote_loc', -10_000.0, 0.0, 0.0)
        use_dings = quotes_kv.bool('use_dings')
        use_microphones = quotes_kv.bool('UseMicrophones')
        global_bullseye = quotes_kv['bullseye', '']
        groups: dict[str, Group] = {}
        events: dict[str, QuoteEvent] = {}
        responses: dict[Response, list[Line]] = {}
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
                raise AppError(TransToken.untranslated(
                    'Invalid response kind "{name}" in config for quote pack {id}!'
                ).format(name=resp_kv.real_name, id=data.id)) from None
            response_dings = resp_kv.bool('use_dings', response_dings)

            lines = responses.setdefault(resp, [])
            with logger.context(repr(resp)):
                for line_kv in resp_kv:
                    if line_kv.name.startswith('line'):
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

    def add_over(self, override: QuotePack) -> None:
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
        self.data.events.update(override.data.events)

    def __repr__(self) -> str:
        return f'<Voice:{self.id}>'

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Verify no quote packs have duplicate IDs."""
        used: set[str] = set()
        voice: QuotePack
        for voice in packset.all_obj(cls):
            for group in voice.data.groups.values():
                used.clear()
                for quote in group.quotes:
                    for line in quote.lines:
                        if line.id in used:
                            LOGGER.warning(
                                'Quote Pack "{}" has duplicate line ID "{}" in group "{}"!',
                                voice.id, line.id, group.id
                            )
                        used.add(line.id)
            used.clear()
            for quote in voice.data.midchamber:
                for line in quote.lines:
                    if line.id in used:
                        LOGGER.warning(
                            'Quote Pack "{}" has duplicate midchamber line ID "{}"',
                            voice.id, line.id,
                        )
                    used.add(line.id)
            used.clear()
            for resp in voice.data.responses.values():
                for line in resp:
                    if line.id in used:
                        LOGGER.warning(
                            'Quote Pack "{}" has duplicate response line ID "{}"',
                            voice.id, line.id,
                        )
                    used.add(line.id)

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

    @classmethod
    def get_selector_attrs(cls, packset: PackagesSet, voice_id: utils.SpecialID) -> AttrMap:
        """Return the attributes for the selector window."""
        if utils.not_special_id(voice_id):
            voice = packset.obj_by_id(cls, voice_id)
            return {
                'CHAR': voice.data.chars or {'???'},
                'MONITOR': voice.data.monitor is not None,
                'TURRET': voice.data.monitor is not None and voice.data.monitor.turret_hate,
            }
        else:
            return NONE_SELECTOR_ATTRS
