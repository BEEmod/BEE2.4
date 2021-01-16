"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
import os
from tkinter import Event
from typing import IO, Optional, Callable, Union, Dict

import utils

from app import TK_ROOT
from srctools.filesys import FileSystemChain, FileSystem, RawFileSystem
import srctools.logger

__all__ = [
    'SOUNDS', 'SamplePlayer',

    'pyglet_version', 'initiallised',
    'load_snd', 'play_sound', 'fx',
    'fx_blockable', 'block_fx',
]

LOGGER = srctools.logger.get_logger(__name__)

play_sound = True

# This starts holding the filenames, but then caches the actual sound object.
SOUNDS: Dict[str, Union[str, 'Source']] = {
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

try:
    import pyglet.media

    pyglet_version = pyglet.version
except Exception:
    LOGGER.warning('ERROR:SOUNDS NOT INITIALISED!', exc_info=True)

    pyglet_version = '(Not installed)'

    def fx(*args, **kwargs):
        """Pyglet has failed to initialise!

        No sounds will be played.
        """

    def load_snd() -> None:
        """Load in sound FX."""

    def fx_blockable(sound: str) -> None:
        """Play a sound effect.

        This waits for a certain amount of time between retriggering sounds
        so they don't overlap.
        """

    def block_fx() -> None:
        """Block fx_blockable() for a short time."""

    initiallised = False
    pyglet = avbin = None  # type: ignore
    SamplePlayer = None  # type: ignore
else:
    # Was able to load Pyglet.
    from pyglet.media.codecs import Source
    from pyglet.media.exceptions import (
        MediaDecodeException, MediaFormatException, CannotSeekException,
    )
    from pyglet.clock import tick
    initiallised = True
    _play_repeat_sfx = True

    def load_snd() -> None:
        """Load all the sounds."""
        for name, fname in SOUNDS.items():
            LOGGER.info('Loading sound "{}" -> sounds/{}.ogg', name, fname)
            SOUNDS[name] = pyglet.media.load(
                str(utils.install_path('sounds/{}.ogg'.format(fname))),
                streaming=False,
            )

    def fx(name, e=None):
        """Play a sound effect stored in the sounds{} dict."""
        if not play_sound:
            return
        # Defer loading these until we actually need them, speeds up
        # startup a little.
        try:
            sound = SOUNDS[name]
        except KeyError:
            raise ValueError(f'Not a valid sound? "{name}"')
        if type(sound) is str:
            LOGGER.warning('load_snd() not called when playing "{}"?', name)
        else:
            sound.play()


    def _reset_fx_blockable() -> None:
        """Reset the fx_norep() call after a delay."""
        global _play_repeat_sfx
        _play_repeat_sfx = True

    def fx_blockable(sound: str) -> None:
        """Play a sound effect.

        This waits for a certain amount of time between retriggering sounds
        so they don't overlap.
        """
        global _play_repeat_sfx
        if play_sound and _play_repeat_sfx:
            fx(sound)
            _play_repeat_sfx = False
            TK_ROOT.after(75, _reset_fx_blockable)

    def block_fx():
        """Block fx_blockable() for a short time."""
        global _play_repeat_sfx
        _play_repeat_sfx = False
        TK_ROOT.after(50, _reset_fx_blockable)

    def ticker() -> None:
        """We need to constantly trigger pyglet.clock.tick().

        Instead of re-registering this, cache off the command name.
        """
        tick()
        TK_ROOT.tk.call(ticker_cmd)

    ticker_cmd = ('after', 150, TK_ROOT.register(ticker))
    TK_ROOT.tk.call(ticker_cmd)

    class SamplePlayer:
        """Handles playing a single audio file, and allows toggling it on/off."""
        def __init__(
            self,
            start_callback:  Callable[[], None],
            stop_callback:  Callable[[], None],
            system: FileSystemChain,
        ) -> None:
            """Initialise the sample-playing manager.
            """
            self.sample: Optional[Source] = None
            self.start_time: float = 0   # If set, the time to start the track at.
            self.after: Optional[str] = None
            self.start_callback: Callable[[], None] = start_callback
            self.stop_callback: Callable[[], None] = stop_callback
            self.cur_file: Optional[str] = None
            # The system we need to cleanup.
            self._handle: Optional[IO[bytes]] = None
            self._cur_sys: Optional[FileSystem] = None
            self.system: FileSystemChain = system

        @property
        def is_playing(self):
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
            pass
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
                except (MediaDecodeException, MediaFormatException):
                    self.stop_callback()
                    LOGGER.exception('Sound sample not valid: "{}"', self.cur_file)
                    return  # Abort if music isn't found..

            if self.start_time:
                try:
                    sound.seek(self.start_time)
                except CannotSeekException:
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
