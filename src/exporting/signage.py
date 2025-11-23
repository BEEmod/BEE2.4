"""Export signage configuration, and write the legend."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Final
from pathlib import Path

from PIL import Image

from aioresult import ResultCapture
from srctools import FileSystem, Keyvalues
from srctools.vtf import VTF, ImageFormats, VTFFlags
import srctools.logger
import trio.to_thread

from app.img import Handle as ImgHandle
from packages import CLEAN_STYLE, PakRef, Style
from packages.signage import (
    CELL_ANT_SIZE, CELL_SIGN_SIZE, LEGEND_SIZE, Signage, SignageLegend, SignStyle,
)
from transtoken import AppError, TransToken

from . import STEPS, ExportData, StepResource


LOGGER = srctools.logger.get_logger(__name__)
SIGN_LOC: Final = 'bee2/materials/bee2/models/props_map_editor/signage/signage.vtf'
SIGN_ANT_LOC: Final = 'bee2/materials/bee2/models/props_map_editor/signage/signage_antline.vtf'

TRANS_MISSING_SELECTED = TransToken.untranslated('Selected signage "{id}" does not exist.')
TRANS_MISSING_CHILD = TransToken.untranslated('Signage "{id}"\'s {child} "{sub_id}" does not exist.')
TRANS_INVALID_NUMBERS_WIDTH = TransToken.untranslated(
    'Signage legend number texture width must be divisible by ten!'
)
TRANS_NO_OVERLAY = TransToken.untranslated(
    'No SignageLegend layout defined for current style (or parents)! Using Clean Style.'
)
TRANS_NO_OVERLAY_NO_CLEAN = TransToken.untranslated(
    'No SignageLegend layout defined for current style (or parents), and no Clean Style available. '
    'Editor models will look incorrect.'
)

EDITOR_SHAPES = [
    'box',
    'cross',
    'dot',
    'moon',
    'slash',
    'triangle',
    'sine',
    'star',
    'circle',
    'wavy',
]


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


def load_conn_icon(fsys: FileSystem, shape: str) -> Image.Image | None:
    """Load the antline signage textures."""
    filename = f'materials/models/props_map_editor/signage_shape_{shape}.vtf'
    try:
        file = fsys[filename]
    except FileNotFoundError:
        return None
    try:
        with file.open_bin() as f:
            vtf = VTF.read(f)
            return vtf.get().to_PIL()
    except Exception as exc:
        exc.add_note(f'File: {fsys}:{filename}')
        raise


@STEPS.add_step(prereq=[StepResource.VPK_WRITTEN], results=[StepResource.VCONF_DATA, StepResource.RES_SPECIAL])
async def step_signage(exp_data: ExportData) -> None:
    """Export the selected signage to the config, and produce the legend."""
    # Timer value -> sign ID.
    sel_ids: list[tuple[str, str]] = [
        *exp_data.selected(Signage.export_info),
        # Special case, arrow is never selectable, but must always be exported.
        ('arrow', 'SIGN_ARROW'),
    ]
    LOGGER.debug('Beginning signage export: {}', sel_ids)

    sel_icons: dict[int, ImgHandle] = {}

    conf = Keyvalues('Signage', [])
    errors = []

    for tim_id, sign_id in sel_ids:
        await trio.lowlevel.checkpoint()
        try:
            sign = exp_data.packset.obj_by_id(Signage, sign_id)
        except KeyError:
            errors.append(AppError(TRANS_MISSING_SELECTED.format(id=sign_id)))
            continue
        kv_block = Keyvalues(str(tim_id), [])

        sty_sign = serialise(sign, kv_block, exp_data.selected_style)

        for sub_name, sub_id in [
            ('primary', sign.prim_id),
            ('secondary', sign.sec_id),
        ]:
            if sub_id:
                try:
                    sub_sign = exp_data.packset.obj_by_id(Signage, sub_id)
                except KeyError:
                    errors.append(AppError(TRANS_MISSING_CHILD.format(
                        id=sign_id,
                        child=sub_name,
                        sub_id=sub_id,
                    )))
                else:
                    sub_block = Keyvalues(sub_name, [])
                    serialise(sub_sign, sub_block, exp_data.selected_style)
                    if sub_block:
                        kv_block.append(sub_block)

        if kv_block:
            conf.append(kv_block)

        # Valid timer number, store to be placed on the texture.
        if tim_id.isdigit() and sty_sign is not None:
            sel_icons[int(tim_id)] = sty_sign.icon
            LOGGER.debug('{} = {}', tim_id, sty_sign)
        else:
            LOGGER.debug('{} = N/A', tim_id)

    if errors:
        raise ExceptionGroup('Signage Export', errors)

    exp_data.vbsp_conf.append(conf)

    LOGGER.debug('Loading connection icons...')
    fsys = await trio.to_thread.run_sync(exp_data.game.get_filesystem)

    async with trio.open_nursery() as nursery:
        ant_icons = {
            ind + 3: ResultCapture.start_soon(
                nursery, trio.to_thread.run_sync,
                load_conn_icon, fsys, shape,
            )
            for ind, shape in enumerate(EDITOR_SHAPES)
        }

    legend_obj: SignageLegend | None = None
    for style in exp_data.selected_style.bases:
        await trio.lowlevel.checkpoint()
        try:
            legend_obj = exp_data.packset.obj_by_id(SignageLegend, style.id, warn=False)
            break
        except KeyError:
            pass
    else:
        # Grab Clean style.
        try:
            legend_obj = exp_data.packset.obj_by_id(SignageLegend, CLEAN_STYLE, warn=False)
        except KeyError:
            exp_data.warn_auth(exp_data.selected_style.pak_id, TRANS_NO_OVERLAY_NO_CLEAN)
        else:
            exp_data.warn_auth(exp_data.selected_style.pak_id, TRANS_NO_OVERLAY)
    sign_path = Path(exp_data.game.abs_path(SIGN_LOC))
    sign_ant_path = Path(exp_data.game.abs_path(SIGN_ANT_LOC))

    exp_data.resources |= {sign_path, sign_ant_path}
    LOGGER.debug('Legend: {}', legend_obj)
    async with trio.open_nursery() as nursery:
        nursery.start_soon(
            trio.to_thread.run_sync, make_legend,
            exp_data, sign_path, sel_icons, legend_obj, False,
        )
        nursery.start_soon(
            trio.to_thread.run_sync, make_legend,
            exp_data, sign_ant_path, ant_icons, legend_obj, True,
        )
    LOGGER.debug('Complete!')


def iter_sign_cells() -> Iterator[tuple[int, int, int]]:
    """Iterate over all timer values and the associated x/y pixel coordinates."""
    for i in range(3, 31):
        y, x = divmod(i - 3, 5)
        if y == 5:  # Last row is shifted over to center.
            x += 1
        yield i, x * CELL_SIGN_SIZE, y * CELL_SIGN_SIZE


def iter_ant_cells() -> Iterator[tuple[int, int, int]]:
    """Iterate over all timer values and the associated x/y pixel coordinates."""
    for i in range(3, 13):
        y, x = divmod(i - 3, 4)
        if y == 2:  # Last row is shifted over to center.
            x += 1
        yield i, x * CELL_ANT_SIZE, y * CELL_ANT_SIZE


def make_legend(
    exp: ExportData,
    sign_path: Path,
    icons: Mapping[int, ImgHandle | ResultCapture[Image.Image | None]],
    legend_obj: SignageLegend | None,
    is_antline: bool,
) -> None:
    """Construct the legend texture for the signage."""
    cell_size = CELL_ANT_SIZE if is_antline else CELL_SIGN_SIZE
    legend = Image.new('RGBA', LEGEND_SIZE, (0, 0, 0, 0))

    ico: Image.Image | None
    overlay: Image.Image | None = None
    blank_img: Image.Image | None = None
    num_sheet: Image.Image | None = None
    background: Image.Image | None = None
    num_step = num_x = num_y = 0

    if legend_obj is not None:
        legend_info = legend_obj.antline_conf if is_antline else legend_obj.symbol_conf
        if legend_info.overlay is not None:
            overlay = legend_info.overlay.get_pil()
        if legend_info.blank is not None:
            blank_img = legend_info.blank.get_pil().resize(
                (cell_size, cell_size),
                Image.Resampling.LANCZOS,
            )
        if legend_info.background is not None:
            # Ensure it's exactly the same size as the legend.
            background = Image.new('RGBA', LEGEND_SIZE, (0, 0, 0, 0))
            background.paste(legend_info.background.get_pil())
            # To allow this to be reused for both legends, skip copying the unused bits
            # of the cells area. So here only copy the bits for the model geometry.
            legend.alpha_composite(background, (0, 623), (0, 623))
        if legend_info.numbers is not None:
            num_sheet = legend_info.numbers.get_pil()
            num_x, num_y = legend_info.num_off
            num_step, num_rem = divmod(num_sheet.width, 10)
            if num_rem != 0:
                exp.warn_auth(legend_obj.pak_id, TRANS_INVALID_NUMBERS_WIDTH)
    else:
        overlay = None

    for num, x, y in iter_ant_cells() if is_antline else iter_sign_cells():
        trio.from_thread.check_cancelled()
        try:
            handle = icons[num]
        except KeyError:
            ico = None
        else:
            if isinstance(handle, ImgHandle):
                ico = handle.get_pil()
            else:
                ico = handle.result()
        if background is not None:
            # Copy in the background to fill this cell.
            legend.alpha_composite(
                background,
                (x, y),
                (x, y, x + cell_size, y + cell_size),
            )
        if ico is None:
            if blank_img is None:
                # Blank this section.
                legend.paste(
                    (0, 0, 0, 0),
                    (x, y, x + cell_size, y + cell_size),
                )
                continue
            ico = blank_img
        ico = ico.resize(
            (cell_size, cell_size),
            Image.Resampling.LANCZOS,
        ).convert('RGBA')
        legend.alpha_composite(ico, (x, y))
        if num_sheet is not None and ico is not blank_img:
            tens, ones = divmod(num, 10)
            y += cell_size - num_y - num_sheet.height
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
    assert legend.size == LEGEND_SIZE, legend
    assert legend.mode == 'RGBA', legend
    # No point compressing, it's only on the user's disk.
    vtf = VTF(*LEGEND_SIZE, fmt=ImageFormats.RGBA8888)
    vtf.get().copy_from(legend.tobytes(), ImageFormats.RGBA8888)
    vtf.clear_mipmaps()
    vtf.flags |= VTFFlags.ANISOTROPIC

    trio.from_thread.check_cancelled()
    sign_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info('Writing {}...', sign_path)

    with sign_path.open('wb') as f:
        vtf.save(f)
