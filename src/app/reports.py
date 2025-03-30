"""Various reports that can be triggered from the options menu."""
from collections import defaultdict, Counter
from pathlib import PurePosixPath

import srctools.logger
import trio
from srctools import FileSystemChain
from srctools.mdl import Model

from packages import Item, OBJ_TYPES, get_loaded_packages
from app import gameMan
import utils


LOGGER = srctools.logger.get_logger(__name__)


def get_report_file(filename: str) -> trio.Path:
    """The folder where reports are dumped to."""
    reports = utils.install_path('reports')
    reports.mkdir(parents=True, exist_ok=True)
    file = trio.Path(reports / filename)
    LOGGER.info('Producing {}...', file)
    return file


async def report_all_obj() -> None:
    """Print a list of every object type and ID."""
    packset = get_loaded_packages()
    for type_name, obj_type in OBJ_TYPES.items():
        async with await get_report_file(f'obj_{type_name}.txt').open('w') as f:
            obj_ids = [obj.id for obj in packset.all_obj(obj_type)]
            obj_ids.sort()
            await f.write(f'{len(obj_ids)} {obj_type.__name__} objects:\n')
            for obj_id in obj_ids:
                await f.write(f'- {obj_id}\n')


async def report_items() -> None:
    """Print out all the item IDs used, with subtypes."""
    await trio.lowlevel.checkpoint()
    packset = get_loaded_packages()
    async with await get_report_file('items.txt').open('w') as f:
        for item in sorted(packset.all_obj(Item), key=lambda it: it.id):
            for vers_name, version in item.versions.items():
                if len(item.versions) == 1:
                    await f.write(f'- `<{item.id}>`\n')
                else:
                    await f.write(f'- `<{item.id}:{vers_name}>`\n')

                variant_to_id = defaultdict(list)
                for sty_id, variant in version.styles.items():
                    variant_to_id[variant].append(sty_id)

                for variant, style_ids in variant_to_id.items():
                    await f.write(
                        f'\t- [ ] {", ".join(sorted(style_ids))}:\n'
                        f'\t  `{variant.source}`\n'
                    )


async def report_editor_models() -> None:
    """Analyse the materials used by editor models."""
    from packages import Item, get_loaded_packages
    packset = get_loaded_packages()
    fsys = FileSystemChain()
    mat_to_usage: dict[str, set[str]] = defaultdict(set)
    usage_counts = Counter[str]()

    LOGGER.info('Checking existing packages...')
    mdl_map_editor = PurePosixPath('resources/models/props_map_editor')
    for pack in packset.packages.values():
        fsys.add_sys(pack.fsys, 'resources')
        for folder in [
            'resources/materials/BEE2/models/props_map_editor/',
            'resources/materials/models/props_map_editor/',
        ]:
            for file in pack.fsys.walk_folder(folder):
                if file.path.endswith('.vmt'):
                    rel_path_str = file.path[10:]  # Strip resources/
                    mat_to_usage[rel_path_str.casefold()] = set()
        for file in pack.fsys.walk_folder(str(mdl_map_editor)):
            if file.path.endswith('.mdl'):
                rel_path = PurePosixPath(file.path).relative_to(mdl_map_editor)
                usage_counts[str(rel_path).casefold()] = 0

    LOGGER.info('Mounting game resources...')
    if (game := gameMan.selected_game.value) is not None:
        fsys.add_sys(game.get_filesystem())

    async def worker(channel: trio.MemoryReceiveChannel[PurePosixPath]) -> None:
        """Evaluates each model."""
        async for mdl_name in channel:
            try:
                file = await trio.to_thread.run_sync(fsys.__getitem__, str('models/props_map_editor' / mdl_name))
            except FileNotFoundError:
                LOGGER.warning('Model "{}" does not exist', mdl_name)
                continue
            try:
                mdl: Model = await trio.to_thread.run_sync(Model, fsys, file)
            except ValueError:
                LOGGER.exception('Model "{}" cannot be parsed.', mdl_name)
                continue
            folded_name = str(mdl_name).casefold()
            for tex in mdl.iter_textures((0, )):  # Only skin 0 is used.
                mat_to_usage[tex.casefold()].add(folded_name)

    LOGGER.info('Checking usage...')
    editor_models = [
        mdl.with_suffix('.mdl')
        for item in packset.all_obj(Item)
        for version in item.versions.values()
        for style in version.styles.values()
        for editor in [style.editor, *style.editor_extra]
        for subtype in editor.subtypes
        for mdl in subtype.models
    ]
    usage_counts.update(str(path).casefold() for path in editor_models)

    send: trio.MemorySendChannel[PurePosixPath]
    rec: trio.MemoryReceiveChannel[PurePosixPath]
    send, rec = trio.open_memory_channel(0)
    LOGGER.info('{} models in total', len(usage_counts))
    async with trio.open_nursery() as nursery, send:
        for _ in range(10):
            nursery.start_soon(worker, rec)
        for mdl in set(editor_models):
            await send.send(mdl)

    LOGGER.info('Analysed, writing info:')
    async with await get_report_file('editor_models.txt').open('w') as f:
        await f.write('Models:\n')
        for filename, count in usage_counts.most_common():
            await f.write(f'- [{count}]: {filename}\n')
        await f.write('\nMaterials:\n')
        # Sort by count, then mat name.
        for mat, mdls in sorted(mat_to_usage.items(), key=lambda t: (len(t[1]), t[0])):
            await f.write(f'- {len(mdls)}x {mat} = [{", ".join(mdls)}]\n')
    LOGGER.info('Editor model report complete!')
