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
from typing import Any, Callable
from enum import Enum
import functools
import webbrowser

import tkinter as tk
from tkinter import ttk

import trio

from consts import DefaultItems
from ui_tk.dialogs import TkDialogs
from ui_tk.img import TKImages, TK_IMG
from ui_tk.wid_transtoken import set_text
from ui_tk import TK_ROOT, tk_tools, tooltip
from .richTextBox import tkRichText
from . import (
    EdgeTrigger, itemconfig, tkMarkdown, sound, img, UI,
    DEV_MODE, background_run,
)
from packages.signage import ITEM_ID as SIGNAGE_ITEM_ID
from .item_properties import PropertyWindow
import utils
import srctools.logger
from editoritems import Handle as RotHandle, Surface, ItemClass, FSPath
from editoritems_props import prop_timer_delay
from transtoken import TransToken


LOGGER = srctools.logger.get_logger(__name__)

wid: dict[str, Any] = {}
wid_subitem: dict[int, ttk.Label] = {}
wid_sprite: dict[SPR, ttk.Label] = {}

selected_item: UI.Item
selected_sub_item: UI.PalItem

version_lookup: list[str] = []

window = tk.Toplevel(TK_ROOT, name='contextWin')
window.overrideredirect(True)
window.resizable(False, False)
window.transient(master=TK_ROOT)
if utils.LINUX:
    window.wm_attributes('-type', 'popup_menu')
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
TRANS_TOOL_FIZZOUT = TransToken.ui(
    'This fizzler has an output. Due to an editor bug, this cannot be used directly. Instead '
    'the Fizzler Output Relay item should be placed on top of this fizzler.'
)
TRANS_TOOL_FIZZOUT_TIMED = TransToken.ui(
    'This fizzler has a timed output. Due to an editor bug, this cannot be used directly. Instead '
    'the Fizzler Output Relay item should be placed on top of this fizzler.'
)
TRANS_NO_VERSIONS = TransToken.ui('No Alternate Versions')


def set_sprite(tk_img: TKImages, pos: SPR, sprite: str) -> None:
    """Set one of the property sprites to a value."""
    widget = wid_sprite[pos]
    tk_img.apply(widget, img.Handle.sprite('icons/' + sprite, 32, 32))
    tooltip.set_tooltip(widget, SPRITE_TOOL[sprite])


def pos_for_item(ind: int) -> int | None:
    """Get the index the specified subitem is located at."""
    positions = SUBITEM_POS[len(selected_item.item.visual_subtypes)]
    for pos, sub in enumerate(positions):
        if sub != -1 and ind == selected_item.item.visual_subtypes[sub]:
            return pos
    else:
        return None


def ind_for_pos(pos: int) -> int | None:
    """Return the subtype index for the specified position."""
    ind = SUBITEM_POS[len(selected_item.item.visual_subtypes)][pos]
    if ind == -1:
        return None
    else:
        return selected_item.item.visual_subtypes[ind]


def sub_sel(pos: int, e: object = None) -> None:
    """Change the currently-selected sub-item."""
    ind = ind_for_pos(pos)
    # Can only change the subitem on the preview window
    if selected_sub_item.is_pre and ind is not None:
        sound.fx('config')
        selected_sub_item.change_subtype(ind)
        # Redisplay the window to refresh data and move it to match
        show_prop(selected_sub_item, warp_cursor=True)


def sub_open(pos: int, e: object = None) -> None:
    """Move the context window to apply to the given item."""
    ind = ind_for_pos(pos)
    if ind is not None:
        sound.fx('expand')
        selected_sub_item.open_menu_at_sub(ind)


def open_event(item: UI.PalItem) -> Callable[[tk.Event], object]:
    """Show the window for a particular PalItem."""
    def func(e: tk.Event) -> None:
        """Show the window."""
        sound.fx('expand')
        show_prop(item)
    return func


def is_visible() -> bool:
    """Checks if the window is visible."""
    return window.winfo_ismapped()


