'''
Handles locating parts of a given game, and modifying GameInfo to support our special content folder.
'''
import os
import os.path
import shutil
from config import ConfigFile

from tkinter import * # ui library
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc

from property_parser import Property
import utils

all_games = []
selected_game = None
root = None

trans_data = {}

config = ConfigFile('games.cfg')

def load_trans_data():
    global trans_data
    try:
        with open('config/basemodui.txt', "r") as trans:
            trans_data = Property.parse(trans, 'config/basemodui.txt')
        trans_data = Property('',trans_data).as_dict()['lang']['Tokens']
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
        return os.path.join(self.root, path)
        
    def edit_gameinfo(self, add_line=False):
        '''Modify all gameinfo.txt files to add or remove our line.
        
        Add_line determines if we are adding or removing it.
        '''
        game_id = ''
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
                        
    def refresh_cache(self):
        dest = os.path.join(self.root, 'sdk_content/maps/instances/BEE2')
        if os.path.isdir('inst_cache/'):
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree('inst_cache/', dest)
            
    def export(self, style, all_items, music, skybox, goo, voice, styleVars):
        '''Generate the editoritems.txt and vbsp_config for the selected style and items.'''
        print('--------------------')
        print('Exporting Items and Style for ' + self.name + '!')
        print(style, music, goo, voice)
        print([key + ' = ' + str(val.get()) for key,val in styleVars.items()])
        
        editoritems = style.editor[:]
        vbsp_config = style.config[:]
        
        for item in sorted(all_items):
            editor_part, config_part = all_items[item].export()
            editoritems.extend(editor_part)
            vbsp_config.extend(config_part)
        
        vbsp_config.append(Property('StyleVars',
            [Property(key,str(val.get())) for key,val in styleVars.items()]))
         
        editor_path = self.abs_path('portal2_dlc2/scripts/editoritems.txt')
        editor_backup_path = self.abs_path('portal2_dlc2/scripts/editoritems_original.txt')
        
        if os.path.isfile(editor_path) and not os.path.isfile(editor_backup_path):
            print('Backing up original editoritems!')
            shutil.move(editor_path, editor_backup_path)
            
        print('Writing Editoritems!')
        with open(self.abs_path('portal2_dlc2/scripts/editoritems.txt'), 'w') as editor_file:
            for prop in editoritems:
                for line in prop.to_strings():
                    editor_file.write(line + '\n')
                    
        print('Writing VBSP Config!')
        with open(self.abs_path('bin/vbsp_config.cfg'), 'w') as vbsp_file:
            for prop in vbsp_config:
                for line in prop.to_strings():
                    vbsp_file.write(line +'\n')
                        
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
                        ind =clean_line.casefold().rfind('game') + 4
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

def load():
    all_games.clear()
    for gm in config:
        if gm != 'DEFAULT':
            try:
                all_games.append(Game(gm, int(config[gm]['SteamID']), config[gm]['Dir']))
            except ValueError:
                pass
    selected_game = all_games[0]
        
def find_game(e=None):
    '''Ask for, and load in a game to export to.'''
    messagebox.showinfo(message='Select the folder where the game executable is located (portal2.exe)...', parent=root)
    exe_loc = filedialog.askopenfilename(title='Find Game Exe', filetypes=[('Executable', '.exe')], initialdir='C:')
    if exe_loc:
        folder = os.path.dirname(exe_loc)
        id, name = find_steam_info(folder)
        if name == "ERR" or id == -1:
            messagebox.showinfo(message='This does not appear to be a valid game folder!', parent=root, icon=messagebox.ERROR)
            return
            
        new_game = Game(name, id, folder)
        new_game.refresh_cache()
        all_games.append(new_game)
        save()
        
    
def remove_game(e=None):
    '''Remove the currently-chosen game from the game list.'''
    if len(all_games) <= 1:
        messagebox.showerror(message='You cannot remove every game from the list!', title='BEE2', parent=root)
    else:
        all_games.remove(selected_game)
        selected_game = all_games[0]
        
def add_menu_opts(menu, callback):
    '''Add the various games to the menu.'''
    global selectedGame_radio, setgame_callback
    setgame_callback = callback
    selectedGame_radio = IntVar(value=0)
    for val, game in enumerate(all_games):
        menu.add_radiobutton(label=game.name, variable=selectedGame_radio, value=val, command=setGame)
    setGame()
        
def setGame():
    global selected_game
    selected_game = all_games[selectedGame_radio.get()]
    setgame_callback(selected_game)
       
if __name__ == '__main__':
    root = Tk()
    Button(root, text = 'Add', command=find_game).grid(row=0, column=0)
    Button(root, text = 'Remove', command=remove_game).grid(row=0, column=1)
    g1 = Game("Portal 2", 620, r"F:\SteamLibrary\SteamApps\common\Portal 2")