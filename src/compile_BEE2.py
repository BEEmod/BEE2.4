from cx_Freeze import setup, Executable
from zipfile import ZipFile, ZipInfo
import os
import shutil
import utils
import io

shutil.rmtree('build_BEE2', ignore_errors=True)

ico_path = os.path.realpath(os.path.join(os.getcwd(), "../bee2.ico"))


def get_localisation(key):
    """Get localisation files from Loco."""
    import requests

    # Make the directories.
    os.makedirs('../build_BEE2/i18n/', exist_ok=True)
    os.makedirs('../i18n/', exist_ok=True)

    print('Reading translations... ', end='', flush=True)
    zip_request = requests.get(
        'https://localise.biz/api/export/archive/mo.zip',
        headers={
            'Authorization': 'Loco ' + key,
        },
        params={
            'path': '{%lang}{_%region}.{%ext}',
        },
    )
    zip_file = ZipFile(io.BytesIO(zip_request.content))
    print('Done!')

    print('Translations: ')

    for file in zip_file.infolist():  # type: ZipInfo
        if 'README.txt' in file.filename:
            continue
        filename = os.path.basename(file.filename)
        print(filename)
        # Copy to the dev and output directory.
        with zip_file.open(file) as src, open('../i18n/' + filename, 'wb') as dest:
            shutil.copyfileobj(src, dest)
        with zip_file.open(file) as src, open('../build_BEE2/i18n/' + filename, 'wb') as dest:
            shutil.copyfileobj(src, dest)

get_localisation('kV-oMlhZPJEJoYPI5EQ6HaqeAc1zQ73G')


# Exclude bits of modules we don't need, to decrease package size.
EXCLUDES = [
    # We just use idlelib.WidgetRedirector
    'idlelib.ClassBrowser',
    'idlelib.ColorDelegator',
    'idlelib.Debugger',
    'idlelib.Delegator',
    'idlelib.EditorWindow',
    'idlelib.FileList',
    'idlelib.GrepDialog',
    'idlelib.IOBinding',
    'idlelib.IdleHistory',
    'idlelib.MultiCall',
    'idlelib.MultiStatusBar',
    'idlelib.ObjectBrowser',
    'idlelib.OutputWindow',
    'idlelib.PathBrowser',
    'idlelib.Percolator',
    'idlelib.PyParse',
    'idlelib.PyShell',
    'idlelib.RemoteDebugger',
    'idlelib.RemoteObjectBrowser',
    'idlelib.ReplaceDialog',
    'idlelib.ScrolledList',
    'idlelib.SearchDialog',
    'idlelib.SearchDialogBase',
    'idlelib.SearchEngine',
    'idlelib.StackViewer',
    'idlelib.TreeWidget',
    'idlelib.UndoDelegator',
    'idlelib.WindowList',
    'idlelib.ZoomHeight',
    'idlelib.aboutDialog',
    'idlelib.configDialog',
    'idlelib.configHandler',
    'idlelib.configHelpSourceEdit',
    'idlelib.configSectionNameDialog',
    'idlelib.dynOptionMenuWidget',
    'idlelib.idle_test.htest',
    'idlelib.idlever',
    'idlelib.keybindingDialog',
    'idlelib.macosxSupport',
    'idlelib.rpc',
    'idlelib.tabbedpages',
    'idlelib.textView',

    # Stop us from then including Qt itself
    'PIL.ImageQt',

    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..

    # Imported by logging handlers which we don't use..
    'win32evtlog',
    'win32evtlogutil',
    'email',
    'smtplib',

    'unittest',  # Imported in __name__==__main__..
    'doctest',
    'optparse',
    'argparse',
]


if not utils.MAC:
    EXCLUDES.append('platform')  # Only used in the mac pyglet code..

# cx_freeze doesn't detect these required modules
INCLUDES = [
    'pyglet.clock',
    'pyglet.resource',
]

# AVbin is needed to read OGG files.
INCLUDE_LIBS = [
    'C:/Windows/system32/avbin.dll',  # Win 32 bit
    'C:/Windows/sysWOW64/avbin64.dll',  # Win 64 bit
    'libavbin.dylib',  # OS X - must be relative.,,
    '/usr/lib/libavbin.so',  # Linux
]


if utils.WIN:
    base = 'Win32GUI'
else:
    base = None

# Filter out files for other platforms
INCLUDE_LIBS = [
    path for path in INCLUDE_LIBS
    if os.path.exists(path)
]

bee_version = input('BEE2 Version: ')


setup(
    name='BEE2',
    version='2.4',
    description='Portal 2 Puzzlemaker item manager.',
    options={
        'build_exe': {
            'build_exe': '../build_BEE2/bin',
            'excludes': EXCLUDES,
            'includes': INCLUDES,
            # These values are added to the generated BUILD_CONSTANTS module.
            'constants': 'BEE_VERSION=' + repr(bee_version),
            'include_files': INCLUDE_LIBS,

            # Include all modules in the zip..
            'zip_include_packages': '*',
            'zip_exclude_packages': '',
        },
    },
    executables=[
        Executable(
            'BEE2.pyw',
            base=base,
            icon=ico_path,
        ),
        Executable(
            'backup.py',
            base=base,
            icon=ico_path,
            targetName='backup_tool' + ('.exe' if utils.WIN else ''),
        ),
        Executable(
            'CompilerPane.py',
            base=base,
            icon=ico_path,
            targetName='compiler_options' + ('.exe' if utils.WIN else ''),
        )
    ],
)

# -------------------------------------------------------
# Now copy the required resources to the build directory.


def copy_resource(tree):
    print('Copying "{}"'.format(tree))
    src = os.path.join('..', tree)
    dest = os.path.join('..', 'build_BEE2', tree)

    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(src, dest)
    else:
        os.makedirs(dest, exist_ok=True)
        for file in os.listdir(src):
            copy_resource(tree + '/' + file)

copy_resource('BEE2.ico')
copy_resource('images/BEE2')
copy_resource('images/icons')
copy_resource('palettes')
for snd in os.listdir('../sounds/'):
    if snd == 'music_samp':
        continue
    copy_resource('sounds/' + snd)