"""Modified version of ConfigParser that can be easily resaved.

It only saves if the values are modified.
Most functions are also altered to allow defaults instead of erroring.
"""
from configparser import ConfigParser, NoOptionError

import os
import utils
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)


class ConfigFile(ConfigParser):
    """A version of ConfigParser which can easily save itself.

    The config will track whether any values change, and only resave
    if modified.
    get_val, get_bool, and get_int are modified to return defaults instead
    of erroring.
    """
    def __init__(self, filename, root=None, auto_load=True):
        """Initialise the config file.

        `filename` is the name of the config file, in the `root` directory.
        If `auto_load` is true, this file will immediately be read and parsed.
        If `root` is not set, it will be set to the 'config/' folder in the BEE2
        folder.
        """
        super().__init__()

        if root is None:
            self.filename = utils.conf_location(os.path.join('config/', filename))
        else:
            self.filename = os.path.join(root, filename)

        self.writer = srctools.AtomicWriter(self.filename)
        self.has_changed = False

        if auto_load:
            self.load()


    def load(self):
        if self.filename is None:
            return

        try:
            with open(self.filename, 'r') as conf:
                self.read_file(conf)
        except (FileNotFoundError, IOError):
            LOGGER.warning(
                'Config "{}" not found! Using defaults...',
                self.filename,
            )
            # If we fail, just continue - we just use the default values
        # We're not different to the file on disk..
        self.has_changed = False

    def save(self):
        """Write our values out to disk."""
        LOGGER.info('Saving changes in config "{}"!', self.filename)
        if self.filename is None:
            raise ValueError('No filename provided!')

        with self.writer as conf:
            self.write(conf)
        self.has_changed = False

    def save_check(self):
        """Check to see if we have different values, and save if needed."""
        if self.has_changed:
            self.save()

    def set_defaults(self, def_settings):
        """Set the default values if the settings file has no values defined."""
        for sect, values in def_settings.items():
            if sect not in self:
                self[sect] = {}
            for key, default in values.items():
                if key not in self[sect]:
                    self[sect][key] = str(default)
        self.save_check()

    def get_val(self, section: str, value: str, default: str) -> str:
        """Get the value in the specifed section.

        If either does not exist, set to the default and return it.
        """
        if section not in self:
            self[section] = {}
        if value in self[section]:
            return self[section][value]
        else:
            self.has_changed = True
            self[section][value] = default
            return default

    def __getitem__(self, section):
        try:
            return super().__getitem__(section)
        except KeyError:
            self[section] = {}
            return super().__getitem__(section)


    def getboolean(self, section, value, default=False) -> bool:
        """Get the value in the specified section, coercing to a Boolean.

            If either does not exist, set to the default and return it.
            """
        if section not in self:
            self[section] = {}
        try:
            return super().getboolean(section, value)
        except (ValueError, NoOptionError):
            #  Invalid boolean, or not found
            self.has_changed = True
            self[section][value] = str(int(default))
            return default

    get_bool = getboolean

    def getint(self, section, value, default=0) -> int:
        """Get the value in the specified section, coercing to a Integer.

            If either does not exist, set to the default and return it.
            """
        if section not in self:
            self[section] = {}
        try:
            return super().getint(section, value)
        except (ValueError, NoOptionError):
            self.has_changed = True
            self[section][value] = str(int(default))
            return default

    get_int = getint

    def add_section(self, section):
        self.has_changed = True
        super().add_section(section)

    def remove_section(self, section):
        self.has_changed = True
        super().remove_section(section)

    def set(self, section, option, value=None):
        orig_val = self.get(section, option, fallback=None)
        value = str(value)
        if orig_val is None or orig_val != value:
            self.has_changed = True
            super().set(section, option, value)

    add_section.__doc__ = ConfigParser.add_section.__doc__
    remove_section.__doc__ = ConfigParser.remove_section.__doc__
    set.__doc__ = ConfigParser.set.__doc__

# Define this here so app modules can easily access the config
# Don't load it though, since this is imported by VBSP too.
GEN_OPTS = ConfigFile('config.cfg', auto_load=False)
