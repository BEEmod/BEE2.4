"""The different properties defineable for items."""
from __future__ import annotations
from enum import Enum
from typing import Any, Callable, Generic, Sequence, Type, TypeVar

import attrs
from srctools import Angle, bool_as_int, conv_bool, conv_float, conv_int
from typing_extensions import Self

from transtoken import TransToken


ValueT = TypeVar('ValueT')
EnumT = TypeVar('EnumT', bound=Enum)


def _unknown_parse(value: str) -> str:
    """Parse function for unrecognised properties. This way it can also be a sentinel."""
    return value


@attrs.define(eq=False, kw_only=True, getstate_setstate=False)
class ItemPropKind(Generic[ValueT]):
    """A type of property for an item."""
    # Property name for this. This is case-sensitive!
    id: str
    # The translation keyword for this, or BLANK if it shouldn't be visible.
    name: TransToken
    # The instance variable this sets, if any.
    instvar: str
    # All the possible values this can have, if used as a subtype.
    # If not usable, this is a zero-length sequence.
    subtype_values: Sequence[ValueT] = ()
    # If false, don't show on the default selection window.
    allow_user_default: bool = True

    # Functions to parse and export the value.
    parse: Callable[[str], ValueT]
    export: Callable[[ValueT], str]

    @classmethod
    def unknown(cls, prop_id: str) -> ItemPropKind[str]:
        """Create a kind for an unknown property."""
        return ItemPropKind[str](
            id=prop_id,
            name=TransToken.BLANK,
            instvar='',
            parse=_unknown_parse,
            export=str,
            allow_user_default=False,
        )

    @property
    def is_unknown(self) -> bool:
        """Check if this is an unknown property."""
        return self.parse is _unknown_parse

    def __hash__(self) -> int:
        """Allow using as a dict key."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Item properties are compared by ID."""
        if isinstance(other, ItemPropKind):
            return self.id == other.id
        return NotImplemented

    def __reduce__(self) -> str | tuple[object, ...]:
        """Handle pickling specially.

        For known props, we fetch the object by ID.
        For unknown props, we simply recreate.
        This means we don't try pickling the parse/export functions.
        """
        try:
            return _known_to_attr[self]
        except KeyError:
            return (ItemPropKind.unknown, (self.id,))


class ItemProp(Generic[ValueT]):
    """A property for an item."""
    def __init__(
        self,
        kind: ItemPropKind[ValueT],
        default: str,
        index: int,
        allow_user_default: bool,
        desc: TransToken,
    ) -> None:
        self.kind = kind
        self.default = kind.parse(default)
        self.index = index
        # The item author and kind must both allow alteration, and it also must not be the
        # SubtypeProperty.
        self.allow_user_default = kind.allow_user_default and allow_user_default
        self.desc = desc

    def __repr__(self) -> str:
        """Generic repr() for properties."""
        return f'{self.kind.id}({self.default!r})'

    def __hash__(self) -> int:
        return hash((self.kind.id, self.default))

    def export(self) -> str:
        """Generate the string to write into a file."""
        return self.kind.export(self.default)

    def parse_value(self, value: str) -> ValueT:
        """Parse string form into the appropriate value."""
        return self.kind.parse(value)


# ID -> class
PROP_TYPES: dict[str, ItemPropKind[Any]] = {}
# class to name in this module, for pickling.
_known_to_attr: dict[ItemPropKind[Any], str] = {}


def bool_prop(
    id: str,
    name: TransToken,
    instvar: str,
    allow_user_default: bool = True,
) -> ItemPropKind[bool]:
    """Create a boolean-type property."""
    return ItemPropKind(
        parse=conv_bool,
        export=bool_as_int,
        subtype_values=(False, True),

        id=id,
        name=name,
        instvar=instvar,
        allow_user_default=allow_user_default,
    )


