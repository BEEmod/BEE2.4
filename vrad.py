import os
import os.path
import sys
import subprocess
import shutil
import random

from property_parser import Property
import utils
    
def quote(txt):
    return '"' + txt + '"'

def run_vrad(args):
    "Execute the original VRAD."
    args = [('"' + x + '"' if " " in x else x) for x in args]
    arg = '"' + os.path.normpath(os.path.join(os.getcwd(),"vrad_original")) + '" ' + " ".join(args)
    utils.con_log("Calling original VRAD...")
    utils.con_log(arg)
    subprocess.call(arg, stdout=None, stderr=subprocess.PIPE, shell=True)
    utils.con_log("Done!")   

# MAIN
to_pack = [] # the file path for any items that we should be packing
to_pack_inst = {} # items to pack for a specific instance
to_pack_mat = {} # files to pack if material is used (by VBSP_styles only)

root = os.path.dirname(os.getcwd())
args = " ".join(sys.argv)
new_args=sys.argv[1:]
path=""
print(sys.argv)
game_dir = ""
next_is_game = False
for a in list(new_args):
    if next_is_game:
        next_is_game = False
        game_dir = os.path.normpath(a)
        new_args[new_args.index(a)] = game_dir
    elif "sdk_content\\maps\\" in os.path.normpath(a):
        path=os.path.normpath(a)
        new_args[new_args.index(a)]=path
    elif a == "-game":
        next_is_game = True
    elif a.casefold() in ("-both", "-final", "-staticproplighting", "-staticproppolys", "-textureshadows"):
        new_args.remove(a)

new_args = ['-bounce', '2', '-noextra'] + new_args

# Fast args: -bounce 2 -noextra -game $gamedir $path\$file
# Final args: -both -final -staticproplighting -StaticPropPolys -textureshadows  -game $gamedir $path\$file

utils.con_log("Map path is " + path)
if path == "":
    raise Exception("No map passed!")
    
if not path.endswith(".bsp"):
    path += ".bsp"

if os.path.basename(path) == "preview.bsp": # Is this a PeTI map?
    utils.con_log("PeTI map detected! (is named preview.vmf)")
    run_vrad(new_args)
else:
    utils.con_log("Hammer map detected! Not forcing cheap lighting..")
    run_vrad(sys.argv[1:])
    
pack_file = path[:-4] + '.filelist.txt'

if os.path.isfile(pack_file):
    utils.con_log("Pack list found, packing files!")
    arg_bits = [quote(os.path.normpath(os.path.join(os.getcwd(),"bspzip"))),
            "-addlist",
            quote(path),
            quote(pack_file),
            quote(path),
            "-game",
            quote(game_dir),
          ]
    arg = " ".join(arg_bits)
    utils.con_log(arg)
    subprocess.call(arg, stdout=None, stderr=subprocess.PIPE, shell=True)
    utils.con_log("Packing complete!")
else:
    utils.con_log("No items to pack!")
utils.con_log("BEE2 VRAD hook finished!")