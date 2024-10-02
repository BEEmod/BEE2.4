"""Export signage configuration, and write the legend."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Final
from pathlib import Path

from PIL import Image
from srctools import Keyvalues
from srctools.vtf import VTF, ImageFormats, VTFFlags
import srctools.logger
import trio.to_thread

from app.img import Handle as ImgHandle
from packages import CLEAN_STYLE, PackagesSet, PakRef, Style
from packages.signage import (
    CELL_SIZE, LEGEND_SIZE, Signage, SignageLegend, SignStyle,
)
from transtoken import AppError, TransToken

from . import STEPS, ExportData, StepResource


LOGGER = srctools.logger.get_logger(__name__)
SIGN_LOC: Final = 'bee2/materials/bee2/models/props_map_editor/signage/signage.vtf'

TRANS_MISSING_SELECTED = TransToken.ui('Selected signage "{id}" does not exist.')
TRANS_MISSING_CHILD = TransToken.ui('Signage "{id}"\'s {child} "{sub_id}" does not exist.')


def serialise(sign: Signage, parent: Keyvalues, style: Style) -> SignStyle | None:
    """Write this sign's data for the style to the provided property."""
    for potential_style in style.bases:
        try:
            data = sign.styles[potential_style.reference()]
            break
        except KeyError:
            pass
    else:
        LOGGER.warning(
            'No valid "{}" style for "{}" signage!',
            style.id,
            sign.id,
        )
        try:
            data = sign.styles[PakRef(Style, CLEAN_STYLE)]
        except KeyError:
            return None
    parent.append(Keyvalues('world', data.world))
    parent.append(Keyvalues('overlay', data.overlay))
    parent.append(Keyvalues('type', data.type))
    return data


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA, StepResource.RES_SPECIAL])
async def step_signage(exp_data: ExportData) -> None:
    """Export the selected signage to the config, and produce the legend."""
    # Timer value -> sign ID.
    sel_ids: list[tuple[str, str]] = [
        *exp_data.selected(Signage.export_info),
        # Special case, arrow is never selectable, but must always be exported.
        ('arrow', 'SIGN_ARROW'),
    ]

    sel_icons: dict[int, ImgHandle] = {}

    conf = Keyvalues('Signage', [])
    errors = []

    for tim_id, sign_id in sel_ids:
        try:
            sign = exp_data.packset.obj_by_id(Signage, sign_id)
        except KeyError:
            errors.append(AppError(TRANS_MISSING_SELECTED.format(id=sign_id)))
            continue
        prop_block = Keyvalues(str(tim_id), [])

        sty_sign = serialise(sign, prop_block, exp_data.selected_style)

        for sub_name, sub_id in [
            ('primary', sign.prim_id),
            ('secondary', sign.sec_id),
        ]:
            if sub_id:
                try:
                    sub_sign = exp_data.packset.obj_by_id(Signage, sub_id)
                except KeyError:
                    errors.append(AppError(TRANS_MISSING_SELECTED.format(
                        id=sign_id,
                        child=sub_name,
                        sub_id=sub_id,
                    )))
                else:
                    sub_block = Keyvalues(sub_name, [])
                    serialise(sub_sign, sub_block, exp_data.selected_style)
                    if sub_block:
                        prop_block.append(sub_block)

        if prop_block:
            conf.append(prop_block)

        # Valid timer number, store to be placed on the texture.
        if tim_id.isdigit() and sty_sign is not None:
            sel_icons[int(tim_id)] = sty_sign.icon

    if errors:
        raise ExceptionGroup('Signage Export', errors)

    exp_data.vbsp_conf.append(conf)
    sign_path = Path(exp_data.game.abs_path(SIGN_LOC))

    exp_data.resources.add(sign_path)
    await trio.to_thread.run_sync(
        make_legend,
        sign_path, exp_data.packset, exp_data.selected_style, sel_icons,
    )


def iter_cells() -> Iterator[tuple[int, int, int]]:
    """Iterate over all timer values and the associated x/y pixel coordinates."""
    for i in range(3, 31):
        y, x = divmod(i - 3, 5)
        if y == 5:  # Last row is shifted over to center.
            x += 1
        yield i, x * CELL_SIZE, y * CELL_SIZE


def make_legend(
    sign_path: Path,
    packset: PackagesSet,
    sel_style: Style,
    icons: dict[int, ImgHandle],
) -> None:
    """Construct the legend texture for the signage."""
    legend = Image.new('RGBA', LEGEND_SIZE, (0, 0, 0, 0))

    blank_img: Image.Image | None = None
    num_sheet: Image.Image | None = None
    num_step = num_x = num_y = 0
    for style in sel_style.bases:
        try:
            legend_info = packset.obj_by_id(SignageLegend, style.id, optional=True)
        except KeyError:
            pass
        else:
            overlay = legend_info.overlay.get_pil()
            if legend_info.blank is not None:
                blank_img = legend_info.blank.get_pil()
            if legend_info.background is not None:
                legend.paste(legend_info.background.get_pil(), (0, 0))
            if legend_info.numbers is not None:
                num_sheet = legend_info.numbers.get_pil()
                num_x, num_y = legend_info.num_off
                num_step, num_rem = divmod(num_sheet.width, 10)
                if num_rem != 0:
                    LOGGER.warning('Signage legend number texture width must be divisible by ten!')
            break
    else:
        LOGGER.warning('No Signage style overlay defined.')
        overlay = None

    for num, x, y in iter_cells():
        try:
            ico = icons[num].get_pil().resize(
                (CELL_SIZE, CELL_SIZE),
                Image.Resampling.LANCZOS,
            ).convert('RGB')
        except KeyError:
            if blank_img is None:
                # Blank this section.
                legend.paste(
                    (0, 0, 0, 0),
                    (x, y, x + CELL_SIZE, y + CELL_SIZE),
                )
                continue
            ico = blank_img
        legend.paste(ico, (x, y))
        if num_sheet is not None and ico is not blank_img:
            tens, ones = divmod(num, 10)
            y += CELL_SIZE - num_y - num_sheet.height
            legend.alpha_composite(
                num_sheet,
                (x + num_x, y),
                (
                    tens * num_step, 0,
                    (tens + 1) * num_step, num_sheet.height,
                ),
            )
            legend.alpha_composite(
                num_sheet,
                (x + num_x + num_step, y),
                (
                    ones * num_step, 0,
                    (ones + 1) * num_step, num_sheet.height,
                ),
            )

    if overlay is not None:
        legend = Image.alpha_composite(legend, overlay)

    vtf = VTF(*LEGEND_SIZE, fmt=ImageFormats.DXT5)
    vtf.get().copy_from(legend.tobytes(), ImageFormats.RGBA8888)
    vtf.clear_mipmaps()
    vtf.flags |= VTFFlags.ANISOTROPIC

    sign_path.parent.mkdir(parents=True, exist_ok=True)
    with sign_path.open('wb') as f:
        try:
            vtf.save(f)
        except NotImplementedError:
            LOGGER.warning('No DXT compressor, using BGRA8888.')
            # No libsquish, so DXT compression doesn't work.
            vtf.format = vtf.low_format = ImageFormats.BGRA4444

            f.truncate(0)
            f.seek(0)
            vtf.save(f)
