"""Implement cubes and droppers."""
from __future__ import annotations

from contextlib import suppress
from weakref import WeakKeyDictionary

from enum import Enum
from typing import NamedTuple, MutableMapping

from srctools.vmf import VMF, Entity, EntityFixup, Output
from srctools import EmptyMapping, Property, Vec, Matrix, Angle
import srctools.logger
import attrs

from precomp import brushLoc, options, packing, conditions, connections
from precomp.conditions.globals import precache_model
from precomp.instanceLocs import resolve as resolve_inst
import user_errors


LOGGER = srctools.logger.get_logger(__name__)

COND_MOD_NAME = 'Cubes/Droppers'

# All the types we have loaded
CUBE_TYPES: dict[str, CubeType] = {}
DROPPER_TYPES: dict[str, DropperType] = {}
ADDON_TYPES: dict[str, CubeAddon] = {}

# All the cubes/droppers
PAIRS: list[CubePair] = []
INST_TO_PAIR: MutableMapping[Entity, CubePair] = WeakKeyDictionary()

# Distance from the floor to the bottom of dropperless cubes.
# That's needed for light bridges and things like that.
DROPPERLESS_OFFSET = 22 - 64

# By position.
# These won't overlap - droppers occupy space, and dropperless cubes
# also do. Dropper+cube items only give the dropper.
# We also snap to nearest voxel, to allow cubes to use an offset handle.
CUBE_POS: dict[tuple[float, float, float], CubePair] = {}

# Prevents duplicating different filter entities. A number of different keys are used depending on
# exactly which kind of filter.
CUBE_FILTERS: dict[object, str] = {}

# Max number of ents in a multi filter.
MULTI_FILTER_COUNT = 10

# filter_activator_class entities for weighted_cube and monster_box.
# These are in global_pti_ents.
FILTER_MONST_CLS = '@is_fbox'
FILTER_CUBE_CLS = '@is_mbox'

# The IDs for the default cube types, matched to the $cube_type value.
VALVE_CUBE_IDS = {
    0: 'VALVE_CUBE_STANDARD',
    1: 'VALVE_CUBE_COMPANION',
    2: 'VALVE_CUBE_REFLECTION',
    3: 'VALVE_CUBE_SPHERE',
    6: 'VALVE_CUBE_FRANKEN',
}
# The ItemBoxDropper class does some unusual stuff.
VALVE_DROPPER_ID = 'VITAL_APPARATUS_VENT'

# A cube type of 6 tricks the prop_weighted_cube,
# making it use the default model (set in the model keyvalue).
# This lets us have custom models - since those are saved and
# loaded in the base-entity machinery.
# It's somewhat buggy though, so we use the SetModel method if possible.
CUBE_ID_CUSTOM_MODEL_HACK = '6'


class CubeEntType(Enum):
    """Cube types, as set on prop_weighted_cube.

    This is used to set behaviour and gel skins for items.
    """
    norm = 'WEIGHTED'
    comp = 'COMPANION'
    reflect = 'REFLECTION'
    sphere = 'SPHERE'
    antique = 'ANTIQUE'
    franken = 'FRANKEN'  # prop_monster_box


class CubeVoiceEvents(Enum):
    """Certain dropper events can trigger dialogue."""
    # Replace a cube:
    RESPAWN_NORM = '@voice_cube_redrop'  # Non-companion
    RESPAWN_CCUBE = '@voice_ccube_redrop'  # Companion only

    # Destroy forever (dropperless) a cube
    DESTROY_NORM = '@voice_cube_dest'
    DESTROY_CCUBE = '@voice_ccube_dest'

    # Pickup a Frankenturret.
    PICKUP_FRANKEN = '@voice_franken_pickup'
    # Pickup any type
    PICKUP_ANY = '@voice_anycube_pickup'

    def add_out(self, ent: Entity, output: str) -> None:
        """Add the output to this cube."""
        ent.add_out(Output(
            output,
            self.value,
            'FireUser1',  # Forwards to the proper input.
            # Ent will ensure it never re-fires, but clean up the output.
            only_once=True,
        ))


# CubeType keyvalue for each of the types.
ENT_TYPE_INDEX = {
    CubeEntType.norm: 0,
    CubeEntType.comp: 1,
    CubeEntType.reflect: 2,
    CubeEntType.sphere: 3,
    CubeEntType.antique: 4,
}

# The models to show for each cube type.
DEFAULT_MODELS = {
    CubeEntType.norm:    'models/props/metal_box.mdl',
    CubeEntType.comp:    'models/props/metal_box.mdl',
    CubeEntType.reflect: 'models/props/reflection_cube.mdl',
    CubeEntType.sphere:  'models/props_gameplay/mp_ball.mdl',
    CubeEntType.antique: 'models/props_underground/underground_weighted_cube.mdl',
}


class CubeOutputs(Enum):
    """Inputs/outputs for cubes which can be configured."""
    # !self is replaced by the cube ent
    SPAWN = 'OnSpawn'  # When created - !self replaced by cube.
    FIZZLED = 'OnFizzle'  # When dissolved...
    DROP_DONE = 'OnFinishedDrop'  # When totally out of the dropper.
    # When picked up/dropped by the player.
    ON_PICKUP = 'OnPickup'
    ON_DROP = 'OnDrop'


class AddonFixups(Enum):
    """Special fixup variables usable in cube addons."""
    DROPPER = 'dropper'
    CUBE = 'cube'
    LINKED = 'linked'


class ModelSwapMeth(Enum):
    """Method to use to swap to custom cube models."""
    SETMODEL = 'SETMODEL'  # self.SetModel()
    CUBE_TYPE = 'CUBE_TYPE'  # CubeType = 6


class CubePaintType(Enum):
    """If a Cube Painter is present, indicates the type of gel to apply.

    The value is the engine paint index.
    """
    BOUNCE = 0
    SPEED = 2


class CubeSkins(NamedTuple):
    """Specifies the various skins present for cubes.

    Rusty skins are only applicable if the map doesn't contain gels, since
    all of the cube types have one or more bad gel skins. If None, there's
    no rusty version.
    For each, the first is the off skin, the second is the on skin.
    """
    clean: tuple[int, int]
    rusty: tuple[int, int] | None
    bounce: tuple[int, int]
    speed: tuple[int, int]

    def spawn_skin(self, paint: CubePaintType | None) -> int:
        """Return the skin this paint would spawn with."""
        if paint is None:
            return self.clean[0]
        elif paint is CubePaintType.BOUNCE:
            return self.bounce[0]
        elif paint is CubePaintType.SPEED:
            return self.speed[0]
        raise AssertionError(f"Unknown value: {paint}")


# (paint, type and rusty) -> off, on skins.
CUBE_SKINS: dict[CubeEntType, CubeSkins] = {
    CubeEntType.norm: CubeSkins(
        clean=(0, 2),
        rusty=(3, 5),
        bounce=(6, 10),
        speed=(7, 11),
    ),
    CubeEntType.comp: CubeSkins(
        clean=(1, 4),
        rusty=None,
        # On-painted skins are actually normal!
        # Not really noticeable though, so don't bother
        # fixing.
        bounce=(8, 10),
        speed=(9, 11),
    ),
    CubeEntType.reflect: CubeSkins(
        clean=(0, 0),
        rusty=(1, 1),
        bounce=(2, 2),
        speed=(3, 3),
        # 4-6 are for Schrodinger...
    ),
    CubeEntType.sphere: CubeSkins(
        clean=(0, 1),
        rusty=None,
        bounce=(2, 2),
        speed=(3, 3),
    ),
    CubeEntType.antique: CubeSkins(
        clean=(0, 0),
        rusty=None,
        bounce=(1, 1),
        speed=(2, 2),
    ),
}


