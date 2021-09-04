"""Build commands for VBSP and VRAD."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
import contextlib
import pkgutil
import os
import sys


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

# Find the BSP transforms from HammerAddons.
try:
    transform_loc = Path(os.environ['BSP_TRANSFORMS']).resolve()
except KeyError:
    transform_loc = Path('../../HammerAddons/transforms/').resolve()
if not transform_loc.exists():
    raise ValueError(
        f'Invalid BSP transforms location "{transform_loc}"!\n'
        'Clone TeamSpen210/HammerAddons next to BEE2.4, or set the '
        'environment variable BSP_TRANSFORMS to the location.'
    )

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

    # Imported in utils, but not required in compiler.
    'bg_daemon',
]

# The modules made available for plugins to use.
INCLUDES = [
    'abc', 'array', 'base64', 'binascii', 'binhex',
    'bisect', 'colorsys', 'collections', 'csv', 'datetime',
    'decimal', 'difflib', 'enum', 'fractions', 'functools',
    'io', 'itertools', 'json', 'math', 'random', 're',
    'statistics', 'string', 'struct',
]
INCLUDES += collect_submodules('srctools', lambda name: 'pyinstaller' not in name and 'test' not in name and 'script' not in name)

# These also aren't required by logging really, but by default
# they're imported unconditionally. Check to see if it's modified first.
import logging.handlers
import logging.config

if not hasattr(logging.handlers, 'socket') and not hasattr(logging.config, 'socket'):
    EXCLUDES.append('socket')
    # Subprocess uses this in UNIX-style OSes, but not Windows.
    if WIN:
        EXCLUDES += ['selectors', 'select']

del logging

if MAC or LINUX:
    EXCLUDES += ['grp', 'pwd']  # Unix authentication modules, optional

    # The only hash algorithm that's used is sha512 - random.seed()
    EXCLUDES += ['_sha1', '_sha256', '_md5']

if sys.version_info >= (3, 7):
    # Only needed on 3.6, it's in the stdlib thereafter.
    EXCLUDES += ['importlib_resources']

# Include the condition sub-modules that are dynamically imported.
INCLUDES += [
    'precomp.conditions.' + module
    for loader, module, is_package in
    pkgutil.iter_modules(['precomp/conditions'])
]


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

# Empty module to be the package __init__.
transforms_stub = Path(workpath, 'transforms_stub.py')
try:
    with transforms_stub.open('x') as f:
        f.write('__path__ = []\n')
except FileExistsError:
    pass

# Finally, run the PyInstaller analysis process.
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

vbsp_vrad_an = Analysis(
    ['compiler_launch.py'],
    pathex=[workpath],
    binaries=[],
    hiddenimports=INCLUDES,
    excludes=EXCLUDES,
    noarchive=False
)

# Force the BSP transforms to be included in their own location.
for mod in transform_loc.rglob('*.py'):
    rel_path = mod.relative_to(transform_loc)

    if rel_path.name.casefold() == '__init__.py':
        rel_path = rel_path.parent
    mod_name = rel_path.with_suffix('')
    dotted = str(mod_name).replace('\\', '.').replace('/', '.')
    vbsp_vrad_an.pure.append(('postcomp.transforms.' + dotted, str(mod), 'PYMODULE'))

vbsp_vrad_an.pure.append(('postcomp.transforms', str(transforms_stub), 'PYMODULE'))

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
