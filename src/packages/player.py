"""Objects defining which player models are available."""
from typing import Self
from collections.abc import Iterator

import trio.lowlevel

from packages import PakObject, ParseData
from quote_pack import LineCriteria, PLAYER_CRITERIA
from transtoken import TransToken, TransTokenSource
import utils


class PlayerModel(PakObject):
    """Specifies a possible player."""
    id: utils.ObjectID
    name: TransToken
    model: str
    pgun_skin: int

    voice_options: dict[LineCriteria, bool]

    def __init__(
        self,
        player_id: utils.ObjectID,
        model: str,
        name: TransToken,
        pgun_skin: int,
        voice_options: dict[LineCriteria, bool],
    ) -> None:
        self.id = player_id
        self.model = model
        self.name = name
        self.pgun_skin = pgun_skin
        self.voice_options = voice_options
        for criteria in PLAYER_CRITERIA:
            voice_options.setdefault(criteria, False)

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        await trio.lowlevel.checkpoint()
        model = data.info['model']
        pgun_skin = data.info.int('gunskin')
        name = TransToken.parse(data.pak_id, data.info['name'])

        voice_block = data.info.find_block('voice', or_blank=True)
        voice_options = {
            criteria: voice_block.bool(criteria.name)
            for criteria in PLAYER_CRITERIA
        }
        return cls(utils.obj_id(data.id), model, name, pgun_skin, voice_options)

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        yield self.name
