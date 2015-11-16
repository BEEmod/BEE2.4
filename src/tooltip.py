# coding=utf-8
"""Display tooltips below a tooltip after a time delay.

Call add_tooltip with a widget to add all the events automatically,
or call show and hide to directly move the window.
"""
import tkinter as tk
from tk_tools import TK_ROOT

import utils

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


def show(widget, text, _=None):
    """Show the context window."""
    context_label['text'] = text
    window.deiconify()
    window.update_idletasks()
    window.lift()

    # Center vertically below the button
    x = (
        widget.winfo_rootx() -
        (
            window.winfo_reqwidth()
            - widget.winfo_reqwidth()
            ) // 2
        )
    y = (
        widget.winfo_rooty()
        + widget.winfo_reqheight()
        )
    window.geometry('+' + str(x) + '+' + str(y))


def hide(e=None):
    window.withdraw()


def add_tooltip(targ_widget, text='', delay=500):
    """Add a tooltip to the specified widget.

    delay is the amount of milliseconds of hovering needed to show the
    tooltip.
    text is the initial text for the tooltip.
    Set targ_widget.tooltip_text to change the tooltip dynamically.
    If the target widget is disabled, no context menu will be shown.
    """
    targ_widget.tooltip_text = text
    event_id = None  # The id of the enter event, so we can cancel it.

    def after_complete():
        """Remove the id and show the tooltip after the delay."""
        nonlocal event_id
        event_id = None  # Invalidate event id
        if targ_widget.tooltip_text:
            show(targ_widget, targ_widget.tooltip_text)

    def enter_handler(e):
        """Schedule showing the tooltip."""
        nonlocal event_id
        if targ_widget.tooltip_text:
            if hasattr(targ_widget, 'instate'):
                if not targ_widget.instate(('!disabled',)):
                    return
            event_id = TK_ROOT.after(
                delay,
                after_complete,
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
