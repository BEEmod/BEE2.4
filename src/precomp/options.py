"""Manages reading general options from vbsp_config."""
import math
from enum import Enum, EnumMeta

import inspect

from srctools import Property, Vec, parse_vec_str
from BEE2_config import ConfigFile
import srctools.logger

from typing import Union, Tuple, TypeVar, Type, Optional, Iterator, Any, TextIO


LOGGER = srctools.logger.get_logger(__name__)

SETTINGS = {}

ITEM_CONFIG = ConfigFile('item_cust_configs.cfg')


class TYPE(Enum):
    """The types arguments can have."""
    STR = str
    INT = int
    FLOAT = float
    BOOL = bool
    VEC = Vec

    def convert(self, value: str) -> Any:
        """Convert a string to the desired argument type."""
        return self.value(value)
    
TYPE_NAMES = {
    TYPE.STR: 'Text',
    TYPE.INT: 'Whole Number',
    TYPE.FLOAT: 'Decimal Number',
    TYPE.BOOL: 'True/False',
    TYPE.VEC: 'Vector',
}

OptionT = TypeVar('OptionT')


class Opt:
    """A type of option that can be chosen."""
    def __init__(
        self,
        opt_id: str,
        default: Union[TYPE, OptionT],
        doc: str,
        fallback: str=None,
    ) -> None:
        if isinstance(default, TYPE):
            self.type = default
            self.default = None
        else:
            self.type = TYPE(type(default))
            self.default = default
        self.id = opt_id.casefold()
        self.name = opt_id
        self.fallback = fallback
        # Remove indentation, and trailing carriage return
        self.doc = inspect.cleandoc(doc).rstrip().splitlines()
        if fallback is not None:
            self.doc.append(
                'If unset, the default is read from `{}`.'.format(default)
            )


def load(opt_blocks: Iterator[Property]) -> None:
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
            # Pass NaN so we can check if it failed..
            parsed_vals = parse_vec_str(val, math.nan)
            if math.isnan(parsed_vals[0]):
                SETTINGS[opt.id] = opt.default
            else:
                SETTINGS[opt.id] = Vec(*parsed_vals)
        elif opt.type is TYPE.BOOL:
            SETTINGS[opt.id] = srctools.conv_bool(val, opt.default)
        else:  # int, float, str - no special handling...
            try:
                SETTINGS[opt.id] = opt.type.convert(val)
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


def set_opt(opt_name: str, value: str) -> None:
    """Set an option to a specific value."""
    folded_name = opt_name.casefold()
    for opt in DEFAULTS:
        if folded_name == opt.id:
            break
    else:
        LOGGER.warning('Invalid option name "{}"!', opt_name)
        return

    if opt.type is TYPE.VEC:
        # Pass nones so we can check if it failed..
        parsed_vals = parse_vec_str(value, x=None)
        if parsed_vals[0] is None:
            return
        SETTINGS[opt.id] = Vec(*parsed_vals)
    elif opt.type is TYPE.BOOL:
        SETTINGS[opt.id] = srctools.conv_bool(value, SETTINGS[opt.id])
    else:  # int, float, str - no special handling...
        try:
            SETTINGS[opt.id] = opt.type.convert(value)
        except (ValueError, TypeError):
            pass


def get(expected_type: Type[OptionT], name: str) -> Optional[OptionT]:
    """Get the given option. 
    expected_type should be the class of the value that's expected.
    The value can be None if unset.

    If expected_type is an Enum, this will be used to convert the output.
    If it fails, a warning is produced and the first value in the enum is
    returned.
    """
    try:
        val = SETTINGS[name.casefold()]
    except KeyError:
        raise TypeError('Option "{}" does not exist!'.format(name)) from None

    if val is None:
        return None

    if isinstance(expected_type, EnumMeta):
        enum_type = expected_type
        expected_type = str
    else:
        enum_type = None
        
    # Don't allow subclasses (bool/int)
    if type(val) is not expected_type:
        raise ValueError('Option "{}" is {} (expected {})'.format(
            name,
            type(val),
            expected_type,
        ))

    if enum_type is not None:
        try:
            return enum_type(val)
        except ValueError:
            LOGGER.warning(
                'Option "{}" is not a valid value. '
                'Allowed values are:\n{}',
                name,
                '\n'.join([mem.value for mem in enum_type])
            )
            return next(iter(enum_type))

    # Vec is mutable, don't allow modifying the original.
    if expected_type is Vec:
        return val.copy()
    else:
        return val


