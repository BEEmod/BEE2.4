"""UI implementation for the dragdrop module."""
from __future__ import annotations
from typing import Callable, Dict, Generic, Optional, Tuple, TypeVar, Union
from typing_extensions import Concatenate, Literal, ParamSpec, override
from tkinter import ttk
import tkinter as tk
from collections.abc import Iterable
from enum import Enum

import attrs

from app import img, localisation, tk_tools
# noinspection PyProtectedMember
from app.dragdrop import (
    SLOT_DRAG, DragWin, FlexiCB, InfoCB, ManagerBase, PositionerBase,
    Slot, in_bbox,
    # Re-exports.
    DragInfo as DragInfo, ItemT as ItemT,
)
from transtoken import TransToken
from ui_tk.img import TK_IMG
import utils


__all__ = ["CanvasPositioner", "DragDrop", "DragInfo", "ItemT", "InfoCB", "Slot"]
ArgsT = ParamSpec('ArgsT')
T = TypeVar('T')

# Tag used on canvases for our flowed slots.
_CANV_TAG = '_BEE2_dragdrop_item'


class GeoManager(Enum):
    """Kind of geometry manager used for a slot."""
    GRID = 'grid'
    PLACE = 'place'
    PACK = 'pack'
    CANVAS = 'canvas'


def _make_placer(
    func: Callable[Concatenate[ttk.Label, ArgsT], object],
    kind: GeoManager,
) -> Callable[Concatenate[DragDrop[ItemT], Slot[ItemT], ArgsT], None]:
    """Calls the original place/pack/grid method, telling the slot which was used.

    This allows propagating the original method args and types.
    """
    def placer(
        self: DragDrop[ItemT], slot: Slot[ItemT], /,
        *args: ArgsT.args, **kwargs: ArgsT.kwargs,
    ) -> None:
        """Call place/pack/grid on the label."""
        slot_ui = self._slot_ui[slot]
        slot_ui.pos_type = kind
        slot_ui.canv_info = None
        func(slot_ui.lbl, *args, **kwargs)
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


class CanvasPositioner(PositionerBase, Generic[T]):
    """Positions slots on a canvas.

    T is the slot object, but it can be anything as long as the place_func matches.
    """
    canvas: tk.Canvas

    def __init__(
        self,
        place_func: Callable[[tk.Canvas, T, int, int, str], object],
        canvas: tk.Canvas,
        item_width: int,
        item_height: int,
        spacing: int = -1,
        yoff: int = 0,
    ):
        self.canvas = canvas
        self._place_func = place_func
        super().__init__(
            canvas.winfo_width(), canvas.winfo_height(),
            item_width, item_height, spacing, yoff
        )

    def resize_canvas(self) -> None:
        """Set the scroll region of the canvas to fit items."""
        width, height = self.get_size()
        self.canvas['scrollregion'] = (0, 0, width, height)

    def place_slots(self, slots: Iterable[T], tag: str, xoff: int = 0) -> None:
        """Place slots onto the canvas."""
        for slot, x, y in self._get_positions(slots, xoff):
            self._place_func(self.canvas, slot, x, y, tag)


@attrs.define
class SlotUI:
    """Widgets associated with a slot."""
    # Our main widget.
    lbl: ttk.Label
    # The two widgets shown at the bottom when moused over.
    text_lbl: Optional[tk.Label]
    info_btn: Optional[tk.Label]

    # The geometry manager used to position this.
    pos_type: Optional[GeoManager] = None
    # If canvas, the tag and x/y coords.
    canv_info: Optional[Tuple[int, int, int]] = None


