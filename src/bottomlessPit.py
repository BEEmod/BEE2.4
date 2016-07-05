"""Generates Bottomless Pits."""
import random
from collections import defaultdict

from srctools import Vec, Property, VMF
import srctools
import utils
import vbsp

LOGGER = utils.getLogger(__name__)

# The base of a pit must be below this z-pos to be considered a pit.
# It must basically be one of the bottom two grid positions.
BOTTOMLESS_PIT_MIN = 192

# The set config options for pits. If SETTINGS is empty, no pits are used.
SETTINGS = {}
PIT_INST = {}


def pits_allowed():
    """Are bottomless pits allowed in the configs?"""
    return bool(SETTINGS)


def is_pit(bbox_min: Vec, bbox_max: Vec):
    """Check if the given location can be a bottomless pit."""
    return BOTTOMLESS_PIT_MIN >= bbox_min.z


def load_settings(pit: Property):
    if not pit:
        SETTINGS.clear()
        # No pits are permitted..
        return

    SETTINGS.update({
        'should_tele': srctools.conv_bool(pit['teleport', '0']),
        'tele_dest': pit['tele_target', '@goo_targ'],
        'tele_ref': pit['tele_ref', '@goo_ref'],
        'off_x': srctools.conv_int(pit['off_x', '0']),
        'off_y': srctools.conv_int(pit['off_y', '0']),
        'skybox': pit['sky_inst', ''],
        'skybox_ceil': pit['sky_inst_ceil', ''],
        'targ': pit['targ_inst', ''],
        'blend_light': pit['blend_light', '']
    })
    for inst_type in (
        'support',
        'side',
        'corner',
        'double',
        'triple',
        'pillar',
    ):
        vals = [
            prop.value
            for prop in
            pit.find_all(inst_type + '_inst')
        ]
        if len(vals) == 0:
            vals = [""]
        PIT_INST[inst_type] = vals


