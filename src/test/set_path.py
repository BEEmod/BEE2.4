"""Adds the main src/ folder to the path, so we can import modules.

"""
import os
import sys
parent, our_dir = os.path.split(os.getcwd())
if our_dir == 'test':
    sys.path.append(
        parent,
    )
del os, sys, parent, our_dir
