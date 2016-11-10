"""Adds various traits to instances, based on item classes."""
from srctools import Entity
from srctools import VMF

from typing import Set

CLASS_ATTRS = {
    'itembuttonfloor': [
        {'white', 'weighted', 'floor_button'},
        {'black', 'weighted', 'floor_button'},
        {'white', 'btn_cube', 'floor_button'},
        {'black', 'btn_cube', 'floor_button'},
        {'white', 'btn_ball', 'floor_button'},
        {'black', 'btn_ball', 'floor_button'},
    ],
    'itemtbeam': [
        {'tbeam_emitter'},
        {'white', 'tbeam_frame'},
        {'black', 'tbeam_frame'},
    ],
    'itemcube': [
        {'dropperless', 'cube_standard'},
        {'dropperless', 'cube_companion'},
        {'dropperless', 'cube_reflect'},
        {'dropperless', 'cube_ball'},
        {'dropperless', 'cube_franken'},
    ],
    'itembarrierhazard': [
        {'fizzler', 'fizzler_base'},
        {'fizzler', 'fizzler_model'},
    ],
    'itemrailplatform': [
        {'track_platform', 'plat_bottom_grate'},
        {'track_platform', 'plat_bottom'},
        {'track_platform', 'plat_middle'},
        {'track_platform', 'plat_top'},
        {'track_platform', 'plat_non_osc'},
        {'track_platform', 'plat_osc'},
        {'track_platform', 'plat_single'},
    ],
    'itembarrier': [
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
    'itementrancedoor': [
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
    'itemexitdoor': [
        {'corridor_1', 'exit_corridor', 'sp_corridor'},
        {'corridor_2', 'exit_corridor', 'sp_corridor'},
        {'corridor_3', 'exit_corridor', 'sp_corridor'},
        {'corridor_4', 'exit_corridor', 'sp_corridor'},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'white'},
        {'corridor_frame', 'exit_corridor', 'sp_corridor', 'black'},
    ],
    'itemcoopentrancedoor': [
        {'entry_corridor', 'coop_corridor'},
        {},
        {},
        {'exit_elevator', 'elevator', 'coop_corridor'},
        {'arrival_departure_transition'},
    ],
    'itemcoopexitdoor': [
        {'corridor_1', 'exit_corridor', 'coop_corridor'},
        {'corridor_2', 'exit_corridor', 'coop_corridor'},
        {'corridor_3', 'exit_corridor', 'coop_corridor'},
        {'corridor_4', 'exit_corridor', 'coop_corridor'},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'white'},
        {'corridor_frame', 'exit_corridor', 'coop_corridor', 'black'},
    ],

    'itempaintdropper': [
        {'paint_dropper', 'paint_dropper_sprayer'},
        {'paint_dropper', 'paint_dropper_bomb'},
    ],

    # Single instance
    'itempistonplatform': [],
    'itemlaseremitter': [],
    'itemstairs': [],
    'itemlightstrip': [],
    'itempedestalbutton': [],
    'itempanelflip': [],
    'itemangledpanel': [],
    'itemcatapulttarget': [],
    'itemcatapult': [],
    'itempaintsplat': [],
    'itemturret': [],
    'itemlightbridge': [],

    # No instances...
    'itembarrierhazardextent': [],
    'itembarrierextent': [],
    'itemrailplatformextent': [],
    'itemgoo': [],
}


def get(inst: Entity) -> Set[str]:
    """Return the traits for an instance."""
    try:
        return inst.traits
    except AttributeError:
        inst.traits = set()
        return inst.traits

def set_traits(vmf: VMF):
    """Scan through the map, and apply traits to instances."""
    pass
