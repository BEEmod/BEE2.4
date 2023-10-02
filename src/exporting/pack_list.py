"""Export the deprecated packlist system."""
from typing import Dict, Optional

import srctools
import trio
from srctools import Keyvalues

from exporting import STEPS, StepResource
from packages import ExportData, PackList


@STEPS.add_step(prereq=[], results=[])
async def step_packlist_conf(exp_data: ExportData) -> None:
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

    async with await trio.open_file(
        exp_data.game.abs_path('bin/bee2/pack_list.cfg'),
        'w',
    ) as pack_file:
        for line in pack_block.export():
            await pack_file.write(line)
