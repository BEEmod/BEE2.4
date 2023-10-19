"""Implements UI for selecting corridors."""
import itertools
import random

from typing import Generic, Iterator, Optional, List, Protocol, Sequence, TypeVar
from typing_extensions import Final

import srctools.logger

from app import DEV_MODE, img, tkMarkdown
from packages import corridor
from corridor import GameMode, Direction, Orient
from config.last_sel import LastSelected
from config.corridors import UIState, Config
from transtoken import TransToken
import config
import packages


LOGGER = srctools.logger.get_logger(__name__)
WIDTH: Final = corridor.IMG_WIDTH_SML + 16
HEIGHT: Final = corridor.IMG_HEIGHT_SML + 16

IMG_CORR_BLANK: Final = img.Handle.blank(corridor.IMG_WIDTH_LRG, corridor.IMG_HEIGHT_LRG)
IMG_ARROW_LEFT: Final = img.Handle.builtin('BEE2/switcher_arrow', 17, 64)
IMG_ARROW_RIGHT: Final = IMG_ARROW_LEFT.crop(transpose=img.FLIP_LEFT_RIGHT)


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
TRANS_HELP = TransToken.ui(
    "Check the boxes to specify which corridors may be used. Ingame, a random corridor will "
    "be picked for each map."
)


