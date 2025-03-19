"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, NewType, NoReturn, ClassVar, Self, cast, overload

from collections.abc import Awaitable, Callable, Collection, Iterable, Iterator, Mapping
from collections import defaultdict
from pathlib import Path
import os
import zipfile

from aioresult import ResultCapture
from config import Config
from trio_util import AsyncValue
from srctools import Keyvalues, NoKeyError, Vec
from srctools.tokenizer import TokenSyntaxError
from srctools.filesys import FileSystem, RawFileSystem, ZipFileSystem, VPKFileSystem, File
import attrs
import trio
import srctools
import srctools.logger

from app.errors import ErrorUI
from app.mdown import MarkdownData
from transtoken import AppError, TransToken, TransTokenSource
from editoritems import Item as EditorItem, Renderable, RenderableType
from corridor import CORRIDOR_COUNTS, GameMode, Direction
from loadScreen import MAIN_PAK as LOAD_PAK, MAIN_OBJ as LOAD_OBJ
from BEE2_config import ConfigFile
from app import DEV_MODE, img, lazy_conf
import utils
import consts


__all__ = [
    # Generally global.
    'OBJ_TYPES', 'PACK_CONFIG',
    'LegacyCorr', 'LEGACY_CORRIDORS',
    'MANDATORY_PACKAGES', 'CLEAN_STYLE',
    'PakObject', 'SelPakObject', 'PackagesSet', 'LOADED', 'get_loaded_packages', 'PakRef',
    'find_packages',
    # For use by lifecycle only.
    '_load_packages', '_load_objects', '_load_templates',

    # Selector win data structures.
    'SelitemData', 'AttrDef', 'AttrTypes', 'AttrValues', 'AttrMap',

    # Package objects.
    'Style', 'Item', 'StyleVar', 'Elevator', 'EditorSound', 'StyleVPK', 'Signage', 'PlayerModel',
    'Skybox', 'Music', 'QuotePack', 'PackList', 'CorridorGroup', 'ConfigGroup', 'BarrierHole',

    # Mainly intended for package object code.
    'ParseData', 'ExportKey', 'reraise_keyerror', 'get_config', 'set_cond_source',
    'parse_multiline_key', 'desc_parse', 'sep_values',
    # For exporting module only.
    '_ExportValue',

    'TRANS_OBJ_NOT_FOUND',
]

LOGGER = srctools.logger.get_logger(__name__, alias='packages')
OBJ_TYPES: dict[str, type[PakObject]] = {}
PACK_CONFIG = ConfigFile('packages.cfg')

# "Package ID" used to indicate that this mod is required.
MUSIC_ID_TAG = utils.special_id('<TAG_MUSIC>')
MUSIC_ID_MEL = utils.special_id('<MEL_MUSIC>')

TRANS_AP_TAG = TransToken.ui('Aperture Tag')
TRANS_MEL = TransToken.ui('Portal Stories: Mel')
TRANS_MISSING_PAK_DIR = TransToken.ui(
    'Package directory does not exist: "{path}"'
)
TRANS_EMPTY_PAK_DIR = TransToken.ui(
    'Package directory did not contain any packages: "{path}"'
)
TRANS_INVALID_PAK_BAD_FORMAT = TransToken.ui(
    'Package file has the incorrect file format: {path}\n'
    'Valid formats are zip archives (.zip or .bee_pack) and VPKs (.vpk)'
)
TRANS_INVALID_PAK_NO_INFO = TransToken.ui(
    'Potential package file has no info.txt: {path}'
)
TRANS_INVALID_PAK_BAD_INFO = TransToken.ui(
    'Package has invalid info.txt file: {path}'
)
TRANS_INVALID_PAK_NO_ID = TransToken.ui(
    'Package has no ID defined: {path}'
)
TRANS_MISSING_REQUIRED_GAME = TransToken.ui(
    'Package "{pak_id}" could not be enabled - {req} is not installed.',
)
TRANS_MISSING_REQUIRED_PACK = TransToken.ui(
    'Package "{pak_id}" could not be enabled - required package "{req}" not installed.',
)
TRANS_UNKNOWN_OBJ_TYPE = TransToken.untranslated(
    'Unknown object type "{obj_type}" with ID "{obj_id}" in package "{pak_id}"!'
)
TRANS_OLD_TEMPLATEBRUSH = TransToken.untranslated(
    'TemplateBrush "{id}" in package "{pak_id}" no longer needs to be defined in info.txt. '
    'Use a bee2_template_conf entity instead.'
)
TRANS_NO_OBJ_ID = TransToken.untranslated(
    'No ID defined for "{obj_type}" object type in "{pak_id}" package!'
)
TRANS_OBJ_NOT_FOUND = TransToken.untranslated(
    'Definition for {object} object "{id}" was not found. Check for missing packages.'
)
TRANS_DUPLICATE_PAK_ID = TransToken.ui(
    'Duplicate package with id "{pak_id}"!\n'
    'If you just updated the mod, delete any old files in packages/.\n'
    'Package 1: {path1}\n'
    'Package 2: {path2}'
)
TRANS_DUPLICATE_OBJ_ID = TransToken.untranslated(
    'The ID "{obj_id}" was used twice for a {obj_type} in the packages "{pak1}" and "{pak2}"!'
)
TRANS_CORR_OPTS = TransToken.ui_plural('{n} option', '{n} options')  # i18n: Corridor options count
TRANS_MISSING_ITEM_DESC = TransToken.ui('The object {id} is missing from loaded packages. Exporting it will fail.')


@utils.freeze_enum_props
class AttrTypes(Enum):
    """The type of labels used for selectoritem attributes."""
    STRING = 'string'  # Normal text
    LIST_AND = 'list_and'  # A sequence, joined by commas
    LIST_OR = 'list_or'  # A sequence, joined by commas
    BOOL = 'bool'  # A yes/no checkmark
    COLOUR = 'color'  # A Vec 0-255 RGB colour

    @property
    def is_wide(self) -> bool:
        """Determine if this should be placed on its own row, or paired with another."""
        return self.value in ('string', 'list_and', 'list_or')

    @property
    def is_image(self) -> bool:
        """Check if this uses an image, or is just text."""
        return self.value in ('bool', 'color')


# TransToken is str()-ified.
type AttrValues = str | TransToken | Iterable[str | TransToken] | bool | Vec
type AttrMap = Mapping[str, AttrValues]


