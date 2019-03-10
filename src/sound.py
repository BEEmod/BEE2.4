"""
This module provides a wrapper around Pyglet, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
"""
import shutil
import os
import utils

from tk_tools import TK_ROOT
from srctools.filesys import RawFileSystem, FileSystemChain
import srctools.logger

__all__ = [
    'SOUNDS', 'SamplePlayer',

    'avbin_version', 'pyglet_version', 'initiallised',
    'load_snd', 'play_sound', 'fx',
    'fx_blockable', 'block_fx',
]

LOGGER = srctools.logger.get_logger(__name__)

play_sound = True

SAMPLE_WRITE_PATH = utils.conf_location('config/music_sample/temp')

# This starts holding the filenames, but then caches the actual sound object.
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
    LOGGER.warning('ERROR:SOUNDS NOT INITIALISED!', exc_info=True)

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

    def clean_folder():
        pass

    initiallised = False
    pyglet = avbin = None  # type: ignore
    SamplePlayer = None  # type: ignore
else:
    # Succeeded in loading PyGame
    from pyglet.media import Source, MediaFormatException, CannotSeekException
    initiallised = True
    _play_repeat_sfx = True

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
            LOGGER.info('Loading sound "{}" -> sounds/{}.ogg', name, sound)
            sound = SOUNDS[name] = pyglet.media.load(
                str(utils.install_path('sounds/{}.ogg'.format(sound))),
                streaming=False,
            )
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

    def clean_folder():
        """Delete files used by the sample player."""
        for file in SAMPLE_WRITE_PATH.parent.iterdir():
            LOGGER.info('Cleaning up "{}"...', file)
            try:
                file.unlink()
            except (PermissionError, FileNotFoundError):
                pass

    class SamplePlayer:
        """Handles playing a single audio file, and allows toggling it on/off."""
        def __init__(self, start_callback, stop_callback, system: FileSystemChain):
            """Initialise the sample-playing manager.
            """
            self.sample = None
            self.start_time = 0   # If set, the time to start the track at.
            self.after = None
            self.start_callback = start_callback
            self.stop_callback = stop_callback
            self.cur_file = None
            self.system = system

        @property
        def is_playing(self):
            """Is the player currently playing sounds?"""
            return self.sample is not None

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

            with self.system:
                try:
                    file = self.system[self.cur_file]
                except (KeyError, FileNotFoundError):
                    self.stop_callback()
                    LOGGER.error('Sound sample not found: "{}"', self.cur_file)
                    return  # Abort if music isn't found..

            # TODO: Pyglet doesn't support direct streams, so we have to
            # TODO: extract sounds to disk first.

            fsystem = self.system.get_system(file)
            if isinstance(fsystem, RawFileSystem):
                # Special case, it's directly lying on the disk -
                # We can just pass that along.
                disk_filename = os.path.join(fsystem.path, file.path)
                LOGGER.info('Directly playing sample "{}"...', disk_filename)
            else:
                # In a filesystem, we need to extract it.
                # SAMPLE_WRITE_PATH + the appropriate extension.
                disk_filename = str(SAMPLE_WRITE_PATH.with_suffix(os.path.splitext(self.cur_file)[1]))
                LOGGER.info('Extracting music sample to "{}"...', disk_filename)
                with self.system.get_system(file), file.open_bin() as fsrc:
                    with open(disk_filename, 'wb') as fdest:
                        shutil.copyfileobj(fsrc, fdest)

            try:
                sound = pyglet.media.load(disk_filename, streaming=False)  # type: Source
            except MediaFormatException:
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
