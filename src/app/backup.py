"""Backup and restore P2C maps.

"""
from typing import List, TYPE_CHECKING, Dict, Any, Optional, Union, cast
from typing_extensions import Self, TypeAlias

from tkinter import filedialog, ttk
import tkinter as tk
import atexit
import os
import shutil
import string
from datetime import datetime
from io import BytesIO, TextIOWrapper
from zipfile import ZipFile, ZIP_LZMA


import loadScreen
import srctools.logger
from app import tk_tools, img, TK_ROOT, background_run
import utils
from app.CheckDetails import CheckDetails, Item as CheckItem
from FakeZip import FakeZip, zip_names, zip_open_bin
from srctools import Keyvalues, KeyValError
from app.tooltip import add_tooltip
from app.localisation import TransToken, set_text, set_menu_text, set_win_title
from ui_tk.img import TKImages


if TYPE_CHECKING:
    from app import gameMan

LOGGER = srctools.logger.get_logger(__name__)

# The backup window - either a toplevel, or TK_ROOT.
window: tk.Toplevel

AnyZip: TypeAlias = Union[ZipFile, FakeZip]
UI: Dict[str, Any] = {}  # Holds all the widgets

menus = {}  # For standalone application, generate menu bars

# Stage name for the exporting screen
AUTO_BACKUP_STAGE = 'BACKUP_ZIP'

# Characters allowed in the backup filename
BACKUP_CHARS = set(string.ascii_letters + string.digits + '_-.')
# Format for the backup filename
AUTO_BACKUP_FILE = 'back_{game}{ind}.zip'

HEADERS = [TransToken.ui('Name'), TransToken.ui('Mode'), TransToken.ui('Date')]

TRANS_SP = TransToken.ui('SP')
TRANS_COOP = TransToken.ui('Coop')
TRANS_DELETE_DESC = TransToken.ui_plural(
    'Do you wish to delete {n} map?\n{maps}',
    'Do you wish to delete {n} maps?\n{maps}',
)
TRANS_OVERWRITE_GAME = TransToken.ui(
    'This map is already in the game directory. Do you wish to overwrite it? ({mapname})'
)
TRANS_OVERWRITE_BACKUP = TransToken.ui(
    'This filename is already in the backup. Do you wish to overwrite it? ({mapname})'
)
TRANS_OVERWRITE_TITLE = TransToken.ui('Overwrite File?')
TRANS_FAIL_PARSE = TransToken.ui('Failed to parse this puzzle file. It can still be backed up.')
TRANS_NO_DESC = TransToken.ui('No description found.')
TRANS_UNSAVED = TransToken.ui('Unsaved Backup')
TRANS_FILETYPE = TransToken.ui('Backup ZIP archive')

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
    ('COPY', TransToken.BLANK),
    title_text=TransToken.ui('Copying maps'),
)

reading_loader = loadScreen.LoadScreen(
    ('READ', TransToken.BLANK),
    title_text=TransToken.ui('Loading maps'),
)

deleting_loader = loadScreen.LoadScreen(
    ('DELETE', TransToken.BLANK),
    title_text=TransToken.ui('Deleting maps'),
)


class P2C:
    """A PeTI map."""
    def __init__(
        self,
        filename: str,
        zip_file: AnyZip,
        create_time: 'Date',
        mod_time: 'Date',
        title: str = '<untitled>',
        desc: TransToken = TRANS_NO_DESC,
        is_coop: bool = False,
    ) -> None:
        self.filename = filename
        self.zip_file = zip_file
        self.create_time = create_time
        self.mod_time = mod_time
        self.title = title
        self.desc = desc
        self.is_coop = is_coop

    @classmethod
    def from_file(cls, path: str, zip_file: Union[ZipFile, FakeZip]) -> 'P2C':
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
                    kv = Keyvalues.parse(textfile, path)
        except KeyValError:
            # Silently fail if we can't parse the file. That way it's still
            # possible to back up.
            LOGGER.warning('Failed parsing puzzle file!', path, exc_info=True)
            kv = Keyvalues('portal2_puzzle', [])
            title = None
            desc = TRANS_FAIL_PARSE
        else:
            kv = kv.find_key('portal2_puzzle', or_blank=True)
            title = kv['title', None]
            try:
                desc = TransToken.untranslated(kv['description'])
            except LookupError:
                desc = TRANS_NO_DESC

        if title is None:
            title = '<' + path.rsplit('/', 1)[-1] + '.p2c>'

        return cls(
            filename=os.path.basename(path),
            zip_file=zip_file,
            title=title,
            desc=desc,
            is_coop=srctools.conv_bool(kv['coop', '0']),
            create_time=Date(kv['timestamp_created', '']),
            mod_time=Date(kv['timestamp_modified', '']),
        )

    def copy(self) -> Self:
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

    def make_item(self) -> CheckItem['P2C']:
        """Make a corresponding CheckItem object."""
        return CheckItem(
            TransToken.untranslated(self.title),
            TRANS_COOP if self.is_coop else TRANS_SP,
            self.mod_time.as_token(),
            hover_text=self.desc,
            user=self,
        )


