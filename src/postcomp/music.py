"""Generates the soundscript for background music."""
import itertools
from typing import Dict, List
from io import StringIO


from srctools.sndscript import SND_CHARS
from srctools.packlist import PackList, FileType
from srctools.vmf import VMF
from srctools import conv_float
from consts import MusicChannel as Channel
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)

# The starting section defining the name and volume.
# SNDLVL_NONE means it's infinite range.
MUSIC_START = """\
"music.BEE2{name}"
{{
"channel" "CHAN_STATIC"
"soundlevel" "SNDLVL_NONE"
"volume" "{vol}"
"""

# The basic operator stack for music without any additional tracks.
MUSIC_BASE = """\
"soundentry_version" "2"
"operator_stacks"
\t{
\t"update_stack"
\t\t{
\t\t"import_stack" "update_music_stereo"
\t\t"volume_fade_in"
\t\t\t{
\t\t\t"input_max" "0.5"
\t\t\t}
\t\t"volume_fade_out"
\t\t\t{
\t\t\t"input_max" "1.5"
\t\t\t}
"""

# We need to stop the sub-tracks after the main track stops...
MUSIC_END = """\
\t\t}
\t"stop_stack"
\t\t{
\t\t"stop_entry"
\t\t\t{
\t\t\t"operator" "sys_stop_entries"
\t\t\t"input_max_entries" "0"
\t\t\t"match_entity" "false"
\t\t\t"match_substring" "true"
\t\t\t"match_entry" "music.BEE2_"
\t\t\t}
\t\t}
\t}
}
"""

# Operator stacks which enable the given gel types.
MUSIC_GEL_BOUNCE_MAIN = """\

\t\t"import_stack" "p2_update_music_play_gel"
\t\t"gel_play_entry"
\t\t\t{
\t\t\t"entry_name" "music.BEE2_gel_bounce"
\t\t\t}
\t\t"gel_stop_entry"
\t\t\t{
\t\t\t"match_entry" "music.BEE2_gel_bounce"
\t\t\t}
"""

MUSIC_GEL_SPEED_MAIN = """\

\t\t"import_stack" "p2_update_music_play_speed_gel"
\t\t"speed_velocity_trigger"
\t\t\t{
\t\t\t"input2" "250"
\t\t\t}
\t\t"speed_play_entry"
\t\t\t{
\t\t\t"entry_name" "music.BEE2_gel_speed"
\t\t\t}
\t\t"speed_stop_entry"
\t\t\t{
\t\t\t"match_entry" "music.BEE2_gel_speed"
\t\t\t}
"""

MUSIC_FUNNEL_MAIN = """\

\t"import_stack" "p2_update_music_play_tbeam"
\t"play_entry"
\t\t{
\t\t"entry_name" "music.BEE2_funnel"
\t\t}
\t"stop_entry"
\t\t{
\t\t"match_entry" "music.BEE2_funnel"
\t\t}
"""

# If no funnel music is defined but the map has funnels, we want to preserve the base track.
MUSIC_FUNNEL_PRESERVEBASE = """\
\t\t"mixer"
\t\t\t{
\t\t\t"mixgroup" "unduckedMusic"
\t\t\t}
"""

# The gel operator stack syncronises the music with the base track.
MUSIC_GEL_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{{
\t"start_stack"
\t\t{{
\t\t"import_stack" "start_sync_to_entry"
\t\t"elapsed_time"
\t\t\t{{
\t\t\t"entry" "music.BEE2"
\t\t\t}}
\t\t"duration_div"
\t\t\t{{
\t\t\t"input2" "1"
\t\t\t}}
\t\t"div_mult"
\t\t\t{{
\t\t\t"input1" "1.0"
\t\t\t}}
\t\t}}
\t"update_stack"
\t\t{{
\t\t"import_stack" "update_music_stereo"
\t\t"volume_fade_in"
\t\t\t{{
\t\t\t"input_max" "{fadein}"
\t\t\t}}
\t\t"volume_fade_out"
\t\t\t{{
\t\t\t"input_max" "{fadeout}"
\t\t\t}}
\t\t}}
\t}}
}}
"""

# This funnel stack makes it start randomly offset into the music.
MUSIC_FUNNEL_RAND_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{
\t"start_stack"
\t\t{
\t\t"random_offset"
\t\t\t{
\t\t\t"operator" "math_random"
\t\t\t"input_min" "0.0"
\t\t\t"input_max" "126"
\t\t\t}
\t\t"negative_delay"
\t\t\t{
\t\t\t"operator" "math_float"
\t\t\t"apply" "mult"
\t\t\t"input1" "@random_offset.output"
\t\t\t"input2" "-1.0"
\t\t\t}
\t\t"delay_output"
\t\t\t{
\t\t\t"operator" "sys_output"
\t\t\t"input_float" "@negative_delay.output"
\t\t\t"output" "delay"
\t\t\t}
\t\t}
"""

