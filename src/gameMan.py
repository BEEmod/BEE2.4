"""
Does stuff related to the actual games.
- Adding and removing games
- Handles locating parts of a given game,
- Modifying GameInfo to support our special content folder.
- Generating and saving editoritems/vbsp_config
"""
import os
import os.path
import shutil

from tkinter import *  # ui library
from tkinter import messagebox  # simple, standard modal dialogs
from tkinter import filedialog  # open/save as dialog creator
from tk_tools import TK_ROOT

from query_dialogs import ask_string
from BEE2_config import ConfigFile
from property_parser import Property
import utils
import loadScreen
import packageLoader
import extract_packages
import backup

all_games = []
selected_game = None  # type: Game
selectedGame_radio = IntVar(value=0)
game_menu = None

trans_data = {}

config = ConfigFile('games.cfg')

FILES_TO_BACKUP = [
    ('Editoritems', 'portal2_dlc2/scripts/editoritems', '.txt'),
    ('VBSP',        'bin/vbsp',                         '.exe'),
    ('VRAD',        'bin/vrad',                         '.exe'),
    ('VBSP',        'bin/vbsp_osx',   ''),
    ('VRAD',        'bin/vrad_osx',   ''),
    ('VBSP',        'bin/vbsp_linux', ''),
    ('VRAD',        'bin/vrad_linux', ''),
]

VOICE_PATHS = [
    ('', '', 'normal'),
    ('MID_', 'mid_', 'MidChamber'),
]

_UNLOCK_ITEMS = [
    'ITEM_EXIT_DOOR',
    'ITEM_COOP_EXIT_DOOR',
    'ITEM_ENTRY_DOOR',
    'ITEM_COOP_ENTRY_DOOR',
    'ITEM_OBSERVATION_ROOM'
    ]

# The location of all the instances in the game directory
INST_PATH = 'sdk_content/maps/instances/BEE2'

# The line we inject to add our BEE2 folder into the game search path.
# We always add ours such that it's the highest priority, other
# than '|gameinfo_path|.'
GAMEINFO_LINE = 'Game\t"BEE2"'

# We inject this line to recognise where our sounds start, so we can modify
# them.
EDITOR_SOUND_LINE = '// BEE2 SOUNDS BELOW'


# The progress bars used when exporting data into a game
export_screen = loadScreen.LoadScreen(
    ('BACK', 'Backup Original Files'),
    (backup.AUTO_BACKUP_STAGE, 'Backup Puzzles'),
    ('CONF', 'Generate Config Files'),
    ('COMP', 'Copy Compiler'),
    ('RES', 'Copy Resources'),
    title_text='Exporting',
)


def init_trans():
    """Load a copy of basemodui, used to translate item strings.

    Valve's items use special translation strings which would look ugly
    if we didn't convert them.
    """
    global trans_data
    try:
        with open('../basemodui.txt') as trans:
            trans_prop = Property.parse(trans, 'basemodui.txt')
        trans_data = {
            item.real_name: item.value
            for item in
            trans_prop.find_key("lang", []).find_key("tokens", [])
        }
    except IOError:
        pass


def translate(string):
    return trans_data.get(string, string)


def setgame_callback(selected_game):
    """Callback function run when games are selected."""
    pass


def quit_application():
    """Command run to quit the application.

    This is overwritten by UI later.
    """
    import sys
    sys.exit()


