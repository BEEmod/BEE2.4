"""UI implementation for the dragdrop module."""
from __future__ import annotations
from typing import override

import wx

from app import img
from app.dragdrop import (
    SLOT_DRAG, DragWin, FlexiCB, InfoCB, ManagerBase,
    Slot,
    # Re-export.
    DragInfo as DragInfo,
)
from transtoken import TransToken
from . import set_fixed_size, PEN_SLOT_BORDER, BRUSH_ALPHA, BRUSH_PETI_BG, PEN_ALPHA
from .img import WX_IMG, ImageSlot


__all__ = ["DragDrop", "DragInfo", "InfoCB", "Slot"]


CUR_MOVE = wx.Cursor(wx.CURSOR_SIZING)
CUR_NO_DROP = wx.Cursor(wx.CURSOR_NO_ENTRY)
SLOT_TEXT_COLOUR = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
FONT_SLOT_TEXT = wx.Font(wx.FontInfo(10))
PEN_GEAR_BORDER = wx.Pen(PEN_SLOT_BORDER.GetColour(), 1)

# Zoom highlighted slots, like in puzzlemaker.
ZOOM_FACTOR = 1.2
ZOOM_SHIFT = (1 - ZOOM_FACTOR) / 2


class SlotUI:
    """The widget for a slot."""
    def __init__(
        self,
        parent: wx.Window,
        width: float, height: float,
        gear: ImageSlot | None,
        text: TransToken,
    ) -> None:
        self.widget = wx.Panel(parent)
        self.contents = ImageSlot(self.widget)
        self.hovered = False
        # Is Slot.contents non-None?
        self.has_item = False
        self.gear = gear  # Image is owned by our manager.
        self.text = text  # Or BLANK if not used.
        # Store the position of the gear as we draw, to match to mouse position.
        self.gear_pos = wx.Rect(-10, -10, 1, 1)

        set_fixed_size(self.widget, width, height)
        self.widget.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, evt: wx.PaintEvent) -> None:
        """Draw the slot."""
        dc = wx.PaintDC(self.widget)
        gc = wx.GraphicsContext.Create(dc)
        wid_size = self.widget.GetSize()
        # Only show the border if we either have an item or have text.
        if self.hovered and (self.has_item or self.text):
            gc.SetBrush(BRUSH_ALPHA)
            gc.SetPen(PEN_SLOT_BORDER)
            gc.DrawRectangle(1, 1, wid_size.width - 1, wid_size.height - 1)
            # Like in puzzlemaker, draw oversized to get a zoom effect. The DC clips for us
            # already.
            self.contents.draw(
                gc,
                round(ZOOM_SHIFT * wid_size.width), round(ZOOM_SHIFT * wid_size.height),
                round(ZOOM_FACTOR * wid_size.width), round(ZOOM_FACTOR * wid_size.width),
            )
            deco_off = self.widget.FromDIP(wx.Size(2, 2))
            if self.text:
                # Text in the upper-left, add a background/border also.
                dc.SetTextForeground(SLOT_TEXT_COLOUR)
                dc.SetFont(FONT_SLOT_TEXT)
                dc.SetPen(PEN_ALPHA)
                dc.SetBrush(BRUSH_PETI_BG)
                text = str(self.text)
                text_size = dc.GetTextExtent(text)
                dc.DrawRectangle(
                    deco_off.x, deco_off.y,
                    text_size.width + 2 * deco_off.x, text_size.height + 2 * deco_off.y,
                )
                dc.DrawText(text, 2 * deco_off.x, 2 * deco_off.y)
            if self.has_item and self.gear is not None:
                # Gear icon in the bottom-right.
                gear_border = self.widget.FromDIP(wx.Size(14, 14))
                gear_size = self.widget.FromDIP(wx.Size(10, 10))
                self.gear_pos = pos = wx.Rect(
                    wid_size.width - gear_border.width,
                    wid_size.height - gear_border.height,
                    gear_border.width, gear_border.height,
                )
                gc.SetPen(PEN_GEAR_BORDER)
                gc.SetBrush(BRUSH_PETI_BG)
                gc.DrawRectangle(pos.x, pos.y, pos.width - 1, pos.height - 1)
                self.gear.draw(
                    gc,
                    pos.x + deco_off.x, pos.y + deco_off.y,
                    gear_size.x, gear_size.y,
                )
        else:
            self.contents.draw(gc, 0, 0, wid_size.width, wid_size.height)

    def inside_conf(self, evt: wx.MouseEvent) -> bool:
        """Check if the specified mouse event occurred inside our gear."""
        return self.gear_pos.Contains(evt.GetPosition())


