"""
The rightclick pane which shows item descriptions,and allows changing
various item properties.
- init() creates all the required widgets, and is called with the root window.
- showProps() shows the screen.
- hideProps() hides the screen.
- open_event is the TK callback version of showProps(), which gets the
  clicked widget from the event
"""
from __future__ import annotations
from typing import Any
from enum import Enum
import functools
import webbrowser

import tkinter as tk
from tkinter import ttk

from .richTextBox import tkRichText
from . import (
    itemconfig, localisation, tkMarkdown, tooltip, tk_tools, sound, img, UI,
    TK_ROOT, DEV_MODE, background_run
)
from .item_properties import PropertyWindow
import utils
import srctools.logger
from editoritems import Handle as RotHandle, Surface, ItemClass, FSPath
from editoritems_props import prop_timer_delay
from app.localisation import TransToken


LOGGER = srctools.logger.get_logger(__name__)

wid: dict[str, Any] = {}
wid_subitem: dict[int, ttk.Label] = {}
wid_sprite: dict[SPR, ttk.Label] = {}

selected_item: UI.Item
selected_sub_item: UI.PalItem

version_lookup: list[str] = []

window = tk.Toplevel(TK_ROOT)
window.overrideredirect(True)
window.resizable(False, False)
window.transient(master=TK_ROOT)
window.withdraw()  # starts hidden

SUBITEM_POS = {
    # Positions of subitems depending on the number of subitems that exist
    # This way they appear nicely centered on the list
    1: (-1, -1,  0, -1, -1),  # __0__
    2: (-1,  0, -1,  1, -1),  # _0_0_
    3: (-1,  0,  1,  2, -1),  # _000_
    4: (+0,  1, -1,  2,  3),  # 00_00
    5: (+0,  1,  2,  3,  4),  # 00000
}

ROT_TYPES: dict[RotHandle, str] = {
    #  Image names that correspond to editoritems values
    RotHandle.NONE:     "rot_0",
    RotHandle.QUAD:     "rot_4",
    RotHandle.CENT_OFF: "rot_5",
    RotHandle.DUAL_OFF: "rot_6",
    RotHandle.QUAD_OFF: "rot_8",
    RotHandle.FREE_ROT: "rot_36",
    RotHandle.FAITH:    "rot_catapult",
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
    'rot_0': TransToken.ui('This item may not be rotated.'),
    'rot_4': TransToken.ui('This item can be pointed in 4 directions.'),
    'rot_5': TransToken.ui('This item can be positioned on the sides and center.'),
    'rot_6': TransToken.ui('This item can be centered in two directions, plus on the sides.'),
    'rot_8': TransToken.ui('This item can be placed like light strips.'),
    'rot_36': TransToken.ui('This item can be rotated on the floor to face 360 degrees.'),
    'rot_catapult': TransToken.ui('This item is positioned using a catapult trajectory.'),
    'rot_paint': TransToken.ui('This item positions the dropper to hit target locations.'),

    'in_none': TransToken.ui('This item does not accept any inputs.'),
    'in_norm': TransToken.ui('This item accepts inputs.'),
    'in_dual': TransToken.ui('This item has two input types (A and B), using the Input A and B items.'),

    'out_none': TransToken.ui('This item does not output.'),
    'out_norm': TransToken.ui('This item has an output.'),
    'out_tim': TransToken.ui('This item has a timed output.'),

    'space_none': TransToken.ui('This item does not take up any space inside walls.'),
    'space_embed': TransToken.ui('This item takes space inside the wall.'),

    'surf_none': TransToken.ui('This item cannot be placed anywhere...'),
    'surf_ceil': TransToken.ui('This item can only be attached to ceilings.'),
    'surf_floor': TransToken.ui('This item can only be placed on the floor.'),
    'surf_floor_ceil': TransToken.ui('This item can be placed on floors and ceilings.'),
    'surf_wall': TransToken.ui('This item can be placed on walls only.'),
    'surf_wall_ceil': TransToken.ui('This item can be attached to walls and ceilings.'),
    'surf_wall_floor': TransToken.ui('This item can be placed on floors and walls.'),
    'surf_wall_floor_ceil': TransToken.ui('This item can be placed in any orientation.'),
}
IMG_ALPHA: img.Handle = img.Handle.blank(64, 64)
# Special case tooltips
TRANS_TOOL_TBEAM = TransToken.ui('Excursion Funnels accept a on/off input and a directional input.')
TRANS_TOOL_CUBE = TransToken.ui(
    '{generic_rot} However when this is set to Reflection Cube, this item can instead rotated on '
    'the floor to face 360 degrees.'
)
TRANS_NO_VERSIONS = TransToken.ui('No Alternate Versions')


