"""Manages reading general options from vbsp_config."""
from enum import Enum
from collections import defaultdict

import inspect
import io
import random

from srctools import Property, Vec, parse_vec_str
import srctools
import utils
import comp_consts as consts

from typing import TypeVar, Type, Optional, Iterator

LOGGER = utils.getLogger(__name__)

SETTINGS = {}
TEXTURES = {}

class TYPE(Enum):
    """The types arguments can have."""
    STR = str
    INT = int
    FLOAT = float
    BOOL = bool
    VEC = Vec
    
TYPE_NAMES = {
    TYPE.STR: 'Text',
    TYPE.INT: 'Whole Number',
    TYPE.FLOAT: 'Decimal Number',
    TYPE.BOOL: 'True/False',
    TYPE.VEC: 'Vector',
}

class Opt:
    def __init__(self, id, default, doc, fallback=None):
        if isinstance(default, TYPE):
            self.type = default
            self.default = None
        else:
            self.type = TYPE(type(default))
            self.default = default
        self.id = id.casefold()
        self.name = id
        self.fallback = fallback
        # Remove indentation, and trailing carriage return
        self.doc = inspect.cleandoc(doc).rstrip('\n').splitlines()
        if fallback is not None:
            self.doc += 'If unset, the default is read from `{}`.'.format(default)


class Tex:
    def __init__(self, group, name, default=(), fallback=None, add=()):
        self.group = group
        self.name = name
        if isinstance(default, (str, consts.ConstGroup)):
            self.default = [default]
        else:
            self.default = list(default)
        self.additional = list(add)
        self.fallback = fallback

    def __repr__(self):
        return (
            'Tex({0.group!r}, {0.name!r}, {0.default!r}, '
            'fallback={0.fallback!r}, add={0.additional!r})'.format(self)
        )


def load_options(opt_blocks: Iterator[Property]):
    """Read settings from the given property block."""
    SETTINGS.clear()
    set_vals = {}
    for opt_block in opt_blocks:
        for prop in opt_block:
            set_vals[prop.name] = prop.value

    options = {opt.id: opt for opt in DEFAULTS}
    if len(options) != len(DEFAULTS):
        from collections import Counter
        # Find ids used more than once..
        raise Exception('Duplicate option(s)! ({})'.format(', '.join(
            k for k, v in
            Counter(opt.id for opt in DEFAULTS).items()
            if v > 1
        )))

    fallback_opts = []

    for opt in DEFAULTS:
        try:
            val = set_vals.pop(opt.id)
        except KeyError:
            if opt.fallback is not None:
                fallback_opts.append(opt)
                assert opt.fallback in options, 'Invalid fallback in ' + opt.id
            else:
                SETTINGS[opt.id] = opt.default
            continue
        if opt.type is TYPE.VEC:
            # Pass nones so we can check if it failed.. 
            parsed_vals = parse_vec_str(val, x=None)
            if parsed_vals[0] is None:
                SETTINGS[opt.id] = opt.default
            else:
                SETTINGS[opt.id] = Vec(*parsed_vals)
        elif opt.type is TYPE.BOOL:
            SETTINGS[opt.id] = srctools.conv_bool(val, opt.default)
        else:  # int, float, str - no special handling...
            try:
                SETTINGS[opt.id] = opt.type.value(val)
            except (ValueError, TypeError):
                SETTINGS[opt.id] = opt.default

    for opt in fallback_opts:
        try:
            SETTINGS[opt.id] = SETTINGS[opt.fallback]
        except KeyError:
            raise Exception('Bad fallback for "{}"!'.format(opt.id))
        # Check they have the same type.
        assert opt.type is options[opt.fallback].type

    if set_vals:
        LOGGER.warning('Extra config options: {}', set_vals)


