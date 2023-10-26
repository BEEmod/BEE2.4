from typing import Optional, Set, Iterator

import attrs

from transtoken import TransTokenSource
from packages import PackagesSet, PakObject, set_cond_source, ParseData, get_config, SelitemData
from srctools import Angle, Keyvalues, Vec, NoKeyError, logger
import srctools


LOGGER = logger.get_logger('packages.quote_pack')


@attrs.frozen(kw_only=True)
class Monitor:
    """Options required for displaying the character in the monitor screen."""
    studio: str
    studio_actor: str
    cam_loc: Vec
    turret_hate: bool
    interrupt: float
    cam_angle: Angle


class QuotePack(PakObject, needs_foreground=True, style_suggest_key='quote'):
    """Adds lists of voice lines which are automatically chosen."""
    def __init__(
        self,
        quote_id: str,
        selitem_data: SelitemData,
        config: Keyvalues,
        *,
        chars: Optional[Set[str]] = None,
        cave_skin: Optional[int] = None,
        monitor: Optional[Monitor] = None,
    ) -> None:
        self.id = quote_id
        self.selitem_data = selitem_data
        self.cave_skin = cave_skin
        self.config = config
        set_cond_source(config, f'QuotePack <{quote_id}>')
        self.chars = chars or {'??'}
        self.monitor = monitor

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
                cam_angle=Angle(data.info.vec('cam_angles')),
                turret_hate=monitor_data.bool('TurretShoot'),
            )

        config = await get_config(
            data.info,
            'voice',
            pak_id=data.pak_id,
            prop_name='file',
        )()

        return cls(
            data.id,
            selitem_data,
            config,
            chars=chars,
            cave_skin=port_skin,
            monitor=monitor,
            )

    def add_over(self, override: 'QuotePack') -> None:
        """Add the additional lines to ourselves."""
        self.selitem_data += override.selitem_data
        self.config += override.config
        self.config.merge_children(
            'quotes_sp',
            'quotes_coop',
        )
        if self.cave_skin is None:
            self.cave_skin = override.cave_skin

        if self.monitor is None:
            self.monitor = override.monitor

    def __repr__(self) -> str:
        return '<Voice:' + self.id + '>'

    @staticmethod
    def strip_quote_data(kv: Keyvalues, _depth: int = 0) -> Keyvalues:
        """Strip unused property blocks from the config files.

        This removes data like the captions which the compiler doesn't need.
        The returned property tree is a deep-copy of the original.
        """
        children = []
        for sub_prop in kv:
            # Make sure it's in the right nesting depth - tests might
            # have arbitrary props in lower depths...
            if _depth == 3:  # 'Line' blocks
                if sub_prop.name == 'trans':
                    continue
                elif sub_prop.name == 'name' and 'id' in kv:
                    continue  # The name isn't needed if an ID is available
            elif _depth == 2 and sub_prop.name == 'name':
                # In the "quote" section, the name isn't used in the compiler.
                continue

            if sub_prop.has_children():
                children.append(QuotePack.strip_quote_data(sub_prop, _depth + 1))
            else:
                children.append(Keyvalues(sub_prop.real_name, sub_prop.value))
        return Keyvalues(kv.real_name, children)

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Verify no quote packs have duplicate IDs."""

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
        """Yield all translation tokens in this voice pack.

        TODO: Parse out translations in the pack itself.
        """
        return self.selitem_data.iter_trans_tokens(f'voiceline/{self.id}')