class Game:
    def __init__(self, name, steam_id, folder):
        self.name = name
        self.steamID = steam_id
        self.root = folder

    def dlc_priority(self):
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

    def abs_path(self, path):
        return os.path.normcase(os.path.join(self.root, path))

    def add_editor_sounds(self, sounds):
        """Add soundscript items so they can be used in the editor."""
        # PeTI only loads game_sounds_editor, so we must modify that.
        # First find the highest-priority file
        for folder in self.dlc_priority():
            file = self.abs_path(os.path.join(
                folder,
                'scripts',
                'game_sounds_editor.txt'
            ))
            if os.path.isfile(file):
                break # We found it
        else:
            # Assume it's in dlc2
            file = self.abs_path(os.path.join(
                'portal2_dlc2',
                'scripts',
                'game_sounds_editor.txt',
            ))
        try:
            with open(file) as f:
                file_data = list(f)
        except FileNotFoundError:
            # If the file doesn't exist, we'll just write our stuff in.
            file_data = []
        for i, line in enumerate(file_data):
            if line.strip() == EDITOR_SOUND_LINE:
                # Delete our marker line and everything after it
                del file_data[i:]

        # Then add our stuff!
        with open(file, 'w') as f:
            f.writelines(file_data)
            f.write(EDITOR_SOUND_LINE + '\n')
            for sound in sounds:
                for line in sound.data.export():
                    f.write(line)
                f.write('\n')  # Add a little spacing

    def edit_gameinfo(self, add_line=False):
        """Modify all gameinfo.txt files to add or remove our line.

        Add_line determines if we are adding or removing it.
        """

        for folder in self.dlc_priority():
            info_path = os.path.join(self.root, folder, 'gameinfo.txt')
            if os.path.isfile(info_path):
                with open(info_path) as file:
                    data = list(file)

                for line_num, line in reversed(list(enumerate(data))):
                    clean_line = utils.clean_line(line)
                    if add_line:
                        if clean_line == GAMEINFO_LINE:
                            break  # Already added!
                        elif '|gameinfo_path|' in clean_line:
                            print("Adding gameinfo hook to " + info_path)
                            # Match the line's indentation
                            data.insert(
                                line_num+1,
                                utils.get_indent(line) + GAMEINFO_LINE + '\n',
                                )
                            break
                    else:
                        if clean_line == GAMEINFO_LINE:
                            print("Removing gameinfo hook from " + info_path)
                            data.pop(line_num)
                            break
                else:
                    if add_line:
                        print(
                            'Failed editing "' +
                            info_path +
                            '" to add our special folder!'
                        )
                    continue

                with open(info_path, 'w') as file:
                    for line in data:
                        file.write(line)
        if not add_line:
            # Restore the original files!
            for name, file, ext in FILES_TO_BACKUP:
                item_path = self.abs_path(file + ext)
                backup_path = self.abs_path(file + '_original' + ext)
                old_version = self.abs_path(file + '_styles' + ext)
                if os.path.isfile(old_version):
                    print("Restoring Stylechanger version of " + name + "!")
                    shutil.copy(old_version, item_path)
                elif os.path.isfile(backup_path):
                    print("Restoring original " + name + "!")
                    shutil.move(backup_path, item_path)
            self.clear_cache()

    def refresh_cache(self):
        """Copy over the resource files into this game."""

        screen_func = export_screen.step
        copy2 = shutil.copy2

        def copy_func(src, dest):
            screen_func('RES')
            copy2(src, dest)

        for folder in os.listdir('../cache/resources/'):
            source = os.path.join('../cache/resources/', folder)
            if folder == 'instances':
                dest = self.abs_path(INST_PATH)
            elif folder.casefold() == 'bee2':
                continue  # Skip app icons
            else:
                dest = self.abs_path(os.path.join('bee2', folder))
            print('Copying to "' + dest + '" ...', end='')
            try:
                shutil.rmtree(dest)
            except (IOError, shutil.Error):
                pass

            shutil.copytree(source, dest, copy_function=copy_func)
            print(' Done!')

    def clear_cache(self):
        """Remove all resources from the game."""
        shutil.rmtree(self.abs_path(INST_PATH), ignore_errors=True)
        shutil.rmtree(self.abs_path('bee2/'), ignore_errors=True)
        shutil.rmtree(self.abs_path('bin/bee2/'), ignore_errors=True)

    def export(
            self,
            style,
            all_items,
            music,
            skybox,
            voice,
            style_vars,
            elevator,
            pack_list,
            editor_sounds,
            should_refresh=False,
            ):
        """Generate the editoritems.txt and vbsp_config.

        - If no backup is present, the original editoritems is backed up
        - We unlock the mandatory items if specified
        -
        """
        print('-' * 20)
        print('Exporting Items and Style for "' + self.name + '"!')
        print('Style =', style)
        print('Music =', music)
        print('Voice =', voice)
        print('Skybox =', skybox)
        print('Elevator = ', elevator)
        print('Style Vars:\n  {')
        for key, val in style_vars.items():
            print('  {} = {!s}'.format(key, val))
        print('  }')
        print(len(pack_list), 'Pack Lists!')
        print(len(editor_sounds), 'Editor Sounds!')
        print('-' * 20)

        # VBSP, VRAD, editoritems
        export_screen.set_length('BACK', len(FILES_TO_BACKUP))
        export_screen.set_length(
            'CONF',
            # VBSP_conf, Editoritems, instances, gameinfo, pack_lists,
            # editor_sounds, template VMF
            7 +
            # Don't add the voicelines to the progress bar if not selected
            (0 if voice is None else len(VOICE_PATHS)),
        )
        # files in compiler/
        export_screen.set_length('COMP', len(os.listdir('../compiler')))

        if should_refresh:
            export_screen.set_length('RES', extract_packages.res_count)
        else:
            export_screen.skip_stage('RES')

        export_screen.show()
        export_screen.grab_set_global()  # Stop interaction with other windows

        vbsp_config = style.config.copy()

        # Editoritems.txt is composed of a "ItemData" block, holding "Item" and
        # "Renderables" sections.
        editoritems = Property("ItemData", list(style.editor.find_all('Item')))

        for item in sorted(all_items):
            item_block, editor_parts, config_part = all_items[item].export()
            editoritems += item_block
            editoritems += editor_parts
            vbsp_config += config_part

        if voice is not None:
            vbsp_config += voice.config

        if skybox is not None:
            vbsp_config.set_key(
                ('Textures', 'Special', 'Sky'),
                skybox.material,
            )
            vbsp_config += skybox.config

        if style.has_video:
            if elevator is None:
                # Use a randomised video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'RAND',
                )
            elif elevator.id == 'VALVE_BLUESCREEN':
                # This video gets a special script and handling
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'BSOD',
                )
            else:
                # Use the particular selected video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'FORCE',
                )
                vbsp_config.set_key(
                    ('Elevator', 'horiz'),
                    elevator.horiz_video,
                )
                vbsp_config.set_key(
                    ('Elevator', 'vert'),
                    elevator.vert_video,
                )
        else:  # No elevator video for this style
            vbsp_config.set_key(
                ('Elevator', 'type'),
                'NONE',
            )

        if music is not None:
            if music.sound is not None:
                vbsp_config.set_key(
                    ('Options', 'music_SoundScript'),
                    music.sound,
                )
            if music.inst is not None:
                vbsp_config.set_key(
                    ('Options', 'music_instance'),
                    music.inst,
                )
            if music.packfiles:
                vbsp_config.set_key(
                    ('PackTriggers', 'Forced'),
                    [
                        Property('File', file)
                        for file in
                        music.packfiles
                    ],
                )

            vbsp_config.set_key(('Options', 'music_ID'), music.id)
            vbsp_config += music.config

        if voice is not None:
            vbsp_config.set_key(
                ('Options', 'voice_pack'),
                voice.id,
            )
            vbsp_config.set_key(
                ('Options', 'voice_char'),
                ','.join(voice.chars)
            )
            if voice.cave_skin is not None:
                vbsp_config.set_key(
                    ('Options', 'cave_port_skin'),
                    voice.cave_skin,
                )

        vbsp_config.set_key(
            ('Options', 'BEE2_loc'),
            os.path.dirname(os.getcwd())  # Go up one dir to our actual location
        )
        vbsp_config.set_key(
            ('Options', 'Game_ID'),
            self.steamID,
        )

        vbsp_config.ensure_exists('StyleVars')
        vbsp_config['StyleVars'] += [
            Property(key, utils.bool_as_int(val))
            for key, val in
            style_vars.items()
        ]

        pack_block = Property('PackList', [])
        # A list of materials which will casue a specific packlist to be used.
        pack_triggers = Property('PackTriggers', [])

        for key, pack in pack_list.items():
            pack_block.append(Property(
                key,
                [
                    Property('File', file)
                    for file in
                    pack.files
                ]
            ))
            for trigger_mat in pack.trigger_mats:
                pack_triggers.append(
                    Property('Material', [
                        Property('Texture', trigger_mat),
                        Property('PackList', pack.id),
                    ])
                )
        if pack_triggers.value:
            vbsp_config.append(pack_triggers)

        # If there are multiple of these blocks, merge them together
        # They will end up in this order.
        vbsp_config.merge_children(
            'Textures',
            'Fizzler',
            'Options',
            'StyleVars',
            'Conditions',
            'Voice',
            'PackTriggers',
        )

        for name, file, ext in FILES_TO_BACKUP:
            item_path = self.abs_path(file + ext)
            backup_path = self.abs_path(file + '_original' + ext)
            if os.path.isfile(item_path) and not os.path.isfile(backup_path):
                print('Backing up original ' + name + '!')
                shutil.copy(item_path, backup_path)
            export_screen.step('BACK')

        # Backup puzzles, if desired
        backup.auto_backup(selected_game, export_screen)

        # This is the connections "heart" icon and "error" icon
        editoritems += style.editor.find_key("Renderables", [])

        # Build a property tree listing all of the instances for each item
        all_instances = Property("AllInstances", [])
        for item in editoritems.find_all("Item"):
            item_prop = Property(item['Type'], [])
            all_instances.append(item_prop)
            for inst_block in item.find_all("Exporting", "instances"):
                for inst in inst_block:
                    item_prop.append(
                        Property('Instance', inst['Name'])
                    )

        if style_vars.get('UnlockDefault', False):
            print('Unlocking Items!')
            for item in editoritems.find_all('Item'):
                # If the Unlock Default Items stylevar is enabled, we
                # want to force the corridors and obs room to be
                # deletable and copyable
                # Also add DESIRES_UP, so they place in the correct orientation
                if item['type', ''] in _UNLOCK_ITEMS:
                    editor_section = item.find_key("Editor", [])
                    editor_section['deletable'] = '1'
                    editor_section['copyable'] = '1'
                    editor_section['DesiredFacing'] = 'DESIRES_UP'

        print('Editing Gameinfo!')
        self.edit_gameinfo(True)

        export_screen.step('CONF')

        print('Writing Editoritems!')
        os.makedirs(self.abs_path('portal2_dlc2/scripts/'), exist_ok=True)
        with open(self.abs_path(
                'portal2_dlc2/scripts/editoritems.txt'), 'w') as editor_file:
            for line in editoritems.export():
                editor_file.write(line)
        export_screen.step('CONF')

        print('Writing VBSP Config!')
        os.makedirs(self.abs_path('bin/bee2/'), exist_ok=True)
        with open(self.abs_path('bin/bee2/vbsp_config.cfg'), 'w') as vbsp_file:
            for line in vbsp_config.export():
                vbsp_file.write(line)
        export_screen.step('CONF')

        print('Writing instance list!')
        with open(self.abs_path('bin/bee2/instances.cfg'), 'w') as inst_file:
            for line in all_instances.export():
                inst_file.write(line)
        export_screen.step('CONF')

        print('Writing packing list!')
        with open(self.abs_path('bin/bee2/pack_list.cfg'), 'w') as pack_file:
            for line in pack_block.export():
                pack_file.write(line)
        export_screen.step('CONF')

        print('Editing game_sounds!')
        self.add_editor_sounds(editor_sounds.values())
        export_screen.step('CONF')

        print('Exporting {} templates!'.format(
            len(packageLoader.data['BrushTemplate'])
        ))
        with open(self.abs_path('bin/bee2/templates.vmf'), 'w') as temp_file:
            packageLoader.TEMPLATE_FILE.export(temp_file)
        export_screen.step('CONF')

        if voice is not None:
            for prefix, dest, pretty in VOICE_PATHS:
                path = os.path.join(
                    os.getcwd(),
                    '..',
                    'config',
                    'voice',
                    prefix + voice.id + '.cfg',
                )
                print(path)
                if os.path.isfile(path):
                    shutil.copy(
                        path,
                        self.abs_path('bin/bee2/{}voice.cfg'.format(dest))
                    )
                    print('Written "{}voice.cfg"'.format(dest))
                else:
                    print('No ' + pretty + ' voice config!')
                export_screen.step('CONF')

        print('Copying Custom Compiler!')
        for file in os.listdir('../compiler'):
            print('\t* compiler/{0} -> bin/{0}'.format(file))
            try:
                shutil.copy(
                    os.path.join('../compiler', file),
                    self.abs_path('bin/')
                )
            except PermissionError:
                # We might not have permissions, if the compiler is currently
                # running.
                export_screen.grab_release()
                export_screen.reset()
                messagebox.showerror(
                    title='BEE2 - Export Failed!',
                    message='Copying compiler file {file} failed.'
                            'Ensure the {game} is not running.'.format(
                                file=file,
                                game=self.name,
                            ),
                    master=TK_ROOT,
                )
                return False
            export_screen.step('COMP')

        if should_refresh:
            print('Copying Resources!')
            self.refresh_cache()

        export_screen.grab_release()
        export_screen.reset()  # Hide loading screen, we're done
        return True


