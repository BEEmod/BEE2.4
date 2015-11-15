"""Backup and restore P2C maps.

"""
import tkinter as tk
from tkinter import ttk
from tk_tools import TK_ROOT

from datetime import datetime
import time
import os

from FakeZip import FakeZip, zip_names
from zipfile import ZipFile

from tooltip import add_tooltip
from property_parser import Property
from CheckDetails import CheckDetails, Item as CheckItem
import img
import utils
import tk_tools
import gameMan


window = None  # type: tk.Toplevel

UI = {}

menus = {}  # For standalone application, generate menu bars

HEADERS = ['Name', 'Mode', 'Date']

# The game subfolder where puzzles are located
PUZZLE_FOLDERS = {
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
    utils.STEAM_IDS['TWTM']: 'TWTM',
}

# The currently-loaded backup files.
BACKUPS = {
    'game': [],
    'back': [],
}


class P2C:
    """A PeTI map."""
    def __init__(self, path, zip_file):
        """Initialise the map.

        path is the file path for the map inside the zip, without extension.
        zip_file is either a ZipFile or FakeZip object.
        """
        with zip_file.open(path + '.p2c') as file:
            props = Property.parse(file, path)
        props = props.find_key('portal2_puzzle', [])

        self.path = path
        self.zip_file = zip_file
        self.title = props['title', None]
        if self.title is None:
            self.title = '<' + path.rsplit('/', 1)[-1] + '.p2c>'
        self.desc = props['description', '...']
        self.is_coop = utils.conv_bool(props['coop', '0'])
        self.create_time = Date(props['timestamp_created', ''])
        self.mod_time = Date(props['timestamp_modified', ''])

    def make_item(self):
        """Make a corresponding CheckItem object."""
        return CheckItem(
            self.title,
            ('Coop' if self.is_coop else 'SP'),
            self.mod_time,
            hover_text=self.desc
        )


class Date:
    """A version of datetime with an invalid value, and read from hex.
    """
    def __init__(self, hex_time):
        """Convert the time format in P2C files into a useable value."""
        try:
            val = int(hex_time, 16)
        except ValueError:
            self.date = None
        else:
            self.date = datetime.fromtimestamp(val)

    def __str__(self):
        """Return value for display."""
        if self.date is None:
            return '???'
        else:
            return time.strftime(
                '%d %b %Y, %I:%M%p',
                self.date.timetuple(),
            )

    # No date = always earlier
    def __lt__(self, other):
        if self.date is None:
            return True
        else:
            return self.date < other.date

    def __gt__(self, other):
        if self.date is None:
            return False
        else:
            return self.date > other.date

    def __le__(self, other):
        if self.date is None:
            return other.date is None
        else:
            return self.date <= other.date

    def __ge__(self, other):
        if self.date is None:
            return other.date is None
        else:
            return self.date >= other.date

    def __eq__(self, other):
        return self.date == other.date

    def __ne__(self, other):
        return self.date != other.date


# Note: All the backup functions use zip files, but also work on FakeZip
# directories.


def load_backup(zip_file):
    """Load in a backup file."""
    maps = []
    for file in zip_names(zip_file):
        if file.endswith('.p2c'):
            bare_file = file[:-4]
            maps.append(P2C(bare_file, zip_file))
    return maps


def load_game(game: gameMan.Game):
    """Callback for gameMan, load in files for a game."""
    puzzle_folder = PUZZLE_FOLDERS.get(str(game.steamID), 'portal2')
    path = game.abs_path(puzzle_folder + '/puzzles/')
    for folder in os.listdir(path):
        if not folder.isdigit():
            continue
        abs_path = os.path.join(path, folder)
        if os.path.isdir(abs_path):
            zip_file = FakeZip(abs_path)
            maps = load_backup(zip_file)
            BACKUPS['game'] = maps
            refresh_details()


def refresh_details():
    """Remake the items in the checkdetails list."""
    game = UI['game_details']
    game.remove_all()
    game.add_items(*(
        peti_map.make_item()
        for peti_map in
        BACKUPS['game']
    ))

    backup = UI['back_details']
    backup.remove_all()
    backup.add_items(*(
        peti_map.make_item()
        for peti_map in
        BACKUPS['back']
    ))


def show_window():
    window.deiconify()
    window.lift()
    utils.center_win(window, TK_ROOT)


def ui_load_backup():
    """Prompt and load in a backup file."""
    pass


def ui_refresh_game():
    """Reload the game maps list."""
    if gameMan.selected_game is not None:
        load_game(gameMan.selected_game)


