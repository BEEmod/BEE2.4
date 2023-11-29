"""Conditions related to global properties - stylevars, music, which game, etc."""
from __future__ import annotations

import re
from typing import Collection, NoReturn

from srctools import Keyvalues, Entity, conv_bool, VMF
import srctools.logger

from precomp import options, conditions
import vbsp
import utils


LOGGER = srctools.logger.get_logger(__name__, alias='cond.globals')
COND_MOD_NAME = 'Global Properties'
# Match 'name[24]'
BRACE_RE = re.compile(r'([^[]+)\[([0-9]+)]')


def global_bool(val: bool) -> bool:
    """Raise Unsatisfiable instead of False.

    These are global checks unrelated to the instance, so if they return False,
    they always will until the global state changes (by some condition succeeding).
    """
    if val:
        return True
    else:
        raise conditions.Unsatisfiable


@conditions.make_test('styleVar')
def check_stylevar(kv: Keyvalues) -> bool:
    """Checks if the given Style Var is true.

    Use the NOT test or "!styleVar" to invert if needed.
    """
    return global_bool(vbsp.settings['style_vars'][kv.value.casefold()])


@conditions.make_test('has')
def check_voice_has(info: conditions.MapInfo, kv: Keyvalues) -> bool:
    """Checks if the given Voice Attribute is present.

    Use the NOT test or "!has" to invert if needed.
    """
    return global_bool(info.has_attr(kv.value))


@conditions.make_test('has_music')
def check_music() -> NoReturn:
    """Checks the selected music ID.

    Use `<NONE>` for no music.
    """
    LOGGER.warning('Checking for selected music is no longer possible!')
    raise conditions.Unsatisfiable


@conditions.make_test('Game')
def check_game(kv: Keyvalues) -> bool:
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
    return global_bool(options.GAME_ID() == utils.STEAM_IDS.get(
        kv.value.upper(),
        kv.value,
    ))


@conditions.make_test('has_char')
def check_voice_char(kv: Keyvalues) -> bool:
    """Checks to see if the given charcter is present in the voice pack.

    `<NONE>` means no voice pack is chosen.
    This is case-insensitive, and allows partial matches - `Cave` matches
    a voice pack with `Cave Johnson`.
    """
    targ_char = kv.value.casefold()
    if targ_char == '<none>':
        return options.VOICE_ID() == '<NONE>'
    for char in options.VOICE_CHAR().split(','):
        if targ_char in char.casefold():
            return True
    raise conditions.Unsatisfiable


@conditions.make_test('HasCavePortrait')
def check_cave_portrait() -> bool:
    """Checks to see if the Cave Portrait option is set for the given voice pack.
    """
    return global_bool(options.CAVE_PORT_SKIN() is not None)


@conditions.make_test('entryCorridor')
def check_entry_corridor(info: conditions.MapInfo, kv: Keyvalues) -> bool:
    """Check the selected entry corridor matches this filename."""
    return global_bool(info.corr_entry.instance.casefold() == kv.value.casefold())


@conditions.make_test('exitCorridor')
def check_exit_corridor(info: conditions.MapInfo, kv: Keyvalues) -> bool:
    """Check the selected exit corridor matches this filename."""
    return global_bool(info.corr_exit.instance.casefold() == kv.value.casefold())


@conditions.make_test('ifMode', 'iscoop', 'gamemode')
def check_game_mode(info: conditions.MapInfo, kv: Keyvalues) -> bool:
    """Checks if the game mode is `SP` or `COOP`.
    """
    mode = kv.value.casefold()
    if mode == 'sp':
        return global_bool(info.is_sp)
    elif mode == 'coop':
        return global_bool(info.is_coop)
    else:
        raise ValueError(f'Unknown gamemode "{kv.value}"!')


@conditions.make_test('ifPreview', 'preview')
def check_is_preview(info: conditions.MapInfo, kv: Keyvalues) -> bool:
    """Checks if the preview mode status equals the given value.

    If preview mode is enabled, the player will start before the entry
    door, and restart the map after reaching the exit door. If `False`,
    they start in the elevator.

    Preview mode is always `False` when publishing.
    """
    expect_preview = conv_bool(kv.value, False)
    return global_bool(expect_preview == (not info.start_at_elevator))


