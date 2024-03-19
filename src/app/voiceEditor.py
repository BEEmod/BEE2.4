"""Allows enabling and disabling specific voicelines."""
import functools
from decimal import Decimal
from enum import Enum
from typing import Iterable, List, Tuple, TypedDict, Dict, Optional
from configparser import SectionProxy

from tkinter import *
from tkinter import font
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

voice_item: Optional[QuotePack] = None


class _WidgetsDict(TypedDict, total=False):
    """TODO Remove."""
    pane: PanedWindow
    tabs: ttk.Notebook
    trans: Text
    trans_scroll: tk_tools.HidingScroll

UI: _WidgetsDict = {}
TABS: List['Tab'] = []

QUOTE_FONT = font.nametofont('TkHeadingFont').copy()
QUOTE_FONT['weight'] = 'bold'

IMG_MID = img.Handle.builtin('icons/mid_quote', 32, 16)
IMG_RESP = img.Handle.builtin('icons/resp_quote', 16, 16)

IMG: Dict[LineCriteria, img.Handle] = {
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
    'Lines played during the actual chamber, '
    'after specific events have occurred.'
)

config: Optional[ConfigFile] = None
config_mid: Optional[ConfigFile] = None
config_resp: Optional[ConfigFile] = None


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

win = Toplevel(TK_ROOT, name='voiceEditor')
win.withdraw()


def quit(event: object = None) -> None:
    """Close the window, discarding changes."""
    global voice_item
    if voice_item is not None:
        voice_item = None
    win.grab_release()
    win.wm_withdraw()


def init_widgets() -> None:
    """Make all the window components."""
    win.columnconfigure(0, weight=1)
    win.transient(master=TK_ROOT)
    tk_tools.set_window_icon(win)
    win.protocol("WM_DELETE_WINDOW", quit)
    win.bind("<Escape>", quit)

    pane = PanedWindow(
        win,
        orient=VERTICAL,
        sashpad=2,  # Padding above/below panes
        sashwidth=3,  # Width of border
        sashrelief=RAISED,  # Raise the border between panes
        )
    UI['pane'] = pane
    pane.grid(row=1, column=0, sticky='NSEW')
    win.rowconfigure(1, weight=1)

    UI['tabs'] = ttk.Notebook(pane)
    UI['tabs'].enable_traversal()  # Add keyboard shortcuts
    pane.add(UI['tabs'])
    pane.paneconfigure(UI['tabs'], minsize=50)

    trans_frame = ttk.Frame(pane)
    trans_frame.rowconfigure(1, weight=1)
    trans_frame.columnconfigure(0, weight=1)

    set_text(ttk.Label(trans_frame), TransToken.ui('Transcript:')).grid(row=0, column=0, sticky=W)

    trans_inner_frame = ttk.Frame(trans_frame, borderwidth=2, relief='sunken')
    trans_inner_frame.grid(row=1, column=0, sticky='NSEW')
    trans_inner_frame.rowconfigure(0, weight=1)
    trans_inner_frame.columnconfigure(0, weight=1)

    default_bold_font = font.nametofont('TkDefaultFont').copy()
    default_bold_font['weight'] = 'bold'

    UI['trans'] = Text(
        trans_inner_frame,
        width=10,
        height=4,
        wrap='word',
        relief='flat',
        state='disabled',
        font='TkDefaultFont',
        )
    UI['trans_scroll'] = tk_tools.HidingScroll(
        trans_inner_frame,
        orient=VERTICAL,
        command=UI['trans'].yview,
        )
    UI['trans'].tag_config(
        'bold',
        font=default_bold_font,
    )
    UI['trans']['yscrollcommand'] = UI['trans_scroll'].set
    UI['trans_scroll'].grid(row=0, column=1, sticky='NS')
    UI['trans'].grid(row=0, column=0, sticky='NSEW')

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


def show_trans(transcript: List[Tuple[str, TransToken]], e: Event) -> None:
    """Add the transcript to the list."""
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    for actor, line in transcript:
        text.insert('end', actor, ('bold',))
        text.insert('end', str(line) + '\n\n')
    # Remove the trailing newlines
    text.delete('end-2char', 'end')
    text['state'] = 'disabled'


def check_toggled(var: BooleanVar, config_section: SectionProxy, quote_id: str) -> None:
    """Update the config file to match the checkbox."""
    config_section[quote_id] = srctools.bool_as_int(var.get())


def save(e) -> None:
    """Save and close the window."""
    global voice_item
    if voice_item is not None:
        voice_item = None
        LOGGER.info('Saving Configs!')
        config.save_check()
        config_mid.save_check()
        config_resp.save_check()
    win.grab_release()
    win.withdraw()


def add_tabs(tk_img: TKImages) -> None:
    """Add the tabs to the notebook."""
    notebook: ttk.Notebook = UI['tabs']
    # Save the current tab index, so we can restore it after.
    try:
        current_tab = notebook.index(notebook.select())
    except TclError:  # .index() will fail if the voice is empty,
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
                compound=RIGHT,
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
    text.delete(1.0, END)
    text['state'] = 'disabled'

    # Destroy all the old tabs
    for tab in TABS:
        try:
            notebook.forget(tab.frame)
        except TclError:
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
    contents: Iterable[Tuple[TransToken, str, Iterable[Line]]],
) -> None:
    """Create all the widgets for a tab."""
    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)

    TABS.append(Tab(tab_type, outer_frame, name))

    # We need a canvas to make the list scrollable.
    canv = Canvas(
        outer_frame,
        highlightthickness=0,
        )
    scroll = tk_tools.HidingScroll(
        outer_frame,
        orient=VERTICAL,
        command=canv.yview,
        )
    canv['yscrollcommand'] = scroll.set
    canv.grid(row=0, column=0, sticky='NSEW')
    scroll.grid(row=0, column=1, sticky='NS')

    UI['tabs'].add(outer_frame)

    # This holds the actual elements
    frame = ttk.Frame(
        canv,
        )
    frame.columnconfigure(0, weight=1)
    canv.create_window(0, 0, window=frame, anchor="nw")

    set_text(
        ttk.Label(frame, anchor='center', font='tkHeadingFont'),
        name,
    ).grid(row=0,column=0, sticky='EW')

    set_text(ttk.Label(frame), desc).grid(row=1, column=0, sticky='EW')

    ttk.Separator(frame, orient=HORIZONTAL).grid(
        row=2,
        column=0,
        sticky='EW',
    )

    for name, conf_id, lines in contents:
        set_text(ttk.Label(frame, font=QUOTE_FONT), name).grid(column=0, sticky=W)

        for line in lines:
            line_frame = ttk.Frame(frame,)
            line_frame.grid(
                column=0,
                padx=(10, 0),
                sticky=W,
            )
            x = 0
            for x, criteria in enumerate(line.criterion):
                label = ttk.Label(line_frame, padding=0)
                tk_img.apply(label, IMG[criteria])
                label.grid(row=0, column=x)
                add_tooltip(label, criteria.tooltip)

            x += 1  # Position after the badges
            line_frame.columnconfigure(x, weight=1)

            quote_var = IntVar(value=config.get_bool(conf_id, line.id, True))
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

    def configure_canv(e: Event) -> None:
        """Allow resizing the windows."""
        canv['scrollregion'] = (
            4,
            0,
            canv.winfo_reqwidth(),
            frame.winfo_reqheight(),
        )
        frame['width'] = canv.winfo_reqwidth()

    canv.bind('<Configure>', configure_canv)