@attrs.define(eq=False)
class AttrDef:
    """Configuration for attributes shown on selector labels."""
    id: str
    desc: TransToken
    default: AttrValues
    type: AttrTypes

    @classmethod
    def string(
        cls, attr_id: str,
        desc: TransToken = TransToken.BLANK,
        default: str = '',
    ) -> AttrDef:
        """Alternative constructor for string-type attrs."""
        return AttrDef(attr_id, desc, default, AttrTypes.STRING)

    @classmethod
    def list_and(
        cls, attr_id: str,
        desc: TransToken = TransToken.BLANK,
        default: Iterable[str | TransToken] | None = None,
    ) -> AttrDef:
        """Alternative constructor for list-type attrs, which should be joined with AND."""
        if default is None:
            default = []
        return AttrDef(attr_id, desc, default, AttrTypes.LIST_AND)

    @classmethod
    def list_or(
        cls, attr_id: str,
        desc: TransToken = TransToken.BLANK,
        default: Iterable[str | TransToken] | None = None,
    ) -> AttrDef:
        """Alternative constructor for list-type attrs, which should be joined with OR."""
        if default is None:
            default = []
        return AttrDef(attr_id, desc, default, AttrTypes.LIST_OR)

    @classmethod
    def bool(
        cls, attr_id: str,
        desc: TransToken = TransToken.BLANK,
        default: bool = False,
    ) -> AttrDef:
        """Alternative constructor for bool-type attrs."""
        return AttrDef(attr_id, desc, default, AttrTypes.BOOL)

    @classmethod
    def color(
        cls, attr_id: str,
        desc: TransToken = TransToken.BLANK,
        default: Vec | None = None,
    ) -> AttrDef:
        """Alternative constructor for color-type attrs."""
        if default is None:
            default = Vec(255, 255, 255)
        return AttrDef(attr_id, desc, default, AttrTypes.COLOUR)


@attrs.frozen(kw_only=True)
class SelitemData:
    """Options which are displayed on the selector window.


    - name: The full item name. This can be very long. If not set,
      this will be the same as the short name.
    - short_name: A shortened version of the full name. This should be <= 20
      characters.
    - context_lbl: The text shown on the rightclick menu. This is either
      the short or long name, depending on the size of the long name.
    - icon: The image handle for the item icon. The icon should be 96x96
      pixels large.
    - large_icon: If set, a different handle to use for the 192x192 icon.
    - desc: A MarkdownData value containing the description.
    - auth: A list of the item's authors.
    - group: Items with the same group name will be shown together.
    """
    name: TransToken  # Longer full name.
    short_name: TransToken  # Shorter name for the icon.
    auth: frozenset[str]
    icon: img.Handle
    large_icon: img.Handle
    desc: MarkdownData
    group: TransToken
    group_id: str
    sort_key: str
    # The packages used to define this, used for debugging.
    packages: frozenset[str] = attrs.Factory(frozenset)

    @property
    def context_lbl(self) -> TransToken:
        """The text displayed on the rightclick menu."""
        if len(self.name.token) > 20:
            return self.short_name
        else:
            return self.name

    @classmethod
    def build(
        cls, *,
        long_name: TransToken,
        short_name: TransToken | None = None,
        authors: Iterable[str] = (),
        small_icon: img.Handle | None = None,
        large_icon: img.Handle | None = None,
        desc: TransToken | MarkdownData = TransToken.BLANK,
        group: TransToken = TransToken.BLANK,
        sort_key: str = '',
        packages: Iterable[utils.ObjectID] = frozenset(),
    ) -> SelitemData:
        """Create, automatically handling omitted names and icons."""
        if short_name is None:
            short_name = long_name

        if small_icon is None:
            if large_icon is not None:
                small_icon = large_icon.transform(
                    (1, 1),
                    width=consts.SEL_ICON_SIZE, height=consts.SEL_ICON_SIZE,
                )
            else:
                small_icon = img.Handle.background(consts.SEL_ICON_SIZE, consts.SEL_ICON_SIZE)
        if large_icon is None:
            large_icon = small_icon
        if isinstance(desc, TransToken):
            desc = MarkdownData(desc, None)

        return cls(
            name=long_name,
            short_name=short_name,
            auth=frozenset(authors),
            icon=small_icon,
            large_icon=large_icon,
            desc=desc,
            group=group,
            group_id=group.token.casefold(),
            sort_key=sort_key or long_name.token,
            packages=frozenset(packages),
        )

    @classmethod
    def parse(cls, info: Keyvalues, pack_id: utils.ObjectID) -> SelitemData:
        """Parse from a keyvalues block."""
        auth = frozenset(sep_values(info['authors', '']))
        name = TransToken.parse(pack_id, info['name'])
        sort_key = info['sort_key', '']
        desc = desc_parse(info, info['id'], pack_id)
        try:
            group = TransToken.parse(pack_id, info['group'])
        except LookupError:
            group = TransToken.BLANK
        try:
            short_name = TransToken.parse(pack_id, info['shortName'])
        except LookupError:
            short_name = name

        try:
            icon = img.Handle.parse(
                info.find_key('icon'),
                pack_id,
                consts.SEL_ICON_SIZE, consts.SEL_ICON_SIZE,
            )
        except LookupError:
            icon = None
        large_key: Keyvalues | None
        try:
            large_key = info.find_key('iconLarge')
        except LookupError:
            large_icon = large_key = None
        else:
            large_icon = img.Handle.parse(
                large_key,
                pack_id,
                *consts.SEL_ICON_SIZE_LRG,
            )

        return cls.build(
            long_name=name,
            short_name=short_name,
            authors=auth,
            small_icon=icon,
            large_icon=large_icon,
            desc=desc,
            group=group,
            sort_key=sort_key,
            packages={pack_id},
        )

    def __add__(self, other: SelitemData) -> SelitemData:
        """Join together two sets of selitem data.

        This uses the over_data values if defined, using our_data if not.
        Authors and descriptions will be joined to each other.
        """
        if not isinstance(other, SelitemData):
            return NotImplemented

        return attrs.evolve(
            self,
            auth=self.auth | other.auth,
            desc=self.desc + other.desc,
            group=other.group or self.group,
            group_id=other.group_id or self.group_id,
            packages=self.packages | other.packages,
        )

    def iter_trans_tokens(self, source: str) -> Iterator[TransTokenSource]:
        """Yield the tokens in this data."""
        yield self.name, f'{source}.long_name'
        yield self.short_name, f'{source}.short_name'
        yield self.group, f'{source}.group'
        yield from self.desc.iter_tokens(f'{source}.desc')


TRANS_NONE_NAME = TransToken.ui("<None>")
NONE_ICON = img.Handle.ico_none(consts.SEL_ICON_SIZE, consts.SEL_ICON_SIZE)

SEL_DATA_NONE = SelitemData.build(
    short_name=TransToken.BLANK,
    long_name=TRANS_NONE_NAME,
    small_icon=NONE_ICON,
    desc=TransToken.ui('Do not add anything.'),
)
SEL_DATA_MISSING = SelitemData.build(
    long_name=TransToken.ui('Unknown Object'),
    short_name=TransToken.ui('???'),
    small_icon=img.Handle.error(consts.SEL_ICON_SIZE, consts.SEL_ICON_SIZE),
    desc=TransToken.ui('This object is missing from loaded packages. Exporting it will fail.'),
)


@attrs.define
class ObjData:
    """Temporary data stored when parsing info.txt, but before .parse() is called.

    This allows us to parse all packages before loading objects.
    """
    fsys: FileSystem
    info_block: Keyvalues = attrs.field(repr=False)
    pak_id: utils.ObjectID
    disp_name: TransToken


