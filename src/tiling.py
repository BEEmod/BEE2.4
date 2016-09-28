"""Generates all tile brushes.

It also tracks overlays assigned to tiles, so we can regenerate all the brushes.
That allows any wall cube to be split into separate brushes, and make quarter-tile patterns.
"""
from enum import Enum
from typing import Tuple, Dict, List

from srctools import Vec
from srctools import VMF, Entity, Side, Solid


TILE_TEMP = {}  # Face surfaces used to generate tiles.
# TILE_TEMP[tile_norm][u_norm, v_norm] = (bevel_face, flat_face)
# TILE_TEMP[tile_norm]['tile'] = front_face
# TILE_TEMP[tile_norm]['bck'] = back_face
# Maps normals to the index in PrismFace.
PRISM_NORMALS = {
    # 0 = solid
    ( 0,  0,  1): 1,  # Top
    ( 0,  0, -1): 2,  # Bottom
    ( 0,  1,  0): 3,  # North
    ( 0, -1,  0): 4,  # South
    ( 1,  0,  0): 5,  # East
    (-1,  0,  0): 6,  # West
}

# All the tiledefs in the map.
# Maps a point -> tiledef, where the points are block origin + 63*normal
TILES = {}


class TileType(Enum):
    """Physical types of geometry for each 1/4 tile."""
    WHITE = 0
    WHITE_4x4 = 1
    BLACK = 2
    BLACK_4x4 = 3
    
    # Below ignore the associated TILE_STYLE.
     
    NODRAW = 10  # Covered, so it should be set to nodraw
    
    # Clean light strips which have a 3-unit recess with nodraw.
    LIGHT_STRIP_CLEAN = 11
    
    # 3 unit recess,  with backpanels or props/plastic behind. 
    # _BROKEN is ignored when allocating patterns - it wasn't there when the 
    #  tiles were installed. 
    # _PARTIAL is not, it's for WIP chambers.
    # If the skybox is 3D, _PARTIAL uses tools/skybox.
    CUTOUT_TILE_BROKEN = 12
    CUTOUT_TILE_PARTIAL = 13
    
    @property
    def is_recess(self):
        return self.value in (11, 12, 13)
     
    @property   
    def is_nodraw(self):
        return self.value in (10, 11)
        
    @property
    def blocks_pattern(self):
        return self.value in (10, 11, 13)
        
    @property
    def is_tile(self):
        return self.value < 10
        
    @property
    def is_white(self):
        return self.value in (0, 1)
        
    @property
    def is_black(self):
        return self.value in (2, 3)
        
    @property
    def is_4x4(self):
        return self.value in (1, 3)
        

class BrushType(Enum):
    NORMAL = 0  # Normal surface.
    NODRAW = 1  # Nodraw brush, but needed to seal void and make backpanels.

    # Replaced by a template or off-grid embedFace. Shouldn't be modified by
    # us beyond retexturing and setting overlays.
    TEMPLATE = 2
    ANGLED_PANEL = 3  # Angled Panel - needs special handling for static versions.
    FLIP_PANEL = 4  # Flip panels - these are double-sided.
    
    
def bbox(first: Tuple[int, int], *points: Tuple[int, int]):
    max_x, max_y = min_x, min_y = first
    for x, y in points:
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
    return min_x, min_y, max_x, max_y  


def bbox_intersect(b1_min, b1_max, b2_min, b2_max):
    # To check for intersect, see if it's totally outside in all
    # directions.
    if b1_max.x < b2_min.x or b1_max.y < b2_min.y: # b1 Left, above b2
        return False
    if b1_min.x > b2_max.x or b1_min.y > b2_max.y: # b1 right, below b2
        return False
    return True


class Pattern:
    """Represents a position a tile can be positioned in."""
    def __init__(self, tex: str, *tiles: Tuple[int, int, int, int], wall_only=False):
        self.tex = tex
        self.wall_only = wall_only
        self.tiles = tiles
            
    def __repr__(self):
        return 'Pattern({!r}, {}{}'.format(
            self.tex,
            ','.join(map(repr, self.tiles)),
            ', wall_only=True)' if self.wall_only else ')'
        )

