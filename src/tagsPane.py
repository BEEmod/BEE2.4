from tkinter import ttk
import tkinter as tk

from functools import partial
from operator import itemgetter

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
    print(sel_tags)

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
            item_tags = {
                tag.casefold()
                for tag in
                item.item.tags
            }
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


def add_tag(tag, pretty=None):
    """Add the tag to the list of known tags."""
    tag = tag.casefold()
    if tag in TAGS:
        return  # Already added

    TAGS[tag] = False
    if pretty is not None:
        PRETTY_TAG[tag] = pretty


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
    )
    cur_tags.tag_config(
        'highlight',
        underline=1,
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
        height=6,
    )
    tag_list.grid(row=1, column=0, sticky='NSEW')
    tag_list.tag_config(
        'highlight',
        underline=1,
    )

    wid['tag_scroll'] = tag_scroll = tk_tools.HidingScroll(
        exp,
        orient=tk.VERTICAL,
        command=tag_list.yview,
    )
    tag_scroll.grid(row=1, column=1, sticky='NS')
    tag_list['yscrollcommand'] = tag_scroll.set
    tag_list['state'] = "disabled" # Prevent users from editing the text
    refresh_tags()


def refresh_tags():
    """Fill in both textboxes, adding the tags to the list."""
    all_text = wid['tag_list']
    sel_text = wid['cur_tags']

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

    for tag, value in sorted(TAGS.items(), key=itemgetter(0)):
        if value:
            sel_text.tag_bind(
                'tag_' + tag,
                utils.EVENTS['LEFT'],
                partial(event_remove_tag, tag),
            )
            textbox = sel_text
        else:
            all_text.tag_bind(
                'tag_' + tag,
                utils.EVENTS['LEFT'],
                partial(event_add_tag, tag),
            )
            textbox = all_text

        textbox.insert(
            'end',
            # text, tag pairs
            '[',
            (),

            PRETTY_TAG.get(tag, tag),
            ('highlight', 'tag_' + tag),

            '], ',
            (),
        )
    # delete the trailing comma and space
    all_text.delete(all_text.index('end')+"-2char", "end")
    sel_text.delete(all_text.index('end')+"-2char", "end")

    all_text['state'] = "disabled"
    sel_text['state'] = "disabled"
