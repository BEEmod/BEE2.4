"""Defines the palette data structure and file saving/loading logic."""
from __future__ import annotations
from typing import IO, Dict, Tuple, cast

from collections.abc import Sequence, Iterator
from typing_extensions import TypeAliasType, TypeGuard, Literal, Final
from uuid import UUID, uuid4, uuid5
import os
import shutil
import zipfile
import random
import io

from srctools import Keyvalues, NoKeyError, KeyValError
import srctools.logger

from transtoken import TransToken
import config
import consts
import utils


LOGGER = srctools.logger.get_logger(__name__)
PAL_DIR = utils.conf_location('palettes/')
GROUP_BUILTIN: Final = '<BUILTIN>'
PAL_EXT: Final = '.bee2_palette'
CUR_VERSION: Final = 3

HorizInd = TypeAliasType("HorizInd", Literal[0, 1, 2, 3])
VertInd = TypeAliasType("VertInd", Literal[0, 1, 2, 3, 4, 5, 6, 7])
ItemPos = TypeAliasType("ItemPos", Dict[Tuple[HorizInd, VertInd], Tuple[str, int]])
HORIZ: Final[Sequence[HorizInd]] = cast(Sequence[HorizInd], range(4))
VERT: Final[Sequence[VertInd]] = cast(Sequence[VertInd], range(8))
COORDS: Sequence[Tuple[HorizInd, VertInd]] = [
    (x, y) for y in VERT for x in HORIZ
]

# Allow translating the names of the built-in palettes
TRANS_NAMES: dict[str, TransToken] = {
    # i18n: Last exported items
    'LAST_EXPORT': TransToken.ui('<Last Export>'),
    # i18n: Empty palette name
    'EMPTY': TransToken.ui('Blank'),

    # i18n: BEEmod 1 palette.
    'BEEMOD': TransToken.ui('BEEMod'),
    # i18n: Default items merged together
    'P2_COLLAPSED': TransToken.ui('Portal 2 Collapsed'),

    # i18n: Original Palette
    'PORTAL2': TransToken.ui('Portal 2'),
    # i18n: Aperture Tag's palette
    'APTAG': TransToken.ui('Aperture Tag'),
}

