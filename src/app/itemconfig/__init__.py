"""Customizable configuration for specific items or groups of them."""
from __future__ import annotations
from typing import Any
from typing_extensions import Protocol

from collections.abc import Awaitable, Callable, Mapping, Iterator
from datetime import timedelta
from tkinter import ttk
import tkinter as tk
import functools

from srctools import logger
from trio_util import AsyncValue
import trio

import utils
from app import EdgeTrigger, UI, sound, StyleVarPane
from ui_tk.tooltip import add_tooltip
# Re-export.
from config.widgets import (
    WidgetConfig, TimerNum as TimerNum, TIMER_NUM as TIMER_NUM,
    TIMER_STR_INF as TIMER_STR_INF,
)
from packages.widgets import (
    CLS_TO_KIND, ConfT, ConfigGroup, ItemVariantConf, OptConfT_contra,
    WidgetType,
    WidgetTypeWithConf,
)
from packages.signage import ITEM_ID as SIGNAGE_ITEM_ID
from transtoken import TransToken, CURRENT_LANG

from app.SubPane import SubPane
from app.tkMarkdown import MarkdownData
from ui_tk.img import TKImages
from ui_tk.wid_transtoken import set_text
from ui_tk import TK_ROOT, tk_tools
import config
import packages

LOGGER = logger.get_logger(__name__)


class SingleCreateTask(Protocol[OptConfT_contra]):
    """A task which creates a widget. 
    
    It is passed a parent frame, the configuration object, and the async value involved.
    The widget to be installed should be passed to started().
    """
    def __call__(
        self, parent: tk.Widget, tk_img: TKImages,
        holder: AsyncValue[str],
        config: OptConfT_contra,
        /, *, task_status: trio.TaskStatus[tk.Widget] = ...,
    ) -> Awaitable[None]: ...


class SingleCreateNoConfTask(Protocol):
    """Variant protocol for a widget that needs no configuration."""
    def __call__(
        self, parent: tk.Widget, tk_img: TKImages,
        holder: AsyncValue[str],
        /, *, task_status: trio.TaskStatus[tk.Widget] = ...,
    ) -> Awaitable[None]: ...


# Override for timer-type widgets to be more compact - passed a list of timer numbers instead.
# The widgets should insert themselves into the parent frame.
# It then yields timer_val, update-func pairs.
class MultiCreateTask(Protocol[OptConfT_contra]):
    """Override for timer-type widgets to be more compact.

    It is passed a parent frame, the configuration object, and the async value involved.
    The widgets should insert themselves into the parent frame.
    """
    def __call__(
        self, parent: tk.Widget, tk_img: TKImages,
        holders: Mapping[TimerNum, AsyncValue[str]],
        config: OptConfT_contra,
        /, *, task_status: trio.TaskStatus[None] = ...,
    ) -> Awaitable[None]: ...


class MultiCreateNoConfTask(Protocol):
    """Variant protocol for a timer-type widget set that needs no configuration."""
    def __call__(
        self, parent: tk.Widget, tk_img: TKImages,
        holders: Mapping[TimerNum, AsyncValue[str]],
        /, *, task_status: trio.TaskStatus[None] = ...,
    ) -> Awaitable[None]: ...


# The functions registered for each.
_UI_IMPL_SINGLE: dict[WidgetType, SingleCreateTask[Any]] = {}
_UI_IMPL_MULTI: dict[WidgetType, MultiCreateTask[Any]] = {}

INF = TransToken.untranslated('∞')
TIMER_NUM_TRANS: dict[TimerNum, TransToken] = {
    num: TransToken.untranslated('{delta:ms}').format(delta=timedelta(seconds=float(num)))
    for num in TIMER_NUM
}
TIMER_NUM_TRANS[TIMER_STR_INF] = INF
TRANS_COLON = TransToken.untranslated('{text}: ')
TRANS_GROUP_HEADER = TransToken.ui('{name} ({page}/{count})')  # i18n: Header layout for Item Properties pane.
# For the item-variant widget, we need to refresh on style changes.
ITEM_VARIANT_LOAD: list[tuple[str, Callable[[], object]]] = []

window: SubPane | None = None


def ui_single_wconf(cls: type[ConfT]) -> Callable[[SingleCreateTask[ConfT]], SingleCreateTask[
    ConfT]]:
    """Register the UI function used for singular widgets with configs."""
    kind = CLS_TO_KIND[cls]

    def deco(func: SingleCreateTask[ConfT]) -> SingleCreateTask[ConfT]:
        """Do the registration."""
        _UI_IMPL_SINGLE[kind] = func
        return func
    return deco


