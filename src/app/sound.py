"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If pyglet fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
from collections import deque
from pathlib import Path, PurePath
from typing import Literal, override

from collections.abc import Callable, Generator
import contextlib
import functools
import os
import shutil

from srctools.filesys import FileSystemChain, RawFileSystem
import srctools.logger
import trio
import trio_util

from config.gen_opts import GenOptions
import config
import utils


__all__ = ['SamplePlayer', 'block_fx', 'fx', 'fx_blockable', 'pyglet_version']
LOGGER = srctools.logger.get_logger(__name__)
MUSIC_WRITE_PATH = utils.conf_location('music_sample/music')
# Other locations to clean up.
_sample_paths: set[Path] = {MUSIC_WRITE_PATH}
# Nursery to hold sound-related tasks. We can cancel this to shut down sound logic.
_nursery: trio.Nursery | None = None
# Keeps track of whether sounds are currently playing, so we know whether to tick or not.
# We're using a context manager so reference counting would be sufficient, but put marker objects
# in a set to be more robust.
_playing_count = trio_util.AsyncValue(0)
_playing: set[object] = set()
type PygletSource = Source  # Forward ref

type SoundName = Literal[
    'select', 'add', 'config', 'subtract', 'connect', 'disconnect', 'expand', 'delete',
    'error', 'contract', 'raise_1', 'raise_2', 'raise_3', 'lower_1', 'lower_2', 'lower_3',
    'move', 'swap',
]
SOUNDS: dict[SoundName, str] = {
    'select': 'rollover',
    'add': 'increment',
    'config': 'reconfig',
    'subtract': 'decrement',
    'connect': 'connection_made',
    'disconnect': 'connection_destroyed',
    'expand': 'extrude',
    'delete': 'collapse',
    'error': 'error',
    'contract': 'carve',
    'raise_1': 'panel_raise_01',
    'raise_2': 'panel_raise_02',
    'raise_3': 'panel_raise_03',
    'lower_1': 'panel_lower_01',
    'lower_2': 'panel_lower_02',
    'lower_3': 'panel_lower_03',
    'move': 'reconfig',
    'swap': 'extrude',
}
is_positive: Callable[[int], bool] = (0).__lt__
is_zero: Callable[[int], bool] = (0).__eq__


@contextlib.contextmanager
def mark_playing() -> Generator[None]:
    """Mark a sound as playing while active."""
    marker = object()
    try:
        _playing.add(marker)
        _playing_count.value = len(_playing)
        yield
    finally:
        _playing.discard(marker)
        _playing_count.value = len(_playing)


class NullSound:
    """Sound implementation which does nothing."""
    def __init__(self) -> None:
        self._block_count = 0

    def _unblock_fx(self) -> None:
        """Reset the ability to use fx_blockable()."""
        self._play_fx = True

    async def block_fx(self) -> None:
        """Block fx_blockable for a short time."""
        self._block_count += 1
        try:
            await trio.sleep(0.50)
        finally:
            self._block_count -= 1

    async def load(self, name: SoundName) -> PygletSource | None:
        """Load and do nothing."""
        return None

    async def fx_blockable(self, sound: SoundName) -> None:
        """Play a sound effect.

        This waits for a certain amount of time between retriggering sounds
        so that they don't overlap.
        """
        if play_fx() and self._block_count == 0:
            self._block_count += 1
            try:
                await self.fx(sound)
            finally:
                self._block_count -= 1

    async def fx(self, sound: SoundName) -> None:
        """Play a sound effect, sleeping for the duration."""
        await trio.lowlevel.checkpoint()


