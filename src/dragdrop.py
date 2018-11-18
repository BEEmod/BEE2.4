"""Implements drag/drop logic."""
import tkinter
import img
from tkinter import ttk
from typing import (
    Union, Generic, TypeVar,
    List, Dict, Tuple,
    Optional,
)

ItemT = TypeVar('ItemT')  # The object the items move around.
# TODO: Protocol for this.
# Attributes:
#  dnd_icon: Image for the item.
#  dnd_group: If set, the group an item belongs to.
#  dnd_group_icon: If only one item is present for a group, it uses this.


class Manager(Generic[ItemT]):
    """Manages a set of drag-drop points."""
    def __init__(
        self,
        tk: tkinter.Tk,
        *,
        size: Tuple[int, int]=(64, 64),
        move_icon: str,
    ):
        """Create a group of drag-drop slots.

        size is the size of each moved image.

        """
        self._drag_win = drag_win = tkinter.Toplevel(tk)
        self.width, self.height = size
        drag_win.withdraw()
        drag_win.wm_overrideredirect(True)

        self._slots = []  # type: List[Slot[ItemT]]

        self._img_blank = img.color_square(img.PETI_ITEM_BG, size)

    def slot(self, parent: tkinter.Misc, *, source: bool) -> 'Slot[ItemT]':
        """Add a slot to this group."""
        slot = Slot(self, parent, source)
        self._slots.append(slot)

        return slot


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
        self._lbl = ttk.Label(
            parent,
            image=man._img_blank,
            relief='raised',
        )

    @property
    def contents(self) -> Optional[ItemT]:
        """Get the item in this slot, or None if empty"""
        return self._contents

    @contents.setter
    def contents(self, value: Optional[ItemT]) -> None:
        old_cont = self._contents
        self._lbl['image'] = value.dnd_icon
        self._contents = value

    def grid(self, *args, **kwargs) -> None:
        """Grid-position this slot."""
        self._lbl.grid(*args, **kwargs)

    def place(self, *args, **kwargs) -> None:
        """Place-position this slot."""
        self._lbl.place(*args, **kwargs)

    def pack(self, *args, **kwargs) -> None:
        """Pack-position this slot."""
        self._lbl.pack(*args, **kwargs)


def _test() -> None:
    """Test the GUI."""
    from srctools.filesys import RawFileSystem
    from tk_tools import TK_ROOT
    from BEE2_config import GEN_OPTS
    from packageLoader import find_packages, PACKAGE_SYS

    # Setup images to read from packages.
    print('Loading packages for images.')
    GEN_OPTS.load()
    find_packages(GEN_OPTS['Directories']['package'])
    img.load_filesystems(PACKAGE_SYS.values())
    print('Done.')

    manager = Manager(
        TK_ROOT,
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

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()

if __name__ == '__main__':
    _test()