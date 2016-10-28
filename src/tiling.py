"""Generates all tile brushes.

It also tracks overlays assigned to tiles, so we can regenerate all the brushes.
That allows any wall cube to be split into separate brushes, and make quarter-tile patterns.
"""
from enum import Enum
from typing import Tuple, Dict, List

from srctools import Vec, Vec_tuple
from srctools import VMF, Entity, Side, Solid
from brushLoc import POS as BLOCK_POS, Block, grid_to_world, world_to_grid
import comp_consts as consts
import utils
import conditions

LOGGER = utils.getLogger(__name__)

TILE_TEMP = {}  # Face surfaces used to generate tiles.
# TILE_TEMP[tile_norm][u_norm, v_norm] = (flat_face, bevel_face)
# TILE_TEMP[tile_norm]['tile'] = front_face
# TILE_TEMP[tile_norm]['back'] = back_face
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

NORMALS = [Vec(x=1), Vec(x=-1), Vec(y=1), Vec(y=-1), Vec(z=1), Vec(z=-1)]
NORM_ANGLES = {v.as_tuple(): v.to_angle() for v in NORMALS}
UV_NORMALS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# All the tiledefs in the map.
# Maps a pos, normal -> tiledef
TILES = {}  # type: Dict[Tuple[Vec_tuple, Vec_tuple], TileDef]


class TileType(Enum):
    """Physical types of geometry for each 1/4 tile."""
    WHITE = 0
    WHITE_4x4 = 1
    BLACK = 2
    BLACK_4x4 = 3
     
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
            (0, 0, 1, 1), (2, 0, 3, 1), (0, 2, 1, 3), (2, 2, 3, 3),  # Corners
            (0, 1, 3, 2),  # Special case - horizontal 2x1, don't use center.
            (1, 1, 2, 2),  # Center
            (1, 0, 2, 1), (1, 2, 2, 3),  # Vertical
            (0, 1, 1, 2), (2, 1, 3, 2),  # Horizontal
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
            (0, 0, 1, 1), (2, 0, 3, 1), (0, 2, 1, 3), (2, 2, 3, 3),  # Corners
        ),
    ],
}


class TileDef:
    """Represents one 128 block side.
    
    Attributes:
        pos: Vec for the center of the side.
        normal: The direction out of the block.
        brush_faces: A list of off-grid brushes that this block uses.
          When exporting, this contains the used brushes.
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
        'brush_type',
        'brush_faces',
        'base_type',
        'sub_tiles',
        'override_tex',
        'is_bullseye',
        'panel_inst',
        'panel_ent',
        'extra_brushes',
    ]

    def __init__(
        self,
        pos: Vec, 
        normal: Vec,
        base_type: TileType,
        brush_type=BrushType.NORMAL,
        subtiles: Dict[Tuple[int, int], TileType]=None,
        override_tex: str=None,
        is_bullseye: bool=False,
        panel_inst: Entity=None,
        panel_ent: Entity=None,
        extra_brushes: List[Solid]=(),
    ):
        self.pos = pos
        self.normal = normal
        self.brush_type = brush_type
        self.brush_faces = []
        self.override_tex = override_tex
        self.base_type = base_type
        self.sub_tiles = subtiles
        self.is_bullseye = is_bullseye
        self.panel_inst = panel_inst
        self.panel_ent = panel_ent
        self.extra_brushes = list(extra_brushes)

    def __repr__(self):
        return '<{}, {} TileDef>'.format(
            self.base_type.name,
            self.brush_type.name,
        )

    def export(self, vmf: VMF):
        """Create the solid for this."""
        if not self.sub_tiles:
            brush, face = make_tile(
                vmf,
                self.pos + self.normal * 64,
                self.normal,
                top_surf=(
                    consts.BlackPan.BLACK_4x4 if
                    self.base_type is TileType.BLACK
                    else consts.WhitePan.WHITE_4x4
                ),
                width=128,
                height=128,
                bevel_umin=True,
                bevel_umax=True,
                bevel_vmin=True,
                bevel_vmax=True,
            )
            self.brush_faces.append(face)
            return [brush]


def make_tile(
    vmf: VMF,
    origin: Vec, 
    normal: Vec, 
    top_surf: str,
    back_surf: str=consts.Tools.NODRAW.value,
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
        * back_surf: Texture to apply to the back of the tile.
        * recess_dist: How far the front is below the block surface.
        * thickness: How far back the back surface is (normally 4). Max of 4, 
           Must be > recess_dist.
        * width: size in the U-direction. Must be > 8.
        * height: size in the V-direction. Must be > 8.
        * bevel_min/max u/v: If that side should be 45° angled.      
    """
    assert TILE_TEMP, "make_tile called without data loaded!"
    template = TILE_TEMP[normal.as_tuple()]

    assert width >=8 and height >=8, 'Tile is too small!'

    top_side = template['front'].copy(map=vmf)  # type: Side
    top_side.mat = top_surf
    top_side.translate(origin - recess_dist * normal)

    back_side = template['back'].copy(map=vmf)  # type: Side
    back_side.mat = back_surf
    back_side.translate(origin - thickness * normal)

    axis_u, axis_v = Vec.INV_AXIS[normal.axis()]

    umin_side = template[-1, 0][bevel_umin].copy(map=vmf)
    umin_side.translate(origin + Vec(**{axis_u: -width/2}))

    umax_side = template[1, 0][bevel_umax].copy(map=vmf)
    umax_side.translate(origin + Vec(**{axis_u: width/2}))

    vmin_side = template[0, -1][bevel_vmin].copy(map=vmf)
    vmin_side.translate(origin + Vec(**{axis_v: -height/2}))

    vmax_side = template[0, 1][bevel_vmax].copy(map=vmf)
    vmax_side.translate(origin + Vec(**{axis_v: height/2}))

    return Solid(vmf, sides=[
        top_side, back_side,
        umin_side, umax_side,
        vmin_side, vmax_side,
    ]), top_side


