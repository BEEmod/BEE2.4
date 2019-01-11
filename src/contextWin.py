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

from srctools import Property
from tk_tools import TK_ROOT
from tkinter import ttk
from tkinter import messagebox

from enum import Enum
import functools
import webbrowser
import srctools.logger

from richTextBox import tkRichText
import img
import itemconfig
import sound as snd
import itemPropWin
import tkMarkdown
import tooltip
import tk_tools
import utils
import packageLoader

import UI

LOGGER = srctools.logger.get_logger(__name__)

OPEN_IN_TAB = 2

wid = {}

selected_item = None  # type: UI.Item
selected_sub_item = None  # type: UI.PalItem
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


class SPR(Enum):
    """The slots for property-indicating sprites. The value is the column."""
    INPUT = 0
    OUTPUT = 1
    ROTATION = 2
    COLLISION = 3
    FACING = 4

SPRITE_TOOL = {
    # The tooltips associated with each sprite.
    'rot_0': _('This item may not be rotated.'),
    'rot_4': _('This item can be pointed in 4 directions.'),
    'rot_5': _('This item can be positioned on the sides and center.'),
    'rot_6': _('This item can be centered in two directions, plus on the sides.'),
    'rot_8': _('This item can be placed like light strips.'),
    'rot_36': _('This item can be rotated on the floor to face 360 degrees.'),
    'rot_catapult': _('This item is positioned using a catapult trajectory.'),
    'rot_paint': _('This item positions the dropper to hit target locations.'),

    'in_none': _('This item does not accept any inputs.'),
    'in_norm': _('This item accepts inputs.'),
    'in_dual': _('This item has two input types (A and B), using the Input A and B items.'),

    'out_none': _('This item does not output.'),
    'out_norm': _('This item has an output.'),
    'out_tim': _('This item has a timed output.'),

    'space_none': _('This item does not take up any space inside walls.'),
    'space_embed': _('This item takes space inside the wall.'),

    'surf_none': _('This item cannot be placed anywhere...'),
    'surf_ceil': _('This item can only be attached to ceilings.'),
    'surf_floor': _('This item can only be placed on the floor.'),
    'surf_floor_ceil': _('This item can be placed on floors and ceilings.'),
    'surf_wall': _('This item can be placed on walls only.'),
    'surf_wall_ceil': _('This item can be attached to walls and ceilings.'),
    'surf_wall_floor': _('This item can be placed on floors and walls.'),
    'surf_wall_floor_ceil': _('This item can be placed in any orientation.'),
}


def set_sprite(pos, sprite):
    """Set one of the property sprites to a value."""
    widget = wid['sprite', pos]
    widget['image'] = img.spr(sprite)
    tooltip.set_tooltip(widget, SPRITE_TOOL.get(sprite, ''))


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
    selected_item.set_properties(vals)


def sub_sel(ind, e=None):
    """Change the currently-selected sub-item."""
    # Can only change the subitem on the preview window
    if selected_sub_item.is_pre:
        pos = SUBITEM_POS[selected_item.num_sub][ind]
        if pos != -1 and pos != selected_sub_item.subKey:
            snd.fx('config')
            selected_sub_item.change_subtype(pos)
            # Redisplay the window to refresh data and move it to match
            show_prop(selected_sub_item, warp_cursor=True)


def sub_open(ind, e=None):
    """Move the context window to apply to the given item."""
    pos = SUBITEM_POS[selected_item.num_sub][ind]
    if pos != -1 and pos != selected_sub_item.subKey:
        snd.fx('expand')
        selected_sub_item.open_menu_at_sub(pos)


def open_event(item):
    """Show the window for a particular PalItem."""
    def func(e):
        snd.fx('expand')
        show_prop(item)
    return func


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

    adjust_position()

    if off_x is not None and off_y is not None:
        # move the mouse cursor
        prop_window.event_generate('<Motion>', warp=True, x=off_x, y=off_y)

    load_item_data()


def set_item_version(e=None):
    """Callback for the version combobox. Set the item variant."""
    selected_item.change_version(version_lookup[wid['variant'].current()])
    # Refresh our data.
    load_item_data()

    # Refresh itemconfig comboboxes to match us.
    for func in itemconfig.ITEM_VARIANT_LOAD:
        if func.item_id == selected_item.id:
            func()


def set_version_combobox(box: ttk.Combobox, item: 'UI.Item') -> list:
    """Set values on the variant combobox.

    This is in a function so itemconfig can reuse it.
    It returns a list of IDs in the same order as the names.
    """
    ver_lookup, version_names = item.get_version_names()
    if len(version_names) <= 1:
        # There aren't any alternates to choose from, disable the box
        box.state(['disabled'])
        box['values'] = [_('No Alternate Versions!')]
        box.current(0)
    else:
        box.state(['!disabled'])
        box['values'] = version_names
        box.current(ver_lookup.index(item.selected_ver))
    return ver_lookup