def ui_single_no_conf(kind: WidgetType) -> Callable[[SingleCreateNoConfTask], SingleCreateNoConfTask]:
    """Register the UI function used for singular widgets without configs."""
    def deco(func: SingleCreateNoConfTask) -> SingleCreateNoConfTask:
        """Do the registration."""
        def wrapper(
            parent: tk.Widget, tk_img: TKImages,
            holder: AsyncValue[str],
            config: None,
            /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
        ) -> Awaitable[None]:
            """Don't pass the config through to the UI function."""
            assert config is None
            return func(parent, tk_img, holder, task_status=task_status)

        if isinstance(kind, WidgetTypeWithConf):
            raise TypeError('Widget type has config, but singular function does not!')
        _UI_IMPL_SINGLE[kind] = wrapper
        return func
    return deco


def ui_multi_wconf(cls: type[ConfT]) -> Callable[[MultiCreateTask[ConfT]], MultiCreateTask[ConfT]]:
    """Register the UI function used for multi widgets with configs."""
    kind = CLS_TO_KIND[cls]

    def deco(func: MultiCreateTask[ConfT]) -> MultiCreateTask[ConfT]:
        """Do the registration."""
        _UI_IMPL_MULTI[kind] = func
        return func
    return deco


def ui_multi_no_conf(kind: WidgetType) -> Callable[[MultiCreateNoConfTask], MultiCreateNoConfTask]:
    """Register the UI function used for multi widgets without configs."""
    def deco(func: MultiCreateNoConfTask) -> MultiCreateNoConfTask:
        """Do the registration."""
        def wrapper(
            parent: tk.Widget, tk_img: TKImages,
            holders: Mapping[TimerNum, AsyncValue[str]],
            config: None,
            /, *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
        ) -> Awaitable[None]:
            """Don't pass the config through to the UI function."""
            assert config is None
            return func(parent, tk_img, holders, task_status=task_status)

        if isinstance(kind, WidgetTypeWithConf):
            raise TypeError('Widget type has config, but multi function does not!')
        _UI_IMPL_MULTI[kind] = wrapper
        return func
    return deco


async def create_group(
    master: ttk.Frame,
    nursery: trio.Nursery,
    tk_img: TKImages,
    signage_trigger: EdgeTrigger[()],
    group: ConfigGroup,
) -> ttk.Frame:
    """Create the widgets for a group."""
    frame = ttk.Frame(master)
    frame.columnconfigure(0, weight=1)
    row = 0

    widget_count = len(group.widgets) + len(group.multi_widgets)
    wid_frame: tk.Widget
    widget: tk.Widget

    # Now make the widgets.
    if group.widgets:
        for row, s_wid in enumerate(group.widgets):
            wid_frame = ttk.Frame(frame)
            wid_frame.grid(row=row, column=0, sticky='ew')
            wid_frame.columnconfigure(1, weight=1)
            await trio.sleep(0)

            label: ttk.Label | None = None
            if s_wid.name:
                if s_wid.kind.is_wide:
                    wid_frame = set_text(
                        ttk.LabelFrame(wid_frame),
                        TRANS_COLON.format(text=s_wid.name),
                    )
                    wid_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=5)
                    wid_frame.columnconfigure(0, weight=1)
                else:
                    label = ttk.Label(wid_frame)
                    set_text(label, TRANS_COLON.format(text=s_wid.name))
                    label.grid(row=0, column=0)
            create_func = _UI_IMPL_SINGLE[s_wid.kind]

            conf = s_wid.config
            if isinstance(conf, ItemVariantConf) and conf.item_id == SIGNAGE_ITEM_ID:
                # Special case. This is a trigger to display the "Configure Signage" button.
                # Replace the config with the edge trigger, signalling the creation func below
                # to handle this.
                conf = signage_trigger

            try:
                with logger.context(f'{group.id}:{s_wid.id}'):
                    LOGGER.debug('Constructing widget with config {!r}...', conf)
                    widget = await nursery.start(create_func, wid_frame, tk_img, s_wid.holder, conf)
            except Exception:
                LOGGER.exception('Could not construct widget {}.{}', group.id, s_wid.id)
                continue
            if label is not None:
                widget.grid(row=0, column=1, sticky='e')
                if isinstance(widget, ttk.Checkbutton):
                    # Special case - allow clicking on the label to toggle checkbuttons.
                    tk_tools.link_checkmark(widget, label)
            else:
                widget.grid(row=0, column=0, columnspan=2, sticky='ew')
            if s_wid.has_values:
                await config.APP.set_and_run_ui_callback(
                    WidgetConfig, s_wid.apply_conf, f'{s_wid.group_id}:{s_wid.id}',
                )
            nursery.start_soon(s_wid.state_store_task)
            if s_wid.tooltip:
                add_tooltip(widget, s_wid.tooltip)
                if label is not None:
                    add_tooltip(label, s_wid.tooltip)
                add_tooltip(wid_frame, s_wid.tooltip)

    if group.widgets and group.multi_widgets:
        ttk.Separator(orient='horizontal').grid(row=1, column=0, sticky='ew')

    # Continue from wherever we were.
    for row, m_wid in enumerate(group.multi_widgets, start=row + 1):  # noqa: B020
        # If we only have 1 widget, don't add a redundant title.
        if widget_count == 1 or not m_wid.name:
            wid_frame = ttk.Frame(frame)
        else:
            wid_frame = set_text(
                ttk.LabelFrame(frame),
                TRANS_COLON.format(text=m_wid.name),
            )

        try:
            multi_func = _UI_IMPL_MULTI[m_wid.kind]
        except KeyError:
            multi_func = widget_timer_generic(_UI_IMPL_SINGLE[m_wid.kind])

        wid_frame.grid(row=row, column=0, sticky='ew', pady=5)
        try:
            with logger.context(f'{group.id}:{m_wid.id}'):
                LOGGER.debug('Constructing widget with config {!r}...', m_wid.config)
                await nursery.start(
                    multi_func,
                    wid_frame, tk_img,
                    m_wid.holders,
                    m_wid.config,
                )
        except Exception:
            LOGGER.exception('Could not construct widget {}.{}', group.id, m_wid.id)
            continue
        await config.APP.set_and_run_ui_callback(
            WidgetConfig, m_wid.apply_conf, f'{m_wid.group_id}:{m_wid.id}',
        )
        nursery.start_soon(m_wid.state_store_task)
        await trio.sleep(0)

        if m_wid.tooltip:
            add_tooltip(wid_frame, m_wid.tooltip)
    return frame