class DragDrop(ManagerBase[ItemT, tk.Misc], Generic[ItemT]):
    """Implements UI functionality for the dragdrop module."""
    def __init__(
        self,
        parent: Union[tk.Tk, tk.Toplevel],
        *,
        info_cb: InfoCB[ItemT],
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
        drag_win.bind(tk_tools.EVENTS['LEFT_MOVE'], self._evt_move)
        
        self._slot_ui: dict[Slot[ItemT], SlotUI] = {}

    @override
    def _ui_set_icon(self, slot: Slot[ItemT] | DragWin, icon: img.Handle) -> None:
        """Set the specified slot to use this icon, or the drag/drop window."""
        if slot is SLOT_DRAG:
            TK_IMG.apply(self._drag_lbl, icon)
        else:
            TK_IMG.apply(self._slot_ui[slot].lbl, icon)

    @override
    def _ui_slot_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        slot_ui = self._slot_ui[slot]
        if slot_ui.pos_type is None:
            return False  # Not visible = can't be hovering.
        return in_bbox(
            x, y,
            slot_ui.lbl.winfo_rootx(),
            slot_ui.lbl.winfo_rooty(),
            slot_ui.lbl.winfo_width(),
            slot_ui.lbl.winfo_height(),
        )

    @override
    def _ui_slot_create(
        self,
        slot: Slot[ItemT],
        parent: tk.Misc,
        title: TransToken,
    ) -> None:
        """Called when a slot is added, to create the UI form."""
        wid_label = ttk.Label(parent, anchor='center')
        
        TK_IMG.apply(wid_label, self._img_blank)
        tk_tools.bind_leftclick(wid_label, lambda evt: self._on_start(slot, evt.x_root, evt.y_root))
        wid_label.bind(tk_tools.EVENTS['LEFT_SHIFT'], lambda evt: self._on_fastdrag(slot))
        wid_label.bind('<Enter>', lambda evt: self._on_hover_enter(slot))
        wid_label.bind('<Leave>', lambda evt: self._on_hover_exit(slot))
        tk_tools.bind_rightclick(wid_label, lambda evt: self._on_configure(slot))

        if title:
            text_lbl = tk.Label(
                wid_label,
                font=('Helvetica', -12),
                relief='ridge',
                bg=img.PETI_ITEM_BG_HEX,
                name="text",
            )
            localisation.set_text(text_lbl, title)
        else:
            text_lbl = None

        if self.config_icon:
            info_btn = tk.Label(
                wid_label,
                relief='ridge',
                name="info",
            )
            TK_IMG.apply(info_btn, img.Handle.builtin('icons/gear', 10, 10))

            @tk_tools.bind_leftclick(info_btn)
            def info_button_click(e: tk.Event[tk.Label]) -> object:
                """Trigger the callback whenever the gear button was pressed."""
                self._on_configure(slot)
                # Cancel the event sequence, so it doesn't travel up to the main
                # window and hide the window again.
                return 'break'

            # Right-click does the same as the main icon.
            tk_tools.bind_rightclick(info_btn, lambda evt: self._on_configure(slot))
        else:
            info_btn = None

        self._slot_ui[slot] = SlotUI(wid_label, text_lbl, info_btn)

    @override
    def _ui_slot_showdeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor hovers over a slot."""
        padding = 2 if utils.WIN else 0
        slot_ui = self._slot_ui[slot]
        # Add border, but only if either icon exists or we contain an item.
        if slot_ui.text_lbl is not None or slot.contents is not None:
            slot_ui.lbl['relief'] = 'ridge'

        # Show configure icon for items.
        if slot_ui.info_btn is not None and slot.contents is not None:
            slot_ui.info_btn.place(
                x=slot_ui.lbl.winfo_width() - padding,
                y=slot_ui.lbl.winfo_height() - padding,
                anchor='se',
            )

        if slot_ui.text_lbl:
            slot_ui.text_lbl.place(
                x=-padding,
                y=slot_ui.lbl.winfo_height() - padding,
                anchor='sw',
            )

    @override
    def _ui_slot_hidedeco(self, slot: Slot[ItemT]) -> None:
        """Fired when a cursor leaves a slot."""
        slot_ui = self._slot_ui[slot]
        slot_ui.lbl['relief'] = 'flat'

        if slot_ui.info_btn is not None:
            slot_ui.info_btn.place_forget()
        if slot_ui.text_lbl is not None:
            slot_ui.text_lbl.place_forget()

    @override
    def _ui_slot_set_highlight(self, slot: Slot[ItemT], highlight: bool) -> None:
        """Apply the highlighted state."""
        slot_ui = self._slot_ui[slot]
        slot_ui.lbl['background'] = tk_tools.LABEL_HIGHLIGHT_BG if highlight else ''

    @override
    def _ui_dragwin_show(self, x: float, y: float) -> None:
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

    @override
    def _ui_dragwin_hide(self) -> None:
        """Hide the drag window."""
        self._drag_win.grab_release()
        self._drag_win.withdraw()

    @override
    def _ui_dragwin_update(self, x: float, y: float) -> None:
        """Move the drag window to this position."""
        if self._cur_slot is None:
            return
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

    def _evt_move(self, evt: tk.Event[tk.Misc]) -> None:
        """Event fired when the drag window is being moved."""
        self._on_move(evt.x_root, evt.y_root)

    def _evt_stop(self, evt: tk.Event[tk.Misc]) -> None:
        """Event fired when dragging should stop."""
        self._on_stop(evt.x_root, evt.y_root)

    # These call the method on the label, setting our attrs.
    # Type-ignore because these are defined on Grid/Place/Pack, not Label...
    slot_grid = _make_placer(ttk.Label.grid_configure, GeoManager.GRID)
    slot_place = _make_placer(ttk.Label.place_configure, GeoManager.PLACE)
    slot_pack = _make_placer(ttk.Label.pack_configure, GeoManager.PACK)

    def slot_canvas(self, canv: tk.Canvas, slot: Slot[ItemT], x: int, y: int, tag: str) -> None:
        """Position this slot on a canvas."""
        slot_ui = self._slot_ui[slot]
        if slot_ui.pos_type is not None and slot_ui.pos_type is not GeoManager.CANVAS:
            raise ValueError("Can't add already positioned slot!")
        obj_id = canv.create_window(
            x, y,
            width=self.width,
            height=self.height,
            anchor='nw',
            window=slot_ui.lbl,
            tags=(tag,),
        )
        slot_ui.pos_type = GeoManager.CANVAS
        slot_ui.canv_info = (obj_id, x, y)

    def get_slot_canvas_pos(self, slot: Slot[ItemT], canv: tk.Canvas) -> Tuple[int, int]:
        """If on a canvas, fetch the current x/y position."""
        slot_ui = self._slot_ui[slot]
        if slot_ui.canv_info is not None:
            _, x, y = slot_ui.canv_info
            return x, y
        raise ValueError('Not on a canvas!')

    def slot_hide(self, slot: Slot[ItemT]) -> None:
        """Remove this slot from the set position manager."""
        slot_ui = self._slot_ui[slot]
        if slot_ui.pos_type is None:
            raise ValueError('Not added to a geometry manager yet!')
        elif slot_ui.pos_type is GeoManager.CANVAS:
            # Attached via canvas, with an ID as suffix.
            canv = slot_ui.lbl.nametowidget(slot_ui.lbl.winfo_parent())
            assert isinstance(canv, tk.Canvas)
            assert slot_ui.canv_info is not None
            obj_id, _, _ = slot_ui.canv_info
            canv.delete(obj_id)
        else:
            _FORGETTER[slot_ui.pos_type](slot_ui.lbl)
        slot_ui.pos_type = None
        slot_ui.canv_info = None

    def flow_slots(
        self,
        canv: tk.Canvas,
        slots: Iterable[Slot[ItemT]],
        spacing: int=16 if utils.MAC else 8,
        yoff: int=0,
        tag: str=_CANV_TAG,
    ) -> int:
        """Place all the slots in a grid on the provided canvas.

        Any previously added slots with the same tag will be removed.
        - spacing is the amount added on each side of each slot.
        - yoff is the offset from the top, the new height is then returned to allow chaining.
        """
        canv.delete(tag)
        pos = CanvasPositioner(self.slot_canvas, canv, self.width, self.height, spacing, yoff)
        pos.place_slots(slots, tag)
        pos.resize_canvas()
        return pos.yoff