def get_itemconf(
    name: Union[str, Tuple[str, str]],
    default: Optional[OptionT],
    timer_delay: int=None,
) -> Optional[OptionT]:
    """Get an itemconfig value.

    The name should be an 'ID:Section', or a tuple of the same.
    The type of the default sets what value it will be converted to.
    None returns the string, or None if not present.
    If set, timer_value is the value used for the timer.
    """
    if name == '':
        return default

    try:
        if isinstance(name, tuple):
            group_id, wid_id = name
        else:
            group_id, wid_id = name.split(':')
    except ValueError:
        LOGGER.warning('Invalid item config: {!r}!', name)
        return default

    wid_id = wid_id.casefold()

    if timer_delay is not None:
        if timer_delay < 3 or timer_delay > 30:
            wid_id += '_inf'
        else:
            wid_id += '_{}'.format(timer_delay)

    value = ITEM_CONFIG.get_val(group_id, wid_id, '')
    if not value:
        return default

    if isinstance(default, str) or default is None:
        return value
    elif isinstance(default, Vec):
        return Vec.from_str(value, default.x, default.y, default.z)
    elif isinstance(default, bool):
        return srctools.conv_bool(value, default)
    elif isinstance(default, float):
        return srctools.conv_int(value, default)
    elif isinstance(default, int):
        return srctools.conv_int(value, default)
    else:
        raise TypeError('Invalid default type "{}"!'.format(type(default).__name__))


INFO_DUMP_FORMAT = """\
## `{id}`{default} ({type})
{desc}

"""

DOC_HEADER = '''\
<!-- Don't edit. This is generated from text in the compiler code. -->

# VBSP_config Options List

This is a list of all current options for the config.
'''


