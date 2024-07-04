"""Implements load screens and the log window in a subprocess.

These need to be used while we are busy doing stuff in the main UI loop.
We do this in another process to sidestep the GIL, and ensure the screen
remains responsive. This is a separate module to reduce the required dependencies.
"""
from __future__ import annotations
from typing_extensions import assert_never, override

from collections.abc import Callable
from tkinter import ttk
from tkinter.font import Font, families as tk_font_families
import tkinter as tk
import logging
import multiprocessing.connection
import queue
import time

from PIL import ImageTk

from ui_tk import TK_ROOT, tk_tools
from app import img
from ipc_types import (
    ScreenID, StageID,
    ARGS_SEND_LOAD, ARGS_REPLY_LOAD, ARGS_SEND_LOGGING,  ARGS_REPLY_LOGGING,
)
import ipc_types
import utils


SCREENS: dict[ScreenID, LoadScreen | SplashScreen] = {}
QUEUE_REPLY_LOAD: multiprocessing.Queue[ARGS_REPLY_LOAD]
TIMEOUT = 0.125  # New iteration if we take more than this long.

# Stores translated strings, which are done in the main process.
TRANSLATION = {
    'skip': 'Skipped',
    'version': 'Version: 2.4.389',
    'cancel': 'Cancel',
    'log_title': 'Logs',
    'log_show': 'Show:',
    'level_debug': 'Debug',
    'level_info': 'Info',
    'level_warn': 'Warnings only',
}

SPLASH_FONTS = [
    'Univers',
    'Segoe UI',
    'San Francisco',
]

# Colours to use for each log level
LVL_COLOURS = {
    logging.CRITICAL: 'white',
    logging.ERROR: 'red',
    logging.WARNING: '#FF7D00',  # 255, 125, 0
    logging.INFO: '#0050FF',
    logging.DEBUG: 'grey',
}

BOX_LEVELS = [
    'DEBUG',
    'INFO',
    'WARNING',
]
START = '1.0'  # Row 1, column 0 = first character


