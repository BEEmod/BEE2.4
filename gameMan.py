'''
Handles locating parts of a given game, and modifying GameInfo to support our special content folder.
'''
import os
import os.path
import shutil
from config import ConfigFile

from tkinter import * # ui library
from tkinter import ttk
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc

from property_parser import Property
import utils

all_games = []
selected_game = None
selectedGame_radio = None 
root = None # This should be set to the Tk() root instance
game_menu = None

trans_data = {}

config = ConfigFile('games.cfg')

FILES_TO_BACKUP = [
    ('Editoritems', 'portal2_dlc2/scripts/editoritems', '.txt'),
    ('VBSP',        'bin/vbsp',                         '.exe'),
    ('VRAD',        'bin/vrad',                         '.exe')
]

_UNLOCK_ITEMS = [
    'ITEM_EXIT_DOOR',
    'ITEM_COOP_EXIT_DOOR',
    'ITEM_ENTRY_DOOR',
    'ITEM_COOP_ENTRY_DOOR',
    'ITEM_OBSERVATION_ROOM'
    ]
  
# The source and desination locations of resources that must be copied 
# into the game folder.
CACHE_LOC = [
    ('inst_cache/', 'sdk_content/maps/instances/BEE2'),
    ('source_cache/', 'BEE2/'),
    ]

def init(tk):
    global trans_data, selectedGame_radio, root
    root = tk
    selectedGame_radio = IntVar(value=0)
    try:
        with open('config/basemodui.txt', "r") as trans:
            trans_data = Property.parse(trans, 'config/basemodui.txt')
        trans_data = trans_data.as_dict()['lang']['Tokens']
    except IOError:
        pass

def translate(str):
    return trans_data.get(str, str)
    
def setgame_callback(selected_game):
    pass

# The line we inject to add our BEE2 folder into the game search path. 
# We always add ours such that it's the highest priority.
GAMEINFO_LINE = 'Game\t"BEE2"'

