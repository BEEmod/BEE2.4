"""Keeps track of which games are known, and allows adding/removing them."""
from __future__ import annotations
from typing import Self

from collections.abc import Iterator, Mapping
from pathlib import Path
import os
import shutil
import subprocess
import sys
import webbrowser

from tkinter import filedialog
import tkinter as tk

from srctools import EmptyMapping, Keyvalues
import srctools.logger
import srctools.fgd
import attrs
import trio_util
import trio

from BEE2_config import ConfigFile
from app import quit_app
from async_util import EdgeTrigger
from app.dialogs import Dialogs
from config.gen_opts import GenOptions
from exporting.compiler import terminate_error_server, restore_backup
from exporting.files import INST_PATH
from exporting.gameinfo import edit_gameinfos
from transtoken import TransToken
import loadScreen
import packages
import utils
import config

LOGGER = srctools.logger.get_logger(__name__)

all_games: list[Game] = []
selected_game: trio_util.AsyncValue[Game | None] = trio_util.AsyncValue(None)
selectedGame_radio = tk.IntVar(value=0)
game_menu: tk.Menu | None = None

CONFIG = ConfigFile('games.cfg')
# Stores the current text for the export button, which is updated based on several
# different criteria.
EXPORT_BTN_TEXT = trio_util.AsyncValue(TransToken.BLANK)

TRANS_EXPORT_BTN = TransToken.ui('Export to "{game}"...')
TRANS_EXPORT_BTN_DIRTY = TransToken.ui('Export to "{game}"*...')

EXE_SUFFIX = (
    '.exe' if utils.WIN else
    '_osx' if utils.MAC else
    '_linux' if utils.LINUX else
    ''
)


