import srctools
from srctools import Keyvalues

from consts import MusicChannel
from transtoken import AppError
from . import ExportData, STEPS, StepResource
from packages import Music, TRANS_OBJ_NOT_FOUND
import utils


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_music_conf(exp_data: ExportData) -> None:
    """Export the selected music."""
    selected: dict[MusicChannel, utils.SpecialID] = exp_data.selected[Music]

    vbsp_config = exp_data.vbsp_conf

    # Store in a list and then raise, so you get errors from all music that failed at once.
    errors: list[AppError] = []

    base_id = selected[MusicChannel.BASE]
    if base_id == utils.ID_EMPTY:
        base_music = None
    else:
        try:
            base_music = exp_data.packset.obj_by_id(Music, base_id)
        except KeyError:
            # Ignore the error here, the for loop below will stop exporting.
            base_music = None
        else:
            vbsp_config += await base_music.config()

    music_conf = Keyvalues('MusicScript', [])
    vbsp_config.append(music_conf)
    to_pack = set()

    for channel, music_id in selected.items():
        if music_id == utils.ID_NONE:
            continue
        try:
            music = exp_data.packset.obj_by_id(Music, music_id)
        except KeyError:
            errors.append(AppError(TRANS_OBJ_NOT_FOUND.format(object="Music", id=music_id)))
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

    if errors:
        raise ExceptionGroup('Music Export', errors)

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