def set_sprite(pos: SPR, sprite: str) -> None:
    """Set one of the property sprites to a value."""
    widget = wid_sprite[pos]
    img.apply(widget, img.Handle.sprite('icons/' + sprite, 32, 32))
    tooltip.set_tooltip(widget, SPRITE_TOOL[sprite])


def pos_for_item(ind: int) -> int | None:
    """Get the index the specified subitem is located at."""
    positions = SUBITEM_POS[len(selected_item.visual_subtypes)]
    for pos, sub in enumerate(positions):
        if sub != -1 and ind == selected_item.visual_subtypes[sub]:
            return pos
    else:
        return None


def ind_for_pos(pos: int) -> int | None:
    """Return the subtype index for the specified position."""
    ind = SUBITEM_POS[len(selected_item.visual_subtypes)][pos]
    if ind == -1:
        return None
    else:
        return selected_item.visual_subtypes[ind]


def hide_item_props() -> None:
    """Called when the item properties panel is hidden."""
    sound.fx('contract')
    if is_visible():
        # Restore the context window if we hid it earlier.
        window.deiconify()


def sub_sel(pos, e=None) -> None:
    """Change the currently-selected sub-item."""
    ind = ind_for_pos(pos)
    # Can only change the subitem on the preview window
    if selected_sub_item.is_pre and ind is not None:
        sound.fx('config')
        selected_sub_item.change_subtype(ind)
        # Redisplay the window to refresh data and move it to match
        show_prop(selected_sub_item, warp_cursor=True)


def sub_open(pos, e=None):
    """Move the context window to apply to the given item."""
    ind = ind_for_pos(pos)
    if ind is not None:
        sound.fx('expand')
        selected_sub_item.open_menu_at_sub(ind)


def open_event(item):
    """Show the window for a particular PalItem."""
    def func(e):
        sound.fx('expand')
        show_prop(item)
    return func

def is_visible() -> bool:
    """Checks if the window is visible."""
    return window.winfo_ismapped()


def show_prop(widget, warp_cursor=False):
    """Show the properties window for an item.

    wid should be the UI.PalItem widget that represents the item.
    If warp_cursor is  true, the cursor will be moved relative to this window so
    it stays on top of the selected subitem.
    """
    global selected_item, selected_sub_item
    if warp_cursor and is_visible():
        cursor_x, cursor_y = window.winfo_pointerxy()
        off_x = cursor_x - window.winfo_rootx()
        off_y = cursor_y - window.winfo_rooty()
    else:
        off_x, off_y = None, None
    window.deiconify()
    window.lift()
    selected_item = widget.item
    selected_sub_item = widget

    adjust_position()

    if off_x is not None and off_y is not None:
        # move the mouse cursor
        window.event_generate('<Motion>', warp=True, x=off_x, y=off_y)

    load_item_data()


def set_item_version(e=None):
    """Callback for the version combobox. Set the item variant."""
    selected_item.change_version(version_lookup[wid['variant'].current()])
    # Refresh our data.
    load_item_data()

    # Refresh itemconfig comboboxes to match us.
    for item_id, func in itemconfig.ITEM_VARIANT_LOAD:
        if selected_item.id == item_id:
            func()


def set_version_combobox(box: ttk.Combobox, item: 'UI.Item') -> list[str]:
    """Set values on the variant combobox.

    This is in a function so itemconfig can reuse it.
    It returns a list of IDs in the same order as the names.
    """
    ver_lookup, version_names = item.get_version_names()
    if len(version_names) <= 1:
        # There aren't any alternates to choose from, disable the box
        box.state(['disabled'])
        box['values'] = [str(TRANS_NO_VERSIONS)]
        box.current(0)
    else:
        box.state(['!disabled'])
        box['values'] = version_names
        box.current(ver_lookup.index(item.selected_ver))
    return ver_lookup


def get_description(global_last, glob_desc, style_desc) -> tkMarkdown.MarkdownData:
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