@attrs.define(eq=False)
class Game:
    """A game that we are able to mod."""
    name: str = attrs.field(eq=False)
    steamID: str
    root: str
    # The last modified date of packages, so we know whether to copy it over.
    mod_times: trio_util.AsyncValue[Mapping[str, int]] = attrs.field(
        init=False, eq=False,
        factory=lambda: trio_util.AsyncValue(EmptyMapping),
    )
    # The style last exported to the game.
    exported_style: str | None = attrs.field(default=None, eq=False)

    # In previous versions, we always wrote our VPK into dlc3. This tracks whether this game was
    # read in from a previous BEE install, and so has created the DLC3 folder even though it's
    # not marked with our marker file.
    unmarked_dlc3_vpk: bool = attrs.field(default=False, eq=False)

    @property
    def root_path(self) -> trio.Path:
        """Return the root, wrapped in a path object."""
        return trio.Path(self.root)

    @classmethod
    def parse(cls, gm_id: str, config: ConfigFile) -> Self:
        """Parse out the given game ID from the config file."""
        steam_id = config.get_val(gm_id, 'SteamID', '<none>')
        if not steam_id.isdigit():
            raise ValueError(f'Game {gm_id} has invalid Steam ID: {steam_id}')

        folder = config.get_val(gm_id, 'Dir', '')
        if not folder:
            raise ValueError(f'Game {gm_id} has no folder!')

        if not os.path.exists(folder):
            raise ValueError(f'Folder {folder} does not exist for game {gm_id}!')

        exp_style = config.get_val(gm_id, 'exported_style', '') or None

        # This flag is only set if we parse from a config that doesn't include it.
        unmarked_dlc3 = config.getboolean(gm_id, 'unmarked_dlc3', True)

        mod_times: dict[str, int] = {}

        for name, value in config.items(gm_id):
            if name.startswith('pack_mod_'):
                mod_times[name.removeprefix('pack_mod_').casefold()] = srctools.conv_int(value)

        game = cls(gm_id, steam_id, folder, exp_style, unmarked_dlc3)
        game.mod_times.value = mod_times
        return game

    def save(self) -> None:
        """Write a game into the config page."""
        # Wipe the original configs
        CONFIG[self.name] = {}
        CONFIG[self.name]['SteamID'] = self.steamID
        CONFIG[self.name]['Dir'] = self.root
        CONFIG[self.name]['unmarked_dlc3'] = srctools.bool_as_int(self.unmarked_dlc3_vpk)
        if self.exported_style is not None:
            CONFIG[self.name]['exported_style'] = self.exported_style
        for pack, mod_time in self.mod_times.value.items():
            CONFIG[self.name]['pack_mod_' + pack] = str(mod_time)

    def dlc_priority(self) -> Iterator[str]:
        """Iterate through all subfolders, in order of high to low priority.

        We assume the priority follows:
        1. update,
        2. portal2_dlc99, ..., portal2_dlc2, portal2_dlc1
        3. portal2,
        4. <all others>
        """
        dlc_count = 1
        priority = ["portal2"]
        while os.path.isdir(self.abs_path("portal2_dlc" + str(dlc_count))):
            priority.append("portal2_dlc" + str(dlc_count))
            dlc_count += 1
        if os.path.isdir(self.abs_path("update")):
            priority.append("update")
        # files are definitely not here
        blacklist = ("bin", "Soundtrack", "sdk_tools", "sdk_content")
        yield from reversed(priority)
        for folder in os.listdir(self.root):
            if (os.path.isdir(self.abs_path(folder)) and
                    folder not in priority and
                    folder not in blacklist):
                yield folder

    def abs_path(self, path: str | Path) -> str:
        """Return the full path to something relative to this game's folder."""
        return os.path.normcase(os.path.join(self.root, path))

    def cache_invalid(self) -> bool:
        """Check to see if the cache is valid."""
        if config.APP.get_cur_conf(GenOptions).preserve_resources:
            # Skipped always
            return False

        # Check lengths, to ensure we re-extract if packages were removed.
        loaded = packages.get_loaded_packages()
        mod_times = self.mod_times.value
        if len(loaded.packages) != len(mod_times):
            LOGGER.info('Need to extract - package counts inconsistent!')
            return True

        return any(
            pack.is_stale(mod_times.get(pack_id.casefold(), 0))
            for pack_id, pack in
            loaded.packages.items()
        )

    async def clear_cache(self) -> None:
        """Remove all resources from the game."""
        shutil.rmtree(self.abs_path(INST_PATH), ignore_errors=True)
        shutil.rmtree(self.abs_path('bee2/'), ignore_errors=True)
        shutil.rmtree(self.abs_path('bin/bee2/'), ignore_errors=True)

        from exporting import vpks
        try:
            vpk_filename = await vpks.find_folder(self)
            LOGGER.info('VPK filename to remove: {}', vpk_filename)
            vpks.clear_files(vpk_filename)
        except (FileNotFoundError, PermissionError):
            pass

        self.mod_times.value = EmptyMapping

    async def launch(self) -> None:
        """Try and launch the game."""
        url = f'steam://rungameid/{self.steamID}'
        if utils.LINUX:
            try:
                await trio.run_process(['xdg-open', url])
            except subprocess.CalledProcessError:
                LOGGER.warning('Could not call xdg-open!')
        else:
            # This works on Windows and Mac.
            await trio.to_thread.run_sync(webbrowser.open, url)

    async def get_game_lang(self) -> str:
        """Load the app manifest file to determine Portal 2's language."""
        # We need to first figure out what language is used (if not English),
        # then load in the file. This is saved in the 'appmanifest'.
        try:
            appman_data = await (self.root_path / '../../appmanifest_620.acf').read_text('ascii')
        except FileNotFoundError:
            # Portal 2 isn't here...
            return 'en'
        appman = Keyvalues.parse(appman_data, 'appmanifest_620.acf')
        del appman_data
        try:
            return appman.find_key('AppState').find_key('UserConfig')['language']
        except LookupError:
            return ''


