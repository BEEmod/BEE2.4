from typing import Any

from tkinter import ttk
import tkinter as tk
from collections.abc import Callable

from srctools.logger import get_logger
import attrs
import trio

from app import sound
from app.img import Handle as ImgHandle
from config.windows import WindowState
from transtoken import TransToken
from ui_tk import tk_tools, tooltip, wid_transtoken
from ui_tk.img import TKImages
import config
import utils


# This is a bit of an ugly hack. On OSX the buttons are set to have
# default padding on the left and right, spreading out the toolbar
# icons too much. This retracts the padding so they are more square
# around the images instead of wasting space.
style = ttk.Style()
style.configure('Toolbar.TButton', padding='-20',)

TOOL_BTN_TOOLTIP = TransToken.ui('Hide/Show the "{window}" window.')
LOGGER = get_logger(__name__)


@attrs.frozen(kw_only=True)
class PaneConf:
    """Configuration for a pane."""
    tool_img: str
    tool_col: int
    title: TransToken
    resize_x: bool = False
    resize_y: bool = False
    name: str = ''
    legacy_name: str = ''

CONF_PALETTE = PaneConf(
    title=TransToken.ui('Palettes'),
    name='pal',
    resize_x=True,
    resize_y=True,
    tool_img='icons/win_palette',
    tool_col=10,
)

CONF_EXPORT_OPTS = PaneConf(
    title=TransToken.ui('Export Options'),
    name='opt',
    resize_x=True,
    tool_img='icons/win_options',
    tool_col=11,
)

CONF_ITEMCONFIG = PaneConf(
    title=TransToken.ui('Style/Item Properties'),
    name='item',
    legacy_name='style',
    resize_x=False,
    resize_y=True,
    tool_img='icons/win_itemvar',
    tool_col=12,
)

CONF_COMPILER = PaneConf(
    title=TransToken.ui('Compile Options'),
    name='compiler',
    resize_x=True,
    resize_y=False,
    tool_img='icons/win_compiler',
    tool_col=13,
)


class SubPane:
    """A Toplevel window that can be shown/hidden.

     This follows the main window when moved.
    """
    def __init__(
        self,
        parent: tk.Toplevel | tk.Tk,
        tk_img: TKImages,
        conf: PaneConf,
        *,
        tool_frame: tk.Frame | ttk.Frame,
        menu_bar: tk.Menu,
    ) -> None:
        self.visible = tk.BooleanVar(parent, True)
        self.win_name = conf.name
        self.legacy_name = conf.legacy_name
        self.allow_snap = False
        self.can_save = False
        self.parent = parent
        self.relX = 0
        self.relY = 0
        self.can_resize_x = conf.resize_x
        self.can_resize_y = conf.resize_y
        self.win = tk.Toplevel(parent, name=f'pane_{conf.name}')
        self.win.withdraw()  # Hide by default
        if utils.LINUX:
            self.win.wm_attributes('-type', 'utility')

        self.tool_button = make_tool_button(
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

        menu_bar.add_checkbutton(variable=self.visible, command=self._set_state_from_menu)
        wid_transtoken.set_menu_text(menu_bar, conf.title)

        self.win.transient(master=parent)
        self.win.resizable(conf.resize_x, conf.resize_y)
        wid_transtoken.set_win_title(self.win, conf.title)
        tk_tools.set_window_icon(self.win)

        self.win.protocol("WM_DELETE_WINDOW", self.hide_win)
        self.win.bind('<Configure>', self.snap_win)
        self.win.bind('<FocusIn>', self.enable_snap)

    def hide_win(self, play_snd: bool = True) -> None:
        """Hide the window."""
        if play_snd:
            sound.fx('config')
        self.win.withdraw()
        self.visible.set(False)
        self.save_conf()
        self.tool_button.state(('!pressed',))

    def show_win(self, play_snd: bool = True) -> None:
        """Show the window."""
        if play_snd:
            sound.fx('config')
        self.win.deiconify()
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

        self.relX = x - self.parent.winfo_x()
        self.relY = y - self.parent.winfo_y()
        self.save_conf()

    def enable_snap(self, _: object = None, /) -> None:
        """Allow the window to snap."""
        self.allow_snap = True

    def snap_win(self, _: object = None, /) -> None:
        """Callback for window movement.

        This allows it to snap to the edge of the main window.
        """
        # TODO: Actually snap to edges of main window
        if self.allow_snap:
            self.relX = self.win.winfo_x() - self.parent.winfo_x()
            self.relY = self.win.winfo_y() - self.parent.winfo_y()
            self.save_conf()

    def follow_main(self, e: object = None) -> None:
        """When the main window moves, sub-windows should move with it."""
        self.allow_snap = False
        x, y = tk_tools.adjust_inside_screen(
            x=self.parent.winfo_x()+self.relX,
            y=self.parent.winfo_y()+self.relY,
            win=self.win,
        )
        self.win.geometry(f'+{x}+{y}')
        self.parent.focus()

    def save_conf(self) -> None:
        """Write configuration to the config file."""
        if self.can_save:
            config.APP.store_conf(WindowState(
                visible=self.visible.get(),
                x=self.relX,
                y=self.relY,
                width=self.win.winfo_width() if self.can_resize_x else -1,
                height=self.win.winfo_height() if self.can_resize_y else -1,
            ), self.win_name)

    async def load_conf(self) -> None:
        """Load configuration from our config file."""
        hide = False
        try:
            state = config.APP.get_cur_conf(WindowState, self.win_name, legacy_id=self.legacy_name)
        except KeyError:
            pass  # No configured state.
        else:
            width = state.width if self.can_resize_x and state.width > 0 else self.win.winfo_reqwidth()
            height = state.height if self.can_resize_y and state.height > 0 else self.win.winfo_reqheight()
            self.win.deiconify()
            await tk_tools.wait_eventloop()

            self.win.geometry(f'{width}x{height}')

            self.relX, self.relY = state.x, state.y

            self.follow_main()
            if not state.visible:
                hide = True

        # Only allow saving after the window has stabilised in its position.
        await trio.sleep(0.15)
        self.parent.bind('<Configure>', self.follow_main, add=True)
        self.can_save = True
        if hide:
            self.hide_win(False)
