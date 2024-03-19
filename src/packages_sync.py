"""Utility for syncing changes in Portal 2 and in unzipped packages.

First, set the PORTAL_2_LOC environment variable to the Portal 2 location.
Then drag and drop folders or files onto this application. If files are in a
package folder, they will be copied to Portal 2. If in Portal 2's directories,
they will be copied to any packages with those resources.

The destination will be 'Portal 2/bee2_dev/' if that exists, or 'Portal 2/bee2/'
otherwise.
"""
import utils
import srctools.logger

utils.fix_cur_directory()
# Don't write to a log file, users of this should be able to handle a command
# prompt.
LOGGER = srctools.logger.init_logging(main_logger=__name__)

import os
import sys
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from srctools import AtomicWriter
from srctools.filesys import RawFileSystem
import trio

from BEE2_config import GEN_OPTS, get_package_locs
from packages import (
    get_loaded_packages, find_packages,
    LOGGER as packages_logger
)
from app.errors import ErrorUI, console_handler
import utils

# If true, user said * for packages - use last for all.
PACKAGE_REPEAT: Optional[RawFileSystem] = None
SKIPPED_FILES: List[str] = []
CONF = utils.conf_location('last_package_sync.txt')


class SkipPackage(Exception):
    """Raised to skip a package."""


def get_package(file: Path) -> RawFileSystem:
    """Get the package desired for a file."""
    global PACKAGE_REPEAT
    try:
        with CONF.open() as f:
            last_package = utils.parse_obj_id(f.read().strip())
    except FileNotFoundError:
        last_package = None

    if last_package:
        if PACKAGE_REPEAT is not None:
            return PACKAGE_REPEAT

        message = f'Choose package ID for "{file}", blank to assume {last_package}, * to repeat last for all, or X to skip: '
    else:
        message = f'Choose package ID for "{file}", or X to skip: '

    error_message = 'Invalid package!\n' + message

    while True:
        pack_id = input(message)

        # After first time, always use the 'invalid package' warning.
        message = error_message

        if pack_id == 'X':
            raise SkipPackage

        if pack_id == '*' and last_package:
            try:
                fsys = get_loaded_packages().packages[last_package].fsys
            except KeyError:
                continue
            if isinstance(fsys, RawFileSystem):
                PACKAGE_REPEAT = fsys
                return PACKAGE_REPEAT
            else:
                print('Packages must be folders, not zips!')
        elif not pack_id and last_package:
            pack_id = last_package

        try:
            fsys = get_loaded_packages().packages[utils.parse_obj_id(pack_id)].fsys
        except KeyError:
            continue
        if isinstance(fsys, RawFileSystem):
            with AtomicWriter(CONF) as f:
                f.write(pack_id + '\n')
            return fsys
        else:
            print('Packages must be folders, not zips!')


def check_file(file: Path, portal2: Path, packages: Path) -> None:
    """Check for the location this file is in, and copy it to the other place."""
    try:
        relative = file.relative_to(portal2)
    except ValueError:
        # Not in Portal 2, in the packages.
        # Find the first 'resources/' folder, and copy to Portal 2.
        try:
            relative = file.relative_to(packages)
        except ValueError:
            # Not in either.
            LOGGER.warning('File "{!s}" not in packages or Portal 2!', file)
            return
        part = relative.parts
        try:
            res_path = Path(*part[part.index('resources')+1:])
        except ValueError:
            LOGGER.warning('File "{!s} not a resource!', file)
            return

        if res_path.parts[0] == 'instances':
            dest = (
                portal2 /
                'sdk_content/maps/instances/bee2' /
                res_path.relative_to('instances')
            )
        elif res_path.parts[0] == 'bee2':
            LOGGER.warning('File "{!s}" not for copying!', file)
            return
        else:
            if (portal2 / 'bee2_dev').exists():
                dest = portal2 / 'bee2_dev' / res_path
            else:
                dest = portal2 / 'bee2' / res_path
        LOGGER.info('"{}" -> "{}"', file, dest)
        os.makedirs(str(dest.parent), exist_ok=True)
        shutil.copy(str(file), str(dest))
    else:
        # In Portal 2, copy to each matching package.
        try:
            rel_loc = Path('resources', 'instances') / relative.relative_to(
                'sdk_content/maps/instances/bee2'
            )
        except ValueError:
            rel_loc = Path('resources') / relative.relative_to(
                'bee2_dev' if (portal2 / 'bee2_dev').exists() else 'bee2'
            )

        target_systems = []

        for package in get_loaded_packages().packages.values():
            if not isinstance(package.fsys, RawFileSystem):
                # In a zip or the like.
                continue
            if str(rel_loc) in package.fsys:
                target_systems.append(package.fsys)

        if not target_systems:
            # This file is totally new.
            try:
                target_systems.append(get_package(rel_loc))
            except SkipPackage:
                return

        for fsys in target_systems:
            full_loc = fsys.path / rel_loc
            LOGGER.info('"{}" -> "{}"', file, full_loc)
            os.makedirs(str(full_loc.parent), exist_ok=True)
            shutil.copy(str(file), str(full_loc))