def find_steam_info(game_dir):
    """Determine the steam ID and game name of this folder, if it has one.

    This only works on Source games!
    """
    game_id = -1
    name = "ERR"
    found_name = False
    found_id = False
    for folder in os.listdir(game_dir):
        info_path = os.path.join(game_dir, folder, 'gameinfo.txt')
        if os.path.isfile(info_path):
            with open(info_path) as file:
                for line in file:
                    clean_line = utils.clean_line(line).replace('\t', ' ')
                    if not found_id and 'steamappid' in clean_line.casefold():
                        raw_id = clean_line.casefold().replace(
                            'steamappid', '').strip()
                        try:
                            game_id = int(raw_id)
                        except ValueError:
                            pass
                    elif not found_name and 'game ' in clean_line.casefold():
                        found_name = True
                        ind = clean_line.casefold().rfind('game') + 4
                        name = clean_line[ind:].strip().strip('"')
                    if found_name and found_id:
                        break
        if found_name and found_id:
            break
    return game_id, name


def save():
    for gm in all_games:
        if gm.name not in config:
            config[gm.name] = {}
        config[gm.name]['SteamID'] = str(gm.steamID)
        config[gm.name]['Dir'] = gm.root
    config.save()


def load():
    global selected_game
    all_games.clear()
    for gm in config:
        if gm != 'DEFAULT':
            try:
                new_game = Game(
                    gm,
                    int(config[gm]['SteamID']),
                    config[gm]['Dir'],
                )
            except ValueError:
                pass
            else:
                all_games.append(new_game)
                new_game.edit_gameinfo(True)
    if len(all_games) == 0:
        # Hide the loading screen, since it appears on top
        loadScreen.main_loader.withdraw()

        # Ask the user for Portal 2's location...
        if not add_game(refresh_menu=False):
            # they cancelled, quit
            quit_application()
        loadScreen.main_loader.deiconify()  # Show it again
    selected_game = all_games[0]


