"""Run the BEE2."""
from multiprocessing import freeze_support, set_start_method
import os
import sys
# We need to add dummy files if these are None - MultiProccessing tries to flush
# them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')
if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r')

freeze_support()
set_start_method('spawn')

if __name__ == '__main__':
    import BEE2

