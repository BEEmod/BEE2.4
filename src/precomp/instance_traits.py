"""Adds various traits to instances, based on item classes."""
from typing import List, MutableMapping, Optional, Dict, Set, Union
from weakref import WeakKeyDictionary

import attrs
from srctools import Entity, VMF
import srctools.logger

from precomp.instanceLocs import ITEM_FOR_FILE
from precomp.collisions import Collisions
from editoritems import Item, ItemClass
from corridor import parse_filename as parse_corr_filename, CORR_TO_ID


LOGGER = srctools.logger.get_logger(__name__)
# Indicates the collision should only go on the main instance.
SKIP_COLL = '_skip_coll'

# Special case - specific attributes..
ID_ATTRS: Dict[str, List[Set[str]]] = {
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
    'ITEM_OBSERVATION_ROOM': [
        {'preplaced'},
    ]
}

CLASS_ATTRS: Dict[ItemClass, List[Set[str]]] = {
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
        {'white', 'tbeam_frame', SKIP_COLL},
        {'black', 'tbeam_frame', SKIP_COLL},
    ],
    ItemClass.CUBE: [
        {'dropperless', 'cube_standard'},
        {'dropperless', 'cube_companion'},
        {'dropperless', 'cube_reflect'},
        {'dropperless', 'cube_ball'},
        {'dropperless', 'cube_franken'},
    ],
    ItemClass.FIZZLER: [
        {'fizzler', 'fizzler_base', SKIP_COLL},
        {'fizzler', 'fizzler_model'},
    ],
    ItemClass.TRACK_PLATFORM: [
        {'track_platform', 'track', 'plat_bottom_grate', SKIP_COLL},
        {'track_platform', 'track', 'plat_bottom', SKIP_COLL},
        {'track_platform', 'track', 'plat_middle', SKIP_COLL},
        {'track_platform', 'track', 'plat_top', SKIP_COLL},
        {'track_platform', 'platform', 'plat_non_osc'},
        {'track_platform', 'platform', 'plat_osc'},
        {'track_platform', 'track', 'plat_single', SKIP_COLL},
    ],
    ItemClass.GLASS: [
        {'barrier', 'barrier_128'},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_corner', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_straight', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_short', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_left', 'frame_convex_corner', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_corner', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_straight', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_short', SKIP_COLL},
        {'barrier', 'barrier_frame', 'frame_right', 'frame_convex_corner', SKIP_COLL},
    ],
    ItemClass.DOOR_ENTRY_SP: [
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'entry_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'corridor_frame', 'entry_corridor', 'sp_corridor', 'white', 'preplaced', SKIP_COLL},
        {'corridor_frame', 'entry_corridor', 'sp_corridor', 'black', 'preplaced', SKIP_COLL},
        {'entry_elevator', 'elevator', 'sp_corridor', 'preplaced', SKIP_COLL},
        {'exit_elevator', 'elevator', 'sp_corridor', 'preplaced', SKIP_COLL},
        {'arrival_departure_transition', 'preplaced', SKIP_COLL},
    ],
    ItemClass.DOOR_EXIT_SP: [
        {'exit_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'exit_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'exit_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'exit_corridor', 'sp_corridor', 'corridor', 'preplaced'},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'white', 'preplaced', SKIP_COLL},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'black', 'preplaced', SKIP_COLL},
    ],
    ItemClass.DOOR_ENTRY_COOP: [
        {'entry_corridor', 'coop_corridor', 'corridor', 'preplaced'},
        set(),  # White/black 'door frames', not used on the entry.
        set(),
        {'exit_elevator', 'elevator', 'coop_corridor', 'preplaced', SKIP_COLL},
        {'arrival_departure_transition', 'preplaced', SKIP_COLL},
    ],
    ItemClass.DOOR_EXIT_COOP: [
        {'exit_corridor', 'coop_corridor', 'preplaced'},
        {'exit_corridor', 'coop_corridor', 'preplaced'},
        {'exit_corridor', 'coop_corridor', 'preplaced'},
        {'exit_corridor', 'coop_corridor', 'preplaced'},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'white', 'preplaced', SKIP_COLL},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'black', 'preplaced', SKIP_COLL},
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


@attrs.define
class TraitInfo:
    """The info associated for each instance."""
    item_class: ItemClass = ItemClass.UNCLASSED
    item_id: Optional[str] = None
    traits: Set[str] = attrs.Factory(set)

# Maps entities to their traits.
ENT_TO_TRAITS: MutableMapping[Entity, TraitInfo] = WeakKeyDictionary()


def get(inst: Entity) -> Set[str]:
    """Return the traits for an instance.

    Modify to set values.
    """
    try:
        return ENT_TO_TRAITS[inst].traits
    except KeyError:
        info = ENT_TO_TRAITS[inst] = TraitInfo()
        return info.traits


def get_class(inst: Entity) -> Optional[ItemClass]:
    """If known, return the item class for this instance.

    It must be the original entity placed by the PeTI.
    """
    try:
        return ENT_TO_TRAITS[inst].item_class
    except KeyError:
        return None


def get_item_id(inst: Entity) -> Optional[str]:
    """If known, return the item ID for this instance.

    It must be the original entity placed by the PeTI.
    """
    try:
        return ENT_TO_TRAITS[inst].item_id
    except KeyError:
        return None


def set_traits(vmf: VMF, id_to_item: Dict[str, Item], coll: Collisions) -> None:
    """Scan through the map, apply traits to instances, and set initial collisions."""
    for inst in vmf.by_class['func_instance']:
        inst_file = inst['file'].casefold()
        if not inst_file:
            continue

        item_ind: Union[str, int]
        # Special case, corridors.
        corr_info = parse_corr_filename(inst_file)
        if corr_info is not None:
            corr_mode, corr_dir, item_ind = corr_info
            item_id = CORR_TO_ID[corr_mode, corr_dir]
        else:
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
            item = id_to_item[item_id.casefold()]
        except KeyError:  # dict fail
            LOGGER.warning('Unknown item ID <{}>', item_id)
            item_class = ItemClass.UNCLASSED
            item = None
        else:
            item_class = item.cls

        info = ENT_TO_TRAITS[inst] = TraitInfo(item_class, item_id)

        try:
            info.traits |= ID_ATTRS[item_id.upper()][item_ind]
        except (IndexError, KeyError):
            pass
        try:
            info.traits |= CLASS_ATTRS[item_class][item_ind]
        except (IndexError, KeyError):
            pass

        if SKIP_COLL in info.traits:
            # Don't add collision, even if it's defined. This is say the tbeam frame instance, or
            # an elevator - we want the collisions on a different instance.
            info.traits.remove(SKIP_COLL)
            # Also skip if no name is set.
        elif item is not None and inst['targetname'] != '':
            coll.add_item_coll(item, inst)