def gen_tile_temp():
    """Generate the sides used to create tiles.

    This populates TILE_TEMP with pre-rotated solids in each direction,
     with each side identified.
    """
    try:
        template = conditions.get_template('__TILING_TEMPLATE__')
        # Template -> world -> first solid
        # We restrict what templates can be used here.
        bevel_temp = template['bevel'][0][0]
        flat_temp = template['flat'][0][0]
    except KeyError:
        raise Exception('Bad Tiling Template!')

    for norm_tup, angles in NORM_ANGLES.items():
        norm = Vec(norm_tup)
        axis_norm = norm.axis()

        rotated_bevel = bevel_temp.copy()
        rotated_flat = flat_temp.copy()

        rotated_bevel.localise(Vec(), angles)
        rotated_flat.localise(Vec(), angles)

        TILE_TEMP[norm_tup] = temp_part = {}

        bevel_sides = {}

        for face in rotated_bevel:
            if face.mat in consts.BlackPan or face.mat in consts.WhitePan:
                temp_part['front'] = face
                face.translate(-2 * norm)
            elif face.mat == consts.Special.BACKPANELS:
                temp_part['back'] = face
                face.translate(2 * norm)
            else:
                # Squarebeams
                face_norm = round(face.get_origin().norm())  # type: Vec
                bevel_sides[face_norm.as_tuple()] = face
                face.translate(-14 * face_norm)

        for face in rotated_flat:
            face_norm = round(face.get_origin().norm())  # type: Vec
            if face_norm[axis_norm]:
                continue

            face.translate(-16 * face_norm)
            temp_part[face_norm.other_axes(norm.axis())] = (
                face,
                bevel_sides[face_norm.as_tuple()],
            )



def analyse_map(vmf_file: VMF):
    """Create TileDefs from all the brush sides."""

    # Face ID -> tileDef, used to match overlays to their face targets.
    # Invalid after we exit, since all the IDs have been freed and may be
    # reused later.
    face_to_tile = {}

    for brush in vmf_file.brushes[:]:
        bbox_min, bbox_max = brush.get_bbox()
        dim = bbox_max - bbox_min
        grid_pos = bbox_min // 128 * 128 + (64, 64, 64)
        if dim == (128, 128, 128):
            tiledefs_from_cube(face_to_tile, brush, grid_pos)
            vmf_file.remove_brush(brush)

    # Parse face IDs saved in overlays - if they're matching a tiledef,
    # remove them.
    for over in vmf_file.by_class['info_overlay']:
        faces = over['sides', ''].split(' ')
        tiles = over.tiledefs = []
        for face in faces[:]:
            try:
                tiles.append(face_to_tile[int(face)])
            except (KeyError, ValueError):
                pass
            else:
                faces.remove(face)
        over['sides'] = ' '.join(faces)


def tiledefs_from_cube(face_to_tile, brush: Solid, grid_pos: Vec):
    """Generate a tiledef matching a 128^3 block."""
    for face in brush:
        normal = -face.normal()
        special_tex = None

        # These cubes don't contain any items, so it's fine
        # if we get rid of sides that aren't useful.
        # if it's bordering void or another solid, it's unneeded.
        neighbour_block = BLOCK_POS['world': grid_pos + 128 * normal]
        if not neighbour_block.traversable:
            continue

        if face.mat in consts.BlackPan:
            tex_kind = TileType.BLACK
        elif face.mat in consts.WhitePan:
            tex_kind = TileType.WHITE
        else:
            tex_kind = TileType.BLACK
            special_tex = face.mat

        tiledef = TileDef(
            grid_pos,
            normal,
            base_type=tex_kind,
            override_tex=special_tex,
        )
        TILES[grid_pos.as_tuple(), normal.as_tuple()] = tiledef
        face_to_tile[face.id] = tiledef


def generate_brushes(vmf: VMF):
    """Generate all the brushes in the map, then set overlay sides."""
    for tile in TILES.values():
        brushes = tile.export(vmf)
        vmf.add_brushes(brushes)

    for over in vmf.by_class['info_overlay']:
        try:
            tiles = over.tiledefs  # type: List[TileDef]
        except AttributeError:
            continue
        faces = over['sides', ''].split(' ')
        for tile in tiles:
            faces.extend(str(f.id) for f in tile.brush_faces)

        if faces:
            over['sides'] = ' '.join(faces)
        else:
            over.remove()

