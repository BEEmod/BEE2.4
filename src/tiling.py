"""Generates all tile brushes.

It also tracks overlays assigned to tiles, so we can regenerate all the brushes.
That allows any wall cube to be split into separate brushes, and make quarter-tile patterns.

Note: We also store a list of tiledefs in overlay entities in the map, if
they were attached to the original brushes.
"""
from collections import defaultdict, Counter

from enum import Enum
from typing import (
    Tuple, Dict, List,
    Optional, Union,
    Iterator,
)

import math

import instanceLocs
import utils
import vbsp_options
from srctools import Vec, VMF, Entity, Side, Solid, Output
import srctools.logger
from brushLoc import POS as BLOCK_POS, Block, grid_to_world
from texturing import TileSize, Portalable
import srctools.vmf
import comp_consts as consts
import template_brush
import texturing
import antlines
import grid_optim

LOGGER = srctools.logger.get_logger(__name__)

# Face surfaces used to generate tiles.
# TILE_TEMP[tile_norm][u_norm, v_norm, thickness, is_bevel] = squarebeams_face
# thickness = 2,4,8
# TILE_TEMP[tile_norm]['tile'] = front_face
# TILE_TEMP[tile_norm]['back'] = back_face
TILE_TEMP: Dict[
    Tuple[float, float, float],
    Dict[Union[str, Tuple[int, int, int, bool]], Side]
] = {}

# Maps normals to the index in PrismFace.
PRISM_NORMALS: Dict[Tuple[float, float, float], int] = {
    # 0 = solid
    Vec.top: 1,
    Vec.bottom: 2,
    Vec.north: 3,
    Vec.south: 4,
    Vec.east: 5,
    Vec.west: 6,
}

NORMALS = [Vec(x=1), Vec(x=-1), Vec(y=1), Vec(y=-1), Vec(z=1), Vec(z=-1)]
# Specific angles, these ensure the textures align to world once done.
# IE upright on walls, up=north for floor and ceilings.
NORM_ANGLES = {
    Vec(x=1).as_tuple(): Vec(0, 0, 0),
    Vec(x=-1).as_tuple(): Vec(0, 180, 0),
    Vec(y=1).as_tuple(): Vec(0, 90, 0),
    Vec(y=-1).as_tuple(): Vec(0, 270, 0),
    Vec(z=1).as_tuple(): Vec(270, 270,  0),
    Vec(z=-1).as_tuple(): Vec(90, 90, 0),
}

NORM_NAMES = {
    Vec(x=1).as_tuple(): 'east',
    Vec(x=-1).as_tuple(): 'west',
    Vec(y=1).as_tuple(): 'north',
    Vec(y=-1).as_tuple(): 'South',
    Vec(z=1).as_tuple(): 'up',
    Vec(z=-1).as_tuple(): 'down',
}

# All the tiledefs in the map.
# Maps a block center, normal -> the tiledef on the side of that block.
TILES: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], 'TileDef'] = {}

# Special key for Tile.SubTile - This is set to 'u' or 'v' to
# indicate the center section should be nodrawed.
SUBTILE_FIZZ_KEY = object()

# Given the two bevel options, determine the correct texturing
# values.
# (min, max) -> (scale, offset)
BEVEL_BACK_SCALE = {
    (False, False): 128/512,  # |__|
    (False, True): 124/512,  # |__/
    (True, False): 124/512,  # \__|
    (True, True): 120/512,   # \__/
}


class TileType(Enum):
    """Physical types of geometry for each 1/4 tile."""
    WHITE = 0
    WHITE_4x4 = 1
    BLACK = 2
    BLACK_4x4 = 3

    GOO_SIDE = 4  # Black sides of goo pits.
     
    NODRAW = 10  # Covered, so it should be set to nodraw

    # Air - used for embedFace sections.
    VOID = 11

    # 3 unit recess,  with backpanels or props/plastic behind. 
    # _BROKEN is ignored when allocating patterns - it wasn't there when the 
    #  tiles were installed. 
    # _PARTIAL is not, it's for WIP chambers.
    # If the skybox is 3D, _PARTIAL uses tools/skybox.
    CUTOUT_TILE_BROKEN = 22
    CUTOUT_TILE_PARTIAL = 23
    
    @property
    def is_recess(self) -> bool:
        """Should this recess the surface?"""
        return self.value in (22, 23)
     
    @property   
    def is_nodraw(self) -> bool:
        """Should this swap to nodraw?"""
        return self.value == 10
        
    @property
    def blocks_pattern(self) -> bool:
        """Does this affect patterns?"""
        return self.value != 22
        
    @property
    def is_tile(self) -> bool:
        """Is this a regular tile (white/black)."""
        return self.value < 10
        
    @property
    def is_white(self) -> bool:
        """Is this portalable?"""
        return self.value in (0, 1)

    @property
    def is_4x4(self) -> bool:
        """Is this forced to be 4x4 in size?"""
        return self.value in (1, 3)

    @property
    def color(self) -> texturing.Portalable:
        """The portalability of the tile."""
        if self.value in (0, 1):
            return texturing.Portalable.WHITE
        elif self.value in (2, 3, 4):
            return texturing.Portalable.BLACK
        raise ValueError('No colour for ' + self.name + '!')

    @property
    def inverted(self) -> 'TileType':
        """Swap the color of a type."""
        return _tiletype_inverted.get(self, self)

    @property
    def tile_size(self) -> TileSize:
        """The size of the tile this should force."""
        if self.value in (1, 3):
            return TileSize.TILE_4x4
        else:
            return TileSize.TILE_1x1

    @staticmethod
    def with_color_and_size(
        size: TileSize,
        color: texturing.Portalable
    ) -> 'TileType':
        """Return the TileType with a size and color."""
        return _tiletype_tiles[size, color]

_tiletype_tiles = {
    (TileSize.TILE_1x1, texturing.Portalable.BLACK): TileType.BLACK,
    (TileSize.TILE_1x1, texturing.Portalable.WHITE): TileType.WHITE,
    (TileSize.TILE_4x4, texturing.Portalable.BLACK): TileType.BLACK_4x4,
    (TileSize.TILE_4x4, texturing.Portalable.WHITE): TileType.WHITE_4x4,
}
_tiletype_inverted = {
    TileType.BLACK: TileType.WHITE,
    TileType.WHITE: TileType.BLACK,
    TileType.BLACK_4x4: TileType.WHITE_4x4,
    TileType.WHITE_4x4: TileType.BLACK_4x4,
    TileType.GOO_SIDE: TileType.WHITE_4x4,
}

