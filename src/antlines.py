"""Handles restyling antlines."""
import random
from typing import NamedTuple, List

from srctools import Vec, Property, conv_float, Entity, VMF
import srctools.vmf
import comp_consts as const


class AntTex(NamedTuple):
    """Represents a single texture, and the parameters it has."""
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
    """Defines the style of antline to use.

    For broken antlines, 'broken_chance' is the percentage chance for brokenness
    per dot.
    """
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

        if broken_chance == 0:
            broken_corner = broken_straight = []

        self.broken_corner = broken_corner
        self.broken_straight = broken_straight
        self.broken_chance = broken_chance

    @classmethod
    def parse(cls, prop: Property):
        """Parse this from a property block."""
        broken_chance = prop.float('broken_chance')
        tex_straight = []
        tex_corner = []
        brok_straight = []
        brok_corner = []
        for ant_list, name in zip(
            [tex_straight, tex_corner, brok_straight, brok_corner],
            ('straight', 'corner', 'broken_straight', 'broken_corner'),
        ):
            for sub_prop in prop.find_all(name):
                ant_list.append(AntTex.parse(sub_prop))
        return cls(
            tex_straight,
            tex_corner,
            brok_straight,
            brok_corner,
            broken_chance,
        )


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


def set_antline_mat(vmf: VMF, over: Entity, conf: AntType, floor_conf: AntType):
    """Retexture an antline.

    floor_conf, if set is an alternate texture set to use on floors and ceilings.
    """
    # Choose a random one
    random.seed(over['origin'])

    # For P1 style, check to see if the antline is on the floor or walls.
    if Vec.from_str(over['basisNormal']).z != 0:
        conf = floor_conf

    if over['material'] == const.Antlines.STRAIGHT:
        mats = conf.tex_straight
        broken_mats = conf.broken_straight
    elif over['material'] == const.Antlines.CORNER:
        mats = conf.tex_corner
        broken_mats = conf.broken_corner
    else:
        raise ValueError('"{}" is not an antline!'.format(over['material']))

    if conf.broken_chance:  # We can have `broken` antlines.
        bbox_min, bbox_max = srctools.vmf.overlay_bounds(over)
        # Number of 'circles' and the length-wise axis
        length = max(bbox_max - bbox_min)
        long_axis = Vec(0, 1, 0).rotate_by_str(over['angles']).axis()

        # It's a corner or short antline - replace instead of adding more
        if length <= 48:
            if random.randrange(100) < conf.broken_corner:
                mats = broken_mats
        else:
            # Generate multiple for broken overlays.
            min_origin = Vec.from_str(over['origin'])
            min_origin[long_axis] -= length / 2

            broken_iter = broken_antline_iter(
                length // 16,
                conf.broken_chance,
            )
            for sect_min, sect_max, is_broken in broken_iter:
                sect_mats = broken_mats if is_broken else mats

                sect_length = sect_max - sect_min

                # Make a section - base it off the original, and shrink it
                new_over = over.copy()
                vmf.add_ent(new_over)

                # Repeats lengthways
                new_over['startV'] = sect_length
                sect_center = (sect_min + sect_max) / 2

                sect_origin = min_origin.copy()
                sect_origin[long_axis] += sect_center * 16
                new_over['basisorigin'] = new_over['origin'] = sect_origin

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

                random.choice(sect_mats).apply(new_over)
            # Remove the original overlay
            vmf.remove_ent(over)
            return  # Don't texture the original.

    random.choice(mats).apply(over)