# The original palette, plus BEEmod 1 and Aperture Tag's palettes.
# Todo: Switch to DefaultItems/ObjectID here.
DEFAULT_PALETTES: dict[str, list[list[tuple[str, int]]]] = {
    'EMPTY': [],
    'PORTAL2': [
        [
            ("ITEM_BUTTON_PEDESTAL", 0),
            ("ITEM_BUTTON_FLOOR", 0),  # Weighted
            ("ITEM_BUTTON_FLOOR", 1),  # Cube
            ("ITEM_BUTTON_FLOOR", 2),  # Ball
        ], [
            ("ITEM_CUBE", 0),  # Standard
            ("ITEM_CUBE", 1),  # Companion
            ("ITEM_CUBE", 3),  # Sphere
            ("ITEM_CUBE", 4),  # Franken
        ], [
            ("ITEM_TBEAM", 0),
            ("ITEM_CATAPULT", 0),
            ("ITEM_LIGHT_BRIDGE", 0),
            ("ITEM_PANEL_STAIRS", 0),
        ], [
            ("ITEM_BARRIER_HAZARD", 0),  # Fizzler
            ("ITEM_BARRIER", 0),  # Glass
            ("ITEM_PISTON_PLATFORM", 0),
            ("ITEM_RAIL_PLATFORM", 0),
        ], [
            ("ITEM_LASER_EMITTER_CENTER", 0),
            ("ITEM_LASER_CATCHER_CENTER", 0),
            ("ITEM_LASER_RELAY_CENTER", 0),
            ("ITEM_CUBE", 2),  # Reflect
        ], [
            ("ITEM_PANEL_CLEAR", 0),
            ("ITEM_PANEL_ANGLED", 0),
            ("ITEM_PANEL_FLIP", 0),
            ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),
        ], [
            ("ITEM_BARRIER_HAZARD", 1),  # Laserfield
            ("ITEM_TURRET", 0),
            ("ITEM_GOO", 0),
            ("ITEM_LIGHT_PANEL", 0),  # Cold
        ], [
            ("ITEM_PAINT_SPLAT", 0),  # Bounce
            ("ITEM_PAINT_SPLAT", 1),  # Speed
            ("ITEM_PAINT_SPLAT", 2),  # Portal
            ("ITEM_PAINT_SPLAT", 3),  # Erase
        ]
    ],
    'BEEMOD': [
        [
            ("ITEM_BUTTON_PEDESTAL", 0),
            ("ITEM_BUTTON_FLOOR", 0),
            ("ITEM_CUBE", 0),
            ("ITEM_PAINT_SPLAT", 3),  # Erase
        ], [
            ("ITEM_TBEAM", 0),
            ("ITEM_CATAPULT", 0),
            ("ITEM_DRAW_BRIDGE", 0),
            ("ITEM_PANEL_STAIRS", 0),
        ], [
            ("ITEM_BARRIER_HAZARD", 0),
            ("ITEM_LIGHT_BRIDGE", 0),
            ("ITEM_PISTON_PLATFORM", 0),
            ("ITEM_RAIL_PLATFORM", 0),
        ], [
            ("ITEM_LASER_EMITTER_CENTER", 0),
            ("ITEM_LASER_CATCHER_CENTER", 0),
            ("ITEM_LASER_RELAY_CENTER", 0),
            ("ITEM_BARRIER", 0),
        ], [
            ("ITEM_PANEL_CLEAR", 0),
            ("ITEM_PANEL_ANGLED", 0),
            ("ITEM_PANEL_FLIP", 0),
            ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),
        ], [
            ("ITEM_GOO", 0),
            ("ITEM_TURRET", 0),
            ("ITEM_CRUSHER", 0),
            ("ITEM_VENT", 0),
        ], [
            ("ITEM_HIGH_ENERGY_PELLET_EMITTER", 0),
            ("ITEM_HIGH_ENERGY_PELLET_CATCHER", 0),
            ("DOOR", 0),
            ("ITEM_LIGHT_PANEL", 0),  # Cold
        ], [
            ("ITEM_TRIGGERS", 0),
            ("ITEM_BEE_LOGIC", 0),
            ("ITEM_AUTOPORTAL", 0),
            ("ITEM_LIGHT_PANEL", 1),  # Warm
        ],
    ],

    'P2_COLLAPSED': [
        [
            ("ITEM_BUTTON_PEDESTAL", 0),
            ("ITEM_BUTTON_FLOOR", 0),
            ("ITEM_CUBE", 0),
            ("ITEM_PAINT_SPLAT", 3),  # Erase
        ], [
            ("ITEM_TBEAM", 0),
            ("ITEM_CATAPULT", 0),
            ("ITEM_PANEL_STAIRS", 0),
            ("ITEM_LIGHT_PANEL", 0),
        ], [
            ("ITEM_BARRIER_HAZARD", 0),
            ("ITEM_LIGHT_BRIDGE", 0),
            ("ITEM_PISTON_PLATFORM", 0),
            ("ITEM_RAIL_PLATFORM", 0),
        ], [
            ("ITEM_LASER_EMITTER_CENTER", 0),
            ("ITEM_LASER_CATCHER_CENTER", 0),
            ("ITEM_LASER_RELAY_CENTER", 0),
            ("ITEM_BARRIER", 0),
        ], [
            ("ITEM_PANEL_CLEAR", 0),
            ("ITEM_PANEL_ANGLED", 0),
            ("ITEM_PANEL_FLIP", 0),
            ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),
        ], [
            ("ITEM_GOO", 0),
            ("ITEM_TURRET", 0),
        ],
    ],

    'APTAG': [
        [],  # Original has 4 paint fizzler items at the top.
        [
            ("ITEM_BUTTON_PEDESTAL", 0),
            ("ITEM_BUTTON_FLOOR", 0),
            ("ITEM_CUBE", 0),
            ("ITEM_PAINT_SPLAT", 3),  # Erase
        ], [
            ("ITEM_TBEAM", 0),
            ("ITEM_CATAPULT", 0),
            ("ITEM_DRAW_BRIDGE", 0),
            ("ITEM_PANEL_STAIRS", 0),
        ], [
            ("ITEM_BARRIER_HAZARD", 0),
            ("ITEM_LIGHT_BRIDGE", 0),
            ("ITEM_PISTON_PLATFORM", 0),
            ("ITEM_RAIL_PLATFORM", 0),
        ], [
            ("ITEM_LASER_EMITTER_CENTER", 0),
            ("ITEM_LASER_CATCHER_CENTER", 0),
            ("ITEM_LASER_RELAY_CENTER", 0),
            ("ITEM_BARRIER", 0),
        ], [
            ("ITEM_PANEL_CLEAR", 0),
            ("ITEM_PANEL_ANGLED", 0),
            ("ITEM_PANEL_FLIP", 0),
            ("ITEM_SECONDARY_OBSERVATION_ROOM", 0),
        ], [
            ("ITEM_GOO", 0),
            ("ITEM_TURRET", 0),
            ("ITEM_CRUSHER", 0),
            ("ITEM_VENT", 0),
        ], [
            ("ITEM_HIGH_ENERGY_PELLET_EMITTER", 0),
            ("ITEM_HIGH_ENERGY_PELLET_CATCHER", 0),
            ("DOOR", 0),
            ("ITEM_LIGHT_PANEL", 0),  # Cold
        ], [
            ("ITEM_TRIGGERS", 0),
            ("ITEM_BEE_LOGIC", 0),
            ("ITEM_AUTOPORTAL", 0),
            ("ITEM_TAG_GUN_ACTIVATOR", 0),
        ],
    ]
}


