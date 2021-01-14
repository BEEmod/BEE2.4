"""Backup and restore P2C maps.

"""
import atexit
import os
import shutil
import string
import time
from datetime import datetime
from io import BytesIO, TextIOWrapper
from typing import List, TYPE_CHECKING, Dict, Any
from zipfile import ZipFile, ZIP_LZMA

import loadScreen
import srctools.logger
from app import tk_tools, img, TK_ROOT
import tkinter as tk
import utils
from app.CheckDetails import CheckDetails, Item as CheckItem
from FakeZip import FakeZip, zip_names, zip_open_bin
from srctools import Property, KeyValError
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
from app.tooltip import add_tooltip
if TYPE_CHECKING:
    from app import gameMan

LOGGER = srctools.logger.get_logger(__name__)

# The backup window - either a toplevel, or TK_ROOT.
window: tk.Toplevel

UI = {}  # Holds all the widgets

menus = {}  # For standalone application, generate menu bars

# Stage name for the exporting screen
AUTO_BACKUP_STAGE = 'BACKUP_ZIP'

# Characters allowed in the backup filename
BACKUP_CHARS = set(string.ascii_letters + string.digits + '_-.')
# Format for the backup filename
AUTO_BACKUP_FILE = 'back_{game}{ind}.zip'

HEADERS = ['Name', 'Mode', 'Date']

# The game subfolder where puzzles are located
PUZZLE_FOLDERS = {
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
    utils.STEAM_IDS['TWTM']: 'TWTM',
}

# The currently-loaded backup files.
BACKUPS: Dict[str, Any] = {
    'game': [],
    'back': [],

    # The path for the game folder
    'game_path': None,

    # The name of the current backup file
    'backup_path': None,

    # The backup zip file
    'backup_zip': None,
    # The currently-open file
    'unsaved_file': None,
}

# Variables associated with the heading text.
backup_name = tk.StringVar()
game_name = tk.StringVar()

# Loadscreens used as basic progress bars
copy_loader = loadScreen.LoadScreen(
    ('COPY', ''),
    title_text=_('Copying maps'),
)

reading_loader = loadScreen.LoadScreen(
    ('READ', ''),
    title_text=_('Loading maps'),
)

deleting_loader = loadScreen.LoadScreen(
    ('DELETE', ''),
    title_text=_('Deleting maps'),
)


class P2C:
    """A PeTI map."""
    def __init__(
            self,
            filename,
            zip_file,
            create_time,
            mod_time,
            title='<untitled>',
            desc='',
            is_coop=False,
            ):
        self.filename = filename
        self.zip_file = zip_file
        self.create_time = create_time
        self.mod_time = mod_time
        self.title = title
        self.desc = desc
        self.is_coop = is_coop

    @classmethod
    def from_file(cls, path, zip_file):
        """Initialise from a file.

        path is the file path for the map inside the zip, without extension.
        zip_file is either a ZipFile or FakeZip object.
        """
        # Some P2Cs may have non-ASCII characters in descriptions, so we
        # need to read it as bytes and convert to utf-8 ourselves - zips
        # don't convert encodings automatically for us.
        try:
            with zip_open_bin(zip_file, path + '.p2c') as file:
                # Decode the P2C as UTF-8, and skip unknown characters.
                # We're only using it for display purposes, so that should
                # be sufficient.
                with TextIOWrapper(
                    file,
                    encoding='utf-8',
                    errors='replace',
                ) as textfile:
                    props = Property.parse(textfile, path)
        except KeyValError:
            # Silently fail if we can't parse the file. That way it's still
            # possible to backup.
            LOGGER.warning('Failed parsing puzzle file!', path, exc_info=True)
            props = Property('portal2_puzzle', [])
            title = None
            desc = _('Failed to parse this puzzle file. It can still be backed up.')
        else:
            props = props.find_key('portal2_puzzle', [])
            title = props['title', None]
            desc = props['description', _('No description found.')]

        if title is None:
            title = '<' + path.rsplit('/', 1)[-1] + '.p2c>'

        return cls(
            filename=os.path.basename(path),
            zip_file=zip_file,
            title=title,
            desc=desc,
            is_coop=srctools.conv_bool(props['coop', '0']),
            create_time=Date(props['timestamp_created', '']),
            mod_time=Date(props['timestamp_modified', '']),
        )

    def copy(self):
        """Copy this item."""
        return self.__class__(
            self.filename,
            create_time=self.create_time,
            zip_file=self.zip_file,
            mod_time=self.mod_time,
            is_coop=self.is_coop,
            desc=self.desc,
            title=self.title,
        )

    def make_item(self):
        """Make a corresponding CheckItem object."""
        chk = CheckItem(
            self.title,
            (_('Coop') if self.is_coop else _('SP')),
            self.mod_time,
            hover_text=self.desc
        )
        chk.p2c = self
        return chk


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
        elif other.date is None:
            return False
        else:
            return self.date < other.date

    def __gt__(self, other):
        if self.date is None:
            return False
        elif other.date is None:
            return True
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
    puzzles = [
        file[:-4]  # Strip extension
        for file in
        zip_names(zip_file)
        if file.endswith('.p2c')
    ]
    # Each P2C init requires reading in the properties file, so this may take
    # some time. Use a loading screen.
    reading_loader.set_length('READ', len(puzzles))
    LOGGER.info('Loading {} maps..', len(puzzles))
    with reading_loader:
        for file in puzzles:
            new_map = P2C.from_file(file, zip_file)
            maps.append(new_map)
            LOGGER.debug(
                'Loading {} map "{}"',
                'coop' if new_map.is_coop else 'sp',
                new_map.title,
            )
            reading_loader.step('READ')
    LOGGER.info('Done!')

    # It takes a while before the detail headers update positions,
    # so delay a refresh call.
    TK_ROOT.after(500, UI['game_details'].refresh)

    return maps


