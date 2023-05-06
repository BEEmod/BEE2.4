"""Include a VScript that reports the app version and other info."""
from srctools.const import FileType
import srctools.logger

from hammeraddons.bsp_transform import Context, trans
import utils


LOGGER = srctools.logger.get_logger(__name__)


@trans('BEE2: Write Debug Info')
def write_debug_info(ctx: Context) -> None:
    """Include a VScript that reports the app version and other info."""
    data = [
        f'printl("BEE version: {utils.BEE_VERSION}");',
        f'printl("Dev mode: {utils.DEV_MODE}, compiled={utils.FROZEN}");',
        f'printl("Map items: ");',
    ]

    used_ids: list[str] = []

    for lst_ent in ctx.vmf.by_class['bee2_item_list']:
        lst_ent.remove()
        for kv_name, value in lst_ent.items():
            if kv_name.startswith('itemid'):
                used_ids.append(value)
    used_ids.sort()
    for item_id in used_ids:
        data.append(f'printl(" - {item_id}");')

    ctx.pack.pack_file(
        'scripts/vscripts/bee_map_info.nut',
        FileType.VSCRIPT_SQUIRREL,
        data='\n'.join(data).encode('utf8'),
    )