def enum_prop(
    enum: Type[EnumT],
    id: str,
    name: TransToken,
    instvar: str,
    allow_user_default: bool = True,
) -> ItemPropKind[EnumT]:
    """Create a property with specific values."""
    def parse(value: str) -> EnumT:
        """Try parsing as the name first, then try the value."""
        try:
            return enum[value.upper()]
        except KeyError:
            pass
        return enum(int(value))

    def export(value: EnumT) -> str:
        """The enum exports as its value."""
        return str(value.value)

    return ItemPropKind(
        id=id,
        name=name,
        instvar=instvar,
        allow_user_default=allow_user_default,
        parse=parse,
        export=export,
        subtype_values=list(enum),
    )


# Enumerations for various types.

class PanelAnimation(Enum):
    """Available angles for angled panels."""
    ANGLE_30 = 30
    ANGLE_45 = 45
    ANGLE_60 = 60
    ANGLE_90 = 90

    @classmethod
    def from_anim(cls, anim: str) -> Self:
        """Parse a string matching the ramp_XX_deg_open animation names.

        :raises LookupError: If the string is not a valid animation.
        """
        if anim.startswith('ramp_') and anim.endswith('_deg_open'):
            try:
                return cls(int(anim[5:-9]))
            except KeyError:
                pass
        raise LookupError(anim)

    @property
    def animation(self) -> str:
        """Return the corresponding animation value."""
        return f'ramp_{self.value}_deg_open'


class PaintTypes(Enum):
    """The 5 types of gel that exist."""
    BLUE = BOUNCE = "bounce"
    ORAN = ORANGE = SPEED = "speed"
    WHITE = PORTAL = "portal"
    WATER = CLEANSING = ERASE = "erase"
    GREY = GRAY = REFLECT = "reflect"  # Extra/hacked in.


class PaintFlows(Enum):
    """The different flow amounts paint can have."""
    LIGHT = 0
    MEDIUM = 1
    HEAVY = 2
    DRIP = 3
    BOMB = 4


class CubeTypes(Enum):
    """The different types of cubes."""
    STANDARD = 0
    COMPANION = 1
    REFLECT = 2
    SPHERE = 3
    FRANKEN = 4


class ButtonTypes(Enum):
    """The different types of floor buttons."""
    WEIGHTED = FLOOR = 0
    CUBE = BOX = 1
    SPHERE = BALL = 2


class FizzlerTypes(Enum):
    """The different types of fizzlers."""
    FIZZLER = 0
    LASERFIELD = 1


class GlassTypes(Enum):
    """The different types of glass."""
    GLASS = 0
    GRATING = GRATE = 1


# First all the generic bools.

# Generic Start Enabled
prop_start_enabled = bool_prop(
    id='StartEnabled',
    instvar='$start_enabled',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_enabled'),
)

# Polarity value for Excursion Funnels.
prop_start_reversed = bool_prop(
    id='StartReversed',
    instvar='$start_reversed',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_reversed'),
)

# Starting position for Angled Panels.
prop_start_deployed = bool_prop(
    id='StartDeployed',
    instvar='$start_deployed',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_deployed'),
)

# Specifies if the SP Exit Door starts open or not.
prop_start_open = bool_prop(
    id='StartOpen',
    instvar='$start_open',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_open'),
)

# Specifies if the Coop Exit Door starts locked.
prop_start_locked = bool_prop(
    id='StartLocked',
    instvar='$start_locked',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_coop_exit_starts_locked'),
)

# Specifies if the flip panel starts portalable."""
prop_portalable = bool_prop(
    id='Portalable',
    instvar='$start_deployed',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_portalable'),
)

# For doors, specifies the map mode and therefore which door is used.
prop_is_coop = bool_prop(
    id='CoopDoor',
    instvar='',  # Controls which item is used.
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_coop_puzzle'),
)

# Enables or disables the dropper for Cubes and Paint.
prop_dropper_enabled = bool_prop(
    id='DropperEnabled',
    instvar='',  # Controls which item exports.
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_dropper_enabled'),
)

