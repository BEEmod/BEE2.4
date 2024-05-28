"""Templates are sets of brushes which can be copied into the map."""
from __future__ import annotations
from typing import Literal, assert_never

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Set as AbstractSet
from collections import defaultdict
from decimal import Decimal
from enum import Enum
from operator import attrgetter
import itertools
import os

import trio
import attrs

from srctools import Keyvalues
from srctools.filesys import FileSystem, ZipFileSystem, RawFileSystem, VPKFileSystem
from srctools.math import AnyAngle, AnyMatrix, FrozenVec, Vec, Angle, Matrix, to_matrix
from srctools.vmf import Entity, EntityGroup, Solid, Side, VMF, UVAxis, ValidKVs, VisGroup
from srctools.dmx import Element
import srctools.logger

from . import tiling, texturing, options, rand, connections, collisions, barriers
from .texturing import Portalable, GenCat, TileSize
from .tiling import TileType
from plane import PlaneKey
import user_errors
import utils
import consts


LOGGER = srctools.logger.get_logger(__name__, alias='template')

# Lookups for templates.
# _TEMPLATES is initially filled with UnparsedTemplate,
# then when each is retrieved we parse to an actual Template.
# _SCALE_TEMP is converted from Template. The frozenset is the visgroups.
_TEMPLATES: dict[str, UnparsedTemplate | Template] = {}
_SCALE_TEMP: dict[tuple[str, frozenset[str]], ScalingTemplate] = {}


class InvalidTemplateName(LookupError):
    """Raised if a template ID is invalid."""
    def __init__(self, temp_name: str) -> None:
        self.temp_name = temp_name

    def __str__(self) -> str:
        # List all the templates that are available.
        return 'Template not found: "{}"\nValid templates:\n{}'.format(
            self.temp_name,
            '\n'.join(
                (' * "' + temp.upper() + '"')
                for temp in
                sorted(_TEMPLATES.keys())
            ),
        )


class TEMP_TYPES(Enum):
    """Value used for import_template()'s force_type parameter.
    """
    default = 0  # Based on the original VMF settings
    world = 1  # Import and add to world
    detail = 2  # Import as a func_detail


class AfterPickMode(Enum):
    """Value used for ColorPicker's remove_brush option."""
    NONE = '0'  # Don't do anything.
    VOID = '1'  # Remove the tile entirely.
    NODRAW = '2'  # Convert to nodraw.


@utils.freeze_enum_props
class AppliedColour(Enum):
    """Different behaviours for tilesetters, other than forcing a specific colour.

    "tile" is also allowed, but that gets converted to Portalable instead.
    """
    MATCH = 'match'
    INVERT = 'invert'
    COPY = 'copy'

    @property
    def inverted(self) -> AppliedColour:
        """Invert this operation."""
        if self is AppliedColour.MATCH:
            return AppliedColour.INVERT
        if self is AppliedColour.INVERT:
            return AppliedColour.MATCH
        if self is AppliedColour.COPY:
            return self
        assert_never(self)


@attrs.define
class UnparsedTemplate:
    """Holds the location of a template that hasn't been parsed yet."""
    id: str
    pak_path: str
    path: str


@attrs.define
class TemplateEntity:
    """One of the several entities defined in templates."""
    visgroups: set[str]  # Visgroups applied to this entity.

    def is_applicable(self, visgroups: Iterable[str]) -> bool:
        """Check if this entity should be used."""
        return self.visgroups.issubset(visgroups)


@attrs.define
class PlanarTemplateEntity(TemplateEntity):
    """A template entity that is applied to a specific plane."""
    offset: Vec
    normal: Vec  # Normal of the surface.


@attrs.define
class ColorPicker(PlanarTemplateEntity):
    """Color pickers allow applying the existing colors onto faces."""
    priority: Decimal  # Decimal order to do them in.
    name: str  # Name to reference from other ents.
    sides: list[str]
    grid_snap: bool  # Snap to grid on non-normal axes
    after: AfterPickMode  # What to do after the color is picked.
    # Instead of just changing the colour, copy the entire face from the
    # tiledef.
    use_pattern: bool

    # Or, use a pair of preset white/black textures.
    force_tex_white: str
    force_tex_black: str


@attrs.define
class VoxelSetter(PlanarTemplateEntity):
    """Set all tiles in a tiledef."""
    tile_type: TileType  # Type to produce.
    force: bool  # Force overwrite existing values.


@attrs.define
class TileSetter(VoxelSetter):
    """Set tiles in a particular position."""
    color: AppliedColour | Portalable
    picker_name: str  # Name of colorpicker to use for the color.


@attrs.define
class CollisionDef(TemplateEntity):
    """Adds a collision shape to the map."""
    bbox: collisions.BBox
    visgroups: set[str]  # Visgroups required to add this.


@attrs.define
class BarrierSetter(PlanarTemplateEntity):
    """Alter the glass/grating barrier present in a particlar sub-voxel."""
    # The ID to use. Blank = remove.
    id: utils.ObjectID | utils.BlankID
    force: bool  # Overwrite an existing barrier if true. Always overwrites if removing.


@attrs.define
class BarrierClearer(PlanarTemplateEntity):
    """Remove barriers on all sides of the specified sub-voxel."""


# We use the skins value on the tilesetter to specify type, allowing visualising it.
# So this is the type for each index.
SKIN_TO_TILETYPE = [
    TileType.BLACK,
    TileType.BLACK_4x4,
    TileType.WHITE,
    TileType.WHITE_4x4,
    TileType.NODRAW,
    TileType.VOID,
    TileType.CUTOUT_TILE_BROKEN,
    TileType.CUTOUT_TILE_PARTIAL,
]
TILETYPE_TO_SKIN = {
    tile_type: skin
    for skin, tile_type in enumerate(SKIN_TO_TILETYPE)
}

NORMALS = [
    Vec.N, Vec.S, Vec.E, Vec.W, Vec.T, Vec.B,
]

