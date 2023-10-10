"""Implements UI for selecting corridors."""
import itertools

from tkinter import ttk
import tkinter as tk
from typing import Any, Generic, Optional, List, Protocol, Sequence, TypeVar
from typing_extensions import Final

import srctools.logger
import trio

from app import (
    TK_ROOT, DEV_MODE,
    img, localisation, sound, tk_tools,
    tkMarkdown,
)
from app.richTextBox import tkRichText
from packages import corridor
from corridor import GameMode, Direction, Orient
from config.last_sel import LastSelected
from config.corridors import UIState, Config
from transtoken import TransToken
import config
import packages
from ui_tk.img import TKImages


LOGGER = srctools.logger.get_logger(__name__)
WIDTH: Final = corridor.IMG_WIDTH_SML + 16
HEIGHT: Final = corridor.IMG_HEIGHT_SML + 16

IMG_CORR_BLANK: Final = img.Handle.blank(corridor.IMG_WIDTH_LRG, corridor.IMG_HEIGHT_LRG)
IMG_ARROW_LEFT: Final = img.Handle.builtin('BEE2/switcher_arrow', 17, 64)
IMG_ARROW_RIGHT: Final = IMG_ARROW_LEFT.crop(transpose=img.FLIP_LEFT_RIGHT)
SELECTED_COLOR: Final = '#14B0FF'

GRP_SELECTED: Final = 'selected'
GRP_UNSELECTED: Final = 'unselected'
HEADER_HEIGHT: Final = 20
HEADER_PAD: Final = 10

# If no groups are defined for a style, use this.
FALLBACK = corridor.CorridorGroup(
    '<Fallback>',
    {
        (mode, direction, orient): []
        for mode in GameMode
        for direction in Direction
        for orient in Orient
    }
)
FALLBACK.pak_id = '<fallback>'
FALLBACK.pak_name = '???'

TRANS_AUTHORS = TransToken.ui_plural('Author: {authors}', 'Authors: {authors}')
TRANS_NO_AUTHORS = TransToken.ui('Authors: Unknown')


class Icon(Protocol):
    """API for corridor icons."""

    @property
    def selected(self) -> bool:
        """If the icon is currently selected."""
        raise NotImplementedError
    @selected.setter
    def selected(self, value: bool) -> None:
        raise NotImplementedError

    def set_highlight(self, enabled: bool) -> None:
        """Set whether a highlight background is enabled."""
        raise NotImplementedError


IconT = TypeVar('IconT', bound=Icon)


