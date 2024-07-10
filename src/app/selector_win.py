"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from __future__ import annotations
from typing import Final, Literal, assert_never

from abc import abstractmethod

from contextlib import aclosing
from collections.abc import Callable, Container, Iterable, Iterator
from collections import defaultdict
from enum import Enum, auto as enum_auto
import functools
import math
import random

from srctools import Vec, EmptyMapping
from srctools.filesys import FileSystemChain
import attrs
import srctools.logger
import trio
import trio_util

from app.mdown import MarkdownData
from app import sound, img, DEV_MODE
from ui_tk import TK_ROOT
from packages import SelitemData, AttrTypes, AttrDef as AttrDef, AttrMap
from transtoken import TransToken
from config.last_sel import LastSelected
from config.windows import SelectorState
import utils
import config
import packages


LOGGER = srctools.logger.get_logger(__name__)

# The two icons used for boolean item attributes
ICON_CHECK = img.Handle.builtin('icons/check', 16, 16)
ICON_CROSS = img.Handle.builtin('icons/cross', 16, 16)

# Arrows used to indicate the state of the group - collapsed or expanded
GRP_COLL: Final = '◁'
GRP_COLL_HOVER: Final = '◀'
GRP_EXP: Final = '▽'
GRP_EXP_HOVER: Final = '▼'

BTN_PLAY: Final = '▶'
BTN_STOP: Final = '■'


class NavKeys(Enum):
    """Enum representing keys used for shifting through items."""
    UP = enum_auto()
    DOWN = enum_auto()
    LEFT = enum_auto()
    RIGHT = enum_auto()

    HOME = enum_auto()
    END = enum_auto()
    ENTER = enum_auto()

    # Space plays the current item.
    PLAY_SOUND = enum_auto()


# Callbacks used to get the info for items in the window.
type GetterFunc[T] = Callable[[packages.PackagesSet, utils.SpecialID], T]

# The three kinds of font for the display textbox.
type DispFont = Literal['suggested', 'mouseover', 'normal']

TRANS_ATTR_DESC = TransToken.untranslated('{desc}: ')
TRANS_ATTR_COLOR = TransToken.ui('Color: R={r}, G={g}, B={b}')  # i18n: Tooltip for colour swatch.
TRANS_WINDOW_TITLE = TransToken.ui('BEE2 - {subtitle}')  # i18n: Window titles.
TRANS_PREVIEW_TITLE = TransToken.ui('Preview - {item}')  # i18n: Preview window.
TRANS_SUGGESTED = TransToken.ui("Suggested")
# Labelframe doesn't look good for the suggested display, use box drawing characters instead.
TRANS_SUGGESTED_MAC = TransToken.untranslated("\u250E\u2500{sugg}\u2500\u2512").format(sugg=TRANS_SUGGESTED)
# If the item is groupless, use 'Other' for the header.
TRANS_GROUPLESS = TransToken.ui('Other')
TRANS_AUTHORS = TransToken.ui_plural('Author: {authors}', 'Authors: {authors}')
TRANS_NO_AUTHORS = TransToken.ui('Authors: Unknown')
TRANS_DEV_ITEM_ID = TransToken.untranslated('**ID:** {item}')
TRANS_LOADING = TransToken.ui('Loading...')


async def _store_results_task(chosen: trio_util.AsyncValue[utils.SpecialID], save_id: str) -> None:
    """Store configured results when changed."""
    async with aclosing(chosen.eventual_values()) as agen:
        async for item_id in agen:
            config.APP.store_conf(LastSelected(item_id), save_id)