def load_item_data() -> None:
    """Refresh the window to use the selected item's data."""
    item_data = selected_item.data

    for ind, pos in enumerate(SUBITEM_POS[len(selected_item.visual_subtypes)]):
        if pos == -1:
            icon = IMG_ALPHA
        else:
            icon = selected_item.get_icon(selected_item.visual_subtypes[pos])
        img.apply(wid_subitem[ind], icon)
        wid_subitem[ind]['relief'] = 'flat'

    wid_subitem[pos_for_item(selected_sub_item.subKey)]['relief'] = 'raised'

    wid['author']['text'] = ', '.join(item_data.authors)
    localisation.set_text(wid['name'], selected_sub_item.name)
    wid['ent_count']['text'] = item_data.ent_count or '??'

    desc = get_description(
        global_last=selected_item.item.glob_desc_last,
        glob_desc=selected_item.item.glob_desc,
        style_desc=item_data.desc,
    )
    # Dump out the instances used in this item.
    if DEV_MODE.get():
        inst_desc = []
        for editor in [selected_item.data.editor] + selected_item.data.editor_extra:
            if editor is selected_item.data.editor:
                heading = '\n\nInstances:\n'
            else:
                heading = f'\nInstances ({editor.id}):\n'
            inst_desc.append(tkMarkdown.TextSegment(heading, (tkMarkdown.TextTag.BOLD, )))
            for ind, inst in enumerate(editor.instances):
                inst_desc.append(tkMarkdown.TextSegment(f'{ind}: ', (tkMarkdown.TextTag.INDENT, )))
                inst_desc.append(
                    tkMarkdown.TextSegment(f'{inst.inst}\n', (tkMarkdown.TextTag.CODE, ))
                    if inst.inst != FSPath() else tkMarkdown.TextSegment('""\n')
                )
            for name, inst_path in editor.cust_instances.items():
                inst_desc.append(tkMarkdown.TextSegment(f'"{name}": ', (tkMarkdown.TextTag.INDENT, )))
                inst_desc.append(
                    tkMarkdown.TextSegment(f'{inst_path}\n', (tkMarkdown.TextTag.CODE, ))
                    if inst_path != FSPath() else tkMarkdown.TextSegment('""\n')
                )
        desc = tkMarkdown.join(desc, tkMarkdown.SingleMarkdown(inst_desc))

    wid['desc'].set_text(desc)

    if DEV_MODE.get():
        source = selected_item.data.source.replace("from", "\nfrom")
        wid['item_id']['text'] = f'{source}\n-> {selected_item.id}:{selected_sub_item.subKey}'
        wid['item_id'].grid()
    else:
        wid['item_id'].grid_remove()

    editor = item_data.editor

    if PropertyWindow.can_edit(editor):
        wid['changedefaults'].state(['!disabled'])
    else:
        wid['changedefaults'].state(['disabled'])

    version_lookup[:] = set_version_combobox(wid['variant'], selected_item)

    if selected_item.data.url is None:
        wid['moreinfo'].state(['disabled'])
        tooltip.set_tooltip(wid['moreinfo'], TransToken.BLANK)
    else:
        wid['moreinfo'].state(['!disabled'])
        tooltip.set_tooltip(wid['moreinfo'], TransToken.untranslated(selected_item.data.url))

    has_timer = any(prop.kind is prop_timer_delay for prop in editor.properties.values())

    if editor.has_prim_input():
        if editor.has_sec_input():
            set_sprite(SPR.INPUT, 'in_dual')
            # Real funnels work slightly differently.
            if selected_item.id.casefold() == 'item_tbeam':
                tooltip.set_tooltip(wid_sprite[SPR.INPUT], TRANS_TOOL_TBEAM)
        else:
            set_sprite(SPR.INPUT, 'in_norm')
    else:
        set_sprite(SPR.INPUT, 'in_none')

    if editor.has_output():
        if has_timer:
            set_sprite(SPR.OUTPUT, 'out_tim')
        else:
            set_sprite(SPR.OUTPUT, 'out_norm')
    else:
        set_sprite(SPR.OUTPUT, 'out_none')

    set_sprite(SPR.ROTATION, ROT_TYPES[editor.handle])

    if editor.embed_voxels:
        set_sprite(SPR.COLLISION, 'space_embed')
    else:
        set_sprite(SPR.COLLISION, 'space_none')

    face_spr = "surf"
    if Surface.WALL not in editor.invalid_surf:
        face_spr += "_wall"
    if Surface.FLOOR not in editor.invalid_surf:
        face_spr += "_floor"
    if Surface.CEIL not in editor.invalid_surf:
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
        # This can have 2 handles - the specified one, overridden to 36 on reflection cubes.
        # Concatenate the two definitions.
        tooltip.set_tooltip(wid_sprite[SPR.ROTATION], TRANS_TOOL_CUBE.format(
            generic_rot=SPRITE_TOOL[ROT_TYPES[editor.handle]]
        ))

    if editor.cls is ItemClass.GEL:
        # Reflection or normal gel...
        set_sprite(SPR.FACING, 'surf_wall_ceil')
        set_sprite(SPR.INPUT, 'in_norm')
        set_sprite(SPR.COLLISION, 'space_none')
        set_sprite(SPR.OUTPUT, 'out_none')
        set_sprite(SPR.ROTATION, 'rot_paint')
    elif editor.cls is ItemClass.TRACK_PLATFORM:
        # Track platform - always embeds into the floor.
        set_sprite(SPR.COLLISION, 'space_embed')

    real_conn_item = editor
    if selected_item.id in ["ITEM_CUBE", "ITEM_PAINT_SPLAT"]:
        # The connections are on the dropper.
        try:
            [real_conn_item] = selected_item.data.editor_extra
        except ValueError:
            # Moved elsewhere?
            pass

    if DEV_MODE.get() and real_conn_item.conn_config is not None:
        # Override tooltips with the raw information.
        blurb = real_conn_item.conn_config.get_input_blurb()
        if real_conn_item.force_input:
            # Strip to remove \n if blurb is empty.
            blurb = ('Input force-enabled!\n' + blurb).strip()
        tooltip.set_tooltip(wid_sprite[SPR.INPUT], TransToken.untranslated(blurb))

        blurb = real_conn_item.conn_config.get_output_blurb()
        if real_conn_item.force_output:
            blurb = ('Output force-enabled!\n' + blurb).strip()
        tooltip.set_tooltip(wid_sprite[SPR.OUTPUT], TransToken.untranslated(blurb))


