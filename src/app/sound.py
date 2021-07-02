"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
from __future__ import annotations
from tkinter import Event
from typing import IO, Optional, Callable
import os
import threading

from app import TK_ROOT
from srctools.filesys import FileSystemChain, FileSystem, RawFileSystem
import srctools.logger
import utils

__all__ = [
    'SamplePlayer',

    'pyglet_version',
    'play_sound', 'fx',
    'fx_blockable', 'block_fx',
]

LOGGER = srctools.logger.get_logger(__name__)
play_sound = True

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


class NullSound:
    """Sound implementation which does nothing."""
    def __init__(self) -> None:
        self._play_fx = True

    def _unblock_fx(self) -> None:
        """Reset the ability to use fx_blockable()."""
        self._play_fx = True

    def block_fx(self) -> None:
        """Block fx_blockable for a short time."""
        self._play_fx = False
        TK_ROOT.after(50, self._unblock_fx)

    def fx_blockable(self, sound: str) -> None:
        """Play a sound effect.

        This waits for a certain amount of time between retriggering sounds
        so they don't overlap.
        """
        if play_sound and self._play_fx:
            self.fx(sound)
            self._play_fx = False
            TK_ROOT.after(75, self._unblock_fx)

    def fx(self, sound: str) -> None:
        """Play a sound effect."""


class PygletSound(NullSound):
    """Sound implementation using Pyglet."""
    def __init__(self) -> None:
        super().__init__()
        self.sources: dict[str, Source] = {}

    def load(self, name: str) -> Source:
        """Load the given UI sound into a source."""
        global sounds
        fname = SOUNDS[name]
        path = str(utils.install_path('sounds/{}.ogg'.format(fname)))
        LOGGER.info('Loading sound "{}" -> {}', name, path)
        try:
            src = pyglet.media.load(path, streaming=False)
        except Exception:
            LOGGER.exception("Couldn't load sound {}:", name)
            LOGGER.info('UI sounds disabled.')
            sounds = NullSound()
        else:
            self.sources[name] = src
            return src

    def fx(self, sound: str) -> None:
        """Play a sound effect."""
        global sounds
        if play_sound:
            try:
                snd = self.sources[sound]
            except KeyError:
                # We were called before the BG thread loaded em, load it
                # synchronously.
                LOGGER.warning('Sound "{}" couldn\'t be loaded in time!', sound)
                snd = self.load(sound)
            try:
                snd.play()
            except Exception:
                LOGGER.exception("Couldn't play sound {}:", sound)
                LOGGER.info('UI sounds disabled.')
                sounds = NullSound()


def ticker() -> None:
    """We need to constantly trigger pyglet.clock.tick().

    Instead of re-registering this, cache off the command name.
    """
    if isinstance(sounds, PygletSound):
        try:
            tick(True)  # True = don't sleep().
        except Exception:
            LOGGER.exception('Pyglet tick failed:')
        else:  # Succeeded, do this again soon.
            TK_ROOT.tk.call(ticker_cmd)


def load_fx() -> None:
    """Load the FX sounds in the background.

    We don't bother locking, we only modify the shared sound
    dict at the end.
    If we happen to hit a race condition with the main
    thread, all that can happen is we load it twice.
    """
    for sound in SOUNDS:
        # Copy locally, so this instance check stays valid.
        snd = sounds
        if isinstance(snd, PygletSound):
            try:
                snd.load(sound)
            except Exception:
                LOGGER.exception('Failed to load sound:')
                return


def fx(name) -> None:
    """Play a sound effect stored in the sounds{} dict."""
    sounds.fx(name)


def fx_blockable(sound: str) -> None:
    """Play a sound effect.

    This waits for a certain amount of time between retriggering sounds
    so they don't overlap.
    """
    sounds.fx_blockable(sound)


def block_fx() -> None:
    """Block fx_blockable() for a short time."""
    sounds.block_fx()


def has_sound() -> bool:
    """Return if the sound system is functional."""
    return isinstance(sounds, PygletSound)


sounds: NullSound
try:
    import pyglet.media
    from pyglet.media.codecs import Source
    from pyglet import version as pyglet_version
    from pyglet.clock import tick

    sounds = PygletSound()
    ticker_cmd = ('after', 150, TK_ROOT.register(ticker))
    TK_ROOT.tk.call(ticker_cmd)
    threading.Thread(target=load_fx, name='BEE2.sound.load', daemon=True).start()
except Exception:
    LOGGER.exception('Pyglet not importable:')
    pyglet_version = '(Not installed)'
    sounds = NullSound()


class SamplePlayer:
    """Handles playing a single audio file, and allows toggling it on/off."""
    def __init__(
        self,
        start_callback: Callable[[], None],
        stop_callback: Callable[[], None],
        system: FileSystemChain,
    ) -> None:
        """Initialise the sample-playing manager.
        """
        self.sample: Optional[Source] = None
        self.start_time: float = 0   # If set, the time to start the track at.
        self.after: Optional[str] = None
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.cur_file: Optional[str] = None
        # The system we need to cleanup.
        self._handle: Optional[IO[bytes]] = None
        self._cur_sys: Optional[FileSystem] = None
        self.system: FileSystemChain = system

    @property
    def is_playing(self) -> bool:
        """Is the player currently playing sounds?"""
        return self.sample is not None

    def _close_handles(self) -> None:
        """Close down previous sounds."""
        if self._handle is not None:
            self._handle.close()
        if self._cur_sys is not None:
            self._cur_sys.close_ref()
        self._handle = self._cur_sys = None

    def play_sample(self, e: Event=None) -> None:
        """Play a sample of music.

        If music is being played it will be stopped instead.
        """
        if self.cur_file is None:
            return

        if self.sample is not None:
            self.stop()
            return

        self._close_handles()

        with self.system:
            try:
                file = self.system[self.cur_file]
            except (KeyError, FileNotFoundError):
                self.stop_callback()
                LOGGER.error('Sound sample not found: "{}"', self.cur_file)
                return  # Abort if music isn't found..

            child_sys = self.system.get_system(file)
            # Special case raw filesystems - Pyglet is more efficient
            # if it can just open the file itself.
            if isinstance(child_sys, RawFileSystem):
                load_path = os.path.join(child_sys.path, file.path)
                self._cur_sys = self._handle = None
                LOGGER.debug('Loading music directly from {!r}', load_path)
            else:
                # Use the file objects directly.
                load_path = self.cur_file
                self._cur_sys = child_sys
                self._cur_sys.open_ref()
                self._handle = file.open_bin()
                LOGGER.debug('Loading music via {!r}', self._handle)
            try:
                sound = pyglet.media.load(load_path, self._handle)
            except Exception:
                self.stop_callback()
                LOGGER.exception('Sound sample not valid: "{}"', self.cur_file)
                return  # Abort if music isn't found or can't be loaded.

        if self.start_time:
            try:
                sound.seek(self.start_time)
            except Exception:
                LOGGER.exception('Cannot seek in "{}"!', self.cur_file)

        self.sample = sound.play()
        self.after = TK_ROOT.after(
            int(sound.duration * 1000),
            self._finished,
        )
        self.start_callback()

    def stop(self) -> None:
        """Cancel the music, if it's playing."""
        if self.sample is None:
            return

        self.sample.pause()
        self.sample = None
        self._close_handles()
        self.stop_callback()

        if self.after is not None:
            TK_ROOT.after_cancel(self.after)
            self.after = None

    def _finished(self) -> None:
        """Reset values after the sound has finished."""
        self.sample = None
        self.after = None
        self._close_handles()
        self.stop_callback()
