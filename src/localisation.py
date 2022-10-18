"""Wraps gettext, to localise all UI text."""
from typing import Callable
from typing_extensions import ParamSpec
import gettext as gettext_mod
import locale
import logging
import sys
import builtins
import warnings

from srctools.property_parser import PROP_FLAGS_DEFAULT
import utils

_TRANSLATOR = gettext_mod.NullTranslations()
P = ParamSpec('P')


class DummyTranslations(gettext_mod.NullTranslations):
    """Dummy form for identifying missing translation entries."""

    def gettext(self, message: str) -> str:
        """Generate placeholder of the right size."""
        # We don't want to leave {arr} intact.
        return ''.join([
            '#' if s.isalnum() or s in '{}' else s
            for s in message
        ])

    def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
        """Generate placeholder of the right size for plurals."""
        return self.gettext(msgid1 if n == 1 else msgid2)

    lgettext = gettext
    lngettext = ngettext


def gettext(message: str) -> str:
    """Translate the given string."""
    return _TRANSLATOR.gettext(message)


def ngettext(msg_sing: str, msg_plural: str, count: int) -> str:
    """Translate the given string, with the count to allow plural forms."""
    return _TRANSLATOR.ngettext(msg_sing, msg_plural, count)


def setup(logger: logging.Logger) -> None:
    """Setup gettext localisations."""
    global _TRANSLATOR
    # Get the 'en_US' style language code
    lang_code = locale.getdefaultlocale()[0]

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    # Expands single code to parent categories.
    expanded_langs = gettext_mod._expand_lang(lang_code)

    logger.info('Language: {!r}', lang_code)
    logger.debug('Language codes: {!r}', expanded_langs)

    # Add these to Property's default flags, so config files can also
    # be localised.
    for lang in expanded_langs:
        PROP_FLAGS_DEFAULT['lang_' + lang] = True

    lang_folder = utils.install_path('i18n')

    for lang in expanded_langs:
        try:
            file = open(lang_folder / (lang + '.mo').format(lang), 'rb')
        except FileNotFoundError:
            continue
        with file:
            _TRANSLATOR = gettext_mod.GNUTranslations(file)
            break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            _TRANSLATOR = DummyTranslations()
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                logger.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            _TRANSLATOR = gettext_mod.NullTranslations()

    def warn_translate(name: str, func: Callable[P, str]):
        """Raise a deprecation warning when this is used from builtins."""
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
            """Raise and call the origina."""
            warnings.warn(
                f"Translation function {name}() called from builtins!",
                DeprecationWarning, stacklevel=2,
            )
            return func(*args, **kwargs)
        setattr(builtins, '_', wrapper)

    # Add functions to builtins, but deprecated.
    warn_translate('_', _TRANSLATOR.gettext)
    warn_translate('gettext', _TRANSLATOR.gettext)
    warn_translate('ngettext', _TRANSLATOR.ngettext)

    # Some lang-specific overrides..

    if gettext('__LANG_USE_SANS_SERIF__') == 'YES':
        # For Japanese/Chinese, we want a 'sans-serif' / gothic font
        # style.
        try:
            from tkinter import font
        except ImportError:
            return
        font_names = [
            'TkDefaultFont',
            'TkHeadingFont',
            'TkTooltipFont',
            'TkMenuFont',
            'TkTextFont',
            'TkCaptionFont',
            'TkSmallCaptionFont',
            'TkIconFont',
            # Note - not fixed-width...
        ]
        for font_name in font_names:
            font.nametofont(font_name).configure(family='sans-serif')
