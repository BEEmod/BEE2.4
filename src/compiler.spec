"""Build commands for VBSP and VRAD."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, get_module_file_attribute
import contextlib
import pkgutil
import os
import sys

# Injected by PyInstaller.
workpath: str
SPECPATH: str

hammeraddons = Path.joinpath(Path(SPECPATH).parent, 'hammeraddons')
sys.path.append(SPECPATH)


import utils
if utils.MAC:
    suffix = '_osx'
elif utils.LINUX:
    suffix = '_linux'
else:
    suffix = ''

# Unneeded packages that cx_freeze detects:
EXCLUDES = [
    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..

    # This isn't ever used in the compiler.
    'tkinter', 'numpy',

    'win32api',
    'win32com',
    'win32wnet',

    # Imported by logging handlers which we don't use..
    'win32evtlog',
    'win32evtlogutil',
    'smtplib',

    # Imported in utils, but not required in compiler.
    'bg_daemon',
    # We don't need to actually run versioning at runtime.
    'versioningit',
]

# The modules made available for plugins to use.
INCLUDES = [
    'abc', 'array', 'base64', 'binascii', 'binhex',
    'bisect', 'colorsys', 'collections', 'csv', 'datetime',
    'decimal', 'difflib', 'enum', 'fractions', 'functools',
    'io', 'itertools', 'json', 'math', 'random', 're',
    'statistics', 'string', 'struct', 'attrs', 'attr',

    # Might not be found?
    'rtree',
    # Ensure all of Hammeraddons is loaded.
    'hammeraddons', 'hammeraddons.acache', 'hammeraddons.config', 'hammeraddons.mdl_compiler',
    'hammeraddons.postcompiler', 'hammeraddons.plugin', 'hammeraddons.propcombine',
    'hammeraddons.plugin',
]
INCLUDES += collect_submodules('srctools', lambda name: 'pyinstaller' not in name and 'script' not in name)

# These also aren't required by logging really, but by default
# they're imported unconditionally. Check to see if it's modified first.
import logging.handlers
import logging.config

if not hasattr(logging.handlers, 'socket') and not hasattr(logging.config, 'socket'):
    EXCLUDES.append('socket')
    # Subprocess uses this in UNIX-style OSes, but not Windows.
    if utils.WIN:
        EXCLUDES += ['selectors', 'select']

del logging

if utils.MAC or utils.LINUX:
    EXCLUDES += ['grp', 'pwd']  # Unix authentication modules, optional

    # The only hash algorithm that's used is sha512 - random.seed()
    EXCLUDES += ['_sha1', '_sha256', '_md5']

# Include the condition sub-modules that are dynamically imported.
INCLUDES += [
    'precomp.conditions.' + module
    for loader, module, is_package in
    pkgutil.iter_modules(['precomp/conditions'])
]

# Find and add libspatialindex DLLs.
if utils.WIN and utils.BITNESS == '32':
    # On 32-bit windows, we have to manually copy our versions -
    # there's no wheel including them by default.
    binaries = []
    lib_path = Path(SPECPATH, '..', 'lib-32').absolute()
    rtree_dir = Path(get_module_file_attribute('rtree'), '../lib').absolute()
    rtree_dir.mkdir(exist_ok=True)
    for dll in lib_path.iterdir():
        if dll.suffix == '.dll' and 'spatialindex' in dll.stem:
            dest = rtree_dir / dll.name
            print(f'Writing {dll} -> {dest}')
            dest.write_bytes(dll.read_bytes())
# Now we can collect the appropriate path.
binaries = collect_dynamic_libs('rtree')

# Copy error display web resources to the compiler folder.
data_files = []
error_display_folder = Path(SPECPATH, '..', 'error_display').resolve()
for dirpath, dirname, filenames in os.walk(error_display_folder):
    for file in filenames:
        full_path = Path(dirpath, file)
        data_files.append((
            str(full_path),
            str('error_display' / full_path.relative_to(error_display_folder).parent),
        ))

print('DATA:', data_files)

# Write this to the temp folder, so it's picked up and included.
# Don't write it out though if it's the same, so PyInstaller doesn't reparse.
version_val = 'BEE_VERSION=' + repr(utils.get_git_version(SPECPATH))
print(version_val)
version_filename = os.path.join(workpath, '_compiled_version.py')

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
    pathex=[workpath, str(hammeraddons / 'src')],
    binaries=binaries,
    hiddenimports=INCLUDES,
    datas=data_files,
    excludes=EXCLUDES,
    noarchive=False,
)

# Force the BSP transforms to be included in their own location.
# Map package -> module.
names: 'dict[str, list[str]]' = {}
transform_loc = hammeraddons / 'transforms'
for mod in transform_loc.rglob('*.py'):
    rel_path = mod.relative_to(transform_loc)

    if rel_path.name.casefold() == '__init__.py':
        rel_path = rel_path.parent
    mod_name = rel_path.with_suffix('')
    dotted = 'postcomp.transforms.' + str(mod_name).replace('\\', '.').replace('/', '.')
    package, module = dotted.rsplit('.', 1)
    names.setdefault(package, []).append(module)
    vbsp_vrad_an.pure.append((dotted, str(mod), 'PYMODULE'))

# The package's __init__, where we add the names of all the transforms.
# Build up a bunch of import statements to import them all.
transforms_stub = Path(workpath, 'transforms_stub.py')
with transforms_stub.open('w') as f:
    f.write(f'__path__ = []\n')  # Make it a package.
    # Sort long first, then by name.
    for pack, modnames in sorted(names.items(), key=lambda t: (-len(t[1]), t[0])):
        if pack:
            f.write(f'from {pack} import ')
        else:
            f.write('import ')
        modnames.sort()
        f.write(', '.join(modnames))
        f.write('\n')

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
