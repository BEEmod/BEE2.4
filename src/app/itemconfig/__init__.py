"""Customizable configuration for specific items or groups of them."""
from typing import (
    Iterable, Optional, Callable, List, Set, Tuple, Dict, Iterator, AsyncIterator,
    Awaitable, Type, Union,
)
from typing_extensions import TypeAlias
from datetime import timedelta
from tkinter import ttk
import tkinter as tk
import functools

from srctools import logger
import trio

from app import (
    TK_ROOT, UI, background_run, localisation, signage_ui, sound, tk_tools,
    StyleVarPane,
)
from app.tooltip import add_tooltip
# Re-export.
from config.widgets import (
    WidgetConfig, TimerNum as TimerNum, TIMER_NUM as TIMER_NUM,
    TIMER_STR_INF as TIMER_STR_INF,
)
from app.localisation import TransToken
import config
import packages
from packages.widgets import (
    CLS_TO_KIND, ConfT, ConfigGroup, ItemVariantConf, OptConfT, UpdateFunc,
    WidgetType,
    WidgetTypeWithConf, nop_update,
)
from ui_tk.img import TKImages
from ..SubPane import SubPane
from ..tkMarkdown import MarkdownData


LOGGER = logger.get_logger(__name__)


# This is called when a new value is loaded, to update the UI contents.
# This should be called when the value changes.
SingleChangeFunc: TypeAlias = Callable[[str], object]
# This variant is for multi-widget overrides.
MultiChangeFunc: TypeAlias = Callable[[TimerNum], SingleChangeFunc]

# Functions for each widget.
# The function is passed a parent frame, the configuration object, and a function to call when the value changes.
# The widget to be installed should be returned, and a callback to refresh the UI (which is called immediately).
# If wide is set, the widget is put into a labelframe, instead of having a label to the side.
SingleCreateFunc: TypeAlias = Callable[
    [tk.Widget, TKImages, SingleChangeFunc, OptConfT],
    Awaitable[Tuple[tk.Widget, UpdateFunc]]
]
SingleCreateNoConfFunc: TypeAlias = Callable[
    [tk.Widget, TKImages, SingleChangeFunc],
    Awaitable[Tuple[tk.Widget, UpdateFunc]]
]

# Override for timer-type widgets to be more compact - passed a list of timer numbers instead.
# The widgets should insert themselves into the parent frame.
# It then yields timer_val, update-func pairs.
MultiCreateFunc: TypeAlias = Callable[
    [tk.Widget, TKImages, Iterable[TimerNum], MultiChangeFunc, OptConfT],
    AsyncIterator[Tuple[TimerNum, UpdateFunc]]
]
MultiCreateNoConfFunc: TypeAlias = Callable[
    [tk.Widget, TKImages, Iterable[TimerNum], MultiChangeFunc],
    AsyncIterator[Tuple[TimerNum, UpdateFunc]]
]

# The functions registered for each.
_UI_IMPL_SINGLE: Dict[WidgetType, SingleCreateFunc] = {}
_UI_IMPL_MULTI: Dict[WidgetType, MultiCreateFunc] = {}

INF = TransToken.untranslated('∞')
TIMER_NUM_TRANS: Dict[TimerNum, TransToken] = {
    num: TransToken.untranslated('{delta:ms}').format(delta=timedelta(seconds=float(num)))
    for num in TIMER_NUM
}
TIMER_NUM_TRANS[TIMER_STR_INF] = INF
TRANS_COLON = TransToken.untranslated('{text}: ')
TRANS_GROUP_HEADER = TransToken.ui('{name} ({page}/{count})')  # i18n: Header layout for Item Properties pane.
# For the item-variant widget, we need to refresh on style changes.
ITEM_VARIANT_LOAD: List[Tuple[str, Callable[[], object]]] = []

window: Optional[SubPane] = None


def ui_single_wconf(cls: Type[ConfT]) -> Callable[[SingleCreateFunc[ConfT]], SingleCreateFunc[
    ConfT]]:
    """Register the UI function used for singular widgets with configs."""
    kind = CLS_TO_KIND[cls]

    def deco(func: SingleCreateFunc[ConfT]) -> SingleCreateFunc[ConfT]:
        """Do the registration."""
        _UI_IMPL_SINGLE[kind] = func
        return func
    return deco


def ui_single_no_conf(kind: WidgetType) -> Callable[[SingleCreateNoConfFunc], SingleCreateNoConfFunc]:
    """Register the UI function used for singular widgets without configs."""
    def deco(func: SingleCreateNoConfFunc) -> SingleCreateNoConfFunc:
        """Do the registration."""
        def wrapper(
            parent: tk.Widget, tk_img: TKImages, on_changed: SingleChangeFunc, conf: None,
        ) -> Awaitable[Tuple[tk.Widget, UpdateFunc]]:
            """Don't pass the config through to the UI function."""
            assert conf is None
            return func(parent, tk_img, on_changed)

        if isinstance(kind, WidgetTypeWithConf):
            raise TypeError('Widget type has config, but singular function does not!')
        _UI_IMPL_SINGLE[kind] = wrapper
        return func
    return deco


