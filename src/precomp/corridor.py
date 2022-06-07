"""Modify and anylsyse corridors in the map."""
from __future__ import annotations
from collections import Counter
from typing import Dict

import attrs
from srctools import Matrix, VMF, Vec, Angle
import srctools.logger

import consts
import utils
from . import instanceLocs, rand
from corridor import (
    GameMode, Direction, Orient,
    CORRIDOR_COUNTS, CORR_TO_ID, ID_TO_CORR,
    Corridor, ExportedConf, parse_filename,
)


LOGGER = srctools.logger.get_logger(__name__)


@attrs.define
class Info:
    """Information about the map retrieved from the corridors."""
    is_publishing: bool
    start_at_elevator: bool
    game_mode: GameMode
    _attrs: Dict[str, bool]
    # The used corridor instances.
    corr_entry: Corridor
    corr_exit: Corridor

    @property
    def is_sp(self) -> bool:
        """Check if the map is in singleplayer mode."""
        return self.game_mode is GameMode.SP

    @property
    def is_coop(self) -> bool:
        """Check if the map is in coop mode."""
        return self.game_mode is GameMode.COOP

    @property
    def is_preview(self) -> bool:
        """Check if the map is preview mode."""
        return not self.is_publishing

    @property
    def start_in_corridor(self) -> bool:
        """Check if we start in the corridor."""
        return not self.start_at_elevator

    def has_attr(self, name: str) -> bool:
        """Check if this attribute is present in the map."""
        return self._attrs[name.casefold()]

    def set_attr(self, *names: str) -> None:
        """Set these attributes to true."""
        for name in names:
            self._attrs[name.casefold()] = True


