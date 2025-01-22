"""Implements a sub-window which follows the main, saves state and can be hidden/shown."""
from contextlib import aclosing
import abc

from srctools.logger import get_logger
from trio_util import AsyncBool
import attrs
import trio

from app import sound
from config.windows import WindowState
from transtoken import TransToken
from ui_tk import tk_tools
import config

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


class SubPaneBase:
    """A sub-window that can be shown/hidden.

     This follows the main window when moved.
    """
    def __init__(self, conf: PaneConf) -> None:
        self.visible = AsyncBool(True)
        self.win_name = conf.name
        self.legacy_name = conf.legacy_name
        self.allow_snap = False
        self.can_save = False
        self._rel_x = 0
        self._rel_y = 0
        self.can_resize_x = conf.resize_x
        self.can_resize_y = conf.resize_y

    async def task(self) -> None:
        """Show/hide the window when the value changes."""
        async with aclosing(self.visible.eventual_values()) as agen:
            async for visible in agen:
                if visible:
                    self._ui_show()
                    self.follow_main()
                else:
                    self._ui_hide()
                self.save_conf()

    def _toggle_win(self) -> None:
        """Toggle the window between shown and hidden."""
        sound.fx('config')
        self.visible.value = not self.visible.value

    def evt_window_closed(self, _: object = None, /) -> None:
        """Window was closed, update."""
        sound.fx('config')
        self.visible.value = False

    def evt_window_focused(self, _: object = None, /) -> None:
        """Allow the window to snap."""
        self.allow_snap = True

    def evt_window_moved(self, _: object = None, /) -> None:
        """Callback for window movement.

        This allows it to snap to the edge of the main window.
        """
        # TODO: Actually snap to edges of main window
        if self.allow_snap:
            self._rel_x, self._rel_y = self._ui_get_pos()
            self.save_conf()

    def follow_main(self, _: object = None) -> None:
        """When the main window moves, sub-windows should move with it."""
        self.allow_snap = False
        self._ui_apply_relative()

    def save_conf(self) -> None:
        """Write configuration to the config file."""
        if self.can_save:
            width, height = self._ui_get_size()
            config.APP.store_conf(WindowState(
                visible=self.visible.value,
                x=self._rel_x,
                y=self._rel_y,
                width=width if self.can_resize_x else -1,
                height=height if self.can_resize_y else -1,
            ), self.win_name)

    async def load_conf(self) -> None:
        """Load configuration from our config file."""
        hide = False
        try:
            state = config.APP.get_cur_conf(WindowState, self.win_name, legacy_id=self.legacy_name)
        except KeyError:
            pass  # No configured state.
        else:
            width = state.width if self.can_resize_x and state.width > 0 else None
            height = state.height if self.can_resize_y and state.height > 0 else None
            self._ui_show()
            await tk_tools.wait_eventloop()

            self._ui_set_size(width, height)

            self._rel_x, self._rel_y = state.x, state.y

            self.follow_main()
            self._ui_bind_parent()
            if not state.visible:
                hide = True

        # Only allow saving after the window has stabilised in its position.
        await trio.sleep(0.15)
        self.can_save = True
        if hide:
            self.evt_window_hidden(False)

    @abc.abstractmethod
    def _ui_show(self) -> None:
        """Show the window, and press in the button."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_hide(self) -> None:
        """Hide the window, and unpress the button."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_get_pos(self) -> tuple[int, int]:
        """Return the window's position relative to the parent."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_apply_relative(self) -> None:
        """Apply rel_x/rel_y."""
        raise NotImplementedError

    def _ui_get_size(self) -> tuple[int, int]:
        """Get the size of the window."""
        raise NotImplementedError

    def _ui_set_size(self, width: int | None, height: int | None) -> None:
        """Set the size of the window, or None to leave unchanged."""
        raise NotImplementedError

    def _ui_bind_parent(self) -> None:
        """Bind follow-main on the parent."""
        raise NotImplementedError
