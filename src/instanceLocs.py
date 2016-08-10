"""This module maintains a copy of all the instances defined in editoritems.

This way VBSP_config files can generically refer to items, and work in
multiple styles.
"""
import logging
from collections import defaultdict
from functools import lru_cache

import utils
from srctools import Property

from typing import Optional, List, Dict

LOGGER = utils.getLogger(__name__)

# The list of instance each item uses.
INSTANCE_FILES = {}

# A dict holding dicts of additional custom instance names - used to define
# names in conditions or BEE2-added features.
CUST_INST_FILES = defaultdict(dict)  # type: Dict[str, Dict[str, str]]

# Special names for some specific instances - those which have special
# functionality which can't be used in custom items like entry/exit doors,
# or indicator panels.
SPECIAL_INST = {
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
    'coopEntryUp':      '<ITEM_COOP_ENTRY_DOOR:bee2_vert_up>',
    'coopEntryDown':    '<ITEM_COOP_ENTRY_DOOR:bee2_vert_down>',
    'spExit':           '<ITEM_ENTRY_DOOR:10>',
    'spEntry':          '<ITEM_ENTRY_DOOR:9>',

    'elevatorEntry':    '<ITEM_ENTRY_DOOR:9>',
    'elevatorExit':     '<ITEM_ENTRY_DOOR:10>',

    'spExitCorr':       '<ITEM_EXIT_DOOR:0,1,2,3>',
    'spExitCorr1':      '<ITEM_EXIT_DOOR:0>',
    'spExitCorr2':      '<ITEM_EXIT_DOOR:1>',
    'spExitCorr3':      '<ITEM_EXIT_DOOR:2>',
    'spExitCorr4':      '<ITEM_EXIT_DOOR:3>',
    'spExitCorrUp':     '<ITEM_EXIT_DOOR:bee2_vert_up>',
    'spExitCorrDown':   '<ITEM_EXIT_DOOR:bee2_vert_down>',

    'spEntryCorr':      '<ITEM_ENTRY_DOOR:0,1,2,3,4,5,6>',
    'spEntryCorr1':     '<ITEM_ENTRY_DOOR:0>',
    'spEntryCorr2':     '<ITEM_ENTRY_DOOR:1>',
    'spEntryCorr3':     '<ITEM_ENTRY_DOOR:2>',
    'spEntryCorr4':     '<ITEM_ENTRY_DOOR:3>',
    'spEntryCorr5':     '<ITEM_ENTRY_DOOR:4>',
    'spEntryCorr6':     '<ITEM_ENTRY_DOOR:5>',
    'spEntryCorr7':     '<ITEM_ENTRY_DOOR:6>',
    'spEntryCorrUp':    '<ITEM_ENTRY_DOOR:bee2_vert_up>',
    'spEntryCorrDown':  '<ITEM_ENTRY_DOOR:bee2_vert_down>',

    'coopCorr':     '<ITEM_COOP_EXIT_DOOR:0,1,2,3>',
    'coopCorr1':    '<ITEM_COOP_EXIT_DOOR:0>',
    'coopCorr2':    '<ITEM_COOP_EXIT_DOOR:1>',
    'coopCorr3':    '<ITEM_COOP_EXIT_DOOR:2>',
    'coopCorr4':    '<ITEM_COOP_EXIT_DOOR:3>',
    'coopCorrUp':   '<ITEM_COOP_EXIT_DOOR:bee2_vert_up>',
    'coopCorrDown': '<ITEM_COOP_EXIT_DOOR:bee2_vert_down>',

    'indToggle':    '<ITEM_INDICATOR_TOGGLE>',
    # Although unused by default, editoritems allows having different instances
    # for toggle/timer panels:
    'indPanCheck':  '<ITEM_INDICATOR_PANEL>',
    'indPanTimer':  '<ITEM_INDICATOR_PANEL_TIMER>',
    # 'indpan' is defined below from these two

    # The values in ITEM_EXIT_DOOR aren't actually used!
    'door_frame_sp': '<ITEM_ENTRY_DOOR:7,8>',
    'white_frame_sp': '<ITEM_ENTRY_DOOR:7>',
    'black_frame_sp': '<ITEM_ENTRY_DOOR:8>',

    # These are though.
    'door_frame_coop': '<ITEM_COOP_EXIT_DOOR:4,5>',
    'white_frame_coop': '<ITEM_COOP_EXIT_DOOR:4>',
    'black_frame_coop': '<ITEM_COOP_EXIT_DOOR:5>',
}

# The resolved versions of SPECIAL_INST
INST_SPECIAL = None  # type: dict