class Game:
    def __init__(self, name, id, folder):
        self.name = name
        self.steamID = id
        self.root = folder
        
    def dlc_priority(self):
        '''Iterate through all subfolders, in order of priority, from high to low.
        
        We assume the priority follows [update, portal2_dlcN, portal2_dlc2, portal2_dlc1, portal2, <all others>]
        '''
        dlc_count = 1
        priority = ["portal2"]
        while os.path.isdir(self.abs_path("portal2_dlc" + str(dlc_count))):
            priority.append("portal2_dlc" + str(dlc_count))
            dlc_count+=1
        if os.path.isdir(self.abs_path("update")):
            priority.append("update")
        blacklist = ("bin", "Soundtrack", "sdk_tools", "sdk_content") # files are definitely not here
        yield from reversed(priority)
        for folder in os.listdir(self.root):
            if os.path.isdir(self.abs_path(folder)) and folder not in priority and folder not in blacklist:
                yield folder
        
    def abs_path(self, path):
        return os.path.normcase(os.path.join(self.root, path))
        
    def is_modded(self):
        return os.path.isfile(self.abs_path('BEE2_EDIT_FLAG'))
        
    def edit_gameinfo(self, add_line=False):
        '''Modify all gameinfo.txt files to add or remove our line.
        
        Add_line determines if we are adding or removing it.
        '''
        
        if self.is_modded() == add_line:
            # It's already in the correct state!
            return
        
        for folder in self.dlc_priority():
            info_path = os.path.join(self.root, folder, 'gameinfo.txt')
            if os.path.isfile(info_path):
                with open(info_path, 'r') as file:
                    data=list(file)
                found_section=False
                for line_num, line in reversed(list(enumerate(data))):
                    clean_line = utils.clean_line(line)
                    if add_line:
                        if clean_line == GAMEINFO_LINE:
                            break # Already added!
                        elif '|gameinfo_path|' in clean_line:
                            print("Adding gameinfo hook to " + info_path)
                            # Match the line's indentation
                            data.insert(line_num+1, utils.get_indent(line) + GAMEINFO_LINE + '\n')
                            break
                    else:
                        if clean_line == GAMEINFO_LINE:
                            print("Removing gameinfo hook from " + info_path)
                            data.pop(line_num)
                            break
                else:
                    if add_line:
                        print('Failed editing "' + info_path + '" to add our special folder!')
                    continue
                    
                with open(info_path, 'w') as file:
                    for line in data:
                        file.write(line)
        if add_line:
            with open(self.abs_path('BEE2_EDIT_FLAG'), 'w') as file:
                file.write('')
        else:
            os.remove(self.abs_path('BEE2_EDIT_FLAG'))
            # Restore the original files!
            for name, file, ext in FILES_TO_BACKUP:
                item_path = self.abs_path(file + ext)
                backup_path = self.abs_path(file + '_original' + ext)
                if os.path.isfile(backup_path):
                    print("Restoring original " + name + "!")
                    shutil.move(backup_path, item_path)
            clear_cache()
            
    def refresh_cache(self):
        '''Copy over the resource files into this game.'''
        for source, dest in CACHE_LOC:
            dest = self.abs_path(INST_LOC)
            try:
                shutil.rmtree(dest)
                shutil.copytree(source, dest)
            except (IOError, shutil.Error):
                pass
            
    def clear_cache(self):
        for source, dest in CACHE_LOC:
            try:
                shutil.rmtree(self.abs_path(dest))
            except (IOError, shutil.Error):
                pass
            
    def export(self, style, all_items, music, skybox, goo, voice, styleVars):
        '''Generate the editoritems.txt and vbsp_config for the selected style and items.'''
        print('--------------------')
        print('Exporting Items and Style for "' + self.name + '"!')
        print('Style =', style)
        print('Music =', music)
        print('Goo =', goo)
        print('Voice =', voice)
        print('Skybox =', skybox)
        print('Style Vars:\n  {')
        for key, val in styleVars.items():
            print('  ' + key + ' = ' + str(val))
        print('  }')
        
        vbsp_config = style.config.copy()
        
        # Editoritems.txt is composed of a "ItemData" block, holding "Item" and "Renderables" sections. 
        editoritems = Property("ItemData", *style.editor.find_all('Item'))
        
        for item in sorted(all_items):
            item_block, editor_parts, config_part = all_items[item].export()
            editoritems += item_block
            editoritems += editor_parts
            vbsp_config += config_part
            
        if voice is not None:
            vbsp_config += voice.config
            
        if skybox is not None:
            vbsp_config.set_key(('Textures', 'Special', 'Sky'), skybox.material)
            vbsp_config += skybox.config
            
        if music is not None:
            if music.sound is not None:
                vbsp_config.set_key(('Options', 'music_SoundScript'), music.sound)
            if music.inst is not None:
                vbsp_config.set_key(('Options', 'music_instance'), music.inst)
            
            vbsp_config.set_key(('Options', 'music_ID'), music.id)
            vbsp_config += music.config
            
            
        # If there are multiple of these blocks, merge them together
        vbsp_config.merge_children('Conditions', 
                                   'InstanceFiles', 
                                   'Options',
                                   'StyleVars',
                                   'Textures')
                                   
                                 
        vbsp_config.ensure_exists('StyleVars')
        vbsp_config['StyleVars'] += [Property(key, utils.bool_as_int(val)) for key,val in styleVars.items()]
        
        for name, file, ext in FILES_TO_BACKUP:
            item_path = self.abs_path(file + ext)
            backup_path = self.abs_path(file + '_original' + ext)
            if os.path.isfile(item_path) and not os.path.isfile(backup_path):
                print('Backing up original ' + name + '!')
                shutil.copy(item_path, backup_path)
                
        editoritems += style.editor.find_key("Renderables", [])
        
        if styleVars.get('UnlockDefault', False):
            print('Unlocking Items!')
            for item in editoritems.find_all('Item'):
                # If the Unlock Default Items stylevar is enabled, we
                # want to force the corridors and obs room to be
                # deletable and copyable
                if item['type', ''] in _UNLOCK_ITEMS:
                    for prop in item.find_key("Editor", []):
                        if prop.name.casefold() in ('deletable', 'copyable'):
                            prop.value = '1'
        
        print('Writing Editoritems!')
        with open(self.abs_path('portal2_dlc2/scripts/editoritems.txt'), 'w') as editor_file:
            for line in editoritems.export():
                editor_file.write(line)
   
        print('Writing VBSP Config!')
        with open(self.abs_path('bin/vbsp_config.cfg'), 'w') as vbsp_file:
            for line in vbsp_config.export():
                vbsp_file.write(line)
                        
