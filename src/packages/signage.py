"""Implements a dynamic item allowing placing the various test chamber signages."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Tuple, NamedTuple, Optional, TYPE_CHECKING

from PIL import Image
import utils
from packages import PakObject, ParseData, ExportData, Style
from app.img import Handle as ImgHandle
from srctools.vtf import ImageFormats, VTF
from srctools import Property
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)
if TYPE_CHECKING:
    from app import gameMan  # Prevent circular import


class SignStyle(NamedTuple):
    """Signage information for a specific style."""
    world: str
    overlay: str
    icon: ImgHandle
    type: str


class SignageLegend(PakObject):
    """Allows specifying image resources used to construct the legend texture."""

    def __init__(self, sty_id: str, blank: ImgHandle, overlay: ImgHandle) -> None:
        self.id = sty_id
        self.blank = blank
        self.overlay = overlay

    @classmethod
    def parse(cls, data: ParseData) -> 'SignageLegend':
        return SignageLegend(
            data.id,
            ImgHandle.parse(data.info, data.pak_id, 51, 51, subkey='blank'),
            ImgHandle.parse(data.info, data.pak_id, 256, 512, subkey='overlay'),
        )
    @staticmethod
    def export(exp_data: ExportData) -> None:
        """This is all performed in Signage."""


class Signage(PakObject, allow_mult=True):
    """Defines different square signage overlays."""

    def __init__(
        self,
        sign_id: str,
        styles: Dict[str, SignStyle],
        disp_name: str,
        primary_id: str=None,
        secondary_id: str=None,
        hidden: bool=False,
    ) -> None:
        self.hidden = hidden or sign_id == 'SIGN_ARROW'
        self.id = sign_id
        self.name = disp_name
        # style_id -> (world, overlay)
        self.styles = styles
        self.prim_id = primary_id
        self.sec_id = secondary_id

        # The icon the UI uses.
        self.dnd_icon = None

    @classmethod
    def parse(cls, data: ParseData) -> Signage:
        styles: Dict[str, SignStyle] = {}
        for prop in data.info.find_children('styles'):
            sty_id = prop.name.upper()

            if not prop.has_children():
                # Style lookup.
                try:
                    prop = next(data.info.find_all('styles', prop.value))
                except StopIteration:
                    raise ValueError('No style <{}>!'.format(prop.value))

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
                img = ImgHandle.file(utils.PackagePath(data.pak_id, overlay_path), 64, 64)

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
    def export(exp_data: ExportData) -> None:
        """Export the selected signage to the config, and produce the legend."""
        # Timer value -> sign ID.
        sel_ids: List[Tuple[str, str]] = exp_data.selected

        # Special case, arrow is never selectable.
        sel_ids.append(('arrow', 'SIGN_ARROW'))

        sel_icons: dict[int, ImgHandle] = {}

        conf = Property('Signage', [])

        for tim_id, sign_id in sel_ids:
            try:
                sign = Signage.by_id(sign_id)
            except KeyError:
                LOGGER.warning('Signage "{}" does not exist!', sign_id)
                continue
            prop_block = Property(str(tim_id), [])

            sty_sign = sign._serialise(prop_block, exp_data.selected_style)

            for sub_name, sub_id in [
                ('primary', sign.prim_id),
                ('secondary', sign.sec_id),
            ]:
                if sub_id:
                    try:
                        sub_sign = Signage.by_id(sub_id)
                    except KeyError:
                        LOGGER.warning(
                            'Signage "{}"\'s {} "{}" '
                            'does not exist!', sign_id, sub_name, sub_id)
                    else:
                        sub_block = Property(sub_name, [])
                        sub_sign._serialise(sub_block, exp_data.selected_style)
                        if sub_block:
                            prop_block.append(sub_block)

            if prop_block:
                conf.append(prop_block)

            # Valid timer number, store to be placed on the texture.
            if tim_id.isdigit() and sty_sign is not None:
                sel_icons[int(tim_id)] = sty_sign.icon

        exp_data.vbsp_conf.append(conf)
        build_texture(exp_data.game, exp_data.selected_style, sel_icons)

    def _serialise(self, parent: Property, style: Style) -> Optional[SignStyle]:
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
        parent.append(Property('world', data.world))
        parent.append(Property('overlay', data.overlay))
        parent.append(Property('type', data.type))
        return data


def build_texture(
    game: gameMan.Game,
    sel_style: Style,
    icons: Dict[int, ImgHandle],
) -> None:
    """Construct the legend texture for the signage."""
    legend = Image.new('RGBA', (256, 512), (0, 0, 0, 0))

    for style in sel_style.bases:
        try:
            legend_info = SignageLegend.by_id(style.id)
        except KeyError:
            pass
        else:
            blank = legend_info.blank.get_pil().convert('RGB')
            overlay = legend_info.overlay.get_pil()
            break
    else:
        LOGGER.warning('No Signage style overlay defined.')
        blank = Image.new('RGBA', (51, 51), (0, 0, 0, 0))
        overlay = None

    for i in range(28):
        y, x = divmod(i, 5)
        if y == 5:  # Last row is shifted over to center.
            x += 1
        try:
            ico = icons[i + 3].get_pil().resize((51, 51), Image.ANTIALIAS).convert('RGB')
        except KeyError:
            ico = blank
        legend.paste(ico, (x * 51, y * 51))

    if overlay is not None:
        legend = Image.alpha_composite(legend, overlay)

    vtf = VTF(256, 512, fmt=ImageFormats.DXT5)
    vtf.get().copy_from(legend.tobytes(), ImageFormats.RGBA8888)
    vtf.clear_mipmaps()
    vtf_loc = game.abs_path(
        'bee2/materials/BEE2/models/'
        'props_map_editor/signage/signage.vtf'
    )
    Path(vtf_loc).parent.mkdir(parents=True, exist_ok=True)
    with open(vtf_loc, 'wb') as f:
        LOGGER.info('Exporting "{}"...', vtf_loc)
        vtf.save(f)
