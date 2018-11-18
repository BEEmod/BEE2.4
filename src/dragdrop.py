"""Implements drag/drop logic."""
from tk_tools import TK_ROOT
import tkinter
import img
import utils
import sound
from tkinter import ttk
from srctools.logger import get_logger
from typing import (
    Union, Generic, TypeVar,
    List, Dict, Tuple,
    Optional,
)

LOGGER = get_logger(__name__)

ItemT = TypeVar('ItemT')  # The object the items move around.
# TODO: Protocol for this.
# Attributes:
#  dnd_icon: Image for the item.
#  dnd_group: If set, the group an item belongs to.
#  dnd_group_icon: If only one item is present for a group, it uses this.


def in_bbox(
    x: float, y: float,
    left: float, top: float,
    width: float, height: float,
) -> bool:
    """Checks if (x, y) is inside the (left, top, width, height) bbox."""
    if x < left or y < top:
        return False
    if x > left + width or y > top + height:
        return False
    return True


class Manager(Generic[ItemT]):
    """Manages a set of drag-drop points."""
    def __init__(
        self,
        *,
        size: Tuple[int, int]=(64, 64),
        move_icon: str,
    ):
        """Create a group of drag-drop slots.

        size is the size of each moved image.

        """
        self.width, self.height = size

        self._slots = []  # type: List[Slot[ItemT]]

        self._img_blank = img.color_square(img.PETI_ITEM_BG, size)

        # If dragging, the item we are dragging.
        self._cur_drag = None  # type: Optional[ItemT]
        # While dragging, the place we started at.
        self._cur_prev_slot = None  # type: Optional[Slot[ItemT]]

        self._drag_win = drag_win = tkinter.Toplevel(TK_ROOT)
        drag_win.withdraw()
        drag_win.transient(master=TK_ROOT)
        drag_win.wm_overrideredirect(True)

        self._drag_lbl = drag_lbl = tkinter.Label(
            drag_win,
            image=self._img_blank,
        )
        drag_lbl.grid(row=0, column=0)
        drag_win.bind(utils.EVENTS['LEFT_RELEASE'], self._evt_stop)

    def slot(self, parent: tkinter.Misc, *, source: bool) -> 'Slot[ItemT]':
        """Add a slot to this group."""
        slot = Slot(self, parent, source)
        self._slots.append(slot)

        return slot

    def _pos_slot(self, x: float, y: float) -> 'Optional[Slot[ItemT]]':
        """Find the slot under this X,Y (if any)."""
        for slot in self._slots:
            if slot._pos_type is not None:
                lbl = slot._lbl
                if in_bbox(
                    x, y,
                    lbl.winfo_rootx(),
                    lbl.winfo_rooty(),
                    lbl.winfo_width(),
                    lbl.winfo_height(),
                ):
                    return slot
        return None

    def _display_item(
        self,
        lbl: Union[tkinter.Label, ttk.Label],
        item: Optional[ItemT],
    ) -> None:
        """Display the specified item on the given label."""
        if item is None:
            lbl['image'] = self._img_blank
        else:
            lbl['image'] = item.dnd_icon

    def _start(self, slot: 'Slot[ItemT]', event: tkinter.Event) -> None:
        """Start the drag."""
        if slot.contents is None:
            return  # Can't pick up blank...

        self._cur_drag = slot.contents

        self._display_item(self._drag_lbl, self._cur_drag)
        self._cur_prev_slot = slot

        LOGGER.info('Started: {}', self._cur_drag)

        sound.fx('config')
        # drag_win.passed_over_pal = False

        # if drag_win.drag_item.is_pre:  # is the cursor over the preview pane?
        #     drag_win.drag_item.kill()
        #     UI['pre_moving'].place(
        #         x=drag_win.drag_item.pre_x * 65 + 4,
        #         y=drag_win.drag_item.pre_y * 65 + 32,
        #     )
        #     drag_win.from_pal = True
        #
        #     for item in pal_picked:
        #         if item.id == drag_win.drag_item.id:
        #             item.load_data()
        #
        #     # When dragging off, switch to the single-only icon
        #     UI['drag_lbl']['image'] = drag_win.drag_item.item.get_icon(
        #         drag_win.drag_item.subKey,
        #         allow_single=False,
        #     )
        # else:
        #     drag_win.from_pal = False
        #     UI['drag_lbl']['image'] = drag_win.drag_item.item.get_icon(
        #         drag_win.drag_item.subKey,
        #         allow_single=True,
        #         single_num=0,
        #     )

        self._drag_win.deiconify()
        self._drag_win.lift(TK_ROOT)
        # grab makes this window the only one to receive mouse events, so
        # it is guaranteed that it'll drop when the mouse is released.
        self._drag_win.grab_set_global()
        # NOTE: _global means no other programs can interact, make sure
        # it's released eventually or you won't be able to quit!

        # Call this to reposition it.
        self._evt_move(event)

        self._drag_win.bind(utils.EVENTS['LEFT_MOVE'], self._evt_move)
        # UI['pre_sel_line'].lift()

    def _evt_move(self, event: tkinter.Event) -> None:
        """Reposition the item whenever moving."""
        if self._cur_drag is None:
            # We aren't dragging, ignore the event.
            return

        self._drag_win.geometry('+{}+{}'.format(
            event.x_root - self.width // 2,
            event.y_root - self.height // 2,
        ))

        # if 0 <= pos_x < 4 and 0 <= pos_y < 8:
        #     drag_win.configure(cursor=utils.CURSORS['move_item'])
        #     UI['pre_sel_line'].place(x=pos_x * 65 + 3, y=pos_y * 65 + 33)
        #     if not drag_win.passed_over_pal:
        #         # If we've passed over the palette, replace identical items
        #         # with movement icons to indicate they will move to the new
        #         # location
        #         for item in pal_picked:
        #             if item == drag_win.drag_item:
        #                 # We haven't removed the original, so we don't need the
        #                 # special label for this.
        #                 # The group item refresh will return this if nothing
        #                 # changes.
        #                 item['image'] = img.png('BEE2/item_moving')
        #                 break
        #
        #     drag_win.passed_over_pal = True
        # else:
        #     if drag_win.from_pal and drag_win.passed_over_pal:
        #         drag_win.configure(cursor=utils.CURSORS['destroy_item'])
        #     else:
        #         drag_win.configure(cursor=utils.CURSORS['invalid_drag'])
        #     UI['pre_sel_line'].place_forget()

    def _evt_stop(self, event: tkinter.Event):
        """User released the item."""
        if not self._cur_drag:
            return

        sound.fx('config')
        self._drag_win.grab_release()
        self._drag_win.withdraw()
        self._drag_win.unbind(utils.EVENTS['LEFT_MOVE'])

        dest = self._pos_slot(event.x_root, event.y_root)
        LOGGER.info('Stopped: {} -> {}', self._cur_drag, dest)

        if dest and not dest.is_source:
            dest.contents = self._cur_drag

        self._cur_drag = None
        self._cur_prev_slot = None


