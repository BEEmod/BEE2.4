"""This module maintains a copy of all the instances defined in editoritems.

This way VBSP_config files can generically refer to items, and work in
multiple styles.
"""
import logging
import re
from collections import defaultdict
from functools import lru_cache

import editoritems
import srctools.logger

from typing import (
    Callable, Optional, Union,
    List, Dict, Tuple, TypeVar, Iterable, overload,
)
import corridor
import user_errors

LOGGER = srctools.logger.get_logger(__name__)

# The list of instances each item uses.
INSTANCE_FILES: Dict[str, List[str]] = {}

# Item ID and index/special name for instances set in editoritems.
# Note this is imperfect - two items could reuse the same instance.
ITEM_FOR_FILE: Dict[str, Tuple[str, Union[int, str]]] = {}

_RE_DEFS = re.compile(r'\s* (\[ [^][]+] | < [^<>]+ >) \s* ,? \s*', re.VERBOSE)
_RE_SUBITEMS = re.compile(r'''
    \s*<
    \s*([^:]+)
    \s*(?:
    : \s*
    ([^>:]+)
    )?
    \s*>\s*
''', re.VERBOSE)

# A dict holding dicts of additional custom instance names - used to define
# names in conditions or BEE2-added features.
CUST_INST_FILES: Dict[str, Dict[str, str]] = defaultdict(dict)

# Special names for some specific instances - those which have special
# functionality which can't be used in custom items like entry/exit doors,
# or indicator panels.
SPECIAL_INST: Dict[str, str] = {
    # Glass only generates borders for genuine ITEM_BARRIER items,
    # so it's possible to define special names.
    'glass_128':                 '<ITEM_BARRIER:0>',
    'glass_left_corner':         '<ITEM_BARRIER:1>',
    'glass_left_straight':       '<ITEM_BARRIER:2>',
    'glass_left_short':          '<ITEM_BARRIER:3>',
    'glass_left_convex_corner':  '<ITEM_BARRIER:4>',
    'glass_right_corner':        '<ITEM_BARRIER:5>',
    'glass_right_straight':      '<ITEM_BARRIER:6>',
    'glass_right_short':         '<ITEM_BARRIER:7>',
    'glass_right_convex_corner': '<ITEM_BARRIER:8>',
    'glass_frames':              '<ITEM_BARRIER:1,2,3,4,5,6,7,8>',

    'glass_corner':         '<ITEM_BARRIER:1,5>',
    'glass_straight':       '<ITEM_BARRIER:2,6>',
    'glass_short':          '<ITEM_BARRIER:3,7>',
    'glass_convex_corner':  '<ITEM_BARRIER:4,8>',

    'coopExit':         '<ITEM_COOP_ENTRY_DOOR:3>',
    'coopEntry':        '<ITEM_COOP_ENTRY_DOOR:0>',
    'spExit':           '<ITEM_ENTRY_DOOR:10>',
    'spEntry':          '<ITEM_ENTRY_DOOR:9>',

    'elevatorEntry':    '<ITEM_ENTRY_DOOR:9>',
    'elevatorExit':     '<ITEM_ENTRY_DOOR:10>',

    'spExitCorr':       '<ITEM_EXIT_DOOR:0,1,2,3>',
    'spExitCorr1':      '<ITEM_EXIT_DOOR:0>',
    'spExitCorr2':      '<ITEM_EXIT_DOOR:1>',
    'spExitCorr3':      '<ITEM_EXIT_DOOR:2>',
    'spExitCorr4':      '<ITEM_EXIT_DOOR:3>',

    'spEntryCorr':      '<ITEM_ENTRY_DOOR:0,1,2,3,4,5,6>',
    'spEntryCorr1':     '<ITEM_ENTRY_DOOR:0>',
    'spEntryCorr2':     '<ITEM_ENTRY_DOOR:1>',
    'spEntryCorr3':     '<ITEM_ENTRY_DOOR:2>',
    'spEntryCorr4':     '<ITEM_ENTRY_DOOR:3>',
    'spEntryCorr5':     '<ITEM_ENTRY_DOOR:4>',
    'spEntryCorr6':     '<ITEM_ENTRY_DOOR:5>',
    'spEntryCorr7':     '<ITEM_ENTRY_DOOR:6>',

    'coopCorr':     '<ITEM_COOP_EXIT_DOOR:0,1,2,3>',
    'coopCorr1':    '<ITEM_COOP_EXIT_DOOR:0>',
    'coopCorr2':    '<ITEM_COOP_EXIT_DOOR:1>',
    'coopCorr3':    '<ITEM_COOP_EXIT_DOOR:2>',
    'coopCorr4':    '<ITEM_COOP_EXIT_DOOR:3>',

    'indToggle':    '<ITEM_INDICATOR_TOGGLE>',
    # Although unused by default, editoritems allows having different instances
    # for toggle/timer panels:
    'indPanCheck':  '<ITEM_INDICATOR_PANEL>',
    'indPanTimer':  '<ITEM_INDICATOR_PANEL_TIMER>',
    'indPan': '<ITEM_INDICATOR_PANEL>, <ITEM_INDICATOR_PANEL_TIMER>',

    # The values in ITEM_EXIT_DOOR aren't actually used!
    'door_frame_sp': '<ITEM_ENTRY_DOOR:7,8>',
    'white_frame_sp': '<ITEM_ENTRY_DOOR:7>',
    'black_frame_sp': '<ITEM_ENTRY_DOOR:8>',

    # These are though.
    'door_frame_coop': '<ITEM_COOP_EXIT_DOOR:4,5>',
    'white_frame_coop': '<ITEM_COOP_EXIT_DOOR:4>',
    'black_frame_coop': '<ITEM_COOP_EXIT_DOOR:5>',

    # Combinations of above
    'door_frame': '<ITEM_ENTRY_DOOR:7,8>, <ITEM_COOP_EXIT_DOOR:4,5>',
    'white_frame': '<ITEM_ENTRY_DOOR:7>, <ITEM_COOP_EXIT_DOOR:4>',
    'black_frame': '<ITEM_ENTRY_DOOR:8>, <ITEM_COOP_EXIT_DOOR:5>',

    # Arrival_departure_ents is set in both entry doors - it's usually the same
    # though.
    'transitionents': '<ITEM_ENTRY_DOOR:11>, <ITEM_COOP_ENTRY_DOOR:4>',

    # Convenience, both parts of laser items:
    'laserEmitter': '<ITEM_LASER_EMITTER_CENTER>, <ITEM_LASER_EMITTER_OFFSET>',
    'laserCatcher': '<ITEM_LASER_CATCHER_CENTER>, <ITEM_LASER_CATCHER_OFFSET>',
    'laserRelay': '<ITEM_LASER_RELAY_CENTER>, <ITEM_LASER_RELAY_OFFSET>',
}

