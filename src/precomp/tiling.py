"""Generates all tile brushes.

It also tracks overlays assigned to tiles, so we can regenerate all the brushes.
That allows any wall cube to be split into separate brushes, and make quarter-tile patterns.

Note: We also store a list of tiledefs in overlay entities in the map, if
they were attached to the original brushes.
"""
from __future__ import annotations
from typing import Iterable, cast
from collections.abc import Iterator, MutableMapping
from collections import defaultdict, Counter
import math
from enum import Enum
from weakref import WeakKeyDictionary

import attrs
from srctools import FrozenMatrix, FrozenVec, Vec, Angle, Matrix
from srctools.vmf import VMF, Entity, Side, Solid, Output, UVAxis
import srctools.logger
import srctools.vmf

from plane import Plane
from precomp.brushLoc import POS as BLOCK_POS, Block, grid_to_world
from precomp.texturing import TileSize, Portalable
from . import (
    grid_optim,
    instanceLocs,
    texturing,
    options,
    antlines,
    template_brush,
    conditions, rand,
)
import utils
import consts


__all__ = [
    'TileSize', 'Portalable',
    'TILETYPE_FROM_CHAR', 'TILETYPE_TO_CHAR', 'PanelType', 'Panel', 'round_grid', 'TileDef',
    'analyse_map', 'generate_brushes',
]
LOGGER = srctools.logger.get_logger(__name__)

# Face surfaces used to generate tiles.
# TILE_TEMP[tile_norm][u_norm, v_norm, thickness, is_bevel] = squarebeams_face
# thickness = 2,4,8
# TILE_TEMP[tile_norm]['tile'] = front_face
# TILE_TEMP[tile_norm]['back'] = back_face
TILE_TEMP: dict[
    tuple[float, float, float],
    dict[str | tuple[int, int, int, bool], Side]
] = {}

NORMALS = [
    FrozenVec(x=+1),
    FrozenVec(x=-1),
    FrozenVec(y=+1),
    FrozenVec(y=-1),
    FrozenVec(z=+1),
    FrozenVec(z=-1),
]
# Specific corresponding, these ensure the textures align to world once done.
# IE upright on walls, up=north for floor and ceilings.
NORMAL_ANGLES = [
    FrozenMatrix.from_angle(0.0, 0.0, 0.0),
    FrozenMatrix.from_angle(0.0, 180, 0.0),
    FrozenMatrix.from_angle(0.0, 90., 0.0),
    FrozenMatrix.from_angle(0.0, 270, 0.0),
    FrozenMatrix.from_angle(270, 270, 0.0),
    FrozenMatrix.from_angle(90., 90., 0.0),
]
NORMAL_NAMES = dict(zip(
    NORMALS,
    ['east', 'west', 'north', 'south', 'up', 'down'],
))
# All the tiledefs in the map.
# Maps a block center, normal -> the tiledef on the side of that block.
TILES: dict[tuple[tuple[float, float, float], tuple[float, float, float]], TileDef] = {}

# Special key for TileDef.subtile - this is set to 'u' or 'v' to
# indicate the center section should be nodrawed.
# This isn't a U,V tuple, but pretend it is, so we can use it as a key.
SUBTILE_FIZZ_KEY: tuple[int, int] = cast('tuple[int, int]', object())

# For each overlay, stores any tiledefs that they're affixed to. We then
# add the front faces of those to the ent at the end.
# It's weak-key to automatically remove bindings for overlays when removed
# from the level.
OVERLAY_BINDS: MutableMapping[Entity, list[TileDef]] = WeakKeyDictionary()

# Given the two bevel options, determine the correct texturing
# values.
# (min, max) -> (scale, offset)
BEVEL_BACK_SCALE = {
    (False, False): 128/512,  # |__|
    (False, True): 124/512,  # |__/
    (True, False): 124/512,  # \__|
    (True, True): 120/512,   # \__/
}

# U, V offset -> points on that side.
# This allows computing the set of bevel orientations from the surrounding tiles.
BEVEL_SIDES: list[tuple[int, int, set[tuple[int, int]]]] = [
    (-1, 0, {(-1, y) for y in range(4)}),
    (+1, 0, {(+4, y) for y in range(4)}),
    (0, -1, {(x, -1) for x in range(4)}),
    (0, +1, {(x, +4) for x in range(4)}),
]
# Combines all the former.
BEVEL_AROUND: frozenset[tuple[int, int]] = frozenset({
    item for u, v, st in BEVEL_SIDES
    for item in st
})


@utils.freeze_enum_props
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
        return self.name.startswith('CUTOUT_TILE')

    @property
    def is_nodraw(self) -> bool:
        """Should this swap to nodraw?"""
        return self is self.NODRAW

    @property
    def blocks_pattern(self) -> bool:
        """Does this affect patterns?"""
        return self is not self.CUTOUT_TILE_BROKEN

    @property
    def is_tile(self) -> bool:
        """Is this a regular tile (white/black)."""
        return self.value < 10

    @property
    def is_white(self) -> bool:
        """Is this portalable?"""
        return self.name.startswith('WHITE')

    @property
    def is_4x4(self) -> bool:
        """Is this forced to be 4x4 in size?"""
        return '4x4' in self.name

    @property
    def color(self) -> texturing.Portalable:
        """The portalability of the tile."""
        if 'WHITE' in self.name:
            return texturing.Portalable.WHITE
        elif 'BLACK' in self.name or self is self.GOO_SIDE:
            return texturing.Portalable.BLACK
        raise ValueError('No colour for ' + self.name + '!')

    @property
    def inverted(self) -> TileType:
        """Swap the color of a type."""
        try:
            col = self.color
        except ValueError:
            return self
        if col is texturing.Portalable.WHITE:
            return self.as_black
        else:
            return self.as_white

    @property
    def as_white(self) -> TileType:
        """Force to the white version."""
        if self is TileType.GOO_SIDE:
            return TileType.WHITE_4x4
        if self.name.startswith('BLACK'):
            tile = getattr(TileType, f'WHITE{self.name[5:]}')
            assert isinstance(tile, TileType)
            return tile
        return self

    @property
    def as_black(self) -> TileType:
        """Force to the black version."""
        if self.is_white:
            tile = getattr(TileType, f'BLACK{self.name[5:]}')
            assert isinstance(tile, TileType)
            return tile
        return self

    @property
    def as_4x4(self) -> TileType:
        """Convert to a 4x4-forcing version."""
        if self is TileType.WHITE:
            return TileType.WHITE_4x4
        elif self is TileType.BLACK:
            return TileType.BLACK_4x4
        return self

    @property
    def tile_size(self) -> TileSize:
        """The size of the tile this should force."""
        if '4x4' in self.name:
            return TileSize.TILE_4x4
        else:
            return TileSize.TILE_1x1

    @staticmethod
    def with_color_and_size(size: TileSize, color: texturing.Portalable) -> TileType:
        """Return the TileType with a size and color."""
        return _tiletype_tiles[size, color]

