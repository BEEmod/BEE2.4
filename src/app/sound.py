"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If pyglet fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
from __future__ import annotations
from collections.abc import Callable
import functools
import os
import shutil

from srctools.filesys import FileSystemChain, RawFileSystem
import srctools.logger
import trio
import trio_util

from ui_tk import TK_ROOT
from config.gen_opts import GenOptions
import config
import utils


__all__ = ['SamplePlayer', 'block_fx', 'fx', 'fx_blockable', 'pyglet_version']
LOGGER = srctools.logger.get_logger(__name__)
SAMPLE_WRITE_PATH = utils.conf_location('music_sample/music')
# Nursery to hold sound-related tasks. We can cancel this to shut down sound logic.
_nursery: trio.Nursery | None = None
# Keeps track of whether sounds are currently playing, so we know whether to tick or not.
# Use a set to ensure double-calling doesn't break anything.
_playing_count = trio_util.AsyncValue(0)
_playing: set[object] = set()

SOUNDS: dict[str, str] = {
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
# Gradually load sounds in the background.
_todo = list(SOUNDS)
is_positive: Callable[[int], bool] = (0).__lt__
is_zero: Callable[[int], bool] = (0).__eq__


def add_playing(snd_marker: object) -> None:
    """Mark a sound as playing. The marker can be anything hashable."""
    _playing.add(snd_marker)
    _playing_count.value = len(_playing)


def remove_playing(snd_marker: object) -> None:
    """Mark a sound as not playing. The marker can be anything hashable."""
    _playing.discard(snd_marker)
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

    async def load(self, name: str) -> Source | None:
        """Load and do nothing."""
        return None

    async def fx_blockable(self, sound: str) -> None:
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

    async def fx(self, sound: str) -> None:
        """Play a sound effect, sleeping for the duration."""
        await trio.lowlevel.checkpoint()


class PygletSound(NullSound):
    """Sound implementation using Pyglet."""
    def __init__(self) -> None:
        super().__init__()
        self.sources: dict[str, Source] = {}

    async def load(self, name: str) -> Source | None:
        """Load the given UI sound into a source."""
        global sounds
        fname = SOUNDS[name]
        path = str(utils.install_path(f'sounds/{fname}.ogg'))
        LOGGER.info('Loading sound "{}" -> {}', name, path)
        try:
            src: pyglet.media.Source = await trio.to_thread.run_sync(functools.partial(
                decoder.decode,
                file=None,
                filename=path,
                streaming=False,
            ))
        except Exception:
            LOGGER.exception("Couldn't load sound {}:", name)
            LOGGER.info('UI sounds disabled.')
            sounds = NullSound()
            if _nursery is not None:
                _nursery.cancel_scope.cancel()
            return None
        else:
            self.sources[name] = src
            return src

    async def fx(self, sound: str) -> None:
        """Play a sound effect, sleeping for the duration."""
        global sounds
        if play_fx():
            try:
                snd = self.sources[sound]
            except KeyError:
                # We were called before the BG thread loaded em, load it now.
                LOGGER.warning('Sound "{}" couldn\'t be loaded in time!', sound)
                snd = await self.load(sound)
            marker = object()
            try:
                add_playing(marker)
                try:
                    if snd is not None:
                        snd.play()
                except Exception:
                    LOGGER.exception("Couldn't play sound {}:", sound)
                    LOGGER.info('UI sounds disabled.')
                    if _nursery is not None:
                        _nursery.cancel_scope.cancel()
                    sounds = NullSound()
                    await trio.sleep(0.1)
                duration: float | None = snd.duration
                if duration is not None:
                    await trio.sleep(duration)
                else:
                    LOGGER.warning('No duration: {}', sound)
                    await trio.sleep(0.75)  # Should be long enough.
            finally:
                remove_playing(marker)
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
            async with trio_util.move_on_when(wait_for_quiet):
                while True:
                    try:
                        tick(True)  # True = don't sleep().
                    except Exception:
                        LOGGER.exception('Pyglet tick failed:')
                        _nursery.cancel_scope.cancel()
                        break
                    await trio.sleep(0.1)


async def _load_bg(sound: str) -> None:
    """Load the FX sounds gradually in the background."""
    try:
        await sounds.load(sound)
    except Exception:
        LOGGER.exception('Failed to load sound:')
        if _nursery is not None:
            _nursery.cancel_scope.cancel()


def fx(name: str) -> None:
    """Play a sound effect stored in the sounds{} dict."""
    if _nursery is not None and not _nursery.cancel_scope.cancel_called:
        _nursery.start_soon(sounds.fx, name)


def fx_blockable(sound: str) -> None:
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
    import pyglet.media

    decoder = FFmpegDecoder()
    sounds = PygletSound()
except Exception:
    LOGGER.exception('Pyglet not importable:')
    pyglet_version = '(Not installed)'
    sounds = NullSound()


def clean_sample_folder() -> None:
    """Delete files used by the sample player."""
    for file in SAMPLE_WRITE_PATH.parent.iterdir():
        LOGGER.info('Cleaning up "{}"...', file)
        try:
            file.unlink()
        except (PermissionError, FileNotFoundError):
            pass


# TODO: Switch this to a constantly-playing task, eliminate TK_ROOT usage.
class SamplePlayer:
    """Handles playing a single audio file, and allows toggling it on/off."""
    def __init__(self, system: FileSystemChain) -> None:
        """Initialise the sample-playing manager."""
        self.player: pyglet.media.Player | None = None
        self.after: str | None = None
        self.cur_file: str | None = None
        self.system: FileSystemChain = system
        self.is_playing = trio_util.AsyncBool()

    def play_sample(self, _: object = None) -> None:
        """Play a sample of music.

        If music is being played it will be stopped instead.
        """
        if self.cur_file is None:
            return

        if self.player is not None:
            self.stop()
            return

        try:
            file = self.system[self.cur_file]
        except (KeyError, FileNotFoundError):
            self.is_playing.value = False
            remove_playing(self)
            LOGGER.error('Sound sample not found: "{}"', self.cur_file)
            return  # Abort if music isn't found..

        child_sys = self.system.get_system(file)
        # Special case raw filesystems - Pyglet is more efficient
        # if it can just open the file itself.
        if isinstance(child_sys, RawFileSystem):
            load_path = os.path.join(child_sys.path, file.path)
            LOGGER.debug('Loading music directly from {!r}', load_path)
        else:
            # In a filesystem, we need to extract it.
            # SAMPLE_WRITE_PATH + the appropriate extension.
            sample_fname = SAMPLE_WRITE_PATH.with_suffix(os.path.splitext(self.cur_file)[1])
            with file.open_bin() as fsrc, sample_fname.open('wb') as fdest:
                shutil.copyfileobj(fsrc, fdest)
            LOGGER.debug('Loading music {} as {}', self.cur_file, sample_fname)
            load_path = str(sample_fname)
        try:
            sound = decoder.decode(filename=load_path, file=None)
        except Exception:
            self.is_playing.value = False
            remove_playing(self)
            LOGGER.exception('Sound sample not valid: "{}"', self.cur_file)
            return  # Abort if music isn't found or can't be loaded.

        self.player = sound.play()
        self.after = TK_ROOT.after(
            int(sound.duration * 1000),
            self._finished,
        )
        self.is_playing.value = True
        add_playing(self)

    def stop(self) -> None:
        """Cancel the music, if it's playing."""
        if self.player is not None:
            self.player.pause()
            self.player = None
            self.is_playing.value = False
            remove_playing(self)

        if self.after is not None:
            TK_ROOT.after_cancel(self.after)
            self.after = None

    def _finished(self) -> None:
        """Reset values after the sound has finished."""
        self.player = None
        self.after = None
        self.is_playing.value = False
        remove_playing(self)
