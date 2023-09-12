"""Allows enabling and disabling specific voicelines."""
import functools
import itertools
from decimal import Decimal
from enum import Enum
from typing import Iterator, List, Tuple, TypedDict, Dict, Optional
from configparser import SectionProxy

import tkinter
from tkinter import *
from tkinter import font
from tkinter import ttk

from srctools import Keyvalues
import srctools.logger
import attrs

from BEE2_config import ConfigFile
from packages import QuotePack
from transtoken import TransToken
from app.tooltip import add_tooltip
from app import img, TK_ROOT, localisation
from app import tk_tools
from ui_tk.img import TKImages


LOGGER = srctools.logger.get_logger(__name__)

voice_item = None


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

IMG: Dict[str, Tuple[img.Handle, TransToken]] = {
    spr: (img.Handle.builtin('icons/quote_' + spr), ctx)
    for spr, ctx in [
        ('sp', TransToken.ui('Singleplayer')),
        ('coop', TransToken.ui('Cooperative')),
        ('atlas', TransToken.ui('ATLAS (SP/Coop)')),
        ('pbody', TransToken.ui('P-Body (SP/Coop)')),
        ('bendy', TransToken.ui('Bendy')),
        ('chell', TransToken.ui('Chell')),
        ('human', TransToken.ui('Human characters (Bendy and Chell)')),
        ('robot', TransToken.ui('AI characters (ATLAS, P-Body, or Coop)')),
    ]
}


RESPONSE_NAMES = {
    'death_generic': TransToken.ui('Death - Generic'),
    'death_goo': TransToken.ui('Death - Toxic Goo'),
    'death_turret': TransToken.ui('Death - Turrets'),
    'death_crush': TransToken.ui('Death - Crusher'),
    'death_laserfield': TransToken.ui('Death - LaserField'),

    # TODO: Fill in the other "animations" for these.
    'taunt_generic': TransToken.ui('Taunts - Generic'),
    'camera_generic': TransToken.ui('Camera Gesture - Generic'),
}
TRANS_NO_NAME = TransToken.ui('No Name!')
# i18n: 'response' tab name, should be short.
TRANS_RESPONSE_TITLE = TransToken.ui('Resp')

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
    """Close the window."""
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

    localisation.set_text(ttk.Label(trans_frame), TransToken.ui('Transcript:')).grid(row=0, column=0, sticky=W)

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

    localisation.set_text(ttk.Button(win, command=save), TransToken.ui('Save')).grid(row=2, column=0)

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


def show_trans(transcript: List[Tuple[str, str]], e: Event) -> None:
    """Add the transcript to the list."""
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    for actor, line in transcript:
        text.insert('end', actor, ('bold',))
        text.insert('end', line + '\n\n')
    # Remove the trailing newlines
    text.delete('end-2char', 'end')
    text['state'] = 'disabled'


def check_toggled(var: BooleanVar, config_section: SectionProxy, quote_id: str) -> None:
    """Update the config file to match the checkbox."""
    config_section[quote_id] = srctools.bool_as_int(var.get())


