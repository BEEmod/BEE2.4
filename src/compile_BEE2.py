from cx_Freeze import setup, Executable
import os, shutil
import utils

shutil.rmtree('build_BEE2', ignore_errors=True)

ico_path = os.path.join(os.getcwd(), "../bee2.ico")

if utils.WIN:
    base = 'Win32GUI'
else:
    base = None

setup(
    name='BEE2',
    version='2.4',
    description='Portal 2 Puzzlemaker item manager.',
    options={
        'build_exe': {
            'build_exe': '../build_BEE2/bin',
        },
    },
    executables=[
        Executable(
            'BEE2.pyw',
            base=base,
            icon=ico_path,
            compress=True,
        )
    ],
)