# Symbols that represent TileSize values.
TILETYPE_TO_CHAR = {
    TileType.WHITE: 'W',
    TileType.WHITE_4x4: 'w',
    TileType.BLACK: 'B',
    TileType.BLACK_4x4: 'b',
    TileType.GOO_SIDE: 'g',
    TileType.NODRAW: 'n',
    TileType.VOID: '.',
    TileType.CUTOUT_TILE_BROKEN: 'x',
    TileType.CUTOUT_TILE_PARTIAL: 'o',
}
TILETYPE_FROM_CHAR: Dict[str, TileType] = {
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


class PanelAngle(Enum):
    """Angles for static angled panels."""
    ANGLE_FLAT = 0  # Start disabled, so it's flat sticking out slightly.
    ANGLE_30 = 30
    ANGLE_45 = 45
    ANGLE_60 = 60
    ANGLE_90 = 90

    @classmethod
    def from_inst(cls, inst: Entity) -> 'PanelAngle':
        """Get the angle desired for a panel."""
        if not inst.fixup.bool('$start_deployed'):
            return cls.ANGLE_FLAT
        # "ramp_90_deg_open" -> 90
        return cls(int(inst.fixup['$animation'][5:7]))


def round_grid(vec: Vec) -> Vec:
    """Round to the center of the grid."""
    return vec // 128 * 128 + (64, 64, 64)


def iter_uv(
    umin: float=0,
    umax: float=3,
    vmin: float=0,
    vmax: float=3
) -> Iterator[Tuple[int, int]]:
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
    def __init__(
        self,
        tex: TileSize,
        *tiles: Tuple[int, int, int, int],
        wall_only=False
    ) -> None:
        self.tex = tex
        self.wall_only = wall_only
        self.tiles = list(tiles)
        tile_u, tile_v = TILE_SIZES[tex]
        # Do some sanity checks on values..
        for umin, vmin, umax, vmax in tiles:
            tile_tex = '{} -> {} {} {} {}'.format(tex, umin, vmin, umax, vmax)
            assert 0 <= umin < umax <= 4, tile_tex
            assert 0 <= vmin < vmax <= 4, tile_tex
            assert (umax - umin) % tile_u == 0, tile_tex
            assert (vmax - vmin) % tile_v == 0, tile_tex
            
    def __repr__(self) -> str:
        return 'Pattern({!r}, {}{}'.format(
            self.tex,
            ','.join(map(repr, self.tiles)),
            ', wall_only=True)' if self.wall_only else ')'
        )


def order_bbox(bbox: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """Used to sort 4x4 pattern positions.

    The pattern order is the order that they're tried in.
    We want to try the largest first so reverse the ordering used on max values.
    """
    umin, vmin, umax, vmax = bbox
    return umin, vmin, -umax, -vmax

PATTERNS: Dict[str, List[Pattern]] = {
    'clean': [
        Pattern(TileSize.TILE_1x1, (0, 0, 4, 4)),
        Pattern(TileSize.TILE_2x1,
            (0, 0, 4, 4),  # Combined
            (0, 0, 2, 4), (2, 0, 4, 4),  # L/R
            (1, 0, 3, 4),  # Middle - only if no left or right.
            wall_only=True,
        ),
        Pattern(
            TileSize.TILE_2x2,
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
    'fizzler_split_u': [],
    'fizzler_split_v': [],
}


def _make_patterns() -> None:
    """Set additional patterns which derive from CLEAN."""
    # These are the same as clean, but they don't allow any pattern
    # which crosses over the centerline in either direction.
    fizz_u = PATTERNS['fizzler_split_u']
    fizz_v = PATTERNS['fizzler_split_v']

    for pat in PATTERNS['clean']:
        pat_u = Pattern(pat.tex, wall_only=pat.wall_only)
        pat_v = Pattern(pat.tex, wall_only=pat.wall_only)
        for tile in pat.tiles:
            umin, vmin, umax, vmax = tile
            if umin >= 2 or umax <= 2:
                pat_u.tiles.append(tile)
            if vmin >= 2 or vmax <= 2:
                pat_v.tiles.append(tile)
        if pat_u.tiles:
            fizz_u.append(pat_u)
        if pat_v.tiles:
            fizz_v.append(pat_v)

_make_patterns()


class TileDef:
    """Represents one 128 block side.
    
    Attributes:
        pos: Vec for the center of the block.
        normal: The direction out of the block.
        brush_faces: A list of brush faces which this tiledef has exported.
          Empty before-hand, but after these are faces to attach antlines to.
        brush_type: BrushType - what sort of brush this is.
        base_type: TileSize this tile started with.
        override: If set, a specific texture to use. (skybox, light,
        backpanels etc)
        _sub_tiles: None or a Dict[(u,v): TileSize]. u/v are either xz,
        yz or xy.
          If None, it's the same as base_type.
        bullseye_count: The number of bullseye items on this surface. If > 0,
          we have some.
        _portal_helper: The number of portal placement helpers here. If > 0,
          a non-anglesnap helper is present. If a Vector instead, a forced
          helper is present pointing this direction.
        panel_inst: The instance for this panel, if it's a panel brush_type.
        panel_ent: The brush entity for the panel, if it's a panel brush_type.
    """
    __slots__ = [
        'pos',
        'normal',
        'brush_type',
        'brush_faces',
        'base_type',
        '_sub_tiles',
        'override',
        'bullseye_count',
        '_portal_helper',
        'panel_inst',
        'panel_ent',
    ]

    pos: Vec
    normal: Vec
    base_type: TileType

    brush_faces: List[Side]
    brush_type: BrushType
    _sub_tiles: Optional[Dict[Tuple[int, int], TileType]]
    override: Optional[Tuple[str, 'template_brush.ScalingTemplate']]

    bullseye_count: int
    _portal_helper: Union[int, Vec]

    panel_inst: Optional[Entity]
    panel_ent: Optional[Entity]

    def __init__(
        self,
        pos: Vec, 
        normal: Vec,
        base_type: TileType,
        brush_type: BrushType=BrushType.NORMAL,
        subtiles: Dict[Tuple[int, int], TileType]=None,
        panel_inst: Entity=None,
        panel_ent: Entity=None,
        has_helper: bool=False,
    ) -> None:
        self.pos = pos
        self.normal = normal
        self.brush_type = brush_type
        self.brush_faces = []
        self.override = None
        self.base_type = base_type
        self._sub_tiles = subtiles
        self.panel_inst = panel_inst
        self.panel_ent = panel_ent
        self.bullseye_count = 0
        self._portal_helper = 1 if has_helper else 0

    @property
    def has_portal_helper(self) -> bool:
        """Check if the portal helper is present."""
        return isinstance(self._portal_helper, Vec) or self._portal_helper != 0

    @property
    def has_oriented_portal_helper(self) -> bool:
        """Check if we have a portal helper with a specific direction."""
        return isinstance(self._portal_helper, Vec)

    @property
    def portal_helper_orient(self) -> Vec:
        """Return the direction of the 'top' of the portal helper."""
        if isinstance(self._portal_helper, Vec):
            return self._portal_helper
        elif self.normal.z == 0:
            # Wall, upward.
            return Vec(0, 0, 1)
        else:
            # floor/ceiling, any direction. So just specify +X.
            return Vec(1, 0, 0)

    def __repr__(self) -> str:
        return '<{}, {} TileDef @ {} of {}>'.format(
            self.base_type.name,
            self.brush_type.name,
            NORM_NAMES.get(self.normal.as_tuple(), self.normal),
            self.pos,
        )

    def print_tiles(self) -> None:
        """Debug utility, log the subtile shape."""
        out = []
        for v in reversed(range(4)):
            for u in range(4):
                out.append(TILETYPE_TO_CHAR[self[u, v]])
            out.append('\n')
        LOGGER.info('Subtiles: \n{}', ''.join(out))

    @classmethod
    def ensure(
        cls,
        grid_pos: Vec,
        norm: Vec,
        tile_type: TileType=TileType.VOID,
    ) -> 'TileDef':
        """Return a tiledef at a position, creating it with a type if not present."""
        try:
            tile = TILES[grid_pos.as_tuple(), norm.as_tuple()]
        except KeyError:
            tile = TILES[grid_pos.as_tuple(), norm.as_tuple()] = cls(
                grid_pos,
                norm,
                tile_type,
            )
        return tile

    def _get_subtiles(self) -> Dict[Tuple[int, int], TileType]:
        """Returns subtiles, creating it if not present."""
        if self._sub_tiles is None:
            self._sub_tiles = tile = {
                (x, y): self.base_type
                for x in range(4) for y in range(4)
            }
            return tile
        else:
            return self._sub_tiles

    def __getitem__(self, item: Tuple[int, int]) -> TileType:
        """Lookup the tile type at a particular sub-location."""
        u, v = item
        if u not in (0, 1, 2, 3) or v not in (0, 1, 2, 3):
            raise IndexError(u, v)
        
        if self._sub_tiles is None:
            return self.base_type
        else:
            return self._sub_tiles[u, v]

    def __setitem__(self, item: Tuple[int, int], value: TileType) -> None:
        """Lookup the tile type at a particular sub-location."""
        u, v = item
        if u not in (0, 1, 2, 3) or v not in (0, 1, 2, 3):
            raise IndexError(u, v)
        
        if self._sub_tiles is None:
            self._sub_tiles = {
                (x, y): value if u == x and v == y else self.base_type
                for x in range(4) for y in range(4)
            }
        else:
            self._sub_tiles[u, v] = value
            
            if SUBTILE_FIZZ_KEY not in self._sub_tiles:
                # Check if we can merge this down to a single value.
                try:
                    [base_type] = set(self._sub_tiles.values())
                except ValueError:
                    pass
                else:
                    self.base_type = base_type
                    self._sub_tiles = None

    def __iter__(self) -> Iterator[Tuple[int, int, TileType]]:
        """Iterate over the axes and tile type."""
        for u in range(4):
            for v in range(4):
                # Check each time, in case users modify while iterating.
                if self._sub_tiles is None:
                    yield u, v, self.base_type
                else:
                    yield u, v, self._sub_tiles[u, v]

    def set_fizz_orient(self, axis: str) -> None:
        """Set the centered fizzler nodraw strip."""
        # This violates the _sub_tiles type definition.
        self._get_subtiles()[SUBTILE_FIZZ_KEY] = axis  # type: ignore

    def uv_offset(self, u: float, v: float, norm: float) -> Vec:
        """Return a u/v offset from our position.

        This is used for subtile orientations:
            norm is in the direction of the normal.
            If norm is x, uv = yz.
            If norm is y, uv = xz.
            If norm is z, uv = xy.
        """
        pos = self.pos.copy()
        u_ax, v_ax = Vec.INV_AXIS[self.normal.axis()]
        pos += self.normal * norm
        pos[u_ax] += u
        pos[v_ax] += v
        return pos

    def bind_overlay(self, over: Entity) -> None:
        """Bind the overlay to this tiledef.

        When the tiles are exported the overlay will be
        adjusted to include the face IDs.
        """
        try:
            overlays = over.tiledefs  # type: ignore
        except AttributeError:
            overlays = over.tiledefs = []  # type: ignore
        overlays.append(self)

    def calc_patterns(
        self,
        tiles: Dict[Tuple[int, int], TileType],
        is_wall: bool=False,
        _pattern: str=None,
    ) -> Iterator[Tuple[float, float, float, float, TileSize, TileType]]:
        """Figure out the brushes needed for a complex pattern.

        This yields (umin, umax, vmin, vmax, grid_size_, tile_type) tuples.
        """

        # copy it, so we can overwrite positions with VOID = not a tile.
        tiles = tiles.copy()

        # Don't check for special types if one is passed - that prevents
        # infinite recursion.
        if not _pattern:
            _pattern = 'clean'
            if SUBTILE_FIZZ_KEY in tiles:  # type: ignore
                # Output the split patterns for centered fizzlers.
                # We need to remove it also so our iteration doesn't choke on it.
                # 'u' or 'v'
                split_type: str
                split_type = tiles.pop(SUBTILE_FIZZ_KEY) # type: ignore
                patterns = self.calc_patterns(
                    tiles,
                    is_wall,
                    'fizzler_split_' + split_type,
                )
                # Loop through our output and adjust the centerline outward.
                if split_type == 'u':
                    for umin, umax, vmin, vmax, grid_size, tile_type in patterns:
                        if umin == 2:
                            umin = 2.5
                        if umax == 2:
                            umax = 1.5
                        yield umin, umax, vmin, vmax, grid_size, tile_type
                    # Now yield the nodraw-brush.
                    yield 1.5, 2.5, 0, 4, TileSize.TILE_4x4, TileType.NODRAW
                elif split_type == 'v':
                    for umin, umax, vmin, vmax, grid_size, tile_type in patterns:
                        if vmin == 2:
                            vmin = 2.5
                        if vmax == 2:
                            vmax = 1.5
                        yield umin, umax, vmin, vmax, grid_size, tile_type
                    # Now yield the nodraw-brush.
                    yield 0, 4, 1.5, 2.5, TileSize.TILE_4x4, TileType.NODRAW
                return  # Don't run our checks on the tiles.

        for pattern in PATTERNS[_pattern]:
            if pattern.wall_only and not is_wall:
                continue
            for umin, vmin, umax, vmax in pattern.tiles:
                tile_type = tiles[umin, vmin]
                for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                    if tiles[uv] is not tile_type:
                        break
                else:
                    for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                        tiles[uv] = TileType.VOID
                    yield umin, umax, vmin, vmax, pattern.tex, tile_type

        # All unfilled spots are single 4x4 tiles, or other objects.
        for (u, v), tile_type in tiles.items():  # type: ignore  # SUBTILE_FIZZ_KEY
            if tile_type is not TileType.VOID:
                yield u, u + 1, v, v + 1, TileSize.TILE_4x4, tile_type

    def should_bevel(self, u: int, v: int) -> bool:
        """Check if this side of the TileDef should be bevelled.

        U and V should be 1 or -1.
        """
        if BLOCK_POS['world': self.uv_offset(128*u, 128*v, 0)].inside_map:
            return True

        u_ax, v_ax = Vec.INV_AXIS[self.normal.axis()]
        side_norm = Vec.with_axes(u_ax, u, v_ax, v)

        try:
            tiledef = TILES[self.pos.as_tuple(), side_norm.as_tuple()]
        except KeyError:
            return False

        return tiledef.base_type is not TileType.VOID

    def can_portal(self) -> bool:
        """Check if this tile could be portalled (in the center)."""

        # If any of the middle 2x2 are black, then nope.
        if (
            not self[1, 1].is_white or not self[1, 2].is_white or
            not self[2, 1].is_white or not self[2, 2].is_white
        ):
            return False

        # If the top and bottom is white, you can always fit a portal.
        if (
            self[1, 0].is_white and self[2, 1].is_white and
            self[3, 0].is_white and self[3, 1].is_white
        ):
            return True

        # Finally, for floors/ceilings you can place it 'sideways'.
        return (
            self.normal.z != 0 and
            self[0, 1].is_white and self[0, 2].is_white and
            self[3, 1].is_white and self[3, 2].is_white
        )

    def export(self, vmf: VMF) -> None:
        """Create the brushes for this.

        This is only called on special tiles with different patterns,
        or which have items modifying them.
        """
        bevels: Tuple[bool, bool, bool, bool] = (
            self.should_bevel(-1, 0),
            self.should_bevel(+1, 0),
            self.should_bevel(0, -1),
            self.should_bevel(0, +1),
        )

        front_pos = self.pos + 64 * self.normal

        is_wall = self.normal.z == 0

        if self.has_oriented_portal_helper:
            force_helper = True
            has_helper = True
        elif self.has_portal_helper and self.can_portal():
            force_helper = False
            has_helper = True
        else:
            force_helper = has_helper = False

        # If all four center blocks can't accept the overlay,
        # we can't add a bullseye.
        if (
            self[1, 1].is_tile or not self[1, 2].is_tile or
            self[2, 1].is_tile or not self[2, 2].is_tile
        ):
            has_bullseye = self.bullseye_count > 0
        else:
            has_bullseye = False

        if self._sub_tiles is None:
            # Force subtiles to be all the parts we need.
            self._sub_tiles = dict.fromkeys(iter_uv(), self.base_type)

        if self.brush_type is BrushType.NORMAL:
            faces, brushes = self.gen_multitile_pattern(
                vmf,
                self._sub_tiles,
                is_wall,
                bevels,
                self.normal,
            )
            self.brush_faces.extend(faces)
            vmf.add_brushes(brushes)

            if has_helper:
                # We need to make a placement helper.
                vmf.create_ent(
                    'info_placement_helper',
                    angles=self.normal.to_angle_roll(self.portal_helper_orient),
                    origin=front_pos,
                    force_placement=int(force_helper),
                    snap_to_helper_angles=int(force_helper),
                    radius=64,
                )
            if has_bullseye:
                # Add the bullseye overlay.
                angles = self.normal.to_angle()
                srctools.vmf.make_overlay(
                    vmf,
                    self.normal,
                    front_pos,
                    Vec(y=64).rotate(*angles),
                    Vec(z=64).rotate(*angles),
                    texturing.OVERLAYS.get(front_pos, 'bullseye'),
                    self.brush_faces,
                )

        elif self.brush_type is BrushType.ANGLED_PANEL:
            assert self.panel_inst is not None
            assert self.panel_ent is not None

            if self.panel_inst.fixup.int('$connectioncount') > 0:
                # Dynamic panels are always beveled.
                bevels = (True, True, True, True)
                static_angle = None
                thickness = vbsp_options.get(int, 'dynamic_pan_thickness')
            else:
                # Static panels can be flat on the sides since they don't need
                # to actually retract..
                bevels = (False, False, False, False)
                static_angle = PanelAngle.from_inst(self.panel_inst)
                thickness = vbsp_options.get(int, 'static_pan_thickness')

            panel_angles = Vec.from_str(self.panel_inst['angles'])
            hinge_axis = Vec(y=1).rotate(*panel_angles)
            front_normal = Vec(x=1).rotate(*panel_angles)

            # For static 90 degree panels, we want to generate as if it's
            # in that position - that way we get the right textures.
            if static_angle is PanelAngle.ANGLE_90:
                faces, brushes = self.gen_multitile_pattern(
                    vmf,
                    self._sub_tiles,
                    is_wall=front_normal.z == 0,
                    bevels=bevels,
                    normal=-front_normal,
                    vec_offset=64 * self.normal - 64 * front_normal,
                    thickness=thickness,
                    is_panel=True,
                )
                if has_bullseye:
                    # Add the bullseye overlay.
                    angles = (-front_normal).to_angle()
                    srctools.vmf.make_overlay(
                        vmf,
                        -front_normal,
                        self.pos + 128 * self.normal - 64 * front_normal,
                        Vec(y=64).rotate(*angles),
                        Vec(z=64).rotate(*angles),
                        texturing.OVERLAYS.get(front_pos, 'bullseye'),
                        faces,
                    )

                if has_helper:
                    # We need to make a placement helper.
                    if force_helper:
                        helper_angles = (-front_normal).to_angle_roll(self.normal)
                    else:
                        helper_angles = (-front_normal).to_angle()
                    vmf.create_ent(
                        'info_placement_helper',
                        angles=helper_angles,
                        origin=self.pos + 128 * self.normal - 64 * front_normal,
                        force_placement=int(force_helper),
                        snap_to_helper_angles=int(force_helper),
                        radius=96,
                    )
            else:
                faces, brushes = self.gen_multitile_pattern(
                    vmf,
                    self._sub_tiles,
                    is_wall,
                    bevels,
                    self.normal,
                    offset=(64+8 if static_angle is PanelAngle.ANGLE_FLAT else 64),
                    thickness=(8 if static_angle is PanelAngle.ANGLE_FLAT else thickness),
                    is_panel=True,
                )
            self.panel_ent.solids.extend(brushes)

            if static_angle is None or static_angle is PanelAngle.ANGLE_90:
                # Dynamic panel, do nothing.
                # 90 degree panels don't rotate either.
                pass
            elif static_angle is PanelAngle.ANGLE_FLAT:
                # Make it a func_detail.
                self.panel_ent.keys = {'classname': 'func_detail'}
                # Add nodraw behind to seal.
                brush, face = make_tile(
                    vmf,
                    self.pos + self.normal * 64,
                    self.normal,
                    top_surf=consts.Tools.NODRAW,
                    width=128,
                    height=128,
                    bevels=(True, True, True, True),
                    back_surf=texturing.SPECIAL.get(self.pos, 'behind'),
                )
                vmf.add_brush(brush)

                if has_helper:
                    # We need to make a placement helper.
                    vmf.create_ent(
                        'info_placement_helper',
                        angles=self.normal.to_angle_roll(self.portal_helper_orient),
                        origin=front_pos + 8 * self.normal,
                        force_placement=int(force_helper),
                        snap_to_helper_angles=int(force_helper),
                        radius=64,
                    )

                if has_bullseye:
                    # Add the bullseye overlay.
                    angles = self.normal.to_angle()
                    srctools.vmf.make_overlay(
                        vmf,
                        self.normal,
                        front_pos + 8 * self.normal,
                        Vec(y=64).rotate(*angles),
                        Vec(z=64).rotate(*angles),
                        texturing.OVERLAYS.get(front_pos, 'bullseye'),
                        faces,
                    )
            else:
                # This is a static rotated panel.
                self.panel_ent.keys = {'classname': 'func_detail'}

                # Rotate the panel to match the panel shape:
                # Figure out if we want to rotate +ve or -ve.
                # We know rotating the surface 90 degrees will point
                # the end straight up, so check if it points at the normal.
                maybe_rotate = Vec(x=1).rotate(*hinge_axis.rotation_around()) == self.normal

                # This direction is inverted...
                if front_normal == (-1, 0, 0):
                    maybe_rotate = not maybe_rotate

                if maybe_rotate:
                    rotation = hinge_axis.rotation_around(static_angle.value)
                else:
                    rotation = hinge_axis.rotation_around(-static_angle.value)

                # Shift so the rotation axis is 0 0 0, then shift back
                # to rotate correctly.
                panel_offset = front_pos - 64 * front_normal

                # Rotating like this though will make the brush clip into the
                # surface it's attached on. We need to clip the hinge edge
                # so it doesn't do that.
                # We can just produce any plane that is the correct
                # orientation and let VBSP sort out the geometry.

                # So construct a box, and grab the side pointing "down".
                clip_template: Side = vmf.make_prism(
                    self.pos + 64 + 128 * self.normal,
                    self.pos - 64 + 128 * self.normal,
                )[PRISM_NORMALS[(-self.normal).as_tuple()]]

                front_axis = front_normal.axis()

                for brush in brushes:
                    clip_face = None
                    for face in brush:
                        if (
                            face.normal() == front_normal
                            and face.get_origin()[front_axis]
                            == panel_offset[front_axis]
                        ):
                            clip_face = face
                            break
                    brush.localise(-panel_offset)
                    brush.localise(panel_offset, rotation)
                    if clip_face is not None:
                        clip_face.uaxis = clip_template.uaxis.copy()
                        clip_face.vaxis = clip_template.vaxis.copy()
                        clip_face.planes = [p.copy() for p in clip_template.planes]
                        clip_face.mat = consts.Tools.NODRAW

                # Helpfully the angled surfaces are always going to be forced
                # upright, so we don't need to compute the orientation matching
                # the item axis.
                angled_normal = self.normal.copy().rotate(*rotation)
                top_center = (
                    (64 * front_normal).rotate(*rotation) -
                    64 * front_normal +
                    front_pos
                )

                if has_helper:
                    # We need to make a placement helper.
                    vmf.create_ent(
                        'info_placement_helper',
                        angles=angled_normal.to_angle(),
                        origin=top_center,
                        force_placement=int(force_helper),
                        snap_to_helper_angles=int(force_helper),
                        radius=64,
                    )

                if has_bullseye:
                    # Add the bullseye overlay.
                    angles = self.normal.to_angle()
                    srctools.vmf.make_overlay(
                        vmf,
                        self.normal,
                        top_center,
                        (64 * front_normal).rotate(*rotation),
                        (64 * hinge_axis),
                        texturing.OVERLAYS.get(front_pos, 'bullseye'),
                        faces,
                    )

        elif self.brush_type is BrushType.FLIP_PANEL:
            assert self.panel_inst is not None
            assert self.panel_ent is not None

            # Two surfaces, forward and backward - each is 4 thick.
            invert_black = self.panel_inst.fixup.bool('$start_reversed')
            inv_subtiles = {
                uv: (
                    tile_type.inverted
                    if invert_black or tile_type.color is Portalable.WHITE else
                    tile_type
                ) for uv, tile_type in self._sub_tiles.items()
            }
            front_faces, brushes = self.gen_multitile_pattern(
                vmf,
                self._sub_tiles,
                is_wall,
                (False, False, False, False),
                self.normal,
                add_bullseye=has_bullseye,
            )
            self.panel_ent.solids.extend(brushes)
            back_faces, brushes = self.gen_multitile_pattern(
                vmf,
                inv_subtiles,
                is_wall,
                (False, False, False, False),
                -self.normal,
                offset=64-8,
                add_bullseye=has_bullseye,
            )
            self.panel_ent.solids.extend(brushes)
            inset_flip_panel(self.panel_ent, front_pos, self.normal)

            # Allow altering the flip panel sounds.
            self.panel_ent['noise1'] = vbsp_options.get(str, 'flip_sound_start')
            self.panel_ent['noise2'] = vbsp_options.get(str, 'flip_sound_stop')

            if self.has_portal_helper:
                # We need to make a placement helper. Don't check portalability
                # since the panel can change. On a flip panel,
                # we don't want to parent so it is always on the front side.
                vmf.create_ent(
                    'info_placement_helper',
                    angles=self.normal.to_angle_roll(self.portal_helper_orient),
                    origin=front_pos,
                    force_placement=int(force_helper),
                    snap_to_helper_angles=int(force_helper),
                    attach_target_name=self.panel_ent['targetname'],
                    radius=64,
                )

    def gen_multitile_pattern(
        self,
        vmf: VMF,
        pattern: Dict[Tuple[int, int], TileType],
        is_wall: bool,
        bevels: Tuple[bool, bool, bool, bool],
        normal: Vec,
        offset: int=64,
        thickness: int=4,
        vec_offset: Vec=None,
        is_panel: bool=False,
        add_bullseye: bool=False,
        face_output: Optional[Dict[Tuple[int, int], Side]]=None,
    ) -> Tuple[List[Side], List[Solid]]:
        """Generate a bunch of tiles, and return the front faces.

        This does the complex job of generating a surface with multiple
        tile types.
        
        If face_output is set, it will be filled with (u, v) -> top face.
        """
        brushes = []
        faces = []

        def neighbour_empty(u: int, v: int) -> bool:
            """For bevelling, check if this neighbour is VOID. If out of this tile ignore."""
            if 0 <= u < 4 and 0 <= v < 4:
                return pattern[u, v] is TileType.VOID
            return False

        # NOTE: calc_patterns can produce 0, 1, 1.5, 2, 2.5, 3, 4!
        # Half-values are for nodrawing fizzlers which are center-aligned.
        for umin, umax, vmin, vmax, grid_size, tile_type in self.calc_patterns(pattern, is_wall):
            # We bevel only the grid-edge tiles, or ones adjacent to VOID.
            # The first equality check ensures we don't go out of bounds in the
            # genexp lookups.
            u_range = range(max(int(umin), 0), min(int(umax), 4))
            v_range = range(max(int(vmin), 0), min(int(vmax), 4))

            tile_bevels = (
                bevels[0] if umin == 0 else
                any(neighbour_empty(int(umin)-1, i) for i in v_range),
                bevels[1] if umax == 4 else
                any(neighbour_empty(int(umax), i) for i in v_range),
                bevels[2] if vmin == 0 else
                any(neighbour_empty(i, int(vmin)-1) for i in u_range),
                bevels[3] if vmax == 4 else
                any(neighbour_empty(i, int(vmax)) for i in u_range),
            )

            # Check if this tile needs to use a bullseye material.
            tile_is_bullseye = add_bullseye and not (
                umin > 2 or vmin > 2 or
                umax < 1 or vmax < 1
            )
            gen_cat = (
                texturing.GenCat.BULLSEYE
                if tile_is_bullseye else
                texturing.GenCat.NORMAL
            )

            tile_center = self.uv_offset(
                (umin + umax) * 16 - 64,
                (vmin + vmax) * 16 - 64,
                offset,
            )
            if vec_offset is not None:
                tile_center += vec_offset

            if tile_type.is_tile:
                if tile_type is TileType.GOO_SIDE:
                    # This forces a specific size.
                    u_size = v_size = 4
                    tex = texturing.gen(
                        gen_cat, normal, Portalable.BLACK
                    ).get(tile_center, TileSize.GOO_SIDE)
                else:
                    if tile_type.is_4x4:
                        grid_size = TileSize.TILE_4x4
                    u_size, v_size = TILE_SIZES[grid_size]
                    tex = texturing.gen(
                        gen_cat, normal, tile_type.color,
                    ).get(tile_center, grid_size)
                brush, face = make_tile(
                    vmf,
                    tile_center,
                    normal,
                    top_surf=tex,
                    width=(umax - umin) * 32,
                    height=(vmax - vmin) * 32,
                    bevels=tile_bevels,
                    back_surf=texturing.SPECIAL.get(tile_center, 'behind'),
                    u_align=u_size * 128,
                    v_align=v_size * 128,
                    thickness=thickness,
                    panel_edge=is_panel,
                )
                faces.append(face)
                brushes.append(brush)

                # With the fizzler offsets, we need to recalculate their
                # positions.
                # We want to crop them, not offset.
                # These are always aligned to a 64-block boundary, so we
                # can just slam them to zero.
                if umin != round(umin):
                    face.uaxis.offset = 0
                if vmin != round(vmin):
                    face.vaxis.offset = 0

            elif tile_type is TileType.NODRAW:
                brush, face = make_tile(
                    vmf,
                    tile_center,
                    normal,
                    top_surf=consts.Tools.NODRAW,
                    width=(umax - umin) * 32,
                    height=(vmax - vmin) * 32,
                    bevels=bevels,
                    back_surf=texturing.SPECIAL.get(tile_center, 'behind'),
                    panel_edge=is_panel,
                )
                faces.append(face)
                brushes.append(brush)
            elif tile_type is TileType.VOID:
                continue
            else:
                raise AssertionError("Can't gen {} yet.".format(tile_type))

            if face_output is not None:
                for u in u_range:
                    for v in v_range:
                        if 0 <= u < 4 and 0 <= v < 4:
                            face_output[u, v] = face
        return faces, brushes

    def can_merge(self) -> bool:
        """Check if this tile is a simple tile that can merge with neighbours."""
        if (
            self._sub_tiles is not None or
            self.panel_ent is not None or
            self.panel_inst is not None or
            self.bullseye_count > 0
        ):
            return False

        if (
            self.brush_type is not BrushType.NORMAL and
            self.brush_type is not BrushType.NODRAW
        ):
            return False

        return self.base_type.is_tile

    def add_portal_helper(self, orient: Vec=None) -> None:
        """Add a portal placement helper to the tile.

        If orient is provided, it should be the direction towards the
        top of the portal.
        """
        # Specific direction overrides everything.
        if orient is not None:
            if self.normal.dot(orient) != 0:
                raise ValueError(
                    'Portal orient of {} is not flat on a '
                    'plane with normal of {}!',
                    orient, self.normal,
                )
            self._portal_helper = orient
        elif isinstance(self._portal_helper, int):
            self._portal_helper += 1
        # else: it's already a Vec, so don't override with a generic helper.

    def remove_portal_helper(self) -> None:
        """Remove a single "generic" placement helper.

        Specifically applied orients are never removed.
        """
        # Clamp at zero.
        if isinstance(self._portal_helper, int):
            self._portal_helper = max(0, self._portal_helper - 1)

    def position_bullseye(self, target: Entity) -> None:
        """Position a faith plate target to hit this panel.

        This needs to set origin and targetname.
        """
        if self.brush_type is BrushType.ANGLED_PANEL:
            assert self.panel_inst is not None
            assert self.panel_ent is not None

            if self.panel_inst.fixup.int('$connectioncount') != 0:
                target['origin'] = self.pos + 64 * self.normal
                target['parentname'] = self.panel_ent['targetname']
                target['targetname']  = (
                    self.panel_inst['targetname'] +
                    '-bullseye_target'
                )
                # Everything else uses a generic name.
                return

            static_angle = PanelAngle.from_inst(self.panel_inst)
            if static_angle is PanelAngle.ANGLE_FLAT:
                target['origin'] = self.pos + 68 * self.normal
            else:
                panel_top = Vec(
                    x=-64 + 64 * math.cos(math.radians(static_angle.value)),
                    z=-64 + 64 * math.sin(math.radians(static_angle.value)),
                )
                panel_top.localise(
                    Vec.from_str(self.panel_inst['origin']),
                    Vec.from_str(self.panel_inst['angles']),
                )
                target['origin'] = panel_top
        else:
            # Otherwise, flat on the surface.
            target['origin'] = self.pos + 64 * self.normal

        target['targetname'] = 'faith_target_'
        target.make_unique()


def find_tile(origin: Vec, normal: Vec, force: bool=False) -> Tuple[TileDef, int, int]:
    """Locate the tiledef for a specific tile.

    The tiledef and the subtile UV are returned, or KeyError is raised
    if the position has no tile. If force is true, create a tile at this location.
    """
    norm_axis = normal.axis()
    u_axis, v_axis = Vec.INV_AXIS[norm_axis]

    grid_pos = round_grid(origin - normal)

    uv_pos = (origin - grid_pos + 64 - 16)
    u = uv_pos[u_axis] // 32 % 4
    v = uv_pos[v_axis] // 32 % 4

    if u != round(u) or v != round(v):
        raise KeyError('Badly offset into a tile!')

    if force:
        tile = TileDef.ensure(grid_pos, normal)
    else:
        tile = TILES[grid_pos.as_tuple(), normal.as_tuple()]
        # except KeyError: raise

    return tile, int(u), int(v)


def edit_quarter_tile(
    origin: Vec,
    normal: Vec,
    tile_type: TileType,
    force: bool=False,
    silent: bool=False,
):
    """Alter a 1/4 tile section of a tile.

    If force is True, this overwrites any existing tile - by default nodraw
    prevents being set back to a tile, etc. It'll also create the tile.
    If silent is True, no warning is given when the tile is missing.
    """

    try:
        tile, u, v = find_tile(origin, normal, force)
    except KeyError:
        if not silent:
            LOGGER.warning(
                'Expected tile, but none found: {}, {}',
                origin,
                normal,
            )
        return

    old_tile = tile[u, v]

    if force:
        tile[u, v] = tile_type
        return

    # Don't replace void spaces with other things
    if old_tile is TileType.VOID:
        return

    # If nodrawed, don't revert for tiles.
    if old_tile is TileType.NODRAW and tile_type.is_tile:
        return

    # Don't regress goo sides to other types of black tile.
    if old_tile is TileType.GOO_SIDE and (
        tile_type is TileType.BLACK or tile_type is TileType.BLACK_4x4
    ):
        return

    tile[u, v] = tile_type


def make_tile(
    vmf: VMF,
    origin: Vec, 
    normal: Vec, 
    top_surf: str,
    back_surf: str=consts.Tools.NODRAW.value,
    *,
    recess_dist: int=0,
    thickness: int=4,
    width: float=16,
    height: float=16,
    bevels: Tuple[bool, bool, bool, bool]=(False, False, False, False),
    panel_edge: bool=False,
    u_align: int=512,
    v_align: int=512,
) -> Tuple[Solid, Side]:
    """Generate a tile. 
    
    This uses UV coordinates, which equal xy, xz, or yz depending on normal.
    
    Parameters:
        vmf: The map to add the tile to.
        origin: Location of the center of the tile, on the block surface.
        normal: Unit vector pointing out of the tile.
        top_surf: Texture to apply to the front of the tile.
        back_surf: Texture to apply to the back of the tile.
        recess_dist: How far the front is below the block surface.
        thickness: How far back the back surface is. This can
            be either 2, 4 or 8.
            Must be larger than the recess_dist.
        width: size in the U-direction. Must be > 8.
        height: size in the V-direction. Must be > 8.
        bevels: If that side should be 45° angled - in order,
            umin, umax, vmin, vmax.
        panel_edge: If True, use the panel-type squarebeams.
        u_align: Wrap offsets to this much at maximum.
        v_align: Wrap offsets to this much at maximum.
    """
    assert TILE_TEMP, "make_tile called without data loaded!"
    template = TILE_TEMP[normal.as_tuple()]

    assert width >= 8 and height >= 8, 'Tile is too small!' \
                                       ' ({}x{})'.format(width, height)
    assert thickness in (2, 4, 8), 'Bad thickness {}'.format(thickness)

    axis_u, axis_v = Vec.INV_AXIS[normal.axis()]

    top_side = template['front'].copy(vmf_file=vmf)
    top_side.mat = top_surf
    top_side.translate(origin - recess_dist * normal)

    block_min = round_grid(origin) - (64, 64, 64)

    top_side.uaxis.offset = 4 * (
        block_min[axis_u] - (origin[axis_u] - width/2)
    ) % u_align
    top_side.vaxis.offset = 4 * (
        block_min[axis_v] - (origin[axis_v] - height/2)
    ) % v_align

    bevel_umin, bevel_umax, bevel_vmin, bevel_vmax = bevels

    back_side = template['back'].copy(vmf_file=vmf)
    back_side.mat = back_surf
    # The offset was set to zero in the original we copy from.
    back_side.uaxis.scale = BEVEL_BACK_SCALE[bevel_umin, bevel_umax]
    back_side.vaxis.scale = BEVEL_BACK_SCALE[bevel_vmin, bevel_vmax]
    # Shift the surface such that it's aligned to the minimum edge.
    back_side.translate(origin - normal * thickness + Vec.with_axes(
        axis_u, 4 * bevel_umin - 64,
        axis_v, 4 * bevel_vmin - 64,
    ))

    umin_side = template[-1, 0, thickness, bevel_umin].copy(vmf_file=vmf)
    umin_side.translate(origin + Vec.with_axes(axis_u, -width/2))

    umax_side = template[1, 0, thickness, bevel_umax].copy(vmf_file=vmf)
    umax_side.translate(origin + Vec.with_axes(axis_u, width/2))

    vmin_side = template[0, -1, thickness, bevel_vmin].copy(vmf_file=vmf)
    vmin_side.translate(origin + Vec.with_axes(axis_v, -height/2))

    vmax_side = template[0, 1, thickness, bevel_vmax].copy(vmf_file=vmf)
    vmax_side.translate(origin + Vec.with_axes(axis_v, height/2))

    for face in [umin_side, umax_side, vmin_side, vmax_side]:
        face.uaxis.offset %= 512
        face.vaxis.offset = 0

    # A bit of a hack, this ensures the textures ignore the 32-unit offsets
    # in subtile shapes.
    back_side.uaxis.offset %= 512
    back_side.vaxis.offset %= 512

    edge_name = 'panel_edge' if panel_edge else 'edge'

    umin_side.mat = texturing.SPECIAL.get(origin, edge_name)
    umax_side.mat = texturing.SPECIAL.get(origin, edge_name)
    vmin_side.mat = texturing.SPECIAL.get(origin, edge_name)
    vmax_side.mat = texturing.SPECIAL.get(origin, edge_name)

    return Solid(vmf, sides=[
        top_side, back_side,
        umin_side, umax_side,
        vmin_side, vmax_side,
    ]), top_side


def gen_tile_temp() -> None:
    """Generate the sides used to create tiles.

    This populates TILE_TEMP with pre-rotated solids in each direction,
     with each side identified.
    """

    categories: Dict[Tuple[int, bool], Solid] = {}
    cat_names = {
        (2, True): 'bevel_thin',
        (4, True): 'bevel_norm',
        (8, True): 'bevel_thick',

        (2, False): 'flat_thin',
        (4, False): 'flat_norm',
        (8, False): 'flat_thick',
    }

    try:
        template = template_brush.get_template('__TILING_TEMPLATE__')
        # Grab the single world brush for each visgroup.
        for (key, name) in cat_names.items():
            world, detail, over = template.visgrouped(name)
            [categories[key]] = world
    except (KeyError, ValueError):
        raise Exception('Bad Tiling Template!')

    for norm_tup, angles in NORM_ANGLES.items():
        norm = Vec(norm_tup)
        axis_norm = norm.axis()

        temp_part: Dict[Union[str, Tuple[int, int, int, bool]], Side] = {}
        TILE_TEMP[norm_tup] = temp_part

        for ((thickness, bevel), temp) in categories.items():
            brush = temp.copy()
            brush.localise(Vec(), angles)

            for face in brush:
                if face.mat == consts.Special.BACKPANELS:
                    # Only copy the front and back from the normal template.
                    if thickness == 4 and not bevel:
                        temp_part['back'] = face
                        face.translate(2 * norm)
                        # Set it to zero here, so we don't need to reset
                        # it in make_tile.
                        face.offset = 0
                elif face.mat in consts.BlackPan or face.mat in consts.WhitePan:
                    if thickness == 4 and not bevel:
                        temp_part['front'] = face
                        face.translate(-2 * norm)
                else:
                    # Squarebeams.
                    # Rounding the position of the face gives us the direction
                    # it's pointing away from the center.
                    face_norm: Vec = round(face.get_origin().norm())
                    face.translate(-16 * face_norm - (thickness / 2) * norm)
                    u_dir, v_dir = face_norm.other_axes(axis_norm)
                    temp_part[int(u_dir), int(v_dir), thickness, bevel] = face


def analyse_map(vmf_file: VMF, side_to_ant_seg: Dict[int, List[antlines.Segment]]):
    """Create TileDefs from all the brush sides.

    Once done, all wall brushes have been removed from the map.
    """

    # Face ID -> tileDef, used to match overlays to their face targets.
    # Invalid after we exit, since all the IDs have been freed and may be
    # reused later.
    face_to_tile: Dict[int, TileDef] = {}

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

    # Look for Angled and Flip Panels, to link the tiledef to the instance.
    # First grab the instances.
    panel_fname = instanceLocs.resolve('<ITEM_PANEL_ANGLED>, <ITEM_PANEL_FLIP>')
    # Also find PeTI-placed placement helpers, and move them into the tiledefs.
    placement_helper_file = instanceLocs.resolve('<ITEM_PLACEMENT_HELPER>')

    panels: Dict[str, Entity] = {}
    for inst in vmf_file.by_class['func_instance']:
        filename = inst['file'].casefold()
        if filename in panel_fname:
            panels[inst['targetname']] = inst
        elif filename in placement_helper_file:
            angles = Vec.from_str(inst['angles'])
            pos = Vec(0, 0, -128)
            pos.localise(Vec.from_str(inst['origin']), angles)
            try:
                tile = TILES[pos.as_tuple(), Vec(z=1).rotate(*angles).as_tuple()]
            except KeyError:
                pass  # On goo or the like.
            else:
                tile.add_portal_helper()
            inst.remove()

    dynamic_pan_parent = vbsp_options.get(str, "dynamic_pan_parent")
    import conditions

    # Find Angled Panel brushes.
    for brush_ent in vmf_file.by_class['func_brush']:
        # Grab the instance name out of the parent - these are the
        # only ones with parents in default PeTI.
        if brush_ent['parentname']:
            # Strip '-model_arms'...
            panel_inst = panels[brush_ent['parentname'][:-11]]

            # Allow styles to configure their instance name.
            brush_ent['parentname'] = conditions.local_name(
                panel_inst,
                dynamic_pan_parent
            )
            tiledef_from_angled_panel(brush_ent, panel_inst)

    # Find all Flip Panels.
    for brush_ent in vmf_file.by_class['func_door_rotating']:
        # Strip '-flipping_panel'...
        panel_inst = panels[brush_ent['targetname'][:-15]]
        tiledef_from_flip_panel(brush_ent, panel_inst)


    # Tell the antlines which tiledefs they attach to.
    for side, segments in side_to_ant_seg.items():
        try:
            tile = face_to_tile[side]
        except KeyError:
            continue
        for seg in segments:
            seg.tiles.add(tile)

    # Parse face IDs saved in overlays - if they're matching a tiledef,
    # remove them.
    for over in vmf_file.by_class['info_overlay']:
        faces = over['sides', ''].split(' ')
        tiles: List[TileDef]
        tiles = over.tiledefs = []  # type: ignore
        for face in faces[:]:
            try:
                tiles.append(face_to_tile[int(face)])
            except (KeyError, ValueError):
                pass
            else:
                faces.remove(face)
        over['sides'] = ' '.join(faces)

    # Strip out all the original goo triggers. Ignore ones with names
    # so we don't touch laserfield trigger here.
    for trig in vmf_file.by_class['trigger_multiple']:
        if trig['wait'] == '0.1' and trig['targetname', ''] == '':
            trig.remove()

    for trig in vmf_file.by_class['trigger_hurt']:
        if trig['targetname', ''] == '':
            trig.remove()

    # Now look at all the blocklocs in the map, applying goo sides.
    # Don't override white surfaces, they can only appear on panels.
    goo_replaceable = [TileType.BLACK, TileType.BLACK_4x4]
    for pos, block in BLOCK_POS.items():
        if block.is_goo:
            for norm in NORMALS:
                grid_pos = grid_to_world(pos) - 128 * norm
                try:
                    tile = TILES[grid_pos.as_tuple(), norm.as_tuple()]
                except KeyError:
                    continue

                for u, v, tile_type in tile:
                    if tile_type in goo_replaceable:
                        tile[u, v] = TileType.GOO_SIDE


def tiledefs_from_cube(face_to_tile: Dict[int, TileDef], brush: Solid, grid_pos: Vec):
    """Generate a tiledef matching a 128^3 block."""
    for face in brush:
        normal = -face.normal()

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
            LOGGER.warning('Unknown cube texture "{}"!', face.mat)

        tiledef = TileDef(
            grid_pos,
            normal,
            base_type=tex_kind,
        )
        TILES[grid_pos.as_tuple(), normal.as_tuple()] = tiledef
        face_to_tile[face.id] = tiledef
    brush.remove()


def tiledefs_from_large_tile(
    face_to_tile: Dict[int, TileDef],
    brush: Solid,
    grid_pos: Vec,
    norm: Vec,
) -> None:
    """Generate a tiledef matching a 128x128x4 side."""
    tex_kind, front_face = find_front_face(brush, grid_pos, norm)

    neighbour_block = BLOCK_POS['world': grid_pos + 128 * norm]

    if neighbour_block is Block.VOID:
        tex_kind = TileType.NODRAW

    tiledef = TileDef(
        grid_pos,
        norm,
        base_type=tex_kind,
    )
    TILES[grid_pos.as_tuple(), norm.as_tuple()] = tiledef
    brush.map.remove_brush(brush)
    face_to_tile[front_face.id] = tiledef


def tiledef_from_angled_panel(brush_ent: Entity, panel_ent: Entity) -> None:
    """Generate a tiledef matching an angled panel."""
    brush = brush_ent.solids.pop()
    assert not brush_ent.solids, 'Multiple brushes in angled panel?'

    grid_pos = round_grid(Vec.from_str(panel_ent['origin']))
    norm = Vec(z=1).rotate_by_str(panel_ent['angles'])
    grid_pos -= 128*norm

    tex_kind, front_face = find_front_face(brush, grid_pos, norm)

    TILES[grid_pos.as_tuple(), norm.as_tuple()] = TileDef(
        grid_pos,
        norm,
        base_type=tex_kind,
        brush_type=BrushType.ANGLED_PANEL,
        panel_ent=brush_ent,
        panel_inst=panel_ent,
        # Add a helper if portalable.
        has_helper=tex_kind.is_white,
    )


def tiledef_from_flip_panel(brush_ent: Entity, panel_ent: Entity) -> None:
    """Generate a tiledef matching a flip panel."""
    brush_ent.solids.clear()
    grid_pos = round_grid(Vec.from_str(panel_ent['origin']))
    norm = Vec(z=1).rotate_by_str(panel_ent['angles'])
    grid_pos -= 128*norm

    TILES[grid_pos.as_tuple(), norm.as_tuple()] = TileDef(
        grid_pos,
        norm,
        # It's always white in the forward direction
        base_type=TileType.WHITE,
        brush_type=BrushType.FLIP_PANEL,
        panel_ent=brush_ent,
        panel_inst=panel_ent,
        # Flip panels always are portalable at some point, so add a helper.
        has_helper=True,
    )


def tiledefs_from_embedface(
    face_to_tile: Dict[int, TileDef],
    brush: Solid,
    grid_pos: Vec,
    norm: Vec,
) -> None:
    """Generate a tiledef matching EmbedFace brushes."""

    tex_kind, front_face = find_front_face(brush, grid_pos, norm)

    norm_axis = norm.axis()

    bbox_min, bbox_max = brush.get_bbox()
    bbox_min[norm_axis] = bbox_max[norm_axis] = 0
    if bbox_min % 32 or bbox_max % 32:
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
        tile[uv] = tex_kind


def find_front_face(
    brush: Solid,
    grid_pos: Vec,
    norm: Vec,
) -> Tuple[TileType, Side]:
    """Find the tile face in a brush. Returns color, face."""
    for face in brush:
        if -face.normal() != norm:
            continue
        if face.mat in consts.BlackPan:
            return TileType.BLACK, face
        elif face.mat in consts.WhitePan:
            return TileType.WHITE, face
        elif face.mat == consts.Tools.NODRAW:
            return TileType.NODRAW, face
        else:
            LOGGER.warning('Unknown panel texture "{}"!', face.mat)
            return TileType.BLACK, face
    else:
        raise Exception('Malformed wall brush at {}, {}'.format(grid_pos, norm))


def inset_flip_panel(panel: Entity, pos: Vec, normal: Vec) -> None:
    """Inset the sides of a flip panel, to not hit the borders."""
    norm_axis = normal.axis()
    for side in panel.sides():
        norm = side.normal()
        if norm.axis() == norm_axis:
            continue  # Front or back

        u_off, v_off = (side.get_origin() - pos).other_axes(norm_axis)
        if abs(u_off) == 64 or abs(v_off) == 64:
            side.translate(2 * norm)
            # Snap squarebeams to each other.
            side.vaxis.offset = 0


def bevel_split(
    rect_points: Dict[Tuple[int, int], bool],
    tile_pos: Dict[Tuple[int, int], TileDef],
) -> Iterator[Tuple[int, int, int, int, Tuple[bool, bool, bool, bool]]]:
    """Split the optimised segments to produce the correct bevelling."""
    for min_u, min_v, max_u, max_v in grid_optim.optimise(rect_points):
        u_range = range(min_u, max_u + 1)
        v_range = range(min_v, max_v + 1)

        # These are sort of reversed around, which is a little confusing.
        # Bevel U is facing in the U direction, running across the V.
        bevel_umins: List[bool] = [
            tile_pos[min_u, v].should_bevel(-1, 0)
            for v in v_range
        ]
        bevel_umaxes: List[bool] = [
            tile_pos[max_u, v].should_bevel(1, 0)
            for v in v_range
        ]
        bevel_vmins: List[bool] = [
            tile_pos[u, min_v].should_bevel(0, -1)
            for u in u_range
        ]
        bevel_vmaxes: List[bool] = [
            tile_pos[u, max_v].should_bevel(0, 1)
            for u in u_range
        ]

        u_group = list(utils.group_runs(zip(bevel_umins, bevel_umaxes)))
        v_group = list(utils.group_runs(zip(bevel_vmins, bevel_vmaxes)))

        for bevel_u, v_ind_min, v_ind_max in u_group:
            for bevel_v, u_ind_min, u_ind_max in v_group:
                yield (
                    min_u + u_ind_min,
                    min_v + v_ind_min,
                    min_u + u_ind_max,
                    min_v + v_ind_max,
                    bevel_u + bevel_v,
                )


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map, then set overlay sides."""
    LOGGER.info('Generating tiles...')
    # Each tile is either a full-block tile, or some kind of subtile/special surface.
    # Each subtile is generated individually. If it's a full-block tile we
    # try to merge tiles together with the same texture.

    # The key is (normal, plane distance, tile type)
    full_tiles: Dict[
        Tuple[float, float, float, float, TileType],
        List[TileDef]
    ] = defaultdict(list)

    for tile in TILES.values():
        if tile.can_merge():
            pos = tile.pos + 64 * tile.normal
            plane_dist = abs(pos.dot(tile.normal))

            full_tiles[
                tile.normal.x, tile.normal.y, tile.normal.z,
                plane_dist,
                tile.base_type,
            ].append(tile)

            if tile.has_portal_helper:
                # Add the portal helper in directly.
                vmf.create_ent(
                    'info_placement_helper',
                    angles=tile.normal.to_angle_roll(tile.portal_helper_orient),
                    origin=pos,
                    force_placement=int(tile.has_oriented_portal_helper),
                    snap_to_helper_angles=int(tile.has_oriented_portal_helper),
                    radius=64,
                )
        else:
            tile.export(vmf)

    for (norm_x, norm_y, norm_z, plane_dist, tile_type), tiles in full_tiles.items():
        # Construct each plane of tiles.
        normal = Vec(norm_x, norm_y, norm_z)
        norm_axis = normal.axis()
        u_axis, v_axis = Vec.INV_AXIS[norm_axis]
        bbox_min, bbox_max = Vec.bbox(tile.pos for tile in tiles)

        grid_pos: Dict[str, Dict[Tuple[int, int], bool]] = defaultdict(dict)

        tile_pos: Dict[Tuple[int, int], TileDef] = {}

        for tile in tiles:
            pos = tile.pos + 64 * tile.normal

            if tile_type is TileType.GOO_SIDE:
                # This forces a specific size.
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    Portalable.BLACK
                ).get(pos, TileSize.GOO_SIDE)
            else:
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    tile.base_type.color
                ).get(pos, tile.base_type.tile_size)

            u_pos = int((pos[u_axis] - bbox_min[u_axis]) // 128)
            v_pos = int((pos[v_axis] - bbox_min[v_axis]) // 128)
            grid_pos[tex][u_pos, v_pos] = True
            tile_pos[u_pos, v_pos] = tile

        for tex, tex_pos in grid_pos.items():
            for min_u, min_v, max_u, max_v, bevels in bevel_split(tex_pos, tile_pos):
                center = Vec.with_axes(
                    norm_axis, plane_dist,
                    u_axis, bbox_min[u_axis] + (min_u + max_u) * 64,
                    v_axis, bbox_min[v_axis] + (min_v + max_v) * 64,
                )
                brush, front = make_tile(
                    vmf,
                    center,
                    normal,
                    tex,
                    texturing.SPECIAL.get(center, 'behind'),
                    bevels=bevels,
                    width=(1 + max_u - min_u) * 128,
                    height=(1 + max_v - min_v) * 128,
                )
                vmf.add_brush(brush)

                for u in range(min_u, max_u + 1):
                    for v in range(min_v, max_v + 1):
                        tile_pos[u, v].brush_faces.append(front)

    for over in vmf.by_class['info_overlay']:
        try:
            over_tiles: List[TileDef] = over.tiledefs  # type: ignore
        except AttributeError:
            continue
        faces = set(over['sides', ''].split(' '))
        for tile in over_tiles:
            faces.update(str(f.id) for f in tile.brush_faces)

        if faces:
            over['sides'] = ' '.join(sorted(faces))
        else:
            over.remove()

    LOGGER.info('Generating goop...')
    generate_goo(vmf)


def generate_goo(vmf: VMF) -> None:
    """Generate goo pit brushes and triggers."""
    # We want to use as few brushes as possible.
    # So group them by their min/max Z, and then produce bounding boxes.
    goo_pos: Dict[Tuple[float, float], Dict[Tuple[float, float], bool]] = defaultdict(dict)

    # For triggers, we want to only group by the top surface, we don't care
    # how deep.
    trig_pos: Dict[float, Dict[Tuple[float, float], bool]] = defaultdict(dict)

    # Calculate the z-level with the largest number of goo brushes,
    # so we can ensure the 'fancy' pit is the largest one.
    # Valve just does it semi-randomly.
    goo_heights: Dict[Tuple[float, float, float], int] = Counter()

    pos = None

    for pos, block_type in BLOCK_POS.items():
        if block_type is Block.GOO_SINGLE:
            goo_pos[pos.z, pos.z][pos.x, pos.y] = True
            trig_pos[pos.z][pos.x, pos.y] = True

            goo_heights[pos.as_tuple()] += 1
        elif block_type is Block.GOO_TOP:
            goo_heights[pos.as_tuple()] += 1
            # Multi-layer..
            lower_pos = BLOCK_POS.raycast(pos, Vec(0, 0, -1))

            goo_pos[lower_pos.z, pos.z][pos.x, pos.y] = True
            trig_pos[pos.z][pos.x, pos.y] = True

    # No goo.
    if not goo_pos or pos is None:
        return

    trig_phys = vmf.create_ent(
        'trigger_multiple',
        spawnflags='8',  # Physics Objects
        wait='0.1',
        origin=pos * 128,
    )
    trig_phys.add_out(
        Output('OnStartTouch', '!activator', 'SilentDissolve'),
        Output('OnStartTouch', '!activator', 'Kill', delay=0.1),
    )

    trig_hurt = vmf.create_ent(
        'trigger_hurt',
        spawnflags='1',  # Clients
        damage='1000',
        damagecap='1000',
        damagetype=(1 << 18),  # Radiation
    )

    goo_scale = vbsp_options.get(float, 'goo_scale')

    # Find key with the highest value - that gives the largest z-level.
    best_goo = max(goo_heights.items(), key=lambda x: x[1])[0]

    for ((min_z, max_z), grid) in goo_pos.items():
        for min_x, min_y, max_x, max_y in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, min_z) * 128
            bbox_max = Vec(max_x, max_y, max_z) * 128
            prism = vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 96),
            )
            # Apply goo scaling
            prism.top.scale = goo_scale
            # Use fancy goo on the level with the
            # highest number of blocks.
            # All plane z are the same.
            prism.top.mat = texturing.SPECIAL.get(
                bbox_max + (0, 0, 96), (
                    'goo' if
                    bbox_max.z == best_goo
                    else 'goo_cheap'
                ),
            )
            vmf.add_brush(prism.solid)

    bbox_min = Vec()

    for (z, grid) in trig_pos.items():
        for min_x, min_y, max_x, max_y in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, z) * 128
            bbox_max = Vec(max_x, max_y, z) * 128
            trig_hurt.solids.append(vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 77),
                mat=consts.Tools.TRIGGER,
            ).solid)
            trig_phys.solids.append(vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 26),
                mat=consts.Tools.TRIGGER,
            ).solid)

    # Set to any random position for the entity.
    trig_phys['origin'] = trig_hurt['origin'] = bbox_min + 64