# Special group injected for the stylevar display.
STYLEVAR_GROUP = ConfigGroup(
    '_STYLEVAR',
    TransToken.ui('Style Properties'),
    MarkdownData.BLANK,
    [], [],
)


async def make_pane(
    tool_frame: tk.Frame | ttk.Frame,
    menu_bar: tk.Menu,
    tk_img: TKImages,
    signage_trigger: EdgeTrigger[()],
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create the item properties pane, with the widgets it uses."""
    global window

    window = SubPane(
        TK_ROOT, tk_img,
        title=TransToken.ui('Style/Item Properties'),
        name='item',
        legacy_name='style',
        menu_bar=menu_bar,
        resize_y=True,
        tool_frame=tool_frame,
        tool_img='icons/win_itemvar',
        tool_col=12,
    )

    ordered_conf: list[ConfigGroup] = sorted(
        packages.get_loaded_packages().all_obj(ConfigGroup),
        key=lambda grp: str(grp.name),
    )
    ordered_conf.insert(0, STYLEVAR_GROUP)

    selection_frame = ttk.Frame(window)
    selection_frame.grid(row=0, column=0, columnspan=2, sticky='ew')

    arrow_left = ttk.Button(
        selection_frame,
        text='◀', width=2,
        command=lambda: select_directional(-1),
    )
    group_label = ttk.Label(
        selection_frame,
        text='Group Name', anchor='center',
        cursor=tk_tools.Cursors.LINK,
    )
    arrow_right = ttk.Button(
        selection_frame,
        text='▶', width=2,
        command=lambda: select_directional(+1),
    )

    arrow_left.grid(row=0, column=0)
    group_label.grid(row=0, column=1, sticky='ew')
    selection_frame.columnconfigure(1, weight=1)
    arrow_right.grid(row=0, column=2)

    label_font = tk.font.nametofont('TkHeadingFont').copy()
    label_font.config(weight='bold')
    group_label['font'] = label_font

    group_label.bind('<Enter>', f'{group_label} configure -foreground "#2873FF"')
    group_label.bind('<Leave>', f'{group_label} configure -foreground ""')

    group_menu = tk.Menu(group_label, tearoff=False)
    group_var = tk.StringVar(window)

    ttk.Separator(window, orient='horizontal').grid(
        row=1, column=0, columnspan=2,
        sticky='EW', pady=2,
    )

    # Need to use a canvas to allow scrolling.
    canvas = tk.Canvas(window, highlightthickness=0, name='scrollcanv')
    canvas.grid(row=2, column=0, sticky='NSEW', padx=(5, 0))
    window.columnconfigure(0, weight=1)
    window.rowconfigure(2, weight=1)

    scrollbar = ttk.Scrollbar(
        window,
        orient='vertical',
        command=canvas.yview,
    )
    scrollbar.grid(row=2, column=1, sticky="ns")
    canvas['yscrollcommand'] = scrollbar.set

    tk_tools.add_mousewheel(canvas, canvas, window)
    canvas_frame = ttk.Frame(canvas)
    frame_winid = canvas.create_window(0, 0, window=canvas_frame, anchor="nw")
    canvas_frame.columnconfigure(0, weight=1)
    canvas_frame.rowconfigure(1, weight=1)

    stylevar_frame = ttk.Frame(canvas_frame)
    await utils.run_as_task(
        StyleVarPane.make_stylevar_pane,
        stylevar_frame,
        packages.get_loaded_packages(),
    )

    loading_text = ttk.Label(canvas_frame)
    set_text(loading_text, TransToken.ui('Loading...'))
    loading_text.grid(row=0, column=0, sticky='ew')
    loading_text.grid_forget()

    group_to_frame: dict[ConfigGroup, ttk.Frame] = {
        STYLEVAR_GROUP: stylevar_frame,
    }
    groups_being_created: set[ConfigGroup] = set()
    cur_group = STYLEVAR_GROUP
    win_max_width = 0

    async def display_group(group: ConfigGroup) -> None:
        """Callback to display the group in the UI, once constructed."""
        nonlocal win_max_width
        if cur_group is not group:
            return
        if loading_text.winfo_ismapped():
            loading_text.grid_forget()
        ui_frame = group_to_frame[group]
        ui_frame.grid(row=1, column=0, sticky='ew')
        await tk_tools.wait_eventloop()
        width = ui_frame.winfo_reqwidth()
        canvas['scrollregion'] = (
            0, 0,
            width,
            ui_frame.winfo_reqheight()
        )
        if width > win_max_width:
            canvas['width'] = width
            win_max_width = width
            scroll_width = scrollbar.winfo_width() + 10
            window.geometry(f'{width + scroll_width}x{window.winfo_height()}')
        canvas.itemconfigure(frame_winid, width=win_max_width)

    def select_group(group: ConfigGroup) -> None:
        """Callback when the combobox is changed."""
        nonlocal cur_group
        new_group = group
        if new_group is cur_group:  # Pointless to reselect.
            return
        if cur_group in group_to_frame:
            group_to_frame[cur_group].grid_forget()
        cur_group = new_group
        update_disp()
        if new_group in group_to_frame:
            # Ready, add.
            nursery.start_soon(display_group, new_group)
        else:  # Begin creating, or loading.
            loading_text.grid(row=0, column=0, sticky='ew')
            if new_group not in groups_being_created:
                LOGGER.info('Creating group: "{}"...', group.id)

                async def task() -> None:
                    """Create the widgets, then display."""
                    group_to_frame[new_group] = await create_group(
                        canvas_frame, nursery, tk_img, signage_trigger,
                        new_group,
                    )
                    groups_being_created.discard(new_group)
                    await display_group(new_group)

                nursery.start_soon(task)
                groups_being_created.add(new_group)

    def select_directional(direction: int) -> None:
        """Change the selection in some direction."""
        # Clamp to ±1 since scrolling can send larger numbers.
        pos = ordered_conf.index(cur_group) + (+1 if direction > 0 else -1)
        if 0 <= pos < len(ordered_conf):
            select_group(ordered_conf[pos])

    def update_disp() -> None:
        """Update widgets if the group has changed."""
        set_text(group_label, TRANS_GROUP_HEADER.format(
            name=cur_group.name,
            page=ordered_conf.index(cur_group) + 1,
            count=len(ordered_conf),
        ))
        pos = ordered_conf.index(cur_group)
        group_var.set(cur_group.id)
        arrow_left.state(['disabled' if pos == 0 else '!disabled'])
        arrow_right.state(['disabled' if pos + 1 == len(ordered_conf) else '!disabled'])

    async def update_translations() -> None:
        """Update translations in the display, reordering if necessary."""
        # Stylevar always goes at the start.
        while True:
            ordered_conf.sort(key=lambda grp: (0 if grp is STYLEVAR_GROUP else 1, str(grp.name)))
            # Remake all the menu widgets.
            group_menu.delete(0, 'end')
            for group in ordered_conf:
                group_menu.insert_radiobutton(
                    'end', label=str(group.name),
                    variable=group_var, value=group.id,
                    command=functools.partial(select_group, group),
                )
            update_disp()
            await CURRENT_LANG.wait_transition()

    async with trio.open_nursery() as nursery:
        # Open the nursery before binding, to make sure it's valid.
        tk_tools.bind_leftclick(group_label, lambda evt: group_menu.post(evt.x_root, evt.y_root))
        tk_tools.bind_mousewheel([
            selection_frame, arrow_left, arrow_right, group_label,
        ], select_directional)

        nursery.start_soon(update_translations)
        await tk_tools.wait_eventloop()

        # Update canvas when the window resizes.
        canvas.bind('<Configure>', f'{canvas} configure -scrollregion [{canvas} bbox all]')
        await display_group(cur_group)
        task_status.started()
        await trio.sleep_forever()


def widget_timer_generic(widget_func: SingleCreateTask[ConfT]) -> MultiCreateTask[ConfT]:
    """For widgets without a multi version, do it generically."""
    async def generic_func(
        parent: tk.Widget,
        tk_img: TKImages,
        holders: Mapping[TimerNum, AsyncValue[str]],
        config: ConfT,
        /, *,
        task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """Generically make a set of labels."""
        async with trio.open_nursery() as nursery:
            for row, (tim_val, holder) in enumerate(holders.items()):
                timer_disp = TIMER_NUM_TRANS[tim_val]
                parent.columnconfigure(1, weight=1)

                label = ttk.Label(parent)
                set_text(label, TRANS_COLON.format(text=timer_disp))
                label.grid(row=row, column=0)
                widget = await nursery.start(
                    widget_func,
                    parent, tk_img, holder, config,
                )
                widget.grid(row=row, column=1, sticky='ew')
            task_status.started()

    return generic_func


def multi_grid(
    holders: Mapping[TimerNum, AsyncValue[str]],
    columns: int = 10,
) -> Iterator[tuple[int, int, TimerNum, TransToken, AsyncValue[str]]]:
    """Generate the row and columns needed for a nice layout of widgets."""
    for tim, holder in holders.items():
        if tim == 'inf':
            tim_disp = INF
            index = 0
        else:
            tim_disp = TIMER_NUM_TRANS[tim]
            index = int(tim)
        row, column = divmod(index - 1, columns)
        yield row, column, tim, tim_disp, holder


def widget_sfx(*args: object) -> None:
    """Play sounds when interacting."""
    sound.fx_blockable('config')


@ui_single_wconf(ItemVariantConf)
async def widget_item_variant(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    conf: ItemVariantConf | EdgeTrigger[()],
    /, *,
    task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Special widget - chooses item variants.

    This replicates the box on the right-click menu for items.
    It's special-cased in the above code in several ways.

    The config is alternatively an EdgeTrigger instance for the special Configure Signage button.
    """
    from app import contextWin

    if isinstance(conf, EdgeTrigger):
        # Even more special case, display the "configure signage" button.
        show_btn = ttk.Button(parent, command=conf.trigger)
        set_text(show_btn, TransToken.ui('Configure Signage'))

        task_status.started(show_btn)
        await tk_tools.apply_bool_enabled_state_task(conf.ready, show_btn)

    try:
        item = UI.item_list[conf.item_id]
    except KeyError:
        raise ValueError(f'Unknown item "{conf.item_id}"!') from None

    version_lookup: list[str] = []

    def update_data() -> None:
        """Refresh the data in the list."""
        nonlocal version_lookup
        version_lookup = contextWin.set_version_combobox(combobox, item)

    def change_callback(e: object = None) -> None:
        """Change the item version."""
        if version_lookup is not None:
            item.change_version(version_lookup[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        values=[''],
    )
    combobox.state(['readonly'])  # Prevent directly typing in values
    combobox.bind('<<ComboboxSelected>>', change_callback)

    load = (item.id, update_data)
    ITEM_VARIANT_LOAD.append(load)
    try:
        task_status.started(combobox)
        await trio.sleep_forever()
    finally:
        ITEM_VARIANT_LOAD.remove(load)


# Load all the widgets.
from . import checkmark, color, dropdown, slider, string, timer  # noqa: F401
