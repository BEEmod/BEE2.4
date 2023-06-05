"""Generates Bottomless Pits."""
from srctools import FrozenVec, Matrix, Vec, Keyvalues, VMF, Solid, Side, Output, Angle
import srctools.logger
import utils
from precomp import brushLoc, options, rand, conditions
import consts


LOGGER = srctools.logger.get_logger(__name__)

# The base of a pit must be below this z-pos to be considered a pit.
# It must basically be one of the bottom two grid positions.
BOTTOMLESS_PIT_MIN = 192

# The set config options for pits. If SETTINGS is empty, no pits are used.
SETTINGS: dict = {}  # TODO: Type correctly
PIT_INST = {}


def pits_allowed() -> bool:
    """Are bottomless pits allowed in the configs?"""
    return bool(SETTINGS)


def is_pit(bbox_min: Vec, bbox_max: Vec):
    """Check if the given location can be a bottomless pit."""
    return BOTTOMLESS_PIT_MIN >= bbox_min.z


def load_settings(pit: Keyvalues) -> None:
    if not pit:
        SETTINGS.clear()
        # No pits are permitted..
        return

    SETTINGS.update({
        'use_skybox': srctools.conv_bool(pit['teleport', '0']),
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
    import vbsp

    tele_ref = SETTINGS['tele_ref']
    tele_dest = SETTINGS['tele_dest']

    use_skybox = bool(SETTINGS['skybox'])

    if use_skybox:
        tele_off = Vec(
            x=SETTINGS['off_x'],
            y=SETTINGS['off_y'],
        )
    else:
        tele_off = Vec(0, 0, 0)

    # Controlled by the style, not skybox!
    blend_light = options.get(str, 'pit_blend_light')

    if use_skybox:
        # Add in the actual skybox edges and triggers.
        conditions.add_inst(
            vmf,
            file=SETTINGS['skybox'],
            targetname='skybox',
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
            conditions.add_inst(
                vmf,
                file=SETTINGS['skybox_ceil'],
                targetname='skybox',
                origin=tele_off + (0, 0, max_height),
            )

        if SETTINGS['targ'] != '':
            # Add in the teleport reference target.
            conditions.add_inst(
                vmf,
                file=SETTINGS['targ'],
                targetname='skybox',
                origin='0 0 0',
            )

    # First, remove all of Valve's triggers inside pits.
    for trig in vmf.by_class['trigger_multiple'] | vmf.by_class['trigger_hurt']:
        if brushLoc.POS.lookup_world(Vec.from_str(trig['origin'])).is_pit:
            trig.remove()

    # Potential locations of bordering brushes..
    wall_pos: set[FrozenVec] = set()

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

    for grid_pos, block_type in brushLoc.POS.items():
        pos = brushLoc.grid_to_world(grid_pos)
        if not block_type.is_pit:
            continue

        # Physics objects teleport when they hit the bottom of a pit.
        if block_type.is_bottom and use_skybox:
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
                    Vec(pos.x - 64, pos.y - 64, -128),
                    pos + (64, 64, 48 if use_skybox else 16),
                    mat='tools/toolstrigger',
                ).solid,
            )

        if not block_type.is_bottom:
            continue
        # Everything else is only added to the bottom-most position.

        if use_skybox and blend_light:
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

        wall_pos |= {
            (pos + off).freeze()
            for off in
            side_dirs
        }

    if hurt_trig is not None:
        hurt_trig.outputs.append(
            Output(
                'OnHurtPlayer',
                '@goo_fade',
                'Fade',
            ),
        )

    if not use_skybox:
        make_pit_shell(vmf)
        return

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
        if not brushLoc.POS.lookup_world(pos).is_solid:
            # Not actually a wall here!
            continue

        # CONN_TYPES has n,s,e,w as keys - whether there's something in that direction.
        nsew = tuple(
            brushLoc.POS.lookup_world(pos + off).is_pit
            for off in
            side_dirs
        )
        LOGGER.info('Pos: {}, NSEW: {}, lookup: {}', pos, nsew, utils.CONN_LOOKUP[nsew])
        inst_type, angle = utils.CONN_LOOKUP[nsew]

        if inst_type is utils.CONN_TYPES.none:
            # Middle of the pit...
            continue

        rng = rand.seed(b'pit', pos.x, pos.y)
        file = rng.choice(side_types[inst_type])

        if file != '':
            conditions.add_inst(
                vmf,
                file=file,
                targetname='goo_side',
                origin=tele_off + pos,
                angles=angle,
            ).make_unique()

        # Straight uses two side-instances in parallel - "|o|"
        if inst_type is utils.CONN_TYPES.straight:
            file = rng.choice(side_types[inst_type])
            if file != '':
                conditions.add_inst(
                    vmf,
                    file=file,
                    targetname='goo_side',
                    origin=tele_off + pos,
                    angles=Angle.from_str(angle) @ Matrix.from_yaw(180.0),
                ).make_unique()


def fix_base_brush(vmf: VMF, solid: Solid, face: Side):
    """Retexture the brush forming the bottom of a pit."""
    if SETTINGS['skybox'] != '':
        face.mat = 'tools/toolsskybox'
    else:
        # We have a pit shell, we don't want a bottom.
        vmf.remove_brush(solid)


def make_pit_shell(vmf: VMF):
    """If the pit is surrounded on all sides, we can just extend walls down.

    That avoids needing to use skybox workarounds."""
    LOGGER.info('Making pit shell...')
    for x in range(-8, 20):
        for y in range(-8, 20):
            block_types = [
                brushLoc.POS[x, y, z]
                for z in
                range(-15, 1)
            ]
            lowest = max((
                z for z in
                range(-15, 1)
                if block_types[z] is not brushLoc.Block.VOID
            ), default=None)

            if lowest is None:
                continue
                # TODO: For opened areas (Wheatley), generate a floor...
                real_pos = brushLoc.grid_to_world(Vec(x, y, 0))
                prism = vmf.make_prism(
                    real_pos + (64, 64, BOTTOMLESS_PIT_MIN + 8),
                    real_pos + (-64, -64, BOTTOMLESS_PIT_MIN),
                    mat='tools/toolsnodraw',
                )
                prism.bottom.mat = consts.Special.BACKPANELS_CHEAP

                vmf.add_brush(prism.solid)
                continue

            if block_types[lowest].is_solid:
                real_pos = brushLoc.grid_to_world(Vec(x, y, lowest))
                for z in range(0, 10):
                    br_pos = real_pos - (0, 0, 512 * z)
                    vmf.add_brush(
                        vmf.make_prism(br_pos + 64, br_pos - (64, 64, 512-64), "metal/black_wall_metal_002c").solid
                    )

    prism = vmf.make_prism(
        Vec(-8 * 128, -8 * 128, -4864),
        Vec(20 * 128, 20 * 128, -4896),
    )
    prism.top.mat = 'tools/toolsblack'
    vmf.add_brush(prism.solid)

    diss_trig = vmf.create_ent(
        classname='trigger_multiple',
        spawnflags=4104,
        wait=0.1,
        origin=options.get(Vec, 'global_pti_ents_loc'),
    )
    diss_trig.solids = [vmf.make_prism(
        Vec(-8 * 128, -8 * 128, -4182),
        Vec(20 * 128, 20 * 128, -4864),
        mat='tools/toolstrigger',
    ).solid]
    diss_trig.add_out(
        Output('OnStartTouch', '!activator', 'SilentDissolve'),
        Output('OnStartTouch', '!activator', 'Break', delay=0.1),
        Output('OnStartTouch', '!activator', 'Kill', delay=0.5),
    )

    # Since we can chuck gel down the pit, cover it in a noportal_volume
    # to stop players from portalling past the hurt trigger.
    diss_trig = vmf.create_ent(
        classname='func_noportal_volume',
        origin=options.get(Vec, 'global_pti_ents_loc'),
    )
    diss_trig.solids = [vmf.make_prism(
        Vec(-8 * 128, -8 * 128, -64),
        Vec(20 * 128, 20 * 128, -4864),
        mat='tools/toolstrigger',
    ).solid]