def adjust_position(e=None) -> None:
    """Move the properties window onto the selected item.

    We call this constantly, so the property window will not go outside
    the screen, and snap back to the item when the main window returns.
    """
    if not is_visible() or selected_sub_item is None:
        return

    # Calculate the pixel offset between the window and the subitem in
    # the properties dialog, and shift if needed to keep it inside the
    # window
    icon_widget = wid_subitem[pos_for_item(selected_sub_item.subKey)]

    loc_x, loc_y = tk_tools.adjust_inside_screen(
        x=(
            selected_sub_item.label.winfo_rootx()
            + window.winfo_rootx()
            - icon_widget.winfo_rootx()
        ),
        y=(
            selected_sub_item.label.winfo_rooty()
            + window.winfo_rooty()
            - icon_widget.winfo_rooty()
        ),
        win=window,
    )

    window.geometry('+{x!s}+{y!s}'.format(x=loc_x, y=loc_y))

# When the main window moves, move the context window also.
TK_ROOT.bind("<Configure>", adjust_position, add='+')


def hide_context(e=None):
    """Hide the properties window, if it's open."""
    global selected_item, selected_sub_item
    if is_visible():
        window.withdraw()
        sound.fx('contract')
        selected_item = selected_sub_item = None


def init_widgets() -> None:
    """Initiallise all the window components."""
    f = ttk.Frame(window, relief="raised", borderwidth="4")
    f.grid(row=0, column=0)

    localisation.set_text(ttk.Label(f, anchor="center"), TransToken.ui("Properties:")).grid(
        row=0,
        column=0,
        columnspan=3,
        sticky="EW",
    )

    wid['name'] = ttk.Label(f, text="", anchor="center")
    wid['name'].grid(row=1, column=0, columnspan=3, sticky="EW")

    wid['item_id'] = ttk.Label(f, text="", anchor="center")
    wid['item_id'].grid(row=2, column=0, columnspan=3, sticky="EW")
    tooltip.add_tooltip(wid['item_id'])

    wid['ent_count'] = ttk.Label(
        f,
        text="",
        anchor="e",
        compound="left",
    )
    img.apply(wid['ent_count'], img.Handle.sprite('icons/gear_ent', 32, 32))
    wid['ent_count'].grid(row=0, column=2, rowspan=2, sticky='e')
    tooltip.add_tooltip(
        wid['ent_count'],
        TransToken.ui(
            'The number of entities used for this item. The Source engine '
            'limits this to 2048 in total. This provides a guide to how many of '
            'these items can be placed in a map at once.'
        ),
    )

    wid['author'] = ttk.Label(f, text="", anchor="center", relief="sunken")
    wid['author'].grid(row=3, column=0, columnspan=3, sticky="EW")

    sub_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    sub_frame.grid(column=0, columnspan=3, row=4)
    for i in range(5):
        wid_subitem[i] = ttk.Label(sub_frame)
        img.apply(wid_subitem[i], IMG_ALPHA)
        wid_subitem[i].grid(row=0, column=i)
        tk_tools.bind_leftclick(wid_subitem[i], functools.partial(sub_sel, i))
        tk_tools.bind_rightclick(wid_subitem[i], functools.partial(sub_open, i))

    localisation.set_text(
        ttk.Label(f, anchor="sw"),
        TransToken.ui("Description:")
    ).grid(row=5, column=0, sticky="SW")

    spr_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=5, sticky='w')
    # sprites: inputs, outputs, rotation handle, occupied/embed state,
    # desiredFacing
    for spr_id in SPR:
        wid_sprite[spr_id] = sprite = ttk.Label(spr_frame, relief="raised")
        img.apply(sprite, img.Handle.sprite('icons/ap_grey', 32, 32))
        sprite.grid(row=0, column=spr_id.value)
        tooltip.add_tooltip(sprite)

    desc_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=6, column=0, columnspan=3, sticky="EW")
    desc_frame.columnconfigure(0, weight=1)

    wid['desc'] = tkRichText(desc_frame, width=40, height=16)
    wid['desc'].grid(row=0, column=0, sticky="EW")

    desc_scroll = tk_tools.HidingScroll(
        desc_frame,
        orient=tk.VERTICAL,
        command=wid['desc'].yview,
    )
    wid['desc']['yscrollcommand'] = desc_scroll.set
    desc_scroll.grid(row=0, column=1, sticky="NS")

    def show_more_info() -> None:
        """Show the 'more info' URL."""
        url = selected_item.data.url
        if url is not None:
            try:
                webbrowser.open_new_tab(url)
            except webbrowser.Error:
                if tk_tools.askyesno(
                    icon="error",
                    title=TransToken.ui("BEE2 - Error"),
                    message=TransToken.ui(
                        'Failed to open a web browser. Do you wish for the URL '
                        'to be copied to the clipboard instead?'
                    ),
                    detail=f'"{url!s}"',
                    parent=window,
                ):
                    LOGGER.info("Saving {} to clipboard!", url)
                    TK_ROOT.clipboard_clear()
                    TK_ROOT.clipboard_append(url)
            # Either the webbrowser or the messagebox could cause the
            # properties to move behind the main window, so hide it
            # so it doesn't appear there.
            hide_context(None)

    wid['moreinfo'] = ttk.Button(f, command=show_more_info)
    localisation.set_text(wid['moreinfo'], TransToken.ui("More Info>>"))
    wid['moreinfo'].grid(row=7, column=2, sticky='e')
    tooltip.add_tooltip(wid['moreinfo'])

    prop_window = PropertyWindow(hide_item_props)

    async def show_item_props() -> None:
        """Display the item property pane."""
        sound.fx('expand')
        await prop_window.show(
            selected_item.data.editor,
            wid['changedefaults'],
            selected_sub_item.name,
        )
        if is_visible():
            # Temporarily hide the context window while we're open.
            window.withdraw()

    wid['changedefaults'] = ttk.Button(f, command=lambda: background_run(show_item_props))
    localisation.set_text(wid['changedefaults'], TransToken.ui("Change Defaults..."))
    wid['changedefaults'].grid(row=7, column=1)
    tooltip.add_tooltip(
        wid['changedefaults'],
        TransToken.ui('Change the default settings for this item when placed.')
    )

    wid['variant'] = ttk.Combobox(
        f,
        values=['VERSION'],
        exportselection=False,
        # On Mac this defaults to being way too wide!
        width=7 if utils.MAC else None,
    )
    wid['variant'].state(['readonly'])  # Prevent directly typing in values
    wid['variant'].bind('<<ComboboxSelected>>', set_item_version)
    wid['variant'].current(0)
    wid['variant'].grid(row=7, column=0, sticky='w')
