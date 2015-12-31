from cx_Freeze import setup, Executable
import os
import utils
import pkgutil


ico_path = os.path.join(os.getcwd(), "../bee2.ico")

if utils.WIN:
    suffix = '.exe'
elif utils.MAC:
    suffix = '_osx'
elif utils.LINUX:
    suffix = '_linux'
else:
    suffix = ''

# Unneeded packages that cx_freeze detects:
EXCLUDES = [
    'email',
    'distutils',  # Found in shutil, used if zipfile is not availible
    'doctest',  # Used in __main__ of decimal and heapq
    'dis',  # From inspect, not needed
]

# Additional modules to include:
INCLUDES = [

]

# Get the list of condition sub-modules that we need to also include.
import conditions
condition_modules = [
    module
    for loader, module, is_package in
    pkgutil.iter_modules(['conditions'])
]

INCLUDES += [
    'conditions.' + module
    for module in
    condition_modules
]

bee_version = input('BEE2 Version: ')

setup(
    name='VBSP_VRAD',
    version='0.1',
    options={
        'build_exe': {
            'build_exe': '../compiler',
            'excludes': EXCLUDES,
            'includes': INCLUDES,
            # These values are added to the generated BUILD_CONSTANTS module.
            'constants': 'BEE_VERSION={ver!r},cond_modules={cond!r}'.format(
                ver=bee_version,
                cond=';'.join(condition_modules),
            ),
        },
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
        ),
    ]
)