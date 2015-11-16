from cx_Freeze import setup, Executable
import os
import utils

ico_path = os.path.join(os.getcwd(), "../bee2.ico")

if utils.WIN:
    suffix = '.exe'
elif utils.MAC:
    suffix = '_osx'
elif utils.LINUX:
    suffix = '_linux'

# Unneeded packages that cx_freeze detects:
EXCLUDES = [
    'email',
    'distutils',  # Found in shutil, used if zipfile is not availible
    'doctest',  # Used in __main__ of decimal and heapq
    'dis',  # From inspect, not needed
]
setup(
    name='VBSP_VRAD',
    version='0.1',
    options={
        'build_exe':
            {
                'build_exe': '../compiler',
                'excludes': EXCLUDES,
            }
    },
    description='BEE2 VBSP and VRAD compilation hooks, '
                'for modifying PeTI maps during compilation.',
    executables=[
        Executable(
            'vbsp_launch.py',
            base='Console',
            icon=ico_path,
            targetName='vbsp' + suffix,
        ),
        Executable(
            'vrad.py',
            base='Console',
            icon=ico_path,
            targetName='vrad' + suffix,
        )
    ]
)