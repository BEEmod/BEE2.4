import os
import shutil
import zipfile
import random
import utils

import srctools.logger
import BEE2_config
from srctools import Property, NoKeyError, KeyValError

from typing import List, Tuple, Optional


LOGGER = srctools.logger.get_logger(__name__)

PAL_DIR = utils.conf_location('palettes/')

PAL_EXT = '.bee2_palette'

pal_list = []  # type: List[Palette]

# Allow translating the names of the built-in palettes
DEFAULT_PALETTES = {
    # i18n: Last exported items
    'LAST_EXPORT': _('<Last Export>'),
    # i18n: Empty palette name
    'EMPTY': _('Blank'),

    # i18n: BEEmod 1 palette.
    'BEEMOD': _('BEEMod'),
    # i18n: Default items merged together
    'P2_COLLAPSED': _('Portal 2 Collapsed'),

    # i18n: Original Palette
    'PORTAL2': _('Portal 2'),
    # i18n: Aperture Tag's palette
    'APTAG': _('Aperture Tag'),
}


class Palette:
    """A palette, saving an arrangement of items for editoritems.txt"""
    def __init__(
        self,
        name,
        pos: List[Tuple[str, int]],
        trans_name='',
        prevent_overwrite=False,
        filename: str=None,
        settings: Optional[Property]=None,
    ):
        # Name of the palette
        self.name = name
        self.trans_name = trans_name
        if trans_name:
            try:
                self.name = DEFAULT_PALETTES[trans_name.upper()]
            except KeyError:
                LOGGER.warning('Unknown translated palette "{}', trans_name)

        # If loaded from a file, the path to use.
        # None determines a filename automatically.
        self.filename = filename
        # List of id, index tuples.
        self.pos = pos
        # If true, prevent overwriting the original file
        # (premade palettes or <LAST EXPORT>)
        self.prevent_overwrite = prevent_overwrite

        # If not None, settings associated with the palette.
        self.settings = settings

    def __str__(self):
        return self.name


    @classmethod
    def parse(cls, path: str):
        with open(path, encoding='utf8') as f:
            props = Property.parse(f, path)
        name = props['Name', '??']
        items = []
        for item in props.find_children('Items'):
            items.append((item.real_name, int(item.value)))

        trans_name = props['TransName', '']

        try:
            settings = props.find_key('Settings')
        except NoKeyError:
            settings = None

        return Palette(
            name,
            items,
            trans_name=trans_name,
            prevent_overwrite=props.bool('readonly'),
            filename=os.path.basename(path),
            settings=settings,
        )

    def save(self, ignore_readonly=False):
        """Save the palette file into the specified location.

        If ignore_readonly is true, this will ignore the `prevent_overwrite`
        property of the palette (allowing resaving those properties over old
        versions). Otherwise those palettes always create a new file.
        """
        LOGGER.info('Saving "{}"!', self.name)
        props = Property(None, [
            Property('Name', self.name),
            Property('TransName', self.trans_name),
            Property('ReadOnly', srctools.bool_as_int(self.prevent_overwrite)),
            Property('Items', [
                Property(item_id, str(subitem))
                for item_id, subitem in self.pos
            ])
        ])
        # If default, don't include in the palette file.
        # Remove the translated name, in case it's not going to write
        # properly to the file.
        if self.trans_name:
            props['Name'] = ''
        else:
            del props['TransName']

        if not self.prevent_overwrite:
            del props['ReadOnly']

        if self.settings is not None:
            self.settings.name = 'Settings'
            props.append(self.settings.copy())

        # We need to write a new file, determine a valid path.
        # Use a hash to ensure it's a valid path (without '-' if negative)
        # If a conflict occurs, add ' ' and hash again to get a different
        # value.
        if self.filename is None or (self.prevent_overwrite and not ignore_readonly):
            hash_src = self.name
            while True:
                hash_filename = str(abs(hash(hash_src))) + PAL_EXT
                if os.path.isfile(hash_filename):
                    # Add a random character to iterate the hash.
                    hash_src += chr(random.randrange(0x10ffff))
                else:
                    file = open(os.path.join(PAL_DIR, hash_filename), 'w', encoding='utf8')
                    self.filename = os.path.join(PAL_DIR, hash_filename)
                    break
        else:
            file = open(os.path.join(PAL_DIR, self.filename), 'w', encoding='utf8')
        with file:
            for line in props.export():
                file.write(line)

    def delete_from_disk(self):
        """Delete this palette from disk."""
        if self.filename is not None:
            os.remove(os.path.join(PAL_DIR, self.filename))