B = Portalable.BLACK
W = Portalable.WHITE
TEMPLATE_RETEXTURE: dict[str, tuple[GenCat, str, None] | tuple[GenCat, TileSize, Portalable]] = {
    # textures map -> surface types for template brushes.
    # It's mainly for grid size and colour - floor/ceiling textures
    # will be used instead at those orientations

    'metal/black_wall_metal_002a': (GenCat.NORMAL, TileSize.TILE_2x2, B),
    'metal/black_wall_metal_002b': (GenCat.NORMAL, TileSize.TILE_4x4, B),
    'metal/black_wall_metal_002c': (GenCat.NORMAL, TileSize.TILE_1x1, B),
    'metal/black_wall_metal_002e': (GenCat.NORMAL, TileSize.TILE_2x1, B),

    'tile/white_wall_tile001a': (GenCat.NORMAL, TileSize.TILE_1x1, W),
    'tile/white_wall_tile003a': (GenCat.NORMAL, TileSize.TILE_1x1, W),
    'tile/white_wall_tile003b': (GenCat.NORMAL, TileSize.TILE_1x1, W),
    'tile/white_wall_tile003c': (GenCat.NORMAL, TileSize.TILE_2x2, W),
    'tile/white_wall_tile003h': (GenCat.NORMAL, TileSize.TILE_1x1, W),
    'tile/white_wall_state': (GenCat.NORMAL, TileSize.TILE_2x2, W),
    'tile/white_wall_tile003f': (GenCat.NORMAL, TileSize.TILE_4x4, W),

    'tile/white_wall_tile004j': (GenCat.PANEL, TileSize.TILE_1x1, W),

    # No black portal-placement texture, so use the bullseye instead
    'metal/black_floor_metal_bullseye_001': (GenCat.PANEL, TileSize.TILE_1x1, B),
    'tile/white_wall_tile_bullseye': (GenCat.PANEL, TileSize.TILE_1x1, W),

    consts.Special.BACKPANELS: (GenCat.SPECIAL, 'behind', None),
    consts.Special.BACKPANELS_CHEAP: (GenCat.SPECIAL, 'behind', None),
    consts.Special.SQUAREBEAMS: (GenCat.SPECIAL, 'edge', None),
    consts.Special.GLASS: (GenCat.SPECIAL, 'glass', None),
    consts.Special.GRATING: (GenCat.SPECIAL, 'grating', None),

    consts.Goo.CHEAP: (GenCat.SPECIAL, 'goo_cheap', None),
}
del B, W

TEMP_TILE_PIX_SIZE = {
    # The width in texture pixels of each tile size.
    # We decrease offset to this much +- at maximum (so adjacent template
    # brushes merge with each other). This still allows creating brushes
    # with half-grid offsets.
    '4x4': 128,
    'floor': 128,  # == 4x4
    'ceiling': 128,

    '2x2': 256,

    'wall': 512,
    'special': 512,
}


# 'Opposite' values for retexture_template(force_colour)
type ForceColour = Literal[
    AppliedColour.MATCH, AppliedColour.INVERT,
    Portalable.white, Portalable.black,
]
TEMP_COLOUR_INVERT: dict[ForceColour, ForceColour] = {
    Portalable.white: Portalable.black,
    Portalable.black: Portalable.white,
    AppliedColour.MATCH: AppliedColour.INVERT,
    AppliedColour.INVERT: AppliedColour.MATCH,
}


@attrs.define(frozen=True, kw_only=True)
class ExportedTemplate:
    """The result of importing a template.

    THis contains all the changes made. orig_ids is a dict mapping the original
    IDs in the template file to the new ones produced.
    Once retexture_template() is caled, picker_results contains the detected
    surface types for colorpickers.

    """
    world: list[Solid]
    detail: Entity | None
    overlay: list[Entity]
    orig_ids: dict[int, int]
    template: Template
    origin: Vec
    orient: Matrix
    visgroups: set[str]
    picker_results: dict[str, Portalable | None]
    picker_type_results: dict[str, TileType | None]
    debug_marker: Callable[..., None] | None


# Make_prism() generates faces aligned to world, copy the required UVs.
realign_solid: Solid = VMF().make_prism(Vec(-16, -16, -16), Vec(16, 16, 16)).solid
REALIGN_UVS: Mapping[FrozenVec, tuple[UVAxis, UVAxis]] = {
    face.normal().freeze(): (face.uaxis, face.vaxis)
    for face in realign_solid
}
del realign_solid


class Template:
    """Represents a template before it's imported into a map."""
    _data: dict[str, tuple[list[Solid], list[Solid], list[Entity]]]
    def __init__(
        self, *,
        temp_id: str,
        visgroup_names: set[str],
        world: dict[str, list[Solid]],
        detail: dict[str, list[Solid]],
        overlays: dict[str, list[Entity]],
        skip_faces: Iterable[str] = (),
        realign_faces: Iterable[str] = (),
        overlay_transfer_faces: Iterable[str] = (),
        vertical_faces: Iterable[str] = (),
        color_pickers: Iterable[ColorPicker] = (),
        tile_setters: Iterable[TileSetter] = (),
        voxel_setters: Iterable[VoxelSetter] = (),
        barrier_setters: Iterable[BarrierSetter] = (),
        barrier_clearers: Iterable[BarrierClearer] = (),
        coll: Iterable[CollisionDef] = (),
        debug: bool = False,
    ) -> None:
        self.id = temp_id
        self._data = {}
        self.debug = debug  # When true, dump info to the map when placed.

        # We ensure the '' group is always present.
        visgroup_names.add('')
        visgroup_names.update(world)
        visgroup_names.update(detail)
        visgroup_names.update(overlays)
        for ent in itertools.chain(
            color_pickers, tile_setters, voxel_setters,
            barrier_setters, barrier_clearers, coll,
        ):
            visgroup_names.update(ent.visgroups)

        for group in visgroup_names:
            self._data[group] = (
                world.get(group, []),
                detail.get(group, []),
                overlays.get(group, []),
            )

        self.realign_faces = set(realign_faces)
        self.overlay_faces = set(overlay_transfer_faces)
        self.vertical_faces = set(vertical_faces)
        self.skip_faces = set(skip_faces)
        # Sort so high IDs are first.
        self.color_pickers = sorted(
            color_pickers,
            key=attrgetter('priority'),
            reverse=True,
        )
        self.tile_setters = list(tile_setters)
        self.voxel_setters = list(voxel_setters)
        # Ensure those that clear barriers occur first.
        self.barrier_setters = sorted(barrier_setters, key=lambda setter: setter.id != "")
        self.barrier_clearers = list(barrier_clearers)
        self.collisions = list(coll)

    def __repr__(self) -> str:
        return (
            f'<Template "{self.id}", '
            f'groups={self._data.keys() - {""}}>'
        )

    @property
    def visgroups(self) -> AbstractSet[str]:
        """Return a view of the template visgroups."""
        return self._data.keys()

    def visgrouped(
        self,
        visgroups: str | Iterable[str] = (),
    ) -> tuple[list[Solid], list[Solid], list[Entity]]:
        """Given some visgroups, return the matching data.

        This returns lists of the world brushes, detail brushes, and overlays.
        visgroups can also be a single string, to select that.
        """
        if isinstance(visgroups, str):
            chosen = {visgroups, ''}
        else:
            chosen = {*visgroups, ''}

        world_brushes: list[Solid] = []
        detail_brushes: list[Solid] = []
        overlays: list[Entity] = []

        for group in chosen:
            try:
                world, detail, over = self._data[group.casefold()]
            except KeyError:
                raise ValueError(
                    f'Unknown visgroup "{group}" for "{self.id}"! '
                    f'(valid: {", ".join(map(repr, self._data))})'
                ) from None
            world_brushes.extend(world)
            detail_brushes.extend(detail)
            overlays.extend(over)

        return world_brushes, detail_brushes, overlays

    def visgrouped_solids(self, visgroups: str | Iterable[str] = ()) -> list[Solid]:
        """Given some visgroups, return the matching brushes.

        This ignores the world/detail brush distinction.
        """
        world, detail, _ = self.visgrouped(visgroups)
        return world + detail