def get_description(global_last, glob_desc, style_desc):
    """Join together the general and style description for an item."""
    if glob_desc and style_desc:
        if global_last:
            return tkMarkdown.join(style_desc, glob_desc)
        else:
            return tkMarkdown.join(glob_desc, style_desc)
    elif glob_desc:
        return glob_desc
    elif style_desc:
        return style_desc
    else:
        return tkMarkdown.MarkdownData()  # No description


def load_item_data():
    """Refresh the window to use the selected item's data."""
    global version_lookup
    item_data = selected_item.data

    for ind, pos in enumerate(SUBITEM_POS[selected_item.num_sub]):
        if pos == -1:
            wid['subitem', ind]['image'] = img.invis_square(64)
        else:
            wid['subitem', ind]['image'] = selected_item.get_icon(pos)
        wid['subitem', ind]['relief'] = 'flat'

    wid['subitem', pos_for_item()]['relief'] = 'raised'

    wid['author']['text'] = ', '.join(item_data.authors)
    wid['name']['text'] = selected_sub_item.name
    wid['ent_count']['text'] = item_data.ent_count or '??'

    wid['desc'].set_text(
        get_description(
            global_last=selected_item.item.glob_desc_last,
            glob_desc=selected_item.item.glob_desc,
            style_desc=item_data.desc,
        )
    )

    if itemPropWin.can_edit(selected_item.properties()):
        wid['changedefaults'].state(['!disabled'])
    else:
        wid['changedefaults'].state(['disabled'])

    version_lookup = set_version_combobox(wid['variant'], selected_item)

    if selected_item.url is None:
        wid['moreinfo'].state(['disabled'])
    else:
        wid['moreinfo'].state(['!disabled'])
    tooltip.set_tooltip(wid['moreinfo'], selected_item.url)

    editor_data = item_data.editor.copy()

    comm_block = Property(selected_item.id, [])
    (
        has_inputs,
        has_outputs,
        has_secondary,
    ) = packageLoader.Item.convert_item_io(comm_block, editor_data)
    del comm_block  # We don't use the config.

    has_timer = any(editor_data.find_all("Properties", "TimerDelay"))

    editor_bit = next(editor_data.find_all("Editor"))
    rot_type = editor_bit["MovementHandle", "HANDLE_NONE"].casefold()

    facing_type = editor_bit["InvalidSurface", ""].casefold()
    surf_wall = "wall" in facing_type
    surf_floor = "floor" in facing_type
    surf_ceil = "ceiling" in facing_type

    is_embed = any(editor_data.find_all("Exporting", "EmbeddedVoxels"))

    if has_inputs:
        if has_secondary:
            set_sprite(SPR.INPUT, 'in_dual')
            # Real funnels work slightly differently.
            if selected_item.id.casefold() == 'item_tbeam':
                wid['sprite', SPR.INPUT].tooltip_text = _(
                    'Excursion Funnels accept a on/off '
                    'input and a directional input.'
                )
        else:
            set_sprite(SPR.INPUT, 'in_norm')
    else:
        set_sprite(SPR.INPUT, 'in_none')

    if has_outputs:
        if has_timer:
            set_sprite(SPR.OUTPUT, 'out_tim')
        else:
            set_sprite(SPR.OUTPUT, 'out_norm')
    else:
        set_sprite(SPR.OUTPUT, 'out_none')

    set_sprite(
        SPR.ROTATION,
        ROT_TYPES.get(
            rot_type.casefold(),
            'rot_none',
        )
    )

    if is_embed:
        set_sprite(SPR.COLLISION, 'space_embed')
    else:
        set_sprite(SPR.COLLISION, 'space_none')

    face_spr = "surf"
    if not surf_wall:
        face_spr += "_wall"
    if not surf_floor:
        face_spr += "_floor"
    if not surf_ceil:
        face_spr += "_ceil"
    if face_spr == "surf":
        # This doesn't seem right - this item won't be placeable at all...
        LOGGER.warning(
            "Item <{}> disallows all orientations. Is this right?",
            selected_item.id,
        )
        face_spr += "_none"

    set_sprite(SPR.FACING, face_spr)

    # Now some special overrides for certain classes.
    if selected_item.id == "ITEM_CUBE":
        # Cubes - they should show info for the dropper.
        set_sprite(SPR.FACING, 'surf_ceil')
        set_sprite(SPR.INPUT, 'in_norm')
        set_sprite(SPR.COLLISION, 'space_embed')
        set_sprite(SPR.OUTPUT, 'out_none')
        set_sprite(SPR.ROTATION, 'rot_36')
        tooltip.set_tooltip(
            wid['sprite', SPR.ROTATION],
            SPRITE_TOOL['rot_36'] + _(
                'This item can be rotated on the floor to face 360 '
                'degrees, for Reflection Cubes only.'
            ),
        )

    item_class = editor_data['ItemClass', ''].casefold()
    if item_class == "itempaintsplat":
        # Reflection or normal gel..
        set_sprite(SPR.FACING, 'surf_wall_ceil')
        set_sprite(SPR.INPUT, 'in_norm')
        set_sprite(SPR.COLLISION, 'space_none')
        set_sprite(SPR.OUTPUT, 'out_none')
        set_sprite(SPR.ROTATION, 'rot_paint')
    elif item_class == 'itemrailplatform':
        # Track platform - always embeds into the floor.
        set_sprite(SPR.COLLISION, 'space_embed')



