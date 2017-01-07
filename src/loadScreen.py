"""Displays a loading menu while packages, palettes, etc are being loaded."""
from tkinter import *  # ui library
from tkinter.font import Font
from tk_tools import TK_ROOT
from tkinter import ttk

from weakref import WeakSet
from abc import abstractmethod
import contextlib

import utils
import img

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


class BaseLoadScreen(Toplevel):
    """Code common to both loading screen types."""
    def __init__(self, stages):
        self.stages = list(stages)
        self.widgets = {}
        self.labels = {}
        self.bar_val = {}
        self.maxes = {}

        self.active = False
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything.

        # Initialise the window
        super().__init__(
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

    def show(self):
        """Display this loading screen."""
        self.active = True
        self.deiconify()
        self.update()  # Force an update so the reqwidth is correct
        loc_x = (self.winfo_screenwidth()-self.winfo_reqwidth())//2
        loc_y = (self.winfo_screenheight()-self.winfo_reqheight())//2
        self.geometry('+' + str(loc_x) + '+' + str(loc_y))
        self.update()  # Force an update of the window to position it

    def set_length(self, stage, num):
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.set_nums(stage)

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
    def set_nums(self, stage: str):
        pass

    @abstractmethod
    def step(self, stage: str):
        pass

    @abstractmethod
    def skip_stage(self, stage: str):
        """Skip over this stage of the loading process."""
        pass

    @abstractmethod
    def reset(self):
        """Hide the loading screen and reset all the progress bars."""
        pass


class LoadScreen(BaseLoadScreen):
    """LoadScreens show a loading screen for items.

    stages should be (id, title) pairs for each screen stage.
    Each stage can be stepped independently, referenced by the given ID.
    The title can be blank.
    """
    def __init__(self, *stages, title_text):
        super().__init__(stages)
        self.bar_var = {}

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

    def step(self, stage):
        """Increment a step by one."""
        self.bar_val[stage] += 1
        self.set_nums(stage)
        if self.active:
            self.widgets[stage].update()

    def set_nums(self, stage):
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
        self.labels[stage]['text'] = _('Skipped!')
        self.bar_var[stage].set(1000)  # Make sure it fills to max

        if self.active:
            self.widgets[stage].update()

    def reset(self):
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
    """The screen show for the main loading screen."""

    def __init__(self, *stages):
        super().__init__(stages)
        self.stage_names = {}
        self.bars = {}

        self.splash, width, height = img.get_splash_screen(
            self.winfo_screenwidth() * 0.6,
            self.winfo_screenheight() * 0.6,
            base_height=len(self.stages) * 20,
        )
        self.height = height
        self.width = width

        self.canvas = canvas = Canvas(
            self,
            width=width,
            height=height
        )
        canvas.grid(row=0, column=0)
        # Splash screen...
        canvas.create_image(
            0, 0,
            anchor='nw',
            image=self.splash,
        )
        canvas.create_image(
            10, 10,
            anchor='nw',
            image=img.png('BEE2/splash_logo'),
        )

        self.disp_font = font = Font(
            family='Times',  # Generic special case
            size=-18,  # negative = in pixels
            weight='bold',
        )

        canvas.create_text(
            10, 125,
            anchor='nw',
            text=_('Better Extended Editor for Portal 2'),
            fill='white',
            font=font,
        )
        canvas.create_text(
            10, 145,
            anchor='nw',
            text=_('Version: ') + utils.BEE_VERSION,
            fill='white',
            font=font,
        )

        for ind, (st_id, stage_name) in enumerate(reversed(self.stages), start=1):
            self.bar_val[st_id] = 0
            self.maxes[st_id] = 10
            self.stage_names[st_id] = stage_name
            self.bars[st_id] = canvas.create_rectangle(
                20,
                height - (ind + 0.5) * 20,
                20,
                height - (ind - 0.5) * 20,
                fill='#00785A',  # 0, 120, 90
                width=0,
            )
            # Border
            canvas.create_rectangle(
                20,
                height - (ind + 0.5) * 20,
                width - 20,
                height - (ind - 0.5) * 20,
                outline='#00785A',
                width=2,
            )
            self.widgets[st_id] = canvas.create_text(
                25,
                height - ind * 20,
                anchor='w',
                text=stage_name + ': (0/??)',
            )

    def step(self, stage):
        """Increment a step by one."""
        self.bar_val[stage] += 1
        self.set_nums(stage)
        self.canvas.update()

    def set_nums(self, stage: str):
        max_val = self.maxes[stage]
        self.canvas.itemconfig(
            self.widgets[stage],
            text='{}: {}/{}'.format(
                self.stage_names[stage],
                self.bar_val[stage],
                max_val,
            )
        )
        self.bar_length(stage, self.bar_val[stage] / max_val)
        self.canvas.update()

    def skip_stage(self, stage: str):
        self.bar_val[stage] = 0
        self.maxes[stage] = 0
        self.canvas.itemconfig(
            self.widgets[stage],
            text=self.stage_names[stage] + ': ' + _('Skipped!'),
        )
        self.bar_length(stage, 1)
        self.canvas.update()

    def bar_length(self, stage, fraction):
        """Set a progress bar to this fractional length."""
        x1, y1, x2, y2 = self.canvas.coords(self.bars[stage])
        self.canvas.coords(
            self.bars[stage],
            20,
            y1,
            20 + round(fraction * (self.width-40)),
            y2,
        )

    def destroy(self):
        """Delete all parts of the loading screen."""
        if self.active:
            super().destroy()
            del self.widgets
            del self.bars
            del self.maxes
            del self.splash
            del self.bar_val
            self.active = False
            _ALL_SCREENS.discard(self)

    def reset(self):
        self.withdraw()
        self.active = False
        for stage, stage_name in self.stages:
            self.maxes[stage] = 10
            self.bar_val[stage] = 0
            self.bar_length(stage, 0)
            self.canvas.itemconfig(self.labels[stage], stage_name + ': (0/??)')
            self.set_nums(stage)

main_loader = SplashScreen(
    ('PAK', _('Packages')),
    ('OBJ', _('Loading Objects')),
    ('IMG_EX', _('Extracting Images')),
    ('IMG', _('Loading Images')),
    ('UI', _('Initialising UI')),
)
