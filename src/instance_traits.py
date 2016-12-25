"""Adds various traits to instances, based on item classes."""
from srctools import Entity
from srctools import VMF

from typing import Set

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
