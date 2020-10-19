"""Build commands for VBSP and VRAD."""
import contextlib
import pkgutil
import os
import sys
import srctools


# THe BEE2 modules cannot be imported inside the spec files.
WIN = sys.platform.startswith('win')
MAC = sys.platform.startswith('darwin')
LINUX = sys.platform.startswith('linux')

if MAC:
    suffix = '_osx'
elif LINUX:
    suffix = '_linux'
else:
    suffix = ''


# Unneeded packages that cx_freeze detects:
EXCLUDES = [
    'argparse',  # Used in __main__ of some modules
    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..
    'distutils',  # Found in shutil, used if zipfile is not availible
    'doctest',  # Used in __main__ of decimal and heapq
    'optparse',  # Used in calendar.__main__
    'pprint',  # From pickle, not needed
    'textwrap',  # Used in zipfile.__main__

    # We don't localise the compiler, but utils imports the modules.
    'locale', 'gettext',

    # This isn't ever used in the compiler.
    'tkinter',

    # We aren't using the Python 2 code, for obvious reasons.
    'importlib_resources._py2',

    'win32api',
    'win32com',
    'win32wnet'

    # Imported by logging handlers which we don't use..
    'win32evtlog',
    'win32evtlogutil',
    'smtplib',
    'http',

    # Pillow is imported by Srctools' VTF support, but we don't need to do that.
    'PIL',

    'sqlite3',  # Imported from aenum, but we don't use that enum subclass.
]

# These also aren't required by logging really, but by default
# they're imported unconditionally. Check to see if it's modified first.
import logging.handlers
import logging.config

if not hasattr(logging.handlers, 'socket') and not hasattr(logging.config, 'socket'):
    EXCLUDES.append('socket')
    # Subprocess uses this in UNIX-style OSes, but not Windows.
    if WIN:
        EXCLUDES += ['selectors', 'select']
if not hasattr(logging.handlers, 'pickle'):
    EXCLUDES.append('pickle')
del logging

if MAC or LINUX:
    EXCLUDES += ['grp', 'pwd']  # Unix authentication modules, optional

    # The only hash algorithm that's used is sha512 - random.seed()
    EXCLUDES += ['_sha1', '_sha256', '_md5']


# Include the condition sub-modules that are dynamically imported.
INCLUDES = [
    'precomp.conditions.' + module
    for loader, module, is_package in
    pkgutil.iter_modules(['precomp/conditions'])
]
print(INCLUDES)

bee_version = input('BEE2 Version ("x.y.z" or blank for dev): ')
if bee_version:
    bee_version = '2 v' + bee_version

# Write this to the temp folder, so it's picked up and included.
# Don't write it out though if it's the same, so PyInstaller doesn't reparse.
version_val = 'BEE_VERSION=' + repr(bee_version)
version_filename = os.path.join(workpath, 'BUILD_CONSTANTS.py')

with contextlib.suppress(FileNotFoundError), open(version_filename) as f:
    if f.read().strip() == version_val:
        version_val = None

if version_val:
    with open(version_filename, 'w') as f:
        f.write(version_val)

# Finally, run the PyInstaller analysis process.
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

vbsp_vrad_an = Analysis(
    ['compiler_launch.py'],
    pathex=[workpath, os.path.dirname(srctools.__path__[0])],
    binaries=[],
    hiddenimports=INCLUDES,
    excludes=EXCLUDES,
    noarchive=False
)

pyz = PYZ(
    vbsp_vrad_an.pure,
    vbsp_vrad_an.zipped_data,
)

vbsp_exe = EXE(
    pyz,
    vbsp_vrad_an.scripts,
    [],
    exclude_binaries=True,
    name='vbsp' + suffix,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='../BEE2.ico'
)

vrad_exe = EXE(
    pyz,
    vbsp_vrad_an.scripts,
    [],
    exclude_binaries=True,
    name='vrad' + suffix,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='../BEE2.ico'
)

coll = COLLECT(
    vbsp_exe, vrad_exe,
    vbsp_vrad_an.binaries,
    vbsp_vrad_an.zipfiles,
    vbsp_vrad_an.datas,
    strip=False,
    upx=True,
    name='compiler',
)
