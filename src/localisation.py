"""Wraps gettext, to localise all UI text."""
import gettext
import locale
import logging
import sys

from srctools.property_parser import PROP_FLAGS_DEFAULT
import utils


class DummyTranslations(gettext.NullTranslations):
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


def setup(logger: logging.Logger) -> None:
    """Setup gettext localisations."""
    # Get the 'en_US' style language code
    lang_code = locale.getdefaultlocale()[0]

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    # Expands single code to parent categories.
    expanded_langs = gettext._expand_lang(lang_code)

    logger.info('Language: {!r}', lang_code)
    logger.debug('Language codes: {!r}', expanded_langs)

    # Add these to Property's default flags, so config files can also
    # be localised.
    for lang in expanded_langs:
        PROP_FLAGS_DEFAULT['lang_' + lang] = True

    lang_folder = utils.install_path('i18n')

    trans: gettext.NullTranslations

    for lang in expanded_langs:
        try:
            file = open(lang_folder / (lang + '.mo').format(lang), 'rb')
        except FileNotFoundError:
            continue
        with file:
            trans = gettext.GNUTranslations(file)
            break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            trans = DummyTranslations()
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                logger.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            trans = gettext.NullTranslations()

    # Add these functions to builtins, plus _=gettext
    trans.install(['gettext', 'ngettext'])

    # Some lang-specific overrides..

    if trans.gettext('__LANG_USE_SANS_SERIF__') == 'YES':
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