# Things that get attached to a cube.
class CubeAddon:
    """A thing that can be attached to a cube."""
    def __init__(
        self,
        addon_id: str,
        inst: str='',
        pack: str='',
        vscript: str='',
        outputs: MutableMapping[CubeOutputs, list[Output]]=EmptyMapping,
        fixups: list[tuple[str, str | AddonFixups]] | None = None,
    ):
        self.id = addon_id
        self.inst = inst
        self.pack = pack
        self.vscript = vscript  # Entity script(s)s to add to the cube.
        self.outputs: dict[CubeOutputs, list[Output]] = {}
        # None means not defined at all, so fallback to copying everything.
        # "fixups" {} on the other hand would not copy any fixups.
        self.fixups = fixups

        for out_type in CubeOutputs:
            self.outputs[out_type] = list(outputs.get(out_type, ()))

    @classmethod
    def parse(cls, props: Property) -> 'CubeAddon':
        addon = cls(
            props['id'],
            props['instance', ''],
            props['packlist', ''],
            props['vscript', ''],
            cls._parse_outputs(props),
            cls._parse_fixups(props),
        )
        return addon

    @classmethod
    def base_parse(cls, cube_id: str, props: Property):
        """Parse from the config for cube types."""
        inst = props['overlay_inst', '']
        pack = props['overlay_pack', '']
        script = props['vscript', '']
        outputs = cls._parse_outputs(props)
        fixups = cls._parse_fixups(props)
        if inst or pack or script or any(outputs.values()) or fixups:
            return cls(cube_id, inst, pack, script, outputs, fixups)
        else:
            return None

    @staticmethod
    def _parse_outputs(props: Property) -> dict[CubeOutputs, list[Output]]:
        """Parse addon outputs."""
        outputs: dict[CubeOutputs, list[Output]] = {}
        out_list: list[Output]

        for out_type in CubeOutputs:
            outputs[out_type] = out_list = []
            for prop in props.find_all(out_type.value):
                out_list.append(Output.parse(prop))

        return outputs

    @staticmethod
    def _parse_fixups(props: Property) -> list[tuple[str, AddonFixups | str]] | None:
        src: AddonFixups | str
        fixups: list[tuple[str, AddonFixups | str]] = []
        found = False
        for parent in props.find_all('Fixups'):
            found = True
            for prop in parent:
                if prop.value.startswith('<') and prop.value.endswith('>'):
                    src = AddonFixups(prop.value[1:-1].casefold())
                else:
                    src = prop.value
                fixups.append((prop.real_name, src))
        return fixups if found else None


class DropperType:
    """A type of dropper that makes cubes."""
    def __init__(
        self,
        drop_id: str,
        item_id: str,
        cube_pos: Vec,
        cube_orient: Angle,
        out_start_drop: tuple[str | None, str],
        out_finish_drop: tuple[str | None, str],
        in_respawn: tuple[str | None, str],
        filter_name: str,
        bounce_paint_file: str,
    ) -> None:
        self.id = drop_id
        self.instances = resolve_inst(item_id)
        self.cube_pos = cube_pos
        # Orientation of the cube.
        self.cube_orient = cube_orient

        # Instance output fired when finishing dropping. !activator
        # should be the cube!
        self.out_finish_drop = out_finish_drop

        # Instance output fired when dropper starts spawning.
        self.out_start_drop = out_start_drop

        # Instance input to respawn the cube.
        self.in_respawn = in_respawn

        # Name of the filter which detects only the cube, used to link up superpos logic.
        self.filter_name = filter_name

        # The instance to use to bounce-paint the dropped cube.
        self.bounce_paint_file = bounce_paint_file

    @classmethod
    def parse(cls, conf: Property) -> DropperType:
        """Parse from vbsp_config."""
        if 'cube_ang' in conf:
            cube_orient = Angle.from_str(conf['cube_ang'])
        elif 'cube_dir' in conf:
            # Old configuration - the X forward direction.+
            LOGGER.warning(
                'Cube type "{}" uses deprectated cube_dir option, '
                'use cube_angles instead.',
                conf['id'],
            )
            cube_dir_str = conf['cube_dir']
            try:
                cube_dir = Vec(conditions.DIRECTIONS[cube_dir_str])
            except KeyError:
                cube_dir = Vec.from_str(cube_dir_str, x=1)
            # Set roll to counteract us being on the ceiling.
            cube_orient = cube_dir.to_angle(180)
        else:
            cube_orient = Angle()

        return cls(
            drop_id=conf['id'].upper(),
            item_id=conf['itemid'],
            cube_pos=conf.vec('cube_pos'),
            cube_orient=cube_orient,
            out_start_drop=Output.parse_name(conf['OutStartDrop']),
            out_finish_drop=Output.parse_name(conf['OutFinishDrop']),
            in_respawn=Output.parse_name(conf['InputRespawn']),
            bounce_paint_file=conf['BluePaintInst', ''],
            filter_name=conf['filtername', 'filter'],
        )


class CubeType:
    """A type of cube that can be spawned from droppers."""
    def __init__(
        self,
        cube_id: str,
        cube_type: CubeEntType,
        has_name: str,
        cube_item_id: str,
        is_companion: bool,
        try_rusty: bool,
        model: str | None,
        model_color: str | None,
        model_swap_meth: ModelSwapMeth,
        pack: str | list[str],
        pack_color: str | list[str],
        base_offset: float,
        base_tint: Vec,
        overlay_addon: CubeAddon | None,
        overlay_think: str | None,
    ):
        self.id = cube_id
        self.instances = resolve_inst(cube_item_id)

        # Suffix for voice attributes.
        self.has_name = has_name.casefold()
        # Basic type - the kind of cube entity to use.
        self.type = cube_type

        # Special cased, these don't link upwards.
        self.is_valve_cube = cube_id in VALVE_CUBE_IDS.values()

        # Models for normal and colorized versions.
        # If set it swaps to that model.
        self.model = model
        self.model_color = model_color
        # Technique to use.
        self.model_swap_meth = model_swap_meth

        # List of files, or a str packlist ID.
        self.pack = pack
        self.pack_color = pack_color

        # Tint rendercolor by this value.
        # This is applied before colour tints, if any.
        self.base_tint = base_tint

        # Conceptually - is it 'companion'-like for voicelines
        self.is_companion = is_companion
        # If true, use the original model and rusty skin type if no gels are
        # present.
        self.try_rusty = try_rusty

        # Distance from model origin to the 'floor'.
        self.base_offset = base_offset

        # If set, an instance to attach onto the cube.
        self.overlay_addon = overlay_addon
        # Only the base cube option can have a think script.
        self.overlay_think = overlay_think

        # Set to true if in the map.
        self.in_map = False
        # Same for colorized version.
        self.color_in_map = False

    @classmethod
    def parse(cls: type[CubeType], conf: Property) -> CubeType:
        """Parse from vbsp_config."""
        cube_id = conf['id'].upper()

        cube_item_id = conf['itemid']

        packlist_prop = conf.find_key('Pack', '')
        packlist: list[str] | str
        if packlist_prop.has_children():
            # Each file individually
            packlist = [
                prop.value for prop in packlist_prop
            ]
        else:
            # One value - packlist ID
            packlist = packlist_prop.value

        packlist_color_prop = conf.find_key('PackColor', '')
        packlist_color: list[str] | str
        if packlist_color_prop.has_children():
            packlist_color = [
                prop.value for prop in packlist_color_prop
            ]
        else:
            packlist_color = packlist_color_prop.value

        try:
            cube_type = CubeEntType(conf['cubetype'].upper())
        except ValueError:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='CubeType',
                value=conf['cubetype'],
                kind='Cube',
                id=cube_id,
            )) from None
        except LookupError:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='cubetype',
                kind='Cube',
                id=cube_id,
            )) from None

        try:
            model_swap_meth = ModelSwapMeth(conf['modelswapmeth', 'SETMODEL'].upper())
        except ValueError:
            raise user_errors.UserError(user_errors.TOK_INVALID_PARAM.format(
                option='ModelSwapMeth',
                value=conf['modelswapmeth'],
                kind='Cube',
                id=cube_id,
            )) from None

        if cube_type is CubeEntType.franken:
            # Frankenturrets can't swap their model.
            cust_model = cust_model_color = None
        else:
            cust_model = conf['model', None]
            cust_model_color = conf['modelColor', None]

        return cls(
            cube_id,
            cube_type,
            conf['hasName'],
            cube_item_id,
            cube_type is CubeEntType.comp or conf.bool('isCompanion'),
            conf.bool('tryRusty'),
            cust_model,
            cust_model_color,
            model_swap_meth,
            packlist,
            packlist_color,
            conf.float('offset', 20),
            conf.vec('baseTint', 255, 255, 255),
            CubeAddon.base_parse(cube_id, conf),
            conf['thinkFunc', None],
        )

    def add_models(self, models: dict[str, str]) -> None:
        """Get the models used for a cube type.

        These are stored as keys of the models dict, with the value a name to
        use for filters or variables.
        """
        # If we have a coloured version, we might need that too.
        if self.model_color and self.color_in_map:
            models[self.model_color] = self.has_name + '_color'

        if self.in_map:
            if self.model:
                models[self.model] = self.has_name
            else:
                # No custom model - it's default.
                models[DEFAULT_MODELS[self.type]] = self.has_name


