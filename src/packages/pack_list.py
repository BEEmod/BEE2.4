from typing import List

from srctools import Keyvalues
import srctools.logger

from packages import PakObject, ParseData, ExportData


LOGGER = srctools.logger.get_logger(__name__)


class PackList(PakObject, allow_mult=True):
    """Specifies a group of resources which can be packed together."""
    def __init__(self, pak_id: str, files: List[str]) -> None:
        self.id = pak_id
        self.files = files

    @classmethod
    async def parse(cls, data: ParseData) -> 'PackList':
        """Read pack lists from packages."""
        filesystem = data.fsys
        conf = data.info.find_key('Config', '')

        if 'AddIfMat' in data.info:
            LOGGER.warning(
                '{}:{}: AddIfMat is no longer used.',
                data.pak_id, data.id,
            )

        files = []

        if conf.has_children():
            # Allow having a child block to define packlists inline
            files = [
                prop.value
                for prop in conf
            ]
        elif conf.value:
            path = f'pack/{conf.value}.cfg'
            with filesystem.open_str(path) as f:
                # Each line is a file to pack.
                # Skip blank lines, strip whitespace, and
                # allow // comments.
                for line in f:
                    line = srctools.clean_line(line)
                    if line:
                        files.append(line)

        # Deprecated old option.
        for prop in data.info.find_all('AddIfMat'):
            files.append(f'materials/{prop.value}.vmt')

        if not files:
            raise ValueError(f'"{data.id}" has no files to pack!')

        return cls(data.id, files)

    def add_over(self, override: 'PackList') -> None:
        """Override items just append to the list of files."""
        # Don't copy over if it's already present
        for item in override.files:
            if item not in self.files:
                self.files.append(item)

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """Export all the packlists."""

        pack_block = Keyvalues('PackList', [])

        for pack in exp_data.packset.all_obj(PackList):
            # Build a
            # "Pack_id"
            # {
            # "File" "filename"
            # "File" "filename"
            # }
            # block for each packlist
            files = [
                Keyvalues('File', file)
                for file in
                pack.files
            ]
            pack_block.append(Keyvalues(
                pack.id,
                files,
            ))

        LOGGER.info('Writing packing list!')
        with open(exp_data.game.abs_path('bin/bee2/pack_list.cfg'), 'w') as pack_file:
            for line in pack_block.export():
                pack_file.write(line)