# The resolved versions of SPECIAL_INST
INST_SPECIAL: Dict[str, List[str]] = {}

# Categories and prefixes for the corridors, so can update the values after
CORR_SPECIALS = [
    (corridor.GameMode.SP, corridor.Direction.ENTRY, 'spentrycorr'),
    (corridor.GameMode.SP, corridor.Direction.EXIT, 'spexitcorr'),
    (corridor.GameMode.COOP, corridor.Direction.ENTRY, 'coopentry'),
    (corridor.GameMode.COOP, corridor.Direction.EXIT, 'coopcorr'),
]

# Give names to reusable instance fields, so you don't need to remember
# indexes
SUBITEMS: Dict[str, Union[int, Tuple[int, ...]]] = {
    # Cube
    'standard': 0,
    'companion': 1,
    'comp': 1,

    'reflect': 2,
    'redirect': 2,
    'reflection': 2,
    'redirection': 2,
    'laser': 2,

    'sphere': 3,
    'edgeless': 3,
    'ball': 3,

    'franken': 4,
    'monster': 4,

    # Button
    'weighted_white': 0,
    'floor_white': 0,
    'weighted_black': 1,
    'floor_black': 1,

    'cube_white': 2,
    'cube_black': 3,

    'sphere_white': 4,
    'sphere_black': 5,
    'ball_white': 4,
    'ball_black': 5,
    'edgeless_white': 4,
    'edgeless_black': 5,

    # Combined button parts
    'btn_weighted': (0, 1),
    'btn_floor': (0, 1),
    'btn_cube': (2, 3),
    'btn_sphere': (4, 5),
    'btn_ball': (4, 5),
    'btn_edgeless': (4, 5),

    'btn_white': (0, 2, 4),
    'btn_black': (1, 3, 5),

    # Track platform
    'track_bottom_grate': 0,
    'track_bottom': 1,
    'track_middle': 2,
    'track_top': 3,
    'track_platform': 4,
    'track_plat': 4,
    'track_platform_oscillate': 5,
    'track_plat_oscil': 5,
    'track_single': 6,

    'track_plats': (4, 5),
    'track_platforms': (4, 5),
    'track_rail': (1, 2, 3, 6),

    # Funnels
    'fun_emitter': 0,
    'fun_white': 1,
    'fun_black': 2,
    'fun_frame': (1, 2),

    # Fizzler
    'fizz_base': 0,
    'fizz_mdl': 1,
    'fizz_model': 1,
}

