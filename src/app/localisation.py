"""Handles parsing language files, and updating UI widgets.

The widgets tokens are applied to are stored, so changing language can update the UI.
"""
from __future__ import annotations

import string
from typing import (
    Any, AsyncIterator, Callable, Iterable, Iterator, List, TypeVar, Union,
    TYPE_CHECKING,
)
from typing_extensions import ParamSpec, TypeAlias
from tkinter import ttk
from collections import defaultdict
import tkinter as tk
import io
import itertools
import os.path
import functools
import datetime

from pathlib import Path
from weakref import WeakKeyDictionary
import gettext as gettext_mod
import locale
import sys

from srctools.filesys import RawFileSystem
from srctools import FileSystem, logger
from babel.messages.pofile import read_po, write_po
from babel.messages.mofile import write_mo
from babel.messages import Catalog
from babel.numbers import format_decimal
from babel.dates import format_date, format_datetime, format_skeleton, format_timedelta
from babel.localedata import load as load_cldr
from babel.lists import format_list
import babel
import trio
import attrs

from config.gen_opts import GenOptions
from app import tk_tools
import config
import packages
import utils

from transtoken import (
    NS_UI, PETI_KEY_PREFIX, DUMMY,
    TransToken, TransTokenSource, PluralTransToken, Language,
)
import transtoken

# Circular import issues.
if TYPE_CHECKING:
    from app import gameMan

__all__ = [
    'TransToken',
    'set_text', 'set_menu_text', 'clear_stored_menu', 'set_win_title', 'add_callback',
    'DUMMY', 'Language', 'set_language', 'load_aux_langs',
    'setup', 'expand_langcode',
    'TransTokenSource', 'rebuild_app_langs', 'rebuild_package_langs',
]

LOGGER = logger.get_logger(__name__)
P = ParamSpec('P')

# Location of basemodui, relative to Portal 2
BASEMODUI_PATH = 'portal2_dlc2/resource/basemodui_{}.txt'

# Widgets that have a 'text' property.
TextWidget: TypeAlias = Union[
    tk.Label, tk.LabelFrame, tk.Button, tk.Radiobutton, tk.Checkbutton,
    ttk.Label, ttk.LabelFrame, ttk.Button, ttk.Radiobutton, ttk.Checkbutton,
]
TextWidgetT = TypeVar('TextWidgetT', bound=TextWidget)
CBackT = TypeVar('CBackT', bound=Callable[[], object])
# Assigns to widget['text'].
_applied_tokens: WeakKeyDictionary[TextWidget, TransToken] = WeakKeyDictionary()
# menu -> index -> token.
_applied_menu_tokens: WeakKeyDictionary[tk.Menu, dict[int, TransToken]] = WeakKeyDictionary()
_window_titles: WeakKeyDictionary[tk.Wm, TransToken] = WeakKeyDictionary()
# For anything else, this is called which will apply tokens.
_langchange_callback: list[Callable[[], object]] = []

FOLDER = utils.install_path('i18n')
PARSE_CANCEL = trio.CancelScope()

PACKAGE_HEADER = """\
# Translations template for BEEmod package "PROJECT".
# Built with BEEmod version VERSION.
#"""


# Country code -> Source name suffix.
STEAM_LANGS = {
    'ar': 'arabic',  # Not in P2.
    'pt_br': 'brazilian',
    'bg': 'bulgarian',
    'cs': 'czech',
    'da': 'danish',
    'nl': 'dutch',
    'en': 'english',
    'fi': 'finnish',
    'fr': 'french',
    'de': 'german',
    'el': 'greek',
    'hu': 'hungarian',
    'it': 'italian',
    'ja': 'japanese',
    'ko': 'korean',
    # 'ko': 'koreana',  # North? identical.
    'es_419': 'latam',
    'no': 'norwegian',
    # '': 'pirate',  # Not real.
    'pl': 'polish',
    'pt': 'portuguese',
    'ro': 'romanian',
    'ru': 'russian',
    'zh_cn': 'schinese',
    'es': 'spanish',
    'sv': 'swedish',
    'zh_tw': 'tchinese',
    'th': 'thai',
    'tr': 'turkish',
    'uk': 'ukrainian',
    'vn': 'vietnamese',
}


