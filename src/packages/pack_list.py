import os
from typing import List

import srctools
from packages import (
    PakObject, ParseData, LOGGER, CHECK_PACKFILE_CORRECTNESS,
    ExportData,
)
from srctools import Property


class PackList(PakObject, allow_mult=True):
    """Specifies a group of resources which can be packed together."""
    def __init__(self, pak_id: str, files: List[str]) -> None:
        self.id = pak_id
        self.files = files

    @classmethod
    def parse(cls, data: ParseData) -> 'PackList':
        """Read pack lists from packages."""
        filesystem = data.fsys
        conf = data.info.find_key('Config', '')

        if 'AddIfMat' in data.info:
            LOGGER.warning(
                '{}:{}: AddIfMat is no '
                'longer used.',
                data.pak_id,
                data.id,
            )

        files = []

        if conf.has_children():
            # Allow having a child block to define packlists inline
            files = [
                prop.value
                for prop in conf
            ]
        elif conf.value:
            path = 'pack/' + conf.value + '.cfg'
            with filesystem, filesystem.open_str(path) as f:
                # Each line is a file to pack.
                # Skip blank lines, strip whitespace, and
                # allow // comments.
                for line in f:
                    line = srctools.clean_line(line)
                    if line:
                        files.append(line)

        # Deprecated old option.
        for prop in data.info.find_all('AddIfMat'):
            files.append('materials/' + prop.value + '.vmt')

        if not files:
            raise ValueError('"{}" has no files to pack!'.format(data.id))

        if CHECK_PACKFILE_CORRECTNESS:
            # Use normpath so sep differences are ignored, plus case.
            resources = {
                os.path.normpath(file.path).casefold()
                for file in
                filesystem.walk_folder('resources/')
            }
            for file in files:
                if file.startswith(('-#', 'precache_sound:')):
                    # Used to disable stock soundscripts, and precache sounds
                    # Not to pack - ignore.
                    continue

                file = file.lstrip('#')  # This means to put in soundscript too...

                #  Check to make sure the files exist...
                file = os.path.join('resources', os.path.normpath(file)).casefold()
                if file not in resources:
                    LOGGER.warning(
                        'Warning: "{file}" not in zip! ({pak_id})',
                        file=file,
                        pak_id=data.pak_id,
                    )

        return cls(data.id, files)

    def add_over(self, override: 'PackList') -> None:
        """Override items just append to the list of files."""
        # Don't copy over if it's already present
        for item in override.files:
            if item not in self.files:
                self.files.append(item)

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export all the packlists."""

        pack_block = Property('PackList', [])

        for pack in PackList.all():  # type: PackList
            # Build a
            # "Pack_id"
            # {
            # "File" "filename"
            # "File" "filename"
            # }
            # block for each packlist
            files = [
                Property('File', file)
                for file in
                pack.files
            ]
            pack_block.append(Property(
                pack.id,
                files,
            ))

        LOGGER.info('Writing packing list!')
        with open(exp_data.game.abs_path('bin/bee2/pack_list.cfg'), 'w') as pack_file:
            for line in pack_block.export():
                pack_file.write(line)