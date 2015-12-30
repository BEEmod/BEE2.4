"""Flags related to global properties - stylevars, music, which game, etc."""
import utils

from conditions import make_flag, STYLE_VARS, VOICE_ATTR, OPTIONS


@make_flag('styleVar')
def flag_stylevar(_, flag):
    """Checks if the given Style Var is true.

    Use the NOT flag to invert if needed.
    """
    return STYLE_VARS[flag.value.casefold()]


@make_flag('has')
def flag_voice_has(_, flag):
    """Checks if the given Voice Attribute is present.

    Use the NOT flag to invert if needed.
    """
    return VOICE_ATTR[flag.value.casefold()]


@make_flag('has_music')
def flag_music(_, flag):
    """Checks the selected music ID.

    Use "<NONE>" for no music.
    """
    return OPTIONS['music_id'] == flag.value


@make_flag('Game')
def flag_game(_, flag):
    """Checks which game is being modded.

    Accepts the ffollowing aliases instead of a Steam ID:
     - PORTAL2
     - APTAG
     - ALATAG
     - TAG
     - Aperture Tag
     - TWTM,
     - Thinking With Time Machine
    """
    return OPTIONS['game_id'] == utils.STEAM_IDS.get(
        flag.value.upper(),
        flag.value,
    )


@make_flag('has_char')
def flag_voice_char(_, flag):
    """Checks to see if the given charcter is present in the voice pack.

    "<NONE>" means no voice pack is chosen.
    This is case-insensitive, and allows partial matches - 'Cave' matches
    a voice pack with 'Cave Johnson'.
    """
    targ_char = flag.value.casefold()
    if targ_char == '<none>':
        return OPTIONS['voice_id'] == '<NONE>'
    for char in OPTIONS['voice_char'].split(','):
        if targ_char in char.casefold():
            return True
    return False


@make_flag('HasCavePortrait')
def res_cave_portrait(inst, res):
    """Checks to see if the Cave Portrait option is set for the given

    skin pack.
    """
    import vbsp
    return vbsp.get_opt('cave_port_skin') != ''


@make_flag('ifOption')
def flag_option(_, flag):
    bits = flag.value.split(' ', 1)
    key = bits[0].casefold()
    if key in OPTIONS:
        return OPTIONS[key] == bits[1]
    else:
        return False


@make_flag('ifMode', 'iscoop', 'gamemode')
def flag_game_mode(_, flag):
    """Checks if the game mode is "SP" or "COOP".
    """
    import vbsp
    return vbsp.GAME_MODE.casefold() == flag.value.casefold()


@make_flag('ifPreview', 'preview')
def flag_is_preview(_, flag):
    """Checks if the preview mode status equals the given value.

    If preview mode is enabled, the player will start before the entry
    door, and restart the map after reaching the exit door. If false,
    they start in the elevator.

    Preview mode is always False when publishing.
    """
    import vbsp
    return vbsp.IS_PREVIEW == utils.conv_bool(flag.value, False)