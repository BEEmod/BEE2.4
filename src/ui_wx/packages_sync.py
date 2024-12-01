"""UI implementation for the packages-sync tool."""
from collections.abc import Callable
from pathlib import Path

import wx

from app.packages_sync import SyncUIBase
from packages import Package
from . import MAIN_WINDOW


class WxUI(SyncUIBase):
    """Wx implementation of the packages-sync UI."""
    # This is a dev tool, we don't need to translate.
    def __init__(self) -> None:
        super().__init__()
        self_ref = self

        self.frm_pack = wx.Frame(
            MAIN_WINDOW,
            title="Select Package",
            style=wx.CAPTION | wx.CLIP_CHILDREN
                  | wx.CLOSE_BOX | wx.RESIZE_BORDER
                  | wx.STAY_ON_TOP | wx.SYSTEM_MENU,
        )
        self.pan_pack = wx.Panel(self, wx.ID_ANY)
        pan_pack_header = wx.Panel(self.pan_pack, wx.ID_ANY, style=wx.BORDER_RAISED)
        sizer_pack_vert = wx.BoxSizer(wx.VERTICAL)
        sizer_pack_vert.Add(pan_pack_header, 0, wx.EXPAND | wx.FIXED_MINSIZE, 0)

        sizer_pan_header = wx.BoxSizer(wx.HORIZONTAL)
        sizer_actions = wx.BoxSizer(wx.VERTICAL)
        sizer_pan_header.Add(sizer_actions, 0, wx.ALL, 4)

        self.btn_skip = wx.Button(pan_pack_header, wx.ID_ANY, "Skip")
        sizer_actions.Add(self.btn_skip, 0, 0, 0)

        self.check_apply_all = wx.CheckBox(pan_pack_header, wx.ID_ANY, "Apply To All")
        sizer_actions.Add(self.check_apply_all, 0, 0, 0)

        sizer_paths = wx.BoxSizer(wx.VERTICAL)
        sizer_pan_header.Add(sizer_paths, 1, wx.EXPAND, 0)

        self.lbl_file_src = wx.StaticText(pan_pack_header, wx.ID_ANY, "")
        sizer_paths.Add(self.lbl_file_src, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        lbl_arrow_down = wx.StaticText(pan_pack_header, wx.ID_ANY, "VVV")
        sizer_paths.Add(lbl_arrow_down, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.lbl_file_dest = wx.StaticText(pan_pack_header, wx.ID_ANY, "")
        sizer_paths.Add(self.lbl_file_dest, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.radio_sort_order = wx.RadioBox(
            pan_pack_header, wx.ID_ANY, "Sort Order",
            choices=["Name", "ID"], majorDimension=2,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.radio_sort_order.SetSelection(0)
        sizer_pan_header.Add(self.radio_sort_order, 0, wx.ALL, 4)

        self.sizer_packages = wx.WrapSizer(wx.HORIZONTAL)
        sizer_pack_vert.Add(self.sizer_packages, 0, wx.EXPAND, 0)

        pan_pack_header.SetSizer(sizer_pan_header)

        self.pan_pack.SetSizer(sizer_pack_vert)
        self.frm_pack.Layout()

        # -----------------------
        # Now the confirm window.
        # -----------------------

        self.dialog_confirm = wx.Dialog(MAIN_WINDOW, title="Confirm File")
        sizer_confirm = wx.BoxSizer(wx.VERTICAL)

        label_confirm = wx.StaticText(self.dialog_confirm, wx.ID_ANY, "Confirm copying files:")
        sizer_confirm.Add(label_confirm)

        self.check_confirm = wx.CheckListBox(
            self.dialog_confirm, wx.ID_ANY,
            choices=[], style=wx.LB_ALWAYS_SB | wx.LB_MULTIPLE,
        )
        sizer_confirm.Add(self.check_confirm, wx.SizerFlags(1).Expand())

        sizer_confirm_btn = wx.StdDialogButtonSizer()
        sizer_confirm.Add(sizer_confirm_btn, wx.SizerFlags().CenterHorizontal().Border(4))

        self.button_ok = wx.Button(self.dialog_confirm, wx.ID_OK, "")
        self.button_ok.SetDefault()
        sizer_confirm_btn.AddButton(self.button_ok)

        self.button_cancel = wx.Button(self.dialog_confirm, wx.ID_CANCEL, "")
        sizer_confirm_btn.AddButton(self.button_cancel)

        sizer_confirm_btn.Realize()

        self.dialog_confirm.SetSizer(sizer_confirm)
        sizer_confirm.Fit(self.dialog_confirm)
        self.dialog_confirm.Bind(wx.EVT_CLOSE, self.evt_confirm_cancel)
        self.button_cancel.Bind(wx.EVT_BUTTON, self.evt_confirm_cancel)
        self.button_ok.Bind(wx.EVT_BUTTON, self.evt_confirm_ok)

        self.dialog_confirm.SetAffirmativeId(self.button_ok.GetId())
        self.dialog_confirm.SetEscapeId(self.button_cancel.GetId())
        self.dialog_confirm.Layout()

    def ui_set_ask_pack(self, src: Path, des: Path) -> None:
        self.lbl_file_src.LabelText = str(src)
        self.lbl_file_dest.LabelText = str(src)
        self.dialog_confirm.Show()

    def evt_confirm_ok(self, event: wx.Event) -> None:
        """Files were confirmed, continue."""
        self.dialog_confirm.Hide()
        self.confirmed.set()

    def evt_confirm_cancel(self, event: wx.Event) -> None:
        """Confirm screen was hidden, abort all."""
        for i in range(self.check_confirm.Count):
            self.check_confirm.Check(i, False)
        self.dialog_confirm.Hide()
        self.confirmed.set()

    def _ui_calc_columns(self) -> int:
        return 0  # Not used

    async def _ui_reposition_items(self) -> None:
        def make_func(pack: Package) -> Callable[[wx.CommandEvent], None]:
            """Create the event handler."""
            def func(evt: wx.CommandEvent):
                """Handle a button being pressed."""
                self.selected_pack.trigger(pack)
                self.frm_pack.Hide()
            return func

        self.sizer_packages.Clear(delete_windows=True)
        flags = wx.SizerFlags().Border()
        for pack in self.packages:
            btn = wx.Button(self.pan_pack, wx.ID_ANY, f"{pack.disp_name}\n<{pack.id}>")
            btn.Bind(wx.EVT_BUTTON, make_func(pack))
            self.sizer_packages.Add(btn, flags)

    def ui_set_confirm_files(self) -> None:
        self.check_confirm.Clear()
        for tup in self.files:
            src, dest = tup
            self.check_confirm.Append(f'{src}\n->{dest}', tup)

    def ui_get_files(self) -> list[tuple[Path, Path]]:
        """Get selected files."""
        return [
            self.check_confirm.GetClientData(ind)
            for ind in self.check_confirm.GetCheckedItems()
        ]
