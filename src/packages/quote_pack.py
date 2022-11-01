import shutil
from typing import Optional, Set, Iterator

import srctools
import utils
from localisation import TransTokenSource
from packages import (
    PackagesSet, PakObject, set_cond_source, ParseData,
    get_config, ExportData, LOGGER, SelitemData,
)
from srctools import Property, Vec, NoKeyError


class QuotePack(PakObject, needs_foreground=True):
    """Adds lists of voice lines which are automatically chosen."""
    def __init__(
        self,
        quote_id,
        selitem_data: 'SelitemData',
        config: Property,
        chars: Optional[Set[str]]=None,
        skin: Optional[int]=None,
        studio: str=None,
        studio_actor: str='',
        cam_loc: Vec=None,
        turret_hate: bool=False,
        interrupt: float=0.0,
        cam_pitch: float=0.0,
        cam_yaw: float=0.0,
    ) -> None:
        self.id = quote_id
        self.selitem_data = selitem_data
        self.cave_skin = skin
        self.config = config
        set_cond_source(config, 'QuotePack <{}>'.format(quote_id))
        self.chars = chars or {'??'}
        self.studio = studio
        self.studio_actor = studio_actor
        self.cam_loc = cam_loc
        self.inter_chance = interrupt
        self.cam_pitch = cam_pitch
        self.cam_yaw = cam_yaw
        self.turret_hate = turret_hate

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
        port_skin = srctools.conv_int(data.info['caveSkin', None], None)

        try:
            monitor_data = data.info.find_key('monitor')
        except NoKeyError:
            mon_studio = mon_cam_loc = None
            mon_interrupt = mon_cam_pitch = mon_cam_yaw = 0.0
            mon_studio_actor = ''
            turret_hate = False
        else:
            mon_studio = monitor_data['studio']
            mon_studio_actor = monitor_data['studio_actor', '']
            mon_interrupt = monitor_data.float('interrupt_chance', 0)
            mon_cam_loc = monitor_data.vec('Cam_loc')
            mon_cam_pitch, mon_cam_yaw, _ = monitor_data.vec('Cam_angles')
            turret_hate = monitor_data.bool('TurretShoot')

        config = get_config(
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
            skin=port_skin,
            studio=mon_studio,
            studio_actor=mon_studio_actor,
            interrupt=mon_interrupt,
            cam_loc=mon_cam_loc,
            cam_pitch=mon_cam_pitch,
            cam_yaw=mon_cam_yaw,
            turret_hate=turret_hate,
            )

    def add_over(self, override: 'QuotePack'):
        """Add the additional lines to ourselves."""
        self.selitem_data += override.selitem_data
        self.config += override.config
        self.config.merge_children(
            'quotes_sp',
            'quotes_coop',
        )
        if self.cave_skin is None:
            self.cave_skin = override.cave_skin

        if self.studio is None:
            self.studio = override.studio
            self.studio_actor = override.studio_actor
            self.cam_loc = override.cam_loc
            self.inter_chance = override.inter_chance
            self.cam_pitch = override.cam_pitch
            self.cam_yaw = override.cam_yaw
            self.turret_hate = override.turret_hate

    def __repr__(self) -> str:
        return '<Voice:' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export the quotepack."""
        if exp_data.selected is None:
            return  # No quote pack!

        try:
            voice = QuotePack.by_id(exp_data.selected)  # type: QuotePack
        except KeyError:
            raise Exception(
                "Selected voice ({}) doesn't exist?".format(exp_data.selected)
            ) from None

        vbsp_config = exp_data.vbsp_conf  # type: Property

        # We want to strip 'trans' sections from the voice pack, since
        # they're not useful.
        for prop in voice.config:
            if prop.name == 'quotes':
                vbsp_config.append(QuotePack.strip_quote_data(prop))
            else:
                vbsp_config.append(prop.copy())

        # Set values in vbsp_config, so flags can determine which voiceline
        # is selected.
        options = vbsp_config.ensure_exists('Options')

        options['voice_pack'] = voice.id
        options['voice_char'] = ','.join(voice.chars)

        if voice.cave_skin is not None:
            options['cave_port_skin'] = str(voice.cave_skin)

        if voice.studio is not None:
            options['voice_studio_inst'] = voice.studio
            options['voice_studio_actor'] = voice.studio_actor
            options['voice_studio_inter_chance'] = str(voice.inter_chance)
            options['voice_studio_cam_loc'] = voice.cam_loc.join(' ')
            options['voice_studio_cam_pitch'] = str(voice.cam_pitch)
            options['voice_studio_cam_yaw'] = str(voice.cam_yaw)
            options['voice_studio_should_shoot'] = srctools.bool_as_int(voice.turret_hate)

        # Copy the config files for this voiceline..
        for prefix, pretty in [
                ('', 'normal'),
                ('mid_', 'MidChamber'),
                ('resp_', 'Responses')]:
            path = utils.conf_location('config/voice/') / (prefix.upper() + voice.id + '.cfg')
            LOGGER.info('Voice conf path: {}', path)
            if path.is_file():
                shutil.copy(
                    str(path),
                    exp_data.game.abs_path(
                        'bin/bee2/{}voice.cfg'.format(prefix)
                    )
                )
                LOGGER.info('Written "{}voice.cfg"', prefix)
            else:
                LOGGER.info('No {} voice config!', pretty)

    @staticmethod
    def strip_quote_data(prop: Property, _depth=0) -> Property:
        """Strip unused property blocks from the config files.

        This removes data like the captions which the compiler doesn't need.
        The returned property tree is a deep-copy of the original.
        """
        children = []
        for sub_prop in prop:
            # Make sure it's in the right nesting depth - flags might
            # have arbitrary props in lower depths..
            if _depth == 3:  # 'Line' blocks
                if sub_prop.name == 'trans':
                    continue
                elif sub_prop.name == 'name' and 'id' in prop:
                    continue  # The name isn't needed if an ID is available
            elif _depth == 2 and sub_prop.name == 'name':
                # In the "quote" section, the name isn't used in the compiler.
                continue

            if sub_prop.has_children():
                children.append(QuotePack.strip_quote_data(sub_prop, _depth + 1))
            else:
                children.append(Property(sub_prop.real_name, sub_prop.value))
        return Property(prop.real_name, children)

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Verify no quote packs have duplicate IDs."""

        def iter_lines(conf: Property) -> Iterator[Property]:
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
