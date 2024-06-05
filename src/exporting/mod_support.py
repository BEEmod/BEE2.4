"""Special behaviour for detecting and copying files from Mel and Tag."""
from __future__ import annotations
from typing import TYPE_CHECKING, Final
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
import math
import os

from srctools import VMF, Keyvalues, Output, Vec
from srctools.filesys import File, RawFileSystem, VPKFileSystem
import srctools.logger
import trio

from packages import PackagesSet
import utils

from . import STAGE_MUSIC, STEPS, ExportData, StepResource


if TYPE_CHECKING:
    from app.gameMan import Game


# The location of the relevant filesystem.
MUSIC_MEL_DIR: Final = 'Portal Stories Mel/portal_stories/pak01_dir.vpk'
MUSIC_TAG_DIR: Final = 'aperture tag/aperturetag/sound/music'

LOGGER = srctools.logger.get_logger(__name__)

# All the PS:Mel track names - all the resources are in the VPK,
# this allows us to skip looking through all the other files...
MEL_MUSIC_NAMES: Final[Sequence[str]] = [
    'portal2_background01.wav',
    'sp_a1_garden.wav',
    'sp_a1_lift.wav',
    'sp_a1_mel_intro.wav',
    'sp_a1_tramride.wav',
    'sp_a2_dont_meet_virgil.wav',
    'sp_a2_firestorm_exploration.wav',
    'sp_a2_firestorm_explosion.wav',
    'sp_a2_firestorm_openvault.wav',
    'sp_a2_garden_destroyed_01.wav',
    'sp_a2_garden_destroyed_02.wav',
    'sp_a2_garden_destroyed_portalgun.wav',
    'sp_a2_garden_destroyed_vault.wav',
    'sp_a2_once_upon.wav',
    'sp_a2_past_power_01.wav',
    'sp_a2_past_power_02.wav',
    'sp_a2_underbounce.wav',
    'sp_a3_concepts.wav',
    'sp_a3_concepts_funnel.wav',
    'sp_a3_faith_plate.wav',
    'sp_a3_faith_plate_funnel.wav',
    'sp_a3_junkyard.wav',
    'sp_a3_junkyard_offices.wav',
    'sp_a3_paint_fling.wav',
    'sp_a3_paint_fling_funnel.wav',
    'sp_a3_transition.wav',
    'sp_a3_transition_funnel.wav',
    'sp_a4_destroyed.wav',
    'sp_a4_destroyed_funnel.wav',
    'sp_a4_factory.wav',
    'sp_a4_factory_radio.wav',
    'sp_a4_overgrown.wav',
    'sp_a4_overgrown_funnel.wav',
    'sp_a4_tb_over_goo.wav',
    'sp_a4_tb_over_goo_funnel.wav',
    'sp_a4_two_of_a_kind.wav',
    'sp_a4_two_of_a_kind_funnel.wav',
    'sp_a5_finale01_01.wav',
    'sp_a5_finale01_02.wav',
    'sp_a5_finale01_03.wav',
    'sp_a5_finale01_funnel.wav',
    'sp_a5_finale02_aegis_revealed.wav',
    'sp_a5_finale02_lastserver.wav',
    'sp_a5_finale02_room01.wav',
    'sp_a5_finale02_room02.wav',
    'sp_a5_finale02_room02_serious.wav',
    'sp_a5_finale02_stage_00.wav',
    'sp_a5_finale02_stage_01.wav',
    'sp_a5_finale02_stage_02.wav',
    'sp_a5_finale02_stage_end.wav',
    # Not used...
    # 'sp_a1_garden_jukebox01.wav',
    # 'sp_a1_jazz.wav',
    # 'sp_a1_jazz_enterstation.wav',
    # 'sp_a1_jazz_tramride.wav',
    # 'still_alive_gutair_cover.wav',
    # 'want_you_gone_guitar_cover.wav',
]


def scan_music_locs(packset: PackagesSet, games: Iterable[Game]) -> None:
    """Try and determine the location of Aperture Tag and PS:Mel.

    If successful we can export the music to games.
    """
    steamapp_locs = {
        os.path.normpath(game.abs_path('../'))
        for game in games
    }

    for loc in steamapp_locs:
        tag_loc = os.path.join(loc, MUSIC_TAG_DIR)
        mel_loc = os.path.join(loc, MUSIC_MEL_DIR)
        if os.path.exists(tag_loc) and packset.tag_music_fsys is None:
            packset.tag_music_fsys = RawFileSystem(tag_loc, constrain_path=False)
            LOGGER.info('Ap-Tag dir: {}', tag_loc)

        if os.path.exists(mel_loc) and packset.mel_music_fsys is None:
            packset.mel_music_fsys = VPKFileSystem(mel_loc)
            LOGGER.info('PS-Mel dir: {}', mel_loc)

        if packset.tag_music_fsys is not None and packset.mel_music_fsys is not None:
            # Found both, no need to search more.
            break


