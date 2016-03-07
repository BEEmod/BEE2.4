"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
from tk_tools import TK_ROOT
import utils

LOGGER = utils.getLogger(__name__)

play_sound = True

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
    import pyglet
    from pyglet.media import avbin # We need this extension, so error early..
except ImportError:
    LOGGER.warning('ERROR:SOUNDS NOT INITIALISED!')

    def fx(*args, **kwargs):
        """Pygame has failed to initialise!

        No sounds will be played.
        """

    def load_snd():
        pass

    initiallised = False
    pyglet = avbin = None
    SamplePlayer = None
else:
    # Succeeded in loading PyGame
    initiallised = True

    def load_snd():
        """Load in sound FX."""
        for key, filename in SOUNDS.items():
            LOGGER.debug('Loading {}', filename)
            SOUNDS[key] = pyglet.media.load('../sounds/' + filename + '.wav', streaming=False)

    def fx(name, e=None):
        """Play a sound effect stored in the sounds{} dict."""
        if play_sound and name in SOUNDS:
            SOUNDS[name].play()

    class SamplePlayer:
        """Handles playing a single audio file, and allows toggling it on/off."""
        def __init__(self, start_callback, stop_callback):
            """Initialise the sample-playing manager.
            """
            self.sample = None
            self.after = None
            self.start_callback = start_callback
            self.stop_callback = stop_callback
            self.cur_file = None

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
                sound = pyglet.media.load(self.cur_file, streaming=False)
            except pyglet.media.MediaFormatException:
                self.stop_callback()
                LOGGER.exception('Sound sample not found: "{}"', self.cur_file)
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
