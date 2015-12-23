from tkinter import ttk
from tkinter import font
from tk_tools import TK_ROOT
import tkinter as tk

from functools import partial
from operator import itemgetter
from collections import defaultdict
from enum import Enum

import sound as snd
import optionWindow
import StyleVarPane
import UI
import utils
import tk_tools

is_expanded = False
wid = {}

TAG_MODE = tk.StringVar(value='ALL')  # The combining mode for the vars
TAG_MODES = {
    'ALL': all,
    'ANY': any,
}

# A list of all tags, mapped to their current state.
TAGS = {}
# A 'pretty' name for a tag, if it exists
PRETTY_TAG = {}

# A list of tags, sorted into sections
TAG_BY_SECTION = defaultdict(list)

BOLD_FONT = font.nametofont('TkDefaultFont').copy()
BOLD_FONT.configure(weight='bold')

class Section(Enum):
    """Sections to group tags in."""
    TAG = 'Tags'
    AUTH = 'Authors'
    PACK = 'Packages'

    def __lt__(self, other):
        return self.index(self) < self.index(other)

# __members__ is an OrderedDict, so this method gives the original order of
# items.
Section.index = [Section[key] for key in Section.__members__.keys()].index


def filter_items():
    """Update items based on selected tags."""
    show_wip = optionWindow.SHOW_WIP.get()
    style_unlocked = StyleVarPane.tk_vars['UnlockDefault'].get() == 1

    # any() or all()
    func = TAG_MODES[TAG_MODE.get()]

    sel_tags = [
        tag
        for tag, enabled
        in TAGS.items()
        if enabled
    ]
    no_tags = len(sel_tags) == 0

    for item in UI.pal_items:
        if item.needs_unlock and not style_unlocked:
            item.visible = False
            continue
        if item.item.is_wip and not show_wip:
            item.visible = False
            continue

        if no_tags:
            item.visible = True
        else:
            item_tags = item.item.filter_tags
            item.visible = func(
                tag in item_tags
                for tag in
                sel_tags
            )
    UI.flow_picker()

# When exiting settings, we need to hide/show WIP items.
optionWindow.refresh_callbacks.append(filter_items)


def expand(_):
    """Expand the filter view."""
    global is_expanded
    is_expanded = True
    wid['expand_frame'].grid(
        row=2,
        column=0,
        columnspan=2,
        sticky='NSEW',
    )
    wid['tag_list']['height'] = TK_ROOT.winfo_height() / 48

    snd.fx('expand')
    UI.flow_picker()


def contract(_):
    """Shrink the filter view."""
    global is_expanded
    is_expanded = False
    wid['expand_frame'].grid_remove()
    snd.fx('contract')
    UI.flow_picker()


def event_add_tag(tag, e):
    """Select the given tag."""
    TAGS[tag] = True
    refresh_tags()
    filter_items()


def event_remove_tag(tag, e):
    """Remove the given tag from our selection list."""
    TAGS[tag] = False
    refresh_tags()
    filter_items()



def add_tag(section: Section, tag, pretty=None):
    """Add the tag to the list of known tags, and return the ID."""
    if pretty is None:
        pretty = tag
    tag = tag.casefold()

    key = (section, tag)

    if key in TAGS:
        return key  # Already added

    TAGS[key] = False
    TAG_BY_SECTION[section].append(tag)
    PRETTY_TAG[key] = pretty


