"""Generates the soundscript for background music."""
from typing import Set
from io import StringIO

from srctools.sndscript import SND_CHARS
from srctools.packlist import PackList
from srctools import Property


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

def generate(data: Property, voice_attr: Set[str], pack_list: PackList) -> bytes:
    """Generate a soundscript file for music."""
    # We also pack the filenames used for the tracks - that way funnel etc
    # only get packed when needed. Stock sounds are in VPKS or in aperturetag/,
    # we don't check there.

    funnel = data.find_key('tbeam', '')
    bounce = data.find_key('bouncegel', '')
    speed = data.find_key('speedgel', '')

    sync_funnel = data.bool('sync_funnel')

    if 'base' not in data:
        base = Property('base', 'bee2/silent_lp.wav')
        # Don't sync to a 2-second sound.
        sync_funnel = False
    else:
        base = data.find_key('base')

    # The sounds must be present, and the items should be in the map.
    has_funnel = funnel.value and (
        'funnel' in voice_attr or
        'excursionfunnel' in voice_attr
    )
    has_bounce = bounce.value and (
        'bouncegel' in voice_attr or
        'bluegel' in voice_attr
    )
    # Speed-gel sounds also play when flinging, so keep it always.

    file = StringIO()

    # Write the base music track
    file.write(MUSIC_START.format(name='', vol='1'))
    write_sound(file, base, pack_list, snd_prefix='#*')
    file.write(MUSIC_BASE)
    # The 'soundoperators' section is still open now.

    # Add the operators to play the auxilluary sounds..
    if has_funnel:
        file.write(MUSIC_FUNNEL_MAIN)
    if has_bounce:
        file.write(MUSIC_GEL_BOUNCE_MAIN)
    if speed.value:
        file.write(MUSIC_GEL_SPEED_MAIN)

    # End the main sound block
    file.write(MUSIC_END)

    if has_funnel:
        # Write the 'music.BEE2_funnel' sound entry
        file.write('\n')
        file.write(MUSIC_START.format(name='_funnel', vol='1'))
        write_sound(file, funnel, pack_list, snd_prefix='*')
        # Some tracks want the funnel music to sync with the normal
        # track, others randomly choose a start.
        file.write(
            MUSIC_FUNNEL_SYNC_STACK
            if sync_funnel else
            MUSIC_FUNNEL_RAND_STACK
        )
        file.write(MUSIC_FUNNEL_UPDATE_STACK)

    if has_bounce:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_bounce', vol='0.5'))
        write_sound(file, bounce, pack_list, snd_prefix='*')
        # Fade in fast (we never get false positives, but fade out slow
        # since this disables when falling back..
        file.write(MUSIC_GEL_STACK.format(fadein=0.25, fadeout=1.5))

    if speed.value:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_speed', vol='0.5'))
        write_sound(file, speed, pack_list, snd_prefix='*')
        # We need to shut off the sound fast, so portals don't confuse it.
        # Fade in slow so it doesn't make much sound (and also as we get
        # up to speed). We stop almost immediately on gel too.
        file.write(MUSIC_GEL_STACK.format(fadein=0.5, fadeout=0.1))

    return file.getvalue().encode()


def write_sound(
    file: StringIO,
    snds: Property,
    pack_list: PackList,
    snd_prefix: str='*',
) -> None:
    """Write either a single sound, or multiple rndsound.

    snd_prefix is the prefix for each filename - *, #, @, etc.
    """
    if snds.has_children():
        file.write('"rndwave"\n\t{\n')
        for snd in snds:
            file.write(
                '\t"wave" "{sndchar}{file}"\n'.format(
                    file=snd.value.lstrip(SND_CHARS),
                    sndchar=snd_prefix,
                )
            )
            pack_list.pack_file('sound/' + snd.value.casefold())
        file.write('\t}\n')
    else:
        file.write(
            '"wave" "{sndchar}{file}"\n'.format(
                file=snds.value.lstrip(SND_CHARS),
                sndchar=snd_prefix,
            )
        )
        pack_list.pack_file('sound/' + snds.value.casefold())
