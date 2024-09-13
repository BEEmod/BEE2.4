"""UI implementation for the dragdrop module."""
from __future__ import annotations
from typing import override

import attrs
import wx

from app import img
from app.dragdrop import (
    SLOT_DRAG, DragWin, FlexiCB, InfoCB, ManagerBase,
    Slot,
    # Re-export.
    DragInfo as DragInfo,
)
from transtoken import TransToken
from . import set_fixed_size
from .img import WX_IMG
from .wid_transtoken import set_text


__all__ = ["DragDrop", "DragInfo", "InfoCB", "Slot"]


CUR_MOVE = wx.Cursor(wx.CURSOR_SIZING)
CUR_NO_DROP = wx.Cursor(wx.CURSOR_NO_ENTRY)


@attrs.define
class SlotUI:
    """Widgets associated with a slot."""
    # Our main widget.
    lbl: wx.GenericStaticBitmap
    # The two widgets shown at the bottom when moused over, and the sizer placing them.
    sizer: wx.BoxSizer
    text_lbl: wx.StaticText | None
    info_btn: wx.BitmapButton | None


class DragDrop[ItemT](ManagerBase[ItemT, wx.Window]):
    """Implements UI functionality for the dragdrop module."""
    # Maps slots to the Wx widget implementing them.
    _slot_ui: dict[Slot[ItemT], SlotUI]

    # The window and bitmap displayed inside.
    _drag_win: wx.Frame
    _drag_img: wx.GenericStaticBitmap

    def __init__(
        self,
        parent: wx.Window,
        *,
        info_cb: InfoCB[ItemT],
        size: tuple[int, int] = (64, 64),
        config_icon: bool = False,
        pick_flexi_group: FlexiCB | None = None,
    ) -> None:
        super().__init__(
            info_cb=info_cb,
            size=size,
            config_icon=config_icon,
            pick_flexi_group=pick_flexi_group,
        )
        self._slot_ui = {}
        self._drag_win = drag_win = wx.Frame(parent, style=wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR)
        self._drag_win.Hide()

        self._drag_img = wx.GenericStaticBitmap(drag_win)
        self._drag_img.SetScaleMode(self._drag_img.Scale_AspectFit)
        set_fixed_size(self._drag_img, self.width * 1.25, self.height * 1.25)

        drag_win.Bind(wx.EVT_LEFT_UP, self._evt_stop)
        drag_win.Bind(wx.EVT_MOTION, self._evt_move)
        drag_win.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda evt: self._on_cancel())

    @override
    def _ui_set_icon(self, slot: Slot[ItemT] | DragWin, icon: img.Handle) -> None:
        """Set the specified slot to use this icon, or the drag/drop window."""
        if slot is SLOT_DRAG:
            WX_IMG.apply(self._drag_img, icon)
            self._drag_win.Fit()
        else:
            WX_IMG.apply(self._slot_ui[slot].lbl, icon)

    @override
    def _ui_slot_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        label = self._slot_ui[slot].lbl
        x, y = label.ScreenToClient(round(x), round(y))
        return label.GetClientRect().Contains(x, y)

    @override
    def _ui_slot_create(
        self,
        slot: Slot[ItemT],
        parent: wx.Window,
        title: TransToken,
    ) -> None:
        """Called when a slot is added, to create the UI form."""
        wid_icon = wx.GenericStaticBitmap(parent)
        wid_icon.SetScaleMode(wid_icon.Scale_AspectFit)
        set_fixed_size(wid_icon, self.width, self.height)
        WX_IMG.apply(wid_icon, self._img_blank)

        def on_leftclick(evt: wx.MouseEvent) -> None:
            """Handle clicking on the icon."""
            evt.Skip()  # Allow normal behaviour to also occur.
            if evt.ShiftDown():
                self._on_fastdrag(slot)
            else:
                pos = wid_icon.ClientToScreen(evt.Position)
                self._on_start(slot, pos.x, pos.y)

        def on_configure(evt: wx.Event) -> None:
            """Share this function."""
            self._on_configure(slot)

        wid_icon.Bind(wx.EVT_LEFT_DOWN, on_leftclick)
        wid_icon.Bind(wx.EVT_ENTER_WINDOW, lambda evt: self._on_hover_enter(slot))
        wid_icon.Bind(wx.EVT_LEAVE_WINDOW, lambda evt: self._on_hover_exit(slot))
        wid_icon.Bind(wx.EVT_RIGHT_UP, on_configure)

        sizer = wx.BoxSizer(wx.VERTICAL)

        if title:
            text_lbl = wx.StaticText(wid_icon, style=wx.BORDER_RAISED)
            set_text(text_lbl, title)
            sizer.Add(text_lbl, wx.SizerFlags().Left())
            text_lbl.Hide()
        else:
            text_lbl = None

        if self.config_icon:
            info_btn = wx.BitmapButton(wid_icon)
            WX_IMG.apply(info_btn, img.Handle.builtin('icons/gear', 10, 10))
            info_btn.Bind(wx.EVT_BUTTON, on_configure)
            info_btn.Bind(wx.EVT_RIGHT_DOWN, on_configure)
            info_btn.Hide()

            sizer.AddStretchSpacer()
            sizer.Add(info_btn, wx.SizerFlags().Right())
        else:
            info_btn = None

        self._slot_ui[slot] = SlotUI(wid_icon, sizer, text_lbl, info_btn)

    @override
    def _ui_slot_showdeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor hovers over a slot."""
        slot_ui = self._slot_ui[slot]
        # Add border, but only if either icon exists or we contain an item.
        if slot_ui.text_lbl is not None or slot.contents is not None:
            slot_ui.lbl.SetWindowStyleFlag(wx.BORDER_RAISED)

        # Show configure icon for items.
        if slot_ui.info_btn is not None and slot.contents is not None:
            slot_ui.sizer.Show(slot_ui.info_btn)
        if slot_ui.text_lbl is not None:
            slot_ui.sizer.Show(slot_ui.text_lbl)
        slot_ui.lbl.Refresh()

    @override
    def _ui_slot_hidedeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor leaves a slot."""
        slot_ui = self._slot_ui[slot]
        slot_ui.lbl.SetWindowStyleFlag(0)

        if slot_ui.info_btn is not None:
            slot_ui.sizer.Hide(slot_ui.info_btn)
        if slot_ui.text_lbl is not None:
            slot_ui.sizer.Hide(slot_ui.text_lbl)
        slot_ui.lbl.Refresh()

    @override
    def _ui_dragwin_show(self, x: float, y: float) -> None:
        """Show the drag window."""
        self._drag_win.ShowWithoutActivating()
        self._drag_win.Raise()
        self._drag_win.SetFocus()
        # grab makes this window the only one to receive mouse events, so
        # it is guaranteed that it'll drop when the mouse is released.
        self._drag_win.CaptureMouse()
        # Reposition.
        self._ui_dragwin_update(x, y)

    @override
    def _ui_dragwin_hide(self) -> None:
        """Hide the drag window."""
        self._drag_win.Hide()

    @override
    def _ui_dragwin_update(self, x: float, y: float) -> None:
        """Move the drag window to this position."""
        if self._cur_slot is None:
            return
        size = self._drag_win.GetSize()
        self._drag_win.SetPosition(wx.Point(
            round(x - size.width // 2),
            round(y - size.height // 2),
        ))

        if self._cur_slot.is_source:
            self._drag_win.SetCursor(CUR_NO_DROP)
        else:
            self._drag_win.SetCursor(CUR_MOVE)

    def _evt_move(self, evt: wx.MouseEvent) -> None:
        """Event fired when the drag window is being moved."""
        if evt.Dragging():
            pos = evt.GetEventObject().ClientToScreen(evt.Position)
            self._on_move(pos.x, pos.y)

    def _evt_stop(self, evt: wx.MouseEvent) -> None:
        """Event fired when dragging should stop."""
        self._drag_win.ReleaseMouse()
        pos = evt.GetEventObject().ClientToScreen(evt.Position)
        self._on_stop(pos.x, pos.y)

    def slot_widget(self: DragDrop[ItemT], slot: Slot[ItemT]) -> wx.Window:
        """Return the widget implementing this slot, so it can be added to a sizer."""
        return self._slot_ui[slot].lbl
