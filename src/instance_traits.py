"""Adds various traits to instances, based on item classes."""
from srctools import Entity
from srctools import VMF
from comp_consts import ItemClass
from conditions import CLASS_FOR_ITEM
from instanceLocs import ITEM_FOR_FILE

import utils

from typing import Optional, Callable, Dict, Set

LOGGER = utils.getLogger(__name__)

# Special case - specific attributes..
ID_ATTRS = {
    'ITEM_PLACEMENT_HELPER': [
        {'placement_helper'},
    ],
    'ITEM_INDICATOR_TOGGLE': [
        {'antline', 'toggle', 'indicator_toggle'},
    ],
    'ITEM_INDICATOR_PANEL': [
        {'antline', 'checkmark', 'indicator_panel'},
    ],
    'ITEM_INDICATOR_PANEL_TIMER': [
        {'antline', 'timer', 'indicator_panel'},
    ],
    'ITEM_POINT_LIGHT': [
        {'ambient_light'},
    ],
    'ITEM_PANEL_ANGLED': [
        {'panel_brush'},
    ],
    'ITEM_PANEL_CLEAR': [
        {'panel_glass'},
    ],
}

CLASS_ATTRS = {
    ItemClass.FLOOR_BUTTON: [
        {'white', 'weighted', 'floor_button'},
        {'black', 'weighted', 'floor_button'},
        {'white', 'btn_cube', 'floor_button'},
        {'black', 'btn_cube', 'floor_button'},
        {'white', 'btn_ball', 'floor_button'},
        {'black', 'btn_ball', 'floor_button'},
    ],
    ItemClass.FUNNEL: [
        {'tbeam_emitter'},
        {'white', 'tbeam_frame'},
        {'black', 'tbeam_frame'},
    ],
    ItemClass.CUBE: [
        {'dropperless', 'cube_standard'},
        {'dropperless', 'cube_companion'},
        {'dropperless', 'cube_reflect'},
        {'dropperless', 'cube_ball'},
        {'dropperless', 'cube_franken'},
    ],
    ItemClass.FIZZLER: [
        {'fizzler', 'fizzler_base'},
        {'fizzler', 'fizzler_model'},
    ],
    ItemClass.TRACK_PLATFORM: [
        {'track_platform', 'plat_bottom_grate'},
        {'track_platform', 'plat_bottom'},
        {'track_platform', 'plat_middle'},
        {'track_platform', 'plat_top'},
        {'track_platform', 'plat_non_osc'},
        {'track_platform', 'plat_osc'},
        {'track_platform', 'plat_single'},
    ],
    ItemClass.GLASS: [
        {'barrier', 'barrier_128'},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_corner'},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_straight'},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_short'},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_convex_corner'},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_corner'},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_straight'},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_short'},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_convex_corner'},
    ],
    ItemClass.DOOR_ENTRY_SP: [
        {'corridor_1', 'entry_corridor', 'sp_corridor'},
        {'corridor_2', 'entry_corridor', 'sp_corridor'},
        {'corridor_3', 'entry_corridor', 'sp_corridor'},
        {'corridor_4', 'entry_corridor', 'sp_corridor'},
        {'corridor_5', 'entry_corridor', 'sp_corridor'},
        {'corridor_6', 'entry_corridor', 'sp_corridor'},
        {'corridor_7', 'entry_corridor', 'sp_corridor'},
        {'corridor_frame', 'entry_corridor', 'sp_corridor', 'white'},
        {'corridor_frame', 'entry_corridor', 'sp_corridor', 'black'},
        {'entry_elevator', 'elevator', 'sp_corridor'},
        {'exit_elevator', 'elevator', 'sp_corridor'},
        {'arrival_departure_transition'},
    ],
    ItemClass.DOOR_EXIT_SP: [
        {'corridor_1', 'exit_corridor', 'sp_corridor'},
        {'corridor_2', 'exit_corridor', 'sp_corridor'},
        {'corridor_3', 'exit_corridor', 'sp_corridor'},
        {'corridor_4', 'exit_corridor', 'sp_corridor'},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'white'},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'black'},
    ],
    ItemClass.DOOR_ENTRY_COOP: [
        {'entry_corridor', 'coop_corridor'},
        set(),
        set(),
        {'exit_elevator', 'elevator', 'coop_corridor'},
        {'arrival_departure_transition'},
    ],
    ItemClass.DOOR_EXIT_COOP: [
        {'corridor_1', 'exit_corridor', 'coop_corridor'},
        {'corridor_2', 'exit_corridor', 'coop_corridor'},
        {'corridor_3', 'exit_corridor', 'coop_corridor'},
        {'corridor_4', 'exit_corridor', 'coop_corridor'},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'white'},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'black'},
    ],

    ItemClass.PAINT_DROPPER: [
        {'paint_dropper', 'paint_dropper_sprayer'},
        {'paint_dropper', 'paint_dropper_bomb'},
    ],

    ItemClass.PANEL_ANGLED: [
        {'panel_angled'},
    ],
    # Other classes have no traits - single or no instances.
}