PATTERNS = {
    'clean': [
        Pattern('1x1', (0, 0, 3, 3)),
        Pattern('2x1', 
            (0, 0, 1, 3), (1, 0, 2, 3), (2, 0, 3, 3),  # L/M/R
            wall_only=True,
        ),
        Pattern('2x2', 
            (0, 0, 1, 1), (2, 0, 3, 1), (0, 2, 1, 3), (2, 2, 3, 3), # Corners
            (0, 1, 3, 2), # Special case - horizontal 2x1, don't use center.
            (1, 1, 2, 2), # Center
            (1, 0, 2, 1), (1, 2, 2, 3), # Vertical
            (0, 1, 1, 2), (2, 1, 3, 2), # Horizontal
        ),
    ],
    
    # Don't have 2x2/1x1 tiles off-grid..
    'grid_only': [
        Pattern('1x1', (0, 0, 3, 3)),
        Pattern('2x1', 
            (0, 0, 1, 3), (2, 0, 3, 3),  # L/R
            wall_only=True,
        ),
        Pattern('2x2', 
            (0, 0, 1, 1), (2, 0, 3, 1), (0, 2, 1, 3), (2, 2, 3, 3), # Corners
        ),
    ],
}


class TileDef:
    """Represents one 128 block side.
    
    Attributes:
        pos: Vec for the center of the side.
        normal: The direction out of the block.
        brush_faces: A list of brush faces that this block uses.
        brush_type: BrushType - what sort of brush this is.
        base_type: TileType this tile started with.
        override_tex: If set, a specific texture to use (skybox, light, backpanels etc)
        sub_tiles: None or a Dict[(u,v): TileType]. u/v are either xz, yz or xy.
          If None or a point is not in the dict, it's the same as base_type. (None=1x1 tile).
        is_bullseye: If this tile has a bullseye attached to it (the instance is destroyed.)
        panel_inst: The instance for this panel, if it's a panel brush_type.
        panel_ent: The brush entity for the panel, if it's a panel brush_type.
    """
    __slots__ = [
        'pos', 
        'normal', 
        'brush_faces', 
        'brush_type', 
        'base_type', 
        'sub_tiles',
        'override_tex',
        'is_bullseye', 
        'panel_inst', 
        'panel_ent',
    ]
    def __init__(
        self,
        pos: Vec, 
        normal: Vec,
        brush_faces: List[Side],
        base_type: TileType,
        brush_type=BrushType.NORMAL,
        subtiles: Dict[Tuple[int, int], TileType]=None,
        override_tex: str=None,
        is_bullseye: bool=False,
        panel_inst: Entity=None,
        panel_ent: Entity=None,
    ):
        self.pos = pos
        self.normal = normal
        self.brush_faces = brush_faces
        self.brush_type = brush_type
        self.override_tex = override_tex
        self.base_type = base_type
        self.sub_tiles = subtiles
        self.is_bullseye = is_bullseye
        self.panel_inst = panel_inst
        self.panel_ent = panel_ent


def make_tile(
    origin: Vec, 
    normal: Vec, 
    top_surf: str, 
    recess_dist=0,
    thickness=4,
    width=16,
    height=16,
    bevel_umin=False,
    bevel_umax=False,
    bevel_vmin=False,
    bevel_vmax=False,
) -> Solid:
    """Generate a tile. 
    
    This uses UV coordinates, which equal xy, xz, or yz depending on normal.
    Parameters:
        * origin: Location of the center of the tile, on the block surface.
        * normal: Unit vector pointing out of the tile.
        * top_surf: Texture to apply to the front of the tile.
        * recess_dist: How far the front is below the block surface.
        * thickness: How far back the back surface is (normally 4). Max of 4, 
           Must be > recess_dist.
        * width: size in the U-direction. Must be > 8.
        * height: size in the V-direction. Must be > 8.
        * bevel_min/max u/v: If that side should be 45° angled.      
    """
    assert TILE_TEMP, "make_tile called without data loaded!"


def gen_tile_temp():
    """Generate the sides used to create tiles.

    This populates TILE_TEMP.
    """

def on_16_grid(face: Side):
    """Check if this side is on the 16-unit grid.

    This assumes face vertices = corners, which is usually true.
    """

def analyse_map(vmf_file: VMF):
    """Create TileDefs from all the brush sides."""
    for brush in vmf_file.brushes[:]:
        pass