class CubePair:
    """Represents a single cube/dropper pair."""
    def __init__(
        self,
        cube_type: CubeType,
        drop_type: DropperType=None,
        dropper: Entity=None,
        cube: Entity=None,
        cube_fixup: EntityFixup=None,
        tint: Vec=None,
    ):
        self.cube_type = cube_type
        # This may be None if it's a dropper-only pair.
        self.cube = cube

        # These may be None, if dropperless!
        self.drop_type = drop_type
        self.dropper = dropper

        # Fixup values from the cube's instance.
        if cube_fixup is None:
            if cube is not None:
                # Grab from the cube instance.
                cube_fixup = cube.fixup
            else:
                # This can only be None for Valve's cubes!
                if not self.cube_type.is_valve_cube:
                    LOGGER.warning('Cube "{}" has no fixup values!')
                cube_fixup = EntityFixup()

        self.cube_fixup = cube_fixup

        # If set, the cube has this paint type.
        self.paint_type: CubePaintType | None = None

        # If set, this is quantum-entangled.
        self.superpos: Superposition | None = None

        self.tint = tint  # If set, Colorizer color to use.

        # Copy from the dropper, allowing specific droppers to update this.
        if drop_type is not None:
            self.spawn_offset = drop_type.cube_pos
        else:
            self.spawn_offset = Vec()

        # Addons to attach to the cubes.
        # Use a set to ensure it doesn't have two copies.
        self.addons: set[CubeAddon] = set()

        if cube_type.overlay_addon is not None:
            self.addons.add(cube_type.overlay_addon)

        # Outputs to fire on the cubes.
        self.outputs: dict[CubeOutputs, list[Output]] = {
            out_type: [] for out_type in CubeOutputs
        }

        # Ensure we can look up the pair by origin and instance.
        # Round to the nearest voxel to allow the cube to be offset.
        if dropper is not None:
            pos = Vec.from_str(dropper['origin']) // 128
            CUBE_POS[pos.as_tuple()] = self
            INST_TO_PAIR[dropper] = self
        if cube is not None:
            pos = Vec.from_str(cube['origin']) // 128
            CUBE_POS[pos.as_tuple()] = self
            INST_TO_PAIR[cube] = self

        # Cache of comp_kv_setters adding outputs to dropper ents.
        self._kv_setters: dict[str, Entity] = {}

    @property
    def is_superpos_ghost(self) -> bool:
        """Return if this is the superpos ghost pair."""
        return self.superpos is not None and self.superpos.ghost is self

    @property
    def is_superpos_real(self) -> bool:
        """Return if this is the superpos real pair."""
        return self.superpos is not None and self.superpos.real is self

    def __repr__(self) -> str:
        drop_id = drop = cube = ''
        if self.dropper:
            drop = self.dropper['targetname']
        if self.cube:
            cube = self.cube['targetname']
        if self.drop_type:
            drop_id = f' "{self.drop_type.id}"'
        return f'<CubePair{drop_id} -> "{self.cube_type.id}": {drop!r} -> {cube!r}, {self.tint!s}>'

    def use_rusty_version(self, has_gel: bool) -> bool:
        """Check if we can use the rusty version.

        This is only allowed if it's one of Valve's cubes,
        no color is used, and no gels are present.
        In this case, we ignore the custom model.
        """
        return (
            not has_gel and
            self.cube_type.try_rusty and
            self.paint_type is None and
            self.tint is None and
            CUBE_SKINS[self.cube_type.type].rusty is not None
        )

    def get_kv_setter(self, name: str) -> Entity:
        """Get a KV setter setting this dropper-local name, creating if required."""
        name = conditions.local_name(self.dropper, name)
        try:
            return self._kv_setters[name]
        except KeyError:
            kv_setter = self._kv_setters[name] = self.dropper.map.create_ent(
                'comp_kv_setter',
                origin=self.dropper['origin'],
                target=name,
            )
            return kv_setter


@attrs.define
class Superposition:
    """Joins two cube pairs into a quantum-entangled superposition cube pair."""
    real: CubePair
    ghost: CubePair
    swap_inst: Entity  # The superposition item itself, with the logic for swapping.


def parse_conf(conf: Property):
    """Parse the config file for cube info."""
    for cube_conf in conf.find_all('DropperItems', 'Cube'):
        cube = CubeType.parse(cube_conf)

        if cube.id in CUBE_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='Cube',
                id=cube.id,
            ))

        CUBE_TYPES[cube.id] = cube

    for dropper_conf in conf.find_all('DropperItems', 'Dropper'):
        dropp = DropperType.parse(dropper_conf)

        if dropp.id in DROPPER_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='Dropper',
                id=dropp.id,
            ))

        DROPPER_TYPES[dropp.id] = dropp

    for addon_conf in conf.find_all('DropperItems', 'CubeAddon'):
        addon = CubeAddon.parse(addon_conf)

        if addon.id in ADDON_TYPES:
            raise user_errors.UserError(user_errors.TOK_DUPLICATE_ID.format(
                kind='CubeItem',
                id=addon.id,
            ))

        ADDON_TYPES[addon.id] = addon

    LOGGER.info(
        'Parsed {} cube types, {} dropper types and {} addons.',
        len(CUBE_TYPES),
        len(DROPPER_TYPES),
        len(ADDON_TYPES)
    )

    # Check we have the Valve cube definitions - if we don't, something's
    # wrong. However, don't error out, in case the user really didn't enable
    # the droppers.
    for cube_id in VALVE_CUBE_IDS.values():
        if cube_id not in CUBE_TYPES:
            LOGGER.warning('Valve Cube type "{}" is missing!', cube_id)


def parse_filter_types(
    cubes: list[str]
) -> tuple[set[CubeType], set[CubeType], set[CubeType]]:
    """Parse a list of cube IDs to a list of included/excluded types.

    Each cube should be the name of an ID, with '!' before to exclude it.
    It succeeds if a target is any of the included types, and not any of the
    excluded types (exclusions override inclusion).
    The IDs may also be:
    * <any> to detect all cube types (including franken)
    * <companion> to detect 'companion' items.
    * <sphere> to detect sphere-type items.
    * <reflect> to detect reflection-type items.

    This returns 3 sets of CubeTypes - all cubes, ones to include, and ones
    to exclude.
    """
    inclusions: set[CubeType] = set()
    exclusions: set[CubeType] = set()

    all_cubes: set[CubeType] = {
        cube
        for cube in CUBE_TYPES.values()
        if cube.in_map or cube.color_in_map
    }

    for cube_id in cubes:
        if cube_id[:1] == '!':
            cube_id = cube_id[1:]
            invert = True
            targ_set = exclusions
        else:
            invert = False
            targ_set = inclusions

        if cube_id[:1] == '<' and cube_id[-1:] == '>':
            # Special name.
            cube_id = cube_id[1:-1].casefold()
            if cube_id == 'any':
                # All cubes.
                if invert:
                    LOGGER.warning("Defining a filter that excludes everything is useless.")
                    return all_cubes, set(), all_cubes.copy()
                targ_set |= all_cubes
            elif cube_id == 'companion':
                for cube in all_cubes:
                    if cube.is_companion:
                        targ_set.add(cube)
            elif cube_id in ('ball', 'sphere'):
                for cube in all_cubes:
                    if cube.type is CubeEntType.sphere:
                        targ_set.add(cube)
            elif cube_id in ('reflect', 'reflection'):
                for cube in all_cubes:
                    if cube.type is CubeEntType.reflect:
                        targ_set.add(cube)
            # The other entity types don't have special behaviour really.
            else:
                raise KeyError('Unknown special cube type "<{}>"', cube_id)
        else:
            try:
                cube = CUBE_TYPES[cube_id]
            except KeyError:
                raise KeyError(f'Unknown cube type "{cube_id}"!')
            targ_set.add(cube)

    if not inclusions and exclusions:
        # We just exclude, so first include everything implicitly.
        inclusions |= all_cubes

    # If excluded, it can't be included.
    # This also means inclusions represents everything we need to worry about.
    inclusions -= exclusions

    return all_cubes, inclusions, exclusions