class ScalingTemplate(Mapping[
    Vec | tuple[float, float, float],
    tuple[str, UVAxis, UVAxis, float]
]):
    """Represents a special version of templates, used for texturing brushes.

    The template is a single world-aligned cube brush, with the 6 sides used
    to determine orientation and materials for some texture set.
    It's stored in an ent, so we don't need all the data. Values are returned
    as (material, U, V, rotation) tuples.
    """

    def __init__(
        self,
        temp_id: str,
        axes: dict[FrozenVec, tuple[str, UVAxis, UVAxis, float]],
    ) -> None:
        self.id = temp_id
        self._axes = axes
        missing = {
            FrozenVec(0, 0, 1), FrozenVec(0, 0, -1),
            FrozenVec(1, 0, 0), FrozenVec(-1, 0, 0),
            FrozenVec(0, -1, 0), FrozenVec(0, 1, 0),
        } - axes.keys()
        if missing:
            raise ValueError(f'Missing axes for scaling template {temp_id}: {missing}')

    @classmethod
    def world(cls, mat: str = consts.Tools.NODRAW) -> ScalingTemplate:
        """Return a scaling template that produces world-aligned brushes."""
        return cls('<world>', {
            norm: (mat, uaxis, vaxis, 0.0)
            for norm, (uaxis, vaxis) in
            REALIGN_UVS.items()
        })

    def __repr__(self) -> str:
        return f'<ScalingTemplate "{self.id}">'

    def __len__(self) -> int:
        return 6

    def __iter__(self) -> Iterator[Vec]:
        yield from [
            Vec(-1, 0, 0),
            Vec(1, 0, 0),
            Vec(0, -1, 0),
            Vec(0, 1, 0),
            Vec(0, 0, -1),
            Vec(0, 0, 1),
        ]

    def __getitem__(
        self,
        normal: Vec | FrozenVec | tuple[float, float, float],
    ) -> tuple[str, UVAxis, UVAxis, float]:
        mat, axis_u, axis_v, rotation = self._axes[FrozenVec(normal)]
        return mat, axis_u.copy(), axis_v.copy(), rotation

    def rotate(
        self,
        angles: AnyAngle | AnyMatrix,
        origin: Vec | FrozenVec | None = None,
    ) -> ScalingTemplate:
        """Rotate this template, and return a new template with those angles."""
        new_axis: dict[FrozenVec, tuple[str, UVAxis, UVAxis, float]] = {}
        if origin is None:
            origin = Vec()

        orient = to_matrix(angles)
        for norm, (mat, axis_u, axis_v, rot) in self._axes.items():
            axis_u = axis_u.localise(origin, orient)
            axis_v = axis_v.localise(origin, orient)
            new_axis[norm @ orient] = mat, axis_u, axis_v, rot

        return ScalingTemplate(self.id, new_axis)

    def apply(self, face: Side, *, change_mat: bool = True) -> None:
        """Apply the template to a face."""
        mat, face.uaxis, face.vaxis, face.ham_rot = self[face.normal()]
        if change_mat:
            face.mat = mat


def parse_temp_name(name: str) -> tuple[str, set[str]]:
    """Parse the visgroups off the end of an ID."""
    if ':' in name:
        temp_name, visgroups = name.rsplit(':', 1)
        return temp_name.casefold(), {
            # Parse comma-seperated visgroups, remove empty, and casefold.
            visgroup.strip().casefold()
            for visgroup in visgroups.split(',')
            if not visgroup.isspace()
        }
    else:
        return name.casefold(), set()


async def load_templates(path: str) -> None:
    """Load in the template file, used for import_template()."""
    def read_templates() -> Element:
        """Read templates from disk."""
        with open(path, 'rb') as f:
            dmx, fmt_name, fmt_ver = Element.parse(f, unicode=True)
        if fmt_name != 'bee_templates' or fmt_ver not in [1]:
            raise ValueError(f'Invalid template file format "{fmt_name}" v{fmt_ver}')
        return dmx

    dmx = await trio.to_thread.run_sync(read_templates)

    for template in dmx['temp'].iter_elem():
        _TEMPLATES[template.name.casefold()] = UnparsedTemplate(
            template.name.upper(),
            template['package'].val_str,
            template['path'].val_str,
        )