def show_prop(widget: UI.PalItem, warp_cursor: bool = False) -> None:
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

    load_item_data(TK_IMG)


def set_item_version(tk_img: TKImages) -> None:
    """Callback for the version combobox. Set the item variant."""
    selected_item.change_version(version_lookup[wid['variant'].current()])
    # Refresh our data.
    load_item_data(tk_img)

    # Refresh itemconfig comboboxes to match us.
    for item_id, func in itemconfig.ITEM_VARIANT_LOAD:
        if selected_item.id == item_id:
            func()


def set_version_combobox(box: ttk.Combobox, item: UI.Item) -> list[str]:
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
        box.current(ver_lookup.index(item.selected_version().id))
    return ver_lookup


def get_description(
    global_last: bool,
    glob_desc: tkMarkdown.MarkdownData,
    style_desc: tkMarkdown.MarkdownData,
) -> tkMarkdown.MarkdownData:
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
        return tkMarkdown.MarkdownData.BLANK  # No description


def load_item_data(tk_img: TKImages) -> None:
    """Refresh the window to use the selected item's data."""
    item_data = selected_item.data
    item_id = utils.obj_id(selected_item.id)

    for ind, pos in enumerate(SUBITEM_POS[len(selected_item.item.visual_subtypes)]):
        if pos == -1:
            icon = IMG_ALPHA
        else:
            icon = selected_item.get_icon(selected_item.item.visual_subtypes[pos])
        tk_img.apply(wid_subitem[ind], icon)
        wid_subitem[ind]['relief'] = 'flat'

    wid_subitem[pos_for_item(selected_sub_item.subKey)]['relief'] = 'raised'

    set_text(wid['author'], TransToken.list_and(
        map(TransToken.untranslated, item_data.authors), sort=True,
    ))
    set_text(wid['name'], selected_sub_item.name)
    wid['ent_count']['text'] = item_data.ent_count or '??'

    desc = get_description(
        global_last=selected_item.item.glob_desc_last,
        glob_desc=selected_item.item.glob_desc,
        style_desc=item_data.desc,
    )
    # Dump out the instances used in this item.
    if DEV_MODE.value:
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

    if DEV_MODE.value:
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

    if item_id == SIGNAGE_ITEM_ID:
        wid['variant'].grid_remove()
        wid['signage_configure'].grid()
    else:
        wid['variant'].grid()
        wid['signage_configure'].grid_remove()

    if selected_item.data.url is None:
        wid['moreinfo'].state(['disabled'])
        tooltip.set_tooltip(wid['moreinfo'], TransToken.BLANK)
    else:
        wid['moreinfo'].state(['!disabled'])
        tooltip.set_tooltip(wid['moreinfo'], TransToken.untranslated(selected_item.data.url))

    has_timer = any(prop.kind is prop_timer_delay for prop in editor.properties.values())

    if editor.has_prim_input():
        if editor.has_sec_input():
            set_sprite(tk_img, SPR.INPUT, 'in_dual')
            # Real funnels work slightly differently.
            if item_id == DefaultItems.funnel.id:
                tooltip.set_tooltip(wid_sprite[SPR.INPUT], TRANS_TOOL_TBEAM)
        else:
            set_sprite(tk_img, SPR.INPUT, 'in_norm')
    else:
        set_sprite(tk_img, SPR.INPUT, 'in_none')

    if editor.has_output():
        if has_timer:
            set_sprite(tk_img, SPR.OUTPUT, 'out_tim')
            # Mention the Fizzler Output Relay here.
            if editor.cls is ItemClass.FIZZLER:
                tooltip.set_tooltip(wid_sprite[SPR.OUTPUT], TRANS_TOOL_FIZZOUT_TIMED)
        else:
            set_sprite(tk_img, SPR.OUTPUT, 'out_norm')
            if editor.cls is ItemClass.FIZZLER:
                tooltip.set_tooltip(wid_sprite[SPR.OUTPUT], TRANS_TOOL_FIZZOUT)
    else:
        set_sprite(tk_img, SPR.OUTPUT, 'out_none')

    set_sprite(tk_img, SPR.ROTATION, ROT_TYPES[editor.handle])

    if editor.embed_voxels:
        set_sprite(tk_img, SPR.COLLISION, 'space_embed')
    else:
        set_sprite(tk_img, SPR.COLLISION, 'space_none')

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

    set_sprite(tk_img, SPR.FACING, face_spr)

    # Now some special overrides for certain classes.
    if item_id == DefaultItems.cube.id:
        # Cubes - they should show info for the dropper.
        set_sprite(tk_img, SPR.FACING, 'surf_ceil')
        set_sprite(tk_img, SPR.INPUT, 'in_norm')
        set_sprite(tk_img, SPR.COLLISION, 'space_embed')
        set_sprite(tk_img, SPR.OUTPUT, 'out_none')
        # This can have 2 handles - the specified one, overridden to 36 on reflection cubes.
        # Concatenate the two definitions.
        tooltip.set_tooltip(wid_sprite[SPR.ROTATION], TRANS_TOOL_CUBE.format(
            generic_rot=SPRITE_TOOL[ROT_TYPES[editor.handle]]
        ))

    if editor.cls is ItemClass.GEL:
        # Reflection or normal gel...
        set_sprite(tk_img, SPR.FACING, 'surf_wall_ceil')
        set_sprite(tk_img, SPR.INPUT, 'in_norm')
        set_sprite(tk_img, SPR.COLLISION, 'space_none')
        set_sprite(tk_img, SPR.OUTPUT, 'out_none')
        set_sprite(tk_img, SPR.ROTATION, 'rot_paint')
    elif editor.cls is ItemClass.TRACK_PLATFORM:
        # Track platform - always embeds into the floor.
        set_sprite(tk_img, SPR.COLLISION, 'space_embed')

    real_conn_item = editor
    if item_id == DefaultItems.cube.id or item_id == DefaultItems.gel_splat.id:
        # The connections are on the dropper.
        try:
            [real_conn_item] = selected_item.data.editor_extra
        except ValueError:
            # Moved elsewhere?
            pass

    if DEV_MODE.value and real_conn_item.conn_config is not None:
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