def cube_filter(vmf: VMF, pos: Vec, cubes: list[str]) -> str:
    """Given a set of cube-type IDs, generate a filter for them.

    The filter will be made if needed, and the targetname to use returned.
    """
    # We just parse it here, then pass on to an internal method recursively
    # to build all the ents.

    all_cubes, inclusions, exclusions = parse_filter_types(cubes)

    # Special case - no cubes at all.
    if not inclusions:
        try:
            return CUBE_FILTERS[frozenset()]
        except KeyError:
            CUBE_FILTERS[frozenset()] = filter_name = vmf.create_ent(
                # Parent class which is True for everything.
                classname='filter_base',
                targetname='@filter_nothing',
                origin=pos,
                negated=True,
            )['targetname']
            return filter_name

    # Some others which are predefined.

    if len(inclusions) > len(CUBE_TYPES) / 2 and 0:
        # If more than half of cubes are included, it's better to exclude
        # the missing ones.
        invert = True
        name_start = '@filter_bee2_exc_'
        children = all_cubes - inclusions
    else:
        name_start = '@filter_bee2_inc_'
        invert = False
        children = inclusions

    # Models we need to include in the multi-filter -> name to use.
    models: dict[str, str] = {}
    # Names to use in the final filter
    names: set[str] = set()

    # Check if we have the two class types.
    has_cube_cls = has_monst_cls = False

    for cube_type in children:
        # Special case - no model, just by class.
        # FrankenTurrets don't have one model.
        if cube_type.type is CubeEntType.franken:
            # We use the cube type instance as a unique key.
            has_monst_cls = True
            if not invert:
                # Don't do this here if inverted - it's done in the
                # multi-filter.
                names.add(FILTER_MONST_CLS)
        else:
            has_cube_cls = True
            cube_type.add_models(models)

    for model, filter_name in models.items():
        # Make a filter for each model name.
        try:
            names.add(CUBE_FILTERS[model])
        except KeyError:
            # We need to make one.
            filter_name = name_start + 'mdl_' + filter_name
            vmf.create_ent(
                classname='filter_activator_model',
                targetname=filter_name,
                origin=pos,
                model=model,
            )
            CUBE_FILTERS[model] = filter_name
            names.add(filter_name)

    # Special case, no invert and a single name - we don't need a _multi.
    if len(names) == 1 and not invert:
        return next(iter(names))

    return _make_multi_filter(
        vmf,
        pos,
        list(names),
        invert,
        has_cube_cls,
        has_monst_cls,
    )


def _make_multi_filter(
    vmf: VMF,
    pos: Vec,
    names: list[str],
    invert: bool,
    has_cube_cls: bool,
    has_monst_cls: bool,
) -> str:
    """Generate the multi-filter for cube filtering.

    This reuses ents for duplicate calls, and recurses if needed.
    """
    # Check for existing ents of the same type.
    key = frozenset(names), invert
    try:
        return CUBE_FILTERS[key]
    except KeyError:
        pass

    if len(names) > MULTI_FILTER_COUNT:
        # 5 is the maximum number in a filter_multi, we need more than one.
        names, extra_names = names[:MULTI_FILTER_COUNT], names[MULTI_FILTER_COUNT:]
        # For inversion, only the first one should be inverted.
        names.append(_make_multi_filter(vmf, pos, extra_names, False, False, False))

    # Names must now be 5 or less.

    filter_ent = vmf.create_ent(
        classname='filter_multi',
        origin=pos,
        negated=invert,
        # If not inverted - OR (1), if inverted AND (0).
        filtertype=not invert,
    ).make_unique('@filter_multi_')

    for ind, name in enumerate(names, start=1):
        filter_ent[f'Filter{ind:02}'] = name

    CUBE_FILTERS[key] = filter_ent['targetname']

    if invert:
        # For inverted ones, we need to check it's a cube class, AND not
        # the models.
        inv_name = filter_ent['targetname']
        try:
            return CUBE_FILTERS[inv_name, all]
        except KeyError:
            pass

        filter_ent = vmf.create_ent(
            classname='filter_multi',
            origin=pos,
            filtertype=0,  # AND
            filter01=inv_name,
        ).make_unique('@filter_multi_')
        if has_cube_cls:
            filter_ent['filter02'] = FILTER_CUBE_CLS
        if has_monst_cls:
            filter_ent['filter03'] = FILTER_MONST_CLS

        CUBE_FILTERS[inv_name, all] = filter_ent['targetname']

    return filter_ent['targetname']


@conditions.make_flag('CubeType')
def flag_cube_type(inst: Entity, res: Property) -> bool:
    """Check if an instance is/should be a cube.

    This is only valid on `ITEM_BOX_DROPPER`, `ITEM_CUBE`, and items marked as
    a custom dropperless cube.
    The value should be the ID of a cube type, or the following special values:

    * `<any>`: Any kind of cube item
    * `<none>`: Not a cube item
    * `<companion>`: A cube marked as companion-like.
    * `<sphere>` or `<ball>`: A sphere-type cube.
    * `<reflection>` or `<reflect>`: A reflection-type cube.
    * `<dropper>`: The dropper half of a pair.
    * `<cube>`: The cube half of a pair.
    """
    try:
        pair = INST_TO_PAIR[inst]
    except KeyError:
        # None checks for if the instance *isn't* a cube.
        return res.value.casefold() == '<none>'

    cube_type = res.value

    if not cube_type:
        raise user_errors.UserError(
            user_errors.TOK_CUBE_NO_CUBETYPE_FLAG,
            docsurl='https://github.com/BEEmod/BEE2-items/wiki/vbsp_config-conditions#cubetype',
        )

    if cube_type[0] == '<' and cube_type[-1] == '>':
        # Special checks.
        cube_type = cube_type[1:-1].casefold()

        if cube_type == 'any':
            # Any cube.
            return True
        elif cube_type == 'none':
            # Not a cube.
            return False
        elif cube_type == 'companion':
            return pair.cube_type.is_companion
        elif cube_type in ('sphere', 'ball'):
            return pair.cube_type.type is CubeEntType.sphere
        elif cube_type in ('reflect', 'reflection'):
            return pair.cube_type.type is CubeEntType.reflect
        elif cube_type == 'dropper':
            return inst is pair.dropper
        elif cube_type == 'cube':
            return inst is pair.cube
        else:
            raise user_errors.UserError(
                user_errors.TOK_CUBE_BAD_SPECIAL_CUBETYPE.format(type=res.value),
                docsurl='https://github.com/BEEmod/BEE2-items/wiki/vbsp_config-conditions#cubetype',
            )

    return pair.cube_type.id == cube_type.upper()


@conditions.make_flag('DropperColor')
def flag_dropper_color(inst: Entity, res: Property) -> bool:
    """Detect the color of a cube on droppers.

    This is `True` if the cube is coloured. The value should be a `$fixup`
    which will have the tint copied into it.
    """
    try:
        data = INST_TO_PAIR[inst]
    except KeyError:
        return False

    if res.value and data.tint is not None:
        inst.fixup[res.value] = data.tint

    return data.tint is not None


@conditions.make_result('CubeAddon', 'DropperAddon')
def res_dropper_addon(inst: Entity, res: Property):
    """Attach an addon to an item."""
    try:
        addon = ADDON_TYPES[res.value]
    except KeyError:
        raise user_errors.UserError(user_errors.TOK_UNKNOWN_ID.format(
            kind='CubeAddon',
            id=res.value,
        ))

    try:
        pair = INST_TO_PAIR[inst]
    except KeyError:
        LOGGER.warning('Cube Addon applied to non cube ("{}")', res.value)
        return

    pair.addons.add(addon)


@conditions.make_result('SetDropperOffset')
def res_set_dropper_off(inst: Entity, res: Property) -> None:
    """Update the position cubes will be spawned at for a dropper."""
    try:
        pair = INST_TO_PAIR[inst]
    except KeyError:
        LOGGER.warning('SetDropperOffset applied to non cube ("{}")', res.value)
    else:
        pair.spawn_offset = Vec.from_str(
            conditions.resolve_value(inst, res.value))


@conditions.make_result('ChangeCubeType', 'SetCubeType')
def res_change_cube_type(inst: Entity, res: Property) -> None:
    """Change the cube type of a cube item.

    This is only valid on `ITEM_BOX_DROPPER`, `ITEM_CUBE`, and instances
    marked as a custom dropperless cube.
    """
    try:
        pair = INST_TO_PAIR[inst]
    except KeyError:
        LOGGER.warning('Attempting to set cube type on non cube ("{}")', inst['targetname'])
        return

    try:
        pair.cube_type = CUBE_TYPES[res.value]
    except KeyError:
        raise user_errors.UserError(user_errors.TOK_UNKNOWN_ID.format(
            kind='CubeType',
            id=res.value,
        ))


@conditions.make_result('CubeFilter')
def res_cube_filter(vmf: VMF, inst: Entity, res: Property) -> None:
    """Given a set of cube-type IDs, generate a filter for them.

    Each cube should be the name of an ID, with `!` before to exclude it.
    It succeeds if a target is any of the included types, and not any of the
    excluded types (exclusions override inclusion).

    The IDs may also be:
    * `<any>` to detect all cube types (including franken)
    * `<companion>` to detect 'companion' items.
    * `<sphere>` to detect sphere-type items.

    The `resultvar` fixup will be set to the name to use.
    """
    inst.fixup[res['ResultVar']] = cube_filter(
        vmf,
        Vec.from_str(inst['origin']), [
            prop.value for prop in res.find_all('Cube')
        ],
    )


