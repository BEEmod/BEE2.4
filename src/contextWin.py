"""
The rightclick pane which shows item descriptions,and allows changing
various item properties.
- init() creates all the required widgets, and is called with the root window.
- showProps() shows the screen.
- hideProps() hides the screen.
- open_event is the TK callback version of showProps(), which gets the
  clicked widget from the event
"""
from tkinter import *
from tk_root import TK_ROOT
from tkinter import ttk
from tkinter import messagebox
import functools
import webbrowser

from richTextBox import tkRichText
import img as png
import sound as snd
import itemPropWin
import tooltip
import utils

OPEN_IN_TAB = 2

wid = dict()

# Holds the 5 sprite labels
wid['subitem'] = [0, 0, 0, 0, 0]
wid['sprite'] = [0, 0, 0, 0, 0]


selected_item = None
selected_sub_item = None
is_open = False

version_lookup = []

SUBITEM_POS = {
    # Positions of subitems depending on the number of subitems that exist
    # This way they appear nicely centered on the list
    1: (-1, -1,  0, -1, -1),  # __0__
    2: (-1,  0, -1,  1, -1),  # _0_0_
    3: (-1,  0,  1,  2, -1),  # _000_
    4: ( 0,  1, -1,  2,  3),  # 00_00
    5: ( 0,  1,  2,  3,  4),  # 00000
}

ROT_TYPES = {
    #  Image names that correspond to editoritems values
    "handle_none":          "rot_0",
    "handle_4_directions":  "rot_4",
    "handle_5_positions":   "rot_5",
    "handle_6_positions":   "rot_6",
    "handle_8_positions":   "rot_8",
    "handle_36_directions": "rot_36",
    "handle_catapult":      "rot_catapult"
}


def pos_for_item():
    """Get the index the selected item is located at."""
    pos = SUBITEM_POS[selected_item.num_sub]
    sub_key = selected_sub_item.subKey
    for ind, sub in enumerate(pos):
        if sub_key == sub:
            return ind
    else:
        return None


def hide_item_props(vals):
    snd.fx('contract')
    print(vals)
    selected_item.set_properties(vals)


def sub_sel(ind, _=None):
    """Change the currently-selected sub-item."""
    # Can only change the subitem on the preview window
    if selected_sub_item.is_pre:
        pos = SUBITEM_POS[selected_item.num_sub][ind]
        if pos != -1 and pos != selected_sub_item.subKey:
            snd.fx('config')
            selected_sub_item.change_subtype(pos)
            # Redisplay the window to refresh data and move it to match
            show_prop(selected_sub_item, warp_cursor=True)


def sub_open(ind, _=None):
    """Move the context window to apply to the given item."""
    pos = SUBITEM_POS[selected_item.num_sub][ind]
    if pos != -1 and pos != selected_sub_item.subKey:
        snd.fx('expand')
        selected_sub_item.open_menu_at_sub(pos)


def more_info_show_url(_=None):
    if selected_item.url is not None:
        tooltip.show(
            wid['moreinfo'],
            selected_item.url,
        )


def open_event(e):
    """Read data from the event, and show the window."""
    snd.fx('expand')
    show_prop(e.widget)


def show_prop(widget, warp_cursor=False):
    """Show the properties window for an item.

    wid should be the UI.PalItem widget that represents the item.
    If warp_cursor is  true, the cursor will be moved relative to this window so
    it stays on top of the selected subitem.
    """
    global selected_item, selected_sub_item, is_open
    if warp_cursor and is_open:
        cursor_x, cursor_y = prop_window.winfo_pointerxy()
        off_x = cursor_x-prop_window.winfo_rootx()
        off_y = cursor_y-prop_window.winfo_rooty()
    else:
        off_x, off_y = None, None
    prop_window.deiconify()
    prop_window.lift(TK_ROOT)
    selected_item = widget.item
    selected_sub_item = widget
    is_open = True

    icon_widget = wid['subitem'][pos_for_item()]

    # Calculate the pixel offset between the window and the subitem in
    # the properties dialog, and shift if needed to keep it inside the
    # window
    loc_x, loc_y = utils.adjust_inside_screen(
        x=(
            widget.winfo_rootx()
            + prop_window.winfo_rootx()
            - icon_widget.winfo_rootx()
        ),
        y=(
            widget.winfo_rooty()
            + prop_window.winfo_rooty()
            - icon_widget.winfo_rooty()
        ),
        win=prop_window,
    )

    prop_window.geometry('+{x!s}+{y!s}'.format(x=loc_x, y=loc_y))
    prop_window.relX = loc_x-TK_ROOT.winfo_x()
    prop_window.relY = loc_y-TK_ROOT.winfo_y()

    if off_x is not None and off_y is not None:
        # move the mouse cursor
        prop_window.event_generate('<Motion>', warp=True, x=off_x, y=off_y)

    load_item_data()


def set_item_version(_=None):
    selected_item.change_version(version_lookup[wid['variant'].current()])
    load_item_data()


