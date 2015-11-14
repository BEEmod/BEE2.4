from cx_Freeze import setup, Executable
import os, shutil
import utils

shutil.rmtree('build_BEE2', ignore_errors=True)

ico_path = os.path.join(os.getcwd(), "../bee2.ico")

# Exclude bits of modules we don't need, to decrease package size.
EXCLUDES = [
    # Just using the core and .mixer
    'pygame.math',
    'pygame.cdrom',
    'pygame.cursors',
    'pygame.display',
    'pygame.draw',
    'pygame.event',
    'pygame.image',
    'pygame.joystick',
    'pygame.key',
    'pygame.mouse',
    'pygame.sprite',
    'pygame.threads',
    'pygame.pixelcopy',
    'pygame.mask',
    'pygame.pixelarray',
    'pygame.overlay',
    'pygame.time',
    'pygame.transform',
    'pygame.font',
    'pygame.sysfont',
    'pygame.movie',
    'pygame.movieext',
    'pygame.scrap',
    'pygame.surfarray',
    'pygame.sndarray',
    'pygame.fastevent',

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
]

if utils.WIN:
    base = 'Win32GUI'
else:
    base = None

setup(
    name='BEE2',
    version='2.4',
    description='Portal 2 Puzzlemaker item manager.',
    options={
        'build_exe': {
            'build_exe': '../build_BEE2/bin',
            'excludes': EXCLUDES,
        },
    },
    executables=[
        Executable(
            'BEE2.pyw',
            base=base,
            icon=ico_path,
            compress=True,
        )
    ],
)