def load_tex(blocks: Iterator[Property]):
    """Load in texture definitions."""
    TEXTURES.clear()
    raw_configs = defaultdict(list)

    for block in blocks:
        for group in block:
            for prop in group:
                raw_configs[group.name, prop.name].append(prop.value)

    tex_options = {tex.group + '.' + tex.name: tex for tex in TEX_DEFAULTS}

    for tex_opt in TEX_DEFAULTS:
        if tex_opt.fallback is None:
            continue
        fallback = tex_options[tex_opt.fallback]
        if fallback.fallback is not None:
            raise TypeError('"{}.{}"' " can't double-fallback!".format(
                tex_opt.group,
                tex_opt.name,
            ))

    need_fallback = []
    need_additional = []
    for dotted, tex_opt in tex_options.items():
        try:
            TEXTURES[dotted] = raw_configs[tex_opt.group, tex_opt.name]
            if TEXTURES[dotted]:
                continue
        except KeyError:
            pass

        if tex_opt.fallback:
            fallback = tex_options[tex_opt.fallback]
            need_fallback.append((dotted, fallback))
        else:
            TEXTURES[dotted] = tex_opt.default

        if tex_opt.additional:
            need_additional.append((dotted, tex_opt))

    for dotted, fallback in need_fallback:
        TEXTURES[dotted] = TEXTURES[fallback.group + '.' + fallback.name].copy()

    for name, tex in TEXTURES.items():
        if not tex or tex == ['']:
            TEXTURES[name] = []

    for dotted, tex_opt in need_additional:
        for add in tex_opt.additional:
            TEXTURES[dotted].extend(TEXTURES[add])

T = TypeVar('T')


def get(expected_type: Type[T], name) -> Optional[T]:
    """Get the given option. 
    expected_type should be the class of the value that's expected.
    The value can be None if unset.
    """
    try:
        val = SETTINGS[name.casefold()]
    except KeyError:
        raise TypeError('Option "{}" does not exist!'.format(name)) from None
    
    if val is None:
        return None
        
    # Don't allow subclasses (bool/int)
    if type(val) is not expected_type:
        raise ValueError('Option "{}" is {} (expected {})'.format(
            name, 
            type(val), 
            expected_type,
        ))
    # Vec is mutable, don't allow modifying the original.
    if expected_type is Vec:
        return val.copy()
    else:
        return val


def get_tex(name: str) -> str:
    try:
        return random.choice(TEXTURES[name])
    except TypeError:
        raise Exception('No texture "{}"!'.format(name))
    except IndexError:
        raise Exception('Empty texture definition for "{}"!'.format(name))


def get_all_tex(name: str) -> list:
    try:
        return TEXTURES[name]
    except TypeError:
        raise Exception('No texture "' + name + '"!')

INFO_DUMP_FORMAT = """\
## `{id}`{default} ({type})
{desc}

"""


def dump_info():
    """Create a Markdown description of all options."""
    file = io.StringIO()
    print('*' * 20, file=file)
    
    print('# VBSP_config options:', file=file)
    
    for opt in DEFAULTS:
        if opt.default is None:
            default = ''
        elif type(opt.default) is Vec:
            default =  '(`' + opt.default.join(' ') + '`)' 
        else:
            default = ' = `' + repr(opt.default) + '`'
        file.write(INFO_DUMP_FORMAT.format(
            id=opt.name, 
            default=default,
            type=TYPE_NAMES[opt.type],
            desc='\n'.join(opt.doc),
        ))
    
    print('*' * 20, file=file)
    return file.getvalue()

