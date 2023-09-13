"""Replacement for Valve's VRAD.

This allows us to change the arguments passed in,
edit the BSP after instances are collapsed, and pack files.
"""
# Run as early as possible to catch errors in imports.
from srctools.logger import init_logging
LOGGER = init_logging('bee2/vrad.log')

import os
import sys
from io import BytesIO
from zipfile import ZipFile
from typing import List, Set
from pathlib import Path


import srctools.run
from srctools import FGD
from srctools.bsp import BSP, BSP_LUMPS
from srctools.filesys import RawFileSystem, ZipFileSystem, FileSystem
from srctools.packlist import PackList
from srctools.game import find_gameinfo

from hammeraddons.bsp_transform import run_transformations
from hammeraddons.plugin import PluginFinder, Source as PluginSource
from hammeraddons import __version__ as version_haddons

import trio

from BEE2_config import ConfigFile
from postcomp import music, screenshot
import utils


def load_transforms() -> None:
    """Load all the BSP transforms.

    We need to do this differently when frozen, since they're embedded in our
    executable.
    """
    if utils.FROZEN:
        # We embedded a copy of all the transforms in this package, which auto-imports the others.
        # noinspection PyUnresolvedReferences
        from postcomp import transforms  # type: ignore
        LOGGER.debug('Loading transforms from frozen package: {}', transforms)
    else:
        # We can just delegate to the regular postcompiler finder.
        transform_loc = utils.install_path('hammeraddons/transforms/').resolve()
        if not transform_loc.exists():
            raise ValueError(
                f'No BSP transforms location "{transform_loc.resolve()}"!\n'
                'Initialise your submodules!'
            )
        finder = PluginFinder('postcomp.transforms', {
            'builtin': PluginSource('builtin', transform_loc, recursive=True),
        })
        sys.meta_path.append(finder)
        LOGGER.debug('Loading transforms from source: {}', transform_loc)
        finder.load_all()

    # Load our additional BSP transforms.
    # noinspection PyUnresolvedReferences
    from postcomp import coop_responses, filter, user_error, debug_info  # noqa: F401


def run_vrad(args: List[str]) -> None:
    """Execute the original VRAD."""
    code = srctools.run.run_compiler(
        os.path.join(os.getcwd(), 'linux32/vrad' if utils.LINUX else 'vrad'),
        args,
    )
    if code == 0:
        LOGGER.info("Done!")
    else:
        LOGGER.warning("VRAD failed! ({})", code)
        sys.exit(code)