class DragDrop[ItemT](ManagerBase[ItemT, wx.Window]):
    """Implements UI functionality for the dragdrop module."""
    # Maps slots to the Wx widget implementing them.
    _slot_ui: dict[Slot[ItemT], SlotUI]

    # The window and bitmap displayed inside.
    _drag_win: wx.Frame
    _drag_img: wx.GenericStaticBitmap
    _gear_img: ImageSlot | None

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
        if self.config_icon:
            self._gear_img = ImageSlot(drag_win)
            self._gear_img.set_handle(img.Handle.builtin('icons/gear', 10, 10))
        else:
            self._gear_img = None
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
            slot_ui = self._slot_ui[slot]
            slot_ui.contents.set_handle(icon)
            slot_ui.has_item = slot.contents is not None
            slot_ui.widget.Refresh()

    @override
    def _ui_slot_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        wid = self._slot_ui[slot].widget
        if not wid.IsShown():
            return False
        x, y = wid.ScreenToClient(round(x), round(y))
        return wid.GetClientRect().Contains(x, y)

    @override
    def _ui_slot_coords(self, slot: Slot[ItemT]) -> tuple[int, int]:
        wid = self._slot_ui[slot].widget
        if wid.IsShown():
            rect = wid.GetClientRect()
            return rect.x, rect.y
        else:
            raise ValueError('Slot not placed!')

    @override
    def _ui_slot_create(
        self,
        slot: Slot[ItemT],
        parent: wx.Window,
        title: TransToken,
    ) -> None:
        """Called when a slot is added, to create the UI form."""
        self._slot_ui[slot] = slot_ui = SlotUI(
            parent, self.width, self.height,
            self._gear_img,
            title,
        )

        wid_icon = wx.GenericStaticBitmap(parent)
        wid_icon.SetScaleMode(wid_icon.Scale_AspectFit)
        set_fixed_size(wid_icon, self.width, self.height)
        WX_IMG.apply(wid_icon, self._img_blank)

        def on_leftclick(evt: wx.MouseEvent) -> None:
            """Handle clicking on the icon."""
            evt.Skip()  # Allow normal behaviour to also occur.
            if evt.ShiftDown():
                self._on_fastdrag(slot)
            elif slot_ui.inside_conf(evt):
                self._on_configure(slot)
            else:
                pos = wid_icon.ClientToScreen(evt.Position)
                self._on_start(slot, pos.x, pos.y)

        def on_configure(evt: wx.Event) -> None:
            """Share this function."""
            self._on_configure(slot)

        slot_ui.widget.Bind(wx.EVT_LEFT_DOWN, on_leftclick)
        slot_ui.widget.Bind(wx.EVT_ENTER_WINDOW, lambda evt: self._on_hover_enter(slot))
        slot_ui.widget.Bind(wx.EVT_LEAVE_WINDOW, lambda evt: self._on_hover_exit(slot))
        slot_ui.widget.Bind(wx.EVT_RIGHT_UP, on_configure)

    @override
    def _ui_slot_showdeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor hovers over a slot."""
        slot_ui = self._slot_ui[slot]
        slot_ui.hovered = True
        slot_ui.widget.Refresh()
        # Add border, but only if either icon exists or we contain an item.
        if slot_ui.text is not None or slot.contents is not None:
            slot_ui.widget.SetWindowStyleFlag(wx.BORDER_RAISED)

    @override
    def _ui_slot_hidedeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor leaves a slot."""
        slot_ui = self._slot_ui[slot]
        slot_ui.hovered = False
        slot_ui.widget.SetWindowStyleFlag(0)
        slot_ui.widget.Refresh()

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
        return self._slot_ui[slot].widget
