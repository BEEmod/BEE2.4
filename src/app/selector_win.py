"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from __future__ import annotations
from typing import Final, Literal, assert_never

from abc import abstractmethod
from tkinter import ttk
import tkinter as tk

from contextlib import aclosing
from collections.abc import Callable, Container, Iterable
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
from ui_tk.tooltip import set_tooltip
from ui_tk.img import TK_IMG
from ui_tk.wid_transtoken import set_menu_text, set_text
from ui_tk import TK_ROOT, tk_tools
from packages import SelitemData, AttrTypes, AttrDef as AttrDef, AttrMap
from consts import SEL_ICON_SIZE as ICON_SIZE
from transtoken import TransToken
from config.last_sel import LastSelected
from config.windows import SelectorState
import utils
import config
import packages


LOGGER = srctools.logger.get_logger(__name__)
ITEM_WIDTH = ICON_SIZE + (32 if utils.MAC else 16)
ITEM_HEIGHT = ICON_SIZE + 51

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


class GroupHeader:
    """The widget used for group headers."""
    def __init__(self, win: SelectorWinBase, title: TransToken, menu: tk.Menu) -> None:
        self.parent = win
        self.frame = frame = ttk.Frame(win.pal_frame)
        self.menu = menu  # The rightclick cascade widget.
        self.menu_pos = -1

        sep_left = ttk.Separator(frame)
        sep_left.grid(row=0, column=0, sticky='EW')
        frame.columnconfigure(0, weight=1)

        self.title = ttk.Label(
            frame,
            font='TkMenuFont',
            anchor='center',
        )
        set_text(self.title, title)
        self.title.grid(row=0, column=1)

        sep_right = ttk.Separator(frame)
        sep_right.grid(row=0, column=2, sticky='EW')
        frame.columnconfigure(2, weight=1)

        self.arrow = ttk.Label(
            frame,
            text=GRP_EXP,
            width=2,
        )
        self.arrow.grid(row=0, column=10)

        self._visible = True

        # For the mouse events to work, we need to bind on all the children too.
        widgets = frame.winfo_children()
        widgets.append(frame)
        for wid in widgets:
            tk_tools.bind_leftclick(wid, self.toggle)
            wid['cursor'] = tk_tools.Cursors.LINK
        frame.bind('<Enter>', self.hover_start)
        frame.bind('<Leave>', self.hover_end)

    @property
    def visible(self) -> bool:
        """Check if the contents are visible."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        """Set if the contents are visible."""
        value = bool(value)
        if value == self._visible:
            return  # Don't do anything..

        self._visible = value
        self.hover_start()  # Update arrow icon
        self.parent.flow_items()

    def toggle(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """Toggle the header on or off."""
        self.visible = not self._visible

    def hover_start(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """When hovered over, fill in the triangle."""
        self.arrow['text'] = (
            GRP_EXP_HOVER
            if self._visible else
            GRP_COLL_HOVER
        )

    def hover_end(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """When leaving, hollow the triangle."""
        self.arrow['text'] = (
            GRP_EXP
            if self._visible else
            GRP_COLL
        )


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


class SelectorWinBase[ButtonT, SuggLblT]:
    """The selection window for skyboxes, music, goo and voice packs.

    Typevars:
    - ButtonT: Type for the button widget.
    - SuggLblT: Type for the widget used to highlight suggested items.

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
    _suggest_lbl: list[SuggLblT]

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
    win: tk.Toplevel  # TODO move
    attrs: list[AttrDef]
    attr_labels: dict[str, ttk.Label]

    # Current list of item IDs we display.
    item_list: list[utils.SpecialID]
    # A map from group name -> header widget
    group_widgets: dict[str, GroupHeader]
    # A map from folded name -> display name
    group_names: dict[str, TransToken]
    # Group name -> items in that group.
    grouped_items: dict[str, list[utils.SpecialID]]
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

    desc_label: ttk.Label
    wid_canvas: tk.Canvas
    pal_frame: ttk.Frame

    sampler: sound.SamplePlayer | None

    context_menu: tk.Menu

    # The headers for the context menu
    context_menus: dict[str, tk.Menu]
    # The widget used to control which menu option is selected.
    context_var: tk.StringVar

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
        self._suggest_lbl = []

        # Should we have the 'reset to default' button?
        self.has_def = opt.has_def
        self.description = opt.desc
        self.readonly_description = opt.readonly_desc
        self.readonly_override = opt.readonly_override

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

        # A map from group name -> header widget
        self.group_widgets = {}
        # A map from folded name -> display name
        self.group_names = {}
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
            nursery.start_soon(self._load_data_task)
            nursery.start_soon(self._rollover_suggest_task)
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
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}
        self._menu_index.clear()
        self._id_to_button.clear()

        # First clear off the menu.
        self.context_menu.delete(0, 'end')

        for button in self._item_buttons:
            self._ui_button_hide(button)

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
            try:
                group = self.group_widgets[group_key]
            except KeyError:
                self.group_widgets[group_key] = group = GroupHeader(
                    self,
                    self.group_names[group_key],
                    tk.Menu(self.context_menu) if group_key else self.context_menu,
                )
            group.menu.add_radiobutton(
                command=functools.partial(self.sel_item_id, item_id),
                variable=self.context_var,
                value=item_id,
            )
            set_menu_text(group.menu, data.context_lbl)
            menu_pos = group.menu.index('end')
            assert menu_pos is not None, "Didn't add to the menu?"
            self._menu_index[item_id] = menu_pos

        # Convert to a normal dictionary, after adding all items.
        self.grouped_items = dict(grouped_items)

        # Figure out the order for the groups - alphabetical.
        # Note - empty string should sort to the beginning!
        self.group_order[:] = sorted(self.grouped_items.keys())

        for group_key in self.group_order:
            await trio.lowlevel.checkpoint()
            if group_key == '':
                # Don't add the ungrouped menu to itself!
                continue
            group = self.group_widgets[group_key]
            self.context_menu.add_cascade(menu=group.menu)
            set_menu_text(self.context_menu, self.group_names[group_key])
            # Track the menu's index. The one at the end is the one we just added.
            menu_pos = self.context_menu.index('end')
            assert menu_pos is not None, "Didn't add to the menu?"
            group.menu_pos = menu_pos

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
                open_groups={
                    grp_id: grp.visible
                    for grp_id, grp in self.group_widgets.items()
                },
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
        self.context_var.set(self.chosen.value)

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
                    try:
                        self.group_widgets[grp_id].visible = is_open
                    except KeyError:  # Stale config, ignore.
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
        self.win.after(2, self.flow_items)
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
            attr_label = self.attr_labels[attr.id]

            if attr.type is AttrTypes.BOOL:
                TK_IMG.apply(attr_label, ICON_CHECK if val else ICON_CROSS)
            elif attr.type is AttrTypes.COLOR:
                assert isinstance(val, Vec)
                TK_IMG.apply(attr_label, img.Handle.color(val, 16, 16))
                # Display the full color when hovering...
                set_tooltip(attr_label, TRANS_ATTR_COLOR.format(
                    r=int(val.x), g=int(val.y), b=int(val.z),
                ))
            elif attr.type.is_list:
                # Join the values (in alphabetical order)
                assert isinstance(val, Iterable) and not isinstance(val, Vec), repr(val)
                children = [
                    txt if isinstance(txt, TransToken) else TransToken.untranslated(txt)
                    for txt in val
                ]
                if attr.type is AttrTypes.LIST_AND:
                    set_text(attr_label, TransToken.list_and(children, sort=True))
                else:
                    set_text(attr_label, TransToken.list_or(children, sort=True))
            elif attr.type is AttrTypes.STRING:
                # Just a string.
                if not isinstance(val, TransToken):
                    val = TransToken.untranslated(str(val))
                set_text(attr_label, val)
            else:
                raise ValueError(f'Invalid attribute type: "{attr.type}"')

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
        self.group_widgets[cur_group_name].visible = True

        # A list of groups names, in the order that they're visible onscreen
        # (skipping hidden ones). Force-include
        ordered_groups = [
            group_name
            for group_name in self.group_order
            if self.group_widgets[group_name].visible
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

    def flow_items(self, _: object = None) -> None:
        """Reposition all the items to fit in the current geometry.

        Called on the <Configure> event.
        """
        self.pal_frame.update_idletasks()
        self.pal_frame['width'] = self.wid_canvas.winfo_width()
        self.desc_label['wraplength'] = self.win.winfo_width() - 10

        width = (self.wid_canvas.winfo_width() - 10) // ITEM_WIDTH
        if width < 1:
            width = 1  # we got way too small, prevent division by zero
        self.item_width = width

        # The offset for the current group
        y_off = 0

        # Hide suggestion indicators if they end up unused.
        for lbl in self._suggest_lbl:
            self._ui_sugg_hide(lbl)
        suggest_ind = 0

        # If only the '' group is present, force it to be visible, and hide
        # the header.
        no_groups = self.group_order == ['']

        for group_key in self.group_order:
            items = self.grouped_items[group_key]
            group_wid = self.group_widgets[group_key]

            if no_groups:
                group_wid.frame.place_forget()
            else:
                group_wid.frame.place(
                    x=0,
                    y=y_off,
                    width=width * ITEM_WIDTH,
                )
                group_wid.frame.update_idletasks()
                y_off += group_wid.frame.winfo_reqheight()

                if not group_wid.visible:
                    # Hide everything!
                    for item_id in items:
                        self._ui_button_hide(self._id_to_button[item_id])
                    continue

            # Place each item
            for i, item_id in enumerate(items):
                button = self._id_to_button[item_id]
                if item_id in self.suggested:
                    # Reuse an existing suggested label.
                    try:
                        sugg_lbl = self._suggest_lbl[suggest_ind]
                    except IndexError:
                        sugg_lbl = self._ui_sugg_create(suggest_ind)
                        self._suggest_lbl.append(sugg_lbl)
                    suggest_ind += 1
                    self._ui_sugg_place(
                        sugg_lbl, button,
                        x=(i % width) * ITEM_WIDTH + 1,
                        y=(i // width) * ITEM_HEIGHT + y_off,
                    )
                self._ui_button_set_pos(
                    button,
                    x=(i % width) * ITEM_WIDTH + 1,
                    y=(i // width) * ITEM_HEIGHT + y_off + 20,
                )

            # Increase the offset by the total height of this item section
            y_off += math.ceil(len(items) / width) * ITEM_HEIGHT + 5

        # Set the size of the canvas and frame to the amount we've used
        self.wid_canvas['scrollregion'] = (
            0, 0,
            width * ITEM_WIDTH,
            y_off,
        )
        self.pal_frame['height'] = y_off

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
            self.flow_items()

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
    def _ui_sugg_create(self, ind: int, /) -> SuggLblT:
        """Create a label for highlighting suggested buttons."""
        raise NotImplementedError

    @abstractmethod
    def _ui_sugg_hide(self, label: SuggLblT, /) -> None:
        """Hide the suggested button label."""
        raise NotImplementedError

    @abstractmethod
    def _ui_sugg_place(self, label: SuggLblT, button: ButtonT, /, x: int, y: int) -> None:
        """Place the suggested button label at this position."""
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
    def _ui_menu_set_font(self, item_id: utils.SpecialID, /, suggested: bool) -> None:
        """Set the font of an item, and its parent group."""
        raise NotImplementedError

    @abstractmethod
    def _ui_menu_reset_suggested(self) -> None:
        """Reset the fonts for all group widgets. menu_set_font() will then set them."""
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