# For cube droppers, decides if it triggers when the player enters.
# On ITEM_CUBE_DROPPER only, this exports inverted like the name suggests.
prop_auto_drop = bool_prop(
    id='AutoDrop',
    instvar='$disable_autodrop',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_auto_drop_cube'),
)

# For cube droppers, decides if it replaces destroyed cubes.
# On ITEM_CUBE_DROPPER only, this exports inverted like the name suggests.
prop_cube_auto_respawn = bool_prop(
    id='AutoRespawn',
    instvar='$disable_autorespawn',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_auto_respawn_cube'),
)

# A property which turns off some of the cube dropper's clips. This is always disabled.
prop_cube_fall_straight_Down = bool_prop(
    id='ItemFallStraightDown',
    instvar='$item_fall_straight_down',
    name=TransToken.BLANK,  # Not visible
)

# Track Platform prop types:

# Starting state for oscillating Track Platforms
# If non-oscillating, this is disabled.
prop_track_start_active = bool_prop(
    id='StartActive',
    instvar='$start_active',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_rail_start_active'),
)

# The mode for Track Platforms.
prop_track_is_oscillating = bool_prop(
    id='Oscillate',
    instvar='',  # Picks instance
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_rail_oscillate'),
)

# The starting fractional position of Track Platforms.
prop_track_starting_pos = ItemPropKind[float](
    id='StartingPosition',
    instvar='$starting_position',
    parse=conv_float,
    export=str,
    name=TransToken.BLANK,  # Hidden
)


# The distance the Track Platform moves overall.
prop_track_move_distance = ItemPropKind[float](
    id='TravelDistance',
    instvar='$travel_distance',
    parse=conv_float,
    export=str,
    name=TransToken.BLANK,  # Hidden
)

# The speed the Track Platform moves at.
# This is always 100 units/sec.
prop_track_speed = ItemPropKind[float](
    id='Speed',
    # Not really right, but should be about right.
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_paint_type_speed'),
    instvar='$speed',
    parse=conv_float,
    export=str,
)


prop_track_move_direction = ItemPropKind[Angle](
    id='TravelDirection',
    instvar='$travel_direction',
    name=TransToken.BLANK,  # Hidden prop
    parse=Angle.from_str,
    export=str,
)


# Piston Platform:
# 4 T
# 3 |
# 2 |
# 1 |__
# 0
def _parse_pist_lower(value: str) -> int:
    # Bug, previous versions mistakenly wrote rounded floats.
    if value.endswith('.0'):
        value = value[:-2]
    try:
        pos = int(value)
        if 0 <= pos < 4:
            return pos
    except ValueError:
        raise ValueError(f'Invalid position {value}!') from None
    raise ValueError(f'Position {value} not in 0, 1, 2, 3!')


def _parse_pist_upper(value: str) -> int:
    # Bug, previous versions mistakenly wrote rounded floats.
    if value.endswith('.0'):
        value = value[:-2]
    try:
        pos = int(value)
        if 0 < pos <= 4:
            return pos
    except ValueError:
        raise ValueError(f'Invalid position {value}!') from None
    raise ValueError(f'Position {value} not in 1, 2, 3, 4!')


prop_pist_lower = ItemPropKind(
    id='BottomLevel',
    instvar='$bottom_level',
    name=TransToken.BLANK,  # Controlled by the widgets.
    subtype_values=[0, 1, 2, 3],
    parse=_parse_pist_lower,
    export=str,
)
prop_pist_upper = ItemPropKind(
    id='TopLevel',
    instvar='$top_level',
    name=TransToken.BLANK,  # Controlled by the widgets.
    subtype_values=[1, 2, 3, 4],
    parse=_parse_pist_upper,
    export=str,
)
# Determines if the piston begins at the upper or lower point.
prop_pist_start_up = bool_prop(
    id='StartUp',
    instvar='$start_up',
    name=TransToken.BLANK,  # Internal property.
)
# Determines if the piston moves automatically.
prop_pist_auto_trigger = bool_prop(
    id='AutoTrigger',
    instvar='$allow_auto_trigger',
    name=TransToken.BLANK,  # Internal property.
)


