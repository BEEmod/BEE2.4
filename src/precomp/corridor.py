"""Modify and analyse corridors in the map."""
from __future__ import annotations
from collections import Counter
from collections.abc import Iterator

from srctools import Vec, Matrix, logger
from srctools.vmf import EntityFixup, VMF, Entity
import attrs

from config.corridors import Options as CorrOptions
from . import instanceLocs, options, rand
from corridor import (
    GameMode, Direction, Orient,
    CORRIDOR_COUNTS, CORR_TO_ID, ID_TO_CORR,
    Corridor, ExportedConf, parse_filename,
)
import config
import utils
import user_errors


__all__ = [
    'Info', 'analyse_and_modify',
    # Re-exports:
    'GameMode', 'Direction', 'Orient',
    'CORRIDOR_COUNTS', 'CORR_TO_ID', 'ID_TO_CORR',
    'Corridor', 'ExportedConf', 'parse_filename',
]
LOGGER = logger.get_logger(__name__)


@attrs.define
class Info:
    """Information about the map retrieved from the corridors."""
    is_publishing: bool
    start_at_elevator: bool
    game_mode: GameMode
    _attrs: set[str] = attrs.field(init=False, factory=set)
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
        return name.casefold() in self._attrs

    def set_attr(self, *names: str) -> None:
        """Set these attributes to true."""
        for name in names:
            self._attrs.add(name.casefold())

    def unset_attr(self, name: str) -> None:
        """Unset a specific attribute. Avoid using."""
        folded = name.casefold()
        if folded in self._attrs:
            LOGGER.warning('Unsetting already-set voice attribute "{}"!', name)
            self._attrs.discard(folded)

    def iter_attrs(self) -> Iterator[str]:
        """Iterate over defined voice attributes."""
        yield from self._attrs


def select_corridor(
    conf: ExportedConf,
    direction: Direction, mode: GameMode, orient: Orient,
    ind: int, file: str,
) -> Corridor:
    """Select the corridor to use, from an existing file."""
    max_count = CORRIDOR_COUNTS[mode, direction]
    poss_corr = conf.corridors[mode, direction, orient]
    if not poss_corr:
        raise user_errors.UserError(user_errors.TOK_CORRIDOR_EMPTY_GROUP.format(
            orient=orient.value.title(),
            mode=mode.value.title(),
            dir=direction.value.title(),
        ))
    elif len(poss_corr) > max_count:
        # More than the entropy we have, use our randomisation.
        chosen = rand.seed(b'corridor', file).choice(poss_corr)
        LOGGER.info(
            '{}_{}_{} corridor randomised to {}',
            mode.value, direction.value, orient.value, chosen,
        )
    else:
        # Enough entropy, use editor index.
        chosen = poss_corr[ind % len(poss_corr)]
        LOGGER.info(
            '{}_{}_{} corridor selected {} -> {}',
            mode.value, direction.value, orient.value, ind, chosen,
        )
    return chosen


def apply_options(
    selected: ExportedConf, fixup: EntityFixup,
    direction: Direction, mode: GameMode,
    corridor: Corridor,
) -> None:
    """Apply options exposed by the group to the user."""
    settings = config.COMPILER.get_cur_conf(CorrOptions, CorrOptions.get_id(
        options.STYLE_ID(), mode, direction,
    ))
    LOGGER.info('Corridor options for {}_{}: {}', mode.value, direction.value, settings)
    for opt_id in (selected.global_opt_ids[mode, direction] | corridor.option_ids):
        try:
            option = selected.options[opt_id]
        except KeyError:
            LOGGER.warning('Unknown corridor option "{}"!', opt_id)
            continue
        value = settings.value_for(option)
        if value == utils.ID_RANDOM:
            rng = rand.seed(b'corr_opt', opt_id, mode.value, direction.value)
            value = rng.choice(option.values).id
        fixup[option.fixup] = value


