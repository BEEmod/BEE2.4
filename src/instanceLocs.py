from functools import lru_cache

from property_parser import Property
import utils

LOGGER = utils.getLogger(__name__)

INSTANCE_FILES = {}

# Special names for these specific instances
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

    'coopExit':    '<ITEM_COOP_ENTRY_DOOR:3>',
    'coopEntry':   '<ITEM_COOP_ENTRY_DOOR:0>',
    'spExit':      '<ITEM_ENTRY_DOOR:10>',
    'spEntry':     '<ITEM_ENTRY_DOOR:9>',

    'elevatorEntry':     '<ITEM_ENTRY_DOOR:9>',
    'elevatorExit':      '<ITEM_ENTRY_DOOR:10>',

    'spExitCorr':   '<ITEM_EXIT_DOOR:0,1,2,3>',
    'spExitCorr1':  '<ITEM_EXIT_DOOR:0>',
    'spExitCorr2':  '<ITEM_EXIT_DOOR:1>',
    'spExitCorr3':  '<ITEM_EXIT_DOOR:2>',
    'spExitCorr4':  '<ITEM_EXIT_DOOR:3>',

    'spEntryCorr':  '<ITEM_ENTRY_DOOR:0,1,2,3,4,5,6>',
    'spEntryCorr1': '<ITEM_ENTRY_DOOR:0>',
    'spEntryCorr2': '<ITEM_ENTRY_DOOR:1>',
    'spEntryCorr3': '<ITEM_ENTRY_DOOR:2>',
    'spEntryCorr4': '<ITEM_ENTRY_DOOR:3>',
    'spEntryCorr5': '<ITEM_ENTRY_DOOR:4>',
    'spEntryCorr6': '<ITEM_ENTRY_DOOR:5>',
    'spEntryCorr7': '<ITEM_ENTRY_DOOR:6>',

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

    for prop in prop_block.find_key('Allinstances'):
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
        resolve('<ITEM_LASER_CATCHER_CENTER>') +
        resolve('<ITEM_LASER_CATCHER_OFFSET>')
    )

    INST_SPECIAL['laseremitter'] = (
        resolve('<ITEM_LASER_EMITTER_CENTER>') +
        resolve('<ITEM_LASER_EMITTER_OFFSET>')
    )

    INST_SPECIAL['laserrelay'] = (
        resolve('<ITEM_LASER_RELAY_CENTER>') +
        resolve('<ITEM_LASER_RELAY_OFFSET>')
    )

@lru_cache()
def resolve(path) -> list:
    """Replace an instance path with the values it refers to.

    Valid paths:
    - "<ITEM_ID:1,2,5>": matches the given indexes for that item.
    - "<ITEM_ID:cube_black, cube_white>": the same, with strings for indexes
    - "[spExitCorridor]": Hardcoded shortcuts for specific items

    This returns a list of instances which match the selector.
    When using <> values, the '' path will never be returned.
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
            out = []
            for val in subitem.split(','):
                ind = SUBITEMS.get(val.strip().casefold(), None)
                if ind is None:
                    try:
                        ind = int(val.strip())
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
            return [
                item_values[ind]
                for ind in out

                # Only use if it's actually in range
                if 0 <= ind < len(item_values)
                # Skip "" instance blocks
                if item_values[ind] != ''
            ]
        else:
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