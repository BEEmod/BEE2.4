from packages import PakObject, ParseData, ExportData
from srctools import Property


class EditorSound(PakObject):
    """Add sounds that are usable in the editor.

    The editor only reads in game_sounds_editor, so custom sounds must be
    added here.
    The ID is the name of the sound, prefixed with 'BEE2_Editor.'.
    The values in 'keys' will form the soundscript body.
    """
    def __init__(self, snd_name: str, data: Property) -> None:
        self.id = 'BEE2_Editor.' + snd_name
        self.data = data
        data.name = self.id

    @classmethod
    def parse(cls, data: ParseData) -> 'EditorSound':
        """Parse editor sounds from the package."""
        return cls(
            snd_name=data.id,
            data=data.info.find_key('keys', [])
        )

    @staticmethod
    def export(exp_data: ExportData):
        """Export EditorSound objects."""
        # Just command the game to do the writing.
        exp_data.game.add_editor_sounds(
            EditorSound.all()
        )