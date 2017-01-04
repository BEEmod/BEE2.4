from enum import Enum
from itertools import count

from markdown.util import etree
from markdown.extensions import smart_strong, sane_lists
from markdown.preprocessors import Preprocessor
import markdown

import utils

LOGGER = utils.getLogger(__name__)

# These tags if present simply add a TK tag.
SIMPLE_TAGS = {
    'u': 'underline',
    'strong': 'bold',
    'em': 'italic',
    # Blockquotes become white-on-black text
    'blockquote': 'invert',
    'li': 'indent',

    # The parser will already split these into their own line,
    # add paragraphs - we just increase font size.
    'h1': 'heading_1',
    'h2': 'heading_2',
    'h3': 'heading_3',
    'h4': 'heading_4',
    'h5': 'heading_5',
    'h6': 'heading_6',
}

UL_START = '\u2022 '
OL_START = '{}. '
HRULE_TEXT = ('\n ', ('hrule', ))

LINK_TAG_START = 'link_callback_'

class TAG(Enum):
    START = 0
    END = 1


class MarkdownData:
    """The output of the conversion, a set of tags and link references for callbacks.

    Tags is a tuple of alternating strings and tag tuples.
    links is a dict mapping urls to callback IDs.
    """
    def __init__(self, tags=(), links=None):
        self.tags = tuple(tags)
        self.links = links if links is not None else {}

    def __bool__(self):
        """Empty data is false."""
        return bool(self.tags)


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


def parse_html(element: etree.Element):
    """Translate markdown HTML into TK tags.

    This yields alternating text and tags, matching the arguments for
    Text widgets.
    The last yielded value is a tag: url dict for the embedded hyperlinks.
    """
    ol_nums = []
    links = {}
    link_counter = count(start=1)

    for path, text in iter_elemtext(element, parent_path=[element]):
        last = path[-1]

        if last.tag == 'div':
            continue  # This wraps around the entire block..

        # Line breaks at <br> or at the end of <p> blocks.
        # <br> emits a START, '', and END - we only want to output for one
        # of those.
        if last.tag in ('br', 'p') and text is TAG.END:
            yield '\n'
            yield ()
            continue

        # Insert the number or bullet
        if last.tag == 'li' and text is TAG.START:
            list_type = path[-2].tag
            if list_type == 'ul':
                yield UL_START
                yield ('list_start', 'indent')
            elif list_type == 'ol':
                ol_nums[-1] += 1
                yield OL_START.format(ol_nums[-1])
                yield ('list_start', 'indent')

        if last.tag == 'li' and text is TAG.END:
            yield '\n'
            yield ('indent', )

        if last.tag == 'ol':
            # Set and reset the counter appropriately..
            if text is TAG.START:
                ol_nums.append(0)
            if text is TAG.END:
                ol_nums.pop()

        if isinstance(text, TAG) or not text:
            # Don't output these internal values.
            continue

        force_return = False

        tk_tags = set()
        for tag in {elem.tag for elem in path}:
            # Simple tags are things like strong, u - no additional value.
            if tag in SIMPLE_TAGS:
                to_add = SIMPLE_TAGS[tag]
                if isinstance(to_add, str):
                    tk_tags.add(to_add)
                else:
                    tk_tags.update(to_add)
            if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                force_return = True

        # Handle links.
        for elem in path:
            if elem.tag != 'a':
                continue
            try:
                url = elem.attrib['href']
            except KeyError:
                continue  # We don't handle anchor a-tags.
            try:
                url_id = links[url]
            except KeyError:
                url_id = links[url] = LINK_TAG_START + str(next(link_counter))
            tk_tags.add('link')  # For formatting
            tk_tags.add(url_id)  # For the click-callback.

        yield text
        yield tuple(tk_tags)

        if force_return:
            yield '\n'
            yield ()

    yield links


class TKConverter(markdown.Extension, Preprocessor):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self, *args, **kwargs):
        self.result = MarkdownData()
        self.md = None  # type: markdown.Markdown
        super().__init__(*args, **kwargs)

    def extendMarkdown(self, md: markdown.Markdown, md_globals):
        self.md = md
        md.registerExtension(self)
        md.preprocessors.add('TKConverter', self, '_end')

    def reset(self):
        self.result = MarkdownData()

    def run(self, lines):
        # Set the markdown class to use our serialiser when run..
        self.md.serializer = self.serialise

        return lines  # And don't modify the text..

    def serialise(self, element: etree.Element):
        """Override Markdown's serialising program so it returns our format instead of HTML.

        """
        # We can't directly return the list, since it'll break Markdown.
        # Return an empty document and save it elsewhere.

        parsed_tags = list(parse_html(element))
        # The last yielded value is the dictionary of URL link keys.
        # Pop that off.
        links = parsed_tags.pop()

        # Remove a bare \n at the end of the description
        # It's followed by the tag.
        if parsed_tags and parsed_tags[-2:-1] == ['\n', ()]:
            parsed_tags.pop()
            parsed_tags.pop()

        self.result = MarkdownData(
            parsed_tags,
            links,
        )

        # StripTopLevelTags expects doc_tag in the output,
        # so give it an empty one.
        return '<{0}></{0}>'.format(self.md.doc_tag)


# Reuse one instance for the conversions.
_converter = TKConverter()
_MD = markdown.Markdown(extensions=[
    _converter,
    smart_strong.SmartEmphasisExtension(),
    sane_lists.SaneListExtension(),
])


def convert(text: str) -> MarkdownData:
    """Convert markdown syntax into data ready to be passed to richTextBox."""
    _MD.reset()
    _MD.convert(text)
    return _converter.result


def join(*args: MarkdownData) -> MarkdownData:
    """Join several text blocks together.

    This merges together blocks, reassigning link callbacks as needed.
    """
    # If no tags are present, a block is empty entirely.
    # Skip processing empty blocks.
    to_join = list(filter(None, args))

    if len(to_join) == 1:
        # We only have one block, just copy and return.
        return MarkdownData(
            to_join[0].tags,
            to_join[0].links.copy(),
        )

    link_ind = 0
    combined_links = {}
    new_text = []
    old_to_new = {}  # Maps original callback to new callback
    for data in to_join:
        tags = data.tags
        links = data.links

        old_to_new.clear()

        # First find any links in the tags..
        for url, call_name in links.items():
            if url not in combined_links:
                link_ind += 1
                old_to_new[call_name] = combined_links[url] = LINK_TAG_START + str(link_ind)

        for tag_text in tags:
            if isinstance(tag_text, str):  # Text to display
                new_text.append(tag_text)
                continue
            new_tag = []
            for tag in tag_text:
                if tag.startswith(LINK_TAG_START):
                    # Replace with the new tag we've set.
                    new_tag.append(old_to_new[tag])
                else:
                    new_tag.append(tag)
            new_text.append(tuple(new_tag))
    return MarkdownData(new_text, combined_links)
