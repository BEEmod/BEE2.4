"""Implements fizzler/laserfield generation and customisation."""
import random
from collections import defaultdict, namedtuple
from typing import Dict, List, Optional, Tuple, Iterator, Set, Callable

import itertools
from enum import Enum

import utils
import srctools.logger
import srctools.vmf
from srctools.vmf import VMF, Solid, Entity, Side, Output
from srctools import Property, NoKeyError, Vec, Matrix, Angle
from precomp import (
    instance_traits, tiling, instanceLocs,
    texturing,
    connections,
    options,
    packing,
    template_brush,
    conditions,
)
import consts


LOGGER = srctools.logger.get_logger(__name__)

FIZZ_TYPES = {}  # type: Dict[str, FizzlerType]

FIZZLERS = {}  # type: Dict[str, Fizzler]

# Fizzler textures are higher-res than laserfields.
FIZZLER_TEX_SIZE = 1024
LASER_TEX_SIZE = 512

# A few positions for material_modify_control,
# so they aren't on top of each other.
MATMOD_OFFSETS = [
    Vec(0,   0, -32),
    Vec(0,  16, -32),
    Vec(0, -16, -64),
    Vec(0,   0,  32),
] * 4  # Just in case there happens to be more textures.


class TexGroup(Enum):
    """Types of textures used for fizzlers."""
    # These set for fizzlers.
    LEFT = 'left'
    RIGHT = 'right'
    CENTER = 'center'
    SHORT = 'short'  # 128 field

    # Other types:
    FITTED = 'fitted'  # If set, use this for all - scaled like laserfields do.
    # If set, it's an invisible trigger/clip - just apply this to all sides.
    TRIGGER = 'trigger'

    # Special case - for Tag fizzlers, when it's on for that side.
    TAG_ON_LEFT = 'tag_left'
    TAG_ON_RIGHT = 'tag_right'
    TAG_ON_CENTER = 'tag_center'
    TAG_ON_SHORT = 'tag_short'


class ModelName(Enum):
    """The method used to give names for models."""
    SAME = 'same'  # The same as the base
    UNIQUE = 'unique'  # Add the local suffix + a random number
    PAIRED = 'paired'  # Each pair gets the same number.
    LOCAL = 'local'  # Use a base_inst-suffix combo.


class FizzInst(Enum):
    """Categories of model instances.

    For all instances, Z is along the fizzler (out of the wall), x is the
    surface normal, and Y is 'upward'.
    """
    ALL = 'model'  # Used for all positions like normal.
    PAIR_MIN = 'model_left'  # min side
    PAIR_MAX = 'model_right'  # max side
    PAIR_SINGLE = 'model_single'  # Replaces min and max for single case
    GRID = 'model_mid'  # One in each block the fizzler is in.

    BASE = 'base_inst'  # If set, swap the instance to this.

MatModify = namedtuple('MatModify', 'name mat_var')
FizzBeam = namedtuple('FizzBeam', 'offset keys speed_min speed_max')


def read_configs(conf: Property) -> None:
    """Read in the fizzler data."""
    for fizz_conf in conf.find_all('Fizzlers', 'Fizzler'):
        fizz = FizzlerType.parse(fizz_conf)

        if fizz.id in FIZZ_TYPES:
            raise ValueError('Duplicate fizzler ID "{}"'.format(fizz.id))

        FIZZ_TYPES[fizz.id] = fizz

    LOGGER.info('Loaded {} fizzlers.', len(FIZZ_TYPES))

    if options.get(str, 'game_id') != utils.STEAM_IDS['APTAG']:
        return
    # In Aperture Tag, we don't have portals. For fizzler types which block
    # portals (trigger_portal_cleanser), additionally fizzle paint.
    for fizz in FIZZ_TYPES.values():
        for brush in fizz.brushes:
            if brush.keys['classname'].casefold() == 'trigger_portal_cleanser':
                brush_name = brush.name
                # Retrieve what key is used for start-disabled.
                brush_start_disabled = None
                for key_map in [brush.keys, brush.local_keys]:
                    if brush_start_disabled is None:
                        for key, value in key_map.items():
                            if key.casefold() == 'startdisabled':
                                brush_start_disabled = value
                                break
                break  # Jump past else.
        else:
            # No fizzlers in this item.
            continue

        # Add a paint fizzler brush to these fizzlers.
        fizz.brushes.append(FizzlerBrush(
            brush_name,
            textures={
                TexGroup.TRIGGER: consts.Tools.TRIGGER,
            },
            keys={
                'classname': 'trigger_paint_cleanser',
                'startdisabled': brush_start_disabled or '0',
                'spawnflags': '9',
            },
            local_keys={},
            outputs=[],
            singular=True,
        ))


