"""Replacement for Valve's VRAD.

This allows us to change the arguments passed in,
edit the BSP after instances are collapsed, and pack files.
"""
# Run as early as possible to catch errors in imports.
from srctools.logger import init_logging
LOGGER = init_logging('bee2/vrad.log')

import os
import shutil
import sys
import importlib
import pkgutil
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
from srctools.bsp_transform import run_transformations
from srctools.scripts.plugin import PluginFinder, Source as PluginSource

from BEE2_config import ConfigFile
from postcomp import music, screenshot
# Load our BSP transforms.
# noinspection PyUnresolvedReferences
from postcomp import (
    coop_responses,
    filter,
)
import utils


def load_transforms() -> None:
    """Load all the BSP transforms.

    We need to do this differently when frozen, since they're embedded in our
    executable.
    """
    # Find the modules in the conditions package.
    # PyInstaller messes this up a bit.
    if utils.FROZEN:
        # This is the PyInstaller loader injected during bootstrap.
        # See PyInstaller/loader/pyimod03_importers.py
        # toc is a PyInstaller-specific attribute containing a set of
        # all frozen modules.
        loader = pkgutil.get_loader('postcomp.transforms')
        for module in loader.toc:
            if module.startswith('postcomp.transforms'):
                LOGGER.debug('Importing transform {}', module)
                sys.modules[module] = importlib.import_module(module)
    else:
        # We can just delegate to the regular postcompiler finder.
        try:
            transform_loc = Path(os.environ['BSP_TRANSFORMS'])
        except KeyError:
            transform_loc = utils.install_path('../HammerAddons/transforms/')
        if not transform_loc.exists():
            raise ValueError(
                f'Invalid BSP transforms location "{transform_loc.resolve()}"!\n'
                'Clone TeamSpen210/HammerAddons next to BEE2.4, or set the '
                'environment variable BSP_TRANSFORMS to the location.'
            )
        finder = PluginFinder('postcomp.transforms', [
            PluginSource(transform_loc, recurse=True),
        ])
        sys.meta_path.append(finder)
        finder.load_all()


def dump_files(bsp: BSP, dump_folder: str) -> None:
    """Dump packed files to a location.
    """
    dump_folder = os.path.abspath(dump_folder)
    
    LOGGER.info('Dumping packed files to "{}"...', dump_folder)

    # Delete files in the folder, but don't delete the folder itself.
    try:
        files = os.listdir(dump_folder)
    except FileNotFoundError:
        return

    for name in files:
        name = os.path.join(dump_folder, name)
        if os.path.isdir(name):
            try:
                shutil.rmtree(name)
            except OSError:
                # It's possible to fail here, if the window is open elsewhere.
                # If so, just skip removal and fill the folder.
                pass
        else:
            os.remove(name)

    for zipinfo in bsp.pakfile.infolist():
        bsp.pakfile.extract(zipinfo, dump_folder)


def run_vrad(args: List[str]) -> None:
    """Execute the original VRAD."""
    code = srctools.run.run_compiler(os.path.join(os.getcwd(), "vrad"), args)
    if code == 0:
        LOGGER.info("Done!")
    else:
        LOGGER.warning("VRAD failed! ({})", code)
        sys.exit(code)


def main(argv: List[str]) -> None:
    """Main VRAD script."""
    LOGGER.info('BEE2 VRAD hook started!')
        
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
            "If not specified, the map name must be \"preview.bsp\" to be "
            "treated as PeTI."
        )
        sys.exit()

    # The path is the last argument to vrad
    # P2 adds wrong slashes sometimes, so fix that.
    fast_args[-1] = path = os.path.normpath(argv[-1])  # type: str

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
            edit_args = not config.get_bool('General', 'vrad_force_full')
        else:
            # publishing - always force full lighting.
            edit_args = False
    else:
        is_peti = edit_args = False

    if '-force_peti' in args or '-force_hammer' in args:
        # we have override commands!
        if '-force_peti' in args:
            LOGGER.warning('OVERRIDE: Applying cheap lighting!')
            is_peti = edit_args = True
        else:
            LOGGER.warning('OVERRIDE: Preserving args!')
            is_peti = edit_args = False

    LOGGER.info('Final status: is_peti={}, edit_args={}', is_peti, edit_args)

    # Grab the currently mounted filesystems in P2.
    game = find_gameinfo(argv)
    root_folder = game.path.parent
    fsys = game.get_filesystem()

    # Special case - move the BEE2 fsys FIRST, so we always pack files found
    # there.
    for child_sys in fsys.systems[:]:
        if 'bee2' in child_sys[0].path.casefold():
            fsys.systems.remove(child_sys)
            fsys.systems.insert(0, child_sys)

    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data)

    # Mount the existing packfile, so the cubemap files are recognised.
    fsys.add_sys(ZipFileSystem('<BSP pakfile>', zipfile))

    fsys.open_ref()

    LOGGER.info('Done!')

    LOGGER.debug('Filesystems:')
    for child_sys in fsys.systems[:]:
        LOGGER.debug('- {}: {!r}', child_sys[1], child_sys[0])

    LOGGER.info('Reading our FGD files...')
    fgd = FGD.engine_dbase()

    packlist = PackList(fsys)
    packlist.load_soundscript_manifest(
        str(root_folder / 'bin/bee2/sndscript_cache.vdf')
    )

    load_transforms()

    # We need to add all soundscripts in scripts/bee2_snd/
    # This way we can pack those, if required.
    for soundscript in fsys.walk_folder('scripts/bee2_snd/'):
        if soundscript.path.endswith('.txt'):
            packlist.load_soundscript(soundscript, always_include=False)

    if is_peti:
        LOGGER.info('Checking for music:')
        music.generate(bsp_file.ents, packlist)

    LOGGER.info('Run transformations...')
    run_transformations(bsp_file.ents, fsys, packlist, bsp_file, game)

    LOGGER.info('Scanning map for files to pack:')
    packlist.pack_from_bsp(bsp_file)
    packlist.pack_fgd(bsp_file.ents, fgd)
    packlist.eval_dependencies()
    LOGGER.info('Done!')

    packlist.write_manifest()

    # We need to disallow Valve folders.
    pack_whitelist = set()  # type: Set[FileSystem]
    pack_blacklist = set()  # type: Set[FileSystem]
    if is_peti:
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

    if '-no_pack' not in args:
        # Cubemap files packed into the map already.
        existing = set(bsp_file.pakfile.namelist())

        LOGGER.info('Writing to BSP...')
        packlist.pack_into_zip(
            bsp_file,
            ignore_vpk=True,
            whitelist=pack_whitelist,
            blacklist=pack_blacklist,
        )

        LOGGER.info('Packed files:\n{}', '\n'.join(
            set(bsp_file.pakfile.namelist()) - existing
        ))

    if config.get_bool('General', 'packfile_dump_enable'):
        dump_files(bsp_file, config.get_val(
            'General',
            'packfile_dump_dir',
            '../dump/'
        ))

    LOGGER.info('Writing BSP...')
    bsp_file.save()
    LOGGER.info(' - BSP written!')

    if is_peti:
        screenshot.modify(config, game.path)

    if edit_args:
        LOGGER.info("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    else:
        if is_peti:
            LOGGER.info("Publishing - Full lighting enabled! (or forced to do so)")
        else:
            LOGGER.info("Hammer map detected! Not forcing cheap lighting..")
        run_vrad(full_args)

    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    main(sys.argv)
