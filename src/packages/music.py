"""Definitions for background music used in the map."""
from __future__ import annotations
from typing import Final, override

from collections.abc import Awaitable, Callable, Mapping, Iterable, Iterator

from srctools import conv_float
import srctools.logger

import utils
from app import lazy_conf
from consts import MusicChannel
from packages import (
    AttrMap, ExportKey, PackagesSet, PackErrorInfo, SelPakObject, ParseData, SelitemData,
    get_config,
)
from transtoken import TransTokenSource


LOGGER = srctools.logger.get_logger(__name__)


class Music(SelPakObject, needs_foreground=True, style_suggest_key='music'):
    """Allows specifying background music for the map."""
    type ExportInfo = Mapping[MusicChannel, utils.SpecialID]
    export_info: Final[ExportKey[ExportInfo]] = ExportKey()

    def __init__(
        self,
        music_id: str,
        selitem_data: SelitemData,
        sound: Mapping[MusicChannel, list[str]],
        *,
        children: Mapping[MusicChannel, str],
        sample: Mapping[MusicChannel, str],
        volume: Mapping[MusicChannel, float],
        config: lazy_conf.LazyConf = lazy_conf.BLANK,
        inst: str | None = None,
        pack: Iterable[str] = (),
        loop_len: int = 0,
        synch_tbeam: bool = False,
    ) -> None:
        self.id = music_id
        self.config = config
        self.children = children
        self.inst = inst
        self.sound = sound
        self.packfiles = list(pack)
        self.len = loop_len
        self.sample = sample
        self.volume = volume

        self.selitem_data = selitem_data

        self.has_synced_tbeam = synch_tbeam

    @classmethod
    @override
    async def parse(cls, data: ParseData) -> Music:
        """Parse a music definition."""
        selitem_data = SelitemData.parse(data.info, data.pak_id)
        inst = data.info['instance', None]
        sound = data.info.find_key('soundscript', or_blank=True)

        sounds: dict[MusicChannel, list[str]]
        channel_snd: list[str]
        if sound.has_children():
            sounds = {}
            for channel in MusicChannel:
                sounds[channel] = channel_snd = []
                for prop in sound.find_all(channel.value):
                    channel_snd.extend(prop.as_array())

            synch_tbeam = sound.bool('sync_funnel')
        else:
            # Only base.
            sounds = {
                channel: []
                for channel in
                MusicChannel
            }
            sounds[MusicChannel.BASE] = [sound.value]
            synch_tbeam = False

        # The sample music file to play, if found.
        sample_block = data.info.find_key('sample', '')
        if sample_block.has_children():
            sample: dict[MusicChannel, str] = {}
            for channel in MusicChannel:
                chan_sample = sample[channel] = sample_block[channel.value, '']
                if chan_sample:
                    zip_sample = (
                        'resources/music_samp/' +
                        chan_sample
                    )
                    if zip_sample not in data.fsys:
                        LOGGER.warning(
                            'Music sample for <{}>{} does not exist in zip: "{}"',
                            data.id,
                            ('' if
                             channel is MusicChannel.BASE
                             else f' ({channel.value})'),
                            zip_sample,
                        )
                else:
                    sample[channel] = ''
        else:
            # Single value, fill it into all channels.
            sample = dict.fromkeys(MusicChannel, sample_block.value)

        snd_length_str = data.info['loop_len', '0']
        # Allow specifying lengths as [hour:]min:sec.
        if ':' in snd_length_str:
            match snd_length_str.split(':'):
                case [hour, minute, second]:
                    snd_length = srctools.conv_int(second)
                    snd_length += 60 * srctools.conv_int(minute)
                    snd_length += 60 * 60 * srctools.conv_int(hour)
                case [minute, second]:
                    snd_length = 60 * srctools.conv_int(minute) + srctools.conv_int(second)
                case _:
                    raise ValueError(
                        f'Unknown music duration "{snd_length_str}". '
                        'Valid durations are "hours:min:sec", "min:sec" or just seconds.'
                    )
        else:
            snd_length = srctools.conv_int(snd_length_str)

        volume_kv = data.info.find_key('volume', '')
        if volume_kv.has_children():
            volume: dict[MusicChannel, float] = {}
            for channel in MusicChannel:
                volume[channel] = volume_kv.float(channel.value, 1.0)
        else:
            # By default, make gel music quieter.
            conf_volume = conv_float(volume_kv.value, 1.0)
            volume = {
                MusicChannel.BASE: conf_volume,
                MusicChannel.TBEAM: conf_volume,
                MusicChannel.BOUNCE: 0.5 * conf_volume,
                MusicChannel.SPEED: 0.5 * conf_volume,
            }

        children_prop = data.info.find_block('children', or_blank=True)

        music = cls(
            data.id,
            selitem_data,
            sounds,
            children={
                channel: children_prop[channel.value, '']
                for channel in MusicChannel
                if channel is not MusicChannel.BASE
            },
            inst=inst,
            sample=sample,
            config=await get_config(
                data.packset,
                data.info,
                'music',
                pak_id=data.pak_id,
                source=f'Music <{data.id}>',
            ),
            pack=[prop.value for prop in data.info.find_all('pack')],
            loop_len=snd_length,
            synch_tbeam=synch_tbeam,
            volume=volume,
        )
        music._parse_migrations(data)
        return music

    @override
    def add_over(self, override: Music) -> None:
        """Add the additional vbsp_config commands to ourselves."""
        self.config = lazy_conf.concat(self.config, override.config)
        self.selitem_data += override.selitem_data

    def __repr__(self) -> str:
        return f'<Music {self.id}>'

    @override
    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield all translation tokens used by this music."""
        yield from self.selitem_data.iter_trans_tokens('music/' + self.id)

    def has_channel(self, packset: PackagesSet, channel: MusicChannel) -> bool:
        """Check if this track or its children has a channel."""
        if self.sound[channel]:
            return True
        if channel is MusicChannel.BASE and self.inst:
            # The instance provides the base track.
            return True
        if not (child_id := self.children[channel]):
            return False
        try:
            children = packset.obj_by_id(Music, child_id)
        except KeyError:
            return False
        return bool(children.sound[channel])

    def get_suggestion(self, packset: PackagesSet, channel: MusicChannel) -> utils.SpecialID:
        """Get the ID we want to suggest for a channel."""
        child = self
        if self.children[channel]:
            try:
                child = packset.obj_by_id(Music, self.children[channel])
            except KeyError:
                pass
        if child.sound[channel]:
            return utils.obj_id(child.id)
        return utils.ID_NONE

    @classmethod
    @override
    async def post_parse(cls, ctx: PackErrorInfo) -> None:
        """Check children of each music item actually exist.

        This must be done after they all were parsed.
        """
        sounds: dict[frozenset[str], str] = {}

        for music in ctx.packset.all_obj(cls):
            for channel in MusicChannel:
                # Base isn't present in this.
                child_id = music.children.get(channel, '')
                if child_id:
                    try:
                        ctx.packset.obj_by_id(cls, child_id)
                    except KeyError:
                        LOGGER.warning(
                            'Music "{}" refers to nonexistent'
                            ' "{}" for {} channel!',
                            music.id,
                            child_id,
                            channel.value,
                        )
                # Look for tracks used in two items, indicates
                # they should be children of one...
                soundset = frozenset({snd.casefold() for snd in music.sound[channel]})
                if not soundset:
                    continue  # Blank shouldn't match blanks...

                try:
                    other_id = sounds[soundset]
                except KeyError:
                    sounds[soundset] = music.id
                else:
                    if music.id != other_id:
                        LOGGER.warning(
                            'Music tracks were reused in "{}" <> "{}": \n{}',
                            music.id,
                            other_id,
                            sorted(soundset)
                        )

    @classmethod
    def music_for_channel(cls, channel: MusicChannel) -> Callable[[PackagesSet], Awaitable[list[utils.SpecialID]]]:
        """Return a callable which lists all music with the specified channel."""
        async def get_channels(packset: PackagesSet) -> list[utils.SpecialID]:
            """Return music with this channel."""
            await packset.ready(cls).wait()
            ids = [utils.ID_NONE]
            for music in packset.all_obj(cls):
                if music.sound[channel]:
                    ids.append(utils.obj_id(music.id))
                elif channel is MusicChannel.BASE and music.inst:
                    # The instance provides the base track.
                    ids.append(utils.obj_id(music.id))
            return ids
        return get_channels

    @classmethod
    def get_base_selector_attrs(cls, packset: PackagesSet, music_id: utils.SpecialID) -> AttrMap:
        """Indicates what sub-tracks are available."""
        if utils.not_special_id(music_id):
            try:
                music = packset.obj_by_id(cls, music_id)
            except KeyError:
                LOGGER.warning('No music track with ID "{}"!', music_id)
                return {}
            attrs = {
                channel.name: music.has_channel(packset, channel)
                for channel in MusicChannel
                if channel is not MusicChannel.BASE
            }
            attrs['TBEAM_SYNC'] = music.has_synced_tbeam
            return attrs
        else:
            # None, no channels.
            return {}

    @classmethod
    def get_funnel_selector_attrs(cls, packset: PackagesSet, music_id: utils.SpecialID) -> AttrMap:
        """Indicate whether the funnel is synced."""
        if utils.not_special_id(music_id):
            try:
                music = packset.obj_by_id(cls, music_id)
            except KeyError:
                return {}
            return {
                'TBEAM_SYNC': music.has_synced_tbeam,
            }
        else:
            # No music is not synced.
            return {'TBEAM_SYNC': False}

    @classmethod
    def sample_getter_func(cls, channel: MusicChannel) -> Callable[[PackagesSet, utils.SpecialID], str]:
        """Return a function which retrieves the sample sound for the specified channel."""
        def sample_getter(packset: PackagesSet, music_id: utils.SpecialID) -> str:
            """Fetch the sample."""
            if utils.not_special_id(music_id):
                try:
                    music = packset.obj_by_id(cls, music_id)
                except KeyError:
                    return ''
                if music.sample[channel]:
                    return music.sample[channel]
                try:
                    children = packset.obj_by_id(cls, music.children[channel])
                except KeyError:
                    return ''
                return children.sample[channel]
            else:
                # No music, no sample.
                return ''
        return sample_getter
