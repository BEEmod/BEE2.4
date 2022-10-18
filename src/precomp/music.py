"""Handles adding music to the level."""
from typing import Set, List

from srctools import VMF, Vec, Property, Output
from precomp import corridor, options, conditions
from consts import MusicChannel as Channel
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)


def add(
    vmf: VMF,
    loc: Vec,
    conf: Property,
    info: corridor.Info,
) -> None:
    """Add music to the map."""
    LOGGER.info("Adding Music...")
    # These values are exported by the BEE2 app, indicating the
    # options on the music item.
    inst = options.get(str, 'music_instance')
    snd_length = options.get(int, 'music_looplen')

    # Don't add our logic if an instance was provided.
    # If this settings is set, we have a music config.
    if conf and not inst:
        music = vmf.create_ent(
            classname='ambient_generic',
            spawnflags='17',  # Looping, Infinite Range, Starts Silent
            targetname='@music',
            origin=loc,
            message='music.BEE2',
            health='10',  # Volume
        )

        music_start = vmf.create_ent(
            classname='logic_relay',
            spawnflags='0',
            targetname='@music_start',
            origin=loc + (-16, 0, -16),
        )
        music_stop = vmf.create_ent(
            classname='logic_relay',
            spawnflags='0',
            targetname='@music_stop',
            origin=loc + (16, 0, -16),
        )
        music_stop.add_out(
            Output('OnTrigger', music, 'StopSound'),
            Output('OnTrigger', music, 'Volume', '0'),
        )

        # In SinglePlayer, music gets killed during reload,
        # so we need to restart it.

        # If snd_length is set, we have a non-loopable MP3
        # and want to re-trigger it after the time elapses, to simulate
        # looping.

        # In either case, we need @music_restart to do that safely.
        if info.is_sp or snd_length > 0:
            music_restart = vmf.create_ent(
                classname='logic_relay',
                spawnflags='2',  # Allow fast retrigger.
                targetname='@music_restart',
                StartDisabled='1',
                origin=loc + (0, 0, -16),
            )

            music_start.add_out(
                Output('OnTrigger', music_restart, 'Enable'),
                Output('OnTrigger', music_restart, 'Trigger', delay=0.01),
            )

            music_stop.add_out(
                Output('OnTrigger', music_restart, 'Disable'),
                Output('OnTrigger', music_restart, 'CancelPending'),
            )

            music_restart.add_out(
                Output('OnTrigger', music, 'StopSound'),
                Output('OnTrigger', music, 'Volume', '0'),
                Output('OnTrigger', music, 'Volume', '10', delay=0.1),
                Output('OnTrigger', music, 'PlaySound', delay=0.1),
            )

            if info.is_sp:
                # Trigger on level loads.
                vmf.create_ent(
                    classname='logic_auto',
                    origin=loc + (0, 0, 16),
                    spawnflags='0',  # Don't remove after fire
                    globalstate='',
                ).add_out(
                    Output('OnLoadGame', music_restart, 'CancelPending'),
                    Output('OnLoadGame', music_restart, 'Trigger', delay=0.01),
                )

            if snd_length > 0:
                # Re-trigger after the music duration.
                music_restart.add_out(
                    Output('OnTrigger', '!self', 'Trigger', delay=snd_length)
                )
                # Set to non-looping, so re-playing will restart it correctly.
                music['spawnflags'] = '49'
        else:
            # The music track never needs to have repeating managed,
            # just directly trigger.
            music_start.add_out(
                Output('OnTrigger', music, 'PlaySound'),
                Output('OnTrigger', music, 'Volume', '10'),
            )

        # Add the ents for the config itself.
        # If the items aren't in the map, we can skip adding them.
        # Speed-gel sounds also play when flinging, so keep it always.
        funnel = conf.find_key('tbeam', or_blank=True)
        bounce = conf.find_key('bouncegel', or_blank=True)

        make_channel_conf(
            vmf, loc,
            Channel.BASE,
            conf.find_key('base', or_blank=True).as_array(),
        )
        make_channel_conf(
            vmf, loc,
            Channel.SPEED,
            conf.find_key('speedgel', or_blank=True).as_array(),
        )
        if info.has_attr('funnel') or info.has_attr('excursionfunnel'):
            make_channel_conf(
                vmf, loc,
                Channel.TBEAM,
                funnel.as_array(),
                conf.bool('sync_funnel'),
            )

        if info.has_attr('bouncegel') or info.has_attr('bluegel'):
            make_channel_conf(
                vmf, loc,
                Channel.BOUNCE,
                bounce.as_array(),
            )

        packfiles = conf.find_key('pack', or_blank=True).as_array()
        if packfiles:
            packer = vmf.create_ent('comp_pack', origin=loc)
            for i, fname in enumerate(packfiles, 1):
                packer[f'generic{i:02}'] = fname

    if inst:
        # We assume the instance is setup correct.
        conditions.add_inst(
            vmf,
            targetname='music',
            origin=loc,
            file=inst,
        )


def make_channel_conf(
    vmf: VMF,
    pos: Vec,
    channel: Channel,
    tracks: List[str],
    sync: bool = False,
) -> None:
    """Embed the specified channel's data into the map via a custom ent."""
    if tracks:
        ent = vmf.create_ent(
            'bee2_music_channel',
            origin=pos,
            channel=channel.value,
            sync=sync,
        )
        for i, track in enumerate(tracks, 1):
            ent[f'track{i:02}'] = track
