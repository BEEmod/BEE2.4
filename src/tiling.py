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
import texturing
from texturing import TexCat as TileSize

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
# Specific angles, these ensure the textures align to world once done.
# IE upright on walls, up=north for floor and ceilings.
NORM_ANGLES = {
    Vec(x=1).as_tuple(): Vec(0, 0, 90),
    Vec(x=-1).as_tuple(): Vec(0, 180, 90),
    Vec(y=1).as_tuple(): Vec(0, 90, 90),
    Vec(y=-1).as_tuple(): Vec(0, 270, 90),
    Vec(z=1).as_tuple(): Vec(270, 270,  0),
    Vec(z=-1).as_tuple(): Vec(90, 90, 0),
}
# U-min, max, V-min, max in order.
UV_NORMALS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

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

    # Air - used for embedFace sections.
    VOID = 11
    
    # Clean light strips which have a 3-unit recess with nodraw.
    LIGHT_STRIP_CLEAN = 21

    # 3 unit recess,  with backpanels or props/plastic behind. 
    # _BROKEN is ignored when allocating patterns - it wasn't there when the 
    #  tiles were installed. 
    # _PARTIAL is not, it's for WIP chambers.
    # If the skybox is 3D, _PARTIAL uses tools/skybox.
    CUTOUT_TILE_BROKEN = 22
    CUTOUT_TILE_PARTIAL = 23
    
    @property
    def is_recess(self):
        return self.value in (21, 22, 23)
     
    @property   
    def is_nodraw(self):
        return self.value in (10, 21)
        
    @property
    def blocks_pattern(self):
        return self.value in (10, 11, 21, 23)
        
    @property
    def is_tile(self):
        """Is this a regular tile (white/black)."""
        return self.value < 10
        
    @property
    def is_white(self):
        return self.value in (0, 1)
        
    @property
    def color(self):
        if self.value in (0, 1):
            return 'white'
        elif self.value in (2, 3):
            return 'black'
        raise ValueError('No colour for ' + self.name + '!')

    @property
    def tile_size(self):
        if self.value in (1, 3):
            return TileSize.TILE_4x4
        else:
            return TileSize.TILE_1x1

# Symbols that represent TileType values.
TILETYPE_TO_CHAR = {
    TileType.WHITE: 'W',
    TileType.WHITE_4x4: 'w',
    TileType.BLACK: 'B',
    TileType.BLACK_4x4: 'b',
    TileType.NODRAW: 'n',
    TileType.VOID: '.',
    TileType.LIGHT_STRIP_CLEAN: '*',
    TileType.CUTOUT_TILE_BROKEN: 'x',
    TileType.CUTOUT_TILE_PARTIAL: 'o',
}
TILETYPE_FROM_CHAR = {
    v: k
    for k, v in
    TILETYPE_TO_CHAR.items()
}


class BrushType(Enum):
    NORMAL = 0  # Normal surface.
    NODRAW = 1  # Nodraw brush, but needed to seal void and make backpanels.

    # Replaced by a template or off-grid embedFace. Shouldn't be modified by
    # us beyond retexturing and setting overlays.
    TEMPLATE = 2
    ANGLED_PANEL = 3  # Angled Panel - needs special handling for static versions.
    FLIP_PANEL = 4  # Flip panels - these are double-sided.


def round_grid(vec: Vec):
    """Round to the center of the grid."""
    return vec // 128 * 128 + (64, 64, 64)


def iter_uv(umin=0, umax=3, vmin=0, vmax=3):
    """Iterate over points in a rectangle."""
    urange = range(int(umin), int(umax + 1))
    vrange = range(int(vmin), int(vmax + 1))
    for u in urange:
        for v in vrange:
            yield u, v

TILE_SIZES = {
    TileSize.TILE_1x1: (4, 4),
    TileSize.TILE_2x1: (2, 4),
    TileSize.TILE_2x2: (2, 2),
    TileSize.TILE_4x4: (1, 1),
}