class Icon(Protocol):
    """API for corridor icons."""

    @property
    def selected(self) -> bool:
        """If the icon is currently selected."""
        raise NotImplementedError

    @selected.setter
    def selected(self, value: bool) -> None:
        raise NotImplementedError

    def set_readonly(self, enabled: bool) -> None:
        """Set the checkbox to be readonly."""
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

    def __init__(self) -> None:
        self.sticky_corr = None
        self.img_ind = 0
        self.cur_images = None
        self.icons = []
        self.corr_list = []

    async def show(self) -> None:
        """Display the window."""
        await self.refresh()
        self.ui_win_show()

    def hide(self) -> None:
        """Hide the window."""
        self.store_conf()
        self.ui_win_hide()
        for icon in self.icons:
            self.ui_icon_set_img(icon, None)

    def prevent_deselection(self) -> None:
        """Ensure at least one widget is selected."""
        icons = list(self.visible_icons())
        if not icons:
            return  # No icons, nothing to do.
        count = sum(icon.selected for icon in icons)
        if count == 0:
            # If all are deselected, select a random one.
            random.choice(icons).selected = True
            count = 1

        if count == 1:
            # If only one is selected, don't allow deselecting that one.
            for icon in icons:
                icon.set_readonly(icon.selected)
        else:
            # Multiple, allow deselection.
            for icon in icons:
                icon.set_readonly(False)

    def visible_icons(self) -> Iterator[IconT]:
        """Iterate over the icons which should currently be visible."""
        return itertools.islice(self.icons, len(self.corr_list))

    def store_conf(self) -> None:
        """Store the configuration for the current corridor."""
        cur_conf = config.APP.get_cur_conf(
            Config,
            self.conf_id,
            default=Config(),
        )
        # Start with the existing config, so we preserve unknown instances.
        enabled = dict(cur_conf.enabled)

        for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
            if icon is not None and corr is not None:
                enabled[corr.instance.casefold()] = icon.selected

        config.APP.store_conf(Config(enabled), self.conf_id)

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
        mode, direction, orient = self.ui_get_buttons()
        self.conf_id = Config.get_id(style_id, mode, direction, orient)

    async def refresh(self, _: object = None) -> None:
        """Called to update the slots with new items if the corridor set changes."""

        mode, direction, orient = self.ui_get_buttons()
        self.conf_id = Config.get_id(self.corr_group.id, mode, direction, orient)
        conf = config.APP.get_cur_conf(Config, self.conf_id, Config())

        config.APP.store_conf(UIState(mode, direction, orient, *self.ui_win_getsize()))

        try:
            self.corr_list = self.corr_group.corridors[mode, direction, orient]
        except KeyError:
            # Up/down can have missing ones.
            if orient is Orient.HORIZONTAL:
                LOGGER.warning(
                    'No flat corridor for {}:{}_{}!',
                    self.corr_group.id, mode.value, direction.value,
                )
            self.corr_list = []

        inst_enabled: dict[str, bool] = {corr.instance.casefold(): False for corr in self.corr_list}
        if conf.enabled:
            for sel_id, enabled in conf.enabled.items():
                try:
                    inst_enabled[sel_id.casefold()] = enabled
                except KeyError:
                    LOGGER.warning('Unknown corridor instance "{}" in config!', sel_id)
        else:
            # No configuration, populate with the defaults.
            for corr in self.corr_group.defaults(mode, direction, orient):
                inst_enabled[corr.instance.casefold()] = True

        # Create enough icons for the current corridor list.
        for _ in range(len(self.corr_list) - len(self.icons)):
            self.ui_icon_create()

        for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
            assert icon is not None
            icon.set_highlight(False)
            if corr is not None:
                self.ui_icon_set_img(icon, corr.icon)
                icon.selected = inst_enabled[corr.instance.casefold()]
            else:
                self.ui_icon_set_img(icon, None)
                icon.selected = False

        self.prevent_deselection()

        # Reset item display, it's invalid.
        self.sticky_corr = None
        self.disp_corr(None)
        # Reposition everything.
        await self.ui_win_reflow()

    async def evt_check_changed(self) -> None:
        """Handle a checkbox changing."""
        self.prevent_deselection()
        self.store_conf()

    async def evt_mode_switch(self, _: object) -> None:
        """We must save the current state before switching."""
        self.store_conf()
        await self.refresh()

    async def evt_resized(self) -> None:
        """When the window is resized, save configuration."""
        config.APP.store_conf(UIState(*self.ui_get_buttons(), *self.ui_win_getsize()))
        await self.ui_win_reflow()

    def evt_hover_enter(self, index: int) -> None:
        """Display the specified corridor temporarily on hover."""
        try:
            corr = self.corr_list[index]
        except IndexError:
            LOGGER.warning("No corridor with index {}!", index)
            return
        self.disp_corr(corr)

    def evt_hover_exit(self) -> None:
        """When leaving, reset to the sticky corridor."""
        if self.sticky_corr is not None:
            self.disp_corr(self.sticky_corr)
        else:
            self.disp_corr(None)

    def evt_selected(self, index: int) -> None:
        """Fires when a corridor icon is clicked."""
        try:
            icon = self.icons[index]
            corr = self.corr_list[index]
        except IndexError:
            LOGGER.warning("No corridor with index {}!", index)
            return
        if self.sticky_corr is corr:
            # Already selected, toggle the checkbox. But only deselect if another is selected.
            if icon.selected:
                for other_icon in self.visible_icons():
                    if other_icon is not icon and other_icon.selected:
                        icon.selected = False
                        self.prevent_deselection()
                        break
            else:
                icon.selected = True
                self.prevent_deselection()
        else:
            if self.sticky_corr is not None:
                # Clear the old one.
                for other_icon in self.icons:
                    other_icon.set_highlight(False)
            icon.set_highlight(True)
            self.sticky_corr = corr
            self.disp_corr(corr)

    def evt_select_one(self) -> None:
        """Select just the sticky corridor."""
        if self.sticky_corr is None:
            return
        for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
            if icon is not None:
                icon.selected = corr is self.sticky_corr

    def disp_corr(self, corr: Optional[corridor.CorridorUI]) -> None:
        """Display the specified corridor, or reset if None."""
        if corr is not None:
            self.img_ind = 0
            self.cur_images = corr.images
            self._sel_img(0)  # Updates the buttons.

            if len(corr.authors) == 0:
                author = TRANS_NO_AUTHORS
            else:
                author = TRANS_AUTHORS.format(
                    authors=TransToken.list_and(corr.authors),
                    n=len(corr.authors),
                )

            if DEV_MODE.get():
                # Show the instance in the description, plus fixups that are assigned.
                description = tkMarkdown.join(
                    tkMarkdown.MarkdownData.text(corr.instance + '\n', tkMarkdown.TextTag.CODE),
                    corr.desc,
                    tkMarkdown.MarkdownData.text('\nFixups:\n', tkMarkdown.TextTag.BOLD),
                    tkMarkdown.convert(TransToken.untranslated('\n'.join([
                        f'* `{var}`: `{value}`'
                        for var, value in corr.fixups.items()
                    ])), None)
                )
            else:
                description = corr.desc
            self.ui_desc_display(
                corr.name,
                author,
                description,
                corr is self.sticky_corr,
            )
        else:  # Reset.
            self.cur_images = None
            self._sel_img(0)  # Update buttons.
            self.ui_desc_display(TransToken.BLANK, TransToken.BLANK, tkMarkdown.MarkdownData.BLANK, False)

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

    def ui_win_hide(self) -> None:
        """Hide the window."""
        raise NotImplementedError

    def ui_win_show(self) -> None:
        """Show the window."""
        raise NotImplementedError

    def ui_win_getsize(self) -> tuple[int, int]:
        """Fetch the current dimensions, for saving."""
        raise NotImplementedError

    async def ui_win_reflow(self) -> None:
        """Reposition everything after the window has resized."""
        raise NotImplementedError

    def ui_get_buttons(self) -> tuple[GameMode, Direction, Orient]:
        """Get the current button positions."""
        raise NotImplementedError

    def ui_icon_create(self) -> None:
        """Create a new icon widget, and append it to the list."""
        raise NotImplementedError

    def ui_icon_set_img(self, icon: IconT, handle: Optional[img.Handle]) -> None:
        """Set the image for the specified corridor icon."""
        raise NotImplementedError

    def ui_desc_display(
        self,
        title: TransToken,
        authors: TransToken,
        desc: tkMarkdown.MarkdownData,
        enable_just_this: bool,
    ) -> None:
        """Display information for a corridor."""
        raise NotImplementedError

    def ui_desc_set_img_state(self, handle: Optional[img.Handle], left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        raise NotImplementedError
