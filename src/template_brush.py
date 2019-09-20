"""Templates are sets of brushes which can be copied into the map."""
import random
from collections import defaultdict

from decimal import Decimal
from enum import Enum
from operator import attrgetter

import srctools
import vbsp_options

from srctools import Entity, Solid, Side, Property, UVAxis, Vec, VMF
from srctools.vmf import EntityFixup
from texturing import Portalable, GenCat, TileSize
from tiling import TileType
import comp_consts as consts
import srctools.logger
import tiling
import texturing

from typing import (
    Iterable, Union, Callable,
    NamedTuple, Tuple,
    Dict, List, Set,
    Iterator, Mapping,
    Optional,
)

LOGGER = srctools.logger.get_logger(__name__, alias='template')

# A lookup for templates.
TEMPLATES = {}  # type: Dict[str, Union[Template, ScalingTemplate]]

# The location of the template data.
TEMPLATE_LOCATION = 'bee2/templates.vmf'


class InvalidTemplateName(LookupError):
    """Raised if a template ID is invalid."""
    def __init__(self, temp_name):
        self.temp_name = temp_name

    def __str__(self):
        # List all the templates that are available.
        return 'Template not found: "{}"\nValid templates:\n{}'.format(
            self.temp_name,
            '\n'.join(
                (' * "' + temp.upper() + '"')
                for temp in
                sorted(TEMPLATES.keys())
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


class ColorPicker(NamedTuple):
    """Color pickers allow applying the existing colors onto faces."""
    priority: Decimal  # Decimal order to do them in.
    name: str  # Name to reference from other ents.
    offset: Vec
    normal: Vec  # Normal of the surface.
    sides: List[str]
    grid_snap: bool  # Snap to grid on non-normal axes
    after: AfterPickMode  # What to do after the color is picked.
    # Instead of just changing the colour, copy the entire face from the
    # tiledef.
    use_pattern: bool

    # Or, use a pair of preset white/black textures.
    force_tex_white: str
    force_tex_black: str



class TileSetter(NamedTuple):
    """Set tiles in a particular position."""
    offset: Vec
    normal: Vec
    color: Union[Portalable, str, None]  # Portalable value, 'INVERT' or None
    tile_type: TileType  # Type to produce.
    picker_name: str  # Name of colorpicker to use for the color.

# We use the skins value on the tilesetter to specify type, allowing visualising it.
# So this is the type for each index.
TILE_SETTER_SKINS = [
    TileType.BLACK,
    TileType.BLACK_4x4,
    TileType.WHITE,
    TileType.WHITE_4x4,
    TileType.NODRAW,
    TileType.VOID,
    TileType.CUTOUT_TILE_BROKEN,
    TileType.CUTOUT_TILE_PARTIAL,
]


B = Portalable.BLACK
W = Portalable.WHITE
TEMPLATE_RETEXTURE: Dict[str, Union[
    Tuple[GenCat, str, None],
    Tuple[GenCat, TileSize, Portalable],
]] = {
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
    consts.Special.PED_SIDE: (GenCat.SPECIAL, 'pedestalside', None),
    consts.Special.SQUAREBEAMS: (GenCat.SPECIAL, 'edge', None),
    consts.Special.GLASS: (GenCat.SPECIAL, 'glass', None),
    consts.Special.GRATING: (GenCat.SPECIAL, 'grating', None),

    consts.Goo.CHEAP: (GenCat.SPECIAL, 'goo_cheap', None),
}
del B, W

TEMP_TILE_PIX_SIZE = {
    # The width in texture pixels of each tile size.
    # We decrease offset to this much +- at maximum (so adjacient template
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
TEMP_COLOUR_INVERT = {
    Portalable.white: Portalable.black,
    Portalable.black: Portalable.white,
    None: 'INVERT',
    'INVERT': None,
}


class ExportedTemplate(NamedTuple):
    """The result of importing a template.

    THis contains all the changes made. orig_ids is a dict mapping the original
    IDs in the template file to the new ones produced.
    Once retexture_template() is caled, picker_results contains the detected
    surface types for colorpickers.

    """
    world: List[Solid]
    detail: Optional[Entity]
    overlay: List[Entity]
    orig_ids: Dict[int, int]
    template: 'Template'
    origin: Vec
    angles: Vec
    picker_results: Dict[str, Optional[Portalable]]


# Make_prism() generates faces aligned to world, copy the required UVs.
realign_solid = VMF().make_prism(Vec(-16,-16,-16), Vec(16,16,16)).solid  # type: Solid
REALIGN_UVS = {
    face.normal().as_tuple(): (face.uaxis, face.vaxis)
    for face in realign_solid
}
del realign_solid


class Template:
    """Represents a template before it's imported into a map."""
    def __init__(
        self,
        temp_id: str,
        world: Dict[str, List[Solid]],
        detail: Dict[str, List[Solid]],
        overlays: Dict[str, List[Entity]],
        skip_faces: Iterable[str]=(),
        realign_faces: Iterable[str]=(),
        overlay_transfer_faces: Iterable[str]=(),
        vertical_faces: Iterable[str]=(),
        color_pickers: Iterable[ColorPicker]=(),
        tile_setters: Iterable[TileSetter]=(),
    ) -> None:
        """Make an overlay.

        """
        self.id = temp_id
        self._data = data = {}  # type: Dict[str, Tuple[List[Solid], List[Solid], List[Entity]]]

        # We ensure the '' group is always present.
        all_groups = {''}
        all_groups.update(world)
        all_groups.update(detail)
        all_groups.update(overlays)
        for group in all_groups:
            data[group] = (
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

    @property
    def visgroups(self) -> Iterator[str]:
        """Iterate over the template visgroups"""
        return iter(self._data)

    def visgrouped(
        self,
        visgroups: Union[str, Iterable[str]]=(),
    ) -> Tuple[List[Solid], List[Solid], List[Entity]]:
        """Given some visgroups, return the matching data.

        This returns lists of the world brushes, detail brushes, and overlays.
        visgroups can also be a single string, to select that.
        """
        if isinstance(visgroups, str):
            visgroups = {'', visgroups}
        else:
            visgroups = set(visgroups)
            visgroups.add('')

        world_brushes = []  # type: List[Solid]
        detail_brushes = []  # type: List[Solid]
        overlays = []  # type: List[Entity]

        for group in visgroups:
            try:
                world, detail, over = self._data[group]
            except KeyError:
                raise ValueError('Unknown visgroup "{}" for "{}"! (valid: {})'.format(
                    group, self.id,
                    ', '.join(map(repr, self._data)),
                ))
            world_brushes.extend(world)
            detail_brushes.extend(detail)
            overlays.extend(over)

        return world_brushes, detail_brushes, overlays


class ScalingTemplate(Mapping[
    Union[Vec, Tuple[float, float, float]],
    Tuple[str, UVAxis, UVAxis, float]
]):
    """Represents a special version of templates, used for texturing brushes.

    The template is a single world-aligned cube brush, with the 6 sides used
    to determine orientation and materials for some texture set.
    It's stored in an ent so we don't need all the data. Values are returned
    as (material, U, V, rotation) tuples.
    """

    def __init__(
        self,
        temp_id: str,
        axes: Dict[Tuple[float, float, float], Tuple[str, UVAxis, UVAxis, float]],
    ):
        self.id = temp_id
        self._axes = axes
        # Only keys used....
        assert set(axes.keys()) == {
            (0, 0, 1), (0, 0, -1),
            (1, 0, 0), (-1, 0, 0),
            (0, -1, 0), (0, 1, 0),
        }, axes.keys()

    @classmethod
    def parse(cls, ent: Entity):
        """Parse a template from a config entity.

        This should be a 'bee2_template_scaling' entity.
        """
        axes = {}

        for norm, name in [
            ((0.0, 0.0, +1.0), 'up'),
            ((0.0, 0.0, -1.0), 'dn'),
            ((0.0, +1.0, 0.0), 'n'),
            ((0.0, -1.0, 0.0), 's'),
            ((+1.0, 0.0, 0.0), 'e'),
            ((-1.0, 0.0, 0.0), 'w'),
        ]:
            axes[norm] = (
                ent[name + '_tex'],
                UVAxis.parse(ent[name + '_uaxis']),
                UVAxis.parse(ent[name + '_vaxis']),
                srctools.conv_float(ent[name + '_rotation']),
            )
        return cls(ent['template_id'], axes)

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
        normal: Union[Vec, Tuple[float, float, float]],
    ) -> Tuple[str, UVAxis, UVAxis, float]:
        if isinstance(normal, Vec):
            normal = normal.as_tuple()
        mat, axis_u, axis_v, rotation = self._axes[normal]
        return mat, axis_u.copy(), axis_v.copy(), rotation

    def rotate(self, angles: Vec, origin: Optional[Vec]=None) -> 'ScalingTemplate':
        """Rotate this template, and return a new template with those angles."""
        new_axis = {}
        if origin is None:
            origin = Vec()

        for norm, (mat, axis_u, axis_v, rot) in self._axes.items():
            axis_u = axis_u.localise(origin, angles)
            axis_v = axis_v.localise(origin, angles)
            v_norm = Vec(norm).rotate(*angles)
            new_axis[v_norm.as_tuple()] = mat, axis_u, axis_v, rot

        return ScalingTemplate(self.id, new_axis)

    def apply(self, face: Side, *, change_mat: bool=True) -> None:
        """Apply the template to a face."""
        mat, face.uaxis, face.vaxis, face.ham_rot = self[face.normal().as_tuple()]
        if change_mat:
            face.mat = mat


def parse_temp_name(name) -> Tuple[str, Set[str]]:
    """Parse the visgroups off the end of an ID."""
    if ':' in name:
        temp_name, visgroups = name.rsplit(':', 1)
        return temp_name.casefold(), {
            vis.strip().casefold()
            for vis in
            visgroups.split(',')
            if not vis.isspace()
        }
    else:
        return name.casefold(), set()


def load_templates() -> None:
    """Load in the template file, used for import_template()."""
    with open(TEMPLATE_LOCATION) as file:
        props = Property.parse(file, TEMPLATE_LOCATION)
    vmf = srctools.VMF.parse(props, preserve_ids=True)

    def make_subdict() -> Dict[str, list]:
        return defaultdict(list)

    # detail_ents[temp_id][visgroup]
    detail_ents = defaultdict(make_subdict)  # type: Dict[str, Dict[str, List[Solid]]]
    world_ents = defaultdict(make_subdict)  # type: Dict[str, Dict[str, List[Solid]]]
    overlay_ents = defaultdict(make_subdict)  # type: Dict[str, Dict[str, List[Entity]]]
    conf_ents = {}

    color_pickers = defaultdict(list)  # type: Dict[str, List[ColorPicker]]
    tile_setters = defaultdict(list)  # type: Dict[str, List[TileSetter]]

    for ent in vmf.by_class['bee2_template_world']:
        world_ents[
            ent['template_id'].casefold()
        ][
            ent['visgroup'].casefold()
        ].extend(ent.solids)

    for ent in vmf.by_class['bee2_template_detail']:
        detail_ents[
            ent['template_id'].casefold()
        ][
            ent['visgroup'].casefold()
        ].extend(ent.solids)

    for ent in vmf.by_class['bee2_template_overlay']:
        overlay_ents[
            ent['template_id'].casefold()
        ][
            ent['visgroup'].casefold()
        ].append(ent)

    for ent in vmf.by_class['bee2_template_conf']:
        conf_ents[ent['template_id'].casefold()] = ent

    for ent in vmf.by_class['bee2_template_scaling']:
        temp = ScalingTemplate.parse(ent)
        TEMPLATES[temp.id.casefold()] = temp

    for ent in vmf.by_class['bee2_template_colorpicker']:
        # Parse the colorpicker data.
        temp_id = ent['template_id'].casefold()
        try:
            priority = Decimal(ent['priority'])
        except ValueError:
            LOGGER.warning(
                'Bad priority for colorpicker in "{}" template!',
                temp_id.upper(),
            )
            priority = Decimal(0)

        try:
            remove_after = AfterPickMode(ent['remove_brush', '0'])
        except ValueError:
            LOGGER.warning(
                'Bad remove-brush mode for colorpicker in "{}" template!',
                temp_id.upper(),
            )
            remove_after = AfterPickMode.NONE

        color_pickers[temp_id].append(ColorPicker(
            priority,
            name=ent['targetname'],
            offset=Vec.from_str(ent['origin']),
            normal=Vec(x=1).rotate_by_str(ent['angles']),
            sides=ent['faces'].split(' '),
            grid_snap=srctools.conv_bool(ent['grid_snap']),
            after=remove_after,
            use_pattern=srctools.conv_bool(ent['use_pattern']),
            force_tex_white=ent['tex_white'],
            force_tex_black=ent['tex_black'],
        ))

    for ent in vmf.by_class['bee2_template_tilesetter']:
        # Parse the tile setter data.
        temp_id = ent['template_id'].casefold()
        tile_type = TILE_SETTER_SKINS[srctools.conv_int(ent['skin'])]
        color = ent['color']
        if color == 'tile':
            try:
                color = tile_type.color
            except ValueError:
                # Non-tile types.
                color = None
        elif color == 'invert':
            color = 'INVERT'
        elif color == 'match':
            color = None
        else:
            raise ValueError('Invalid TileSetter color '
                             '"{}" for "{}"'.format(color, temp_id))

        tile_setters[temp_id].append(TileSetter(
            offset=Vec.from_str(ent['origin']),
            normal=Vec(z=1).rotate_by_str(ent['angles']),
            color=color,
            tile_type=tile_type,
            picker_name=ent['color_picker'],
        ))

    temp_ids = set(conf_ents).union(
        detail_ents,
        world_ents,
        overlay_ents,
        color_pickers,
        tile_setters,
    )

    for temp_id in temp_ids:
        try:
            conf = conf_ents[temp_id]
        except KeyError:
            overlay_faces = []  # type: List[str]
            skip_faces = []  # type: List[str]
            vertical_faces = []  # type: List[str]
            realign_faces = []  # type: List[str]
        else:
            vertical_faces = conf['vertical_faces'].split()
            realign_faces = conf['realign_faces'].split()
            overlay_faces = conf['overlay_faces'].split()
            skip_faces = conf['skip_faces'].split()

        TEMPLATES[temp_id.casefold()] = Template(
            temp_id,
            world_ents[temp_id],
            detail_ents[temp_id],
            overlay_ents[temp_id],
            skip_faces,
            realign_faces,
            overlay_faces,
            vertical_faces,
            color_pickers[temp_id],
            tile_setters[temp_id],
        )


def get_template(temp_name) -> Template:
    """Get the data associated with a given template."""
    try:
        temp = TEMPLATES[temp_name.casefold()]
    except KeyError:
        raise InvalidTemplateName(temp_name) from None

    if isinstance(temp, ScalingTemplate):
        raise ValueError(
            'Scaling Template "{}" cannot be used '
            'as a normal template!'.format(temp_name)
        )

    return temp


def import_template(
    temp_name: Union[str, Template],
    origin: Vec,
    angles: Optional[Vec]=None,
    targetname: str='',
    force_type: TEMP_TYPES=TEMP_TYPES.default,
    add_to_map: bool=True,
    additional_visgroups: Iterable[str]=(),
    visgroup_choose: Callable[[Iterable[str]], Iterable[str]]=lambda x: (),
) -> ExportedTemplate:
    """Import the given template at a location.

    temp_name can be a string, or a template instance. visgroups is a list
    of additional visgroups to use after the ones in the name string (if given).

    If force_type is set to 'detail' or 'world', all brushes will be converted
    to the specified type instead. A list of world brushes and the func_detail
    entity will be returned. If there are no detail brushes, None will be
    returned instead of an invalid entity.

    If targetname is set, it will be used to localise overlay names.
    add_to_map sets whether to add the brushes and func_detail to the map.
    visgroup_choose is a callback used to determine if visgroups should be
    added - it's passed a list of names, and should return a list of ones to use.
    """
    import vbsp
    if isinstance(temp_name, Template):
        template, temp_name = temp_name, temp_name.id
        chosen_groups = set()  # type: Set[str]
    else:
        temp_name, chosen_groups = parse_temp_name(temp_name)
        template = get_template(temp_name)

    chosen_groups.update(additional_visgroups)
    chosen_groups.update(visgroup_choose(template.visgroups))

    orig_world, orig_detail, orig_over = template.visgrouped(chosen_groups)

    new_world = []  # type: List[Solid]
    new_detail = []  # type: List[Solid]
    new_over = []  # type: List[Entity]

    # A map of the original -> new face IDs.
    id_mapping = {}  # type: Dict[int, int]

    for orig_list, new_list in [
            (orig_world, new_world),
            (orig_detail, new_detail)
        ]:
        for old_brush in orig_list:
            brush = old_brush.copy(
                vmf_file=vbsp.VMF,
                side_mapping=id_mapping,
                keep_vis=False,
            )
            brush.localise(origin, angles)
            new_list.append(brush)

    for overlay in orig_over:  # type: Entity
        new_overlay = overlay.copy(
            vmf_file=vbsp.VMF,
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

        srctools.vmf.localise_overlay(new_overlay, origin, angles)
        orig_target = new_overlay['targetname']

        # Only change the targetname if the overlay is not global, and we have
        # a passed name.
        if targetname and orig_target and orig_target[0] != '@':
            new_overlay['targetname'] = targetname + '-' + orig_target

        vbsp.VMF.add_ent(new_overlay)
        new_over.append(new_overlay)

        # Don't let the overlays get retextured too!
        vbsp.IGNORED_OVERLAYS.add(new_overlay)

    if force_type is TEMP_TYPES.detail:
        new_detail.extend(new_world)
        new_world.clear()
    elif force_type is TEMP_TYPES.world:
        new_world.extend(new_detail)
        new_detail.clear()

    if add_to_map:
        vbsp.VMF.add_brushes(new_world)

    detail_ent: Optional[Entity] = None

    if new_detail:
        detail_ent = vbsp.VMF.create_ent(
            classname='func_detail'
        )
        # Don't let this be touched later..
        vbsp.IGNORED_BRUSH_ENTS.add(detail_ent)
        detail_ent.solids = new_detail
        if not add_to_map:
            detail_ent.remove()

    # Don't let these get retextured normally - that should be
    # done by retexture_template(), if at all!
    for solid in new_world:
        vbsp.IGNORED_FACES.update(solid.sides)
    for solid in new_detail:
        vbsp.IGNORED_FACES.update(solid.sides)

    return ExportedTemplate(
        new_world,
        detail_ent,
        new_over,
        id_mapping,
        template,
        origin,
        angles or Vec(0, 0, 0),
        {},  # Filled by retexture_template.
    )


def get_scaling_template(temp_id: str) -> ScalingTemplate:
    """Get the scaling data from a template.

    This is a dictionary mapping normals to the U,V and rotation data.
    """
    temp_name, over_names = parse_temp_name(temp_id)

    try:
        temp = TEMPLATES[temp_name.casefold()]
    except KeyError:
        raise InvalidTemplateName(temp_name) from None

    if isinstance(temp, ScalingTemplate):
        return temp

    # Otherwise parse the normal template into a scaling one.

    LOGGER.warning(
        'Template "{}" used as scaling template,'
        ' but is not really one!',
        temp_id,
    )

    world, detail, over = temp.visgrouped(over_names)

    if detail:
        world += detail

    uvs = {}

    for brush in world:
        for side in brush.sides:
            uvs[side.normal().as_tuple()] = (
                side.mat,
                side.uaxis.copy(),
                side.vaxis.copy(),
                side.ham_rot
            )

    return ScalingTemplate(
        temp.id,
        uvs
    )


def retexture_template(
    template_data: ExportedTemplate,
    origin: Vec,
    fixup: EntityFixup=None,
    replace_tex: Mapping[str, Union[List[str], str]]=srctools.EmptyMapping,
    force_colour: Portalable=None,
    force_grid: TileSize=None,
    generator: GenCat=GenCat.NORMAL,
    sense_offset: Optional[Vec]=None,
):
    """Retexture a template at the given location.

    - Only textures in the TEMPLATE_RETEXTURE dict will be replaced.
    - Others will be ignored (nodraw, plasticwall, etc)
    - Wall textures pointing up and down will switch to floor/ceiling textures.
    - Textures of the same type, normal and inst origin will randomise to the
      same type.
    - replace_tex is a replacement table. This overrides everything else.
      The values should either be a list (random), or a single value.
    - If force_colour is set, all tile textures will be switched accordingly.
      If set to 'INVERT', white and black textures will be swapped.
    - If force_grid is set, all tile textures will be that size.
    - generator defines the generator category to use for surfaces.
    - Fixup is the inst.fixup value, used to allow $replace in replace_tex.
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
    rand_prefix = 'TEMPLATE_{}_{}_{}:'.format(*(origin // 128))

    # Ensure all values are lists.
    replace_tex = {
        key.casefold(): ([value] if isinstance(value, str) else value)
        for key, value in
        replace_tex.items()
    }

    if sense_offset is None:
        sense_offset = Vec()
    else:
        sense_offset = sense_offset.copy().rotate(*template_data.angles)

    # For each face, if it needs to be forced to a colour, or None if not.
    # If a string it's forced to that string specifically.
    force_colour_face: Dict[str, Union[Portalable, str, None]] = defaultdict(lambda: None)
    # Picker names to their results.
    picker_results: Dict[str, Optional[texturing.Portalable]] = template_data.picker_results

    # If the "use patterns" option is enabled, face ID -> temp face to copy from.
    picker_patterned: Dict[str, Optional[Side]] = defaultdict(lambda: None)
    # Then also a cache of the tiledef -> dict of template faces.
    pattern_cache: Dict[tiling.TileDef, Dict[Tuple[int, int], Side]] = {}

    # Already sorted by priority.
    for color_picker in template.color_pickers:
        picker_pos = color_picker.offset.copy().rotate(*template_data.angles)
        picker_pos += template_data.origin + sense_offset
        picker_norm = color_picker.normal.copy().rotate(*template_data.angles)

        if color_picker.grid_snap:
            for axis in 'xyz':
                # Don't realign things in the normal's axis -
                # those are already fine.
                if not picker_norm[axis]:
                    picker_pos[axis] = picker_pos[axis] // 128 * 128 + 64

        try:
            tiledef, u, v = tiling.find_tile(picker_pos, picker_norm)
        except KeyError:
            # Doesn't exist.
            if color_picker.name:
                picker_results[color_picker.name] = None
            continue

        tile_type = tiledef[u, v]

        try:
            tile_color = tile_type.color
        except ValueError:
            # Not a tile with color (void, etc). Treat as missing.
            picker_results[color_picker.name] = None
            continue

        if color_picker.name:
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
                    is_wall=tiledef.normal.z != 0,
                    bevels=(False, False, False, False),
                    normal=tiledef.normal,
                    face_output=pattern,
                )

            for side in color_picker.sides:
                if picker_patterned[side] is None and (u, v) in pattern:
                    picker_patterned[side] = pattern[u, v]
        else:
            # Only do the highest priority successful one.
            for side in color_picker.sides:
                if force_colour_face[side] is None:
                    if tile_color is tile_color.WHITE:
                        force_colour_face[side] = color_picker.force_tex_white or tile_color
                    else:
                        force_colour_face[side] = color_picker.force_tex_black or tile_color

        if color_picker.after is AfterPickMode.VOID:
            tiledef[u, v] = TileType.VOID
        elif color_picker.after is AfterPickMode.NODRAW:
            tiledef[u, v] = TileType.NODRAW

    for tile_setter in template.tile_setters:
        setter_pos = tile_setter.offset.copy().rotate(*template_data.angles)
        setter_pos += template_data.origin + sense_offset
        setter_norm = tile_setter.normal.copy().rotate(*template_data.angles)
        setter_type = tile_setter.tile_type  # type: TileType

        if setter_type.is_tile:
            if isinstance(tile_setter.color, Portalable):
                # The color was specifically set. Inverting
                # is the only thing that has an effect.
                if force_colour == 'INVERT':
                    setter_color = ~tile_setter.color
                else:
                    setter_color = tile_setter.color
            # Otherwise it copies the forced colour - it needs to be white or black.
            elif isinstance(force_colour, Portalable):
                if tile_setter.color == 'INVERT':
                    setter_color = ~force_colour
                else:
                    setter_color = force_colour
            else:
                raise ValueError('"{}": Tile Setter requires a valid color value!')

            setter_type = TileType.with_color_and_size(
                setter_type.tile_size,
                setter_color,
            )

        tiling.edit_quarter_tile(
            setter_pos,
            setter_norm,
            setter_type,
            silent=True,  # Don't log missing positions.
        )

    for brush in all_brushes:
        for face in brush:
            orig_id = rev_id_mapping[face.id]

            if orig_id in template.skip_faces:
                continue

            template_face = picker_patterned[orig_id]
            if template_face is not None:
                face.mat = template_face.mat
                face.uaxis = template_face.uaxis.copy()
                face.vaxis = template_face.vaxis.copy()
                continue

            folded_mat = face.mat.casefold()

            norm = face.normal()
            random.seed(rand_prefix + norm.join('_'))

            if orig_id in template.realign_faces:
                try:
                    uaxis, vaxis = REALIGN_UVS[norm.as_tuple()]
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

            override_mat: Optional[List[str]]
            try:
                override_mat = replace_tex['#' + orig_id]
            except KeyError:
                try:
                    override_mat = replace_tex[folded_mat]
                except KeyError:
                    override_mat = None

            if override_mat is not None:
                # Replace_tex overrides everything.
                mat = random.choice(override_mat)
                if mat[:1] == '$' and fixup is not None:
                    mat = fixup[mat]
                if mat.startswith('<') or mat.endswith('>'):
                    # Lookup in the style data.
                    gen, mat = texturing.parse_name(mat[1:-1])
                    mat = gen.get(face.get_origin(), mat)
                face.mat = mat
                continue

            if folded_mat == 'tile/white_wall_tile003b':
                LOGGER.warning('"{}": white_wall_tile003b has changed definitions.', template.id)

            try:
                tex_type = TEMPLATE_RETEXTURE[folded_mat]
            except KeyError:
                continue  # It's nodraw, or something we shouldn't change

            tex_colour: Optional[Portalable]
            gen_type, tex_name, tex_colour = tex_type

            if not gen_type.is_tile:
                # It's something like squarebeams or backpanels, so
                # we don't need much special handling.
                texturing.apply(gen_type, face, tex_name)

                if tex_name in ('goo', 'goo_cheap'):
                    if norm != (0, 0, 1):
                        # Goo must be facing upright!
                        # Retexture to nodraw, so a template can be made with
                        # all faces goo to work in multiple orientations.
                        face.mat = 'tools/toolsnodraw'
                    else:
                        # Goo always has the same orientation!
                        face.uaxis = UVAxis(
                            1, 0, 0,
                            offset=0,
                            scale=vbsp_options.get(float, 'goo_scale'),
                        )
                        face.vaxis = UVAxis(
                            0, -1, 0,
                            offset=0,
                            scale=vbsp_options.get(float, 'goo_scale'),
                        )
                continue
            else:
                assert isinstance(tex_colour, Portalable)
                # Allow overriding to panel or bullseye types.
                if gen_type is GenCat.NORMAL:
                    gen_type = generator
            # Otherwise, it's a panel wall or the like

            if force_colour_face[orig_id] is not None:
                tex_colour = force_colour_face[orig_id]
                if isinstance(tex_colour, str):
                    face.mat = tex_colour
                    continue
            elif force_colour == 'INVERT':
                # Invert the texture
                tex_colour = ~tex_colour
            elif force_colour is not None:
                tex_colour = force_colour

            if force_grid is not None:
                tex_name = force_grid

            texturing.apply(gen_type, face, tex_name, tex_colour)

    for over in template_data.overlay[:]:
        over_pos = Vec.from_str(over['basisorigin'])
        mat = over['material'].casefold()

        if mat in replace_tex:
            mat = random.choice(replace_tex[mat])
            if mat[:1] == '$' and fixup is not None:
                mat = fixup[mat]
            if mat.startswith('<') or mat.endswith('>'):
                mat = mat[1:-1]
                gen, tex_name = texturing.parse_name(mat[1:-1])
                mat = gen.get(over_pos, tex_name)
        elif mat in consts.Signage:
            import vbsp
            sign_type = vbsp.TEX_VALVE[mat][1]
            mat = texturing.OVERLAYS.get(over_pos, sign_type)

        if mat == '':
            # If blank, remove the overlay from the map and the list.
            # (Since it's inplace, this can affect the tuple.)
            template_data.overlay.remove(over)
            over.remove()
        else:
            over['material'] = mat