class Pattern:
    """Represents a position a tile can be positioned in."""
    def __init__(self, tex: TileSize, *tiles: Tuple[int, int, int, int], wall_only=False):
        self.tex = tex
        self.wall_only = wall_only
        self.tiles = tiles
        tile_u, tile_v = TILE_SIZES[tex]
        # Do some sanity checks on values..
        for umin, vmin, umax, vmax in tiles:
            tile_tex = '{} -> {} {} {} {}'.format(tex, umin, vmin, umax, vmax)
            assert 0 <= umin < umax <= 4, tile_tex
            assert 0 <= vmin < vmax <= 4, tile_tex
            assert (umax - umin) % tile_u == 0, tile_tex
            assert (vmax - vmin) % tile_v == 0, tile_tex

            
    def __repr__(self):
        return 'Pattern({!r}, {}{}'.format(
            self.tex,
            ','.join(map(repr, self.tiles)),
            ', wall_only=True)' if self.wall_only else ')'
        )


def order_bbox(bbox):
    """Used to sort 4x4 pattern positions.

    The pattern order is the order that they're tried in.
    We want to try the largest first so reverse the ordering used on max values.
    """
    umin, vmin, umax, vmax = bbox
    return umin, vmin, -umax, -vmax

PATTERNS = {
    'clean': [
        Pattern(TileSize.TILE_1x1, (0, 0, 4, 4)),
        Pattern(TileSize.TILE_2x1,
            (0, 0, 4, 4),  # Combined
            (0, 0, 2, 4), (1, 0, 3, 4), (2, 0, 4, 4),  # L/M/R
            wall_only=True,
        ),
        Pattern(TileSize.TILE_2x2,
            # Combinations:
            (0, 0, 2, 4), (0, 0, 4, 2), (0, 2, 4, 4), (2, 0, 4, 4),
            (1, 0, 3, 4), (0, 1, 4, 3),

            (0, 0, 2, 2), (2, 0, 4, 2), (0, 2, 2, 4), (2, 2, 4, 4),  # Corners
            (0, 1, 4, 3),  # Special case - horizontal 2x1, don't use center.
            (1, 1, 3, 3),  # Center
            (1, 0, 3, 4), (1, 2, 3, 4),  # Vertical
            (0, 1, 2, 3), (2, 1, 4, 3),  # Horizontal
        ),

        # Combinations for 4x4, to merge adjacent blocks..
        Pattern(
            TileSize.TILE_4x4,
            *sorted([vals for x in range(4) for vals in [
                # V-direction, U-direction for each row/column.
                (x, 0, x+1, 4), (0, x, 4, x+1),  # 0-4
                (x, 2, x+1, 4), (2, x, 4, x+1),  # 2-4
                (x, 0, x+1, 2), (0, x, 2, x+1),  # 0-2
                (x, 1, x+1, 3), (1, x, 3, x+1),  # 1-3
                ]
            ], key=order_bbox)
        )
    ],

    # Don't have 2x2/1x1 tiles off-grid..
    'grid_only': [
        Pattern(TileSize.TILE_1x1, (0, 0, 4, 4)),
        Pattern(TileSize.TILE_2x1,
            (0, 0, 2, 4), (2, 0, 4, 4),  # L/R
            wall_only=True,
        ),
        Pattern(TileSize.TILE_2x2,
            (0, 0, 2, 2), (2, 0, 4, 2), (0, 2, 2, 4), (2, 2, 4, 4),  # Corners
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

    def print_tiles(self):
        out = []
        for v in reversed(range(4)):
            for u in range(4):
                out.append(TILETYPE_TO_CHAR[self.sub_tiles[u, v]])
            out.append('\n')
        LOGGER.info('Subtiles: \n{}', ''.join(out))

    @classmethod
    def ensure(cls, grid_pos, norm, tile_type=TileType.VOID):
        """Return a tiledef at a position, creating it with a type if not present."""
        try:
            tile = TILES[grid_pos.as_tuple(), norm.as_tuple()]
        except KeyError:
            tile = TILES[grid_pos.as_tuple(), norm.as_tuple()] = cls(
                grid_pos,
                norm,
                tile_type,
            )
        tile.get_subtiles()
        return tile

    def get_subtiles(self):
        """Returns subtiles, creating it if not present."""
        if self.sub_tiles is None:
            self.sub_tiles = {
                (x, y): self.base_type
                for x in range(4) for y in range(4)
            }
        return self.sub_tiles

    def uv_offset(self, u, v, norm):
        """Return a u/v offset from our position.

        This is used for subtile orientations:
            norm is in the direction of the normal.
            If norm is x, uv = yz.
            If norm is y, uv = xz.
            If norm is z, uv = xy.
        """
        pos = self.pos.copy()
        u_ax, v_ax = Vec.INV_AXIS[self.normal.axis()]
        pos += 128 * self.normal * norm
        pos[u_ax] += 128 * u
        pos[v_ax] += 128 * v
        return pos

    def calc_patterns(self, is_wall=False):
        """Figure out the brushes needed for a complex pattern.

        This returns
        """
        # copy it, so we can overwrite positions with None = not a tile.

        tiles = self.sub_tiles.copy()  # type: Dict[Tuple[int, int], TileType]

        for pattern in PATTERNS['clean']:
            if pattern.wall_only and not is_wall:
                continue
            for (umin, vmin, umax, vmax) in pattern.tiles:
                tile_type = tiles[umin, vmin]
                if not tile_type.is_tile:
                    continue
                for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                    if tiles[uv] is not tile_type:
                        break
                else:
                    for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                        tiles[uv] = TileType.VOID
                    yield umin, umax, vmin, vmax, pattern.tex, tile_type

        # All unfilled spots are single 4x4 tiles.
        for (u, v), tile_type in tiles.items():
            if tile_type is not TileType.VOID:
                yield u, u + 1, v, v + 1, '4x4', tile_type


    def export(self, vmf: VMF):
        """Create the solid for this."""
        bevels = [
            BLOCK_POS['world': self.uv_offset(u, v, 0)].value not in (1, 2)
            for u, v in UV_NORMALS
        ]

        if self.normal == (0, 0, 1):
            orient = 'floor'
        elif self.normal == (0, 0, -1):
            orient = 'ceiling'
        else:
            orient = 'wall'

        front_pos = self.pos + 64 * self.normal

        if self.sub_tiles is None:
            full_type = self.base_type
        else:
            # Normalise subtiles - remove values outside 0-3, and set
            # unset positions to base_type.
            orig_tiles = self.sub_tiles
            self.sub_tiles = {}
            for uv in iter_uv():
                self.sub_tiles[uv] = orig_tiles.get(uv, self.base_type)

            if len(set(self.sub_tiles.values())) == 1:
                full_type = next(iter(self.sub_tiles.values()))
            else:
                full_type = None

        if full_type is not None:
            if full_type.is_nodraw:
                tex = consts.Tools.NODRAW
            else:
                tex = get_tile_tex(
                    full_type.color,
                    orient,
                    full_type.tile_size,
                    front_pos,
                )
            brush, face = make_tile(
                vmf,
                self.pos + self.normal * 64,
                self.normal,
                top_surf=tex,
                width=128,
                height=128,
                bevels=bevels,
                back_surf=texturing.special.rand('behind'),
            )
            self.brush_faces.append(face)
            yield brush
            return

        assert self.sub_tiles is not None

        # Multiple tile types in the block - figure out the tile patterns to use.
        patterns = list(self.calc_patterns(orient == 'wall'))
        for umin, umax, vmin, vmax, grid_size, tile_type in patterns:
            if tile_type.is_tile:
                u_size, v_size = TILE_SIZES[grid_size]
                tex = get_tile_tex(tile_type.color, orient, grid_size, front_pos)
                brush, face = make_tile(
                    vmf,
                    self.uv_offset(
                        (umin + umax) / 8 - 0.5,
                        (vmin + vmax) / 8 - 0.5,
                        0.5,
                    ),
                    self.normal,
                    top_surf=tex,
                    width=(umax - umin) * 32,
                    height=(vmax - vmin) * 32,
                    # We bevel only the grid-edge tiles.
                    bevels=[a and b for a, b in zip(bevels, [
                        umin == 0, umax == 3, vmin == 0, vmax == 3
                    ])],
                    back_surf=texturing.special.rand('behind'),
                    u_align=u_size * 128,
                    v_align=v_size * 128,
                )
                self.brush_faces.append(face)
                yield brush
            elif tile_type is TileType.NODRAW:
                brush, face = make_tile(
                    vmf,
                    self.uv_offset(
                        (umin + umax) / 8 - 0.5,
                        (vmin + vmax) / 8 - 0.5,
                        0.5,
                    ),
                    self.normal,
                    top_surf=consts.Tools.NODRAW,
                    width=(umax - umin) * 32,
                    height=(vmax - vmin) * 32,
                    # We bevel only the grid-edge tiles.
                    bevels=[a and b for a, b in zip(bevels, [
                        umin == 0, umax == 3, vmin == 0, vmax == 3
                    ])],
                    back_surf=texturing.special.rand('behind'),
                )
                self.brush_faces.append(face)
                yield brush


def get_tile_tex(color, orient, grid_size, pos):
    """Get the appropriate texture name for a tile."""
    return texturing.GROUPS[color, orient].get_tex(grid_size, pos)


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
    bevels=(False, False, False, False),
    u_align=512,
    v_align=512,
) -> Tuple[Solid, Side]:
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
        * bevels: If that side should be 45° angled - in order, umin/max, vmin/max.
    """
    assert TILE_TEMP, "make_tile called without data loaded!"
    template = TILE_TEMP[normal.as_tuple()]

    assert width >= 8 and height >= 8, 'Tile is too small!' \
                                       ' ({}x{})'.format(width, height)

    axis_u, axis_v = Vec.INV_AXIS[normal.axis()]

    top_side = template['front'].copy(map=vmf)  # type: Side
    top_side.mat = top_surf
    top_side.translate(origin - recess_dist * normal)

    block_min = round_grid(origin) - (64, 64, 64)

    top_side.uaxis.offset = 4 * (
        block_min[axis_u] - (origin[axis_u] - width/2)
    ) % u_align
    top_side.vaxis.offset = 4 * (
        block_min[axis_v] - (origin[axis_v] - height/2)
    ) % v_align

    back_side = template['back'].copy(map=vmf)  # type: Side
    back_side.mat = back_surf
    back_side.translate(origin - thickness * normal)


    bevel_umin, bevel_umax, bevel_vmin, bevel_vmax = bevels

    umin_side = template[-1, 0][bevel_umin].copy(map=vmf)
    umin_side.translate(origin + Vec(**{axis_u: -width/2}))

    umax_side = template[1, 0][bevel_umax].copy(map=vmf)
    umax_side.translate(origin + Vec(**{axis_u: width/2}))

    vmin_side = template[0, -1][bevel_vmin].copy(map=vmf)
    vmin_side.translate(origin + Vec(**{axis_v: -height/2}))

    vmax_side = template[0, 1][bevel_vmax].copy(map=vmf)
    vmax_side.translate(origin + Vec(**{axis_v: height/2}))

    for face in [back_side, umin_side, umax_side, vmin_side, vmax_side]:
        face.uaxis.offset %= 512
        face.vaxis.offset %= 512

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
                face.translate(-16 * face_norm - 2 * norm)

        # Flat-side squarebeams...
        for face in rotated_flat:
            face_norm = round(face.get_origin().norm())  # type: Vec
            if face_norm[axis_norm]:
                continue

            face.translate(-16 * face_norm - 2 * norm)
            temp_part[face_norm.other_axes(norm.axis())] = (
                face,
                bevel_sides[face_norm.as_tuple()],
            )


def analyse_map(vmf_file: VMF):
    """Create TileDefs from all the brush sides.

    Once done, all wall brushes have been removed from the map.
    """

    # Face ID -> tileDef, used to match overlays to their face targets.
    # Invalid after we exit, since all the IDs have been freed and may be
    # reused later.
    face_to_tile = {}

    for brush in vmf_file.brushes[:]:
        bbox_min, bbox_max = brush.get_bbox()
        dim = bbox_max - bbox_min
        grid_pos = round_grid(bbox_min)
        if dim == (128, 128, 128):
            tiledefs_from_cube(face_to_tile, brush, grid_pos)
            continue

        norm = Vec()
        for axis in 'xyz':
            if dim[axis] == 4:
                norm[axis] = (-1 if bbox_min[axis] - grid_pos[axis] < 0 else 1)
                break
        else:
            # Has no 4-unit side - not a PeTI brush?
            LOGGER.warning('Unrecognised brush from {} to {}'.format(bbox_min, bbox_max))
            continue

        tile_size = dim.other_axes(norm.axis())
        if tile_size == (128, 128):
            # 128x128x4 block..
            tiledefs_from_large_tile(face_to_tile, brush, grid_pos, norm)
        else:
            # EmbedFace block..
            tiledefs_from_embedface(face_to_tile, brush, grid_pos, norm)

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
    brush.remove()


def tiledefs_from_large_tile(face_to_tile, brush: Solid, grid_pos: Vec, norm: Vec):
    """Generate a tiledef matching a 128x128x4 side."""
    tex_kind, special_tex, front_face = find_front_face(brush, grid_pos, norm)

    neighbour_block = BLOCK_POS['world': grid_pos + 128 * norm]

    if neighbour_block is Block.VOID:
        tex_kind = TileType.NODRAW

    tiledef = TileDef(
        grid_pos,
        norm,
        base_type=tex_kind,
        override_tex=special_tex,
    )
    TILES[grid_pos.as_tuple(), norm.as_tuple()] = tiledef
    brush.map.remove_brush(brush)
    face_to_tile[front_face.id] = tiledef


def tiledefs_from_embedface(
    face_to_tile,
    brush: Solid,
    grid_pos: Vec,
    norm: Vec,
):
    """Generate a tiledef matching EmbedFace brushes."""

    tex_kind, special_tex, front_face = find_front_face(brush, grid_pos, norm)

    norm_axis = norm.axis()

    bbox_min, bbox_max = brush.get_bbox()
    bbox_min[norm_axis] = bbox_max[norm_axis] = 0
    if bbox_min % 32 or bbox_max % 32 or special_tex is not None:
        # Not aligned to grid, leave this here!
        return

    tile = TileDef.ensure(grid_pos, norm)
    face_to_tile[front_face.id] = tile
    brush.remove()

    grid_min = grid_pos - (64, 64, 64)
    u_min, v_min = (bbox_min - grid_min).other_axes(norm_axis)
    u_max, v_max = (bbox_max - grid_min).other_axes(norm_axis)

    u_min, u_max = u_min // 32, u_max // 32 - 1
    v_min, v_max = v_min // 32, v_max // 32 - 1
    for uv in iter_uv(u_min, u_max, v_min, v_max):
        tile.sub_tiles[uv] = tex_kind


def find_front_face(brush, grid_pos, norm):
    """Find the tile face in a brush. Returns color, special_mat, face."""
    for face in brush:
        if -face.normal() != norm:
            continue
        if face.mat in consts.BlackPan:
            return TileType.BLACK, None, face
        elif face.mat in consts.WhitePan:
            return TileType.WHITE, None, face
        else:
            return TileType.BLACK, face.mat, face
    else:
        raise Exception('Malformed wall brush at {}, {}'.format(grid_pos, norm))


def generate_brushes(vmf: VMF):
    """Generate all the brushes in the map, then set overlay sides."""
    for tile in TILES.values():
        brushes = list(tile.export(vmf))
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