class FizzlerType:
    """Implements a specific fizzler type."""
    def __init__(
        self,
        fizz_id: str,
        item_ids: List[str],
        voice_attrs: List[str],
        pack_lists: Set[str],
        pack_lists_static: Set[str],
        model_local_name: str,
        model_name_type: ModelName,
        nodraw_behind: bool,
        brushes: List['FizzlerBrush'],
        beams: List['FizzBeam'],
        inst: Dict[Tuple[FizzInst, bool], List[str]],

        temp_brush_keys: Property,
        temp_min: Optional[str],
        temp_max: Optional[str],
        temp_single: Optional[str],
    ):
        self.id = fizz_id

        # The item ID(s) this fizzler is produced from, optionally
        # with a :laserfield or :fizzler suffix to choose a specific
        # type.
        self.item_ids = item_ids

        # The brushes to generate.
        self.brushes = brushes

        # Beams to generate.
        self.beams = beams

        self.voice_attrs = voice_attrs

        # Packfiles to pack if we're in the map.
        self.pack_lists = pack_lists
        self.pack_lists_static = pack_lists_static

        # The method used to name the models.
        self.model_naming = model_name_type
        self.model_name = model_local_name
        # Instances to use - FizzInst, is_static -> list of instances.
        self.inst = inst

        # If set, nodraw the 128x32 area behind the fizzler - to allow
        # the Clean model to stick through.
        self.nodraw_behind = nodraw_behind

        # If set, add a brush ent using templates.
        self.temp_single = temp_single
        self.temp_max = temp_max
        self.temp_min = temp_min
        self.temp_brush_keys = temp_brush_keys

    @classmethod
    def parse(cls, conf: Property):
        """Read in a fizzler from a config."""
        fizz_id = conf['id']
        item_ids = [
            prop.value.casefold()
            for prop in
            conf.find_all('item_id')
        ]

        try:
            model_name_type = ModelName(conf['NameType', 'same'].casefold())
        except ValueError:
            LOGGER.warning('Bad model name type: "{}"', conf['NameType'])
            model_name_type = ModelName.SAME

        model_local_name = conf['ModelName', '']
        if not model_local_name:
            # We can't rename without a local name.
            model_name_type = ModelName.SAME

        inst: Dict[Tuple[FizzInst, bool], List[str]] = {}
        for inst_type, is_static in itertools.product(FizzInst, (False, True)):
            inst_type_name = inst_type.value + ('_static' if is_static else '')
            inst[inst_type, is_static] = instances = [
                file
                for prop in conf.find_all(inst_type_name)
                for file in instanceLocs.resolve(prop.value)
            ]
            # Allow specifying weights to bias model locations
            weights = conf[inst_type_name + '_weight', '']
            if weights:
                # Produce the weights, then process through the original
                # list to build a new one with repeated elements.
                inst[inst_type, is_static] = instances = [
                    instances[i]
                    for i in conditions.weighted_random(len(instances), weights)
                ]
            # If static versions aren't given, reuse non-static ones.
            # We do False, True so it's already been calculated.
            if not instances and is_static:
                inst[inst_type, True] = inst[inst_type, False]

        voice_attrs = []
        for prop in conf.find_all('Has'):
            if prop.has_children():
                for child in prop:
                    voice_attrs.append(child.name.casefold())
            else:
                voice_attrs.append(prop.value.casefold())

        pack_lists = {
            prop.value
            for prop in
            conf.find_all('Pack')
        }
        pack_lists_static = {
            prop.value
            for prop in
            conf.find_all('PackStatic')
        }

        brushes = [
            FizzlerBrush.parse(prop)
            for prop in
            conf.find_all('Brush')
        ]

        beams = []  # type: List[FizzBeam]
        for beam_prop in conf.find_all('Beam'):
            offsets = [
                Vec.from_str(off.value)
                for off in
                beam_prop.find_all('pos')
            ]
            keys = Property('', [
                beam_prop.find_key('Keys', []),
                beam_prop.find_key('LocalKeys', [])
            ])
            beams.append(FizzBeam(
                offsets,
                keys,
                beam_prop.int('RandSpeedMin', 0),
                beam_prop.int('RandSpeedMax', 0),
            ))

        try:
            temp_conf = conf.find_key('TemplateBrush')
        except NoKeyError:
            temp_brush_keys = temp_min = temp_max = temp_single = None
        else:
            temp_brush_keys = Property('--', [
                temp_conf.find_key('Keys'),
                temp_conf.find_key('LocalKeys', []),
            ])

            # Find and load the templates.
            temp_min = temp_conf['Left', None]
            temp_max = temp_conf['Right', None]
            temp_single = temp_conf['Single', None]

        return FizzlerType(
            fizz_id,
            item_ids,
            voice_attrs,
            pack_lists,
            pack_lists_static,
            model_local_name,
            model_name_type,
            conf.bool('nodraw_behind'),
            brushes,
            beams,
            inst,
            temp_brush_keys,
            temp_min,
            temp_max,
            temp_single,
        )