# This funnel stack makes it synchronise with the main track.
MUSIC_FUNNEL_SYNC_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{
\t"start_stack"
\t\t{
\t\t"import_stack" "start_sync_to_entry"
\t\t"elapsed_time"
\t\t\t{
\t\t\t"entry" "music.BEE2"
\t\t\t}
\t\t"duration_div"
\t\t\t{
\t\t\t"input2" "1"
\t\t\t}
\t\t"div_mult"
\t\t\t{
\t\t\t"input1" "1.0"
\t\t\t}
\t\t}
"""

# Both funnel versions share the same update stack.
MUSIC_FUNNEL_UPDATE_STACK = """\
\t"update_stack"
\t\t{
\t\t"import_stack" "update_music_stereo"
\t\t"mixer"
\t\t\t{
\t\t\t"mixgroup" "unduckedMusic"
\t\t\t}
\t\t"volume_fade_in"
\t\t\t{
\t\t\t"input_max" "3.0"
\t\t\t"input_map_min" "0.05"
\t\t\t}
\t\t"volume_fade_out"
\t\t\t{
\t\t\t"input_max" "0.75"
\t\t\t"input_map_min" "0.05"
\t\t\t}
\t\t"volume_lfo_time_scale"
\t\t\t{
\t\t\t"input2" "0.3"
\t\t\t}
\t\t"volume_lfo_scale"
\t\t\t{
\t\t\t"input2" "0.4"
\t\t\t}
\t\t}
\t}
}
"""


def generate(bsp: VMF, pack_list: PackList) -> None:
    """Generate a soundscript file for music."""
    # We also pack the filenames used for the tracks - that way funnel etc
    # only get packed when needed. Stock sounds are in VPKS or in aperturetag/,
    # we don't check there.
    tracks: Dict[Channel, List[str]] = {}
    volume: Dict[Channel, float] = dict.fromkeys(Channel, 1.0)
    sync_funnel = False

    for conf_ent in bsp.by_class['bee2_music_channel']:
        conf_ent.remove()
        channel = Channel(conf_ent['channel'].casefold())
        volume[channel] = conv_float(conf_ent['volume'], 1.0)
        if channel is Channel.TBEAM:
            sync_funnel = srctools.conv_bool(conf_ent['sync'])

        track = []
        for i in itertools.count(1):
            snd = conf_ent[f'track{i:02}']
            if not snd:
                break
            track.append(snd)
        if track:
            tracks[channel] = track

    if not tracks:
        return  # No music.

    file = StringIO()
    LOGGER.info('Volume: {}', volume)

    # Write the base music track
    if Channel.BASE in tracks:
        file.write(MUSIC_START.format(name='', vol=volume[Channel.BASE]))
        write_sound(file, tracks[Channel.BASE], pack_list, snd_prefix='#*')
    else:
        # It's not present, we need a sound to have the soundscript operating though.
        file.write(MUSIC_START.format(name='', vol='0.01'))
        write_sound(file, ['BEE2/silent_lp.wav'], pack_list, snd_prefix='')
        # Don't sync to a 2-second sound.
        sync_funnel = False

    file.write(MUSIC_BASE)
    # The 'soundoperators' section is still open now.

    # Add the operators to play the auxiliary sounds..
    if Channel.TBEAM in tracks:
        file.write(MUSIC_FUNNEL_MAIN)
    elif 'prop_tractor_beam' in bsp.by_class:
        # We have no funnel music, but we do have a funnel. Force the base track to continue playing.
        file.write(MUSIC_FUNNEL_PRESERVEBASE)

    if Channel.BOUNCE in tracks:
        file.write(MUSIC_GEL_BOUNCE_MAIN)
    if Channel.SPEED in tracks:
        file.write(MUSIC_GEL_SPEED_MAIN)

    # End the main sound block
    file.write(MUSIC_END)

    if Channel.TBEAM in tracks:
        # Write the 'music.BEE2_funnel' sound entry
        file.write('\n')
        file.write(MUSIC_START.format(name='_funnel', vol=volume[Channel.TBEAM]))
        write_sound(file, tracks[Channel.TBEAM], pack_list)
        # Some tracks want the funnel music to sync with the normal
        # track, others randomly choose a start.
        file.write(
            MUSIC_FUNNEL_SYNC_STACK
            if sync_funnel else
            MUSIC_FUNNEL_RAND_STACK
        )
        file.write(MUSIC_FUNNEL_UPDATE_STACK)

    if Channel.BOUNCE in tracks:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_bounce', vol=volume[Channel.BOUNCE]))
        write_sound(file, tracks[Channel.BOUNCE], pack_list)
        # Fade in fast (we never get false positives, but fade out slow
        # since this disables when falling back..
        file.write(MUSIC_GEL_STACK.format(fadein=0.25, fadeout=1.5))

    if Channel.SPEED in tracks:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_speed', vol=volume[Channel.SPEED]))
        write_sound(file, tracks[Channel.SPEED], pack_list)
        # We need to shut off the sound fast, so portals don't confuse it.
        # Fade in slow so that it doesn't make much sound (and also as we get
        # up to speed). We stop almost immediately on gel too.
        file.write(MUSIC_GEL_STACK.format(fadein=0.5, fadeout=0.1))

    pack_list.pack_file(
        'scripts/BEE2_generated_music.txt',
        FileType.SOUNDSCRIPT,
        data=file.getvalue().encode()
    )


def write_sound(
    file: StringIO,
    snds: List[str],
    pack_list: PackList,
    snd_prefix: str = '*',
) -> None:
    """Write either a single sound, or multiple rndsound.

    snd_prefix is the prefix for each filename - *, #, @, etc.
    """
    if len(snds) > 1:
        file.write('"rndwave"\n\t{\n')
        for snd in snds:
            file.write(f'\t"wave" "{snd_prefix}{snd.lstrip(SND_CHARS)}"\n')
            pack_list.pack_file(f'sound/{snd.casefold()}')
        file.write('\t}\n')
    else:
        file.write(f'"wave" "{snd_prefix}{snds[0].lstrip(SND_CHARS)}"\n')
        pack_list.pack_file(f'sound/{snds[0].casefold()}')
