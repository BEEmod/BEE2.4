"""Backup and restore P2C maps.

"""
from __future__ import annotations

from typing import List, TYPE_CHECKING, Dict, Any, Union, cast
from typing_extensions import Self, TypeAliasType

from tkinter import filedialog, ttk
from datetime import datetime
from io import BytesIO, TextIOWrapper
from zipfile import ZipFile, ZIP_LZMA
import tkinter as tk
import atexit
import os
import shutil
import string

from srctools import EmptyMapping, Keyvalues, KeyValError
import srctools.logger
import trio

from FakeZip import FakeZip, zip_names, zip_open_bin
from app import img, background_run
from transtoken import TransToken
from ui_tk import TK_ROOT, tk_tools
from ui_tk.check_table import CheckDetails, Item as CheckItem
from ui_tk.dialogs import Dialogs, DIALOG, TkDialogs
from ui_tk.img import TKImages
from ui_tk.tooltip import add_tooltip
from ui_tk.wid_transtoken import set_menu_text, set_text, set_win_title
import loadScreen
import utils


if TYPE_CHECKING:
    from app import gameMan

LOGGER = srctools.logger.get_logger(__name__)

# The backup window - either a toplevel, or TK_ROOT.
window: tk.Toplevel

AnyZip = TypeAliasType("AnyZip", Union[ZipFile, FakeZip])
UI: Dict[str, Any] = {}  # Holds all the widgets

# Loading stage used during backup.
AUTO_BACKUP_STAGE = loadScreen.ScreenStage(TransToken.ui('Backup Puzzles'))

# Characters allowed in the backup filename
BACKUP_CHARS = set(string.ascii_letters + string.digits + '_-.')
# Format for the backup filename
AUTO_BACKUP_FILE = 'back_{game}{ind}.zip'

HEADERS = [TransToken.ui('Name'), TransToken.ui('Mode'), TransToken.ui('Date')]

