"""Objects defining which player models are available."""
from typing import Self
from collections.abc import Iterator

import trio.lowlevel

from config import Config
from packages import PackagesSet, PakObject, ParseData
from quote_pack import LineCriteria
from transtoken import TransToken, TransTokenSource
import utils

# Criteria the model can set.
CRITERIA = [
    LineCriteria.CHELL,
    LineCriteria.BENDY,
    LineCriteria.ATLAS,
    LineCriteria.PBODY,
    LineCriteria.HUMAN,
    LineCriteria.ROBOT,
]

LEGACY_IDS = {

}


class PlayerModel(PakObject):
    """Specifies a possible player."""
    id: utils.ObjectID
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
        for criteria in CRITERIA:
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
            for criteria in CRITERIA
        }
        return cls(utils.obj_id(data.id), model, name, pgun_skin, voice_options)

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        yield self.name

    @classmethod
    async def migrate_config(cls, packset: PackagesSet, conf: Config) -> Config:
        """Convert from old non-package-based definitions."""
        return conf
