"""Defines the palette data structure and file saving/loading logic."""
from __future__ import annotations
from typing import IO, Iterator
import os
import shutil
import zipfile
import random
import io
from uuid import UUID, uuid4, uuid5


import srctools.logger
from srctools import Property, NoKeyError, KeyValError

from localisation import gettext
from app import config
import utils


LOGGER = srctools.logger.get_logger(__name__)
PAL_DIR = utils.conf_location('palettes/')
GROUP_BUILTIN = '<BUILTIN>'
PAL_EXT = '.bee2_palette'

# Allow translating the names of the built-in palettes
TRANS_NAMES: dict[str, str] = {
    # i18n: Last exported items
    'LAST_EXPORT': gettext('<Last Export>'),
    # i18n: Empty palette name
    'EMPTY': gettext('Blank'),

    # i18n: BEEmod 1 palette.
    'BEEMOD': gettext('BEEMod'),
    # i18n: Default items merged together
    'P2_COLLAPSED': gettext('Portal 2 Collapsed'),

    # i18n: Original Palette
    'PORTAL2': gettext('Portal 2'),
    # i18n: Aperture Tag's palette
    'APTAG': gettext('Aperture Tag'),
}
DEFAULT_NS = UUID('91001b81-60ee-494d-9d2a-6371397b2240')
UUID_PORTAL2 = uuid5(DEFAULT_NS, 'PORTAL2')
UUID_EXPORT = uuid5(DEFAULT_NS, 'LAST_EXPORT')
UUID_BLANK = uuid5(DEFAULT_NS, 'EMPTY')

