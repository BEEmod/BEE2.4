"""Allows searching and selecting various resources."""
from typing import Final, Literal, assert_never

from collections.abc import Mapping, Sequence
import abc
import enum

from srctools import FileSystemChain, KeyValError, Keyvalues, choreo
from srctools.filesys import File, FileSystem
from srctools.sndscript import Sound
from srctools.tokenizer import Tokenizer, TokenSyntaxError

from trio_util import AsyncBool, AsyncValue
import srctools.logger
import trio
import trio_util

from app.gameMan import Game, is_valid_game, selected_game
from async_util import EdgeTrigger
from packages import LOADED, PackagesSet
from transtoken import TransToken
import async_util


LOGGER = srctools.logger.get_logger(__name__)

# If only choreo, be more specific.
TRANS_SND_TITLE = TransToken.ui("Sounds Browser")
TRANS_SND_TITLE_CHOREO = TransToken.ui("Choreographed Scene Browser")
TRANS_SND_HEADING = TransToken.ui("Sounds:")
TRANS_SND_NAME = TransToken.ui("Sound Name:")
TRANS_SND_FIlE = TransToken.ui("Sound File:")
TRANS_SND_TYPE = TransToken.ui("Sound Type:")
TRANS_SND_FILTER = TransToken.ui("Filter:")
TRANS_SND_AUTOPLAY = TransToken.ui("Autoplay Sounds")
TRANS_SND_PREVIEW = TransToken.ui("Preview")


class Browser(abc.ABC):
    """Base functionality - reload if game changes, only allow opening once."""
    def __init__(self) -> None:
        self._ready = AsyncBool(False)
        self._wants_open = AsyncBool(False)
        self.result: EdgeTrigger[str | None] = EdgeTrigger()
        self.initial: str | None = None
        # If non-none, a user is trying to browse.
        self._close_event: trio.Event | None = None
        # Should be set when something exposes a browse button to the user,
        # so it can begin loading.
        self.init_event = trio.Event()

    def start_loading(self) -> None:
        """Begin loading data in the background."""
        self.init_event.set()

    async def task(self) -> None:
        """Handles main flow."""
        await self.init_event.wait()
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
        if not self.init_event.is_set():
            raise ValueError("Browser must start loading before we can browse!")
        await self._ready.wait_value(True)
        while self.result.ready.value:
            self.result.trigger(None)
            self._ui_hide_window()
            await trio.sleep(0.25)
        return await self.result.wait()

    def _evt_cancel(self, _: object = None) -> None:
        """Close the browser, cancelling."""
        self.result.trigger(None)

    @abc.abstractmethod
    async def _reload(self, packset: PackagesSet, game: Game) -> None:
        """Reload data for a new game or packages."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_show_window(self) -> None:
        """Show the window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_hide_window(self) -> None:
        """Hide the window."""
        raise NotImplementedError


class AllowedSounds(enum.Flag):
    """Types of sounds allowed. The order is what we'd prefer to select."""
    CHOREO = enum.auto()
    SOUNDSCRIPT = enum.auto()
    RAW_SOUND = enum.auto()

    # Not necessary, but makes sure type checkers know there's other members possible.
    ALL = SOUNDSCRIPT | RAW_SOUND | CHOREO


# A single sound.
type SoundMode = Literal[AllowedSounds.SOUNDSCRIPT, AllowedSounds.RAW_SOUND, AllowedSounds.CHOREO]
SND_PREFERENCE: list[SoundMode] = [
    AllowedSounds.CHOREO, AllowedSounds.SOUNDSCRIPT, AllowedSounds.RAW_SOUND
]
SOUND_TYPES: list[tuple[SoundMode, TransToken]] = [
    (AllowedSounds.SOUNDSCRIPT, TransToken.ui("Soundscript")),
    (AllowedSounds.RAW_SOUND, TransToken.ui("Raw Sounds")),
    (AllowedSounds.CHOREO, TransToken.ui("Choreo Scenes")),
]


def parse_soundscript(file: File) -> dict[str, Sound]:
    """Parse a soundscript file."""
    with file.open_str(encoding='cp1252') as f:
        kv = Keyvalues.parse(
            f, file.path,
            allow_escapes=False,
            periodic_callback=trio.from_thread.check_cancelled,
        )
    return Sound.parse(kv)


type AnySound = Sound | str | choreo.Entry
type SoundSeq = Sequence[AnySound]


