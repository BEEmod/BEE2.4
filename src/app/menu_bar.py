"""The widgets for the main menu bar."""
from typing import Final

import tkinter as tk

from collections.abc import Callable, Iterable
from contextlib import aclosing
from pathlib import Path
import os

import trio
import trio_util

import BEE2_config
import utils
from transtoken import TransToken
from app import (
    gameMan, optionWindow, packageMan, backup as backup_win, background_run, quit_app,
)
from ui_tk import tk_tools, help_menu
from ui_tk.dialogs import DIALOG
from ui_tk.img import TKImages
from ui_tk.wid_transtoken import set_menu_text


EXPORT_BTN_POS: Final = 0  # Position of the export button.
FOLDER_OPTIONS: list[tuple[TransToken, Callable[['gameMan.Game'], Iterable[Path]]]] = [
    (TransToken.ui('{game} Puzzle Folder'), lambda game: [Path(game.abs_path('portal2/puzzles/'))]),
    (TransToken.ui('{game} Folder'), lambda game: [Path(game.abs_path('.'))]),
    (TransToken.ui('Palettes Folder'), lambda game: [utils.conf_location('palettes')]),
    (TransToken.ui('Packages Folder'), lambda game: BEE2_config.get_package_locs()),
]


class MenuBar:
    """The main window's menu bar."""
    def __init__(
        self,
        parent: tk.Tk,
        export: Callable[[], object],
    ) -> None:
        """Create the top menu bar.

        This returns the View and palette menus, for later population.
        """
        self._can_export = False
        self.export_func = export
        self.bar = bar = tk.Menu(parent, name='main_menu')
        # Suppress ability to make each menu a separate window - weird old
        # TK behaviour
        parent.option_add('*tearOff', '0')
        if utils.MAC:
            # OS X has a special quit menu item.
            parent.createcommand('tk::mac::Quit', quit_app)  # type: ignore[no-untyped-call]

        if utils.MAC:
            # Name is used to make this the special 'BEE2' menu item
            self.file_menu = tk.Menu(bar, name='apple')
        else:
            self.file_menu = tk.Menu(bar, name='file')

        bar.add_cascade(menu=self.file_menu)
        set_menu_text(bar, TransToken.ui('File'))

        # Assign the bar as the main window's menu.
        # Must be done after creating the apple menu.
        parent['menu'] = bar

        self.file_menu.add_command(command=export, accelerator=tk_tools.ACCEL_EXPORT)
        set_menu_text(self.file_menu, TransToken.ui('Export'))
        self.export_btn_pos = utils.not_none(self.file_menu.index('end'))
        self.file_menu.entryconfigure(self.export_btn_pos, state='disabled')

        self.file_menu.add_command(command=lambda: background_run(gameMan.add_game, DIALOG))
        set_menu_text(self.file_menu, TransToken.ui("Add Game"))

        self.file_menu.add_command(command=lambda: background_run(gameMan.remove_game, DIALOG))
        set_menu_text(self.file_menu, TransToken.ui("Uninstall from Selected Game"))

        self.file_menu.add_command(command=backup_win.show_window)
        set_menu_text(self.file_menu, TransToken.ui("Backup/Restore Puzzles..."))

        self.folder_menu = tk.Menu(bar, name='folders')
        self.file_menu.add_cascade(menu=self.folder_menu)
        set_menu_text(self.file_menu, TransToken.ui("Open Folder..."))

        for label, path_getter in FOLDER_OPTIONS:
            self.folder_menu.add_command(command=self._evt_open_dir(path_getter))
            set_menu_text(self.folder_menu, label)

        self.file_menu.add_separator()

        self.file_menu.add_command(command=packageMan.show,)
        set_menu_text(self.file_menu, TransToken.ui("Manage Packages..."))

        self.file_menu.add_command(command=optionWindow.show)
        set_menu_text(self.file_menu, TransToken.ui("Options"))

        if not utils.MAC:
            self.file_menu.add_command(command=quit_app)
            set_menu_text(self.file_menu, TransToken.ui("Quit"))

        self.file_menu.add_separator()

        # Add a set of options to pick the game into the menu system
        gameMan.add_menu_opts(self.file_menu)
        gameMan.game_menu = self.file_menu

        self.pal_menu = tk.Menu(bar, name='palette')
        bar.add_cascade(menu=self.pal_menu)
        set_menu_text(bar, TransToken.ui("Palette"))

        self.view_menu = tk.Menu(bar, name='view')
        bar.add_cascade(menu=self.view_menu)
        set_menu_text(bar, TransToken.ui("View"))

        # Using this name displays this correctly in OS X
        self.help_menu = tk.Menu(parent, name='help')

        bar.add_cascade(menu=self.help_menu)
        set_menu_text(bar, TransToken.ui("Help"))

        if utils.CODE_DEV_MODE:
            self.dev_menu: tk.Menu | None = tk.Menu(parent)
            # Don't bother translating.
            bar.add_cascade(menu=self.dev_menu, label='Dev')
        else:
            self.dev_menu = None

    def set_export_allowed(self, allowed: bool) -> None:
        """Configure if exporting is allowed from the UI."""
        self._can_export = allowed
        self.file_menu.entryconfigure(self.export_btn_pos, state='normal' if allowed else 'disabled')

    async def task(self, tk_img: TKImages) -> None:
        """Operate the menu bar."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(help_menu.create, self.help_menu, tk_img)
            nursery.start_soon(self._update_export_btn_task)
            nursery.start_soon(self._update_folder_btns_task)
            if self.dev_menu is not None:
                from ui_tk import devmenu
                nursery.start_soon(devmenu.menu_task, self.dev_menu)

    async def _update_export_btn_task(self) -> None:
        """Update the export button."""
        async with aclosing(gameMan.EXPORT_BTN_TEXT.eventual_values()) as agen:
            async for name in agen:
                set_menu_text(self.file_menu, name, self.export_btn_pos)

    async def _update_folder_btns_task(self) -> None:
        """Update folder buttons to show the current game."""
        async with aclosing(gameMan.selected_game.eventual_values()) as agen:
            async for game in agen:
                name = game.name if game is not None else '???'

                for i, (label, path_getter) in enumerate(FOLDER_OPTIONS):
                    set_menu_text(self.folder_menu, label.format(game=name), i)

    def _evt_open_dir(self, path_getter: Callable[['gameMan.Game'], Iterable[Path]]) -> Callable[[], None]:
        """Get an event function which opens the specified folder."""
        def handler() -> None:
            """When called opens the path."""
            game = gameMan.selected_game.value
            if game is None:
                return
            paths = path_getter(game)
            if utils.WIN:
                for path in paths:
                    os.startfile(path)
            # TODO: Other OSes.
        return handler
