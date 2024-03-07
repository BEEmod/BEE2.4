"""Definitions for Glass/Grating holes.

These are separated from the item, because they vary not by style but based on the type of
barrier they're placed onto.
"""
from typing_extensions import Self

from packages import PakObject, ParseData, get_config
from app import lazy_conf


class BarrierHole(PakObject, allow_mult=True):
    """Definitions for Glass/Grating holes."""
    def __init__(
        self,
        hole_id: str,
        *,
        footprint_id: str,
        variant_conf: lazy_conf.LazyConf,
    ) -> None:
        self.id = hole_id
        self.footprint_id = footprint_id
        self.variant_conf = variant_conf

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse barrier holes from the package."""
        footprint_id = data.info['footprint']
        variant_conf = get_config(
            data.info,
            'items', data.pak_id,
            prop_name='variants',
            source=f'Barrier Hole <{data.id}>',
        )
        return cls(
            data.id,
            footprint_id=footprint_id,
            variant_conf=variant_conf,
        )

    def add_over(self, override: Self) -> None:
        """Merge together two hole definitions."""
        self.variant_conf = lazy_conf.concat(self.variant_conf, override.variant_conf)