def add_game(_=None, refresh_menu=True):
    """Ask for, and load in a game to export to."""

    messagebox.showinfo(
        message='Select the folder where the game executable is located '
                '(portal2.exe)...',
        parent=TK_ROOT,
        title='BEE2 - Add Game',
        )
    exe_loc = filedialog.askopenfilename(
        title='Find Game Exe',
        filetypes=[('Executable', '.exe')],
        initialdir='C:',
        )
    if exe_loc:
        folder = os.path.dirname(exe_loc)
        gm_id, name = find_steam_info(folder)
        if name == "ERR" or gm_id == -1:
            messagebox.showinfo(
                message='This does not appear to be a valid game folder!',
                parent=TK_ROOT,
                icon=messagebox.ERROR,
                title='BEE2 - Add Game',
                )
            return False
        invalid_names = [gm.name for gm in all_games]
        while True:
            name = ask_string(
                prompt="Enter the name of this game:",
                title='BEE2 - Add Game',
                initialvalue=name,
                )
            if name in invalid_names:
                messagebox.showinfo(
                    icon=messagebox.ERROR,
                    parent=TK_ROOT,
                    message='This name is already taken!',
                    title='BEE2 - Add Game',
                    )
            elif name is None:
                return False
            elif name == '':
                messagebox.showinfo(
                    icon=messagebox.ERROR,
                    parent=TK_ROOT,
                    message='Please enter a name for this game!',
                    title='BEE2 - Add Game',
                    )
            else:
                break

        new_game = Game(name, gm_id, folder)
        new_game.edit_gameinfo(add_line=True)
        all_games.append(new_game)
        if refresh_menu:
            add_menu_opts(game_menu)
        save()
        return True