@attrs.frozen(kw_only=True)
class Options:
    """Creation options for selector windows.

    - parent: Must be a Toplevel window, either the tk() root or another
    window if needed.
    - func_get_data: Function to get the data for an ID. Should fetch a cached result, will
      be called for every item.
    - func_get_ids: Called to retrieve the list of item IDs.
    - save_id: The ID used to save/load the window state.
    - store_last_selected: If set, save/load the selected ID.
    - lst: A list of Item objects, defining the visible items.
    - If `has_def` is True, the 'Reset to Default' button will appear,
      which resets to the suggested item.
    - `default_id` is the item to initially select, if no previous one is set.
    - If snd_sample_sys is set, a '>' button will appear next to names
      to play the associated audio sample for the item.
      The value should be a FileSystem to look for samples in.
    - title is the title of the selector window.
    - full_context controls if the short or long names are used for the
      context menu.
    - attributes is a list of AttrDef tuples.
      Each tuple should contain an ID, display text, and default value.
      If the values are True or False a check/cross will be displayed,
      otherwise they're a string.
    - desc is descriptive text to display on the window, and in the widget
      tooltip.
    - readonly_desc will be displayed on the widget tooltip when readonly.
    - readonly_override, if set will override the textbox when readonly.
    - modal: If True, the window will block others while open.
    """
    func_get_data: GetterFunc[SelitemData]
    func_get_ids: Callable[[packages.PackagesSet], Iterable[utils.SpecialID]]
    save_id: str  # Required!
    store_last_selected: bool = True
    has_def: bool = True
    sound_sys: FileSystemChain | None = None
    func_get_sample: GetterFunc[str] | None = None
    modal: bool = False
    default_id: utils.SpecialID = utils.ID_NONE
    title: TransToken = TransToken.untranslated('???')
    desc: TransToken = TransToken.BLANK
    readonly_desc: TransToken = TransToken.BLANK
    readonly_override: TransToken | None = None
    attributes: Iterable[AttrDef] = ()
    func_get_attr: GetterFunc[AttrMap] = lambda packset, item_id: EmptyMapping