@attrs.define
class PackErrorInfo:
    """Object to pass to various methods, with a packset and errorUI object.

    Has methods to warn/error only for development packages.
    """
    # The entire loaded packages set. The repr is massive, just show the ID.
    packset: PackagesSet = attrs.field(repr=lambda pack: f'<PackagesSet @ {id(pack):x}>')
    errors: ErrorUI

    def warn(self, warning: AppError | TransToken) -> None:
        """Emit a non-fatal warning, shortcut for errors.add()."""
        self.errors.add(warning)

    def warn_auth(self, package: utils.SpecialID, warning: AppError | TransToken, /) -> None:
        """If the specified package is a developer package, emit a warning."""
        try:
            # If it's a special ID, this will fail to find.
            is_dev = self.packset.packages[utils.ObjectID(package)].is_dev()
        except KeyError:
            LOGGER.warning('Trying to warn about package "{}" which does not exist?', package)
            is_dev = True  # Missing, warn about it?
        if DEV_MODE.value or is_dev:
            self.errors.add(warning)

    def warn_auth_fatal(self, package: utils.SpecialID, warning: AppError | TransToken, /) -> None:
        """If the specified package is a developer package, emit a fatal warning."""
        if not isinstance(warning, AppError):
            warning = AppError(warning)
        warning.fatal = True
        self.warn_auth(package, warning)


@attrs.define
class ParseData(PackErrorInfo):
    """The arguments for pak_object.parse()."""
    fsys: FileSystem
    id: str
    info: Keyvalues = attrs.field(repr=False)
    pak_id: utils.ObjectID
    is_override: bool

    @overload
    def warn_auth(self, warning: AppError | TransToken, /) -> None: ...
    @overload
    def warn_auth(self, package: utils.SpecialID, warning: AppError | TransToken) -> None: ...
    def warn_auth(
        self,
        package: utils.SpecialID | AppError | TransToken,
        warning: AppError | TransToken | None = None,
    ) -> None:
        """If this package/the specified package is a developer one, emit a warning."""
        if isinstance(package, str):
            if warning is None:
                raise TypeError("warn_auth() missing warning parameter.")
            super().warn_auth(package, warning)
        else:
            super().warn_auth(self.pak_id, package)

    @overload
    def warn_auth_fatal(self, warning: AppError | TransToken, /) -> None: ...
    @overload
    def warn_auth_fatal(self, package: utils.SpecialID, warning: AppError | TransToken) -> None: ...
    def warn_auth_fatal(
        self,
        package: utils.SpecialID | AppError | TransToken,
        warning: AppError | TransToken | None = None,
    ) -> None:
        """If this package/the specified package is a developer one, emit a fatal warning."""
        if isinstance(package, str):
            if warning is None:
                raise TypeError("warn_auth() missing warning parameter.")
            super().warn_auth_fatal(package, warning)
        else:
            super().warn_auth_fatal(self.pak_id, package)


@attrs.define
class LegacyCorr:
    """Legacy definitions for each corridor in a style."""
    name: str = ''
    icon: utils.PackagePath = img.PATH_BLANK
    desc: str = ''


# Corridor enums to legacy names
LEGACY_CORRIDORS = {
    (GameMode.SP, Direction.ENTRY): 'sp_entry',
    (GameMode.SP, Direction.EXIT): 'sp_exit',
    (GameMode.COOP, Direction.EXIT): 'coop',
}

# These packages contain necessary components, and must be available.
MANDATORY_PACKAGES = {
    utils.obj_id('BEE2_CLEAN_STYLE'),
    utils.obj_id('BEE2_CORE'),
}
# We fall back to the Clean Style in some cases.
CLEAN_STYLE = utils.obj_id('BEE2_CLEAN')


style_suggest_keys: dict[str, type[SelPakObject]] = {}


