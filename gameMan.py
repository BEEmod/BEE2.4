'''
Handles locating parts of a given game, and modifying GameInfo to support our special content folder.
'''
import os
import os.path

from property_parser import Property
import utils

games = {}

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
        for folder in self.dlc_priority():
            info_path = os.path.join(self.root, folder, 'gameinfo.txt')
            if os.path.isfile(info_path):
                with open(info_path, 'r') as file:
                    data=list(file)
                found_section=False
                for line_num, line in enumerate(data):
                    clean_line = utils.clean_line(line)
                    if add_line:
                        if clean_line.casefold() == 'searchpaths':
                            found_section=True
                        elif clean_line == GAMEINFO_LINE:
                            break # Already added!
                        elif found_section and clean_line == '{':
                            # Match the next line's indentation (braces usually use different indent)
                            indent = utils.get_indent(data[line_num+1])
                            data.insert(line_num+1, indent + GAMEINFO_LINE + '\n')
                            break
                    else:
                        if clean_line == GAMEINFO_LINE:
                            data.pop(line_num)
                            break
                else:
                    if add_line:
                        print('Failed editing "' + info_path + '" to add our special folder!')
                    continue
                    
            with open(info_path, 'w') as file:
                for line in data:
                    file.write(line)
                    
gm = Game('P2', r'F:\SteamLibrary\SteamApps\common\Portal 2\\')
gm.edit_gameinfo(1)