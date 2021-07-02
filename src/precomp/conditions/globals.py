"""Conditions related to global properties - stylevars, music, which game, etc."""

from typing import Collection, Set, Dict, Tuple

from srctools import Vec, Property, Entity, conv_bool, VMF
import srctools.logger

from precomp import options
from precomp.conditions import make_flag, make_result, RES_EXHAUSTED
import vbsp
import utils


LOGGER = srctools.logger.get_logger(__name__, alias='cond.globals')

COND_MOD_NAME = 'Global Properties'


@make_flag('styleVar')
def flag_stylevar(flag: Property) -> bool:
    """Checks if the given Style Var is true.

    Use the NOT flag to invert if needed.
    """
    return vbsp.settings['style_vars'][flag.value.casefold()]


@make_flag('has')
def flag_voice_has(flag: Property) -> bool:
    """Checks if the given Voice Attribute is present.

    Use the NOT flag to invert if needed.
    """
    return vbsp.settings['has_attr'][flag.value.casefold()]


@make_flag('has_music')
def flag_music() -> bool:
    """Checks the selected music ID.

    Use `<NONE>` for no music.
    """
    LOGGER.warning('Checking for selected music is no longer possible!')
    return False


@make_flag('Game')
def flag_game(flag: Property) -> bool:
    """Checks which game is being modded.

    Accepts the following aliases instead of a Steam ID:

    - `PORTAL2`
    - `APTAG`
    - `ALATAG`
    - `TAG`
    - `Aperture Tag`
    - `TWTM`
    - `Thinking With Time Machine`
    - `DEST_AP`
    - `Destroyed Aperture`
    """
    return options.get(str, 'game_id') == utils.STEAM_IDS.get(
        flag.value.upper(),
        flag.value,
    )


@make_flag('has_char')
def flag_voice_char(flag: Property) -> bool:
    """Checks to see if the given charcter is present in the voice pack.

    `<NONE>` means no voice pack is chosen.
    This is case-insensitive, and allows partial matches - `Cave` matches
    a voice pack with `Cave Johnson`.
    """
    targ_char = flag.value.casefold()
    if targ_char == '<none>':
        return options.get(str, 'voice_id') == '<NONE>'
    for char in options.get(str, 'voice_char').split(','):
        if targ_char in char.casefold():
            return True
    return False


@make_flag('HasCavePortrait')
def res_cave_portrait() -> bool:
    """Checks to see if the Cave Portrait option is set for the given voice pack.
    """
    return options.get(int, 'cave_port_skin') is not None


@make_flag('ifMode', 'iscoop', 'gamemode')
def flag_game_mode(flag: Property) -> bool:
    """Checks if the game mode is `SP` or `COOP`.
    """
    import vbsp
    return vbsp.GAME_MODE.casefold() == flag.value.casefold()


@make_flag('ifPreview', 'preview')
def flag_is_preview(flag: Property) -> bool:
    """Checks if the preview mode status equals the given value.

    If preview mode is enabled, the player will start before the entry
    door, and restart the map after reaching the exit door. If `False`,
    they start in the elevator.

    Preview mode is always `False` when publishing.
    """
    return vbsp.IS_PREVIEW == conv_bool(flag.value, False)


@make_flag('hasExitSignage')
def flag_has_exit_signage(vmf: VMF) -> bool:
    """Check to see if either exit sign is present."""
    for over in vmf.by_class['info_overlay']:
        if over['targetname'] in ('exitdoor_arrow', 'exitdoor_stickman'):
            return True
    return False


@make_result('setOption')
def res_set_option(res: Property) -> bool:
    """Set a value in the "options" part of VBSP_config.

    Each child property will be set.
    """
    for opt in res.value:
        options.set_opt(opt.name, opt.value)
    return RES_EXHAUSTED