def _parse_template(loc: UnparsedTemplate) -> Template:
    """Parse a template VMF."""
    filesys: FileSystem
    if os.path.isdir(loc.pak_path):
        filesys = RawFileSystem(loc.pak_path)
    else:
        ext = os.path.splitext(loc.pak_path)[1].casefold()
        if ext in ('.bee_pack', '.zip'):
            filesys = ZipFileSystem(loc.pak_path)
        elif ext == '.vpk':
            filesys = VPKFileSystem(loc.pak_path)
        else:
            raise ValueError(f'Unknown filesystem type for "{loc.pak_path}"!')

    with filesys[loc.path].open_str() as f:
        kv = Keyvalues.parse(f, f'{loc.pak_path}:{loc.path}')
    vmf = srctools.VMF.parse(kv, preserve_ids=True)
    del kv, filesys, f  # Discard all this data.

    # visgroup -> list of brushes/overlays
    detail_ents: dict[str, list[Solid]] = defaultdict(list)
    world_ents: dict[str, list[Solid]] = defaultdict(list)
    overlay_ents: dict[str, list[Entity]] = defaultdict(list)

    color_pickers: list[ColorPicker] = []
    tile_setters: list[TileSetter] = []
    voxel_setters: list[VoxelSetter] = []
    barrier_setters: list[BarrierSetter] = []
    barrier_clearers: list[BarrierClearer] = []

    # The BEE2 app verified all of this, so it should not normally be possible to get mismatches
    # here. Crash the compiler if that happens.
    conf_ents = vmf.by_class['bee2_template_conf']
    if len(conf_ents) > 1:
        raise ValueError(f'Multiple configuration entities in template <var>"{loc.id}"</var>!')
    elif not conf_ents:
        raise ValueError(f'No configration entity for template <var>"{loc.id}"</var>!')
    else:
        [conf] = conf_ents

    if conf['template_id'].upper() != loc.id:
        raise ValueError(f'Mismatch in template IDs: "{conf["template_id"]}" != "{loc.id}"!')

    def yield_world_detail() -> Iterator[tuple[list[Solid], bool, set[int]]]:
        """Yield all world/detail solids in the map.

        This also indicates if it's a func_detail, and the visgroup IDs.
        (Those are stored in the ent for detail, and the solid for world.)
        """
        for brush in vmf.brushes:
            yield [brush], False, brush.visgroup_ids
        for detail in vmf.by_class['func_detail']:
            yield detail.solids, True, detail.visgroup_ids

    force = conf['temp_type']
    force_is_detail: bool | None
    if force.casefold() == 'detail':
        force_is_detail = True
    elif force.casefold() == 'world':
        force_is_detail = False
    else:
        force_is_detail = None

    visgroup_names = {
        vis.id: vis.name.casefold()
        for vis in
        vmf.vis_tree
    }
    conf_auto_visgroup = 1 if srctools.conv_bool(conf['detail_auto_visgroup']) else 0

    if not srctools.conv_bool(conf['discard_brushes']):
        for brushes, is_detail, vis_ids in yield_world_detail():
            visgroups = list(map(visgroup_names.__getitem__, vis_ids))
            if len(visgroups) > 1:
                raise user_errors.UserError(user_errors.TOK_TEMPLATE_MULTI_VISGROUPS.format(
                    id=loc.id,
                    kind='brush',
                    groups=', '.join(visgroups),
                ))
            # No visgroup = ''
            visgroup = visgroups[0] if visgroups else ''

            # Auto-visgroup puts func_detail ents in unique visgroups.
            if is_detail and not visgroup and conf_auto_visgroup:
                visgroup = f'__auto_group_{conf_auto_visgroup}__'
                # Reuse as the unique index, >0 are True too..
                conf_auto_visgroup += 1

            # Check this after auto-visgroup, so world/detail can be used to
            # opt into the grouping, then overridden to be the same.
            if force_is_detail is not None:
                is_detail = force_is_detail

            if is_detail:
                detail_ents[visgroup].extend(brushes)
            else:
                world_ents[visgroup].extend(brushes)

    for ent in vmf.by_class['info_overlay']:
        visgroups = list(map(visgroup_names.__getitem__, ent.visgroup_ids))
        if len(visgroups) > 1:
            raise user_errors.UserError(user_errors.TOK_TEMPLATE_MULTI_VISGROUPS.format(
                id=loc.id,
                kind='overlay',
                groups=', '.join(visgroups),
            ))
        # No visgroup = ''
        overlay_ents[visgroups[0] if visgroups else ''].append(ent)

    for ent in vmf.by_class['bee2_template_colorpicker']:
        # Parse the colorpicker data.
        try:
            priority = Decimal(ent['priority'])
        except ArithmeticError:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='priority',
                value=ent['remove_brush'],
                kind='Template ColorPicker',
                id=f'{loc.id}:{ent["targetname"]}',
            )) from None

        try:
            remove_after = AfterPickMode(ent['remove_brush', '0'])
        except ValueError:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='remove_brush',
                value=ent['remove_brush'],
                kind='Template ColorPicker',
                id=f'{loc.id}:{ent["targetname"]}',
            )) from None

        color_pickers.append(ColorPicker(
            priority=priority,
            name=ent['targetname'],
            visgroups=set(map(visgroup_names.__getitem__, ent.visgroup_ids)),
            offset=Vec.from_str(ent['origin']),
            normal=Matrix.from_angstr(ent['angles']).forward(),
            sides=ent['faces'].split(' '),
            grid_snap=srctools.conv_bool(ent['grid_snap']),
            after=remove_after,
            use_pattern=srctools.conv_bool(ent['use_pattern']),
            force_tex_white=ent['tex_white'],
            force_tex_black=ent['tex_black'],
        ))

    for ent in vmf.by_class['bee2_template_voxelsetter']:
        tile_type = SKIN_TO_TILETYPE[srctools.conv_int(ent['skin'])]

        voxel_setters.append(VoxelSetter(
            offset=Vec.from_str(ent['origin']),
            normal=Matrix.from_angstr(ent['angles']).up(),
            visgroups=set(map(visgroup_names.__getitem__, ent.visgroup_ids)),
            tile_type=tile_type,
            force=srctools.conv_bool(ent['force']),
        ))

    for ent in vmf.by_class['bee2_template_tilesetter']:
        tile_type = SKIN_TO_TILETYPE[srctools.conv_int(ent['skin'])]
        color_str = ent['color']
        color: Portalable | AppliedColour
        if color_str == 'tile':
            try:
                color = tile_type.color
            except ValueError:
                # Non-tile types.
                color = AppliedColour.MATCH
        else:
            try:
                color = AppliedColour(color_str)
            except ValueError:
                raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                    option='color',
                    value=color_str,
                    kind='Template TileSetter',
                    id=loc.id,
                )) from None

        tile_setters.append(TileSetter(
            offset=Vec.from_str(ent['origin']),
            normal=Matrix.from_angstr(ent['angles']).up(),
            visgroups=set(map(visgroup_names.__getitem__, ent.visgroup_ids)),
            color=color,
            tile_type=tile_type,
            picker_name=ent['color_picker'],
            force=srctools.conv_bool(ent['force']),
        ))

    for ent in vmf.by_class['bee2_template_barriersetter']:
        barrier_setters.append(BarrierSetter(
            offset=Vec.from_str(ent['origin']),
            normal=Matrix.from_angstr(ent['angles']).up(),
            visgroups=set(map(visgroup_names.__getitem__, ent.visgroup_ids)),
            id=utils.obj_id_optional(ent['barrierid'], 'Barrier Type'),
            force=srctools.conv_bool(ent['force']),
        ))

    for ent in vmf.by_class['bee2_template_barrier_voxel_clear']:
        barrier_clearers.append(BarrierClearer(
            offset=Vec.from_str(ent['origin']),
            visgroups=set(map(visgroup_names.__getitem__, ent.visgroup_ids)),
            normal=Vec.N.thaw(),
        ))

    coll: list[CollisionDef] = []
    for ent in vmf.by_class['bee2_collision_bbox']:
        visgroup_set = set(map(visgroup_names.__getitem__, ent.visgroup_ids))
        for bbox in collisions.BBox.from_ent(ent):
            coll.append(CollisionDef(bbox, visgroup_set))

    for ent in vmf.by_class['bee2_collision_volume']:
        visgroup_set = set(map(visgroup_names.__getitem__, ent.visgroup_ids))
        for bbox in collisions.Volume.from_ent(ent):
            coll.append(CollisionDef(bbox, visgroup_set))

    return Template(
        temp_id=loc.id,
        visgroup_names=set(visgroup_names.values()),
        world=world_ents,
        detail=detail_ents,
        overlays=overlay_ents,
        skip_faces=conf['skip_faces'].split(),
        realign_faces=conf['realign_faces'].split(),
        overlay_transfer_faces=conf['overlay_faces'].split(),
        vertical_faces=conf['vertical_faces'].split(),
        color_pickers=color_pickers,
        tile_setters=tile_setters,
        voxel_setters=voxel_setters,
        barrier_setters=barrier_setters,
        barrier_clearers=barrier_clearers,
        coll=coll,
        debug=srctools.conv_bool(conf['debug']),
    )


def get_template(temp_name: str) -> Template:
    """Get the data associated with a given template."""
    try:
        temp = _TEMPLATES[temp_name.casefold()]
    except KeyError:
        raise InvalidTemplateName(temp_name) from None

    if isinstance(temp, UnparsedTemplate):
        LOGGER.debug('Parsing template {}', temp_name.upper())
        temp = _TEMPLATES[temp_name.casefold()] = _parse_template(temp)
        if temp.debug:
            LOGGER.info('Template {} in debug mode.', temp_name.upper())

    return temp


