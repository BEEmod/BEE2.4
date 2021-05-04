# coding=utf-8
"""Display tooltips below a tooltip after a time delay.

Call add_tooltip with a widget to add all the events automatically.
"""
import tkinter as tk
from app import TK_ROOT, img


PADDING = 0  # Space around the target widget
CENT_DIST = 50  # Distance around center where we align centered.

# Create the widgets we use.
window = tk.Toplevel(TK_ROOT)
window.withdraw()
window.transient(master=TK_ROOT)
window.overrideredirect(1)
window.resizable(False, False)

context_label = tk.Label(
    window,
    text='',
    font="TkSmallCaptionFont",

    bg='white',
    fg='black',
    relief="groove",
    padx=5,

    # Put image above text if both are provided.
    compound='top',
    justify='left',
    wraplength=260,  # Stop it getting too long.
)
context_label.grid(row=0, column=0)


def _show(widget: tk.Misc, mouse_x, mouse_y) -> None:
    """Show the context window."""
    # noinspection PyUnresolvedReferences, PyProtectedMember
    context_label['text'] = widget._bee2_tooltip_text
    # noinspection PyUnresolvedReferences, PyProtectedMember
    img.apply(context_label, widget._bee2_tooltip_img)

    window.deiconify()
    window.update_idletasks()
    window.lift()

    # We're going to position tooltips towards the center of the main window.
    # That way they don't tend to stick out, even in multi-window setups.

    # To decide where to put the tooltip, we first want the center of the
    # main window.
    x = cent_x = TK_ROOT.winfo_rootx() + TK_ROOT.winfo_width() / 2
    y = cent_y = TK_ROOT.winfo_rooty() + TK_ROOT.winfo_height() / 2

    x_centered = y_centered = True

    # If the widget is smaller than the context window, always center.
    if widget.winfo_width() > window.winfo_width():
        if cent_x > mouse_x + CENT_DIST:
            # Left of center, so place right of the target
            x = widget.winfo_rootx() + widget.winfo_width() + PADDING
            x_centered = False
        elif cent_x < mouse_x - CENT_DIST:
            # Right of center, so place left of the target
            x = widget.winfo_rootx() - window.winfo_width() - PADDING
            x_centered = False

    if widget.winfo_height() > window.winfo_height():
        if cent_y > mouse_y + CENT_DIST:
            # Above center, so place below target
            y = widget.winfo_rooty() + widget.winfo_height() + PADDING
            y_centered = False
        elif cent_y < mouse_y - CENT_DIST:
            # Below center, so place above target
            y = widget.winfo_rooty() - window.winfo_height() - PADDING
            y_centered = False

    if x_centered:  # Center horizontally
        x = (
            widget.winfo_rootx() +
            (widget.winfo_width() - window.winfo_width()) // 2
        )

    if y_centered:
        y = (
            widget.winfo_rooty() +
            (widget.winfo_height() - window.winfo_height()) // 2
        )

        # If both X and Y are centered, the tooltip will appear on top of
        # the mouse and immediately hide. Offset it to fix that.
        if x_centered:
            if mouse_y < cent_y:
                y = widget.winfo_rooty() + widget.winfo_height() + PADDING
            else:
                y = widget.winfo_rooty() - window.winfo_height() - PADDING

    window.geometry('+{}+{}'.format(int(x), int(y)))


def set_tooltip(widget: tk.Misc, text: str='', image: img.Handle=None):
    """Change the tooltip for a widget."""
    widget._bee2_tooltip_text = text
    widget._bee2_tooltip_img = image


def add_tooltip(
    targ_widget: tk.Misc,
    text: str='',
    image: img.Handle=None,
    delay: int=500,
    show_when_disabled: bool=False,
) -> None:
    """Add a tooltip to the specified widget.

    delay is the amount of milliseconds of hovering needed to show the
    tooltip.
    text is the initial text for the tooltip.
    If set, image is also shown on the tooltip.
    If show_when_disabled is false, no context menu will be shown if the
    target widget is disabled.
    """
    targ_widget._bee2_tooltip_text = text
    targ_widget._bee2_tooltip_img = image

    event_id = None  # The id of the enter event, so we can cancel it.

    # Only check for disabled widgets if the widget actually has a state,
    # and the user hasn't disabled the functionality
    check_disabled = hasattr(targ_widget, 'instate') and not show_when_disabled

    def after_complete(x, y):
        """Remove the id and show the tooltip after the delay."""
        nonlocal event_id
        event_id = None  # Invalidate event id
        # noinspection PyUnresolvedReferences, PyProtectedMember
        if targ_widget._bee2_tooltip_text or targ_widget._bee2_tooltip_img is not None:
            _show(targ_widget, x, y)

    def enter_handler(event):
        """Schedule showing the tooltip."""
        nonlocal event_id
        # noinspection PyUnresolvedReferences, PyProtectedMember
        if targ_widget._bee2_tooltip_text or targ_widget._bee2_tooltip_img is not None:
            # We know it has this method from above!
            # noinspection PyUnresolvedReferences
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
        window.withdraw()
        if event_id is not None:
            TK_ROOT.after_cancel(
                event_id
            )

    targ_widget.bind('<Enter>', enter_handler)
    targ_widget.bind('<Leave>', exit_handler)