def make_bottomless_pit(vmf: VMF, max_height):
    """Generate bottomless pits."""
    teleport = SETTINGS['should_tele']

    tele_ref = SETTINGS['tele_ref']
    tele_dest = SETTINGS['tele_dest']

    tele_off_x = SETTINGS['off_x'] + 64
    tele_off_y = SETTINGS['off_y'] + 64

    # Controlled by the style, not skybox!
    blend_light = vbsp.get_opt('pit_blend_light')

    if SETTINGS['skybox'] != '':
        # Add in the actual skybox edges and triggers.
        vmf.create_ent(
            classname='func_instance',
            file=SETTINGS['skybox'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} 0'.format(
                tele_off_x - 64,
                tele_off_y - 64,
            ),
        )

        fog_opt = vbsp.settings['fog']

        # Now generate the sky_camera, with appropriate values.
        sky_camera = vmf.create_ent(
            classname='sky_camera',
            scale='1.0',

            origin='{!s} {!s} 0'.format(
                tele_off_x - 64,
                tele_off_y - 64,
            ),

            angles=fog_opt['direction'],
            fogdir=fog_opt['direction'],
            fogcolor=fog_opt['primary'],
            fogstart=fog_opt['start'],
            fogend=fog_opt['end'],

            fogenable='1',

            heightFogStart=fog_opt['height_start'],
            heightFogDensity=fog_opt['height_density'],
            heightFogMaxDensity=fog_opt['height_max_density'],
        )

        if fog_opt['secondary']:
            # Only enable fog blending if a secondary color is enabled
            sky_camera['fogblend'] = '1'
            sky_camera['fogcolor2'] = fog_opt['secondary']
            sky_camera['use_angles'] = '1'
        else:
            sky_camera['fogblend'] = '0'
            sky_camera['use_angles'] = '0'

    if SETTINGS['skybox_ceil'] != '':
        # We dynamically add the ceiling so it resizes to match the map,
        # and lighting won't be too far away.
        vmf.create_ent(
            classname='func_instance',
            file=SETTINGS['skybox_ceil'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} {!s}'.format(
                tele_off_x - 64,
                tele_off_y - 64,
                max_height,
            ),
        )

    if SETTINGS['targ'] != '':
        # Add in the teleport reference target.
        vmf.create_ent(
            classname='func_instance',
            file=SETTINGS['targ'],
            targetname='skybox',
            angles='0 0 0',
            origin='0 0 0',
        )

    # To figure out what positions need edge pieces, we use a dict
    # indexed by XY tuples. The four Nones match the NSEW directions.
    # For each trigger, we loop through the grid points it's in. We
    # set all the center parts to None, but set the 4 neighbouring
    # blocks if they aren't None.
    # If a value = None, it is occupied by goo.
    edges = defaultdict(lambda: [None, None, None, None])
    dirs = [
        # x, y, offsets
        (0, 128),   # North
        (0, -128),  # South
        (128, 0),   # East
        (-128, 0)   # West
    ]
    if teleport:
        # Transform the skybox physics triggers into teleports to move cubes
        # into the skybox zone

        # Only use 1 entity for the teleport triggers. If multiple are used,
        # cubes can contact two at once and get teleported odd places.
        tele_trig = None
        for trig in vmf.by_class['trigger_multiple']:
            if trig['wait'] != '0.1' or trig in vbsp.IGNORED_BRUSH_ENTS:
                continue

            bbox_min, bbox_max = trig.get_bbox()
            origin = (bbox_min + bbox_max) / 2  # type: Vec
            # We only modify triggers which are below the given z-index
            if bbox_min.z > BOTTOMLESS_PIT_MIN:
                continue

            if tele_trig is None:
                tele_trig = trig
                trig['classname'] = 'trigger_teleport'
                trig['spawnflags'] = '4106'  # Physics and npcs
                trig['landmark'] = tele_ref
                trig['target'] = tele_dest
                trig.outputs.clear()
            else:
                tele_trig.solids.extend(trig.solids)
                trig.remove()

            for x, y in utils.iter_grid(
                min_x=int(bbox_min.x),
                max_x=int(bbox_max.x),
                min_y=int(bbox_min.y),
                max_y=int(bbox_max.y),
                stride=128,
            ):
                # Remove the pillar from the center of the item
                edges[x, y] = None
                for i, (xoff, yoff) in enumerate(dirs):
                    side = edges[x + xoff, y + yoff]
                    if side is not None:
                        side[i] = origin.z - 13

                if blend_light:
                    # Generate dim lights at the skybox location,
                    # to blend the lighting together.
                    vmf.create_ent(
                        classname='light',
                        origin='{} {} {}'.format(
                            x + 64,
                            y + 64,
                            origin.z + 3,
                        ),
                        _light=blend_light,
                        _fifty_percent_distance='256',
                        _zero_percent_distance='512',
                    )
                    vmf.create_ent(
                        classname='light',
                        origin='{} {} {}'.format(
                            x + tele_off_x,
                            y + tele_off_y,
                            origin.z + 3,
                        ),
                        _light=blend_light,
                        _fifty_percent_distance='256',
                        _zero_percent_distance='512',
                    )

            # The triggers are 26 high, make them 10 units thick to
            # make it harder to see the teleport
            for side in trig.sides():
                for plane in side.planes:
                    if plane.z > origin.z:
                        plane.z -= 16
        if tele_trig is not None:
            vbsp.IGNORED_BRUSH_ENTS.add(tele_trig)

    instances = SETTINGS['inst']

    side_types = {
        utils.CONN_TYPES.side: instances['side'],  # o|
        utils.CONN_TYPES.corner: instances['corner'],  # _|
        utils.CONN_TYPES.straight: instances['side'],  # Add this twice for |o|
        utils.CONN_TYPES.triple: instances['triple'],  # U-shape
        utils.CONN_TYPES.all: instances['pillar'],  # [o]
        utils.CONN_TYPES.none: [''],  # Never add instance if no walls
    }

    for (x, y), mask in edges.items():
        if mask is None:
            continue  # This is goo

        random.seed(str(x) + str(y) + 'sides')

        inst_type, angle = utils.CONN_LOOKUP[
            tuple((val is not None) for val in mask)
        ]

        file = random.choice(side_types[inst_type])

        if file != '':
            vmf.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_side',
                origin='{!s} {!s} {!s}'.format(
                    x + tele_off_x,
                    y + tele_off_y,
                    max(
                        x
                        for x in mask
                        if x is not None
                    ),
                ),
                angles=angle,
            ).make_unique()

        # Straight uses two side-instances in parallel - "|o|"
        if inst_type is utils.CONN_TYPES.straight:
            file = random.choice(side_types[inst_type])
            if file != '':
                vmf.create_ent(
                    classname='func_instance',
                    file=file,
                    targetname='goo_side',
                    origin='{!s} {!s} {!s}'.format(
                        x + tele_off_x,
                        y + tele_off_y,
                        max(
                            x
                            for x in mask
                            if x is not None
                        ),
                    ),
                    # Reverse direction
                    angles=Vec.from_str(angle) + (0, 180, 0),
                ).make_unique()

        random.seed(str(x) + str(y) + '-support')
        file = random.choice(instances['support'])

        if file != '':
            vmf.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_support',
                angles='0 ' + str(random.randrange(0, 360, 90)) + ' 0',
                origin='{!s} {!s} {!s}'.format(
                    x+tele_off_x,
                    y+tele_off_y,
                    BOTTOMLESS_PIT_MIN,
                ),
            ).make_unique()