async def update_export_text() -> None:
    """Monitor various criteria, and set the text for the export button."""
    trigger = EdgeTrigger[()]()

    async def on_setting_change() -> None:
        """Refresh whenever 'preserve resources' changes."""
        preserve: bool | None = None
        opt: config.gen_opts.GenOptions
        with config.APP.get_ui_channel(config.gen_opts.GenOptions) as channel:
            async for opt in channel:
                if opt.preserve_resources is not preserve:
                    preserve = opt.preserve_resources
                    trigger.maybe_trigger()

    async def on_packset_change() -> None:
        """Refresh whenever the packages changes."""
        while True:
            await packages.LOADED.wait_transition()
            trigger.maybe_trigger()

    async def on_game_change() -> None:
        """Refresh whenever a game changes, or updates its config."""
        while True:
            game = selected_game.value
            if game is None:
                await selected_game.wait_transition()
            else:
                await trio_util.wait_any(
                    selected_game.wait_transition,
                    game.mod_times.wait_transition,
                )
            trigger.maybe_trigger()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(on_setting_change)
        nursery.start_soon(on_packset_change)
        nursery.start_soon(on_game_change)

        while True:
            game = selected_game.value
            if game is None:
                EXPORT_BTN_TEXT.value = TRANS_EXPORT_BTN.format(game='???')
            elif game.cache_invalid():
                EXPORT_BTN_TEXT.value = TRANS_EXPORT_BTN_DIRTY.format(game=game.name)
            else:
                EXPORT_BTN_TEXT.value = TRANS_EXPORT_BTN.format(game=game.name)
            await trigger.wait()


async def find_steam_info(game_dir: str) -> tuple[str | None, str | None]:
    """Determine the steam ID and game name of this folder, if it has one.

    This only works on Source games!
    """
    game_id: str | None = None
    name: str | None = None
    found_name = False
    found_id = False
    for folder in os.listdir(game_dir):
        info_path = os.path.join(game_dir, folder, 'gameinfo.txt')
        try:
            file = await trio.open_file(info_path, encoding='utf8', errors='replace')
        except FileNotFoundError:
            continue
        async with file:
            line: str
            async for line in file:
                clean_line = srctools.clean_line(line).replace('\t', ' ')
                if not found_id and 'steamappid' in clean_line.casefold():
                    raw_id = clean_line.casefold().replace('steamappid', '').strip()
                    if raw_id.isdigit():
                        game_id = raw_id
                elif not found_name and 'game ' in clean_line.casefold():
                    found_name = True
                    ind = clean_line.casefold().rfind('game') + 4
                    name = clean_line[ind:].strip().strip('"')
                if found_name and found_id:
                    break
        if found_name and found_id:
            break
    return game_id, name


async def check_app_in_game(dialog: Dialogs) -> None:
    """Check proactively for the user placing the BEE folder directly in P2."""
    # Check early on for a common mistake - putting the BEE2 folder directly in Portal 2 means
    # when we export we'll try and overwrite ourselves. Use Steam's appid file as a marker.
    if utils.install_path('../steam_appid.txt').exists() and utils.install_path('.').name.casefold() == 'bee2':
        await dialog.show_info(
            message=TransToken.ui(
                "It appears that the BEE2 application was installed directly in a game directory. "
                "The bee2/ folder name is used for exported resources, so this will cause issues.\n\n"
                "Move the application folder elsewhere, then re-run."
            ),
            icon=dialog.ERROR,
        )
        sys.exit()
    else:
        await trio.sleep(0)


def save() -> None:
    for gm in all_games:
        gm.save()
    CONFIG.save_check()


async def load(dialogs: Dialogs) -> None:
    """Load the game configuration."""
    all_games.clear()
    for gm in CONFIG:
        if gm == CONFIG.default_section:
            continue
        try:
            new_game = Game.parse(gm, CONFIG)
        except ValueError:
            LOGGER.warning("Can't parse game: ", exc_info=True)
            continue
        all_games.append(new_game)
        LOGGER.info('Load game: {}', new_game)
    if len(all_games) == 0:
        # Hide the loading screen, since it appears on top
        loadScreen.main_loader.suppress()

        # Ask the user for Portal 2's location...
        if not await add_game(dialogs):
            # they cancelled, quit
            quit_app()
            return
        loadScreen.main_loader.unsuppress()  # Show it again
    selected_game.value = all_games[0]