@conditions.make_result('VScriptCubePredicate')
def res_script_cube_predicate(vmf: VMF, ent: Entity, res: Property) -> object:
    """Given a set of cube-type IDs, generate VScript code to identify them.

    This produces a script to include, which will define the specified function
    name. Specifying the same filename twice will include all the functions.
    For that reason the filename should be unique.

    Each cube should be the name of an ID, with `!` before to exclude it.
    It succeeds if a target is any of the included types, and not any of the
    excluded types (exclusions override inclusion).
    The IDs may also be:

    * `<any>` to detect all cube types (including franken)
    * `<companion>` to detect 'companion' items.
    * `<sphere>` to detect sphere-type items.

    Config options:

    * `function`: Name of the function - called with an entity as an argument.
    * `filename`: Path to the .nut script, relative to scripts/vscripts/.
    * `Cube`: A cube to include.
    """
    script_function = res['function']
    script_filename = res['filename']

    # Allow function() and filenames without '.nut'.
    if script_function[-2:] == '()':
        script_function = script_function[:-2]
    if script_filename[-4:] != '.nut':
        script_filename += '.nut'

    all_cubes, inclusions, exclusions = parse_filter_types([
        prop.value for prop in res.find_all('Cube')
    ])

    # We don't actually care about exclusions anymore.

    models: dict[str, str] = {}
    for cube_type in inclusions:
        cube_type.add_models(models)

    # Normalise the names to a consistent format.
    model_names = list({
        model.lower().replace('\\', '/')
        for model in models
    })

    conf_ent = vmf.create_ent(
        'bee2_cube_filter_script',
        origin=ent['origin'],
        filename=script_filename,
        function=script_function,
    )
    for i, model in enumerate(model_names, 1):
        conf_ent[f'mdl{i:02}'] = model

    return conditions.RES_EXHAUSTED


@conditions.meta_cond(priority=-750, only_once=True)
def link_cubes(vmf: VMF, info: conditions.MapInfo) -> None:
    """Determine the cubes set based on instance settings.

    This sets data, but doesn't implement the changes.
    """
    # cube or dropper -> cubetype or droppertype value.
    inst_to_cube: dict[str, CubeType] = {
        fname: cube_type
        for cube_type in CUBE_TYPES.values()
        for fname in cube_type.instances
    }
    inst_to_drop: dict[str, DropperType] = {
        fname: drop_type
        for drop_type in DROPPER_TYPES.values()
        for fname in drop_type.instances
    }

    # Origin -> instances
    dropper_pos: dict[tuple[float, float, float], tuple[Entity, DropperType]] = {}
    # Timer value -> instances if not 0.
    dropper_timer: dict[int, tuple[Entity, DropperType]] = {}
    # Instance -> if linked, the position of the cube.
    used_droppers: dict[Entity, str] = {}

    # Cube items.
    cubes: list[tuple[Entity, CubeType]] = []

    for inst in vmf.by_class['func_instance']:
        fname = inst['file'].casefold()
        try:
            cube_type = inst_to_cube[fname]
        except KeyError:
            pass  # Non cube.
        else:
            # A dropperless cube.
            cubes.append((inst, cube_type))
            continue
        try:
            drop_type = inst_to_drop[fname]
        except KeyError:
            continue  # Not cube or dropper, we don't care.

        timer = inst.fixup.int('$timer_delay', 0)
        # Don't allow others access to this value.
        del inst.fixup['$timer_delay']
        # Infinite and 3 (default) are treated as off.
        if 3 < timer <= 30:
            if timer in dropper_timer:
                other_inst, _ = dropper_timer[timer]
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_TIMERS_DUPLICATE.format(timer=timer),
                    voxels=[
                        Vec.from_str(inst['origin']),
                        Vec.from_str(other_inst['origin']),
                    ]
                )
            else:
                dropper_timer[timer] = inst, drop_type
        # For setup later.
        dropper_pos[Vec.from_str(inst['origin']).as_tuple()] = inst, drop_type
        used_droppers[inst] = ''

    # Now link and match up all the cubes.
    for cube, cube_type in cubes:
        # First look for a timer value, for linking cubes specifically.
        timer = cube.fixup.int('$timer_delay', 0)

        # Don't allow others access to this value.
        del cube.fixup['$timer_delay']

        # Infinite and 3 (default) are treated as off.
        if 3 < timer <= 30:
            try:
                dropper, drop_type = dropper_timer[timer]
            except KeyError:
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_TIMERS_INVALID_CUBEVAL.format(timer=timer),
                    voxels=[Vec.from_str(cube['origin'])],
                ) from None
            if used_droppers[dropper]:
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_TIMERS_DUPLICATE.format(timer=timer),
                    voxels=[
                        Vec.from_str(cube['origin']),
                        Vec.from_str(used_droppers[dropper]),
                        Vec.from_str(dropper['origin']),
                    ]
                ) from None
            used_droppers[dropper] = cube['origin']

            # Autodrop on the dropper shouldn't be on - that makes
            # linking useless since the cube immediately fizzles.

            # Valve's dropper inverts the value, so it needs to be 1 to disable.
            # Custom items need 0 to disable.
            dropper.fixup['$disable_autodrop'] = (drop_type.id == VALVE_DROPPER_ID)

            PAIRS.append(CubePair(cube_type, drop_type, dropper, cube))
            continue

        # Next try to link to a dropper on the ceiling.
        # We don't do this for Valve cubes, since those
        # already can set their types.

        # In this case, the cube is removed from the map.
        # It's only used to set what cube the dropper is.
        if not cube_type.is_valve_cube:
            ceil_pos = brushLoc.POS.raycast_world(
                Vec.from_str(cube['origin']),
                direction=(0, 0, 1),
            )
            try:
                dropper, drop_type = dropper_pos[ceil_pos.as_tuple()]
            except KeyError:
                pass  # Drop out of if
            else:
                if used_droppers[dropper]:
                    raise user_errors.UserError(
                        user_errors.TOK_CUBE_DROPPER_LINKED.format(type=cube_type.id),
                        voxels=[
                            Vec.from_str(cube['origin']),
                            Vec.from_str(used_droppers[dropper]),
                            Vec.from_str(dropper['origin']),
                        ]
                    ) from None
                used_droppers[dropper] = cube['origin']
                cube.remove()
                PAIRS.append(CubePair(cube_type, drop_type, dropper, cube_fixup=cube.fixup))
                continue

        # Otherwise, both cases fail - the cube is dropperless.
        PAIRS.append(CubePair(cube_type, cube=cube))

    # Now cubes are done, loop through the remaining droppers and assign
    # Valve cube types to those.
    for dropper, is_used in used_droppers.items():
        if is_used:
            continue
        cube_type_num = dropper.fixup.int('$cube_type')
        try:
            cube_type_id = VALVE_CUBE_IDS[cube_type_num]
        except KeyError:
            raise user_errors.UserError(
                user_errors.TOK_INVALID_PARAM.format(
                    option='$cube_type',
                    value=cube_type_num,
                    kind='Valve Cube',
                    id=dropper['targetname']
                ),
                voxels=[Vec.from_str(dropper['origin'])],
            ) from None
        try:
            cube_type = CUBE_TYPES[cube_type_id]
        except KeyError:
            raise user_errors.UserError(
                user_errors.TOK_UNKNOWN_ID.format(kind='Valve cube', id=cube_type_id),
                voxels=[Vec.from_str(dropper['origin'])],
            ) from None

        drop_type = inst_to_drop[dropper['file'].casefold()]
        PAIRS.append(CubePair(cube_type, drop_type, dropper=dropper))

    # Check for colorisers, superpos entanglers and gel splats in the map, and apply those.
    coloriser_inst = resolve_inst('<ITEM_BEE2_CUBE_COLORISER>', silent=True)
    superpos_inst = resolve_inst('<ITEM_BEE2_SUPERPOSITION_ENTANGLER>', silent=True)
    splat_inst = resolve_inst('<ITEM_PAINT_SPLAT>', silent=True)

    for inst in vmf.by_class['func_instance']:
        file = inst['file'].casefold()

        if file in coloriser_inst:
            kind = coloriser_inst
        elif file in superpos_inst:
            kind = superpos_inst
        elif file in splat_inst:
            kind = splat_inst
        else:
            # Not one we care about.
            continue

        pairs: list[CubePair] = []

        origin = Vec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])

        with suppress(KeyError):
            pairs.append(CUBE_POS[(origin // 128).as_tuple()])

        # If pointing up, check the ceiling too, so droppers can find a
        # colorizer
        # placed on the illusory cube item under them.
        if orient.up().z > 0.9:
            pos = brushLoc.POS.raycast_world(
                origin,
                direction=(0, 0, 1),
            ) // 128
            with suppress(KeyError):
                pairs.append(CUBE_POS[pos.as_tuple()])

        if kind is coloriser_inst:
            # The instance is useless now we know about it.
            inst.remove()

            color = Vec.from_str(options.get_itemconf(
                ('BEE2_CUBE_COLORISER', 'COLOR'),
                '255 255 255',
                timer_delay=inst.fixup.int('$timer_delay'),
            ))
            for pair in pairs:
                pair.tint = color.copy()
        elif kind is splat_inst:
            try:
                paint_type = CubePaintType(inst.fixup.int('$paint_type'))
            except ValueError:
                # Don't touch if not bounce/speed.
                continue

            # Only 'use up' one splat, so you can place multiple to apply them
            # to both the cube and surface.
            used = False

            for pair in pairs:
                if pair.paint_type is None:
                    pair.paint_type = paint_type
                    used = True
            if used:
                inst.remove()
        elif kind is superpos_inst:
            try:
                superpos_item = connections.ITEMS[inst['targetname']]
            except KeyError:
                LOGGER.warning('No item for superpos instance "{}"!', inst['targetname'])
                continue
            real_pair: CubePair
            conn: connections.Connection
            try:
                # Don't link to dropperless cubes.
                [real_pair] = filter(lambda p: p.dropper is not None, pairs)
            except ValueError:
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_SUPERPOS_BAD_REAL,
                    voxels=[Vec.from_str(inst['origin'])],
                )
            try:
                [conn] = superpos_item.outputs
                ghost_pair = INST_TO_PAIR[conn.to_item.inst]
                if ghost_pair.dropper is None:
                    raise ValueError
            except (ValueError, KeyError):
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_SUPERPOS_BAD_GHOST,
                    voxels=[Vec.from_str(inst['origin'])],
                )
            conn.remove()
            superpos_item.delete_antlines()
            if real_pair.superpos is not None:
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_SUPERPOS_MULTILINK,
                    voxels=[
                        Vec.from_str(inst['origin']),
                        Vec.from_str(real_pair.dropper['origin']),
                    ]
                )
            if ghost_pair.superpos is not None:
                raise user_errors.UserError(
                    user_errors.TOK_CUBE_SUPERPOS_MULTILINK,
                    voxels=[
                        Vec.from_str(inst['origin']),
                        Vec.from_str(ghost_pair.dropper['origin']),
                    ]
                )
            real_pair.superpos = ghost_pair.superpos = superpos = Superposition(
                real_pair, ghost_pair, inst,
            )
            inst.fixup['$ghost_alpha'] = min(255, max(0, options.get(
                int, 'superposition_ghost_alpha',
            )))
            LOGGER.info('Superpos link: {}', superpos)
        else:
            raise AssertionError(f'Unknown kind {kind!r}?')

    # After that's done, save what cubes are present for filter optimisation,
    # and set Voice 'Has' attrs.
    if PAIRS:
        info.set_attr('cube')

    for pair in PAIRS:
        if pair.tint is not None:
            pair.cube_type.color_in_map = True
        else:
            pair.cube_type.in_map = True

        if pair.paint_type is CubePaintType.BOUNCE:
            info.set_attr('gel', 'bouncegel', 'BlueGel')
        elif pair.paint_type is CubePaintType.SPEED:
            info.set_attr('gel', 'speedgel', 'OrangeGel')

        if pair.dropper:
            info.set_attr('cubedropper')
            # Remove this since it's not useful, with our changes.
            del pair.dropper.fixup['$cube_type']

        has_name = pair.cube_type.has_name
        names = [has_name]

        if not pair.cube_type.is_companion:
            names.append('notcompanion')
        # Any spherical item, not specifically edgeless cubes.
        if pair.cube_type.type is CubeEntType.sphere:
            names.append('sphereshaped')
        else:
            names.append('notsphereshaped')

        for name in names:
            info.set_attr('cube' + name)
            if pair.dropper:
                info.set_attr('cubedropper', 'cubedropper' + name)
            else:
                info.set_attr('cubedropperless' + name)