class PakObject:
    """PackObject(allow_mult=False, has_img=True): The base class for package objects.

    In the class base list, set 'allow_mult' to True if duplicates are allowed.
    If duplicates occur, they will be treated as overrides.
    Setting `needs_foreground` indicates that it is unable to load after the main UI.
    If `style_suggest_key` is set, this is the keyvalue in Style definitions containing IDs to suggest.
    `suggest_default` is then the default item to provide if none are specified.
    """
    # ID of the object - TODO: Make it ReadOnly[SpecialID] (most subclasses will just be ObjectID).
    id: str
    # ID of the package.
    pak_id: utils.SpecialID
    # Display name of the package.
    pak_name: str

    _id_to_obj: ClassVar[dict[str, PakObject]]
    allow_mult: ClassVar[bool]
    needs_foreground: ClassVar[bool]

    def __init_subclass__(
        cls,
        allow_mult: bool = False,
        needs_foreground: bool = False,
    ) -> None:
        super().__init_subclass__()
        if cls.__name__ == 'SelPakObject':
            return  # Do not register this.

        OBJ_TYPES[cls.__name__.casefold()] = cls

        # Maps object IDs to the object.
        cls._id_to_obj = {}
        cls.allow_mult = allow_mult
        cls.needs_foreground = needs_foreground

    def reference(self) -> PakRef[Self]:
        """Get a PakRef for this package object."""
        return PakRef(type(self), utils.obj_id(self.id))

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse the package object from the info.txt block.

        ParseData is a namedtuple containing relevant info:
        - fsys, the package's FileSystem
        - id, the ID of the item
        - info, the Keyvalues block in info.txt
        - pak_id, the ID of the package
        """
        raise NotImplementedError

    def add_over(self, override: Self) -> None:
        """Called to override values.
        self is the originally defined item, and override is the override item
        to copy values from.
        """
        pass

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yields translation tokens in this object.

        This is used to regenerate package translation files.
        """
        return iter(())

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Do processing after all objects of this type have been fully parsed (but others may not)."""
        pass

    @classmethod
    async def migrate_config(cls, packset: PackagesSet, conf: Config, /) -> Config:
        """Update configs based on the loaded packages."""
        return conf


class SelPakObject(PakObject):
    """Defines PakObjects which have SelItemData."""
    suggest_default: ClassVar[str]

    selitem_data: SelitemData

    def __init_subclass__(
        cls,
        style_suggest_key: str = '',
        suggest_default: str = '<NONE>',
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if style_suggest_key:
            assert style_suggest_key.casefold() not in style_suggest_keys
            style_suggest_keys[style_suggest_key.casefold()] = cls
            cls.suggest_default = suggest_default
        else:
            cls.suggest_default = ''

    @classmethod
    def selector_id_getter(
        cls, include_none: bool,
    ) -> Callable[[PackagesSet], Awaitable[list[utils.SpecialID]]]:
        """Called by selector windows to get the current list of IDs for this item."""
        async def get_ids(packset: PackagesSet) -> list[utils.SpecialID]:
            """Fetch all IDs."""
            await packset.ready(cls).wait()
            ids = []
            if include_none:
                ids.append(utils.ID_NONE)
            for obj in packset.all_obj(cls):
                ids.append(utils.special_id(obj.id))
            return ids
        return get_ids

    @classmethod
    def selector_data_getter(cls, none_data: SelitemData | None) -> Callable[[PackagesSet, utils.SpecialID], SelitemData]:
        """Produces a function which retrieves the data from this object type."""
        def getter(packset: PackagesSet, item_id: utils.SpecialID) -> SelitemData:
            """Fetch the data."""
            if item_id == utils.ID_NONE and none_data is not None:
                return none_data
            elif utils.not_special_id(item_id):
                return packset.obj_by_id(cls, item_id).selitem_data
            else:
                # Other special IDs are entirely prohibited.
                LOGGER.warning('Invalid {} ID {!r}', cls.__name__, item_id)
                return SEL_DATA_MISSING
        return getter


@attrs.frozen
class PakRef[PakT: PakObject]:
    """Encapsulates an ID for a specific pakobject class."""
    obj: type[PakT]
    id: utils.ObjectID

    @classmethod
    def of(cls, obj: PakT) -> PakRef[PakT]:
        """Return a reference to an existing object."""
        return cls(type(obj), utils.obj_id(obj.id))

    @classmethod
    def parse(cls, type: type[PakT], value: str) -> PakRef[PakT]:
        """Parse the object ID, producing appropriate error messages."""
        return cls(type, utils.obj_id(value, type.__name__))

    def resolve(self, packset: PackagesSet) -> PakT | None:
        """Look up this object, or return None if missing.

        If missing this has already logged a warning.
        """
        try:
            return packset.obj_by_id(self.obj, self.id)
        except KeyError:
            return None

    def __str__(self) -> str:
        """The string form is the ID itself."""
        return self.id


@attrs.define(eq=False)
class ExportKey[T]:
    """Keys which define the types required to export different package objects.

    These are defined as a constant on each PakObject, called to get values to accumulate,
    then ExportData allows retrieving.
    """
    cls: type[PakObject] | None = None

    def __set_name__(self, owner: type[PakObject], name: str) -> None:
        """Store the associated object for reference purposes."""
        self.cls = owner

    def __call__(self, value: T) -> _ExportValue:
        return _ExportValue((self, value))


# Only for instantiation in ExportKey.
_ExportValue = NewType('_ExportValue', tuple[ExportKey[Any], Any])


def reraise_keyerror(err: NoKeyError | IndexError, obj_id: str) -> NoReturn:
    """Replace NoKeyErrors with a nicer one, giving the item that failed."""
    key_error: NoKeyError
    if isinstance(err, IndexError):
        if isinstance(err.__cause__, NoKeyError):
            # Keyvalues.__getitem__ raises IndexError from
            # NoKeyError, so read from the original
            key_error = err.__cause__
        else:
            # We shouldn't have caught this
            raise err
    else:
        key_error = err
    raise Exception(f'No "{key_error.key}" in {obj_id!s} object!') from err


async def get_config(
    packset: PackagesSet,
    prop_block: Keyvalues,
    folder: str,
    /,
    pak_id: utils.ObjectID,
    *,
    prop_name: str = 'config',
    extension: str = '.cfg',
    source: str = '',
) -> lazy_conf.LazyConf:
    """Lazily extract a config file referred to by the given keyvalues block.

    Looks for one or more prop_name keys in the given prop_block.
    For each:
        If the keyvalue has a value of "", it is skipped.
        If it has children, a copy of them will be returned.
        Otherwise, the value is a filename in the zip which will be parsed.

    If multiple are defined, they get appended together.
    If source is supplied, set_cond_source() will be run.
    """
    conf = lazy_conf.BLANK
    for kv_block in prop_block.find_all(prop_name):
        if kv_block.has_children():
            kv = kv_block.copy()
            kv.name = ""
            conf = lazy_conf.concat(conf, lazy_conf.raw_prop(kv, source=source))
        elif kv_block.value:
            # Zips must use '/' for the separator, even on Windows!
            path = f'{folder}/{kv_block.value}'
            if len(path) < 3 or path[-4] != '.':
                # Add extension
                path += extension
            conf = lazy_conf.concat(conf, await lazy_conf.from_file(
                packset,
                utils.PackagePath(pak_id, path),
                source=f'{pak_id}:{path}',
            ))
    return conf


def set_cond_source(kv: Keyvalues, source: str) -> None:
    """Set metadata for Conditions in the given config blocks.

    This generates '__src__' keyvalues in Condition blocks with info like
    the source object ID and originating file, so errors can be traced back
    to the config file creating it.
    """
    for cond in kv.find_all('Conditions', 'Condition'):
        if '__src__' not in cond:
            cond['__src__'] = f'{source}:{cond.line_num}' if source else f'{cond.line_num}'


def _obj_dict() -> dict[type[PakObject], dict[str, Any]]:
    """Make empty dicts for PackagesSet, with all types present."""
    return {
        typ: {}
        for typ in OBJ_TYPES.values()
    }


@attrs.define
class PackagesSet:
    """Holds all the data parsed from packages.

    This is swapped out to reload packages.
    """
    packages: dict[utils.ObjectID, Package] = attrs.Factory(dict)
    # type -> id -> object
    # The object data before being parsed, and the final result.
    unparsed: dict[type[PakObject], dict[str, ObjData]] = attrs.field(factory=_obj_dict, repr=False)
    objects: dict[type[PakObject], dict[str, PakObject]] = attrs.Factory(_obj_dict)
    # For overrides, a type/ID pair to the list of overrides.
    overrides: dict[tuple[type[PakObject], str], list[ParseData]] = attrs.Factory(lambda: defaultdict(list))

    # The templates found in the packages. This maps an ID to the file.
    templates: dict[str, utils.PackagePath] = attrs.field(init=False, factory=dict)

    # Indicates if an object type has been fully parsed.
    _type_ready: dict[type[PakObject], trio.Event] = attrs.field(init=False, factory=dict)
    # Internal, indicates if all parse() calls were complete (but maybe not post_parse).
    _parsed: set[type[PakObject]] = attrs.field(init=False, factory=set)

    # If found, the folders where the music is present.
    mel_music_fsys: FileSystem | None = None
    tag_music_fsys: FileSystem | None = None

    # Objects we've warned about not being present. Since this is stored
    # here it'll automatically clear when reloading. If None, it's suppressed instead.
    _unknown_obj_warnings: set[tuple[type[PakObject], str]] | None = attrs.Factory(set)

    # In dev mode, all lazy files are sent here to be syntax checked.
    # The other end is implemented in lifecycle.
    devmode_filecheck_chan: trio.MemorySendChannel[tuple[utils.PackagePath, File]] | None = None

    @classmethod
    def blank(cls) -> Self:
        """Create an empty set, with all types marked as finished."""
        pakset = cls()
        event = trio.Event()
        event.set()
        pakset._parsed.update(OBJ_TYPES.values())
        pakset._type_ready = dict.fromkeys(pakset._parsed, event)
        pakset._unknown_obj_warnings = None
        return pakset

    @property
    def has_mel_music(self) -> bool:
        """Have we found Portal Stories:Mel?"""
        return self.mel_music_fsys is not None

    @property
    def has_tag_music(self) -> bool:
        """Have we found Aperture Tag?"""
        return self.tag_music_fsys is not None

    def ready(self, cls: type[PakObject]) -> trio.Event:
        """Return a Trio Event which is set when a specific object type is fully parsed."""
        try:
            return self._type_ready[cls]
        except KeyError:
            self._type_ready[cls] = evt = trio.Event()
            return evt

    def can_export(self) -> bool:
        """Check if we're currently able to export."""
        try:
            return all(self._type_ready[cls].is_set() for cls in OBJ_TYPES.values())
        except KeyError:
            # ready() was never called on at least one class, so it can't possibly be done yet!
            return False

    def all_obj[PakT: PakObject](self, cls: type[PakT]) -> Collection[PakT]:
        """Get the list of objects parsed."""
        if cls not in self._parsed:
            raise ValueError(f'{cls.__name__} has not been parsed yet!')
        return cast('dict[str, PakT]', self.objects[cls]).values()

    def obj_by_id[PakT: PakObject](
        self,
        cls: type[PakT],
        obj_id: str,
        *,
        optional: bool = False,
    ) -> PakT:
        """Return the object with a given ID.

        If not found, by default a warning is printed refrerencing the parent.
        """
        if cls not in self._parsed:
            raise ValueError(f'{cls.__name__} has not been parsed yet!')
        obj_dict = cast('dict[str, PakT]', self.objects[cls])
        try:
            return obj_dict[obj_id.casefold()]
        except KeyError:
            if (
                not optional
                and self._unknown_obj_warnings is not None
                and (key := (cls, obj_id)) not in self._unknown_obj_warnings
            ):
                self._unknown_obj_warnings.add(key)
                LOGGER.warning('The {} package object "{}" does not exist!', cls.__name__, obj_id)
            raise

    def add(self, obj: PakObject, pak_id: utils.SpecialID, pak_name: str) -> None:
        """Add an object to our dataset later, with the given package name."""
        self.objects[type(obj)][obj.id.casefold()] = obj
        if not hasattr(obj, 'pak_id'):
            obj.pak_id = pak_id
            obj.pak_name = pak_name

    async def migrate_conf(self, conf: Config) -> Config:
        """Migrate configs based on the loaded packages."""
        for cls in OBJ_TYPES.values():
            conf = await cls.migrate_config(self, conf)
        return conf


