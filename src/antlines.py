"""Handles restyling antlines."""
import random
from typing import NamedTuple, List

from srctools import vmf, Vec, Property, conv_float, Entity
from vbsp import VMF, IGNORED_OVERLAYS


class AntTex(NamedTuple):
    texture: str
    scale: float
    static: bool

    @staticmethod
    def parse(prop: Property):
        """Parse from property values.

        The value can be in four forms:
        "prop" "material"
        "prop" "<scale>|material"
        "prop" "<scale>|material|static"
        "prop"
            {
            "tex"    "<mat>"
            "scale"  "<scale>"
            "static" "<is_static>"
            }
        """
        if prop.has_children():
            tex = prop['tex']
            scale = prop.float('scale', 0.25)
            static = prop.bool('static')
        else:
            vals = prop.value.split('|')
            opts = ()
            scale_str = '0.25'

            if len(vals) == 2:
                scale_str, tex = vals
            elif len(vals) > 2:
                scale_str, tex, *opts = vals
            else:
                # Unpack to ensure it only has 1 section
                [tex] = vals
            scale = conv_float(scale_str, 0.25)
            static = 'static' in opts

        return AntTex(tex, scale, static)

    def apply(self, overlay: Entity):
        """Apply the texture to the overlay."""
        overlay['material'] = self.texture
        overlay['endu'] = self.scale
        if self.static:
            del overlay['targetname']


class AntType:
    """Defines the style of antline to use."""
    def __init__(
        self,
        tex_straight: List[AntTex],
        tex_corner: List[AntTex],
        broken_straight: List[AntTex],
        broken_corner: List[AntTex],
        broken_chance: float,
    ):
        self.tex_straight = tex_straight
        self.tex_corner = tex_corner

        self.broken_corner = broken_corner
        self.broken_straight = broken_straight
        self.broken_chance = broken_chance


def broken_antline_iter(dist, chance):
    """Iterator used in set_antline_mat().

    This produces min, max pairs which fill the space from 0-dist.
    Neighbouring sections will be merged when they have the same type.
    """
    run_start = 0
    last_type = random.randrange(100) < chance
    for i in range(1, dist):
        next_type = random.randrange(100) < chance
        if next_type != last_type:
            yield run_start, i, last_type
            last_type = next_type
            run_start = i
    yield run_start, dist, last_type

    return


def set_antline_mat(over: Entity, conf: AntType, floor_conf: AntType):
    """Retexture an antline.

    floor_mat, if set is an alternate material to use for floors.
    The material is split into 3 parts, separated by '|':
    - Scale: the u-axis width of the material, used for clean antlines.
    - Material: the material
    - Static: if 'static', the antline will lose the targetname. This
      makes it non-dynamic, and removes the info_overlay_accessor
      entity from the compiled map.
    If only 2 parts are given, the overlay is assumed to be dynamic.
    If one part is given, the scale is assumed to be 0.25.

    For broken antlines,  'broken_chance' is the percentage chance for
    brokenness. broken_dist is the largest run of lights that can be broken.
    broken and broken_floor are the textures used for the broken lights.
    """
    # Choose a random one
    random.seed(over['origin'])

    # For P1 style, check to see if the antline is on the floor or walls.
    if Vec.from_str(over['basisNormal']).z != 0:
        conf = floor_conf

    if broken_chance and any(broken):  # We can have `broken` antlines.
        bbox_min, bbox_max = vmf.overlay_bounds(over)
        # Number of 'circles' and the length-wise axis
        length = max(bbox_max - bbox_min)
        long_axis = Vec(0, 1, 0).rotate_by_str(over['angles']).axis()

        # It's a corner or short antline - replace instead of adding more
        if length // 16 < broken_dist:
            if random.randrange(100) < broken_chance:
                mats = broken
                floor_mats = broken_floor
        else:
            min_origin = Vec.from_str(over['origin'])
            min_origin[long_axis] -= length / 2

            broken_iter = broken_antline_iter(
                length // 16,
                broken_chance,
            )
            for sect_min, sect_max, is_broken in broken_iter:

                if is_broken:
                    tex, floor_tex = broken, broken_floor
                else:
                    tex, floor_tex = mats, floor_mats

                sect_length = sect_max - sect_min

                # Make a section - base it off the original, and shrink it
                new_over = over.copy()
                VMF.add_ent(new_over)
                # Make sure we don't restyle this twice.
                IGNORED_OVERLAYS.add(new_over)

                # Repeats lengthways
                new_over['startV'] = str(sect_length)
                sect_center = (sect_min + sect_max) / 2

                sect_origin = min_origin.copy()
                sect_origin[long_axis] += sect_center * 16
                new_over['basisorigin'] = new_over['origin'] = sect_origin.join(' ')

                # Set the 4 corner locations to determine the overlay size.
                # They're in local space - x is -8/+8, y=length, z=0
                # Match the sign of the current value
                for axis in '0123':
                    pos = Vec.from_str(new_over['uv' + axis])
                    if pos.y < 0:
                        pos.y = -8 * sect_length
                    else:
                        pos.y = 8 * sect_length
                    new_over['uv' + axis] = pos.join(' ')

                # Recurse to allow having values in the material value
                set_antline_mat(new_over, tex, floor_tex, broken_chance=0)
            # Remove the original overlay
            VMF.remove_ent(over)

    if any(floor_mats):  # Ensure there's actually a value
        # For P1 style, check to see if the antline is on the floor or
        # walls.
        if Vec.from_str(over['basisNormal']).z != 0:
            mats = floor_mats

    mat = random.choice(mats).split('|')
    opts = []

    if len(mat) == 2:
        # rescale antlines if needed
        over['endu'], over['material'] = mat
    elif len(mat) > 2:
        over['endu'], over['material'], *opts = mat
    else:
        # Unpack to ensure it only has 1 section
        over['material'], = mat
        over['endu'] = '0.25'

    if 'static' in opts:
        # If specified, remove the targetname so the overlay
        # becomes static.
        del over['targetname']