def setup_output(
    template: Output,
    inst: Entity,
    output: str,
    self_name: str='!self',
):
    """Modify parts of an output.

    inst is the instance to fixup names to fire into.
    self_name is the entity to replace '!self' with.
    """
    out = template.copy()
    out.output = output
    out.comma_sep = False
    if out.target == '!self':
        out.target = self_name
    else:
        out.target = conditions.local_name(inst, out.target)
    return out


def make_cube(
    vmf: VMF,
    pair: CubePair,
    floor_pos: Vec,
    in_dropper: bool,
    bounce_in_map: bool,
    speed_in_map: bool,
) -> tuple[bool, Entity]:
    """Place a cube on the specified floor location.

    floor_pos is the location of the bottom of the cube.
    """
    cube_type = pair.cube_type
    drop_type = pair.drop_type

    origin = floor_pos.copy()

    is_frank = cube_type.type is CubeEntType.franken

    if is_frank:
        # If in droppers, frankenturrets are in box
        # form, so they're flat. If dropperless
        # they're standing up and so are higher up.
        origin.z += 20 if in_dropper else 24
    else:
        origin.z += cube_type.base_offset

    spawn_paint = pair.paint_type

    ent = vmf.create_ent(
        classname='prop_weighted_cube',
        origin=origin,
        PaintPower=4,  # Unpainted
    )

    if in_dropper:
        assert drop_type is not None
        assert pair.dropper is not None

        if not pair.drop_type:
            raise ValueError('Cube in dropper without dropper!')

        angles = drop_type.cube_orient @ Angle.from_str(pair.dropper['angles'])
        targ_inst = pair.dropper
    else:
        angles = Angle(0, 180, 0) @ Angle.from_str(pair.cube['angles'])
        targ_inst = pair.cube

    cust_model = cube_type.model
    pack: str | list[str] | None = cube_type.pack

    if is_frank:
        # No tinting or custom models for this.
        cust_model = pack = None
        rendercolor = '255 255 255'
    elif pair.tint is not None:
        cust_model = cube_type.model_color
        pack = cube_type.pack_color
        # Multiply the two tints together.
        # a/255 * b/255 * 255 -> a*b/255
        r = cube_type.base_tint.x * pair.tint.x // 255
        g = cube_type.base_tint.y * pair.tint.y // 255
        b = cube_type.base_tint.z * pair.tint.z // 255
        ent['rendercolor'] = rendercolor = f'{int(r)} {int(g)} {int(b)}'
    else:
        ent['rendercolor'] = rendercolor = cube_type.base_tint

    if pair.superpos is not None and pair.is_superpos_ghost:
        # Superposition ghost cubes are regular physics props, most of this functionality doesn't
        # apply.
        del ent['PaintPower']
        ent['classname'] = 'prop_physics_override'
        ent['rendermode'] = '9'  # World Space Glow
        ent['renderamt'] = ghost_alpha = pair.superpos.swap_inst.fixup['$ghost_alpha']
        ent['responsecontext'] = 'nofizzle:1,superpos_ghost:1'
        ent['spawnflags'] = 1048576 | 256  # Can always pickup, generate output on USE.
        ent['vscripts'] = 'BEE2/superpos_ghost.nut'
        ent['thinkfunction'] = 'Think'
        # The VScript needs to know the color, so it can reset after painting.
        ent['vscript_init_code'] = f"ghost_color <- `{rendercolor}`; ghost_alpha <- {ghost_alpha}"

        ent['model'] = cust_model or DEFAULT_MODELS[cube_type.type]
        # If in droppers, disable portal funnelling until it falls out.
        ent['AllowFunnel'] = not in_dropper
        ent['angles'] = angles
        # Add a dummy entity to force fixup names.
        vmf.create_ent(
            'info_null',
            targetname=conditions.local_name(targ_inst, 'cube_addon_superpos_dummy'),
            parentname=conditions.local_name(targ_inst, 'box'),
        )
        return False, ent

    if pair.paint_type is not None:
        if is_frank:
            # Special case - frankenturrets don't have inputs for it.
            # We need a sprayer to generate the actual paint,

            # Set rendercolor to what it will be, so it doesn't
            # visually change. (speed_paint_color, bounce_paint_color ConVars.)
            if pair.paint_type is CubePaintType.SPEED:
                ent['rendercolor'] = '255 106 0'
            elif pair.paint_type is CubePaintType.BOUNCE:
                ent['rendercolor'] = '0 165 255'

            vmf.create_ent(
                targetname=conditions.local_name(targ_inst, 'cube_addon_painter'),
                classname='info_paint_sprayer',
                origin=ent['origin'],
                ambientsound=0,
                drawonly=0,
                silent=1,
                painttype=pair.paint_type.value,
            )
        else:
            # Two ways of applying paint - immediately on spawn, or at playtime.
            # Orange cubes can stay put when dropped, so they're fine.
            # Dropperless cubes should spawn bouncing around.
            if not in_dropper or pair.paint_type is CubePaintType.SPEED or drop_type is None:
                ent['PaintPower'] = pair.paint_type.value

            # Another special case - droppers which can spawn bounce-gel
            # directly.
            # Make the dropper 'non-stick' by manually applying the skin,
            # then set paint type after exiting. That way it can't bounce off
            # the dropper walls, but will look visually painted.
            elif drop_type.bounce_paint_file.casefold() == '<prepaint>':
                assert drop_type is not None
                assert pair.dropper is not None

                # Apply the skin after spawn.
                ent.add_out(
                    Output(
                        'OnUser4',
                        '!self',
                        'Skin',
                        CUBE_SKINS[pair.cube_type.type].spawn_skin(CubePaintType.BOUNCE),
                        only_once=True,
                    )
                )

                # Manually add the dropper outputs here, so they only add to the
                # actual dropper (not the other cube if present).
                drop_name, drop_cmd = drop_type.out_finish_drop
                pair.get_kv_setter(drop_name).add_out(
                    # Paint the cube, so it now has the functionality.
                    Output(
                        drop_cmd,
                        '!activator',
                        'SetPaint',
                        pair.paint_type.value,
                    )
                )
            else:
                assert drop_type is not None
                assert pair.dropper is not None

                # Add the bounce painter. This is only on the dropper.
                conditions.add_inst(
                    vmf,
                    targetname=pair.dropper['targetname'],
                    origin=pair.dropper['origin'],
                    angles=pair.dropper['angles'],
                    file=drop_type.bounce_paint_file,
                )
                # Manually add the dropper outputs here, so they only add to the
                # actual dropper.
                drop_name, drop_cmd = drop_type.out_finish_drop
                pair.get_kv_setter(drop_name).add_out(
                    # Fire an input to activate the effects.
                    Output(
                        drop_cmd,
                        conditions.local_name(pair.dropper, 'painter_blue'),
                        'FireUser1',
                    ),
                    # And also paint the cube itself.
                    Output(
                        drop_cmd,
                        '!activator',
                        'SetPaint',
                        pair.paint_type.value,
                    )
                )
                # Don't paint it on spawn.
                spawn_paint = None

    has_addon_inst = False
    vscripts = []
    for addon in pair.addons:
        if addon.inst:
            has_addon_inst = True
            inst = conditions.add_inst(
                vmf,
                targetname=targ_inst['targetname'],
                origin=origin,
                # If out of dropper, spin to match the frankenturret box position.
                angles=(
                    Angle(-25.5, 0, 0) @ angles
                    if is_frank and not in_dropper
                    else angles
                ),
                file=addon.inst,
            )
            if addon.fixups is not None:
                for fixup_var, fixup_src in addon.fixups:
                    if fixup_src is AddonFixups.CUBE:
                        inst.fixup[fixup_var] = not in_dropper
                    elif fixup_src is AddonFixups.DROPPER:
                        inst.fixup[fixup_var] = in_dropper
                    elif fixup_src is AddonFixups.LINKED:
                        inst.fixup[fixup_var] = pair.dropper is not None and pair.cube is not None
                    else:
                        inst.fixup[fixup_var] = pair.cube_fixup.substitute(fixup_src, allow_invert=True)
            else:
                inst.fixup.update(pair.cube_fixup)
        packing.pack_list(vmf, addon.pack)
        if addon.vscript:
            vscripts.append(addon.vscript.strip())

    if is_frank:
        ent['classname'] = 'prop_monster_box'
        if in_dropper:
            ent['angles'] = Angle(25.5, 0, 0) @ angles
        else:
            ent['angles'] = angles
        ent['StartAsBox'] = in_dropper
        ent['AllowSilentDissolve'] = 1
    else:
        # A prop_weighted_cube
        ent['NewSkins'] = '1'

        skin = CUBE_SKINS[pair.cube_type.type]
        skinset: set[int] = set()

        if pair.use_rusty_version(bounce_in_map or speed_in_map):
            ent['SkinType'] = '1'
            ent['Skin'] = skin.rusty[0]
            skinset.update(skin.rusty)
            cust_model = None
        else:
            ent['SkinType'] = '0'
            ent['Skin'] = skin.spawn_skin(spawn_paint)
            skinset.update(skin.clean)
            if bounce_in_map or spawn_paint is CubePaintType.BOUNCE:
                skinset.update(skin.bounce)
            if speed_in_map or spawn_paint is CubePaintType.BOUNCE:
                skinset.update(skin.speed)

        ent['skinset'] = ' '.join(map(str, sorted(skinset)))
        ent['angles'] = angles
        # If in droppers, disable portal funnelling until it falls out.
        ent['AllowFunnel'] = not in_dropper

        ent['CubeType'] = ENT_TYPE_INDEX[cube_type.type]

        if cust_model:
            ent['model'] = cust_model

            if cube_type.model_swap_meth is ModelSwapMeth.CUBE_TYPE:
                ent['CubeType'] = CUBE_ID_CUSTOM_MODEL_HACK
            elif cube_type.model_swap_meth is ModelSwapMeth.SETMODEL:
                precache_model(vmf, cust_model, skinset)

            if isinstance(pack, list):
                packing.pack_files(vmf, *pack)
            elif isinstance(pack, str):
                packing.pack_list(vmf, pack)
        else:
            # The model is unused, but set it so it looks nicer.
            ent['model'] = DEFAULT_MODELS[cube_type.type]

    ent['vscripts'] = ' '.join(vscripts)
    if vscripts and cube_type.overlay_think:
        ent['thinkfunction'] = cube_type.overlay_think

    for temp_out in pair.outputs[CubeOutputs.ON_PICKUP]:
        ent.add_out(setup_output(
            temp_out,
            targ_inst,
            'OnPlayerPickup',
        ))
    for temp_out in pair.outputs[CubeOutputs.ON_DROP]:
        ent.add_out(setup_output(
            temp_out,
            targ_inst,
            'OnPhysGunDrop',
        ))

    return has_addon_inst, ent


