from cx_Freeze import setup, Executable
import os, shutil
import utils

shutil.rmtree('build_BEE2', ignore_errors=True)

ico_path = os.path.join(os.getcwd(), "../bee2.ico")

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

    'inspect',
    'pkgutil',

    'unittest',  # Imported in __name__==__main__..
    'doctest',
    'optparse',
    'argparse',
]


if not utils.MAC:
    EXCLUDES.append('platform')  # Only used in the mac pyglet code..

]

if utils.WIN:
    base = 'Win32GUI'
else:
    base = None

bee_version = input('BEE2 Version: ')


setup(
    name='BEE2',
    version='2.4',
    description='Portal 2 Puzzlemaker item manager.',
    options={
        'build_exe': {
            'build_exe': '../build_BEE2/bin',
            'excludes': EXCLUDES,
            # These values are added to the generated BUILD_CONSTANTS module.
            'constants': 'BEE_VERSION=' + repr(bee_version),
        },
    },
    executables=[
        Executable(
            'BEE2.pyw',
            base=base,
            icon=ico_path,
            compress=True,
        ),
        Executable(
            'backup.py',
            base=base,
            icon=ico_path,
            compress=True,
            targetName='backup_tool' + ('.exe' if utils.WIN else ''),
        )
    ],
)
