"""Allows enabling and disabling individual packages.
"""
from tkinter import ttk
import tkinter as tk
from tk_tools import TK_ROOT

from CheckDetails import CheckDetails, Item as CheckItem
from BEE2_config import ConfigFile
import packageLoader
import utils
import tk_tools

PACK_CONFIG = ConfigFile('packages.cfg')
