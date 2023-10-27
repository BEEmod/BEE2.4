"""Export quote pack configurations."""
from typing import Optional
import pickle
import shutil

import srctools
import trio

import utils
from exporting import ExportData, STEPS, StepResource
from packages import QuotePack
from quote_pack import QuoteInfo


LOGGER = srctools.logger.get_logger(__name__)


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_quote_pack(exp_data: ExportData) -> None:
    """Export the quotepack."""
    sel_id: Optional[str] = exp_data.selected[QuotePack]
    if sel_id is None:
        return  # No quote pack selected at all, don't write anything.

    try:
        voice = exp_data.packset.obj_by_id(QuotePack, sel_id)
    except KeyError:
        raise Exception(f"Selected voice ({sel_id}) doesn't exist?") from None

    exp_data.vbsp_conf += voice.config

    data = QuoteInfo(
        id=voice.id,
        chars=voice.chars,
        cave_skin=voice.cave_skin,
        base_inst=voice.base_inst,
        position=voice.position,
        use_dings=voice.use_dings,
        use_microphone=voice.use_microphone,
        global_bullseye=voice.global_bullseye,
        groups=voice.groups,
        events=voice.events,
        responses=voice.responses,
        midchamber=voice.midchamber,
        monitor=voice.monitor,
    )
    pickle_data = await trio.to_thread.run_sync(pickle.dumps, data, pickle.HIGHEST_PROTOCOL)
    await trio.Path(exp_data.game.abs_path('bin/bee2/voice.bin')).write_bytes(pickle_data)
    del pickle_data

    # Copy the config files for this voice line...
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
