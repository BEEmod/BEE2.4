"""Implements fizzler/laserfield generation and customisation."""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from enum import Enum

import utils
from srctools import Output, Vec, VMF, Solid, Entity, Side, Property
import comp_consts as const
import instance_traits
import instanceLocs

LOGGER = utils.getLogger(__name__)

# The tint colours used in the map, that VRAD has to generate and pack.
SIDE_TINTS = set()

FIZZ_TYPES = {}  # type: Dict[str, FizzlerType]

FIZZLERS = {}  # type: Dict[str, Fizzler]

# Fizzler textures are higher-res than laserfields.
FIZZLER_TEX_SIZE = 1024
LASER_TEX_SIZE = 512


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


def read_configs(conf: Property):
    """Read in the fizzler data."""
    for fizz_conf in conf.find_all('Fizzlers', 'Fizzler'):
        fizz = FizzlerType.parse(fizz_conf)

        if fizz.id in FIZZ_TYPES:
            raise ValueError('Duplicate fizzler ID "{}"'.format(fizz.id))

        FIZZ_TYPES[fizz.id] = fizz

    LOGGER.info('Loaded "{}" fizzlers.', len(FIZZ_TYPES))


class FizzlerType:
    """Implements a specific fizzler type."""
    def __init__(
        self,
        fizz_id: str,
        brushes: List['FizzlerBrush'],
        item_id: str,
    ):
        self.id = fizz_id
        self.brushes = brushes
        # The item ID this fizzler is produced from, optionally
        # with a :laserfield or :fizzler suffix to choose a specific
        # type.
        self.item_id = item_id

    @classmethod
    def parse(cls, conf: Property):
        """Read in a fizzler from a config."""
        fizz_id = conf['id']
        item_id = conf['item_id']

        brushes = [
            FizzlerBrush.parse(prop)
            for prop in
            conf.find_all('Brush')
        ]
        return FizzlerType(fizz_id, brushes, item_id)


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
            conf.find_all('keys')
        }

        local_keys = {
            prop.real_name: prop.value
            for prop in
            conf.find_all('localkeys')
        }

        return FizzlerBrush(
            conf['name'],
            textures,
            keys,
            local_keys,
            outputs,
            conf.float('thickness', 2.0),
            side_tint,
            conf['mat_mod_name', None],
            conf['mat_mod_var', None],
        )

    def _side_tint(self, side: Side, normal: Vec, min_pos: Vec):
        """Output the side texture for fields."""
        if not self.side_tint:
            # Just apply nodraw.
            side.mat = const.Tools.NODRAW
            return

        # Produce a hex colour string, and use that as the material name.
        side.mat = 'BEE2/fizz_sides/side_color_{:02X}{:02X}{:02X}'.format(
            int(self.side_tint.x),
            int(self.side_tint.y),
            int(self.side_tint.z),
        )
        # Record that we need to make that material in VRAD.
        SIDE_TINTS.add(self.side_tint.as_tuple())

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
        inst_name: str,
    ):
        """Generate the actual brush."""
        brush_ent = Entity(vmf, self.keys)
        vmf.add_ent(brush_ent)
        brush_ent['targetname'] = inst_name + '-' + self.name

        diff = neg - pos
        # Size of fizzler
        field_length = diff.mag()
        # Direction it extends across.
        field_axis = diff.norm()

        # Out of the fizzler.
        normal = fizz.up_axis.cross(field_axis)

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
            if trigger_tex:
                for side in brush.sides:
                    side.mat = trigger_tex
            else:
                mat = fitted_tex or self.textures[TexGroup.SHORT]
                for side in brush.sides:
                    side_norm = abs(side.normal())
                    if side_norm == abs(fizz.up_axis):
                        self._side_tint(side, normal, neg)

                    if side_norm != abs(normal):
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

            brush_ent.solids.append(brush)
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

                brushes = [
                    (brush_left, TexGroup.LEFT, 64),
                    (brush_center, TexGroup.CENTER, center_len),
                    (brush_right, TexGroup.RIGHT, 64),
                ]
            else:
                brushes = [
                    (brush_left, TexGroup.LEFT, side_len),
                    (brush_right, TexGroup.RIGHT, side_len),
                ]

            for brush, tex_group, brush_length in brushes:
                brush_ent.solids.append(brush)
                for side in brush.sides:
                    side_norm = abs(side.normal())
                    if side_norm == abs(fizz.up_axis):
                        self._side_tint(side, normal, neg)

                    if side_norm != abs(normal):
                        continue
                    side.mat = self.textures[tex_group]

                    self._texture_fit(
                        side,
                        FIZZLER_TEX_SIZE,
                        brush_length,
                        fizz,
                        neg,
                        pos,
                    )

    def _texture_fit(
        self,
        side: Side,
        tex_size: float,
        field_length: float,
        fizz_set: Fizzler,
        neg: Vec,
        pos: Vec,
        is_laserfield=False,
    ):
        """Calculate the texture offsets required for fitting a texture."""

        if fizz_set.up_axis.z == 0:
            side.vaxis, side.uaxis = side.uaxis, side.vaxis

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


def parse_map(vmf: VMF):
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

        base_inst.comments = fizz_type.id

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