class BaseLoadScreen:
    """Code common to both loading screen types."""
    drag_x: int | None
    drag_y: int | None

    def __init__(
        self,
        scr_id: ScreenID,
        title_text: str,
        force_ontop: bool,
        stages: list[tuple[StageID, str]],
    ) -> None:
        self.scr_id = scr_id
        self.title_text = title_text

        self.win = tk.Toplevel(TK_ROOT, name=f'loadscreen_{scr_id}')
        self.win.withdraw()
        self.win.wm_overrideredirect(True)
        self.win.wm_attributes('-topmost', int(force_ontop))
        if utils.LINUX:
            self.win.wm_attributes('-type', 'splash')
        self.win['cursor'] = tk_tools.Cursors.WAIT
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(0, weight=1)

        self.values: dict[StageID, int] = {}
        self.maxes: dict[StageID, int] = {}
        self.names: dict[StageID, str] = {}
        self.stages = stages
        self.is_shown = False

        for st_id, stage_name in stages:
            self.values[st_id] = 0
            self.maxes[st_id] = 10
            self.names[st_id] = stage_name

        # Because of wm_overrideredirect, we have to manually do dragging.
        self.drag_x = self.drag_y = None

        self.win.bind('<Button-1>', self.move_start)
        self.win.bind('<ButtonRelease-1>', self.move_stop)
        self.win.bind('<B1-Motion>', self.move_motion)
        self.win.bind('<Escape>', self.cancel)

    def cancel(self, event: object = None) -> None:
        """User pressed the cancel button."""
        self.op_reset()
        QUEUE_REPLY_LOAD.put(ipc_types.Daemon2Load_Cancel(self.scr_id))

    def move_start(self, event: tk.Event) -> None:
        """Record offset of mouse on click."""
        self.drag_x = event.x
        self.drag_y = event.y
        self.win['cursor'] = tk_tools.Cursors.MOVE_ITEM

    def move_stop(self, event: tk.Event) -> None:
        """Clear values when releasing."""
        self.win['cursor'] = tk_tools.Cursors.WAIT
        self.drag_x = self.drag_y = None

    def move_motion(self, event: tk.Event) -> None:
        """Move the window when moving the mouse."""
        if self.drag_x is None or self.drag_y is None:
            return
        x = self.win.winfo_x() + event.x - self.drag_x
        y = self.win.winfo_y() + event.y - self.drag_y
        self.win.geometry(f'+{x:g}+{y:g}')

    def op_show(self, title: str, labels: list[str]) -> None:
        """Show the window."""
        self.win.title(title)
        for (st_id, _), name in zip(self.stages, labels, strict=True):
            self.names[st_id] = name

        self.is_shown = True
        self.win.deiconify()
        self.win.lift()
        self.win.update()  # Force an update so the reqwidth is correct
        x = self.win.winfo_screenwidth() - self.win.winfo_reqwidth()
        y = self.win.winfo_screenheight() - self.win.winfo_reqheight()
        self.win.geometry(f'+{x // 2:g}+{y // 2:g}')

    def op_hide(self) -> None:
        """Hide the window."""
        self.is_shown = False
        self.win.withdraw()

    def op_reset(self) -> None:
        """Hide and reset values in all bars."""
        self.op_hide()
        for stage in self.values.keys():
            self.maxes[stage] = 10
            self.values[stage] = 0
        self.reset_stages()

    def op_step(self, stage: StageID) -> None:
        """Increment the specified value."""
        self.values[stage] += 1
        self.update_stage(stage)

    def op_set_length(self, stage: StageID, num: int) -> None:
        """Set the number of items in a stage."""
        if num == 0:
            self.op_skip_stage(stage)
        else:
            self.maxes[stage] = num
            self.update_stage(stage)

    def op_skip_stage(self, stage: StageID) -> None:
        """Skip over this stage of the loading process."""
        raise NotImplementedError

    def update_stage(self, stage: StageID) -> None:
        """Update the UI for the given stage."""
        raise NotImplementedError

    def reset_stages(self) -> None:
        """Return the UI to the initial state with unknown max."""
        raise NotImplementedError

    def op_destroy(self) -> None:
        """Remove this screen."""
        self.win.withdraw()
        self.win.destroy()
        del SCREENS[self.scr_id]