def ui_multi_wconf(cls: Type[ConfT]) -> Callable[[MultiCreateFunc[ConfT]], MultiCreateFunc[ConfT]]:
    """Register the UI function used for multi widgets with configs."""
    kind = CLS_TO_KIND[cls]

    def deco(func: MultiCreateFunc[ConfT]) -> MultiCreateFunc[ConfT]:
        """Do the registration."""
        _UI_IMPL_MULTI[kind] = func
        return func
    return deco


def ui_multi_no_conf(kind: WidgetType) -> Callable[[MultiCreateNoConfFunc], MultiCreateNoConfFunc]:
    """Register the UI function used for multi widgets without configs."""
    def deco(func: MultiCreateNoConfFunc) -> MultiCreateNoConfFunc:
        """Do the registration."""
        def wrapper(
            parent: tk.Widget, tk_img: TKImages, tim: Iterable[TimerNum],
            on_changed: MultiChangeFunc, conf: None,
        ) -> AsyncIterator[Tuple[TimerNum, UpdateFunc]]:
            """Don't pass the config through to the UI function."""
            assert conf is None
            return func(parent, tk_img, tim, on_changed)

        if isinstance(kind, WidgetTypeWithConf):
            raise TypeError('Widget type has config, but multi function does not!')
        _UI_IMPL_MULTI[kind] = wrapper
        return func
    return deco


async def create_group(master: ttk.Frame, tk_img: TKImages, group: ConfigGroup) -> ttk.Frame:
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

            label: Optional[ttk.Label] = None
            if s_wid.name:
                if s_wid.kind.is_wide:
                    wid_frame = localisation.set_text(
                        ttk.LabelFrame(wid_frame),
                        TRANS_COLON.format(text=s_wid.name),
                    )
                    wid_frame.grid(row=0, column=0, columnspan=2, sticky='ew', pady=5)
                    wid_frame.columnconfigure(0, weight=1)
                else:
                    label = ttk.Label(wid_frame)
                    localisation.set_text(label, TRANS_COLON.format(text=s_wid.name))
                    label.grid(row=0, column=0)
            create_func = _UI_IMPL_SINGLE[s_wid.kind]
            try:
                with logger.context(f'{group.id}:{s_wid.id}'):
                    widget, s_wid.ui_cback = await create_func(wid_frame, tk_img, s_wid.on_changed, s_wid.config)
            except Exception:
                LOGGER.exception('Could not construct widget {}.{}', group.id, s_wid.id)
                continue
            # Do an initial update, so it has the right value.
            await s_wid.ui_cback(s_wid.value)

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
            wid_frame = localisation.set_text(
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
                async for tim_val, update_cback in multi_func(
                    wid_frame, tk_img,
                    m_wid.values.keys(),
                    m_wid.get_on_changed,
                    m_wid.config,
                ):
                    m_wid.ui_cbacks[tim_val] = update_cback
                    await update_cback(m_wid.values[tim_val])
        except Exception:
            LOGGER.exception('Could not construct widget {}.{}', group.id, m_wid.id)
            continue
        await config.APP.set_and_run_ui_callback(
            WidgetConfig, m_wid.apply_conf, f'{m_wid.group_id}:{m_wid.id}',
        )
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
    tool_frame: Union[tk.Frame, ttk.Frame],
    menu_bar: tk.Menu,
    tk_img: TKImages,
    update_item_vis: Callable[[], None],
) -> None:
    """Create the item properties pane, with the widgets it uses.

    update_item_vis is passed through to the stylevar pane.
    """
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

    ordered_conf: List[ConfigGroup] = sorted(
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

    group_menu = tk.Menu(group_label, tearoff=False)
    group_var = tk.StringVar(window)

    ttk.Separator(window, orient='horizontal').grid(row=1, column=0, columnspan=2, sticky='EW')

    # Need to use a canvas to allow scrolling.
    canvas = tk.Canvas(window, highlightthickness=0)
    canvas.grid(row=2, column=0, sticky='NSEW', padx=(5, 0))
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)

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
    await StyleVarPane.make_stylevar_pane(stylevar_frame, packages.get_loaded_packages(), update_item_vis)

    loading_text = ttk.Label(canvas_frame)
    localisation.set_text(loading_text, TransToken.ui('Loading...'))
    loading_text.grid(row=0, column=0, sticky='ew')
    loading_text.grid_forget()

    group_to_frame: Dict[ConfigGroup, ttk.Frame] = {
        STYLEVAR_GROUP: stylevar_frame,
    }
    groups_being_created: Set[ConfigGroup] = set()
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
            background_run(display_group, new_group)
        else:  # Begin creating, or loading.
            loading_text.grid(row=0, column=0, sticky='ew')
            if new_group not in groups_being_created:
                async def task() -> None:
                    """Create the widgets, then display."""
                    group_to_frame[new_group] = await create_group(canvas_frame, tk_img,new_group)
                    groups_being_created.discard(new_group)
                    await display_group(new_group)

                background_run(task)
                groups_being_created.add(new_group)

    def select_directional(direction: int) -> None:
        """Change the selection in some direction."""
        # Clamp to ±1 since scrolling can send larger numbers.
        pos = ordered_conf.index(cur_group) + (+1 if direction > 0 else -1)
        if 0 <= pos < len(ordered_conf):
            select_group(ordered_conf[pos])

    def update_disp() -> None:
        """Update widgets if the group has changed."""
        localisation.set_text(group_label, TRANS_GROUP_HEADER.format(
            name=cur_group.name,
            page=ordered_conf.index(cur_group) + 1,
            count=len(ordered_conf),
        ))
        pos = ordered_conf.index(cur_group)
        group_var.set(cur_group.id)
        arrow_left.state(['disabled' if pos == 0 else '!disabled'])
        arrow_right.state(['disabled' if pos + 1 == len(ordered_conf) else '!disabled'])

    @localisation.add_callback(call=True)
    def update_selector() -> None:
        """Update translations in the display, reordering if necessary."""
        # Stylevar always goes at the start.
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

    tk_tools.bind_leftclick(group_label, lambda evt: group_menu.post(evt.x_root, evt.y_root))
    tk_tools.bind_mousewheel([
        selection_frame, arrow_left, arrow_right, group_label,
    ], select_directional)
    group_label.bind('<Enter>', f'{group_label} configure -foreground "#2873FF"')
    group_label.bind('<Leave>', f'{group_label} configure -foreground ""')

    await tk_tools.wait_eventloop()

    # Update canvas when the window resizes.
    canvas.bind('<Configure>', f'{canvas} configure -scrollregion [{canvas} bbox all]')
    await display_group(cur_group)


