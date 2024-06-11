"""Export quote pack configurations."""
from typing import TYPE_CHECKING
import pickle
import shutil

import srctools
import trio
from srctools import Vec

import utils
from exporting import ExportData, STEPS, StepResource
from packages import QuotePack
from quote_pack import QuoteInfo


if TYPE_CHECKING:
    from app.gameMan import Game


__all__: list[str] = []
LOGGER = srctools.logger.get_logger(__name__)


async def write_data(game: 'Game', data: QuoteInfo | None) -> None:
    """Write the quote data."""
    pickle_data = await trio.to_thread.run_sync(pickle.dumps, data, pickle.HIGHEST_PROTOCOL)
    await trio.Path(game.abs_path('bin/bee2/voice.bin')).write_bytes(pickle_data)


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_quote_pack(exp_data: ExportData) -> None:
    """Export the quotepack."""
    sel_id: str | None = exp_data.selected[QuotePack]
    if sel_id is None:
        # No quote pack selected at all. Write a blank definition.
        await write_data(exp_data.game, QuoteInfo(
            id='',
            cave_skin=None,
            use_dings=False,
            use_microphones=False,
            global_bullseye='',
            chars=set(),
            base_inst='',
            position=Vec(),
            groups={},
            events={},
            response_use_dings=False,
            responses={},
            midchamber=[],
            monitor=None,
        ))
        return

    try:
        voice = exp_data.packset.obj_by_id(QuotePack, sel_id)
    except KeyError:
        raise Exception(f"Selected voice ({sel_id}) doesn't exist?") from None

    exp_data.vbsp_conf += voice.config
    await write_data(exp_data.game, voice.data)

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