class LoadScreen(BaseLoadScreen):
    """Normal loading screens."""

    def __init__(
        self,
        scr_id: ScreenID,
        title_text: str,
        force_ontop: bool,
        stages: list[tuple[StageID, str]],
    ) -> None:
        super().__init__(scr_id, title_text, force_ontop, stages)

        self.frame = ttk.Frame(self.win, cursor=tk_tools.Cursors.WAIT)
        self.frame.grid(row=0, column=0)

        self.title_lbl = ttk.Label(
            self.frame,
            text=self.title_text + '...',
            font=("Helvetica", 12, "bold"),
            cursor=tk_tools.Cursors.WAIT,
        )
        self.title_lbl.grid(row=0, column=0)
        ttk.Separator(
            self.frame,
            orient=tk.HORIZONTAL,
            cursor=tk_tools.Cursors.WAIT,
        ).grid(row=1, sticky="EW", columnspan=2)

        self.cancel_btn = ttk.Button(self.frame, command=self.cancel)
        self.cancel_btn.grid(row=0, column=1)

        self.bar_var: dict[StageID, tk.IntVar] = {}
        self.bars: dict[StageID, ttk.Progressbar] = {}
        self.titles: dict[StageID, ttk.Label] = {}
        self.labels: dict[StageID, ttk.Label] = {}

        for ind, (st_id, stage_name) in enumerate(self.stages):
            if stage_name:
                # If stage name is blank, don't add a caption
                self.titles[st_id] = ttk.Label(
                    self.frame,
                    text=stage_name + ':',
                    cursor=tk_tools.Cursors.WAIT,
                )
                self.titles[st_id].grid(
                    row=ind * 2 + 2,
                    columnspan=2,
                    sticky="W",
                )
            self.bar_var[st_id] = tk.IntVar()

            self.bars[st_id] = ttk.Progressbar(
                self.frame,
                length=210,
                maximum=1000,
                variable=self.bar_var[st_id],
                cursor=tk_tools.Cursors.WAIT,
            )
            self.labels[st_id] = ttk.Label(
                self.frame,
                text='0/??',
                cursor=tk_tools.Cursors.WAIT,
            )
            self.bars[st_id].grid(row=ind * 2 + 3, column=0, columnspan=2)
            self.labels[st_id].grid(row=ind * 2 + 2, column=1, sticky="E")

    def update_translations(self) -> None:
        """Update translations."""
        self.cancel_btn['text'] = TRANSLATION['cancel']

    @override
    def reset_stages(self) -> None:
        """Put the stage in the initial state, before maxes are provided."""
        for stage in self.values.keys():
            self.bar_var[stage].set(0)
            self.labels[stage]['text'] = '0/??'

    @override
    def update_stage(self, stage: StageID) -> None:
        """Redraw the given stage."""
        max_val = self.maxes[stage]
        if max_val == 0:  # 0/0 sections are skipped automatically.
            self.bar_var[stage].set(1000)
        else:
            self.bar_var[stage].set(round(
                1000 * self.values[stage] / max_val
            ))
        self.labels[stage]['text'] = f'{self.values[stage]!s}/{max_val!s}'

    @override
    def op_show(self, title: str, labels: list[str]) -> None:
        """Show the window."""
        self.title_text = title
        self.win.title(title)
        self.title_lbl['text'] = title + '...',
        for (st_id, _), name in zip(self.stages, labels, strict=True):
            if st_id in self.titles:
                self.titles[st_id]['text'] = name + ':'
        super().op_show(title, labels)

    @override
    def op_skip_stage(self, stage: StageID) -> None:
        """Skip over this stage of the loading process."""
        self.values[stage] = 0
        self.maxes[stage] = 0
        self.labels[stage]['text'] = TRANSLATION['skip']
        self.bar_var[stage].set(1000)  # Make sure it fills to max