SPECIAL_INST_FOLDED = {
    key.casefold(): value
    for key, value in
    SPECIAL_INST.items()
}


def load_conf(items: Iterable[editoritems.Item]) -> None:
    """Read the config and build our dictionaries."""
    cust_instances: dict[str, str]
    EMPTY = editoritems.FSPath()
    for item in items:
        # Extra definitions: key -> filename.
        # Make sure to do this first, so numbered instances are set in
        # ITEM_FOR_FILE.
        if item.cust_instances:
            CUST_INST_FILES[item.id.casefold()] = cust_instances = {}
            for name, file in item.cust_instances.items():
                cust_instances[name] = folded = str(file).casefold()
                ITEM_FOR_FILE[folded] = (item.id, name)

        # Normal instances: index -> filename
        INSTANCE_FILES[item.id.casefold()] = [
            '' if inst.inst == EMPTY else str(inst.inst).casefold()
            for inst in item.instances
        ]
        for ind, inst in enumerate(item.instances):
            fname = str(inst.inst).casefold()
            # Not real instances.
            if fname != '.' and not fname.startswith('instances/bee2_corridor/'):
                ITEM_FOR_FILE[fname] = (item.id, ind)

    INST_SPECIAL.clear()
    INST_SPECIAL.update({
        key.casefold(): resolve(val_string, silent=True)
        for key, val_string in
        SPECIAL_INST.items()
    })


def set_chosen_corridor(
    sel_mode: corridor.GameMode,
    selected: Dict[corridor.Direction, corridor.Corridor],
) -> None:
    """Alter our stored corridor filenames to include the selected corridor.

    If the corridor isn't present it's forced to [], otherwise it holds the single selected.
    The numbered ones are filled in for those legacy corridors only.
    """
    for mode, direction, prefix in CORR_SPECIALS:
        count = corridor.CORRIDOR_COUNTS[mode, direction]
        item_id = corridor.CORR_TO_ID[mode, direction]
        if mode is sel_mode:
            corr = selected[direction]
            inst = corr.instance.casefold()
            INST_SPECIAL[prefix] = [inst]
            for i in range(1, count + 1):
                INST_SPECIAL[f'{prefix}{i}'] = [inst] if corr.orig_index == i else []
            # Update raw item IDs too. Pretend it's repeated for all.
            ITEM_FOR_FILE[inst] = (item_id, 0)
            INSTANCE_FILES[item_id.casefold()][:count] = [inst] * count
        else:  # Not being used.
            INST_SPECIAL[prefix] = []
            for i in range(1, count + 1):
                INST_SPECIAL[f'{prefix}{i}'] = []
            INSTANCE_FILES[item_id.casefold()][:count] = [''] * count
    # Clear since these were evaluated before.
    _resolve.cache_clear()


def resolve(path: str, silent: bool=False) -> List[str]:
    """Resolve an instance path into the values it refers to.

    Valid paths:
    - "<ITEM_ID>" matches all indexes.
    - "<ITEM_ID:>" gives all indexes and custom extra instances.
    - "<ITEM_ID:1,2,5>": matches the given indexes for that item.
    - "<ITEM_ID:cube_black, cube_white>": the same, with strings for indexes
    - "<ITEM_ID:bee2_value>": Custom extra instances defined in editoritems.
    - "<ITEM_ID:bee2_value, 3, 2, cube_black>": Any combination of the above
    - "[spExitCorridor]": Hardcoded shortcuts for specific items
    - "path/to_instance": A single direct instance path

    This returns a list of instances which match the selector, or an empty list
    if it's invalid. Incorrect [] will raise an exception (since these are
    hardcoded).
    When using <> values, "" filenames will be skipped.
    Multiple paths can be used in the same string (other than raw paths):
    "<ITEM_ID>, [spExitCorridor], <ITEM_2:0>"...

    If silent is True, no error messages will be output (for use with hardcoded
    names).
    """
    if silent:
        # Ignore messages < ERROR (warning and info)
        log_level = LOGGER.level
        LOGGER.setLevel(logging.ERROR)
        try:
            return _resolve(path)
        finally:
            LOGGER.setLevel(log_level)
    else:
        return _resolve(path)

Default_T = TypeVar('Default_T')


