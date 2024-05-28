"""Implements a dynamic item allowing placing the various test chamber signages."""
from __future__ import annotations
from typing import Optional, Final
from typing_extensions import Self

import attrs
import srctools.logger

from packages import PakObject, PakRef, ParseData, Style
from app.img import Handle as ImgHandle
import utils

__all__ = ['LEGEND_SIZE', 'CELL_SIZE', 'ITEM_ID', 'Signage', 'SignageLegend', 'SignStyle']
LOGGER = srctools.logger.get_logger(__name__)
LEGEND_SIZE: Final = (512, 1024)
CELL_SIZE: Final = 102
# The signage item, used to trigger adding the "Configure Signage" button to its UI.
ITEM_ID: Final = utils.obj_id('ITEM_BEE2_SIGNAGE')


@attrs.frozen
class SignStyle:
    """Signage information for a specific style."""
    world: str
    overlay: str
    icon: ImgHandle
    type: str


class SignageLegend(PakObject):
    """Allows specifying image resources used to construct the legend texture.

    The background texture if specified is added to the upper-left of the image.
    It is useful to provide a backing, or to fill in unset signages.
    If provided, the blank image is inserted instead of unset signage.

    Finally, the overlay is composited on top, to allow setting the unwrapped
    model parts.
    """
    def __init__(
        self,
        sty_id: str,
        overlay: ImgHandle,
        background: Optional[ImgHandle],
        blank: Optional[ImgHandle],
    ) -> None:
        self.id = sty_id
        self.overlay = overlay
        self.background = background
        self.blank = blank

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse a signage legend."""
        if 'blank' in data.info:
            blank = ImgHandle.parse(data.info, data.pak_id, CELL_SIZE, CELL_SIZE, subkey='blank')
        else:
            blank = None
        if 'background' in data.info:
            bg = ImgHandle.parse(data.info, data.pak_id, 0, 0, subkey='background')
        else:
            bg = None

        return cls(
            data.id,
            ImgHandle.parse(data.info, data.pak_id, *LEGEND_SIZE, subkey='overlay'),
            bg, blank,
        )


class Signage(PakObject, allow_mult=True, needs_foreground=True):
    """Defines different square signage overlays."""
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