@make_flag('ItemConfig')
def res_match_item_config(inst: Entity, res: Property) -> bool:
    """Check if an Item Config Panel value matches another value.

    * `ID` is the ID of the group.
    * `Name` is the name of the widget.
    * If `UseTimer` is true, it uses `$timer_delay` to choose the value to use.
    * `Value` is the value to compare to.
    """
    group_id = res['ID']
    wid_name = res['Name'].casefold()
    desired_value = res['Value']
    if res.bool('UseTimer'):
        timer_delay = inst.fixup.int('$timer_delay')
    else:
        timer_delay = None

    conf = options.get_itemconf((group_id, wid_name), None, timer_delay)
    if conf is None:  # Doesn't exist
        return False

    return conf == desired_value


@make_result('styleVar')
def res_set_style_var(res: Property) -> bool:
    """Set Style Vars.

    The value should be a set of `SetTrue` and `SetFalse` keyvalues.
    """
    for opt in res.value:
        if opt.name == 'settrue':
            vbsp.settings['style_vars'][opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            vbsp.settings['style_vars'][opt.value.casefold()] = False
    return RES_EXHAUSTED


@make_result('has')
def res_set_voice_attr(res: Property) -> object:
    """Sets a number of Voice Attributes.

    Each child property will be set. The value is ignored, but must
    be present for syntax reasons.
    """
    if res.has_children():
        for opt in res:
            vbsp.settings['has_attr'][opt.name] = True
    else:
        vbsp.settings['has_attr'][res.value.casefold()] = True
    return RES_EXHAUSTED


# The set is the set of skins to use. If empty, all are used.
CACHED_MODELS: Dict[str, Tuple[Set[int], Entity]] = {}


@make_result('PreCacheModel')
def res_pre_cache_model(vmf: VMF, res: Property) -> None:
    """Precache the given model for switching.

    This places it as a `prop_dynamic_override`.
    """
    if res.has_children():
        model = res['model']
        skins = [int(skin) for skin in res['skinset', ''].split()]
    else:
        model = res.value
        skins = ()
    precache_model(vmf, model, skins)


def precache_model(vmf: VMF, mdl_name: str, skinset: Collection[int]=()) -> None:
    """Precache the given model for switching.

    This places it as a `comp_precache_model`.
    """
    mdl_name = mdl_name.casefold().replace('\\', '/')
    if not mdl_name.startswith('models/'):
        mdl_name = 'models/' + mdl_name
    if not mdl_name.endswith('.mdl'):
        mdl_name += '.mdl'
    if mdl_name in CACHED_MODELS:
        return

    try:
        skins, ent = CACHED_MODELS[mdl_name]
    except KeyError:
        ent = vmf.create_ent(
            classname='comp_precache_model',
            origin=options.get(Vec, 'global_ents_loc'),
            model=mdl_name,
        )
        skins = set(skinset)
        CACHED_MODELS[mdl_name] = skins, ent
    else:
        if skins:  # If empty, it's wildcard so ignore specifics.
            if len(skinset) == 0:
                skins.clear()
            else:
                skins.update(skinset)
    if skins:
        ent['skinset'] = ' '.join(map(str, sorted(skinset)))
    else:
        ent['skinset'] = ''


@make_result('GetItemConfig')
def res_item_config_to_fixup(inst: Entity, res: Property) -> None:
    """Load a config from the item config panel onto a fixup.

    * `ID` is the ID of the group.
    * `Name` is the name of the widget.
    * `resultVar` is the location to store the value into.
    * If `UseTimer` is true, it uses `$timer_delay` to choose the value to use.
    * `Default` is the default value, if the config isn't found.
    """
    group_id = res['ID']
    wid_name = res['Name']
    default = res['default']
    if res.bool('UseTimer'):
        timer_delay = inst.fixup.int('$timer_delay')
    else:
        timer_delay = None

    inst.fixup[res['ResultVar']] = options.get_itemconf(
        (group_id, wid_name),
        default,
        timer_delay,
    )
