"""Implement Shredders.

Shredders are a variation on Goo which can be placed in different orientations.
There are 3 mostly-separate styles
"""
from typing import Set, List, Tuple, Iterable

import conditions
import template_brush
import utils
import comp_consts as const
from brushLoc import POS as BLOCK_POS, Block
from conditions import make_result
from srctools import Property, VMF, Entity, Solid, Output, Vec


COND_MOD_NAME = 'Main Conditions'

LOGGER = utils.getLogger(__name__, alias='cond.core')

# We use this to ensure multiple shredders in the same pit do not intersect.
ALL_SHREDDERS = set()  # type: Set[Tuple[float, float, float]]


def group_lengths(pos: List[float]):
    """Group up offsets into runs in order. The positions need to be sorted."""
    min_pos = pos[0]
    expect_pos = pos[0] + 128
    run = None
    for run in pos[1:]:
        if run != expect_pos:
            yield min_pos, expect_pos - 128
            min_pos = run
        expect_pos = run + 128
    if run is None:
        yield min_pos, min_pos
    else:
        yield min_pos, run


def get_factory_model(model_type: str, side: str, size: int) -> str:
    """Get the BTS model for a specific size and type."""
    return f'models/BEE2/props_bts/shredder/{side}_{model_type}_{size//128}.mdl'


@make_result('Shredder')
def res_shredder(vmf: VMF, inst: Entity, res: Property):
    """Implement Shredders.

    Parameters:
        "type": "factory", "furnace", or "spikepit"
    """
    normal = Vec(x=-1).rotate_by_str(inst['angles'])
    forward = Vec(z=1).rotate_by_str(inst['angles'])
    side = Vec(y=1).rotate_by_str(inst['angles'])

    # Recursively add all neighbours to positions.
    positions = [Vec.from_str(inst['origin'])]  # type: List[Vec]
    if positions[0].as_tuple() in ALL_SHREDDERS:
        # Another shredder was placed here. Quit.
        inst.remove()
        return
    ALL_SHREDDERS.add(positions[0].as_tuple())

    for pos in positions:
        for neighbour in [
            pos - 128*forward,
            pos + 128*forward,
            pos - 128*side,
            pos + 128*side,
        ]:
            if neighbour.as_tuple() not in ALL_SHREDDERS:
                if BLOCK_POS['world': neighbour] is Block.AIR:
                    if BLOCK_POS['world': neighbour - 128*normal] is Block.AIR:
                        ALL_SHREDDERS.add(neighbour.as_tuple())
                        positions.append(neighbour)

    shred_type = res['type'].casefold()
    try:
        func = globals()['make_shredder_' + shred_type]
    except KeyError:
        raise ValueError('Unknown shredder type "{}"!'.format(shred_type)) from None

    func(vmf, inst, res, positions, normal, forward, side)


