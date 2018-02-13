"""Templates are sets of brushes which can be copied into the map."""
import random
from collections import defaultdict, namedtuple
from collections.abc import Mapping

from decimal import Decimal
from enum import Enum

import srctools
import vbsp_options

from srctools import Entity, Solid, Side, Property, Vec_tuple, UVAxis, Vec, VMF
import comp_consts as consts
import utils
import conditions

from typing import (
    Iterable, Union, Callable,
    NamedTuple, Tuple,
    Dict, List, Set,
)

LOGGER = utils.getLogger(__name__, alias='template')

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

ColorPicker = namedtuple('ColorPicker', [
    'priority',  # Decimal order to do them in.
    'offset',
    'normal',  # Normal of the surface.
    'sides',
    'grid_snap',  # Snap to grid on non-normal axes
    'remove_brush',  # Remove the brush after
])


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
    consts.Special.BACKPANELS_CHEAP: 'special.behind',
    consts.Special.SQUAREBEAMS: 'special.edge',
    consts.Special.GLASS: 'special.glass',
    consts.Special.GRATING: 'special.grating',

    consts.Goo.CHEAP: 'special.goo_cheap',
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
    MAT_TYPES.white: MAT_TYPES.black,
    MAT_TYPES.black: MAT_TYPES.white,
    None: 'INVERT',
    'INVERT': None,
}

ExportedTemplate = NamedTuple('ExportedTemplate', [
    ('world', List[Solid]),
    ('detail', Entity),
    ('overlay', List[Entity]),
    ('orig_ids', Dict[str, str]),
    ('template', 'Template'),
    ('origin', Vec),
    ('angles', Vec),
])

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
        temp_id,
        world: Dict[str, List[Solid]],
        detail: Dict[str, List[Solid]],
        overlays: Dict[str, List[Entity]],
        skip_faces: Iterable[str]=(),
        realign_faces: Iterable[str]=(),
        overlay_transfer_faces: Iterable[str]=(),
        vertical_faces: Iterable[str]=(),
        color_pickers: Iterable[ColorPicker]=(),
    ):
        """Make an overlay.

        """
        self.id = temp_id
        self._data = data = {}

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
            key=ColorPicker.priority.__get__,
            reverse=True,
        )

    @property
    def visgroups(self):
        """Iterate over the template visgroups"""
        return iter(self._data)

    def visgrouped(
        self,
        visgroups: Set[str]=(),
    ) -> Tuple[List[Solid], List[Solid], List[Entity]]:
        """Given some visgroups, return the matching data.

        This returns lists of the world brushes, detail brushes, and overlays.
        """
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


class ScalingTemplate(Mapping):
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

        for norm, name in (
            ((0, 0, 1), 'up'),
            ((0, 0, -1), 'dn'),
            ((0, 1, 0), 'n'),
            ((0, -1, 0), 's'),
            ((1, 0, 0), 'e'),
            ((-1, 0, 0), 'w'),
        ):
            axes[norm] = (
                ent[name + '_tex'],
                UVAxis.parse(ent[name + '_uaxis']),
                UVAxis.parse(ent[name + '_vaxis']),
                srctools.conv_float(ent[name + '_rotation']),
            )
        return cls(ent['template_id'], axes)

    def __len__(self):
        return 6

    def __iter__(self):
        yield from [
            Vec(-1, 0, 0),
            Vec(1, 0, 0),
            Vec(0, -1, 0),
            Vec(0, 1, 0),
            Vec(0, 0, -1),
            Vec(0, 0, 1),
        ]

    def __getitem__(self, normal: Union[Vec, Tuple[float, float, float]]):
        mat, axis_u, axis_v, rotation = self._axes[tuple(normal)]
        return mat, axis_u.copy(), axis_v.copy(), rotation

    def rotate(self, angles: Vec, origin: Vec=(0, 0, 0)):
        """Rotate this template, and return a new template with those angles."""
        new_axis = {}
        origin = Vec(origin)
        for norm, (mat, axis_u, axis_v, rot) in self._axes.items():
            axis_u = axis_u.localise(origin, angles)
            axis_v = axis_v.localise(origin, angles)
            norm = Vec(norm).rotate(*angles)
            new_axis[norm.as_tuple()] = mat, axis_u, axis_v, rot

        return ScalingTemplate(self.id, new_axis)

    def apply(self, face: Side, *, change_mat=True):
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
        }
    else:
        return name.casefold(), set()