class PygletSound(NullSound):
    """Sound implementation using Pyglet."""
    def __init__(self) -> None:
        super().__init__()
        self.sources: dict[str, PygletSource] = {}

    @override
    async def load(self, name: SoundName) -> PygletSource | None:
        """Load the given UI sound into a source."""
        global sounds
        fname = SOUNDS[name]
        path = str(utils.install_path(f'sounds/{fname}.ogg'))
        try:
            src: PygletSource = await trio.to_thread.run_sync(functools.partial(
                decoder.decode,
                file=None,
                filename=path,
                streaming=False,
            ))
        except Exception:
            LOGGER.exception('Couldn\'t load sound "{}" -> {}', name, path)
            LOGGER.info('UI sounds disabled.')
            sounds = NullSound()
            if _nursery is not None:
                _nursery.cancel_scope.cancel()
            return None
        else:
            LOGGER.info('Loaded sound "{}" -> {}', name, path)
            self.sources[name] = src
            return src

    @override
    async def fx(self, sound: SoundName) -> None:
        """Play a sound effect, sleeping for the duration."""
        global sounds
        if play_fx():
            try:
                snd = self.sources[sound]
            except KeyError:
                # We were called before the BG thread loaded em, load it now.
                LOGGER.warning('Sound "{}" couldn\'t be loaded in time!', sound)
                snd = await self.load(sound)
            if snd is None:
                await trio.lowlevel.checkpoint()
                return
            with mark_playing():
                try:
                    snd.play()
                except Exception:
                    LOGGER.exception("Couldn't play sound {}:", sound)
                    LOGGER.info('UI sounds disabled.')
                    if _nursery is not None:
                        _nursery.cancel_scope.cancel()
                    sounds = NullSound()
                    await trio.sleep(0.1)
                if (duration := snd.duration) is not None:
                    await trio.sleep(duration)
                else:
                    LOGGER.warning('No duration: {}', sound)
                    await trio.sleep(0.75)  # Should be long enough.
        await trio.lowlevel.checkpoint()


async def sound_task() -> None:
    """Task run to manage the sound system.

    We need to constantly trigger pyglet.clock.tick(). This also provides a nursery for
    triggering sound tasks, and gradually loads background sounds.
    """
    async def wait_for_quiet() -> None:
        """Wait until all sounds are stopped and remain stopped."""
        await _playing_count.wait_value(is_zero, held_for=0.75)

    global _nursery
    async with trio.open_nursery() as _nursery:
        # Send off sound tasks.
        for sound in SOUNDS:
            _nursery.start_soon(_load_bg, sound)
        # Only tick if we actually have sounds playing.
        while True:
            await _playing_count.wait_value(is_positive)
            async with trio_util.move_on_when(wait_for_quiet) as scope:
                while not scope.cancel_called:
                    try:
                        tick(True)  # True = don't sleep().
                    except Exception:
                        LOGGER.exception('Pyglet tick failed:')
                        _nursery.cancel_scope.cancel()
                        break
                    await trio.sleep(0.1)


async def _load_bg(sound: SoundName) -> None:
    """Load the FX sounds gradually in the background."""
    try:
        await sounds.load(sound)
    except Exception:
        LOGGER.exception('Failed to load sound:')
        if _nursery is not None:
            _nursery.cancel_scope.cancel()


def fx(name: SoundName) -> None:
    """Play a sound effect stored in the sounds{} dict."""
    if _nursery is not None and not _nursery.cancel_scope.cancel_called:
        _nursery.start_soon(sounds.fx, name)


def fx_blockable(sound: SoundName) -> None:
    """Play a sound effect.

    This waits for a certain amount of time between retriggering sounds,
    so that they don't overlap.
    """
    if _nursery is not None and not _nursery.cancel_scope.cancel_called:
        _nursery.start_soon(sounds.fx_blockable, sound)


def block_fx() -> None:
    """Block fx_blockable() for a short time."""
    if _nursery is not None and not _nursery.cancel_scope.cancel_called:
        _nursery.start_soon(sounds.block_fx)


def has_sound() -> bool:
    """Return if the sound system is functional."""
    return isinstance(sounds, PygletSound)


def play_fx() -> bool:
    """Return if sounds should play."""
    return config.APP.get_cur_conf(GenOptions).play_sounds


if utils.WIN:
    if utils.FROZEN:
        _libs_folder = utils.bins_path(".")
    else:
        _libs_folder = utils.bins_path("lib-" + utils.BITNESS)
    # Add a libs folder for FFmpeg dlls.
    os.environ['PATH'] = f'{_libs_folder.absolute()};{os.environ["PATH"]}'
    LOGGER.debug('Appending "{}" to $PATH.', _libs_folder)

sounds: NullSound
try:
    from pyglet import version as pyglet_version
    from pyglet.clock import tick
    from pyglet.media.codecs import Source
    from pyglet.media.codecs.ffmpeg import FFmpegDecoder

    decoder = FFmpegDecoder()
    sounds = PygletSound()
