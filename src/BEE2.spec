import os
import sys
from pathlib import Path
import contextlib
from babel.messages import Catalog
import babel.messages.frontend
import babel.messages.extract
from babel.messages.pofile import read_po, write_po
from babel.messages.mofile import write_mo

ico_path = os.path.realpath(os.path.join(os.getcwd(), "../bee2.ico"))
# Injected by PyInstaller.
workpath: str
SPECPATH: str

# Allow importing utils.
sys.path.append(SPECPATH)
import utils

# src -> build subfolder.
data_files = [
    ('../BEE2.ico', '.'),
    ('../BEE2.fgd', '.'),
    ('../images/BEE2/*.png', 'images/BEE2/'),
    ('../images/icons/*.png', 'images/icons/'),
    ('../images/splash_screen/*.jpg', 'images/splash_screen/'),
]


def do_localisation() -> None:
    """Build localisation."""

    # Make the directories.
    i18n = Path('../i18n')
    i18n.mkdir(exist_ok=True)

    print('Reading translations from source...', flush=True)

    catalog = Catalog(
        header_comment='# BEEMOD2 v4',
        msgid_bugs_address='https://github.com/BEEmod/BEE2.4/issues',
    )

    extracted = babel.messages.extract.extract_from_dir(
        '.',
        comment_tags=['i18n:'],
    )
    for filename, lineno, message, comments, context in extracted:
        catalog.add(
            message,
            locations=[(os.path.normpath(filename), lineno)],
            auto_comments=comments,
            context=context,
        )

    with open(i18n / 'BEE2.pot', 'wb') as f:
        write_po(f, catalog, include_lineno=False)

    print('Done!')

    print('Updating translations: ')

    for trans in i18n.glob('*.po'):

        locale = trans.stem

        print('>', locale)

        # Update the translations.
        with trans.open('rb') as src:
            trans_cat = read_po(src, locale)
        trans_cat.update(catalog)
        with trans.open('wb') as dest:
            write_po(dest, trans_cat)

        # Compile them all.
        comp = trans.with_suffix('.mo')
        with comp.open('wb') as dest:
            write_mo(dest, trans_cat)

        data_files.append((str(comp), 'i18n/'))

    catalog.locale = 'en'
    with (i18n / 'en.mo').open('wb') as dest:
        write_mo(dest, catalog)

    data_files.append((str(i18n / 'en.mo'), 'i18n/'))


do_localisation()


# Exclude bits of modules we don't need, to decrease package size.
EXCLUDES = [
    # We just use idlelib.WidgetRedirector and idlelib.query
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

    'numpy',  # PIL.ImageFilter imports, we don't need NumPy!

    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..

    # Imported by logging handlers which we don't use..
    'win32evtlog',
    'win32evtlogutil',
    'smtplib',

    'unittest',  # Imported in __name__==__main__..
    'doctest',
    'optparse',
    'argparse',
]

binaries = []
if utils.WIN:
    lib_path = Path(SPECPATH, '..', 'lib-' + utils.BITNESS).absolute()
    try:
        for dll in lib_path.iterdir():
            if dll.suffix == '.dll' and dll.stem.startswith(('av', 'swscale', 'swresample')):
                binaries.append((str(dll), '.'))
    except FileNotFoundError:
        lib_path.mkdir(exist_ok=True)
        pass
    if not binaries:  # Not found.
        raise ValueError(f'FFmpeg dlls should be downloaded into "{lib_path}".')


# Write this to the temp folder, so it's picked up and included.
# Don't write it out though if it's the same, so PyInstaller doesn't reparse.
version_val = 'BEE_VERSION=' + repr(utils.get_git_version(SPECPATH))
print(version_val)
version_filename = os.path.join(workpath, '_compiled_version.py')

with contextlib.suppress(FileNotFoundError), open(version_filename) as f:
    if f.read().strip() == version_val:
        version_val = ''

if version_val:
    with open(version_filename, 'w') as f:
        f.write(version_val)

for snd in os.listdir('../sounds/'):
    if snd == 'music_samp':
        continue
    data_files.append(('../sounds/' + snd, 'sounds'))

# Include the compiler, picking the right architecture.
bitness = 64 if sys.maxsize > (2**33) else 32
data_files.append((f'../dist/{bitness}bit/compiler/', 'compiler'))

# Finally, run the PyInstaller analysis process.

bee2_a = Analysis(
    ['BEE2_launch.pyw'],
    pathex=[workpath],
    datas=data_files,
    hiddenimports=[
        'PIL._tkinter_finder',
    ],
    binaries=binaries,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False
)

# Need to add this manually, so it can have a different name.
bee2_a.datas.append((
    'README.txt',
    os.path.join(os.getcwd(), '../INSTALL_GUIDE.txt'),
    'DATA',
))

pyz = PYZ(
    bee2_a.pure,
    bee2_a.zipped_data,
)

exe = EXE(
    pyz,
    bee2_a.scripts,
    [],
    exclude_binaries=True,
    name='BEE2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    windowed=True,
    icon='../BEE2.ico'
)

coll = COLLECT(
    exe,
    bee2_a.binaries,
    bee2_a.zipfiles,
    bee2_a.datas,
    strip=False,
    upx=True,
    name='BEE2',
)