class SplashScreen(BaseLoadScreen):
    """The splash screen shown when booting up.

    Since this is only shown once before you can access the settings window, we don't need to worry
    about reloading translations.
    """

    def __init__(
        self,
        scr_id: ScreenID,
        title_text: str,
        force_ontop: bool,
        stages: list[tuple[StageID, str]],
    ) -> None:
        super().__init__(scr_id, title_text, force_ontop, stages)

        self.is_compact = True

        all_fonts = set(tk_font_families())

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

        self.lrg_canvas = tk.Canvas(self.win)
        self.sml_canvas = tk.Canvas(
            self.win,
            background='#009678',  # 0, 150, 120
        )

        sml_width = int(min(self.win.winfo_screenwidth() * 0.5, 400))
        sml_height = int(min(self.win.winfo_screenheight() * 0.5, 175))

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
        splash_img = img.make_splash_screen(
            max(self.win.winfo_screenwidth() * 0.6, 500),
            max(self.win.winfo_screenheight() * 0.6, 500),
            base_height=len(self.stages) * 20,
            text1_bbox=self.lrg_canvas.bbox(text1),
            text2_bbox=self.lrg_canvas.bbox(text2),
        )
        lrg_width, lrg_height = splash_img.size
        self.splash_img = ImageTk.PhotoImage(image=splash_img)  # Keep this alive
        self.lrg_canvas.tag_lower(self.lrg_canvas.create_image(
            0, 0,
            anchor='nw',
            image=self.splash_img,
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
            canvas.bind(tk_tools.EVENTS['LEFT_DOUBLE'], self.toggle_compact)

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

    @override
    def update_stage(self, stage: StageID) -> None:
        """Update all the text."""
        if self.maxes[stage] == 0:
            text = f'{self.names[stage]}: (0/0)'
            self.set_bar(stage, 1)
        else:
            text = (
                f'{self.names[stage]}: '
                f'({self.values[stage]}/{self.maxes[stage]})'
            )
            self.set_bar(stage, self.values[stage] / self.maxes[stage])

        self.sml_canvas.itemconfig('text_' + stage, text=text)
        self.lrg_canvas.itemconfig('text_' + stage, text=text)

    def set_bar(self, stage: str, fraction: float) -> None:
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

    @override
    def op_set_length(self, stage: StageID, num: int) -> None:
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.update_stage(stage)

        for canvas, width, height in self.canvas:

            canvas.delete('tick_' + stage)

            if num == 0:
                continue  # No ticks

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

    @override
    def reset_stages(self) -> None:
        """Reset all stages."""
        pass

    @override
    def op_skip_stage(self, stage: StageID) -> None:
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
        QUEUE_REPLY_LOAD.put(ipc_types.Daemon2Load_MainSetCompact(is_compact))

    def toggle_compact(self, event: tk.Event) -> None:
        """Toggle when the splash screen is double-clicked."""
        self.op_set_is_compact(not self.is_compact)

        # Snap to the center of the window.
        canvas = self.sml_canvas if self.is_compact else self.lrg_canvas
        self.win.wm_geometry('+{:g}+{:g}'.format(
            event.x_root - int(canvas['width']) // 2,
            event.y_root - int(canvas['height']) // 2,
        ))

    def compact_button(self, compact: bool, old_width: int, new_width: int) -> Callable[[tk.Event], None]:
        """Make the event function to set values."""
        offset = old_width - new_width

        def func(_: tk.Event) -> None:
            """Event handler."""
            self.op_set_is_compact(compact)
            # Snap to where the button is.
            self.win.wm_geometry(f'+{self.win.winfo_x() + offset:g}+{self.win.winfo_y():g}')
        return func


class LogWindow:
    """Implements the logging window."""
    def __init__(self, queue: multiprocessing.Queue[ARGS_REPLY_LOGGING]) -> None:
        """Initialise the window."""
        self.win = window = tk.Toplevel(TK_ROOT, name='logWin')
        self.queue = queue
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        window.protocol('WM_DELETE_WINDOW', self.evt_close)
        window.withdraw()

        self.has_text = False
        self.text = tk.Text(
            window,
            name='text_box',
            width=50,
            height=15,
        )
        self.text.grid(row=0, column=0, sticky='NSEW')

        scroll = tk_tools.HidingScroll(
            window,
            name='scroll',
            orient=tk.VERTICAL,
            command=self.text.yview,
        )
        scroll.grid(row=0, column=1, sticky='NS')
        self.text['yscrollcommand'] = scroll.set

        # Assign colours for each logging level
        for level, colour in LVL_COLOURS.items():
            self.text.tag_config(
                logging.getLevelName(level),
                foreground=colour,
                # For multi-line messages, indent this much.
                lmargin2=30,
            )
        self.text.tag_config(
            logging.getLevelName(logging.CRITICAL),
            background='red',
        )
        # If multi-line messages contain carriage returns, lmargin2 doesn't
        # work. Add a tag for that.
        self.text.tag_config(
            'INDENT',
            lmargin1=30,
            lmargin2=30,
        )

        button_frame = ttk.Frame(window, name='button_frame')
        button_frame.grid(row=1, column=0, columnspan=2, sticky='EW')

        self.clear_btn = ttk.Button(
            button_frame,
            name='clear_btn',
            command=self.evt_clear,
        )
        self.clear_btn.grid(row=0, column=0)

        self.copy_btn = ttk.Button(
            button_frame,
            name='copy_btn',
            command=self.evt_copy,
        )
        self.copy_btn.grid(row=0, column=1)

        sel_frame = ttk.Frame(button_frame)
        sel_frame.grid(row=0, column=2, sticky='EW')
        button_frame.columnconfigure(2, weight=1)

        self.log_show = ttk.Label(
            sel_frame,
            anchor='e',
            justify='right',
        )
        self.log_show.grid(row=0, column=0, sticky='E')

        self.level_selector = ttk.Combobox(
            sel_frame,
            name='level_selector',
            values=BOX_LEVELS,
            exportselection=False,
        )
        # On Mac this defaults to being way too wide!
        if utils.MAC:
            self.level_selector['width'] = 15
        self.level_selector.state(['readonly'])  # Prevent directly typing in values
        self.level_selector.bind('<<ComboboxSelected>>', self.evt_set_level)
        self.level_selector.current(1)

        self.level_selector.grid(row=0, column=1, sticky='E')
        sel_frame.columnconfigure(1, weight=1)

        tk_tools.add_mousewheel(self.text, window, sel_frame, button_frame)

        if tk_tools.USE_SIZEGRIP:
            ttk.Sizegrip(button_frame).grid(row=0, column=3)
        self.update_translations()

    def update_translations(self) -> None:
        """Apply translations."""
        self.win.title(TRANSLATION['log_title'])
        self.clear_btn['text'] = TRANSLATION['clear']
        self.copy_btn['text'] = TRANSLATION['copy']
        self.log_show['text'] = TRANSLATION['log_show']
        old_current = self.level_selector.current()
        self.level_selector['values'] = [
            TRANSLATION['level_debug'],
            TRANSLATION['level_info'],
            TRANSLATION['level_warn'],
        ]
        self.level_selector.current(old_current)

    def log(self, level_name: str, text: str) -> None:
        """Write a log message to the window."""
        self.text['state'] = "normal"
        # We don't want to indent the first line.
        firstline, *lines = text.split('\n')

        if self.has_text:
            # Add a newline to the existing text, since we don't end with it.
            self.text.insert(tk.END, '\n', ())

        self.text.insert(tk.END, firstline, (level_name,))
        for line in lines:
            self.text.insert(
                tk.END,
                '\n',
                ('INDENT',),
                line,
                # Indent lines after the first.
                (level_name, 'INDENT'),
            )
        self.text.see(tk.END)  # Scroll to the end
        self.text['state'] = "disabled"
        self.has_text = True

    def evt_set_level(self, event: tk.Event) -> None:
        """Set the level of the log window."""
        level = BOX_LEVELS[self.level_selector.current()]
        self.queue.put(('level', level))

    def evt_close(self) -> None:
        """Called when the window close button is pressed."""
        try:
            self.queue.put(('visible', False))
        except ValueError:  # Lost connection, completely quit.
            TK_ROOT.quit()
        else:
            self.win.withdraw()

    def evt_copy(self) -> None:
        """Copy the selected text, or the whole console."""
        try:
            text = self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:  # No selection
            text = self.text.get(START, tk.END)
        self.text.clipboard_clear()
        self.text.clipboard_append(text)

    def evt_clear(self) -> None:
        """Clear the console."""
        self.text['state'] = "normal"
        self.text.delete(START, tk.END)
        self.has_text = False
        self.text['state'] = "disabled"

    def handle(self, msg: ARGS_SEND_LOGGING) -> None:
        """Handle messages from the main app."""
        match msg:
            case ['log', str() as level, str() as message]:
                self.log(level, message)
            case ['visible', bool() as visible]:
                if visible:
                    self.win.deiconify()
                else:
                    self.win.withdraw()
            case ['level', str() as level]:
                self.level_selector.current(BOX_LEVELS.index(level))
            case _:
                raise ValueError(f'Bad command: {msg!r}!')


def run_background(
    queue_rec_load: multiprocessing.Queue[ARGS_SEND_LOAD],
    queue_reply_load: multiprocessing.Queue[ARGS_REPLY_LOAD],
    queue_rec_log: multiprocessing.Queue[ARGS_SEND_LOGGING],
    queue_reply_log: multiprocessing.Queue[ARGS_REPLY_LOGGING],
    # Pass in various bits of translated text so, we don't need to do it here.
    translations: dict[str, str],
) -> None:
    """Runs in the other process, with an end of a pipe for input."""
    global QUEUE_REPLY_LOAD
    QUEUE_REPLY_LOAD = queue_reply_load
    TRANSLATION.update(translations)

    force_ontop = True

    log_window = LogWindow(queue_reply_log)

    def check_queue() -> None:
        """Update stages from the parent process."""
        nonlocal force_ontop
        had_values = False
        cur_time = time.monotonic()
        try:
            while True:  # Pop off all the values.
                try:
                    op = queue_rec_load.get_nowait()
                except queue.Empty:
                    break
                except ValueError as exc:
                    raise BrokenPipeError from exc
                had_values = True
                if time.monotonic() - cur_time > TIMEOUT:
                    # ensure we do run the logs too if we timeout, but if we don't share the same timeout.
                    cur_time = time.monotonic()
                    break
                if isinstance(op, ipc_types.Load2Daemon_Init):
                    # Create a new loadscreen.
                    screen = (SplashScreen if op.is_splash else LoadScreen)(op.scr_id, op.title, force_ontop, op.stages)
                    SCREENS[op.scr_id] = screen
                elif isinstance(op, ipc_types.Load2Daemon_UpdateTranslations):
                    TRANSLATION.update(op.translations)
                    log_window.update_translations()
                    for screen in SCREENS.values():
                        if isinstance(screen, LoadScreen):
                            screen.update_translations()
                elif isinstance(op, ipc_types.Load2Daemon_SetForceOnTop):
                    for screen in SCREENS.values():
                        screen.win.attributes('-topmost', op.on_top)
                elif isinstance(op, ipc_types.ScreenOp):
                    try:
                        screen = SCREENS[op.screen]
                    except KeyError:
                        continue

                    if isinstance(op, ipc_types.Load2Daemon_Show):
                        screen.op_show(op.title, op.stage_names)
                    elif isinstance(op, ipc_types.Load2Daemon_Hide):
                        screen.op_hide()
                    elif isinstance(op, ipc_types.Load2Daemon_Reset):
                        screen.op_reset()
                    elif isinstance(op, ipc_types.Load2Daemon_Destroy):
                        screen.op_destroy()
                    elif isinstance(op, ipc_types.Load2Daemon_SetLength):
                        screen.op_set_length(op.stage, op.size)
                    elif isinstance(op, ipc_types.Load2Daemon_Step):
                        screen.op_step(op.stage)
                    elif isinstance(op, ipc_types.Load2Daemon_Skip):
                        screen.op_skip_stage(op.stage)
                    elif isinstance(op, ipc_types.Load2Daemon_SetIsCompact):
                        if isinstance(screen, SplashScreen):
                            screen.op_set_is_compact(op.compact)
                        else:
                            print('Called set_is_compact() on regular loadscreen?')
                    else:
                        assert_never(op)
                else:
                    assert_never(op)
            while True:  # Pop off all the values.
                try:
                    rec_args = queue_rec_log.get_nowait()
                except queue.Empty:
                    break
                except ValueError as exc:
                    raise BrokenPipeError from exc
                if time.monotonic() - cur_time > TIMEOUT:
                    break

                had_values = True
                log_window.handle(rec_args)

        except BrokenPipeError:
            # A pipe failed, means the main app quit. Terminate ourselves.
            print('BG: Lost pipe!')
            TK_ROOT.quit()
            return

        # Continually re-run this function in the TK loop.
        # If we didn't find anything in the queues, wait longer.
        # Otherwise, we hog the CPU.
        TK_ROOT.after(1 if had_values else 200, check_queue)

    TK_ROOT.after(10, check_queue)
    TK_ROOT.mainloop()  # Infinite loop, until the entire process tree quits.