def init():
    """Initialise all widgets in the given window."""
    for cat, btn_text in [
            ('back_', 'Restore:'),
            ('game_', 'Backup:'),
            ]:
        UI[cat + 'frame'] = frame = ttk.Frame(
            window,
        )
        UI[cat + 'title_frame'] = title_frame = ttk.Frame(
            frame,
        )
        title_frame.grid(row=0, column=0, sticky='EW')
        UI[cat + 'title'] = ttk.Label(
            title_frame,
        )
        UI[cat + 'title'].grid(row=0, column=0, sticky='EW')
        title_frame.rowconfigure(0, weight=1)
        title_frame.columnconfigure(0, weight=1)

        UI[cat + 'details'] = CheckDetails(
            frame,
            headers=HEADERS,
        )
        UI[cat + 'details'].grid(row=1, column=0, sticky='NSEW')
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        button_frame = ttk.Frame(
            frame,
        )
        button_frame.grid(column=0, row=2)
        ttk.Label(button_frame, text=btn_text).grid(row=0, column=0)
        UI[cat + 'btn_all'] = ttk.Button(
            button_frame,
            text='All',
            width=3,
        )
        UI[cat + 'btn_sel'] = ttk.Button(
            button_frame,
            text='Checked',
            width=8,
        )
        UI[cat + 'btn_all'].grid(row=0, column=1)
        UI[cat + 'btn_sel'].grid(row=0, column=2)

        UI[cat + 'btn_del'] = ttk.Button(
            button_frame,
            text='Delete Checked',
            width=14,
        )
        UI[cat + 'btn_del'].grid(row=1, column=0, columnspan=3)

        utils.add_mousewheel(
            UI[cat + 'details'].wid_canvas,
            UI[cat + 'frame'],
        )

    UI['game_refresh'] = ttk.Button(
        UI['game_title_frame'],
        image=img.png('icons/tool_sub'),
        command=ui_refresh_game,
    )
    UI['game_refresh'].grid(row=0, column=1, sticky='E')
    add_tooltip(
        UI['game_refresh'],
        "Reload the map list.",
    )

    UI['back_frame'].grid(row=1, column=0, sticky='NSEW')
    ttk.Separator(orient=tk.VERTICAL).grid(
        row=1, column=1, sticky='NS', padx=5,
    )
    UI['game_frame'].grid(row=1, column=2, sticky='NSEW')

    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)
    window.columnconfigure(2, weight=1)


def init_application():
    """Initialise the standalone application."""
    global window
    window = TK_ROOT
    init()

    UI['bar'] = bar = tk.Menu(TK_ROOT)
    window.option_add('*tearOff', False)

    gameMan.load()

    ui_refresh_game()

    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = menus['file'] = tk.Menu(bar, name='apple')
    else:
        file_menu = menus['file'] = tk.Menu(bar)
    file_menu.add_command(label='New Backup')
    file_menu.add_command(label='Open Backup')
    file_menu.add_command(label='Save Backup')
    file_menu.add_command(label='Save Backup As')

    bar.add_cascade(menu=file_menu, label='File')

    game_menu = menus['game'] = tk.Menu(bar)

    game_menu.add_command(label='Add Game', command=gameMan.add_game)
    game_menu.add_command(label='Remove Game', command=gameMan.remove_game)
    game_menu.add_separator()

    bar.add_cascade(menu=game_menu, label='Game')
    window['menu'] = bar

    gameMan.add_menu_opts(game_menu)
    gameMan.game_menu = game_menu


def init_backup_settings():
    """Initialise the auto-backup settings widget."""
    UI['auto_frame'] = frame = ttk.LabelFrame(
        window,
    )
    UI['auto_enable'] = enable_check = ttk.Checkbutton(
        frame,
        text='Automatic Backup After Export',
    )
    frame['labelwidget'] = enable_check
    frame.grid(row=2, column=0, columnspan=3)

    UI['auto_dir'] = tk_tools.ReadOnlyEntry(frame)

    UI['auto_dir'].grid(row=0, column=0)


def init_toplevel():
    """Initialise the window as part of the BEE2."""
    global window
    window = tk.Toplevel(TK_ROOT)
    window.transient(TK_ROOT)
    window.withdraw()

    # Don't destroy window when quit!
    window.protocol("WM_DELETE_WINDOW", window.withdraw)

    init()
    init_backup_settings()

    ui_refresh_game()


if __name__ == '__main__':
    # Run this standalone.
    init_application()

    TK_ROOT.deiconify()

    def fix_details():
        # It takes a while before the detail headers update positions,
        # so delay a refresh call.
        TK_ROOT.update_idletasks()
        UI['game_details'].refresh()
    TK_ROOT.after(500, fix_details)

    TK_ROOT.mainloop()