DEFAULTS = [
    Opt('goo_mist', False,
        """Add misty info_particle_systems to goo pits.

        This appears most commonly in Portal 1 maps.
        It can be disabled globally by a style var.
        """),
    Opt('remove_info_lighting', False,
        """Remove the glass/grating info_lighting entities.
        This should be used when the border is made of brushes.
        """),
    Opt('remove_pedestal_plat', False,
        """Remove the PeTI-generated pedestal button platforms.
        """),
    Opt('remove_exit_signs', False,
        """Remove the exit sign overlays for singleplayer.
        """),

    Opt('rotate_edge', False,
        """Rotate squarebeams textures 90 degrees.
        """),
    Opt('reset_edge_off', False,
        """Set the offset of squarebeams to 0.
        """),
    Opt('edge_scale', 0.15,
       """The scale on squarebeams textures.
       """),
    Opt('rotate_edge_special', TYPE.BOOL,
        """Rotate squarebeams textures on angled/flip panels 90 degrees.
        """, fallback='rotate_edge'),
    Opt('reset_edge_off_special', TYPE.BOOL,
        """Set the offset of squarebeams on angled/flip panels to 0.
        """, fallback='reset_edge_off'),
    Opt('edge_scale_special', TYPE.FLOAT,
        """The scale on angled/flip panel squarebeams textures.
        """, fallback='edge_scale'),

    Opt('tile_texture_lock', True,
        """If disabled, reset offsets for all white/black brushes.

        This makes EmbedFace textures contiguous, for irregular textures.
        """),

    Opt('fizz_border_vertical', False,
        """For fizzler borders, indicate that the texture is vertical.
        """),

    Opt('fizz_border_thickness', 8,
        """For fizzler borders, set the width of the generated overlays.
        """),
    Opt('fizz_border_repeat', 128,
        """For fizzler borders, the distance before the
        texture will repeat again.
        """),

    Opt('fizz_visibility', True,
        """Whether fizzlers should be visible.

        When `False`, this disables fizzler sounds and implies
        `fizz_scanline` is also `False`.
        """),

    Opt('force_fizz_reflect', False,
        """Force fast reflections on fizzlers.
        """),
    Opt('force_brush_reflect', False,
        """Force fast reflections on func_brushes.
        """),

    Opt('flip_sound_start', "World.a3JumpIntroRotatingPanelTravel",
        """Set the starting sound for Flip Panel brushes.
        """),
    Opt('flip_sound_stop', "World.a3JumpIntroRotatingPanelArrive",
        """Set the stopping sound for Flip Panel brushes.
        """),

    Opt('staticPan', TYPE.STR,
        """Folder for static panels.

        Instances follow the pattern `ang_type.vmf`,
        where ang = (`00`, `30`, `45`, `60`, `90`) and type=(`glass`, `surf`).
        """),
    Opt('static_pan_temp_flat', "BEE2_STATIC_PAN_FLAT",
        """Template used for 0-degree static panels.

        This should be a panel sticking slightly out of the surface.
        """),
    Opt('static_pan_temp_white', "BEE2_STATIC_PAN_ANGLED",
        """Template used for angled portalable static panels.
        """),
    Opt('static_pan_temp_black', "BEE2_STATIC_PAN_ANGLED",
        """Template used for angled non-portalable static panels.
        """),
    # If set,
    Opt('dynamic_pan_temp', TYPE.STR,
        """If set, replace panel func_brushes with this.

        The top texture should be set to `black_wall_metal_002c`.
        """),
    Opt('dynamic_pan_parent', "model_arms,panel_attach",
        """The local name that the panel func_brush should parent to.
        Adding the attachment name to the parent after a comma
        automatically sets the attachment point for the brush.
        """),

    Opt('signInst', TYPE.STR,
        """Adds this instance on all the signs.

        The origin is positioned on the surface.
        """),
    Opt('signSize', 32,
        """Set the size of the sign overlays.
        """),
    Opt('signPack', TYPE.STR,
        """Packlist to use when `signInst` is added.
        """),

    Opt('broken_antline_chance', 0.0,
        """The chance an antline will be 'broken'.

        For each antline, this is checked. If true, `broken_antline_distance`
        at most become broken.
        """),
    Opt('broken_antline_distance', 3,
        """The maximum distance of a single broken section.
        """),
    Opt('goo_scale', 1.00,
        """Scale of the goo textures.
        """),

    Opt('pit_blend_light', TYPE.STR,
        """Color of lights in bottomless pits.

        These are added at in the skybox and in the map, to blend together the
        lighting. It should be set to the ambient light color.
        """),

    Opt('glass_clip', "BEE2/glass_player_clip",
        """Texture used for glass player clips.
        """),
    Opt('grating_clip', "BEE2/grate_player_clip",
        """Texture used for grating player clips.
        """),
    Opt('keep_barrier_inst', False,
        """Keep glass/grating brush instances. If glass_clip or grating_clip
        is set, they are removed by default. This disables that behaviour.
        """),

    # Packlists for glass and gratings
    Opt('glass_pack', "PACK_PLAYER_CLIP_GLASS",
        """Packlist for glass clips.

        This is used for `glass_clip`.
        """),
    Opt('grating_pack', "PACK_PLAYER_CLIP_GRATE",
        """Packlist for grating clips.

        This is used for `grating_clip`.
        """),
    Opt('grating_filter', "@not_paint_bomb",
        """Filter used on grating `func_vphysics_clips`.

        """),
    Opt('glass_template', TYPE.STR,
        """A template for rotation and scaling of glass.

        This overrides `glass_scale` if set. It should be a single brush
        cube - the glass is set to the same rotation as the matching side.
        """),
    Opt('grating_template', TYPE.STR,
        """A template for rotation and scaling of grates.

        This overrides `grating_scale` if set. It should be a single brush
        cube - the grate is set to the same rotation as the matching side.
        """),

    Opt('goo_wall_scale_temp', TYPE.STR,
        """A template for rotation and scaling for `goo_wall` textures.

        It should be a single brush cube - the wall is set to the same
        rotation as the matching side. (The bottom is ignored).
        """),

    Opt('glass_scale', 0.15,
        """Scale of glass textures.

        This is overridden by `glass_template`.
        """),
    Opt('grating_scale', 0.15,
        """Scale of grating textures.

        This is overridden by `grating_template`.
        """),

    Opt('glass_floorbeam_temp', TYPE.STR,
        """Template for beams in the middle of large glass floors.

        The template should be two brushes for the texture scaling.
        """),
    Opt('glass_floorbeam_sep', 2,
        """Number of blocks between beams.
        """),

    Opt('clump_wall_tex', False,
        """Use the clumping wall algorithm.

        This creates groups of the same texture.
        `clump_size`, `clump_width`, and `clump_number` must be set.
        """),
    Opt('clump_size', 4,
        """The maximum length of a clump.

        Clumps are rectangular, and this indicates the long dimension.
        """),
    Opt('clump_width', 2,
        """The maximum width of a clump.

        Clumps are rectangular, and this indicates the short dimensions.
        """),
    Opt('clump_number', 6,
        """The amount of clumps created.

        The actual number of clumps is equal to
        `surfaces / clump_max_area * clump_number`.
        """),
    Opt('clump_ceil', False,
        """Apply clumping to ceilings as well.
        """),
    Opt('clump_floor', False,
        """Apply clumping to floors as well.
        """),

    # Default to the origin of the elevator instance - that's likely to
    # be enclosed
    Opt('music_location_sp', Vec(-2000, 2000, 0),
        """The location of music entities in SP.

        The default is the location of the entry elevator instance.
        """),
    Opt('music_location_coop', Vec(-2000, -2000, 0),
        """The location of music entities in Coop.

        The default is the location of the disassembly room instance.
        """),
    # Instance used for pti_ents
    Opt('global_pti_ents', "instances/BEE2/global_pti_ents.vmf",
        """The instance used for `global_pti_ents`.

        This shouldn't need to be changed.
        """),
    
    Opt('global_pti_ents_loc', Vec(-2400, -2800, 0),
        """Location of global_pti_ents.

        The default pos is next to `arrival_departure_ents`.
        Note that many other entities are added at this point, since it's
        sealed from the void.
        """),

    Opt('model_changer_loc', Vec(-2400, -2800, -256),
        """Location of the model changer instance (if used).
        """),

    ######
    # The following are set by the BEE2.4 app automatically:

    Opt('bee2_loc', TYPE.STR,
        """(Automatic) The location of the BEE2 application.
        """),
    Opt('game_id', "620",
        """(Automatic) The game's steam ID.
        """),
    Opt('music_id', "<NONE>",
        """The ID of the selected music.
        """),
    Opt('music_instance', TYPE.STR,
        """The instance for the chosen music.
        """),
    Opt('music_soundscript', TYPE.STR,
        """The soundscript for the chosen music.
        """),
    Opt('music_looplen', 0,
        """If set, re-trigger music after this number of seconds.
        """),
    Opt('elev_type', "RAND",
        """What type of elevator script to use:

        This should be set to one of `RAND`, `FORCE`, `NONE` or `BSOD`
        """),
    Opt('elev_horiz', TYPE.STR,
        """The horizontal elevator video to use.
        """),
    Opt('elev_vert', TYPE.STR,
        """The vertical elevator video to use.
        """),
    Opt('voice_id', "<NONE>",
        """The ID of the selected voice pack.
        """),
    Opt('voice_char', TYPE.STR,
        """Comma-separated list of characters in the pack.
        """),
    Opt('cave_port_skin', TYPE.INT,
        """If a Cave map, indicate which portrait to use.
        
        * 0: 50's Cave
        * 1: 80's Cave
        * 2: 70's Cave 
        * 3: 70's Cave with Caroline
        """),

    Opt('voice_studio_inst', TYPE.STR,
        """Instance to use for monitor backdrop.
        """),
    Opt('voice_studio_inter_chance', 0.0,
        """Chance to switch to the voice character.
        """),
    Opt('voice_studio_cam_loc', Vec(0, 0, 0),
        """Offset for the camera in the studio.
        """),
    Opt('voice_studio_cam_pitch', 0.0,
        """Pitch direction of the camera.
        """),
    Opt('voice_studio_cam_yaw', 0.0,
        """Yaw direction of the camera.
        """),
    Opt('voice_studio_actor', TYPE.STR,
        """Indicates that an actor is in the instance.

        If set, no bullseye is output with this name in voicelines.
        """),
]

