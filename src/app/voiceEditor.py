"""Allows enabling and disabling specific voicelines."""
import functools
import itertools
from decimal import Decimal
from enum import Enum
from typing import Iterator, List, Tuple, Dict

from tkinter import *
from tkinter import font
from tkinter import ttk

from app import img, TK_ROOT
import srctools.logger
from app import tk_tools
import utils
from BEE2_config import ConfigFile
from app.tooltip import add_tooltip
from srctools import Property


LOGGER = srctools.logger.get_logger(__name__)

voice_item = None

UI = {}

TABS = {}

QUOTE_FONT = font.nametofont('TkHeadingFont').copy()
QUOTE_FONT['weight'] = 'bold'

IMG_TEXT = {
    'sp': _('Singleplayer'),
    'coop': _('Cooperative'),
    'atlas': _('ATLAS (SP/Coop)'),
    'pbody': _('P-Body (SP/Coop)'),
    'bendy': _('Bendy'),
    'chell': _('Chell'),
    'human': _('Human characters (Bendy and Chell)'),
    'robot': _('AI characters (ATLAS, P-Body, or Coop)'),
}

IMG = {
    spr: (img.png('icons/quote_' + spr), ctx)
    for spr, ctx in IMG_TEXT.items()
}  # type: Dict[str, Tuple[PhotoImage, str]]


# Friendly names given to certain response channels.
RESPONSE_NAMES = {
    'death_goo': _('Death - Toxic Goo'),
    'death_turret': _('Death - Turrets'),
    'death_crush': _('Death - Crusher'),
    'death_laserfield': _('Death - LaserField'),
}

config = config_mid = config_resp = None  # type: ConfigFile


class TabTypes(Enum):
    NORM = 0
    MIDCHAMBER = MID = 1
    RESPONSE = RESP = 2

win = Toplevel(TK_ROOT, name='voiceEditor')
win.withdraw()


def quit(event=None):
    """Close the window."""
    win.grab_release()
    win.wm_withdraw()


def init_widgets():
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

    ttk.Label(
        trans_frame,
        text=_('Transcript:'),
        ).grid(
            row=0,
            column=0,
            sticky=W,
            )

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

    ttk.Button(
        win,
        text=_('Save'),
        command=save,
        ).grid(row=2, column=0)

    # Don't allow resizing the transcript box to be smaller than the
    # original size.
    trans_frame.update_idletasks()
    pane.paneconfigure(trans_frame, minsize=trans_frame.winfo_reqheight())


def quote_sort_func(quote):
    """The quotes will be sorted by their priority value."""
    # Use Decimal so any number of decimal points can be used.
    try:
        return Decimal(quote['priority', '0'])
    except ValueError:
        return Decimal('0')


def show_trans(e):
    """Add the transcript to the list."""
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    for actor, line in e.widget.transcript:
        text.insert('end', actor, ('bold',))
        text.insert('end', line + '\n\n')
    # Remove the trailing newlines
    text.delete('end-2char', 'end')
    text['state'] = 'disabled'


def check_toggled(var, config_section, quote_id):
    """Update the config file to match the checkbox."""
    config_section[quote_id] = srctools.bool_as_int(var.get())


def save():
    global voice_item
    if voice_item is not None:
        voice_item = None
        LOGGER.info('Saving Configs!')
        config.save_check()
        config_mid.save_check()
        config_resp.save_check()
        win.grab_release()
        win.withdraw()


def add_tabs():
    """Add the tabs to the notebook."""
    notebook = UI['tabs']
    # Save the current tab index so we can restore it after.
    try:
        current_tab = notebook.index(notebook.select())
    except TclError:  # .index() will fail if the voice is empty,
        current_tab = None  # in that case abandon remembering the tab.

    # Add or remove tabs so only the correct mode is visible.
    for name, tab in sorted(TABS.items()):
        notebook.add(tab)
        # For the special tabs, we use a special image to make
        # sure they are well-distinguished from the other groups
        if tab.nb_type is TabTypes.MID:
            notebook.tab(
                tab,
                compound='image',
                image=img.png('icons/mid_quote'),
                )
        if tab.nb_type is TabTypes.RESPONSE:
            notebook.tab(
                tab,
                compound=RIGHT,
                image=img.png('icons/resp_quote'),
                #Note: 'response' tab name, should be short.
                text=_('Resp')
                )
        else:
            notebook.tab(tab, text=tab.nb_text)

    if current_tab is not None:
        notebook.select(current_tab)


def show(quote_pack):
    """Display the editing window."""
    global voice_item, config, config_mid, config_resp
    if voice_item is not None:
        return

    voice_item = quote_pack

    win.title(_('BEE2 - Configure "{}"').format(voice_item.selitem_data.name))
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
    for tab in TABS.values():
        try:
            notebook.forget(tab)
        except TclError:
            pass
        tab.destroy()

    TABS.clear()

    for group in quote_data.find_all('quotes', 'group'):
        make_tab(
            group,
            config,
            TabTypes.NORM
        )

    # Merge all blocks into one
    mid_quotes = Property(
        'midChamber',
        list(itertools.chain.from_iterable(
            quote_data.find_all('quotes', 'midChamber')
        ))
    )

    if len(mid_quotes):
        make_tab(
            mid_quotes,
            config_mid,
            TabTypes.MIDCHAMBER,
        )

    responses = Property(
        'CoopResponses',
        list(itertools.chain.from_iterable(
            quote_data.find_all('quotes', 'CoopResponses')
        )),
    )

    if len(responses):
        make_tab(
            responses,
            config_resp,
            TabTypes.RESPONSE,
        )

    config.save()
    config_mid.save()
    config_resp.save()

    add_tabs()

    win.deiconify()
    utils.center_win(win)  # Center inside the parent
    win.lift()