class Fizzler:
    """Represents a specific pair of emitters and a field."""
    def __init__(
        self,
        fizz_type: FizzlerType,
        up_axis: Vec,
        base_inst: Entity,
        emitters: List[Tuple[Vec, Vec]]
    ) -> None:
        self.fizz_type = fizz_type
        self.base_inst = base_inst
        self.up_axis = up_axis  # Pointing toward the 'up' side of the field.
        self.emitters = emitters  # Pairs of left, right positions.

        self.has_cust_position = False  # If the emitters are a custom layout
        # True if the fizzler is in the original position, and so we need
        # to adjust tiles for the sides.
        self.embedded = True

        # Special case - for TAG fizzlers, if that side is enabled.
        # We generate the triggers elsewhere.
        self.tag_on_pos = self.tag_on_neg = False

    def forward(self) -> Vec:
        """The axis moving from one side to another."""
        return (self.emitters[0][1] - self.emitters[0][0]).norm()

    def normal(self) -> Vec:
        """The axis moving in and out of the surface."""
        return abs(self.up_axis.cross(self.forward()))

    def gen_flinch_trigs(self, vmf: VMF, name: str, start_disabled: str) -> None:
        """For deadly fizzlers optionally make them safer.

        This adds logic to force players
        back instead when walking into the field.
        Only applies to vertical triggers.
        """
        normal = abs(self.normal())  # type: Vec

        # Horizontal fizzlers would just have you fall through.
        if normal.z:
            return

        # Disabled.
        if not options.get_itemconf(('VALVE_FIZZLER', 'FlinchBack'), False):
            return

        # Make global entities if not present.
        if '_fizz_flinch_hurt' not in vmf.by_target:
            glob_ent_loc = options.get(Vec, 'global_ents_loc')
            vmf.create_ent(
                classname='point_hurt',
                targetname='_fizz_flinch_hurt',
                Damage=10,  # Just for visuals and sounds.
                # BURN | ENERGYBEAM | PREVENT_PHYSICS_FORCE
                DamageType=8 | 1024 | 2048,
                DamageTarget='!activator',  # Hurt the triggering player.
                DamageRadius=1,  # Target makes this unused.
                origin=glob_ent_loc,
            )

        # We need two catapults - one for each side.
        neg_brush = vmf.create_ent(
            targetname=name,
            classname='trigger_catapult',
            spawnflags=1,  # Players only.
            origin=self.base_inst['origin'],
            physicsSpeed=0,
            playerSpeed=96,
            launchDirection=(-normal).to_angle(),
            startDisabled=start_disabled,
        )
        neg_brush.add_out(Output('OnCatapulted', '_fizz_flinch_hurt', 'Hurt'))

        pos_brush = neg_brush.copy()
        pos_brush['launchDirection'] = normal.to_angle()
        vmf.add_ent(pos_brush)

        for seg_min, seg_max in self.emitters:
            neg_brush.solids.append(vmf.make_prism(
                p1=(seg_min
                    - 4 * normal
                    - 64 * self.up_axis
                    ),
                p2=seg_max + 64 * self.up_axis,
                mat=consts.Tools.TRIGGER,
            ).solid)
            pos_brush.solids.append(vmf.make_prism(
                p1=seg_min - 64 * self.up_axis,
                p2=(seg_max
                    + 4 * normal
                    + 64 * self.up_axis
                    ),
                mat=consts.Tools.TRIGGER,
            ).solid)

    def set_tiles_behind_models(self, origin: Vec, normal: Vec, to_nodraw: bool):
        """Set the tile surface behind a model to specific values.

        position is the center-point on the wall.
        normal is the direction out of the model.
        If to_nodraw is true, set to nodraw. Otherwise, set to 4x4 if grid aligned.
        """
        up_axis = self.up_axis.axis()
        u_axis, v_axis = Vec.INV_AXIS[normal.axis()]

        if origin % 64 == (0, 0, 0):
            # Aligned with the 64-grid - it's centered in the tile.
            # That means we need to set special values.

            # Don't bother if not nodrawing.
            if not to_nodraw:
                return

            tile = tiling.TILES[
                (origin - 64 * normal).as_tuple(),
                normal.as_tuple()
            ]  # type: tiling.TileDef

            # Reversed?
            if up_axis == u_axis:
                tile.set_fizz_orient('v')
            elif up_axis == v_axis:
                tile.set_fizz_orient('u')  # type: ignore
            else:
                LOGGER.error(
                    'Not U or V?: {} @ {} ("{}")',
                    origin,
                    normal,
                    self.base_inst['targetname'],
                )
        elif to_nodraw:
            # Side-aligned, we just edit quarter-tiles.
            for off in [-48, -16, 16, 48]:
                tiling.edit_quarter_tile(
                    origin + Vec.with_axes(up_axis, off),
                    normal,
                    tiling.TileType.NODRAW,
                )
        else:
            # Swap surfaces to 4x4 sizes.
            for off in [-48, -16, 16, 48]:
                try:
                    tile, u, v = tiling.find_tile(
                        origin + Vec.with_axes(up_axis, off),
                        normal,
                    )
                except KeyError:
                    continue
                orig = tile[u, v]
                if orig.is_tile and not orig.is_4x4:
                    tile[u, v] = tiling.TileType.with_color_and_size(
                        tiling.TileSize.TILE_4x4,
                        orig.color,
                    )

    def _gen_fizz_border(self, vmf: VMF, seg_min: Vec, seg_max: Vec):
        """Generate borders above/below fizzlers."""
        up = abs(self.up_axis)
        forward = (seg_max - seg_min).norm()
        norm_dir = self.normal().axis()

        tiledefs_up: List[tiling.TileDef] = []
        tiledefs_dn: List[tiling.TileDef] = []

        overlay_len = int((seg_max - seg_min).mag())

        # We need to snap the axis normal_axis to the grid, since it could
        # be forward or back.
        min_pos = seg_min.copy()
        min_pos[norm_dir] = min_pos[norm_dir] // 128 * 128 + 64

        for offset in range(64, overlay_len, 128):
            # Each position on top or bottom, inset 64 from each end
            pos = min_pos + offset * forward
            try:
                top_tile = tiling.TILES[
                    (pos + 128 * up).as_tuple(),
                    (-up).as_tuple()
                ]
            except KeyError:
                pass
            else:
                if any(tile.is_tile for u, v, tile in top_tile):
                    tiledefs_up.append(top_tile)
            try:
                btm_tile = tiling.TILES[
                    (pos - 128 * up).as_tuple(),
                    up.as_tuple()
                ]
            except KeyError:
                pass
            else:
                if any(tile.is_tile for u, v, tile in btm_tile):
                    tiledefs_dn.append(btm_tile)

        if not tiledefs_up and not tiledefs_dn:
            return

        overlay_thickness = options.get(int, 'fizz_border_thickness')
        overlay_repeat = options.get(int, 'fizz_border_repeat')
        flip_uv = options.get(bool, 'fizz_border_vertical')

        if flip_uv:
            u_rep = 1.0
            v_rep = overlay_len / overlay_repeat
        else:
            u_rep = overlay_len / overlay_repeat
            v_rep = 1.0

        cent_pos = (seg_min + seg_max) / 2

        if tiledefs_up:
            over = srctools.vmf.make_overlay(
                vmf,
                normal=-up,
                origin=cent_pos + 64 * up,
                uax=forward * overlay_len,
                vax=Vec.cross(up, forward) * overlay_thickness,
                material=texturing.SPECIAL.get(cent_pos + 64 * up, 'fizz_border'),
                surfaces=[],
                u_repeat=u_rep,
                v_repeat=v_rep,
                swap=flip_uv,
            )
            for tile in tiledefs_up:
                tile.bind_overlay(over)

        if tiledefs_dn:
            over = srctools.vmf.make_overlay(
                vmf,
                normal=up,
                origin=cent_pos - 64 * up,
                uax=forward * overlay_len,
                vax=Vec.cross(-up, forward) * overlay_thickness,
                material=texturing.SPECIAL.get(cent_pos - 64 * up, 'fizz_border'),
                surfaces=[],
                u_repeat=u_rep,
                v_repeat=v_rep,
                swap=flip_uv,
            )
            for tile in tiledefs_dn:
                tile.bind_overlay(over)


