import os
import sys
from pathlib import Path
import contextlib
from typing import Any, Iterable, List, Optional, Tuple, Union, cast

from babel.messages import Catalog
import babel.messages.frontend
import babel.messages.extract
from babel.messages.pofile import read_po, write_po
from babel.messages.mofile import write_mo
from srctools.fgd import FGD

ico_path = os.path.realpath(os.path.join(os.getcwd(), "../bee2.ico"))
# Injected by PyInstaller.
workpath: str
SPECPATH: str

hammeraddons = Path.joinpath(Path(SPECPATH).parent, 'hammeraddons')

# Allow importing utils.
sys.path.append(SPECPATH)
import utils

# src -> build subfolder.
data_files = [
    ('../BEE2.ico', '.'),
    ('../BEE2.fgd', '.'),
    ('../hammeraddons.fgd', '.'),
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

    # Type hint specifies -> None, incorrect.
    extracted: Iterable[tuple[
        str, int, Union[str, Tuple[str, ...]], List[str], Optional[str]
    ]]
    extracted = babel.messages.extract.extract_from_dir(  # type: ignore  # noqa
        '.',
        comment_tags=['i18n:'],
        keywords={
            **babel.messages.extract.DEFAULT_KEYWORDS,
            'ui': (1, ),
            'ui_plural': (1, 2),
        },
    )
    for filename, lineno, message, comments, context in extracted:
        if 'test_localisation' in filename:
            # Test code for the localisation module, skip these tokens.
            continue
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

    # Build out the English translation from the template.
    catalog.locale = 'en'
    with (i18n / 'en.mo').open('wb') as dest:
        write_mo(dest, catalog)

    data_files.append((str(i18n / 'en.mo'), 'i18n/'))


def build_fgd() -> None:
    """Export out a copy of the srctools-specific FGD data."""
    sys.path.append(str(hammeraddons))
    print('Loading FGD database...')
    from hammeraddons import unify_fgd, __version__ as version
    database, base_ent = unify_fgd.load_database(hammeraddons / 'fgd')

    fgd = FGD()

    # HammerAddons tags relevant to P2.
    fgd_tags = frozenset({
        'SINCE_HL2', 'SINCE_HLS', 'SINCE_EP1', 'SINCE_EP2', 'SINCE_TF2',
        'SINCE_P1', 'SINCE_L4D', 'SINCE_L4D2', 'SINCE_ASW', 'SINCE_P2',
        'P2', 'UNTIL_CSGO', 'VSCRIPT', 'INST_IO'
    })

    for ent in database:
        ent.strip_tags(fgd_tags)
        if ent.classname.startswith('comp_') or ent.classname == "hammer_notes":
            fgd.entities[ent.classname] = ent
            ent.helpers = [
                helper for helper in ent.helpers
                if not helper.IS_EXTENSION
            ]

    database.collapse_bases()
    with open('../hammeraddons.fgd', 'w') as file:
        file.write(f'// Hammer Addons version {version}\n')
        file.write(
            "// These are a minimal copy of HA FGDs for comp_ entities, so they can be collapsed.\n"
            "// If you want to use Hammer Addons, install that manually, don't use these.\n"
        )
        fgd.export(file)


do_localisation()
build_fgd()


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