class Date:
    """A version of datetime with an invalid value, and read from hex."""
    def __init__(self, hex_time: str) -> None:
        """Convert the time format in P2C files into a useable value."""
        try:
            val = int(hex_time, 16)
        except ValueError:
            self.date = None
        else:
            self.date = datetime.fromtimestamp(val)

    def as_token(self) -> TransToken:
        """Return value for display."""
        if self.date is None:
            return TransToken.untranslated('???')
        else:
            return TransToken.untranslated('{date:medium}').format(date=self.date)

    # No date = always earlier
    def __lt__(self, other: 'Date') -> bool:
        if self.date is None:
            return True
        elif other.date is None:
            return False
        else:
            return self.date < other.date

    def __gt__(self, other: 'Date') -> bool:
        if self.date is None:
            return False
        elif other.date is None:
            return True
        else:
            return self.date > other.date

    def __le__(self, other: 'Date') -> bool:
        if self.date is None:
            return other.date is None
        else:
            return self.date <= other.date

    def __ge__(self, other: 'Date') -> bool:
        if self.date is None:
            return other.date is None
        else:
            return self.date >= other.date

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Date):
            return self.date == other.date
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        if isinstance(other, Date):
            return self.date != other.date
        return NotImplemented


# Note: All the backup functions use zip files, but also work on FakeZip
# directories.


def load_backup(zip_file: AnyZip) -> List[P2C]:
    """Load in a backup file."""
    maps: List[P2C] = []
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


def load_game(game: 'gameMan.Game') -> None:
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


def find_puzzles(game: 'gameMan.Game') -> Optional[str]:
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


def backup_maps(maps: List[P2C]) -> None:
    """Copy the given maps to the backup."""
    back_zip: ZipFile = BACKUPS['backup_zip']

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
        if map_path in zip_names(back_zip) or scr_path in zip_names(back_zip):
            if not tk_tools.askyesno(
                title=TRANS_OVERWRITE_TITLE,
                message=TRANS_OVERWRITE_BACKUP.format(mapname=p2c.title),
                parent=window,
            ):
                continue
        new_item = p2c.copy()
        map_dict[p2c.filename] = new_item

    BACKUPS['back'] = list(map_dict.values())
    refresh_back_details()


def auto_backup(game: 'gameMan.Game', loader: loadScreen.LoadScreen) -> None:
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
            LOGGER.info('Moving: {} -> {}', old_name, new_name)
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


def save_backup() -> None:
    """Save the backup file."""
    # We generate it from scratch, since that's the only way to remove
    # files.
    new_zip_data = BytesIO()
    new_zip = ZipFile(new_zip_data, 'w', compression=ZIP_LZMA)

    maps: List[P2C] = [
        item.user
        for item in
        UI['back_details'].items
    ]

    if not maps:
        tk_tools.showerror(TransToken.ui('BEE2 Backup'), TransToken.ui('No maps were chosen to backup!'))
        return

    copy_loader.set_length('COPY', len(maps))

    with copy_loader:
        for p2c in maps:
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