async def main(argv: List[str]) -> None:
    """Main VRAD script."""
    LOGGER.info(
        "BEE{} VRAD hook initiallised, srctools v{}, Hammer Addons v{}",
        utils.BEE_VERSION, srctools.__version__, version_haddons,
    )

    # Warn if srctools Cython code isn't installed.
    utils.check_cython(LOGGER.warning)

    args = " ".join(argv)
    fast_args = argv[1:]
    full_args = argv[1:]

    if not fast_args:
        # No arguments!
        LOGGER.info(
            'No arguments!\n'
            "The BEE2 VRAD takes all the regular VRAD's "
            'arguments, with some extra arguments:\n'
            '-force_peti: Force enabling map conversion. \n'
            "-force_hammer: Don't convert the map at all.\n"
            "-skip_vrad: Don't run the original VRAD after conversion.\n"
            "If not specified, the map name must be \"preview.bsp\" to be "
            "treated as PeTI."
        )
        sys.exit()

    # The path is the last argument to vrad
    # P2 adds wrong slashes sometimes, so fix that.
    fast_args[-1] = path = os.path.normpath(argv[-1])

    LOGGER.info("Map path is " + path)

    LOGGER.info('Loading Settings...')
    config = ConfigFile('compile.cfg')

    for a in fast_args[:]:
        folded_a = a.casefold()
        if folded_a.casefold() in (
                "-final",
                "-staticproplighting",
                "-staticproppolys",
                "-textureshadows",
                ):
            # remove final parameters from the modified arguments
            fast_args.remove(a)
        elif folded_a == '-both':
            # LDR Portal 2 isn't actually usable, so there's not much
            # point compiling for it.
            pos = fast_args.index(a)
            fast_args[pos] = full_args[pos] = '-hdr'
        elif a in ('-force_peti', '-force_hammer', '-no_pack'):
            # we need to strip these out, otherwise VRAD will get confused
            fast_args.remove(a)
            full_args.remove(a)

    fast_args = ['-bounce', '2', '-noextra'] + fast_args

    # Fast args: -bounce 2 -noextra -game $gamedir $path\$file
    # Final args: -both -final -staticproplighting -StaticPropPolys
    # -textureshadows  -game $gamedir $path\$file

    if not path.endswith(".bsp"):
        path += ".bsp"

    if not os.path.exists(path):
        raise ValueError(f'"{path}" does not exist!')
    if not os.path.isfile(path):
        raise ValueError(f'"{path}" is not a file!')

    LOGGER.info('Reading BSP')
    bsp_file = BSP(path)

    # Hard to determine if the map is PeTI or not, so use VBSP's stashed info.
    if srctools.conv_bool(bsp_file.ents.spawn['BEE2_is_peti']):
        is_peti = True
        # VBSP passed this along.
        is_preview = srctools.conv_bool(bsp_file.ents.spawn['BEE2_is_preview'])
        if is_preview:
            # Checks what the light config was set to.
            light_args = config.get_val('General', 'vrad_compile_type', 'FAST')
            # If shift is held, reverse.
            if utils.check_shift():
                if light_args == 'FAST':
                    light_args = 'FULL'
                else:
                    light_args = 'FAST'
                LOGGER.info('Shift held, changing configured lighting option to {}!', light_args)
        else:
            # publishing - always force full lighting.
            light_args = 'FULL'
    else:
        is_peti = False
        is_preview = False
        light_args = 'FULL'

    if '-force_peti' in args or '-force_hammer' in args or '-skip_vrad' in args:
        # we have override commands!
        if '-force_peti' in args:
            LOGGER.warning('OVERRIDE: Applying cheap lighting!')
            is_peti = True
            light_args = 'FAST'
        else:
            LOGGER.warning('OVERRIDE: Preserving args!')
            is_peti = False
            light_args = 'FULL'

        if '-skip_vrad' in args:
            LOGGER.warning('OVERRIDE: VRAD will not run!')
            light_args = 'NONE'

    LOGGER.info('Map status: is_peti={}, is_preview={} light_args={}', is_peti, is_preview, light_args)
    if not is_peti:
        # Skip everything, if the user wants these features install the Hammer Addons postcompiler.
        LOGGER.info("Hammer map detected! Skipping all transforms.")
        run_vrad(full_args)
        return

    # Grab the currently mounted filesystems in P2.
    game = find_gameinfo(argv)
    root_folder = game.path.parent
    fsys = game.get_filesystem()

    # Special case - move the BEE2 filesystem FIRST, so we always pack files found there.
    for child_sys in fsys.systems[:]:
        if 'bee2' in child_sys[0].path.casefold():
            fsys.systems.remove(child_sys)
            fsys.systems.insert(0, child_sys)

    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data)

    # Mount the existing packfile, so the cubemap files are recognised.
    pakfile_fs = ZipFileSystem('<BSP pakfile>', zipfile)
    fsys.add_sys(pakfile_fs)

    LOGGER.info('Done!')

    LOGGER.debug('Filesystems:')
    for child_sys in fsys.systems[:]:
        LOGGER.debug('- {}: {!r}', child_sys[1], child_sys[0])

    LOGGER.info('Reading our FGD files...')
    fgd = FGD.engine_dbase()

    packlist = PackList(fsys)
    LOGGER.info('Reading soundscripts...')
    packlist.load_soundscript_manifest(root_folder / 'bin/bee2/sndscript_cache.dmx')

    # We need to add all soundscripts in scripts/bee2_snd/
    # This way we can pack those, if required.
    for soundscript in fsys.walk_folder('scripts/bee2_snd/'):
        if soundscript.path.endswith('.txt'):
            packlist.load_soundscript(soundscript, always_include=False)

    LOGGER.info('Reading particles....')
    packlist.load_particle_manifest(root_folder / 'bin/bee2/particle_cache.dmx')

    LOGGER.info('Loading transforms...')
    load_transforms()

    LOGGER.info('Checking for music:')
    music.generate(bsp_file.ents, packlist)

    LOGGER.info('Run transformations...')
    await run_transformations(bsp_file.ents, fsys, packlist, bsp_file, game)

    if '-no_pack' not in args and (
        not is_preview or config.getboolean("General", "packfile_auto_enable", True)
    ):
        LOGGER.info('Scanning map for files to pack:')
        packlist.pack_from_bsp(bsp_file)
        packlist.pack_from_ents(bsp_file.ents, Path(path).stem, ['P2'])
        packlist.eval_dependencies()
        LOGGER.info('Done!')

        packlist.write_soundscript_manifest()
        packlist.write_particles_manifest(f'maps/{Path(path).stem}_particles.txt')
    else:
        LOGGER.warning('Packing disabled!')

    # We need to disallow Valve folders.
    pack_whitelist: Set[FileSystem] = set()
    pack_blacklist: Set[FileSystem] = {pakfile_fs}

    # Exclude absolutely everything except our folder.
    for child_sys, _ in fsys.systems:
        # Add 'bee2/' and 'bee2_dev/' only.
        if (
            isinstance(child_sys, RawFileSystem) and
            'bee2' in os.path.basename(child_sys.path).casefold()
        ):
            pack_whitelist.add(child_sys)
        else:
            pack_blacklist.add(child_sys)

    if config.get_bool('General', 'packfile_dump_enable'):
        dump_loc = Path(config.get_val(
            'General',
            'packfile_dump_dir',
            '../dump/'
        )).absolute()
    else:
        dump_loc = None

    LOGGER.info('Writing BSP...')
    bsp_file.save()
    LOGGER.info(' - BSP written!')

    # VRAD only runs if light_args is not set to "NONE"
    if light_args == 'FAST':
        LOGGER.info("Running VRAD: forcing cheap lighting.")
        run_vrad(fast_args)
    elif light_args == 'FULL':
        LOGGER.info("Running VRAD: full lighting enabled (publishing, or forced to do so)")
        run_vrad(full_args)
    else:
        LOGGER.info("Running VRAD was skipped!")

    LOGGER.info("VRAD completed. Reopening and packing files.")

    bsp_file = BSP(path)

    # Cubemap files packed into the map already.
    existing = set(bsp_file.pakfile.namelist())

    # Pack to the BSP *after* running VRAD, to ensure an extra-large packfile doesn't crash
    # VRAD.
    LOGGER.info('Writing to BSP...')
    packlist.pack_into_zip(
        bsp_file,
        ignore_vpk=True,
        whitelist=pack_whitelist,
        blacklist=pack_blacklist,
        dump_loc=dump_loc,
    )

    LOGGER.info('Writing BSP...')
    bsp_file.save()
    LOGGER.info(' - BSP written!')

    LOGGER.info('Packed files:\n{}', '\n'.join(
        set(bsp_file.pakfile.namelist()) - existing
    ))

    screenshot.modify(config, game.path)

    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    trio.run(main, sys.argv)
