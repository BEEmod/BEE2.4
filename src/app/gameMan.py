"""
Does stuff related to the actual games.
- Adding and removing games
- Handles locating parts of a given game,
- Modifying GameInfo to support our special content folder.
- Generating and saving editoritems/vbsp_config
"""
from __future__ import annotations

from typing import NoReturn, Optional, Union, Any, Type, IO, Iterator
from pathlib import Path

from tkinter import *  # ui library
from tkinter import filedialog  # open/save as dialog creator

import math
import os
import re
import shutil
import webbrowser

from srctools import Vec, VPK, Keyvalues, AtomicWriter, VMF, Output
import srctools.logger
import srctools.fgd
import attrs
from typing_extensions import Self

from BEE2_config import ConfigFile
from app import backup, tk_tools, TK_ROOT, background_run
from config.gen_opts import GenOptions
from exporting.compiler import terminate_error_server, restore_backup
from transtoken import TransToken
import loadScreen
import packages
import packages.template_brush
import utils
import config
import event


LOGGER = srctools.logger.get_logger(__name__)

all_games: list[Game] = []
selected_game: Optional[Game] = None
selectedGame_radio = IntVar(value=0)
game_menu: Optional[Menu] = None
ON_GAME_CHANGED: event.Event[Game] = event.Event('game_changed')

CONFIG = ConfigFile('games.cfg')

# The location of all the instances in the game directory
INST_PATH = 'sdk_content/maps/instances/BEE2'

# The line we inject to add our BEE2 folder into the game search path.
# We always add ours such that it's the highest priority, other
# than '|gameinfo_path|.'
GAMEINFO_LINE = 'Game\t|gameinfo_path|../bee2'
OLD_GAMEINFO_LINE = 'Game\t"BEE2"'

# The progress bars used when exporting data into a game
export_screen = loadScreen.LoadScreen(
    ('BACK', TransToken.ui('Backup Original Files')),
    (backup.AUTO_BACKUP_STAGE, TransToken.ui('Backup Puzzles')),
    ('EXP', TransToken.ui('Export Configuration')),
    ('COMP', TransToken.ui('Copy Compiler')),
    ('RES', TransToken.ui('Copy Resources')),
    ('MUS', TransToken.ui('Copy Music')),
    title_text=TransToken.ui('Exporting'),
)

TRANS_EXPORT_BTN = TransToken.ui('Export to "{game}"...')
TRANS_EXPORT_BTN_DIRTY = TransToken.ui('Export to "{game}"*...')

EXE_SUFFIX = (
    '.exe' if utils.WIN else
    '_osx' if utils.MAC else
    '_linux' if utils.LINUX else
    ''
)

# We search for Tag and Mel's music files, and copy them to games on export.
# That way they can use the files.
MUSIC_MEL_VPK: Optional[VPK] = None
MUSIC_TAG_LOC: Optional[str] = None
TAG_COOP_INST_VMF: Optional[VMF] = None



def quit_application() -> NoReturn:
    """Command run to quit the application.

    This is overwritten by UI later.
    """
    import sys
    sys.exit()


