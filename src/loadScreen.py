"""Displays a loading menu while packages, palettes, etc are being loaded."""
from tkinter import *
from tk_tools import TK_ROOT
from tkinter import ttk

from weakref import WeakSet
from abc import abstractmethod
import contextlib
import multiprocessing

from loadScreen_daemon import run_screen as _splash_daemon
import utils

# Keep a reference to all loading screens, so we can close them globally.
_ALL_SCREENS = WeakSet()

LOGGER = utils.getLogger(__name__)


def close_all():
    """Hide all loadscreen windows."""
    for screen in _ALL_SCREENS:
        screen.reset()


@contextlib.contextmanager
def surpress_screens():
    """A context manager to supress loadscreens while the body is active."""
    active = []
    for screen in _ALL_SCREENS:
        if not screen.active:
            continue
        screen.wm_focusmodel()
        screen.withdraw()
        screen.active = False
        active.append(screen)

    yield

    for screen in active:
        screen.deiconify()
        screen.active = True
        screen.lift()


def patch_tk_dialogs():
    """Patch various tk windows to hide loading screens while they're are open.

    """
    from tkinter import commondialog

    # contextlib managers can also be used as decorators.
    supressor = surpress_screens()  # type: contextlib.ContextDecorator
    # Mesageboxes, file dialogs and colorchooser all inherit from Dialog,
    # so patching .show() will fix them all.
    commondialog.Dialog.show = supressor(commondialog.Dialog.show)

patch_tk_dialogs()


