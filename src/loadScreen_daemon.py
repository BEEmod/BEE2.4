"""Implements the splash screen in a subprocess.

During package loading, we are busy performing tasks in the main thread.
We do this in another process to sidestep the GIL, and ensure the screen
remains responsive. This is a separate module to reduce the required dependencies.
"""
from typing import Optional, Dict, Tuple, List, Iterator

from tkinter.font import Font
import tkinter as tk
from app import img
import wx
import multiprocessing.connection

import utils

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

SPLASH_FONTS = [
    'Univers',
    'Segoe UI',
    'San Francisco',
]

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

    def op_set_is_compact(self, compact: bool) -> None:
        pass


class SplashScreen(BaseLoadScreen):
    """The splash screen shown when booting up."""

    def __init__(self, *args):
        super().__init__(*args)

        self.is_compact = True

        all_fonts = set(tk.font.families())

        for font_family in all_fonts:
            # DIN is the font used by Portal 2's logo,
            # so try and use that.
            if 'DIN' in font_family:
                break
        else:  # Otherwise, use system UI fonts from a list.
            for font_family in SPLASH_FONTS:
                if font_family in all_fonts:
                    break
            else:
                font_family = 'Times'  # Generic special case

        font = Font(
            family=font_family,
            size=-18,  # negative = in pixels
            weight='bold',
        )

        progress_font = Font(
            family=font_family,
            size=-12,  # negative = in pixels
        )

        logo_img = img.png('BEE2/splash_logo')

        self.lrg_canvas = tk.Canvas(self.win)
        self.sml_canvas = tk.Canvas(
            self.win,
            background='#009678',  # 0, 150, 120
        )

        sml_width = int(min(self.win.winfo_screenwidth() * 0.5, 400))
        sml_height = int(min(self.win.winfo_screenheight() * 0.5, 175))

        self.lrg_canvas.create_image(
            10, 10,
            anchor='nw',
            image=logo_img,
        )

        self.sml_canvas.create_text(
            sml_width / 2, 30,
            anchor='n',
            text=self.title_text,
            fill='white',
            font=font,
        )
        self.sml_canvas.create_text(
            sml_width / 2, 50,
            anchor='n',
            text=TRANSLATION['version'],
            fill='white',
            font=font,
        )

        text1 = self.lrg_canvas.create_text(
            10, 125,
            anchor='nw',
            text=self.title_text,
            fill='white',
            font=font,
        )
        text2 = self.lrg_canvas.create_text(
            10, 145,
            anchor='nw',
            text=TRANSLATION['version'],
            fill='white',
            font=font,
        )

        # Now add shadows behind the text, and draw to the canvas.
        splash, lrg_width, lrg_height = img.make_splash_screen(
            max(self.win.winfo_screenwidth() * 0.6, 500),
            max(self.win.winfo_screenheight() * 0.6, 500),
            base_height=len(self.stages) * 20,
            text1_bbox=self.lrg_canvas.bbox(text1),
            text2_bbox=self.lrg_canvas.bbox(text2),
        )
        self.splash_img = splash  # Keep this alive
        self.lrg_canvas.tag_lower(self.lrg_canvas.create_image(
            0, 0,
            anchor='nw',
            image=splash,
        ))

        self.canvas = [
            (self.lrg_canvas, lrg_width, lrg_height),
            (self.sml_canvas, sml_width, sml_height),
        ]

        for canvas, width, height in self.canvas:
            canvas.create_rectangle(
                width - 40,
                0,
                width - 20,
                20,
                fill='#00785A',
                width=0,
                tags='resize_button',
            )
            # 150, 120, 64
            # Diagonal part of arrow.
            canvas.create_line(
                width - 20 - 4, 4,
                width - 20 - 16, 16,
                fill='black',
                width=2,
                tags='resize_button',
            )
            canvas.tag_bind(
                'resize_button',
                '<Button-1>',
                self.compact_button(
                    canvas is self.lrg_canvas,
                    width,
                    lrg_width if width == sml_width else sml_width,
                ),
            )
        self.sml_canvas.create_line(
            sml_width - 20 - 4, 4,
            sml_width - 20 - 16, 4,
            fill='black',
            width=2,
            tags='resize_button',
        )
        self.sml_canvas.create_line(
            sml_width - 20 - 4, 4,
            sml_width - 20 - 4, 16,
            fill='black',
            width=2,
            tags='resize_button',
        )
        self.lrg_canvas.create_line(
            lrg_width - 20 - 16, 16,
            lrg_width - 20 - 4, 16,
            fill='black',
            width=2,
            tags='resize_button',
        )
        self.lrg_canvas.create_line(
            lrg_width - 20 - 16, 16,
            lrg_width - 20 - 16, 4,
            fill='black',
            width=2,
            tags='resize_button',
        )

        for canvas, width, height in self.canvas:
            canvas['width'] = width
            canvas['height'] = height
            canvas.bind(utils.EVENTS['LEFT_DOUBLE'], self.toggle_compact)

            canvas.create_rectangle(
                width-20,
                0,
                width,
                20,
                fill='#00785A',
                width=0,
                tags='quit_button',
            )
            canvas.create_rectangle(
                width-20,
                0,
                width,
                20,
                fill='#00785A',
                width=0,
                tags='quit_button',
            )
            # 150, 120, 64
            canvas.create_line(
                width-16, 4,
                width-4, 16,
                fill='black',
                width=2,
                tags='quit_button',
            )
            canvas.create_line(
                width-4, 4,
                width-16, 16,
                fill='black',
                width=2,
                tags='quit_button',
            )
            canvas.tag_bind('quit_button', '<Button-1>', self.cancel)

            for ind, (st_id, stage_name) in enumerate(reversed(self.stages), start=1):
                canvas.create_rectangle(
                    20,
                    height - (ind + 0.5) * 20,
                    20,
                    height - (ind - 0.5) * 20,
                    fill='#00785A',  # 0, 120, 90
                    width=0,
                    tags='bar_' + st_id,
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
                canvas.create_text(
                    25,
                    height - ind * 20,
                    anchor='w',
                    text=stage_name + ': (0/???)',
                    fill='white',
                    tags='text_' + st_id,
                    font=progress_font,
                )

    def update_stage(self, stage):
        text = '{}: ({}/{})'.format(
            self.names[stage],
            self.values[stage],
            self.maxes[stage],
        )
        self.sml_canvas.itemconfig('text_' + stage, text=text)
        self.lrg_canvas.itemconfig('text_' + stage, text=text)
        self.set_bar(stage, self.values[stage] / self.maxes[stage])

    def set_bar(self, stage, fraction):
        """Set a progress bar to this fractional length."""
        for canvas, width, height in self.canvas:
            x1, y1, x2, y2 = canvas.coords('bar_' + stage)
            canvas.coords(
                'bar_' + stage,
                20,
                y1,
                20 + round(fraction * (width - 40)),
                y2,
            )

    def op_set_length(self, stage, num):
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.update_stage(stage)

        for canvas, width, height in self.canvas:

            canvas.delete('tick_' + stage)

            if num == 0:
                return  # No ticks

            # Draw the ticks in...
            _, y1, _, y2 = canvas.coords('bar_' + stage)

            dist = (width - 40) / num
            if round(dist) <= 1:
                # Don't have ticks if they're right next to each other
                return
            tag = 'tick_' + stage
            for i in range(num):
                pos = int(20 + dist * i)
                canvas.create_line(
                    pos, y1, pos, y2,
                    fill='#00785A',
                    tags=tag,
                )
            canvas.tag_lower('tick_' + stage, 'bar_' + stage)

    def reset_stages(self):
        pass

    def op_skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        self.values[stage] = 0
        self.maxes[stage] = 0
        for canvas, width, height in self.canvas:
            canvas.itemconfig(
                'text_' + stage,
                text=self.names[stage] + ': ' + TRANSLATION['skip'],
            )
        self.set_bar(stage, 1.0)  # Force stage to be max filled.

    # Operations:
    def op_set_is_compact(self, is_compact: bool) -> None:
        """Set the display mode."""
        self.is_compact = is_compact
        if is_compact:
            self.lrg_canvas.grid_remove()
            self.sml_canvas.grid(row=0, column=0)
        else:
            self.sml_canvas.grid_remove()
            self.lrg_canvas.grid(row=0, column=0)
        PIPE_SEND.send(('main_set_compact', is_compact))

    def toggle_compact(self, event: tk.Event) -> None:
        """Toggle when the splash screen is double-clicked."""
        self.op_set_is_compact(not self.is_compact)

        # Snap to the center of the window.
        canvas = self.sml_canvas if self.is_compact else self.lrg_canvas
        self.win.wm_geometry('+{:g}+{:g}'.format(
            event.x_root - int(canvas['width']) // 2,
            event.y_root - int(canvas['height']) // 2,
        ))

    def compact_button(self, compact: bool, old_width, new_width):
        """Make the event function to set values."""
        offset = old_width - new_width

        def func(event=None):
            """Event handler."""
            self.op_set_is_compact(compact)
            # Snap to where the button is.
            self.win.wm_geometry('+{:g}+{:g}'.format(
                self.win.winfo_x() + offset,
                self.win.winfo_y(),
            ))
        return func


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
                is_main = False  # TODO
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
