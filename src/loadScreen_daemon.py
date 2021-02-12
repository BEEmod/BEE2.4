"""Implements the splash screen in a subprocess.

During package loading, we are busy performing tasks in the main thread.
We do this in another process to sidestep the GIL, and ensure the screen
remains responsive. This is a separate module to reduce the required dependencies.
"""
import os
import sys
from typing import Optional, Dict, Tuple, List, Iterator

from tkinter.font import Font
import tkinter as tk
import wx
import multiprocessing.connection

import utils
import random

# ID -> screen.
SCREENS: Dict[int, 'BaseLoadScreen'] = {}

PIPE_REC: multiprocessing.connection.Connection
PIPE_SEND: multiprocessing.connection.Connection

# Stores translated strings, which are done in the main process.
TRANSLATION = {
    'skip': 'Skipped',
    'version': 'Version: 2.4.389',
    'cancel': 'Cancel',
}

# The window style for loadscreens.
WIN_STYLE = wx.NO_BORDER


def window_children(win: wx.Window) -> Iterator[wx.Window]:
    """Iterate through all the children of this window, including itself."""
    yield win
    if win.GetSizer():
        yield from _iter_sizer(win.GetSizer())


def _iter_sizer(sizer: wx.Sizer) -> Iterator[wx.Window]:
    size_item: wx.SizerItem
    for size_item in sizer:
        child = size_item.GetWindow()
        if child:
            yield from window_children(child)
        if size_item.GetSizer():
            yield from _iter_sizer(size_item.GetSizer())


def get_splash_image(
    max_width: float,
    max_height: float,
) -> wx.Bitmap:
    """Get the splash screen images.

    This uses a random screenshot from the splash_screens directory.
    It then adds the gradients on top.
    """
    folder = str(utils.install_path('images/splash_screen'))
    path = '<nothing>'
    try:
        path = random.choice(os.listdir(folder))
        image = wx.Image(os.path.join(folder, path))
    except (FileNotFoundError, IndexError, IOError):
        # Not found, substitute a gray block.
        print(f'No splash screen found (tried "{path}")', file=sys.stderr)
        return wx.Bitmap.FromRGBA(
            round(max_width), round(max_height),
            128, 128, 128, 255,
        )
    else:
        if image.Height > max_height:
            image.Rescale(
                round(image.Width / image.Height * max_height),
                round(max_height),
            )
        if image.Width > max_width:
            image.Rescale(
                round(max_width),
                round(image.Height / image.Width * max_width),
            )
        return wx.Bitmap(image)