@attrs.define(eq=False)
class Game:
    name: str
    steamID: str
    root: str
    # The last modified date of packages, so we know whether to copy it over.
    mod_times: dict[str, int] = attrs.Factory(dict)
    # The style last exported to the game.
    exported_style: Optional[str] = None

    # In previous versions, we always wrote our VPK into dlc3. This tracks whether this game was
    # read in from a previous BEE install, and so has created the DLC3 folder even though it's
    # not marked with our marker file.
    unmarked_dlc3_vpk: bool = False

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

        mod_times = {}

        for name, value in config.items(gm_id):
            if name.startswith('pack_mod_'):
                mod_times[name[9:].casefold()] = srctools.conv_int(value)

        return cls(gm_id, steam_id, folder, mod_times, exp_style, unmarked_dlc3)

    def save(self) -> None:
        """Write a game into the config page."""
        # Wipe the original configs
        CONFIG[self.name] = {}
        CONFIG[self.name]['SteamID'] = self.steamID
        CONFIG[self.name]['Dir'] = self.root
        CONFIG[self.name]['unmarked_dlc3'] = srctools.bool_as_int(self.unmarked_dlc3_vpk)
        if self.exported_style is not None:
            CONFIG[self.name]['exported_style'] = self.exported_style
        for pack, mod_time in self.mod_times.items():
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

    def abs_path(self, path: Union[str, Path]) -> str:
        """Return the full path to something relative to this game's folder."""
        return os.path.normcase(os.path.join(self.root, path))

    def edit_gameinfo(self, add_line: bool = False) -> None:
        """Modify all gameinfo.txt files to add or remove our line.

        Add_line determines if we are adding or removing it.
        """

        for folder in self.dlc_priority():
            info_path = os.path.join(self.root, folder, 'gameinfo.txt')
            if os.path.isfile(info_path):
                with open(info_path, encoding='utf8') as file:
                    data = list(file)

                for line_num, line in reversed(list(enumerate(data))):
                    clean_line = srctools.clean_line(line)
                    if add_line:
                        if clean_line == GAMEINFO_LINE:
                            break  # Already added!
                        elif clean_line == OLD_GAMEINFO_LINE:
                            LOGGER.debug(
                                "Updating gameinfo hook to {}",
                                info_path,
                            )
                            data[line_num] = utils.get_indent(line) + GAMEINFO_LINE + '\n'
                            break
                        elif '|gameinfo_path|' in clean_line and GAMEINFO_LINE not in line:
                            LOGGER.debug(
                                "Adding gameinfo hook to {}",
                                info_path,
                            )
                            # Match the line's indentation
                            data.insert(
                                line_num+1,
                                utils.get_indent(line) + GAMEINFO_LINE + '\n',
                                )
                            break
                    else:
                        if clean_line == GAMEINFO_LINE or clean_line == OLD_GAMEINFO_LINE:
                            LOGGER.debug(
                                "Removing gameinfo hook from {}", info_path
                            )
                            data.pop(line_num)
                            break
                else:
                    if add_line:
                        LOGGER.warning(
                            'Failed editing "{}" to add our special folder!',
                            info_path,
                        )
                    continue

                with AtomicWriter(info_path, encoding='utf8') as file2:
                    for line in data:
                        file2.write(line)

    def edit_fgd(self, add_lines: bool=False) -> None:
        """Add our FGD files to the game folder.

        This is necessary so that VBSP offsets the entities properly,
        if they're in instances.
        Add_line determines if we are adding or removing it.
        """
        file: IO[bytes]
        # We do this in binary to ensure non-ASCII characters pass though
        # untouched.

        fgd_path = self.abs_path('bin/portal2.fgd')
        try:
            with open(fgd_path, 'rb') as file:
                data = file.readlines()
        except FileNotFoundError:
            LOGGER.warning('No FGD file? ("{}")', fgd_path)
            return

        for i, line in enumerate(data):
            match = re.match(
                br'// BEE\W*2 EDIT FLAG\W*=\W*([01])',
                line,
                re.IGNORECASE,
            )
            if match:
                if match.group(1) == b'0':
                    LOGGER.info('FGD editing disabled by file.')
                    return  # User specifically disabled us.
                # Delete all data after this line.
                del data[i:]
                break

        with AtomicWriter(fgd_path, is_bytes=True) as file:
            for line in data:
                file.write(line)
            if add_lines:
                file.write(
                    b'// BEE 2 EDIT FLAG = 1 \n'
                    b'// Added automatically by BEE2. Set above to "0" to '
                    b'allow editing below text without being overwritten.\n'
                    b'// You\'ll want to do that if installing Hammer Addons.'
                    b'\n\n'
                )
                with utils.install_path('BEE2.fgd').open('rb') as bee2_fgd:
                    shutil.copyfileobj(bee2_fgd, file)
                file.write(b'\n')
                try:
                    with utils.install_path('hammeraddons.fgd').open('rb') as ha_fgd:
                        shutil.copyfileobj(ha_fgd, file)
                except FileNotFoundError:
                    if utils.FROZEN:
                        raise  # Should be here!
                    else:
                        LOGGER.warning('Missing hammeraddons.fgd, build the app at least once!')

    def cache_invalid(self) -> bool:
        """Check to see if the cache is valid."""
        if config.APP.get_cur_conf(GenOptions).preserve_resources:
            # Skipped always
            return False

        # Check lengths, to ensure we re-extract if packages were removed.
        loaded = packages.get_loaded_packages()
        if len(loaded.packages) != len(self.mod_times):
            LOGGER.info('Need to extract - package counts inconsistent!')
            return True

        return any(
            pack.is_stale(self.mod_times.get(pack_id.casefold(), 0))
            for pack_id, pack in
            loaded.packages.items()
        )

    def refresh_cache(self, already_copied: set[str]) -> None:
        """Copy over the resource files into this game.

        already_copied is passed from copy_mod_music(), to
        indicate which files should remain. It is the full path to the files.
        """
        screen_func = export_screen.step
        packset = packages.get_loaded_packages()

        for pack in packset.packages.values():
            if not pack.enabled:
                continue
            for file in pack.fsys.walk_folder('resources'):
                try:
                    res, start_folder, path = file.path.split('/', 2)
                except ValueError:
                    LOGGER.warning('File in resources root: "{}"!', file.path)
                    continue
                assert res.casefold() == 'resources', file.path

                start_folder = start_folder.casefold()

                if start_folder == 'instances':
                    dest = self.abs_path(INST_PATH + '/' + path.casefold())
                elif start_folder in ('bee2', 'music_samp'):
                    screen_func('RES', start_folder)
                    continue  # Skip app icons and music samples.
                else:
                    # Preserve original casing.
                    dest = self.abs_path(os.path.join('bee2', start_folder, path))

                # Already copied from another package.
                if dest.casefold() in already_copied:
                    screen_func('RES', dest)
                    continue
                already_copied.add(dest.casefold())

                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with file.open_bin() as fsrc, open(dest, 'wb') as fdest:
                    shutil.copyfileobj(fsrc, fdest)
                screen_func('RES', file.path)

        LOGGER.info('Cache copied.')

        for path in [INST_PATH, 'bee2']:
            abs_path = self.abs_path(path)
            for dirpath, dirnames, filenames in os.walk(abs_path):
                for filename in filenames:
                    # Keep VMX backups, disabled editor models, and the coop
                    # gun instance.
                    if filename.endswith(('.vmx', '.mdl_dis', 'tag_coop_gun.vmf')):
                        continue
                    path = os.path.join(dirpath, filename)

                    if path.casefold() not in already_copied:
                        LOGGER.info('Deleting: {}', path)
                        os.remove(path)

        # Save the new cache modification date.
        self.mod_times.clear()
        for pack_id, pack in packset.packages.items():
            self.mod_times[pack_id.casefold()] = pack.get_modtime()
        self.save()
        CONFIG.save_check()

    async def clear_cache(self) -> None:
        """Remove all resources from the game."""
        shutil.rmtree(self.abs_path(INST_PATH), ignore_errors=True)
        shutil.rmtree(self.abs_path('bee2/'), ignore_errors=True)
        shutil.rmtree(self.abs_path('bin/bee2/'), ignore_errors=True)

        from exporting import vpks
        try:
            vpk_folder = await vpks.find_folder(self)
            vpks.clear_files(vpk_folder)
        except (vpks.NoVPKExport, PermissionError):
            pass

        self.mod_times.clear()

    async def export(
        self,
        packset: packages.PackagesSet,
        style: packages.Style,
        selected_objects: dict[Type[packages.PakObject], Any],
        should_refresh: bool = False,
    ) -> tuple[bool, bool]:
        """Generate the editoritems.txt and vbsp_config.

        - If no backup is present, the original editoritems is backed up.
        - For each object type, run its .export() function with the given
        - item.
        - Styles are a special case.
        """
        # files in compiler/
        try:
            num_compiler_files = sum(1 for file in utils.install_path('compiler').rglob('*'))
        except FileNotFoundError:
            num_compiler_files = 0

        if self.steamID == utils.STEAM_IDS['APERTURE TAG']:
            # Coop paint gun instance
            num_compiler_files += 1

        if num_compiler_files == 0:
            LOGGER.warning('No compiler files!')
            export_screen.skip_stage('COMP')
        else:
            export_screen.set_length('COMP', num_compiler_files)

        # Each object type
        # Editoritems
        # VBSP_config
        # Instance list
        # Editor models
        # Template file
        # FGD file
        # Gameinfo
        # Misc resources
        export_screen.set_length('EXP', len(packages.OBJ_TYPES) + 8)

        # Do this before setting music and resources,
        # those can take time to compute.
        export_screen.show()
        try:

            if should_refresh:
                # Count the files.
                export_screen.set_length(
                    'RES',
                    sum(
                        1
                        for pack in packset.packages.values()
                        for _ in pack.fsys.walk_folder('resources/')
                    ),
                )
            else:
                export_screen.skip_stage('RES')
                export_screen.skip_stage('MUS')

            vpk_success = True

            # Backup puzzles, if desired
            backup.auto_backup(selected_game, export_screen)

            LOGGER.info('Editing Gameinfo...')
            self.edit_gameinfo(True)
            export_screen.step('EXP', 'gameinfo')

            if not config.APP.get_cur_conf(GenOptions).preserve_fgd:
                LOGGER.info('Adding ents to FGD.')
                self.edit_fgd(True)
            export_screen.step('EXP', 'fgd')

            error_server_running = await terminate_error_server()


            if should_refresh:
                LOGGER.info('Copying Resources!')
                music_files = self.copy_mod_music()
                self.refresh_cache(music_files)

            self.exported_style = style.id
            save()

            export_screen.reset()  # Hide loading screen, we're done
            return True, vpk_success
        except loadScreen.Cancelled:
            return False, False

    def launch(self) -> None:
        """Try and launch the game."""
        webbrowser.open('steam://rungameid/' + str(self.steamID))

    def get_game_lang(self) -> str:
        """Load the app manifest file to determine Portal 2's language."""
        # We need to first figure out what language is used (if not English),
        # then load in the file. This is saved in the 'appmanifest'.
        try:
            appman_file = open(self.abs_path('../../appmanifest_620.acf'))
        except FileNotFoundError:
            # Portal 2 isn't here...
            return 'en'
        with appman_file:
            appman = Keyvalues.parse(appman_file, 'appmanifest_620.acf')
        try:
            return appman.find_key('AppState').find_key('UserConfig')['language']
        except LookupError:
            return ''

    def get_export_text(self) -> TransToken:
        """Return the text to use on export button labels."""
        return (
            TRANS_EXPORT_BTN_DIRTY if self.cache_invalid() else TRANS_EXPORT_BTN
        ).format(game=self.name)


