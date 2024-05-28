"""Implements UI for selecting corridors."""
from __future__ import annotations
from typing_extensions import Final
from collections.abc import Sequence, Iterator
import itertools
import random

from trio_util import AsyncValue, RepeatedEvent
import attrs
import srctools.logger
import trio
import trio_util

from app import DEV_MODE, EdgeTrigger, img, tkMarkdown
from config.corridors import UIState, Config, Options
from corridor import GameMode, Direction, Orient, Option
from packages import corridor
from transtoken import TransToken
import utils
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
    id='<Fallback>',
    corridors={
        (mode, direction, orient): []
        for mode in GameMode
        for direction in Direction
        for orient in Orient
    },
)
FALLBACK.pak_id = utils.special_id('<FALLBACK>')
FALLBACK.pak_name = '???'

TRANS_AUTHORS = TransToken.ui_plural('Author: {authors}', 'Authors: {authors}')
TRANS_NO_AUTHORS = TransToken.ui('Authors: Unknown')
TRANS_HELP = TransToken.ui(
    "Check the boxes to specify which corridors may be used. Ingame, a random corridor will "
    "be picked for each map."
)
TRANS_OPT_TITLE = {
    (GameMode.SP, Direction.ENTRY): TransToken.ui('Singleplayer Entry Options:'),
    (GameMode.SP, Direction.EXIT): TransToken.ui('Singleplayer Exit Options:'),
    (GameMode.COOP, Direction.ENTRY): TransToken.ui('Cooperative Entry Options:'),
    (GameMode.COOP, Direction.EXIT): TransToken.ui('Cooperative Exit Options:'),
}
TRANS_NO_OPTIONS = TransToken.ui('No options!')
TRANS_RAND_OPTION = TransToken.ui('Randomise')


class Icon:
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


class OptionRow:
    """API for a row used for corridor options."""
    # The current value for the row.
    current: AsyncValue[utils.SpecialID]

    def __init__(self) -> None:
        self.current = AsyncValue(utils.ID_RANDOM)

    async def display(self, row: int, option: Option, remove_event: trio.Event) -> None:
        """Reconfigure this row to display the specified option, then show it.

        Once the event triggers, remove the row.
        """
        raise NotImplementedError


