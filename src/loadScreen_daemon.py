"""Implements the splash screen in a subprocess.

During package loading, we are busy performing tasks in the main thread.
We do this in another process to sidestep the GIL, and ensure the screen
remains responsive. This is a seperate module to reduce the required dependencies.
"""
from tkinter.font import Font
import tkinter as tk

import utils


def run_screen(
    cmd_source,
    stages,
    # Pass in various bits of translated text
    # so we don't need to do it here.
    trans_title,
    trans_version,
    trans_skipped,
):
    """Runs in the other process, with an end of a pipe for input."""

    window = tk.Tk()
    window.wm_overrideredirect(True)
    window.attributes('-topmost', 1)

    window['cursor'] = utils.CURSORS['wait']
    
    stage_values = {}
    stage_maxes = {}
    stage_names = {}

    import img

    logo_img = img.png('BEE2/splash_logo')

    canvas = tk.Canvas(window)
    canvas.grid(row=0, column=0)
    canvas.create_image(
        10, 10,
        anchor='nw',
        image=logo_img,
    )

    font = Font(
        family='Times',  # Generic special case
        size=-18,  # negative = in pixels
        weight='bold',
    )

    text1 = canvas.create_text(
        10, 125,
        anchor='nw',
        text=trans_title,
        fill='white',
        font=font,
    )
    text2 = canvas.create_text(
        10, 145,
        anchor='nw',
        text=trans_version,
        fill='white',
        font=font,
    )

    # Now add shadows behind the text, and draw to the canvas.
    splash, canvas['width'], canvas['height'] = splash, width, height = img.make_splash_screen(
        max(window.winfo_screenwidth() * 0.6, 500),
        max(window.winfo_screenheight() * 0.6, 500),
        base_height=len(stages) * 20,
        text1_bbox=canvas.bbox(text1),
        text2_bbox=canvas.bbox(text2),
    )
    canvas.tag_lower(canvas.create_image(
        0, 0,
        anchor='nw',
        image=splash,
    ))
    canvas.splash_img = splash  # Keep this alive

    for ind, (st_id, stage_name) in enumerate(reversed(stages), start=1):
        stage_values[st_id] = 0
        stage_maxes[st_id] = 10
        stage_names[st_id] = stage_name
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
        
    def bar_length(stage, fraction):
        """Set a progress bar to this fractional length."""
        x1, y1, x2, y2 = canvas.coords('bar_' + stage)
        canvas.coords(
            'bar_' + stage,
            20,
            y1,
            20 + round(fraction * (width - 40)),
            y2,
        )
        
    def set_nums(stage):
        canvas.itemconfig(
            'text_' + stage,
            text='{}: ({}/{})'.format(
                stage_names[stage],
                stage_values[stage],
                stage_maxes[stage],
            )
        )
        bar_length(stage, stage_values[stage] / stage_maxes[stage])
        
    def set_length(stage, num):
        """Set the number of items in a stage."""
        stage_maxes[stage] = num
        set_nums(stage)

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
            pos = int(20 + dist*i)
            canvas.create_line(
                pos, y1, pos, y2,
                fill='#00785A',
                tags=tag,
            )
        canvas.tag_lower('tick_' + stage, 'bar_' + stage)
        
    def skip_stage(stage):
        """Skip over this stage of the loading process."""
        stage_values[stage] = 0
        stage_maxes[stage] = 0
        canvas.itemconfig(
            'text_' + stage,
            text=stage_names[stage] + ': ' + trans_skipped,
        )
        bar_length(stage, 1)  # Force stage to be max filled.
        canvas.delete('tick_' + stage)
        canvas.update()
    
    def check_queue():
        """Update stages from the parent process."""
        while cmd_source.poll():  # Pop off all the values.
            stage, operation, value = cmd_source.recv()
            if operation == 'kill':
                # Destroy everything
                window.destroy()
                # mainloop() will quit, this function will too, and
                # all our stuff will die.
                return
            elif operation == 'hide':
                window.withdraw()
            elif operation == 'show':
                window.deiconify()
            elif operation == 'value':
                stage_values[stage] = value
                set_nums(stage)
            elif operation == 'length':
                set_length(stage, value)
            elif operation == 'skip':
                skip_stage(stage)
            else:
                raise ValueError('Bad operation {!r}!'.format(operation))
            
        # Continually re-run this function in the TK loop.
        window.after_idle(check_queue)
     
    # We have to implement dragging ourselves.
    x = y = None

    def move_start(event):
        """Record offset of mouse on click"""
        nonlocal x, y
        x = event.x 
        y = event.y
        window['cursor'] = utils.CURSORS['move_item']

    def move_stop(event):
        """Clear values when releasing."""
        window['cursor'] = utils.CURSORS['wait']
        nonlocal x, y
        x = y = None

    def move_motion(event):
        """Move the window when moving the mouse."""
        if x is None or y is None:
            return
        window.geometry('+{x:g}+{y:g}'.format(
            x=window.winfo_x() + (event.x - x),
            y=window.winfo_y() + (event.y - y),
        ))

    window.bind('<Button-1>', move_start)
    window.bind('<ButtonRelease-1>', move_stop)
    window.bind('<B1-Motion>', move_motion)
        
    window.deiconify()
    window.lift()
    window.update()  # Force an update so the reqwidth is correct
    window.geometry('+{x:g}+{y:g}'.format(
        x=(window.winfo_screenwidth() - window.winfo_reqwidth()) // 2,
        y=(window.winfo_screenheight() - window.winfo_reqheight()) // 2,
    ))
    
    window.after(10, check_queue)
    window.mainloop()  # Infinite loop until we've quit here...
