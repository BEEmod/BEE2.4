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
from tk_tools import TK_ROOT
import utils

LOGGER = utils.getLogger(__name__)

UPDATE_INTERVAL = 500  # Number of miliseconds between each progress check

files_done = False
res_count = -1
progress_var = tk.IntVar()
zip_list = []
currently_done = multiprocessing.Value('I')  # int value used to show status
# in main window
export_btn_text = tk.StringVar()


def done_callback():
    pass


def do_copy(zip_list, done_files):
    cache_path = os.path.abspath('../cache/')
    shutil.rmtree(cache_path, ignore_errors=True)

    img_loc = os.path.join('resources', 'bee2')
    for zip_path in zip_list:
        if os.path.isfile(zip_path):
            zip_file = ZipFile(zip_path)
        else:
            zip_file = FakeZip(zip_path)
        with zip_file:
            for path in zip_names(zip_file):
                loc = os.path.normcase(path)
                if not loc.startswith("resources"):
                    continue
                # Don't re-extract images
                if loc.startswith(img_loc):
                    continue
                zip_file.extract(path, path=cache_path)
                with done_files.get_lock():
                    done_files.value += 1


def start_copying(zip_list):
    global copy_process
    copy_process = multiprocessing.Process(
        target=do_copy,
        args=(zip_list, currently_done),
    )
    copy_process.daemon = True
    LOGGER.info('Starting background process!')
    copy_process.start()
    TK_ROOT.after(UPDATE_INTERVAL, update)


def update():
    """Check the progress of the copying until it's done.
    """
    progress_var.set(
        1000 * currently_done.value / res_count,
    )
    export_btn_text.set(
        'Extracting Resources ({!s}/{!s})...'.format(
            currently_done.value,
            res_count,
        )
    )
    if not copy_process.is_alive():
        # We've finished copying
        export_btn_text.set(
            'Export...'
        )
        done_callback()
    else:
        # Coninuously tell TK to re-run this, so we update
        # without deadlocking the CPU
        TK_ROOT.after(UPDATE_INTERVAL, update)