def save() -> None:
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
                text=str(TRANS_RESPONSE_TITLE),
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

    localisation.set_win_title(win, TransToken.ui(
        'BEE2 - Configure "{item}"',
    ).format(item=voice_item.selitem_data.name))
    win.grab_set()
    notebook = UI['tabs']

    quote_data = quote_pack.config

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

    for group in quote_data.find_all('quotes', 'group'):
        make_tab(
            tk_img,
            quote_pack.pak_id,
            group,
            config,
            TabTypes.NORM
        )

    # Merge all blocks into one
    mid_quotes = Keyvalues(
        'midChamber',
        list(itertools.chain.from_iterable(
            quote_data.find_all('quotes', 'midChamber')
        ))
    )

    if len(mid_quotes):
        make_tab(
            tk_img,
            quote_pack.pak_id,
            mid_quotes,
            config_mid,
            TabTypes.MIDCHAMBER,
        )

    responses = Keyvalues(
        'CoopResponses',
        list(itertools.chain.from_iterable(
            quote_data.find_all('quotes', 'CoopResponses')
        )),
    )

    if len(responses):
        make_tab(
            tk_img,
            quote_pack.pak_id,
            responses,
            config_resp,
            TabTypes.RESPONSE,
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
    pak_id: str, group: Keyvalues, config: ConfigFile, tab_type: TabTypes,
) -> None:
    """Create all the widgets for a tab."""
    if tab_type is TabTypes.MIDCHAMBER:
        # Mid-chamber voice lines have predefined values.
        group_name = TransToken.ui('Mid - Chamber')
        group_id = 'MIDCHAMBER'
        group_desc = TransToken.ui(
            'Lines played during the actual chamber, '
            'after specific events have occurred.'
        )
    elif tab_type is TabTypes.RESPONSE:
        # Note: 'Response' tab header, and description
        group_name = TransToken.ui('Responses')
        group_id = None
        group_desc = TransToken.ui(
            'Lines played in response to certain events in Coop.'
        )
    elif tab_type is TabTypes.NORM:
        try:
            group_name = TransToken.parse(pak_id, group['name'])
        except LookupError:
            group_name = TransToken.ui('No Name!')
        group_id = group_name.token.upper()
        group_desc = TransToken.parse(pak_id, group['desc', ''])
    else:
        raise ValueError('Invalid tab type!')

    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)

    TABS.append(Tab(tab_type, outer_frame,group_name))

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

    localisation.set_text(
        ttk.Label(frame, anchor='center', font='tkHeadingFont'),
        group_name,
    ).grid(row=0,column=0, sticky='EW')

    localisation.set_text(ttk.Label(frame), group_desc).grid(row=1, column=0, sticky='EW')

    ttk.Separator(frame, orient=HORIZONTAL).grid(
        row=2,
        column=0,
        sticky='EW',
    )

    if tab_type is TabTypes.RESPONSE:
        sorted_quotes = sorted(
            group,
            key=lambda prop: prop.real_name
        )
    else:
        sorted_quotes = sorted(
            group.find_all('Quote'),
            key=quote_sort_func,
            reverse=True,
        )

    for quote in sorted_quotes:
        if not quote.has_children():
            continue  # Skip over config commands..

        if tab_type is TabTypes.RESPONSE:
            try:
                name = RESPONSE_NAMES[quote.name]
            except KeyError:
                LOGGER.warning('No name for response: "{}"', quote.real_name)
                name = TransToken.untranslated(quote.real_name)

            group_id = quote.name
        else:
            # note: default for quote names
            try:
                name = TransToken.parse(pak_id, quote['name'])
            except LookupError:
                name = TRANS_NO_NAME

        localisation.set_text(ttk.Label(frame, font=QUOTE_FONT), name).grid(column=0, sticky=W)

        if tab_type is TabTypes.RESPONSE:
            line_iter = find_resp_lines(quote)
        else:
            line_iter = find_lines(quote)

        for badges, line, line_id in line_iter:
            line_frame = ttk.Frame(
                frame,
            )
            line_frame.grid(
                column=0,
                padx=(10, 0),
                sticky=W,
            )
            for x, (img_handle, ctx) in enumerate(badges):
                label = ttk.Label(line_frame, padding=0)
                tk_img.apply(label, img_handle)
                label.grid(row=0, column=x)
                add_tooltip(label, ctx)

            line_frame.columnconfigure(len(badges), weight=1)

            check = ttk.Checkbutton(line_frame)
            quote_var = IntVar(value=config.get_bool(group_id, line_id, True))
            try:
                check['text'] = line['name']
            except LookupError:
                check['text'] = ''

            check['variable'] = quote_var

            check['command'] = functools.partial(
                check_toggled,
                var=quote_var,
                config_section=config[group_id],
                quote_id=line_id,
            )
            check.grid(
                row=0,
                column=len(badges),
            )
            check.bind("<Enter>", functools.partial(show_trans, list(get_trans_lines(line))))

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


def find_lines(quote_block: Keyvalues) -> Iterator[Tuple[
    List[Tuple[img.Handle, TransToken]],
    Keyvalues,
    str,
]]:
    """Find the line property blocks in a quote."""
    for prop in quote_block:
        if not prop.name.startswith('line'):
            continue

        line_id = prop['id', prop['name']]

        if prop.name == 'line':
            yield [], prop, line_id
        elif prop.name.startswith('line_'):
            try:
                images = [
                    IMG[img]
                    for img in
                    prop.name.split('_')[1:]
                ]
            except KeyError as exc:
                LOGGER.warning('Invalid line type in "{}" {!r}!',
                    prop.name,
                    exc.args,
                )
                images = []
            yield images, prop, line_id


def find_resp_lines(quote_block: Keyvalues) -> Iterator[Tuple[
    List[Tuple[img.Handle, TransToken]],
    Keyvalues,
    str,
]]:
    """Find the line blocks in response items."""
    for index, prop in enumerate(quote_block):
        yield [], prop, f'line_{index}'


def get_trans_lines(trans_block: Keyvalues) -> Iterator[Tuple[str, str]]:
    for prop in trans_block:
        if prop.name == 'trans':
            if ':' in prop.value:
                name, trans = prop.value.split(':', 1)
                yield name.rstrip(), ': "' + trans.lstrip() + '"'
            else:
                yield '', '"' + prop.value + '"'