def widget_timer_generic(widget_func: SingleCreateFunc[ConfT]) -> MultiCreateFunc[ConfT]:
    """For widgets without a multi version, do it generically."""
    async def generic_func(
        parent: tk.Widget,
        tk_img: TKImages,
        timers: Iterable[TimerNum],
        get_on_changed: MultiChangeFunc,
        conf: ConfT,
    ) -> AsyncIterator[Tuple[TimerNum, UpdateFunc]]:
        """Generically make a set of labels."""
        for row, tim_val in enumerate(timers):
            timer_disp = TIMER_NUM_TRANS[tim_val]
            parent.columnconfigure(1, weight=1)

            label = ttk.Label(parent)
            localisation.set_text(label, TRANS_COLON.format(text=timer_disp))
            label.grid(row=row, column=0)
            widget, update = await widget_func(
                parent, tk_img, get_on_changed(tim_val), conf,
            )
            yield tim_val, update
            widget.grid(row=row, column=1, sticky='ew')

    return generic_func


def multi_grid(
    timers: Iterable[TimerNum],
    columns: int = 10,
) -> Iterator[Tuple[int, int, TimerNum, TransToken]]:
    """Generate the row and columns needed for a nice layout of widgets."""
    for tim in timers:
        if tim == 'inf':
            tim_disp = INF
            index = 0
        else:
            tim_disp = TIMER_NUM_TRANS[tim]
            index = int(tim)
        row, column = divmod(index - 1, columns)
        yield row, column, tim, tim_disp


def widget_sfx(*args: object) -> None:
    """Play sounds when interacting."""
    sound.fx_blockable('config')


@ui_single_wconf(ItemVariantConf)
async def widget_item_variant(
    parent: tk.Widget, tk_img: TKImages,
    _: SingleChangeFunc,
    conf: ItemVariantConf,
) -> Tuple[tk.Widget, UpdateFunc]:
    """Special widget - chooses item variants.

    This replicates the box on the right-click menu for items.
    It's special-cased in the above code.
    """
    from app import contextWin
    try:
        item = UI.item_list[conf.item_id]
    except KeyError:
        raise ValueError(f'Unknown item "{conf.item_id}"!') from None

    if item.id == 'ITEM_BEE2_SIGNAGE':
        # Even more special case, display the "configure signage" button.
        return await signage_ui.init_widgets(parent, tk_img), nop_update

    version_lookup: Optional[List[str]] = None

    def update_data() -> None:
        """Refresh the data in the list."""
        nonlocal version_lookup
        version_lookup = contextWin.set_version_combobox(combobox, item)

    def change_callback(e: Optional[tk.Event[tk.Misc]] = None) -> None:
        """Change the item version."""
        item.change_version(version_lookup[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        values=[''],
    )
    combobox.state(['readonly'])  # Prevent directly typing in values
    combobox.bind('<<ComboboxSelected>>', change_callback)

    ITEM_VARIANT_LOAD.append((item.id, update_data))
    update_data()
    return combobox, nop_update


# Load all the widgets.
from . import checkmark, color, dropdown, slider, string, timer  # noqa: F401
