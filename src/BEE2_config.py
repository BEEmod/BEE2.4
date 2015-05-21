import os.path

from configparser import ConfigParser


class ConfigFile(ConfigParser):
    def __init__(self, filename, root='../config'):
        """Initialise the config file.

        filename is the name of the config file, in the 'root' directory.
        This file will immediately be read and parsed.
        """
        super().__init__()
        self.filename = os.path.join(root, filename)
        self.load()
        self.has_changed = False

    def load(self):
        if self.filename is None:
            return

        try:
            with open(self.filename, 'r') as conf:
                self.read_file(conf)
        except FileNotFoundError:
            print('Config "' + self.filename + '" not found! Using defaults...')
            # If we fail, just continue - we just use the default values
        self.has_changed = False

    def save(self):
        """Write our values out to disk."""
        if self.filename is None:
            return
        self.has_changed = False
        with open(self.filename, 'w') as conf:
            self.write(conf)

    def save_check(self):
        """Check to see if we have different values, and save if needed."""
        if self.has_changed:
            print('Saving changes in config "' + self.filename + '"!')
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

    def get_val(self, section, value, default):
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

    def getboolean(self, section, value, default=False) -> bool:
        """Get the value in the specified section, coercing to a Boolean.

            If either does not exist, set to the default and return it.
            """
        if section not in self:
            self[section] = {}
        if value in self[section]:
            return super().getboolean(section, value)
        else:
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
        if value in self[section]:
            return super().getint(section, value)
        else:
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
        if orig_val is None or orig_val is not value:
            self.has_changed = True
            super().set(section, option, str(value))

    add_section.__doc__ = ConfigParser.add_section.__doc__
    remove_section.__doc__ = ConfigParser.remove_section.__doc__
    set.__doc__ = ConfigParser.set.__doc__

GEN_OPTS = ConfigFile('config.cfg')