def import_template(
    vmf: VMF,
    temp_name: str | Template,
    origin: Vec,
    angles: AnyAngle | AnyMatrix | None = None,
    targetname: str = '',
    force_type: TEMP_TYPES = TEMP_TYPES.default,
    add_to_map: bool = True,
    additional_visgroups: Iterable[str] = (),
    bind_tile_pos: Collection[Vec] = (),
    align_bind: bool = False,
    coll: collisions.Collisions | None = None,
    coll_add: collisions.CollideType = collisions.CollideType.NOTHING,
    coll_mask: collisions.CollideType = collisions.CollideType.EVERYTHING,
) -> ExportedTemplate:
    """Import the given template at a location.

    * `temp_name` can be a string, or a template instance.
    * `visgroups` is a list of additional visgroups to use after the ones in the name string (if given).
    * If `force_type` is set to 'detail' or 'world', all brushes will be converted
      to the specified type instead. A list of world brushes and the func_detail
      entity will be returned. If there are no detail brushes, None will be
      returned instead of an invalid entity.
    * If `targetname` is set, it will be used to localise overlay names.
      add_to_map sets whether to add the brushes and func_detail to the map.
    * IF `coll` is provided, the template may have bee2_collision volumes. The targetname must be
      provided in this case.
    * If any `bound_tile_pos` are provided, these are offsets to tiledefs which
      should have all the overlays in this template bound to them, and vice versa.
    * If `align_bind` is set, these will be first aligned to grid.
    * `coll_mask` and `coll_force` allow modifying the collision types added. `coll_mask` is AND-ed
      with the bbox type, then `coll_add` is OR-ed in. If the collide type ends up being NOTHING, it
      is skipped.
    """
    import vbsp
    if isinstance(temp_name, Template):
        template, temp_name = temp_name, temp_name.id
        chosen_groups: set[str] = set()
    else:
        temp_name, chosen_groups = parse_temp_name(temp_name)
        template = get_template(temp_name)

    chosen_groups.update(additional_visgroups)
    chosen_groups.add('')

    orig_world, orig_detail, orig_over = template.visgrouped(chosen_groups)

    new_world: list[Solid] = []
    new_detail: list[Solid] = []
    new_over: list[Entity] = []

    # A map of the original -> new face IDs.
    id_mapping: dict[int, int] = {}
    orient = to_matrix(angles)

    dbg_visgroup: VisGroup | None = None
    dbg_group: EntityGroup | None = None
    dbg_add: Callable[..., None] | None = None
    if template.debug:
        # Find the visgroup for template debug data, and create an entity group.
        for dbg_visgroup in vmf.vis_tree:
            if dbg_visgroup.name == 'Templates':
                break
        else:
            dbg_visgroup = vmf.create_visgroup('Templates', (113, 113, 0))
        dbg_group = EntityGroup(vmf, color=Vec(113, 113, 0))

        def dbg_add(classname: str, **kwargs: ValidKVs) -> None:
            """Add a marker to the map."""
            ent = vmf.create_ent(classname, **kwargs)
            ent.visgroup_ids.add(dbg_visgroup.id)
            ent.groups.add(dbg_group.id)
            ent.vis_shown = False
            ent.hidden = True

        dbg_add(
            'bee2_template_conf',
            template_id=template.id,
            origin=origin,
            angles=orient.to_angle(),
            visgroups=' '.join(chosen_groups - {''})
        )

    for orig_list, new_list in [
        (orig_world, new_world),
        (orig_detail, new_detail)
    ]:
        for old_brush in orig_list:
            brush = old_brush.copy(
                vmf_file=vmf,
                side_mapping=id_mapping,
                keep_vis=False,
            )
            brush.localise(origin, orient)
            new_list.append(brush)

    for overlay in orig_over:
        new_overlay = overlay.copy(
            vmf_file=vmf,
            keep_vis=False,
        )
        del new_overlay['template_id']  # Remove this, it's not part of overlays
        new_overlay['classname'] = 'info_overlay'

        sides = overlay['sides'].split()
        new_overlay['sides'] = ' '.join(
            str(id_mapping[int(side)])
            for side in sides
            if int(side) in id_mapping
        )

        srctools.vmf.localise_overlay(new_overlay, origin, orient)
        orig_target = new_overlay['targetname']

        # Only change the targetname if the overlay is not global, and we have
        # a passed name.
        if targetname and orig_target and orig_target[0] != '@':
            new_overlay['targetname'] = targetname + '-' + orig_target

        vmf.add_ent(new_overlay)
        new_over.append(new_overlay)

        # Don't let the overlays get retextured too!
        vbsp.IGNORED_OVERLAYS.add(new_overlay)
        if dbg_visgroup is not None and dbg_group is not None:
            overlay.groups.add(dbg_group.id)

    if force_type is TEMP_TYPES.detail:
        new_detail.extend(new_world)
        new_world.clear()
    elif force_type is TEMP_TYPES.world:
        new_world.extend(new_detail)
        new_detail.clear()

    if add_to_map:
        vmf.add_brushes(new_world)

    detail_ent: Entity | None = None

    if new_detail:
        detail_ent = vmf.create_ent(classname='func_detail')
        detail_ent.solids = new_detail
        if not add_to_map:
            detail_ent.remove()
        if dbg_visgroup is not None and dbg_group is not None:
            detail_ent.groups.add(dbg_group.id)

    # Only world brushes.
    if dbg_visgroup is not None and dbg_group is not None:
        for brush in new_world:
            brush.group_id = dbg_group.id

    if bind_tile_pos:
        # Bind all our overlays without IDs to a set of tiles,
        # and add any marked faces to those tiles to be given overlays.
        new_overlay_faces = {
            id_mapping[old_id]
            for str_id in template.overlay_faces
            if (old_id := int(str_id)) in id_mapping
        }
        bound_overlay_faces = [
            face
            for brush in (new_world + new_detail)
            for face in brush.sides
            if face.id in new_overlay_faces
        ]

        tile_norm = orient.up()
        for tile_off in bind_tile_pos:
            tile_off = tile_off.copy()
            tile_off.localise(origin, orient)
            for axis in ('xyz' if align_bind else ''):
                # Don't realign things in the normal's axis -
                # those are already fine.
                if abs(tile_norm[axis]) < 1e-6:
                    tile_off[axis] = tile_off[axis] // 128 * 128 + 64
            try:
                tile = tiling.TILES[tile_off.as_tuple(), tile_norm.as_tuple()]
            except KeyError:
                LOGGER.warning(
                    'No tile to bind at {} for "{}"!',
                    tile_off, template.id,
                )
                continue
            for over in new_over:
                if over['sides'] == '':
                    tile.bind_overlay(over)
            tile.brush_faces.extend(bound_overlay_faces)

            if dbg_add is not None:
                dbg_add(
                    'info_target',
                    targetname='bound_tiles',
                    origin=tile_off,
                    faces=' '.join(map(str, new_overlay_faces)),
                )

    if template.collisions:
        if coll is None:
            LOGGER.warning('Template "{}" has collisions, but unable to apply these!', template.id)
        elif targetname:
            for coll_def in template.collisions:
                if not coll_def.visgroups.issubset(chosen_groups):
                    continue
                contents = (coll_def.bbox.contents & coll_mask) | coll_add
                if contents is not collisions.CollideType.NOTHING:
                    bbox = coll_def.bbox @ orient + origin
                    coll.add(bbox.with_attrs(name=targetname, contents=contents))
        else:
            LOGGER.warning('With collisions provided, the instance name must not be blank!')

    return ExportedTemplate(
        world=new_world,
        detail=detail_ent,
        overlay=new_over,
        orig_ids=id_mapping,
        template=template,
        origin=origin,
        orient=Matrix(orient),
        visgroups=chosen_groups,
        picker_results={},  # Filled by retexture_template.
        picker_type_results={},
        debug_marker=dbg_add,
    )