# Special functions to call on an instance for their item ID (str)
# or class (enum).
# Arguments are the instance, trait set, item ID and subtype index.
TRAIT_ID_FUNC = {}  # type: Dict[str, Callable[[Entity, Set[str], str, int], None]]
TRAIT_CLS_FUNC = {}  # type: Dict[ItemClass, Callable[[Entity, Set[str], str, int], None]]


def trait_id_func(target: str):
    def deco(func):
        TRAIT_ID_FUNC[target.casefold()] = func
        return func
    return deco


def trait_cls_func(target: ItemClass):
    def deco(func):
        TRAIT_ID_FUNC[target] = func
        return func
    return deco


def get(inst: Entity) -> Set[str]:
    """Return the traits for an instance.

    Modify to set values.
    """
    try:
        return inst.traits
    except AttributeError:
        inst.traits = set()
        return inst.traits


def get_class(inst: Entity) -> Optional[ItemClass]:
    """If known, return the item class for this instance.

    It must be the original entity placed by the PeTI.
    """
    return getattr(inst, 'peti_class', None)


def set_traits(vmf: VMF):
    """Scan through the map, and apply traits to instances."""
    for inst in vmf.by_class['func_instance']:
        inst_file = inst['file'].casefold()
        if not inst_file:
            continue
        try:
            item_id, item_ind = ITEM_FOR_FILE[inst_file]
        except KeyError:
            LOGGER.warning('Unknown instance "{}"!', inst['file'])
            continue

        # BEE2_xxx special instance, shouldn't be in the original map...
        if isinstance(item_ind, str):
            LOGGER.warning('<{}:bee2_{}> found in original map?', item_id, item_ind)
            continue

        try:
            item_class = ItemClass(CLASS_FOR_ITEM[item_id.casefold()])
        except KeyError:  # dict fail
            LOGGER.warning('Unknown item ID <{}>', item_id)
            item_class = ItemClass.UNCLASSED
        except ValueError:  # ItemClass() fail
            LOGGER.warning('Unknown item class for id <{}>', item_id)
            item_class = ItemClass.UNCLASSED

        inst.peti_class = item_class
        traits = get(inst)
        try:
            traits |= ID_ATTRS[item_id.upper()][item_ind]
        except (IndexError, KeyError):
            pass
        try:
            traits |= CLASS_ATTRS[item_class][item_ind]
        except (IndexError, KeyError):
            pass

        try:
            func = TRAIT_ID_FUNC[item_id.casefold()]
        except KeyError:
            pass
        else:
            func(inst, traits, item_id, item_ind)
        try:
            func = TRAIT_CLS_FUNC[item_class]
        except KeyError:
            pass
        else:
            func(inst, traits, item_id, item_ind)