def make_tag_coop_inst(filename: str) -> VMF:
    """Make the coop version of the tag instances.

    This needs to be shrunk, so all the logic entities are not spread
    out so much (coop tubes are small).

    This way we avoid distributing the logic.
    """
    with open(filename, 'ascii') as f:
        kv = Keyvalues.parse(f)
    vmf = VMF.parse(kv)
    del kv
    ent_count = len(vmf.entities)

    def logic_pos() -> Iterator[Vec]:
        """Put the entities in a nice circle..."""
        while True:
            ang: float
            for ang in range(ent_count):
                ang *= 360 / ent_count
                yield Vec(16 * math.sin(ang), 16 * math.cos(ang), 32)
    pos = logic_pos()
    # Move all entities that don't care about position to the base of the player
    for ent in vmf.entities:
        if ent['classname'] == 'info_coop_spawn':
            # Remove the original spawn point from the instance.
            # That way it can overlay over other dropper instances.
            ent.remove()
        elif ent['classname'] in ('info_target', 'info_paint_sprayer'):
            pass
        else:
            ent['origin'] = next(pos)

            # These originally use the coop spawn point, but this doesn't
            # always work. Switch to the name of the player, which is much
            # more reliable.
            if ent['classname'] == 'logic_measure_movement':
                ent['measuretarget'] = '!player_blue'

    # Add in a trigger to start the gel gun, and reset the activated
    # gel whenever the player spawns.
    trig_brush = vmf.make_prism(
        Vec(-32, -32, 0),
        Vec(32, 32, 16),
        mat='tools/toolstrigger',
    ).solid
    start_trig = vmf.create_ent(
        classname='trigger_playerteam',
        target_team=3,  # ATLAS
        spawnflags=1,  # Clients only
        origin='0 0 8',
    )
    start_trig.solids = [trig_brush]
    start_trig.add_out(
        # This uses the !activator as the target player, so it must be fired via trigger.
        Output('OnStartTouchBluePlayer', '@gel_ui', 'Activate', delay=0, only_once=True),
        # Reset the gun to fire nothing.
        Output('OnStartTouchBluePlayer', '@blueisenabled', 'SetValue', 0, delay=0.1),
        Output('OnStartTouchBluePlayer', '@orangeisenabled', 'SetValue', 0, delay=0.1),
    )
    return vmf


@STEPS.add_step(prereq=[], results=[])
async def step_add_tag_coop_inst(exp: ExportData) -> None:
    """Generate and export the coop version of the gel gun instance."""
    if exp.game.steamID == utils.STEAM_IDS['APERTURE TAG']:
        src_fname = exp.game.abs_path('sdk_content/maps/instances/alatag/lp_paintgun_instance_coop.vmf')
        vmf = await trio.to_thread.run_sync(make_tag_coop_inst, src_fname)

        dest_fname = trio.Path(exp.game.abs_path('sdk_content/maps/instances/bee2/tag_coop_gun.vmf'))
        await dest_fname.parent.mkdir(parents=True, exist_ok=True)
        await dest_fname.write_text(await trio.to_thread.run_sync(vmf.export))


@STEPS.add_step(prereq=[], results=[StepResource.RES_SPECIAL])
async def step_copy_mod_music(exp: ExportData) -> None:
    """Copy music files from Tag and PS:Mel."""

    tag_dest = trio.Path(exp.game.abs_path('bee2/sound/music/'))
    # Mel's music has similar names to P2's, so put it in a subdir to avoid confusion.
    mel_dest = trio.Path(exp.game.abs_path('bee2/sound/music/mel/'))

    # Ensure the folders exist, so we can copy there.
    await mel_dest.mkdir(parents=True, exist_ok=True)

    fsys_tag = exp.packset.tag_music_fsys
    fsys_mel = exp.packset.mel_music_fsys

    copied_files: set[Path] = set()

    async def copy_music(dest_fname: trio.Path, file: File) -> None:
        """Copy a single music track.

        We know that it's very unlikely Tag or Mel's going to update the music files.
        So we can check to see if they already exist, and if so skip copying - that'll
        speed up any exports after the first. We'll still go through the list though,
        just in case one was deleted.
        """
        name = trio.Path(file.path).name
        dest = dest_fname / name
        copied_files.add(Path(dest))
        if not await dest.exists():
            with file.open_bin() as f:
                await dest.write_bytes(await trio.to_thread.run_sync(f.read))
        await STAGE_MUSIC.step(name)

    async with trio.open_nursery() as nursery:
        # Obviously Tag has its music already, skip copying to itself.
        count = 0
        if fsys_tag is not None and exp.game.steamID != utils.STEAM_IDS['APERTURE TAG']:
            for file in fsys_tag.walk_folder():
                nursery.start_soon(copy_music, tag_dest, file)
                count += 1

        if fsys_mel is not None:
            for filename in MEL_MUSIC_NAMES:
                nursery.start_soon(copy_music, mel_dest, fsys_mel['sound/music/' + filename])
                count += 1

        await STAGE_MUSIC.set_length(count)

    exp.resources |= copied_files