def find_steam_info(game_dir: str) -> tuple[str | None, str | None]:
    """Determine the steam ID and game name of this folder, if it has one.

    This only works on Source games!
    """
    game_id: str | None = None
    name: str | None = None
    found_name = False
    found_id = False
    for folder in os.listdir(game_dir):
        info_path = os.path.join(game_dir, folder, 'gameinfo.txt')
        if os.path.isfile(info_path):
            with open(info_path) as file:
                for line in file:
                    clean_line = srctools.clean_line(line).replace('\t', ' ')
                    if not found_id and 'steamappid' in clean_line.casefold():
                        raw_id = clean_line.casefold().replace(
                            'steamappid', '').strip()
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


def app_in_game_error() -> None:
    """Display a message warning about the issues with placing the BEE folder directly in P2."""
    tk_tools.showerror(
        message=TransToken.ui(
            "It appears that the BEE2 application was installed directly in a game directory. "
            "The bee2/ folder name is used for exported resources, so this will cause issues.\n\n"
            "Move the application folder elsewhere, then re-run."
        ),
    )


def save() -> None:
    for gm in all_games:
        gm.save()
    CONFIG.save_check()


def load() -> None:
    global selected_game
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
        if not add_game():
            # they cancelled, quit
            quit_application()
        loadScreen.main_loader.unsuppress()  # Show it again
    selected_game = all_games[0]


