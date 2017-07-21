"""Implements fizzler/laserfield generation and customisation."""
import random
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Iterator

import itertools
from enum import Enum

import conditions
import utils
from srctools import Output, Vec, VMF, Solid, Entity, Side, Property
import comp_consts as const
import instance_traits
import instanceLocs

LOGGER = utils.getLogger(__name__)

FIZZ_TYPES = {}  # type: Dict[str, FizzlerType]

FIZZLERS = {}  # type: Dict[str, Fizzler]

# Fizzler textures are higher-res than laserfields.
FIZZLER_TEX_SIZE = 1024
LASER_TEX_SIZE = 512

# Given a normal and the up-axis, the angle used for the instance.
FIZZ_ANGLES  = {}  # type: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], Vec]


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


def read_configs(conf: Property):
    """Read in the fizzler data."""
    for fizz_conf in conf.find_all('Fizzlers', 'Fizzler'):
        fizz = FizzlerType.parse(fizz_conf)

        if fizz.id in FIZZ_TYPES:
            raise ValueError('Duplicate fizzler ID "{}"'.format(fizz.id))

        FIZZ_TYPES[fizz.id] = fizz

    LOGGER.info('Loaded "{}" fizzlers.', len(FIZZ_TYPES))


def _calc_fizz_angles():
    """Generate FIZZ_ANGLES."""
    it = itertools.product('xyz', (-1, 1), 'xyz', (-1, 1))
    for norm_axis, norm_mag, roll_axis, roll_mag in it:
        if norm_axis == roll_axis:
            # They can't both be the same...
            continue
        norm = Vec.with_axes(norm_axis, norm_mag)
        roll = Vec.with_axes(roll_axis, roll_mag)

        # Norm is Z, roll is X,  we want y.
        angle = roll.to_angle_roll(norm)
        up_dir = norm.cross(roll)
        FIZZ_ANGLES[norm.as_tuple(), up_dir.as_tuple()] = angle

_calc_fizz_angles()
del _calc_fizz_angles


class FizzlerType:
    """Implements a specific fizzler type."""
    def __init__(
        self,
        fizz_id: str,
        item_id: str,
        voice_attrs: List[str],
        model_local_name: str,
        model_name_type: ModelName,
        brushes: List['FizzlerBrush'],
        inst: Dict[FizzInst, List[str]],
    ):
        self.id = fizz_id
        # The brushes to generate.
        self.brushes = brushes

        self.voice_attrs = voice_attrs

        # The method used to name the models.
        self.model_naming = model_name_type
        self.model_name = model_local_name
        # Instances to use.
        self.inst = inst

        # The item ID this fizzler is produced from, optionally
        # with a :laserfield or :fizzler suffix to choose a specific
        # type.
        self.item_id = item_id

    @classmethod
    def parse(cls, conf: Property):
        """Read in a fizzler from a config."""
        fizz_id = conf['id']
        item_id = conf['item_id']

        try:
            model_name_type = ModelName(conf['NameType', 'same'].casefold())
        except ValueError:
            LOGGER.warning('Bad model name type: "{}"', conf['NameType'])
            model_name_type = ModelName.SAME

        model_local_name = conf['ModelName', '']
        if not model_local_name:
            # We can't rename without a local name.
            model_name_type = ModelName.SAME

        inst = {}
        for inst_type in FizzInst:
            inst[inst_type] = [
                file
                for prop in conf.find_all(inst_type.value)
                for file in instanceLocs.resolve(prop.value)
            ]

        voice_attrs = []
        for prop in conf.find_all('Has'):
            if prop.has_children():
                for child in prop:
                    voice_attrs.append(child.name)
            voice_attrs.append(prop.name)

        brushes = [
            FizzlerBrush.parse(prop)
            for prop in
            conf.find_all('Brush')
        ]
        return FizzlerType(
            fizz_id,
            item_id,
            voice_attrs,
            model_local_name,
            model_name_type,
            brushes,
            inst,
        )