async def add_game(dialogs: Dialogs) -> bool:
    """Ask for, and load in a game to export to."""
    title = TransToken.ui('BEE2 - Add Game')
    await dialogs.show_info(
        TransToken.ui(
            'Select the folder where the game executable is located ({appname})...'
        ).format(appname='portal2' + EXE_SUFFIX),
        title,
    )
    if utils.WIN:
        exe_loc = filedialog.askopenfilename(
            title=str(TransToken.ui('Find Game Exe')),
            filetypes=[(str(TransToken.ui('Executable')), '.exe')]
        )
    else:
        exe_loc = filedialog.askopenfilename(title=str(TransToken.ui('Find Game Binaries')))
    if exe_loc:
        folder = os.path.dirname(exe_loc)
        gm_id, name = await find_steam_info(folder)
        if name is None or gm_id is None:
            await dialogs.show_info(
                TransToken.ui('This does not appear to be a valid game folder!'),
                title=title,
                icon=dialogs.ERROR,
            )
            return False

        # Mel doesn't use PeTI, so that won't make much sense...
        if gm_id == utils.STEAM_IDS['MEL']:
            await dialogs.show_info(
                TransToken.ui("Portal Stories: Mel doesn't have an editor!"),
                title=title,
                icon=dialogs.ERROR,
            )
            return False

        invalid_names = [gm.name.casefold() for gm in all_games]
        while True:
            name = await dialogs.prompt(
                TransToken.ui("Enter the name of this game:"),
                title=title,
                initial_value=TransToken.untranslated(name),
            )
            if name is None:
                return False
            elif name.casefold() in invalid_names:
                await dialogs.show_info(
                    TransToken.ui('This name is already taken!'),
                    title=title,
                    icon=dialogs.ERROR,
                )
            elif name == '':
                await dialogs.show_info(
                    TransToken.ui('Please enter a name for this game!'),
                    title=title,
                    icon=dialogs.ERROR,
                )
            else:
                break

        new_game = Game(name, gm_id, folder)
        all_games.append(new_game)
        if game_menu is not None:
            add_menu_opts(game_menu)
        save()
        return True
    return False


async def remove_game(dialogs: Dialogs) -> None:
    """Remove the currently-chosen game from the game list."""
    from exporting.fgd import edit_fgd
    cur_game = selected_game.value
    if cur_game is None:
        LOGGER.warning('No games defined?')
        quit_app()
        return
    lastgame_mess = (
        TransToken.ui(
            'Are you sure you want to delete "{game}"?\n'
            '(BEE2 will quit, this is the last game set!)'
        ) if len(all_games) == 1 else
        TransToken.ui('Are you sure you want to delete "{game}"?')
    )
    if await dialogs.ask_yes_no(
        title=TransToken.ui('BEE2 - Remove Game'),
        message=lastgame_mess.format(game=cur_game.name),
    ):
        await terminate_error_server()
        await edit_gameinfos(cur_game, add_line=False)
        edit_fgd(cur_game, add_lines=False)
        await restore_backup(cur_game)
        await cur_game.clear_cache()

        all_games.remove(cur_game)
        CONFIG.remove_section(cur_game.name)
        CONFIG.save()

        if not all_games:
            quit_app()  # If we have no games, nothing can be done
            return

        selected_game.value = all_games[0]
        selectedGame_radio.set(0)
        if game_menu is not None:
            add_menu_opts(game_menu)


def add_menu_opts(menu: tk.Menu) -> None:
    """Add the various games to the menu."""
    length = menu.index('end')
    if length is not None:
        for ind in reversed(range(length)):
            # Delete all the old radiobuttons
            # Iterate backward to ensure indexes stay the same.
            if menu.type(ind) == tk.RADIOBUTTON:
                menu.delete(ind)

    def set_from_radio() -> None:
        """Apply the radio button."""
        selected_game.value = game = all_games[selectedGame_radio.get()]

    for val, game in enumerate(all_games):
        menu.add_radiobutton(
            label=game.name,
            variable=selectedGame_radio,
            value=val,
            command=set_from_radio,
        )


def set_game_by_name(name: utils.SpecialID) -> None:
    """Select the game with the specified name."""
    for game in all_games:
        if utils.obj_id(game.name) == name:
            selected_game.value = game
            selectedGame_radio.set(all_games.index(game))
            break