class Selector(Generic[IconT]):
    """Corridor selection UI."""
    # When you click a corridor, it's saved here and displayed when others aren't
    # moused over. Reset on style/group swap.
    sticky_corr: Optional[corridor.CorridorUI]
    # The currently selected images.
    cur_images: Optional[Sequence[img.Handle]]
    img_ind: int

    # The widgets for each corridor.
    icons: List[IconT]
    # The corresponding items for each slot.
    corr_list: List[corridor.CorridorUI]

    # The current corridor group for the selected style, and the config ID to save/load.
    # These are updated by load_corridors().
    corr_group: corridor.CorridorGroup
    conf_id: str

    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages) -> None:
        super().__init__(packset)
        self.sticky_corr = None
        self.img_ind = 0
        self.cur_images = None
        self.icons = []
        self.corr_list = []

    def show(self) -> None:
        """Display the window."""
        self.refresh()
        self.win.deiconify()
        tk_tools.center_win(self.win, TK_ROOT)

    def hide(self) -> None:
        """Hide the window."""
        self.win.withdraw()
        for icon in self.icons:
            self.ui_icon_set_img(icon, None)

    async def _on_changed(self) -> None:
        """Store configuration when changed."""
        self.store_conf()

    def store_conf(self) -> None:
        """Store the configuration for the current corridor."""
        selected: List[str] = []
        unselected: List[str] = []

        for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
            if icon is not None and corr is not None:
                (selected if corr.is_selected() else unselected).append(corr.instance.casefold())

        config.APP.store_conf(Config(selected=selected, unselected=unselected), self.conf_id)

        # Fix up the highlight, if it was moved.
        for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
            if icon is not None:
                icon.set_highlight(corr is self.sticky_corr)

    def load_corridors(self, packset: packages.PackagesSet) -> None:
        """Fetch the current set of corridors from this style."""
        style_id = config.APP.get_cur_conf(
            LastSelected, 'styles',
            LastSelected('BEE2_CLEAN'),
        ).id or 'BEE2_CLEAN'
        try:
            self.corr_group = packset.obj_by_id(corridor.CorridorGroup, style_id)
        except KeyError:
            LOGGER.warning('No corridors defined for style "{}"', style_id)
            self.corr_group = FALLBACK
        self.conf_id = Config.get_id(
            style_id,
            self.btn_mode.current,
            self.btn_direction.current,
            self.btn_orient.current,
        )

    async def refresh(self, _: object = None) -> None:
        """Called to update the slots with new items if the corridor set changes."""
        mode = self.btn_mode.current
        direction = self.btn_direction.current
        orient = self.btn_orient.current
        self.conf_id = Config.get_id(self.corr_group.id, mode, direction, orient)
        conf = config.APP.get_cur_conf(Config, self.conf_id, Config())

        config.APP.store_conf(UIState(
            mode, direction, orient,
            self.win.winfo_width(),
            self.win.winfo_height(),
        ))

        try:
            corr_list = self.corr_group.corridors[mode, direction, orient]
        except KeyError:
            # Up/down can have missing ones.
            if orient is Orient.HORIZONTAL:
                LOGGER.warning(
                    'No flat corridor for {}:{}_{}!',
                    self.corr_group.id, mode.value, direction.value,
                )
            corr_list = []

        # Ensure enough slots exist to hold all of them, and clear em all.
        for slot in self.slots:
            slot.highlight = False
            slot.contents = None
            slot.flexi_group = GRP_UNSELECTED
        for _ in range(len(corr_list) + 1 - len(self.slots)):
            self.slots.append(self.drag_man.slot_flexi(self.canvas))

        inst_to_corr = {corr.instance.casefold(): corr for corr in corr_list}
        next_slot = 0
        if conf.selected:
            for sel_id in conf.selected:
                try:
                    self.slots[next_slot].contents = inst_to_corr.pop(sel_id.casefold())
                    self.slots[next_slot].flexi_group = GRP_SELECTED
                except KeyError:
                    LOGGER.warning('Unknown corridor instance "{}" in config!')
                else:
                    next_slot += 1
        else:
            # No configuration, populate with the defaults.
            defaults = self.corr_group.defaults(mode, direction, orient)
            for slot, corr in zip(self.slots, defaults):
                slot.contents = corr
                slot.flexi_group = GRP_SELECTED
                del inst_to_corr[corr.instance.casefold()]
            next_slot = len(defaults)

        for sel_id in conf.unselected:
            try:
                self.slots[next_slot].contents = inst_to_corr.pop(sel_id.casefold())
                self.slots[next_slot].flexi_group = GRP_UNSELECTED
            except KeyError:
                LOGGER.warning('Unknown corridor instance "{}" in config!', sel_id)
            else:
                next_slot += 1

        # Put all remaining in a spare slot.
        for slot, corr in zip(
            self.slots[next_slot:],
            sorted(inst_to_corr.values(), key=lambda corr: corr.name.token),
        ):
            slot.contents = corr
            slot.flexi_group = GRP_UNSELECTED

        self.drag_man.load_icons()

        # Reset item display, it's invalid.
        self.sticky_corr = None
        self.disp_corr(None)
        # Reposition everything.
        await self.reflow()

    async def evt_resized(self) -> None:
        """When the window is resized, save configuration."""
        config.APP.store_conf(UIState(
            self.btn_mode.current,
            self.btn_direction.current,
            self.btn_orient.current,
            self.win.winfo_width(),
            self.win.winfo_height(),
        ))
        await self.reflow()

    async def evt_hover_enter(self, index: int) -> None:
        """Display the specified corridor temporarily on hover."""
        try:
            corr = self.corr_list[index]
        except IndexError:
            LOGGER.warning("No corridor with index {}!", index)
            return
        self.disp_corr(corr)

    async def evt_hover_exit(self) -> None:
        """When leaving, reset to the sticky corridor."""
        if self.sticky_corr is not None:
            self.disp_corr(self.sticky_corr)
        else:
            self.disp_corr(None)

    async def evt_selected(self, index: int) -> None:
        """Fires when a corridor icon is clicked."""
        try:
            icon = self.icons[index]
            corr = self.corr_list[index]
        except IndexError:
            LOGGER.warning("No corridor with index {}!", index)
            return
        if self.sticky_corr is corr:
            return  # Already selected.
        if self.sticky_corr is not None:
            # Clear the old one.
            for old_icon in self.icons:
                old_icon.set_highlight(False)
        icon.set_highlight(True)
        self.sticky_corr = corr
        self.disp_corr(corr)

    def disp_corr(self, corr: Optional[corridor.CorridorUI]) -> None:
        """Display the specified corridor, or reset if None."""
        if corr is not None:
            self.img_ind = 0
            self.cur_images = corr.images
            self._sel_img(0)  # Updates the buttons.
            localisation.set_text(self.wid_title, corr.name)

            if len(corr.authors) == 0:
                localisation.set_text(self.wid_authors, TRANS_NO_AUTHORS)
            else:
                localisation.set_text(self.wid_authors, TRANS_AUTHORS.format(
                    authors=TransToken.list_and(corr.authors),
                    n=len(corr.authors),
                ))

            if DEV_MODE.get():
                # Show the instance in the description, plus fixups that are assigned.
                self.wid_desc.set_text(tkMarkdown.join(
                    tkMarkdown.MarkdownData.text(corr.instance + '\n', tkMarkdown.TextTag.CODE),
                    corr.desc,
                    tkMarkdown.MarkdownData.text('\nFixups:\n', tkMarkdown.TextTag.BOLD),
                    tkMarkdown.convert(TransToken.untranslated('\n'.join([
                        f'* `{var}`: `{value}`'
                        for var, value in corr.fixups.items()
                    ])), None)
                ))
            else:
                self.wid_desc.set_text(corr.desc)
        else:  # Reset.
            self.cur_images = None
            localisation.set_text(self.wid_title, TransToken.BLANK)
            self.wid_desc.set_text(tkMarkdown.MarkdownData.BLANK)
            localisation.set_text(self.wid_authors, TransToken.BLANK)
            self.tk_img.apply(self.wid_image, IMG_CORR_BLANK)
            self.wid_image_left.state(('disabled', ))
            self.wid_image_right.state(('disabled', ))

    def _sel_img(self, direction: int) -> None:
        """Go forward or backwards in the preview images."""
        if self.cur_images is None:
            # Not selected, hide entirely.
            self.img_ind = 0
            self.ui_desc_set_img_state(IMG_CORR_BLANK, False, False)
            return

        direction = min(1, max(-1, direction))  # Clamp

        max_ind = len(self.cur_images) - 1
        self.img_ind += direction
        # These comparisons are ordered so that img_ind is forced to 0 if cur_images is empty.
        if self.img_ind > max_ind:
            self.img_ind = max_ind
        if self.img_ind < 0:
            self.img_ind = 0

        if self.cur_images:
            icon = self.cur_images[self.img_ind]
        else:  # No icons, use a generic one.
            icon = corridor.ICON_GENERIC_LRG
        self.ui_desc_set_img_state(
            icon,
            self.img_ind > 0,
            self.img_ind < max_ind,
        )

    def ui_icon_set_img(self, icon: IconT, handle: Optional[img.Handle]) -> None:
        """Set the image for the specified corridor icon."""
        raise NotImplementedError

    def ui_desc_set_img_state(self, handle: Optional[img.Handle], left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        raise NotImplementedError


async def test() -> None:
    from app import background_run
    from typing import Dict
    from ui_tk.img import TK_IMG
    background_run(img.init, Dict[str, srctools.FileSystem[Any]](), TK_IMG)
    background_run(sound.sound_task)

    test_sel = Selector(packages.get_loaded_packages(), TK_IMG)
    config.APP.read_file()
    test_sel.show()
    with trio.CancelScope() as scope:
        test_sel.win.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