class UIFormatter(string.Formatter):
    """Alters field formatting to use babel's locale-sensitive format functions."""
    def __init__(self, lang_code: str) -> None:
        self.locale = _get_locale(lang_code)

    def format_field(self, value: Any, format_spec: str) -> Any:
        """Format a field."""
        if isinstance(value, (int, float)):
            if not format_spec:
                # This is the standard format for this language.
                format_spec = self.locale.decimal_formats[None]
            return format_decimal(value, format_spec, self.locale)
        if isinstance(value, datetime.datetime):
            return format_datetime(value, format_spec or 'medium', locale=self.locale)
        if isinstance(value, datetime.date):
            return format_date(value, format_spec or 'medium', self.locale)
        if isinstance(value, datetime.timedelta):
            # format_skeleton gives access to useful HH:mm:ss layouts, but it accepts a datetime.
            # So convert our delta to a datetime - the format string should just ignore the date
            # part.
            if value.days > 0:
                raise ValueError("This doesn't work for durations over a day.")
            sec = float(value.seconds)
            mins, sec = divmod(sec, 60.0)
            hours, mins = divmod(mins, 60.0)
            return format_skeleton(
                format_spec or 'Hms',
                datetime.time(
                    hour=round(hours), minute=round(mins), second=round(sec),
                    microsecond=value.microseconds,
                    tzinfo=datetime.timezone.utc,
                ),
                locale=self.locale,
            )
        return format(value, format_spec)


@functools.lru_cache(maxsize=1)  # Cache until it has changed.
def _get_locale(lang_code: str) -> babel.Locale:
    """Fetch the current locale."""
    try:
        return babel.Locale.parse(lang_code)
    except (babel.UnknownLocaleError, ValueError) as exc:
        LOGGER.warning('Could not find locale data for language "{}":', lang_code, exc_info=exc)
        return babel.Locale.parse('en_US')  # Should exist?


def _format_list(lang_code: str, list_kind: transtoken.ListStyle, items: List[str]) -> str:
    """Formate a list according to the locale."""
    return format_list(items, list_kind.value, _get_locale(lang_code))


transtoken.ui_format_getter = UIFormatter
transtoken.ui_list_getter = _format_list


def set_text(widget: TextWidgetT, token: TransToken) -> TextWidgetT:
    """Apply a token to the specified label/button/etc."""
    widget['text'] = str(token)
    _applied_tokens[widget] = token
    return widget


def set_win_title(win: tk.Wm, token: TransToken) -> None:
    """Set the title of a window to this token."""
    win.wm_title(str(token))
    _window_titles[win] = token


def set_menu_text(menu: tk.Menu, token: TransToken, index: str | int = 'end') -> None:
    """Apply this text to the item on the specified menu.

    By default, it is applied to the last item.
    """
    try:
        tok_map = _applied_menu_tokens[menu]
    except KeyError:
        tok_map = _applied_menu_tokens[menu] = {}
    ind = menu.index(index)
    menu.entryconfigure(ind, label=str(token))
    tok_map[ind] = token


def clear_stored_menu(menu: 'tk.Menu') -> None:
    """Clear the tokens for the specified menu."""
    _applied_menu_tokens.pop(menu, None)


def add_callback(*, call: bool) -> Callable[[CBackT], CBackT]:
    """Register a function which is called after translations are reloaded.

    This should be used to re-apply tokens in complicated situations after languages change.
    If call is true, the function will immediately be called to apply it now.
    """
    def deco(func: CBackT) -> CBackT:
        """Register when called as a decorator."""
        _langchange_callback.append(func)
        LOGGER.debug('Add lang callback: {!r}, {} total', func, len(_langchange_callback))
        if call:
            func()
        return func
    return deco


def expand_langcode(lang_code: str) -> list[str]:
    """If a language is a lang/country specific code like en_AU, return that and the generic version."""
    expanded = [lang_code.casefold()]
    if '_' in lang_code:
        expanded.append(lang_code[:lang_code.index('_')].casefold())
    return expanded