def load_item_data():
    """Refresh the window to use the selected item's data."""
    global version_lookup
    item_data = selected_item.data

    for ind, pos in enumerate(SUBITEM_POS[selected_item.num_sub]):
        if pos == -1:
            wid['subitem'][ind]['image'] = png.png('BEE2/alpha_64')
        else:
            wid['subitem'][ind]['image'] = selected_item.get_icon(pos)
        wid['subitem'][ind]['relief'] = 'flat'

    wid['subitem'][pos_for_item()]['relief'] = 'raised'

    wid['author']['text'] = ', '.join(item_data['auth'])
    wid['name']['text'] = selected_sub_item.name
    wid['ent_count']['text'] = item_data['ent']

    wid['desc'].set_text(item_data['desc'])

    if itemPropWin.can_edit(selected_item.properties()):
        wid['changedefaults'].state(['!disabled'])
    else:
        wid['changedefaults'].state(['disabled'])

    if selected_item.is_wip and selected_item.is_dep:
        wid['wip_dep']['text'] = 'WIP, Deprecated Item!'
    elif selected_item.is_wip:
        wid['wip_dep']['text'] = 'WIP Item!'
    elif selected_item.is_dep:
        wid['wip_dep']['text'] = 'Deprecated Item!'
    else:
        wid['wip_dep']['text'] = ''

    version_lookup, version_names = selected_item.get_version_names()
    if len(version_names) <= 1:
        # There aren't any alternates to choose from, disable the box
        wid['variant'].state(['disabled'])
        # We want to display WIP / Dep tags still, so users know.
        if selected_item.is_wip and selected_item.is_dep:
            wid['variant']['values'] = ['[WIP] [DEP] No Alts!']
        elif selected_item.is_wip:
            wid['variant']['values'] = ['[WIP] No Alt Versions!']
        elif selected_item.is_dep:
            wid['variant']['values'] = ['[DEP] No Alt Versions!']
        else:
            wid['variant']['values'] = ['No Alternate Versions!']
        wid['variant'].current(0)
    else:
        wid['variant'].state(['!disabled'])
        wid['variant']['values'] = version_names
        wid['variant'].current(version_lookup.index(selected_item.selected_ver))

    if selected_item.url is None:
        wid['moreinfo'].state(['disabled'])
    else:
        wid['moreinfo'].state(['!disabled'])
    editor_data = item_data['editor']
    has_inputs = False
    has_polarity = False
    has_outputs = False
    for inp_list in editor_data.find_all("Exporting", "Inputs"):
        for inp in inp_list:
            if inp.name == "CONNECTION_STANDARD":
                has_inputs = True
            elif inp.name == "CONNECTION_TBEAM_POLARITY":
                has_polarity = True
    for out_list in editor_data.find_all("Exporting", "Outputs"):
        for out in out_list:
            if out.name == "CONNECTION_STANDARD":
                has_outputs = True
                break
    has_timer = any(editor_data.find_all("Properties", "TimerDelay"))

    editor_bit = next(editor_data.find_all("Editor"))
    rot_type = editor_bit["MovementHandle", "HANDLE_NONE"].casefold()

    facing_type = editor_bit["InvalidSurface", ""].casefold()
    surf_wall = "wall" in facing_type
    surf_floor = "floor" in facing_type
    surf_ceil = "ceiling" in facing_type

    is_embed = any(editor_data.find_all("Exporting", "EmbeddedVoxels"))

    if has_inputs:
        if has_polarity:
            wid['sprite'][0]['image'] = png.spr('in_polarity')
        else:
            wid['sprite'][0]['image'] = png.spr('in_norm')
    else:
        wid['sprite'][0]['image'] = png.spr('in_none')

    if has_outputs:
        if has_timer:
            wid['sprite'][1]['image'] = png.spr('out_tim')
        else:
            wid['sprite'][1]['image'] = png.spr('out_norm')
    else:
        wid['sprite'][1]['image'] = png.spr('out_none')

    wid['sprite'][2]['image'] = png.spr(
        ROT_TYPES.get(
            rot_type.casefold(),
            'rot_none',
        )
    )

    if is_embed:
        wid['sprite'][3]['image'] = png.spr('space_embed')
    else:
        wid['sprite'][3]['image'] = png.spr('space_none')

    face_spr = "surf"
    if not surf_wall:
        face_spr += "_wall"
    if not surf_floor:
        face_spr += "_floor"
    if not surf_ceil:
        face_spr += "_ceil"
    if face_spr == "surf":
        face_spr += "_none"
    wid['sprite'][4]['image'] = png.spr(face_spr)


def follow_main(_=None):
    """Move the properties window to keep a relative offset to the main window.

    """
    prop_window.geometry('+'+str(prop_window.relX+TK_ROOT.winfo_x()) +
                         '+'+str(prop_window.relY+TK_ROOT.winfo_y()))