def validate_x(x: int) -> TypeGuard[HorizInd]:
    """Validate that this is a valid horizontal coordinate."""
    return x in HORIZ


def validate_y(y: int) -> TypeGuard[VertInd]:
    """Validate that this is a valid vertical coordinate."""
    return y in VERT


class FutureVersionError(Exception):
    """Raised if a palette is from a future version."""
    def __init__(self, version: int) -> None:
        super().__init__(f'Unknown version {version}!')
        self.version = version


class Palette:
    """A palette, saving an arrangement of items for editoritems.txt"""
    def __init__(
        self,
        name: str,
        items: ItemPos,
        trans_name: str = '',
        readonly: bool = False,
        group: str = '',
        filename: str | None = None,
        settings: config.Config | None = None,
        uuid: UUID | None = None,
    ) -> None:
        # Name of the palette
        self.trans_name = trans_name
        if trans_name:
            try:
                self.name = TRANS_NAMES[trans_name.upper()]
            except KeyError:
                LOGGER.warning('Unknown translated palette "{}', trans_name)
        else:
            self.name = TransToken.untranslated(name)

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
        # x/y -> item, subtype tuple.
        self.items = items
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
    def parse(cls, kv: Keyvalues, path: str) -> tuple[Palette, bool]:
        """Parse a palette from a file.

        The returned boolean indicates if it should be resaved.
        """
        needs_upgrade = False
        version = kv.int('version', 1)
        name = kv['Name', '??']

        items: ItemPos = {}

        # v2 reused the Items key, v3 restores a copy of the old block for backward compat.
        if version in (2, 3):
            for item_prop in kv.find_children('Positions' if version == 3 else 'Items'):
                try:
                    x_str, y_str = item_prop.name.split()
                    x = int(x_str)
                    y = int(y_str)
                    if not validate_x(x) or not validate_y(y):
                        raise ValueError
                except ValueError:
                    LOGGER.warning('Invalid position {} in palette "{}"!', item_prop.name, path)
                    continue
                try:
                    item_id = item_prop['id']
                except LookupError:
                    LOGGER.warning('No item in position ({}, {})', x, y)
                    continue
                items[x, y] = (item_id, item_prop.int('subtype', 0))

        elif version == 1:
            for pos, item in zip(COORDS, kv.find_children('Items')):
                items[pos] = (item.real_name, int(item.value))
        elif version < 1:
            raise ValueError(f'Invalid version {version}!')
        else:
            raise FutureVersionError(version)

        if version != CUR_VERSION:
            needs_upgrade = True

        trans_name = kv['TransName', '']
        if trans_name:
            # Builtin, force a fixed uuid. This is mainly for LAST_EXPORT.
            uuid = uuid5(consts.PALETTE_NS, trans_name)
        else:
            try:
                uuid = UUID(hex=kv['UUID'])
            except (ValueError, LookupError):
                uuid = uuid4()
                needs_upgrade = True

        settings: config.Config | None
        try:
            settings_conf = kv.find_key('Settings')
        except NoKeyError:
            settings = None
        else:
            settings, upgraded_settings = config.PALETTE.parse_kv1(settings_conf)
            if upgraded_settings:
                needs_upgrade = True

        pal = Palette(
            name,
            items,
            trans_name=trans_name,
            group=kv['group', ''],
            readonly=kv.bool('readonly'),
            filename=os.path.basename(path),
            uuid=uuid,
            settings=settings,
        )
        return pal, needs_upgrade

    def save(self, ignore_readonly: bool = False) -> None:
        """Save the palette file into the specified location.

        If ignore_readonly is true, this will ignore the `readonly`
        property of the palette (allowing resaving those properties over old
        versions). Otherwise, those palettes always create a new file.
        """
        LOGGER.info('Saving "{}"!', self.name)
        item_kv = Keyvalues('Positions', [])
        # Still support v1 app, by writing them out as the original block.
        legacy_kv = Keyvalues('Items', [])
        kv = Keyvalues.root(
            Keyvalues('Name', 'name'),
            Keyvalues('Version', str(CUR_VERSION)),
            Keyvalues('TransName', 'trans_name'),
            Keyvalues('Group', self.group),
            Keyvalues('ReadOnly', srctools.bool_as_int(self.readonly)),
            Keyvalues('UUID', self.uuid.hex),
            item_kv,
            legacy_kv,
        )
        for (x, y) in COORDS:
            try:
                item_id, subtype = self.items[x, y]
            except KeyError:
                pass
            else:
                item_kv.append(Keyvalues(f'{x} {y}', [
                    Keyvalues('id', item_id),
                    Keyvalues('subtype', str(subtype)),
                ]))
                legacy_kv.append(Keyvalues(item_id, str(subtype)))

        # If defaulted, don't include in the palette file.
        # Remove the translated name, in case it's not going to write
        # properly to the file.
        if self.trans_name:
            kv['TransName'] = self.trans_name
            kv['Name'] = ''
        else:
            kv['Name'] = self.name.token
            del kv['TransName']

        if self.settings is not None:
            settings_prop = Keyvalues('settings', [])
            settings_prop.extend(config.PALETTE.build_kv1(self.settings))
            kv.append(settings_prop)

        # We need to write a new file, determine a valid path.
        # Use a hash to ensure it's a valid path (without '-' if negative)
        # If a conflict occurs, add ' ' and hash again to get a different
        # value.
        if self.filename is None or (self.readonly and not ignore_readonly):
            hash_src = self.name.token
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
            for line in kv.export():
                file.write(line)

    def delete_from_disk(self) -> None:
        """Delete this palette from disk."""
        if self.filename is not None:
            os.remove(os.path.join(PAL_DIR, self.filename))