def get_loaded_packages() -> PackagesSet:
    """The current set of loaded packages.

    TODO: Try to make this local wherever possible?
    """
    return LOADED.value


LOADED = AsyncValue(PackagesSet())


async def find_packages(errors: ErrorUI, packset: PackagesSet, pak_dir: Path) -> bool:
    """Search a folder for packages, recursing if necessary.

    This returns True if at least one package was found.
    """
    found_pak = False
    try:
        contents = list(pak_dir.iterdir())
    except FileNotFoundError:
        errors.add(TRANS_MISSING_PAK_DIR.format(path=pak_dir))
        return False

    children: list[ResultCapture[bool]] = []
    async with trio.open_nursery() as nursery:
        for name in contents:  # Both files and dirs
            folded = name.stem.casefold()
            if folded.endswith('.vpk') and not folded.endswith('_dir.vpk'):
                # _000.vpk files, useless without the directory
                continue

            LOGGER.debug('Reading package "{}"', name)

            filesys: FileSystem
            if name.is_dir():
                filesys = RawFileSystem(name)
            else:
                ext = name.suffix.casefold()
                try:
                    if ext in ('.bee_pack', '.zip'):
                        filesys = await trio.to_thread.run_sync(ZipFileSystem, name, abandon_on_cancel=True)
                    elif ext == '.vpk':
                        filesys = await trio.to_thread.run_sync(VPKFileSystem, name, abandon_on_cancel=True)
                    else:
                        LOGGER.info('Extra file: {}', name)
                        continue
                except (ValueError, zipfile.BadZipFile) as exc:
                    LOGGER.warning('Failed to parse "{}":', name, exc_info=exc)
                    errors.add(TRANS_INVALID_PAK_BAD_FORMAT.format(path=name))
                    continue

            # Valid packages must have an info.txt file!
            try:
                info = await trio.to_thread.run_sync(filesys.read_kv1, 'info.txt', abandon_on_cancel=True)
            except FileNotFoundError:
                if name.is_dir():
                    # This isn't a package, so check the subfolders too...
                    LOGGER.debug('Checking subdir "{}" for packages...', name)
                    children.append(ResultCapture.start_soon(
                        nursery, find_packages,
                        errors, packset, name,
                    ))
                else:
                    # Just a warning, could be something else.
                    errors.add(TRANS_INVALID_PAK_NO_INFO.format(path=name))
                # Don't continue to parse this "package"
                continue
            except TokenSyntaxError as exc:
                LOGGER.exception('Invalid info: {}:info.txt', filesys.path, exc_info=exc)
                errors.add(TRANS_INVALID_PAK_BAD_INFO.format(path=f'{filesys.path}:info.txt'))
                continue
            try:
                pak_id = utils.obj_id(info['ID'])
            except LookupError:
                errors.add(TRANS_INVALID_PAK_NO_ID.format(path=f'{filesys.path}:info.txt'))
                continue  # Skip this.

            if pak_id in packset.packages:
                duplicate = packset.packages[pak_id]
                raise AppError(TRANS_DUPLICATE_PAK_ID.format(
                    pak_id=pak_id,
                    path1=duplicate.fsys.path,
                    path2=filesys.path,
                ))

            packset.packages[pak_id] = Package(
                pak_id,
                filesys,
                info,
                name,
            )
            found_pak = True

    if found_pak or any(result.result() for result in children):
        return True
    else:
        LOGGER.info('Directory {} was empty.', pak_dir)
        return False


async def _load_packages(
    packset: PackagesSet,
    pak_dirs: list[Path],
    errors: ErrorUI,
) -> None:
    """Scan and read in all packages."""
    async with trio.open_nursery() as find_nurs:
        find_sources = [
            (pak_dir, ResultCapture.start_soon(find_nurs, find_packages, errors, packset, pak_dir))
            for pak_dir in pak_dirs
        ]
    # Once they've all run, check if any sources failed to find any packages - that's probably an error.
    for pak_dir, find_res in find_sources:
        if not find_res.result():
            errors.add(TRANS_EMPTY_PAK_DIR.format(path=pak_dir))
    pack_count = len(packset.packages)
    await LOAD_PAK.set_length(pack_count)

    # These packages are required.
    missing = MANDATORY_PACKAGES - packset.packages.keys()
    if missing:
        if pack_count == 0:  # None at all
            message = TransToken.ui('No packages found!')
        else:
            message = TransToken.ui_plural(
                'Critical package missing: {pack}'
                'These are required for some essential resources and objects.',

                'Critical packages missing: {pack}'
                'These are required for some essential resources and objects.',
            ).format(pack=TransToken.list_and([
                TransToken.untranslated(pak_id)
                for pak_id in missing
            ]), n=len(missing))

        if len(pak_dirs) == 1:
            trailer = TransToken.untranslated(str((os.getcwd() / pak_dirs[0]).resolve()))
        else:
            trailer = TransToken.ui(
                'one of the following locations:\n{loc}'
            ).format(loc='\n'.join(
                f' - {(os.getcwd() / fold).resolve()}'
                for fold in pak_dirs
            ))
        raise AppError(TransToken.ui(
            '{msg}\n'
            'Get the packages from "https://github.com/BEEmod/BEE2-items" '
            'and place them in {trailer}'
        ).format(msg=message, trailer=trailer))

    # Ensure all objects are in the dicts.
    for obj_type in OBJ_TYPES.values():
        packset.unparsed[obj_type] = {}
        packset.objects[obj_type] = {}

    async with trio.open_nursery() as nursery:
        for pack in packset.packages.values():
            if not pack.enabled:
                LOGGER.info('Package {} disabled!', pack.id)
                pack_count -= 1
                await LOAD_PAK.set_length(pack_count)
                continue

            nursery.start_soon(parse_package, nursery, errors, packset, pack)
        LOGGER.debug('Submitted packages.')

    LOGGER.debug('Parsed packages.')