class BaseLoadScreen:
    """Code common to both loading screen types."""
    def __init__(
        self,
        scr_id: int,
        title_text: str,
        force_ontop: bool,
        stages: List[Tuple[str, str]],
    ) -> None:
        self.scr_id = scr_id
        self.title_text = title_text

        style = WIN_STYLE
        if force_ontop:
            style |= wx.STAY_ON_TOP

        self.win = wx.Frame(None, style=style, name=title_text)
        self.win.Cursor = wx.Cursor(wx.CURSOR_WAIT)
        self.win.Hide()

        self.values = {}
        self.maxes = {}
        self.names = {}
        self.stages = stages
        self.is_shown = False

        for st_id, stage_name in stages:
            self.values[st_id] = 0
            self.maxes[st_id] = 10
            self.names[st_id] = stage_name

        # Because there's no border, we have to manually do dragging.
        self.drag_x: Optional[int] = None
        self.drag_y: Optional[int] = None

    def bind_events(self, wid: wx.Window) -> None:
        """Bind event handlers to all the widgets in the window."""
        # Reuse the same method objects.
        start = self.move_start
        stop = self.move_stop
        move = self.move_motion
        cancel = self.cancel

        for win in window_children(wid):
            if not isinstance(win, wx.Button):
                win.Bind(wx.EVT_LEFT_DOWN, start)
                win.Bind(wx.EVT_LEFT_UP, stop)
                win.Bind(wx.EVT_MOTION, move)
                win.Bind(wx.EVT_KEY_UP, cancel)

    def cancel(self, event: wx.Event=None) -> None:
        """User pressed the cancel button."""
        if isinstance(event, wx.KeyEvent) and event.GetKeyCode() != wx.WXK_ESCAPE:
            # Not the escape key.
            event.Skip()
            return

        self.op_reset()
        PIPE_SEND.send(('cancel', self.scr_id))

    def move_start(self, event: wx.MouseEvent) -> None:
        """Record offset of mouse on click."""
        self.win.Cursor = wx.Cursor(wx.CURSOR_CROSS)  # Or SIZE_NSEW?
        self.win.CaptureMouse()
        event.Skip()  # Allow normal focus processing to take place.

    def move_stop(self, event: wx.MouseEvent) -> None:
        """Clear values when releasing."""
        self.win.Cursor = wx.Cursor(wx.CURSOR_WAIT)
        self.win.ReleaseMouse()
        self.drag_x = self.drag_y = None

    def move_motion(self, event: wx.MouseEvent) -> None:
        """Move the window when moving the mouse."""
        if not event.LeftIsDown():
            return
        if self.drag_x is None or self.drag_y is None:
            # This doesn't get set right in on-press, so we have to
            # store off the first position.
            self.drag_x, self.drag_y = event.GetPosition().Get()
            return

        pos_x, pos_y = self.win.GetPosition().Get()
        mouse_x, mouse_y = event.GetPosition().Get()
        self.win.MoveXY(
            x=pos_x + (mouse_x - self.drag_x),
            y=pos_y + (mouse_y - self.drag_y),
        )

    def op_show(self) -> None:
        """Show the window."""
        self.is_shown = True
        self.win.Show()
        self.win.Raise()
        self.win.Center()

    def op_hide(self) -> None:
        self.is_shown = False
        # We must not have the mouse captured when hiding the window.
        self.win.ReleaseMouse()
        self.win.Hide()

    def op_reset(self) -> None:
        """Hide and reset values in all bars."""
        self.op_hide()
        for stage in self.values.keys():
            self.maxes[stage] = 10
            self.values[stage] = 0
        self.reset_stages()

    def op_step(self, stage: str) -> None:
        """Increment the specified value."""
        self.values[stage] += 1
        self.update_stage(stage)

    def op_set_length(self, stage: str, num: int) -> None:
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.update_stage(stage)

    def op_skip_stage(self, stage: str) -> None:
        """Skip over this stage of the loading process."""
        raise NotImplementedError

    def update_stage(self, stage: str) -> None:
        """Update the UI for the given stage."""
        raise NotImplementedError

    def reset_stages(self) -> None:
        """Return the UI to the initial state with unknown max."""
        raise NotImplementedError

    def op_destroy(self) -> None:
        """Remove this screen."""
        self.win.Show(False)
        self.win.Destroy()
        del SCREENS[self.scr_id]


