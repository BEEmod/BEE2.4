"""Implements the splash screen in a subprocess.

During package loading, we are busy performing tasks in the main thread.
We do this in another process to sidestep the GIL, and ensure the screen
remains responsive. This is a separate module to reduce the required dependencies.
"""
from typing import Optional

from tkinter import ttk
from tkinter.font import Font
import tkinter as tk
import multiprocessing

import utils

# ID -> screen.
SCREENS = {}

PIPE_REC = ...  # type: multiprocessing.Connection
PIPE_SEND = ...  # type: multiprocessing.Connection

# Stores translated strings, which are done in the main process.
TRANSLATION = {
    'skip': 'Skipped',
    'version': 'Version: 2.4.389',
    'cancel': 'Cancel',
}


class BaseLoadScreen:
    """Code common to both loading screen types."""
    def __init__(self, master, scr_id, title_text, force_ontop, stages):
        self.scr_id = scr_id
        self.title_text = title_text

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.wm_overrideredirect(True)
        self.win.attributes('-topmost', int(force_ontop))
        self.win['cursor'] = utils.CURSORS['wait']
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(0, weight=1)

        self.values = {}
        self.maxes = {}
        self.names = {}
        self.stages = stages
        self.is_shown = False

        for st_id, stage_name in stages:
            self.values[st_id] = 0
            self.maxes[st_id] = 10
            self.names[st_id] = stage_name

        # Because of wm_overrideredirect, we have to manually do dragging.
        self.drag_x = self.drag_y = None  # type: Optional[int]

        self.win.bind('<Button-1>', self.move_start)
        self.win.bind('<ButtonRelease-1>', self.move_stop)
        self.win.bind('<B1-Motion>', self.move_motion)
        self.win.bind('<Escape>', self.cancel)

    def cancel(self, event: tk.Event=None):
        """User pressed the cancel button."""
        self.op_reset()
        PIPE_SEND.send(('cancel', self.scr_id))

    def move_start(self, event: tk.Event):
        """Record offset of mouse on click."""
        self.drag_x = event.x
        self.drag_y = event.y
        self.win['cursor'] = utils.CURSORS['move_item']

    def move_stop(self, event: tk.Event):
        """Clear values when releasing."""
        self.win['cursor'] = utils.CURSORS['wait']
        self.drag_x = self.drag_y = None

    def move_motion(self, event: tk.Event):
        """Move the window when moving the mouse."""
        if self.drag_x is None or self.drag_y is None:
            return
        self.win.geometry('+{x:g}+{y:g}'.format(
            x=self.win.winfo_x() + (event.x - self.drag_x),
            y=self.win.winfo_y() + (event.y - self.drag_y),
        ))

    def op_show(self):
        """Show the window."""
        self.is_shown = True
        self.win.deiconify()
        self.win.lift()
        self.win.update()  # Force an update so the reqwidth is correct
        self.win.geometry('+{x:g}+{y:g}'.format(
            x=(self.win.winfo_screenwidth() - self.win.winfo_reqwidth()) // 2,
            y=(self.win.winfo_screenheight() - self.win.winfo_reqheight()) // 2,
        ))

    def op_hide(self):
        self.is_shown = False
        self.win.withdraw()

    def op_reset(self):
        """Hide and reset values in all bars."""
        self.op_hide()
        for stage in self.values.keys():
            self.maxes[stage] = 10
            self.values[stage] = 0
        self.reset_stages()

    def op_step(self, stage):
        """Increment the specified value."""
        self.values[stage] += 1
        self.update_stage(stage)

    def op_set_length(self, stage, num):
        """Set the number of items in a stage."""
        self.maxes[stage] = num
        self.update_stage(stage)

    def op_skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        raise NotImplementedError

    def update_stage(self, stage):
        """Update the UI for the given stage."""
        raise NotImplementedError

    def reset_stages(self):
        """Return the UI to the initial state with unknown max."""
        raise NotImplementedError

    def op_destroy(self):
        """Remove this screen."""
        self.win.withdraw()
        self.win.destroy()
        del SCREENS[self.scr_id]


