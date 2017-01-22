"""Templates are sets of brushes which can be copied into the map."""
from collections import namedtuple
from enum import Enum

from srctools import Entity, Solid, Side
import comp_consts as consts
import conditions

from typing import (
    Iterable, NamedTuple,
    Dict, List, Set,
)

TEMPLATES = {}


class MAT_TYPES(Enum):
    """Represents Black vs White."""
    black = 0
    white = 1

    def __str__(self):
        if self is MAT_TYPES.black:
            return 'black'
        if self is MAT_TYPES.white:
            return 'white'

class TEMP_TYPES(Enum):
    """Value used for import_template()'s force_type parameter.
    """
    default = 0  # Based on the original VMF settings
    world = 1  # Import and add to world
    detail = 2  # Import as a func_detail


B = MAT_TYPES.black
W = MAT_TYPES.white
TEMPLATE_RETEXTURE = {
    # textures map -> surface types for template brushes.
    # It's mainly for grid size and colour - floor/ceiling textures
    # will be used instead at those orientations

    'metal/black_wall_metal_002c': (B, 'wall'),
    'metal/black_wall_metal_002a': (B, '2x2'),
    'metal/black_wall_metal_002b': (B, '4x4'),

    'tile/white_wall_tile001a': (W, 'wall'),
    'tile/white_wall_tile003a': (W, 'wall'),
    'tile/white_wall_tile003b': (W, 'wall'),
    'tile/white_wall_tile003c': (W, '2x2'),
    'tile/white_wall_tile003h': (W, 'wall'),
    'tile/white_wall_state': (W, '2x2'),
    'tile/white_wall_tile003f': (W, '4x4'),

    # No black portal-placement texture, so use the bullseye instead
    'metal/black_floor_metal_bullseye_001': (B, 'special'),
    'tile/white_wall_tile004j': (W, 'special'),
    'tile/white_wall_tile_bullseye': (W, 'special'),  # For symmetry

    consts.Special.BACKPANELS: 'special.behind',
    consts.Special.SQUAREBEAMS: 'special.edge',
    consts.Special.GLASS: 'special.glass',
    consts.Special.GRATING: 'special.grating',

    consts.Goo.CHEAP: 'special.goo_cheap',
}
del B, W

ExportedTemplate = NamedTuple('ExportedTemplate', [
    ('world', List[Solid]),
    ('detail', List[Solid]),
    ('overlay', List[Entity]),
    ('orig_ids', Dict[str, str]),
])


# 'Opposite' values for retexture_template(force_colour)
TEMP_COLOUR_INVERT = {
    MAT_TYPES.white: MAT_TYPES.black,
    MAT_TYPES.black: MAT_TYPES.white,
    None: 'INVERT',
    'INVERT': None,
}


class Template:
    """Represents a template before it's imported into a map."""
    def __init__(
        self,
        temp_id,
        brushes: Dict[str, List[Solid]],
        details: Dict[str, List[Solid]],
        overlays: Dict[str, List[Entity]],
        realign_faces: Iterable[str],
        overlay_transfer_faces: Iterable[str],
    ):
        self.id = temp_id
        self.brushes = brushes
        self.details = details
        self.overlays = overlays

        self.realign_faces = set(realign_faces)
        self.overlay_faces = set(overlay_transfer_faces)

        TEMPLATES[temp_id] = self