def print_package_ids() -> None:
    """Print all the packages out."""
    packages = get_loaded_packages().packages.values()
    id_len = max(len(pack.id) for pack in packages)
    row_count = 128 // (id_len + 2)
    for i, pack in enumerate(sorted(pack.id for pack in packages), start=1):
        print(' {0:<{1}} '.format(pack, id_len), end='')
        if i % row_count == 0:
            print()
    print()


async def main(files: List[str]) -> int:
    """Run the transfer."""
    if not files:
        LOGGER.error('No files to copy!')
        LOGGER.error('packages_sync: {}', __doc__)
        return 1

    try:
        portal2_loc = Path(os.environ['PORTAL_2_LOC'])
    except KeyError:
        raise ValueError(
            'Environment Variable $PORTAL_2_LOC not set! '
            'This should be set to Portal 2\'s directory.'
        ) from None

    # Load the general options in to find out where packages are.
    GEN_OPTS.load()

    # Borrow PackageLoader to do the finding and loading for us.
    LOGGER.info('Locating packages...')

    # Disable logging of package info.
    packages_logger.setLevel(logging.ERROR)
    with ErrorUI.install_handler(console_handler):
        async with ErrorUI() as errors, trio.open_nursery() as nursery:
            for loc in get_package_locs():
                nursery.start_soon(
                    find_packages,
                    errors,
                    get_loaded_packages(),
                    loc,
                )
    packages_logger.setLevel(logging.INFO)

    LOGGER.info('Done!')

    print_package_ids()

    package_loc = Path('../', GEN_OPTS['Directories']['package']).resolve()

    file_list: List[Path] = []

    for file in files:
        file_path = Path(file)
        if file_path.is_dir():
            for sub_file in file_path.glob('**/*'):
                if sub_file.is_file():
                    file_list.append(sub_file)
        else:
            file_list.append(file_path)

    files_to_check = set()

    for file_path in file_list:
        if file_path.suffix.casefold() in {'.vmx', '.log', '.bsp', '.prt', '.lin'}:
            # Ignore these file types.
            continue
        files_to_check.add(file_path)
        if file_path.suffix == '.mdl':
            for suffix in ['.vvd', '.phy', '.dx90.vtx', '.sw.vtx']:
                sub_file = file_path.with_suffix(suffix)
                if sub_file.exists():
                    files_to_check.add(sub_file)

    LOGGER.info('Processing {} files...', len(files_to_check))

    for file_path in files_to_check:
        check_file(file_path, portal2_loc, package_loc)

    if SKIPPED_FILES:
        LOGGER.warning('Skipped missing files:')
        for file in SKIPPED_FILES:
            LOGGER.info('- {}', file)

    return 0


if __name__ == '__main__':
    LOGGER.info('BEE{} packages syncer, args={}', utils.BEE_VERSION, sys.argv[1:])
    sys.exit(trio.run(main, sys.argv[1:]))
