"""Modify and anylsyse corridors in the map."""
from collections import defaultdict, Counter
from typing import Dict
from typing_extensions import Literal

import attrs
from srctools import Entity, VMF, Vec, Angle
import srctools.logger

import BEE2_config
import consts
import utils
from . import instanceLocs


LOGGER = srctools.logger.get_logger(__name__)


@attrs.define
class Info:
    """Information about the map retrieved from the corridors."""
    is_publishing: bool
    start_at_elevator: bool
    is_coop: bool
    _attrs: Dict[str, bool] = attrs.Factory(lambda: defaultdict(bool))

    @property
    def is_sp(self) -> bool:
        """Check if this is in singleplayer mode."""
        return not self.is_coop

    @property
    def is_preview(self) -> bool:
        """Check if this is preview mode."""
        return not self.is_publishing

    @property
    def start_in_corridor(self) -> bool:
        """Check if we start in the corridor."""
        return not self.start_at_elevator

    def has_attr(self, name: str) -> bool:
        """Check if this attribute is present in the map."""
        return self._attrs[name.casefold()]

    def set_attr(self, name: str):
        """Set this attribute to true."""
        self._attrs[name.casefold()] = True


def analyse_and_modify(vmf: VMF, conf: BEE2_config.ConfigFile, voice_attrs: Dict[str, bool]) -> Info:
    """Modify corridors to match configuration, and report map settings gleaned from them."""
    file_coop_entry = instanceLocs.get_special_inst('coopEntry')
    file_coop_exit = instanceLocs.get_special_inst('coopExit')
    file_sp_exit = instanceLocs.get_special_inst('spExit')
    file_sp_entry = instanceLocs.get_special_inst('spEntry')

    # These have multiple instances, so 'in' must be used.
    # If both frames are set to "", get_special returns None so fix that.
    file_coop_corr = instanceLocs.get_special_inst('coopCorr')
    file_sp_entry_corr = instanceLocs.get_special_inst('spEntryCorr')
    file_sp_exit_corr = instanceLocs.get_special_inst('spExitCorr')
    file_sp_door_frame = instanceLocs.get_special_inst('door_frame_sp')
    file_coop_door_frame = instanceLocs.get_special_inst('door_frame_coop')

    # Should we force the player to spawn in the elevator?
    elev_override = conf.get_bool('General', 'spawn_elev')
    # If shift is held, this is reversed.
    if utils.check_shift():
        LOGGER.info('Shift held, inverting configured elevator/chamber spawn!')
        elev_override = not elev_override

    if elev_override:
        # Make conditions set appropriately
        LOGGER.info('Forcing elevator spawn!')

    # Door frames use the same instance for both the entry and exit doors,
    # and it'd be useful to distinguish between them. Add an instvar to help.
    door_frames = []
    entry_origin = Vec(-999, -999, -999)
    exit_origin = Vec(-999, -999, -999)

    exit_fixup = entry_fixup = None  # Copy the exit/entry fixup to the frame.

    override_sp_entry = conf.get_int('Corridor', 'sp_entry', 0)
    override_sp_exit = conf.get_int('Corridor', 'sp_exit', 0)
    override_coop_corr = conf.get_int('Corridor', 'coop', 0)

    # The type of corridor - used to replace doorframes, if needed.
    # 0-7 = normal, 'up'/'down' = vert up/down
    entry_corr_type = exit_corr_type = 0
    entry_corr_name = exit_corr_name = ""

    # The door frame instances
    entry_door_frame = exit_door_frame = None

    filenames = Counter()
    # Use sets, so we can detect contradictory instances.
    no_player_start: set[bool] = set()
    game_mode: set[Literal['SP', 'COOP']] = set()

    for item in vmf.by_class['func_instance']:
        # Loop through all the instances in the map, looking for the entry/exit
        # doors.
        # - Read the $no_player_start var to see if we're in preview mode,
        #   or override the value if specified in compile.cfg
        # - Determine whether the map is SP or Coop by the
        #   presence of certain instances.
        # - Switch the entry/exit corridors to particular ones if specified
        #   in compile.cfg
        # Also build a set of all instances, to make a condition check easy
        # later

        file = item['file'].casefold()
        filenames[file] += 1
        if file in file_sp_exit_corr:
            game_mode.add('SP')
            # In SP mode the same instance is used for entry and exit door
            # frames. Use the position of the item to distinguish the two.
            # We need .rotate() since they could be in the same block.
            exit_origin = Vec(0, 0, -64) @ Angle.from_str(item['angles'])
            exit_origin += Vec.from_str(item['origin'])
            exit_corr_name = item['targetname']
            exit_fixup = item.fixup
            exit_corr_type = mod_entryexit(
                item,
                'spExitCorr',
                'SP Exit',
                elev_override,
                override_sp_exit,
                is_exit=True,
            )
            no_player_start.add(srctools.conv_bool(item.fixup['no_player_start']))
        elif file in file_sp_entry_corr:
            game_mode.add('SP')
            entry_origin = Vec(0, 0, -64) @ Angle.from_str(item['angles'])
            entry_origin += Vec.from_str(item['origin'])
            entry_corr_name = item['targetname']
            entry_fixup = item.fixup
            entry_corr_type = mod_entryexit(
                item,
                'spEntryCorr',
                'SP Entry',
                elev_override,
                override_sp_entry,
            )
            no_player_start.add(srctools.conv_bool(item.fixup['no_player_start']))
        elif file in file_coop_corr:
            game_mode.add('COOP')
            exit_corr_name = item['targetname']
            exit_fixup = item.fixup
            exit_corr_type = mod_entryexit(
                item,
                'coopCorr',
                'Coop Exit',
                elev_override,
                override_coop_corr,
                is_exit=True,
            )
            no_player_start.add(srctools.conv_bool(item.fixup['no_player_start']))
        elif file_coop_entry == file:
            game_mode.add('COOP')
            entry_corr_name = item['targetname']
            entry_fixup = item.fixup
            mod_entryexit(
                item,
                'coopCorr',
                'Coop Spawn',
                elev_override,
            )
        elif file_coop_exit == file:
            game_mode.add('COOP')
            # Elevator instances don't get named - fix that...
            item['targetname'] = 'coop_exit'
            if elev_override:
                item.fixup['no_player_start'] = '1'
        elif file_sp_exit == file or file_sp_entry == file:
            game_mode.add('SP')
            if elev_override:
                item.fixup['no_player_start'] = '1'
            # Elevator instances don't get named - fix that...
            item['targetname'] = (
                'elev_entry' if
                file_sp_entry == file
                else 'elev_exit'
            )
        elif file in file_sp_door_frame:
            # We need to inspect origins to determine the entry door type.
            door_frames.append(item)
        elif file in file_coop_door_frame:
            # The coop frame must be the exit door...
            exit_door_frame = item

    LOGGER.debug('Instances present:\n{}', '\n'.join([
        f'- "{file}": {count}'
        for file, count in filenames.most_common()
    ]))

    LOGGER.info("Game Mode: {}", game_mode)
    LOGGER.info("Player Start: {}", no_player_start)

    if not game_mode:
        raise Exception('Unknown game mode - Map missing exit room!')
    elif len(game_mode) > 2:
        raise Exception('Both singleplayer and coop corridors present! This is nonsensical!')

    if not no_player_start:
        raise Exception(
            "Can't determine if preview is enabled "
            '- Map likely missing entry room!'
        )
    if len(no_player_start) > 2:
        raise Exception("Preview mode is both enabled and disabled! Recompile the map!")

    # Now check the door frames, to allow distinguishing between
    # the entry and exit frames.
    for door_frame in door_frames:
        origin = Vec(0, 0, -64) @ Angle.from_str(door_frame['angles'])
        # Corridors are placed 64 units below doorframes - reverse that.
        origin.z -= 64
        origin += Vec.from_str(door_frame['origin'])
        if origin == entry_origin:
            door_frame.fixup['door_type'] = 'entry'
            entry_door_frame = door_frame
            if entry_fixup is not None:
                # Copy the entry-door's fixup values to the frame itself..
                door_frame.fixup.update(entry_fixup)
        elif origin == exit_origin:
            door_frame.fixup['door_type'] = 'exit'
            exit_door_frame = door_frame
            if exit_fixup is not None:
                door_frame.fixup.update(exit_fixup)

    [is_publishing] = no_player_start
    info = Info(
        is_publishing=is_publishing,
        start_at_elevator=elev_override or is_publishing,
        is_coop='COOP' in game_mode,
        attrs=voice_attrs,  # Todo: remove from settings.
    )

    if info.is_coop:
        mod_doorframe(
            exit_door_frame,
            'ITEM_COOP_EXIT_DOOR',
            exit_corr_type,
            exit_corr_name,
        )
    else:
        mod_doorframe(
            entry_door_frame,
            'ITEM_ENTRY_DOOR',
            entry_corr_type,
            entry_corr_name,
        )
        mod_doorframe(
            exit_door_frame,
            'ITEM_EXIT_DOOR',
            exit_corr_type,
            exit_corr_name,
        )
    LOGGER.info('Map global info: {}', info)
    return info