TRANS_SP = TransToken.ui('SP')
TRANS_COOP = TransToken.ui('Coop')
TRANS_DELETE_DESC = TransToken.ui_plural(
    'Do you wish to delete {n} map?',
    'Do you wish to delete {n} maps?',
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
LOAD_STAGE = loadScreen.ScreenStage(TransToken.BLANK)

copy_loader = loadScreen.LoadScreen(
    LOAD_STAGE,
    title_text=TransToken.ui('Copying maps'),
)

reading_loader = loadScreen.LoadScreen(
    LOAD_STAGE,
    title_text=TransToken.ui('Loading maps'),
)

deleting_loader = loadScreen.LoadScreen(
    LOAD_STAGE,
    title_text=TransToken.ui('Deleting maps'),
)


class P2C:
    """A PeTI map."""
    def __init__(
        self,
        filename: str,
        zip_file: AnyZip,
        create_time: Date,
        mod_time: Date,
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
    def from_file(cls, path: str, zip_file: AnyZip) -> P2C:
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

    def make_item(self) -> CheckItem[P2C]:
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
    def __lt__(self, other: Date) -> bool:
        if self.date is None:
            return True
        elif other.date is None:
            return False
        else:
            return self.date < other.date

    def __gt__(self, other: Date) -> bool:
        if self.date is None:
            return False
        elif other.date is None:
            return True
        else:
            return self.date > other.date

    def __le__(self, other: Date) -> bool:
        if self.date is None:
            return other.date is None
        else:
            return self.date <= other.date

    def __ge__(self, other: Date) -> bool:
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


async def load_backup(zip_file: AnyZip) -> List[P2C]:
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
    LOGGER.info('Loading {} maps..', len(puzzles))
    async with reading_loader, utils.aclosing(LOAD_STAGE.iterate(puzzles)) as agen:
        async for file in agen:
            new_map = await trio.to_thread.run_sync(P2C.from_file, file, zip_file)
            maps.append(new_map)
            LOGGER.debug(
                'Loading {} map "{}"',
                'coop' if new_map.is_coop else 'sp',
                new_map.title,
            )
    LOGGER.info('Done!')

    # It takes a while before the detail headers update positions,
    # so delay a refresh call.
    TK_ROOT.after(500, UI['game_details'].refresh)

    return maps


async def load_game(game: gameMan.Game) -> None:
    """Callback for gameMan, load in files for a game."""
    game_name.set(game.name)

    puzz_path = find_puzzles(game)
    if puzz_path:
        zip_file = FakeZip(puzz_path)
        BACKUPS['game'] = await load_backup(zip_file)
        BACKUPS['game_path'] = puzz_path
        BACKUPS['game_zip'] = zip_file
        refresh_game_details()


def find_puzzles(game: gameMan.Game) -> str | None:
    """Find the path for the p2c files."""
    # The puzzles are located in:
    # <game_folder>/portal2/puzzles/<steam_id>
    # 'portal2' changes with different games.

    puzzle_folder = PUZZLE_FOLDERS.get(str(game.steamID), 'portal2')
    path = game.abs_path(puzzle_folder + '/puzzles/')
    try:
        id_folders = os.listdir(path)
    except FileNotFoundError:
        # No puzzles folder at all...
        return None

    for folder in id_folders:
        # The steam ID is all digits, so look for a folder with only digits
        # in the name
        if not folder.isdigit():
            continue
        abs_path = os.path.join(path, folder)
        if os.path.isdir(abs_path):
            return abs_path
    return None


async def backup_maps(dialogs: Dialogs, maps: List[P2C]) -> None:
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
            if not await dialogs.ask_yes_no(
                title=TRANS_OVERWRITE_TITLE,
                message=TRANS_OVERWRITE_BACKUP.format(mapname=p2c.title),
            ):
                continue
        new_item = p2c.copy()
        map_dict[p2c.filename] = new_item

    BACKUPS['back'] = list(map_dict.values())
    refresh_back_details()


async def auto_backup(game: gameMan.Game) -> None:
    """Perform an automatic backup for the given game.

    We do this seperately since we don't need to read the property files.
    """
    from BEE2_config import GEN_OPTS
    if not GEN_OPTS.get_bool('General', 'enable_auto_backup'):
        # Don't backup!
        await AUTO_BACKUP_STAGE.skip()
        return

    folder = find_puzzles(game)
    if not folder:
        await AUTO_BACKUP_STAGE.skip()
        return

    # Keep this many previous
    extra_back_count = GEN_OPTS.get_int('General', 'auto_backup_count', 0)

    to_backup = await trio.to_thread.run_sync(os.listdir, folder)
    backup_dir = GEN_OPTS.get_val('Directories', 'backup_loc', 'backups/')

    os.makedirs(backup_dir, exist_ok=True)

    # A version of the name stripped of special characters
    # Allowed: a-z, A-Z, 0-9, '_-.'
    safe_name = srctools.whitelist(
        game.name,
        valid_chars=BACKUP_CHARS,
    )

    await AUTO_BACKUP_STAGE.set_length(len(to_backup))

    if extra_back_count:
        back_files = [
            AUTO_BACKUP_FILE.format(game=safe_name, ind='')
        ] + [
            AUTO_BACKUP_FILE.format(game=safe_name, ind='_'+str(i+1))
            for i in range(extra_back_count)
        ]
        # Move each file over by 1 index, ignoring missing ones
        # We need to reverse to ensure we don't overwrite any zips
        for old_name, new_name in reversed(list(zip(back_files, back_files[1:]))):
            LOGGER.info('Moving: {} -> {}', old_name, new_name)
            old_name = os.path.join(backup_dir, old_name)
            new_name = os.path.join(backup_dir, new_name)
            try:
                await trio.to_thread.run_sync(os.remove, new_name)
            except FileNotFoundError:
                pass  # We're overwriting this anyway
            try:
                await trio.to_thread.run_sync(os.rename, old_name, new_name)
            except FileNotFoundError:
                pass

    final_backup = os.path.join(
        backup_dir,
        AUTO_BACKUP_FILE.format(game=safe_name, ind=''),
    )
    LOGGER.info('Writing backup to "{}"', final_backup)
    with open(final_backup, 'wb') as f, ZipFile(f, mode='w', compression=ZIP_LZMA) as zip_file:
        async with utils.aclosing(AUTO_BACKUP_STAGE.iterate(to_backup)) as agen:
            async for file in agen:
                await trio.to_thread.run_sync(
                    zip_file.write,
                    os.path.join(folder, file),
                    file,
                    ZIP_LZMA,
                )


async def save_backup(dialogs: Dialogs) -> None:
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
        await dialogs.show_info(
            title=TransToken.ui('BEE2 Backup'),
            message=TransToken.ui('No maps were chosen to backup!'),
            icon=dialogs.ERROR
        )
        return

    async with copy_loader, utils.aclosing(LOAD_STAGE.iterate(maps)) as agen:
        async for p2c in agen:
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


async def restore_maps(dialogs: Dialogs, maps: List[P2C]) -> None:
    """Copy the given maps to the game."""
    game_dir = BACKUPS['game_path']
    if game_dir is None:
        LOGGER.warning('No game selected to restore from?')
        return

    async with copy_loader, utils.aclosing(LOAD_STAGE.iterate(maps)) as agen:
        async for p2c in agen:
            back_zip = p2c.zip_file
            scr_path = p2c.filename + '.jpg'
            map_path = p2c.filename + '.p2c'
            abs_scr = os.path.join(game_dir, scr_path)
            abs_map = os.path.join(game_dir, map_path)
            if os.path.isfile(abs_scr) or os.path.isfile(abs_map):
                if not await dialogs.ask_yes_no(
                    title=TRANS_OVERWRITE_TITLE,
                    message=TRANS_OVERWRITE_GAME.format(mapname=p2c.title),
                ):
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
    background_run(ui_refresh_game)
    window.update()
    UI['game_details'].refresh()
    UI['back_details'].refresh()


async def ui_load_backup() -> None:
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
        BACKUPS['back'] = await load_backup(zip_file)
        BACKUPS['backup_zip'] = zip_file

        BACKUPS['backup_name'] = os.path.basename(file)
        backup_name.set(BACKUPS['backup_name'])

        refresh_back_details()
    except Exception:
        zip_file.close()
        raise


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


async def ui_save_backup(dialogs: Dialogs) -> None:
    """Save a backup."""
    if BACKUPS['backup_path'] is None:
        # No backup path, prompt first
        await ui_save_backup_as(dialogs)
    else:
        await save_backup(dialogs)


async def ui_save_backup_as(dialogs: Dialogs) -> None:
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
    await ui_save_backup(dialogs)


async def ui_refresh_game() -> None:
    """Reload the game maps list."""
    from app import gameMan
    if gameMan.selected_game is not None:
        await load_game(gameMan.selected_game)


async def ui_backup_sel(dialogs: Dialogs) -> None:
    """Backup selected maps."""
    await backup_maps(dialogs, [
        item.user
        for item in
        UI['game_details'].items
        if item.state
    ])


async def ui_backup_all(dialogs: Dialogs) -> None:
    """Backup all maps."""
    await backup_maps(dialogs, [
        item.user
        for item in
        UI['game_details'].items
    ])


async def ui_restore_sel(dialogs: Dialogs) -> None:
    """Restore selected maps."""
    await restore_maps(dialogs, [
        item.user
        for item in
        UI['back_details'].items
        if item.state
    ])


async def ui_restore_all(dialogs: Dialogs) -> None:
    """Backup all maps."""
    await restore_maps(dialogs, [
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


async def ui_delete_game(dialog: Dialogs) -> None:
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
    if not await dialog.ask_yes_no(
        title=TransToken.ui('Confirm Deletion'),
        message=TRANS_DELETE_DESC.format(n=len(to_delete)),
        detail='\n'.join([f'- "{p2c.title}" ({p2c.filename}.p2c)' for p2c in to_delete]),
    ):
        return

    async with deleting_loader, utils.aclosing(LOAD_STAGE.iterate(to_delete)) as agen:
        async for p2c in agen:
            scr_path = p2c.filename + '.jpg'
            map_path = p2c.filename + '.p2c'
            abs_scr = os.path.join(game_dir, scr_path)
            abs_map = os.path.join(game_dir, map_path)
            try:
                await trio.to_thread.run_sync(os.remove, abs_scr)
            except FileNotFoundError:
                LOGGER.info('{} not present!', abs_scr)
            try:
                await trio.to_thread.run_sync(os.remove, abs_map)
            except FileNotFoundError:
                LOGGER.info('{} not present!', abs_map)

    BACKUPS['game'] = to_keep
    refresh_game_details()


def init(tk_img: TKImages) -> None:
    """Initialise all widgets in the given window."""
    dialog = TkDialogs(window)
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
        command=lambda: background_run(ui_refresh_game),
    )
    game_refresh.grid(row=0, column=1, sticky='E')
    add_tooltip(game_refresh, TransToken.ui("Reload the map list."))
    tk_img.apply(game_refresh, img.Handle.builtin('icons/tool_sub', 16, 16))

    UI['game_title']['textvariable'] = game_name
    UI['back_title']['textvariable'] = backup_name

    UI['game_btn_all']['command'] = lambda: background_run(ui_backup_all, dialog)
    UI['game_btn_sel']['command'] = lambda: background_run(ui_backup_sel, dialog)
    UI['game_btn_del']['command'] = lambda: background_run(ui_delete_game, dialog)

    UI['back_btn_all']['command'] = lambda: background_run(ui_restore_all, dialog)
    UI['back_btn_sel']['command'] = lambda: background_run(ui_restore_sel, dialog)
    UI['back_btn_del']['command'] = ui_delete_backup


    UI['back_frame'].grid(row=1, column=0, sticky='NSEW')
    ttk.Separator(orient=tk.VERTICAL).grid(
        row=1, column=1, sticky='NS', padx=5,
    )
    UI['game_frame'].grid(row=1, column=2, sticky='NSEW')

    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)
    window.columnconfigure(2, weight=1)


async def init_application() -> None:
    """Initialise the standalone application."""
    from ui_tk.img import TK_IMG
    from app import gameMan, _APP_QUIT_SCOPE
    global window
    window = cast(tk.Toplevel, TK_ROOT)
    set_win_title(TK_ROOT, TransToken.ui(
        'BEEMOD {version} - Backup / Restore Puzzles',
    ).format(version=utils.BEE_VERSION))

    loadScreen.main_loader.destroy()
    # Initialise images, but don't load anything from packages.
    background_run(img.init, EmptyMapping, TK_IMG)
    # We don't need sound or language reload handling.

    init(TK_IMG)

    UI['bar'] = bar = tk.Menu(TK_ROOT)
    window.option_add('*tearOff', False)

    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = tk.Menu(bar, name='apple')
    else:
        file_menu = tk.Menu(bar, name='file')

    file_menu.add_command(command=ui_new_backup)
    set_menu_text(file_menu, TransToken.ui('New Backup'))
    file_menu.add_command(command=lambda: background_run(ui_load_backup))
    set_menu_text(file_menu, TransToken.ui('Open Backup'))
    file_menu.add_command(command=lambda: background_run(ui_save_backup, DIALOG))
    set_menu_text(file_menu, TransToken.ui('Save Backup'))
    file_menu.add_command(command=lambda: background_run(ui_save_backup_as, DIALOG))
    set_menu_text(file_menu, TransToken.ui('Save Backup As'))

    bar.add_cascade(menu=file_menu)
    set_menu_text(bar, TransToken.ui('File'))

    game_menu = tk.Menu(bar)

    game_menu.add_command(command=lambda: background_run(gameMan.add_game, DIALOG))
    set_menu_text(game_menu, TransToken.ui('Add Game'))
    game_menu.add_command(command=lambda: background_run(gameMan.remove_game, DIALOG))
    set_menu_text(game_menu, TransToken.ui('Remove Game'))
    game_menu.add_separator()

    bar.add_cascade(menu=game_menu)
    set_menu_text(bar, TransToken.ui('Game'))
    gameMan.game_menu = game_menu

    from app import helpMenu
    # Add the 'Help' menu here too.
    background_run(helpMenu.make_help_menu, bar, TK_IMG)

    window['menu'] = bar

    with _APP_QUIT_SCOPE:
        window.deiconify()
        window.update()

        await gameMan.load(DIALOG)
        ui_new_backup()

        @gameMan.ON_GAME_CHANGED.register
        async def cback(game: gameMan.Game) -> None:
            """UI.py isn't present, so we use this callback."""
            await load_game(game)

        gameMan.add_menu_opts(game_menu)

        await trio.sleep_forever()


def init_backup_settings() -> None:
    """Initialise the auto-backup settings widget."""
    from BEE2_config import GEN_OPTS
    check_var = tk.IntVar(
        value=GEN_OPTS.get_bool('General', 'enable_auto_backup')
    )
    count_value = GEN_OPTS.get_int('General', 'auto_backup_count', 0)
    back_dir = GEN_OPTS.get_val('Directories', 'backup_loc', 'backups/')

    def check_callback() -> None:
        GEN_OPTS['General']['enable_auto_backup'] = srctools.bool_as_int(check_var.get())

    def count_callback() -> None:
        GEN_OPTS['General']['auto_backup_count'] = str(count.value)

    def directory_callback(path: str) -> None:
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

    dir_frame = ttk.Frame(frame)
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

    count_frame = ttk.Frame(frame)
    count_frame.grid(row=0, column=1)
    set_text(ttk.Label(count_frame), TransToken.ui('Keep (Per Game):')).grid(row=0, column=0)

    count = tk_tools.ttk_Spinbox(
        count_frame,
        domain=range(50),
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
    dialog = TkDialogs(window)

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
        ttk.Button(toolbar_frame, command=lambda: background_run(ui_load_backup)),
        TransToken.ui('Open Backup'),
    ).grid(row=0, column=1)

    set_text(
        ttk.Button(toolbar_frame, command=lambda: background_run(ui_save_backup, dialog)),
        TransToken.ui('Save Backup'),
    ).grid(row=0, column=2)

    set_text(
        ttk.Button(toolbar_frame, command=lambda: background_run(ui_save_backup_as, dialog)),
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
