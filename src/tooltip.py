# coding=utf-8
"""Display tooltips below a tooltip after a time delay.

Call add_tooltip with a widget to add all the events automatically,
or call show and hide to directly move the window.
"""
import tkinter as tk
from tk_tools import TK_ROOT

import utils

PADDING = 0  # Space around the target widget
CENT_DIST = 50  # Distance around center where we align centered.

window = tk.Toplevel(TK_ROOT)
window.withdraw()
window.transient(master=TK_ROOT)
window.overrideredirect(1)
window.resizable(False, False)

context_label = tk.Label(
    window,
    text='',
    font="TkSmallCaptionFont",

    bg=(
        'white' if utils.WIN else
        'white' if utils.MAC else
        'white'
    ),
    fg=(
        'black' if utils.WIN else
        'black' if utils.MAC else
        'black'
    ),
    relief="groove",
    padx=5,

    justify='left',
    wraplength=200,  # Stop it getting too long.
    )
context_label.grid(row=0, column=0)


def show(widget: tk.Misc, text, mouse_x, mouse_y):
    """Show the context window."""
    context_label['text'] = text
    window.deiconify()
    window.update_idletasks()
    window.lift()

    # We're going to position tooltips towards the center of the main window.
    # That way they don't tend to stick out, even in multi-window setups.

    # To decide where to put the tooltip, we first want the center of the
    # main window.
    cent_x = TK_ROOT.winfo_rootx() + TK_ROOT.winfo_width() / 2
    cent_y = TK_ROOT.winfo_rooty() + TK_ROOT.winfo_height() / 2

    x_centered = False

    if cent_x > mouse_x + CENT_DIST:
        # Left of center, so place right of the target
        x = widget.winfo_rootx() + widget.winfo_width() + PADDING
    elif cent_x < mouse_x - CENT_DIST:
        # Right of center, so place left of the target
        x = widget.winfo_rootx() - window.winfo_width() - PADDING
    else:  # Center horizontally
        x = (
            widget.winfo_rootx() +
            (widget.winfo_width() - window.winfo_width()) // 2
        )
        x_centered = True

    if cent_y > mouse_y + CENT_DIST:
        # Above center, so place below target
        y = widget.winfo_rooty() + widget.winfo_height() + PADDING
    elif cent_y < mouse_y - CENT_DIST:
        # Below center, so place above target
        y = widget.winfo_rooty() - window.winfo_height() - PADDING
    else:  # Center vertically
        y = (
            widget.winfo_rooty() +
            (widget.winfo_height() - window.winfo_height()) // 2
        )

        # If both X and Y are centered, the tooltip will appear on top of
        # the mouse and immediately hide. Offset it to fix that.
        if x_centered:
            y += window.winfo_height()

    window.geometry('+{}+{}'.format(int(x), int(y)))


def hide(e=None):
    window.withdraw()


def add_tooltip(targ_widget, text='', delay=500, show_when_disabled=False):
    """Add a tooltip to the specified widget.

    delay is the amount of milliseconds of hovering needed to show the
    tooltip.
    text is the initial text for the tooltip.
    Set targ_widget.tooltip_text to change the tooltip dynamically.
    If show_when_disabled is false, no context menu will be shown if the
    target widget is disabled.
    """
    targ_widget.tooltip_text = text
    event_id = None  # The id of the enter event, so we can cancel it.

    # Only check for disabled widgets if the widget actually has a state,
    # and the user hasn't disabled the functionality
    check_disabled = hasattr(targ_widget, 'instate') and not show_when_disabled

    def after_complete(x, y):
        """Remove the id and show the tooltip after the delay."""
        nonlocal event_id
        event_id = None  # Invalidate event id
        if targ_widget.tooltip_text:
            show(targ_widget, targ_widget.tooltip_text, x, y)

    def enter_handler(event: tk.Event):
        """Schedule showing the tooltip."""
        nonlocal event_id
        if targ_widget.tooltip_text:
            if check_disabled and not targ_widget.instate(('!disabled',)):
                return
            event_id = TK_ROOT.after(
                delay,
                after_complete,
                event.x_root, event.y_root,
            )

    def exit_handler(e):
        """When the user leaves, cancel the event."""
        # We only want to cancel if the event hasn't expired already
        nonlocal event_id
        hide()
        if event_id is not None:
            TK_ROOT.after_cancel(
                event_id
            )

    targ_widget.bind(
        '<Enter>',
        enter_handler,
    )
    targ_widget.bind(
        '<Leave>',
        exit_handler,
    )
