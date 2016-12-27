import os.path
import shutil
import zipfile
import random

import utils
import srctools
from srctools import Property

from typing import List, Tuple


LOGGER = utils.getLogger(__name__)

PAL_DIR = "palettes\\"

PAL_EXT = '.bee2_palette'

pal_list = []  # type: List[Palette]

class Palette:
    """A palette, saving an arrangement of items for editoritems.txt"""
    def __init__(self, name, pos: List[Tuple[str, int]], options=None):
        self.opt = {} if options is None else options
        # Name of the palette
        self.name = name
        # If loaded from a file, the path to use.
        # None determines a filename from PAL_DIR
        self.filename = None  # type: Optional[str]
        # List of id, index tuples.
        self.pos = pos
        # If true, prevent overwriting the original file
        # (premade palettes or <LAST EXPORT>)
        self.prevent_overwrite = False

    def __str__(self):
        return self.name


    @classmethod
    def parse(cls, path: str):
        with open(path) as f:
            props = Property.parse(f, path)
        name = props['Name']
        items = []
        for item in props.find_children('Items'):
            items.append((item.real_name, int(item.value)))

        pal = Palette(name, items)
        pal.prevent_overwrite = props.bool('readonly')
        pal.filename = path
        return pal

    def save(self):
        """Save the palette file into the specified location."""
        LOGGER.info('Saving "{}"!', self.name)
        props = Property(None, [
            Property('Name', self.name),
            Property('ReadOnly', srctools.bool_as_int(self.prevent_overwrite)),
            Property('Items', [
                Property(item_id, str(subitem))
                for item_id, subitem in self.pos
            ])
        ])

        # Determine a valid path.
        # Use a hash to ensure it's a valid path (without '-' if negative)
        # If a conflict occurs, add ' ' and hash again to get a different
        # value.
        if self.filename is None or self.prevent_overwrite:
            hash_src = self.name
            while True:
                hash_filename = os.path.join(
                    PAL_DIR,
                    str(abs(hash(hash_src))) + PAL_EXT
                )
                if os.path.isfile(hash_filename):
                    # Add a random character to iterate the hash.
                    hash_src += chr(random.randrange(0x10ffff))
                else:
                    file = open(hash_filename, 'w')
                    self.filename = hash_filename
                    break
        else:
            file = open(self.filename, 'w')
        with file:
            for line in props.export():
                file.write(line)

    def delete_from_disk(self, name=None):
        """Delete this palette from disk."""
        if name is None:
            name = self.filename
        is_zip = name.endswith('.zip')
        path = os.path.join(PAL_DIR, name)
        if is_zip:
            os.remove(path)
        else:
            shutil.rmtree(path)


def load_palettes(pal_dir):
    """Scan and read in all palettes in the specified directory."""
    global PAL_DIR
    PAL_DIR = os.path.abspath(os.path.join('..', pal_dir))
    full_dir = os.path.join(os.getcwd(), PAL_DIR)

    for name in os.listdir(full_dir):  # this is both files and dirs
        LOGGER.info('Loading "{}"', name)
        path = os.path.join(full_dir, name)
        pos_file, prop_file = None, None
        try:
            if name.endswith(PAL_EXT):
                pal_list.append(Palette.parse(path))
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

    return pal_list


def parse_legacy(posfile, propfile, path):
    """Parse the original BEE2.2 palette format."""
    props = Property.parse(propfile, path + ':properties.txt')
    name = "Unnamed"
    opts = {}
    for option in props:
        if option.name == "name":
            name = option.value
        else:
            opts[option.name.casefold()] = option.value
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
    return Palette(name, pos, opts)


def save_pal(items, name):
    """Save a palette under the specified name."""
    for pal in pal_list:
        if pal.name == name and not pal.prevent_overwrite:
            pal.pos = list(items)
            break
    else:
        pal = Palette(name, list(items))
        pal_list.append(pal)

    pal.save()
    return pal


def check_exists(name):
    """Check if a palette with the given name exists."""
    for pal in pal_list:
        if pal.name == name:
            return True
    return False


if __name__ == '__main__':
    results = load_palettes('palettes\\')
    for palette in results:
        print(palette)
