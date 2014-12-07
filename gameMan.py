'''
Handles locating parts of a given game, and modifying GameInfo to support our special content folder.
'''
import os
import os.path

from tkinter import * # ui library
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc

from property_parser import Property
import utils

all_games = []
root = None

def game_set(game):
    pass

# The line we inject to add our BEE2 folder into the game search path. 
# We always add ours such that it's the highest priority.
GAMEINFO_LINE = 'Game\t"BEE2"'

class Game:
    def __init__(self, name, folder):
        self.name = name
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
                        
def load(games):
    for gm in games:
        all_games.append(Game(gm['Name'], gm['Dir']))
        
def as_props():
    return [Property("Game", [
            Property("Name", gm.name),
            Property("Dir", gm.root)]) for gm in all_games]
        
def find_game(e=None):
    '''Ask for, and load in a game to export to.'''
    mesaagebox.showinfo(message='Select the folder where 
    
def remove_game(e=None):
    '''Remove the currently-chosen game from the game list.'''
    if len(all_games) <= 1:
        messagebox.showerror(message='You cannot remove every game from the list!', title='BEE2', parent=root)
        
def add_menu_opts(menu):
    global selectedGame_radio
    selectedGame_radio = IntVar(value=0)
    for val, game in enumerate(all_games): 
        menu.add_radiobutton(label=game.name, variable=selectedGame_radio, value=val, command=setGame)
        
def setGame():
    pass
       
if __name__ == '__main__':
    root = Tk()
    Button(root, text = 'Add', command=find_game).grid(row=0, column=0)
    Button(root, text = 'Remove', command=remove_game).grid(row=0, column=1)