async def _load_objects(packset: PackagesSet, errors: ErrorUI) -> None:
    """Parse all the objects in a packset."""
    LOGGER.debug('Parsing objects...')

    await LOAD_OBJ.set_length(sum(
        len(obj_map)
        for obj_type, obj_map in
        packset.unparsed.items()
        if obj_type.needs_foreground
    ))

    LOGGER.info('Object counts:\n{}', '\n'.join(
        f'{obj_type.__name__:<15}: {len(objs)}'
        for obj_type, objs in
        sorted(packset.unparsed.items(), key=lambda t: len(t[1]), reverse=True)
    ))

    async with trio.open_nursery() as nursery:
        for obj_class, objs in packset.unparsed.items():
            nursery.start_soon(
                parse_type,
                packset, errors, obj_class, objs,
            )


async def _load_templates(packset: PackagesSet) -> None:
    """Parse templates in a packset."""
    from packages import template_brush  # Avoid circular imports

    async def find_temp(pack: Package) -> None:
        """Find templates for a package."""
        for template in pack.fsys.walk_folder('templates'):
            await trio.lowlevel.checkpoint()
            if template.path.casefold().endswith('.vmf'):
                nursery.start_soon(template_brush.parse_template, packset, pack.id, template)

    async with trio.open_nursery() as nursery:
        for package in packset.packages.values():
            nursery.start_soon(find_temp, package)
    LOGGER.info('Loaded all templates.')


async def parse_type[PakT: PakObject](
    packset: PackagesSet,
    errors: ErrorUI,
    obj_class: type[PakT],
    objs: Iterable[str]
) -> None:
    """Parse all of a specific object type."""
    async with trio.open_nursery() as nursery:
        for obj_id in objs:
            nursery.start_soon(
                parse_object,
                packset, errors, obj_class, obj_id,
            )
    LOGGER.info('Post-process {} objects...', obj_class.__name__)
    # Tricky, we want to let post_parse() call all_obj() etc, but not let other blocked tasks
    # run until post_parse finishes. So use two flags.
    # noinspection PyProtectedMember
    packset._parsed.add(obj_class)
    await obj_class.post_parse(packset)
    packset.ready(obj_class).set()


async def parse_package(
    nursery: trio.Nursery,
    errors: ErrorUI,
    packset: PackagesSet,
    pack: Package,
) -> None:
    """Parse through the given package to find all the components."""
    for pre in pack.info.find_children('Prerequisites'):
        # Special case - disable these packages when the music isn't copied.
        required_id = utils.special_id(pre.value)
        if required_id == MUSIC_ID_TAG:
            if not packset.has_tag_music:
                errors.add(TRANS_MISSING_REQUIRED_GAME.format(pak_id=pack.id, req=TRANS_AP_TAG))
                return
        elif required_id == MUSIC_ID_MEL:
            if not packset.has_mel_music:
                errors.add(TRANS_MISSING_REQUIRED_GAME.format(pak_id=pack.id, req=TRANS_MEL))
                return
        elif required_id not in packset.packages:
            errors.add(TRANS_MISSING_REQUIRED_PACK.format(pak_id=pack.id, req=pre.value))
            return

    desc: list[str] = []
    # If this package is unzipped, show warnings about extra values directly to the user.
    pack_warn: Callable[[TransToken], None]
    if DEV_MODE.value or pack.is_dev():
        pack_warn = errors.add
    else:
        def pack_warn(token: TransToken) -> None:
            """Just put warnings in the console."""
            LOGGER.warning('Package "{}": {}', pack.id, token)

    for obj in pack.info:
        await trio.lowlevel.checkpoint()
        if obj.name in ['prerequisites', 'id', 'name']:
            # Not object IDs.
            continue
        if obj.name in ['desc', 'description']:
            desc.extend(obj.as_array())
            continue
        if not obj.has_children():
            LOGGER.warning(
                'Unknown package option "{}" with value "{}"!',
                obj.real_name, obj.value,
            )
            continue

        if obj.name in ('templatebrush', 'brushtemplate'):
            pack_warn(TRANS_OLD_TEMPLATEBRUSH.format(
                id=obj['id', '<NO ID>'],
                pak_id=pack.id,
            ))
        elif obj.name == 'transtoken':
            # Special case for now, since it's package-specific.
            parse_pack_transtoken(pack, obj)
        elif obj.name == 'overrides':
            for over_prop in obj:
                if over_prop.name in ('templatebrush', 'brushtemplate'):
                    pack_warn(TRANS_OLD_TEMPLATEBRUSH.format(
                        id=over_prop['id', '<NO ID>'],
                        pak_id=pack.id,
                    ))
                    continue
                try:
                    obj_type = OBJ_TYPES[over_prop.name]
                except KeyError:
                    pack_warn(TRANS_UNKNOWN_OBJ_TYPE.format(
                        obj_type=over_prop.real_name,
                        obj_id=over_prop['id', '<NO ID>'],
                        pak_id=pack.id,
                    ))
                    continue
                try:
                    obj_id = over_prop['id']
                except LookupError:
                    raise AppError(TRANS_NO_OBJ_ID.format(obj_type=obj_type, pak_id=pack.id)) from None
                packset.overrides[obj_type, obj_id.casefold()].append(
                    ParseData(packset, errors, pack.fsys, obj_id, over_prop, pack.id, True)
                )
        else:
            try:
                obj_type = OBJ_TYPES[obj.name]
            except KeyError:
                pack_warn(TRANS_UNKNOWN_OBJ_TYPE.format(
                    obj_type=obj.real_name,
                    obj_id=obj['id', '<NO ID>'],
                    pak_id=pack.id,
                ))
                continue
            try:
                obj_id = obj['id']
            except LookupError:
                # Always fatal, this is just invalid.
                raise AppError(TRANS_NO_OBJ_ID.format(obj_type=obj_type, pak_id=pack.id)) from None
            if obj_id in packset.unparsed[obj_type]:
                existing = packset.unparsed[obj_type][obj_id]
                if obj_type.allow_mult:
                    # Pretend this is an override, but don't actually set the bool so parsing
                    # will still require all fields.
                    packset.overrides[obj_type, obj_id.casefold()].append(
                        ParseData(packset, errors, pack.fsys, obj_id, obj, pack.id, False)
                    )
                else:
                    # Duplicates and neither takes precedence, this is a problem.
                    raise AppError(TRANS_DUPLICATE_OBJ_ID.format(
                        obj_id=obj_id,
                        obj_type=obj_type.__name__,
                        pak2=existing.pak_id,
                        pak1=pack.id,
                    ))
            else:
                packset.unparsed[obj_type][obj_id] = ObjData(
                    pack.fsys,
                    obj,
                    pack.id,
                    pack.disp_name,
                )

    if desc:
        pack.desc = TransToken.parse(pack.id, '\n'.join(desc))

    await LOAD_PAK.step(pack.id)


