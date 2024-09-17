"""Tk-specific code for the window that shows item information."""
from __future__ import annotations
from typing import override

from tkinter import ttk
import tkinter as tk
from contextlib import aclosing
import functools

from srctools.logger import get_logger
from trio_util import AsyncValue
import trio

from app import img, sound
from app.contextWin import (
    IMG_ALPHA, SPR, TRANS_ENT_COUNT, TRANS_NO_VERSIONS, ContextWinBase,
)
from app.item_picker import ItemPickerBase
from app.item_properties import PropertyWindow
from app.mdown import MarkdownData
from async_util import EdgeTrigger
from packages import PakRef, Style
from packages.item import Item
from transtoken import TransToken
import utils

from . import TK_ROOT, tk_tools, tooltip
from .dialogs import TkDialogs
from .img import TKImages
from .rich_textbox import RichText
from .wid_transtoken import set_text


LOGGER = get_logger(__name__)


def set_version_combobox(box: ttk.Combobox, item: Item, cur_style: PakRef[Style]) -> list[str]:
    """Set values on the variant combobox.

    This is in a function so itemconfig can reuse it.
    It returns a list of IDs in the same order as the names.
    """
    ver_lookup, version_names = item.get_version_names(cur_style)
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


class ContextWin(ContextWinBase):
    """Tk-specific item context window."""
    wid_subitem: list[ttk.Label]
    wid_sprite: dict[SPR, ttk.Label]
    version_lookup: list[str]

    def __init__(
        self,
        item_picker: ItemPickerBase,
        tk_img: TKImages,
        cur_style: AsyncValue[PakRef[Style]],
    ) -> None:
        self.window = tk.Toplevel(TK_ROOT, name='contextWin')
        self.window.overrideredirect(True)
        self.window.resizable(False, False)
        self.window.transient(master=TK_ROOT)
        if utils.LINUX:
            self.window.wm_attributes('-type', 'popup_menu')
        self.window.withdraw()  # starts hidden

        super().__init__(item_picker, TkDialogs(self.window), cur_style)

        self.tk_img = tk_img
        self.wid_subitem = []
        self.wid_sprite = {}
        self.version_lookup = []

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

        self.wid_desc = RichText(desc_frame, name='desc', width=40, height=16)
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

        self.wid_changedefaults = ttk.Button(f, command=self.defaults_trigger.trigger)
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
        )
        if utils.MAC:  # On Mac this defaults to being way too wide!
            self.wid_variant['width'] = 7
        self.wid_variant.state(['readonly'])  # Prevent directly typing in values
        self.wid_variant.bind('<<ComboboxSelected>>', self._evt_version_changed)
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

    def _evt_moreinfo_clicked(self) -> None:
        """Handle the more-info button being clicked."""
        url = self.moreinfo_url.value
        if url is not None and self.moreinfo_trigger.ready.value:
            self.moreinfo_trigger.trigger(url)

    def _evt_version_changed(self, _: object) -> None:
        """Callback for the version combobox. Set the item variant."""
        from app import itemconfig
        assert self.selected is not None
        version_id = self.version_lookup[self.wid_variant.current()]
        item_ref = self.selected.item
        self.picker.change_version(item_ref, version_id)
        # Refresh our data.
        self.load_item_data()

        # Refresh itemconfig combo-boxes to match us.
        style_ref = self.picker.cur_style()
        for conf_item_ref, func in itemconfig.ITEM_VARIANT_LOAD:
            if conf_item_ref == item_ref:
                func(style_ref)

    @override
    async def ui_task(self, signage_trigger: EdgeTrigger[()]) -> None:
        """Run logic to update the UI."""

        async def update_more_info(widget: ttk.Button, avalue: AsyncValue[str | None]) -> None:
            """Update the state of the more-info button."""
            async with aclosing(avalue.eventual_values()) as agen:
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
            nursery.start_soon(
                tk_tools.apply_bool_enabled_state_task,
                self.defaults_trigger.ready, self.wid_changedefaults,
            )
            nursery.start_soon(update_more_info, self.wid_moreinfo, self.moreinfo_url)
            nursery.start_soon(self._change_defaults_task)
            await trio.sleep_forever()

    async def _change_defaults_task(self) -> None:
        """Handle clicking the Change Defaults button.

        TODO: move to app.contextwin, once Item Properties are converted.
        """
        prop_window = PropertyWindow(self.tk_img)
        while True:
            await self.defaults_trigger.wait()

            item, version, variant, subtype = self.get_current()

            sound.fx('expand')
            was_temp_hidden = self.is_visible
            if was_temp_hidden:
                # Temporarily hide the context window while we're open.
                self.window.withdraw()
            try:
                self.props_open = True
                await prop_window.show(variant.editor, self.window, subtype.name)
            finally:
                self.props_open = False
            sound.fx('contract')
            if was_temp_hidden:
                # Restore the context window if we hid it earlier.
                self.window.deiconify()

    @override
    def ui_get_icon_offset(self, ind: int) -> tuple[int, int]:
        """Get the offset of the specified icon, in this window."""
        widget = self.wid_subitem[ind]
        x = widget.winfo_rootx() - self.window.winfo_rootx()
        y = widget.winfo_rooty() - self.window.winfo_rooty()
        return x, y

    @override
    def ui_hide_window(self) -> None:
        """Hide the window."""
        self.window.withdraw()
        # Clear the description, to free images.
        self.wid_desc.set_text('')

    @override
    def ui_show_window(self, x: int, y: int) -> None:
        """Show the window."""
        loc_x, loc_y = tk_tools.adjust_inside_screen(x=x, y=y, win=self.window)
        self.window.deiconify()
        self.window.lift()
        self.window.geometry(f'+{loc_x!s}+{loc_y!s}')

    @override
    def ui_get_cursor_offset(self) -> tuple[int, int]:
        """Fetch the offset of the cursor relative to the window, for restoring when it moves."""
        cursor_x, cursor_y = self.window.winfo_pointerxy()
        off_x = cursor_x - self.window.winfo_rootx()
        off_y = cursor_y - self.window.winfo_rooty()
        return off_x, off_y

    @override
    def ui_set_cursor_offset(self, offset: tuple[int, int]) -> None:
        """Apply the offset, after the window has moved."""
        off_x, off_y = offset
        self.window.event_generate('<Motion>', warp=True, x=off_x, y=off_y)

    @override
    def ui_set_sprite_img(self, sprite: SPR, icon: img.Handle) -> None:
        """Set the image for the connection sprite."""
        self.tk_img.apply(self.wid_sprite[sprite], icon)

    @override
    def ui_set_sprite_tool(self, sprite: SPR, tool: TransToken) -> None:
        """Set the tooltip for the connection sprite."""
        tooltip.set_tooltip(self.wid_sprite[sprite], tool)

    @override
    def ui_set_props_main(
        self,
        name: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        ent_count: str,
    ) -> None:
        """Set the main set of widgets for properties."""
        set_text(self.wid_author, authors)
        set_text(self.wid_name, name)
        self.wid_ent_count['text'] = ent_count
        self.wid_desc.set_text(desc)

    @override
    def ui_set_props_icon(self, ind: int, icon: img.Handle, selected: bool) -> None:
        """Set the palette icon in the menu."""
        widget = self.wid_subitem[ind]
        self.tk_img.apply(widget, icon)
        widget['relief'] = 'raised' if selected else 'flat'

    @override
    def ui_set_debug_itemid(self, item_id: str) -> None:
        """Set the debug item ID, or hide it if blank."""
        if item_id:
            self.wid_item_id['text'] = item_id
            self.wid_item_id.grid()
        else:
            self.wid_item_id.grid_remove()

    @override
    def ui_show_sign_config(self) -> None:
        """Show the special signage-configure button."""
        self.wid_variant.grid_remove()
        self.wid_signage_configure.grid()

    @override
    def ui_show_variants(self, item: Item) -> None:
        """Show the variants combo-box, and configure it."""
        self.wid_variant.grid()
        self.wid_signage_configure.grid_remove()

        self.version_lookup = set_version_combobox(self.wid_variant, item, self.picker.cur_style())

    @override
    def ui_set_defaults_enabled(self, enable: bool) -> None:
        """Set whether the Change Defaults button is enabled."""
        if enable:
            self.wid_changedefaults.state(['!disabled'])
        else:
            self.wid_changedefaults.state(['disabled'])

    @override
    def ui_set_clipboard(self, text: str) -> None:
        """Set the clipboard."""
        TK_ROOT.clipboard_clear()
        TK_ROOT.clipboard_append(text)