def load_game(game: 'gameMan.Game'):
    """Callback for gameMan, load in files for a game."""
    game_name.set(game.name)

    puzz_path = find_puzzles(game)
    if puzz_path:
        zip_file = FakeZip(puzz_path)
        try:
            BACKUPS['game'] = load_backup(zip_file)
        except loadScreen.Cancelled:
            return

        BACKUPS['game_path'] = puzz_path
        BACKUPS['game_zip'] = zip_file
        refresh_game_details()


def find_puzzles(game: 'gameMan.Game'):
    """Find the path for the p2c files."""
    # The puzzles are located in:
    # <game_folder>/portal2/puzzles/<steam_id>
    # 'portal2' changes with different games.

    puzzle_folder = PUZZLE_FOLDERS.get(str(game.steamID), 'portal2')
    path = game.abs_path(puzzle_folder + '/puzzles/')

    for folder in os.listdir(path):
        # The steam ID is all digits, so look for a folder with only digits
        # in the name
        if not folder.isdigit():
            continue
        abs_path = os.path.join(path, folder)
        if os.path.isdir(abs_path):
            return abs_path
    return None


def backup_maps(maps):
    """Copy the given maps to the backup."""
    back_zip = BACKUPS['backup_zip']  # type: ZipFile

    # Allow removing old maps when we overwrite objects
    map_dict = {
        p2c.filename: p2c
        for p2c in
        BACKUPS['back']
    }

    # You can't remove files from a zip, so we need to create a new one!
    # Here we'll just add entries into BACKUPS['back'].
    # Also check for overwriting
    for p2c in maps:
        scr_path = p2c.filename + '.jpg'
        map_path = p2c.filename + '.p2c'
        if (
                map_path in zip_names(back_zip) or
                scr_path in zip_names(back_zip)
                ):
            if not messagebox.askyesno(
                    title='Overwrite File?',
                    message=_('This filename is already in the backup.'
                              'Do you wish to overwrite it? '
                              '({})').format(p2c.title),
                    parent=window,
                    icon=messagebox.QUESTION,
                    ):
                continue
        new_item = p2c.copy()
        map_dict[p2c.filename] = new_item

    BACKUPS['back'] = list(map_dict.values())
    refresh_back_details()


