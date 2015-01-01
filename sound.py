'''
This module provides a wrapper around PyGame, in order to play sounds easily.
To use, call sound.fx() with one of the dict keys.
If PyGame fails to load, all fx() calls will fail silently.
(Sounds are not critical to the app, so they just won't play.)
'''
muted = False

try:
    import pygame
    # buffer must be power of 2, higher means less choppy audio but
    # higher latency between play() and the sound actually playing.
    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=1024)
except Exception:
    print('ERROR:SOUNDS NOT INITIALISED!')
    def fx(*args):
        '''Pygame has failed to initialise!
        
        No sounds will be played.
        '''
    initiallised = False
else:
    # Succeeded
    initiallised = True
    sounds = {
        'select':'rollover',
        'add':'increment',
        'config':'reconfig',
        'subtract':'decrement',
        'connect':'connection_made',
        'disconnect':'connection_destroyed',
        'expand':'extrude',
        'delete':'collapse',
        'error':'error',
        'contract':'carve',
        'raise_1':'panel_raise_01',
        'raise_2':'panel_raise_02',
        'raise_3':'panel_raise_03',
        'lower_1':'panel_lower_01',
        'lower_2':'panel_lower_02',
        'lower_3':'panel_lower_03',
        'move':'reconfig',
        'swap':'extrude',
        }

    for key in sounds:
        sounds[key] = pygame.mixer.Sound('sounds/' + sounds[key] + '.wav')

    def fx(name, e=None):
        """Play a sound effect stored in the sounds{} dict."""
        if not muted and name in sounds:
            sounds[name].play()
