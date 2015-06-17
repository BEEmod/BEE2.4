from functools import lru_cache

from property_parser import Property
import utils
INSTANCE_FILES = {}

# Special names for these specific instances
SPECIAL_INST = {
    # Glass
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

    'coopExit':    '<ITEM_COOP_ENTRY_DOOR:3>',
    'coopEntry':   '<ITEM_COOP_ENTRY_DOOR:0>',
    'spExit':      '<ITEM_ENTRY_DOOR:10>',
    'spEntry':     '<ITEM_ENTRY_DOOR:9>',

    'elevatorEntry':     '<ITEM_ENTRY_DOOR:9>',
    'elevatorExit':      '<ITEM_ENTRY_DOOR:10>',

    'spExitCorr':  '<ITEM_EXIT_DOOR:0,1,2,3>',
    'spEntryCorr': '<ITEM_ENTRY_DOOR:0,1,2,3,4,5,6>',
    'coopCorr':    '<ITEM_COOP_EXIT_DOOR:0,1,2,3>',
    'indToggle':    '<ITEM_INDICATOR_TOGGLE>',
    # although unused, editoritems allows having different instances
    # for toggle/timer panels
    'indPanCheck':  '<ITEM_INDICATOR_PANEL>',
    'indPanTimer':  '<ITEM_INDICATOR_PANEL_TIMER>',
    # 'indpan' is defined below from these two

    'exit_frame': '<ITEM_EXIT_DOOR:4,5>',
    'entry_frame': '<ITEM_ENTRY_DOOR:7,8>',
}

# Gives names to reusable instance fields, so you don't need to remember
# indexes
SUBITEMS = {
    # Cube
    'standard': 0,
    'companion': 1,
    'comp': 1,

    'reflect': 2,
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
    # Without the texture default to the white one.
    'btn_weighted': 0,
    'btn_floor': 0,
    'btn_cube': 2,
    'btn_sphere': 4,
    'btn_ball': 4,
    'btn_edgeless': 4,
}

def load_conf():
    """Read the config and build our dictionaries."""
    global INST_SPECIAL
    with open('bee2/instances.cfg') as f:
        prop_block = Property.parse(
            f, 'bee2/instances.cfg'
        ).find_key('Allinstances')

    for prop in prop_block:
        INSTANCE_FILES[prop.real_name] = [
            inst.value.casefold()
            for inst in
            prop
        ]
    INST_SPECIAL = {
        key.casefold(): resolve(val_string)
        for key, val_string in
        SPECIAL_INST.items()
    }

    INST_SPECIAL['indpan'] = (
        INST_SPECIAL['indpancheck'] +
        INST_SPECIAL['indpantimer']
    )
    INST_SPECIAL['white_frames'] = (
        resolve('<ITEM_ENTRY_DOOR:7>') +
        resolve('<ITEM_EXIT_DOOR:4>')
    )
    INST_SPECIAL['black_frames'] = (
        resolve('<ITEM_ENTRY_DOOR:8>') +
        resolve('<ITEM_EXIT_DOOR:5>')
    )

@lru_cache()
def resolve(path) -> list:
    """Replace an instance path with the values it refers to.

    Valid paths:
    - "<ITEM_ID:1,2,5>": matches the given indexes for that item.
    - "<ITEM_ID:cube_black, cube_white>": the same, with strings for indexes
    - "[spExitCorridor]": Hardcoded shortcuts for specific items

    This returns a list of instances which match the selector.
    """

    if path.startswith('<') and path.endswith('>'):
        path = path[1:-1]
        if ':' in path:  # We have a set of subitems to parse
            item, subitem = path.split(':')
            try:
                item_values = INSTANCE_FILES[item]
            except KeyError:
                utils.con_log(
                    '"{}" not a valid item!'.format(item)
                )
                return []
            out = []
            for val in subitem.split(','):
                ind = SUBITEMS.get(val.strip().casefold(), None)
                if ind is None:
                    ind = int(val.strip())
                # Only add if it's actually in range
                if 0 <= ind < len(item_values):
                    out.append(item_values[ind])
            return out
        else:
            try:
                return INSTANCE_FILES[path]
            except KeyError:
                utils.con_log(
                    '"{}" not a valid item!'.format(path)
                )
                return []
    elif path.startswith('[') and path.endswith(']'):
        path = path[1:-1].casefold()
        try:
            return INST_SPECIAL[path]
        except KeyError:
            utils.con_log('"{}" not a valid instance category!'.format(path))
            return []
    else:  # Just a normal path
        return [path.casefold()]