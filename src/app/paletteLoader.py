"""Defines the palette data structure and file saving/loading logic."""
from __future__ import annotations
from typing import IO, TypeGuard, Literal, Final, cast

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4, uuid5
import os
import shutil
import zipfile
import random
import io

from srctools import Keyvalues, NoKeyError, KeyValError
import srctools.logger

from transtoken import TransToken
from consts import DefaultItems
import config
import consts
import utils


LOGGER = srctools.logger.get_logger(__name__)
PAL_DIR = utils.conf_location('palettes/')
GROUP_BUILTIN: Final = '<BUILTIN>'
PAL_EXT: Final = '.bee2_palette'
CUR_VERSION: Final = 3

type HorizInd = Literal[0, 1, 2, 3]
type VertInd = Literal[0, 1, 2, 3, 4, 5, 6, 7]
type Coord = tuple[HorizInd, VertInd]
# TODO: Switch item ID here to ObjectID
type ItemPos = dict[Coord, tuple[str, int]]
type BuiltinPal = list[list[
    tuple[DefaultItems | utils.ObjectID, int],
]]
HORIZ: Final[Sequence[HorizInd]] = cast(Sequence[HorizInd], range(4))
VERT: Final[Sequence[VertInd]] = cast(Sequence[VertInd], range(8))
COORDS: Sequence[Coord] = [(x, y) for y in VERT for x in HORIZ]

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
DEFAULT_PALETTES: dict[str, BuiltinPal] = {
    'EMPTY': [],
    'PORTAL2': [
        [
            (DefaultItems.button_pedestal, 0),
            (DefaultItems.button_floor, 0),  # Weighted
            (DefaultItems.button_floor, 1),  # Cube
            (DefaultItems.button_floor, 2),  # Ball
        ], [
            (DefaultItems.cube, 0),  # Standard
            (DefaultItems.cube, 1),  # Companion
            (DefaultItems.cube, 3),  # Sphere
            (DefaultItems.cube, 4),  # Franken
        ], [
            (DefaultItems.funnel, 0),
            (DefaultItems.faith_plate, 0),
            (DefaultItems.light_bridge, 0),
            (DefaultItems.panel_stairs, 0),
        ], [
            (DefaultItems.fizzler, 0),  # Fizzler
            (DefaultItems.glass, 0),
            (DefaultItems.piston_platform, 0),
            (DefaultItems.track_platform, 0),
        ], [
            (DefaultItems.laser_emitter_center, 0),
            (DefaultItems.laser_catcher_center, 0),
            (DefaultItems.laser_relay_center, 0),
            (DefaultItems.cube, 2),  # Reflect
        ], [
            (DefaultItems.panel_glass, 0),
            (DefaultItems.panel_angled, 0),
            (DefaultItems.panel_flip, 0),
            (DefaultItems.obs_room_small, 0),
        ], [
            (DefaultItems.fizzler, 1),  # Laserfield
            (DefaultItems.turret, 0),
            (DefaultItems.goo, 0),
            (DefaultItems.light_strip, 0),  # Cold
        ], [
            (DefaultItems.gel_splat, 0),  # Bounce
            (DefaultItems.gel_splat, 1),  # Speed
            (DefaultItems.gel_splat, 2),  # Portal
            (DefaultItems.gel_splat, 3),  # Erase
        ]
    ],
    'BEEMOD': [
        [
            (DefaultItems.button_pedestal, 0),
            (DefaultItems.button_floor, 0),
            (DefaultItems.cube, 0),
            (DefaultItems.gel_splat, 3),  # Erase
        ], [
            (DefaultItems.funnel, 0),
            (DefaultItems.faith_plate, 0),
            (utils.obj_id("ITEM_DRAW_BRIDGE"), 0),
            (DefaultItems.panel_stairs, 0),
        ], [
            (DefaultItems.fizzler, 0),  # Fizzler
            (DefaultItems.light_bridge, 0),
            (DefaultItems.piston_platform, 0),
            (DefaultItems.track_platform, 0),
        ], [
            (DefaultItems.laser_emitter_center, 0),
            (DefaultItems.laser_catcher_center, 0),
            (DefaultItems.laser_relay_center, 0),
            (DefaultItems.glass, 0),
        ], [
            (DefaultItems.panel_glass, 0),
            (DefaultItems.panel_angled, 0),
            (DefaultItems.panel_flip, 0),
            (DefaultItems.obs_room_small, 0),
        ], [
            (DefaultItems.goo, 0),
            (DefaultItems.turret, 0),
            (utils.obj_id("ITEM_CRUSHER"), 0),
            (utils.obj_id("ITEM_VENT"), 0),
        ], [
            (utils.obj_id("ITEM_HIGH_ENERGY_PELLET_EMITTER"), 0),
            (utils.obj_id("ITEM_HIGH_ENERGY_PELLET_CATCHER"), 0),
            (utils.obj_id("DOOR"), 0),
            (DefaultItems.light_strip, 0),  # Cold
        ], [
            (utils.obj_id("ITEM_TRIGGERS"), 0),
            (utils.obj_id("ITEM_BEE_LOGIC"), 0),
            (utils.obj_id("ITEM_AUTOPORTAL"), 0),
            (DefaultItems.light_strip, 1),  # Warm
        ],
    ],

    'P2_COLLAPSED': [
        [
            (DefaultItems.button_pedestal, 0),
            (DefaultItems.button_floor, 0),
            (DefaultItems.cube, 0),
            (DefaultItems.gel_splat, 3),  # Erase
        ], [
            (DefaultItems.funnel, 0),
            (DefaultItems.faith_plate, 0),
            (DefaultItems.panel_stairs, 0),
            (DefaultItems.light_strip, 0),
        ], [
            (DefaultItems.fizzler, 0),
            (DefaultItems.light_bridge, 0),
            (DefaultItems.piston_platform, 0),
            (DefaultItems.track_platform, 0),
        ], [
            (DefaultItems.laser_emitter_center, 0),
            (DefaultItems.laser_catcher_center, 0),
            (DefaultItems.laser_relay_center, 0),
            (DefaultItems.glass, 0),
        ], [
            (DefaultItems.panel_glass, 0),
            (DefaultItems.panel_angled, 0),
            (DefaultItems.panel_flip, 0),
            (DefaultItems.obs_room_small, 0),
        ], [
            (DefaultItems.goo, 0),
            (DefaultItems.turret, 0),
        ],
    ],

    'APTAG': [
        [],  # Original has 4 paint fizzler items at the top.
        [
            (DefaultItems.button_pedestal, 0),
            (DefaultItems.button_floor, 0),
            (DefaultItems.cube, 0),
            (DefaultItems.gel_splat, 3),  # Erase
        ], [
            (DefaultItems.funnel, 0),
            (DefaultItems.faith_plate, 0),
            (utils.obj_id("ITEM_DRAW_BRIDGE"), 0),
            (DefaultItems.panel_stairs, 0),
        ], [
            (DefaultItems.fizzler, 0),
            (DefaultItems.light_bridge, 0),
            (DefaultItems.piston_platform, 0),
            (DefaultItems.track_platform, 0),
        ], [
            (DefaultItems.laser_emitter_center, 0),
            (DefaultItems.laser_catcher_center, 0),
            (DefaultItems.laser_relay_center, 0),
            (DefaultItems.glass, 0),
        ], [
            (DefaultItems.panel_glass, 0),
            (DefaultItems.panel_angled, 0),
            (DefaultItems.panel_flip, 0),
            (DefaultItems.obs_room_small, 0),
        ], [
            (DefaultItems.goo, 0),
            (DefaultItems.turret, 0),
            (utils.obj_id("ITEM_CRUSHER"), 0),
            (utils.obj_id("ITEM_VENT"), 0),
        ], [
            (utils.obj_id("ITEM_HIGH_ENERGY_PELLET_EMITTER"), 0),
            (utils.obj_id("ITEM_HIGH_ENERGY_PELLET_CATCHER"), 0),
            (utils.obj_id("DOOR"), 0),
            (DefaultItems.light_strip, 0),  # Cold
        ], [
            (utils.obj_id("ITEM_TRIGGERS"), 0),
            (utils.obj_id("ITEM_BEE_LOGIC"), 0),
            (utils.obj_id("ITEM_AUTOPORTAL"), 0),
            (utils.obj_id("ITEM_TAG_GUN_ACTIVATOR"), 0),
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
    settings: config.Config | None
    filename: str | None
    uuid: UUID
    group: str
    readonly: bool
    trans_name: str
    items: ItemPos
    name: TransToken

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
                    item_id = utils.obj_id(item_prop['id'])
                except LookupError:
                    LOGGER.warning('No item in position ({}, {})', x, y)
                    continue
                except ValueError as exc:
                    LOGGER.warning('Invalid item ID:', exc_info=exc)
                    continue
                items[x, y] = (item_id, item_prop.int('subtype', 0))

        elif version == 1:
            for pos, item in zip(COORDS, kv.find_children('Items'), strict=False):
                items[pos] = (utils.obj_id(item.name), int(item.value))
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
        # Use a hash to ensure it's a valid path (without '-' if negative).
        # If a conflict occurs, add a character and hash again to get a different value.
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
            kv.serialise(file)

    def delete_from_disk(self) -> None:
        """Delete this palette from disk."""
        if self.filename is not None:
            os.remove(os.path.join(PAL_DIR, self.filename))

    @classmethod
    def builtin(cls, name: str, items: BuiltinPal) -> Palette:
        """Build a palette object for a builtin palette"""
        return Palette(
            name,
            {
                (x, y): ((item.id if isinstance(item, DefaultItems) else item), subtype)
                for y, row in enumerate(items)
                for x, (item, subtype) in enumerate(row)
                if validate_x(x) and validate_y(y)
            },
            name,
            readonly=True,
            group=GROUP_BUILTIN,
            uuid=uuid5(consts.PALETTE_NS, name),
        )


def load_palettes() -> Iterator[Palette]:
    """Scan and read in all palettes. Legacy files will be converted in the process."""
    for name, items in DEFAULT_PALETTES.items():
        yield Palette.builtin(name, items)

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
            # Legacy parsing of BEE2.2 files...
            try:
                yield parse_legacy(pos_file, prop_file, name)
            except ValueError as exc:
                LOGGER.warning('Failed to parse "{}":', name, exc_info=exc)
                continue
        finally:
            if pos_file is not None:
                pos_file.close()
            if prop_file is not None:
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


def parse_legacy(posfile: IO[str], propfile: IO[str], path: str) -> Palette:
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
                        raise ValueError('Too many items!') from None
                else:
                    raise ValueError(f'Malformed row "{line}"!')
    return Palette(name, pos)


if __name__ == '__main__':
    results = load_palettes()
    for palette in results:
        print(palette)