def make_tab(group, config: ConfigFile, tab_type):
    """Create all the widgets for a tab."""
    if tab_type is TabTypes.MIDCHAMBER:
        # Mid-chamber voice lines have predefined values.
        group_name = _('Mid - Chamber')
        group_id = 'MIDCHAMBER'
        group_desc = _(
            'Lines played during the actual chamber, '
            'after specific events have occurred.'
        )
    elif tab_type is TabTypes.RESPONSE:
        # Note: 'Response' tab header, and description
        group_name = _('Responses')
        group_id = None
        group_desc = _(
            'Lines played in response to certain events in Coop.'
        )
    elif tab_type is TabTypes.NORM:
        group_name = group['name', 'No Name!']
        group_id = group_name.upper()
        group_desc = group['desc', ''] + ':'
    else:
        raise ValueError('Invalid tab type!')

    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)

    TABS[group_name] = outer_frame
    # We add this attribute so the refresh() method knows all the
    # tab names
    outer_frame.nb_text = group_name
    outer_frame.nb_type = tab_type

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

    ttk.Label(
        frame,
        text=group_name,
        anchor='center',
        font='tkHeadingFont',
        ).grid(
            row=0,
            column=0,
            sticky='EW',
            )

    ttk.Label(
        frame,
        text=group_desc,
        ).grid(
            row=1,
            column=0,
            sticky='EW',
            )

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

    for quote in sorted_quotes:  # type: Property
        if not quote.has_children():
            continue # Skip over config commands..

        if tab_type is TabTypes.RESPONSE:
            try:
                name = RESPONSE_NAMES[quote.name]
            except KeyError:
                # Convert channels of the form 'death_goo' into 'Death - Goo'.
                channel, ch_arg = quote.name.split('_', 1)
                name = channel.title() + ' - ' + ch_arg.title()
                del channel, ch_arg

            group_id = quote.name
        else:
            # note: default for quote names
            name = quote['name', _('No Name!')]

        ttk.Label(
            frame,
            text=name,
            font=QUOTE_FONT,
        ).grid(
            column=0,
            sticky=W,
        )

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
            for x, (img, ctx) in enumerate(badges):
                label = ttk.Label(line_frame, image=img, padding=0)
                label.grid(row=0, column=x)
                add_tooltip(label, ctx)

            line_frame.columnconfigure(len(badges), weight=1)

            check = ttk.Checkbutton(
                line_frame,
                # note: default voice line name next to checkbox.
                text=line['name', _('No Name?')],
            )

            check.quote_var = IntVar(
                value=config.get_bool(group_id, line_id, True),
            )

            check['variable'] = check.quote_var

            check['command'] = functools.partial(
                check_toggled,
                var=check.quote_var,
                config_section=config[group_id],
                quote_id=line_id,
            )
            check.transcript = list(get_trans_lines(line))
            check.grid(
                row=0,
                column=len(badges),
            )
            check.bind("<Enter>", show_trans)

    def configure_canv(e):
        """Allow resizing the windows."""
        canv['scrollregion'] = (
            4,
            0,
            canv.winfo_reqwidth(),
            frame.winfo_reqheight(),
        )
        frame['width'] = canv.winfo_reqwidth()

    canv.bind('<Configure>', configure_canv)

    return outer_frame


def find_lines(quote_block: Property) -> Iterator[Tuple[
    List[Tuple[PhotoImage, str]],
    Property,
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


def find_resp_lines(quote_block: Property) -> Iterator[Tuple[
    List[Tuple[PhotoImage, str]],
    Property,
    str,
]]:
    """Find the line blocks in response items."""
    for index, prop in enumerate(quote_block):
        yield [], prop, 'line_{}'.format(index)


def get_trans_lines(trans_block):
    for prop in trans_block:
        if prop.name == 'trans':
            if ':' in prop.value:
                name, trans = prop.value.split(':', 1)
                yield name.rstrip(), ': "' + trans.lstrip() + '"'
            else:
                yield '', '"' + prop.value + '"'

if __name__ == '__main__':
    import packageLoader
    data = packageLoader.load_packages('packages\\', False)

    TK_ROOT = Tk()
    lab = ttk.Label(TK_ROOT, text='Root Window')
    lab.bind(utils.EVENTS['LEFT'], lambda e: show(d['BEE2_CAVE_50s']))
    lab.grid()
    init_widgets()
    d = {quote.id: quote for quote in data['QuotePack']}
    print(d)
    show(d['BEE2_GLADOS_CLEAN'])