@conditions.make_test('hasExitSignage')
def check_has_exit_signage(vmf: VMF) -> bool:
    """Check to see if either exit sign is present."""
    for over in vmf.by_class['info_overlay']:
        if over['targetname'] in ('exitdoor_arrow', 'exitdoor_stickman'):
            return True
    raise conditions.Unsatisfiable


@conditions.make_result('setOption')
def res_set_option(res: Keyvalues) -> object:
    """Set a value in the "options" part of VBSP_config.

    Each child property will be set.
    """
    for opt in res:
        options.set_opt(opt.name, opt.value)
    return conditions.RES_EXHAUSTED


@conditions.make_result('styleVar')
def res_set_style_var(res: Keyvalues) -> object:
    """Set Style Vars.

    The value should be a set of `SetTrue` and `SetFalse` keyvalues.
    """
    for opt in res:
        if opt.name == 'settrue':
            vbsp.settings['style_vars'][opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            vbsp.settings['style_vars'][opt.value.casefold()] = False
    return conditions.RES_EXHAUSTED


@conditions.make_result('has')
def res_set_voice_attr(info: conditions.MapInfo, res: Keyvalues) -> object:
    """Sets a number of Voice Attributes.

    Each child property will be set. The value is ignored, but must
    be present for syntax reasons.
    """
    if res.has_children():
        for opt in res:
            info.set_attr(opt.name)
    else:
        info.set_attr(res.value)
    return conditions.RES_EXHAUSTED


# The set is the set of skins to use. If empty, all are used.
CACHED_MODELS: dict[str, tuple[set[int], Entity]] = {}


@conditions.make_result('PreCacheModel')
def res_pre_cache_model(vmf: VMF, res: Keyvalues) -> None:
    """Precache the given model for switching.

    This places it as a `prop_dynamic_override`.
    """
    if res.has_children():
        model = res['model']
        skins = [int(skin) for skin in res['skinset', ''].split()]
    else:
        model = res.value
        skins = []
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
            origin=options.GLOBAL_ENTS_LOC(),
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


def get_itemconf(inst: Entity, res: Keyvalues) -> str | None:
    """Implement ItemConfig and GetItemConfig shared logic."""
    timer_delay: int | None

    group_id = res['ID']
    wid_name = inst.fixup.substitute(res['Name']).casefold()

    match = BRACE_RE.match(wid_name)
    if match is not None:  # Match name[timer], after $fixup substitution.
        wid_name, timer_str = match.groups()
        # Should not fail, we matched it above.
        timer_delay = int(timer_str)
    elif res.bool('UseTimer'):
        LOGGER.warning(
            'UseTimer is deprecated, use name = "{}[$timer_delay]".',
            wid_name,
        )
        timer_delay = inst.fixup.int('$timer_delay')
    else:
        timer_delay = None

    return options.get_itemconf((group_id, wid_name), None, timer_delay)


@conditions.make_test('ItemConfig')
def res_match_item_config(inst: Entity, res: Keyvalues) -> bool:
    """Check if an Item Config Panel value matches another value.

    * `ID` is the ID of the group.
    * `Name` is the name of the widget, or "name[timer]" to pick the value for
      timer multi-widgets.
    * If `UseTimer` is true, it uses `$timer_delay` to choose the value to use.
    * `Value` is the value to compare to.
    """
    conf = get_itemconf(inst, res)
    desired_value = res['Value']
    if conf is None:  # Doesn't exist
        return False

    return global_bool(conf == desired_value)


@conditions.make_result('GetItemConfig')
def res_item_config_to_fixup(inst: Entity, res: Keyvalues) -> None:
    """Load a config from the item config panel onto a fixup.

    * `ID` is the ID of the group.
    * `Name` is the name of the widget, or "name[timer]" to pick the value for
      timer multi-widgets.
    * If `UseTimer` is true, it uses `$timer_delay` to choose the value to use.
    * `resultVar` is the location to store the value into.
    * `Default` is the default value, if the config isn't found.
    """
    default = res['default']
    conf = get_itemconf(inst, res)
    inst.fixup[res['ResultVar']] = conf if conf is not None else default