TEX_DEFAULTS = [
    # TODO: remove these..
    Tex('black', 'wall', consts.BlackPan.BLACK_1x1),
    Tex('white', 'wall', consts.WhitePan.WHITE_2x1),


    Tex('black', 'floor', consts.BlackPan.BLACK_FLOOR),  # 4x4
    Tex('black', 'floor_2x2', fallback='black.2x2'),
    Tex('black', 'floor_1x1', fallback='black.1x1', add=[
        'black.floor_2x2', 'black.floor',
    ]),
    Tex('black', 'ceiling', consts.BlackPan.BLACK_FLOOR),
    Tex('black', 'ceiling_2x2', fallback='black.2x2'),
    Tex('black', 'ceiling_1x1', fallback='black.1x1', add=[
        'black.ceiling_2x2', 'ceiling.floor',
    ]),
    Tex('black', '1x1', consts.BlackPan.BLACK_1x1, add=[
        'black.2x1', 'black.2x2', 'black.4x4',
    ]),
    Tex('black', '2x1', consts.BlackPan.BLACK_2x1),
    Tex('black', '2x2', consts.BlackPan.BLACK_2x2),
    Tex('black', '4x4', consts.BlackPan.BLACK_4x4),
    Tex('black', 'bullseye_floor'),
    Tex('black', 'bullseye_wall', fallback='white.bullseye_floor'),
    Tex('black', 'bullseye_ceiling', fallback='white.bullseye_floor'),

    Tex('white', 'floor', consts.WhitePan.WHITE_FLOOR),  # 4x4
    Tex('white', 'floor_2x2', fallback='white.2x2'),
    Tex('white', 'floor_1x1', fallback='white.1x1', add=[
        'white.floor_2x2', 'white.floor',
    ]),
    Tex('white', 'ceiling', consts.WhitePan.WHITE_4x4),
    Tex('white', 'ceiling_2x2', fallback='white.2x2'),
    Tex('white', 'ceiling_1x1', fallback='white.1x1', add=[
        'white.ceiling_2x2', 'white.ceiling',
    ]),
    Tex('white', '1x1', consts.WhitePan.WHITE_1x1, add=[
        'white.2x1', 'white.2x2', 'white.4x4',
    ]),
    Tex('white', '2x1', consts.WhitePan.WHITE_2x1),
    Tex('white', '2x2', consts.WhitePan.WHITE_2x2),
    Tex('white', '4x4', consts.WhitePan.WHITE_4x4),
    Tex('white', 'bullseye_floor'),
    Tex('white', 'bullseye_wall', fallback='white.bullseye_floor'),
    Tex('white', 'bullseye_ceiling', fallback='white.bullseye_floor'),

    Tex('overlay', 'exit', consts.Signage.EXIT),
    Tex('overlay', 'arrow', consts.Signage.ARROW),
    Tex('overlay', 'dot', consts.Signage.SHAPE_DOT),
    Tex('overlay', 'moon', consts.Signage.SHAPE_MOON),
    Tex('overlay', 'triangle', consts.Signage.SHAPE_TRIANGLE),
    Tex('overlay', 'cross', consts.Signage.SHAPE_CROSS),
    Tex('overlay', 'square', consts.Signage.SHAPE_SQUARE),
    Tex('overlay', 'circle', consts.Signage.SHAPE_CIRCLE),
    Tex('overlay', 'sine', consts.Signage.SHAPE_SINE),
    Tex('overlay', 'slash', consts.Signage.SHAPE_SLASH),
    Tex('overlay', 'star', consts.Signage.SHAPE_STAR),
    Tex('overlay', 'wavy', consts.Signage.SHAPE_WAVY),

    # Special additional scale information...
    Tex('overlay', 'antline', '0.25|' + consts.Antlines.STRAIGHT),
    Tex('overlay', 'antlinecorner', '1|' + consts.Antlines.CORNER),

    # This is for the P1 style, where antlines use different textures
    # on the floor and wall.
    # We just use the regular version if unset.
    Tex('overlay', 'antlinecornerfloor'),
    Tex('overlay', 'antlinefloor'),

    # Broken version of antlines
    Tex('overlay', 'antlinebroken'),
    Tex('overlay', 'antlinebrokencorner'),
    Tex('overlay', 'antlinebrokenfloor'),
    Tex('overlay', 'antlinebrokenfloorcorner'),


    Tex('special', 'behind', consts.Special.BACKPANELS_CHEAP),
    Tex('special', 'pedestalside', consts.Special.PED_SIDE),
    Tex('special', 'edge', consts.Special.SQUAREBEAMS),
    Tex('special', 'edge_special', fallback='special.edge'),
    Tex('special', 'goo', consts.Goo.REFLECTIVE),
    Tex('special', 'goo_cheap', consts.Goo.CHEAP),
    Tex('special', 'glass', consts.Special.GLASS),
    Tex('special', 'grating', consts.Special.GRATING),
    Tex('special', 'laserfield', consts.Special.LASERFIELD),
    Tex('special', 'sky', "sky_black"),

    # These replacements are deactivated when unset
    Tex('special', 'white'),
    Tex('special', 'black'),
    Tex('special', 'white_wall', fallback='special.white'),
    Tex('special', 'black_wall', fallback='special.black'),
    Tex('special', 'white_gap', fallback='white.4x4'),
    Tex('special', 'black_gap', fallback='black.4x4'),

    Tex('special', 'goo_wall'),
    Tex('special', 'goo_floor', fallback='special.goo_wall'),
    Tex('special', 'fizz_border'),
]