class Slot(Generic[ItemT]):
    """Represents a single slot."""
    def __init__(
        self,
        man: Manager,
        parent: tkinter.Misc,
        is_source: bool
    ) -> None:
        """Internal only, use Manager.slot()."""

        self.man = man
        self.is_source = is_source
        self._contents = None  # type: Optional[ItemT]
        self._pos_type = None
        self._lbl = ttk.Label(
            parent,
            image=man._img_blank,
            relief='raised',
        )
        utils.bind_leftclick(self._lbl, self._evt_start)

    @property
    def contents(self) -> Optional[ItemT]:
        """Get the item in this slot, or None if empty"""
        return self._contents

    @contents.setter
    def contents(self, value: Optional[ItemT]) -> None:
        old_cont = self._contents
        self.man._display_item(self._lbl, value)
        self._contents = value

    def grid(self, *args, **kwargs) -> None:
        """Grid-position this slot."""
        self._pos_type = 'grid'
        self._lbl.grid(*args, **kwargs)

    def place(self, *args, **kwargs) -> None:
        """Place-position this slot."""
        self._pos_type = 'place'
        self._lbl.place(*args, **kwargs)

    def pack(self, *args, **kwargs) -> None:
        """Pack-position this slot."""
        self._pos_type = 'pack'
        self._lbl.pack(*args, **kwargs)

    def hide(self) -> None:
        """Remove this slot from the set position manager."""
        if self._pos_type is None:
            raise ValueError('Not added to a geometry manager yet!')
        getattr(self._lbl, self._pos_type + '_forget')()
        self._pos_type = None

    def _evt_start(self, event: tkinter.Event) -> None:
        """Start dragging."""
        self.man._start(self, event)


