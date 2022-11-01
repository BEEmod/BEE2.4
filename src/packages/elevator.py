"""Definitions for elevator videos.

We can't pack BIKs, so this is mainly for Valve's existing ones.
"""
from typing import Iterator

from srctools import Property

from packages import ParseData, ExportData, SelitemData, PakObject, Style, TransTokenSource


class Elevator(PakObject, needs_foreground=True):
    """An elevator video definition.

    This is mainly defined just for Valve's items - you can't pack BIKs.
    """
    def __init__(
        self,
        elev_id,
        selitem_data: SelitemData,
        video,
        vert_video=None,
    ) -> None:
        self.id = elev_id

        self.selitem_data = selitem_data

        if vert_video is None:
            self.has_orient = False
            self.horiz_video = video
            self.vert_video = video
        else:
            self.has_orient = True
            self.horiz_video = video
            self.vert_video = vert_video

    @classmethod
    async def parse(cls, data: ParseData) -> 'Elevator':
        """Read elevator videos from the package."""
        info = data.info
        selitem_data = SelitemData.parse(info, data.pak_id)

        if 'vert_video' in info:
            video = info['horiz_video']
            vert_video = info['vert_video']
        else:
            video = info['video']
            vert_video = None

        return cls(
            data.id,
            selitem_data,
            video,
            vert_video,
        )

    def __repr__(self) -> str:
        return f'<Elevator {self.id}>'

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield translation tokens present in the elevator."""
        return self.selitem_data.iter_trans_tokens('elevators/' + self.id)

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export the chosen video into the configs."""
        style: Style = exp_data.selected_style
        vbsp_config: Property = exp_data.vbsp_conf

        if exp_data.selected is None:
            elevator = None
        else:
            try:
                elevator = exp_data.packset.obj_by_id(Elevator, exp_data.selected)
            except KeyError:
                raise Exception(f"Selected elevator ({exp_data.selected}) doesn't exist?") from None

        if style.has_video:
            if elevator is None:
                # Use a randomised video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'RAND',
                )
            elif elevator.id == 'VALVE_BLUESCREEN':
                # This video gets a special script and handling
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'BSOD',
                )
            else:
                # Use the particular selected video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'FORCE',
                )
                vbsp_config.set_key(
                    ('Elevator', 'horiz'),
                    elevator.horiz_video,
                )
                vbsp_config.set_key(
                    ('Elevator', 'vert'),
                    elevator.vert_video,
                )
        else:  # No elevator video for this style
            vbsp_config.set_key(
                ('Elevator', 'type'),
                'NONE',
            )
