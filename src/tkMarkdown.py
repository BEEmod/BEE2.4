from enum import Enum

from markdown.util import etree
from markdown.preprocessors import Preprocessor
from markdown.serializers import to_html_string
import markdown

import utils

LOGGER = utils.getLogger(__name__)

# These tags if present simply add a TK tag.
SIMPLE_TAGS = {
    'u': 'underline',
    'strong': 'bold',
    'em': 'italic',
}

UL_FORMAT = '\u2022 {}\n'
OL_FORMAT = '{i}. {}\n'
HRULE_TEXT = ('\n ', ('hrule', ))

class TAG(Enum):
    START = 0
    END = 1


def iter_elemtext(elem: etree.Element, parent_path=()):
    """Flatten out an elementTree into the text parts.

    Yields path, text tuples. path is a list of the parent elements for the
    text. Text is the text itself, with '' for < />-style tags
    """
    path = list(parent_path) + [elem]

    yield path, TAG.START

    if elem.text is None:
        yield path, ''
    else:
        yield path, elem.text

    for child in elem:
        yield from iter_elemtext(child, path)

    yield path, TAG.END

    if elem.tail is not None:  # Text after this element..
        yield parent_path, elem.tail


def parse_html(element):
    """Translate markdown HTML into TK tags."""
        yield text, ()


class TKConverter(markdown.Extension, Preprocessor):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self, *args, **kwargs):
        self.result = []
        self.md = None  # type: markdown.Markdown
        super().__init__(*args, **kwargs)

    def extendMarkdown(self, md: markdown.Markdown, md_globals):
        self.md = md
        md.registerExtension(self)
        md.preprocessors.add('TKConverter', self, '_end')

    def reset(self):
        self.result = []

    def run(self, lines):
        # Set the markdown class to use our serialiser when run..
        self.md.serializer = self.serialise

        return lines  # And don't modify the text..

    def serialise(self, element: etree.Element):
        self.result = list(parse_html(element))
        # We can't directly return the list, since it'll break Markdown.
        # Return an empty document and save it elsewhere.

        # StripTopLevelTags expects something, so give it <div></div>.
        LOGGER.info('HTML: {}', to_html_string(element))
        return '<{0}></{0}>'.format(self.md.doc_tag)

# Reuse one instance for the conversions.
_converter = TKConverter()
_MD = markdown.Markdown(extensions=[_converter])


def convert(text):
    _MD.reset()
    _MD.convert(text)
    return _converter.result
