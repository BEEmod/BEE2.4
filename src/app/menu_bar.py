"""The widgets for the main menu bar."""
import os
import tkinter as tk
from typing import Callable, Iterable, List, Tuple
from typing_extensions import Final
from pathlib import Path

import BEE2_config
import utils
from transtoken import TransToken
from app import (
    gameMan, helpMenu, localisation, optionWindow, packageMan, tk_tools,
    backup as backup_win, background_run,
)
from ui_tk.dialogs import DIALOG
from ui_tk.img import TKImages


EXPORT_BTN_POS: Final = 0  # Position of the export button.
FOLDER_OPTIONS: List[Tuple[TransToken, Callable[['gameMan.Game'], Iterable[Path]]]] = [
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
        tk_img: TKImages,
        quit_app: Callable[[], object],
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
            parent.createcommand('tk::mac::Quit', quit_app)

        if utils.MAC:
            # Name is used to make this the special 'BEE2' menu item
            self.file_menu = tk.Menu(bar, name='apple')
        else:
            self.file_menu = tk.Menu(bar, name='file')

        bar.add_cascade(menu=self.file_menu)
        localisation.set_menu_text(bar, TransToken.ui('File'))

        # Assign the bar as the main window's menu.
        # Must be done after creating the apple menu.
        parent['menu'] = bar

        self.file_menu.add_command(command=export, accelerator=tk_tools.ACCEL_EXPORT)
        localisation.set_menu_text(self.file_menu, TransToken.ui('Export'))
        self.export_btn_pos = self.file_menu.index('end')
        self.file_menu.entryconfigure(self.export_btn_pos, state='disabled')

        self.file_menu.add_command(command=lambda: background_run(gameMan.add_game, DIALOG))
        localisation.set_menu_text(self.file_menu, TransToken.ui("Add Game"))

        self.file_menu.add_command(command=lambda: background_run(gameMan.remove_game, DIALOG))
        localisation.set_menu_text(self.file_menu, TransToken.ui("Uninstall from Selected Game"))

        self.file_menu.add_command(command=backup_win.show_window)
        localisation.set_menu_text(self.file_menu, TransToken.ui("Backup/Restore Puzzles..."))

        self.folder_menu = tk.Menu(bar, name='folders')
        self.file_menu.add_cascade(menu=self.folder_menu)
        localisation.set_menu_text(self.file_menu, TransToken.ui("Open Folder..."))

        for label, path_getter in FOLDER_OPTIONS:
            self.folder_menu.add_command(command=self._evt_open_dir(path_getter))
            localisation.set_menu_text(self.folder_menu, label)

        self.file_menu.add_separator()

        self.file_menu.add_command(command=packageMan.show,)
        localisation.set_menu_text(self.file_menu, TransToken.ui("Manage Packages..."))

        self.file_menu.add_command(command=optionWindow.show)
        localisation.set_menu_text(self.file_menu, TransToken.ui("Options"))

        if not utils.MAC:
            self.file_menu.add_command(command=quit_app)
            localisation.set_menu_text(self.file_menu, TransToken.ui("Quit"))

        self.file_menu.add_separator()

        # Add a set of options to pick the game into the menu system
        gameMan.add_menu_opts(self.file_menu)
        gameMan.game_menu = self.file_menu

        self.pal_menu = tk.Menu(bar, name='palette')
        bar.add_cascade(menu=self.pal_menu)
        localisation.set_menu_text(bar, TransToken.ui("Palette"))

        self.view_menu = tk.Menu(bar, name='view')
        bar.add_cascade(menu=self.view_menu)
        localisation.set_menu_text(bar, TransToken.ui("View"))

        helpMenu.make_help_menu(bar, tk_img)
        gameMan.ON_GAME_CHANGED.register(self._game_changed)

        if utils.CODE_DEV_MODE:
            self.dev_menu = tk.Menu(parent)  # Don't bother translating.
            bar.add_cascade(menu=self.dev_menu, label='Dev')

            from ui_tk import devmenu
            devmenu.make_menu(self.dev_menu)

    def set_export_allowed(self, allowed: bool) -> None:
        """Configure if exporting is allowed from the UI."""
        self._can_export = allowed
        self.file_menu.entryconfigure(self.export_btn_pos, state='normal' if allowed else 'disabled')

    def _evt_open_dir(self, path_getter: Callable[['gameMan.Game'], Iterable[Path]]) -> Callable[[], None]:
        """Get an event function which opens the specified folder."""
        def handler() -> None:
            """When called opens the path."""
            paths = path_getter(gameMan.selected_game)
            if utils.WIN:
                for path in paths:
                    os.startfile(path)
            # TODO: Other OSes.
        return handler

    async def _game_changed(self, game: 'gameMan.Game') -> None:
        """Callback for when games are changed."""
        localisation.set_menu_text(self.file_menu, game.get_export_text(), self.export_btn_pos)
        for i, (label, path_getter) in enumerate(FOLDER_OPTIONS):
            localisation.set_menu_text(self.folder_menu, label.format(game=game.name), i)
