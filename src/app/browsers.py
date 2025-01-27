"""Allows searching and selecting various resources."""
from typing import Literal

from abc import ABC
from collections.abc import Mapping
import abc
import enum

from srctools import FileSystemChain, KeyValError, Keyvalues, choreo
from srctools.filesys import File
from srctools.sndscript import Sound
from srctools.tokenizer import Tokenizer, TokenSyntaxError
from trio_util import AsyncBool
import srctools.logger
import trio
import trio_util

from app.gameMan import Game, is_valid_game, selected_game
from async_util import EdgeTrigger
from packages import LOADED, PackagesSet


LOGGER = srctools.logger.get_logger(__name__)


class Browser(ABC):
    """Base functionality - reload if game changes, only allow opening once."""
    def __init__(self) -> None:
        self._ready = AsyncBool(False)
        self._wants_open = AsyncBool(False)
        self.result: EdgeTrigger[str | None] = EdgeTrigger()
        self.initial: str | None = None
        # If non-none, a user is trying to browse.
        self._close_event: trio.Event | None = None

    async def task(self) -> None:
        """Handles main flow."""
        while True:
            self._ready.value = False
            self._ui_hide_window()
            game = await selected_game.wait_value(is_valid_game)
            async with trio_util.move_on_when(
                trio_util.wait_any,
                selected_game.wait_transition,
                LOADED.wait_transition,
            ):
                await self._reload(LOADED.value, game)
                self._ready.value = True
                while True:
                    await self.result.ready.wait_value(True)
                    self._ui_show_window()
                    await self.result.ready.wait_value(False)
                    self._ui_hide_window()

    async def browse(self, initial: str) -> str | None:
        """Browse for a value."""
        await self._ready.wait_value(True)
        while self.result.ready.value:
            self.result.trigger(None)
            self._ui_hide_window()
            await trio.sleep(0.25)
        return await self.result.wait()

    def _evt_cancel(self, _: object = None) -> None:
        """Close the browser, cancelling."""
        self.result.trigger(None)

    def _evt_ok(self, value: str) -> None:
        """Successfully select a value."""
        self.result.trigger(value)

    async def _reload(self, packset: PackagesSet, game: Game) -> None:
        """Reload data for a new game or packages."""

    @abc.abstractmethod
    def _ui_show_window(self) -> None:
        """Show the window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_hide_window(self) -> None:
        """Hide the window."""
        raise NotImplementedError


class AllowedSounds(enum.Flag):
    """Types of sounds allowed."""
    SOUNDSCRIPT = enum.auto()
    RAW_SOUND = enum.auto()
    CHOREO = enum.auto()

    # Not necessary, but makes sure type checkers know there's other members possible.
    ALL = SOUNDSCRIPT | RAW_SOUND | CHOREO

# A single sound.
type SoundMode = Literal[AllowedSounds.SOUNDSCRIPT, AllowedSounds.RAW_SOUND, AllowedSounds.CHOREO]


def parse_soundscript(file: File) -> dict[str, Sound]:
    """Parse a soundscript file."""
    with file.open_str(encoding='cp1252') as f:
        kv = Keyvalues.parse(f, file.path, allow_escapes=False)
    return Sound.parse(kv)


class SoundBrowser(Browser, ABC):
    """Browses for soundscripts, raw sounds or choreo scenes, like Hammer's."""
    def __init__(self) -> None:
        super().__init__()
        self.mode: SoundMode = AllowedSounds.SOUNDSCRIPT
        self.allowed: AllowedSounds = AllowedSounds.ALL

        self._fsys = FileSystemChain()
        self._soundscripts: dict[str, Sound] = {}
        self._scenes: dict[str, choreo.Entry] = {}

    async def browse(
        self,
        initial: str,
        allowed: AllowedSounds = AllowedSounds.ALL,
    ) -> str | None:
        self.allowed = allowed
        return await super().browse(initial)

    async def _reload(self, packset: PackagesSet, game: Game) -> None:
        self._fsys = await trio.to_thread.run_sync(game.get_filesystem)
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._load_soundscripts, self._fsys, packset)
            nursery.start_soon(self._load_choreo, self._fsys)

    async def _load_soundscripts(self, fsys: FileSystemChain, packset: PackagesSet) -> None:
        LOGGER.info('Reloading soundscripts for browser...')
        self._soundscripts.clear()
        try:
            sounds_manifest = await trio.to_thread.run_sync(fsys.read_kv1, 'scripts/game_sounds_manifest.txt', 'cp1252')
        except FileNotFoundError:
            LOGGER.warning('No soundscript manifest?')
            return

        # We need to preserve the order, in case any override each other.
        # So fill parsed with EmptyMapping of the same length, have each task
        # insert into the correct slot.
        script_files: list[File] = []
        parsed: list[Mapping[str, Sound]] = []
        file: File

        for prop in sounds_manifest.find_children('game_sounds_manifest'):
            if not prop.name.endswith('_file'):
                continue
            try:
                file = fsys[prop.value]
            except FileNotFoundError:
                LOGGER.warning('Soundscript "{}" does not exist!', prop.value)
            else:
                script_files.append(file)
                parsed.append(srctools.EmptyMapping)
        for pack in packset.packages.values():
            for folder in ['resources/scripts/bee2_snd/', 'resources/scripts/bee_snd/']:
                for file in pack.fsys.walk_folder(folder):
                    if file.path.endswith('.txt'):
                        script_files.append(file)
                        parsed.append(srctools.EmptyMapping)

        async def parse_script(file: File, i: int) -> None:
            """Parse a soundscript then add it to the list of scripts."""
            try:
                parsed[i] = await trio.to_thread.run_sync(parse_soundscript, file, abandon_on_cancel=True)
            except (KeyValError, ValueError) as exc:
                LOGGER.warning('Invalid soundscript: {}', file.path, exc_info=exc)

        LOGGER.info('{} soundscript files', len(script_files))
        assert len(script_files) == len(parsed)

        async with trio.open_nursery() as nursery:
            for pos, file in enumerate(script_files):
                LOGGER.debug('Parsing {}...', file.path)
                nursery.start_soon(parse_script, file, pos)
        # Merge everything together.
        for sounds in parsed:
            self._soundscripts.update(sounds)
        LOGGER.info('{} soundscripts loaded.', len(self._soundscripts))

    async def _load_choreo(self, fsys: FileSystemChain) -> None:
        """Parse all VCD files."""
        self._scenes.clear()
        LOGGER.info('Reloading choreo scenes...')
        # Load scenes.image, if it's there that lets us skip parsing the VCDs. But we need to
        # still look for those, since otherwise we don't have filenames.
        try:
            image_file = fsys['scenes/scenes.image']
        except FileNotFoundError:
            LOGGER.warning('No scenes.image file found.')
            image = {}
        else:
            with image_file.open_bin() as f:
                image = await trio.to_thread.run_sync(choreo.parse_scenes_image, f, abandon_on_cancel=True)

        async def choreo_worker(channel: trio.MemoryReceiveChannel[File]) -> None:
            """Parse each choreo scene. Ideally this is in the image."""
            file: File
            with channel:
                async for file in channel:
                    crc = choreo.checksum_filename(file.path)
                    try:
                        entry = image[crc]
                    except KeyError:
                        pass
                    else:
                        self._scenes[file.path] = entry
                        entry.filename = file.path
                        continue
                    # Not here, need to parse.
                    LOGGER.debug('Scene "{}" is not in scenes.image, parsing', file.path)
                    try:
                        with file.open_str() as f:
                            scene = await trio.to_thread.run_sync(
                                choreo.Scene.parse_text, Tokenizer(f),
                            )
                    except TokenSyntaxError as exc:
                        LOGGER.warning('Could not parse choreo scene "{}"!', file.path, exc_info=exc)
                    else:
                        self._scenes[file.path] = choreo.Entry.from_scene(file.path, scene)

        send_file: trio.MemorySendChannel[File]
        rec_file: trio.MemoryReceiveChannel[File]
        send_file, rec_file = trio.open_memory_channel(0)
        async with trio.open_nursery() as nursery, send_file:
            for _ in range(16):
                nursery.start_soon(choreo_worker, rec_file.clone())
            rec_file.close()
            for file in fsys.walk_folder('scenes'):
                if file.path.casefold().endswith('.vcd'):
                    await send_file.send(file)
        LOGGER.info('Loaded {} choreo scenes', len(self._scenes))