def adjust_position(e=None):
    """Move the properties window onto the selected item.

    We call this constantly, so the property window will not go outside
    the screen, and snap back to the item when the main window returns.
    """
    if not is_open or selected_sub_item is None:
        return

    # Calculate the pixel offset between the window and the subitem in
    # the properties dialog, and shift if needed to keep it inside the
    # window
    icon_widget = wid['subitem', pos_for_item()]

    loc_x, loc_y = utils.adjust_inside_screen(
        x=(
            selected_sub_item.winfo_rootx()
            + prop_window.winfo_rootx()
            - icon_widget.winfo_rootx()
        ),
        y=(
            selected_sub_item.winfo_rooty()
            + prop_window.winfo_rooty()
            - icon_widget.winfo_rooty()
        ),
        win=prop_window,
    )

    prop_window.geometry('+{x!s}+{y!s}'.format(x=loc_x, y=loc_y))

# When the main window moves, move the context window also.
TK_ROOT.bind("<Configure>", adjust_position, add='+')


def hide_context(e=None):
    """Hide the properties window, if it's open."""
    global is_open, selected_item, selected_sub_item
    if is_open:
        is_open = False
        prop_window.withdraw()
        snd.fx('contract')
        selected_item = selected_sub_item = None


def init_widgets():
    """Initiallise all the window components."""
    global prop_window
    prop_window = Toplevel(TK_ROOT)
    prop_window.overrideredirect(1)
    prop_window.resizable(False, False)
    prop_window.transient(master=TK_ROOT)
    prop_window.attributes('-topmost', 1)
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
        text="",
        anchor="e",
        compound="left",
        image=img.spr('gear_ent'),
    )
    wid['ent_count'].grid(row=0, column=2, rowspan=2, sticky=E)
    tooltip.add_tooltip(
        wid['ent_count'],
        _('The number of entities used for this item. The Source engine '
          'limits this to 2048 in total. This provides a guide to how many of '
          'these items can be placed in a map at once.')
    )

    wid['author'] = ttk.Label(f, text="", anchor="center", relief="sunken")
    wid['author'].grid(row=2, column=0, columnspan=3, sticky="EW")

    sub_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    sub_frame.grid(column=0, columnspan=3, row=3)
    for i in range(5):
        wid['subitem', i] = ttk.Label(
            sub_frame,
            image=img.invis_square(64),
        )
        wid['subitem', i].grid(row=0, column=i)
        utils.bind_leftclick(
            wid['subitem', i],
            functools.partial(sub_sel, i),
        )
        utils.bind_rightclick(
            wid['subitem', i],
            functools.partial(sub_open, i),
        )

    ttk.Label(f, text=_("Description:"), anchor="sw").grid(
        row=4,
        column=0,
        sticky="SW",
    )

    spr_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
    # sprites: inputs, outputs, rotation handle, occupied/embed state,
    # desiredFacing
    for spr_id in SPR:
        wid['sprite', spr_id] = sprite = ttk.Label(
            spr_frame,
            image=img.spr('ap_grey'),
            relief="raised",
        )
        sprite.grid(row=0, column=spr_id.value)
        tooltip.add_tooltip(sprite)

    desc_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=5, column=0, columnspan=3, sticky="EW")
    desc_frame.columnconfigure(0, weight=1)

    wid['desc'] = tkRichText(desc_frame, width=40, height=16)
    wid['desc'].grid(row=0, column=0, sticky="EW")

    desc_scroll = tk_tools.HidingScroll(
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
                        message=_('Failed to open a web browser. Do you wish '
                                  'for the URL to be copied to the clipboard '
                                  'instead?'),
                        detail='"{!s}"'.format(url),
                        parent=prop_window
                        ):
                    LOGGER.info("Saving {} to clipboard!", url)
                    TK_ROOT.clipboard_clear()
                    TK_ROOT.clipboard_append(url)
            # Either the webbrowser or the messagebox could cause the
            # properties to move behind the main window, so hide it
            # so it doesn't appear there.
            hide_context(None)

    wid['moreinfo'] = ttk.Button(f, text=_("More Info>>"), command=show_more_info)
    wid['moreinfo'].grid(row=6, column=2, sticky=E)
    tooltip.add_tooltip(wid['moreinfo'])

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
        text=_("Change Defaults..."),
        command=show_item_props,
        )
    wid['changedefaults'].grid(row=6, column=1)
    tooltip.add_tooltip(
        wid['changedefaults'],
        _('Change the default settings for this item when placed.')
    )

    wid['variant'] = ttk.Combobox(
        f,
        values=['VERSION'],
        exportselection=0,
        # On Mac this defaults to being way too wide!
        width=7 if utils.MAC else None,
    )
    wid['variant'].state(['readonly'])  # Prevent directly typing in values
    wid['variant'].bind('<<ComboboxSelected>>', set_item_version)
    wid['variant'].current(0)
    wid['variant'].grid(row=6, column=0, sticky=W)

    itemPropWin.init(hide_item_props)
