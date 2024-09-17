"""Implements UI for selecting corridors."""
from __future__ import annotations
from typing import Final
from typing_extensions import override

from abc import abstractmethod
from collections.abc import Sequence
from contextlib import aclosing
import itertools
import random

from trio_util import AsyncValue, RepeatedEvent
import attrs
import srctools.logger
import trio
import trio_util

from async_util import EdgeTrigger, iterval_cancelling
from config.corridors import Config, Options, UIState
from corridor import Attachment, Direction, GameMode, Option
from packages import CorridorGroup, PackagesSet, PakRef, Style, corridor
from transtoken import TransToken
import config
import packages
import utils

from . import DEV_MODE, ReflowWindow, WidgetCache, img
from .mdown import MarkdownData


LOGGER = srctools.logger.get_logger(__name__)
WIDTH: Final = corridor.IMG_WIDTH_SML + 16
HEIGHT: Final = corridor.IMG_HEIGHT_SML + 16

IMG_CORR_BLANK: Final = img.Handle.background(corridor.IMG_WIDTH_LRG, corridor.IMG_HEIGHT_LRG)
IMG_ARROW_LEFT: Final = img.Handle.builtin('BEE2/switcher_arrow', 17, 64)
IMG_ARROW_RIGHT: Final = IMG_ARROW_LEFT.transform(transpose=img.FLIP_LEFT_RIGHT)


# If no groups are defined for a style, use this.
FALLBACK = corridor.CorridorGroup(
    id='<Fallback>',
    corridors={
        (mode, direction, attach): []
        for mode in GameMode
        for direction in Direction
        for attach in Attachment
    },
)
FALLBACK.pak_id = utils.special_id('<FALLBACK>')
FALLBACK.pak_name = '???'

TRANS_TITLE = TransToken.ui('BEEmod - Select Corridor')
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
TRANS_ONLY_THIS = TransToken.ui('Use Only This')
TRANS_GROUP_MODE = TransToken.ui('Game Mode')
TRANS_GROUP_DIR = TransToken.ui('Corridor Type')
TRANS_GROUP_ATTACH = TransToken.ui('Attachment Surface')

OPTS_MODE = [
    (GameMode.SP, TransToken.ui('SP')),
    (GameMode.COOP, TransToken.ui('Coop')),
]
OPTS_DIR = [
    (Direction.ENTRY, TransToken.ui('Entry')),
    (Direction.EXIT, TransToken.ui('Exit')),
]
OPTS_ATTACH = [
    (Attachment.FLAT, TransToken.ui('Flat')),
    (Attachment.FLOOR, TransToken.ui('Floor')),
    (Attachment.CEILING, TransToken.ui('Ceiling')),
]