def init(frm):
    """Initialise the UI objects."""

    frm.bind('<Enter>', expand)
    frm.bind('<Leave>', contract)

    wid['tag_mode_any'] = widget = tk.Radiobutton(
        frm,
        text='Any',
        variable=TAG_MODE,
        value='ANY',
        command=filter_items,
    )
    widget.grid(row=0, column=0, sticky='W')

    wid['tag_mode_all'] = widget = tk.Radiobutton(
        frm,
        text='All',
        variable=TAG_MODE,
        value='ALL',
        command=filter_items,
    )
    widget.grid(row=1, column=0, sticky='W')

    wid['cur_tags'] = cur_tags = tk.Text(
        frm,
        font='TkDefaultFont',
        width=10,
        height=2,
        cursor=utils.CURSORS['regular'],
    )
    cur_tags.grid(row=0, rowspan=2, column=1, sticky='EW')

    wid['expand_frame'] = exp = ttk.Frame(
        frm,
    )

    # Resize to fit the expansion frame
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(2, weight=1)

    ttk.Label(
        exp,
        text='Available Tags (click):',
    ).grid(row=0, column=0, columnspan=2)

    # Make the tag section the dynamically-resizing portion
    exp.columnconfigure(0, weight=1)
    exp.rowconfigure(0, weight=1)

    wid['tag_list'] = tag_list = tk.Text(
        exp,
        font='TkDefaultFont',
        width=10,
        height=8,
        cursor=utils.CURSORS['regular'],
    )
    tag_list.grid(row=1, column=0, sticky='NSEW')

    wid['tag_scroll'] = tag_scroll = tk_tools.HidingScroll(
        exp,
        orient=tk.VERTICAL,
        command=tag_list.yview,
    )
    tag_scroll.grid(row=1, column=1, sticky='NS')
    tag_list['yscrollcommand'] = tag_scroll.set
    tag_list['state'] = "disabled"  # Prevent users from editing the text

    def event_hover_tag(text: tk.Text, e):
        """When hovering over a tag, change the cursor."""
        text['cursor'] = utils.CURSORS['link']

    def event_unhover_tag(text: tk.Text, e):
        text['cursor'] = utils.CURSORS['regular']

    for text in (tag_list, cur_tags):
        text.tag_config(
            'highlight',
            underline=1,
        )
        # We can't change the cursor property for individual tags, so
        # change it globally when the cursor enters and leaves.
        text.tag_bind(
            'highlight',
            '<Enter>',
            partial(event_hover_tag, text)
        )
        text.tag_bind(
            'highlight',
            '<Leave>',
            partial(event_unhover_tag, text)
        )
    tag_list.tag_config(
        'header',
        font=BOLD_FONT,
    )

    refresh_tags()


def refresh_tags():
    """Fill in both textboxes, adding the tags to the list."""
    all_text = wid['tag_list']  # type: tk.Text
    sel_text = wid['cur_tags']  # type: tk.Text

    # Remove existing textbox tags
    for tag in all_text.tag_names():
        if tag.startswith('tag_'):
            all_text.tag_delete(tag)
    for tag in sel_text.tag_names():
        if tag.startswith('tag_'):
            sel_text.tag_delete(tag)

    # Unset readonly, and delete everything
    all_text['state'] = "normal"
    all_text.delete(1.0, tk.END)
    sel_text['state'] = "normal"
    sel_text.delete(1.0, tk.END)

    for section, tags in sorted(TAG_BY_SECTION.items(), key=itemgetter(0)):
        all_text.insert(
            'end',
            section.value + ':\n',
            ('header',)
        )
        for tag in sorted(tags):
            bind_val = 'tag_' + section.name + '_' + tag
            tag_key = (section, tag)
            if TAGS[tag_key]:
                sel_text.tag_bind(
                    bind_val,
                    utils.EVENTS['LEFT'],
                    partial(event_remove_tag, tag_key),
                )
                textbox = sel_text
            else:
                all_text.tag_bind(
                    bind_val,
                    utils.EVENTS['LEFT'],
                    partial(event_add_tag, tag_key),
                )
                textbox = all_text

            textbox.insert(
                'end',
                # text, tag pairs
                '[',
                (),

                PRETTY_TAG[tag_key],
                ('highlight', bind_val),

                '], ',
                (),
            )
        # delete the trailing comma and space after each category
        all_text.delete(all_text.index('end') + "-3char", "end")
        # Line break between categories
        all_text.insert('end', '\n', ('header',))

    # Delete the last line break
    all_text.delete(all_text.index('end') + "-1char", "end")
    # Delete the trailing comma in the selected tags pane
    sel_text.delete(all_text.index('end') + "-3char", "end")

    all_text['state'] = "disabled"
    sel_text['state'] = "disabled"