def auto_backup(game: 'gameMan.Game', loader: loadScreen.LoadScreen):
    """Perform an automatic backup for the given game.

    We do this seperately since we don't need to read the property files.
    """
    from BEE2_config import GEN_OPTS
    if not GEN_OPTS.get_bool('General', 'enable_auto_backup'):
        # Don't backup!
        loader.skip_stage(AUTO_BACKUP_STAGE)
        return

    folder = find_puzzles(game)
    if not folder:
        loader.skip_stage(AUTO_BACKUP_STAGE)
        return

    # Keep this many previous
    extra_back_count = GEN_OPTS.get_int('General', 'auto_backup_count', 0)

    to_backup = os.listdir(folder)
    backup_dir = GEN_OPTS.get_val('Directories', 'backup_loc', 'backups/')

    os.makedirs(backup_dir, exist_ok=True)

    # A version of the name stripped of special characters
    # Allowed: a-z, A-Z, 0-9, '_-.'
    safe_name = srctools.whitelist(
        game.name,
        valid_chars=BACKUP_CHARS,
    )

    loader.set_length(AUTO_BACKUP_STAGE, len(to_backup))

    if extra_back_count:
        back_files = [
            AUTO_BACKUP_FILE.format(game=safe_name, ind='')
        ] + [
            AUTO_BACKUP_FILE.format(game=safe_name, ind='_'+str(i+1))
            for i in range(extra_back_count)
        ]
        # Move each file over by 1 index, ignoring missing ones
        # We need to reverse to ensure we don't overwrite any zips
        for old_name, new_name in reversed(
                list(zip(back_files, back_files[1:]))
                ):
            LOGGER.info(
                'Moving: {old} -> {new}',
                old=old_name,
                new=new_name,
            )
            old_name = os.path.join(backup_dir, old_name)
            new_name = os.path.join(backup_dir, new_name)
            try:
                os.remove(new_name)
            except FileNotFoundError:
                pass  # We're overwriting this anyway
            try:
                os.rename(old_name, new_name)
            except FileNotFoundError:
                pass

    final_backup = os.path.join(
        backup_dir,
        AUTO_BACKUP_FILE.format(game=safe_name, ind=''),
    )
    LOGGER.info('Writing backup to "{}"', final_backup)
    with open(final_backup, 'wb') as f:
        with ZipFile(f, mode='w', compression=ZIP_LZMA) as zip_file:
            for file in to_backup:
                zip_file.write(
                    os.path.join(folder, file),
                    file,
                    ZIP_LZMA,
                )
                loader.step(AUTO_BACKUP_STAGE)


def save_backup():
    """Save the backup file."""
    # We generate it from scratch, since that's the only way to remove
    # files.
    new_zip_data = BytesIO()
    new_zip = ZipFile(new_zip_data, 'w', compression=ZIP_LZMA)

    maps = [
        item.p2c
        for item in
        UI['back_details'].items
    ]

    if not maps:
        messagebox.showerror(
            _('BEE2 Backup'),
            _('No maps were chosen to backup!'),
        )
        return

    copy_loader.set_length('COPY', len(maps))

    with copy_loader:
        for p2c in maps:  # type: P2C
            old_zip = p2c.zip_file
            map_path = p2c.filename + '.p2c'
            scr_path = p2c.filename + '.jpg'
            if scr_path in zip_names(old_zip):
                with zip_open_bin(old_zip, scr_path) as f:
                    new_zip.writestr(scr_path, f.read())

            # Copy the map as bytes, so encoded characters are transfered
            # unaltered.
            with zip_open_bin(old_zip, map_path) as f:
                new_zip.writestr(map_path, f.read())
            copy_loader.step('COPY')

    new_zip.close()  # Finalize zip

    with open(BACKUPS['backup_path'], 'wb') as backup:
        backup.write(new_zip_data.getvalue())
    BACKUPS['unsaved_file'] = new_zip_data

    # Remake the zipfile object, so it's open again.
    BACKUPS['backup_zip'] = new_zip = ZipFile(
        new_zip_data,
        mode='w',
        compression=ZIP_LZMA,
    )

    # Update the items, so they use this zip now.
    for p2c in maps:
        p2c.zip_file = new_zip