def restore_maps(maps: List[P2C]) -> None:
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
            if os.path.isfile(abs_scr) or os.path.isfile(abs_map):
                if not tk_tools.askyesno(
                    title=TRANS_OVERWRITE_TITLE,
                    message=TRANS_OVERWRITE_GAME.format(mapname=p2c.title),
                    parent=window,
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


def refresh_game_details() -> None:
    """Remake the items in the game maps list."""
    game = UI['game_details']
    game.remove_all()
    game.add_items(*(
        peti_map.make_item()
        for peti_map in
        BACKUPS['game']
    ))


def refresh_back_details() -> None:
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
    tk_tools.center_win(window, TK_ROOT)
    # Load our game data!
    ui_refresh_game()
    window.update()
    UI['game_details'].refresh()
    UI['back_details'].refresh()


def ui_load_backup() -> None:
    """Prompt and load in a backup file."""
    file = filedialog.askopenfilename(
        title=str(TransToken.ui('Load Backup')),
        filetypes=[(str(TRANS_FILETYPE), '.zip')],
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
    backup_name.set(str(TRANS_UNSAVED))
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
        title=str(TransToken.ui('Save Backup As')),
        filetypes=[(str(TRANS_FILETYPE), '.zip')],
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
    from app import gameMan
    if gameMan.selected_game is not None:
        load_game(gameMan.selected_game)


def ui_backup_sel() -> None:
    """Backup selected maps."""
    backup_maps([
        item.user
        for item in
        UI['game_details'].items
        if item.state
    ])


def ui_backup_all() -> None:
    """Backup all maps."""
    backup_maps([
        item.user
        for item in
        UI['game_details'].items
    ])


def ui_restore_sel() -> None:
    """Restore selected maps."""
    restore_maps([
        item.user
        for item in
        UI['back_details'].items
        if item.state
    ])


def ui_restore_all() -> None:
    """Backup all maps."""
    restore_maps([
        item.user
        for item in UI['back_details'].items
    ])


def ui_delete_backup() -> None:
    """Delete the selected items in the backup."""
    BACKUPS['back'] = [
        item.user
        for item in UI['back_details'].items
        if not item.state
    ]

    refresh_back_details()


def ui_delete_game() -> None:
    """Delete selected items in the game list."""
    game_dir = BACKUPS['game_path']
    if game_dir is None:
        LOGGER.warning('No game selected to delete from?')
        return

    game_detail: CheckDetails[P2C] = UI['game_details']

    to_delete = [
        item.user
        for item in
        game_detail.items
        if item.state
    ]
    to_keep = [
        item.user
        for item in
        game_detail.items
        if not item.state
    ]

    if not to_delete:
        return
    if not tk_tools.askyesno(TransToken.ui('Confirm Deletion'), TRANS_DELETE_DESC.format(
        n=len(to_delete),
        maps='\n'.join([f'- "{p2c.title}" ({p2c.filename}.p2c)' for p2c in to_delete]),
    )):
        return

    deleting_loader.set_length('DELETE', len(to_delete))
    try:
        with deleting_loader:
            for p2c in to_delete:
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


def init(tk_img: TKImages) -> None:
    """Initialise all widgets in the given window."""
    for cat, btn_text in [
        ('back_', TransToken.ui('Restore:')),
        ('game_', TransToken.ui('Backup:')),
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

        button_frame = ttk.Frame(frame)
        button_frame.grid(column=0, row=2)
        set_text(ttk.Label(button_frame), btn_text).grid(row=0, column=0)
        UI[cat + 'btn_all'] = ttk.Button(
            button_frame,
            text='All',
            width=3,
        )
        UI[cat + 'btn_sel'] = set_text(ttk.Button(button_frame, width=8), TransToken.ui('Checked'))

        UI[cat + 'btn_all'].grid(row=0, column=1)
        UI[cat + 'btn_sel'].grid(row=0, column=2)

        UI[cat + 'btn_del'] = btn_del = ttk.Button(button_frame, width=14)
        set_text(btn_del, TransToken.ui('Delete Checked'))
        btn_del.grid(row=1, column=0, columnspan=3)

        tk_tools.add_mousewheel(UI[cat + 'details'].wid_canvas, UI[cat + 'frame'])

    game_refresh = ttk.Button(
        UI['game_title_frame'],
        command=ui_refresh_game,
    )
    game_refresh.grid(row=0, column=1, sticky='E')
    add_tooltip(game_refresh, TransToken.ui("Reload the map list."))
    tk_img.apply(game_refresh, img.Handle.builtin('icons/tool_sub', 16, 16))

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


def init_application(tk_img: TKImages) -> None:
    """Initialise the standalone application."""
    from app import gameMan
    global window
    window = cast(tk.Toplevel, TK_ROOT)
    set_win_title(TK_ROOT, TransToken.ui(
        'BEEMOD {version} - Backup / Restore Puzzles',
    ).format(version=utils.BEE_VERSION))

    init(tk_img)

    UI['bar'] = bar = tk.Menu(TK_ROOT)
    window.option_add('*tearOff', False)

    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = menus['file'] = tk.Menu(bar, name='apple')
    else:
        file_menu = menus['file'] = tk.Menu(bar, name='file')

    file_menu.add_command(command=ui_new_backup)
    set_menu_text(file_menu, TransToken.ui('New Backup'))
    file_menu.add_command(command=ui_load_backup)
    set_menu_text(file_menu, TransToken.ui('Open Backup'))
    file_menu.add_command(command=ui_save_backup)
    set_menu_text(file_menu, TransToken.ui('Save Backup'))
    file_menu.add_command(command=ui_save_backup_as)
    set_menu_text(file_menu, TransToken.ui('Save Backup As'))

    bar.add_cascade(menu=file_menu)
    set_menu_text(bar, TransToken.ui('File'))

    game_menu = menus['game'] = tk.Menu(bar)

    game_menu.add_command(command=gameMan.add_game)
    set_menu_text(game_menu, TransToken.ui('Add Game'))
    game_menu.add_command(command=lambda: background_run(gameMan.remove_game))
    set_menu_text(game_menu, TransToken.ui('Remove Game'))
    game_menu.add_separator()

    bar.add_cascade(menu=game_menu)
    set_menu_text(bar, TransToken.ui('Game'))
    gameMan.game_menu = game_menu

    from app import helpMenu
    # Add the 'Help' menu here too.
    helpMenu.make_help_menu(bar, tk_img)

    window['menu'] = bar

    window.deiconify()
    window.update()

    gameMan.load()
    ui_new_backup()

    async def cback(game):
        """UI.py isn't present, so we use this callback."""
        load_game(game)
    gameMan.ON_GAME_CHANGED.register(cback)

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
        variable=check_var,
        command=check_callback,
    )
    set_text(enable_check, TransToken.ui('Automatic Backup After Export'))

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
    set_text(ttk.Label(count_frame), TransToken.ui('Keep (Per Game):')).grid(row=0, column=0)

    count = tk_tools.ttk_Spinbox(
        count_frame,
        range=range(50),
        command=count_callback,
    )
    count.grid(row=1, column=0)
    count.value = count_value


def init_toplevel(tk_img: TKImages) -> None:
    """Initialise the window as part of the BEE2."""
    global window
    window = tk.Toplevel(TK_ROOT, name='backupWin')
    window.transient(TK_ROOT)
    window.withdraw()
    set_win_title(window, TransToken.ui('Backup/Restore Puzzles'))

    def quit_command() -> None:
        """Close the window."""
        from BEE2_config import GEN_OPTS
        window.withdraw()
        GEN_OPTS.save_check()

    window.protocol("WM_DELETE_WINDOW", quit_command)

    init(tk_img)
    init_backup_settings()

    # When embedded in the BEE2, use regular buttons and a dropdown!
    toolbar_frame = ttk.Frame(window)
    set_text(
        ttk.Button(toolbar_frame, command=ui_new_backup),
        TransToken.ui('New Backup'),
    ).grid(row=0, column=0)

    set_text(
        ttk.Button(toolbar_frame, command=ui_load_backup),
        TransToken.ui('Open Backup'),
    ).grid(row=0, column=1)

    set_text(
        ttk.Button(toolbar_frame, command=ui_save_backup),
        TransToken.ui('Save Backup'),
    ).grid(row=0, column=2)

    set_text(
        ttk.Button(toolbar_frame, command=ui_save_backup_as),
        TransToken.ui('.. As'),
    ).grid(row=0, column=3)

    toolbar_frame.grid(row=0, column=0, columnspan=3, sticky='W')
    ui_new_backup()


@atexit.register
def deinit() -> None:
    """When shutting down, we need to close the backup zipfile."""
    for name in ('backup_zip', 'unsaved_file'):
        obj = BACKUPS[name]
        if obj is not None:
            obj.close()
