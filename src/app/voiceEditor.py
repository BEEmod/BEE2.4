"""Allows enabling and disabling specific voicelines."""
from __future__ import annotations
import functools
from decimal import Decimal
from enum import Enum
from typing import Iterable, TypedDict
from configparser import SectionProxy

import tkinter as tk
from tkinter.font import nametofont as tk_nametofont
from tkinter import ttk

from srctools import Keyvalues
import srctools.logger
import attrs

from BEE2_config import ConfigFile
from packages import QuotePack
from quote_pack import Line, LineCriteria
from transtoken import TransToken
from app.tooltip import add_tooltip
from app import img, TK_ROOT
from app import tk_tools
from ui_tk.img import TKImages
from ui_tk.wid_transtoken import set_text, set_win_title


LOGGER = srctools.logger.get_logger(__name__)

voice_item: QuotePack | None = None


class _WidgetsDict(TypedDict, total=False):
    """TODO Remove."""
    tabs: ttk.Notebook
    trans: tk.Text

UI: _WidgetsDict = {}
TABS: list[Tab] = []

QUOTE_FONT = tk_nametofont('TkHeadingFont').copy()
QUOTE_FONT['weight'] = 'bold'
ACTOR_FONT = tk_nametofont('TkDefaultFont').copy()
ACTOR_FONT['weight'] = 'bold'

IMG_MID = img.Handle.builtin('icons/mid_quote', 32, 16)
IMG_RESP = img.Handle.builtin('icons/resp_quote', 16, 16)

IMG: dict[LineCriteria, img.Handle] = {
    criteria: img.Handle.builtin('icons/quote_' + criteria.name.lower())
    for criteria in LineCriteria
}

ID_MIDCHAMBER = 'MIDCHAMBER'
# i18n: 'response' tab name, should be short.
TRANS_RESPONSE_SHORT = TransToken.ui('Resp')
# i18n: 'Response' tab header.
TRANS_RESPONSE_TITLE = TransToken.ui('Responses')
TRANS_RESPONSE_DESC = TransToken.ui(
    'Lines played in response to certain events in Coop.'
)
TRANS_MIDCHAMBER_TITLE = TransToken.ui('Mid - Chamber')
TRANS_MIDCHAMBER_DESC = TransToken.ui(
    'Lines played during the actual chamber, after specific events have occurred.'
)

config: ConfigFile | None = None
config_mid: ConfigFile | None = None
config_resp: ConfigFile | None = None


class TabTypes(Enum):
    """Kinds of tabs."""
    NORM = 0
    MIDCHAMBER = MID = 1
    RESPONSE = RESP = 2


@attrs.define(eq=False)
class Tab:
    """Information for the tabs that are spawned."""
    kind: TabTypes
    frame: ttk.Frame
    title: TransToken

win = tk.Toplevel(TK_ROOT, name='voiceEditor')
win.withdraw()


def close(event: object = None) -> None:
    """Close the window, discarding changes."""
    global voice_item, config, config_mid, config_resp
    voice_item = config = config_mid = config_resp = None
    win.grab_release()
    win.wm_withdraw()


def init_widgets() -> None:
    """Make all the window components."""
    win.columnconfigure(0, weight=1)
    win.transient(master=TK_ROOT)
    tk_tools.set_window_icon(win)
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", close)

    pane = tk.PanedWindow(
        win,
        orient='vertical',
        sashpad=2,  # Padding above/below panes
        sashwidth=3,  # Width of border
        sashrelief='raised',  # Raise the border between panes
        )
    pane.grid(row=1, column=0, sticky='NSEW')
    win.rowconfigure(1, weight=1)

    UI['tabs'] = ttk.Notebook(pane)
    UI['tabs'].enable_traversal()  # Add keyboard shortcuts
    pane.add(UI['tabs'])
    pane.paneconfigure(UI['tabs'], minsize=50)

    trans_frame = ttk.Frame(pane)
    trans_frame.rowconfigure(1, weight=1)
    trans_frame.columnconfigure(0, weight=1)

    set_text(
        ttk.Label(trans_frame), TransToken.ui('Transcript:'),
    ).grid(row=0, column=0, sticky='W')

    trans_inner_frame = ttk.Frame(trans_frame, borderwidth=2, relief='sunken')
    trans_inner_frame.grid(row=1, column=0, sticky='NSEW')
    trans_inner_frame.rowconfigure(0, weight=1)
    trans_inner_frame.columnconfigure(0, weight=1)

    UI['trans'] = transcript = tk.Text(
        trans_inner_frame,
        width=10,
        height=4,
        wrap='word',
        relief='flat',
        state='disabled',
        font='TkDefaultFont',
        )
    trans_scroll = tk_tools.HidingScroll(
        trans_inner_frame,
        orient='vertical',
        command=transcript.yview,
        )
    transcript.tag_config('actor', font=ACTOR_FONT)
    transcript['yscrollcommand'] = trans_scroll.set
    trans_scroll.grid(row=0, column=1, sticky='NS')
    transcript.grid(row=0, column=0, sticky='NSEW')

    set_text(ttk.Button(win, command=save), TransToken.ui('Save')).grid(row=2, column=0)

    # Don't allow resizing the transcript box to be smaller than the
    # original size.
    trans_frame.update_idletasks()
    pane.paneconfigure(trans_frame, minsize=trans_frame.winfo_reqheight())