class Fizzler:
    """Represents a specific pair of emitters and a field."""
    def __init__(
        self,
        fizz_type: FizzlerType,
        up_axis: Vec,
        base_inst: Entity,
        emitters: List[Tuple[Vec, Vec]]
    ):
        self.fizz_type = fizz_type
        self.base_inst = base_inst
        self.up_axis = up_axis  # Pointing toward the 'up' side of the field.
        self.emitters = emitters  # Pairs of left, right positions.


class FizzlerBrush:
    """A brush-set used in a fizzler."""
    def __init__(
        self,
        name: str,
        textures: Dict[TexGroup, Optional[str]],
        keys: Dict[str, str],
        local_keys: Dict[str, str],
        outputs: List[Output],
        thickness=2.0,
        side_tint: Vec=None,
        singular: bool=False,
        mat_mod_name: str=None,
        mat_mod_var: str=None,
    ):
        self.keys = keys
        self.local_keys = local_keys
        self.name = name  # Local name of the fizzler brush.
        self.outputs = list(outputs)
        # Width of the brush.
        self.thickness = thickness
        # If set, a colour to apply to the sides.
        self.side_tint = side_tint

        # Use only one brush for all the parts of this.
        self.singular = singular

        # If set, add a material_modify_control to control these brushes.
        self.mat_mod_var = mat_mod_var
        self.mat_mod_name = mat_mod_name

        self.textures = {}
        for group in TexGroup:
            self.textures[group] = textures.get(group, None)

    @classmethod
    def parse(cls, conf: Property):
        """Parse from a config file."""
        if 'side_tint' in conf:
            side_tint = conf.vec('side_tint')
        else:
            side_tint = None

        outputs = [
            Output.parse(prop)
            for prop in
            conf.find_children('Outputs')
        ]

        textures = {}
        for group in TexGroup:
            textures[group] = conf['tex_' + group.value, None]

        keys = {
            prop.real_name: prop.value
            for prop in
            conf.find_children('keys')
        }

        local_keys = {
            prop.real_name: prop.value
            for prop in
            conf.find_children('localkeys')
        }

        return FizzlerBrush(
            conf['name'],
            textures,
            keys,
            local_keys,
            outputs,
            conf.float('thickness', 2.0),
            side_tint,
            conf.bool('singular'),
            conf['mat_mod_name', None],
            conf['mat_mod_var', None],
        )

    def _side_tint(self, side: Side, normal: Vec, min_pos: Vec):
        """Output the side texture for fields."""
        if not self.side_tint:
            # Just apply nodraw.
            side.mat = const.Tools.NODRAW
            return

        import vbsp

        # Produce a hex colour string, and use that as the material name.
        side.mat = 'BEE2/fizz_sides/side_color_{:02X}{:02X}{:02X}'.format(
            int(self.side_tint.x),
            int(self.side_tint.y),
            int(self.side_tint.z),
        )

        # Pack the file.
        vbsp.PACK_FILES.add('materials/{}.vmt'.format(side.mat))

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
    ) -> List[Solid]:
        """Generate the actual brush."""
        diff = neg - pos
        # Size of fizzler
        field_length = diff.mag()
        # Direction it extends across.
        field_axis = diff.norm()

        # Out of the fizzler.
        normal = abs(fizz.up_axis.cross(field_axis))  # type: Vec

        origin = (pos + neg)/2

        # If either of these, we only need 1 brush.
        trigger_tex = self.textures[TexGroup.TRIGGER]
        fitted_tex = self.textures[TexGroup.FITTED]

        if trigger_tex or fitted_tex:
            tex_size = LASER_TEX_SIZE
        else:
            # Fizzlers are larger resolution..
            tex_size = FIZZLER_TEX_SIZE

        if field_length == 128 or trigger_tex or fitted_tex:
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
            else:
                mat = fitted_tex or self.textures[TexGroup.SHORT]
                for side in brush.sides:
                    side_norm = abs(side.normal())
                    if side_norm == abs(fizz.up_axis):
                        self._side_tint(side, normal, neg)

                    if side_norm != normal:
                        continue
                    side.mat = mat

                    self._texture_fit(
                        side,
                        tex_size,
                        field_length,
                        fizz,
                        neg,
                        pos,
                        bool(fitted_tex),
                    )
        else:
            # Generate the three brushes for fizzlers.

            if field_length < 128:
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
            else:
                brush_center = None
                brushes = [
                    (brush_left, field_axis, side_len),
                    (brush_right, -field_axis, side_len),
                ]

            for brush, model_normal, brush_length in brushes:
                yield brush
                for side in brush.sides:
                    side_norm = abs(side.normal())
                    if side_norm == abs(fizz.up_axis):
                        self._side_tint(side, normal, neg)

                    if side_norm != abs(normal):
                        continue

                    if model_normal is None:
                        side.mat = self.textures[TexGroup.CENTER]

                    self._texture_fit(
                        side,
                        FIZZLER_TEX_SIZE,
                        brush_length,
                        fizz,
                        neg,
                        pos,
                        model_normal=model_normal,
                    )

    def _texture_fit(
        self,
        side: Side,
        tex_size: float,
        field_length: float,
        fizz: Fizzler,
        neg: Vec,
        pos: Vec,
        is_laserfield=False,
        model_normal: Vec=None,
    ):
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

        # For left and right, we need to figure out what direction the texture
        # should be in. uaxis is in the direction of the surface.
        if model_normal is not None:
            uaxis_dir = side.uaxis.vec()
            if uaxis_dir == model_normal:
                side.mat = self.textures[TexGroup.RIGHT]
            else:
                side.mat = self.textures[TexGroup.LEFT]

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