def restore_maps(maps: List[P2C]):
    """Copy the given maps to the game."""
    game_dir = BACKUPS['game_path']
    if game_dir is None:
        LOGGER.warning('No game selected to restore from?')
        return

    copy_loader.set_length('COPY', len(maps))
    with copy_loader:
        for p2c in maps:
            back_zip = p2c.zip_file
            scr_path = p2c.filename + '.jpg'
            map_path = p2c.filename + '.p2c'
            abs_scr = os.path.join(game_dir, scr_path)
            abs_map = os.path.join(game_dir, map_path)
            if (
                    os.path.isfile(abs_scr) or
                    os.path.isfile(abs_map)
                    ):
                if not messagebox.askyesno(
                        title='Overwrite File?',
                        message=_('This map is already in the game directory.'
                                  'Do you wish to overwrite it? '
                                  '({})').format(p2c.title),
                        parent=window,
                        icon=messagebox.QUESTION,
                        ):
                    copy_loader.step('COPY')
                    continue

            if scr_path in zip_names(back_zip):
                    with zip_open_bin(back_zip, scr_path) as src:
                        with open(abs_scr, 'wb') as dest:
                            shutil.copyfileobj(src, dest)

            with zip_open_bin(back_zip, map_path) as src:
                with open(abs_map, 'wb') as dest:
                    shutil.copyfileobj(src, dest)

            new_item = p2c.copy()
            new_item.zip_file = FakeZip(game_dir)
            BACKUPS['game'].append(new_item)
            copy_loader.step('COPY')

    refresh_game_details()


def refresh_game_details():
    """Remake the items in the game maps list."""
    game = UI['game_details']
    game.remove_all()
    game.add_items(*(
        peti_map.make_item()
        for peti_map in
        BACKUPS['game']
    ))


def refresh_back_details():
    """Remake the items in the backup list."""
    backup = UI['back_details']
    backup.remove_all()
    backup.add_items(*(
        peti_map.make_item()
        for peti_map in
        BACKUPS['back']
    ))


def show_window() -> None:
    window.deiconify()
    window.lift()
    utils.center_win(window, TK_ROOT)
    # Load our game data!
    ui_refresh_game()
    window.update()
    UI['game_details'].refresh()
    UI['back_details'].refresh()


def ui_load_backup() -> None:
    """Prompt and load in a backup file."""
    file = filedialog.askopenfilename(
        title=_('Load Backup'),
        filetypes=[(_('Backup zip'), '.zip')],
    )
    if not file:
        return

    BACKUPS['backup_path'] = file
    with open(file, 'rb') as f:
        # Read the backup zip into memory!
        data = f.read()
        BACKUPS['unsaved_file'] = unsaved = BytesIO(data)

    zip_file = ZipFile(
        unsaved,
        mode='a',
        compression=ZIP_LZMA,
    )
    try:
        BACKUPS['back'] = load_backup(zip_file)
        BACKUPS['backup_zip'] = zip_file

        BACKUPS['backup_name'] = os.path.basename(file)
        backup_name.set(BACKUPS['backup_name'])

        refresh_back_details()
    except loadScreen.Cancelled:
        zip_file.close()


def ui_new_backup() -> None:
    """Create a new backup file."""
    BACKUPS['back'].clear()
    BACKUPS['backup_name'] = None
    BACKUPS['backup_path'] = None
    backup_name.set(_('Unsaved Backup'))
    BACKUPS['unsaved_file'] = unsaved = BytesIO()
    BACKUPS['backup_zip'] = ZipFile(
        unsaved,
        mode='w',
        compression=ZIP_LZMA,
    )


def ui_save_backup() -> None:
    """Save a backup."""
    if BACKUPS['backup_path'] is None:
        # No backup path, prompt first
        ui_save_backup_as()
        return

    try:
        save_backup()
    except loadScreen.Cancelled:
        pass


def ui_save_backup_as() -> None:
    """Prompt for a name, and then save a backup."""
    path = filedialog.asksaveasfilename(
        title=_('Save Backup As'),
        filetypes=[(_('Backup zip'), '.zip')],
    )
    if not path:
        return
    if not path.endswith('.zip'):
        path += '.zip'

    BACKUPS['backup_path'] = path
    BACKUPS['backup_name'] = os.path.basename(path)
    backup_name.set(BACKUPS['backup_name'])
    ui_save_backup()


def ui_refresh_game() -> None:
    """Reload the game maps list."""
    if gameMan.selected_game is not None:
        load_game(gameMan.selected_game)


def ui_backup_sel() -> None:
    """Backup selected maps."""
    backup_maps([
        item.p2c
        for item in
        UI['game_details'].items
        if item.state
    ])


def ui_backup_all() -> None:
    """Backup all maps."""
    backup_maps([
        item.p2c
        for item in
        UI['game_details'].items
    ])


def ui_restore_sel() -> None:
    """Restore selected maps."""
    restore_maps([
        item.p2c
        for item in
        UI['back_details'].items
        if item.state
    ])