# Paint stuff.
def paint_type_prop(
    *order: PaintTypes,
    id: str, instvar: str, name: TransToken,
) -> ItemPropKind[PaintTypes]:
    """There's two paint type properties with different configuration."""
    def parse(value: str) -> PaintTypes:
        """Parse the paint type."""
        try:
            # Allow symbolic names.
            return PaintTypes[value.upper()]
        except KeyError:
            pass

        index = int(value)
        if 0 <= index < 5:
            return order[index]
        raise ValueError(f'{value} is not a valid paint type!') from None

    return ItemPropKind[PaintTypes](
        id=id,
        instvar=instvar,
        name=name,
        subtype_values=order,
        parse=parse,
        export=lambda value: str(order.index(value)),
    )

# The main paint type property, directly specifying each paint type.
prop_paint_type = paint_type_prop(
    PaintTypes.BOUNCE,
    PaintTypes.SPEED,
    PaintTypes.PORTAL,
    PaintTypes.ERASE,
    # This is not actually valid, but it works to get a single custom type.
    PaintTypes.REFLECT,

    id='PaintType',
    instvar='',  # Done through the other props.
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_paint_type'),
)

# An internal property that exports the actual paint type used.
# This matches the engine's paint type indexes.
prop_paint_export_type = paint_type_prop(
    PaintTypes.BOUNCE,
    PaintTypes.REFLECT,
    PaintTypes.SPEED,
    PaintTypes.PORTAL,
    PaintTypes.ERASE,
    id='PaintExportType',
    instvar='$paint_type',
    name=TransToken.BLANK,  # Internal prop.
)


# The amount of gel that drops.
# This actually sets multiple variables:
# - $blobs_per_second
# - $angled_blobs_per_second
# - $streak_angle
# - $ambient_sound
# - $render_mode
# The first is the most "important".
prop_paint_flow_type = enum_prop(
    PaintFlows,
    id='PaintFlowType',
    instvar='$blobs_per_second',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type'),
)


# Specifies if the paint can streak across a surface.
# This actually exports either 0.35 or 0 to the instvar.
prop_paint_allow_streaks = bool_prop(
    id='AllowStreak',
    instvar='$streak_time',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_allow_streak_paint'),
)


def _parse_connection_count(value: str) -> int:
    count = int(value)
    if count < 0:
        raise ValueError('Connection count cannot be negative!')
    return count

prop_connection_count = ItemPropKind[int](
    id='ConnectionCount',
    instvar="$connectioncount",
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_tbeam_activate'),
    parse=_parse_connection_count,
    export=str,
)
# Specific for funnels, tracks the number of polarity-type input items.
prop_connection_count_polarity = ItemPropKind[int](
    id='ConnectionCountPolarity',
    instvar="$connectioncountpolarity",
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_tbeam_polarity'),
    parse=_parse_connection_count,
    export=str,
)


# The Timer Delay property, providing 0-30 second delays."""
def _parse_timer_delay(value: str) -> int:
    time = conv_int(value, 3)
    return max(0, min(30, time))

prop_timer_delay = ItemPropKind[int](
    id="TimerDelay",
    instvar="$timer_delay",
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_timer_delay'),
    subtype_values=range(0, 31),
    parse=_parse_timer_delay,
    export=str,
)

# Specifies if a pedestal button should play timer sounds.
prop_timer_sound = bool_prop(
    id='TimerSound',
    instvar='$timer_sound',
    name=TransToken.BLANK,  # Not visible.
)


