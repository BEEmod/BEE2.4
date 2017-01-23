"""Templates are sets of brushes which can be copied into the map."""
import random
from collections import defaultdict
from enum import Enum

import srctools
import vbsp_options

from srctools import Entity, Solid, Side, Property, Vec_tuple, UVAxis, Vec
import comp_consts as consts
import utils

from typing import (
    Iterable, Union, Callable,
    NamedTuple, Tuple,
    Dict, List, Set,
)

LOGGER = utils.getLogger(__name__, alias='template')

# A lookup for templates.
TEMPLATES = {}  # type: Dict[str, Template]

# The location of the template data.
TEMPLATE_LOCATION = 'bee2/templates.vmf'


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
    ('detail', List[Solid]),
    ('overlay', List[Entity]),
    ('orig_ids', Dict[str, str]),
])


class Template:
    """Represents a template before it's imported into a map."""
    def __init__(
        self,
        temp_id,
        world: Dict[str, List[Solid]],
        detail: Dict[str, List[Solid]],
        overlays: Dict[str, List[Entity]],
        realign_faces: Iterable[str]=(),
        overlay_transfer_faces: Iterable[str]=(),
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

        TEMPLATES[temp_id.casefold()] = self

    @property
    def visgroups(self):
        """Iterate over the template visgroups"""
        return iter(self._data)

    def visgrouped(
        self,
        visgroups: Iterable[str]=(),
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
                raise ValueError('Unknown visgroup "{}" for ""! (valid: {})'.format(
                    group, self.id,
                    ', '.join(map(repr, self._data)),
                ))
            world_brushes.extend(world)
            detail_brushes.extend(detail)
            overlays.extend(over)

        return world_brushes, detail_brushes, overlays


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

    for temp_id in set(detail_ents).union(world_ents, overlay_ents):
        Template(
            temp_id,
            world_ents[temp_id],
            detail_ents[temp_id],
            overlay_ents[temp_id],
        )


def get_template(temp_name):
    """Get the data associated with a given template.

    This is a dictionary mapping visgroups -> (world, detail, over) tuples.
    """
    try:
        return TEMPLATES[temp_name.casefold()]
    except KeyError as err:
        # Replace the KeyError with a more useful error message, and
        # list all the templates that are available.
        err.args ('Template not found: "{}"\n{}'.format(
            temp_name,
            '\n'.join(
            ('* "' + temp.upper() + '"')
            for temp in
            sorted(TEMPLATES.keys())
            ),
        ), )
        raise err


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
    )


def get_scaling_template(
        temp_id: str,
    ) -> Dict[Vec_tuple, Tuple[UVAxis, UVAxis, float]]:
    """Get the scaling data from a template.

    This is a dictionary mapping normals to the U,V and rotation data.
    """
    temp_name, over_names = parse_temp_name(temp_id)
    world, detail, over = get_template(temp_name).visgrouped(over_names)

    if detail:
        world += detail

    uvs = {}

    for brush in world:
        for side in brush.sides:
            uvs[side.normal().as_tuple()] = (
                side.uaxis.copy(),
                side.vaxis.copy(),
                side.ham_rot,
            )

    return uvs


def retexture_template(
        template_data: ExportedTemplate,
        origin: Vec,
        fixup: srctools.vmf.EntityFixup=None,
        replace_tex: dict= srctools.EmptyMapping,
        force_colour: MAT_TYPES=None,
        force_grid: str=None,
        use_bullseye=False,
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
    """
    import vbsp

    all_brushes = list(template_data.world)
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

    for brush in all_brushes:
        for face in brush:
            folded_mat = face.mat.casefold()

            norm = face.normal()
            random.seed(rand_prefix + norm.join('_'))

            if folded_mat in replace_tex:
                # Replace_tex overrides everything.
                mat = random.choice(replace_tex[folded_mat])
                LOGGER.info('Mat: {}, replacement: {}', folded_mat, mat)
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
                    if face.normal() != (0, 0, 1):
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

            if force_colour == 'INVERT':
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

            if can_clump:
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
