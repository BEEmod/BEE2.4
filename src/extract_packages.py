# coding=utf-8
"""
Handles extracting all the package resources in a background process, so users
can do other things without waiting.
"""
import tkinter as tk

import multiprocessing
import shutil
import os.path
from zipfile import ZipFile

from FakeZip import zip_names, FakeZip
from tk_root import TK_ROOT

UPDATE_INTERVAL = 500  # Number of miliseconds between each progress check

files_done = False
res_count = -1
progress_var = tk.IntVar()
zip_list = []
currently_done = multiprocessing.Value('i')  # int value used to show status
# in main window
export_btn_text = tk.StringVar()

def done_callback():
    pass

def make_progress_infinite():
    # Overwritten by UI, callback function to make the exporting progress
    # bar infinite while we're transferring files
    pass

def do_copy(zip_list, done_files):
    img_loc = os.path.join('resources', 'bee2')
    for zip_path in zip_list:
        if os.path.isfile(zip_path):
            zip_file = ZipFile(zip_path)
        else:
            zip_file = FakeZip(zip_path)
        with zip_file:
            for path in zip_names(zip_file):
                loc = os.path.normcase(path)
                if loc.startswith("resources"):
                    # Don't re-extract images
                    if not loc.startswith(img_loc):
                        zip_file.extract(path, path="../cache/")
                    with currently_done.get_lock():
                        done_files.value += 1

    with currently_done.get_lock():
        # Signal the main process to switch to an infinite
        # progress bar
        done_files.value = -1

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


def start_copying(zip_list):
    global copy_process
    copy_process = multiprocessing.Process(
        target=do_copy,
        args=(zip_list, currently_done),
    )
    copy_process.daemon = True
    print(copy_process)
    print('Starting background process!')
    copy_process.start()
    TK_ROOT.after(UPDATE_INTERVAL, update)

def update():
    """Check the progress of the copying until it's done.
    """
    # Flag to indicate it's now just copying the files to correct locations
    done_val = currently_done.value
    if done_val == -1:
        with currently_done.get_lock():
            # Set this to something else so we only do this once.
            currently_done.value = -2
        make_progress_infinite()
        export_btn_text.set(
            'Organising files...'
        )
    elif done_val == -2:
        pass
    else:
        progress_var.set(
            1000 * done_val / res_count,
        )
        export_btn_text.set(
            'Extracting Resources ({!s}/{!s})...'.format(
                done_val,
                res_count,
            )
        )
    if not copy_process.is_alive():
        export_btn_text.set(
            'Export...'
        )
        done_callback()
    else:
        TK_ROOT.after(UPDATE_INTERVAL, update)