async def parse_object(
    packset: PackagesSet,
    errors: ErrorUI,
    obj_class: type[PakObject],
    obj_id: str
) -> None:
    """Parse through the object and store the resultant class."""
    obj_data = packset.unparsed[obj_class][obj_id]
    try:
        with srctools.logger.context(f'{obj_data.pak_id}:{obj_id}'):
            object_ = await obj_class.parse(
                ParseData(
                    packset,
                    errors,
                    obj_data.fsys,
                    obj_id,
                    obj_data.info_block,
                    obj_data.pak_id,
                    is_override=False,
                )
            )
            await trio.lowlevel.checkpoint()
    except (NoKeyError, IndexError) as e:
        reraise_keyerror(e, obj_id)
    except TokenSyntaxError as e:
        # Add the relevant package to the filename.
        if e.file:
            e.file = f'{obj_data.pak_id}:{e.file}'
        raise
    except Exception as e:
        raise ValueError(
            'Error occured parsing '
            f'{obj_data.pak_id}:{obj_id} item!'
        ) from e

    if not hasattr(object_, 'id'):
        raise ValueError(f'"{obj_class.__name__}" object {object_} has no ID!')
    assert object_.id == obj_id, f'{object_!r} -> {object_.id} != "{obj_id}"!'

    object_.pak_id = obj_data.pak_id
    object_.pak_name = str(obj_data.disp_name)
    for override_data in packset.overrides[obj_class, obj_id.casefold()]:
        await trio.lowlevel.checkpoint()
        try:
            with srctools.logger.context(f'override {override_data.pak_id}:{obj_id}'):
                override = await obj_class.parse(override_data)
        except (NoKeyError, IndexError) as e:
            reraise_keyerror(e, f'{override_data.pak_id}:{obj_id}')
        except TokenSyntaxError as e:
            # Add the relevant package to the filename.
            if e.file:
                e.file = f'{override_data.pak_id}:{e.file}'
            raise
        except Exception as e:
            raise ValueError(
                f'Error occured parsing {obj_id} override '
                f'from package {override_data.pak_id}!'
            ) from e

        await trio.lowlevel.checkpoint()
        object_.add_over(override)
    assert obj_id.casefold() not in packset.objects[obj_class], f'{obj_class}("{obj_id}") = {object_}'
    packset.objects[obj_class][obj_id.casefold()] = object_
    if obj_class.needs_foreground:
        await LOAD_OBJ.step(obj_id)


def parse_pack_transtoken(pack: Package, kv: Keyvalues) -> None:
    """Define an additional translation token in a package."""
    try:
        obj_id = kv['id'].casefold()
    except LookupError:
        raise ValueError('No ID for "TransToken" object type!') from None
    if obj_id in pack.additional_tokens:
        raise ValueError('Duplicate translation token "{}:{}"', pack.id, obj_id)
    with srctools.logger.context(f'{pack.id}:{obj_id}'):
        token = TransToken.parse(pack.id, parse_multiline_key(kv, 'text'))

    pack.additional_tokens[obj_id] = token