def add_game(e: Event = None) -> bool:
    """Ask for, and load in a game to export to."""
    title = TransToken.ui('BEE2 - Add Game')
    tk_tools.showinfo(
        title,
        TransToken.ui(
            'Select the folder where the game executable is located ({appname})...'
        ).format(appname='portal2' + EXE_SUFFIX),
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
        gm_id, name = find_steam_info(folder)
        if name is None or gm_id is None:
            tk_tools.showerror(title, TransToken.ui(
                'This does not appear to be a valid game folder!'
            ))
            return False

        # Mel doesn't use PeTI, so that won't make much sense...
        if gm_id == utils.STEAM_IDS['MEL']:
            tk_tools.showerror(title, TransToken.ui(
                "Portal Stories: Mel doesn't have an editor!"
            ))
            return False

        invalid_names = [gm.name for gm in all_games]
        while True:
            name = tk_tools.prompt(
                title,
                TransToken.ui("Enter the name of this game:"),
                initialvalue=name,
            )
            if name in invalid_names:
                tk_tools.showerror(title, TransToken.ui('This name is already taken!'))
            elif name is None:
                return False
            elif name == '':
                tk_tools.showerror(title, TransToken.ui('Please enter a name for this game!'))
            else:
                break

        new_game = Game(name, gm_id, folder)
        all_games.append(new_game)
        if game_menu is not None:
            add_menu_opts(game_menu)
        save()
        return True
    return False


async def remove_game() -> None:
    """Remove the currently-chosen game from the game list."""
    global selected_game
    lastgame_mess = (
        TransToken.ui(
            'Are you sure you want to delete "{game}"?\n'
            '(BEE2 will quit, this is the last game set!)'
        ) if len(all_games) == 1 else
        TransToken.ui('Are you sure you want to delete "{game}"?')
    )
    if tk_tools.askyesno(
        title=TransToken.ui('BEE2 - Remove Game'),
        message=lastgame_mess.format(game=selected_game.name),
    ):
        await terminate_error_server()
        selected_game.edit_gameinfo(add_line=False)
        selected_game.edit_fgd(add_lines=False)
        await restore_backup(selected_game)
        await selected_game.clear_cache()

        all_games.remove(selected_game)
        CONFIG.remove_section(selected_game.name)
        CONFIG.save()

        if not all_games:
            quit_application()  # If we have no games, nothing can be done

        selected_game = all_games[0]
        selectedGame_radio.set(0)
        add_menu_opts(game_menu)


def add_menu_opts(menu: Menu) -> None:
    """Add the various games to the menu."""
    for ind in range(menu.index(END), 0, -1):
        # Delete all the old radiobutton
        # Iterate backward to ensure indexes stay the same.
        if menu.type(ind) == RADIOBUTTON:
            menu.delete(ind)

    for val, game in enumerate(all_games):
        menu.add_radiobutton(
            label=game.name,
            variable=selectedGame_radio,
            value=val,
            command=setGame,
        )
    setGame()


def setGame() -> None:
    global selected_game
    selected_game = all_games[selectedGame_radio.get()]
    # TODO: make this function async to eliminate.
    background_run(ON_GAME_CHANGED, selected_game)


def set_game_by_name(name: str) -> None:
    global selected_game
    for game in all_games:
        if game.name == name:
            selected_game = game
            selectedGame_radio.set(all_games.index(game))
            # TODO: make this function async too to eliminate.
            background_run(ON_GAME_CHANGED, selected_game)
            break

if __name__ == '__main__':
    Button(TK_ROOT, text='Add', command=add_game).grid(row=0, column=0)
    Button(TK_ROOT, text='Remove', command=lambda: background_run(remove_game)).grid(row=0, column=1)
    test_menu = Menu(TK_ROOT)
    dropdown = Menu(test_menu)
    test_menu.add_cascade(menu=dropdown, label='Game')
    TK_ROOT['menu'] = test_menu

    load()
    add_menu_opts(dropdown)