# The original palette, plus BEEmod 1 and Aperture Tag's palettes.
DEFAULT_PALETTES: dict[str, list[tuple[str, int]]] = {
    'EMPTY': [],
    'PORTAL2': [
        ("ITEM_BUTTON_PEDESTAL", 0),
        ("ITEM_BUTTON_FLOOR", 0),  # Weighted
        ("ITEM_BUTTON_FLOOR", 1),  # Cube
        ("ITEM_BUTTON_FLOOR", 2),  # Ball

        ("ITEM_CUBE", 0),  # Standard
        ("ITEM_CUBE", 1),  # Companion
        ("ITEM_CUBE", 3),  # Sphere
        ("ITEM_CUBE", 4),  # Franken

        ("ITEM_TBEAM", 0),
        ("ITEM_CATAPULT", 0),
        ("ITEM_LIGHT_BRIDGE", 0),
        ("ITEM_PANEL_STAIRS", 0),

        ("ITEM_BARRIER_HAZARD", 0),  # Fizzler
        ("ITEM_BARRIER", 0),  # Glass
        ("ITEM_PISTON_PLATFORM", 0),
        ("ITEM_RAIL_PLATFORM", 0),

        ("ITEM_LASER_EMITTER_CENTER", 0),
        ("ITEM_LASER_CATCHER_CENTER", 0),
        ("ITEM_LASER_RELAY_CENTER", 0),
        ("ITEM_CUBE", 2),  # Reflect

        ("ITEM_PANEL_CLEAR", 0),
        ("ITEM_PANEL_ANGLED", 0),
        ("ITEM_PANEL_FLIP", 0),
        ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),

        ("ITEM_BARRIER_HAZARD", 1),  # Laserfield
        ("ITEM_TURRET", 0),
        ("ITEM_GOO", 0),
        ("ITEM_LIGHT_PANEL", 0),  # Cold

        ("ITEM_PAINT_SPLAT", 0),  # Bounce
        ("ITEM_PAINT_SPLAT", 1),  # Speed
        ("ITEM_PAINT_SPLAT", 2),  # Portal
        ("ITEM_PAINT_SPLAT", 3),  # Erase
    ],
    'BEEMOD': [
        ("ITEM_BUTTON_PEDESTAL", 0),
        ("ITEM_BUTTON_FLOOR", 0),
        ("ITEM_CUBE", 0),
        ("ITEM_PAINT_SPLAT", 3),  # Erase

        ("ITEM_TBEAM", 0),
        ("ITEM_CATAPULT", 0),
        ("ITEM_DRAW_BRIDGE", 0),
        ("ITEM_PANEL_STAIRS", 0),

        ("ITEM_BARRIER_HAZARD", 0),
        ("ITEM_LIGHT_BRIDGE", 0),
        ("ITEM_PISTON_PLATFORM", 0),
        ("ITEM_RAIL_PLATFORM", 0),

        ("ITEM_LASER_EMITTER_CENTER", 0),
        ("ITEM_LASER_CATCHER_CENTER", 0),
        ("ITEM_LASER_RELAY_CENTER", 0),
        ("ITEM_BARRIER", 0),

        ("ITEM_PANEL_CLEAR", 0),
        ("ITEM_PANEL_ANGLED", 0),
        ("ITEM_PANEL_FLIP", 0),
        ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),

        ("ITEM_GOO", 0),
        ("ITEM_TURRET", 0),
        ("ITEM_CRUSHER", 0),
        ("ITEM_VENT", 0),

        ("ITEM_HIGH_ENERGY_PELLET_EMITTER", 0),
        ("ITEM_HIGH_ENERGY_PELLET_CATCHER", 0),
        ("DOOR", 0),
        ("ITEM_LIGHT_PANEL", 0),  # Cold

        ("ITEM_TRIGGERS", 0),
        ("ITEM_BEE_LOGIC", 0),
        ("ITEM_AUTOPORTAL", 0),
        ("ITEM_LIGHT_PANEL", 1),  # Warm
    ],

    'P2_COLLAPSED': [
        ("ITEM_BUTTON_PEDESTAL", 0),
        ("ITEM_BUTTON_FLOOR", 0),
        ("ITEM_CUBE", 0),
        ("ITEM_PAINT_SPLAT", 3),  # Erase
        ("ITEM_TBEAM", 0),
        ("ITEM_CATAPULT", 0),
        ("ITEM_PANEL_STAIRS", 0),
        ("ITEM_LIGHT_PANEL", 0),
        ("ITEM_BARRIER_HAZARD", 0),
        ("ITEM_LIGHT_BRIDGE", 0),
        ("ITEM_PISTON_PLATFORM", 0),
        ("ITEM_RAIL_PLATFORM", 0),
        ("ITEM_LASER_EMITTER_CENTER", 0),
        ("ITEM_LASER_CATCHER_CENTER", 0),
        ("ITEM_LASER_RELAY_CENTER", 0),
        ("ITEM_BARRIER", 0),
        ("ITEM_PANEL_CLEAR", 0),
        ("ITEM_PANEL_ANGLED", 0),
        ("ITEM_PANEL_FLIP", 0),
        ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),
        ("ITEM_GOO", 0),
        ("ITEM_TURRET", 0),
    ],

    'APTAG': [
        # Original has 4 paint fizzler items at the top.

        ("ITEM_BUTTON_PEDESTAL", 0),
        ("ITEM_BUTTON_FLOOR", 0),
        ("ITEM_CUBE", 0),
        ("ITEM_PAINT_SPLAT", 3),  # Erase

        ("ITEM_TBEAM", 0),
        ("ITEM_CATAPULT", 0),
        ("ITEM_DRAW_BRIDGE", 0),
        ("ITEM_PANEL_STAIRS", 0),

        ("ITEM_BARRIER_HAZARD", 0),
        ("ITEM_LIGHT_BRIDGE", 0),
        ("ITEM_PISTON_PLATFORM", 0),
        ("ITEM_RAIL_PLATFORM", 0),

        ("ITEM_LASER_EMITTER_CENTER", 0),
        ("ITEM_LASER_CATCHER_CENTER", 0),
        ("ITEM_LASER_RELAY_CENTER", 0),
        ("ITEM_BARRIER", 0),

        ("ITEM_PANEL_CLEAR", 0),
        ("ITEM_PANEL_ANGLED", 0),
        ("ITEM_PANEL_FLIP", 0),
        ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),

        ("ITEM_GOO", 0),
        ("ITEM_TURRET", 0),
        ("ITEM_CRUSHER", 0),
        ("ITEM_VENT", 0),

        ("ITEM_HIGH_ENERGY_PELLET_EMITTER", 0),
        ("ITEM_HIGH_ENERGY_PELLET_CATCHER", 0),
        ("DOOR", 0),
        ("ITEM_LIGHT_PANEL", 0),  # Cold

        ("ITEM_TRIGGERS", 0),
        ("ITEM_BEE_LOGIC", 0),
        ("ITEM_AUTOPORTAL", 0),
        ("ITEM_TAG_GUN_ACTIVATOR", 0),
    ]
}


