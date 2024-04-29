"""Tk-specific code for the window that shows item information."""
from __future__ import annotations
from tkinter import ttk
import tkinter as tk
import functools
from typing import Callable

import trio
from trio_util import AsyncValue

from app import EdgeTrigger, background_run, img, sound, tkMarkdown, UI
from app.contextWin import ContextWinBase, IMG_ALPHA, SPR, TRANS_ENT_COUNT, TargetT
from app.item_properties import PropertyWindow
from app.richTextBox import tkRichText
from packages import PakRef
from packages.item import Item, SubItemRef
from transtoken import TransToken
from ui_tk import TK_ROOT, tk_tools, tooltip
from ui_tk.dialogs import TkDialogs
from ui_tk.wid_transtoken import set_text
from ui_tk.img import TKImages
import utils


class ContextWin(ContextWinBase[UI.PalItem]):
    """Tk-specific item context window."""
    def __init__(self, tk_img: TKImages) -> None:

        self.window = tk.Toplevel(TK_ROOT, name='contextWin')
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.transient(master=TK_ROOT)
        if utils.LINUX:
            self.window.wm_attributes('-type', 'popup_menu')
        self.window.withdraw()  # starts hidden

        super().__init__(TkDialogs(self.window))

        self.tk_img = tk_img
        self.wid_subitem = []
        self.wid_sprite = {}

        f = ttk.Frame(self.window, relief="raised", borderwidth="4")
        f.grid(row=0, column=0)

        set_text(ttk.Label(f, anchor="center"), TransToken.ui("Properties:")).grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="EW",
        )

        self.wid_name = ttk.Label(f, text="", anchor="center")
        self.wid_name.grid(row=1, column=0, columnspan=3, sticky="EW")

        self.wid_item_id = ttk.Label(f, text="", anchor="center")
        self.wid_item_id.grid(row=2, column=0, columnspan=3, sticky="EW")
        tooltip.add_tooltip(self.wid_item_id)

        self.wid_ent_count = ttk.Label(
            f,
            text="",
            anchor="e",
            compound="left",
        )
        tk_img.apply(self.wid_ent_count, img.Handle.sprite('icons/gear_ent', 32, 32))
        self.wid_ent_count.grid(row=0, column=2, rowspan=2, sticky='e')
        tooltip.add_tooltip(self.wid_ent_count, TRANS_ENT_COUNT)

        self.wid_author = ttk.Label(f, text="", anchor="center", relief="sunken")
        self.wid_author.grid(row=3, column=0, columnspan=3, sticky="EW")

        sub_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
        sub_frame.grid(column=0, columnspan=3, row=4)
        for i in range(5):
            wid_subitem = ttk.Label(sub_frame)
            self.wid_subitem.append(wid_subitem)
            tk_img.apply(wid_subitem, IMG_ALPHA)
            wid_subitem.grid(row=0, column=i)
            tk_tools.bind_leftclick(wid_subitem, functools.partial(self.sub_sel, i))
            tk_tools.bind_rightclick(wid_subitem, functools.partial(self.sub_open, i))

        set_text(
            ttk.Label(f, anchor="sw"),
            TransToken.ui("Description:")
        ).grid(row=5, column=0, sticky="SW")

        spr_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
        spr_frame.grid(column=1, columnspan=2, row=5, sticky='w')
        # sprites: inputs, outputs, rotation handle, occupied/embed state,
        # desiredFacing
        for spr_id in SPR:
            self.wid_sprite[spr_id] = sprite = ttk.Label(spr_frame, relief="raised")
            tk_img.apply(sprite, img.Handle.sprite('icons/ap_grey', 32, 32))
            sprite.grid(row=0, column=spr_id.value)
            tooltip.add_tooltip(sprite)

        desc_frame = ttk.Frame(f, borderwidth=4, relief="sunken")
        desc_frame.grid(row=6, column=0, columnspan=3, sticky="EW")
        desc_frame.columnconfigure(0, weight=1)

        self.wid_desc = tkRichText(desc_frame, name='desc', width=40, height=16)
        self.wid_desc.grid(row=0, column=0, sticky="EW")

        desc_scroll = tk_tools.HidingScroll(
            desc_frame,
            orient=tk.VERTICAL,
            command=self.wid_desc.yview,
        )
        self.wid_desc['yscrollcommand'] = desc_scroll.set
        desc_scroll.grid(row=0, column=1, sticky="NS")

        self.wid_moreinfo = ttk.Button(f, command=self._evt_moreinfo_clicked)
        set_text(self.wid_moreinfo, TransToken.ui("More Info>>"))
        self.wid_moreinfo.grid(row=7, column=2, sticky='e')
        tooltip.add_tooltip(self.wid_moreinfo)

        was_temp_hidden = False

        def hide_item_props() -> None:
            """Called when the item properties panel is hidden."""
            sound.fx('contract')
            if was_temp_hidden:
                # Restore the context window if we hid it earlier.
                self.window.deiconify()

        async def show_item_props() -> None:
            """Display the item property pane."""
            nonlocal was_temp_hidden
            sound.fx('expand')
            await prop_window.show(
                selected_item.data.editor,
                self.wid_changedefaults,
                selected_sub_item.name,
            )
            was_temp_hidden = self.is_visible()
            if was_temp_hidden:
                # Temporarily hide the context window while we're open.
                self.window.withdraw()

        prop_window = PropertyWindow(tk_img, hide_item_props)

        self.wid_changedefaults = ttk.Button(f, command=lambda: background_run(show_item_props))
        set_text(self.wid_changedefaults, TransToken.ui("Change Defaults..."))
        self.wid_changedefaults.grid(row=7, column=1)
        tooltip.add_tooltip(
            self.wid_changedefaults,
            TransToken.ui('Change the default settings for this item when placed.')
        )

        self.wid_variant = ttk.Combobox(
            f,
            values=['VERSION'],
            exportselection=False,
            # On Mac this defaults to being way too wide!
            width=7 if utils.MAC else None,
        )
        self.wid_variant.state(['readonly'])  # Prevent directly typing in values
        self.wid_variant.bind('<<ComboboxSelected>>', lambda e: self.set_item_version(tk_img))
        self.wid_variant.current(0)

        # Special button for signage items only.
        self.wid_signage_configure = ttk.Button(f)
        set_text(self.wid_signage_configure, TransToken.ui('Select Signage...'))
        tooltip.add_tooltip(
            self.wid_signage_configure,
            TransToken.ui('Change which signs are specified by each timer value.')
        )

        # Assign the grid positions, so we can call grid() later to put them here.
        self.wid_variant.grid(row=7, column=0, sticky='w')
        self.wid_variant.grid_remove()
        self.wid_signage_configure.grid(row=7, column=0, sticky='w')
        self.wid_signage_configure.grid_remove()

        # When the main window moves, move the context window also.
        TK_ROOT.bind("<Configure>", self.adjust_position, add='+')

    def open_event(self, item: UI.PalItem) -> Callable[[tk.Event], object]:
        """Make a function that shows the window for a particular PalItem."""
        def func(e: tk.Event) -> None:
            """Show the window."""
            sound.fx('expand')
            self.show_prop(item, ref)
        return func

    def _evt_moreinfo_clicked(self) -> None:
        """Handle the more-info button being clicked."""
        url = self.moreinfo_url.value
        if url is not None and self.moreinfo_trigger.ready.value:
            self.moreinfo_trigger.trigger(url)

    async def ui_task(self, signage_trigger: EdgeTrigger[()]) -> None:
        """Run logic to update the UI."""
        async def update_more_info(widget: ttk.Label, avalue: AsyncValue[str | None]) -> None:
            """Update the state of the more-info button."""
            async with utils.aclosing(avalue.eventual_values()) as agen:
                async for val in agen:
                    if val is not None:
                        widget.state(['!disabled'])
                        tooltip.set_tooltip(widget, TransToken.untranslated(val))
                    else:
                        widget.state(['disabled'])
                        tooltip.set_tooltip(widget, TransToken.BLANK)

        self.wid_signage_configure['command'] = signage_trigger.trigger
        async with trio.open_nursery() as nursery:
            nursery.start_soon(
                tk_tools.apply_bool_enabled_state_task,
                signage_trigger.ready, self.wid_signage_configure,
            )
            nursery.start_soon(update_more_info, self.wid_moreinfo, self.moreinfo_url)
            await trio.sleep_forever()

    def ui_get_target_pos(self, widget: TargetT) -> tuple[int, int]:
        """Get the offset of our target widget."""

    def ui_get_icon_offset(self, ind: int) -> tuple[int, int]:
        """Get the offset of the specified icon, in this window."""
        widget = self.wid_subitem[ind]
        x = widget.winfo_rootx() - self.window.winfo_rootx()
        y = widget.winfo_rooty() - self.window.winfo_rooty()
        return x, y

    def ui_hide_window(self) -> None:
        """Hide the window."""
        self.window.withdraw()
        # Clear the description, to free images.
        self.wid_desc.set_text('')

    def ui_show_window(self, x: int, y: int) -> None:
        """Show the window."""
        loc_x, loc_y = tk_tools.adjust_inside_screen(x=x, y=y, win=self.window)
        self.window.deiconify()
        self.window.lift()
        self.window.geometry(f'+{loc_x!s}+{loc_y!s}')

    def ui_get_cursor_offset(self) -> tuple[int, int]:
        """Fetch the offset of the cursor relative to the window, for restoring when it moves."""
        cursor_x, cursor_y = self.window.winfo_pointerxy()
        off_x = cursor_x - self.window.winfo_rootx()
        off_y = cursor_y - self.window.winfo_rooty()
        return off_x, off_y

    def ui_set_cursor_offset(self, offset: tuple[int, int]) -> None:
        """Apply the offset, after the window has moved."""
        off_x, off_y = offset
        self.window.event_generate('<Motion>', warp=True, x=off_x, y=off_y)
        raise NotImplementedError

    def ui_set_sprite_img(self, sprite: SPR, icon: img.Handle) -> None:
        """Set the image for the connection sprite."""
        self.tk_img.apply(self.wid_sprite[sprite], icon)

    def ui_set_sprite_tool(self, sprite: SPR, tool: TransToken) -> None:
        """Set the tooltip for the connection sprite."""
        tooltip.set_tooltip(self.wid_sprite[sprite], tool)

    def ui_set_props_main(
        self,
        name: TransToken,
        authors: TransToken,
        desc: tkMarkdown.MarkdownData,
        ent_count: TransToken,
    ) -> None:
        """Set the main set of widgets for properties."""
        set_text(self.wid_author, authors)
        set_text(self.wid_name, name)
        self.wid_ent_count['text'] = ent_count
        self.wid_desc.set_text(desc)

    def ui_set_props_icon(self, ind: int, icon: img.Handle, selected: bool) -> None:
        """Set the palette icon in the menu."""
        widget = self.wid_subitem[ind]
        self.tk_img.apply(widget, icon)
        widget['relief'] = 'raised' if selected else 'flat'

    def ui_set_debug_itemid(self, item_id: str) -> None:
        """Set the debug item ID, or hide it if blank."""
        if item_id:
            self.wid_item_id['text'] = item_id
            self.wid_item_id.grid()
        else:
            self.wid_item_id.grid_remove()

    def ui_set_clipboard(self, text: str) -> None:
        """Set the clipboard."""
        TK_ROOT.clipboard_clear()
        TK_ROOT.clipboard_append(text)