def get_lang_name(lang: Language) -> str:
    """Fetch the name of this language from the Unicode Common Locale Data Repository.

     This shows the name of the language both in its own language and the current one.
     This does NOT get affected by the dummy lang, so users can swap back.
     """
    if lang is DUMMY:
        # Fake langauge code for debugging, no need to translate.
        return '<DUMMY>'

    if transtoken.CURRENT_LANG is DUMMY:
        # Use english in lang code mode.
        cur_lang = 'en_au'
    else:
        cur_lang = transtoken.CURRENT_LANG.lang_code

    targ_langs = expand_langcode(lang.lang_code)
    cur_langs = expand_langcode(cur_lang)

    # Try every combination of country/generic language.
    # First the language in its own language.
    for targ, key in itertools.product(targ_langs, targ_langs):
        try:
            name_in_lang = load_cldr(targ)['languages'][targ]
            break
        except (KeyError, FileNotFoundError):
            pass
    else:
        LOGGER.warning('No name in database for "{}"', lang.lang_code)
        name_in_lang = lang.lang_code  # Use the raw lang code.

    # Then it translated in the current language.
    for cur, targ in itertools.product(cur_langs, targ_langs):
        try:
            name_in_cur = load_cldr(cur)['languages'][targ]
            break
        except (KeyError, FileNotFoundError):
            pass
    else:
        LOGGER.warning(
            'No name in database for "{}" in "{}"',
            lang.lang_code, cur_lang,
        )
        # Just return the name we have.
        return name_in_lang

    if name_in_lang == name_in_cur:
        return name_in_lang
    else:
        return f'{name_in_lang} ({name_in_cur})'


def find_basemodui(games: list[gameMan.Game], langs: list[str]) -> str:
    """Load basemodui.txt from Portal 2, to provide translations for the default items."""
    # Check Portal 2 first, others might not be fully correct?
    games.sort(key=lambda gm: gm.steamID != '620')

    for lang in langs:
        try:
            game_lang = STEAM_LANGS[lang.casefold()]
            break
        except KeyError:
            pass
    else:
        game_lang = ''

    for game in games:
        if game_lang:
            loc = game.abs_path(BASEMODUI_PATH.format(game_lang))
            LOGGER.debug('Checking lang "{}"', loc)
            if os.path.exists(loc):
                return loc
        # Fall back to configured language.
        game_lang = game.get_game_lang()
        if game_lang:
            loc = game.abs_path(BASEMODUI_PATH.format(game_lang))
            LOGGER.debug('Checking lang "{}"', loc)
            if os.path.exists(loc):
                return loc

    # Nothing found, pick first english copy.
    for game in games:
        loc = game.abs_path(BASEMODUI_PATH.format('english'))
        LOGGER.debug('Checking lang "{}"', loc)
        if os.path.exists(loc):
            return loc
    return ''  # Failed.


def parse_basemodui(result: dict[str, str], data: bytes) -> None:
    """Parse the basemodui keyvalues file."""
    # This file is in keyvalues format, supposedly.
    # But it's got a bunch of syntax errors - extra quotes,
    # missing brackets.
    # The structure doesn't matter, so just process line by line.
    # Also operate on the raw bytes, because the line endings are sometimes ASCII-style, not UTF16!
    # We instead parse each key/value pair individually.
    for line in data.splitlines():
        key_byte: bytes
        try:
            __, key_byte, __, value, __ = line.split(b'"\x00')
        except ValueError:
            continue
        key = key_byte.decode('utf_16_le')
        # Ignore non-puzzlemaker keys.
        if key.startswith(PETI_KEY_PREFIX):
            result[key] = value.decode('utf_16_le').replace("\\'", "'")


def setup(conf_lang: str) -> None:
    """Setup localisations."""
    # Get the 'en_US' style language code
    lang_code, encoding = locale.getlocale()

    if conf_lang:
        lang_code = conf_lang

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    if lang_code is None:
        lang_code = 'en'

    expanded_langs = expand_langcode(lang_code)

    LOGGER.info('Language: {!r}', lang_code)
    LOGGER.debug('Language codes: {!r}', expanded_langs)

    for lang in expanded_langs:
        filename = FOLDER / (lang + '.mo')
        try:
            file = open(filename, 'rb')
        except FileNotFoundError:
            continue
        with file:
            translator = gettext_mod.GNUTranslations(file)
        language = Language(
            lang_code=lang_code,
            ui_filename=filename,
            trans={NS_UI: translator},
        )
        break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            language = DUMMY
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                LOGGER.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            language = Language(lang_code='en', trans={})

    set_language(language)