def remove_game(_=None):
    """Remove the currently-chosen game from the game list."""
    global selected_game
    lastgame_mess = (
        "\n (BEE2 will quit, this is the last game set!)"
        if len(all_games) == 1 else
        ""
    )
    confirm = messagebox.askyesno(
        title="BEE2",
        message='Are you sure you want to delete "'
                + selected_game.name
                + '"?'
                + lastgame_mess,
        )
    if confirm:
        selected_game.edit_gameinfo(add_line=False)

        all_games.remove(selected_game)
        config.remove_section(selected_game.name)
        config.save()

        if not all_games:
            quit_application()  # If we have no games, nothing can be done

        selected_game = all_games[0]
        selectedGame_radio.set(0)
        add_menu_opts(game_menu)


def add_menu_opts(menu, callback=None):
    """Add the various games to the menu."""
    global selectedGame_radio, setgame_callback
    if callback is not None:
        setgame_callback = callback

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


def setGame():
    global selected_game
    selected_game = all_games[selectedGame_radio.get()]
    setgame_callback(selected_game)


def set_game_by_name(name):
    global selected_game, selectedGame_radio
    for game in all_games:
        if game.name == name:
            selected_game = game
            selectedGame_radio.set(all_games.index(game))
            setgame_callback(selected_game)
            break

if __name__ == '__main__':
    Button(TK_ROOT, text='Add', command=add_game).grid(row=0, column=0)
    Button(TK_ROOT, text='Remove', command=remove_game).grid(row=0, column=1)
    test_menu = Menu(TK_ROOT)
    dropdown = Menu(test_menu)
    test_menu.add_cascade(menu=dropdown, label='Game')
    dropdown.game_pos = 0
    TK_ROOT['menu'] = test_menu

    init_trans()
    load()
    add_menu_opts(dropdown, setgame_callback)