def quote_sort_func(quote: Keyvalues) -> Decimal:
    """The quotes will be sorted by their priority value."""
    # Use Decimal so any number of decimal points can be used.
    try:
        return Decimal(quote['priority', '0'])
    except ArithmeticError:
        return Decimal('0')


def show_trans(transcript: list[tuple[str, TransToken]], e: tk.Event) -> None:
    """Add the transcript to the list."""
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, tk.END)
    for actor, line in transcript:
        text.insert('end', actor, ('actor',))
        text.insert('end', str(line) + '\n\n')
    # Remove the trailing newlines
    text.delete('end-2char', 'end')
    text['state'] = 'disabled'


def check_toggled(var: tk.BooleanVar, config_section: SectionProxy, quote_id: str) -> None:
    """Update the config file to match the checkbox."""
    config_section[quote_id] = srctools.bool_as_int(var.get())


def save() -> None:
    """Save and close the window."""
    if voice_item is not None:
        LOGGER.info('Saving Configs!')
        if config is not None:
            config.save_check()
        if config_mid is not None:
            config_mid.save_check()
        if config_resp is not None:
            config_resp.save_check()
    close()


def add_tabs(tk_img: TKImages) -> None:
    """Add the tabs to the notebook."""
    notebook: ttk.Notebook = UI['tabs']
    # Save the current tab index, so we can restore it after.
    try:  # Currently typed as Any, hence the type-ignore.
        current_tab = notebook.index(notebook.select())  # type: ignore[no-untyped-call]
    except tk.TclError:  # .index() will fail if the voice is empty,
        current_tab = None  # in that case abandon remembering the tab.

    # Add or remove tabs so only the correct mode is visible.
    for tab in TABS:
        notebook.add(tab.frame)
        # For the special tabs, we use a special image to make
        # sure they are well-distinguished from the other groups
        if tab.kind is TabTypes.MID:
            notebook.tab(
                tab.frame,
                compound='image',
                image=tk_img.sync_load(IMG_MID),
                )
        if tab.kind is TabTypes.RESPONSE:
            notebook.tab(
                tab.frame,
                compound='right',
                image=tk_img.sync_load(IMG_RESP),
                text=str(TRANS_RESPONSE_SHORT),
            )
        else:
            notebook.tab(tab.frame, text=str(tab.title))

    if current_tab is not None:
        notebook.select(current_tab)


