"""Displays logs for the application.
"""
from tkinter import ttk
import tkinter as tk

import logging

import srctools.logger
from tk_tools import TK_ROOT
from BEE2_config import GEN_OPTS
import tk_tools
import utils

# Colours to use for each log level
LVL_COLOURS = {
    logging.CRITICAL: 'white',
    logging.ERROR: 'red',
    logging.WARNING: '#FF7D00',  # 255, 125, 0
    logging.INFO: '#0050FF',
    logging.DEBUG: 'grey',
}

BOX_LEVELS = [
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
]

LVL_TEXT = {
    logging.DEBUG: _('Debug messages'),
    logging.INFO: _('Default'),
    logging.WARNING: _('Warnings Only'),
}

window = tk.Toplevel(TK_ROOT)
window.wm_withdraw()

log_handler = None  # type: TextHandler
text_box = None  # type: tk.Text
level_selector = None  # type: ttk.Combobox

START = '1.0'  # Row 1, column 0 = first character
END = tk.END


class TextHandler(logging.Handler):
    """Log all data to a Tkinter Text widget."""
    def __init__(self, widget: tk.Text, level=logging.NOTSET):
        self.widget = widget
        super().__init__(level)

        # Assign colours for each logging level
        for level, colour in LVL_COLOURS.items():
            widget.tag_config(
                logging.getLevelName(level),
                foreground=colour,
                # For multi-line messages, indent this much.
                lmargin2=30,
            )
        widget.tag_config(
            logging.getLevelName(logging.CRITICAL),
            background='red',
        )
        # If multi-line messages contain carriage returns, lmargin2 doesn't
        # work. Add an additional tag for that.
        widget.tag_config(
            'INDENT',
            lmargin1=30,
            lmargin2=30,
        )

        self.has_text = False

        widget['state'] = "disabled"

    def emit(self, record: logging.LogRecord):
        """Add a logging message."""

        msg = record.msg
        if isinstance(record.msg, srctools.logger.LogMessage):
            # Ensure we don't use the extra ASCII indents here.
            record.msg = record.msg.format_msg()

        self.widget['state'] = "normal"
        # We don't want to indent the first line.
        firstline, *lines = self.format(record).split('\n')

        if self.has_text:
            # Start with a newline so it doesn't end with one.
            self.widget.insert(
                END,
                '\n',
                (),
            )

        self.widget.insert(
            END,
            firstline,
            (record.levelname,),
        )
        for line in lines:
            self.widget.insert(
                END,
                '\n',
                ('INDENT',),
                line,
                # Indent following lines.
                (record.levelname, 'INDENT'),
            )
        self.widget.see(END)  # Scroll to the end
        self.widget['state'] = "disabled"
        # Update it, so it still runs even when we're busy with other stuff.
        self.widget.update_idletasks()

        self.has_text = True

        # Undo the record overwrite, so other handlers get the correct object.
        record.msg = msg


def set_visible(is_visible: bool):
    """Show or hide the window."""
    if is_visible:
        window.deiconify()
    else:
        window.withdraw()
    GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(is_visible)


def btn_copy():
    """Copy the selected text, or the whole console."""
    try:
        text = text_box.get(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:  # No selection
        text = text_box.get(START, END)
    text_box.clipboard_clear()
    text_box.clipboard_append(text)


def btn_clear():
    """Clear the console."""
    text_box['state'] = "normal"
    text_box.delete(START, END)
    log_handler.has_text = False
    text_box['state'] = "disabled"


def set_level(event):
    level = BOX_LEVELS[event.widget.current()]
    log_handler.setLevel(level)
    GEN_OPTS['Debug']['window_log_level'] = logging.getLevelName(level)


def init(start_open: bool, log_level: str='info') -> None:
    """Initialise the window."""
    global log_handler, text_box, level_selector

    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    window.title(_('Logs - {}').format(utils.BEE_VERSION))
    window.protocol('WM_DELETE_WINDOW', lambda: set_visible(False))

    text_box = tk.Text(
        window,
        name='text_box',
        width=50,
        height=15,
    )
    text_box.grid(row=0, column=0, sticky='NSEW')

    log_level = logging.getLevelName(log_level.upper())

    log_handler = TextHandler(text_box)

    try:
        log_handler.setLevel(log_level)
    except ValueError:
        log_level = logging.INFO
    log_handler.setFormatter(logging.Formatter(
        # One letter for level name
        '[{levelname[0]}] {module}.{funcName}(): {message}',
        style='{',
    ))

    logging.getLogger().addHandler(log_handler)

    scroll = tk_tools.HidingScroll(
        window,
        name='scroll',
        orient=tk.VERTICAL,
        command=text_box.yview,
    )
    scroll.grid(row=0, column=1, sticky='NS')
    text_box['yscrollcommand'] = scroll.set

    button_frame = ttk.Frame(window, name='button_frame')
    button_frame.grid(row=1, column=0, columnspan=2, sticky='EW')

    ttk.Button(
        button_frame,
        name='clear_btn',
        text='Clear',
        command=btn_clear,
    ).grid(row=0, column=0)

    ttk.Button(
        button_frame,
        name='copy_btn',
        text=_('Copy'),
        command=btn_copy,
    ).grid(row=0, column=1)

    sel_frame = ttk.Frame(
        button_frame,
    )
    sel_frame.grid(row=0, column=2, sticky='EW')
    button_frame.columnconfigure(2, weight=1)

    ttk.Label(
        sel_frame,
        text=_('Show:'),
        anchor='e',
        justify='right',
    ).grid(row=0, column=0, sticky='E')

    level_selector = ttk.Combobox(
        sel_frame,
        name='level_selector',
        values=[
            LVL_TEXT[level]
            for level in
            BOX_LEVELS
        ],
        exportselection=0,
        # On Mac this defaults to being way too wide!
        width=15 if utils.MAC else None,
    )
    level_selector.state(['readonly'])  # Prevent directly typing in values
    level_selector.bind('<<ComboboxSelected>>', set_level)
    level_selector.current(BOX_LEVELS.index(log_level))

    level_selector.grid(row=0, column=1, sticky='E')
    sel_frame.columnconfigure(1, weight=1)

    utils.add_mousewheel(text_box, window, sel_frame, button_frame)

    if utils.USE_SIZEGRIP:
        ttk.Sizegrip(button_frame).grid(row=0, column=3)

    if start_open:
        window.deiconify()
        window.lift()
        # Force an update, we're busy with package extraction...
        window.update()
    else:
        window.withdraw()


if __name__ == '__main__':
    srctools.logger.init_logging()
    LOGGER = srctools.logger.get_logger('BEE2')
    init(True, log_level='DEBUG')

    # Generate a bunch of log messages to test the window.
    def errors():
        # Use a generator to easily run these functions with a delay.
        yield LOGGER.info('Info Message')
        yield LOGGER.critical('Critical Message')
        yield LOGGER.warning('Warning')

        try:
            raise ValueError('An error')
        except ValueError:
            yield LOGGER.exception('Error message')

        yield LOGGER.warning('Post-Exception warning')
        yield LOGGER.info('Info')
        yield LOGGER.debug('Debug Message')

    err_iterator = errors()

    def next_error():
        # Use False since functions return None usually
        if next(err_iterator, False) is not False:
            TK_ROOT.after(1000, next_error)

    TK_ROOT.after(1000, next_error)
    TK_ROOT.mainloop()