def load_palettes() -> Iterator[Palette]:
    """Scan and read in all palettes. Legacy files will be converted in the process."""
    name: str
    # Load our builtin palettes.
    for name, items in DEFAULT_PALETTES.items():
        LOGGER.info('Loading builtin "{}"', name)
        yield Palette(
            name,
            {
                (x, y): item
                for y, row in enumerate(items)
                for x, item in enumerate(row)
                if validate_x(x) and validate_y(y)
            },
            name,
            readonly=True,
            group=GROUP_BUILTIN,
            uuid=uuid5(consts.PALETTE_NS, name),
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
                        with open(path, encoding='utf8') as f:
                            kv = Keyvalues.parse(f, path)
                        pal, needs_upgrade = Palette.parse(kv, path)
                except KeyValError as exc:
                    # We don't need the traceback, this isn't an error in the app
                    # itself.
                    LOGGER.warning('Could not parse palette file, skipping:\n{}', exc)
                except FutureVersionError as fut:
                    LOGGER.warning('Palette file "{}" using future version {}, skipping...',  name, fut.version)
                else:
                    if needs_upgrade:
                        LOGGER.info('Resaving older palette file {}', pal.filename)
                        pal.save(ignore_readonly=True)
                    yield pal
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
        except (KeyError, FileNotFoundError, zipfile.BadZipFile) as exc:
            #  KeyError is returned by zipFile.open() if file is not present
            LOGGER.warning('Bad palette file "{}"!', name, exc_info=exc)
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


def parse_legacy(posfile: IO[str], propfile: IO[str], path: str) -> Palette | None:
    """Parse the original BEE2.2 palette format."""
    kv = Keyvalues.parse(propfile, path + ':properties.txt')
    name = kv['name', 'Unnamed']
    pos: ItemPos = {}
    coords = iter(COORDS)
    for dirty_line in posfile:
        line = srctools.clean_line(dirty_line)
        if line:
            # Lines follow the form
            # "ITEM_BUTTON_FLOOR", 2
            # for subtype 3 of the button
            if line.startswith('"'):
                val = line.split('",')
                if len(val) == 2:
                    item_id = val[0][1:]
                    subtype = int(val[1])
                    try:
                        pos[next(coords)] = (item_id, subtype)
                    except StopIteration:
                        LOGGER.warning('Too many items!')
                else:
                    LOGGER.warning('Malformed row "{}"!', line)
                    return None
    return Palette(name, pos)

if __name__ == '__main__':
    results = load_palettes()
    for palette in results:
        print(palette)
