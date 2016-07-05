"""Generates Bottomless Pits."""
import random

from srctools import Vec, Property, VMF, Output
import srctools
import utils
import vbsp
import brushLoc

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

    tele_off = Vec(
        x=SETTINGS['off_x'],
        y=SETTINGS['off_y'],
    )

    # Controlled by the style, not skybox!
    blend_light = vbsp.get_opt('pit_blend_light')

    if SETTINGS['skybox'] != '':
        # Add in the actual skybox edges and triggers.
        vmf.create_ent(
            classname='func_instance',
            file=SETTINGS['skybox'],
            targetname='skybox',
            angles='0 0 0',
            origin=tele_off,
        )

        fog_opt = vbsp.settings['fog']

        # Now generate the sky_camera, with appropriate values.
        sky_camera = vmf.create_ent(
            classname='sky_camera',
            scale='1.0',

            origin=tele_off,

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
            origin=tele_off + (0, 0, max_height),
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

    # First, remove all of Valve's triggers inside pits.
    for trig in vmf.by_class['trigger_multiple'] | vmf.by_class['trigger_hurt']:
        if brushLoc.POS['world': Vec.from_str(trig['origin'])].is_pit:
            trig.remove()

    # Potential locations of bordering brushes..
    wall_pos = set()

    side_dirs = [
        (0, -128, 0),   # N
        (0, +128, 0),  # S
        (-128, 0, 0),   # E
        (+128, 0, 0)   # W
    ]

    # Only use 1 entity for the teleport triggers. If multiple are used,
    # cubes can contact two at once and get teleported odd places.
    tele_trig = None
    hurt_trig = None

    for grid_pos, block_type in brushLoc.POS.items():  # type: Vec, brushLoc.Block
        pos = brushLoc.grid_to_world(grid_pos)
        if not block_type.is_pit:
            continue

        # Physics objects teleport when they hit the bottom of a pit.
        if block_type.is_bottom:
            if tele_trig is None:
                tele_trig = vmf.create_ent(
                    classname='trigger_teleport',
                    spawnflags='4106',  # Physics and npcs
                    landmark=tele_ref,
                    target=tele_dest,
                    origin=pos,
                )
            tele_trig.solids.append(
                vmf.make_prism(
                    pos + (-64, -64, -64),
                    pos + (64, 64, -8),
                    mat='tools/toolstrigger',
                ).solid,
            )

        # Players, however get hurt as soon as they enter - that way it's
        # harder to see that they don't teleport.
        if block_type.is_top:
            if hurt_trig is None:
                hurt_trig = vmf.create_ent(
                    classname='trigger_hurt',
                    damagetype=32,  # FALL
                    spawnflags=1,  # CLients
                    damage=100000,
                    nodmgforce=1,  # No physics force when hurt..
                    damagemodel=0,  # Always apply full damage.
                    origin=pos,  # We know this is not in the void..
                )
            hurt_trig.solids.append(
                vmf.make_prism(
                    pos + (-64, -64, -64),
                    pos + (64, 64, 48),
                    mat='tools/toolstrigger',
                ).solid,
            )

        if not block_type.is_bottom:
            continue
        # Everything else is only added to the bottom-most position.

        if blend_light:
            # Generate dim lights at the skybox location,
            # to blend the lighting together.
            light_pos = pos + (0, 0, -60)
            vmf.create_ent(
                classname='light',
                origin=light_pos,
                _light=blend_light,
                _fifty_percent_distance='256',
                _zero_percent_distance='512',
            )
            vmf.create_ent(
                classname='light',
                origin=light_pos + tele_off,
                _light=blend_light,
                _fifty_percent_distance='256',
                _zero_percent_distance='512',
            )

            wall_pos.update([
                (pos + off).as_tuple()
                for off in
                side_dirs
            ])

    if tele_trig is not None:
        vbsp.IGNORED_BRUSH_ENTS.add(tele_trig)
    if hurt_trig is not None:
        vbsp.IGNORED_BRUSH_ENTS.add(hurt_trig)
        hurt_trig.outputs.append(
            Output(
                'OnHurtPlayer',
                '@goo_fade',
                'Fade',
            ),
        )

    # Now determine the position of side instances.
    # We use the utils.CONN_TYPES dict to determine instance positions
    # based on where nearby walls are.
        side_types = {
            utils.CONN_TYPES.side: PIT_INST['side'],  # o|
            utils.CONN_TYPES.corner: PIT_INST['corner'],  # _|
            utils.CONN_TYPES.straight: PIT_INST['side'],  # Add this twice for |o|
            utils.CONN_TYPES.triple: PIT_INST['triple'],  # U-shape
            utils.CONN_TYPES.all: PIT_INST['pillar'],  # [o]
        }

        LOGGER.info('Pit instances: {}', side_types)

    for pos in wall_pos:
        pos = Vec(pos)
        if not brushLoc.POS['world': pos].is_solid:
            # Not actually a wall here!
            continue

        # CONN_TYPES has n,s,e,w as keys - whether there's something in that direction.
        nsew = tuple(
            brushLoc.POS['world': pos + off].is_pit
            for off in
            side_dirs
        )
        LOGGER.info('Pos: {}, NSEW: {}, lookup: {}', pos, nsew, utils.CONN_LOOKUP[nsew])
        inst_type, angle = utils.CONN_LOOKUP[nsew]

        if inst_type is utils.CONN_TYPES.none:
            # Middle of the pit...
            continue

        random.seed('pit_' + str(pos.x) + str(pos.y) + 'sides')

        file = random.choice(side_types[inst_type])

        if file != '':
            vmf.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_side',
                origin=tele_off + pos,
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
                    origin=tele_off + pos,
                    # Reverse direction
                    angles=Vec.from_str(angle) + (0, 180, 0),
                ).make_unique()