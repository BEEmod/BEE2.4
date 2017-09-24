"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
import shutil
import os.path

from tk_tools import TK_ROOT
from srctools.filesys import FileSystem, FileSystemChain
import utils

__all__ = [
    'SOUNDS', 'SamplePlayer',

    'avbin_version', 'pyglet_version', 'initiallised',
    'load_snd', 'play_sound', 'fx',
    'fx_blockable', 'block_fx',
]

LOGGER = utils.getLogger(__name__)

play_sound = True

SAMPLE_WRITE_PATH = '../config/music_sample_temp'

SOUNDS = {
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
    from pyglet.media import avbin  # We need this extension, so error early.

    pyglet_version = pyglet.version
    avbin_version = avbin.get_version()
except ImportError:
    LOGGER.warning('ERROR:SOUNDS NOT INITIALISED!')

    pyglet_version = avbin_version = '(Not installed)'

    def fx(*args, **kwargs):
        """Pyglet has failed to initialise!

        No sounds will be played.
        """

    def load_snd():
        """Load in sound FX."""

    def fx_blockable(sound):
        """Play a sound effect.

        This waits for a certain amount of time between retriggering sounds
        so they don't overlap.
        """

    def block_fx():
        """Block fx_blockable() for a short time."""

    initiallised = False
    pyglet = avbin = None
    SamplePlayer = None
else:
    # Succeeded in loading PyGame
    from pyglet.media import Source, MediaFormatException, CannotSeekException
    initiallised = True
    _play_repeat_sfx = True

    def load_snd():
        """Load in sound FX."""
        for key, filename in SOUNDS.items():
            LOGGER.debug('Loading {}', filename)
            SOUNDS[key] = pyglet.media.load(
                '../sounds/' + filename + '.ogg',
                streaming=False,
            )

    def fx(name, e=None):
        """Play a sound effect stored in the sounds{} dict."""
        if play_sound and name in SOUNDS:
            SOUNDS[name].play()


    def _reset_fx_blockable():
        """Reset the fx_norep() call after a delay."""
        global _play_repeat_sfx
        _play_repeat_sfx = True

    def fx_blockable(sound):
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

    class SamplePlayer:
        """Handles playing a single audio file, and allows toggling it on/off."""
        def __init__(self, start_callback, stop_callback, system: FileSystemChain):
            """Initialise the sample-playing manager.
            """
            self.sample = None
            self.after = None
            self.start_callback = start_callback
            self.stop_callback = stop_callback
            self.cur_file = None
            self.system = system

        @property
        def is_playing(self):
            return bool(self.sample)

        def play_sample(self, e=None):
            pass
            """Play a sample of music.

            If music is being played it will be stopped instead.
            """
            if self.cur_file is None:
                return

            if self.sample is not None:
                self.stop()
                return

            try:
                file = self.system[self.cur_file]
            except KeyError:
                self.stop_callback()
                LOGGER.error('Sound sample not found: "{}"', self.cur_file)
                return  # Abort if music isn't found..

            # TODO: Pyglet doesn't support direct streams, so we have to
            # TODO: extract sounds to disk first.
            with self.system.get_system(file), file.open_bin() as fsrc, open(
                SAMPLE_WRITE_PATH + os.path.splitext(self.cur_file)[1], 'wb',
            ) as fdest:
                shutil.copyfileobj(fsrc, fdest)

            try:
                sound = pyglet.media.load(disk_filename, streaming=False)  # type: Source
            except MediaFormatException:
                self.stop_callback()
                LOGGER.exception('Sound sample not valid: "{}"', self.cur_file)
                return  # Abort if music isn't found..

            self.sample = sound.play()
            self.after = TK_ROOT.after(
                int(sound.duration * 1000),
                self._finished,
            )
            self.start_callback()

        def stop(self):
            """Cancel the music, if it's playing."""
            if self.sample is None:
                return

            self.sample.pause()
            self.sample = None
            self.stop_callback()

            if self.after is not None:
                TK_ROOT.after_cancel(self.after)
                self.after = None

        def _finished(self):
            """Reset values after the sound has finished."""
            self.sample = None
            self.after = None
            self.stop_callback()
