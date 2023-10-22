"""Export quote pack configurations."""
import shutil

import srctools
import trio

import utils
from exporting import ExportData, STEPS, StepResource
from packages import QuotePack


LOGGER = srctools.logger.get_logger(__name__)


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_quote_pack(exp_data: ExportData) -> None:
    """Export the quotepack."""
    if exp_data.selected is None:
        return  # No quote pack selected at all, don't write anything.

    try:
        voice = exp_data.packset.obj_by_id(QuotePack, exp_data.selected[QuotePack])
    except KeyError:
        raise Exception(f"Selected voice ({exp_data.selected}) doesn't exist?") from None

    vbsp_config = exp_data.vbsp_conf

    # We want to strip 'trans' sections from the voice pack, since
    # they're not useful.
    for prop in voice.config:
        if prop.name == 'quotes':
            vbsp_config.append(QuotePack.strip_quote_data(prop))
        else:
            vbsp_config.append(prop.copy())

    # Set values in vbsp_config, so tests can determine which voiceline
    # is selected.
    options = vbsp_config.ensure_exists('Options')

    options['voice_pack'] = voice.id
    options['voice_char'] = ','.join(voice.chars)

    if voice.cave_skin is not None:
        options['cave_port_skin'] = str(voice.cave_skin)

    if voice.studio is not None:
        options['voice_studio_inst'] = voice.studio
        options['voice_studio_actor'] = voice.studio_actor
        options['voice_studio_inter_chance'] = str(voice.inter_chance)
        if voice.cam_loc is not None:
            options['voice_studio_cam_loc'] = voice.cam_loc.join(' ')
        options['voice_studio_cam_pitch'] = str(voice.cam_pitch)
        options['voice_studio_cam_yaw'] = str(voice.cam_yaw)
        options['voice_studio_should_shoot'] = srctools.bool_as_int(voice.turret_hate)

    # Copy the config files for this voiceline..
    for prefix, pretty in [
        ('', 'normal'),
        ('mid_', 'MidChamber'),
        ('resp_', 'Responses')
    ]:
        path = utils.conf_location('config/voice/') / (prefix.upper() + voice.id + '.cfg')
        LOGGER.info('Voice conf path: {}', path)
        if await trio.to_thread.run_sync(path.is_file):
            await trio.to_thread.run_sync(
                shutil.copy,
                str(path),
                exp_data.game.abs_path(f'bin/bee2/{prefix}voice.cfg')
            )
            LOGGER.info('Written "{}voice.cfg"', prefix)
        else:
            LOGGER.info('No {} voice config!', pretty)