class LoadScreen(BaseLoadScreen):
    """Normal loading screens."""

    def __init__(self, *args):
        super().__init__(*args)

        self.frame = ttk.Frame(self.win, cursor=utils.CURSORS['wait'])
        self.frame.grid(row=0, column=0)

        ttk.Label(
            self.frame,
            text=self.title_text + '...',
            font=("Helvetica", 12, "bold"),
            cursor=utils.CURSORS['wait'],
        ).grid(row=0, column=0)
        ttk.Separator(
            self.frame,
            orient=tk.HORIZONTAL,
            cursor=utils.CURSORS['wait'],
        ).grid(row=1, sticky="EW", columnspan=2)

        ttk.Button(
            self.frame,
            text=TRANSLATION['cancel'],
            command=self.cancel,
        ).grid(row=0, column=1)

        self.bar_var = {}
        self.bars = {}
        self.labels = {}

        for ind, (st_id, stage_name) in enumerate(self.stages):
            if stage_name:
                # If stage name is blank, don't add a caption
                ttk.Label(
                    self.frame,
                    text=stage_name + ':',
                    cursor=utils.CURSORS['wait'],
                ).grid(
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
                cursor=utils.CURSORS['wait'],
            )
            self.labels[st_id] = ttk.Label(
                self.frame,
                text='0/??',
                cursor=utils.CURSORS['wait'],
            )
            self.bars[st_id].grid(row=ind * 2 + 3, column=0, columnspan=2)
            self.labels[st_id].grid(row=ind * 2 + 2, column=1, sticky="E")

    def reset_stages(self):
        """Put the stage in the initial state, before maxes are provided."""
        for stage in self.values.keys():
            self.bar_var[stage].set(0)
            self.labels[stage]['text'] = '0/??'

    def update_stage(self, stage):
        """Redraw the given stage."""
        max_val = self.maxes[stage]
        if max_val == 0:  # 0/0 sections are skipped automatically.
            self.bar_var[stage].set(1000)
        else:
            self.bar_var[stage].set(
                1000 * self.values[stage] / max_val
            )
        self.labels[stage]['text'] = '{!s}/{!s}'.format(
            self.values[stage],
            max_val,
        )

    def op_skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        self.values[stage] = 0
        self.maxes[stage] = 0
        self.labels[stage]['text'] = TRANSLATION['skip']
        self.bar_var[stage].set(1000)  # Make sure it fills to max


class SplashScreen(BaseLoadScreen):
    """The splash screen shown when booting up."""

    def __init__(self, *args):
        super().__init__(*args)

        self.is_compact = True

        font = Font(
            family='Times',  # Generic special case
            size=-18,  # negative = in pixels
            weight='bold',
        )

        # Must be done late, so we know TK is initialised.
        import img

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
            sml_width / 2, 40,
            anchor='n',
            text=self.title_text,
            fill='white',
            font=font,
        )
        self.sml_canvas.create_text(
            sml_width / 2, 60,
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
    def op_set_is_compact(self, is_compact):
        """Set the display mode."""
        self.is_compact = is_compact
        if is_compact:
            self.lrg_canvas.grid_remove()
            self.sml_canvas.grid(row=0, column=0)
        else:
            self.sml_canvas.grid_remove()
            self.lrg_canvas.grid(row=0, column=0)
        PIPE_SEND.send(('main_set_compact', is_compact))

    def toggle_compact(self, event: tk.Event):
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
    pipe_send,
    pipe_rec,
    # Pass in various bits of translated text
    # so we don't need to do it here.
    translations,
):
    """Runs in the other process, with an end of a pipe for input."""
    global PIPE_REC, PIPE_SEND
    PIPE_SEND = pipe_send
    PIPE_REC = pipe_rec
    TRANSLATION.update(translations)

    root = tk.Tk()
    root.withdraw()
    force_ontop = True

    def check_queue():
        """Update stages from the parent process."""
        nonlocal force_ontop
        had_values = False
        while PIPE_REC.poll():  # Pop off all the values.
            had_values = True
            operation, scr_id, args = PIPE_REC.recv()
            if operation == 'init':
                # Create a new loadscreen.
                is_main, title, stages = args
                screen = (SplashScreen if is_main else LoadScreen)(root, scr_id, title, force_ontop, stages)
                SCREENS[scr_id] = screen
            elif operation == 'set_force_ontop':
                [force_ontop] = args
                for screen in SCREENS.values():
                    screen.win.attributes('-topmost', force_ontop)
            else:
                try:
                    func = getattr(SCREENS[scr_id], 'op_' + operation)
                except AttributeError:
                    raise ValueError('Bad command "{}"!'.format(operation))
                try:
                    func(*args)
                except Exception:
                    raise Exception(operation)

        # Continually re-run this function in the TK loop.
        # If we didn't find anything in the pipe, wait longer.
        # Otherwise we hog the CPU.
        root.after(1 if had_values else 200, check_queue)
    
    root.after(10, check_queue)
    root.mainloop()  # Infinite loop, until the entire process tree quits.