class BaseLoadScreen:
    """Code common to both loading screen types."""
    def __init__(self, stages):
        self.stages = list(stages)
        self.labels = {}
        self.bar_val = {}
        self.maxes = {}

        self.active = False
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything

    def __enter__(self):
        """LoadScreen can be used as a context manager.

        Inside the block, the screen will be visible.
        """
        self.show()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Hide the loading screen, and passthrough execptions.
        """
        self.reset()

    # Methods the subclasses must implement.
    
    @abstractmethod
    def set_length(self, stage: str, num: str):
        pass

    @abstractmethod
    def step(self, stage: str):
        pass

    @abstractmethod
    def skip_stage(self, stage: str):
        """Skip over this stage of the loading process."""
        pass
        
    @abstractmethod
    def show(self):
        """Display the loading screen."""
        pass

    @abstractmethod
    def reset(self):
        """Hide the loading screen and reset all the progress bars."""
        pass


class LoadScreen(BaseLoadScreen, Toplevel):
    """LoadScreens show a loading screen for items.

    stages should be (id, title) pairs for each screen stage.
    Each stage can be stepped independently, referenced by the given ID.
    The title can be blank.
    """
    def __init__(self, *stages, title_text):
        BaseLoadScreen.__init__(self, stages)
        self.bar_var = {}
        self.widgets = {}
        
        # Initialise the window
        Toplevel.__init__(
            self,
            TK_ROOT,
            cursor=utils.CURSORS['wait'],
        )
        self.withdraw()

        _ALL_SCREENS.add(self)
        
        # this prevents stuff like the title bar, normal borders etc from
        # appearing in this window.
        self.overrideredirect(1)
        self.resizable(False, False)
        self.attributes('-topmost', 1)

        self.frame = ttk.Frame(self, cursor=utils.CURSORS['wait'])
        self.frame.grid(row=0, column=0)

        ttk.Label(
            self.frame,
            text=title_text + '...',
            font=("Helvetica", 12, "bold"),
            cursor=utils.CURSORS['wait'],
            ).grid(columnspan=2)
        ttk.Separator(
            self.frame,
            orient=HORIZONTAL,
            cursor=utils.CURSORS['wait'],
            ).grid(row=1, sticky="EW", columnspan=2)

        for ind, (st_id, stage_name) in enumerate(self.stages):
            if stage_name:
                # If stage name is blank, don't add a caption
                ttk.Label(
                    self.frame,
                    text=stage_name + ':',
                    cursor=utils.CURSORS['wait'],
                    ).grid(
                        row=ind*2+2,
                        columnspan=2,
                        sticky="W",
                        )
            self.bar_var[st_id] = IntVar()
            self.bar_val[st_id] = 0
            self.maxes[st_id] = 10

            self.widgets[st_id] = ttk.Progressbar(
                self.frame,
                length=210,
                maximum=1000,
                variable=self.bar_var[st_id],
                cursor=utils.CURSORS['wait'],
                )
            self.labels[st_id] = ttk.Label(
                self.frame,
                text='0/??',
                cursor=utils.CURSORS['wait'],
            )
            self.widgets[st_id].grid(row=ind*2+3, column=0, columnspan=2)
            self.labels[st_id].grid(row=ind*2+2, column=1, sticky="E")
            
    def show(self):
        """Display this loading screen."""
        self.active = True
        self.deiconify()
        self.lift()
        self.update()  # Force an update so the reqwidth is correct
        loc_x = (self.winfo_screenwidth()-self.winfo_reqwidth())//2
        loc_y = (self.winfo_screenheight()-self.winfo_reqheight())//2
        self.geometry('+' + str(loc_x) + '+' + str(loc_y))
        self.update()  # Force an update of the window to position it

    def step(self, stage):
        """Increment a stage by one."""
        self.bar_val[stage] += 1
        self.set_nums(stage)
        if self.active:
            self.widgets[stage].update()
            
    def set_length(self, stage, num):
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.set_nums(stage)

    def set_nums(self, stage):
        """Set the fraction text for a stage."""
        max_val = self.maxes[stage]
        if max_val == 0:  # 0/0 sections are skipped automatically.
            self.bar_var[stage].set(1000)
        else:
            self.bar_var[stage].set(
                1000 * self.bar_val[stage] / max_val
            )
        self.labels[stage]['text'] = '{!s}/{!s}'.format(
            self.bar_val[stage],
            max_val,
        )

    def skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        self.labels[stage]['text'] = _('Skipped!')
        self.bar_var[stage].set(1000)  # Make sure it fills to max

        if self.active:
            self.widgets[stage].update()

    def reset(self):
        """Hide the loading screen, and reset stages to zero."""
        self.withdraw()
        self.active = False
        for stage, _ in self.stages:
            self.maxes[stage] = 10
            self.bar_val[stage] = 0
            self.bar_var[stage].set(0)
            self.labels[stage]['text'] = '0/??'
            self.set_nums(stage)

    def destroy(self):
        """Delete all parts of the loading screen."""
        if self.active:
            super().destroy()
            del self.widgets
            del self.maxes
            del self.bar_var
            del self.bar_val
            self.active = False
            _ALL_SCREENS.discard(self)


class SplashScreen(BaseLoadScreen):
    """The screen shown for the main loading screen. It only works once.
    
    This is implemented as a subprocess, to enable interacting with
    the UI while loading occurs. TKinter does not play well with 
    multiple threads, and Python's GIL makes that difficult as well.
    """

    def __init__(self, *stages):
        super().__init__(stages)
        self.values = {
            stage_id: 0 
            for stage_id, disp_name in 
            stages
        }
        
        self.maxes = {
            stage_id: 10 
            for stage_id, disp_name in 
            stages
        }
        
        # self.pipe -> sub_conn
        sub_conn, self._pipe = multiprocessing.Pipe(duplex=False)
        
        self._subproc = multiprocessing.Process(
            target=_splash_daemon,
            # Pass lots of data along, so it doesn't have to import
            # things to calculate those itself.
            args=(
                sub_conn,
                stages,
                _('Better Extended Editor for Portal 2'),
                _('Version: ') + utils.BEE_VERSION,
                _('Skipped!'),
            ),
            name='BEE2_splashscreen',
        )
        # Destroy when we quit, in case of errors
        self._subproc.daemon = True
        
        self.active = True
            
    def show(self):
        """Start the process."""
        self._subproc.start()

    def step(self, stage):
        """Increment a step by one."""
        self.values[stage] += 1
        self._pipe.send((stage, 'value', self.values[stage]))

    def set_length(self, stage, num):
        """Set the number of items in a stage."""
        self._pipe.send((stage, 'length', num))

    def skip_stage(self, stage: str):
        """Skip over this stage of the loading process."""
        self._pipe.send((stage, 'skip', None))

    def destroy(self):
        """Delete all parts of the loading screen."""
        if self.active:
            del self.values
            del self.maxes
            self._pipe.send((None, None, None)) # Instruct subprocess to self-destruct.
            self.active = False
            _ALL_SCREENS.discard(self)
            self._subproc.join()  # Wait until quit.

    reset = destroy

main_loader = SplashScreen(
    ('PAK', _('Packages')),
    ('OBJ', _('Loading Objects')),
    ('IMG', _('Loading Images')),
    ('UI', _('Initialising UI')),
)