class Selector[IconT: Icon, OptionRowT: OptionRow]:
    """Corridor selection UI."""
    # When you click a corridor, it's saved here and displayed when others aren't
    # moused over. Reset on style/group swap.
    sticky_corr: corridor.CorridorUI | None
    # This is the corridor actually displayed right now.
    displayed_corr: AsyncValue[corridor.CorridorUI | None]
    # The currently selected images.
    cur_images: Sequence[img.Handle] | None
    img_ind: int

    # Event which is triggered to show and hide the UI.
    show_trigger: EdgeTrigger[()]
    close_event: RepeatedEvent
    # Triggered by the UI to indicate a corridor was (de)selected
    _select_trigger: EdgeTrigger[()]

    # The widgets for each corridor.
    icons: list[IconT]
    # The corresponding items for each slot.
    corr_list: list[corridor.CorridorUI]

    # The current corridor group for the selected style, and the config ID to save/load.
    # These are updated by load_corridors().
    corr_group: corridor.CorridorGroup
    conf_id: str

    # The rows created for options. These are hidden if no longer used.
    option_rows: list[OptionRowT]

    # The current state of the three main selector buttons.
    state_orient: AsyncValue[Orient]
    state_dir: AsyncValue[Direction]
    state_mode: AsyncValue[GameMode]

    def __init__(self, conf: UIState) -> None:
        self.sticky_corr = None
        self.displayed_corr = AsyncValue(None)
        self.img_ind = 0
        self.cur_images = None
        self.icons = []
        self.corr_list = []
        self.option_rows = []
        self.state_orient = AsyncValue(conf.last_orient)
        self.state_dir = AsyncValue(conf.last_direction)
        self.state_mode = AsyncValue(conf.last_mode)
        self.show_trigger = EdgeTrigger()
        self._select_trigger = EdgeTrigger()
        self.close_event = RepeatedEvent()

    async def task(self) -> None:
        """Main task handling interaction with the corridor."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._window_task)
            nursery.start_soon(self._display_task)
            nursery.start_soon(self._save_config_task)
            nursery.start_soon(self._mode_switch_task)
            nursery.start_soon(self.ui_task)

    async def _window_task(self) -> None:
        """Run to allow opening/closing the window."""
        while True:
            await self.show_trigger.wait()
            await self.refresh()
            self.ui_win_show()

            await self.close_event.wait()

            self.store_conf()
            self.ui_win_hide()
            for icon in self.icons:
                self.ui_icon_set_img(icon, None)

    async def _save_config_task(self) -> None:
        """When a checkmark is changed, store the new config."""
        while True:
            await self._select_trigger.wait()
            self.prevent_deselection()
            self.store_conf()

    async def _mode_switch_task(self) -> None:
        """React to a mode being switched by reloading the corridor."""
        while True:
            await trio_util.wait_any(
                self.state_orient.wait_transition,
                self.state_mode.wait_transition,
                self.state_dir.wait_transition,
            )
            self.store_conf()
            await self.refresh()

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

    def load_corridors(self, packset: packages.PackagesSet, style_id: utils.ObjectID) -> None:
        """Fetch the current set of corridors from this style."""
        try:
            self.corr_group = packset.obj_by_id(corridor.CorridorGroup, style_id)
        except KeyError:
            LOGGER.warning('No corridors defined for style "{}"', style_id)
            self.corr_group = FALLBACK
        self.conf_id = Config.get_id(
            style_id,
            self.state_mode.value, self.state_dir.value, self.state_orient.value,
        )

    async def refresh(self, _: object = None) -> None:
        """Called to update the slots with new items if the corridor set changes."""
        mode = self.state_mode.value
        direction = self.state_dir.value
        orient = self.state_orient.value
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
        self.displayed_corr.value = None
        # Reposition everything.
        await self.ui_win_reflow()

    async def evt_resized(self) -> None:
        """When the window is resized, save configuration."""
        width, height = self.ui_win_getsize()
        config.APP.store_conf(UIState(
            self.state_mode.value,
            self.state_dir.value,
            self.state_orient.value,
            width, height,
        ))
        await self.ui_win_reflow()

    def evt_hover_enter(self, index: int) -> None:
        """Display the specified corridor temporarily on hover."""
        try:
            corr = self.corr_list[index]
        except IndexError:
            LOGGER.warning("No corridor with index {}!", index)
            return
        self.displayed_corr.value = corr

    def evt_hover_exit(self) -> None:
        """When leaving, reset to the sticky corridor."""
        self.displayed_corr.value = self.sticky_corr

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
            self.displayed_corr.value = corr

    def evt_select_one(self) -> None:
        """Select just the sticky corridor."""
        if self.sticky_corr is not None:
            for icon, corr in itertools.zip_longest(self.icons, self.corr_list):
                if icon is not None:
                    icon.selected = corr is self.sticky_corr
            self.ui_enable_just_this(False)
            self.prevent_deselection()

    async def _display_task(self) -> None:
        """This runs continually, updating which corridor is shown."""
        corr: corridor.CorridorUI | None = None

        def corr_changed(new: corridor.CorridorUI | None) -> bool:
            """Value predicate."""
            return new is not corr

        while True:
            if corr is not None and self.corr_group is not FALLBACK:
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

                # Figure out which options to show.
                mode = self.state_mode.value
                direction = self.state_dir.value
                options = list(self.corr_group.get_options(mode, direction, corr))

                if DEV_MODE.value:
                    # Show the instance in the description, plus fixups that are assigned.
                    fixups = [
                        f'* `{var}` = `{value}`'
                        for var, value in corr.fixups.items()
                    ] + [
                        f'* `{opt.fixup}` = {opt.name}'
                        for opt in options
                    ]
                    description = tkMarkdown.join(
                        tkMarkdown.MarkdownData.text(f'{corr.instance}\n', tkMarkdown.TextTag.CODE),
                        corr.desc,
                        tkMarkdown.MarkdownData.text('\nFixups:\n', tkMarkdown.TextTag.BOLD),
                        tkMarkdown.convert(TransToken.untranslated('\n'.join(fixups)), None)
                    )
                else:
                    description = corr.desc

                # "Enable Just This" can be clicked if this icon is deselected or any other
                # icon is selected.
                self.ui_enable_just_this(any(
                    icon.selected != (ico_corr is corr)
                    for icon, ico_corr in itertools.zip_longest(self.icons, self.corr_list)
                ))

                # Display our information.
                self.ui_desc_display(
                    title=corr.name,
                    authors=author,
                    desc=description,
                    options_title=TRANS_OPT_TITLE[mode, direction],
                    show_no_options=not options,
                )

                # Place all options in the UI.
                option_conf_id = Options.get_id(self.corr_group.id, mode, direction)
                option_conf = config.APP.get_cur_conf(Options, option_conf_id, default=Options())
                while len(options) > len(self.option_rows):
                    self.option_rows.append(self.ui_option_create())

                option_async_vals = []
                async with trio.open_nursery() as nursery:
                    done_event = trio.Event()
                    opt: Option
                    row: OptionRowT
                    for ind, (opt, row) in enumerate(zip(options, self.option_rows)):
                        row.current.value = option_conf.value_for(opt)
                        nursery.start_soon(row.display, ind, opt, done_event)
                        option_async_vals.append((opt.id, row.current))

                    # This task stores results when a config is changed. Not required
                    # if we don't actually have any options.
                    if option_async_vals:
                        nursery.start_soon(
                            self._store_options_task,
                            option_async_vals,
                            option_conf_id,
                            done_event,
                        )

                    # Wait for a new corridor to be switched to, then cancel the event to remove
                    # them all.
                    corr = await self.displayed_corr.wait_value(corr_changed)
                    done_event.set()
            else:  # Reset.
                self.cur_images = None
                self._sel_img(0)  # Update buttons.
                # Clear the display entirely.
                self.ui_desc_display(
                    title=TransToken.BLANK,
                    authors=TransToken.BLANK,
                    options_title=TransToken.BLANK,
                    desc=tkMarkdown.MarkdownData.BLANK,
                    show_no_options=False,
                )
                self.ui_enable_just_this(False)
                corr = await self.displayed_corr.wait_value(corr_changed)

    @staticmethod
    async def _store_options_task(
        async_vals: list[tuple[utils.ObjectID, AsyncValue[utils.SpecialID]]],
        conf_id: str,
        done_event: trio.Event,
    ) -> None:
        """Run while options are visible. This stores them when changed."""
        assert async_vals, "No options?"
        wait_funcs = [val.wait_transition for opt_id, val in async_vals]
        async with trio_util.move_on_when(done_event.wait):
            while True:
                await trio.lowlevel.checkpoint()
                await trio_util.wait_any(*wait_funcs)
                conf = config.APP.get_cur_conf(Options, conf_id, default=Options())
                config.APP.store_conf(attrs.evolve(conf, options={
                    # Preserve any existing, unknown IDs.
                    **conf.options,
                    **{
                        opt_id: val.value
                        for opt_id, val in async_vals
                    },
                }), conf_id)

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

    async def ui_task(self) -> None:
        """Task which is run to update the UI."""
        raise NotImplementedError

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

    def ui_icon_create(self) -> None:
        """Create a new icon widget, and append it to the list."""
        raise NotImplementedError

    def ui_icon_set_img(self, icon: IconT, handle: img.Handle | None) -> None:
        """Set the image for the specified corridor icon."""
        raise NotImplementedError

    def ui_enable_just_this(self, enable: bool) -> None:
        """Set whether the just this button is pressable."""
        raise NotImplementedError

    def ui_desc_display(
        self, *,
        title: TransToken,
        authors: TransToken,
        desc: tkMarkdown.MarkdownData,
        options_title: TransToken,
        show_no_options: bool,
    ) -> None:
        """Display information for a corridor."""
        raise NotImplementedError

    def ui_desc_set_img_state(self, handle: img.Handle | None, left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        raise NotImplementedError

    def ui_option_create(self) -> OptionRowT:
        """Create a new option row."""
        raise NotImplementedError
