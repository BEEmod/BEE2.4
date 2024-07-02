"""Definitions for elevator videos.

We can't pack BIKs, so this is mainly for Valve's existing ones.
"""
from typing import Iterator, Optional

from packages import PackagesSet, PakObject, ParseData, SelitemData, AttrMap
from transtoken import TransTokenSource
import utils


class Elevator(PakObject, needs_foreground=True, style_suggest_key='elev'):
    """An elevator video definition.

    This is mainly defined just for Valve's items - you can't pack BIKs.
    """
    def __init__(
        self,
        elev_id: str,
        selitem_data: SelitemData,
        video: str,
        vert_video: Optional[str] = None,
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

    @classmethod
    def get_selector_attrs(cls, packset: PackagesSet, elev_id: utils.SpecialID) -> AttrMap:
        """Return the attributes for the selector window."""
        if utils.not_special_id(elev_id):
            return {'ORIENT': packset.obj_by_id(cls, elev_id).has_orient}
        else:
            # None, no orientation
            return {}