@conditions.meta_cond(priority=750, only_once=True)
def generate_cubes(vmf: VMF, info: conditions.MapInfo) -> None:
    """After other conditions are run, generate cubes."""
    bounce_in_map = info.has_attr('bouncegel')
    speed_in_map = info.has_attr('speedgel')

    # point_template for spawning dropperless cubes.
    # We can fit 16 in each, start with the count = 16 so
    # we make one immediately.
    dropperless_temp = None
    dropperless_temp_count = 16

    for pair in PAIRS:
        # Don't include the original cube instance.
        if pair.cube:
            pair.cube.remove()

        if pair.is_superpos_ghost:
            # Ghost does not have functionality, and cannot be painted.
            pair.addons.clear()
            pair.paint_type = None

        # Add the custom model logic. But skip if we use the rusty version.
        # That overrides it to be using the normal model.
        if (
            pair.cube_type.model_swap_meth is ModelSwapMeth.SETMODEL
            and not pair.use_rusty_version(bounce_in_map or speed_in_map)
        ):
            cust_model = (
                pair.cube_type.model_color
                if pair.tint is not None else
                pair.cube_type.model
            )
            if cust_model:
                # Fire an on-spawn output that swaps the model,
                # then resets the skin to the right one.
                # If we have a bounce cube painter, it needs to be the normal skin.
                if (
                    pair.paint_type is CubePaintType.BOUNCE and
                    pair.drop_type.bounce_paint_file.casefold() != '<prepaint>'
                ):
                    spawn_paint = None
                else:
                    spawn_paint = pair.paint_type

                pair.outputs[CubeOutputs.SPAWN].append(Output(
                    '', '!self', 'RunScriptCode',
                    'self.SetModel(`{}`); '
                    'self.__KeyValueFromInt(`skin`, {});'.format(
                        cust_model,
                        CUBE_SKINS[pair.cube_type.type].spawn_skin(spawn_paint),
                    ),
                ))

        drop_cube = cube = should_respawn = None

        # One or both of the cube ents we make.
        cubes: list[Entity] = []

        # Transfer addon outputs to the pair data.
        for addon in pair.addons:
            for out_type, out_list in addon.outputs.items():
                pair.outputs[out_type].extend(out_list)

        # Generate the outputs to paint the cubes.
        if pair.cube_type.type is CubeEntType.franken and pair.paint_type is not None:
            pair.outputs[CubeOutputs.SPAWN].append(Output(
                'Spawn',
                'cube_addon_painter',
                'Start',
            ))
            pair.outputs[CubeOutputs.SPAWN].append(Output(
                'Spawn',
                'cube_addon_painter',
                'Kill',
                delay=0.1,
            ))

        if pair.dropper:
            assert pair.drop_type is not None
            pos = Vec.from_str(pair.dropper['origin'])
            pos += pair.spawn_offset @ Angle.from_str(pair.dropper['angles'])
            has_addon, drop_cube = make_cube(vmf, pair, pos, True, bounce_in_map, speed_in_map)
            cubes.append(drop_cube)

            # We can't refer to the dropped cube directly because of the template name
            # mangling.
            drop_cube['targetname'] = conditions.local_name(
                pair.dropper, 'box',
            )

            # Implement the outputs.

            for temp_out in pair.outputs[CubeOutputs.FIZZLED]:
                drop_cube.add_out(setup_output(temp_out, pair.dropper, 'OnFizzled'))

            drop_done_name, drop_done_command = pair.drop_type.out_finish_drop
            for temp_out in pair.outputs[CubeOutputs.DROP_DONE]:
                pair.get_kv_setter(drop_done_name).add_out(setup_output(
                    temp_out,
                    pair.dropper,
                    drop_done_command,
                    self_name='!activator',
                ))

            # We always enable portal funnelling after dropping,
            # since we turn it off inside.
            pair.get_kv_setter(drop_done_name).add_out(Output(
                drop_done_command,
                '!activator',
                'EnablePortalFunnel',
            ))

            # We FireUser4 after the template ForceSpawns.
            for temp_out in pair.outputs[CubeOutputs.SPAWN]:
                out = setup_output(
                    temp_out,
                    pair.dropper,
                    'OnUser4',
                )
                # After first firing, it deletes, so it doesn't trigger after.
                out.only_once = True
                drop_cube.add_out(out)

            if pair.superpos is not None:
                # Link up our half to the swapper instance.
                superpos_script = conditions.local_name(pair.superpos.swap_inst, 'script')
                kind = 'Ghost' if pair.is_superpos_ghost else 'Real'
                pair.get_kv_setter(drop_done_name).add_out(Output(
                    drop_done_command, superpos_script, 'CallScriptFunction',
                    'Spawned' + kind,
                ))
                drop_cube.outputs.append(Output(
                    'OnFizzled', superpos_script, 'CallScriptFunction',
                    'Fizzled' + kind,
                ))
                vmf.create_ent(
                    'comp_kv_setter',
                    origin=pair.superpos.swap_inst['origin'],
                    target=conditions.local_name(
                        pair.superpos.swap_inst,
                        'tele_ghost' if pair.is_superpos_ghost else 'tele_real',
                    ),
                    mode='kv',
                    kv_name='filtername',
                    kv_value_global=conditions.local_name(pair.dropper, pair.drop_type.filter_name),
                )
                # Ghost doesn't support the Fizzle input, hook that up ourselves.
                if pair.is_superpos_ghost:
                    pair.get_kv_setter(drop_done_name).add_out(Output(
                        drop_done_command,'!activator',
                        'CallScriptFunction','Spawned',
                    ))
                    drop_cube.outputs.append(Output(
                        'OnUser1', '!self',
                        'CallScriptFunction', 'FizzleIfOutside',
                    ))

            # After it spawns, swap the cube type back to the actual value
            # for the item. Then it'll properly behave with gel, buttons,
            # etc.
            if drop_cube['CubeType'] == CUBE_ID_CUSTOM_MODEL_HACK:
                drop_cube.add_out(Output(
                    'OnUser4',
                    '!self',
                    'AddOutput',
                    'CubeType ' + str(ENT_TYPE_INDEX[pair.cube_type.type]),
                    only_once=True,
                ))

            # For frankenTurrets, we need to disable funnelling via input.
            if pair.cube_type.type is CubeEntType.franken:
                drop_cube.add_out(Output(
                    'OnUser4',
                    '!self',
                    'DisablePortalFunnel',
                    only_once=True,
                ))

                # For FrankenTurrets, we also pop it out after finishing
                # spawning.
                pair.get_kv_setter(drop_done_name).add_out(Output(
                    drop_done_command,
                    '!activator',
                    'BecomeMonster',
                    delay=0.2,
                ))

            # Add output to respawn the cube.
            should_respawn = pair.dropper.fixup.bool('$disable_autorespawn')
            if pair.drop_type.id == VALVE_DROPPER_ID:
                # Valve's dropper makes these match the name (inverted to
                # the checkboxes in the editor), but in custom items they
                # match the checkboxes.
                should_respawn = not should_respawn

            if should_respawn:
                drop_respawn_name, drop_respawn_command = pair.drop_type.in_respawn
                drop_cube.add_out(Output(
                    'OnFizzled',
                    conditions.local_name(pair.dropper, drop_respawn_name),
                    drop_respawn_command,
                ))

                # Voice outputs for when cubes are to be replaced.
                if pair.cube_type.is_companion:
                    CubeVoiceEvents.RESPAWN_CCUBE.add_out(drop_cube, 'OnFizzled')
                else:
                    CubeVoiceEvents.RESPAWN_NORM.add_out(drop_cube, 'OnFizzled')

        if pair.cube:
            pos = Vec.from_str(pair.cube['origin'])
            pos += Vec(z=DROPPERLESS_OFFSET) @ Angle.from_str(pair.cube['angles'])
            has_addon, cube = make_cube(vmf, pair, pos, False, bounce_in_map, speed_in_map)
            cubes.append(cube)
            cube_name = cube['targetname'] = conditions.local_name(pair.cube, 'box')

            if has_addon:
                # Addon items for safety get one template each.
                cube_temp = vmf.create_ent(
                    classname='point_template',
                    targetname='@template_spawn_3',
                    spawnflags=2,
                    origin=pos + (0, 0, 48),
                    Template01=cube_name,
                    Template02=conditions.local_name(pair.cube, 'cube_addon_*'),
                )
            else:
                if dropperless_temp_count == 16:
                    dropperless_temp = vmf.create_ent(
                        classname='point_template',
                        targetname='@template_spawn_3',
                        spawnflags=2,
                        # Put it above the cube for aesthetics.
                        origin=pos + (0, 0, 48),
                    )
                    dropperless_temp_count = 0
                dropperless_temp_count += 1
                dropperless_temp[
                    'Template{:02g}'.format(dropperless_temp_count)
                ] = cube_name
                cube_temp = dropperless_temp

            for temp_out in pair.outputs[CubeOutputs.FIZZLED]:
                cube.add_out(setup_output(temp_out, pair.cube, 'OnFizzled'))

            # For consistency with the dropped cube, add a User1 output
            # that fizzles it.
            cube.add_out(Output('OnUser1', '!self', 'Dissolve'))

            for temp_out in pair.outputs[CubeOutputs.SPAWN]:
                cube_temp.add_out(setup_output(
                    temp_out,
                    pair.cube,
                    'OnEntitySpawned',
                    self_name=cube_name,
                ))

            for temp_out in pair.outputs[CubeOutputs.DROP_DONE]:
                output = setup_output(
                    temp_out,
                    pair.cube,
                    'OnEntitySpawned',
                    self_name=cube_name,
                )
                output.delay += 0.5
                cube_temp.add_out(output)

            # After it spawns, swap the cube type back to the actual value
            # for the item. Then it'll properly behave with gel, buttons,
            # etc.
            if cube['CubeType'] == CUBE_ID_CUSTOM_MODEL_HACK:
                cube_temp.add_out(Output(
                    'OnEntitySpawned',
                    cube_name,
                    'AddOutput',
                    'CubeType ' + str(ENT_TYPE_INDEX[pair.cube_type.type]),
                ))

            # Voice event for when the cube is destroyed, and
            # it won't be replaced.
            if pair.dropper is None:
                if pair.cube_type.is_companion:
                    CubeVoiceEvents.DESTROY_CCUBE.add_out(cube, 'OnFizzled')
                else:
                    CubeVoiceEvents.DESTROY_NORM.add_out(cube, 'OnFizzled')

        if drop_cube is not None and cube is not None:
            # We have both - it's a linked cube and dropper.
            # We need to trigger commands back and forth for this.

            # Trigger the dropper when fizzling a cube.
            if should_respawn:
                drop_respawn_name, drop_respawn_command = pair.drop_type.in_respawn
                cube.add_out(Output(
                    'OnFizzled',
                    conditions.local_name(pair.dropper, drop_respawn_name),
                    drop_respawn_command,
                ))

                # It is getting replaced.
                if pair.cube_type.is_companion:
                    CubeVoiceEvents.RESPAWN_CCUBE.add_out(cube, 'OnFizzled')
                else:
                    CubeVoiceEvents.RESPAWN_NORM.add_out(cube, 'OnFizzled')

            # Fizzle the cube when triggering the dropper.
            drop_fizzle_name, drop_fizzle_command = pair.drop_type.out_start_drop
            pair.get_kv_setter(drop_fizzle_name).add_out(Output(
                drop_fizzle_command,
                cube['targetname'],
                'Dissolve',
                only_once=True,
            ))

        # Voice events to add to all cubes.
        for cube in cubes:
            if pair.cube_type.type is CubeEntType.franken:
                CubeVoiceEvents.PICKUP_FRANKEN.add_out(cube, 'OnPlayerPickup')
            CubeVoiceEvents.PICKUP_ANY.add_out(cube, 'OnPlayerPickup')
