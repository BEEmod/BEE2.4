from __future__ import annotations
from collections.abc import Iterator

from srctools import Keyvalues

from transtoken import TransTokenSource
from packages import AttrMap, PackagesSet, PakObject, ParseData, SelitemData, get_config
from app import lazy_conf
import utils


class Skybox(
    PakObject,
    needs_foreground=True,
    style_suggest_key='skybox', suggest_default='SKY_BLACK',
):
    """Configures skybox and fog settings."""
    def __init__(
        self,
        sky_id: str,
        selitem_data: SelitemData,
        config: lazy_conf.LazyConf,
        fog_opts: Keyvalues,
        mat: str,
        draw_first: bool,
    ) -> None:
        self.id = sky_id
        self.selitem_data = selitem_data
        self.material = mat
        self.config = config
        self.fog_opts = fog_opts
        # Unset r_skybox_draw_last to fix issues with certain skyboxes.
        self.draw_first = draw_first

        # Extract this for selector windows to easily display
        self.fog_color = fog_opts.vec('primarycolor', 255, 255, 255)

    @classmethod
    async def parse(cls, data: ParseData) -> Skybox:
        """Parse a skybox definition."""
        selitem_data = SelitemData.parse(data.info, data.pak_id)
        mat = data.info['material', 'sky_black']
        draw_first = data.info.bool('sky_draw_first')
        config = get_config(
            data.info,
            'skybox',
            pak_id=data.pak_id,
            source=f'Skybox <{data.id}>',
        )

        fog_opts = data.info.find_key("Fog", or_blank=True)

        return cls(
            data.id,
            selitem_data,
            config,
            fog_opts,
            mat,
            draw_first,
        )

    def add_over(self, override: Skybox) -> None:
        """Add the additional vbsp_config commands to ourselves."""
        self.selitem_data += override.selitem_data
        self.config = lazy_conf.concat(self.config, override.config)
        self.fog_opts += override.fog_opts.copy()

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield translation tokens used by this skybox."""
        return self.selitem_data.iter_trans_tokens('skyboxes/' + self.id)

    def __repr__(self) -> str:
        return f'<Skybox {self.id}>'

    @classmethod
    def get_selector_attrs(cls, packset: PackagesSet, sky_id: utils.SpecialID) -> AttrMap:
        """Return the attributes for the selector window."""
        assert utils.not_special_id(sky_id), f'None is not valid for styles: {sky_id!r}'
        sky = packset.obj_by_id(cls, sky_id)
        return {
            # If this has a config, it is 3D.
            '3D': sky.config is not lazy_conf.BLANK,
            'COLOR': sky.fog_color,
        }
