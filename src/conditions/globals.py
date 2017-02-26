"""Flags related to global properties - stylevars, music, which game, etc."""
import utils
import vbsp_options

from srctools import Vec, Property, Entity, conv_bool
from conditions import (
    make_flag, make_result, RES_EXHAUSTED,
)
import vbsp



@make_flag('styleVar')
def flag_stylevar(flag: Property):
    """Checks if the given Style Var is true.

    Use the NOT flag to invert if needed.
    """
    return vbsp.settings['style_vars'][flag.value.casefold()]


@make_flag('has')
def flag_voice_has(flag: Property):
    """Checks if the given Voice Attribute is present.

    Use the NOT flag to invert if needed.
    """
    return vbsp.settings['has_attr'][flag.value.casefold()]


@make_flag('has_music')
def flag_music(flag: Property):
    """Checks the selected music ID.

    Use "<NONE>" for no music.
    """
    return vbsp_options.get(str, 'music_id') == flag.value


@make_flag('Game')
def flag_game(flag: Property):
    """Checks which game is being modded.

    Accepts the following aliases instead of a Steam ID:
     - PORTAL2
     - APTAG
     - ALATAG
     - TAG
     - Aperture Tag
     - TWTM,
     - Thinking With Time Machine
     - DEST_AP
     - Destroyed Aperture
    """
    return vbsp_options.get(str, 'game_id') == utils.STEAM_IDS.get(
        flag.value.upper(),
        flag.value,
    )


@make_flag('has_char')
def flag_voice_char(flag: Property):
    """Checks to see if the given charcter is present in the voice pack.

    "<NONE>" means no voice pack is chosen.
    This is case-insensitive, and allows partial matches - 'Cave' matches
    a voice pack with 'Cave Johnson'.
    """
    targ_char = flag.value.casefold()
    if targ_char == '<none>':
        return vbsp_options.get(str, 'voice_id') == '<NONE>'
    for char in vbsp_options.get(str, 'voice_char').split(','):
        if targ_char in char.casefold():
            return True
    return False


@make_flag('HasCavePortrait')
def res_cave_portrait():
    """Checks to see if the Cave Portrait option is set for the given

    skin pack.
    """
    return vbsp_options.get(int, 'cave_port_skin') is not None


@make_flag('ifMode', 'iscoop', 'gamemode')
def flag_game_mode(flag: Property):
    """Checks if the game mode is "SP" or "COOP".
    """
    import vbsp
    return vbsp.GAME_MODE.casefold() == flag.value.casefold()


@make_flag('ifPreview', 'preview')
def flag_is_preview(flag: Property):
    """Checks if the preview mode status equals the given value.

    If preview mode is enabled, the player will start before the entry
    door, and restart the map after reaching the exit door. If false,
    they start in the elevator.

    Preview mode is always False when publishing.
    """
    import vbsp
    return vbsp.IS_PREVIEW == conv_bool(flag.value, False)


@make_flag('hasExitSignage')
def flag_has_exit_signage():
    """Check to see if either exit sign is present."""
    for over in vbsp.VMF.by_class['info_overlay']:
        if over['targetname'] in ('exitdoor_arrow', 'exitdoor_stickman'):
            return True
    return False


@make_result('styleVar')
def res_set_style_var(res: Property):
    """Set Style Vars.

    The value should be set of "SetTrue" and "SetFalse" keyvalues.
    """
    for opt in res.value:
        if opt.name == 'settrue':
            vbsp.settings['style_vars'][opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            vbsp.settings['style_vars'][opt.value.casefold()] = False
    return RES_EXHAUSTED


@make_result('has')
def res_set_voice_attr(res: Property):
    """Sets a number of Voice Attributes.

        Each child property will be set. The value is ignored, but must
        be present for syntax reasons.
    """
    if res.has_children():
        for opt in res.value:
            vbsp.settings['has_attr'][opt.name] = True
    else:
        vbsp.settings['has_attr'][res.value.casefold()] = 1
    return RES_EXHAUSTED

CACHED_MODELS = set()


@make_result('PreCacheModel')
def res_pre_cache_model(res: Property):
    """Precache the given model for switching.

    This places it as a prop_dynamic_override.
    """
    mdl_name = res.value.casefold()
    if not mdl_name.startswith('models/'):
        mdl_name = 'models/' + mdl_name
    if not mdl_name.endswith('.mdl'):
        mdl_name += '.mdl'

    if mdl_name in CACHED_MODELS:
        return
    CACHED_MODELS.add(mdl_name)
    vbsp.VMF.create_ent(
        classname='prop_dynamic_override',
        targetname='@precache',
        origin=vbsp_options.get(Vec, 'global_pti_ents_loc'),
        model=mdl_name,

        # Disable shadows and similar things, it shouldn't ever be in
        # PVS but we might as well.
        rendermode=10,
        disableshadowdepth=1,
        disableshadows=1,
        solid=0,
        shadowdepthnocache=2,
        spawnflags=256,  # Start with collision off.
    )


@make_result('GetItemConfig')
def res_get_item_config(inst: Entity, res: Property):
    """Load a config from the item config panel onto a fixup.

    ID is the ID of the group. Name is the name of the widget, and resultVar
    is the location to store. If UseTimer is true, it uses $timer_delay to
    choose the value to use. Default is the default value, if the config
    isn't found.
    """
    group_id = res['ID']
    wid_name = res['Name']
    default = res['default']
    if res.bool('UseTimer'):
        timer_delay = inst.fixup.int('$timer_delay')
    else:
        timer_delay = None

    inst.fixup[res['ResultVar']] = vbsp_options.get_itemconf(
        (group_id, wid_name),
        default,
        timer_delay,
    )