# Gives names to reusable instance fields, so you don't need to remember
# indexes
SUBITEMS = {
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

    # Combined buttom parts
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


def load_conf(prop_block: Property):
    """Read the config and build our dictionaries."""
    global INST_SPECIAL

    for prop in prop_block.find_key('Allinstances', []):
        INSTANCE_FILES[prop.real_name] = [
            inst.value.casefold()
            for inst in
            prop
        ]

    for prop in prop_block.find_key('CustInstances', []):
        CUST_INST_FILES[prop.real_name] = {
            inst.name: inst.value.casefold()
            for inst in
            prop
        }

    INST_SPECIAL = {
        key.casefold(): resolve(val_string, silent=True)
        for key, val_string in
        SPECIAL_INST.items()
    }

    # Several special items which use multiple item types!

    # Checkmark and Timer indicator panels:
    INST_SPECIAL['indpan'] = (
        INST_SPECIAL['indpancheck'] +
        INST_SPECIAL['indpantimer']
    )

    INST_SPECIAL['door_frame'] = (
        INST_SPECIAL['door_frame_sp'] +
        INST_SPECIAL['door_frame_coop']
    )

    INST_SPECIAL['white_frame'] = (
        INST_SPECIAL['white_frame_sp'] +
        INST_SPECIAL['white_frame_coop']
    )

    INST_SPECIAL['black_frame'] = (
        INST_SPECIAL['black_frame_sp'] +
        INST_SPECIAL['black_frame_coop']
    )

    # Arrival_departure_ents is set in both entry doors - it's usually the same
    # though.
    INST_SPECIAL['transitionents'] = (
        resolve('<ITEM_ENTRY_DOOR:11>') +
        resolve('<ITEM_COOP_ENTRY_DOOR:4>')
    )

    # Laser items have the offset and centered item versions.
    INST_SPECIAL['lasercatcher'] = (
        resolve('<ITEM_LASER_CATCHER_CENTER>', silent=True) +
        resolve('<ITEM_LASER_CATCHER_OFFSET>', silent=True)
    )

    INST_SPECIAL['laseremitter'] = (
        resolve('<ITEM_LASER_EMITTER_CENTER>', silent=True) +
        resolve('<ITEM_LASER_EMITTER_OFFSET>', silent=True)
    )

    INST_SPECIAL['laserrelay'] = (
        resolve('<ITEM_LASER_RELAY_CENTER>', silent=True) +
        resolve('<ITEM_LASER_RELAY_OFFSET>', silent=True)
    )

    LOGGER.warning('None in vals: {}', None in INST_SPECIAL.values())


def resolve(path, silent=False) -> List[str]:
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

    If silent is True, no error messages will be output (for use with hardcoded
    names).
    """
    if silent:
        # Ignore messages < ERROR (warning and info)
        LOGGER.setLevel(logging.ERROR)
        val = _resolve(path)
        LOGGER.setLevel(logging.NOTSET)
        return val
    else:
        return _resolve(path)


# Cache the return values, since they're constant.
@lru_cache(maxsize=256)
def _resolve(path):
    """Use a secondary function to allow caching values, while ignoring the
    'silent' parameter.
    """

    if path.startswith('<') and path.endswith('>'):
        path = path[1:-1]
        if ':' in path:  # We have a set of subitems to parse
            item, subitem = path.split(':')
            try:
                item_values = INSTANCE_FILES[item]
            except KeyError:
                LOGGER.warning(
                    '"{}" not a valid item!',
                    item,
                )
                return []
            cust_item_vals = CUST_INST_FILES[item]
            out = []
            if not subitem:
                # <ITEM_ID:> gives all items + subitems...
                return [
                    inst for inst in
                    item_values
                    if inst != ''
                ] + list(CUST_INST_FILES[item].values())
            for val in subitem.split(','):
                folded_value = val.strip().casefold()
                if folded_value.startswith('bee2_'):
                    # A custom value...
                    try:
                        out.append(cust_item_vals[folded_value[5:]])
                        continue
                    except KeyError:
                        LOGGER.warning(
                            'Invalid custom instance name - "{}" for '
                            '<{}> (Valid: {!r})',
                            folded_value[5:],
                            item,
                            cust_item_vals,
                        )
                        return []

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
                # SUBITEMS has tuple values, which represent multiple subitems.
                if isinstance(ind, tuple):
                    out.extend(ind)
                else:
                    out.append(ind)

            # Convert to instance lists
            inst_out = []
            for ind in out:
                if isinstance(ind, str):
                    inst_out.append(ind)
                    continue

                # Only use if it's actually in range
                if 0 <= ind < len(item_values):
                    # Skip "" instance blocks
                    if item_values[ind] != '':
                        inst_out.append(item_values[ind])
            return inst_out
        else:
            # It's just the <item_id>, return all the values
            try:
                # Skip "" instances
                return [
                    inst for inst in
                    INSTANCE_FILES[path]
                    if inst != ''
                    ]
            except KeyError:
                LOGGER.warning(
                    '"{}" not a valid item!',
                    path,
                )
                return []
    elif path.startswith('[') and path.endswith(']'):
        path = path[1:-1].casefold()
        try:
            return INST_SPECIAL[path]
        except KeyError:
            LOGGER.warning('"{}" not a valid instance category!', path)
            return []
    else:  # Just a normal path
        return [path.casefold()]

# Copy over the lru_cache() functions to make them easily acessable.
resolve.cache_info = _resolve.cache_info
resolve.cache_clear = _resolve.cache_clear


def get_cust_inst(item_id: str, inst: str) -> Optional[str]:
    """Get the filename used for a custom instance defined in editoritems.

    This returns None if the given value is not present.
    """
    return CUST_INST_FILES[item_id].get(inst.casefold(), None)


def get_special_inst(name: str):
    """Get the instance associated with a "[special]" instance path."""
    try:
        inst = INST_SPECIAL[name.casefold()]
    except KeyError:
        raise KeyError("Invalid special instance name! ({})".format(name))

    # The number you'll get is fixed, so it's fine if we return different
    # types - unpack single instances, since that's what you want most of the
    # time.
    if len(inst) == 1:
        return inst[0]
    elif len(inst) == 0:
        return None  # No value
    else:
        return inst