def show(tk_img: TKImages, quote_pack: QuotePack) -> None:
    """Display the editing window."""
    global voice_item, config, config_mid, config_resp
    if voice_item is not None:
        return

    voice_item = quote_pack

    set_win_title(win, TransToken.ui(
        'BEE2 - Configure "{item}"',
    ).format(item=voice_item.selitem_data.name))
    win.grab_set()
    notebook = UI['tabs']

    config = ConfigFile('voice/' + quote_pack.id + '.cfg')
    config_mid = ConfigFile('voice/MID_' + quote_pack.id + '.cfg')
    config_resp = ConfigFile('voice/RESP_' + quote_pack.id + '.cfg')

    # Clear the transcript textbox
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, 'end')
    text['state'] = 'disabled'

    # Destroy all the old tabs
    for tab in TABS:
        try:
            notebook.forget(tab.frame)
        except tk.TclError:
            pass
        tab.frame.destroy()

    TABS.clear()

    for group in quote_pack.data.groups.values():
        make_tab(
            tk_img,
            TabTypes.NORM,
            name=group.name,
            desc=group.desc,
            config=config,
            contents=(
                (quote.name, group.id, quote.lines)
                for quote in sorted(group.quotes, key=lambda quote: quote.priority)
            )
        )

    if quote_pack.data.midchamber:
        make_tab(
            tk_img,
            TabTypes.MIDCHAMBER,
            name=TRANS_MIDCHAMBER_TITLE,
            desc=TRANS_MIDCHAMBER_DESC,
            config=config_mid,
            contents=(
                (quote.name, ID_MIDCHAMBER, quote.lines)
                for quote in sorted(quote_pack.data.midchamber, key=lambda quote: quote.name.token)
            )
        )

    if any(quote_pack.data.responses.values()):
        make_tab(
            tk_img,
            TabTypes.RESPONSE,
            name=TRANS_RESPONSE_TITLE,
            desc=TRANS_RESPONSE_DESC,
            config=config_resp,
            contents=(
                (resp.title, resp.name.lower(), lines)
                for resp, lines in quote_pack.data.responses.items()
            )
        )

    config.save()
    config_mid.save()
    config_resp.save()

    add_tabs(tk_img)

    win.deiconify()
    tk_tools.center_win(win)  # Center inside the parent
    win.lift()


def make_tab(
    tk_img: TKImages,
    tab_type: TabTypes,
    name: TransToken,
    desc: TransToken,
    config: ConfigFile,
    contents: Iterable[tuple[TransToken, str, Iterable[Line]]],
) -> None:
    """Create all the widgets for a tab."""
    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)

    TABS.append(Tab(tab_type, outer_frame, name))

    # We need a canvas to make the list scrollable.
    canv = tk.Canvas(outer_frame, highlightthickness=0)
    scroll = tk_tools.HidingScroll(
        outer_frame,
        orient='vertical',
        command=canv.yview,
        )
    canv['yscrollcommand'] = scroll.set
    canv.grid(row=0, column=0, sticky='NSEW')
    scroll.grid(row=0, column=1, sticky='NS')

    UI['tabs'].add(outer_frame)

    # This holds the actual elements
    frame = ttk.Frame(canv)
    frame.columnconfigure(0, weight=1)
    canv.create_window(0, 0, window=frame, anchor="nw")

    set_text(
        ttk.Label(frame, anchor='center', font='tkHeadingFont'),
        name,
    ).grid(row=0, column=0, sticky='EW')

    set_text(ttk.Label(frame), desc).grid(row=1, column=0, sticky='EW')

    ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
        row=2,
        column=0,
        sticky='EW',
    )

    for name, conf_id, lines in contents:
        set_text(ttk.Label(frame, font=QUOTE_FONT), name).grid(column=0, sticky='W')

        for line in lines:
            line_frame = ttk.Frame(frame,)
            line_frame.grid(
                column=0,
                padx=(10, 0),
                sticky='W',
            )
            x = 0
            for x, criteria in enumerate(line.criterion):
                label = ttk.Label(line_frame, padding=0)
                tk_img.apply(label, IMG[criteria])
                label.grid(row=0, column=x)
                add_tooltip(label, criteria.tooltip)

            x += 1  # Position after the badges
            line_frame.columnconfigure(x, weight=1)

            quote_var = tk.IntVar(value=config.get_bool(conf_id, line.id, True))
            check = ttk.Checkbutton(
                line_frame,
                variable=quote_var,
                command=functools.partial(
                    check_toggled,
                    var=quote_var,
                    config_section=config[conf_id],
                    quote_id=line.id,
                )
            )
            set_text(check, line.name)
            check.grid(row=0, column=x)
            check.bind("<Enter>", functools.partial(show_trans, line.transcript))

    def configure_canv(_: object) -> None:
        """Allow resizing the windows."""
        canv['scrollregion'] = (
            0,
            0,
            canv.winfo_reqwidth(),
            frame.winfo_reqheight(),
        )
        frame['width'] = canv.winfo_reqwidth()

    canv.bind('<Configure>', configure_canv)