def get_languages() -> Iterator[Language]:
    """Load all languages we have available."""
    for filename in FOLDER.iterdir():
        if filename.suffix != '.mo':  # Ignore POT and PO sources.
            continue
        try:
            with filename.open('rb') as f:
                translator = gettext_mod.GNUTranslations(f)
        except (IOError, OSError):
            LOGGER.warning('Could not parse "{}"', filename, exc_info=True)
            continue
        yield Language(
            # Special case, hardcode this name since this is the template and will produce the token.
            lang_code=translator.info().get('Language', filename.stem),
            ui_filename=filename,
            trans={NS_UI: translator},
        )


def set_language(lang: Language) -> None:
    """Change the app's language."""
    PARSE_CANCEL.cancel()
    transtoken.CURRENT_LANG = lang

    conf = config.APP.get_cur_conf(GenOptions)
    config.APP.store_conf(attrs.evolve(conf, language=lang.lang_code))

    # Reload all our localisations.
    for text_widget, token in _applied_tokens.items():
        text_widget['text'] = str(token)
    for menu, menu_map in _applied_menu_tokens.items():
        for index, token in menu_map.items():
            menu.entryconfigure(index, label=str(token))
    for window, token in _window_titles.items():
        window.wm_title(str(token))
    for func in _langchange_callback:
        func()


async def rebuild_app_langs() -> None:
    """Compile .po files for the app into .mo files. This does not extract tokens, that needs source."""
    def build_file(filename: Path) -> None:
        """Synchronous I/O code run as a background thread."""
        with filename.open('rb') as src:
            catalog = read_po(src, locale=filename.stem)
        with filename.with_suffix('.mo').open('wb') as dest:
            write_mo(dest, catalog)

    async def build_lang(filename: Path) -> None:
        """Taks run to compile each file simultaneously."""
        try:
            await trio.to_thread.run_sync(build_file, fname)
        except (IOError, OSError):
            LOGGER.warning('Could not convert "{}"', filename, exc_info=True)
        else:
            LOGGER.info('Converted "{}"', filename)

    async with trio.open_nursery() as nursery:
        for fname in FOLDER.iterdir():
            if fname.suffix == '.po':
                nursery.start_soon(build_lang, fname)
    tk_tools.showinfo(TransToken.ui('BEEMod'), TransToken.ui('UI Translations rebuilt.'))


async def load_aux_langs(
    games: Iterable[gameMan.Game],
    packset: packages.PackagesSet,
    lang: Language = None,
) -> None:
    """Load all our non-UI translation files in the background.

    We already loaded the UI langs to create Language.
    """
    global PARSE_CANCEL
    PARSE_CANCEL.cancel()  # Stop any other in progress loads.

    if lang is None:
        lang = transtoken.CURRENT_LANG

    if lang is DUMMY:
        # Dummy does not need to load these files.
        set_language(lang)
        return

    # Preserve only the UI translations.
    lang_map: dict[str, transtoken.GetText] = {}
    try:
        # noinspection PyProtectedMember
        lang_map[NS_UI] = lang._trans[NS_UI]
    except KeyError:
        # Should always be there, perhaps this is early initialisation, dummy lang, error etc.
        # Continue to load, will likely just produce errors and fall back but that's fine.
        LOGGER.warning('Loading lang "{}" which has no UI translations!', lang.lang_code)

    # The parsed game translations.
    game_dict: dict[str, str] = {}

    # Expand to a generic country code.
    expanded = expand_langcode(lang.lang_code)

    async def package_lang(pak_id: str, fsys: FileSystem) -> None:
        """Load the package language in the background."""
        for code in expanded:
            try:
                file = fsys[f'resources/i18n/{code}.mo']
            except FileNotFoundError:
                continue
            LOGGER.debug('Found localisation file {}:{}', pak_id, file.path)
            try:
                with file.open_bin() as f:
                    lang_map[pak_id] = await trio.to_thread.run_sync(gettext_mod.GNUTranslations, f)
                return
            except (OSError, UnicodeDecodeError) as exc:
                LOGGER.warning('Invalid localisation file {}:{}', pak_id, file.path, exc_info=exc)

    async def game_lang(game_it: Iterable[gameMan.Game], expanded_langs: list[str]) -> None:
        """Load the game language in the background."""
        basemod_loc = find_basemodui(list(game_it), expanded_langs)
        if not basemod_loc:
            LOGGER.warning('Could not find BaseModUI file for Portal 2!')
            return
        try:
            # BaseModUI files are encoded in UTF-16. But it's kinda broken, with line endings
            # sometimes 1-char long.
            data = await trio.Path(basemod_loc).read_bytes()
            await trio.to_thread.run_sync(parse_basemodui, game_dict, data)
        except FileNotFoundError:
            LOGGER.warning('BaseModUI file "{}" does not exist!', basemod_loc)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            LOGGER.warning('Invalid BaseModUI file "{}"', basemod_loc, exc_info=exc)

    with trio.CancelScope() as PARSE_CANCEL:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(game_lang, games, expanded)
            for pack in packset.packages.values():
                nursery.start_soon(package_lang, pack.id, pack.fsys)
    # We're not canceled, replace the global language with our new translations.
    set_language(attrs.evolve(lang, trans=lang_map, game_trans=game_dict))


