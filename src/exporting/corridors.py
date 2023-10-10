"""Export corridor configuration."""
from __future__ import annotations

import pickle
import itertools

from srctools import Vec
import srctools.logger
import trio

from config.corridors import Config
from corridor import (
    Orient, Direction, GameMode,
    CORRIDOR_COUNTS, ID_TO_CORR,
    ExportedConf,
)
from . import ExportData, STEPS, StepResource
from packages.corridor import CorridorUI, CorridorGroup
import config
import editoritems


LOGGER = srctools.logger.get_logger(__name__)


@STEPS.add_step(prereq=[StepResource.EI_ITEMS], results=[StepResource.EI_DATA, StepResource.VCONF_DATA])
async def step_corridor_conf(exp_data: ExportData) -> None:
    """Override editoritems with the new corridor specifier."""
    style_id = exp_data.selected_style.id
    try:
        group = exp_data.packset.obj_by_id(CorridorGroup, style_id)
    except KeyError:
        raise Exception(f'No corridor group for style "{style_id}"!') from None

    export: ExportedConf = {}
    for mode, direction, orient in itertools.product(GameMode, Direction, Orient):
        conf = config.APP.get_cur_conf(
            Config,
            Config.get_id(style_id, mode, direction, orient),
            Config(),
        )
        try:
            inst_to_corr = {
                corr.instance.casefold(): corr
                for corr in group.corridors[mode, direction, orient]
            }
        except KeyError:
            # None defined for this corridor. This is not an error for vertical ones.
            (LOGGER.warning if orient is Orient.HORIZONTAL else LOGGER.debug)(
                'No corridors defined for {}:{}_{}',
                style_id, mode.value, direction.value
            )
            export[mode, direction, orient] = []
            continue

        if conf.enabled:
            chosen = [
                corr
                for corr_id, enabled in conf.enabled.items()
                if enabled and (corr := inst_to_corr.get(corr_id.casefold())) is not None
            ]

            if not chosen:
                LOGGER.warning(
                    'No corridors selected for {}:{}_{}_{}',
                    style_id,
                    mode.value, direction.value, orient.value,
                )
                chosen = group.defaults(mode, direction, orient)
        else:
            # Use default setup, don't warn.
            chosen = group.defaults(mode, direction, orient)

        for corr in chosen:
            exp_data.vbsp_conf.extend(await corr.config())
        export[mode, direction, orient] = list(map(CorridorUI.strip_ui, chosen))

    # Now write out.
    LOGGER.info('Writing corridor configuration...')
    pickle_data = await trio.to_thread.run_sync(pickle.dumps, export, pickle.HIGHEST_PROTOCOL)
    await trio.Path(exp_data.game.abs_path('bin/bee2/corridors.bin')).write_bytes(pickle_data)
    del pickle_data

    # Change out all the instances in items to names following a pattern.
    # This allows the compiler to easily recognise. Also force 64-64-64 offset.
    for item in exp_data.all_items:
        try:
            (mode, direction) = ID_TO_CORR[item.id]
        except KeyError:
            continue
        count = CORRIDOR_COUNTS[mode, direction]
        # For all items these are at the start.
        for i in range(count):
            item.set_inst(i, editoritems.InstCount(editoritems.FSPath(
                f'instances/bee2_corridor/{mode.value}/{direction.value}/corr_{i + 1}.vmf'
            )))
        item.offset = Vec(64, 64, 64)
        # If vertical corridors exist, allow placement there.
        has_vert = False
        if export[mode, direction, Orient.UP]:
            item.invalid_surf.discard(
                editoritems.Surface.FLOOR if direction is Direction.ENTRY else editoritems.Surface.CEIL
            )
            has_vert = True
        if export[mode, direction, Orient.DN]:
            item.invalid_surf.discard(
                editoritems.Surface.CEIL if direction is Direction.ENTRY else editoritems.Surface.FLOOR
            )
            has_vert = True
        if has_vert:
            # Add a rotation handle.
            item.handle = editoritems.Handle.QUAD
        # Set desired facing to make them face upright, no matter what.
        item.facing = editoritems.DesiredFacing.UP