def hide_context(_=None):
    """Hide the properties window, if it's open."""
    global is_open
    if is_open:
        is_open = False
        prop_window.withdraw()
        snd.fx('contract')


def init_widgets():
    """Initiallise all the window components."""
    global prop_window, moreinfo_win
    prop_window = Toplevel(TK_ROOT)
    prop_window.overrideredirect(1)
    prop_window.resizable(False, False)
    prop_window.transient(master=TK_ROOT)
    prop_window.attributes('-topmost', 1)
    prop_window.relX = 0
    prop_window.relY = 0
    prop_window.withdraw()  # starts hidden

    f = ttk.Frame(prop_window, relief="raised", borderwidth="4")
    f.grid(row=0, column=0)

    ttk.Label(
        f,
        text="Properties:",
        anchor="center",
        ).grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="EW",
            )

    wid['name'] = ttk.Label(f, text="", anchor="center")
    wid['name'].grid(row=1, column=0, columnspan=3, sticky="EW")

    wid['ent_count'] = ttk.Label(
        f,
        text="2",
        anchor="e",
        compound="left",
        image=png.spr('gear_ent'),
        )
    wid['ent_count'].grid(row=0, column=2, rowspan=2, sticky=E)

    wid['author'] = ttk.Label(f, text="", anchor="center", relief="sunken")
    wid['author'].grid(row=2, column=0, columnspan=3, sticky="EW")

    sub_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    sub_frame.grid(column=0, columnspan=3, row=3)
    for i, _ in enumerate(wid['subitem']):
        wid['subitem'][i] = ttk.Label(
            sub_frame,
            image=png.png('BEE2/alpha_64'),
        )
        wid['subitem'][i].grid(row=0, column=i)
        wid['subitem'][i].bind(utils.EVENTS['LEFT'], functools.partial(sub_sel, i))
        utils.bind_rightclick(
            wid['subitem'][i],
            functools.partial(sub_open, i),
        )

    wid['wip_dep'] = ttk.Label(f, text='', anchor="nw")
    wid['wip_dep'].grid(row=4, column=0, sticky="NW")

    ttk.Label(f, text="Description:", anchor="sw").grid(
        row=4,
        column=0,
        sticky="SW",
        )

    spr_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
    # sprites: inputs, outputs, rotation handle, occupied/embed state,
    # desiredFacing
    for i in range(5):
        spr = png.spr('ap_grey')
        wid['sprite'][i] = ttk.Label(spr_frame, image=spr, relief="raised")
        wid['sprite'][i].grid(row=0, column=i)

    desc_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=5, column=0, columnspan=3, sticky="EW")

    wid['desc'] = tkRichText(desc_frame, width=40, height=8, font=None)
    wid['desc'].grid(row=0, column=0, sticky="EW")

    desc_scroll = ttk.Scrollbar(
        desc_frame,
        orient=VERTICAL,
        command=wid['desc'].yview,
        )
    wid['desc']['yscrollcommand'] = desc_scroll.set
    desc_scroll.grid(row=0, column=1, sticky="NS")

    def show_more_info():
        url = selected_item.url
        if url is not None:
            try:
                webbrowser.open(url, new=OPEN_IN_TAB, autoraise=True)
            except webbrowser.Error:
                if messagebox.askyesno(
                        icon="error",
                        title="BEE2 - Error",
                        message='Failed to open a web browser. Do you wish for '
                                'the URL to be copied to the clipboard '
                                'instead?',
                        detail='"{!s}"'.format(url),
                        parent=prop_window
                        ):
                    print("Saving " + url + "to clipboard!")
                    TK_ROOT.clipboard_clear()
                    TK_ROOT.clipboard_append(url)
            # Either the webbrowser or the messagebox could cause the
            # properties to move behind the main window, so hide it
            # so it doesn't appear there.
            hide_context(None)

    wid['moreinfo'] = ttk.Button(f, text="More Info>>", command=show_more_info)
    wid['moreinfo'].grid(row=6, column=2, sticky=E)
    wid['moreinfo'].bind('<Enter>', more_info_show_url)
    wid['moreinfo'].bind('<Leave>', tooltip.hide)

    menu_info = Menu(wid['moreinfo'])
    menu_info.add_command(label='', state='disabled')

    def show_item_props():
        snd.fx('expand')
        itemPropWin.show_window(
            selected_item.get_properties(),
            wid['changedefaults'],
            selected_sub_item.name,
        )

    wid['changedefaults'] = ttk.Button(
        f,
        text="Change Defaults...",
        command=show_item_props,
        )
    wid['changedefaults'].grid(row=6, column=1)

    wid['variant'] = ttk.Combobox(f, values=['VERSION'], exportselection=0)
    wid['variant'].state(['readonly'])  # Prevent directly typing in values
    wid['variant'].bind('<<ComboboxSelected>>', set_item_version)
    wid['variant'].current(0)
    wid['variant'].grid(row=6, column=0, sticky=W)

    itemPropWin.init(hide_item_props)
