"""Implements a dynamic item allowing placing the various test chamber signages."""
from __future__ import annotations
from typing import NamedTuple, Optional
from typing_extensions import Self

from io import BytesIO

from PIL import Image
from srctools.vtf import ImageFormats, VTF, VTFFlags
from srctools import Keyvalues
import srctools.logger

from packages import PackagesSet, PakObject, ParseData, ExportData, Style
from app.img import Handle as ImgHandle
import utils

LOGGER = srctools.logger.get_logger(__name__)
LEGEND_SIZE = (512, 1024)
CELL_SIZE = 102
SIGN_LOC = 'bee2/materials/BEE2/models/props_map_editor/signage/signage.vtf'


class SignStyle(NamedTuple):
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

    Finally the overlay is composited on top, to allow setting the unwrapped
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

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """This is all performed in Signage."""


class Signage(PakObject, allow_mult=True, needs_foreground=True):
    """Defines different square signage overlays."""
    def __init__(
        self,
        sign_id: str,
        styles: dict[str, SignStyle],
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
        styles: dict[str, SignStyle] = {}
        for prop in data.info.find_children('styles'):
            sty_id = prop.name.upper()

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

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """Export the selected signage to the config, and produce the legend."""
        # Timer value -> sign ID.
        sel_ids: list[tuple[str, str]] = exp_data.selected

        # Special case, arrow is never selectable.
        sel_ids.append(('arrow', 'SIGN_ARROW'))

        sel_icons: dict[int, ImgHandle] = {}

        conf = Keyvalues('Signage', [])

        for tim_id, sign_id in sel_ids:
            try:
                sign = exp_data.packset.obj_by_id(Signage, sign_id)
            except KeyError:
                LOGGER.warning('Signage "{}" does not exist!', sign_id)
                continue
            prop_block = Keyvalues(str(tim_id), [])

            sty_sign = sign._serialise(prop_block, exp_data.selected_style)

            for sub_name, sub_id in [
                ('primary', sign.prim_id),
                ('secondary', sign.sec_id),
            ]:
                if sub_id:
                    try:
                        sub_sign = exp_data.packset.obj_by_id(Signage, sub_id)
                    except KeyError:
                        LOGGER.warning(
                            'Signage "{}"\'s {} "{}" '
                            'does not exist!', sign_id, sub_name, sub_id)
                    else:
                        sub_block = Keyvalues(sub_name, [])
                        sub_sign._serialise(sub_block, exp_data.selected_style)
                        if sub_block:
                            prop_block.append(sub_block)

            if prop_block:
                conf.append(prop_block)

            # Valid timer number, store to be placed on the texture.
            if tim_id.isdigit() and sty_sign is not None:
                sel_icons[int(tim_id)] = sty_sign.icon

        exp_data.vbsp_conf.append(conf)
        exp_data.resources[SIGN_LOC] = build_texture(
            exp_data.packset, exp_data.selected_style, sel_icons,
        )

    def _serialise(self, parent: Keyvalues, style: Style) -> Optional[SignStyle]:
        """Write this sign's data for the style to the provided property."""
        for potential_style in style.bases:
            try:
                data = self.styles[potential_style.id.upper()]
                break
            except KeyError:
                pass
        else:
            LOGGER.warning(
                'No valid "{}" style for "{}" signage!',
                style.id,
                self.id,
            )
            try:
                data = self.styles['BEE2_CLEAN']
            except KeyError:
                return None
        parent.append(Keyvalues('world', data.world))
        parent.append(Keyvalues('overlay', data.overlay))
        parent.append(Keyvalues('type', data.type))
        return data


def build_texture(
    packset: PackagesSet,
    sel_style: Style,
    icons: dict[int, ImgHandle],
) -> bytes:
    """Construct the legend texture for the signage."""
    legend = Image.new('RGBA', LEGEND_SIZE, (0, 0, 0, 0))

    blank_img: Optional[Image.Image] = None
    for style in sel_style.bases:
        try:
            legend_info = packset.obj_by_id(SignageLegend, style.id)
        except KeyError:
            pass
        else:
            overlay = legend_info.overlay.get_pil()
            if legend_info.blank is not None:
                blank_img = legend_info.blank.get_pil().convert('RGB')
            if legend_info.background is not None:
                legend.paste(legend_info.background.get_pil(), (0, 0))
            break
    else:
        LOGGER.warning('No Signage style overlay defined.')
        overlay = None

    for i in range(28):
        y, x = divmod(i, 5)
        if y == 5:  # Last row is shifted over to center.
            x += 1
        try:
            ico = icons[i + 3].get_pil().resize((CELL_SIZE, CELL_SIZE), Image.Resampling.LANCZOS).convert('RGB')
        except KeyError:
            if blank_img is None:
                continue
            ico = blank_img
        legend.paste(ico, (x * CELL_SIZE, y * CELL_SIZE))

    if overlay is not None:
        legend = Image.alpha_composite(legend, overlay)

    vtf = VTF(*LEGEND_SIZE, fmt=ImageFormats.DXT5)
    vtf.get().copy_from(legend.tobytes(), ImageFormats.RGBA8888)
    vtf.clear_mipmaps()
    vtf.flags |= VTFFlags.ANISOTROPIC

    buf = BytesIO()
    try:
        vtf.save(buf)
    except NotImplementedError:
        LOGGER.warning('No DXT compressor, using BGRA8888.')
        # No libsquish, so DXT compression doesn't work.
        vtf.format = vtf.low_format = ImageFormats.BGRA4444

        buf = BytesIO()
        vtf.save(buf)

    return buf.getvalue()