# Specifies if a Faith Plate is in straight-up or angled mode.
prop_faith_vertical_alignment = bool_prop(
    id='VerticalAlignment',
    instvar='',  # None!
    name=TransToken.BLANK,  # Not visible.
)

# Stores the Faith Plate's speed, defining the arc height.
prop_faith_speed = ItemPropKind[float](
    id='CatapultSpeed',
    instvar='$catapult_speed',
    name=TransToken.BLANK,  # Not visible.
    parse=conv_float,
    export=str,
)


# Set to the name of the overlay the env_texturetoggle should control.
prop_antline_indicator = ItemPropKind[str](
    id='IndicatorName',
    instvar='$indicator_name',
    name=TransToken.BLANK,  # Inaccessible to users.
    parse=str,
    export=str,
)


# Set on the antline sign items to determine their type.
prop_antline_is_timer = bool_prop(
    id='IsTimer',
    instvar='$is_timer',
    name=TransToken.BLANK,  # Inaccessible to users.
)


# Set on the placement helper instance, always 64.
prop_helper_radius = ItemPropKind[float](
    id='HelperRadius',
    instvar='$helper_radius',
    name=TransToken.BLANK,  # Not visible.
    parse=conv_float,
    export=str,
)


# Set on the placement helper instance, always false.
prop_helper_use_angles = bool_prop(
    id='UseHelperAngles',
    instvar='$use_helper_angles',
    name=TransToken.BLANK,  # Not visible.
)


# Set on the placement helper instance, always false.
prop_helper_force_placement = bool_prop(
    id='ForcePlacement',
    instvar='$force_placement',
    name=TransToken.BLANK,  # Not visible.
)


# Logically would store or produce the name of the target.
# However, this never does anything.
prop_faith_targetname = ItemPropKind[str](
    id='TargetName',
    instvar='',
    parse=str,
    export=str,
    name=TransToken.BLANK,  # Hidden
)


# Differentiates between the two angled panel items, presumably.
# Defaults to 2 always, so the value isn't important.
prop_angled_panel_type = ItemPropKind[str](
    id='AngledPanelType',
    name=TransToken.BLANK,  # Hidden
    instvar='',  # None!
    parse=str,
    export=str,
)


def _parse_angled_panel_anim(value: str) -> PanelAnimation:
    """Parse angled panel animations."""
    orig_value = value
    value = value.casefold()
    # Allow the full anim name or just the degree.
    try:
        return PanelAnimation.from_anim(value)
    except ValueError:
        pass
    ind = int(value)
    if ind < 30:  # If 0-3 use index, if 30/45/60/90 use that
        try:
            return prop_angled_panel_anim.subtype_values[ind]
        except IndexError:
            raise ValueError(f'Unknown animation {orig_value}') from None
    else:
        return PanelAnimation(int(value))

# The angle the panel rises to.
prop_angled_panel_anim = ItemPropKind[PanelAnimation](
    id='AngledPanelAnimation',
    instvar='$animation',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type'),
    subtype_values=list(PanelAnimation),
    parse=_parse_angled_panel_anim,
    export=lambda angle: angle.animation,
)

prop_cube_type = enum_prop(
    CubeTypes,
    id='CubeType',
    instvar='$cubetype',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_cube_type'),
)


prop_button_type = enum_prop(
    ButtonTypes,
    id='ButtonType',
    instvar='',  # Sets instance index.
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_button_type'),
)


prop_fizzler_type = enum_prop(
    FizzlerTypes,
    id='HazardType',
    instvar='$skin',
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_barrier_hazard_type'),
)


prop_glass_type = enum_prop(
    GlassTypes,
    id='BarrierType',
    instvar='',  # Brushes placed only
    name=TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_barrier_type'),
)


# Register everything.
_known_to_attr.update({
    prop: name
    for name, prop in globals().items()
    if isinstance(prop, ItemPropKind)
})
PROP_TYPES.update({
    prop.id.casefold(): prop
    for prop in _known_to_attr.keys()
})
