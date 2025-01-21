import io
import os
import sys
import shutil
import zipfile
from pathlib import Path
import contextlib
from typing import Iterable, List, Optional, Tuple, Union

from babel.messages import Catalog
import babel.messages.frontend
import babel.messages.extract
from babel.messages.pofile import read_po, write_po
from babel.messages.mofile import write_mo
from srctools.fgd import FGD

ico_path = os.path.realpath(os.path.join(os.getcwd(), "../bee2.ico"))

# Injected by PyInstaller.
workpath: str = globals()['workpath']
SPECPATH: str = globals()['SPECPATH']
DISTPATH: str = globals()['DISTPATH']

hammeraddons = Path.joinpath(Path(SPECPATH).parent, 'hammeraddons')

# Allow importing utils.
sys.path.append(SPECPATH)
import utils

# src -> binaries subfolder.
data_bin_files = [
    ('../BEE2.ico', '.'),
    ('../BEE2.fgd', '.'),
    ('../hammeraddons.fgd', '.'),
]
# src -> app subfolder, in 6.0+
data_files = [
    ('../images/BEE2/*.png', 'images/BEE2/'),
    ('../images/icons/*.png', 'images/icons/'),
    ('../images/splash_screen/*.jpg', 'images/splash_screen/'),
    ('../sounds/*.ogg', 'sounds'),
    ('../INSTALL_GUIDE.txt', '.'),
]

HA_VERSION = utils.get_git_version(hammeraddons)


def copy_datas(appfolder: Path, compiler_loc: str) -> None:
    """Copy `datas_files` files to the root of the app folder."""
    for gl_src, dest in data_files:
        for filename in Path().glob(gl_src):
            name = filename.name
            if name == 'INSTALL_GUIDE.txt':
                # Special case, use a different name.
                name = 'README.txt'

            p_dest = Path(appfolder, dest, name)

            print(filename, '->', p_dest)
            p_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(filename, p_dest)

    (appfolder / 'packages').mkdir(exist_ok=True)

    compiler_dest = Path(appfolder, 'bin', 'compiler')
    print(compiler_loc, '->', compiler_dest)
    shutil.copytree(compiler_loc, compiler_dest)


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
        if 'test_localisation' in filename or 'test_transtoken' in filename:
            # Test code for the localisation module, skip these tokens.
            continue
        elif 'user_errors.py' in filename and all('game_text' not in comm for comm in comments):
            # Tokens for the error display are here, so indicate they accept HTML.
            # But not the message shown in game_text.
            comments.append('This uses HTML syntax.')
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
            trans_cat: babel.messages.Catalog = read_po(src, locale)
        trans_cat.update(catalog)

        # Go through, and discard untranslated and removed messages.
        for msg_id in [
            msg.id for msg in trans_cat.obsolete.values()
            if not msg.string
        ]:
            del trans_cat.obsolete[msg_id]

        with io.BytesIO() as buffer:
            write_po(buffer, trans_cat, include_lineno=False)
            if utils.write_lang_pot(trans, buffer.getvalue()):
                print(f'Written {trans}')

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
    sys.path.append(str(hammeraddons / 'src'))
    print('Loading FGD database. path=', sys.path)
    from hammeraddons import unify_fgd
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
        file.write(f'// Hammer Addons version {HA_VERSION}\n')
        file.write(
            "// These are a minimal copy of HA FGDs for comp_ entities, so they can be collapsed.\n"
            "// If you want to use Hammer Addons, install that manually, don't use these.\n"
        )
        fgd.export(file)


do_localisation()
build_fgd()


# Exclude bits of modules we don't need, to decrease package size.
EXCLUDES = [
    'idlelib',
    'numpy',  # PIL.ImageFilter imports, we don't need NumPy!
    'stackscope',  # Only used in dev.

    'bz2',  # We aren't using this compression format (shutil, zipfile etc handle ImportError)..

    # Imported by logging handlers which we don't use...
    'win32evtlog',
    'win32evtlogutil',
    'smtplib',

    # Pulls in all of pytest etc, not required.
    'trio.testing',
    # Trio -> CFFI -> uses setuptools for C compiler in some modes, but
    # trio doesn't use those.
    'setuptools',

    'markupsafe',  # Used by TransToken.translate_html(), only relevant for Jinja.

    'unittest',  # Imported in __name__==__main__..
    'doctest',
    'optparse',
    'argparse',
]

binaries = []
if utils.WIN:
    lib_path = Path(SPECPATH, '..', 'lib-' + utils.BITNESS).resolve()
    ci_folder = Path(SPECPATH, '..', 'libs').resolve()
    ci_zip = list(ci_folder.glob('*.zip'))
    if ci_zip:
        # Downloaded from releases, unpack.
        with zipfile.ZipFile(ci_zip[0]) as zipf:
            for info in zipf.infolist():
                if info.filename.endswith('.dll'):
                    dest = Path(ci_folder, Path(info.filename).name).resolve()
                    with zipf.open(info) as srcf, dest.open('wb') as destf:
                        shutil.copyfileobj(srcf, destf)
                    binaries.append((str(dest), '.'))
    else:
        try:
            for dll in lib_path.iterdir():
                if dll.suffix == '.dll' and dll.stem.startswith(('av', 'swscale', 'swresample')):
                    binaries.append((str(dll), '.'))
        except FileNotFoundError:  # Make the directory for the user to copy to.
            lib_path.mkdir(exist_ok=True)
            pass

    if not binaries:  # Not found.
        raise ValueError(f'FFmpeg dlls should be downloaded into "{lib_path}".')


# Write this to the temp folder, so it's picked up and included.
# Don't write it out though if it's the same, so PyInstaller doesn't reparse.
version_val = f'''\
BEE_VERSION={utils.get_git_version(SPECPATH)!r}
HA_VERSION={HA_VERSION!r}
'''
print(version_val)
version_filename = os.path.join(workpath, '_compiled_version.py')

with contextlib.suppress(FileNotFoundError), open(version_filename) as f:
    if f.read() == version_val:
        version_val = ''

if version_val:
    with open(version_filename, 'w') as f:
        f.write(version_val)

# Include the compiler, picking the right architecture.
bitness = 64 if sys.maxsize > (2**33) else 32
COMPILER_LOC = f'../dist/{bitness}bit/compiler/'

# Finally, run the PyInstaller analysis process.

bee2_a = Analysis(
    ['BEE2_launch.py'],
    pathex=[workpath],
    datas=data_files + data_bin_files,
    hiddenimports=[
        'PIL._tkinter_finder',
        # Needed to unpickle the CLDR.
        'babel.numbers',
    ],
    binaries=binaries,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False
)

pyz = PYZ(
    bee2_a.pure,
    bee2_a.zipped_data,
)

bee_exe = EXE(
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
    contents_directory='bin',
    windowed=True,
    icon='../BEE2.ico'
)

backup_exe = EXE(
    pyz,
    bee2_a.scripts,
    [],
    exclude_binaries=True,
    name='backup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    contents_directory='bin',
    windowed=True,
    icon='../BEE2.ico'
)

compiler_settings_exe = EXE(
    pyz,
    bee2_a.scripts,
    [],
    exclude_binaries=True,
    name='compiler_settings',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    contents_directory='bin',
    windowed=True,
    icon='../BEE2.ico'
)

coll = COLLECT(
    bee_exe, backup_exe, compiler_settings_exe,
    bee2_a.binaries,
    bee2_a.zipfiles,
    bee2_a.datas,
    strip=False,
    upx=True,
    name='BEE2',
)

copy_datas(Path(coll.name), COMPILER_LOC)