def mod_entryexit(
    inst: Entity,
    resolve_name: str,
    pretty_name: str,
    elev_override: bool = False,
    override_corr: int = -1,
    is_exit: bool = False,
) -> str:
    """Modify this entrance or exit.

    This sets IS_PREVIEW, switches to vertical variants, and chooses a
    particular corridor number.
    This returns the corridor used - 1-7, 'up', or 'down'.
    The corridor used is also copied to '$corr_index'.
    """
    normal = Vec(0, 0, 1) @ Angle.from_str(inst['angles'])

    if is_exit:
        # Swap the normal direction, so the up/down names match the direction
        # of travel.
        normal = -normal

    vert_up = instanceLocs.get_special_inst(resolve_name + 'Up')
    vert_down = instanceLocs.get_special_inst(resolve_name + 'Down')
    files = instanceLocs.get_special_inst(resolve_name)

    # The coop spawn instance doesn't have no_player_start...
    if 'no_player_start' in inst.fixup and elev_override:
        inst.fixup['no_player_start'] = '1'

    if normal == (0, 0, 1) and vert_up is not None:
        LOGGER.info(
            'Using upward variant for {}',
            pretty_name,
        )
        inst['file'] = vert_up
        return 'vert_up'

    if normal == (0, 0, -1) and vert_down is not None:
        LOGGER.info(
            'Using downward variant for {}',
            pretty_name,
        )
        inst['file'] = vert_down
        return 'vert_down'

    if override_corr == -1:
        return '0'  # There aren't any variants (coop spawn room)

    if override_corr == 0:
        index = files.index(inst['file'].casefold())
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = index + 1
        LOGGER.info(
            'Using random {} ({})',
            pretty_name,
            index + 1,
        )
        return str(index)
    else:
        LOGGER.info(
            'Setting {} to {}',
            pretty_name,
            override_corr,
        )
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = override_corr
        inst['file'] = files[override_corr - 1]
        return str(override_corr - 1)


def mod_doorframe(inst: Entity, corr_id: str, corr_type: str, corr_name: str) -> None:
    """Change the instance used by door frames, if desired.

    corr_id is the item ID of the dooor, and corr_type is the
    return value of mod_entryexit(). corr_name is the name of the corridor.
    """
    if inst is None:
        return  # This doorframe doesn't exist...

    is_white = inst['file'].casefold() in instanceLocs.get_special_inst(
        'white_frame',
    )

    inst['targetname'] = corr_name

    replace = instanceLocs.get_cust_inst(
        # Allow using a custom instance path to replace corridor types:
        # "frame_1_white", "frame_vert_down_white"
        corr_id,
        'frame_{type}_{color}'.format(
            type=corr_type,
            color='white' if is_white else 'black',
        )
    )
    if replace is not None:
        inst['file'] = replace