def ui_restore_all() -> None:
    """Backup all maps."""
    restore_maps([
        item.p2c
        for item in
        UI['back_details'].items
    ])


def ui_delete_backup() -> None:
    """Delete the selected items in the backup."""
    BACKUPS['back'] = [
        item.p2c
        for item in
        UI['back_details'].items
        if not item.state
    ]

    refresh_back_details()


def ui_delete_game() -> None:
    """Delete selected items in the game list."""
    game_dir = BACKUPS['game_path']
    if game_dir is None:
        LOGGER.warning('No game selected to delete from?')
        return

    game_detail = UI['game_details']  # type: CheckDetails

    to_delete = [
        item.p2c
        for item in
        game_detail.items
        if item.state
    ]
    to_keep = [
        item.p2c
        for item in
        game_detail.items
        if not item.state
    ]

    if not to_delete:
        return
    map_count = len(to_delete)
    if not messagebox.askyesno(
        _('Confirm Deletion'),
        ngettext(
            'Do you wish to delete {} map?\n',
            'Do you wish to delete {} maps?\n',
            map_count,
        ).format(map_count) + '\n'.join([
            '{} ({})'.format(map.title, map.filename)
            for map in to_delete
        ])
    ):
        return

    deleting_loader.set_length('DELETE', len(to_delete))
    try:
        with deleting_loader:
            for p2c in to_delete:  # type: P2C
                scr_path = p2c.filename + '.jpg'
                map_path = p2c.filename + '.p2c'
                abs_scr = os.path.join(game_dir, scr_path)
                abs_map = os.path.join(game_dir, map_path)
                try:
                    os.remove(abs_scr)
                except FileNotFoundError:
                    LOGGER.info('{} not present!', abs_scr)
                try:
                    os.remove(abs_map)
                except FileNotFoundError:
                    LOGGER.info('{} not present!', abs_map)

        BACKUPS['game'] = to_keep
    except loadScreen.Cancelled:
        pass
    refresh_game_details()


def init() -> None:
    """Initialise all widgets in the given window."""
    for cat, btn_text in [
            ('back_', _('Restore:')),
            ('game_', _('Backup:')),
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
            font='TkHeadingFont',
        )
        UI[cat + 'title'].grid(row=0, column=0)
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
            text=_('Checked'),
            width=8,
        )
        UI[cat + 'btn_all'].grid(row=0, column=1)
        UI[cat + 'btn_sel'].grid(row=0, column=2)

        UI[cat + 'btn_del'] = ttk.Button(
            button_frame,
            text=_('Delete Checked'),
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

    UI['game_title']['textvariable'] = game_name
    UI['back_title']['textvariable'] = backup_name

    UI['game_btn_all']['command'] = ui_backup_all
    UI['game_btn_sel']['command'] = ui_backup_sel
    UI['game_btn_del']['command'] = ui_delete_game

    UI['back_btn_all']['command'] = ui_restore_all
    UI['back_btn_sel']['command'] = ui_restore_sel
    UI['back_btn_del']['command'] = ui_delete_backup


    UI['back_frame'].grid(row=1, column=0, sticky='NSEW')
    ttk.Separator(orient=tk.VERTICAL).grid(
        row=1, column=1, sticky='NS', padx=5,
    )
    UI['game_frame'].grid(row=1, column=2, sticky='NSEW')

    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)
    window.columnconfigure(2, weight=1)


def init_application() -> None:
    """Initialise the standalone application."""
    global window
    window = TK_ROOT
    TK_ROOT.title(
        _('BEEMOD {} - Backup / Restore Puzzles').format(utils.BEE_VERSION)
    )

    init()

    UI['bar'] = bar = tk.Menu(TK_ROOT)
    window.option_add('*tearOff', False)

    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = menus['file'] = tk.Menu(bar, name='apple')
    else:
        file_menu = menus['file'] = tk.Menu(bar)
    file_menu.add_command(label=_('New Backup'), command=ui_new_backup)
    file_menu.add_command(label=_('Open Backup'), command=ui_load_backup)
    file_menu.add_command(label=_('Save Backup'), command=ui_save_backup)
    file_menu.add_command(label=_('Save Backup As'), command=ui_save_backup_as)

    bar.add_cascade(menu=file_menu, label=_('File'))

    game_menu = menus['game'] = tk.Menu(bar)

    game_menu.add_command(label=_('Add Game'), command=gameMan.add_game)
    game_menu.add_command(label=_('Remove Game'), command=gameMan.remove_game)
    game_menu.add_separator()

    bar.add_cascade(menu=game_menu, label=_('Game'))
    gameMan.game_menu = game_menu

    from app import helpMenu
    # Add the 'Help' menu here too.
    helpMenu.make_help_menu(bar)

    window['menu'] = bar

    window.deiconify()
    window.update()

    gameMan.load()
    ui_new_backup()

    # UI.py isn't present, so we use this callback
    gameMan.setgame_callback = load_game

    gameMan.add_menu_opts(game_menu)