def load_palettes():
    """Scan and read in all palettes in the specified directory."""

    # Load our builtin palettes:
    for builtin_pal in utils.install_path('palettes/').glob('*' + PAL_EXT):
        LOGGER.info('Loading builtin "{}"', builtin_pal.stem)
        pal_list.append(Palette.parse(str(builtin_pal)))

    for name in os.listdir(PAL_DIR):  # this is both files and dirs
        LOGGER.info('Loading "{}"', name)
        path = os.path.join(PAL_DIR, name)
        pos_file, prop_file = None, None
        try:
            if name.endswith(PAL_EXT):
                try:
                    pal_list.append(Palette.parse(path))
                except KeyValError as exc:
                    # We don't need the traceback, this isn't an error in the app
                    # itself.
                    LOGGER.warning('Could not parse palette file, skipping:\n{}', exc)
                continue
            elif name.endswith('.zip'):
                # Extract from a zip
                with zipfile.ZipFile(path) as zip_file:
                    pos_file = zip_file.open('positions.txt')
                    prop_file = zip_file.open('properties.txt')
            elif os.path.isdir(path):
                # Open from the subfolder
                pos_file = open(os.path.join(path, 'positions.txt'))
                prop_file = open(os.path.join(path, 'properties.txt'))
            else:  # A non-palette file, skip it.
                LOGGER.debug('Skipping "{}"', name)
                continue
        except (KeyError, FileNotFoundError, zipfile.BadZipFile):
            #  KeyError is returned by zipFile.open() if file is not present
            LOGGER.warning('Bad palette file "{}"!', name)
            continue
        else:
            # Legacy parsing of BEE2.2 files..
            pal = parse_legacy(pos_file, prop_file, name)
            if pal is not None:
                pal_list.append(pal)
        finally:
            if pos_file:
                pos_file.close()
            if prop_file:
                prop_file.close()

        LOGGER.warning('"{}" is a legacy palette - resaving!', name)
        # Resave with the new format, then delete originals.
        if name.endswith('.zip'):
            pal.save()
            os.remove(path)
        else:
            # Folders can't be overwritten...
            pal.prevent_overwrite = True
            pal.save()
            shutil.rmtree(path)

    # Ensure the list has a defined order..
    pal_list.sort(key=str)
    return pal_list


def parse_legacy(posfile, propfile, path):
    """Parse the original BEE2.2 palette format."""
    props = Property.parse(propfile, path + ':properties.txt')
    name = props['name', 'Unnamed']
    pos = []
    for dirty_line in posfile:
        line = srctools.clean_line(dirty_line)
        if line:
            # Lines follow the form
            # "ITEM_BUTTON_FLOOR", 2
            # for subtype 3 of the button
            if line.startswith('"'):
                val = line.split('",')
                if len(val) == 2:
                    pos.append((
                        val[0][1:], # Item ID
                        int(val[1].strip()), # Item subtype
                        ))
                else:
                    LOGGER.warning('Malformed row "{}"!', line)
                    return None
    return Palette(name, pos)


def save_pal(items, name: str, include_settings: bool):
    """Save a palette under the specified name."""
    for pal in pal_list:
        if pal.name == name and not pal.prevent_overwrite:
            pal.pos = list(items)
            break
    else:
        pal = Palette(name, list(items))
        pal_list.append(pal)

    if include_settings:
        pal.settings = BEE2_config.get_curr_settings()
    else:
        pal.settings = None

    pal.save()
    return pal


def check_exists(name):
    """Check if a palette with the given name exists."""
    for pal in pal_list:
        if pal.name == name:
            return True
    return False


if __name__ == '__main__':
    results = load_palettes()
    for palette in results:
        print(palette)