def analyse_and_modify(
    vmf: VMF,
    conf: ExportedConf,
    elev_override: bool,
) -> Info:
    """Modify corridors to match configuration, and report map settings gleaned from them.

    elev_override indicates if we force the player to spawn in the elevator.
    """
    # The three elevators.
    file_coop_exit = instanceLocs.resolve_filter('[coopExit]')
    file_sp_exit = instanceLocs.resolve_filter('[spExit]')
    file_sp_entry = instanceLocs.resolve_filter('[spEntry]')

    file_door_frame = instanceLocs.resolve_filter('[door_frame]')

    # If shift is held, this is reversed.
    if utils.check_shift():
        LOGGER.info('Shift held, inverting configured elevator/chamber spawn!')
        elev_override = not elev_override

    if elev_override:
        # Make conditions set appropriately
        LOGGER.info('Forcing elevator spawn!')

    chosen_entry: Corridor | None = None
    chosen_exit: Corridor | None = None
    entry_fixups = EntityFixup()
    exit_fixups = EntityFixup()

    filenames: Counter[str] = Counter()
    # Use sets, so we can detect contradictory instances.
    seen_no_player_start: set[bool] = set()
    seen_game_modes: set[GameMode] = set()

    inst_elev_entry: Entity | None = None
    inst_elev_exit: Entity | None = None

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
                seen_no_player_start.add(item.fixup.bool('no_player_start'))
            orient = Matrix.from_angstr(item['angles'])
            origin = Vec.from_str(item['origin'])
            norm = orient.up()
            if norm.z > 0.5:
                corr_orient = Orient.DN
            elif norm.z < -0.5:
                corr_orient = Orient.UP
            else:
                corr_orient = Orient.HORIZONTAL
            corr_attach = corr_orient
            # entry_up is on the floor, so you travel *up*.
            if corr_dir is Direction.ENTRY:
                corr_orient = corr_orient.flipped

            chosen = select_corridor(conf, corr_dir, corr_mode, corr_orient, corr_ind, file)
            item['file'] = chosen.instance
            file = chosen.instance.casefold()

            if corr_dir is Direction.ENTRY:
                chosen_entry = chosen
                fixup = entry_fixups
            else:
                chosen_exit = chosen
                fixup = exit_fixups

            item.fixup['$type'] = corr_dir.value
            item.fixup['$direction'] = corr_orient.value
            item.fixup['$attach'] = corr_attach.value
            # Accumulate options into this so that it can be assigned to the elevator too.
            # Assign it to the instance after the above fixups are computed
            # so that they can be overridden if desired.

            fixup.update(chosen.fixups)
            apply_options(conf, fixup, corr_dir, corr_mode, chosen)
            item.fixup.update(fixup)

            if chosen.legacy:
                # Converted type, keep original angles and positioning.
                item['origin'] = origin - (0, 0, 64)
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
        elif file in file_coop_exit:
            seen_game_modes.add(GameMode.COOP)
            # Elevator instances don't get named - fix that...
            if elev_override:
                item.fixup['no_player_start'] = '1'
            item['targetname'] = 'coop_exit'
            inst_elev_exit = item
        elif file in file_sp_entry:
            seen_game_modes.add(GameMode.SP)
            if elev_override:
                item.fixup['no_player_start'] = '1'
            item['targetname'] = 'elev_entry'
            inst_elev_entry = item
        elif file in file_sp_exit:
            seen_game_modes.add(GameMode.SP)
            if elev_override:
                item.fixup['no_player_start'] = '1'
            item['targetname'] = 'elev_exit'
            inst_elev_exit = item
        # Skip frames and include the chosen corridor
        filenames[file] += 1

    LOGGER.debug('Instances present:\n{}', '\n'.join([
        f'- "{file}": {count}'
        for file, count in filenames.most_common()
    ]))

    LOGGER.info("Game Mode: {}", seen_game_modes)
    LOGGER.info("Player Start: {}", seen_no_player_start)

    if chosen_entry is None:
        raise user_errors.UserError(
            user_errors.TOK_CORRIDOR_NO_CORR_ITEM.format(kind=user_errors.TOK_CORRIDOR_ENTRY)
        )
    if chosen_exit is None:
        raise user_errors.UserError(
            user_errors.TOK_CORRIDOR_NO_CORR_ITEM.format(kind=user_errors.TOK_CORRIDOR_EXIT)
        )

    if not seen_game_modes:
        # Should be caught by above UserError if actually missing.
        raise Exception('Unknown game mode - No corridors??')
    if len(seen_game_modes) >= 2:
        raise user_errors.UserError(user_errors.TOK_CORRIDOR_BOTH_MODES)

    if not seen_no_player_start:
        # Should be caught by above UserError if missing, something else is wrong.
        raise Exception("Can't determine if preview is enabled - no fixups on corridors?")
    if len(seen_no_player_start) >= 2:
        # Should be impossible.
        raise Exception("Preview mode is both enabled and disabled! Recompile the map!")

    # Apply selected fixups to the elevator also.
    if inst_elev_entry is not None:
        inst_elev_entry.fixup.update(entry_fixups)
    if inst_elev_exit is not None:
        inst_elev_exit.fixup.update(exit_fixups)

    [is_publishing] = seen_no_player_start
    [game_mode] = seen_game_modes
    info = Info(
        is_publishing=is_publishing,
        start_at_elevator=elev_override or is_publishing,
        game_mode=game_mode,
        corr_entry=chosen_entry,
        corr_exit=chosen_exit,
    )
    instanceLocs.set_chosen_corridor(game_mode, {
        Direction.ENTRY: chosen_entry,
        Direction.EXIT: chosen_exit,
    })

    LOGGER.info('Map global info: {}', info)
    return info