def init_backup_settings() -> None:
    """Initialise the auto-backup settings widget."""
    from BEE2_config import GEN_OPTS
    check_var = tk.IntVar(
        value=GEN_OPTS.get_bool('General', 'enable_auto_backup')
    )
    count_value = GEN_OPTS.get_int('General', 'auto_backup_count', 0)
    back_dir = GEN_OPTS.get_val('Directories', 'backup_loc', 'backups/')

    def check_callback():
        GEN_OPTS['General']['enable_auto_backup'] = srctools.bool_as_int(
            check_var.get()
        )

    def count_callback():
        GEN_OPTS['General']['auto_backup_count'] = str(count.value)

    def directory_callback(path):
        GEN_OPTS['Directories']['backup_loc'] = path

    UI['auto_frame'] = frame = ttk.LabelFrame(
        window,
    )
    UI['auto_enable'] = enable_check = ttk.Checkbutton(
        frame,
        text=_('Automatic Backup After Export'),
        variable=check_var,
        command=check_callback,
    )

    frame['labelwidget'] = enable_check
    frame.grid(row=2, column=0, columnspan=3)

    dir_frame = ttk.Frame(
        frame,
    )
    dir_frame.grid(row=0, column=0)

    ttk.Label(
        dir_frame,
        text='Directory',
    ).grid(row=0, column=0)

    UI['auto_dir'] = tk_tools.FileField(
        dir_frame,
        loc=back_dir,
        is_dir=True,
        callback=directory_callback,
    )
    UI['auto_dir'].grid(row=1, column=0)

    count_frame = ttk.Frame(
        frame,
    )
    count_frame.grid(row=0, column=1)
    ttk.Label(
        count_frame,
        text=_('Keep (Per Game):'),
    ).grid(row=0, column=0)

    count = tk_tools.ttk_Spinbox(
        count_frame,
        range=range(50),
        command=count_callback,
    )
    count.grid(row=1, column=0)
    count.value = count_value


def init_toplevel() -> None:
    """Initialise the window as part of the BEE2."""
    global window
    window = tk.Toplevel(TK_ROOT)
    window.transient(TK_ROOT)
    window.withdraw()
    window.title(_('Backup/Restore Puzzles'))

    def quit_command():
        from BEE2_config import GEN_OPTS
        window.withdraw()
        GEN_OPTS.save_check()

    # Don't destroy window when quit!
    window.protocol("WM_DELETE_WINDOW", quit_command)

    init()
    init_backup_settings()

    # When embedded in the BEE2, use regular buttons and a dropdown!
    toolbar_frame = ttk.Frame(
        window,
    )
    ttk.Button(
        toolbar_frame,
        text=_('New Backup'),
        command=ui_new_backup,
        width=14,
    ).grid(row=0, column=0)

    ttk.Button(
        toolbar_frame,
        text=_('Open Backup'),
        command=ui_load_backup,
        width=13,
    ).grid(row=0, column=1)

    ttk.Button(
        toolbar_frame,
        text=_('Save Backup'),
        command=ui_save_backup,
        width=11,
    ).grid(row=0, column=2)

    ttk.Button(
        toolbar_frame,
        text='.. As',
        command=ui_save_backup_as,
        width=5,
    ).grid(row=0, column=3)

    toolbar_frame.grid(row=0, column=0, columnspan=3, sticky='W')

    TK_ROOT.update()
    ui_new_backup()


@atexit.register
def deinit() -> None:
    """When shutting down, we need to close the backup zipfile."""
    for name in ('backup_zip', 'unsaved_file'):
        obj = BACKUPS[name]
        if obj is not None:
            obj.close()

