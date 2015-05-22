# coding=utf-8
"""
Handles extracting all the package resources in a background thread, so users
can do other things without waiting.
"""
import tkinter as tk

import threading
import shutil
import os.path
from zipfile import ZipFile

from FakeZip import zip_names, FakeZip
from tk_root import TK_ROOT

files_done = False
currently_done = 0  # We can't call TK commands from other threads,
res_count = -1
progress_var = tk.IntVar()  # so use this indirection.
zip_list = []

def done_callback():
    pass

def do_copy(zip_list):
    #global currently_done, files_done
    img_loc = os.path.join('resources', 'bee2')
    for zip_path in zip_list:
        #print('Extracting Resources from', zip_path)
        if os.path.isfile(zip_path):
            zip_file = ZipFile(zip_path)
        else:
            zip_file = FakeZip(zip_path)
        with zip_file:
            for path in zip_names(zip_file):
                loc = os.path.normcase(path)
                if loc.startswith("resources"):
                    #currently_done += 1
                    # Don't re-extract images
                    if not loc.startswith(img_loc):
                        zip_file.extract(path, path="../cache/")

    shutil.rmtree('../inst_cache/', ignore_errors=True)
    shutil.rmtree('../source_cache/', ignore_errors=True)

    if os.path.isdir("../cache/resources/instances"):
        shutil.move("../cache/resources/instances", "../inst_cache/")
    for file_type in ("materials", "models", "sounds", "scripts"):
        if os.path.isdir("../cache/resources/" + file_type):
            shutil.move(
                "../cache/resources/" + file_type,
                "../source_cache/" + file_type,
            )

    shutil.rmtree('../cache/', ignore_errors=True)
    #files_done = True


def start_copying(zip_list):
    global currently_done, files_done
    currently_done = 0
    files_done = False
    copy_thread = threading.Thread(target=do_copy, args=(zip_list,))
    print(copy_thread)
    print('Starting background thread!')
    copy_thread.run()

    #TK_ROOT.after(100, update)


def update():
    """Check the progress of the copying until it's done.
    """
    progress_var.set(
        1000 * currently_done / res_count,
    )
    if files_done:
        done_callback()
    else:
        TK_ROOT.after(100, update)
