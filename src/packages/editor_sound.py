"""Adds sounds useable in the editor."""
from srctools import Keyvalues

from packages import PakObject, ParseData


class EditorSound(PakObject):
    """Add sounds that are usable in the editor.

    The editor only reads in game_sounds_editor, so custom sounds must be
    added here.
    The ID is the name of the sound, prefixed with 'BEE2_Editor.'.
    The values in 'keys' will form the soundscript body.
    """
    def __init__(self, snd_name: str, data: Keyvalues) -> None:
        self.id = snd_name
        self.data = data
        data.name = 'BEE2_Editor.' + self.id

    @classmethod
    async def parse(cls, data: ParseData) -> 'EditorSound':
        """Parse editor sounds from the package."""
        return cls(
            snd_name=data.id,
            data=data.info.find_key('keys', or_blank=True)
        )
