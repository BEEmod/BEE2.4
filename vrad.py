import os
import os.path
import sys
import subprocess

import utils


def quote(txt):
    return '"' + txt + '"'


def run_vrad(args):
    "Execute the original VRAD."
    joined_args = (
        '"' + os.path.normpath(
            os.path.join(os.getcwd(), "vrad_original")
            ) +
        '" ' +
        " ".join(
            # put quotes around args which contain spaces
            (quote(x) if " " in x else x)
            for x in args
            )
        )
    utils.con_log("Calling original VRAD...")
    utils.con_log(joined_args)
    code = subprocess.call(
        joined_args,
        stdout=None,
        stderr=subprocess.PIPE,
        shell=True,
    )
    if code == 0:
        utils.con_log("Done!")
    else:
        utils.con_log("VRAD failed! (" + str(code) + ")")
        sys.exit(code)

# MAIN
to_pack = []  # the file path for any items that we should be packing
to_pack_inst = {}  # items to pack for a specific instance
to_pack_mat = {}  # files to pack if material is used (by VBSP_styles only)

TK_ROOT = os.path.dirname(os.getcwd())
args = " ".join(sys.argv)
fast_args = sys.argv[1:]
full_args = sys.argv[1:]
path = ""

for a in fast_args[:]:
    if "sdk_content\\maps\\" in os.path.normpath(a):
        path = os.path.normpath(a)
        fast_args[fast_args.index(a)] = path
    elif a.casefold() in (
            "-both",
            "-final",
            "-staticproplighting",
            "-staticproppolys",
            "-textureshadows",
            ):
        # remove final parameters from the modified arguments
        fast_args.remove(a)
    elif a in ('-force_peti', '-force_hammer', '-no_pack'):
        # we need to strip these out, otherwise VBSP will get confused
        fast_args.remove(a)
        full_args.remove(a)

fast_args = ['-bounce', '2', '-noextra'] + fast_args

# Fast args: -bounce 2 -noextra -game $gamedir $path\$file
# Final args: -both -final -staticproplighting -StaticPropPolys
# -textureshadows  -game $gamedir $path\$file

utils.con_log("Map path is " + path)
if path == "":
    raise Exception("No map passed!")

if not path.endswith(".bsp"):
    path += ".bsp"

if '-force_peti' in args or '-force_hammer' in args:
    # we have override command!
    if '-force_peti' in args:
        utils.con_log('OVERRIDE: Applying cheap lighting!')
        is_peti = True
    else:
        utils.con_log('OVERRIDE: Preserving args!')
        is_peti = False
else:
    # If we don't get the special -force args, check for the name
    # equalling preview to determine if we should convert
    is_peti = os.path.basename(path) == "preview.bsp"
if is_peti:
    utils.con_log("PeTI map detected!")
    run_vrad(fast_args)
else:
    utils.con_log("Hammer map detected! Not forcing cheap lighting..")
    run_vrad(full_args)

pack_file = path[:-4] + '.filelist.txt'

if '-no_pack' not in args:
    utils.con_log("Running PakRat!")
    arg_bits = [
        quote(os.path.normpath(os.path.join(os.getcwd(), "bee2/pakrat.jar"))),
        "-auto",
        quote(os.path.normpath(
            os.path.join(
                os.path.dirname(os.getcwd()),
                'bee2/',
            )
        )),
        quote(path),
    ]
    arg = " ".join(arg_bits)
    utils.con_log(arg)
    subprocess.call(arg, stdout=None, stderr=subprocess.PIPE, shell=True)
    utils.con_log("Packing complete!")
else:
    utils.con_log("No items to pack!")
utils.con_log("BEE2 VRAD hook finished!")