def _test() -> None:
    """Test the GUI."""
    from srctools.logger import init_logging
    from tk_tools import TK_ROOT
    from BEE2_config import GEN_OPTS
    from packageLoader import find_packages, PACKAGE_SYS

    init_logging()

    # Setup images to read from packages.
    print('Loading packages for images.')
    GEN_OPTS.load()
    find_packages(GEN_OPTS['Directories']['package'])
    img.load_filesystems(PACKAGE_SYS.values())
    print('Done.')

    manager = Manager(
        move_icon='BEE2/item_moving.png',
    )

    left_frm = ttk.Frame(TK_ROOT)
    right_frm = ttk.Frame(TK_ROOT)

    left_frm.grid(row=0, column=0, sticky='NSEW', padx=8)
    right_frm.grid(row=0, column=1, sticky='NSEW', padx=8)
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.columnconfigure(1, weight=1)

    slot_dest = []
    slot_src = []

    class TestItem:
        def __init__(self, name, icon, group=None, group_icon=None):
            self.name = name
            self.dnd_icon = img.png('items/clean/{}.png'.format(icon))
            self.dnd_group = group
            if group_icon:
                self.dnd_group_icon = img.png('items/clean/{}.png'.format(group_icon))

        def __repr__(self):
            return '<Item {}>'.format(self.name)

    items = [
        TestItem('Dropper', 'dropper'),
        TestItem('Entry', 'entry_door'),
        TestItem('Exit', 'exit_door'),
        TestItem('Large Obs', 'large_obs_room'),
        TestItem('Faith Plate', 'faithplate'),

        TestItem('Standard Cube', 'cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Companion Cube', 'companion_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Reflection Cube', 'reflection_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Edgeless Cube', 'edgeless_safety_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Franken Cube', 'frankenturret', 'ITEM_CUBE', 'cubes'),

        TestItem('Repulsion', 'paintsplat_bounce', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Propulsion', 'paintsplat_speed', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Reflection', 'paintsplat_reflection', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Conversion', 'paintsplat_portal', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Cleansing', 'paintsplat_water', 'ITEM_PAINT_SPLAT', 'paints'),
    ]

    for x in range(4):
        for y in range(8):
            slot = manager.slot(left_frm, source=False)
            slot.grid(column=x, row=y, padx=1, pady=1)
            slot_dest.append(slot)

    for i, item in enumerate(items):
            slot = manager.slot(right_frm, source=True)
            slot.grid(column=i % 5, row=i // 5, padx=1, pady=1)
            slot_src.append(slot)
            slot.contents = item

    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=lambda: print('Dest:', [slot.contents for slot in slot_dest])
    ).grid(row=2, column=0)
    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=lambda: print('Source:', [slot.contents for slot in slot_src])
    ).grid(row=2, column=1)

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()

if __name__ == '__main__':
    _test()