def dump_info(file: TextIO) -> None:
    """Create the wiki page for item options, given a file to write to."""
    print(DOC_HEADER, file=file)
    
    for opt in DEFAULTS:
        if opt.default is None:
            default = ''
        elif type(opt.default) is Vec:
            default = '(`' + opt.default.join(' ') + '`)'
        else:
            default = ' = `' + repr(opt.default) + '`'
        file.write(INFO_DUMP_FORMAT.format(
            id=opt.name, 
            default=default,
            type=TYPE_NAMES[opt.type],
            desc='\n'.join(opt.doc),
        ))

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
    Opt('remove_exit_signs', False,
        """Remove the exit sign overlays for singleplayer.
        """),

    Opt('_tiling_template_', '__TILING_TEMPLATE__',
        """Change the template used for generating brushwork. 
        
        If changing this use caution and only modify texture orientations.
        DO NOT change brush shapes or positions!
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

    Opt('force_brush_reflect', False,
        """Force fast reflections on func_brushes.
        """),

    Opt('flip_sound_start', "World.a3JumpIntroRotatingPanelTravel",
        """Set the starting sound for Flip Panel brushes.
        """),
    Opt('flip_sound_stop', "World.a3JumpIntroRotatingPanelArrive",
        """Set the stopping sound for Flip Panel brushes.
        """),

    Opt('static_pan_thickness', 2,
        """Thickness of static angled panel brushes. 
        
        Must be either 2, 4 or 8.
        """),
    # If set this is used.
    Opt('dynamic_pan_temp', TYPE.STR,
        """If set, replace panel func_brushes with this.

        The top texture should be set to `black_wall_metal_002c`.
        """),
    Opt('dynamic_pan_parent', "model_arms,panel_attach",
        """The local name that the panel func_brush should parent to.
        Adding the attachment name to the parent after a comma
        automatically sets the attachment point for the brush.
        """),
    Opt('dynamic_pan_thickness', 2,
        """Thickness of moveable angled panel brushes. 
        
        Must be either 2, 4 or 8.
        """),
    Opt('dynamic_pan_nodraw', False,
        """If set, apply nodraw to the side and bottom of dynamic 
        angled panels.
        """),

    Opt('ind_pan_check_switching', 'custom',
        """Specify the type of switching behaviour used in the instance.
        
        This can allow optimising control of antlines. The $indicator_name
        fixup value should be used for the names of overlays. If the option is
        set to 'internal', one instance contains the toggle/panel entity. If it 
        is set to 'external', one is generated for the instance(s). If set to 
        'custom' (default), no optimisation is done (other than skipping the
        proxy).
        """),

    Opt('ind_pan_timer_switching', 'custom',
        """Specify the type of switching behaviour used in the instance.
        
        This can allow optimising control of antlines. The $indicator_name
        fixup value should be used for the names of overlays. If the option is
        set to 'internal', one instance contains the toggle/panel entity. If it 
        is set to 'external', one is generated for the instance(s). If set to 
        'custom' (default), no optimisation is done (other than skipping the
        proxy).
        """),

    Opt('timer_sound', 'Portal.room1_TickTock',
        """The soundscript used for timer tick-tock sounds. 
        
        Re-played every second, so it should not loop."""),

    Opt('timer_sound_cc', TYPE.STR,
        """Closed caption soundscript for tick-tock sounds.
        
        We mimic this soundscript when `timer_sound` is played.
        Set to "" to disable adding additional closed captions. 
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
    Opt('signExitInst', TYPE.STR,
        """Use an instance for a double exit sign instead of overlays.
        
        The instance is placed at the midpoint of the two overlays, and two vars
        are set:
        - $orient is set to "horizontal" or "vertical" to indicate if the pair
          is positioned horizontally or vertically.
        - $arrow is set to "north", "south", "east" or "west" to indicate the 
          direction the arrow should point relative to the sign.
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

    Opt('glass_hole_temp', TYPE.STR,
        """Template used to generate glass/grating holes. This should have 
        'large' and 'small' visgroup sections. It should range from x=60-64.
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
    Opt('glass_template', 'BEE2_GLASS_TEMPLATE',
        """A template for rotation and scaling of glass."""),
    Opt('grating_template', 'BEE2_GRATING_TEMPLATE',
        """A template for rotation and scaling of grates."""),

    Opt('goo_wall_scale_temp', TYPE.STR,
        """A template for rotation and scaling for `goo_wall` textures.

        It should be a single brush cube - the wall is set to the same
        rotation as the matching side. (The bottom is ignored).
        """),
    Opt('generate_tidelines', False,
        """Generate tideline overlays around the outside of goo pits.
        """),

    Opt('glass_floorbeam_temp', TYPE.STR,
        """Template for beams in the middle of large glass floors.

        The template should be two brushes for the texture scaling.
        """),
    Opt('glass_floorbeam_sep', 2,
        """Number of blocks between beams.
        """),
    Opt('glass_hole_size_small', 32.0,
        """Size of the small glass hole. 
        
        This is used for glass floor beams.
        """),
    Opt('glass_hole_size_large', 160.0,
        """Size of the large glass hole. 
        
        This is used for glass floor beams.
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

    # Instance used for pti_ents
    Opt('global_pti_ents', "instances/bee2/global_pti_ents.vmf",
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

    Opt('global_ents_loc', Vec(-2400, 0, 0),
        """Location of global entities.

        A 128x128 room is added there, and logic ents are added inside.
        """),

    ######
    # The following are set by the BEE2.4 app automatically:

    Opt('dev_mode', False,
        """Whether 'development mode' is enabled in the app.
        
        This enables extra outputs for assisting with package development.
        """),
    Opt('game_id', "620",
        """(Automatic) The game's steam ID.
        """),
    Opt('music_instance', TYPE.STR,
        """The instance for the chosen music.
        """),
    Opt('music_looplen', 0,
        """If set, re-trigger music after this number of seconds.
        """),
    Opt('music_sync_tbeam', False,
        """If set, funnel music syncs with the main track.
        """),
    Opt('skybox', 'sky_black',
        """The skybox name to use for the map.
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
    Opt('voice_studio_should_shoot', False,
        """Should turrets shoot at this character when shown?
        """),
]
