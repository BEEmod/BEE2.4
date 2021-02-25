from typing import Callable, Any

import tkinter as tk
from tkinter import ttk
from BEE2_config import GEN_OPTS

from app import tooltip
from app import tk_tools
from app.img import Handle as ImgHandle, apply as apply_img
import utils
import srctools
from app import sound


# This is a bit of an ugly hack. On OSX the buttons are set to have
# default padding on the left and right, spreading out the toolbar
# icons too much. This retracts the padding so they are more square
# around the images instead of wasting space.
style = ttk.Style()
style.configure(
    'Toolbar.TButton',
    padding='-20',
)


def make_tool_button(
    frame: tk.Misc,
    img: str,
    command: Callable[[], Any]
) -> ttk.Button:
    """Make a toolbar icon."""
    button = ttk.Button(
        frame,
        style=('Toolbar.TButton' if utils.MAC else 'BG.TButton'),
        command=command,
    )
    apply_img(button, ImgHandle.builtin(img, 16, 16))

    return button


class SubPane(tk.Toplevel):
    """A Toplevel window that can be shown/hidden.

     This follows the main window when moved.
    """
    def __init__(
        self,
        parent: tk.Misc,
        *,
        tool_frame: tk.Frame,
        tool_img: str,
        menu_bar: tk.Menu,
        tool_col: int=0,
        title: str='',
        resize_x: bool=False,
        resize_y: bool=False,
        name: str='',
    ) -> None:
        self.visible = tk.BooleanVar(parent, True)
        self.win_name = name
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
            frame=tool_frame,
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
        tooltip.add_tooltip(
            self.tool_button,
            text=_('Hide/Show the "{}" window.').format(title))
        menu_bar.add_checkbutton(
            label=title,
            variable=self.visible,
            command=self._set_state_from_menu,
        )

        self.transient(master=parent)
        self.resizable(resize_x, resize_y)
        self.title(title)
        tk_tools.set_window_icon(self)

        self.protocol("WM_DELETE_WINDOW", self.hide_win)
        parent.bind('<Configure>', self.follow_main, add='+')
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

        x, y = utils.adjust_inside_screen(x, y, win=self)
        self.geometry('{!s}x{!s}+{!s}+{!s}'.format(
            max(10, width),
            max(10, height),
            x,
            y,
        ))

        self.relX = x - self.parent.winfo_x()
        self.relY = y - self.parent.winfo_y()
        self.save_conf()

    def enable_snap(self, e=None) -> None:
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
        x, y = utils.adjust_inside_screen(
            x=self.parent.winfo_x()+self.relX,
            y=self.parent.winfo_y()+self.relY,
            win=self,
            )
        self.geometry('+'+str(x)+'+'+str(y))
        self.parent.focus()

    def save_conf(self) -> None:
        """Write configuration to the config file."""
        if not self.can_save:
            return
        opt_block = GEN_OPTS['win_state']
        opt_block[self.win_name + '_visible'] = srctools.bool_as_int(self.visible.get())
        opt_block[self.win_name + '_x'] = str(self.relX)
        opt_block[self.win_name + '_y'] = str(self.relY)
        if self.can_resize_x:
            opt_block[self.win_name + '_width'] = str(self.winfo_width())
        if self.can_resize_y:
            opt_block[self.win_name + '_height'] = str(self.winfo_height())

    def load_conf(self) -> None:
        """Load configuration from our config file."""
        try:
            if self.can_resize_x:
                width = int(GEN_OPTS['win_state'][self.win_name + '_width'])
            else:
                width = self.winfo_reqwidth()
            if self.can_resize_y:
                height = int(GEN_OPTS['win_state'][self.win_name + '_height'])
            else:
                height = self.winfo_reqheight()
            self.deiconify()

            self.geometry('{!s}x{!s}'.format(width, height))
            self.sizefrom('user')

            self.relX = int(GEN_OPTS['win_state'][self.win_name + '_x'])
            self.relY = int(GEN_OPTS['win_state'][self.win_name + '_y'])

            self.follow_main()
            self.positionfrom('user')
        except (ValueError, KeyError):
            pass
        if not GEN_OPTS.get_bool('win_state', self.win_name + '_visible', True):
            self.after(150, self.hide_win)

        # Prevent this until here, so the <config> event won't erase our
        #  settings
        self.can_save = True
