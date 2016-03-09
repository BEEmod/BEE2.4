from enum import Enum

from markdown.util import etree
from markdown.preprocessors import Preprocessor
import markdown

import utils

LOGGER = utils.getLogger(__name__)

# These tags if present simply add a TK tag.
SIMPLE_TAGS = {
    'u': ('underline',),
    'strong': ('bold',),
    'em': ('italic',),
    # Blockquotes become white-on-black text
    'blockquote': ('invert',),
    'li': ('indent', ),
}

UL_START = '\u2022 '
OL_START = '{}. '
HRULE_TEXT = ('\n ', ('hrule', ))


class TAG(Enum):
    START = 0
    END = 1


def iter_elemtext(elem: etree.Element, parent_path=()):
    """Flatten out an elementTree into the text parts.

    Yields path, text tuples. path is a list of the parent elements for the
    text. Text is either the text itself, with '' for < />-style tags, or
    TAG.START/END to match the beginning and end of tag blocks.
    """
    path = list(parent_path) + [elem]

    yield path, TAG.START

    if elem.text is None:
        yield path, ''
    else:
        yield path, elem.text.replace('\n', '')

    for child in elem:
        yield from iter_elemtext(child, path)

    yield path, TAG.END

    if elem.tail is not None:  # Text after this element..
        yield parent_path, elem.tail.replace('\n', '')


def parse_html(element):
    """Translate markdown HTML into TK tags."""
    ol_nums = []

    for path, text in iter_elemtext(element, parent_path=[element]):
        last = path[-1]

        if last.tag == 'div':
            continue  # This wraps around the entire block..

        # Line breaks at <br> or at the end of <p> blocks.
        if last.tag == 'br' or (last.tag == 'p' and text is TAG.END):
            yield '\n', ()
            continue

        # Insert the number or bullet
        if last.tag == 'li' and text is TAG.START:
            list_type = path[-2].tag
            if list_type == 'ul':
                yield UL_START, ('list_start', 'indent')
            elif list_type == 'ol':
                ol_nums[-1] += 1
                yield OL_START.format(ol_nums[-1]), ('list_start', 'indent')

        if last.tag == 'li' and text is TAG.END:
            yield '\n', ('indent')

        if last.tag == 'ol':
            # Set and reset the counter appropriately..
            if text is TAG.START:
                ol_nums.append(0)
            if text is TAG.END:
                ol_nums.pop()

        if isinstance(text, TAG) or not text:
            # Don't output these internal values.
            continue

        tk_tags = []
        for tag in {elem.tag for elem in path}:
            # Simple tags are things like strong, u - no additional value.
            if tag in SIMPLE_TAGS:
                tk_tags.extend(SIMPLE_TAGS[tag])
        yield text, tuple(tk_tags)


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
        # We can't directly return the list, since it'll break Markdown.
        # Return an empty document and save it elsewhere.
        self.result = list(parse_html(element))

        # Remove a bare \n at the end of the description
        if self.result and self.result[-1][0] == '\n':
            self.result.pop()

        # StripTopLevelTags expects doc_tag in the output,
        # so give it an empty one.
        return '<{0}></{0}>'.format(self.md.doc_tag)


# Reuse one instance for the conversions.
_converter = TKConverter()
_MD = markdown.Markdown(extensions=[_converter])


def convert(text):
    _MD.reset()
    _MD.convert(text)
    return _converter.result