class SoundBrowserBase(Browser, abc.ABC):
    """Browses for soundscripts, raw sounds or choreo scenes, like Hammer's."""
    def __init__(self) -> None:
        super().__init__()
        self.mode: AsyncValue[SoundMode] = AsyncValue(AllowedSounds.SOUNDSCRIPT)
        self.filter = AsyncValue('')
        self.allowed: AllowedSounds = AllowedSounds.ALL

        self._fsys = FileSystemChain()
        # Make these final so references can be passed out.
        self._soundscripts: Final[list[Sound]] = []
        self._scenes: Final[list[choreo.Entry]] = []
        self._raw: Final[list[str]] = []

    @staticmethod
    def path_for(value: AnySound) -> str:
        """Get the filename/path for this sound."""
        match value:
            case Sound() as sndscript:
                return sndscript.name
            case choreo.Entry() as scene:
                return scene.filename
            case str() as raw:
                return raw
            case err:
                assert_never(err)

    async def filter_task(self) -> None:
        """When the filter changes, find the items, filter and display."""
        while True:
            async with trio_util.move_on_when(
                trio_util.wait_any,
                self.mode.wait_transition,
                self.filter.wait_transition,
            ):
                await trio.sleep(0.1)
                filter_text = self.filter.value.casefold()
                result: SoundSeq
                match self.mode.value:
                    case AllowedSounds.SOUNDSCRIPT:
                        result = [
                            sound for sound in self._soundscripts
                            if filter_text in sound.name.casefold()
                        ] if filter_text else self._soundscripts
                    case AllowedSounds.RAW_SOUND:
                        result = [
                            raw for raw in self._raw
                            if filter_text in raw.casefold()
                        ] if filter_text else self._raw
                    case AllowedSounds.CHOREO:
                        result = [
                            scene for scene in self._scenes
                            if filter_text in scene.filename.casefold()
                        ] if filter_text else self._scenes
                    case err:
                        assert_never(err)
                await self._ui_set_items(result)
                await trio.sleep_forever()

    async def task(self) -> None:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(super().task)
            nursery.start_soon(self.filter_task)

    async def browse(
        self,
        initial: str,
        allowed: AllowedSounds = AllowedSounds.ALL,
    ) -> str | None:
        for snd_type in SND_PREFERENCE:
            if snd_type in allowed:
                self.mode.value = snd_type
                break
        else:
            raise ValueError('No sound types provided!')
        self.allowed = allowed
        self._ui_set_allowed(
            allowed,
            TRANS_SND_TITLE_CHOREO if allowed is AllowedSounds.CHOREO else TRANS_SND_TITLE,
        )
        return await super().browse(initial)

    async def _reload(self, packset: PackagesSet, game: Game) -> None:
        self._fsys = await trio.to_thread.run_sync(game.get_filesystem)
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._load_soundscripts, self._fsys, packset)
            nursery.start_soon(self._load_choreo, self._fsys)
            nursery.start_soon(self._load_raw, self._fsys, packset)

    async def _load_soundscripts(self, fsys: FileSystemChain, packset: PackagesSet) -> None:
        LOGGER.info('Reloading soundscripts for browser...')
        self._soundscripts.clear()
        try:
            sounds_manifest = await async_util.parse_kv1_fsys(
                fsys, 'scripts/game_sounds_manifest.txt',
                encoding='cp1252',
            )
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
        soundscripts: dict[str, Sound] = {}
        for sounds in parsed:
            soundscripts.update(sounds)
        self._soundscripts.extend(soundscripts.values())
        self._soundscripts.sort(key=lambda snd: snd.name)
        LOGGER.info('{} soundscripts loaded.', len(self._soundscripts))

    async def _load_raw(self, fsys: FileSystemChain, packset: PackagesSet) -> None:
        """Locate all raw sound files."""
        self._raw.clear()

        def check_fsys(fs: FileSystem, path: str) -> None:
            """Crawl the sounds in this filesystem."""
            for file in fs.walk_folder(path):
                if file.path.endswith(('.mp3', '.wav')):
                    self._raw.append(file.path.replace('\\', '/').removeprefix('resources/'))

        async with trio.open_nursery() as nursery:
            nursery.start_soon(trio.to_thread.run_sync, check_fsys, fsys, 'sound')
            for pack in packset.packages.values():
                nursery.start_soon(trio.to_thread.run_sync, check_fsys, pack.fsys, 'resources/sound')

        self._raw.sort()
        LOGGER.info('{} raw sounds loaded.', len(self._raw))

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
                image = await trio.to_thread.run_sync(
                    choreo.parse_scenes_image,
                    f, abandon_on_cancel=True,
                )

        scenes = {}

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
                        scenes[file.path] = entry
                        entry.filename = file.path
                        continue
                    # Not here, need to parse.
                    LOGGER.debug('Scene "{}" is not in scenes.image, parsing', file.path)
                    try:
                        with file.open_str() as f:
                            scene = await trio.to_thread.run_sync(
                                choreo.Scene.parse_text,
                                Tokenizer(f, periodic_callback=trio.from_thread.check_cancelled),
                            )
                    except TokenSyntaxError as exc:
                        LOGGER.warning('Could not parse choreo scene "{}"!', file.path, exc_info=exc)
                    else:
                        scenes[file.path] = choreo.Entry.from_scene(file.path, scene)

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
        self._scenes.extend(scenes.values())
        self._scenes.sort(key=lambda entry: entry.filename)
        LOGGER.info('Loaded {} choreo scenes', len(self._scenes))

    def _evt_ok(self, _: object = None) -> None:
        """Successfully select a value."""
        self.result.trigger(self._ui_get_name())

    def _evt_preview(self, _: object = None) -> None:
        """Preview the selected value."""
        raise NotImplementedError # TODO

    def _evt_select(self, _: object = None) -> None:
        """Item was selected in the listbox, update the display."""
        match self._ui_get_selected():
            # TODO: Determine original filenames.
            case Sound() as sndscript:
                self._ui_set_props(sndscript.name, '???')
            case choreo.Entry() as scene:
                self._ui_set_props(scene.filename, '???')
            case str() as raw:
                return self._ui_set_props(raw, raw)
            case None:
                self._ui_set_props('', '')
            case err:
                assert_never(err)

    @abc.abstractmethod
    def _ui_get_selected(self) -> AnySound | None:
        """Get the currently selected sound, or None if none selected."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_get_name(self) -> str:
        """Get the sound name that was set"""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_set_allowed(self, allowed: AllowedSounds, title: TransToken) -> None:
        """Set the allowed sound modes, and window title."""
        raise NotImplementedError

    @abc.abstractmethod
    async def _ui_set_items(self, items: SoundSeq) -> None:
        """Update the items displayed."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_set_props(self, name: str, file: str) -> None:
        """Update the displayed values."""
        raise NotImplementedError
