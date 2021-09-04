"""Displays logs for the application.
"""
import wx
import wx.richtext

import logging

import srctools.logger
from BEE2_config import GEN_OPTS
from app import optionWindow
import utils

# Colours to use for each log level
LVL_COLOURS = {
    logging.CRITICAL: wx.TextAttr(
        colText=(255, 255, 255),
        colBack=(255, 32, 32),
    ),  # White on red
    logging.ERROR: wx.TextAttr((255, 32, 32)),  # Red
    logging.WARNING: wx.TextAttr((255, 125, 0)),  # Portal Orange
    logging.INFO: wx.TextAttr((0, 80, 255)),  # Portal Blue
    logging.DEBUG: wx.TextAttr((80, 80, 80)),  # Grey
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


class LogWindow(logging.Handler):
    """Log all data to a Tkinter Text widget."""
    def __init__(self, start_visible: bool, start_level: str) -> None:

        super().__init__(level=logging.NOTSET)
        self.setFormatter(logging.Formatter(
            # One letter for level name
            '[{levelname[0]}] {module}.{funcName}(): {message}',
            style='{',
        ))
        self.has_text = False

        conf_level = logging.getLevelName(start_level.upper())
        try:
            self.setLevel(conf_level)
        except ValueError:
            self.setLevel(logging.INFO)

        self.win = win = wx.Frame(None, wx.ID_ANY)
        win.SetSize((638, 300))
        win.SetTitle(_('Logs - {}').format(utils.BEE_VERSION))
        win.Show(start_visible)

        self.wrapper = wx.Panel(win, wx.ID_ANY, style=wx.BORDER_NONE)
        self.wrapper.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        self.wrapper.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))

        sizer_vert = wx.BoxSizer(wx.VERTICAL)

        self.log_display = wx.richtext.RichTextCtrl(
            self.wrapper, wx.ID_ANY,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
        )
        self.log_display.SetFont(wx.Font(
            wx.FontInfo(10).FaceName("Courier New").Family(wx.FONTFAMILY_MODERN)
        ))
        # Indent multiline messages under the first line.
        sizer_vert.Add(self.log_display, 1, wx.EXPAND, 0)

        sizer_toolbar = wx.BoxSizer(wx.HORIZONTAL)
        sizer_vert.Add(sizer_toolbar, 0, wx.EXPAND, 0)

        self.btn_clear = wx.Button(self.wrapper, wx.ID_CLEAR, "")
        sizer_toolbar.Add(self.btn_clear, 0, 0, 0)

        self.btn_copy = wx.Button(self.wrapper, wx.ID_COPY, "")
        sizer_toolbar.Add(self.btn_copy, 0, 0, 0)

        lbl_show = wx.StaticText(self.wrapper, wx.ID_ANY, _("Show:"), style=wx.ALIGN_RIGHT)
        lbl_show.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        sizer_toolbar.Add(lbl_show, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)

        self.filter_combo = wx.ComboBox(
            self.wrapper,
            wx.ID_ANY,
            style=wx.CB_DROPDOWN | wx.TE_READONLY,
            choices=[LVL_TEXT[level] for level in BOX_LEVELS],
        )
        try:
            self.filter_combo.SetSelection(BOX_LEVELS.index(conf_level))
        except ValueError:
            pass
        sizer_toolbar.Add(self.filter_combo, 0, 0, 0)
        self.wrapper.SetSizer(sizer_vert)
        win.Layout()

        self.filter_combo.Bind(wx.EVT_COMBOBOX, self._event_set_level)
        self.btn_clear.Bind(wx.EVT_BUTTON, self._event_clear)
        self.btn_copy.Bind(wx.EVT_BUTTON, self._event_copy)
        logging.getLogger().addHandler(self)
        optionWindow.refresh_callbacks.append(self._settings_changed)