@overload
def resolve_one(path, *, error: bool) -> str: ...
@overload
def resolve_one(path, default: Default_T, *, error: bool) -> Union[str, Default_T]: ...
def resolve_one(path, default: Union[str, Default_T]='', *, error: bool) -> Union[str, Default_T]:
    """Resolve a path into one instance.

    If multiple are given, this returns the first.
    If none are found, the default is returned (which may be any value).
    If error is True, an exception will be raised instead.
    """
    instances = resolve(path)
    if not instances:
        if error:
            raise user_errors.UserError(user_errors.TOK_INSTLOC_EMPTY.format(path=path))
        return default
    if len(instances) > 1:
        if error:
            raise user_errors.UserError(
                user_errors.TOK_INSTLOC_MULTIPLE.format(path=path),
                textlist=instances,
            )
        LOGGER.warning('Path "{}" returned multiple instances', path)
    return instances[0]


# Cache the return values, since they're constant.
@lru_cache(maxsize=100)
def _resolve(path: str) -> List[str]:
    """Use a secondary function to allow caching values, while ignoring the
    'silent' parameter.
    """
    groups = _RE_DEFS.findall(path)
    if groups:
        out = []
        for group in groups:
            if group[0] == '<':
                try:
                    item_id, subitems = _RE_SUBITEMS.fullmatch(group).groups()
                except (ValueError, AttributeError):  # None.groups fail
                    LOGGER.warning('Could not parse instance lookup "{}"!', group)
                    return []

                item_id = item_id.casefold()
                try:
                    item_inst = INSTANCE_FILES[item_id]
                except KeyError:
                    LOGGER.warning('"{}" is not a valid item!', item_id)
                    return []
                if subitems:
                    out.extend(get_subitems(subitems, item_inst, item_id))
                else:
                    # It's just the <item_id>, return all the values
                    out.extend(item_inst)

            elif group[0] == '[':
                special_name = group[1:-1].casefold()
                try:
                    out.extend(INST_SPECIAL[special_name])
                except KeyError:
                    LOGGER.warning('"{}" is not a valid instance category!', special_name)
                    continue
            else:
                raise Exception(group)
        # Remove "" from the output.
        return list(filter(None, out))
    else:
        return [path.casefold()]


def get_subitems(comma_list: str, item_inst: List[str], item_id: str) -> List[str]:
    """Pick out the subitems from a list."""
    output: List[Union[str, int]] = []
    for val in comma_list.split(','):
        folded_value = val.strip().casefold()
        if folded_value.startswith('bee2_'):
            # A custom value...
            bee_inst = CUST_INST_FILES[item_id]
            try:
                output.append(bee_inst[folded_value[5:]])
                continue
            except KeyError:
                LOGGER.warning(
                    'Invalid custom instance name - "{}" for '
                    '<{}> (Valid: {!r})',
                    folded_value[5:],
                    item_id,
                    bee_inst,
                )
                continue

        ind = SUBITEMS.get(folded_value, None)

        if ind is None:
            try:
                ind = int(folded_value)
            except ValueError:
                LOGGER.info('--------\nValid subitems:')
                LOGGER.info('\n'.join(
                    ('> ' + k + ' = ' + str(v))
                    for k, v in
                    SUBITEMS.items()
                ))
                LOGGER.info('--------')
                raise Exception(
                    '"' + val + '" is not a valid instance'
                                ' subtype or index!'
                )
        # SUBITEMS has tuple values, which represent multiple sub-items.
        if isinstance(ind, tuple):
            output.extend(ind)
        else:
            output.append(ind)

    # Convert to instance lists
    inst_out = []
    for inst in output:
        # bee_ instance, already evaluated
        if isinstance(inst, str):
            inst_out.append(inst)
            continue

        # Only use if it's actually in range
        if 0 <= inst < len(item_inst):
            # Skip "" instance blocks
            if item_inst[inst] != '':
                inst_out.append(item_inst[inst])
    return inst_out


# Make this publicly accessible.
resolve_cache_info: Callable[[], object] = _resolve.cache_info


def get_cust_inst(item_id: str, inst: str) -> Optional[str]:
    """Get the filename used for a custom instance defined in editoritems.

    This returns None if the given value is not present.
    """
    return CUST_INST_FILES[item_id.casefold()].get(inst.casefold(), None)


def get_special_inst(name: str):
    """Get the instance associated with a "[special]" instance path."""
    try:
        inst = INST_SPECIAL[name.casefold()]
    except KeyError:
        raise KeyError(f"Invalid special instance name! ({name})")

    # The number you'll get is fixed, so it's fine if we return different
    # types.
    # Unpack single instances, since that's what you want most of the
    # time. We only do that if there's no ',' in the <> lookup, so it doesn't
    # affect
    if len(inst) == 1 and ',' not in SPECIAL_INST_FOLDED[name.casefold()]:
        return inst[0]
    elif len(inst) == 0:
        return ()
    else:
        return inst
