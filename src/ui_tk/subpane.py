"""Tk-specific implementation for the togglable sub-panes."""
from tkinter import ttk
import tkinter as tk

import utils
from app import sound
from app.SubPane import PaneConf, SubPaneBase, TOOL_BTN_TOOLTIP
from ui_tk import tk_tools, tooltip, wid_transtoken
from ui_tk.img import TKImages


class SubPane(SubPaneBase):
    """Tk window that can be shown/hidden."""
    def __init__(
        self,
        parent: tk.Toplevel | tk.Tk,
        tk_img: TKImages,
        conf: PaneConf,
        *,
        tool_frame: tk.Frame | ttk.Frame,
        menu_bar: tk.Menu,
    ) -> None:
        super().__init__(conf)

        self.parent = parent
        self.win = tk.Toplevel(parent, name=f'pane_{conf.name}')
        self.vis_var = tk.BooleanVar(self.win, True)
        self.win.withdraw()  # Hide by default
        if utils.LINUX:
            self.win.wm_attributes('-type', 'utility')

        self.tool_button = tk_tools.make_tool_button(
            tool_frame, tk_img,
            img=conf.tool_img,
            command=self._toggle_win,
        )
        self.tool_button.state(('pressed',))
        self.tool_button.grid(
            row=0,
            column=conf.tool_col,
            # Contract the spacing to allow the icons to fit.
            padx=(2 if utils.MAC else (5, 2)),
        )
        tooltip.add_tooltip(self.tool_button, text=TOOL_BTN_TOOLTIP.format(window=conf.title))

        menu_bar.add_checkbutton(variable=self.vis_var, command=self._set_state_from_menu)
        wid_transtoken.set_menu_text(menu_bar, conf.title)

        self.win.transient(master=parent)
        self.win.resizable(conf.resize_x, conf.resize_y)
        wid_transtoken.set_win_title(self.win, conf.title)
        tk_tools.set_window_icon(self.win)

        self.win.protocol("WM_DELETE_WINDOW", self.evt_window_closed)
        self.win.bind('<Configure>', self.evt_window_moved)
        self.win.bind('<FocusIn>', self.evt_window_focused)

    def _set_state_from_menu(self) -> None:
        """Called when the menu bar button is pressed.

        This has already toggled the variable, so we just need to read
        from it.
        """
        visible = self.vis_var.get()
        if self.visible.value is not visible:
            sound.fx('config')
            self.visible.value = visible

    def move(
        self,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        """Move the window to the specified position.

        Effectively an easier-to-use form of Toplevel.geometry(), that
        also updates `relX` and `relY`.
        """
        # If we're resizable, keep the current size. Otherwise, autosize to
        # contents.
        if width is None:
            width = self.win.winfo_width() if self.can_resize_x else self.win.winfo_reqwidth()
        if height is None:
            height = self.win.winfo_height() if self.can_resize_y else self.win.winfo_reqheight()
        if x is None:
            x = self.win.winfo_x()
        if y is None:
            y = self.win.winfo_y()

        x, y = tk_tools.adjust_inside_screen(x, y, win=self.win)
        self.win.geometry(f'{max(10, width)!s}x{max(10, height)!s}+{x!s}+{y!s}')

        self._rel_x, self._rel_y = self._ui_get_pos()
        self.save_conf()

    def resize(self) -> None:
        """Resize the window to fit its contents."""
        # If we're resizable, keep the current size. Otherwise, autosize to
        # contents.
        width = self.win.winfo_width() if self.can_resize_x else self.win.winfo_reqwidth()
        height = self.win.winfo_height() if self.can_resize_y else self.win.winfo_reqheight()
        self.win.geometry(f'{max(10, width)!s}x{max(10, height)!s}')
        self.save_conf()

    def _ui_show(self) -> None:
        self.win.deiconify()
        self.tool_button.state(('pressed',))
        self.vis_var.set(True)

    def _ui_hide(self) -> None:
        self.win.withdraw()
        self.tool_button.state(('!pressed',))
        self.vis_var.set(False)

    def _ui_get_pos(self) -> tuple[int, int]:
        return (
            self.win.winfo_x() - self.parent.winfo_x(),
            self.win.winfo_y() - self.parent.winfo_y(),
        )

    def _ui_apply_relative(self) -> None:
        """Apply rel_x/rel_y."""
        x, y = tk_tools.adjust_inside_screen(
            x=self.parent.winfo_x()+self._rel_x,
            y=self.parent.winfo_y()+self._rel_y,
            win=self.win,
        )
        self.win.geometry(f'+{x}+{y}')
        self.parent.focus()

    def _ui_get_size(self) -> tuple[int, int]:
        return self.win.winfo_width(), self.win.winfo_height()

    def _ui_set_size(self, width: int | None, height: int | None) -> None:
        if width is None:
            width = self.win.winfo_reqwidth()
        if height is None:
            height = self.win.winfo_reqheight()
        self.win.geometry(f'{width}x{height}')

    def _ui_bind_parent(self) -> None:
        self.parent.bind('<Configure>', self.follow_main, add=True)