def make_shredder_factory(
    vmf: VMF,
    inst: Entity,
    res: Property,
    positions: List[Vec],
    normal: Vec,
    forward: Vec,
    side: Vec,
):
    """Make BTS-style shredders."""
    bbox_min, bbox_max = Vec.bbox(positions)
    norm_off = positions[0][normal.axis()]
    forward_ax = forward.axis()
    side_ax = side.axis()

    grinder_angles = Vec.with_axes(forward_ax, 1).to_angle()

    rotator_template = template_brush.get_template('BEE2_SHREDDER_FACTORY_ROT')

    trigger_hurt = vmf.create_ent(
        classname='trigger_hurt',
        targetname=conditions.local_name(inst, 'trigger'),
        origin=positions[0],
        damage=10000,
        damagetype=4+1,  # CRUSH + SLASH
        spawnflags=1,  # Clients
        startdisabled=0,
    )

    trigger_physics = vmf.create_ent(
        classname='trigger_multiple',
        targetname=conditions.local_name(inst, 'trigger'),
        origin=positions[0],
        startdisabled=0,
        spawnflags=72,  # Physics Objects + NPCs + Everything
    )
    trigger_physics.add_out(
        Output('OnStartTouch', '!activator', 'SelfDestructImmediately'),
        Output('OnStartTouch', '!activator', 'Dissolve'),
        Output('OnStartTouch', '!activator', 'Break', delay=0.1),
    )

    for col_num, side_off in enumerate(range(
        int(bbox_min[side_ax]),
        int(bbox_max[side_ax]) + 1,
        128,
    )):
        columns = [
            pos[forward_ax]
            for pos in positions
            if round(pos[side_ax]) == side_off
        ]
        columns.sort()

        if not columns:
            continue

        rot_name = conditions.local_name(inst, f'rot_{col_num+1}')
        side = 'left' if col_num % 2 == 0 else 'right'

        spawnflags = 256 + 16  # Medium Sound Radius + Acc/Dcc
        if forward_ax == 'x':
            spawnflags += 4
        elif forward_ax == 'y':
            spawnflags += 8
        if side == 'left':
            spawnflags += 2  # Reverse.

        column_pos = Vec.with_axes(
            normal.axis(), norm_off,
            side_ax, side_off,
        ) - 64 * normal

        rotator = vmf.create_ent(
            'func_rotating',
            targetname=rot_name,
            origin=column_pos + Vec.with_axes(forward_ax, columns[0]),
            volume=4,
            message='World.GrinderLp',
            dmg=1000,  # Insta-kill.
            spawnflags=spawnflags,
        )

        for min_off, max_off in group_lengths(columns):
            cylinder = template_brush.import_template(
                rotator_template,
                column_pos + Vec.with_axes(forward_ax, min_off),
                grinder_angles,
                add_to_map=False,
                force_type=template_brush.TEMP_TYPES.world,
            )
            rotator.solids.extend(cylinder.world)
            # Resize to the needed size, by finding the marked faces.
            front_faces = {
                cylinder.orig_ids[int(face)]
                for face in
                rotator_template.realign_faces
            }
            for face in rotator.solids[-1].sides:
                if face.id in front_faces:
                    face.translate(forward * (max_off - min_off))

            trigger_brush = vmf.make_prism(
                column_pos + Vec.with_axes(
                    side_ax, 64,
                    forward_ax, min_off-64,
                ) + 70 * normal,
                column_pos + Vec.with_axes(
                    side_ax, -64,
                    forward_ax, max_off+64,
                ) - 128 * normal,
                mat=const.Tools.TRIGGER,
            )
            trigger_hurt.solids.append(trigger_brush.solid)
            trigger_physics.solids.append(trigger_brush.solid.copy())

            model_sizes = utils.fit(max_off - min_off + 128, (1024, 512, 256, 128))
            model_off = min_off - 64
            for model_size in model_sizes:
                vmf.create_ent(
                    'prop_dynamic',
                    origin=column_pos + Vec.with_axes(
                        forward_ax,
                        model_off + model_size / 2,
                    ),
                    model=get_factory_model('grind', side, model_size),
                    # The original model does a full rotation, and is 1024 units
                    # long. So figure out an appropriate rotation for this offset.
                    angles=grinder_angles - Vec(z=model_off * 360/1024),
                    parentname=rot_name,
                )

                model_off += model_size


def make_shredder_spikepit(
    vmf: VMF,
    inst: Entity,
    res: Property,
    positions: List[Vec],
    normal: Vec,
    forward: Vec,
    side: Vec,
):
    """Make spike pit shredders, for Old Aperture."""
    raise NotImplementedError


def make_shredder_portal1(
    vmf: VMF,
    inst: Entity,
    res: Property,
    positions: List[Vec],
    normal: Vec,
    forward: Vec,
    side: Vec,
):
    """Make Incinerator-style shredders, for Portal 1."""
    raise NotImplementedError