@attrs.define(eq=False, init=False)
class Package:
    """Represents a package."""
    id: utils.ObjectID
    fsys: FileSystem = attrs.field(repr=False)
    info: Keyvalues = attrs.field(repr=False)
    path: Path
    disp_name: TransToken
    additional_tokens: dict[str, TransToken]
    desc: TransToken = attrs.field(repr=False)

    def __init__(
        self,
        pak_id: utils.ObjectID,
        filesystem: FileSystem,
        info: Keyvalues,
        path: Path,
    ) -> None:
        try:
            disp_name = TransToken.parse(pak_id, info['Name'])
        except LookupError:
            LOGGER.warning('Warning: {} has no display name!', pak_id)
            disp_name = TransToken.untranslated(pak_id.lower())

        self.id = pak_id
        self.fsys = filesystem
        self.info = info
        self.path = path
        self.disp_name = disp_name
        self.additional_tokens = {}
        self.desc = TransToken.ui('No description!')  # Filled in by parse_package().

    @property
    def enabled(self) -> bool:
        """Should this package be loaded?"""
        if self.id in MANDATORY_PACKAGES:
            # These are special, they cannot be disabled.
            return True

        return PACK_CONFIG.get_bool(self.id, 'Enabled', default=True)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable the package."""
        if self.id in MANDATORY_PACKAGES:
            raise ValueError(f'Mandatory package "{self.id}" cannot be disabled!')

        PACK_CONFIG[self.id]['Enabled'] = srctools.bool_as_int(value)

    def is_dev(self) -> bool:
        """Check to see whether this is an unzipped package.

        These are treated as development versions, so extra warnings are enabled.
        """
        return isinstance(self.fsys, RawFileSystem)

    def is_stale(self, mod_time: int) -> bool:
        """Check to see if this package has been modified since the last run."""
        if self.is_dev():
            # Always extract, it's hard to detect if a folder changed anyway.
            LOGGER.info('Need to extract resources - {} is unzipped!', self.id)
            return True

        if self.enabled:
            zip_modtime = int(self.path.stat().st_mtime)

            # If zero, it's never extracted...
            if zip_modtime != mod_time or mod_time == 0:
                LOGGER.info('Need to extract resources - {} is stale!', self.id)
                return True
        else:
            # For disabled packages, need to refresh if we were extracted.
            if mod_time != 0:
                LOGGER.info('Need to extract resources - {} was previously enabled.', self.id)
                return True
        return False

    def get_modtime(self) -> int:
        """After the cache has been extracted, set the modification dates
         in the config."""
        # Raw filesystems have no mod time. Do the same for disabled ones.
        if isinstance(self.fsys, RawFileSystem) or not self.enabled:
            return 0
        else:
            return int(self.path.stat().st_mtime)


class Style(SelPakObject, needs_foreground=True):
    """Represents a style, specifying the era a test was built in."""
    def __init__(
        self,
        style_id: str,
        selitem_data: SelitemData,
        items: list[EditorItem],
        renderables: dict[RenderableType, Renderable],
        suggested: dict[type[SelPakObject], set[str]],
        config: lazy_conf.LazyConf = lazy_conf.BLANK,
        base_style: str | None = None,
        has_video: bool = True,
        vpk_name: str = '',
        legacy_corridors: Mapping[tuple[GameMode, Direction, int], LegacyCorr] = srctools.EmptyMapping,
    ) -> None:
        self.id = style_id
        self.selitem_data = selitem_data
        self.items = items
        self.renderables = renderables
        self.base_style = base_style
        # Set by post_parse() after all objects are read.
        # this is a list of this style, plus parents in order.
        self.bases: list[Style] = []
        self.suggested = suggested
        self.has_video = has_video
        self.vpk_name = vpk_name
        self.legacy_corridors: dict[tuple[GameMode, Direction, int], LegacyCorr] = {}

        for (mode, direction), length in CORRIDOR_COUNTS.items():
            if (mode, direction) not in LEGACY_CORRIDORS:
                continue
            for i in range(1, length + 1):
                try:
                    self.legacy_corridors[mode, direction, i] = legacy_corridors[mode, direction, i]
                except KeyError:
                    self.legacy_corridors[mode, direction, i] = LegacyCorr()

        self.config = config

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse a style definition."""
        info = data.info
        selitem_data = SelitemData.parse(info, data.pak_id)
        base = info['base', ''] or None
        has_video = srctools.conv_bool(
            info['has_video', ''],
            not data.is_override,  # Assume no video for override
        )
        vpk_name = info['vpk_name', ''].casefold()
        items: list[EditorItem]
        renderables: dict[RenderableType, Renderable]

        suggested: dict[type[SelPakObject], set[str]] = {
            pak_type: set()
            for pak_type in style_suggest_keys.values()
        }
        for kv in info.find_children('suggested'):
            try:
                sugg_cls = style_suggest_keys[kv.name]
            except KeyError:
                LOGGER.warning('Unknown suggestion types for style {}: {}', data.id, kv.name)
            else:
                suggested[sugg_cls].add(kv.value)

        corr_conf = info.find_key('corridors', or_blank=True)
        legacy_corridors: dict[tuple[GameMode, Direction, int], LegacyCorr] = {}

        icon_folder = corr_conf['icon_folder', '']

        for (mode, direction), length in CORRIDOR_COUNTS.items():
            try:
                group = LEGACY_CORRIDORS[mode, direction]
            except KeyError:  # Coop entry
                continue
            group_kv = corr_conf.find_key(group, or_blank=True)
            for i in range(1, length + 1):
                kv = group_kv.find_key(str(i), '')

                if icon_folder:
                    icon = utils.PackagePath(data.pak_id, f'corr/{icon_folder}/{group}/{i}.jpg')
                else:
                    icon = img.PATH_BLANK

                if kv.has_children():
                    legacy_corridors[mode, direction, i] = LegacyCorr(
                        name=kv['name', ''],
                        icon=utils.PackagePath.parse(kv['icon', icon], data.pak_id),
                        desc=kv['Desc', ''],
                    )
                else:
                    legacy_corridors[mode, direction, i] = LegacyCorr(
                        name=kv.value,
                        icon=icon,
                        desc='',
                    )
        try:
            folder = 'styles/' + info['folder']
        except LookupError:
            # It's OK for override styles to be missing their 'folder'
            # value.
            if data.is_override:
                items = []
                renderables = {}
                vbsp = lazy_conf.BLANK
            else:
                raise ValueError(f'Style "{data.id}" missing configuration folder!') from None
        else:
            with data.fsys[folder + '/items.txt'].open_str() as f:
                items, renderables = await trio.to_thread.run_sync(EditorItem.parse, f, data.pak_id)
            vbsp = await lazy_conf.from_file(
                data.packset,
                utils.PackagePath(data.pak_id, folder + '/vbsp_config.cfg'),
                missing_ok=True,
                source=f'Style <{data.id}>',
            )

        return cls(
            style_id=data.id,
            selitem_data=selitem_data,
            items=items,
            renderables=renderables,
            config=vbsp,
            base_style=base,
            suggested=suggested,
            has_video=has_video,
            legacy_corridors=legacy_corridors,
            vpk_name=vpk_name,
        )

    def add_over(self, override: Style) -> None:
        """Add the additional commands to ourselves."""
        self.items.extend(override.items)
        self.renderables.update(override.renderables)
        self.config = lazy_conf.concat(self.config, override.config)
        self.selitem_data += override.selitem_data

        self.has_video = self.has_video or override.has_video
        # If overrides have suggested IDs, add those.
        for sugg_cls, sugg in override.suggested.items():
            self.suggested[sugg_cls].update(sugg)

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Assign the bases lists for all styles, and set default suggested items."""
        for style in packset.all_obj(Style):
            for sugg_cls, sugg_set in style.suggested.items():
                if not sugg_set:
                    sugg_set.add(sugg_cls.suggest_default)

            base = []
            b_style = style
            while b_style is not None:
                # Recursively find all the base styles for this one.
                if b_style in base:
                    # Already hit this!
                    raise Exception(f'Loop in bases for "{b_style.id}"!')
                # Just append the style.base_style to the list,
                # until the style with that ID isn't found any more.
                base.append(b_style)
                if b_style.base_style is not None:
                    try:
                        b_style = packset.obj_by_id(cls, b_style.base_style)
                    except KeyError:
                        LOGGER.warning('Unknown style "{}"!', b_style.base_style)
                        break
                else:
                    # No more.
                    break
            style.bases = base
            LOGGER.debug('Inheritance path for {} = {}', style, style.bases)

    def __repr__(self) -> str:
        return f'<Style: {self.id}>'

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Iterate over translation tokens in the style."""
        return self.selitem_data.iter_trans_tokens('styles/' + self.id)

    @classmethod
    def get_selector_attrs(cls, packset: PackagesSet, style_id: utils.SpecialID) -> AttrMap:
        """Return the attributes for the selector window."""
        assert utils.not_special_id(style_id), f'None is not valid for styles: {style_id!r}'
        style = packset.obj_by_id(cls, style_id)
        try:
            corr_count = len(packset.obj_by_id(CorridorGroup, style_id).options)
        except KeyError:
            corr_count = 0
        return {
            'VID': style.has_video,
            'CORR_OPTS': TRANS_CORR_OPTS.format(n=corr_count),
        }


def parse_multiline_key(info: Keyvalues, prop_name: str, *, allow_old_format: bool = False) -> str:
    """Allow several methods for entering multi-line keyvalues.

    Any combination of the following is allowed:
    "key" "single line"
    "key" "another line"
    "key"
        {
        "" "blah"
        "" "Blah blah"
        }
    """
    has_warning = False
    lines = []
    for kv in info.find_all(prop_name):
        if kv.has_children():
            for line in kv:
                if line.name and not has_warning:
                    LOGGER.warning('Old desc format found. Keys inside the block should be ""!')
                    has_warning = True
                lines.append(line.value)
        else:
            lines.append(kv.value)
    return '\n'.join(lines)


def desc_parse(
    info: Keyvalues,
    source: str,
    pak_id: utils.ObjectID,
    *,
    prop_name: str = 'description',
) -> MarkdownData:
    """Parse the description blocks, to create data which matches richTextBox.

    """
    with srctools.logger.context(source):
        token = TransToken.parse(pak_id, parse_multiline_key(info, prop_name))
    return MarkdownData(token, pak_id)


def sep_values(string: str, delimiters: Iterable[str] = ',;/') -> list[str]:
    """Split a string by a delimiter, and then strip whitespace.

    Multiple delimiter characters can be passed.
    """
    delim, *extra_del = delimiters
    if string == '':
        return []

    for extra in extra_del:
        string = string.replace(extra, delim)

    vals = string.split(delim)
    return [
        stripped for stripped in
        (val.strip() for val in vals)
        if stripped
    ]


# Load all the package object classes, registering them in the process.
from .barrier_hole import BarrierHole
from .corridor import CorridorGroup
from .editor_sound import EditorSound
from .elevator import Elevator
from .item import Item
from .music import Music
from .pack_list import PackList
from .player import PlayerModel
from .quote_pack import QuotePack
from .signage import Signage
from .skybox import Skybox
from .style_vpk import StyleVPK
from .stylevar import StyleVar
from .widgets import ConfigGroup
