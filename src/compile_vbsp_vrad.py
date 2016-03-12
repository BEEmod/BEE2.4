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
    'argparse',  # Used in __main__ of some modules
    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..
    'distutils',  # Found in shutil, used if zipfile is not availible
    'doctest',  # Used in __main__ of decimal and heapq
    'dis',  # From inspect, not needed
    'lzma',  # We use this for packages, but not in VBSP & VRAD
    'optparse',  # Used in calendar.__main__
    'pprint',  # From pickle, not needed
    'textwrap',  # Used in zipfile.__main__
    'pkgutil',  # Used by conditions only when unfrozen


    # Imported by logging handlers which we don't use..
    'win32evtlog',
    'win32evtlogutil',
    'email',
    'smtplib',
    'http',
]

if utils.WIN:
    # Subprocess uses these in UNIX-style OSes, but not Windows
    EXCLUDES += ['select', 'selectors']

if utils.MAC or utils.LINUX:
    EXCLUDES += ['grp', 'pwd']  # Unix authentication modules, optional

    # The only hash algorithm that's used is sha512 - random.seed()
    EXCLUDES += ['_sha1', '_sha256', '_md5']


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
                # Pass on the list of frozen constants so we can import them
                # later.
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