"""Export signage configuration, and write the legend."""

from io import BytesIO
from typing import Final, Optional

import trio.to_thread
from PIL import Image
from srctools.vtf import ImageFormats, VTF, VTFFlags
from srctools import Keyvalues
import srctools.logger

from exporting import STEPS, StepResource
from packages import PackagesSet, ExportData, Style
from app.img import Handle as ImgHandle
from packages.signage import CELL_SIZE, LEGEND_SIZE, Signage, SignStyle, SignageLegend


LOGGER = srctools.logger.get_logger(__name__)
SIGN_LOC: Final = 'bee2/materials/BEE2/models/props_map_editor/signage/signage.vtf'


def serialise(sign: Signage, parent: Keyvalues, style: Style) -> Optional[SignStyle]:
    """Write this sign's data for the style to the provided property."""
    for potential_style in style.bases:
        try:
            data = sign.styles[potential_style.id.upper()]
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
            data = sign.styles['BEE2_CLEAN']
        except KeyError:
            return None
    parent.append(Keyvalues('world', data.world))
    parent.append(Keyvalues('overlay', data.overlay))
    parent.append(Keyvalues('type', data.type))
    return data


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA, StepResource.RES_DATA])
async def export(exp_data: ExportData) -> None:
    """Export the selected signage to the config, and produce the legend."""
    # Timer value -> sign ID.
    sel_ids: list[tuple[str, str]] = [
        *exp_data.selected[Signage],
        # Special case, arrow is never selectable, but must always be exported.
        ('arrow', 'SIGN_ARROW'),
    ]

    sel_icons: dict[int, ImgHandle] = {}

    conf = Keyvalues('Signage', [])

    for tim_id, sign_id in sel_ids:
        try:
            sign = exp_data.packset.obj_by_id(Signage, sign_id)
        except KeyError:
            LOGGER.warning('Signage "{}" does not exist!', sign_id)
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
                    LOGGER.warning(
                        'Signage "{}"\'s {} "{}" '
                        'does not exist!', sign_id, sub_name, sub_id)
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

    exp_data.vbsp_conf.append(conf)
    exp_data.resources[SIGN_LOC] = await trio.to_thread.run_sync(
        build_texture,
        exp_data.packset, exp_data.selected_style, sel_icons,
    )


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
            ico = icons[i + 3].get_pil().resize(
                (CELL_SIZE, CELL_SIZE),
                Image.Resampling.LANCZOS,
            ).convert('RGB')
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
