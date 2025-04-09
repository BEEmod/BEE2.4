"""Implements a dynamic item allowing placing the various test chamber signages."""
from __future__ import annotations
from typing import Final, Self

from collections.abc import Sequence

import attrs
import srctools.logger
import trio
from srctools import Keyvalues, NoKeyError

from app.img import Handle as ImgHandle
from packages import ExportKey, Item, PakObject, PakRef, ParseData, Style
import utils


__all__ = [
    'LEGEND_SIZE', 'CELL_SIGN_SIZE', 'CELL_ANT_SIZE',
    'ITEM_ID', 'Signage', 'SignageLegend', 'SignStyle',
]
LOGGER = srctools.logger.get_logger(__name__)
# Sizes for the generated legend textures.
LEGEND_SIZE: Final = (512, 1024)
CELL_SIGN_SIZE: Final = 102
CELL_ANT_SIZE: Final = 128
# The signage item, used to trigger adding the "Configure Signage" button to its UI.
ITEM_ID: Final = PakRef(Item, utils.obj_id('ITEM_BEE2_SIGNAGE'))


@attrs.frozen
class SignStyle:
    """Signage information for a specific style."""
    world: str
    overlay: str
    icon: ImgHandle
    type: str


@attrs.frozen(kw_only=True)
class LegendInfo:
    """Image resources used to construct one of the two legend textures.

    The background texture if specified is added to the upper-left of the image.
    It is useful to provide a backing, or to fill in unset signages.
    If provided, the blank image is inserted instead of unset signage.

    The overlay is composited on top, to allow setting the unwrapped
    model parts.
    Lastly, the numbers image is used as a spritesheet to add numbers to the sign.
    """
    overlay: ImgHandle | None
    background: ImgHandle | None
    blank: ImgHandle | None
    numbers: ImgHandle | None
    num_off: tuple[int, int]

    @staticmethod
    def _get_img(
        kv: Keyvalues, pak_id: utils.ObjectID, name: str,
        width: int, height: int,
    ) -> ImgHandle | None:
        """Fetch an image."""
        try:
            subkey = kv.find_key(name)
        except NoKeyError:
            return None
        else:
            return ImgHandle.parse(subkey, pak_id, width, height)

    @classmethod
    def parse(cls, kv: Keyvalues, pak_id: utils.ObjectID, cell_size: int) -> Self:
        """Parse from KV data."""
        try:
            numbers_kv = kv.find_key('numbers')
        except NoKeyError:
            numbers = None
            num_off = (0, 0)
        else:
            numbers = ImgHandle.parse(numbers_kv, pak_id, 0, 0)
            num_off = kv.int('num_left'), kv.int('num_bottom')

        return cls(
            overlay=cls._get_img(kv, pak_id, 'overlay', *LEGEND_SIZE),
            background=cls._get_img(kv, pak_id, 'background', 0, 0),
            blank=cls._get_img(kv, pak_id, 'blank', cell_size, cell_size),
            numbers=numbers, num_off=num_off,
        )


LEGEND_INFO_BLANK = LegendInfo(
    overlay=None, background=None, blank=None,
    numbers=None, num_off=(0, 0)
)


class SignageLegend(PakObject):
    """Allows specifying image resources used to construct the legend texture.

    'symbol' is for the standard item, 'connection' is for the antline variant.
    """
    def __init__(
        self,
        sty_id: str,
        symbol_conf: LegendInfo,
        antline_conf: LegendInfo,
    ) -> None:
        self.id = sty_id
        self.symbol_conf = symbol_conf
        self.antline_conf = antline_conf

    @classmethod
    async def parse(cls, data: ParseData) -> SignageLegend:
        """Parse a signage legend."""
        await trio.lowlevel.checkpoint()
        try:
            sym_kv = data.info.find_key('symbol')
        except NoKeyError:
            symbol_conf = LegendInfo.parse(data.info, data.pak_id, CELL_SIGN_SIZE)
        else:
            symbol_conf = LegendInfo.parse(sym_kv, data.pak_id, CELL_SIGN_SIZE)

        try:
            ant_kv = data.info.find_key('antline')
        except NoKeyError:
            antline_conf = LEGEND_INFO_BLANK
        else:
            antline_conf = LegendInfo.parse(ant_kv, data.pak_id, CELL_ANT_SIZE)

        return cls(data.id, symbol_conf, antline_conf)


class Signage(PakObject, allow_mult=True, needs_foreground=True):
    """Defines different square signage overlays."""
    type ExportInfo = Sequence[tuple[str, utils.ObjectID]]
    export_info: Final[ExportKey[ExportInfo]] = ExportKey()

    def __init__(
        self,
        sign_id: str,
        styles: dict[PakRef[Style], SignStyle],
        disp_name: str,
        primary_id: str | None = None,
        secondary_id: str | None = None,
        hidden: bool = False,
    ) -> None:
        self.hidden = hidden or sign_id == 'SIGN_ARROW'
        self.id = sign_id
        self.name = disp_name
        # style_id -> (world, overlay)
        self.styles = styles
        self.prim_id = primary_id
        self.sec_id = secondary_id

        # The icon the UI uses.
        self.icon: ImgHandle | None = None

    @classmethod
    async def parse(cls, data: ParseData) -> Signage:
        await trio.lowlevel.checkpoint()
        styles: dict[PakRef[Style], SignStyle] = {}
        for prop in data.info.find_children('styles'):
            sty_id = PakRef.parse(Style, prop.real_name)

            if not prop.has_children():
                # Style lookup.
                try:
                    prop = next(data.info.find_all('styles', prop.value))
                except StopIteration:
                    raise ValueError(f'No style <{prop.value}>!') from None

            world_tex = prop['world', '']
            overlay_tex = prop['overlay', '']

            # Don't warn, we don't actually need this yet.

            # if not world_tex:
            #     LOGGER.warning(
            #         '"{}" signage has no "world" value '
            #         'for the "{}" style!',
            #         data.id,
            #         sty_id
            #     )
            if not overlay_tex:
                raise ValueError(
                    f'"{data.id}"" signage has no "overlay" value '
                    f'option for the "{sty_id}" style!'
                )

            if 'icon' in prop:
                img = ImgHandle.parse(prop, data.pak_id, 64, 64, subkey='icon')
            else:
                # Use the overlay texture.
                overlay_path = overlay_tex
                if not overlay_path.casefold().endswith('.vtf'):
                    overlay_path += '.vtf'
                # Strip alpha, that's usually used for selfillum.
                img = ImgHandle.file(
                    utils.PackagePath(data.pak_id, overlay_path),
                    64, 64,
                ).with_alpha_stripped()

            styles[sty_id] = SignStyle(
                world_tex,
                overlay_tex,
                img,
                prop['type', 'square']
            )
        return cls(
            data.id,
            styles,
            data.info['name'],
            data.info['primary', None],
            data.info['secondary', None],
            data.info.bool('hidden'),
        )

    def add_over(self, override: Signage) -> None:
        """Append additional styles to the signage."""
        for sty_id, opts in override.styles.items():
            if sty_id in self.styles:
                raise ValueError(
                    f'Duplicate "{sty_id}" style definition for {self.id}!'
                )
            self.styles[sty_id] = opts
        if override.sec_id:
            if not self.sec_id:
                self.sec_id = override.sec_id
            elif self.sec_id != override.sec_id:
                raise ValueError(
                    'Mismatch in secondary IDs for '
                    f'signage "{self.id}"! '
                    f'({self.sec_id} != {override.sec_id})'
                )
