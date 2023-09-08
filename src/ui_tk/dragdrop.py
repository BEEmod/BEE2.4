"""UI implementation for the dragdrop module."""
from __future__ import annotations

import tkinter as tk
from enum import Enum

from tkinter import ttk
from typing import Callable, Dict, Generic, Optional, Tuple, Union

from typing_extensions import Concatenate, Literal, ParamSpec

from app import img, localisation, tk_tools
from app.dragdrop import DragWin, FlexiCB, ItemT, ManagerBase, InfoCB, SLOT_DRAG, Slot, in_bbox
from transtoken import TransToken
from ui_tk.img import TK_IMG


ArgsT = ParamSpec('ArgsT')


class GeoManager(Enum):
    """Kind of geometry manager used for a slot."""
    GRID = 'grid'
    PLACE = 'place'
    PACK = 'pack'
    CANVAS = 'canvas'


def _make_placer(
    func: Callable[Concatenate[ttk.Label, ArgsT], object],
    kind: GeoManager,
) -> Callable[Concatenate[DragDrop, Slot, ArgsT], None]:
    """Calls the original place/pack/grid method, telling the slot which was used.

    This allows propagating the original method args and types.
    """
    def placer(man: DragDrop, slot: Slot, /, *args: ArgsT.args, **kwargs: ArgsT.kwargs) -> None:
        """Call place/pack/grid on the label."""
        slot._pos_type = kind
        slot._canv_info = None
        func(man._slot_ui[slot].lbl, *args, **kwargs)
    return placer


# Functions which remove a label from the parent.
_FORGETTER: Dict[
    Literal[GeoManager.PACK, GeoManager.PLACE, GeoManager.GRID],
    Callable[[ttk.Label], object]
] = {
    GeoManager.PLACE: ttk.Label.place_forget,
    GeoManager.GRID: ttk.Label.grid_forget,
    GeoManager.PACK: ttk.Label.pack_forget,
}

class SlotUI:
    """Widgets associated with a slot."""
    # The two widgets shown at the bottom when moused over.
    text_lbl: Optional[tk.Label]
    info_btn: Optional[tk.Label]
    # Our main widget.
    lbl: ttk.Label

    # The geometry manager used to position this.
    _pos_type: Optional[GeoManager] = None
    # If canvas, the tag and x/y coords.
    _canv_info: Optional[Tuple[int, int, int]] = None
    

class DragDrop(ManagerBase[ItemT, tk.Misc], Generic[ItemT]):
    """Implements UI functionality for the dragdrop module."""
    def __init__(
        self,
        parent: Union[tk.Tk, tk.Toplevel],
        *,
        info_cb: InfoCB,
        size: Tuple[int, int]=(64, 64),
        config_icon: bool=False,
        pick_flexi_group: Optional[FlexiCB]=None,
    ) -> None:
        super().__init__(
            info_cb=info_cb,
            size=size,
            config_icon=config_icon,
            pick_flexi_group=pick_flexi_group,
        )
        self.parent = parent

        self._drag_win = drag_win = tk.Toplevel(parent, name='drag_icon')
        drag_win.withdraw()
        drag_win.transient(master=parent)
        drag_win.wm_overrideredirect(True)

        self._drag_lbl = tk.Label(drag_win)
        self._drag_lbl.grid(row=0, column=0)
        drag_win.bind(tk_tools.EVENTS['LEFT_RELEASE'], self._evt_stop)
        
        self._slot_ui: dict[Slot[ItemT], SlotUI] = {}

    def _ui_set_icon(self, slot: Slot[ItemT] | DragWin, icon: img.Handle) -> None:
        """Set the specified slot to use this icon, or the drag/drop window."""
        if slot is SLOT_DRAG:
            TK_IMG.apply(self._drag_lbl, self._img_blank)
        else:
            TK_IMG.apply(self._slot_ui[slot].lbl, self._img_blank)

    def _ui_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        lbl = self._slot_ui[slot].lbl
        return in_bbox(
            x, y,
            lbl.winfo_rootx(),
            lbl.winfo_rooty(),
            lbl.winfo_width(),
            lbl.winfo_height(),
        )
            
    def _ui_create_slot(
        self,
        slot: Slot[ItemT],
        parent: tk.Misc,
        title: TransToken,
    ) -> None:
        """Called when a slot is added, to create the UI form."""
        wid_label = ttk.Label(parent, anchor='center')
        
        TK_IMG.apply(wid_label, self._img_blank)
        tk_tools.bind_leftclick(wid_label, self._evt_start)
        wid_label.bind(tk_tools.EVENTS['LEFT_SHIFT'], self._evt_fastdrag)
        wid_label.bind('<Enter>', self._evt_hover_enter)
        wid_label.bind('<Leave>', self._evt_hover_exit)
        # Bind this not the self variable.
        config_event = self._on_configured(slot)
        tk_tools.bind_rightclick(wid_label, config_event)

        if title:
            text_lbl = tk.Label(
                wid_label,
                font=('Helvetica', -12),
                relief='ridge',
                bg=img.PETI_ITEM_BG_HEX,
            )
            localisation.set_text(text_lbl, title)
        else:
            text_lbl = None

        if self.config_icon:
            info_btn = tk.Label(
                wid_label,
                relief='ridge',
            )
            TK_IMG.apply(info_btn, img.Handle.builtin('icons/gear', 10, 10))

            @tk_tools.bind_leftclick(info_btn)
            def info_button_click(e: tk.Event) -> object:
                """Trigger the callback whenever the gear button was pressed."""
                config_event(e)
                # Cancel the event sequence, so it doesn't travel up to the main
                # window and hide the window again.
                return 'break'

            # Rightclick does the same as the main icon.
            tk_tools.bind_rightclick(info_btn, config_event)
        else:
            info_btn = None

    def _ui_drag_show(self, x: float, y: float) -> None:
        """Show the drag window."""
        self._drag_win.deiconify()
        self._drag_win.lift()
        # grab makes this window the only one to receive mouse events, so
        # it is guaranteed that it'll drop when the mouse is released.
        self._drag_win.grab_set_global()
        # NOTE: _global means no other programs can interact, make sure
        # it's released eventually. Otherwise, you won't be able to quit!
        # Reposition.
        self._ui_dragwin_update(x, y)

    def _ui_drag_hide(self) -> None:
        """Hide the drag window."""
        self._drag_win.grab_release()
        self._drag_win.withdraw()

    def _ui_dragwin_update(self, x: float, y: float) -> None:
        """Move the drag window to this position."""
        self._drag_win.geometry(f'+{round(x - self.width // 2)}+{round(y - self.height // 2)}')

        dest = self._pos_slot(x, y)

        if dest:
            self._drag_win['cursor'] = tk_tools.Cursors.MOVE_ITEM
        elif self._cur_slot.is_source:
            self._drag_win['cursor'] = tk_tools.Cursors.INVALID_DRAG
        elif self._cur_slot.is_flexi:  # If it's a flexi slot, it's going back.
            self._drag_win['cursor'] = tk_tools.Cursors.MOVE_ITEM
        else:
            self._drag_win['cursor'] = tk_tools.Cursors.DESTROY_ITEM

    def _evt_move(self, evt: tk.Event) -> None:
        """Event fired when the drag window is being moved."""
        self._on_move(evt.x_root, evt.y_root)

    def _evt_stop(self, evt: tk.Event) -> None:
        """Event fired when dragging should stop."""
        self._on_stop(evt.x_root, evt.y_root)
