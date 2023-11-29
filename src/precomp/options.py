"""Manages reading general options from vbsp_config."""
from typing import Dict, Generic, Iterator, Optional, TextIO, Tuple, Type, TypeVar, Union
from enum import Enum
import inspect
import math

from srctools import Keyvalues, Vec, parse_vec_str
import srctools.logger

from BEE2_config import ConfigFile


LOGGER = srctools.logger.get_logger(__name__)
SETTINGS: Dict[str, Union[str, int, float, bool, Vec, None]] = {}
ITEM_CONFIG = ConfigFile('item_cust_configs.cfg')


TYPE_NAMES = {
    str: 'Text',
    int: 'Whole Number',
    float: 'Decimal Number',
    bool: 'True/False',
    Vec: 'Vector',
}

EnumT = TypeVar('EnumT', bound=Enum)
OptionT = TypeVar('OptionT', bound=Union[str, int, float, bool, Vec])


class Opt(Generic[OptionT]):
    """A type of option that can be chosen, which may also be unset."""
    def __init__(
        self,
        opt_id: str,
        kind: Type[OptionT],
        doc: str,
        fallback: Optional[str] =None,
        hidden: bool = False,
    ) -> None:
        self.type = kind
        self.id = opt_id.casefold()
        self.name = opt_id
        self.fallback = fallback
        self.hidden = hidden
        # Remove indentation, and trailing carriage return
        self.doc = inspect.cleandoc(doc).rstrip().splitlines()
        if fallback is not None:
            self.doc.append(f'If unset, the default is read from `{fallback}`.')

    @classmethod
    def string_or_none(
        cls, opt_id: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'Opt[str]':
        """A string option, which can be unset."""
        return Opt(opt_id, str, doc, fallback, hidden)

    @classmethod
    def int_or_none(
        cls, opt_id: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'Opt[int]':
        """An integer option, which can be unset."""
        return Opt(opt_id, int, doc, fallback, hidden)

    @classmethod
    def float_or_none(
        cls, opt_id: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'Opt[float]':
        """A float option, which can be unset."""
        return Opt(opt_id, float, doc, fallback, hidden)

    @classmethod
    def bool_or_none(
        cls, opt_id: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'Opt[bool]':
        """A boolean option, which can be unset."""
        return Opt(opt_id, bool, doc, fallback, hidden)

    @classmethod
    def vec_or_none(
        cls, opt_id: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'Opt[Vec]':
        """A boolean option, which can be unset."""
        return Opt(opt_id, Vec, doc, fallback, hidden)

    @classmethod
    def string(
        cls, opt_id: str, default: str, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'OptWithDefault[str]':
        """A string option, with a default value."""
        return OptWithDefault(opt_id, default, doc, fallback, hidden)

    @classmethod
    def integer(
        cls, opt_id: str, default: int, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'OptWithDefault[int]':
        """An integer option, with a default value."""
        return OptWithDefault(opt_id, default, doc, fallback, hidden)

    @classmethod
    def float_num(
        cls, opt_id: str, default: float, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'OptWithDefault[float]':
        """A float option, with a default value."""
        return OptWithDefault(opt_id, default, doc, fallback, hidden)

    @classmethod
    def boolean(
        cls, opt_id: str, default: bool, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'OptWithDefault[bool]':
        """A bool option, with a default value."""
        return OptWithDefault(opt_id, default, doc, fallback, hidden)

    @classmethod
    def vector(
        cls, opt_id: str, default: Vec, doc: str,
        *,
        fallback: Optional[str] = None,
        hidden: bool = False,
    ) -> 'OptWithDefault[Vec]':
        """A vector option, with a default value."""
        return OptWithDefault(opt_id, default, doc, fallback, hidden)

    def __call__(self) -> Optional[OptionT]:
        """Get the value of the option. The value can be none if it was never set."""
        try:
            val = SETTINGS[self.id]
        except KeyError:
            raise TypeError(f'Option "{self.name}" does not exist!') from None

        if val is None:
            return None

        # Vec is mutable, don't allow modifying the original.
        if isinstance(val, Vec):
            val = val.copy()

        assert self.type is type(val)
        return val

    def as_enum(self: 'Opt[str]', enum: Type[EnumT]) -> EnumT:
        """Get an option, constraining it to an enumeration.

        If it fails, a warning is produced and the first value in the enum is returned.
        """
        value = self()
        try:
            return enum(value)
        except ValueError:
            LOGGER.warning(
                'Option "{}" was set to an invalid value "{}". '
                'Allowed values are:\n{}',
                self.name, value,
                '\n'.join([mem.value for mem in enum])
            )
            return next(iter(enum))


class OptWithDefault(Opt[OptionT], Generic[OptionT]):
    """A type of option that can be chosen, which has a default (and so cannot be None)."""
    def __init__(
        self,
        opt_id: str,
        default: OptionT,
        doc: str,
        fallback: Optional[str] =None,
        hidden: bool = False,
    ) -> None:
        super().__init__(opt_id, type(default), doc, fallback, hidden)
        self.default = default

    def __call__(self) -> OptionT:
        """Get the value of the option. This returns the default if not set"""
        result = super().__call__()
        if result is not None:
            return result
        elif isinstance(self.default, Vec):
            # self.default == Vec & OptionT
            return self.default.copy()  # type: ignore[return-value]
        else:
            return self.default


def load(opt_blocks: Iterator[Keyvalues]) -> None:
    """Read settings from the given property block."""
    SETTINGS.clear()
    set_vals: Dict[str, str] = {}
    for opt_block in opt_blocks:
        for prop in opt_block:
            set_vals[prop.name] = prop.value

    options = {opt.id: opt for opt in _ALL_OPTIONS}
    if len(options) != len(_ALL_OPTIONS):
        from collections import Counter

        # Find ids used more than once..
        raise Exception('Duplicate option(s)! ({})'.format(', '.join(
            k for k, v in
            Counter(opt.id for opt in _ALL_OPTIONS).items()
            if v > 1
        )))

    fallback_opts = []

    for opt in _ALL_OPTIONS:
        if isinstance(opt, OptWithDefault):
            default = opt.default
        else:
            default = None

        try:
            val = set_vals.pop(opt.id)
        except KeyError:
            if opt.fallback is not None:
                fallback_opts.append(opt)
                assert opt.fallback in options, 'Invalid fallback in ' + opt.id
            else:
                SETTINGS[opt.id] = default
            continue

        if opt.type is Vec:
            # Pass NaN, so we can check if it failed...
            parsed_vals = parse_vec_str(val, math.nan)
            if math.isnan(parsed_vals[0]):
                SETTINGS[opt.id] = default
            else:
                SETTINGS[opt.id] = Vec(*parsed_vals)
        elif opt.type is bool:
            SETTINGS[opt.id] = srctools.conv_bool(val, default)
        else:  # int, float, str - no special handling...
            try:
                SETTINGS[opt.id] = opt.type(val)
            except (ValueError, TypeError):
                SETTINGS[opt.id] = default

    for opt in fallback_opts:
        try:
            SETTINGS[opt.id] = SETTINGS[opt.fallback]
        except KeyError:
            raise Exception(f'Bad fallback for "{opt.id}"!')
        # Check they have the same type.
        assert opt.type is options[opt.fallback].type

    if set_vals:
        LOGGER.warning('Extra config options: {}', set_vals)


def set_opt(opt_name: str, value: str) -> None:
    """Set an option to a specific value."""
    folded_name = opt_name.casefold()
    for opt in _ALL_OPTIONS:
        if folded_name == opt.id:
            break
    else:
        LOGGER.warning('Invalid option name "{}"!', opt_name)
        return

    if opt.type is Vec:
        # Pass nones so we can check if it failed..
        parsed_vals = parse_vec_str(value, x=None)
        if parsed_vals[0] is None:
            return
        SETTINGS[opt.id] = Vec(*parsed_vals)
    elif opt.type is bool:
        SETTINGS[opt.id] = srctools.conv_bool(value, SETTINGS[opt.id])
    else:  # int, float, str - no special handling...
        try:
            SETTINGS[opt.id] = opt.type(value)
        except (ValueError, TypeError):
            pass


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
            wid_id += f'_{timer_delay}'

    value = ITEM_CONFIG.get_val(group_id, wid_id, '')
    if not value:
        return default

    result: Union[str, Vec, bool, float, None]
    if isinstance(default, str) or default is None:
        return value  # type: ignore

    if isinstance(default, Vec):
        result = Vec.from_str(value, default.x, default.y, default.z)
    elif isinstance(default, bool):
        result = srctools.conv_bool(value, default)
    elif isinstance(default, float):
        result = srctools.conv_float(value, default)
    elif isinstance(default, int):
        result = srctools.conv_int(value, default)
    else:
        raise TypeError(f'Invalid default type "{type(default).__name__}"!')

    assert type(result) is type(default), f'{default!r} -> {result!r}'
    return result  # type: ignore


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

    for opt in _ALL_OPTIONS:
        if opt.hidden:
            continue
        if isinstance(opt, OptWithDefault):
            if opt.type is Vec:
                default = '(`' + opt.default.join(' ') + '`)'
            else:
                default = ' = `' + repr(opt.default) + '`'
        else:
            default = ''
        file.write(INFO_DUMP_FORMAT.format(
            id=opt.name,
            default=default,
            type=TYPE_NAMES[opt.type],
            desc='\n'.join(opt.doc),
        ))

GOO_MIST = Opt.boolean(
    'goo_mist', False,
    """Add misty info_particle_systems to goo pits.

    This appears most commonly in Portal 1 maps.
    It can be disabled globally by a style var.
    """)

REMOVE_INFO_LIGHTING = Opt.boolean(
    'remove_info_lighting', False,
    """Remove the glass/grating info_lighting entities.
    This should be used when the border is made of brushes.
    """)

TILING_TEMPLATE = Opt.string(
    '_tiling_template_', '__TILING_TEMPLATE__',
    """Change the template used for generating brushwork. 
    
    If changing this use caution and only modify texture orientations.
    DO NOT change brush shapes or positions!
    """)

ROTATE_EDGE = Opt.boolean(
    'rotate_edge', False,
    """Rotate squarebeams textures 90 degrees.
    """)
RESET_EDGE_OFF = Opt.boolean(
    'reset_edge_off', False,
    """Set the offset of squarebeams to 0.
    """)
EDGE_SCALE = Opt.float_num(
    'edge_scale', 0.15,
    """The scale on squarebeams textures.
    """)
ROTATE_EDGE_SPECIAL = Opt.bool_or_none(
    'rotate_edge_special',
    """Rotate squarebeams textures on angled/flip panels 90 degrees.
    """, fallback='rotate_edge')
RESET_EDGE_OFF_SPECIAL = Opt.bool_or_none(
    'reset_edge_off_special',
    """Set the offset of squarebeams on angled/flip panels to 0.
    """, fallback='reset_edge_off')
EDGE_SCALE_SPECIAL = Opt.float_or_none(
    'edge_scale_special',
    """The scale on angled/flip panel squarebeams textures.
    """, fallback='edge_scale')

TILE_TEXTURE_LOCK = Opt.boolean(
    'tile_texture_lock', True,
    """If disabled, reset offsets for all white/black brushes.

    This makes EmbedFace textures contiguous, for irregular textures.
    """)

FIZZ_BORDER_VERTICAL = Opt.boolean(
    'fizz_border_vertical', False,
    """For fizzler borders, indicate that the texture is vertical.
    """)

FIZZ_BORDER_THICKNESS = Opt.integer(
    'fizz_border_thickness', 8,
    """For fizzler borders, set the width of the generated overlays.
    """)
FIZZ_BORDER_REPEAT = Opt.integer(
    'fizz_border_repeat', 128,
    """For fizzler borders, the distance before the
    texture will repeat again.
    """)

FORCE_BRUSH_REFLECT = Opt.boolean(
    'force_brush_reflect', False,
    """Force fast reflections on func_brushes.
    """)

FLIP_SOUND_START = Opt.string(
    'flip_sound_start', "World.a3JumpIntroRotatingPanelTravel",
    """Set the starting sound for Flip Panel brushes.
    """)
FLIP_SOUND_STOP = Opt.string(
    'flip_sound_stop', "World.a3JumpIntroRotatingPanelArrive",
    """Set the stopping sound for Flip Panel brushes.
    """)

STATIC_PAN_THICKNESS = Opt.integer(
    'static_pan_thickness', 2,
    """Thickness of static angled panel brushes. 
    
    Must be either 2, 4 or 8.
    """)
# If set this is used.
DYNAMIC_PAN_TEMP = Opt.string_or_none(
    'dynamic_pan_temp',
    """If set, replace panel func_brushes with this.

    The top texture should be set to `black_wall_metal_002c`.
    """)
DYNAMIC_PAN_PARENT = Opt.string(
    'dynamic_pan_parent', "model_arms,panel_attach",
    """The local name that the panel func_brush should parent to.
    Adding the attachment name to the parent after a comma
    automatically sets the attachment point for the brush.
    """)
DYNAMIC_PAN_THICKNESS = Opt.integer(
    'dynamic_pan_thickness', 2,
    """Thickness of moveable angled panel brushes. 
    
    Must be either 2, 4 or 8.
    """)
DYNAMIC_PAN_NODRAW = Opt.boolean(
    'dynamic_pan_nodraw', False,
    """If set, apply nodraw to the side and bottom of dynamic 
    angled panels.
    """)

IND_PAN_CHECK_SWITCHING = Opt.string(
    'ind_pan_check_switching', 'custom',
    """Specify the type of switching behaviour used in the instance.
    
    This can allow optimising control of antlines. The $indicator_name
    fixup value should be used for the names of overlays. If the option is
    set to 'internal', one instance contains the toggle/panel entity. If it 
    is set to 'external', one is generated for the instance(s). If set to 
    'custom' (default), no optimisation is done (other than skipping the
    proxy).
    """)

IND_PAN_TIMER_SWITCHING = Opt.string(
    'ind_pan_timer_switching', 'custom',
    """Specify the type of switching behaviour used in the instance.
    
    This can allow optimising control of antlines. The $indicator_name
    fixup value should be used for the names of overlays. If the option is
    set to 'internal', one instance contains the toggle/panel entity. If it 
    is set to 'external', one is generated for the instance(s). If set to 
    'custom' (default), no optimisation is done (other than skipping the
    proxy).
    """)

TIMER_SOUND = Opt.string(
    'timer_sound', 'Portal.room1_TickTock',
    """The soundscript used for timer tick-tock sounds. 
    
    Re-played every second, so it should not loop.""")

TIMER_SOUND_CC = Opt.string_or_none(
    'timer_sound_cc',
    """Closed caption soundscript for tick-tock sounds.
    
    We mimic this soundscript when `timer_sound` is played.
    Set to "" to disable adding additional closed captions. 
    """)

SIGN_INST = Opt.string_or_none(
    'signInst',
    """Adds this instance on all the signs.

    The origin is positioned on the surface.
    """)
SIGN_SIZE = Opt.integer(
    'signSize', 32,
    """Set the size of the sign overlays.
    """)
SIGN_PACK = Opt.string_or_none(
    'signPack',
    """Packlist to use when `signInst` is added.
    """)
SIGN_EXIT_INST = Opt.string_or_none(
    'signExitInst',
    """Use an instance for a double exit sign instead of overlays.
    
    The instance is placed at the midpoint of the two overlays, and two vars
    are set:
    - $orient is set to "horizontal" or "vertical" to indicate if the pair
      is positioned horizontally or vertically.
    - $arrow is set to "north", "south", "east" or "west" to indicate the 
      direction the arrow should point relative to the sign.
    """)
REMOVE_EXIT_SIGNS = Opt.boolean(
    'remove_exit_signs', False,
    """Remove the exit sign overlays for singleplayer.
    
    This does not apply if signExitInst is set and the overlays are next to
    each other.
    """)
REMOVE_EXIT_SIGNS_DUAL = Opt.boolean('remove_exit_signs_dual', True,
    """Remove the exit sign overlays if signExitInst is set and they're 
    next to each other.
    """)

BROKEN_ANTLINE_CHANCE = Opt.float_num(
    'broken_antline_chance', 0.0,
    """The chance an antline will be 'broken'.

    For each antline, this is checked. If true, `broken_antline_distance`
    at most become broken.
    """)
BROKEN_ANTLINE_DISTANCE = Opt.integer(
    'broken_antline_distance', 3,
    """The maximum distance of a single broken section.
    """)
GOO_SCALE = Opt.float_num(
    'goo_scale', 1.0,
    """Scale of the goo textures.
    """)

PIT_BLEND_LIGHT = Opt.string_or_none(
    'pit_blend_light',
    """Color of lights in bottomless pits.

    These are added at in the skybox and in the map, to blend together the
    lighting. It should be set to the ambient light color.
    """)

SUPERPOSITION_GHOST_ALPHA = Opt.integer(
    'superposition_ghost_alpha', 50,
    """The amount of transparency to give Quantum Superposition Ghost Cubes.
    
    Ranges from 0-255.
    """)

GLASS_HOLE_TEMP = Opt.string_or_none(
    'glass_hole_temp',
    """Template used to generate glass/grating holes. This should have 
    'large' and 'small' visgroup sections. It should range from x=60-64.
    """)

# Packlists for glass and gratings
GLASS_PACK = Opt.string(
    'glass_pack', "PACK_PLAYER_CLIP_GLASS",
    """Packlist for glass clips.

    This is used for `glass_clip`.
    """)
GRATING_PACK = Opt.string(
    'grating_pack', "PACK_PLAYER_CLIP_GRATE",
    """Packlist for grating clips.

    This is used for `grating_clip`.
    """)
GLASS_TEMPLATE = Opt.string(
    'glass_template', 'BEE2_GLASS_TEMPLATE',
    """A template for rotation and scaling of glass.""")
GRATING_TEMPLATE= Opt.string(
    'grating_template', 'BEE2_GRATING_TEMPLATE',
    """A template for rotation and scaling of grates.""")

GOO_WALL_SCALE_TEMP = Opt.string_or_none('goo_wall_scale_temp',
    """A template for rotation and scaling for `goo_wall` textures.

    It should be a single brush cube - the wall is set to the same
    rotation as the matching side. (The bottom is ignored).
    """)
GENERATE_TIDELINES = Opt.boolean('generate_tidelines', False,
    """Generate tideline overlays around the outside of goo pits.
    
    The material used is configured by `overlays.tideline`.
    """)

GLASS_FLOORBEAM_TEMP = Opt.string_or_none(
    'glass_floorbeam_temp',
    """Template for beams in the middle of large glass floors.

    The template must be a single brush, aligned on the X axis.
    """)
GLASS_FLOORBEAM_SEP = Opt.integer(
    'glass_floorbeam_sep', 2,
    """Number of blocks between beams.
    """)
GLASS_HOLE_SIZE_SMALL = Opt.float_num(
    'glass_hole_size_small', 32.0,
    """Size of the small glass hole. 
    
    This is used for glass floor beams.
    """)
GLASS_HOLE_SIZE_LARGE = Opt.float_num(
    'glass_hole_size_large', 160.0,
    """Size of the large glass hole. 
    
    This is used for glass floor beams.
    """)

CLUMP_WALL_TEX = Opt.boolean(
    'clump_wall_tex', False,
    """Use the clumping wall algorithm.

    This creates groups of the same texture.
    `clump_size`, `clump_width`, and `clump_number` must be set.
    """)
CLUMP_SIZE = Opt.integer(
    'clump_size', 4,
    """The maximum length of a clump.

    Clumps are rectangular, and this indicates the long dimension.
    """)
CLUMP_WIDTH = Opt.integer(
    'clump_width', 2,
    """The maximum width of a clump.

    Clumps are rectangular, and this indicates the short dimensions.
    """)
CLUMP_NUMBER = Opt.integer(
    'clump_number', 6,
    """The amount of clumps created.

    The actual number of clumps is equal to
    `surfaces / clump_max_area * clump_number`.
    """)
CLUMP_CEIL = Opt.boolean(
    'clump_ceil', False,
    """Apply clumping to ceilings as well.
    """)
CLUMP_FLOOR = Opt.boolean(
    'clump_floor', False,
    """Apply clumping to floors as well.
    """)

# Instance used for pti_ents
GLOBAL_PTI_ENTS = Opt.string(
    'global_pti_ents', "instances/bee2/global_pti_ents.vmf",
    """The instance used for `global_pti_ents`.

    This shouldn't need to be changed.
    """)

GLOBAL_PTI_ENTS_LOC = Opt.vector(
    'global_pti_ents_loc', Vec(-2400, -2800, 0),
    """Location of global_pti_ents.

    The default pos is next to `arrival_departure_ents`.
    Note that many other entities are added at this point, since it's
    sealed from the void.
    """)

MODEL_CHANGER_LOC = Opt.vector(
    'model_changer_loc', Vec(-2400, -2800, -256),
    """Location of the model changer instance (if used).
    """)

GLOBAL_ENTS_LOC = Opt.vector(
    'global_ents_loc', Vec(-2400, 0, 0),
    """Location of global entities.

    A 128x128 room is added there, and logic ents are added inside.
    """)

######
# The following are set by the BEE2.4 app automatically:

DEV_MODE = Opt.boolean(
    'dev_mode', False,
    """(Automatic) Whether 'development mode' is enabled in the app.
    
    This enables extra outputs for assisting with package development.
    """)
GAME_ID = Opt.string(
    'game_id', "620",
    """(Automatic) The game's steam ID.
    """)
MUSIC_INSTANCE = Opt.string_or_none(
    'music_instance',
    """(Automatic) The instance for the chosen music.
    """)
ERROR_TRANSLATIONS = Opt.string(
    'error_translations', '',
    """(Automatic) Set to the `.mo` translation to use for error text."""
    )
MUSIC_LOOPLEN = Opt.integer(
    'music_looplen', 0,
    """(Automatic) If set, re-trigger music after this number of seconds.
    """)
MUSIC_SYNC_TBEAM = Opt.boolean(
    'music_sync_tbeam', False,
    """(Automatic) If set, funnel music syncs with the main track.
    """)
SKYBOX = Opt.string(
    'skybox', 'sky_black',
    """(Automatic) The skybox name to use for the map.
    """)
ELEV_TYPE = Opt.string(
    'elev_type', "RAND",
    """(Automatic) What type of elevator script to use:

    This should be set to one of `RAND`, `FORCE`, `NONE` or `BSOD`
    """)
ELEV_HORIZ = Opt.string_or_none(
    'elev_horiz',
    """(Automatic) The horizontal elevator video to use.
    """)
ELEV_VERT = Opt.string_or_none(
    'elev_vert',
    """(Automatic) The vertical elevator video to use.
    """)
VOICE_ID = Opt.string(
    'voice_id', "<NONE>",
    """(Automatic) The ID of the selected voice pack.
    """)
VOICE_CHAR = Opt.string_or_none(
    'voice_char',
    """(Automatic) Comma-separated list of characters in the pack.
    """)
CAVE_PORT_SKIN = Opt.int_or_none(
    'cave_port_skin',
    """(Automatic) If a Cave map, indicate which portrait to use.
    
    * 0: 50's Cave
    * 1: 80's Cave
    * 2: 70's Cave 
    * 3: 70's Cave with Caroline
    """)

VOICE_STUDIO_INST = Opt.string_or_none(
    'voice_studio_inst',
    """(Automatic) Instance to use for monitor backdrop.
    """)
VOICE_STUDIO_INTER_CHANCE = Opt.float_num(
    'voice_studio_inter_chance', 0.0,
    """(Automatic) Chance to switch to the voice character.
    """)
VOICE_STUDIO_CAM_LOC = Opt.vector(
    'voice_studio_cam_loc', Vec(0, 0, 0),
    """(Automatic) Offset for the camera in the studio.
    """)
VOICE_STUDIO_CAM_PITCH = Opt.float_num(
    'voice_studio_cam_pitch', 0.0,
    """(Automatic) Pitch direction of the camera.
    """)
VOICE_STUDIO_CAM_YAW = Opt.float_num(
    'voice_studio_cam_yaw', 0.0,
    """(Automatic) Yaw direction of the camera.
    """)
VOICE_STUDIO_ACTOR = Opt.string_or_none(
    'voice_studio_actor',
    """(Automatic) Indicates that an actor is in the instance.

    If set, no bullseye is output with this name in voicelines.
    """)
VOICE_STUDIO_SHOULD_SHOOT = Opt.boolean(
    'voice_studio_should_shoot', False,
    """(Automatic) Should turrets shoot at this character when shown?
    """)

_ALL_OPTIONS = [
    opt
    for opt in globals().values()
    if isinstance(opt, Opt)
]
