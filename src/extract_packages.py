# coding=utf-8
"""
Handles extracting all the package resources in a background thread, so users
can do other things without waiting.
"""

import threading

files_done = False

def do_copy(zips):