def load_templates():
    """Load in the template file, used for import_template()."""
    with open(TEMPLATE_LOCATION) as file:
        props = Property.parse(file, TEMPLATE_LOCATION)
    vmf = srctools.VMF.parse(props, preserve_ids=True)

    def make_subdict():
        return defaultdict(list)
    # detail_ents[temp_id][visgroup]
    detail_ents = defaultdict(make_subdict)
    world_ents = defaultdict(make_subdict)
    overlay_ents = defaultdict(make_subdict)
    conf_ents = {}

    color_pickers = defaultdict(list)

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
        color_pickers[temp_id].append(ColorPicker(
            priority,
            offset=Vec.from_str(ent['origin']),
            normal=Vec(x=1).rotate_by_str(ent['angles']),
            sides=ent['faces'].split(' '),
            grid_snap=srctools.conv_bool(ent['grid_snap']),
            remove_brush=srctools.conv_bool(ent['remove_brush']),
        ))

    for temp_id in set(detail_ents).union(world_ents, overlay_ents):
        try:
            conf = conf_ents[temp_id]
        except KeyError:
            overlay_faces = []
            skip_faces = []
            vertical_faces = []
            realign_faces = []
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
        origin,
        angles=None,
        targetname='',
        force_type=TEMP_TYPES.default,
        add_to_map=True,
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
        chosen_groups = set()
    else:
        temp_name, chosen_groups = parse_temp_name(temp_name)
        template = get_template(temp_name)

    chosen_groups.update(additional_visgroups)
    chosen_groups.update(visgroup_choose(template.visgroups))

    orig_world, orig_detail, orig_over = template.visgrouped(chosen_groups)

    new_world = []  # type: List[Solid]
    new_detail = []  # type: List[Solid]
    new_over = []  # type: List[Entity]

    id_mapping = {}  # A map of the original -> new face IDs.

    for orig_list, new_list in [
            (orig_world, new_world),
            (orig_detail, new_detail)
        ]:
        for old_brush in orig_list:
            brush = old_brush.copy(
                map=vbsp.VMF,
                side_mapping=id_mapping,
                keep_vis=False,
            )
            brush.localise(origin, angles)
            new_list.append(brush)

    for overlay in orig_over:  # type: Entity
        new_overlay = overlay.copy(
            map=vbsp.VMF,
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

    if new_detail:
        detail_ent = vbsp.VMF.create_ent(
            classname='func_detail'
        )
        # Don't let this be touched later..
        vbsp.IGNORED_BRUSH_ENTS.add(detail_ent)
        detail_ent.solids = new_detail
        if not add_to_map:
            detail_ent.remove()
    else:
        detail_ent = None
        new_detail = []

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
    fixup: srctools.vmf.EntityFixup=None,
    replace_tex: dict= srctools.EmptyMapping,
    force_colour: MAT_TYPES=None,
    force_grid: str=None,
    use_bullseye=False,
    no_clumping=False,
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
    - If force_grid is set, all tile textures will be that size:
      ('wall', '2x2', '4x4', 'special')
    - If use_bullseye is true, the bullseye textures will be used for all panel
      sides instead of the normal textures. (This overrides force_grid.)
    - Fixup is the inst.fixup value, used to allow $replace in replace_tex.
    - Set no_clump if the brush is used on a special entity, and therefore
      won't get retextured by the main code. That means we need to directly
      retexture here.
    """
    import vbsp

    template = template_data.template  # type: Template

    rev_id_mapping = {
        new_id: str(old_id)
        for old_id, new_id in
        template_data.orig_ids.items()
    }

    all_brushes = list(template_data.world)  # type: List[Solid]
    if template_data.detail is not None:
        all_brushes.extend(template_data.detail.solids)

    # Template faces are randomised per block and side. This means
    # multiple templates in the same block get the same texture, so they
    # can clip into each other without looking bad.
    rand_prefix = 'TEMPLATE_{}_{}_{}:'.format(*(origin // 128))

    # Even if not axis-aligned, make mostly-flat surfaces
    # floor/ceiling (+-40 degrees)
    # sin(40) = ~0.707
    floor_tolerance = 0.8

    can_clump = vbsp.can_clump()

    # Ensure all values are lists.
    replace_tex = {
        key.casefold(): ([value] if isinstance(value, str) else value)
        for key, value in
        replace_tex.items()
    }

    # For each face, if it needs to be forced to a colour, or None if not.
    force_colour_face = defaultdict(lambda: None)

    # Already sorted by priority.
    for color_picker in template.color_pickers:
        picker_pos = color_picker.offset.copy().rotate(*template_data.angles)
        picker_pos += template_data.origin
        picker_norm = color_picker.normal.copy().rotate(*template_data.angles)

        if color_picker.grid_snap:
            for axis in 'xyz':
                # Don't realign things in the normal's axis -
                # those are already fine.
                if not picker_norm[axis]:
                    picker_pos[axis] = picker_pos[axis] // 128 * 128 + 64

        brush = conditions.SOLIDS.get(picker_pos.as_tuple(), None)

        if brush is None or abs(brush.normal) != abs(picker_norm):
            # Doesn't exist.
            continue

        if color_picker.remove_brush and brush.solid in vbsp.VMF.brushes:
            brush.solid.remove()

        for side in color_picker.sides:
            # Only do the highest priority successful one.
            if force_colour_face[side] is None:
                force_colour_face[side] = brush.color

    for brush in all_brushes:
        for face in brush:
            orig_id = rev_id_mapping[face.id]

            if orig_id in template.skip_faces:
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

            if folded_mat in replace_tex:
                # Replace_tex overrides everything.
                mat = random.choice(replace_tex[folded_mat])
                if mat[:1] == '$' and fixup is not None:
                    mat = fixup[mat]
                if mat.startswith('<') or mat.endswith('>'):
                    # Lookup in the style data.
                    mat = vbsp.get_tex(mat[1:-1])
                face.mat = mat
                continue

            tex_type = TEMPLATE_RETEXTURE.get(folded_mat)

            if tex_type is None:
                continue  # It's nodraw, or something we shouldn't change

            if isinstance(tex_type, str):
                # It's something like squarebeams or backpanels, just look
                # it up
                face.mat = vbsp.get_tex(tex_type)

                if tex_type == 'special.goo_cheap':
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
            # It's a regular wall type!
            tex_colour, grid_size = tex_type

            if force_colour_face[orig_id] is not None:
                tex_colour = force_colour_face[orig_id]
            elif force_colour == 'INVERT':
                # Invert the texture
                tex_colour = (
                    MAT_TYPES.white
                    if tex_colour is MAT_TYPES.black else
                    MAT_TYPES.black
                )
            elif force_colour is not None:
                tex_colour = force_colour

            if force_grid is not None:
                grid_size = force_grid

            if 1 in norm or -1 in norm:  # Facing NSEW or up/down
                # If axis-aligned, make the orientation aligned to world
                # That way multiple items merge well, and walls are upright.
                # We allow offsets < 1 grid tile, so items can be offset.
                face.uaxis.offset %= TEMP_TILE_PIX_SIZE[grid_size]
                face.vaxis.offset %= TEMP_TILE_PIX_SIZE[grid_size]

            if use_bullseye:
                # We want to use the bullseye textures, instead of normal
                # ones
                if norm.z < -floor_tolerance:
                    face.mat = vbsp.get_tex(
                        'special.bullseye_{}_floor'.format(tex_colour)
                    )
                elif norm.z > floor_tolerance:
                    face.mat = vbsp.get_tex(
                        'special.bullseye_{}_ceiling'.format(tex_colour)
                    )
                else:
                    face.mat = ''  # Ensure next if statement triggers

                # If those aren't defined, try the wall texture..
                if face.mat == '':
                    face.mat = vbsp.get_tex(
                        'special.bullseye_{}_wall'.format(tex_colour)
                    )
                if face.mat != '':
                    continue  # Set to a bullseye texture,
                    # don't use the wall one

            if grid_size == 'special':
                # Don't use wall on faces similar to floor/ceiling:
                if -floor_tolerance < norm.z < floor_tolerance:
                    face.mat = vbsp.get_tex(
                        'special.{!s}_wall'.format(tex_colour)
                    )
                else:
                    face.mat = ''  # Ensure next if statement triggers

                # Various fallbacks if not defined
                if face.mat == '':
                    face.mat = vbsp.get_tex(
                        'special.{!s}'.format(tex_colour)
                    )
                if face.mat == '':
                    # No special texture - use a wall one.
                    grid_size = 'wall'
                else:
                    # Set to a special texture,
                    continue # don't use the wall one

            if norm.z > floor_tolerance:
                grid_size = 'ceiling'
            if norm.z < -floor_tolerance:
                grid_size = 'floor'

            if can_clump and not no_clumping:
                # For the clumping algorithm, set to Valve PeTI and let
                # clumping handle retexturing.
                vbsp.IGNORED_FACES.remove(face)
                if tex_colour is MAT_TYPES.white:
                    if grid_size == '4x4':
                        face.mat = 'tile/white_wall_tile003f'
                    elif grid_size == '2x2':
                        face.mat = 'tile/white_wall_tile003c'
                    else:
                        face.mat = 'tile/white_wall_tile003h'
                elif tex_colour is MAT_TYPES.black:
                    if grid_size == '4x4':
                        face.mat = 'metal/black_wall_metal_002b'
                    elif grid_size == '2x2':
                        face.mat = 'metal/black_wall_metal_002a'
                    else:
                        face.mat = 'metal/black_wall_metal_002e'
            else:
                face.mat = vbsp.get_tex(
                    '{!s}.{!s}'.format(tex_colour, grid_size)
                )

    for over in template_data.overlay[:]:
        random.seed('TEMP_OVERLAY_' + over['basisorigin'])
        mat = over['material'].casefold()
        if mat in replace_tex:
            mat = random.choice(replace_tex[mat])
            if mat[:1] == '$':
                mat = fixup[mat]
            if mat.startswith('<') or mat.endswith('>'):
                # Lookup in the style data.
                mat = vbsp.get_tex(mat[1:-1])
        elif mat in vbsp.TEX_VALVE:
            mat = vbsp.get_tex(vbsp.TEX_VALVE[mat])
        else:
            continue
        if mat == '':
            # If blank, remove the overlay from the map and the list.
            # (Since it's inplace, this can affect the tuple.)
            template_data.overlay.remove(over)
            over.remove()
        else:
            over['material'] = mat
