"""UI implementation for the packages-sync tool."""
from typing import override
from collections.abc import Awaitable, Callable
from pathlib import PurePath
import contextlib

import trio
import wx

import app
from app.packages_sync import SyncUIBase
from packages import Package
from . import MAIN_WINDOW
from .core import start_main


RIGHT_ARROW = '\N{WIDE-HEADED RIGHTWARDS HEAVY BARB ARROW}'


class WxUI(SyncUIBase):
    """Wx implementation of the packages-sync UI."""
    # This is a dev tool, we don't need to translate.
    def __init__(self) -> None:
        super().__init__()
        self.frm_pack = wx.Frame(
            MAIN_WINDOW,
            title="Select Package",
            style=wx.CAPTION | wx.CLIP_CHILDREN
                  | wx.CLOSE_BOX | wx.RESIZE_BORDER
                  | wx.STAY_ON_TOP | wx.SYSTEM_MENU,
        )
        self.frm_pack.Bind(wx.EVT_CLOSE, self.evt_skip)
        self.pan_pack = wx.Panel(self.frm_pack)
        pan_pack_header = wx.Panel(self.pan_pack, style=wx.BORDER_RAISED)
        sizer_pack_vert = wx.BoxSizer(wx.VERTICAL)
        sizer_pack_vert.Add(pan_pack_header, 0, wx.EXPAND, 0)

        sizer_pan_header = wx.BoxSizer(wx.HORIZONTAL)
        sizer_actions = wx.BoxSizer(wx.VERTICAL)
        sizer_pan_header.Add(sizer_actions, 0, wx.ALL, 4)

        self.btn_skip = wx.Button(pan_pack_header, label="Skip")
        sizer_actions.Add(self.btn_skip, 0, 0, 0)
        self.btn_skip.Bind(wx.EVT_BUTTON, self.evt_skip)

        self.check_apply_all = wx.CheckBox(pan_pack_header, label="Apply To All")
        sizer_actions.Add(self.check_apply_all, 0, 0, 0)
        self.check_apply_all.Bind(wx.EVT_CHECKBOX, self.evt_set_apply_all)

        sizer_paths = wx.BoxSizer(wx.VERTICAL)
        sizer_pan_header.Add(sizer_paths, 1, wx.EXPAND, 0)

        self.lbl_file_src = wx.StaticText(pan_pack_header)
        sizer_paths.Add(self.lbl_file_src, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        lbl_arrow_down = wx.StaticText(pan_pack_header, label="VVV")
        sizer_paths.Add(lbl_arrow_down, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.lbl_file_dest = wx.StaticText(pan_pack_header)
        sizer_paths.Add(self.lbl_file_dest, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.radio_sort_order = wx.RadioBox(
            pan_pack_header, label="Sort Order",
            choices=["Name", "ID"], majorDimension=2,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.radio_sort_order.SetSelection(0)
        sizer_pan_header.Add(self.radio_sort_order, 0, wx.ALL, 4)
        self.radio_sort_order.Bind(wx.EVT_RADIOBOX, self.evt_set_sort)

        self.sizer_packages = wx.WrapSizer(wx.HORIZONTAL)
        sizer_pack_vert.Add(self.sizer_packages, 0, wx.EXPAND, 0)

        pan_pack_header.SetSizer(sizer_pan_header)

        self.pan_pack.SetSizer(sizer_pack_vert)
        self.frm_pack.Layout()

        # -----------------------
        # Now the confirm window.
        # -----------------------
        MAIN_WINDOW.SetTitle("BEE2 Packages Sync")
        sizer_confirm = wx.BoxSizer(wx.VERTICAL)

        label_confirm = wx.StaticText(MAIN_WINDOW, wx.ID_ANY, "Confirm copying files:")
        sizer_confirm.Add(label_confirm)

        self.button_reset_apply_all = wx.Button(MAIN_WINDOW, label="Reset Package")
        sizer_confirm.Add(self.button_reset_apply_all)

        self.check_confirm = wx.CheckListBox(
            MAIN_WINDOW, wx.ID_ANY,
            choices=[], style=wx.LB_ALWAYS_SB | wx.LB_MULTIPLE,
        )
        sizer_confirm.Add(self.check_confirm, wx.SizerFlags(1).Expand())

        sizer_confirm_btn = wx.BoxSizer(wx.HORIZONTAL)
        sizer_confirm.Add(sizer_confirm_btn, wx.SizerFlags().CenterHorizontal().Border(wx.ALL, 4))

        self.button_ok = wx.Button(MAIN_WINDOW, wx.ID_OK, "")
        self.button_ok.SetDefault()
        sizer_confirm_btn.Add(self.button_ok)

        self.button_skip = wx.Button(MAIN_WINDOW, label="Skip")
        sizer_confirm_btn.Add(self.button_skip)

        MAIN_WINDOW.SetSizer(sizer_confirm)
        sizer_confirm.Fit(MAIN_WINDOW)
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: app.quit_app())
        self.button_skip.Bind(wx.EVT_BUTTON, self.evt_confirm_skip)
        self.button_reset_apply_all.Bind(wx.EVT_BUTTON, self.evt_reset_apply_all)
        self.button_ok.Bind(wx.EVT_BUTTON, self.evt_confirm_ok)

        MAIN_WINDOW.Layout()

    @classmethod
    def run_loop(
        cls,
        func: Callable[['SyncUIBase', trio.Nursery, list[str]], Awaitable[object]],
        files: list[str],
    ) -> None:
        """Run the WX loop."""
        async def init(nursery: trio.Nursery) -> None:
            """Run the app."""
            nursery.start_soon(ui._can_confirm_task)
            nursery.start_soon(ui.reposition_items_task)
            nursery.start_soon(ui._applies_to_all_task)
            await func(ui, nursery, files)
        ui = cls()
        start_main(init)

    async def _applies_to_all_task(self) -> None:
        """Update the checkbox when the value changes."""
        async with contextlib.aclosing(self.applies_to_all.eventual_values()) as agen:
            async for self.check_apply_all.Value in agen:
                pass

    async def _can_confirm_task(self) -> None:
        """Disable the confirm button when files flow in."""
        async with contextlib.aclosing(self.can_confirm.eventual_values()) as agen:
            async for self.button_ok.Enabled in agen:
                pass

    @override
    def ui_set_ask_pack(self, src: trio.Path, dest: PurePath, /) -> None:
        self.lbl_file_src.LabelText = str(src)
        self.lbl_file_dest.LabelText = str(dest)
        self.frm_pack.Show()

    @override
    def ui_set_reset_applies(self, enabled: bool, text: str) -> None:
        self.button_reset_apply_all.Enable(enabled)
        self.button_reset_apply_all.Label = text

    def evt_set_sort(self, _: wx.CommandEvent) -> None:
        """Apply the radio's selections."""
        self.pack_sort_by_id.value = self.radio_sort_order.Selection == 1

    def evt_set_apply_all(self, _: wx.CommandEvent) -> None:
        """Apply the applies-to-all checkbox."""
        self.applies_to_all.value = self.check_apply_all.Value

    def evt_skip(self, _: wx.Event) -> None:
        """Skip the specified file."""
        self.selected_pack.trigger(None)
        self.frm_pack.Hide()

    def evt_confirm_ok(self, _: wx.Event, /) -> None:
        """Files were confirmed, process them."""
        if self.can_confirm.value:
            self.confirmed.set()

    def evt_confirm_skip(self, _: wx.Event) -> None:
        """Skip the current set of files."""
        for i in range(self.check_confirm.Count):
            self.check_confirm.Check(i, False)
        self.confirmed.set()

    def _ui_calc_columns(self, /) -> int:
        return 0  # Not used

    async def _ui_reposition_items(self, /) -> None:
        def make_evt_handler(pack: Package) -> Callable[[wx.CommandEvent], None]:
            """Create the event handler."""
            def btn_handler(_: wx.CommandEvent, /) -> None:
                """Handle a button being pressed."""
                self.selected_pack.trigger(pack)
                self.frm_pack.Hide()
            return btn_handler

        self.sizer_packages.Clear(delete_windows=True)
        flags = wx.SizerFlags().Border()
        for pack in self.packages:
            btn = wx.Button(self.pan_pack, wx.ID_ANY, f"{pack.disp_name}\n<{pack.id}>")
            btn.Bind(wx.EVT_BUTTON, make_evt_handler(pack))
            self.sizer_packages.Add(btn, flags)
        self.sizer_packages.Layout()

    @override
    def ui_reset(self, /) -> None:
        """Reset the list of confirmed items."""
        self.check_confirm.Clear()

    @override
    def ui_add_confirm_file(self, src: trio.Path, dest: trio.Path, /) -> None:
        item = self.check_confirm.Append(
            f'{self.short_path(src)} {RIGHT_ARROW} {self.short_path(dest)} ',
            (src, dest),
        )
        self.check_confirm.Check(item, True)
        MAIN_WINDOW.Fit()

    @override
    def ui_get_files(self, /) -> list[tuple[trio.Path, trio.Path]]:
        """Get selected files."""
        return [
            self.check_confirm.GetClientData(ind)
            for ind in self.check_confirm.GetCheckedItems()
        ]