class Icon:
    """API for corridor icons."""

    @abstractmethod
    def set_image(self, handle: img.Handle | None) -> None:
        """Set the image for this icon."""
        raise NotImplementedError

    @property
    @abstractmethod
    def selected(self) -> bool:
        """If the icon is currently selected."""
        raise NotImplementedError

    @selected.setter
    @abstractmethod
    def selected(self, value: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_readonly(self, enabled: bool) -> None:
        """Set the checkbox to be readonly."""
        raise NotImplementedError

    @abstractmethod
    def set_highlight(self, enabled: bool) -> None:
        """Set whether a highlight background is enabled."""
        raise NotImplementedError


class OptionRow:
    """API for a row used for corridor options."""
    # The current value for the row.
    current: AsyncValue[utils.SpecialID]
    _value_order: Sequence[utils.SpecialID]

    def __init__(self) -> None:
        self.current = AsyncValue(utils.ID_RANDOM)

    @abstractmethod
    async def display(
        self,
        row: int, option: Option, remove_event: trio.Event,
        *, task_status: trio.TaskStatus = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """Reconfigure this row to display the specified option, then show it.

        Once the event triggers, remove the row.
        """
        raise NotImplementedError


class Selector[IconT: Icon, OptionRowT: OptionRow](ReflowWindow):
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
    select_trigger: EdgeTrigger[()]
    # Triggered when we need to refresh the corridor list.
    corridors_dirty: trio.Event

    # The widgets for each corridor.
    icons: WidgetCache[IconT]
    # The corresponding items for each slot.
    corr_list: list[corridor.CorridorUI]

    # The current corridor group for the selected style, and the config ID to save/load.
    # These are updated by load_corridors().
    corr_group: corridor.CorridorGroup
    conf_id: str

    # Currently loaded packages/style.
    packset: PackagesSet
    cur_style: AsyncValue[PakRef[Style]]

    # The rows created for options. These are hidden if no longer used.
    option_rows: list[OptionRowT]

    # The current state of the three main selector buttons.
    state_attach: AsyncValue[Attachment]
    state_dir: AsyncValue[Direction]
    state_mode: AsyncValue[GameMode]

    def __init__(self, conf: UIState, cur_style: AsyncValue[PakRef[Style]]) -> None:
        super().__init__()
        self.sticky_corr = None
        self.displayed_corr = AsyncValue(None)
        self.packset = PackagesSet.blank()
        self.cur_style = cur_style
        self.state_attach = AsyncValue(conf.last_attach)
        self.state_dir = AsyncValue(conf.last_direction)
        self.state_mode = AsyncValue(conf.last_mode)
        self.show_trigger = EdgeTrigger()
        self.select_trigger = EdgeTrigger()
        self.close_event = RepeatedEvent()
        self.corridors_dirty = trio.Event()
        # Dummy values used until we fully load.
        self.img_ind = 0
        self.cur_images = None
        self.corr_group = FALLBACK
        self.conf_id = ''
        self.corr_list = []
        self.option_rows = []

    async def task(self) -> None:
        """Main task handling interaction with the corridor."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._window_task)
            nursery.start_soon(self._display_task)
            nursery.start_soon(self._packages_changed_task)
            nursery.start_soon(self.reposition_items_task)
            nursery.start_soon(self._save_config_task)
            nursery.start_soon(self._mode_switch_task)
            nursery.start_soon(self._reload_task)
            nursery.start_soon(self.ui_task)

    async def _window_task(self) -> None:
        """Run to allow opening/closing the window."""
        while True:
            await self.show_trigger.wait()
            self.corridors_dirty.set()
            self.ui_win_show()

            await self.close_event.wait()

            self.store_conf()
            self.ui_win_hide()
            self.icons.hide_all()

    async def _save_config_task(self) -> None:
        """When a checkmark is changed, store the new config."""
        while True:
            await self.select_trigger.wait()
            self.prevent_deselection()
            self.store_conf()

    async def _mode_switch_task(self) -> None:
        """React to a mode being switched by reloading the corridor."""
        while True:
            await trio_util.wait_any(
                self.state_attach.wait_transition,
                self.state_mode.wait_transition,
                self.state_dir.wait_transition,
            )
            self.store_conf()
            self.corridors_dirty.set()

    async def _packages_changed_task(self) -> None:
        """When packages or styles change, reload."""
        packset: PackagesSet
        async with iterval_cancelling(packages.LOADED) as aiterator:
            async for scope in aiterator:
                # This scope is cancelled if new packages load.
                async with scope as packset:
                    # Only use the packages once styles and corridors are ready for
                    # us.
                    await packset.ready(Style).wait()
                    await packset.ready(CorridorGroup).wait()
                    self.packset = packset
                    async with aclosing(self.cur_style.eventual_values()) as agen:
                        async for style in agen:
                            self.load_corridors(style)
                            self.corridors_dirty.set()

    def prevent_deselection(self) -> None:
        """Ensure at least one widget is selected."""
        icons = self.icons.placed
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

    def store_conf(self) -> None:
        """Store the configuration for the current corridor."""
        cur_conf = config.APP.get_cur_conf(Config, self.conf_id)
        # Start with the existing config, so we preserve unknown instances.
        enabled = dict(cur_conf.enabled)

        for icon, corr in itertools.zip_longest(self.icons.placed, self.corr_list):
            if icon is not None and corr is not None:
                enabled[corr.instance.casefold()] = icon.selected

        config.APP.store_conf(Config(enabled), self.conf_id)

    def load_corridors(self, cur_style: PakRef[Style]) -> None:
        """Fetch the current set of corridors from this style."""
        try:
            self.corr_group = self.packset.obj_by_id(corridor.CorridorGroup, cur_style.id)
        except KeyError:
            LOGGER.warning('No corridors defined for style "{}"', cur_style)
            self.corr_group = FALLBACK
        self.conf_id = Config.get_id(
            cur_style.id,
            self.state_mode.value, self.state_dir.value, self.state_attach.value,
        )

    async def _reload_task(self) -> None:
        """Manages calls to _refresh()."""
        while True:
            await self._refresh()
            await self.corridors_dirty.wait()
            self.corridors_dirty = trio.Event()

    async def _refresh(self) -> None:
        """Called to update the slots with new items if the corridor set changes.

        Should only be called by _reload_task.
        """
        mode = self.state_mode.value
        direction = self.state_dir.value
        attach = self.state_attach.value
        self.conf_id = Config.get_id(self.corr_group.id, mode, direction, attach)
        conf = config.APP.get_cur_conf(Config, self.conf_id)

        await trio.lowlevel.checkpoint()
        config.APP.store_conf(UIState(mode, direction, attach, *self.ui_win_getsize()))

        try:
            self.corr_list = self.corr_group.corridors[mode, direction, attach]
        except KeyError:
            # Up/down can have missing ones.
            if attach is Attachment.HORIZONTAL:
                LOGGER.warning(
                    'No flat corridor for {}:{}_{}!',
                    self.corr_group.id, mode.value, direction.value,
                )
            self.corr_list = []

        inst_enabled: dict[str, bool] = {corr.instance.casefold(): False for corr in self.corr_list}
        await trio.lowlevel.checkpoint()
        if conf.enabled:
            for sel_id, enabled in conf.enabled.items():
                try:
                    inst_enabled[sel_id.casefold()] = enabled
                except KeyError:
                    LOGGER.warning('Unknown corridor instance "{}" in config!', sel_id)
        else:
            # No configuration, populate with the defaults.
            for corr in self.corr_group.defaults(mode, direction, attach):
                inst_enabled[corr.instance.casefold()] = True

        self.icons.reset()
        for corr in self.corr_list:
            await trio.lowlevel.checkpoint()
            icon = self.icons.fetch()
            icon.set_highlight(False)
            icon.set_image(corr.icon)
            icon.selected = inst_enabled[corr.instance.casefold()]
        self.icons.hide_unused()

        await trio.lowlevel.checkpoint()
        self.prevent_deselection()

        # Reset item display, it's invalid.
        self.sticky_corr = None
        self.displayed_corr.value = None
        # Items must be repositioned.
        self.item_pos_dirty.set()

    @override
    def evt_window_resized(self, event: object) -> None:
        """When the window is resized, save configuration."""
        super().evt_window_resized(event)
        width, height = self.ui_win_getsize()
        config.APP.store_conf(UIState(
            self.state_mode.value,
            self.state_dir.value,
            self.state_attach.value,
            width, height,
        ))

    def evt_hover_enter(self, icon: IconT) -> None:
        """Display the specified corridor temporarily on hover."""
        try:
            corr = self.corr_list[self.icons.placed.index(icon)]
        except IndexError:
            LOGGER.warning("Icon has no matching corridor!")
            return
        self.displayed_corr.value = corr

    def evt_hover_exit(self) -> None:
        """When leaving, reset to the sticky corridor."""
        self.displayed_corr.value = self.sticky_corr

    def evt_selected(self, icon: IconT) -> None:
        """Fires when a corridor icon is clicked."""
        try:
            corr = self.corr_list[self.icons.placed.index(icon)]
        except IndexError:
            LOGGER.warning("Icon has no matching corridor!")
            return
        if self.sticky_corr is corr:
            # Already selected, toggle the checkbox. But only deselect if another is selected.
            if icon.selected:
                for other_icon in self.icons.placed:
                    if other_icon is not icon and other_icon.selected:
                        icon.selected = False
                        break
            else:
                icon.selected = True
            self.prevent_deselection()
        else:
            if self.sticky_corr is not None:
                # Clear the old one.
                for other_icon in self.icons.placed:
                    other_icon.set_highlight(False)
            icon.set_highlight(True)
            self.sticky_corr = corr
            self.displayed_corr.value = corr

    def evt_select_one(self) -> None:
        """Select just the sticky corridor."""
        if self.sticky_corr is not None:
            for icon, corr in zip(self.icons.placed, self.corr_list, strict=True):
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

                option_conf_id = Options.get_id(self.corr_group.id, mode, direction)
                option_conf = config.APP.get_cur_conf(Options, option_conf_id)

                if DEV_MODE.value:
                    # Show the instance in the description, plus fixups that are assigned.
                    fixup_corr = '\n'.join([
                        f'* `{var}` = `{value}`'
                        for var, value in corr.fixups.items()
                    ])
                    fixup_opt = '\n'.join([
                        f'* `{opt.fixup}` = {option_conf.value_for(opt)}'
                        for opt in options
                    ])
                    description = (
                        MarkdownData(TransToken.untranslated(f'`{corr.instance}`\n'), None)
                        + corr.desc
                        + MarkdownData(TransToken.untranslated(
                            f'\n**Fixups:**\n{fixup_corr}\n{fixup_opt}'
                        ), None)
                    )
                else:
                    description = corr.desc

                # "Enable Just This" can be clicked if this icon is deselected or any other
                # icon is selected.
                self.ui_enable_just_this(any(
                    icon.selected != (ico_corr is corr)
                    for icon, ico_corr in zip(self.icons.placed, self.corr_list, strict=True)
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
                while len(options) > len(self.option_rows):
                    self.option_rows.append(self.ui_option_create())

                option_async_vals = []
                async with trio.open_nursery() as nursery:
                    done_event = trio.Event()
                    opt: Option
                    row: OptionRowT
                    # This nursery exits only once all the option tasks has fully initialised.
                    async with trio.open_nursery() as start_nursery:
                        for ind, (opt, row) in enumerate(
                            zip(options, self.option_rows, strict=False)
                        ):
                            row.current.value = option_conf.value_for(opt)
                            start_nursery.start_soon(
                                nursery.start,
                                row.display, ind, opt, done_event,
                            )
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
                    self.ui_option_refreshed()

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
                    desc=MarkdownData.BLANK,
                    show_no_options=False,
                )
                self.ui_enable_just_this(False)
                self.ui_option_refreshed()
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
        async with trio_util.move_on_when(done_event.wait) as scope:
            while not scope.cancel_called:
                await trio.lowlevel.checkpoint()
                await trio_util.wait_any(*wait_funcs)
                conf = config.APP.get_cur_conf(Options, conf_id)
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

    @abstractmethod
    async def ui_task(self) -> None:
        """Task which is run to update the UI."""
        raise NotImplementedError

    @abstractmethod
    def ui_win_hide(self) -> None:
        """Hide the window."""
        raise NotImplementedError

    @abstractmethod
    def ui_win_show(self) -> None:
        """Show the window."""
        raise NotImplementedError

    @abstractmethod
    def ui_win_getsize(self) -> tuple[int, int]:
        """Fetch the current dimensions, for saving."""
        raise NotImplementedError

    @abstractmethod
    def ui_enable_just_this(self, enable: bool) -> None:
        """Set whether the just this button is pressable."""
        raise NotImplementedError

    @abstractmethod
    def ui_desc_display(
        self, *,
        title: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        options_title: TransToken,
        show_no_options: bool,
    ) -> None:
        """Display information for a corridor."""
        raise NotImplementedError

    @abstractmethod
    def ui_desc_set_img_state(self, handle: img.Handle | None, left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        raise NotImplementedError

    @abstractmethod
    def ui_option_create(self) -> OptionRowT:
        """Create a new option row."""
        raise NotImplementedError

    def ui_option_refreshed(self) -> None:
        """Called when the options have changed, so they can re re-layouted."""
        # If not defined, do nothing.
