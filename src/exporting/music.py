from typing import Dict, Optional

import srctools
from srctools import Keyvalues

from consts import MusicChannel
from . import ExportData, STEPS, StepResource
from packages import Music


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_music_conf(exp_data: ExportData) -> None:
    """Export the selected music."""
    selected: Dict[MusicChannel, Optional[Music]] = exp_data.selected[Music]

    base_music = selected[MusicChannel.BASE]

    vbsp_config = exp_data.vbsp_conf

    if base_music is not None:
        vbsp_config += await base_music.config()

    music_conf = Keyvalues('MusicScript', [])
    vbsp_config.append(music_conf)
    to_pack = set()

    for channel, music in selected.items():
        if music is None:
            continue

        sounds = music.sound[channel]
        channel_block = Keyvalues(channel.value, [
            Keyvalues('volume', str(music.volume.get(channel, 1.0))),
        ])
        music_conf.append(channel_block)
        if len(sounds) == 1:
            channel_block.append(Keyvalues('sound', sounds[0]))
        else:
            channel_block.append(Keyvalues('sound', [
                Keyvalues('snd', snd)
                for snd in sounds
            ]))

        to_pack.update(music.packfiles)

    # If we need to pack, add the files to be unconditionally
    # packed.
    if to_pack:
        music_conf.append(Keyvalues('pack', [
            Keyvalues('file', filename)
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
