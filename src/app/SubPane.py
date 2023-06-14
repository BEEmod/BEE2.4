from typing import Callable, Any, Optional, Union

import tkinter as tk
from tkinter import ttk

from app import localisation, tooltip, tk_tools, sound
from app.img import Handle as ImgHandle
from ui_tk.img import TKImages
from transtoken import TransToken
from config.windows import WindowState
import utils
import config


# This is a bit of an ugly hack. On OSX the buttons are set to have
# default padding on the left and right, spreading out the toolbar
# icons too much. This retracts the padding so they are more square
# around the images instead of wasting space.
style = ttk.Style()
style.configure('Toolbar.TButton', padding='-20',)

TOOL_BTN_TOOLTIP = TransToken.ui('Hide/Show the "{window}" window.')


def make_tool_button(
    frame: tk.Misc, tk_img: TKImages,
    img: str,
    command: Callable[[], Any],
) -> ttk.Button:
    """Make a toolbar icon."""
    button = ttk.Button(
        frame,
        style=('Toolbar.TButton' if utils.MAC else 'BG.TButton'),
        command=command,
    )
    tk_img.apply(button, ImgHandle.builtin(img, 16, 16))

    return button


class SubPane(tk.Toplevel):
    """A Toplevel window that can be shown/hidden.

     This follows the main window when moved.
    """
    def __init__(
        self,
        parent: Union[tk.Toplevel, tk.Tk],
        tk_img: TKImages,
        *,
        tool_frame: Union[tk.Frame, ttk.Frame],
        tool_img: str,
        menu_bar: tk.Menu,
        tool_col: int,
        title: TransToken,
        resize_x: bool=False,
        resize_y: bool=False,
        name: str='',
        legacy_name: str='',
    ) -> None:
        self.visible = tk.BooleanVar(parent, True)
        self.win_name = name
        self.legacy_name = legacy_name
        self.allow_snap = False
        self.can_save = False
        self.parent = parent
        self.relX = 0
        self.relY = 0
        self.can_resize_x = resize_x
        self.can_resize_y = resize_y
        super().__init__(parent, name='pane_' + name)
        self.withdraw()  # Hide by default

        self.tool_button = make_tool_button(
            tool_frame, tk_img,
            img=tool_img,
            command=self._toggle_win,
        )
        self.tool_button.state(('pressed',))
        self.tool_button.grid(
            row=0,
            column=tool_col,
            # Contract the spacing to allow the icons to fit.
            padx=(2 if utils.MAC else (5, 2)),
        )
        tooltip.add_tooltip(self.tool_button, text=TOOL_BTN_TOOLTIP.format(window=title))

        menu_bar.add_checkbutton(variable=self.visible, command=self._set_state_from_menu)
        localisation.set_menu_text(menu_bar, title)

        self.transient(master=parent)
        self.resizable(resize_x, resize_y)
        localisation.set_win_title(self, title)
        tk_tools.set_window_icon(self)

        self.protocol("WM_DELETE_WINDOW", self.hide_win)
        parent.bind('<Configure>', self.follow_main, add=True)
        self.bind('<Configure>', self.snap_win)
        self.bind('<FocusIn>', self.enable_snap)

    def hide_win(self, play_snd: bool=True) -> None:
        """Hide the window."""
        if play_snd:
            sound.fx('config')
        self.withdraw()
        self.visible.set(False)
        self.save_conf()
        self.tool_button.state(('!pressed',))

    def show_win(self, play_snd: bool=True) -> None:
        """Show the window."""
        if play_snd:
            sound.fx('config')
        self.deiconify()
        self.visible.set(True)
        self.save_conf()
        self.tool_button.state(('pressed',))
        self.follow_main()

    def _toggle_win(self) -> None:
        """Toggle the window between shown and hidden."""
        if self.visible.get():
            self.hide_win()
        else:
            self.show_win()

    def _set_state_from_menu(self) -> None:
        """Called when the menu bar button is pressed.

        This has already toggled the variable, so we just need to read
        from it.
        """
        if self.visible.get():
            self.show_win()
        else:
            self.hide_win()

    def move(self, x: int=None, y: int=None, width: int=None, height: int=None) -> None:
        """Move the window to the specified position.

        Effectively an easier-to-use form of Toplevel.geometry(), that
        also updates relX and relY.
        """
        # If we're resizable, keep the current size. Otherwise autosize to
        # contents.
        if width is None:
            width = self.winfo_width() if self.can_resize_x else self.winfo_reqwidth()
        if height is None:
            height = self.winfo_height() if self.can_resize_y else self.winfo_reqheight()
        if x is None:
            x = self.winfo_x()
        if y is None:
            y = self.winfo_y()

        x, y = tk_tools.adjust_inside_screen(x, y, win=self)
        self.geometry(f'{max(10, width)!s}x{max(10, height)!s}+{x!s}+{y!s}')

        self.relX = x - self.parent.winfo_x()
        self.relY = y - self.parent.winfo_y()
        self.save_conf()

    def enable_snap(self, e: Optional[tk.Event]=None) -> None:
        """Allow the window to snap."""
        self.allow_snap = True

    def snap_win(self, e=None) -> None:
        """Callback for window movement.

        This allows it to snap to the edge of the main window.
        """
        # TODO: Actually snap to edges of main window
        if self.allow_snap:
            self.relX = self.winfo_x() - self.parent.winfo_x()
            self.relY = self.winfo_y() - self.parent.winfo_y()
            self.save_conf()

    def follow_main(self, e=None) -> None:
        """When the main window moves, sub-windows should move with it."""
        self.allow_snap = False
        x, y = tk_tools.adjust_inside_screen(
            x=self.parent.winfo_x()+self.relX,
            y=self.parent.winfo_y()+self.relY,
            win=self,
        )
        self.geometry('+'+str(x)+'+'+str(y))
        self.parent.focus()

    def save_conf(self) -> None:
        """Write configuration to the config file."""
        if self.can_save:
            config.APP.store_conf(WindowState(
                visible=self.visible.get(),
                x=self.relX,
                y=self.relY,
                width=self.winfo_width() if self.can_resize_x else -1,
                height=self.winfo_height() if self.can_resize_y else -1,
            ), self.win_name)

    def load_conf(self) -> None:
        """Load configuration from our config file."""
        try:
            state = config.APP.get_cur_conf(WindowState, self.win_name, legacy_id=self.legacy_name)
        except KeyError:
            pass  # No configured state.
        else:
            width = state.width if self.can_resize_x and state.width > 0 else self.winfo_reqwidth()
            height = state.height if self.can_resize_y and state.height > 0 else self.winfo_reqheight()
            self.deiconify()

            self.geometry(f'{width}x{height}')
            self.sizefrom('user')

            self.relX, self.relY = state.x, state.y

            self.follow_main()
            self.positionfrom('user')
            if not state.visible:
                self.after(150, self.hide_win)

        # Prevent this until here, so the <config> event won't erase our
        #  settings
        self.can_save = True
