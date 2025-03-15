import os

import trio
from srctools import AtomicWriter

from . import ExportData, STEPS
from packages.editor_sound import EditorSound


# We inject this line to recognise where our sounds start, so we can modify them.
EDITOR_SOUND_LINE = '// BEE2 SOUNDS BELOW'


@STEPS.add_step(prereq=[], results=[])
async def step_add_editor_sounds(exp_data: ExportData) -> None:
    """Add soundscript items so that they can be used in the editor."""
    sounds = exp_data.packset.all_obj(EditorSound)
    game = exp_data.game
    # PeTI only loads game_sounds_editor, so we must modify that.
    # First find the highest-priority file
    for folder in game.dlc_priority():
        file = trio.Path(game.abs_path(os.path.join(
            folder,
            'scripts',
            'game_sounds_editor.txt'
        )))
        if await file.exists():
            break  # We found it
    else:
        # Assume it's in dlc2
        file = trio.Path(game.abs_path(os.path.join(
            'portal2_dlc2',
            'scripts',
            'game_sounds_editor.txt',
        )))
    try:
        file_data = (await file.read_text('utf8')).splitlines(keepends=True)
    except FileNotFoundError:
        # If the file doesn't exist, we'll just write our stuff in.
        file_data = []
    for i, line in enumerate(file_data):
        if line.strip() == EDITOR_SOUND_LINE:
            # Delete our marker line and everything after it
            del file_data[i:]
            break

    # Then add our stuff!
    with AtomicWriter(file, encoding='utf8') as f:
        await trio.to_thread.run_sync(f.writelines, file_data)
        f.write(EDITOR_SOUND_LINE + '\n')
        for sound in sounds:
            sound.data.serialise(f)
            f.write('\n')  # Add a little spacing
