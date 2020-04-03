"""Wrapper around the markdown module, converting it to display in TKinter widgets.

This produces a stream of values, which are fed into richTextBox to display.
"""
from enum import Enum
from itertools import count

from xml.etree.ElementTree import Element as XMLElement
from markdown.extensions.sane_lists import SaneListExtension
from markdown.preprocessors import Preprocessor
import markdown
import srctools.logger

from typing import Iterable, Iterator, Union, List, Tuple, Optional, Any, Dict


LOGGER = srctools.logger.get_logger(__name__)

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

LINK_TAG_START = 'link_callback_'


class TAG(Enum):
    """Marker used to indicate when tags start/end."""
    START = 0
    END = 1


class BlockTags(Enum):
    """The various kinds of blocks that can happen."""
    # Paragraphs of regular text or other stuff we can insert.
    # The data is alternating text, tag-tuples suitable to pass
    # to Text.insert().
    TEXT = 'text'
    # An image, data is the file path.
    IMAGE = 'image'


class MarkdownData:
    """The output of the conversion, a set of tags and link references for callbacks.

    Blocks are a list of two-tuples - each is a Block type, and data for it.
    Links is a dict mapping urls to callback IDs.
    """
    def __init__(
        self,
        blocks: Iterable[Tuple[BlockTags, Any]] = (),
        links: Dict[str, str] = None,
    ) -> None:
        self.blocks = list(blocks)
        self.links = links if links is not None else {}

    def __bool__(self) -> bool:
        """Empty data is false."""
        return bool(self.blocks)

    def copy(self) -> 'MarkdownData':
        """Create and return a duplicate of this object."""
        return MarkdownData(self.blocks, self.links.copy())

    __copy__ = copy


def iter_elemtext(
    elem: XMLElement,
    parent_path: Iterable[XMLElement]=(),
) -> Iterator[Tuple[List[XMLElement], Union[str, TAG]]]:
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

    # Text after this element..
    # Do not return if we are the root element - "</div>\n"
    if elem.tail is not None and parent_path:
        yield parent_path, elem.tail.replace('\n', '')


def parse_html(element: XMLElement):
    """Translate markdown HTML into TK tags.

    This returns lists of alternating text and tags, matching the arguments for
    Text widgets.
    This also returns a tag: url dict for the embedded hyperlinks.
    """
    ol_nums = []
    links = {}
    link_counter = count(start=1)
    force_return = False

    blocks = []
    cur_text_block = []

    def finish_text_block():
        """Copy the cur_text_block into blocks ready for another type."""
        if cur_text_block:
            blocks.append((BlockTags.TEXT, tuple(cur_text_block)))
            cur_text_block.clear()

    for path, text in iter_elemtext(element, parent_path=[]):
        last = path[-1]

        if last.tag == 'div':
            continue  # This wraps around the entire block..

        # We need to insert a return after <p> or <br>, but only if
        # the next block is empty.
        if force_return:
            force_return = False
            cur_text_block.append('\n')
            cur_text_block.append(())

        # Line breaks at <br> or at the end of <p> blocks.
        # <br> emits a START, '', and END - we only want to output for one
        # of those.
        if last.tag in ('br', 'p') and text is TAG.END:
            cur_text_block.append('\n')
            cur_text_block.append(())
            continue

        # Insert the number or bullet
        if last.tag == 'li' and text is TAG.START:
            list_type = path[-2].tag
            if list_type == 'ul':
                cur_text_block.append(UL_START)
                cur_text_block.append(('list_start', 'indent'))
            elif list_type == 'ol':
                ol_nums[-1] += 1
                cur_text_block.append(OL_START.format(ol_nums[-1]))
                cur_text_block.append(('list_start', 'indent'))

        if last.tag == 'hr' and text == '':
            cur_text_block.extend((
                '\n', (),
                '\n', ('hrule', ),
                '\n', (),
            ))

        if last.tag == 'li' and text is TAG.END:
            cur_text_block.append('\n')
            cur_text_block.append(('indent', ))

        if last.tag == 'ol':
            # Set and reset the counter appropriately..
            if text is TAG.START:
                ol_nums.append(0)
            if text is TAG.END:
                ol_nums.pop()

        if last.tag == 'img' and not text:
            # Add the image - it's own block type.
            finish_text_block()
            blocks.append((BlockTags.IMAGE, last.attrib['src']))

        if isinstance(text, TAG) or not text:
            # Don't output these internal values.
            continue

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

        cur_text_block.append(text)
        cur_text_block.append(tuple(tk_tags))

    # Finish our last block.
    finish_text_block()

    return blocks, links


class TKConverter(markdown.Extension, Preprocessor):
    """Extension needed to extract our list from the tree.
    """
    def __init__(self, *args, **kwargs) -> None:
        self.result = MarkdownData()
        self.md: Optional[markdown.Markdown] = None
        super().__init__(*args, **kwargs)

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        """Applies the extension to Markdown."""
        self.md = md
        md.registerExtension(self)
        md.preprocessors.add('TKConverter', self, '_end')

    def reset(self) -> None:
        """Clear out our data for the next run."""
        self.result = MarkdownData()

    def run(self, lines: List[str]) -> List[str]:
        """Set the markdown class to use our serialiser when run."""
        self.md.serializer = self.serialise

        return lines  # And don't modify the text..

    def serialise(self, element: XMLElement):
        """Override Markdown's serialising program so it returns our format instead of HTML.

        """
        # We can't directly return the list, since it'll break Markdown.
        # Return an empty document and save it elsewhere.

        blocks, links = parse_html(element)

        self.result = MarkdownData(
            blocks,
            links,
        )

        # StripTopLevelTags expects doc_tag in the output,
        # so give it an empty one.
        return '<{0}></{0}>'.format(self.md.doc_tag)


# Reuse one instance for the conversions.
_converter = TKConverter()
_MD = markdown.Markdown(extensions=[
    _converter,
    SaneListExtension(),
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
            to_join[0].blocks,
            to_join[0].links.copy(),
        )

    link_ind = 0
    combined_links = {}
    new_blocks = []
    old_to_new = {}  # Maps original callback to new callback
    for data in to_join:
        blocks = data.blocks
        links = data.links

        old_to_new.clear()

        # First find any links in the tags..
        for url, call_name in links.items():
            if url not in combined_links:
                link_ind += 1
                old_to_new[call_name] = combined_links[url] = LINK_TAG_START + str(link_ind)

        # Modify tags to use the new links.
        for block_type, block_data in blocks:
            if block_type is not BlockTags.TEXT:
                # Other block types.
                new_blocks.append((block_type, block_data))
                continue

            new_block_data = []
            # block_type == BlockTags.TEXT
            new_blocks.append((block_type, new_block_data))
            for tag_text in block_data:
                if isinstance(tag_text, str):  # Text to display
                    new_block_data.append(tag_text)
                    continue

                new_tag = []
                for tag in tag_text:
                    if tag.startswith(LINK_TAG_START):
                        # Replace with the new tag we've set.
                        new_tag.append(old_to_new[tag])
                    else:
                        new_tag.append(tag)
                new_block_data.append(tuple(new_tag))

    return MarkdownData(new_blocks, combined_links)