except Exception:
    LOGGER.exception('Pyglet not importable:')
    pyglet_version = '(Not installed)'
    sounds = NullSound()


def clean_sample_folder() -> None:
    """Delete files used by the sample player."""
    for base_fname in _sample_paths:
        for file in base_fname.parent.iterdir():
            LOGGER.info('Cleaning up "{}"...', file)
            try:
                file.unlink()
            except (PermissionError, FileNotFoundError):
                pass


class SamplePlayer:
    """Handles playing one or more audio files, and allows toggling it on/off."""
    # The current queue of sounds to play.
    _queue: deque[str]
    # Filesystem to load sounds from. Can be changed by callers.
    system: FileSystemChain
    # True if we are playing sounds or want to play them. Queue must be non-empty if so.
    is_playing: trio_util.AsyncBool
    # Used to cancel current playback.
    _play_scope: trio.CancelScope

    extract_path: Path  # Location to extract files to.

    def __init__(self, system: FileSystemChain, extract_path: Path) -> None:
        """Initialise the sample-playing manager."""
        self._queue = deque()
        self.system = system
        self.is_playing = trio_util.AsyncBool()
        self._play_scope = trio.CancelScope()
        self.extract_path = extract_path
        _sample_paths.add(extract_path)

    def play(self, *filenames: str) -> None:
        """Play sounds, clearing existing sounds."""
        self._play_scope.cancel()
        self._queue.clear()
        self._queue.extend(filenames)
        self.is_playing.value = True

    def queue(self, filename: str) -> None:
        """Queue a new sound."""
        self._queue.append(filename)
        self.is_playing.value = True

    def stop(self) -> None:
        """Cancel playback, if it's playing."""
        self._play_scope.cancel()
        self._queue.clear()
        self.is_playing.value = False

    async def task(self) -> None:
        """Plays audio samples."""
        # We wait for playing to be set, then start iterating the queue.
        # If the scope is cancelled, we abort, leaving is-playing untouched. If it is set we
        # immediately resume. If we finish we set it false and leave it there.
        while True:
            await self.is_playing.wait_value(True)
            with trio.CancelScope() as self._play_scope, mark_playing():
                LOGGER.debug('Playing queue with {} items', len(self._queue))
                while self._queue:
                    LOGGER.debug('Playback queue: {}', self._queue)
                    filename = self._queue.popleft()
                    await trio.lowlevel.checkpoint()

                    snd_path = self._get_path(filename)
                    if snd_path is None:
                        continue  # Not valid, skip.
                    try:
                        sound = await trio.to_thread.run_sync(
                            decoder.decode,
                            str(snd_path), None, True,
                        )
                    except Exception:
                        LOGGER.exception('Sound sample not valid: "{}"', filename)
                        return
                    player = sound.play()
                    LOGGER.debug('Sound duration: {}={}', snd_path, sound.duration)
                    try:
                        await trio.sleep(sound.duration + 0.1)
                    finally:
                        player.delete()
                LOGGER.debug('Queue completed successfully.')
                # Definitely finished, reset.
                self.is_playing.value = False

    def _get_path(self, filename: str) -> Path | None:
        """Get the real path for this fsys file.

        If raw, give that path, otherwise extract.
        """
        # TODO: Make a context manager, delete sample when finished.
        try:
            file = self.system[filename]
        except (KeyError, FileNotFoundError):
            LOGGER.error('Sound file not found: "{}"', filename)
            return None  # Abort if file isn't found..

        child_sys = self.system.get_system(file)
        # Special case raw filesystems - Pyglet is more efficient
        # if it can just open the file itself.
        if isinstance(child_sys, RawFileSystem) and False:
            load_path = Path(child_sys.path, file.path)
            LOGGER.debug('Loading sound directly from {!r}', load_path)
            return load_path
        else:
            # In a filesystem, we need to extract it.
            # Inherit the original extension.
            extract_to = self.extract_path.with_suffix(PurePath(filename).suffix)
            with file.open_bin() as fsrc, extract_to.open('wb') as fdest:
                shutil.copyfileobj(fsrc, fdest)
            LOGGER.debug('Loading sound {} as {}', filename, extract_to)
            return Path(extract_to)