class FizzlerBrush:
    """A brush-set used in a fizzler."""
    def __init__(
        self,
        name: str,
        textures: Dict[TexGroup, Optional[str]],
        keys: Dict[str, str],
        local_keys: Dict[str, str],
        outputs: List[Output],
        thickness: float=2.0,
        stretch_center: bool=True,
        side_color: Vec=None,
        singular: bool=False,
        set_axis_var: bool=False,
        mat_mod_name: str=None,
        mat_mod_var: str=None,
    ) -> None:
        self.keys = keys
        self.local_keys = local_keys
        self.name = name  # Local name of the fizzler brush.
        self.outputs = list(outputs)
        # Width of the brush.
        self.thickness = thickness
        # If set, a colour to apply to the sides.
        self.side_color = side_color

        # Use only one brush for all the parts of this.
        self.singular = singular

        # If set, stretch the center to the brush size.
        self.stretch_center = stretch_center

        # If set, store a 'axis' variable in VScript to the plane.
        self.set_axis_var = set_axis_var

        # If set, add a material_modify_control to control these brushes.
        if mat_mod_var is not None and not mat_mod_var.startswith('$'):
            mat_mod_var = '$' + mat_mod_var
            if mat_mod_name is None:
                mat_mod_name = 'mat_mod'
            if not singular:
                LOGGER.warning('Material modify requires Singular!')
                self.singular = True

        self.mat_mod_var = mat_mod_var
        self.mat_mod_name = mat_mod_name

        self.textures = {}  # type: Dict[TexGroup, Optional[str]]
        for group in TexGroup:
            self.textures[group] = textures.get(group, None)

    @classmethod
    def parse(cls, conf: Property) -> 'FizzlerBrush':
        """Parse from a config file."""
        if 'side_color' in conf:
            side_color = conf.vec('side_color')
        else:
            side_color = None

        outputs = [
            Output.parse(prop)
            for prop in
            conf.find_children('Outputs')
        ]

        textures = {}
        for group in TexGroup:
            textures[group] = conf['tex_' + group.value, None]

        keys = {
            prop.name: prop.value
            for prop in
            conf.find_children('keys')
        }

        local_keys = {
            prop.name: prop.value
            for prop in
            conf.find_children('localkeys')
        }

        if 'classname' not in keys:
            raise ValueError(
                'Fizzler Brush "{}" does not have a classname!'.format(
                conf['name'],
                )
            )

        return FizzlerBrush(
            name=conf['name'],
            textures=textures,
            keys=keys,
            local_keys=local_keys,
            outputs=outputs,
            thickness=conf.float('thickness', 2.0),
            stretch_center=conf.bool('stretch_center', True),
            side_color=side_color,
            singular=conf.bool('singular'),
            mat_mod_name=conf['mat_mod_name', None],
            mat_mod_var=conf['mat_mod_var', None],
            set_axis_var=conf.bool('set_axis_var'),
        )

    def _side_color(
        self,
        side: Side,
        normal: Vec,
        min_pos: Vec,
        used_tex_func: Callable[[str], None],
    ) -> None:
        """Output the side texture for fields.

        used_tex_func is called with each material we use.
        """
        if not self.side_color:
            # Just apply nodraw.
            side.mat = consts.Tools.NODRAW
            return

        # Produce a hex colour string, and use that as the material name.
        side.mat = 'bee2/fizz_sides/side_color_{:02X}{:02X}{:02X}'.format(
            round(self.side_color.x * 255),
            round(self.side_color.y * 255),
            round(self.side_color.z * 255),
        )
        used_tex_func(side.mat)

        # FLip orientation if needed.
        if not side.uaxis.vec().dot(normal):
            side.vaxis, side.uaxis = side.uaxis, side.vaxis
        # The texture width is 32 pixels.
        side.scale = self.thickness / 32
        side.uaxis.offset = 16 + 2 * self.thickness * side.uaxis.vec().dot(min_pos) % 32

    def generate(
        self,
        vmf: VMF,
        fizz: Fizzler,
        neg: Vec,
        pos: Vec,
        used_tex_func: Callable[[str], None],
    ) -> Iterator[Solid]:
        """Generate the actual brush.

        used_tex will be filled with the textures used.
        """
        diff = neg - pos
        # Size of fizzler
        field_length = diff.mag()
        # Direction it extends across.
        field_axis = diff.norm()

        # Out of the fizzler.
        normal = fizz.normal()

        origin = (pos + neg)/2

        # If either of these, we only need 1 brush.
        trigger_tex = self.textures[TexGroup.TRIGGER]
        fitted_tex = self.textures[TexGroup.FITTED]
        # If we don't have this, we can't be a single brush.
        short_tex = self.textures[TexGroup.SHORT]

        if trigger_tex or fitted_tex:
            tex_size = LASER_TEX_SIZE
        else:
            # Fizzlers are larger resolution..
            tex_size = FIZZLER_TEX_SIZE

        # Treat 127.9999 as 128, etc.
        if (round(field_length) == 128 and short_tex) or trigger_tex or fitted_tex:
            # We need only one brush.
            brush = vmf.make_prism(
                p1=(origin
                    + (self.thickness/2) * normal
                    + 64 * fizz.up_axis
                    + (field_length/2) * field_axis
                ),
                p2=(origin
                    - (self.thickness / 2) * normal
                    - 64 * fizz.up_axis
                    - (field_length / 2) * field_axis
                ),
            ).solid  # type: Solid
            yield brush
            if trigger_tex:
                for side in brush.sides:
                    side.mat = trigger_tex
                used_tex_func(trigger_tex)
            else:
                for side in brush.sides:
                    side_norm = side.normal()

                    if abs(side_norm) == abs(fizz.up_axis):
                        self._side_color(side, normal, neg, used_tex_func)

                    if abs(side_norm) != normal:
                        continue

                    side.mat = fitted_tex or self.textures[
                        TexGroup.TAG_ON_SHORT if (
                            fizz.tag_on_pos
                            if normal.dot(side_norm) > 0 else
                            fizz.tag_on_neg
                        ) else TexGroup.SHORT
                    ]
                    used_tex_func(side.mat)

                    self._texture_fit(
                        side,
                        tex_size,
                        field_length,
                        fizz,
                        neg,
                        pos,
                        bool(fitted_tex),
                    )

                    if not self.stretch_center:
                        side.uaxis.scale = 0.25
        else:
            # Generate the three brushes for fizzlers.
            if round(field_length) <= 128:
                side_len = field_length / 2
                center_len = 0
            else:
                # Bugfix - the boundary texture wrapping causes
                # artifacts to appear at the join, we need to avoid a small
                # amount of that texture.
                side_len = 63
                center_len = field_length - 126

            brush_left = vmf.make_prism(
                p1=(origin
                    - (self.thickness / 2) * normal
                    - 64 * fizz.up_axis
                    - (side_len - field_length/2) * field_axis
                    ),
                p2=(origin
                    + (self.thickness / 2) * normal
                    + 64 * fizz.up_axis
                    + (field_length / 2) * field_axis
                    ),
            ).solid  # type: Solid
            yield brush_left

            brush_right = vmf.make_prism(
                p1=(origin
                    - (self.thickness / 2) * normal
                    - 64 * fizz.up_axis
                    - (field_length / 2) * field_axis
                    ),
                p2=(origin
                    + (self.thickness / 2) * normal
                    + 64 * fizz.up_axis
                    + (side_len - field_length/2) * field_axis
                    ),
            ).solid  # type: Solid
            yield brush_right

            if center_len:
                brush_center = vmf.make_prism(
                    p1=(origin
                        - (self.thickness / 2) * normal
                        - 64 * fizz.up_axis
                        - (center_len / 2) * field_axis
                        ),
                    p2=(origin
                        + (self.thickness / 2) * normal
                        + 64 * fizz.up_axis
                        + (center_len/2) * field_axis
                        ),
                ).solid  # type: Solid
                yield brush_center

                brushes = [
                    (brush_left, field_axis, 64),
                    (brush_center, None, center_len),
                    (brush_right, -field_axis, 64),
                ]
                used_tex_func(self.textures[TexGroup.CENTER])
            else:
                brushes = [
                    (brush_left, field_axis, side_len),
                    (brush_right, -field_axis, side_len),
                ]

            for brush, model_normal, brush_length in brushes:
                for side in brush.sides:
                    side_norm = side.normal()
                    if abs(side_norm) == abs(fizz.up_axis):
                        self._side_color(side, normal, neg, used_tex_func)

                    if abs(side_norm) != abs(normal):
                        continue

                    tag_enabled = (
                        fizz.tag_on_pos
                        if normal.dot(side_norm) > 0 else
                        fizz.tag_on_neg
                    )

                    self._texture_fit(
                        side,
                        FIZZLER_TEX_SIZE,
                        brush_length,
                        fizz,
                        neg,
                        pos,
                    )

                    if model_normal is None:
                        # Center textures.
                        side.mat = self.textures[
                            TexGroup.TAG_ON_CENTER
                            if tag_enabled else
                            TexGroup.CENTER
                        ]
                        if not self.stretch_center:
                            side.uaxis.scale = 0.25
                    else:
                        # For left and right, we need to figure out what
                        # direction the texture should be in. The uaxis is
                        # in the direction of the surface.
                        if side.uaxis.vec() == model_normal:
                            side.mat = self.textures[
                                TexGroup.TAG_ON_RIGHT
                                if tag_enabled else
                                TexGroup.RIGHT
                            ]
                        else:
                            side.mat = self.textures[
                                TexGroup.TAG_ON_LEFT
                                if tag_enabled else
                                TexGroup.LEFT
                            ]
                    used_tex_func(side.mat)

    def _texture_fit(
        self,
        side: Side,
        tex_size: float,
        field_length: float,
        fizz: Fizzler,
        neg: Vec,
        pos: Vec,
        is_laserfield=False,
    ) -> None:
        """Calculate the texture offsets required for fitting a texture."""
        if side.vaxis.vec() != -fizz.up_axis:
            # Rotate it
            rot_angle = side.normal().rotation_around()
            for _ in range(4):
                side.uaxis = side.uaxis.rotate(rot_angle)
                side.vaxis = side.vaxis.rotate(rot_angle)
                if side.vaxis.vec() == -fizz.up_axis:
                    break
            else:
                LOGGER.warning("Can't fix rotation for {} -> {}", side.vaxis, fizz.up_axis)

        side.uaxis.offset = -(tex_size / field_length) * neg.dot(side.uaxis.vec())
        side.vaxis.offset = -(tex_size / 128) * neg.dot(side.vaxis.vec())

        #  The above fits it correctly, except it's vertically half-offset.
        # For laserfields that's what we want, for fizzlers we want it normal.
        if not is_laserfield:
            side.vaxis.offset += tex_size / 2

        side.uaxis.scale = field_length / tex_size
        side.vaxis.scale = 128 / tex_size

        side.uaxis.offset %= tex_size
        side.vaxis.offset %= tex_size