_tiletype_tiles = {
    (TileSize.TILE_1x1, texturing.Portalable.BLACK): TileType.BLACK,
    (TileSize.TILE_1x1, texturing.Portalable.WHITE): TileType.WHITE,
    (TileSize.TILE_4x4, texturing.Portalable.BLACK): TileType.BLACK_4x4,
    (TileSize.TILE_4x4, texturing.Portalable.WHITE): TileType.WHITE_4x4,
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
TILETYPE_FROM_CHAR: dict[str, TileType] = {
    v: k
    for k, v in
    TILETYPE_TO_CHAR.items()
}


@utils.freeze_enum_props
class PanelType(Enum):
    """Special functionality for tiling panels."""
    NORMAL = 'normal'
    FLIP_BLACK = 'flip_black'
    FLIP_INVERT = 'flip_invert'
    ANGLE_30 = 'angle_30'
    ANGLE_45 = 'angle_45'
    ANGLE_60 = 'angle_60'
    ANGLE_90 = 'angle_90'

    @staticmethod
    def from_panel(inst: Entity) -> PanelType:
        """Get the angle desired for a panel."""
        if not inst.fixup.bool('$start_deployed'):
            return PanelType.NORMAL
        # "ramp_90_deg_open" -> 90
        return PanelType('angle_' + inst.fixup['$animation'][5:7])

    @property
    def is_angled(self) -> bool:
        """Check if this is an ANGLE panel type."""
        return self.value[:5] == 'angle'

    @property
    def is_flip(self) -> bool:
        """Check if this is a FLIP panel type."""
        return self.value[:4] == 'flip'

    @property
    def angle(self) -> int:
        """Return the angle, if is_angled is True."""
        try:
            return int(self.value[6:])
        except ValueError:
            raise ValueError(
                f"PanelType.{self.name} "
                "is not an angled panel!"
            ) from None


def round_grid(vec: Vec) -> Vec:
    """Round to the center of the grid."""
    return vec // 128 * 128 + (64, 64, 64)


def iter_uv(
    umin: float=0,
    umax: float=3,
    vmin: float=0,
    vmax: float=3
) -> Iterator[tuple[int, int]]:
    """Iterate over points in a rectangle."""
    urange = range(int(umin), int(umax + 1))
    vrange = range(int(vmin), int(vmax + 1))
    for u in urange:
        for v in vrange:
            yield u, v


class Pattern:
    """Represents a position a tile can be positioned in."""
    def __init__(
        self,
        tex: TileSize,
        *tiles: tuple[int, int, int, int],
        wall_only: bool = False,
    ) -> None:
        self.tex = tex
        self.wall_only = wall_only
        self.tiles = list(tiles)
        tile_u, tile_v = tex.size
        # Do some sanity checks on values...
        for umin, vmin, umax, vmax in tiles:
            tile_tex = f'{tex} -> {umin} {vmin} {umax} {vmax}'
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


def order_bbox(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Used to sort 4x4 pattern positions.

    The pattern order is the order that they're tried in.
    We want to try the largest first so reverse the ordering used on max values.
    """
    umin, vmin, umax, vmax = bbox
    return umin, vmin, -umax, -vmax

PATTERNS: dict[str, list[Pattern]] = {
    'clean': [
        Pattern(TileSize.TILE_1x1, (0, 0, 4, 4)),
        Pattern(
            TileSize.TILE_2x1,
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
            (1, 0, 3, 2), (1, 2, 3, 4),  # Vertical
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
        Pattern(
            TileSize.TILE_2x1,
            (0, 0, 2, 4), (2, 0, 4, 4),  # L/R
            wall_only=True,
        ),
        Pattern(
            TileSize.TILE_2x2,
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


def _panel_bevel_conv(val: Iterable[tuple[int, int]] = ()) -> set[tuple[int, int]]:
    """Explicitly specify the generic for converters, inference isn't possible."""
    return set(val)


@attrs.define(eq=False)
class Panel:
    # noinspection PyUnresolvedReferences
    """Represents a potentially dynamic specially positioned part of a tile.

    This is used for angled/flip panel items, and things like those.
    The points are removed from the original tile, and transferred to this.

    Attributes:
        brush_ent: The brush entity the panel will be added to,
          or None if it should be a world brush.
        inst: The instance for the associated item.
        points: The set of UVs this will use. Others will generate as a
          standard tile.
        pan_type: Specifies which special features to enable.
          FLIP generates an inverted copy on the other side.
          ANGLED_30/45/60/90 rotates it to match static panels.
          NORMAL generates a regular slab.
        thickness: 2, 4 or 8 units thick.
        template: If set, generate this template and include it in the brush.
        bevels: A set of UV points that neighbours will bevel towards.
        nodraw: If true, apply nodraw to the squarebeam and backpanel faces.
        seal: If true, place nodraw tiles behind the panel instead of void.
        offset: Offset the tile by this much (local to the instance).
    """
    brush_ent: Entity | None
    inst: Entity
    pan_type: PanelType
    thickness: int = 4
    bevels: set[tuple[int, int]] = attrs.field(converter=_panel_bevel_conv, factory=set)

    points: set[tuple[int, int]] = attrs.Factory({
        (x, y)
        for x in range(4)
        for y in range(4)
    }.copy)
    template: str = ''
    nodraw: bool = False
    seal: bool  = False
    steals_bullseye: bool = False
    offset: Vec = attrs.Factory(Vec)

    def same_item(self, inst: Entity) -> bool:
        """Check if the two instances come from the same item.

        If they have names, those can just match. Otherwise, the instances must actually be the same.
        """
        if inst is self.inst:
            return True
        name = self.inst['targetname']
        if name and name == inst['targetname']:
            return True
        return False

    def export(
        self,
        tile: TileDef,
        vmf: VMF,
        sub_tiles: dict[tuple[int, int], TileType],
        has_helper: bool,
        force_helper: bool,
    ) -> None:
        """Generate the panel brushes."""
        # We need to do the checks to handle multiple panels with shared
        # data.
        if all(subtile is TileType.VOID for subtile in sub_tiles.values()):
            LOGGER.debug('Placing panel failed at {} @ {}: {} = {}', tile.pos, tile.normal, self, tile.format_tiles())
            # The brush entity isn't used.
            if self.brush_ent in vmf.entities:
                self.brush_ent.remove()
            # In dev mode, display a visual of this location.
            if utils.DEV_MODE:
                try:
                    [visgroup] = [vis for vis in vmf.vis_tree if vis.name == 'TilePanels']
                except ValueError:
                    visgroup = vmf.create_visgroup('TilePanels')
                panel_trace = vmf.create_ent(
                    'info_particle_system',
                    origin=tile.pos,
                    targetname=self.inst['targetname'],
                    angles=tile.normal.to_angle(),
                )
                panel_trace.comments = tile.format_tiles().replace('\n', ', ')
                panel_trace.vis_shown = False
                panel_trace.hidden = True
                panel_trace.visgroup_ids.add(visgroup.id)
            return
        else:
            # We do use it.
            if self.brush_ent is not None and self.brush_ent not in vmf.entities:
                vmf.add_ent(self.brush_ent)

        LOGGER.debug('Placing panel at {} @ {}: {}', tile.pos, tile.normal, self)

        is_static = (
            self.brush_ent is None or
            self.brush_ent['classname'].casefold() == 'func_detail'
        )
        use_bullseye = tile.use_bullseye()

        inst_orient = orient = Matrix.from_angstr(self.inst['angles'])
        if orient.up() != tile.normal:
            # It's not aligned to ourselves, so dump the rotation for our
            # logic.
            orient = Matrix.from_angle(conditions.PETI_INST_ANGLE[tile.normal.freeze()])
        front_pos = Vec(0, 0, 64) @ orient + tile.pos

        offset = self.offset.copy()

        is_wall = tile.normal.z == 0

        all_brushes: list[Solid] = []

        if self.pan_type.is_flip:
            # Two surfaces, forward and backward - each is 4 thick.
            invert_black = self.pan_type is PanelType.FLIP_INVERT
            back_subtiles = {
                uv: (
                    tile_type.inverted
                    if invert_black or tile_type.color is Portalable.WHITE else
                    tile_type
                ) for uv, tile_type in sub_tiles.items()
            }
            # If facing black first, use that side.
            if not self.inst.fixup.bool(consts.FixupVars.ST_DEPLOYED):
                back_subtiles, sub_tiles = sub_tiles, back_subtiles

            # Now, we need to flip this across the appropriate axis to
            # replicate rotation.
            u_ax, v_ax = Vec.INV_AXIS[tile.normal.axis()]
            rot_flag = srctools.conv_int(self.brush_ent['spawnflags'])
            if rot_flag & 64:
                rot_axis = 'x'
            elif rot_flag & 128:
                rot_axis = 'y'
            else:
                rot_axis = 'z'
            if rot_axis == v_ax:
                back_subtiles = {
                    (3-u, v): tile_type
                    for (u, v), tile_type in back_subtiles.items()
                }
            elif rot_axis == u_ax:
                back_subtiles = {
                    (u, 3-v): tile_type
                    for (u, v), tile_type in back_subtiles.items()
                }
            else:
                LOGGER.warning(
                    'Flip panel "{}" rotates on normal axis??',
                    self.brush_ent['targetname'],
                )
        else:  # Should never be needed, but makes typecheck happy.
            back_subtiles = sub_tiles

        faces, brushes = tile.gen_multitile_pattern(
            vmf,
            sub_tiles,
            is_wall,
            self.bevels,
            tile.normal,
            thickness=self.thickness,
            is_panel=True,
            add_bullseye=use_bullseye and not is_static,
            interior_bevel=False,  # User must specify this themselves.
        )
        all_brushes += brushes

        if is_static:
            # Include these as faces to apply antlines etc to.
            tile.brush_faces += faces

        # If requested apply nodraw to everything that's not the front.
        if self.nodraw:
            for brush in brushes:
                for side in brush:
                    if side.normal() != -tile.normal:
                        side.mat = consts.Tools.NODRAW
                        side.offset = 0
                        side.scale = 0.25

        if self.pan_type.is_flip:
            back_faces, brushes = tile.gen_multitile_pattern(
                vmf,
                back_subtiles,
                is_wall,
                self.bevels,
                -tile.normal,
                thickness=self.thickness,
                offset=64 - 2*self.thickness,
                is_panel=True,
                add_bullseye=use_bullseye and not is_static,
                interior_bevel=False,  # User must specify this themselves.
            )
            all_brushes += brushes
            inset_flip_panel(all_brushes, front_pos, tile.normal)

        if self.template:
            template = template_brush.import_template(
                vmf,
                self.template,
                # Don't offset these at all. Assume the user knows
                # where it should go. Similarly, always use the instance orient.
                Vec.from_str(self.inst['origin']),
                inst_orient,
                self.inst['targetname'],
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            )
            template_brush.retexture_template(
                template,
                front_pos + offset,
                self.inst.fixup,
            )
            all_brushes += template.world

        if self.pan_type.is_angled:
            # Rotate the panel to match the panel shape, by rotating around its Y axis.
            rotation = Matrix.axis_angle(-orient.left(), self.pan_type.angle)

            # Shift so the rotation axis is 0 0 0, then shift back to rotate correctly.
            panel_offset = front_pos - Vec(64, 0, 0) @ orient

            # Rotating like this though will make the brush clip into the surface it's attached on.
            # We need to clip the hinge edge, so it doesn't do that. We can just produce any
            # plane that is the correct orientation and let VBSP sort out the geometry.

            front_normal = orient.forward()
            for brush in all_brushes:
                clip_face = None
                # Find the face at the edge pointing in the front normal direction.
                # That's the face we're replacing. There should be only one in
                # each brush, but it could be not there - if it's split for tiles.
                for face in brush:
                    if (
                        Vec.dot(face.normal(), front_normal) > 0.99
                        and math.isclose(
                            face.get_origin().dot(front_normal),
                            panel_offset.dot(front_normal)
                        )
                    ):
                        clip_face = face
                        break
                # Move to put 0 0 0 at the hinge point, then rotate and return.
                brush.localise(-panel_offset)
                brush.localise(panel_offset, rotation)
                if clip_face is not None:
                    # Figure out the appropriate face info. We don't really
                    # care about texture scaling etc.
                    clip_face.uaxis = UVAxis(*orient.left())
                    clip_face.vaxis = UVAxis(*orient.forward())
                    clip_face.planes = [
                        panel_offset + Vec(64, 64, 0) @ orient,
                        panel_offset + Vec(0, 64, 0) @ orient,
                        panel_offset + Vec(0, -64, 0) @ orient,
                    ]
                    clip_face.mat = consts.Tools.NODRAW

            # Helpfully the angled surfaces are always going to be forced
            # upright, so we don't need to compute the orientation matching
            # the item axis.
            angled_normal = tile.normal @ rotation
            top_center = (
                64 * front_normal @ rotation -
                64 * front_normal +
                front_pos
            )

            if has_helper:
                # We need to make a placement helper.
                vmf.create_ent(
                    'info_placement_helper',
                    angles=Matrix.from_basis(z=tile.portal_helper_orient, x=tile.normal) @ rotation,
                    origin=top_center,
                    force_placement=int(force_helper),
                    snap_to_helper_angles=int(force_helper),
                    radius=64,
                )

            if use_bullseye and is_static:
                # Add the bullseye overlay.
                srctools.vmf.make_overlay(
                    vmf,
                    angled_normal,
                    top_center,
                    64 * front_normal @ rotation,
                    64 * orient.left(),
                    texturing.OVERLAYS.get(front_pos, 'bullseye'),
                    faces,
                )
        else:
            # Do non-angled helpers.
            if use_bullseye and is_static:
                # Add the bullseye overlay.
                srctools.vmf.make_overlay(
                    vmf,
                    tile.normal,
                    front_pos + offset,
                    64 * orient.left(),
                    64 * orient.forward(),
                    texturing.OVERLAYS.get(front_pos, 'bullseye'),
                    faces,
                )

            # If it's a flip panel, always create a helper.
            if has_helper or self.pan_type.is_flip:
                # We need to make a placement helper.
                helper = vmf.create_ent(
                    'info_placement_helper',
                    angles=Angle.from_basis(z=tile.portal_helper_orient, x=tile.normal),
                    origin=front_pos + offset,
                    force_placement=int(force_helper),
                    snap_to_helper_angles=int(force_helper),
                    radius=64,
                )
                # On a flip panel don't parent. The helper can just stay on the front side.
                if not is_static:
                    if self.pan_type.is_flip:
                        helper['attach_target_name'] = self.brush_ent[
                            'targetname']
                    else:
                        helper['parentname'] = self.brush_ent['targetname']

        if offset:
            for brush in all_brushes:
                brush.localise(offset)

        if self.brush_ent is None:
            vmf.add_brushes(all_brushes)
        else:
            self.brush_ent.solids.extend(all_brushes)

    def position_bullseye(self, tile: TileDef, target: Entity) -> None:
        """Compute the position required for the bullseye overlay."""
        if self.pan_type.is_angled:
            angle = self.pan_type.angle
            panel_top = Vec(
                x=-64 + 64 * math.cos(math.radians(angle)),
                z=-64 + 64 * math.sin(math.radians(angle)),
            )
            panel_top.localise(
                Vec.from_str(self.inst['origin']),
                Angle.from_str(self.inst['angles']),
            )
        else:
            panel_top = tile.pos + 64 * tile.normal
        target['origin'] = panel_top + self.offset

        if (
            self.brush_ent is not None and
            self.brush_ent['classname'] != 'func_detail'
        ):
            self.brush_ent.make_unique('panel')  # In case it's unnamed.
            target['parentname'] = self.brush_ent['targetname']


class TileDef:
    """Represents one 128 block side.

    Attributes:
        pos: Vec for the center of the block.
        normal: The direction out of the block, towards the face.
        brush_faces: A list of brush faces which this tiledef has exported.
          Empty beforehand, but after these are faces to attach antlines to.
        base_type: TileSize this tile started with.
        override: If set, a specific texture to use and orientation.
          This only applies to .is_tile tiles.
        _sub_tiles: None or a Dict[(u,v): TileSize]. u/v are either xz,
        yz or xy.
          If None, it's the same as base_type.
        bullseye_count: The number of bullseye items on this surface. If > 0,
          we have some.
        _portal_helper: The number of portal placement helpers here. If > 0,
          a non-anglesnap helper is present. If a Vector instead, a forced
          helper is present pointing this direction.
        panels: A list of "panels" for the tiledef, allowing moving or split parts.
          If present, each of these "steals" some UV positions and instead
          generates them (potentially offset) as a brush entity.
        is_antigel: If this is marked to not accept gel.
    """
    __slots__ = [
        'pos',
        'normal',
        'brush_faces',
        'base_type',
        '_sub_tiles',
        'override',
        'bullseye_count',
        '_portal_helper',
        'panels',
        'is_antigel',
    ]

    pos: Vec
    normal: Vec
    base_type: TileType

    brush_faces: list[Side]
    panels: list[Panel]
    _sub_tiles: dict[tuple[int, int], TileType] | None
    override: tuple[str, template_brush.ScalingTemplate] | None

    bullseye_count: int
    _portal_helper: int | Vec

    def __init__(
        self,
        pos: Vec,
        normal: Vec,
        base_type: TileType,
        subtiles: dict[tuple[int, int], TileType]=None,
        has_helper: bool=False,
    ) -> None:
        self.pos = pos
        self.normal = normal
        self.brush_faces = []
        self.override = None
        self.base_type = base_type
        self._sub_tiles = subtiles
        self.panels = []
        self.bullseye_count = 0
        self._portal_helper = 1 if has_helper else 0
        self.is_antigel = False

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
        return '<{} TileDef @ {} of {}>'.format(
            self.base_type.name,
            NORMAL_NAMES.get(self.normal.freeze(), self.normal),
            self.pos,
        )

    def format_tiles(self) -> str:
        """Debug utility, log the subtile shape."""
        out = []
        for v in reversed(range(4)):
            for u in range(4):
                out.append(TILETYPE_TO_CHAR[self[u, v]])
            out.append('\n')
        return ''.join(out)

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

    def _get_subtiles(self) -> dict[tuple[int, int], TileType]:
        """Returns subtiles, creating it if not present."""
        if self._sub_tiles is None:
            self._sub_tiles = tile = {
                (x, y): self.base_type
                for x in range(4) for y in range(4)
            }
            return tile
        else:
            return self._sub_tiles

    def __getitem__(self, item: tuple[int, int]) -> TileType:
        """Lookup the tile type at a particular sub-location."""
        u, v = item
        if u not in (0, 1, 2, 3) or v not in (0, 1, 2, 3):
            raise IndexError(u, v)

        if self._sub_tiles is None:
            return self.base_type
        else:
            return self._sub_tiles[u, v]

    def __setitem__(self, item: tuple[int, int], value: TileType) -> None:
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

            # Check if we can merge this down to a single value.
            # We can if we don't have the special fizzler key, and all
            # the subtiles are the same.
            if SUBTILE_FIZZ_KEY not in self._sub_tiles:
                base_type = self._sub_tiles[0, 0]
                for tile in self._sub_tiles.values():
                    if tile is not base_type:
                        return
                self.base_type = base_type
                self._sub_tiles = None

    def __iter__(self) -> Iterator[tuple[int, int, TileType]]:
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
        self._get_subtiles()[SUBTILE_FIZZ_KEY] = cast(TileType, axis)

    def uv_offset(self, u: float, v: float, norm: float) -> Vec:
        """Return an u/v offset from our position.

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
        overlays = OVERLAY_BINDS.setdefault(over, [])
        overlays.append(self)

    def calc_patterns(
        self,
        tiles: dict[tuple[int, int], TileType],
        is_wall: bool=False,
        _pattern: str=None,
    ) -> Iterator[tuple[float, float, float, float, TileSize, TileType]]:
        """Figure out the brushes needed for a complex pattern.

        This yields (umin, umax, vmin, vmax, grid_size_, tile_type) tuples.
        """

        # copy it, so we can overwrite positions with VOID = not a tile.
        tiles = tiles.copy()

        # Don't check for special types if one is passed - that prevents
        # infinite recursion.
        if not _pattern:
            _pattern = 'clean'
            if SUBTILE_FIZZ_KEY in tiles:
                # Output the split patterns for centered fizzlers.
                # We need to remove it also so our iteration doesn't choke on it.
                # 'u' or 'v'
                split_type = cast(str, tiles.pop(SUBTILE_FIZZ_KEY))
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
                if tile_type is TileType.VOID:
                    continue
                for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                    if tiles[uv] is not tile_type:
                        break
                else:
                    for uv in iter_uv(umin, umax-1, vmin, vmax-1):
                        tiles[uv] = TileType.VOID
                    yield umin, umax, vmin, vmax, pattern.tex, tile_type

        # All unfilled spots are single 4x4 tiles, or other objects.
        for (u, v), tile_type in tiles.items():
            if tile_type is not TileType.VOID:
                yield u, u + 1, v, v + 1, TileSize.TILE_4x4, tile_type

    def should_bevel(self, u: int, v: int) -> bool:
        """Check if this side of the TileDef should be bevelled.

        U and V should be 1 or -1.
        """
        # If there's a fully solid block on this side, we don't need to.
        if BLOCK_POS.lookup_world(self.uv_offset(128*u, 128*v, 0)).inside_map:
            return True

        # Otherwise, check for another tile attached to our side.
        u_ax, v_ax = Vec.INV_AXIS[self.normal.axis()]
        side_norm = Vec.with_axes(u_ax, u, v_ax, v)

        try:
            tiledef = TILES[self.pos.as_tuple(), side_norm.as_tuple()]
        except KeyError:
            # No tile. As a special case, if we're an EMBED and this side is
            # empty then embed so the instance can fit.
            if BLOCK_POS.lookup_world(self.pos) is Block.EMBED:
                try:
                    tiledef = TILES[
                        (self.pos + 128 * side_norm).as_tuple(),
                        self.normal.as_tuple()
                    ]
                except KeyError:
                    return True
                else:
                    return tiledef.base_type is TileType.VOID
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
            self[1, 0].is_white and self[2, 0].is_white and
            self[1, 3].is_white and self[2, 3].is_white
        ):
            return True

        # Finally, for floors/ceilings you can place it 'sideways'.
        return (
            self.normal.z != 0 and
            self[0, 1].is_white and self[0, 2].is_white and
            self[3, 1].is_white and self[3, 2].is_white
        )

    def use_bullseye(self) -> bool:
        """Check if this should use a bullseye overlay."""
        # If all four center blocks can't accept the overlay,
        # we can't add a bullseye.
        if (
            self[1, 1].is_tile or self[1, 2].is_tile or
            self[2, 1].is_tile or self[2, 2].is_tile
        ):
            return self.bullseye_count > 0
        else:
            return False

    def export(self, vmf: VMF) -> None:
        """Create the brushes for this.

        This is only called on special tiles with different patterns,
        or which have items modifying them.
        """
        bevels: set[tuple[int, int]] = set()
        for u, v, side_bevels in BEVEL_SIDES:
            if self.should_bevel(u, v):
                bevels |= side_bevels

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

        # The tiles used by panels can't be re-placed by other panels
        # or the "base".
        filled_tiles: dict[tuple[int, int], TileType] = {}

        for panel in self.panels:
            # Compute a copy of subtiles with only the tiles the panel
            # has, and also without the fizzler key if present.
            panel_tiles = {
                (u, v): tile if (
                    (u, v) in panel.points
                    and (u, v) not in filled_tiles
                ) else TileType.VOID
                for u, v, tile in self
            }
            panel.export(self, vmf, panel_tiles, has_helper, force_helper)
            # Then mark these tiles so later panels or the main panel don't
            # use them. If seal is true, use nodraw.
            for pos in panel.points:
                filled_tiles[pos] = TileType.NODRAW if panel.seal else TileType.VOID

        # Then copy the void/nodraw tiles down onto ourselves.
        for pos, tile in filled_tiles.items():
            self[pos] = tile

        if all(tile is TileType.VOID for u, v, tile in self):
            return

        faces, brushes = self.gen_multitile_pattern(
            vmf,
            self._get_subtiles(),
            is_wall,
            bevels,
            self.normal,
        )
        self.brush_faces.extend(faces)
        vmf.add_brushes(brushes)

        if has_helper and self.can_portal():
            # We need to make a placement helper.
            vmf.create_ent(
                'info_placement_helper',
                angles=Angle.from_basis(x=self.normal, z=self.portal_helper_orient),
                origin=front_pos,
                force_placement=force_helper,
                snap_to_helper_angles=force_helper,
                radius=64,
            )
        if self.use_bullseye():
            # Add the bullseye overlay.
            orient = Matrix.from_angle(self.normal.to_angle())
            srctools.vmf.make_overlay(
                vmf,
                orient.forward(),
                front_pos,
                64 * orient.left(),
                64 * orient.up(),
                texturing.OVERLAYS.get(front_pos, 'bullseye'),
                self.brush_faces,
            )

    def gen_multitile_pattern(
        self,
        vmf: VMF,
        pattern: dict[tuple[int, int], TileType],
        is_wall: bool,
        bevels: set[tuple[int, int]],
        normal: Vec,
        offset: int=64,
        thickness: int=4,
        vec_offset: Vec=None,
        is_panel: bool=False,
        add_bullseye: bool=False,
        face_output: dict[tuple[int, int], Side] | None=None,
        interior_bevel: bool=True,
    ) -> tuple[list[Side], list[Solid]]:
        """Generate a bunch of tiles, and return the front faces.

        This does the complex job of generating a surface with multiple
        tile types.

        The specified bevels are a set of UV points around the tile. If a tile
        neighbours one of these points, it will be bevelled. If interior_bevel
        is true, VOID tiles also are treated as this.

        If face_output is set, it will be filled with (u, v) -> top face.
        """
        brushes = []
        faces = []

        if interior_bevel:
            bevels = set(bevels)
            for uv, tile in pattern.items():
                if tile is TileType.VOID:
                    bevels.add(uv)

        # NOTE: calc_patterns can produce 0, 1, 1.5, 2, 2.5, 3, 4!
        # Half-values are for nodrawing fizzlers which are center-aligned.
        for umin, umax, vmin, vmax, grid_size, tile_type in self.calc_patterns(pattern, is_wall):
            u_range = range(max(int(umin), 0), min(int(umax), 4))
            v_range = range(max(int(vmin), 0), min(int(vmax), 4))

            tile_bevels = (
                any((int(umin)-1, i) in bevels for i in v_range),
                any((int(umax), i) in bevels for i in v_range),
                any((i, int(vmin)-1) in bevels for i in u_range),
                any((i, int(vmax)) in bevels for i in u_range),
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
                    ).get(tile_center, TileSize.GOO_SIDE, antigel=False)
                else:
                    if tile_type.is_4x4:
                        grid_size = TileSize.TILE_4x4
                    u_size, v_size = grid_size.size
                    tex = texturing.gen(
                        gen_cat, normal, tile_type.color,
                    ).get(tile_center, grid_size, antigel=self.is_antigel)

                template: template_brush.ScalingTemplate | None
                if self.override is not None:
                    tex, template = self.override
                else:
                    template = None

                brush, face = make_tile(
                    vmf,
                    tile_center,
                    normal,
                    top_surf=tex,
                    width=(umax - umin) * 32,
                    height=(vmax - vmin) * 32,
                    bevels=tile_bevels,
                    back_surf=texturing.SPECIAL.get(tile_center, 'behind', antigel=self.is_antigel),
                    u_align=u_size * 128,
                    v_align=v_size * 128,
                    thickness=thickness,
                    panel_edge=is_panel,
                    antigel=self.is_antigel,
                )
                if template is not None:
                    # If the texture isn't supplied, use the one from the
                    # template.
                    template.apply(face, change_mat=not tex)

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
                    bevels=tile_bevels,
                    back_surf=texturing.SPECIAL.get(tile_center, 'behind', antigel=self.is_antigel),
                    panel_edge=is_panel,
                    antigel=self.is_antigel,
                )
                faces.append(face)
                brushes.append(brush)
            elif tile_type is TileType.VOID:
                continue
            else:
                raise AssertionError(f"Can't gen {tile_type} yet.")

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
            self.panels or
            self.bullseye_count > 0 or
            self.override is not None
        ):
            return False

        return self.base_type.is_tile

    def add_portal_helper(self, orient: Vec | None = None) -> None:
        """Add a portal placement helper to the tile.

        If orient is provided, it should be the direction towards the
        top of the portal.
        """
        # Specific direction overrides everything.
        if orient is not None:
            if self.normal.dot(orient) > 0.001:
                raise ValueError(
                    'Portal orient of {} is not flat on a '
                    'plane with normal of {}!',
                    orient, self.normal,
                )
            self._portal_helper = round(orient, 6)
        elif isinstance(self._portal_helper, int):
            self._portal_helper += 1
        # else: it's already a Vec, so don't override with a generic helper.

    def remove_portal_helper(self, *, all: bool=False) -> None:
        """Remove a "generic" placement helper.

        If "all" is checked, all helpers are removed.
        Otherwise, specifically applied orients are never removed.
        """
        if all:
            self._portal_helper = 0
        elif isinstance(self._portal_helper, int):
            # Clamp at zero.
            self._portal_helper = max(0, self._portal_helper - 1)

    def position_bullseye(self, target: Entity) -> None:
        """Position a faith plate target to hit this panel.

        This needs to set origin.
        """
        # Ask each panel to position, which they will if angled.
        for panel in self.panels:
            if panel.steals_bullseye:
                panel.position_bullseye(self, target)
                break
        else:
            # No panels, default to flat on the surface.
            target['origin'] = self.pos + 64 * self.normal


def find_tile(
    origin: Vec | FrozenVec,
    normal: Vec | FrozenVec,
    force: bool = False,
) -> tuple[TileDef, int, int]:
    """Locate the tiledef for a specific tile.

    The tiledef and the subtile UV are returned, or KeyError is raised
    if the position has no tile. If force is true, create a tile at this location.
    """
    norm_axis = normal.axis()
    u_axis, v_axis = Vec.INV_AXIS[norm_axis]

    grid_pos = Vec.with_axes(
        norm_axis, origin - 64 * normal,
        u_axis, origin[u_axis] // 128 * 128 + 64,
        v_axis, origin[v_axis] // 128 * 128 + 64,
    )
    grid_pos: Vec = round(grid_pos, 6)
    normal: Vec = Vec(round(normal, 6))
    # grid_pos = round_grid(origin - normal)

    uv_pos = round(origin - grid_pos + 64 - 16, 6)
    u = uv_pos[u_axis] / 32 % 4
    v = uv_pos[v_axis] / 32 % 4

    if u != round(u) or v != round(v):
        raise KeyError(f'Bad tile position: {origin} with orient {normal} had a UV of {u}, {v}')

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
    force: bool = False,
    silent: bool = False,
) -> None:
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
    bevels: tuple[bool, bool, bool, bool]=(False, False, False, False),
    panel_edge: bool=False,
    u_align: int=512,
    v_align: int=512,
    antigel: bool | None = None,
) -> tuple[Solid, Side]:
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
        antigel: If the tile is known to be antigel.
    """
    assert TILE_TEMP, "make_tile called without data loaded!"
    template = TILE_TEMP[normal.as_tuple()]

    assert width >= 8 and height >= 8, 'Tile is too small!' \
                                       ' ({}x{})'.format(width, height)
    assert thickness in (2, 4, 8), f'Bad thickness {thickness}'

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

    umin_side.mat = texturing.SPECIAL.get(origin, edge_name, antigel=antigel)
    umax_side.mat = texturing.SPECIAL.get(origin, edge_name, antigel=antigel)
    vmin_side.mat = texturing.SPECIAL.get(origin, edge_name, antigel=antigel)
    vmax_side.mat = texturing.SPECIAL.get(origin, edge_name, antigel=antigel)

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

    categories: dict[tuple[int, bool], Solid] = {}
    cat_names = {
        (2, True): 'bevel_thin',
        (4, True): 'bevel_norm',
        (8, True): 'bevel_thick',

        (2, False): 'flat_thin',
        (4, False): 'flat_norm',
        (8, False): 'flat_thick',
    }

    try:
        template = template_brush.get_template(
            options.get(str, '_tiling_template_'))
        # Grab the single world brush for each visgroup.
        for (key, name) in cat_names.items():
            [categories[key]] = template.visgrouped_solids(name)
    except (KeyError, ValueError) as exc:
        raise Exception('Bad Tiling Template!') from exc

    for norm, orient in zip(NORMALS, NORMAL_ANGLES):
        axis_norm = norm.axis()

        temp_part: dict[str | tuple[int, int, int, bool], Side] = {}
        TILE_TEMP[norm.as_tuple()] = temp_part

        for (thickness, bevel), temp in categories.items():
            brush = temp.copy()
            brush.localise(Vec(), orient)

            for face in brush:
                if face.mat == consts.Special.BACKPANELS:
                    # Only copy the front and back from the normal template.
                    if thickness == 4 and not bevel:
                        temp_part['back'] = face
                        face.translate(+2.0 * norm)
                        # Set it to zero here, so we don't need to reset
                        # it in make_tile.
                        face.offset = 0
                elif face.mat in consts.BlackPan or face.mat in consts.WhitePan:
                    if thickness == 4 and not bevel:
                        temp_part['front'] = face
                        face.translate(-2.0 * norm)
                else:
                    # Squarebeams.
                    # Rounding the position of the face gives us the direction
                    # it's pointing away from the center.
                    face_norm: Vec = round(face.get_origin().norm(), 0)
                    face.translate(-16 * face_norm - (thickness / 2) * norm)
                    u_dir, v_dir = face_norm.other_axes(axis_norm)
                    temp_part[int(u_dir), int(v_dir), thickness, bevel] = face
            # Verify all keys are present.
            assert (1, 0, thickness, bevel) in temp_part, f't={thickness}, b={bevel}, res={temp_part}'
            assert (0, 1, thickness, bevel) in temp_part, f't={thickness}, b={bevel}, res={temp_part}'
            assert (0, -1, thickness, bevel) in temp_part, f't={thickness}, b={bevel}, res={temp_part}'
            assert (-1, 0, thickness, bevel) in temp_part, f't={thickness}, b={bevel}, res={temp_part}'
        assert 'front' in temp_part
        assert 'back' in temp_part


def analyse_map(vmf_file: VMF, side_to_ant_seg: dict[int, list[antlines.Segment]]) -> None:
    """Create TileDefs from all the brush sides.

    Once done, all wall brushes have been removed from the map.
    """

    # Face ID -> tileDef, used to match overlays to their face targets.
    # Invalid after we exit, since all the IDs have been freed and may be
    # reused later.
    face_to_tile: dict[int, TileDef] = {}

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
            LOGGER.warning(f'Unrecognised brush from {bbox_min} to {bbox_max}')
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
    panel_fname = instanceLocs.resolve_filter('<ITEM_PANEL_ANGLED>, <ITEM_PANEL_FLIP>')
    # Also find PeTI-placed placement helpers, and move them into the tiledefs.
    placement_helper_file = instanceLocs.resolve_filter('<ITEM_PLACEMENT_HELPER>')

    panels: dict[str, Entity] = {}
    for inst in vmf_file.by_class['func_instance']:
        filename = inst['file'].casefold()
        if filename in panel_fname:
            panels[inst['targetname']] = inst
        elif filename in placement_helper_file:
            angles = Angle.from_str(inst['angles'])
            pos = Vec(0, 0, -128)
            pos.localise(Vec.from_str(inst['origin']), angles)
            up = Matrix.from_angle(angles).up()
            try:
                tile = TILES[pos.as_tuple(), up.as_tuple()]
            except KeyError:
                pass  # On goo or the like.
            else:
                tile.add_portal_helper()
            inst.remove()

    dynamic_pan_parent = options.get(str, "dynamic_pan_parent")

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

    # Remove the pedestal platforms. Use templates instead if you need to.
    for ent in vmf_file.by_class['func_detail']:
        for side in ent.sides():
            if side == consts.Special.PED_SIDE:
                vmf_file.remove_ent(ent)
                break  # Skip to next entity

    # Tell the antlines which tiledefs they attach to.
    for side_id, segments in side_to_ant_seg.items():
        try:
            tile = face_to_tile[side_id]
        except KeyError:
            continue
        for seg in segments:
            seg.tiles.add(tile)

    # Parse face IDs saved in overlays - if they're matching a tiledef,
    # remove them.
    for over in vmf_file.by_class['info_overlay']:
        faces = over['sides', ''].split()
        tiles = OVERLAY_BINDS[over] = []
        for face in faces[:]:
            try:
                tiles.append(face_to_tile[int(face)])
            except (KeyError, ValueError):
                pass
            else:
                faces.remove(face)
        over['sides'] = ' '.join(faces)

    # Strip out all the original goo triggers. Ignore ones with names, so we don't touch
    # laserfield triggers here.
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
            for fnorm in NORMALS:
                grid_pos = grid_to_world(pos) - 128 * fnorm
                try:
                    tile = TILES[grid_pos.as_tuple(), fnorm.as_tuple()]
                except KeyError:
                    continue

                for u, v, tile_type in tile:
                    if tile_type in goo_replaceable:
                        tile[u, v] = TileType.GOO_SIDE


def tiledefs_from_cube(face_to_tile: dict[int, TileDef], brush: Solid, grid_pos: Vec) -> None:
    """Generate a tiledef matching a 128^3 block."""
    for face in brush:
        normal = -face.normal()

        # These cubes don't contain any items, so it's fine
        # if we get rid of sides that aren't useful.
        # if it's bordering void or another solid, it's unneeded.
        neighbour_block = BLOCK_POS.lookup_world(grid_pos + 128 * normal)
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
    face_to_tile: dict[int, TileDef],
    brush: Solid,
    grid_pos: Vec,
    norm: Vec,
) -> None:
    """Generate a tiledef matching a 128x128x4 side."""
    tex_kind, front_face = find_front_face(brush, grid_pos, norm)

    neighbour_block = BLOCK_POS.lookup_world(grid_pos + 128 * norm)

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
    norm = Vec(z=1) @ Angle.from_str(panel_ent['angles'])
    grid_pos -= 128*norm

    tex_kind, front_face = find_front_face(brush, grid_pos, norm)

    TILES[grid_pos.as_tuple(), norm.as_tuple()] = tile = TileDef(
        grid_pos,
        norm,
        base_type=tex_kind,
        # Add a helper if portalable.
        has_helper=tex_kind.is_white,
    )
    tile.panels.append(Panel(
        brush_ent,
        panel_ent,
        PanelType.NORMAL,
        thickness=2,
        bevels=set(BEVEL_AROUND),
    ))


def tiledef_from_flip_panel(brush_ent: Entity, panel_ent: Entity) -> None:
    """Generate a tiledef matching a flip panel."""
    brush_ent.solids.clear()
    grid_pos = round_grid(Vec.from_str(panel_ent['origin']))
    norm = Vec(z=1) @ Angle.from_str(panel_ent['angles'])
    grid_pos -= 128*norm

    # To match the editor model, flip around the orientation.
    panel_ent['spawnflags'] = srctools.conv_int(panel_ent['spawnflags']) ^ 2

    TILES[grid_pos.as_tuple(), norm.as_tuple()] = tile = TileDef(
        grid_pos,
        norm,
        # It's always white in the forward direction
        base_type=TileType.WHITE,
        # Flip panels always are portalable at some point, so add a helper.
        has_helper=True,
    )
    tile.panels.append(Panel(
        brush_ent,
        panel_ent,
        PanelType.FLIP_BLACK,
    ))


def tiledefs_from_embedface(
    face_to_tile: dict[int, TileDef],
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
) -> tuple[TileType, Side]:
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
        raise Exception(f'Malformed wall brush at {grid_pos}, {norm}')


def inset_flip_panel(panel: list[Solid], pos: Vec, normal: Vec) -> None:
    """Inset the sides of a flip panel, to not hit the borders."""
    norm_axis = normal.axis()
    for brush in panel:
        for side in brush:
            norm = side.normal()
            if abs(Vec.dot(norm, normal)) > 0.99:
                continue  # Front or back

            u_off, v_off = (side.get_origin() - pos).other_axes(norm_axis)
            if abs(round(u_off)) == 64 or abs(round(v_off)) == 64:
                side.translate(2 * norm)
                # Snap squarebeams to each other.
                side.vaxis.offset = 0


def bevel_split(
    rect_points: Plane[bool],
    tile_pos: Plane[TileDef],
) -> Iterator[tuple[int, int, int, int, tuple[bool, bool, bool, bool]]]:
    """Split the optimised segments to produce the correct bevelling."""
    for min_u, min_v, max_u, max_v, _ in grid_optim.optimise(rect_points):
        u_range = range(min_u, max_u + 1)
        v_range = range(min_v, max_v + 1)

        # These are sort of reversed around, which is a little confusing.
        # Bevel U is facing in the U direction, running across the V.
        bevel_umins: list[bool] = [
            tile_pos[min_u, v].should_bevel(-1, 0)
            for v in v_range
        ]
        bevel_umaxes: list[bool] = [
            tile_pos[max_u, v].should_bevel(1, 0)
            for v in v_range
        ]
        bevel_vmins: list[bool] = [
            tile_pos[u, min_v].should_bevel(0, -1)
            for u in u_range
        ]
        bevel_vmaxes: list[bool] = [
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
    full_tiles: dict[
        tuple[float, float, float, float, TileType],
        list[TileDef]
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
                    angles=Angle.from_basis(x=tile.normal, z=tile.portal_helper_orient),
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

        # (type, is_antigel, texture) -> (u, v) -> present/absent
        grid_pos: dict[tuple[TileType, bool, str], Plane[bool]] = defaultdict(Plane)

        tile_pos: Plane[TileDef] = Plane()

        for tile in tiles:
            pos = tile.pos + 64 * tile.normal

            if tile_type is TileType.GOO_SIDE:
                # This forces a specific size.
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    Portalable.BLACK
                ).get(pos, TileSize.GOO_SIDE, antigel=False)
            elif tile_type is TileType.NODRAW:
                tex = consts.Tools.NODRAW
            else:
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    tile.base_type.color
                ).get(pos, tile.base_type.tile_size, antigel=tile.is_antigel)

            u_pos = int((pos[u_axis] - bbox_min[u_axis]) // 128)
            v_pos = int((pos[v_axis] - bbox_min[v_axis]) // 128)
            grid_pos[tile.base_type, tile.is_antigel, tex][u_pos, v_pos] = True
            tile_pos[u_pos, v_pos] = tile

        for (subtile_type, is_antigel, tex), tex_pos in grid_pos.items():
            for min_u, min_v, max_u, max_v, bevels in bevel_split(tex_pos, tile_pos):
                center = Vec.with_axes(
                    norm_axis, plane_dist,
                    # Compute avg(128*min, 128*max)
                    # = (128 * min + 128 * max) / 2
                    # = (min + max) * 64
                    u_axis, bbox_min[u_axis] + (min_u + max_u) * 64,
                    v_axis, bbox_min[v_axis] + (min_v + max_v) * 64,
                )
                gen = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    subtile_type.color
                )
                if TileSize.TILE_DOUBLE in gen and (1 + max_u - min_u) % 2 == 0 and (1 + max_v - min_v) % 2 == 0:
                    is_double = True
                    tex = gen.get(center, TileSize.TILE_DOUBLE, antigel=is_antigel)
                else:
                    is_double = False

                brush, front = make_tile(
                    vmf,
                    center,
                    normal,
                    tex,
                    texturing.SPECIAL.get(center, 'behind', antigel=is_antigel),
                    bevels=bevels,
                    width=(1 + max_u - min_u) * 128,
                    height=(1 + max_v - min_v) * 128,
                    antigel=is_antigel,
                )
                vmf.add_brush(brush)
                if is_double:
                    # Compute the offset so that a 0,0 aligned brush can be
                    # offset so that point is at the minimum point of the tile,
                    # then round to the nearest 256 tile.
                    # That will ensure it gets the correct texturing.
                    # We know the scale is 0.25, so don't bother looking that up.
                    tile_min = Vec.with_axes(
                        norm_axis, plane_dist,
                        u_axis, bbox_min[u_axis] + 128 * min_u - 64,
                        v_axis, bbox_min[v_axis] + 128 * min_v - 64,
                    )
                    front.uaxis.offset = (Vec.dot(tile_min, front.uaxis.vec()) / 0.25) % (256/0.25)
                    front.vaxis.offset = (Vec.dot(tile_min, front.vaxis.vec()) / 0.25) % (256/0.25)
                    if gen.options['scaleup256']:
                        # It's actually a 128x128 tile, that we want to double scale for.
                        front.scale = 0.5
                        front.uaxis.offset /= 2
                        front.vaxis.offset /= 2

                for u in range(min_u, max_u + 1):
                    for v in range(min_v, max_v + 1):
                        tile_pos[u, v].brush_faces.append(front)

    LOGGER.info('Generating goop...')
    generate_goo(vmf)

    nodraw = consts.Tools.NODRAW
    for over, over_tiles in OVERLAY_BINDS.items():
        # Keep already set sides.
        faces = set(over['sides', ''].split())
        # We don't want to include nodraw, since that doesn't accept
        # overlays anyway.
        for tile in over_tiles:
            faces.update(
                str(f.id)
                for f in tile.brush_faces
                if f.mat != nodraw
            )

        # If it turns out there's no faces for this, discard the overlay.
        if faces:
            over['sides'] = ' '.join(sorted(faces))
        else:
            over.remove()


@attrs.define(frozen=False)
class Tideline:
    """Temporary data used to hold the in-progress tideline overlays."""
    over: Entity
    mid: float
    min: float
    max: float


def generate_goo(vmf: VMF) -> None:
    """Generate goo pit brushes and triggers."""
    # We want to use as few brushes as possible.
    # So group them by their min/max Z, and then produce bounding boxes.
    goo_pos: dict[tuple[float, float], dict[tuple[int, int], int]] = defaultdict(dict)

    # For triggers, we want to only group by the top surface, we don't care
    # how deep.
    trig_pos: dict[float, dict[tuple[int, int], bool]] = defaultdict(dict)

    # Calculate the z-level with the largest number of goo brushes,
    # so we can ensure the 'fancy' pit is the largest one.
    # Valve just does it semi-randomly.
    goo_heights: dict[float, int] = Counter()

    # If enabled, generate tideline overlays.
    use_tidelines = options.get(bool, 'generate_tidelines')
    # Z, x-cell, y-cell, x-norm, y-norm = overlay ent.
    tideline_over: dict[tuple[float, float, float, int, int], Tideline] = {}

    pos: Vec | None = None
    for pos, block_type in BLOCK_POS.items():
        if block_type is Block.GOO_SINGLE:
            goo_pos[pos.z, pos.z][round(pos.x), round(pos.y)] = True
        elif block_type is Block.GOO_TOP:
            # Multi-layer..
            lower_pos = BLOCK_POS.raycast(pos, Vec(0, 0, -1))

            goo_pos[lower_pos.z, pos.z][round(pos.x), round(pos.y)] = True
        else:  # Not goo.
            continue
        goo_heights[pos.z] += 1
        trig_pos[pos.z][round(pos.x), round(pos.y)] = True
        if use_tidelines:
            voxel_center = 128 * pos + 64
            for x, y in [(-1, 0), (0, -1), (1, 0), (0, 1)]:
                norm = Vec(x, y)
                try:
                    tile = TILES[(voxel_center - 128*norm).as_tuple(), (x, y, 0)]
                except KeyError:
                    continue
                side = Vec.cross(norm, (0.0, 0.0, -1.0))
                off = Vec.dot(voxel_center, side)

                # Divide the x/y into sections, so we don't extend the overlay
                # too much over too many faces.
                key = pos.z, pos.x//8, pos.y//8, x, y
                try:
                    tideline = tideline_over[key]
                except KeyError:
                    ent_pos = voxel_center + 32 * Vec(x, y, 1)
                    tideline = tideline_over[key] = Tideline(
                        vmf.create_ent(
                            'info_overlay',
                            material=texturing.OVERLAYS.get(ent_pos, 'tideline'),
                            angles='0 0 0',
                            origin=ent_pos,
                            basisOrigin=ent_pos,
                            basisNormal=f'{x} {y} 0',
                            basisU=side,
                            basisV='0 0 1',
                            startU='0',
                            startV='1',
                            endU='1',
                            endV='0',
                        ),
                        off, off, off,
                    )
                    OVERLAY_BINDS[tideline.over] = [tile]
                else:
                    tideline.min = min(tideline.min, off)
                    tideline.max = max(tideline.max, off)
                    OVERLAY_BINDS[tideline.over].append(tile)

    for tideline in tideline_over.values():
        tide_min = tideline.min - tideline.mid - 64
        tide_max = tideline.max - tideline.mid + 64
        rng = rand.seed(b'tideline', tide_min, tide_max)

        width = (tide_max - tide_min) / 128.0
        # Randomly flip around
        if rng.choice((False, True)):
            tideline.over['startu'] = 0
            tideline.over['endu'] = width
        else:
            tideline.over['endu'] = 0
            tideline.over['startu'] = width

        # Vary the ends up/down from 32, to distort a little.
        tideline.over['uv0'] = f'{tide_min} {rng.randint(-36, -28)} 0'
        tideline.over['uv1'] = f'{tide_min} {rng.randint(28, 32)} 0'
        tideline.over['uv2'] = f'{tide_max} {rng.randint(28, 32)} 0'
        tideline.over['uv3'] = f'{tide_max} {rng.randint(-36, -28)} 0'

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
        Output('OnStartTouch', '!activator', 'CallScriptFunction', 'FellInGoo', delay=0.01),
        Output('OnStartTouch', '!activator', 'Kill', delay=0.1),
    )

    trig_hurt = vmf.create_ent(
        'trigger_hurt',
        spawnflags='1',  # Clients
        damage='1000',
        damagecap='1000',
        damagetype=(1 << 18),  # Radiation
    )

    goo_scale = options.get(float, 'goo_scale')

    # Find key with the highest value - that gives the largest z-level.
    [best_goo, _] = max(goo_heights.items(), key=lambda x: x[1])

    for ((min_z, max_z), grid) in goo_pos.items():
        for min_x, min_y, max_x, max_y, _ in grid_optim.optimise(grid):
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
                    max_z == best_goo
                    else 'goo_cheap'
                ),
            )
            vmf.add_brush(prism.solid)

    bbox_min = Vec()

    for (z, grid) in trig_pos.items():
        for min_x, min_y, max_x, max_y, _ in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, z) * 128
            bbox_max = Vec(max_x, max_y, z) * 128
            trig_hurt.solids.append(vmf.make_prism(
                bbox_min,
                # 19 units below the surface.
                bbox_max + (128, 128, 96 - 19),
                mat=consts.Tools.TRIGGER,
            ).solid)
            trig_phys.solids.append(vmf.make_prism(
                bbox_min,
                # 70 units below the surface - 1 unit more than the height of a turret with its
                # antenna extended. Most likely this is why PeTI uses this particular height.
                bbox_max + (128, 128, 96 - 70),
                mat=consts.Tools.TRIGGER,
            ).solid)

    # Set to any random position for the entity.
    trig_phys['origin'] = trig_hurt['origin'] = bbox_min + 64