#
# class TextHandler(logging.Handler):
#     """Log all data to a Tkinter Text widget."""
#     def __init__(self) -> None:
#         super().__init__(logging.NOTSET)
#         self.setFormatter(logging.Formatter(
#             # One letter for level name
#             '[{levelname[0]}] {module}.{funcName}(): {message}',
#             style='{',
#         ))

    def emit(self, record: logging.LogRecord) -> None:
        """Add a logging message."""

        msg = record.msg
        if isinstance(record.msg, srctools.logger.LogMessage):
            # Ensure we don't use the extra ASCII indents here.
            record.msg = record.msg.format_msg()

        if self.has_text:
            # Start with a newline so it doesn't end with one.
            self.log_display.MoveEnd()
            self.log_display.Newline()

        self.log_display.BeginLeftIndent(
            leftIndent=0,
            leftSubIndent=30,
        )
        # This has to be done inside BeginLeftIndent.
        try:
            self.log_display.SetDefaultStyle(LVL_COLOURS[record.levelno])
        except KeyError:
            pass
        # Convert line breaks inside the message to a soft line break, which
        # gets indented.
        self.log_display.MoveEnd()
        self.log_display.WriteText(
            self.format(record).strip('\n').replace('\n', wx.richtext.RichTextLineBreakChar)
        )
        self.log_display.EndLeftIndent()

        # Scroll to the end
        self.log_display.ShowPosition(self.log_display.GetLastPosition())

        self.log_display.Update()
        self.has_text = True

        # Undo the record overwrite, so other handlers get the correct object.
        record.msg = msg

    def set_visible(self, is_visible: bool) -> None:
        """Show or hide the window."""
        self.win.Show(is_visible)
        GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(is_visible)

    def _event_copy(self, event: wx.CommandEvent) -> None:
        """Copy the selected text, or the whole console."""
        text = self.log_display.GetStringSelection()
        if not text:
            text = self.log_display.GetValue()
        clip: wx.Clipboard = wx.Clipboard.Get()
        clip.SetData(wx.TextDataObject(text))

    def _event_clear(self, event: wx.CommandEvent) -> None:
        """Clear the console."""
        self.log_display.Clear()
        self.has_text = False

    def _event_set_level(self, event: wx.CommandEvent) -> None:
        """Set the level of log messages we display."""
        level = BOX_LEVELS[event.GetSelection()]
        self.setLevel(level)
        GEN_OPTS['Debug']['window_log_level'] = logging.getLevelName(level)

    def _settings_changed(self) -> None:
        """Callback from optionWindow, used to hide/show us as required."""
        self.win.Show(optionWindow.SHOW_LOG_WIN.get())


def test() -> None:
    """Display a test window."""
    LOGGER = srctools.logger.get_logger('BEE2')
    app = wx.App()
    window = LogWindow(True, 'DEBUG')
    # Generate a bunch of log messages to test the window.
    def errors():
        # Use a generator to easily run these functions with a delay.
        yield LOGGER.info('Info Message\nWith a second line.')
        yield LOGGER.critical('Critical Message\nWith a second line.')
        yield LOGGER.warning('Warning\nWith a second line.')

        try:
            raise ValueError('An error')
        except ValueError:
            yield LOGGER.exception('Error message')

        yield LOGGER.warning('Post-Exception warning')
        yield LOGGER.info('Info')
        yield LOGGER.debug('Debug Message')

    err_iterator = errors()

    def next_error():
        try:
            next(err_iterator)
            timer.Start(1000)
        except StopIteration:
            pass

    timer = wx.PyTimer(next_error)
    timer.Start(1000)

#         try:
#             if isinstance(record.msg, srctools.logger.LogMessage):
#                 # Ensure we don't use the extra ASCII indents here.
#                 record.msg = record.msg.format_msg()
#             text = self.format(record)
#         finally:
#             # Undo the record overwrite, so other handlers get the correct object.
#             record.msg = msg
#         _PIPE_MAIN_SEND.send(('log', record.levelname, text))
#
#     def set_visible(self, is_visible: bool):
#         """Show or hide the window."""
#         GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(is_visible)
#         _PIPE_MAIN_SEND.send(('visible', is_visible, None))
#
#     def setLevel(self, level: Union[int, str]) -> None:
#         """Set the level of the log window."""
#         if isinstance(level, int):
#             level = logging.getLevelName(level)
#         super(TextHandler, self).setLevel(level)
#         _PIPE_MAIN_SEND.send(('level', level, None))
#
# HANDLER = TextHandler()
# logging.getLogger().addHandler(HANDLER)
#
#
# def setting_apply_thread() -> None:
#     """Thread to apply setting changes."""
#     while True:
#         cmd, param = _PIPE_MAIN_REC.recv()
#         if cmd == 'level':
#             TextHandler.setLevel(HANDLER, param)
#             GEN_OPTS['Debug']['window_log_level'] = param
#         elif cmd == 'visible':
#             GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(param)
#         else:
#             raise ValueError(f'Unknown command {cmd}({param})!')
#
# _setting_thread = threading.Thread(
#     target=setting_apply_thread,
#     name='logwindow_settings_apply',
#     daemon=True,
# )
# _setting_thread.start()