async def get_package_tokens(packset: packages.PackagesSet) -> AsyncIterator[TransTokenSource]:
    """Get all the tokens from all packages."""
    for pack in packset.packages.values():
        yield pack.disp_name, 'package/name'
        yield pack.desc, 'package/desc'
    for obj_type in packset.objects:
        LOGGER.debug('Checking object type {}', obj_type.__name__)
        for obj in packset.all_obj(obj_type):
            for tup in obj.iter_trans_tokens():
                yield tup
            await trio.lowlevel.checkpoint()


def _get_children(tok: TransToken) -> Iterator[TransToken]:
    """If this token has children, yield those."""
    yield tok
    for val in tok.parameters.values():
        if isinstance(val, TransToken):
            yield from _get_children(val)


async def rebuild_package_langs(packset: packages.PackagesSet) -> None:
    """Write out POT templates for unzipped packages."""
    tok2pack: dict[str | tuple[str, str], set[str]] = defaultdict(set)
    pack_paths: dict[str, tuple[trio.Path, Catalog]] = {}

    for pak_id, pack in packset.packages.items():
        if isinstance(pack.fsys, RawFileSystem):
            pack_paths[pak_id.casefold()] = trio.Path(pack.path, 'resources', 'i18n'), Catalog(
                project=pack.disp_name.token,
                version=utils.BEE_VERSION,
            )

    LOGGER.info('Collecting translations...')
    async for orig_tok, source in get_package_tokens(packset):
        for tok in _get_children(orig_tok):
            if not tok:
                continue  # Ignore blank tokens, not important to translate.
            try:
                pack_path, catalog = pack_paths[tok.namespace.casefold()]
            except KeyError:
                continue
            # Line number is just zero - we don't know which lines these originated from.
            if tok.namespace.casefold() != tok.orig_pack.casefold():
                # Originated from a different package, include that.
                loc = [(f'{tok.orig_pack}:{source}', 0)]
            else:  # Omit, most of the time.
                loc = [(source, 0)]

            if isinstance(tok, PluralTransToken):
                catalog.add((tok.token, tok.token_plural), locations=loc)
                tok2pack[tok.token, tok.token_plural].add(tok.namespace)
            else:
                catalog.add(tok.token, locations=loc)
                tok2pack[tok.token].add(tok.namespace)

    for pak_id, (pack_path, catalog) in pack_paths.items():
        LOGGER.info('Exporting translations for {}...', pak_id.upper())
        await pack_path.mkdir(parents=True, exist_ok=True)
        catalog.header_comment = PACKAGE_HEADER
        with open(pack_path / 'en.pot', 'wb') as f:
            write_po(f, catalog, include_previous=True, sort_output=True, width=120)
        for lang_file in await pack_path.iterdir():
            if lang_file.suffix != '.po':
                continue
            data = await lang_file.read_text()
            existing: Catalog = read_po(io.StringIO(data))
            existing.update(catalog)
            catalog.header_comment = PACKAGE_HEADER
            existing.version = utils.BEE_VERSION
            LOGGER.info('- Rewriting {}', lang_file)
            with open(lang_file, 'wb') as f:
                write_po(f, existing, sort_output=True, width=120)
            with open(lang_file.with_suffix('.mo'), 'wb') as f:
                write_mo(f, existing)

    LOGGER.info('Repeated tokens:\n{}', '\n'.join([
        f'{", ".join(sorted(tok_pack))} -> {token!r} '
        for (token, tok_pack) in
        sorted(tok2pack.items(), key=lambda t: len(t[1]), reverse=True)
        if len(tok_pack) > 1
    ]))