def analyse_and_modify(
    vmf: VMF,
    conf: ExportedConf,
    elev_override: bool,
    voice_attrs: Dict[str, bool],
) -> Info:
    """Modify corridors to match configuration, and report map settings gleaned from them.

    elev_override indicates if we force the player to spawn in the elevator.
    """
    # The three elevators.
    file_coop_exit = instanceLocs.get_special_inst('coopExit')
    file_sp_exit = instanceLocs.get_special_inst('spExit')
    file_sp_entry = instanceLocs.get_special_inst('spEntry')

    file_door_frame = instanceLocs.get_special_inst('door_frame')

    # If shift is held, this is reversed.
    if utils.check_shift():
        LOGGER.info('Shift held, inverting configured elevator/chamber spawn!')
        elev_override = not elev_override

    if elev_override:
        # Make conditions set appropriately
        LOGGER.info('Forcing elevator spawn!')

    chosen_entry: Corridor | None = None
    chosen_exit: Corridor | None = None

    filenames: Counter[str] = Counter()
    # Use sets, so we can detect contradictory instances.
    seen_no_player_start: set[bool] = set()
    seen_game_modes: set[GameMode] = set()

    for item in vmf.by_class['func_instance']:
        # Loop through all the instances in the map, looking for the entry/exit
        # doors.
        # - Read the $no_player_start var to see if we're in preview mode,
        #   or override the value if specified in compile.cfg
        # - Determine whether the map is SP or Coop by the
        #   presence of certain instances.
        # - Switch the entry/exit corridors to particular ones if specified
        #   in compile.cfg
        # Also build a set of all instances, to make a condition check easy later.

        file = item['file'].casefold()
        corr_info = parse_filename(item['file'])
        if corr_info is not None:
            corr_mode, corr_dir, corr_ind = corr_info
            seen_game_modes.add(corr_mode)
            if 'no_player_start' in item.fixup:
                seen_no_player_start.add(srctools.conv_bool(item.fixup['no_player_start']))
            orient = Matrix.from_angle(Angle.from_str(item['angles']))
            origin = Vec.from_str(item['origin'])
            norm = orient.up()
            if norm.z > 0.5:
                corr_orient = Orient.DN
            elif norm.z < -0.5:
                corr_orient = Orient.UP
            else:
                corr_orient = Orient.HORIZONTAL
            corr_attach = corr_orient
            # entry_up is on the floor, so you go *up*.
            if corr_dir is Direction.ENTRY:
                corr_orient = corr_orient.flipped

            max_count = CORRIDOR_COUNTS[corr_mode, corr_dir]
            poss_corr = conf[corr_mode, corr_dir, corr_orient]
            if not poss_corr:
                raise ValueError(
                    f'No corridors available for {corr_orient.value} {corr_mode.value} '
                    f'{corr_dir.value.title()}!'
                )
            elif len(poss_corr) > max_count:
                # More than the entropy we have, use our randomisation.
                chosen = rand.seed(b'corridor', file).choice(poss_corr)
                LOGGER.info(
                    '{}_{}_{} corridor randomised to {}',
                    corr_mode.value, corr_dir.value, corr_orient.value, chosen,
                )
            else:
                # Enough entropy, use editor index.
                chosen = poss_corr[corr_ind % len(poss_corr)]
                LOGGER.info(
                    '{}_{}_{} corridor selected {} -> {}',
                    corr_mode.value, corr_dir.value, corr_orient.value, corr_ind, chosen,
                )
            item['file'] = chosen.instance
            file = chosen.instance.casefold()

            if corr_dir is Direction.ENTRY:
                chosen_entry = chosen
            else:
                chosen_exit = chosen

            item.fixup['$type'] = corr_dir.value
            item.fixup['$direction'] = corr_orient.value
            item.fixup['$attach'] = corr_attach.value
            # Do after so it overwrites these automatic ones.
            item.fixup.update(chosen.fixups)

            if chosen.legacy:
                # Converted type, keep original angles and positioning.
                item['origin'] = origin - (0, 0, 64)
                # And write the index.
                item.fixup[consts.FixupVars.BEE_CORR_INDEX] = chosen.orig_index
            # Otherwise, give more useful orientations for building instances.
            # Keep it upright, with x pointing in the door direction for horizontal.
            else:
                orient = Matrix.from_basis(
                    x=norm if corr_orient is Orient.HORIZONTAL else orient.forward(),
                    z=Vec(0, 0, 1.0),
                )
                item['angles'] = orient.to_angle()
        elif file in file_door_frame:
            # Tiling means this isn't useful, we always use templates.
            item.remove()
            continue
        elif file_coop_exit == file:
            seen_game_modes.add(GameMode.COOP)
            # Elevator instances don't get named - fix that...
            item['targetname'] = 'coop_exit'
            if elev_override:
                item.fixup['no_player_start'] = '1'
        elif file_sp_exit == file or file_sp_entry == file:
            seen_game_modes.add(GameMode.SP)
            if elev_override:
                item.fixup['no_player_start'] = '1'
            # Elevator instances don't get named - fix that...
            item['targetname'] = (
                'elev_entry' if
                file_sp_entry == file
                else 'elev_exit'
            )
        # Skip frames and include the chosen corridor
        filenames[file] += 1

    LOGGER.debug('Instances present:\n{}', '\n'.join([
        f'- "{file}": {count}'
        for file, count in filenames.most_common()
    ]))

    LOGGER.info("Game Mode: {}", seen_game_modes)
    LOGGER.info("Player Start: {}", seen_no_player_start)

    if not seen_game_modes:
        raise Exception('Unknown game mode - Map missing exit room!')
    if len(seen_game_modes) > 2:
        raise Exception('Both singleplayer and coop corridors present! This is nonsensical!')

    if not seen_no_player_start:
        raise Exception(
            "Can't determine if preview is enabled "
            '- Map likely missing entry room!'
        )
    if len(seen_no_player_start) > 2:
        raise Exception("Preview mode is both enabled and disabled! Recompile the map!")

    if chosen_entry is None:
        raise Exception('Entry corridor is missing!')
    if chosen_exit is None:
        raise Exception('Exit corridor is missing!')

    [is_publishing] = seen_no_player_start
    [game_mode] = seen_game_modes
    info = Info(
        is_publishing=is_publishing,
        start_at_elevator=elev_override or is_publishing,
        game_mode=game_mode,
        attrs=voice_attrs,  # Todo: remove from settings.
        corr_entry=chosen_entry,
        corr_exit=chosen_exit,
    )
    instanceLocs.set_chosen_corridor(game_mode, {
        Direction.ENTRY: chosen_entry,
        Direction.EXIT: chosen_exit,
    })

    LOGGER.info('Map global info: {}', info)
    return info
