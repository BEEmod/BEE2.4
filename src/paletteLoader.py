import os
import os.path
import io
import zipfile
import shutil

from property_parser import Property
import utils

LOGGER = utils.getLogger(__name__)

PAL_DIR = "palettes\\"

pal_list = []

class Palette:
    """A palette, saving an arrangement of items for editoritems.txt"""
    def __init__(self, name, pos, options=None, filename=None):
        self.opt = {} if options is None else options
        self.name = name
        self.filename = name if filename is None else filename
        self.pos = pos

    def __str__(self):
        return self.name

    def save(self, allow_overwrite, name=None):
        """Save the palette file into the specified location."""
        LOGGER.info('Saving "' + self.name + '"!')
        if name is None:
            name = self.filename
        is_zip = name.endswith('.zip')
        path = os.path.join(PAL_DIR, name)
        if not allow_overwrite:
            if os.path.isdir(path) or os.path.isfile(path):
                LOGGER.warning('"' + name + '" exists already!')
                return False
        try:
            if is_zip:
                pos_file = io.StringIO()
                prop_file = io.StringIO()
            else:
                if not os.path.isdir(path):
                    os.mkdir(path)
                pos_file = open(os.path.join(path, 'positions.txt'), 'w')
                prop_file = open(os.path.join(path, 'properties.txt'), 'w')

            for ind, (item_id, item_sub) in enumerate(self.pos):
                if ind % 4 == 0:
                    if ind != 0:
                        pos_file.write('\n') # Don't start the file with a newline
                    pos_file.write("//Row " + str(ind//4) + '\n')
                pos_file.write('"' + item_id + '", ' + str(item_sub) + '\n')

            prop_file.write('"Name" "' + self.name + '"\n')
            for opt, val in self.opt.items():
                prop_file.write('"' + opt + '" "' + val + '"\n')

            if is_zip:
                with zipfile.ZipFile(path, 'w') as zip_file:
                    zip_file.writestr('properties.txt', prop_file.getvalue())
                    zip_file.writestr('positions.txt', pos_file.getvalue())
        finally:
            pos_file.close()
            prop_file.close()

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
    "Scan and read in all palettes in the specified directory."
    global PAL_DIR, pal_list
    PAL_DIR = os.path.abspath(os.path.join('..', pal_dir))
    full_dir = os.path.join(os.getcwd(), PAL_DIR)
    contents = os.listdir(full_dir)  # this is both files and dirs

    pal_list = []
    for name in contents:
        LOGGER.info('Loading "{}"', name)
        path = os.path.join(full_dir, name)
        pos_file, prop_file = None, None
        try:
            if name.endswith('.zip'):
                # Extract from a zip
                with zipfile.ZipFile(path, ) as zip_file:
                    pos_file = zip_file.open('positions.txt')
                    prop_file = zip_file.open('properties.txt')
            elif os.path.isdir(path):
                # Open from the subfolder
                pos_file = open(os.path.join(path, 'positions.txt'))
                prop_file = open(os.path.join(path, 'properties.txt'))
            else: # A non-palette file, skip it.
                LOGGER.debug('Skipping "{}"', name)
                continue
        except (KeyError, FileNotFoundError, zipfile.BadZipFile):
            #  KeyError is returned by zipFile.open() if file is not present
            LOGGER.warning('Bad palette file "{}"!', name)
        else:
            pal = parse(pos_file, prop_file, name)
            if pal is not None:
                pal_list.append(pal)
        finally:
            if pos_file:
                pos_file.close()
            if prop_file:
                prop_file.close()
    return pal_list


def parse(posfile, propfile, path):
    "Parse through the given palette file to get all data."
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
        line = utils.clean_line(dirty_line)
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
    return Palette(name, pos, opts, filename=path)


def save_pal(items, name):
    """Save a palette under the specified name."""
    pos = [(it.id, it.subKey) for it in items]
    LOGGER.debug(name, pos, name, [])
    new_palette = Palette(name, pos)

    for pal in pal_list[:]:
        if pal.name == name:
            pal_list.remove(name)
    pal_list.append(new_palette)
    return new_palette.save(allow_overwrite=False)

if __name__ == '__main__':
    results = load_palettes('palettes\\')
    for palette in results:
        print(palette)
