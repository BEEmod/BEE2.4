"""Definitions for background music used in the map."""
from __future__ import annotations
from collections.abc import Iterable
from typing import Iterator

from srctools import Property
import srctools.logger

from consts import MusicChannel
from app import lazy_conf
from localisation import TransTokenSource
from packages import PackagesSet, PakObject, ParseData, SelitemData, get_config, ExportData


LOGGER = srctools.logger.get_logger(__name__)


class Music(PakObject, needs_foreground=True):
    """Allows specifying background music for the map."""
    def __init__(
        self,
        music_id,
        selitem_data: SelitemData,
        sound: dict[MusicChannel, list[str]],
        children: dict[MusicChannel, str],
        config: lazy_conf.LazyConf = lazy_conf.BLANK,
        inst: str | None = None,
        sample: dict[MusicChannel, str | None] = None,
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

        self.selitem_data = selitem_data

        self.has_synced_tbeam = synch_tbeam

    @classmethod
    async def parse(cls, data: ParseData):
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
            sample: dict[MusicChannel, str | None] = {}
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
                    sample[channel] = None
        else:
            # Single value, fill it into all channels.
            sample = {
                channel: sample_block.value
                for channel in MusicChannel
            }

        snd_length_str = data.info['loop_len', '0']
        # Allow specifying lengths as [hour:]min:sec.
        if ':' in snd_length_str:
            parts = snd_length_str.split(':')
            if len(parts) == 3:
                hour, minute, second = parts
                snd_length = srctools.conv_int(second)
                snd_length += 60 * srctools.conv_int(minute)
                snd_length += 60 * 60 * srctools.conv_int(hour)
            elif len(parts) == 2:
                minute, second = parts
                snd_length = 60 * srctools.conv_int(minute) + srctools.conv_int(second)
            else:
                raise ValueError(
                    f'Unknown music duration "{snd_length_str}". '
                    'Valid durations are "hours:min:sec", "min:sec" or just seconds.'
                )
        else:
            snd_length = srctools.conv_int(snd_length_str)

        children_prop = data.info.find_block('children', or_blank=True)

        return cls(
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
            config=get_config(data.info, 'music', pak_id=data.pak_id, source=f'Music <{data.id}>'),
            pack=[prop.value for prop in data.info.find_all('pack')],
            loop_len=snd_length,
            synch_tbeam=synch_tbeam,
        )

    def add_over(self, override: 'Music') -> None:
        """Add the additional vbsp_config commands to ourselves."""
        self.config = lazy_conf.concat(self.config, override.config)
        self.selitem_data += override.selitem_data

    def __repr__(self) -> str:
        return f'<Music {self.id}>'

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield all translation tokens used by this music."""
        yield from self.selitem_data.iter_trans_tokens('music/' + self.id)

    def provides_channel(self, channel: MusicChannel) -> bool:
        """Check if this music has this channel."""
        if self.sound[channel]:
            return True
        if channel is MusicChannel.BASE and self.inst:
            # The instance provides the base track.
            return True
        return False

    def has_channel(self, packset: PackagesSet, channel: MusicChannel) -> bool:
        """Check if this track or its children has a channel."""
        if self.sound[channel]:
            return True
        if channel is MusicChannel.BASE and self.inst:
            # The instance provides the base track.
            return True
        try:
            children = packset.obj_by_id(Music, self.children[channel])
        except KeyError:
            return False
        return bool(children.sound[channel])

    def get_attrs(self, packset: PackagesSet) -> dict[str, bool]:
        """Generate attributes for SelectorWin."""
        attrs = {
            channel.name: self.has_channel(packset, channel)
            for channel in MusicChannel
            if channel is not MusicChannel.BASE
        }
        attrs['TBEAM_SYNC'] = self.has_synced_tbeam
        return attrs

    def get_suggestion(self, channel: MusicChannel) -> str | None:
        """Get the ID we want to suggest for a channel."""
        try:
            child = Music.by_id(self.children[channel])
        except KeyError:
            child = self
        if child.sound[channel]:
            return child.id
        return None

    def get_sample(self, channel: MusicChannel) -> str | None:
        """Get the path to the sample file, if present."""
        if self.sample[channel]:
            return self.sample[channel]
        try:
            children = Music.by_id(self.children[channel])
        except KeyError:
            return None
        return children.sample[channel]

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected music."""
        selected: dict[MusicChannel, Music | None] = exp_data.selected

        base_music = selected[MusicChannel.BASE]

        vbsp_config = exp_data.vbsp_conf

        if base_music is not None:
            vbsp_config += base_music.config()

        music_conf = Property('MusicScript', [])
        vbsp_config.append(music_conf)
        to_pack = set()

        for channel, music in selected.items():
            if music is None:
                continue

            sounds = music.sound[channel]
            if len(sounds) == 1:
                music_conf.append(Property(channel.value, sounds[0]))
            else:
                music_conf.append(Property(channel.value, [
                    Property('snd', snd)
                    for snd in sounds
                ]))

            to_pack.update(music.packfiles)

        # If we need to pack, add the files to be unconditionally
        # packed.
        if to_pack:
            music_conf.append(Property('pack', [
                Property('file', filename)
                for filename in to_pack
            ]))

        if base_music is not None:
            vbsp_config.set_key(
                ('Options', 'music_looplen'),
                str(base_music.len),
            )

            vbsp_config.set_key(
                ('Options', 'music_sync_tbeam'),
                srctools.bool_as_int(base_music.has_synced_tbeam),
            )
            vbsp_config.set_key(
                ('Options', 'music_instance'),
                base_music.inst or '',
            )

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Check children of each music item actually exist.

        This must be done after they all were parsed.
        """
        sounds: dict[frozenset[str], str] = {}

        for music in packset.all_obj(cls):
            for channel in MusicChannel:
                # Base isn't present in this.
                child_id = music.children.get(channel, '')
                if child_id:
                    try:
                        packset.obj_by_id(cls, child_id)
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
                soundset = frozenset(map(str.casefold, music.sound[channel]))
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