class SelectorWinBase[ButtonT]:
    """The selection window for skyboxes, music, goo and voice packs.

    Typevars:
    - ButtonT: Type for the button widget.

    Attributes:
    - chosen: The currently-selected item.
    - selected: The item currently selected in the window, not the actually chosen one.
    - suggested: The Item which is suggested by the style.
    """
    # Callback functions used to retrieve the data for the window.
    func_get_attr: GetterFunc[AttrMap]
    func_get_data: GetterFunc[SelitemData]
    func_get_sample: GetterFunc[str] | None
    func_get_ids: Callable[[packages.PackagesSet], Iterable[utils.SpecialID]]

    # Packages currently loaded for the window.
    _packset: packages.PackagesSet

    # Currently suggested item objects. This would be a set, but we want to randomly pick.
    suggested: list[utils.SpecialID]
    # While the user hovers over the "suggested" button, cycle through random items. But we
    # want to apply that specific item when clicked.
    _suggested_rollover: utils.SpecialID | None

    # Should we have the 'reset to default' button?
    has_def: bool
    description: TransToken
    readonly_description: TransToken
    # If set, force textbox to display this when readonly.
    readonly_override: TransToken | None

    # The selected item is the one clicked on inside the window, while chosen
    # is the one actually chosen.
    chosen: trio_util.AsyncValue[utils.SpecialID]
    selected: utils.SpecialID
    _visible: bool  # If the window is currently open.
    _readonly: bool
    _loading: bool  # This overrides readonly.
    modal: bool
    attrs: list[AttrDef]
    # Event set whenever the items needs to be redrawn/reflowed.
    items_dirty: trio.Event

    # Current list of item IDs we display.
    item_list: list[utils.SpecialID]
    # A map from folded name -> display name
    group_names: dict[str, TransToken]
    # Group name -> items in that group.
    grouped_items: dict[str, list[utils.SpecialID]]
    # Group name -> is visible.
    group_visible: dict[str, bool]
    # A list of casefolded group names in the display order.
    group_order: list[str]
    # Maps item ID to the menu position.
    _menu_index: dict[utils.SpecialID, int]

    # Buttons we have constructed, corresponding to the same in the item list.
    _item_buttons: list[ButtonT]
    # And a lookup from ID -> button
    _id_to_button: dict[utils.SpecialID, ButtonT]

    # The maximum number of items that fits per row (set in flow_items)
    item_width: int

    # The ID used to persist our window state across sessions.
    save_id: str
    store_last_selected: bool
    # Indicate that flow_items() should restore state.
    first_open: bool

    sampler: sound.SamplePlayer | None

    def __init__(self, opt: Options) -> None:
        self.func_get_attr = opt.func_get_attr
        self.func_get_sample = opt.func_get_sample
        self.func_get_data = opt.func_get_data
        self.func_get_ids = opt.func_get_ids

        self._readonly = False
        self._loading = True
        self._visible = False
        self.modal = opt.modal

        # Currently suggested item objects. This would be a set, but we want to randomly pick.
        self.suggested = []
        # While the user hovers over the "suggested" button, cycle through random items. But we
        # want to apply that specific item when clicked. This stores the selected item.
        self._suggested_rollover = None
        # And this is used to control whether to start/stop hovering.
        self.suggested_rollover_active = trio_util.AsyncBool()
        self.items_dirty = trio.Event()

        # Should we have the 'reset to default' button?
        self.has_def = opt.has_def
        self.description = opt.desc
        self.readonly_description = opt.readonly_desc
        self.readonly_override = opt.readonly_override
        self.attrs = list(opt.attributes)

        prev_state = config.APP.get_cur_conf(
            LastSelected,
            opt.save_id,
            default=LastSelected(opt.default_id),
        )
        if opt.store_last_selected:
            config.APP.store_conf(prev_state, opt.save_id)

        self.selected = prev_state.id
        self.chosen = trio_util.AsyncValue(self.selected)

        self._packset = packages.PackagesSet()

        self.item_list = []
        self._item_buttons = []
        self._id_to_button = {}
        self._menu_index = {}

        # A map from folded name -> display name
        self.group_names = {}
        self.group_visible = {}
        self.grouped_items = {}
        # A list of casefolded group names in the display order.
        self.group_order = []

        # The maximum number of items that fits per row (set in flow_items)
        self.item_width = 1

        # The ID used to persist our window state across sessions.
        self.save_id = opt.save_id.casefold()
        self.store_last_selected = opt.store_last_selected
        # Indicate that flow_items() should restore state.
        self.first_open = True

        # For music items, add a '>' button to play sound samples
        if opt.sound_sys is not None and sound.has_sound() and opt.func_get_sample is not None:
            self.sampler = sound.SamplePlayer(system=opt.sound_sys)
        else:
            self.sampler = None

    async def task(self) -> None:
        """This must be run to make the window operational."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._ui_task)
            nursery.start_soon(self._load_data_task)
            nursery.start_soon(self._rollover_suggest_task)
            nursery.start_soon(self._refresh_items_task)
            if self.sampler is not None:
                nursery.start_soon(self._update_sampler_task)
            if self.store_last_selected:
                nursery.start_soon(self._load_selected_task)
                nursery.start_soon(_store_results_task, self.chosen, self.save_id)

    def __repr__(self) -> str:
        return f'<SelectorWin "{self.save_id}">'

    @property
    def chosen_id(self) -> utils.SpecialID:
        """The currently selected item, or None if none is selected."""
        return self.chosen.value

    @property
    def readonly(self) -> bool:
        """Setting the readonly property to True makes the option read-only.

        The window cannot be opened, and all other inputs will fail.
        """
        return self._readonly

    @readonly.setter
    def readonly(self, value: bool) -> None:
        self._readonly = bool(value)

    def _get_data(self, item_id: utils.SpecialID) -> SelitemData:
        """Call func_get_data, handling KeyError."""
        try:
            return self.func_get_data(self._packset, item_id)
        except KeyError:
            LOGGER.warning('ID "{}" does not exist', item_id)
            return packages.SEL_DATA_MISSING

    async def _load_data_task(self) -> None:
        """Whenever packages change, reload all items."""
        async with aclosing(packages.LOADED.eventual_values()) as agen:
            async for packset in agen:
                LOGGER.debug('Reloading data for selectorwin {}...', self.save_id)
                # Lock into the loading state so that it can't be interacted with while loading.
                self._loading = True
                self.set_disp()
                self.exit()
                self._packset = packset
                await self._rebuild_items(packset)
                self._loading = False
                self.set_disp()
                LOGGER.debug('Reload complete for selectorwin {}', self.save_id)

    async def _rebuild_items(self, packset: packages.PackagesSet) -> None:
        """Rebuild the menus and options based on the item list."""
        get_data = self._get_data

        def sort_func(item_id: utils.SpecialID) -> str:
            """Sort the item list. Special items go to the start, otherwise sort by the sort key."""
            if utils.is_special_id(item_id):
                return f'0{item_id}'
            else:
                return f'1{get_data(item_id).sort_key}'

        self.item_list = sorted(self.func_get_ids(self._packset), key=sort_func)
        grouped_items = defaultdict(list)
        self.group_names = {'':  TRANS_GROUPLESS}
        self._menu_index.clear()
        self._id_to_button.clear()

        # First, clear everything.
        self._ui_menu_clear()
        for button in self._item_buttons:
            self._ui_button_hide(button)

        # Create additional buttons so we have enough.
        while len(self._item_buttons) < len(self.item_list):
            await trio.lowlevel.checkpoint()
            self._item_buttons.append(self._ui_button_create(len(self._item_buttons)))

        for item_id, button in zip(self.item_list, self._item_buttons, strict=False):
            await trio.lowlevel.checkpoint()
            data = self.func_get_data(self._packset, item_id)
            self._id_to_button[item_id] = button
            # Special icons have no text.
            if utils.is_special_id(item_id):
                self._ui_button_set_text(button, TransToken.BLANK)
            else:
                self._ui_button_set_text(button, data.short_name)

            group_key = data.group_id
            grouped_items[group_key].append(item_id)
            await trio.lowlevel.checkpoint()

            if group_key not in self.group_names:
                self.group_names[group_key] = data.group
            self._ui_group_create(
                group_key,
                self.group_names[group_key],
            )
            self._ui_menu_add(
                group_key,
                item_id,
                functools.partial(self.sel_item_id, item_id),
                data.context_lbl,
            )

        # Convert to a normal dictionary, after adding all items.
        self.grouped_items = dict(grouped_items)

        # Figure out the order for the groups - alphabetical.
        # Note - empty string should sort to the beginning!
        self.group_order[:] = sorted(self.grouped_items.keys())

        for group_key in self.group_order:
            self.group_visible[group_key] = True
            await trio.lowlevel.checkpoint()
            # Don't add the ungrouped menu to itself!
            if group_key != '':
                self._ui_group_add(group_key, self.group_names[group_key])

    def _attr_widget_positions(self) -> Iterator[tuple[
        AttrDef, int,
        Literal['left', 'right', 'wide'],
    ]]:
        """Positions all the required attribute widgets.

        Yields (attr, row, col_type) tuples.
        """
        self.attrs.sort(key=lambda at: 0 if at.type.is_wide else 1)
        index = 0
        for attr in self.attrs:
            # Wide ones have their own row, narrow ones are two to a row.
            if attr.type.is_wide:
                if index % 2:  # Row has a single narrow, skip the empty space.
                    index += 1
                yield attr, index // 2, 'wide'
                index += 2
            else:
                if index % 2:
                    yield attr, index // 2, 'right'
                else:
                    yield attr, index // 2, 'left'
                index += 1

    async def _refresh_items_task(self) -> None:
        """Calls refresh_items whenever they're marked dirty."""
        while True:
            await self.items_dirty.wait()
            await self._ui_reposition_items()
            self.items_dirty = trio.Event()
    async def _rollover_suggest_task(self) -> None:
        """Handle previewing suggested items when hovering over the 'set suggested' button."""
        while True:
            await self.suggested_rollover_active.wait_value(True)
            async with trio_util.move_on_when(
                self.suggested_rollover_active.wait_value, False,
            ):
                if self.suggested:
                    while True:
                        self._suggested_rollover = random.choice(self.suggested)
                        self.set_disp()
                        await trio.sleep(1.0)
                else:
                    # If there's nothing to suggest, wait until the button is re-hovered.
                    await trio.sleep_forever()
            self._suggested_rollover = None
            self.set_disp()

    def exit(self, _: object = None) -> None:
        """Quit and cancel, choosing the originally-selected item."""
        self.selected = self.chosen.value
        self.save()

    def save(self, _: object = None) -> None:
        """Save the selected item, close the window.."""
        # Stop sample sounds if they're playing
        if self.sampler is not None:
            self.sampler.stop()

        for button in self._item_buttons:
            # Un-press everything, clear icons to allow them to unload.
            self._ui_button_set_selected(button, False)
            self._ui_button_set_img(button, None)

        if not self.first_open:  # We've got state to store.
            width, height = self._ui_win_get_size()
            state = SelectorState(
                open_groups=self.group_visible.copy(),
                width=width,
                height=height,
            )
            config.APP.store_conf(state, self.save_id)

        self._ui_win_hide()
        self._visible = False
        self.choose_item(self.selected)
        self._ui_props_set_desc(MarkdownData.BLANK)  # Free resources used.

    def set_disp(self) -> None:
        """Update the display textbox."""
        text: TransToken | None = None
        font: DispFont

        # Lots of states which override each other.
        if self._loading:
            enabled = False
            font = 'normal'
            tooltip = TransToken.BLANK
            text = TRANS_LOADING
        elif self._readonly:
            enabled = False
            font = 'normal'
            tooltip = self.readonly_description
            if self.readonly_override is not None:
                text = self.readonly_override
        else:
            # "Normal", can be edited.
            enabled = True
            tooltip = self.description
            if self._suggested_rollover is not None:
                font = 'mouseover'
            elif self.is_suggested():
                # Bold the text if the suggested item is selected
                # (like the context menu).
                font = 'suggested'
            else:
                font = 'normal'

        if text is None:
            # No override for the text is set, use the
            # suggested-rollover one, or the selected item.
            if self._suggested_rollover is not None:
                data = self._get_data(self._suggested_rollover)
            else:
                data = self._get_data(self.chosen.value)
            text = data.context_lbl

        self._ui_display_set(enabled=enabled, text=text, tooltip=tooltip, font=font)

    def _evt_button_click(self, index: int) -> None:
        """Handle clicking on an item.

        If it's already selected, save and close the window.
        """
        try:
            item_id = self.item_list[index]
        except IndexError:
            return  # Shouldn't be visible.
        if item_id == self.selected:
            self.save()
        else:
            self.sel_item_id(item_id)

    async def _load_selected_task(self) -> None:
        """When configs change, load new items."""
        selected: LastSelected
        with config.APP.get_ui_channel(LastSelected, self.save_id) as channel:
            async for selected in channel:
                self.sel_item_id(selected.id)
                self.save()

    async def _update_sampler_task(self) -> None:
        """Update the sampler's display."""
        assert self.sampler is not None
        async with aclosing(self.sampler.is_playing.eventual_values()) as agen:
            async for is_playing in agen:
                self._ui_props_set_samp_button_icon(BTN_STOP if is_playing else BTN_PLAY)

    def _evt_icon_clicked(self, event: object) -> None:
        """When the large image is clicked, play sounds if available."""
        if self.sampler is not None:
            self.sampler.play_sample()

    def _evt_group_clicked(self, group_key: str) -> None:
        """Toggle the header on or off."""
        self.group_visible[group_key] = not self.group_visible.get(group_key)
        self.items_dirty.set()

    def _evt_group_hover_start(self, group_key: str) -> None:
        """When hovered over, fill in the triangle."""
        self._ui_group_set_arrow(
            group_key,
            GRP_EXP_HOVER
            if self.group_visible.get(group_key) else
            GRP_COLL_HOVER
        )

    def _evt_group_hover_end(self, group_key: str) -> None:
        """When leaving, hollow the triangle."""
        self._ui_group_set_arrow(
            group_key,
            GRP_EXP
            if self.group_visible.get(group_key) else
            GRP_COLL
        )

    def open_win(self, _: object = None) -> object:
        """Display the window."""
        if self._readonly:
            TK_ROOT.bell()
            return 'break'  # Tell tk to stop processing this event

        for item_id, button in zip(self.item_list, self._item_buttons, strict=False):
            self._ui_button_set_img(button, self._get_data(item_id).icon)

        # Restore configured states.
        if self.first_open:
            self.first_open = False
            try:
                state = config.APP.get_cur_conf(SelectorState, self.save_id)
            except KeyError:
                pass
            else:
                LOGGER.debug(
                    'Restoring saved selectorwin state "{}" = {}',
                    self.save_id, state,
                )
                for grp_id, is_open in state.open_groups.items():
                    if grp_id in self.group_visible:
                        self.group_visible[grp_id] = is_open
                    else:  # Stale config, ignore.
                        LOGGER.warning(
                            '({}): invalid selectorwin group: "{}"',
                            self.save_id, grp_id,
                        )
                if state.width > 0 or state.height > 0:
                    width, height = self._ui_win_get_size()
                    if state.width > 0:
                        width = state.width
                    if state.height > 0:
                        height = state.height
                    self._ui_win_set_size(width, height)

        self._ui_win_show()
        self._visible = True
        self.sel_item(self.chosen.value)
        self.items_dirty.set()
        return None

    def sel_suggested(self) -> None:
        """Select the suggested item."""
        # Pick the hovered item.
        if self._suggested_rollover is not None:
            self.choose_item(self._suggested_rollover)
        # Not hovering, but we have some, randomly pick.
        elif self.suggested:
            # Do not re-pick the same item if we can avoid it.
            if self.selected in self.suggested and len(self.suggested) > 1:
                pool = self.suggested.copy()
                pool.remove(self.selected)
            else:
                pool = self.suggested
            self.choose_item(random.choice(pool))

    def sel_item_id(self, it_id: str) -> bool:
        """Select the item with the given ID."""
        item_id = utils.special_id(it_id)
        if item_id in self.item_list:
            self.choose_item(item_id)
            return True
        return False

    def choose_item(self, item_id: utils.SpecialID) -> None:
        """Set the current item to this one."""
        if self._visible:
            # Only update UI if it is actually visible.
            self.sel_item(item_id)
        self.chosen.value = item_id
        self.set_disp()
        if self.store_last_selected:
            config.APP.store_conf(LastSelected(item_id), self.save_id)

    def sel_item(self, item_id: utils.SpecialID, _: object = None) -> None:
        """Select the specified item in the UI, but don't actually choose it."""
        data = self._get_data(item_id)

        self._ui_props_set_name(data.name)
        if utils.is_special_id(item_id):
            self._ui_props_set_author(TransToken.BLANK)
        elif len(data.auth) == 0:
            self._ui_props_set_author(TRANS_NO_AUTHORS)
        else:
            self._ui_props_set_author(TRANS_AUTHORS.format(
                authors=TransToken.list_and(TransToken.untranslated(auth) for auth in data.auth),
                n=len(data.auth),
            ))

        self._ui_props_set_icon(data.large_icon)

        if DEV_MODE.value:
            # Show the ID of the item in the description
            text = MarkdownData(TRANS_DEV_ITEM_ID.format(
                item=f'`{', '.join(data.packages)}`:`{item_id}`\n' if data.packages else f'`{item_id}`\n',
            ), None)
            self._ui_props_set_desc(text + data.desc)
        else:
            self._ui_props_set_desc(data.desc)

        try:
            button = self._id_to_button[self.selected]
        except KeyError:
            pass
        else:
            self._ui_button_set_selected(button, False)
        try:
            button = self._id_to_button[item_id]
        except KeyError:
            # Should never happen, but don't crash...
            LOGGER.warning('No button for item {}??', item_id)
        else:
            self._ui_button_set_selected(button, True)
            self._ui_button_scroll_to(button)

        self.selected = item_id

        if self.sampler:
            assert self.func_get_sample is not None
            is_playing = self.sampler.is_playing.value
            self.sampler.stop()

            self.sampler.cur_file = self.func_get_sample(self._packset, item_id)
            if self.sampler.cur_file:
                self._ui_props_set_samp_button_enabled(True)
                if is_playing:
                    # Start the sampler again, so it plays the current item!
                    self.sampler.play_sample()
            else:
                self._ui_props_set_samp_button_enabled(False)

        if self.has_def:
            self._ui_enable_reset(self.can_suggest())

        # Set the attribute items.
        try:
            item_attrs = self.func_get_attr(self._packset, item_id)
        except KeyError:
            LOGGER.warning(
                'Selectorwin {}: item {} did not exist when fetching attributes?',
                self.save_id, item_id,
            )
            item_attrs = EmptyMapping
        for attr in self.attrs:
            val = item_attrs.get(attr.id, attr.default)
            match attr.type:
                case AttrTypes.BOOL:
                    self._ui_attr_set_image(attr, ICON_CHECK if val else ICON_CROSS)
                case AttrTypes.COLOUR:
                    assert isinstance(val, Vec)
                    self._ui_attr_set_image(attr, img.Handle.color(val, 16, 16))
                    # Display the full color when hovering...
                    self._ui_attr_set_tooltip(attr, TRANS_ATTR_COLOR.format(
                        r=int(val.x), g=int(val.y), b=int(val.z),
                    ))
                case AttrTypes.LIST_OR | AttrTypes.LIST_AND:
                    # Join the values (in alphabetical order)
                    assert isinstance(val, Iterable) and not isinstance(val, Vec), repr(val)
                    children = [
                        txt if isinstance(txt, TransToken) else TransToken.untranslated(txt)
                        for txt in val
                    ]
                    if attr.type is AttrTypes.LIST_AND:
                        self._ui_attr_set_text(attr, TransToken.list_and(children, sort=True))
                    else:
                        self._ui_attr_set_text(attr, TransToken.list_or(children, sort=True))
                case AttrTypes.STRING:
                    # Just a string.
                    if not isinstance(val, TransToken):
                        val = TransToken.untranslated(str(val))
                    self._ui_attr_set_text(attr, val)
                case _:
                    assert_never(attr.type)

    def key_navigate(self, key: NavKeys) -> None:
        """Navigate using arrow keys."""

        if key is NavKeys.PLAY_SOUND:
            if self.sampler is not None:
                self.sampler.play_sample()
            return
        elif key is NavKeys.ENTER:
            self.save()
            return

        cur_group_name = self._get_data(self.selected).group_id
        cur_group = self.grouped_items[cur_group_name]
        # Force the current group to be visible, so you can see what's
        # happening.
        self.group_visible[cur_group_name] = True

        # A list of groups names, in the order that they're visible onscreen
        # (skipping hidden ones). Force-include
        ordered_groups = [
            group_name
            for group_name in self.group_order
            if self.group_visible.get(group_name)
        ]

        if not ordered_groups:
            return  # No visible items!

        if key is NavKeys.HOME:
            self._offset_select(
                ordered_groups,
                group_ind=-1,
                item_ind=0,
            )
            return
        elif key is NavKeys.END:
            self._offset_select(
                ordered_groups,
                group_ind=len(ordered_groups),
                item_ind=0,
            )
            return

        # The index in the current group for an item
        try:
            item_ind = cur_group.index(self.selected)
        except IndexError:
            return  # Not present?
        # The index in the visible groups
        group_ind = ordered_groups.index(cur_group_name)

        if key is NavKeys.LEFT:
            item_ind -= 1
        elif key is NavKeys.RIGHT:
            item_ind += 1
        elif key is NavKeys.UP:
            item_ind -= self.item_width
        elif key is NavKeys.DOWN:
            item_ind += self.item_width
        else:
            assert_never(key)

        self._offset_select(
            ordered_groups,
            group_ind,
            item_ind,
            key is NavKeys.UP or key is NavKeys.DOWN,
        )

    def _offset_select(self, group_list: list[str], group_ind: int, item_ind: int, is_vert: bool = False) -> None:
        """Helper for key_navigate(), jump to the given index in a group.

        group_list is sorted list of group names.
        group_ind is the index of the current group, and item_ind is the index
        in that group to move to.
        If the index is above or below, it will jump to neighbouring groups.
        """
        if group_ind < 0:  # Jump to the first item, out of bounds
            first_group = self.grouped_items[self.group_order[0]]
            self.sel_item(first_group[0])
            return
        elif group_ind >= len(group_list):  # Ditto, last group
            last_group = self.grouped_items[self.group_order[-1]]
            self.sel_item(last_group[-1])
            return

        cur_group = self.grouped_items[group_list[group_ind]]

        # Go back a group...
        if item_ind < 0:
            if group_ind == 0:  # First group - can't go back further!
                self.sel_item(cur_group[0])
            else:
                prev_group = self.grouped_items[group_list[group_ind - 1]]
                if is_vert:
                    # Jump to the same horizontal position..
                    row_num = math.ceil(len(prev_group) / self.item_width)
                    item_ind += row_num * self.item_width
                    if item_ind >= len(prev_group):
                        # The last row is missing an item at this spot.
                        # Jump back another row again.
                        item_ind -= self.item_width
                else:
                    item_ind += len(prev_group)
                # Recurse to check the previous group..
                self._offset_select(
                    group_list,
                    group_ind - 1,
                    item_ind,
                )

        # Go forward a group...
        elif item_ind >= len(cur_group):
            #  Last group - can't go forward further!
            if group_ind == len(group_list):
                self.sel_item(cur_group[-1])
            else:
                # Recurse to check the next group...
                if is_vert:
                    # We just jump to the same horizontal position.
                    item_ind %= self.item_width
                else:
                    item_ind -= len(cur_group)

                self._offset_select(
                    group_list,
                    group_ind + 1,
                    item_ind,
                )

        else:  # Within this group
            self.sel_item(cur_group[item_ind])

    def is_suggested(self) -> bool:
        """Return whether the current item is a suggested one."""
        return self.chosen.value in self.suggested

    def can_suggest(self) -> bool:
        """Check if a new item can be suggested."""
        if not self.suggested:
            return False
        if len(self.suggested) > 1:
            return True
        # If we suggest one item which is selected, that's
        # pointless.
        return self.suggested != [self.chosen.value]

    def set_suggested(self, suggested: Container[str] = ()) -> None:
        """Set the suggested items to the set of IDs.

        If it is empty, the suggested ID will be cleared.
        """
        self.suggested.clear()
        self._ui_menu_reset_suggested()

        for item_id in self.item_list:
            if item_id in suggested:
                self._ui_menu_set_font(item_id, True)
                self.suggested.append(item_id)
            else:
                self._ui_menu_set_font(item_id, False)

        self.set_disp()  # Update the textbox if necessary.
        # Reposition all our items, but only if we're visible.
        if self._visible:
            self.items_dirty.set()

    async def _ui_task(self) -> None:
        """Executed by task() to allow updating the UI."""
        # Not abstract, will just exit if not overridden.

    @abstractmethod
    def _ui_win_hide(self, /) -> None:
        """Close the window."""
        raise NotImplementedError

    @abstractmethod
    def _ui_win_show(self, /) -> None:
        """Show the window, centred on the parent."""
        raise NotImplementedError

    @abstractmethod
    def _ui_win_get_size(self, /) -> tuple[int, int]:
        """Get the current size, for storing in configs."""
        raise NotImplementedError

    @abstractmethod
    def _ui_win_set_size(self, width: int, height: int, /) -> None:
        """Apply size from configs."""
        raise NotImplementedError

    @abstractmethod
    async def _ui_reposition_items(self) -> None:
        """Reposition all the items to fit in the current geometry.

        Called whenever items change or the window is resized.
        """
        raise NotImplementedError

    @abstractmethod
    def _ui_button_create(self, ind: int, /) -> ButtonT:
        """Create a new button widget for the main item list.

        The index should be passed to `_evt_button_click()`.
        """
        raise NotImplementedError

    @abstractmethod
    def _ui_button_set_text(self, button: ButtonT, text: TransToken, /) -> None:
        """Change the text on a button. If set to BLANK, only the icon is shown."""
        raise NotImplementedError

    @abstractmethod
    def _ui_button_set_img(self, button: ButtonT, image: img.Handle | None, /) -> None:
        """Set the icon for a button, or clear it if None."""
        raise NotImplementedError

    @abstractmethod
    def _ui_button_set_selected(self, button: ButtonT, selected: bool, /) -> None:
        """Set whether the button should be highlighted as if selected."""
        raise NotImplementedError

    @abstractmethod
    def _ui_button_hide(self, button: ButtonT, /) -> None:
        """Hide this button, it is no longer necessary."""
        raise NotImplementedError

    @abstractmethod
    def _ui_button_set_pos(self, button: ButtonT, /, x: int, y: int) -> None:
        """Place this button at the specified location."""
        raise NotImplementedError

    @abstractmethod
    def _ui_button_scroll_to(self, button: ButtonT, /) -> None:
        """Scroll to an item so it's visible."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_author(self, author: TransToken, /) -> None:
        """Set the author text for the selected item."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_name(self, name: TransToken, /) -> None:
        """Set the name text for the selected item."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_desc(self, desc: MarkdownData, /) -> None:
        """Set the description for the selected item."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_icon(self, image: img.Handle, /) -> None:
        """Set the large icon's image, and whether to show a zoom-in cursor."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_samp_button_enabled(self, enabled: bool, /) -> None:
        """Set whether the sample button is enabled."""
        raise NotImplementedError

    @abstractmethod
    def _ui_props_set_samp_button_icon(self, glyph: str, /) -> None:
        """Set the icon in the play-sample button."""
        raise NotImplementedError

    @abstractmethod
    def _ui_attr_set_text(self, attr: AttrDef, text: TransToken, /) -> None:
        """Set the value of a text-style attribute widget."""
        raise NotImplementedError

    @abstractmethod
    def _ui_attr_set_image(self, attr: AttrDef, image: img.Handle, /) -> None:
        """Set the image for an image-style attribute widget."""
        raise NotImplementedError

    @abstractmethod
    def _ui_attr_set_tooltip(self, attr: AttrDef, tooltip: TransToken, /) -> None:
        """Set the hover tooltip. This only applies to image-style widgets."""
        raise NotImplementedError

    @abstractmethod
    def _ui_menu_clear(self) -> None:
        """Remove all items from the main context menu, as well as clear the group widgets."""
        raise NotImplementedError

    @abstractmethod
    def _ui_menu_set_font(self, item_id: utils.SpecialID, /, suggested: bool) -> None:
        """Set the font of an item, and its parent group."""
        raise NotImplementedError

    @abstractmethod
    def _ui_menu_reset_suggested(self) -> None:
        """Reset the fonts for all group widgets. menu_set_font() will then set them."""
        raise NotImplementedError

    @abstractmethod
    def _ui_menu_add(self, group_key: str, item: utils.SpecialID, func: Callable[[], object], label: TransToken, /) -> None:
        """Add a radio-selection menu option for this item."""
        raise NotImplementedError

    @abstractmethod
    def _ui_group_create(self, key: str, label: TransToken) -> None:
        """Ensure a group exists with this key, and text."""
        raise NotImplementedError

    @abstractmethod
    def _ui_group_add(self, key: str, name: TransToken) -> None:
        """Add the specified group to the rightclick menu."""
        raise NotImplementedError

    @abstractmethod
    def _ui_group_set_arrow(self, key: str, arrow: str) -> None:
        """Set the arrow for a group widget."""
        raise NotImplementedError

    @abstractmethod
    def _ui_enable_reset(self, enabled: bool, /) -> None:
        """Set whether the 'reset to default' button can be used."""
        raise NotImplementedError

    @abstractmethod
    def _ui_display_set(
        self, *,
        enabled: bool,
        text: TransToken,
        tooltip: TransToken,
        font: DispFont,
    ) -> None:
        """Set the state of the display textbox and button."""