def get_scaling_template(temp_id: str) -> ScalingTemplate:
    """Get the scaling data from a template.

    This is a dictionary mapping normals to the U,V and rotation data.
    """
    temp_name, over_names = parse_temp_name(temp_id)
    key = temp_name, frozenset(over_names)

    try:
        return _SCALE_TEMP[key]
    except KeyError:
        pass
    temp = get_template(temp_name)
    uvs: dict[FrozenVec, tuple[str, UVAxis, UVAxis, float]] = {}

    for brush in temp.visgrouped_solids(over_names):
        for side in brush.sides:
            uvs[side.normal().freeze()] = (
                side.mat,
                side.uaxis.copy(),
                side.vaxis.copy(),
                side.ham_rot
            )

    _SCALE_TEMP[key] = res = ScalingTemplate(temp.id, uvs)
    return res


def retexture_template(
    template_data: ExportedTemplate,
    origin: Vec,
    instance: Entity | None = None,
    replace_tex: Mapping[str, list[str] | str] = srctools.EmptyMapping,
    force_colour: ForceColour = AppliedColour.MATCH,
    force_grid: TileSize | None = None,
    generator: GenCat = GenCat.NORMAL,
    sense_offset: Vec | None = None,
) -> None:
    """Retexture a template at the given location.

    - Only textures in the TEMPLATE_RETEXTURE dict will be replaced.
    - Others will be ignored (nodraw, plasticwall, etc)
    - Wall textures pointing up and down will switch to floor/ceiling textures.
    - Textures of the same type, normal and inst origin will randomise to the
      same type.
    - replace_tex is a replacement table. This overrides everything else.
      The values should either be a list (random), or a single value.
    - force_colour controls how textures are overridden.
    - If force_grid is set, all tile textures will be that size.
    - generator defines the generator category to use for surfaces.
    - An instance must be passed to allow $replace in replace_tex, and also to create new barriers.
    - If sense_offset is set, color pickers and tilesetters will be treated
      as if they were locally offset this far in the template.
    """

    template = template_data.template

    rev_id_mapping = {
        new_id: str(old_id)
        for old_id, new_id in
        template_data.orig_ids.items()
    }

    all_brushes = list(template_data.world)
    if template_data.detail is not None:
        all_brushes.extend(template_data.detail.solids)

    # Template faces are randomised per block and side. This means
    # multiple templates in the same block get the same texture, so they
    # can clip into each other without looking bad.
    rand_prefix = f'TEMPLATE_{(origin // 128).x}_{(origin // 128).y}_{(origin // 128).z}:'

    # Reprocess the replace_tex passed in, converting values.
    evalled_replace_tex: dict[str, list[str]] = {}
    for key, value in replace_tex.items():
        if isinstance(value, str):
            value = [value]
        if instance is not None:
            # Convert the material and key for fixup names.
            key = instance.fixup.substitute(key)
            value = [instance.fixup.substitute(mat) for mat in value]
        # If starting with '#', it's a face id, or a list of those.
        if key.startswith('#'):
            for k in key[1:].split():
                try:
                    old_id = int(k)
                except (ValueError, TypeError):
                    pass
                else:
                    evalled_replace_tex.setdefault('#' + str(old_id), []).extend(value)
        else:
            evalled_replace_tex.setdefault(key.casefold(), []).extend(value)

    if sense_offset is None:
        sense_offset = Vec()
    else:
        sense_offset = sense_offset @ template_data.orient

    # For each face, if it needs to be forced to a colour, or None if not.
    # If a string it's forced to that string specifically.
    force_colour_faces: dict[str, Portalable | str | None] = defaultdict(lambda: None)
    # Picker names to their results.
    picker_results = template_data.picker_results
    picker_type_results: dict[str, TileType | None] = {}

    # If the "use patterns" option is enabled, face ID -> temp face to copy from.
    picker_patterned: dict[str, Side | None] = defaultdict(lambda: None)
    # Then also a cache of the tiledef -> dict of template faces.
    pattern_cache: dict[tiling.TileDef, dict[tuple[int, int], Side]] = {}

    # Already sorted by priority.
    for color_picker in template.color_pickers:
        if not color_picker.is_applicable(template_data.visgroups):
            continue

        picker_pos: Vec = round(
            color_picker.offset @ template_data.orient
            + template_data.origin + sense_offset, 6)
        picker_norm: Vec = round(color_picker.normal @ template_data.orient, 6)

        if color_picker.grid_snap:
            for axis in 'xyz':
                # Don't realign things in the normal's axis -
                # those are already fine.
                if abs(picker_norm[axis]) < 0.01:
                    picker_pos[axis] = picker_pos[axis] // 128 * 128 + 64

        if template_data.debug_marker is not None:
            template_data.debug_marker(
                'bee2_template_colorpicker',
                targetname=color_picker.name,
                origin=picker_pos,
                angles=picker_norm.to_angle(),
                faces=' '.join([
                    str(side.id)
                    for old_id in color_picker.sides
                    if (side := picker_patterned[old_id]) is not None
                ]),
            )

        try:
            tiledef, u, v = tiling.find_tile(picker_pos, picker_norm)
        except KeyError:
            # Doesn't exist. But only set if not already present.
            if color_picker.name:
                picker_results.setdefault(color_picker.name, None)
                picker_type_results.setdefault(color_picker.name, None)
            continue

        tile_type = tiledef[u, v]

        picker_type_results[color_picker.name] = tile_type

        try:
            tile_color = tile_type.color
        except ValueError:
            # Not a tile with color (void, etc). Treat as missing a color.
            picker_results.setdefault(color_picker.name, None)
            continue

        if color_picker.name and picker_results.get(color_picker.name, None) is None:
            picker_results[color_picker.name] = tile_color

        if color_picker.use_pattern:
            # Generate the brushwork for the tile to determine the top faces
            # required. We can then throw away the brushes themselves.
            try:
                pattern = pattern_cache[tiledef]
            except KeyError:
                pattern = pattern_cache[tiledef] = {}
                tiledef.gen_multitile_pattern(
                    VMF(), {
                        (u, v): tiledef[u, v]
                        for u in (0, 1, 2, 3)
                        for v in (0, 1, 2, 3)
                    },
                    is_wall=abs(tiledef.normal.z) > 0.01,
                    bevels=set(),
                    normal=tiledef.normal,
                    face_output=pattern,
                )

            for side_id in color_picker.sides:
                if picker_patterned[side_id] is None and (u, v) in pattern:
                    picker_patterned[side_id] = pattern[u, v]
        else:
            # Only do the highest priority successful one.
            for side_id in color_picker.sides:
                if force_colour_faces[side_id] is None:
                    if tile_color is Portalable.WHITE:
                        force_colour_faces[side_id] = color_picker.force_tex_white or tile_color
                    else:
                        force_colour_faces[side_id] = color_picker.force_tex_black or tile_color

        if color_picker.after is AfterPickMode.VOID:
            tiledef[u, v] = TileType.VOID
        elif color_picker.after is AfterPickMode.NODRAW:
            tiledef[u, v] = TileType.NODRAW

    for voxel_setter in template.voxel_setters:
        if not voxel_setter.is_applicable(template_data.visgroups):
            continue

        setter_pos = round(
            voxel_setter.offset @ template_data.orient
            + template_data.origin + sense_offset, 6)
        setter_norm = round(voxel_setter.normal @ template_data.orient, 6)

        if template_data.debug_marker is not None:
            template_data.debug_marker(
                'bee2_template_voxelsetter',
                origin=setter_pos,
                angles=Angle.from_basis(z=voxel_setter.normal),
                skin=TILETYPE_TO_SKIN[voxel_setter.tile_type],
                force=voxel_setter.force,
            )

        norm_axis = setter_norm.axis()
        u_axis, v_axis = Vec.INV_AXIS[norm_axis]
        offsets = (-48, -16, 16, 48)
        for uoff in offsets:
            for voff in offsets:
                tiling.edit_quarter_tile(
                    setter_pos + Vec.with_axes(u_axis, uoff, v_axis, voff),
                    setter_norm,
                    voxel_setter.tile_type,
                    silent=True,  # Don't log missing positions.
                    force=voxel_setter.force,
                )

    for tile_setter in template.tile_setters:
        if not tile_setter.is_applicable(template_data.visgroups):
            continue

        setter_pos = round(
            tile_setter.offset @ template_data.orient
            + template_data.origin + sense_offset, 6)
        setter_norm = round(tile_setter.normal @ template_data.orient, 6)

        setter_type: TileType = tile_setter.tile_type

        if template_data.debug_marker is not None:
            template_data.debug_marker(
                'bee2_template_tilesetter',
                origin=setter_pos,
                angles=Angle.from_basis(z=setter_norm),
                skin=TILETYPE_TO_SKIN[setter_type],
                force=tile_setter.force,
                picker_name=tile_setter.picker_name,
                color=repr(tile_setter.color),
            )

        if tile_setter.color is AppliedColour.COPY:
            if not tile_setter.picker_name:
                raise ValueError(
                    f'"{template.id}": Tile Setter set to copy mode '
                    f'must have a color picker!'
                )
            # If a color picker is set, it overrides everything else.
            try:
                picker_res = picker_type_results[tile_setter.picker_name]
            except KeyError:
                raise ValueError(
                    f'"{template.id}": Tile Setter specified color picker '
                    f'"{tile_setter.picker_name}" which does not exist!'
                ) from None
            if picker_res is None:
                raise ValueError(
                    f'"{template.id}": Color picker '
                    f'"{tile_setter.picker_name}" has no tile to pick!'
                )
            setter_type = picker_res
        elif setter_type.is_tile:
            if tile_setter.picker_name:
                # If a color picker is set, it overrides everything else.
                try:
                    setter_color = picker_results[tile_setter.picker_name]
                except KeyError:
                    raise ValueError(
                        f'"{template.id}": Tile Setter specified color picker '
                        f'"{tile_setter.picker_name}" which does not exist!'
                    ) from None
                if setter_color is None:
                    raise ValueError(
                        f'"{template.id}": Color picker "{tile_setter.picker_name}" '
                        f'has no tile to pick!'
                    )
            elif isinstance(tile_setter.color, Portalable):
                # The color was specifically set.
                setter_color = tile_setter.color
            elif isinstance(force_colour, Portalable):
                # Otherwise it copies the forced colour -
                # it needs to be white or black.
                setter_color = force_colour
            else:
                # We need a forced color, but none was provided.
                raise ValueError(
                    f'"{template.id}": Tile Setter set to use colour value from '
                    "the template's overall color, but not given one!"
                )

            # Inverting applies to all of these.
            if force_colour is AppliedColour.INVERT:
                setter_color = ~setter_color

            setter_type = TileType.with_color_and_size(
                setter_type.tile_size,
                setter_color,
            )

        tiling.edit_quarter_tile(
            setter_pos,
            setter_norm,
            setter_type,
            silent=True,  # Don't log missing positions.
            force=tile_setter.force,
        )

    for barrier_clearer in template.barrier_clearers:
        if not barrier_clearer.is_applicable(template_data.visgroups):
            continue
        setter_pos = round(barrier_clearer.offset @ template_data.orient + template_data.origin + sense_offset, 6)

        if template_data.debug_marker is not None:
            template_data.debug_marker(
                'bee2_template_barrier_voxel_clear',
                origin=setter_pos,
            )

        for normal in NORMALS:
            # Don't bother rotating, it doesn't make any difference unless the template
            # is not axis aligned.
            setter_plane = PlaneKey(normal, setter_pos - 16 * normal)
            local = setter_plane.world_to_plane(setter_pos)
            del barriers.BARRIERS[setter_plane][local.x // 32, local.y // 32]

    # We want multiple barrier-setters to merge their instances.
    type_to_barrier: dict[barriers.BarrierType, barriers.Barrier] = {}
    # If our instance name is in the barriers dict, reuse it across multiple templates.
    targetname = instance['targetname'] if instance is not None else ''
    if targetname:
        try:
            existing = barriers.BARRIERS_BY_NAME[targetname]
        except KeyError:
            pass
        else:
            type_to_barrier[existing.type] = existing

    for barrier_setter in template.barrier_setters:
        if not barrier_setter.is_applicable(template_data.visgroups):
            continue

        setter_pos = round(barrier_setter.offset @ template_data.orient + template_data.origin + sense_offset, 6)
        setter_plane = PlaneKey(barrier_setter.normal @ template_data.orient, setter_pos)
        local = setter_plane.world_to_plane(setter_pos)
        uv = (local.x // 32, local.y // 32)
        barrier_grid = barriers.BARRIERS[setter_plane]

        if template_data.debug_marker is not None:
            template_data.debug_marker(
                'bee2_template_barrier_voxel_clear',
                origin=setter_pos,
            )

        if barrier_setter.id == "":
            # Always replace if we're removing it
            del barrier_grid[uv]
            continue
        # Otherwise, we want to check.
        existing = barrier_grid[uv]

        # We need an instance and valid barrier type.
        if instance is None or not targetname:
            raise ValueError(
                f'"{template.id}": Barrier setters can only create barriers if '
                f'a named instance is associated with this template import!'
            )

        try:
            new_barrier_type = barriers.BARRIER_TYPES[barrier_setter.id]
        except KeyError:
            raise ValueError(
                f'"{template.id}": Barrier setter is set to invalid ID "{barrier_setter.id}"!\n'
                f'Known IDs: "", ' + ', '.join(sorted([f'"{barr}"' for barr in barriers.BARRIER_TYPES]))
            ) from None

        # We replace if "force" is on or the existing barrier is not present.
        if barrier_setter.force or existing is barriers.BARRIER_EMPTY:
            try:
                # Did we already place this barrier?
                new_barrier = type_to_barrier[new_barrier_type]
            except KeyError:
                new_barrier = type_to_barrier[new_barrier_type] = barriers.Barrier(
                    name=targetname,
                    type=new_barrier_type,
                    item=connections.ITEMS.get(targetname, None),
                    instances=[instance],
                )

                # This won't preserve identity if multiple types are created for one item.
                if targetname:
                    barriers.BARRIERS_BY_NAME.setdefault(targetname, new_barrier)
            barrier_grid[uv] = new_barrier

    for brush in all_brushes:
        for face in brush:
            orig_id = rev_id_mapping.get(face.id) or ''

            if orig_id in template.skip_faces:
                continue

            template_face = picker_patterned[orig_id]
            if template_face is not None:
                face.mat = template_face.mat
                face.uaxis = template_face.uaxis.copy()
                face.vaxis = template_face.vaxis.copy()
                continue

            folded_mat = face.mat.casefold()

            norm = face.normal().freeze()

            if orig_id in template.realign_faces:
                try:
                    uaxis, vaxis = REALIGN_UVS[norm]
                except KeyError:
                    LOGGER.warning(
                        'Realign face in template "{}" ({} in final) is '
                        'not on grid!',
                        template.id,
                        face.id,
                    )
                else:
                    face.uaxis = uaxis.copy()
                    face.vaxis = vaxis.copy()
            elif orig_id in template.vertical_faces:
                # Rotate the face in increments of 90 degrees, so it is as
                # upright as possible.
                pos_u = face.uaxis
                pos_v = face.vaxis
                # If both are zero, we're on the floor/ceiling and this is
                # pointless.
                if pos_u.z != 0 or pos_v.z != 0:
                    neg_u = UVAxis(-pos_u.x, -pos_u.y, -pos_u.z, pos_u.offset,
                                   pos_u.scale)
                    neg_v = UVAxis(-pos_v.x, -pos_v.y, -pos_v.z, pos_v.offset,
                                   pos_v.scale)
                    # Each row does u, v = v, -u to rotate 90 degrees.
                    # We want whichever makes V point vertically.
                    face.uaxis, face.vaxis = max([
                        (pos_u, pos_v),
                        (pos_v, neg_u),
                        (neg_u, neg_v),
                        (neg_v, pos_u),
                    ], key=lambda uv: -uv[1].z)

            override_mat: list[str] | None
            try:
                override_mat = evalled_replace_tex['#' + orig_id]
            except KeyError:
                try:
                    override_mat = evalled_replace_tex[folded_mat]
                except KeyError:
                    override_mat = None

            if override_mat is not None:
                # Replace_tex overrides everything.
                mat =  rand.seed(b'template', norm, face.get_origin()).choice(override_mat)
                if instance is not None:
                    mat = instance.fixup.substitute(mat)
                if mat.startswith('<') and mat.endswith('>'):
                    # Lookup in the style data.
                    gen, mat = texturing.parse_name(mat[1:-1])
                    mat = gen.get(face.get_origin() + face.normal(), mat)
                # If blank, don't set.
                if mat:
                    face.mat = mat
                    continue

            if folded_mat == 'tile/white_wall_tile003b':
                LOGGER.warning('"{}": white_wall_tile003b has changed definitions.', template.id)

            try:
                tex_type = TEMPLATE_RETEXTURE[folded_mat]
            except KeyError:
                continue  # It's nodraw, or something we shouldn't change

            tex_colour: Portalable | None
            gen_type, tex_name, tex_colour = tex_type

            if not gen_type.is_tile:
                # It's something like squarebeams or backpanels, so
                # we don't need much special handling.
                texturing.apply(gen_type, face, tex_name)

                if tex_name in ('goo', 'goo_cheap'):
                    if norm.z > -0.9:
                        # Goo must be facing upright!
                        # Retexture to nodraw, so a template can be made with
                        # all faces goo to work in multiple orientations.
                        face.mat = 'tools/toolsnodraw'
                    else:
                        # Goo always has the same orientation!
                        face.uaxis = UVAxis(
                            1, 0, 0,
                            offset=0,
                            scale=options.GOO_SCALE(),
                        )
                        face.vaxis = UVAxis(
                            0, -1, 0,
                            offset=0,
                            scale=options.GOO_SCALE(),
                        )
                continue
            else:
                assert isinstance(tex_colour, Portalable)
                # Allow overriding to panel or bullseye types.
                if gen_type is GenCat.NORMAL:
                    gen_type = generator
            # Otherwise, it's a panel wall or the like

            force_colour_face = force_colour_faces[orig_id]
            if force_colour_face is not None:
                if isinstance(force_colour_face, str):
                    face.mat = force_colour_face
                    continue
                tex_colour = force_colour_face
            elif force_colour is AppliedColour.INVERT:
                # Invert the texture
                tex_colour = ~tex_colour
            elif force_colour is not AppliedColour.MATCH:
                tex_colour = force_colour

            if force_grid is not None:
                tex_name = force_grid

            texturing.apply(gen_type, face, tex_name, tex_colour)

    for over in template_data.overlay[:]:
        over_pos = Vec.from_str(over['basisorigin'])
        mat = over['material'].casefold()

        if mat in replace_tex:
            rng = rand.seed(b'temp', template_data.template.id, over_pos, mat)
            mat = rng.choice(replace_tex[mat])
            if instance is not None:
                mat = instance.fixup.substitute(mat)
            if mat.startswith('<') or mat.endswith('>'):
                mat = mat[1:-1]
                gen, tex_name = texturing.parse_name(mat[1:-1])
                mat = gen.get(over_pos, tex_name)
        else:
            try:
                sign_type = consts.Signage(mat)
            except ValueError:
                pass
            else:
                mat = texturing.OVERLAYS.get(over_pos, sign_type)

        if mat == '':
            # If blank, remove the overlay from the map and the list.
            # (Since it's inplace, this can affect the tuple.)
            template_data.overlay.remove(over)
            over.remove()
        else:
            over['material'] = mat