class LoadScreen(BaseLoadScreen):
    """Normal loading screens."""

    def __init__(self, *args) -> None:
        super().__init__(*args)

        sizer_vert = wx.BoxSizer(wx.VERTICAL)

        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer_vert.Add(title_sizer)

        title_wid = wx.StaticText(self.win, label=self.title_text + '...')
        title_wid.SetFont(wx.Font(15, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        title_sizer.Add(title_wid, wx.EXPAND)

        sizer_vert.Add(wx.StaticLine(self.win, style=wx.LI_HORIZONTAL))

        title_sizer.Add(wx.Button(self.win, wx.ID_CANCEL))
        self.win.Bind(wx.EVT_BUTTON, self.cancel, id=wx.ID_CANCEL)

        # self.bar_var = {}
        self.bars: Dict[str, wx.Gauge] = {}
        self.labels: Dict[str, wx.StaticText] = {}

        stage_sizer = wx.GridBagSizer()
        sizer_vert.Add(stage_sizer, proportion=1, flag=wx.EXPAND)

        for ind, (st_id, stage_name) in enumerate(self.stages):
            if stage_name:
                # If stage name is blank, don't add a caption
                name_wid = wx.StaticText(self.win, label=stage_name + ':')
                stage_sizer.Add(name_wid, pos=(ind*2 + 0, 0), flag=wx.EXPAND | wx.ALIGN_LEFT)
            else:
                # Add a spacer.
                stage_sizer.Add(0, 0, pos=(ind*2 + 0, 0), flag=wx.EXPAND)

            self.bars[st_id] = bar = wx.Gauge(
                self.win,
                style=wx.GA_HORIZONTAL | wx.GA_SMOOTH,
                range=1000,
            )
            self.labels[st_id] = label = wx.StaticText(self.win, label='0/??')
            stage_sizer.Add(bar, (ind * 2 + 1, 0), span=(1, 2), flag=wx.EXPAND)
            stage_sizer.Add(label, (ind * 2 + 0, 1), flag=wx.ALIGN_RIGHT)

        stage_sizer.AddGrowableCol(0)
        self.stage_sizer = stage_sizer
        self.win.SetSizerAndFit(sizer_vert)
        self.bind_events(self.win)


    def reset_stages(self) -> None:
        """Put the stage in the initial state, before maxes are provided."""
        for stage in self.values.keys():
            self.bars[stage].SetValue(0)
            self.labels[stage].LabelText = '0/??'

    def update_stage(self, stage: str) -> None:
        """Redraw the given stage."""
        max_val = self.maxes[stage]
        if max_val == 0:  # 0/0 sections are skipped automatically.
            self.bars[stage].Value = 1000
            self.bars[stage].Range = 1000
        else:
            self.bars[stage].Value = self.values[stage]
            self.bars[stage].Range = max_val
        self.labels[stage].LabelText = '{!s}/{!s}'.format(
            self.values[stage],
            max_val,
        )
        self.win.GetSizer().Layout()

    def op_skip_stage(self, stage: str) -> None:
        """Skip over this stage of the loading process."""
        self.values[stage] = 0
        self.maxes[stage] = 0
        self.labels[stage].LabelText = TRANSLATION['skip']
        # Make sure it fills to max
        self.bars[stage].Value = 1000
        self.bars[stage].Range = 1000


class SplashScreen(BaseLoadScreen):
    """The splash screen shown when booting up."""

    def __init__(self, *args):
        super().__init__(*args)

        self.is_compact = True

        # Default to the system GUI if others can't be found.
        font: wx.Font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        # Try and find DIN, then Univers in that order.
        # If not, we'll reset to what it was.
        for name in ['DIN', 'Univers', font.GetFaceName()]:
            font.SetFaceName(name)
            if font.IsOk():
                break

        self.font = font.GetBaseFont()
        self.font.SetPixelSize((0, 18))
        self.font.MakeBold()

        self.progress_font = font.GetBaseFont()
        self.progress_font.SetPixelSize((0, 12))

        screen_width = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_X, self.win)
        screen_height = wx.SystemSettings.GetMetric(wx.SYS_SCREEN_Y, self.win)

        self.sml_width = int(min(0.5 * screen_width, 400))
        self.sml_height = int(min(0.5 * screen_height, 175))

        self.logo = wx.Bitmap()
        self.logo.LoadFile(str(utils.install_path('images/BEE2/splash_logo.png')))

        icons = wx.Image()
        icons.LoadFile(str(utils.install_path('images/BEE2/splash_icons.png')))
        arrow: wx.Image = icons.Copy().Resize((20, 20), (0, 0))
        self.contract_ico = wx.Bitmap(arrow)
        self.expand_ico = wx.Bitmap(arrow.Rotate180())
        self.quit_ico = wx.Bitmap(icons.Copy().Resize((20, 20), (-20, 0)))

        self.splash_bg = get_splash_image(
            max(screen_width * 0.6, 500),
            max(screen_height * 0.6, 500),
        )
        self.lrg_width = self.splash_bg.Width
        self.lrg_height = self.splash_bg.Height

        # To avoid flickering when rendering the bars, first render to a bitmap.
        self.bars_buff = wx.Bitmap()
        self.last_buff = None
        self.bars_dc = wx.MemoryDC()

        self.win.Bind(wx.EVT_PAINT, self.on_paint)
        self.win.Bind(wx.EVT_LEFT_DCLICK, self.toggle_compact)
        self.win.Bind(wx.EVT_LEFT_UP, self.clicked)

        self.win.Bind(wx.EVT_LEFT_DOWN, self.move_start)
        self.win.Bind(wx.EVT_MOTION, self.move_motion)
        self.win.Bind(wx.EVT_KEY_UP, self.cancel)

        self.refresh()

    @property
    def width(self) -> int:
        """Return the current width of the window."""
        if self.is_compact:
            return self.sml_width
        else:
            return self.lrg_width

    @property
    def height(self) -> int:
        """Return the current height of the window."""
        if self.is_compact:
            return self.sml_height
        else:
            return self.lrg_height

    def on_paint(self, event: wx.PaintEvent) -> None:
        """Handle repainting when requested by the OS."""
        self.repaint(wx.PaintDC(self.win), complete=True)

    def refresh(self) -> None:
        """Update the UI to respond to changes.

        We only need to repaint the bars area.
        """
        dc = wx.ClientDC(self.win)
        self.repaint(dc, complete=False)

    def repaint(self, dc: wx.DC, complete: bool) -> None:
        """Render the entire window."""
        gc: wx.GraphicsContext = wx.GraphicsContext.Create(dc)

        if complete:
            if self.is_compact:
                self.on_paint_sml(gc)
            else:
                self.on_paint_lrg(gc)

        gc.DrawBitmap(
            self.expand_ico if self.is_compact else self.expand_ico,
            self.width - 40, 0,
            20, 20,
        )
        gc.DrawBitmap(
            self.quit_ico,
            self.width - 20, 0,
            20, 20,
        )

        self.repaint_bars()
        gc.DrawBitmap(
            self.bars_buff,
            20,
            self.height - 20 * len(self.stages) - 20,
            self.bars_buff.Width, self.bars_buff.Height,
        )

    def repaint_bars(self) -> None:
        """Render the bars area."""
        bar_width = self.width - 40
        bar_height = 20 * len(self.stages)

        if self.last_buff is not self.is_compact:
            try:
                self.bars_dc.SelectObject(wx.NullBitmap)
                self.bars_buff.Create(bar_width, bar_height)
            finally:
                self.bars_dc.SelectObjectAsSource(self.bars_buff)
            self.last_buff = self.is_compact

        gc: wx.GraphicsContext = wx.GraphicsContext.Create(self.bars_dc)

        bar_fg = wx.Brush((0, 120, 90))
        bar_bg = wx.Brush((0, 60, 45))
        bar_border = wx.Pen((0, 120, 90), width=2)

        gc.SetFont(self.progress_font, wx.WHITE)
        for ind, (st_id, stage_name) in enumerate(self.stages):
            st_val = self.values[st_id]
            st_max = self.maxes[st_id]
            bar_y = ind * 20

            if self.maxes[st_id] == 0:
                fraction = 1.0  # Skipped, show completed.
                text = f'{stage_name}: {TRANSLATION["skip"]}'
                tick_width = 0
            else:
                fraction = st_val / st_max
                text = f'{stage_name}: ({st_val}/{st_max})'
                tick_width = (bar_width - 2) / st_max
            # Border
            gc.SetBrush(bar_bg)
            gc.SetPen(bar_border)
            gc.DrawRectangle(0, bar_y, bar_width, 20)
            # The bar itself. If there's enough width, show discrete
            # segments. Otherwise, show a solid beam.
            gc.SetBrush(bar_fg)
            gc.SetPen(wx.TRANSPARENT_PEN)
            if tick_width > 4:
                for i in range(st_val):
                    gc.DrawRectangle(
                        2 + i * tick_width,
                        bar_y + 3,
                        tick_width - 2,
                        14,
                    )
            else:
                gc.DrawRectangle(2, bar_y + 3, fraction * (bar_width - 4), 14)
            text_height = gc.GetFullTextExtent(text)[1]
            gc.DrawText(text, 5, ind * 20 + (20 - text_height) / 2)

    def on_paint_sml(self, gc: wx.GraphicsContext) -> Tuple[int, int]:
        """Handle painting the compact splash screen."""

        # Fill with the green colour.
        gc.SetBrush(wx.Brush((0, 150, 120)))
        gc.DrawRectangle(0, 0, self.sml_width, self.sml_height)

        gc.SetFont(self.font, wx.WHITE)
        # Center both text.
        title_w, title_h, *_ = gc.GetFullTextExtent(self.title_text)
        vers_w, vers_h, *_ = gc.GetFullTextExtent(TRANSLATION['version'])

        gc.DrawText(
            self.title_text,
            (self.sml_width - title_w) / 2, 20,
        )
        gc.DrawText(
            TRANSLATION['version'],
            (self.sml_width - vers_w)/ 2, 40,
        )
        return self.sml_width, self.sml_height

    def on_paint_lrg(self, gc: wx.GraphicsContext) -> Tuple[int, int]:
        """Handle painting the full splash screen."""
        gc.DrawBitmap(self.splash_bg, 0, 0, self.lrg_width, self.lrg_height)
        gc.DrawBitmap(self.logo, 10, 10, self.logo.Width, self.logo.Height)

        gc.SetFont(self.font, wx.WHITE)
        # Center both text.
        title_w, title_h, *_ = gc.GetFullTextExtent(self.title_text)
        vers_w, vers_h, *_ = gc.GetFullTextExtent(TRANSLATION['version'])

        title_x, title_y = 10, 125
        vers_x, vers_y = 10, 145

        # Draw shadows behind the text.
        # This is done by progressively drawing smaller rectangles
        # with a low alpha. The center is overdrawn more making it thicker.
        gc.SetBrush(wx.Brush((0, 150, 120, 20)))
        for border in reversed(range(5)):
            gc.DrawRectangle(
                title_x - border,
                title_y - border,
                title_w + 2 * border,
                title_h + 2 * border,
            )
            gc.DrawRectangle(
                vers_x - border,
                vers_y - border,
                vers_w + 2 * border,
                vers_h + 2 * border,
            )

        gc.DrawText(self.title_text, title_x, title_y)
        gc.DrawText(TRANSLATION['version'], vers_x, vers_y)

        base_height = len(self.stages) * 20

        solid_height = base_height + 40

        # Add a gradient above the rectangle..
        gc.SetBrush(gc.CreateLinearGradientBrush(
            0, self.lrg_height - solid_height - 40,
            0, self.lrg_height - solid_height,
            wx.Colour(0, 150, 120, 0),
            wx.Colour(0, 150, 120, 128),
        ))
        gc.DrawRectangle(
            0, self.lrg_height - solid_height - 40,
            self.lrg_width, 40,
        )
        gc.SetBrush(wx.Brush((0, 150, 120, 128)))
        gc.DrawRectangle(
            0,
            self.lrg_height - solid_height,
            self.lrg_width,
            solid_height,
        )
        return self.lrg_width, self.lrg_height

    def update_stage(self, stage):
        """To update the stage, we just trigger a repaint."""
        self.refresh()

    def op_set_length(self, stage, num):
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.refresh()

    def reset_stages(self):
        self.maxes = dict.fromkeys(self.maxes, 10)
        self.values = dict.fromkeys(self.maxes, 0)
        self.refresh()

    def op_skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        self.values[stage] = 0
        self.maxes[stage] = 0
        self.refresh()

    # Operations:
    def op_set_is_compact(self, is_compact: bool) -> None:
        """Set the display mode."""
        self.is_compact = is_compact
        if is_compact:
            self.win.SetSize(
                wx.DefaultCoord, wx.DefaultCoord,
                self.sml_width, self.sml_height
            )
        else:
            self.win.SetSize(
                wx.DefaultCoord, wx.DefaultCoord,
                self.lrg_width, self.lrg_height
            )
        PIPE_SEND.send(('main_set_compact', is_compact))
        # Repaint the entire window.
        dc = wx.ClientDC(self.win)
        self.repaint(dc, complete=True)

    def toggle_compact(self, event: wx.MouseEvent) -> None:
        """Toggle when the splash screen is double-clicked."""
        self.op_set_is_compact(not self.is_compact)

        # Snap to the center of the window.
        self.win.Move(
            event.x - self.width // 2,
            event.y - self.height // 2,
        )

    def clicked(self, event: wx.MouseEvent) -> None:
        """When clicked, we have to detect clicks on the buttons."""
        event.Skip()
        x = event.x
        y = event.y
        width = self.width
        if y < 20:
            if self.width - 40 <= x < self.width - 20:
                self.op_set_is_compact(not self.is_compact)
                offset = width - self.width
                # Keep the button where it was.
                x, y = self.win.GetPosition().Get()
                self.win.Move(x + offset, y)

                return
            elif self.width - 20 <= x <= self.width:
                self.cancel()
                return

        self.move_start(event)

    # def compact_button(self, compact: bool, old_width, new_width):
    #     """Make the event function to set values."""
    #     self.compact_button(
    #         canvas is self.lrg_canvas,
    #         width,
    #         lrg_width if width == sml_width else sml_width,
    #     ),
    #     offset = old_width - new_width
    #
    #     def func(event=None):
    #         """Event handler."""
    #         self.op_set_is_compact(compact)
    #         # Snap to where the button is.
    #         self.win.wm_geometry('+{:g}+{:g}'.format(
    #             self.win.winfo_x() + offset,
    #             self.win.winfo_y(),
    #         ))
    #     return func


def run_screen(
    pipe_send: multiprocessing.connection.Connection,
    pipe_rec: multiprocessing.connection.Connection,
    # Pass in various bits of translated text
    # so we don't need to do it here.
    translations,
):
    """Runs in the other process, with an end of a pipe for input."""
    global PIPE_REC, PIPE_SEND

    PIPE_SEND = pipe_send
    PIPE_REC = pipe_rec
    TRANSLATION.update(translations)

    force_ontop = True
    app = wx.App()

    def check_queue(event: wx.IdleEvent) -> None:
        """Update stages from the parent process."""
        nonlocal force_ontop
        had_values = False
        while PIPE_REC.poll():  # Pop off all the values.
            had_values = True
            operation, scr_id, args = PIPE_REC.recv()
            # logger.info('<{}>.{}{!r}', scr_id, operation, args)
            if operation == 'init':
                # Create a new loadscreen.
                is_main, title, stages = args
                screen = (SplashScreen if is_main else LoadScreen)(scr_id, title, force_ontop, stages)
                SCREENS[scr_id] = screen
            elif operation == 'set_force_ontop':
                [force_ontop] = args
                style = WIN_STYLE
                if force_ontop:
                    style |= wx.STAY_ON_TOP
                for screen in SCREENS.values():
                    screen.win.SetWindowStyle(style)
            elif operation == 'exit':
                wx.Exit()
            else:
                try:
                    func = getattr(SCREENS[scr_id], 'op_' + operation)
                except AttributeError:
                    raise ValueError('Bad command "{}"!'.format(operation))
                try:
                    func(*args)
                except Exception:
                    raise Exception(operation)
        # Ensure another idle event will be fired.
        event.RequestMore()

    app.Bind(wx.EVT_IDLE, check_queue)
    wx.WakeUpIdle()
    check_queue(wx.IdleEvent())
    app.MainLoop()  # Infinite loop, until the entire process tree quits.