class Palette:
    """A palette, saving an arrangement of items for editoritems.txt"""
    def __init__(
        self,
        name: str,
        pos: list[tuple[str, int]],
        trans_name: str = '',
        readonly: bool = False,
        group: str = '',
        filename: str = None,
        settings: config.Config | None = None,
        uuid: UUID = None,
    ) -> None:
        # Name of the palette
        self.name = name
        self.trans_name = trans_name
        if trans_name:
            try:
                self.name = TRANS_NAMES[trans_name.upper()]
            except KeyError:
                LOGGER.warning('Unknown translated palette "{}', trans_name)

        # Group to show the palette in.
        self.group = group

        # ID unique to this palette.
        if uuid is not None:
            self.uuid = uuid
        else:
            self.uuid = uuid4()

        # If loaded from a file, the path to use.
        # None determines a filename automatically.
        self.filename = filename
        # List of id, index tuples.
        self.pos = pos
        # If true, prevent overwriting the original file
        # (premade palettes or <LAST EXPORT>)
        self.readonly = readonly
        if readonly:
            self.group = GROUP_BUILTIN

        # If not None, settings associated with the palette.
        self.settings = settings

    def __repr__(self) -> str:
        return f'<Palette {self.name!r} @ {self.uuid}>'

    @classmethod
    def parse(cls, path: str) -> Palette:
        """Parse a palette from a file."""
        needs_save = False
        with open(path, encoding='utf8') as f:
            props = Property.parse(f, path)
        name = props['Name', '??']
        items = []
        for item in props.find_children('Items'):
            items.append((item.real_name, int(item.value)))

        trans_name = props['TransName', '']
        if trans_name:
            # Builtin, force a fixed uuid. This is mainly for LAST_EXPORT.
            uuid = uuid5(DEFAULT_NS, trans_name)
        else:
            try:
                uuid = UUID(hex=props['UUID'])
            except (ValueError, LookupError):
                uuid = uuid4()
                needs_save = True

        settings: config.Config | None
        try:
            settings_conf = props.find_key('Settings')
        except NoKeyError:
            settings = None
        else:
            settings, upgraded_settings = config.parse_conf(settings_conf)
            if upgraded_settings:
                needs_save = True

        pal = Palette(
            name,
            items,
            trans_name=trans_name,
            group=props['group', ''],
            readonly=props.bool('readonly'),
            filename=os.path.basename(path),
            uuid=uuid,
            settings=settings,
        )
        if needs_save:
            LOGGER.info('Resaving older palette file {}', pal.filename)
            pal.save()
        return pal

    def save(self, ignore_readonly: bool = False) -> None:
        """Save the palette file into the specified location.

        If ignore_readonly is true, this will ignore the `readonly`
        property of the palette (allowing resaving those properties over old
        versions). Otherwise those palettes always create a new file.
        """
        LOGGER.info('Saving "{}"!', self.name)
        props = Property.root(
            Property('Name', self.name),
            Property('TransName', self.trans_name),
            Property('Group', self.group),
            Property('ReadOnly', srctools.bool_as_int(self.readonly)),
            Property('UUID', self.uuid.hex),
            Property('Items', [
                Property(item_id, str(subitem))
                for item_id, subitem in self.pos
            ])
        )
        # If default, don't include in the palette file.
        # Remove the translated name, in case it's not going to write
        # properly to the file.
        if self.trans_name:
            props['Name'] = ''
        else:
            del props['TransName']

        if self.settings is not None:
            settings_prop = Property('settings', [])
            settings_prop.extend(config.build_conf(self.settings))
            props.append(settings_prop)

        # We need to write a new file, determine a valid path.
        # Use a hash to ensure it's a valid path (without '-' if negative)
        # If a conflict occurs, add ' ' and hash again to get a different
        # value.
        if self.filename is None or (self.readonly and not ignore_readonly):
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

    def delete_from_disk(self) -> None:
        """Delete this palette from disk."""
        if self.filename is not None:
            os.remove(os.path.join(PAL_DIR, self.filename))


def load_palettes() -> Iterator[Palette]:
    """Scan and read in all palettes. Legacy files will be converted in the process."""

    # Load our builtin palettes.
    for name, items in DEFAULT_PALETTES.items():
        LOGGER.info('Loading builtin "{}"', name)
        yield Palette(
            name,
            items,
            name,
            readonly=True,
            group=GROUP_BUILTIN,
            uuid=uuid5(DEFAULT_NS, name),
        )

    for name in os.listdir(PAL_DIR):  # this is both files and dirs
        LOGGER.info('Loading "{}"', name)
        path = os.path.join(PAL_DIR, name)

        pos_file: IO[str] | None = None
        prop_file: IO[str] | None = None
        try:
            if name.endswith(PAL_EXT):
                try:
                    with srctools.logger.context(name):
                        yield Palette.parse(path)
                except KeyValError as exc:
                    # We don't need the traceback, this isn't an error in the app
                    # itself.
                    LOGGER.warning('Could not parse palette file, skipping:\n{}', exc)
                continue
            elif name.endswith('.zip'):
                # Extract from a zip
                with zipfile.ZipFile(path) as zip_file:
                    pos_file = io.TextIOWrapper(zip_file.open('positions.txt'), encoding='ascii', errors='ignore')
                    prop_file = io.TextIOWrapper(zip_file.open('properties.txt'), encoding='ascii', errors='ignore')
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
                yield pal
            else:
                continue
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
            pal.readonly = True
            pal.save()
            shutil.rmtree(path)


def parse_legacy(posfile, propfile, path) -> Palette | None:
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
                        val[0][1:],  # Item ID
                        int(val[1].strip()),  # Item subtype
                        ))
                else:
                    LOGGER.warning('Malformed row "{}"!', line)
                    return None
    return Palette(name, pos)

if __name__ == '__main__':
    results = load_palettes()
    for palette in results:
        print(palette)