def parse_map(vmf: VMF, voice_attrs: Dict[str, bool]) -> None:
    """Analyse fizzler instances to assign fizzler types.

    Instance traits are required.
    The model instances and brushes will be removed from the map.
    Needs connections to be parsed.
    """

    # Item ID and model skin -> fizzler type
    fizz_types = {}  # type: Dict[Tuple[str, int], FizzlerType]

    for fizz_type in FIZZ_TYPES.values():
        for item_id in fizz_type.item_ids:
            if ':' in item_id:
                item_id, barrier_type = item_id.split(':')
                if barrier_type == 'laserfield':
                    barrier_skin = 2
                elif barrier_type == 'fizzler':
                    barrier_skin = 0
                else:
                    LOGGER.error('Invalid barrier type ({}) for "{}"!', barrier_type, item_id)
                    fizz_types[item_id, 0] = fizz_type
                    fizz_types[item_id, 2] = fizz_type
                    continue
                fizz_types[item_id, barrier_skin] = fizz_type
            else:
                fizz_types[item_id, 0] = fizz_type
                fizz_types[item_id, 2] = fizz_type

    fizz_bases = {}  # type: Dict[str, Entity]
    fizz_models = defaultdict(list)  # type: Dict[str, List[Entity]]

    # Position and normal -> name, for output relays.
    fizz_pos = {}  # type: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], str]

    # First use traits to gather up all the instances.
    for inst in vmf.by_class['func_instance']:
        traits = instance_traits.get(inst)
        if 'fizzler' not in traits:
            continue

        name = inst['targetname']

        if 'fizzler_model' in traits:
            name = name.rsplit('_model', 1)[0]
            fizz_models[name].append(inst)
            inst.remove()
        elif 'fizzler_base' in traits:
            fizz_bases[name] = inst
        else:
            LOGGER.warning('Fizzler "{}" has non-base, non-model instance?', name)
            continue

        origin = Vec.from_str(inst['origin'])
        normal = Vec(z=1).rotate_by_str(inst['angles'])
        fizz_pos[origin.as_tuple(), normal.as_tuple()] = name

    for name, base_inst in fizz_bases.items():
        models = fizz_models[name]
        orient = Matrix.from_angle(Angle.from_str(base_inst['angles']))
        up_axis = orient.left()

        # If upside-down, make it face upright.
        if up_axis == (0, 0, -1):
            up_axis = Vec(z=1)

        base_inst.outputs.clear()

        # Now match the pairs of models to each other.
        # The length axis is the line between them.
        # We don't care about the instances after this, so don't keep track.
        length_axis = orient.up().axis()

        emitters = []  # type: List[Tuple[Vec, Vec]]

        model_pairs = {}  # type: Dict[Tuple[float, float], Vec]

        model_skin = models[0].fixup.int('$skin')

        try:
            item_id, item_subtype = instanceLocs.ITEM_FOR_FILE[base_inst['file'].casefold()]
            fizz_type = fizz_types[item_id, model_skin]
        except KeyError:
            LOGGER.warning('Fizzler types: {}', fizz_types.keys())
            raise ValueError('No fizzler type for "{}"!'.format(
                base_inst['file'],
            )) from None

        for attr_name in fizz_type.voice_attrs:
            voice_attrs[attr_name] = True

        for model in models:
            pos = Vec.from_str(model['origin'])
            try:
                other_pos = model_pairs.pop(pos.other_axes(length_axis))
            except KeyError:
                # No other position yet, we need to find that.
                model_pairs[pos.other_axes(length_axis)] = pos
                continue

            min_pos, max_pos = Vec.bbox(pos, other_pos)

            # Move positions to the wall surface.
            min_pos[length_axis] -= 64
            max_pos[length_axis] += 64
            emitters.append((min_pos, max_pos))

        FIZZLERS[name] = Fizzler(fizz_type, up_axis, base_inst, emitters)

    # Delete all the old brushes associated with fizzlers
    for brush in (
        vmf.by_class['trigger_portal_cleanser'] |
        vmf.by_class['trigger_hurt'] |
        vmf.by_class['func_brush']
    ):
        name = brush['targetname']
        if not name:
            continue
        name = name.rsplit('_brush')[0]
        if name in FIZZLERS:
            brush.remove()

    # Check for fizzler output relays.
    relay_file = instanceLocs.resolve('<ITEM_BEE2_FIZZLER_OUT_RELAY>', silent=True)
    if not relay_file:
        # No relay item - deactivated most likely.
        return

    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in relay_file:
            continue

        inst.remove()

        relay_item = connections.ITEMS[inst['targetname']]

        try:
            fizz_name = fizz_pos[
                Vec.from_str(inst['origin']).as_tuple(),
                Vec(0, 0, 1).rotate_by_str(inst['angles']).as_tuple()
            ]
            fizz_item = connections.ITEMS[fizz_name]
        except KeyError:
            # Not placed on a fizzler, or a fizzler with no IO
            # - ignore, and destroy.
            for out in list(relay_item.outputs):
                out.remove()
            for out in list(relay_item.inputs):
                out.remove()
            del connections.ITEMS[relay_item.name]
            continue

        # Copy over fixup values
        fizz_item.inst.fixup.update(inst.fixup)

        # Copy over the timer delay set in the relay.
        fizz_item.timer = relay_item.timer
        # Transfer over antlines.
        fizz_item.antlines |= relay_item.antlines
        fizz_item.shape_signs += relay_item.shape_signs
        fizz_item.ind_panels |= relay_item.ind_panels

        # Remove the relay item so it doesn't get added to the map.
        del connections.ITEMS[relay_item.name]

        for conn in list(relay_item.outputs):
            conn.from_item = fizz_item


