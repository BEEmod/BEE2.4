from cx_Freeze import setup, Executable
import os, shutil

shutil.rmtree('build_BEE2', ignore_errors=True)

ico_path = os.path.join(os.getcwd(), "bee2.ico")

setup(
    name='BEE2',
    version='2.4',
    description='Portal 2 Puzzlemaker item manager.',
    options={
        'build_exe': {
            'build_exe': 'build_BEE2/bin',
            'include_files': ['bee2.ico'],
        },
    },
    executables=[
        Executable(
            'src/BEE2.pyw',
            base='Win32GUI',
            icon=ico_path,
            compress=True,
        )
    ],
)