def find_steam_info(game_dir):
    '''Determine the steam ID and game name of this folder, if it has one.
    
    This only works on Source games!
    '''
    id = -1
    name = "ERR"
    found_name = False
    found_id = False
    for folder in os.listdir(game_dir):
        info_path = os.path.join(game_dir, folder, 'gameinfo.txt')
        if os.path.isfile(info_path):
            with open(info_path, 'r') as file:
                for line in file:
                    clean_line = utils.clean_line(line).replace('\t',' ')
                    if not found_id and 'steamappid' in clean_line.casefold():
                        ID = clean_line.casefold().replace('steamappid', '').strip()
                        try:
                            id = int(ID)
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
    return id, name
    
def save():
    for gm in all_games:
        if gm.name not in config:
            config[gm.name] = {}
        config[gm.name]['SteamID'] = str(gm.steamID)
        config[gm.name]['Dir'] = gm.root
    config.save()

def load(UI_quit_func, loadScreen_window):
    all_games.clear()
    for gm in config:
        if gm != 'DEFAULT':
            try:
                new_game = Game(gm, int(config[gm]['SteamID']), config[gm]['Dir'])
            except ValueError:
                pass
            else:
                all_games.append(new_game)
                new_game.edit_gameinfo(True)
    if len(all_games) == 0:
        # Hide the loading screen, since it appears on top
        loadScreen_window.withdraw()
        
        # Ask the user for Portal 2's location...
        if not add_game(refresh_menu=False):
            # they cancelled, quit
            UI_quit_func()
        loadScreen_window.deiconify()
    selected_game = all_games[0]
        
def add_game(e=None, refresh_menu=True):
    '''Ask for, and load in a game to export to.'''
    
    messagebox.showinfo(
        message='Select the folder where the game executable is located '
                '(portal2.exe)...',
        parent=root,
        )
    exe_loc = filedialog.askopenfilename(
        title='Find Game Exe',
        filetypes=[('Executable', '.exe')],
        initialdir='C:',
        )
    if exe_loc:
        folder = os.path.dirname(exe_loc)
        id, name = find_steam_info(folder)
        if name == "ERR" or id == -1:
            messagebox.showinfo(
                message='This does not appear to be a valid game folder!', 
                parent=root, 
                icon=messagebox.ERROR,
                )
            return False
        invalid_names = [gm.name for gm in all_games]
        while True:
            name = simpledialog.askstring(
                prompt="Enter the name of this game:", 
                title="BEE2",
                )
            if name in invalid_names:
                messagebox.showinfo(
                    icon=messagebox.ERROR, 
                    parent=root,
                    message='This name is already taken!',
                    )
            elif name == '':
                messagebox.showinfo(
                    icon=messagebox.ERROR, 
                    parent=root,
                    message='Please enter a name for this game!',
                    )
            else:
                break
            
        new_game = Game(name, id, folder)
        new_game.edit_gameinfo(add_line=True)
        all_games.append(new_game)
        if refresh_menu:
            add_menu_opts(game_menu)
        save()
        return True
    
def remove_game(e=None):
    '''Remove the currently-chosen game from the game list.'''
    global selected_game, selectedGame_radio
    if messagebox.askyesno(title="BEE2", message='Are you sure you want to delete "' + selected_game.name + '"?'):
        if len(all_games) <= 1:
            messagebox.showerror(message='You cannot remove every game from the list!', title='BEE2', parent=root)
        else:
            selected_game.edit_gameinfo(add_line=False)
            
            all_games.remove(selected_game)
            config.remove_section(selected_game.name)
            config.save()
            
            selected_game = all_games[0]
            selectedGame_radio.set(0)
            add_menu_opts(game_menu)
        
def add_menu_opts(menu, callback=None):
    '''Add the various games to the menu.'''
    global selectedGame_radio, setgame_callback
    if callback is not None:
        setgame_callback = callback
    menu.delete(menu.game_pos, 999)
    for val, game in enumerate(all_games):
        menu.add_radiobutton(label=game.name, variable=selectedGame_radio, value=val, command=setGame)
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
    root = Tk()
    Button(root, text = 'Add', command=add_game).grid(row=0, column=0)
    Button(root, text = 'Remove', command=remove_game).grid(row=0, column=1)
    menu = Menu(root)
    dropdown = Menu(menu)
    menu.add_cascade(menu=dropdown, label='Game')
    dropdown.game_pos = 0
    root['menu'] = menu
    
    init(root)
    load(quit, Toplevel())
    add_menu_opts(dropdown, setgame_callback)