def adjust_position(e: object = None) -> None:
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

    window.geometry(f'+{loc_x!s}+{loc_y!s}')

# When the main window moves, move the context window also.
TK_ROOT.bind("<Configure>", adjust_position, add='+')


def hide_context(e: object = None) -> None:
    """Hide the properties window, if it's open."""
    global selected_item, selected_sub_item
    if is_visible():
        window.withdraw()
        sound.fx('contract')
        selected_item = selected_sub_item = None
        # Clear the description, to free images.
        wid['desc'].set_text('')


async def init_widgets(
    tk_img: TKImages, signage_trigger: EdgeTrigger[()],
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Initiallise all the window components."""
    f = ttk.Frame(window, relief="raised", borderwidth="4")
    f.grid(row=0, column=0)

    set_text(ttk.Label(f, anchor="center"), TransToken.ui("Properties:")).grid(
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
    tk_img.apply(wid['ent_count'], img.Handle.sprite('icons/gear_ent', 32, 32))
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
        tk_img.apply(wid_subitem[i], IMG_ALPHA)
        wid_subitem[i].grid(row=0, column=i)
        tk_tools.bind_leftclick(wid_subitem[i], functools.partial(sub_sel, i))
        tk_tools.bind_rightclick(wid_subitem[i], functools.partial(sub_open, i))

    set_text(
        ttk.Label(f, anchor="sw"),
        TransToken.ui("Description:")
    ).grid(row=5, column=0, sticky="SW")

    spr_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=5, sticky='w')
    # sprites: inputs, outputs, rotation handle, occupied/embed state,
    # desiredFacing
    for spr_id in SPR:
        wid_sprite[spr_id] = sprite = ttk.Label(spr_frame, relief="raised")
        tk_img.apply(sprite, img.Handle.sprite('icons/ap_grey', 32, 32))
        sprite.grid(row=0, column=spr_id.value)
        tooltip.add_tooltip(sprite)

    desc_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=6, column=0, columnspan=3, sticky="EW")
    desc_frame.columnconfigure(0, weight=1)

    wid['desc'] = tkRichText(desc_frame, name='desc', width=40, height=16)
    wid['desc'].grid(row=0, column=0, sticky="EW")

    desc_scroll = tk_tools.HidingScroll(
        desc_frame,
        orient=tk.VERTICAL,
        command=wid['desc'].yview,
    )
    wid['desc']['yscrollcommand'] = desc_scroll.set
    desc_scroll.grid(row=0, column=1, sticky="NS")

    dialog = TkDialogs(window)

    async def show_more_info() -> None:
        """Show the 'more info' URL."""
        url = selected_item.data.url
        if url is not None:
            try:
                webbrowser.open_new_tab(url)
            except webbrowser.Error:
                if await dialog.ask_yes_no(
                    title=TransToken.ui("BEE2 - Error"),
                    message=TransToken.ui(
                        'Failed to open a web browser. Do you wish for the URL '
                        'to be copied to the clipboard instead?'
                    ),
                    icon=dialog.ERROR,
                    detail=f'"{url!s}"',
                ):
                    LOGGER.info("Saving {} to clipboard!", url)
                    TK_ROOT.clipboard_clear()
                    TK_ROOT.clipboard_append(url)
            # Either the webbrowser or the messagebox could cause the
            # properties to move behind the main window, so hide it
            # so that it doesn't appear there.
            hide_context(None)

    wid['moreinfo'] = ttk.Button(f, command=lambda: background_run(show_more_info))
    set_text(wid['moreinfo'], TransToken.ui("More Info>>"))
    wid['moreinfo'].grid(row=7, column=2, sticky='e')
    tooltip.add_tooltip(wid['moreinfo'])

    was_temp_hidden = False

    def hide_item_props() -> None:
        """Called when the item properties panel is hidden."""
        sound.fx('contract')
        if was_temp_hidden:
            # Restore the context window if we hid it earlier.
            window.deiconify()

    async def show_item_props() -> None:
        """Display the item property pane."""
        nonlocal was_temp_hidden
        sound.fx('expand')
        await prop_window.show(
            selected_item.data.editor,
            wid['changedefaults'],
            selected_sub_item.name,
        )
        was_temp_hidden = is_visible()
        if was_temp_hidden:
            # Temporarily hide the context window while we're open.
            window.withdraw()

    prop_window = PropertyWindow(tk_img, hide_item_props)

    wid['changedefaults'] = ttk.Button(f, command=lambda: background_run(show_item_props))
    set_text(wid['changedefaults'], TransToken.ui("Change Defaults..."))
    wid['changedefaults'].grid(row=7, column=1)
    tooltip.add_tooltip(
        wid['changedefaults'],
        TransToken.ui('Change the default settings for this item when placed.')
    )

    wid['variant'] = wid_variant = ttk.Combobox(
        f,
        values=['VERSION'],
        exportselection=False,
        # On Mac this defaults to being way too wide!
        width=7 if utils.MAC else None,
    )
    wid_variant.state(['readonly'])  # Prevent directly typing in values
    wid_variant.bind('<<ComboboxSelected>>', lambda e: set_item_version(tk_img))
    wid_variant.current(0)

    # Special button for signage items only.
    wid['signage_configure'] = wid_sign_config = ttk.Button(
        f, command=signage_trigger.trigger,
    )
    set_text(wid_sign_config, TransToken.ui('Select Signage...'))
    tooltip.add_tooltip(
        wid_sign_config,
        TransToken.ui('Change which signs are specified by each timer value.')
    )

    wid_variant.grid(row=7, column=0, sticky='w')
    wid_variant.grid_remove()
    wid_sign_config.grid(row=7, column=0, sticky='w')
    wid_sign_config.grid_remove()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(
            tk_tools.apply_bool_enabled_state_task,
            signage_trigger.ready, wid_sign_config,
        )
        task_status.started()
