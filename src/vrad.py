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
from typing import List
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
# Load our BSP transforms.
# noinspection PyUnresolvedReferences
from postcomp import coop_responses, filter
import utils


def load_transforms() -> None:
    """Load all the BSP transforms.

    We need to do this differently when frozen, since they're embedded in our
    executable.
    """
    if utils.FROZEN:
        # We embedded a copy of all the transforms in this package, which auto-imports the others.
        # noinspection PyUnresolvedReferences
        from postcomp import transforms
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


def run_vrad(args: List[str]) -> None:
    """Execute the original VRAD."""
    code = srctools.run.run_compiler(os.path.join(os.getcwd(), "vrad"), args)
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
        raise ValueError('"{}" does not exist!'.format(path))
    if not os.path.isfile(path):
        raise ValueError('"{}" is not a file!'.format(path))

    LOGGER.info('Reading BSP')
    bsp_file = BSP(path)

    # If VBSP marked it as Hammer, trust that.
    if srctools.conv_bool(bsp_file.ents.spawn['BEE2_is_peti']):
        is_peti = True
        # Detect preview via knowing the bsp name. If we are in preview,
        # check the config file to see what was specified there.
        if os.path.basename(path) == "preview.bsp":
            # Checks what the light config was set to.
            light_args = config.get_val('General', 'vrad_compile_type')
            edit_args = not config.get_bool('General', 'vrad_force_full')
            # If shift is held, reverse.
            if utils.check_shift():
                if light_args == 'FAST':
                    light_args == 'FULL'
                else:
                    light_args == 'FAST'
                LOGGER.info('Shift held, changing configured lighting option to {}!', light_args)
        else:
            # publishing - always force full lighting.
            light_args = 'FULL'
    else:
        is_peti = False
        light_args = 'FULL'

    if '-force_peti' in args or '-force_hammer' in args or '-skip_vrad':
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

    LOGGER.info('Final status: is_peti={}, light_args={}', is_peti, light_args)
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
    fsys.add_sys(ZipFileSystem('<BSP pakfile>', zipfile))

    LOGGER.info('Done!')

    LOGGER.debug('Filesystems:')
    for child_sys in fsys.systems[:]:
        LOGGER.debug('- {}: {!r}', child_sys[1], child_sys[0])

    LOGGER.info('Reading our FGD files...')
    fgd = FGD.engine_dbase()

    packlist = PackList(fsys)
    LOGGER.info('Reading soundscripts...')
    packlist.load_soundscript_manifest(
        str(root_folder / 'bin/bee2/sndscript_cache.vdf')
    )

    # We need to add all soundscripts in scripts/bee2_snd/
    # This way we can pack those, if required.
    for soundscript in fsys.walk_folder('scripts/bee2_snd/'):
        if soundscript.path.endswith('.txt'):
            packlist.load_soundscript(soundscript, always_include=False)

    LOGGER.info('Reading particles....')
    packlist.load_particle_manifest()

    LOGGER.info('Loading transforms...')
    load_transforms()

    LOGGER.info('Checking for music:')
    music.generate(bsp_file.ents, packlist)

    LOGGER.info('Run transformations...')
    await run_transformations(bsp_file.ents, fsys, packlist, bsp_file, game)

    LOGGER.info('Scanning map for files to pack:')
    packlist.pack_from_bsp(bsp_file)
    packlist.pack_fgd(bsp_file.ents, fgd)
    packlist.eval_dependencies()
    LOGGER.info('Done!')

    packlist.write_soundscript_manifest()
    packlist.write_particles_manifest(f'maps/{Path(path).stem}_particles.txt')

    # We need to disallow Valve folders.
    pack_whitelist: set[FileSystem] = set()
    pack_blacklist: set[FileSystem] = set()

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

    if '-no_pack' not in args:
        # Cubemap files packed into the map already.
        existing = set(bsp_file.pakfile.namelist())

        LOGGER.info('Writing to BSP...')
        packlist.pack_into_zip(
            bsp_file,
            ignore_vpk=True,
            whitelist=pack_whitelist,
            blacklist=pack_blacklist,
            dump_loc=dump_loc,
        )

        LOGGER.info('Packed files:\n{}', '\n'.join(
            set(bsp_file.pakfile.namelist()) - existing
        ))

    LOGGER.info('Writing BSP...')
    bsp_file.save()
    LOGGER.info(' - BSP written!')

    screenshot.modify(config, game.path)

    # VRAD only runs if light_args is not set to "NONE"
    if light_args == 'FAST':
        LOGGER.info("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    elif light_args == 'FULL':
        LOGGER.info("Publishing - Full lighting enabled! (or forced to do so)")
        run_vrad(full_args)
    else:
        LOGGER.info("Forcing to skip VRAD!")

    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    trio.run(main, sys.argv)