@conditions.meta_cond(priority=500, only_once=True)
def generate_fizzlers(vmf: VMF):
    """Generates fizzler models and the brushes according to their set types.

    After this is done, fizzler-related conditions will not function correctly.
    However the model instances are now available for modification.
    """
    from vbsp import MAP_RAND_SEED

    has_fizz_border = 'fizz_border' in texturing.SPECIAL

    for fizz in FIZZLERS.values():
        if fizz.base_inst not in vmf.entities:
            continue   # The fizzler was removed from the map.

        fizz_name = fizz.base_inst['targetname']
        fizz_type = fizz.fizz_type

        # Static versions are only used for fizzlers which start on.
        # Permanently-off fizzlers are kinda useless, so we don't need
        # to bother optimising for it.
        # TODO: This needs to use connections to correctly check this.
        is_static = bool(
            fizz.base_inst.fixup.int('$connectioncount', 0) == 0
            and fizz.base_inst.fixup.bool('$start_enabled', 1)
        )

        pack_list = (
            fizz.fizz_type.pack_lists_static
            if is_static else
            fizz.fizz_type.pack_lists
        )
        for pack in pack_list:
            packing.pack_list(vmf, pack)

        if fizz_type.inst[FizzInst.BASE, is_static]:
            random.seed('{}_fizz_base_{}'.format(MAP_RAND_SEED, fizz_name))
            fizz.base_inst['file'] = random.choice(fizz_type.inst[FizzInst.BASE, is_static])

        if not fizz.emitters:
            LOGGER.warning('No emitters for fizzler "{}"!', fizz_name)
            continue

        # Brush index -> entity for ones that need to merge.
        # template_brush is used for the templated one.
        single_brushes = {}  # type: Dict[FizzlerBrush, Entity]

        if fizz_type.temp_max or fizz_type.temp_min:
            template_brush_ent = vmf.create_ent(
                classname='func_brush',
                origin=fizz.base_inst['origin'],
            )
            conditions.set_ent_keys(
                template_brush_ent,
                fizz.base_inst,
                fizz_type.temp_brush_keys,
            )
        else:
            template_brush_ent = None

        up_dir = fizz.up_axis
        forward = (fizz.emitters[0][1] - fizz.emitters[0][0]).norm()

        min_orient = Matrix.from_basis(z=forward, y=up_dir)
        max_orient = Matrix.from_basis(z=-forward, y=up_dir)

        model_min = (
            fizz_type.inst[FizzInst.PAIR_MIN, is_static]
            or fizz_type.inst[FizzInst.ALL, is_static]
        )
        model_max = (
            fizz_type.inst[FizzInst.PAIR_MAX, is_static]
            or fizz_type.inst[FizzInst.ALL, is_static]
        )

        if not model_min or not model_max:
            raise ValueError(
                'No model specified for one side of "{}"'
                ' fizzlers'.format(fizz_type.id),
            )

        # Define a function to do the model names.
        model_index = 0
        if fizz_type.model_naming is ModelName.SAME:
            def get_model_name(ind):
                """Give every emitter the base's name."""
                return fizz_name
        elif fizz_type.model_naming is ModelName.LOCAL:
            def get_model_name(ind):
                """Give every emitter a name local to the base."""
                return fizz_name + '-' + fizz_type.model_name
        elif fizz_type.model_naming is ModelName.PAIRED:
            def get_model_name(ind):
                """Give each pair of emitters the same unique name."""
                return '{}-{}{:02}'.format(
                    fizz_name,
                    fizz_type.model_name,
                    ind,
                )
        elif fizz_type.model_naming is ModelName.UNIQUE:
            def get_model_name(ind):
                """Give every model a unique name."""
                nonlocal model_index
                model_index += 1
                return '{}-{}{:02}'.format(
                    fizz_name,
                    fizz_type.model_name,
                    model_index,
                )
        else:
            raise ValueError('Bad ModelName?')

        # Generate env_beam pairs.
        for beam in fizz_type.beams:
            beam_template = Entity(vmf)
            conditions.set_ent_keys(beam_template, fizz.base_inst, beam.keys)
            beam_template['classname'] = 'env_beam'
            del beam_template['LightningEnd']  # Don't allow users to set end pos.
            name = beam_template['targetname'] + '_'

            counter = 1
            for seg_min, seg_max in fizz.emitters:
                for offset in beam.offset:  # type: Vec
                    min_off = offset.copy()
                    max_off = offset.copy()
                    min_off.localise(seg_min, min_orient)
                    max_off.localise(seg_max, max_orient)
                    beam_ent = beam_template.copy()
                    vmf.add_ent(beam_ent)

                    # Allow randomising speed and direction.
                    if 0 < beam.speed_min  < beam.speed_max:
                        random.seed('{}{}{}'.format(MAP_RAND_SEED, min_off, max_off))
                        beam_ent['TextureScroll'] = random.randint(beam.speed_min, beam.speed_max)
                        if random.choice((False, True)):
                            # Flip to reverse direction.
                            min_off, max_off = max_off, min_off

                    beam_ent['origin'] = min_off
                    beam_ent['LightningStart'] = beam_ent['targetname'] = (
                        name + str(counter)
                    )
                    counter += 1
                    beam_ent['targetpoint'] = max_off

        # Prepare to copy over instance traits for the emitters.
        fizz_traits = instance_traits.get(fizz.base_inst).copy()
        # Special case, mark emitters that have a custom position for Clean
        # models.
        if fizz.has_cust_position:
            fizz_traits.add('cust_shape')

        mat_mod_tex = {}  # type: Dict[FizzlerBrush, Set[str]]
        for brush_type in fizz_type.brushes:
            if brush_type.mat_mod_var is not None:
                mat_mod_tex[brush_type] = set()

        # Record the data for trigger hurts so flinch triggers can match them.
        trigger_hurt_name = ''
        trigger_hurt_start_disabled = '0'

        for seg_ind, (seg_min, seg_max) in enumerate(fizz.emitters, start=1):
            length = (seg_max - seg_min).mag()
            random.seed('{}_fizz_{}'.format(MAP_RAND_SEED, seg_min))
            if length == 128 and fizz_type.inst[FizzInst.PAIR_SINGLE, is_static]:
                min_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(fizz_type.inst[FizzInst.PAIR_SINGLE, is_static]),
                    origin=(seg_min + seg_max)/2,
                    angles=min_orient.to_angle(),
                )
            else:
                # Both side models.
                min_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(model_min),
                    origin=seg_min,
                    angles=min_orient.to_angle(),
                )
                random.seed('{}_fizz_{}'.format(MAP_RAND_SEED, seg_max))
                max_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(model_max),
                    origin=seg_max,
                    angles=max_orient.to_angle(),
                )
                max_inst.fixup.update(fizz.base_inst.fixup)
                instance_traits.get(max_inst).update(fizz_traits)
            min_inst.fixup.update(fizz.base_inst.fixup)
            instance_traits.get(min_inst).update(fizz_traits)

            if has_fizz_border:
                fizz._gen_fizz_border(vmf, seg_min, seg_max)

            if fizz.embedded:
                fizz.set_tiles_behind_models(seg_min, forward, fizz_type.nodraw_behind)
                fizz.set_tiles_behind_models(seg_max, -forward, fizz_type.nodraw_behind)

            if fizz_type.inst[FizzInst.GRID, is_static]:
                # Generate one instance for each position.

                # Go 64 from each side, and always have at least 1 section
                # A 128 gap will have length = 0
                for ind, dist in enumerate(range(64, round(length) - 63, 128)):
                    mid_pos = seg_min + forward * dist
                    random.seed('{}_fizz_mid_{}'.format(MAP_RAND_SEED, mid_pos))
                    mid_inst = vmf.create_ent(
                        classname='func_instance',
                        targetname=fizz_name,
                        angles=min_orient.to_angle(),
                        file=random.choice(fizz_type.inst[FizzInst.GRID, is_static]),
                        origin=mid_pos,
                    )
                    mid_inst.fixup.update(fizz.base_inst.fixup)
                    instance_traits.get(mid_inst).update(fizz_traits)

            if template_brush_ent is not None:
                if length == 128 and fizz_type.temp_single:
                    temp = template_brush.import_template(
                        vmf,
                        fizz_type.temp_single,
                        (seg_min + seg_max) / 2,
                        min_orient,
                        force_type=template_brush.TEMP_TYPES.world,
                        add_to_map=False,
                    )
                    template_brush_ent.solids.extend(temp.world)
                else:
                    if fizz_type.temp_min:
                        temp = template_brush.import_template(
                            vmf,
                            fizz_type.temp_min,
                            seg_min,
                            min_orient,
                            force_type=template_brush.TEMP_TYPES.world,
                            add_to_map=False,
                        )
                        template_brush_ent.solids.extend(temp.world)
                    if fizz_type.temp_max:
                        temp = template_brush.import_template(
                            vmf,
                            fizz_type.temp_max,
                            seg_max,
                            max_orient,
                            force_type=template_brush.TEMP_TYPES.world,
                            add_to_map=False,
                        )
                        template_brush_ent.solids.extend(temp.world)

            # Generate the brushes.
            for brush_type in fizz_type.brushes:
                brush_ent = None
                # If singular, we reuse the same brush ent for all the segments.
                if brush_type.singular:
                    brush_ent = single_brushes.get(brush_type, None)

                # Non-singular or not generated yet - make the entity.
                if brush_ent is None:
                    brush_ent = vmf.create_ent(classname='func_brush')

                    for key_name, key_value in brush_type.keys.items():
                        brush_ent[key_name] = conditions.resolve_value(fizz.base_inst, key_value)

                    for key_name, key_value in brush_type.local_keys.items():
                        brush_ent[key_name] = conditions.local_name(
                            fizz.base_inst, conditions.resolve_value(
                                fizz.base_inst, key_value,
                            )
                        )

                    brush_ent['targetname'] = conditions.local_name(
                        fizz.base_inst, brush_type.name,
                    )
                    # Set this to the center, to make sure it's not going to leak.
                    brush_ent['origin'] = (seg_min + seg_max)/2

                    # For fizzlers flat on the floor/ceiling, scanlines look
                    # useless. Turn them off.
                    if 'usescanline' in brush_ent and fizz.normal().z:
                        brush_ent['UseScanline'] = 0

                    if brush_ent['classname'] == 'trigger_hurt':
                        trigger_hurt_name = brush_ent['targetname']
                        trigger_hurt_start_disabled = brush_ent['startdisabled']

                    if brush_type.set_axis_var:
                        brush_ent['vscript_init_code'] = (
                            'axis <- `{}`;'.format(
                                fizz.normal().axis(),
                            )
                        )

                    for out in brush_type.outputs:
                        new_out = out.copy()
                        new_out.target = conditions.local_name(
                            fizz.base_inst,
                            new_out.target,
                        )
                        brush_ent.add_out(new_out)

                    if brush_type.singular:
                        # Record for the next iteration.
                        single_brushes[brush_type] = brush_ent

                # If we have a material_modify_control to generate,
                # we need to parent it to ourselves to restrict it to us
                # only. We also need one for each material, so provide a
                # function to the generator which adds to a set.
                if brush_type.mat_mod_var is not None:
                    used_tex_func = mat_mod_tex[brush_type].add
                else:
                    def used_tex_func(val):
                        """If not, ignore those calls."""
                        return None

                # Generate the brushes and texture them.
                brush_ent.solids.extend(
                    brush_type.generate(
                        vmf,
                        fizz,
                        seg_min,
                        seg_max,
                        used_tex_func,
                    )
                )

        # We have a trigger_hurt in this fizzler, potentially generate
        # the flinching logic.
        if trigger_hurt_name:
            fizz.gen_flinch_trigs(
                vmf,
                trigger_hurt_name,
                trigger_hurt_start_disabled,
            )

        # If we have the config, but no templates used anywhere in this brush,
        # remove the empty brush entity.
        if template_brush_ent is not None and not template_brush_ent.solids:
            template_brush_ent.remove()

        # Generate the material modify controls.
        # One is needed for each texture used on the brush, unfortunately.
        for brush_type, used_tex in mat_mod_tex.items():
            brush_name = conditions.local_name(fizz.base_inst, brush_type.name)
            mat_mod_name = conditions.local_name(fizz.base_inst, brush_type.mat_mod_name)
            for off, tex in zip(MATMOD_OFFSETS, sorted(used_tex)):
                pos = off @ min_orient
                pos += Vec.from_str(fizz.base_inst['origin'])
                vmf.create_ent(
                    classname='material_modify_control',
                    origin=pos,
                    targetname=mat_mod_name,
                    materialName='materials/' + tex + '.vmt',
                    materialVar=brush_type.mat_mod_var,
                    parentname=brush_name,
                )
