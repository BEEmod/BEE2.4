from __future__ import annotations
from typing import Final

from collections.abc import AsyncIterator

from srctools import Keyvalues, NoKeyError, logger
import srctools
import trio

from app import lazy_conf
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
# The displayed attributes for the <NONE> quote, IE no quote pack enabled.
NONE_SELECTOR_ATTRS: AttrMap = {
    'CHAR': [TransToken.ui('<Multiverse Cave only>')],
    'TURRET': False,
    'MONITOR': False,
}


class QuotePack(SelPakObject, needs_foreground=True, style_suggest_key='quote'):
    """Adds lists of voice lines which are automatically chosen."""
    export_info: Final[ExportKey[utils.SpecialID]] = ExportKey()

    data: QuoteInfo  # TODO remove

    def __init__(
        self,
        quote_id: str,
        selitem_data: SelitemData,
        config: lazy_conf.LazyConf,
        chars: set[str],
        cave_skin: int | None,
        monitor: Monitor | None,
    ) -> None:
        self.id = quote_id
        self.selitem_data = selitem_data
        # These are combined into the quote info and additional configs.
        self._raw_config = config
        self.cave_skin = cave_skin
        self.chars = chars
        self.monitor = monitor

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

        config = await get_config(
            data.packset,
            data.info,
            'voice',
            pak_id=data.pak_id,
            prop_name='file',
        )
        result = cls(data.id, selitem_data, config, chars, port_skin, monitor)
        # TODO: remove.
        result.data, _ = await result.parse_conf()
        return result

    async def parse_conf(self) -> tuple[QuoteInfo, Keyvalues]:
        """Read and parse the config."""

        # Parse immediately.
        config = await self._raw_config()
        if utils.not_special_id(self.pak_id):
            pak_id = self.pak_id
        else:
            raise ValueError(f'Special package ID provided? {self.pak_id!r}:{self.id!r}')

        # If multiple exist from different definitions, merge.
        config.merge_children('Quotes')
        try:
            quotes_kv = config.find_key('Quotes')
        except NoKeyError:
            raise AppError(TransToken.untranslated(
                'No "Quotes" key in config for quote pack {id}!'
            ).format(id=self.id)) from None
        else:
            del config['Quotes']

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
            with logger.context(self.id):
                group = Group.parse(pak_id, group_kv)
            if group.id in groups:
                groups[group.id] += group
            else:
                groups[group.id] = group

        with logger.context(f'{self.id} - Midchamber'):
            for mid_kv in quotes_kv.find_all('Midchamber', 'Quote'):
                midchamber.append(Quote.parse(pak_id, mid_kv, True))

        for event_kv in quotes_kv.find_all('QuoteEvents', 'Event'):
            event = QuoteEvent.parse(event_kv)
            if event.id in events:
                LOGGER.warning(
                    'Duplicate QuoteEvent "{}" for quote pack {}',
                    event.id, self.id
                )
            events[event.id] = event

        response_dings = use_dings
        used_ids = set()

        for resp_kv in quotes_kv.find_children('CoopResponses'):
            try:
                resp = RESPONSE_NAMES[resp_kv.name]
            except KeyError:
                raise AppError(TransToken.untranslated(
                    'Invalid response kind "{name}" in config for quote pack {id}!'
                ).format(name=resp_kv.real_name, id=self.id)) from None
            response_dings = resp_kv.bool('use_dings', response_dings)

            lines = responses.setdefault(resp, [])
            with logger.context(repr(resp)):
                for line_kv in resp_kv:
                    if line_kv.name.startswith('line'):
                        lines.append(line := Line.parse(pak_id, line_kv, False))
                        if line.id in used_ids:
                            LOGGER.warning(
                                'Quote Pack "{}" has duplicate response line ID "{}"',
                                self.id, line.id
                            )
                        used_ids.add(line.id)

        data = QuoteInfo(
            id=self.id,
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

            chars=self.chars,
            cave_skin=self.cave_skin,
            monitor=self.monitor,
        )
        set_cond_source(config, f'QuotePack <{self.id}>')
        return data, config

    def add_over(self, override: QuotePack) -> None:
        """Add the additional lines to ourselves."""
        self.selitem_data += override.selitem_data
        self._raw_config = lazy_conf.concat(self._raw_config, override._raw_config)

        if self.cave_skin is None:
            self.cave_skin = override.cave_skin

        if self.monitor is None:
            self.monitor = override.monitor

    def __repr__(self) -> str:
        return f'<Voice:{self.id}>'

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """If dev mode is enabled for any quote packs, write their configs out."""
        await trio.lowlevel.checkpoint()
        async with trio.open_nursery() as nursery:
            for quote in packset.all_obj(QuotePack):
                await trio.lowlevel.checkpoint()
                if utils.not_special_id(quote.pak_id):
                    if packset.packages[quote.pak_id].is_dev():
                        nursery.start_soon(quote.parse_conf)

    async def iter_trans_tokens(self) -> AsyncIterator[TransTokenSource]:
        """Yield all translation tokens in this voice pack."""
        async for tok in self.selitem_data.iter_trans_tokens(f'voiceline/{self.id}'):
            yield tok
        data, _ = await self.parse_conf()
        for group in data.groups.values():
            yield group.name, f'voiceline/{self.id}/{group.id}.name'
            yield group.desc, f'voiceline/{self.id}/{group.id}.desc'
            for quote in group.quotes:
                for tok in quote.iter_trans_tokens(f'voiceline/{self.id}/{group.id}'):
                    yield tok
        for resp, lines in data.responses.items():
            for line in lines:
                for tok in line.iter_trans_tokens(f'voiceline/{self.id}/responses'):
                    yield tok
        for quote in data.midchamber:
            for tok in quote.iter_trans_tokens(f'voiceline/{self.id}/midchamber/{quote.name.token}'):
                yield tok

    @classmethod
    def get_selector_attrs(cls, packset: PackagesSet, voice_id: utils.SpecialID) -> AttrMap:
        """Return the attributes for the selector window."""
        if utils.not_special_id(voice_id):
            voice = packset.obj_by_id(cls, voice_id)
            return {
                'CHAR': voice.chars or {'???'},
                'MONITOR': voice.monitor is not None,
                'TURRET': voice.monitor is not None and voice.monitor.turret_hate,
            }
        else:
            return NONE_SELECTOR_ATTRS
