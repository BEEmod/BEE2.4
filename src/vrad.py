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
from io import BytesIO
from zipfile import ZipFile
from typing import List, Set

import srctools.run
from srctools import Property
from srctools.bsp import BSP, BSP_LUMPS
from srctools.filesys import (
    RawFileSystem, VPKFileSystem, ZipFileSystem,
    FileSystem,
)
from srctools.packlist import PackList, load_fgd
from srctools.game import find_gameinfo
from srctools.bsp_transform import run_transformations

from postcomp import (
    music,
    screenshot,
    coop_responses,
    filter,
)


def dump_files(bsp: BSP, dump_folder: str) -> None:
    """Dump packed files to a location.
    """
    if not dump_folder:
        return

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

    with bsp.packfile() as zipfile:
        for zipinfo in zipfile.infolist():
            zipfile.extract(zipinfo, dump_folder)


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
    try:
        with open("bee2/vrad_config.cfg", encoding='utf8') as config:
            conf = Property.parse(config, 'bee2/vrad_config.cfg').find_key(
                'Config', []
            )
    except FileNotFoundError:
        conf = Property('Config', [])
    else:
        LOGGER.info('Config Loaded!')

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

    bsp_ents = bsp_file.read_ent_data()

    # If VBSP thinks it's hammer, trust it.
    if conf.bool('is_hammer', False):
        is_peti = edit_args = False
    else:
        is_peti = True
        # Detect preview via knowing the bsp name. If we are in preview,
        # check the config file to see what was specified there.
        if os.path.basename(path) == "preview.bsp":
            edit_args = not conf.bool('force_full', False)
        else:
            # publishing - always force full lighting.
            edit_args = False

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

    # Put the Mel and Tag filesystems in so we can pack from there.
    fsys_tag = fsys_mel = None
    if is_peti and 'mel_vpk' in conf:
        fsys_mel = VPKFileSystem(conf['mel_vpk'])
        fsys.add_sys(fsys_mel)
    if is_peti and 'tag_dir' in conf:
        fsys_tag = RawFileSystem(conf['tag_dir'])
        fsys.add_sys(fsys_tag)

    # Special case - move the BEE2 fsys FIRST, so we always pack files found
    # there.
    for child_sys in fsys.systems[:]:
        if 'bee2' in child_sys[0].path.casefold():
            fsys.systems.remove(child_sys)
            fsys.systems.insert(0, child_sys)

    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data, mode='a')

    # Mount the existing packfile, so the cubemap files are recognised.
    fsys.systems.append((ZipFileSystem('', zipfile), ''))

    fsys.open_ref()

    LOGGER.info('Done!')

    LOGGER.debug('Filesystems:')
    for child_sys in fsys.systems[:]:
        LOGGER.debug('- {}: {!r}', child_sys[1], child_sys[0])

    LOGGER.info('Reading our FGD files...')
    fgd = load_fgd()

    packlist = PackList(fsys)
    packlist.load_soundscript_manifest(
        str(root_folder / 'bin/bee2/sndscript_cache.vdf')
    )

    # We need to add all soundscripts in scripts/bee2_snd/
    # This way we can pack those, if required.
    for soundscript in fsys.walk_folder('scripts/bee2_snd/'):
        if soundscript.path.endswith('.txt'):
            packlist.load_soundscript(soundscript, always_include=False)

    if is_peti:
        LOGGER.info('Checking for music:')
        music.generate(bsp_ents, packlist)

        for prop in conf.find_children('InjectFiles'):
            filename = os.path.join('bee2', 'inject', prop.real_name)
            try:
                with open(filename, 'rb') as f:
                    LOGGER.info('Injecting "{}" into packfile.', prop.value)
                    packlist.pack_file(prop.value, data=f.read())
            except FileNotFoundError:
                pass

    LOGGER.info('Run transformations...')
    run_transformations(bsp_ents, fsys, packlist, bsp_file, game)

    LOGGER.info('Scanning map for files to pack:')
    packlist.pack_from_bsp(bsp_file)
    packlist.pack_fgd(bsp_ents, fgd)
    packlist.eval_dependencies()
    LOGGER.info('Done!')

    if is_peti:
        packlist.write_manifest()
    else:
        # Write with the map name, so it loads directly.
        packlist.write_manifest(os.path.basename(path)[:-4])

    # We need to disallow Valve folders.
    pack_whitelist = set()  # type: Set[FileSystem]
    pack_blacklist = set()  # type: Set[FileSystem]
    if is_peti:
        if fsys_mel is not None:
            pack_whitelist.add(fsys_mel)
        if fsys_tag is not None:
            pack_whitelist.add(fsys_tag)
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
        with bsp_file.packfile() as zipfile:
            existing = set(zipfile.namelist())

        LOGGER.info('Writing to BSP...')
        packlist.pack_into_zip(
            bsp_file,
            ignore_vpk=True,
            whitelist=pack_whitelist,
            blacklist=pack_blacklist,
        )

        with bsp_file.packfile() as zipfile:
            LOGGER.info('Packed files:\n{}', '\n'.join(
                set(zipfile.namelist()) - existing
            ))

    dump_files(bsp_file, conf['packfile_dump', ''])

    # Copy new entity data.
    bsp_file.lumps[BSP_LUMPS.ENTITIES].data = BSP.write_ent_data(bsp_ents)

    bsp_file.save()
    LOGGER.info(' - BSP written!')

    if is_peti:
        screenshot.modify(conf)

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
