"""Implements fizzler/laserfield generation and customisation."""
from typing import Dict, List, Optional

from enum import Enum

from srctools import Output, Vec, VMF, Solid, Entity
import comp_consts as const

# The tint colours used in the map, that VRAD has to generate and pack.
SIDE_TINTS = set()

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


class FizzlerSet:
    """Represents a specific pair of emitters and a field."""
    def __init__(
        self,
        up_axis: Vec,
        neg: Vec,
        pos: Vec,
    ):
        self.up_axis = up_axis  # Pointing toward the 'up' side of the field.
        self.neg = neg # Position of the left side of the brush
        self.pos = pos # Position of the right side of the brush.


class FizzlerBrush:
    """A brush-set used in a fizzler."""
    def __init__(
        self,
        name: str,
        textures: Dict[TexGroup, Optional[str]],
        keys: Dict[str, str],
        outputs: List[Output],
        thickness=2.0,
        side_tint: Vec=None,
        mat_mod_name: str=None,
        mat_mod_var: str=None,
    ):
        self.keys = keys
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

    def _side_tint_mat(self):
        """Output the side texture for fields."""
        if self.side_tint:
            # Produce a hex colour string, and use that as the material name.
            SIDE_TINTS.add(self.side_tint.as_tuple())
            return 'BEE2/fizz/side_color_{:02X}{:02X}{:02X}'.format(
                int(self.side_tint.x),
                int(self.side_tint.y),
                int(self.side_tint.z),
            )
        else:
            # Just apply nodraw.
            return const.Tools.NODRAW

    def generate(
        self,
        vmf: VMF,
        fizz_set: FizzlerSet,
        inst_name: str,
    ):
        """Generate the actual brush."""
        brush_ent = Entity(vmf, self.keys)
        vmf.add_ent(brush_ent)
        brush_ent['targetname'] = inst_name + '-' + self.name

        diff = fizz_set.neg - fizz_set.pos
        # Size of fizzler
        field_length = diff.mag()
        # Direction it extends across.
        field_axis = diff.norm()

        # Out of the fizzler.
        normal = fizz_set.up_axis.cross(field_axis)

        origin = (fizz_set.pos + fizz_set.neg)/2

        # If either of these, we only need 1 brush.
        trigger_tex = self.textures[TexGroup.TRIGGER]
        fitted_tex = self.textures[TexGroup.FITTED]

        if trigger_tex or fitted_tex:
            tex_size = 512
        else:
            # Fizzlers are larger resolution..
            tex_size = 1024

        if field_length == 128 or trigger_tex or fitted_tex:
            # We need only one brush.
            brush = vmf.make_prism(
                p1=(origin
                    + (self.thickness/2) * normal
                    + 64 * fizz_set.up_axis
                    + (field_length/2) * field_axis
                ),
                p2=(origin
                    - (self.thickness / 2) * normal
                    - 64 * fizz_set.up_axis
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
                    if side_norm == abs(fizz_set.up_axis):
                        side.mat = self._side_tint_mat()

                    if side_norm != abs(normal):
                        continue
                    side.mat = mat

                    # Now calculate the texture offsets we need.
                    if fizz_set.up_axis.z == 0:
                        side.vaxis, side.uaxis = side.uaxis, side.vaxis

                    side.uaxis.offset = (tex_size / field_length) * fizz_set.neg.dot(field_axis)
                    side.uaxis.scale = field_length / tex_size

                    side.vaxis.offset = (tex_size/128) * fizz_set.neg.dot(fizz_set.up_axis)
                    # We need to offset over laserfields by half, and if vertical
                    # we also need to offset. those cancel each out though.
                    if fizz_set.up_axis.z == 0 and not fitted_tex:
                        side.vaxis.offset += tex_size/2

                    side.vaxis.scale = 128 / tex_size

                    side.uaxis.offset %= tex_size
                    side.vaxis.offset %= tex_size

            brush_ent.solids.append(brush)
        else:
            # Generate the three brushes for fizzlers.
            brush_ent.remove()


if __name__ == '__main__':
    import os
    _vmf = VMF.parse(os.environ['PORTAL_2_LOC'] +
                     '/sdk_content/maps/fizzler_test.vmf')

    _brushes = [
        FizzlerBrush(
            'fizzler',
            outputs=[],
            side_tint=Vec(55, 100, 110),
            textures={
                TexGroup.LEFT: 'effects/fizzler_l',
                TexGroup.CENTER: 'effects/fizzler_center',
                TexGroup.RIGHT: 'effects/fizzler_r',
                TexGroup.SHORT: 'effects/fizzler',
            },
            keys={
                'classname': 'trigger_portal_cleanser',
            }
        ),
        FizzlerBrush(
            'laserfield',
            outputs=[],
            side_tint=Vec(255, 0, 0),
            textures={
                TexGroup.FITTED: 'effects/laserplane',
            },
            keys={
                'classname': 'func_brush',
            }
        ),
        FizzlerBrush(
            'trigger',
            outputs=[],
            textures={
                TexGroup.TRIGGER: 'tools/toolstrigger',
            },
            keys={
                'classname': 'trigger_hurt',
            }
        ),
    ]

    for fizz in _vmf.by_class['env_beam']:
        print('Making', fizz['targetname'])
        neg, pos = sorted([
            Vec.from_str(fizz['targetpoint']),
            Vec.from_str(fizz['origin']),
        ])
        fizz_set = FizzlerSet(Vec.from_str(fizz.comments), neg, pos)
        for br in _brushes:
            print('  Brush = ', br.name)
            br.generate(_vmf, fizz_set, fizz['targetname'])

    with open(os.environ['PORTAL_2_LOC'] +
              '/sdk_content/maps/fizzler_test_2.vmf', 'w') as f:
        _vmf.export(f)
