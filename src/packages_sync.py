"""Utility for syncing changes in Portal 2 and in unzipped packages.

First, set the PORTAL_2_LOC environment variable to the Portal 2 location.
Then drag and drop folders or files onto this application. If files are in a
package folder, they will be copied to Portal 2. If in Portal 2's directories,
they will be copied to any packages with those resources.

The destination will be 'Portal 2/bee2_dev/' if that exists, or 'Portal 2/bee2/'
otherwise.
"""

import utils
from srctools.filesys import RawFileSystem


utils.fix_cur_directory()
LOGGER = utils.init_logging(
    '../logs/packages_sync.log',
    __name__,
)
# This is needed to allow us to import things properly.
utils.setup_localisations(LOGGER)

import os
import sys
from pathlib import Path
from typing import List

import shutil

from BEE2_config import GEN_OPTS
from packageLoader import (
    PACKAGE_SYS,
    packages as PACKAGES,
    Package,
    find_packages
)


def check_file(file: Path, portal2: Path, packages: Path):
    """Check for the location this file is in, and copy it to the other place."""

    if file.suffix in ('vmx', 'log', 'bsp', 'prt', 'lin'):
        # Ignore these file types.
        return

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
        except IndexError:
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
            rel_loc = 'resources/instances' / relative.relative_to(
                'sdk_content/maps/instances/bee2'
            )
        except ValueError:
            rel_loc = 'resources/' / relative.relative_to(
                'bee2_dev' if (portal2 / 'bee2_dev').exists() else 'bee2'
            )

        for package in PACKAGES.values():
            if not isinstance(package.fsys, RawFileSystem):
                # In a zip or the like.
                continue
            if str(rel_loc) in package.fsys:
                full_loc = package.fsys.path / rel_loc
                LOGGER.info('"{}" -> "{}"', file, full_loc)
                os.makedirs(str(full_loc.parent), exist_ok=True)
                shutil.copy(str(file), str(full_loc))


def main(files: List[str]):
    """Run the transfer."""
    if not files:
        LOGGER.error('No files to copy!')
        LOGGER.error('packages_sync: {}', __doc__)
        return 1

    try:
        portal2_loc = Path(os.environ['PORTAL_2_LOC'])
    except KeyError:
        LOGGER.error(
            'Environment Variable $PORTAL_2_LOC not set! '
            'This should be set to Portal 2\'s directory.'
        )

    # Load the general options in to find out where packages are.
    GEN_OPTS.load()

    # Borrow PackageLoader to do the finding and loading for us.
    LOGGER.info('Locating packages...')
    find_packages(GEN_OPTS['Directories']['package'])

    package_loc = Path('../', GEN_OPTS['Directories']['package']).resolve()

    for file in files:
        file_path = Path(file)
        if file_path.is_dir():
            for sub_file in file_path.glob('**/*'):  # type: Path
                if sub_file.is_file():
                    check_file(sub_file, portal2_loc, package_loc)
        else:
            check_file(file_path, portal2_loc, package_loc)


if __name__ == '__main__':
    LOGGER.info('BEE{} packages syncer, args=', utils.BEE_VERSION, sys.argv[1:])
    sys.exit(main(sys.argv[1:]))