def parse_map(vmf: VMF, voice_attrs: Dict[str, bool]):
    """Analyse fizzler instances to assign fizzler types.

    Instance traits are required.
    The model instances and brushes will be removed from the map.
    """

    # Item ID and model skin -> fizzler type
    fizz_types = {}  # type: Dict[Tuple[str, int], FizzlerType]

    for fizz_type in FIZZ_TYPES.values():
        if ':' in fizz_type.item_id:
            item_id, barrier_type = fizz_type.item_id.casefold().split(':')
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
            item_id = fizz_type.item_id.casefold()
            fizz_types[item_id, 0] = fizz_type
            fizz_types[item_id, 2] = fizz_type

    fizz_bases = {}  # type: Dict[str, Entity]
    fizz_models = defaultdict(list)  # type: Dict[str, List[Entity]]

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

    for name, base_inst in fizz_bases.items():
        models = fizz_models[name]
        up_axis = Vec(y=1).rotate_by_str(base_inst['angles'])

        # If upside-down, make it face upright.
        if up_axis == (0, 0, -1):
            up_axis = Vec(z=1)

        base_inst.outputs.clear()

        # Now match the pairs of models to each other.
        # The length axis is the line between them.
        # We don't care about the instances after this, so don't keep track.
        length_axis = Vec(z=1).rotate_by_str(base_inst['angles']).axis()

        emitters = []  # type: List[Tuple[Vec, Vec]]

        model_pairs = {}  # type: Dict[Tuple[float, float], Vec]

        model_skin = models[0].fixup.int('$skin')

        try:
            item_id, item_subtype = instanceLocs.ITEM_FOR_FILE[base_inst['file'].casefold()]
            fizz_type = fizz_types[item_id, model_skin]
        except KeyError:
            raise ValueError('No fizzler type for "{}"!'.format(
                base_inst['file']
            ))

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


@conditions.meta_cond(priority=500, only_once=True)
def generate_fizzlers(vmf: VMF):
    """Generates fizzler models and the brushes according to their set types.

    After this is done, fizzler-related conditions will not function correctly.
    However the model instances are now available for modification.
    """
    from vbsp import MAP_RAND_SEED

    for fizz in FIZZLERS.values():
        if fizz.base_inst not in vmf.entities:
            continue   # The fizzler was removed from the map.

        fizz_name = fizz.base_inst['targetname']
        fizz_type = fizz.fizz_type

        if fizz_type.inst[FizzInst.BASE]:
            random.seed('{}_fizz_base_{}'.format(MAP_RAND_SEED, fizz_name))
            fizz.base_inst['file'] = random.choice(fizz_type.inst[FizzInst.BASE])

        if not fizz.emitters:
            LOGGER.warning('No emitters for fizzler "{}"!', fizz_name)
            continue

        # Brush index -> entity for ones that need to merge.
        single_brushes = {}  # type: Dict[FizzlerBrush, Entity]

        up_dir = fizz.up_axis
        forward = (fizz.emitters[0][1] - fizz.emitters[0][0]).norm()

        min_angles = FIZZ_ANGLES[forward.as_tuple(), up_dir.as_tuple()]
        max_angles = FIZZ_ANGLES[(-forward).as_tuple(), up_dir.as_tuple()]

        model_min = fizz_type.inst[FizzInst.PAIR_MIN] or fizz_type.inst[FizzInst.ALL]
        model_max = fizz_type.inst[FizzInst.PAIR_MAX] or fizz_type.inst[FizzInst.ALL]
        if not model_min or not model_max:
            raise ValueError(
                'No model specified a side of "{}"'
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

        for seg_ind, (seg_min, seg_max) in enumerate(fizz.emitters, start=1):
            length = (seg_max - seg_min).mag()
            random.seed('{}_fizz_{}'.format(MAP_RAND_SEED, seg_min))
            if length == 128 and fizz_type.inst[FizzInst.PAIR_SINGLE]:
                min_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(fizz_type.inst[FizzInst.PAIR_SINGLE]),
                    origin=seg_min + 64 * forward,
                    angles=min_angles,
                )
            else:
                # Both side models.
                min_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(model_min),
                    origin=seg_min,
                    angles=min_angles,
                )
                random.seed('{}_fizz_{}'.format(MAP_RAND_SEED, seg_max))
                max_inst = vmf.create_ent(
                    targetname=get_model_name(seg_ind),
                    classname='func_instance',
                    file=random.choice(model_max),
                    origin=seg_max,
                    angles=max_angles,
                )
                max_inst.fixup.update(fizz.base_inst.fixup)
            min_inst.fixup.update(fizz.base_inst.fixup)

            if fizz_type.inst[FizzInst.GRID]:
                # Generate one instance for each position.

                # Go 64 from each side, and always have at least 1 section
                # A 128 gap will have length = 0
                for ind, dist in enumerate(range(64, round(length) - 127, 128)):
                    mid_pos = seg_min + forward * dist
                    random.seed('{}_fizz_mid_{}'.format(MAP_RAND_SEED, mid_pos))
                    mid_inst = vmf.create_ent(
                        classname='func_instance',
                        targetname=fizz_name,
                        angles=min_angles,
                        file=random.choice(fizz_type.inst[FizzInst.GRID]),
                        origin=mid_pos,
                    )
                    mid_inst.fixup.update(fizz.base_inst.fixup)

            for brush_type in fizz_type.brushes:
                brush_ent = None
                if brush_type.singular:
                    brush_ent = single_brushes.get(brush_type, None)
                if brush_ent is None:
                    brush_ent = Entity(vmf, keys=brush_type.keys)
                    vmf.add_ent(brush_ent)
                    if 'classname' not in brush_ent:
                        brush_ent['classname'] = 'func_brush'
                    for key_name, key_value in brush_type.local_keys.items():
                        brush_ent[key_name] = conditions.local_name(fizz.base_inst, key_value)
                    brush_ent['targetname'] = conditions.local_name(
                        fizz.base_inst, brush_type.name,
                    )
                    brush_ent['origin'] = (seg_min + seg_max)/2
                    if brush_type.singular:
                        single_brushes[brush_type] = brush_ent

                brush_ent.solids.extend(
                    brush_type.generate(vmf, fizz, seg_min, seg_max)
                )
