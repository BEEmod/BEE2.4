import utils

from typing import (
    Optional, Union, Any,
    Dict, List, Tuple, Iterator,
)

__all__ = ['KeyValError', 'NoKeyError', 'Property', 'INVALID']

# various escape sequences that we allow
REPLACE_CHARS = {
    r'\n':  '\n',
    r'\t':  '\t',
    '\\\\': '\\',
    r'\/':   '/',
}

# Sentinel value to indicate that no default was given to find_key()
_NO_KEY_FOUND = object()

_Prop_Value = Union[List['Property'], str]
_as_dict_return = Dict[str, Union[str, 'as_dict_return']]


class KeyValError(Exception):
    """An error that occured when parsing a Valve KeyValues file.

    mess = The error message that occured.
    file = The filename passed to Property.parse(), if it exists
    line_num = The line where the error occured.
    """
    def __init__(
            self,
            message: str,
            file: Optional[str],
            line: Optional[int]
            ) -> None:
        super().__init__()
        self.mess = message
        self.file = file
        self.line_num = line

    def __repr__(self):
        return 'KeyValError({!r}, {!r}, {!r})'.format(
            self.mess,
            self.file,
            self.line_num,
            )

    def __str__(self):
        """Generate the complete error message.

        This includes the line number and file, if avalible.
        """
        mess = self.mess
        if self.line_num:
            mess += '\nError occured on line ' + str(self.line_num)
            if self.file:
                mess += ', with file'
        if self.file:
            if not self.line_num:
                mess += '\nError occured with file'
            mess += ' "' + self.file + '"'
        return mess


class NoKeyError(Exception):
    """Raised if a key is not found when searching from find_key().

    key = The missing key that was asked for.
    """
    def __init__(self, key):
        super().__init__()
        self.key = key

    def __repr__(self):
        return 'NoKeyError({!r})'.format(self.key)

    def __str__(self):
        return "No key " + self.key + "!"


def read_multiline_value(file, line_num, filename):
    """Pull lines out until a quote character is reached."""
    lines = ['']  # We return with a beginning newline
    # Re-looping over the same iterator means we don't repeat lines
    for line_num, line in file:
        if isinstance(line, bytes):
            # Decode bytes using utf-8
            line = line.decode('utf-8')
        line = line.strip()
        if line.endswith('"'):
            lines.append(line[:-1])
            return '\n'.join(lines)
        lines.append(line)
    else:
        # We hit EOF!
        raise KeyValError(
            "Reached EOF without ending quote!",
            filename,
            line_num,
        )


class Property:
    """Represents Property found in property files, like those used by Valve.

    Value should be a string (for leaf properties), or a list of children
    Property objects.
    The name should be a string, or None for a root object.
    Root objects export each child at the topmost indent level.
        This is produced from Property.parse() calls.
    """
    # Helps decrease memory footprint with lots of Property values.
    __slots__ = ('_folded_name', 'real_name', 'value')

    def __init__(
            self: 'Property',
            name: Optional[str],
            value: _Prop_Value,
            ):
        """Create a new property instance.

        """
        self.real_name = name  # type: Optional[str]
        self.value = value  # type: _Prop_Value
        self._folded_name = (
            None if name is None
            else name.casefold()
        )  # type: Optional[str]

    @property
    def name(self) -> Optional[str]:
        """Name automatically casefolds() any given names.

        This ensures comparisons are always case-sensitive.
        Read .real_name to get the original value.
        """
        return self._folded_name

    @name.setter
    def name(self, new_name):
        self.real_name = new_name
        if new_name is None:
            self._folded_name = None
        else:
            self._folded_name = new_name.casefold()

    def edit(self, name=None, value=None):
        """Simultaneously modify the name and value."""
        if name is not None:
            self.real_name = name
            self._folded_name = name.casefold()
        if value is not None:
            self.value = value

    @staticmethod
    def parse(file_contents, filename='') -> "Property":
        """Returns a Property tree parsed from given text.

        filename, if set should be the source of the text for debug purposes.
        file_contents should be an iterable of strings
        """
        from utils import is_identifier

        file_iter = enumerate(file_contents, start=1)

        # The block we are currently adding to.

        # The special name 'None' marks it as the root property, which
        # just outputs its children when exported. This way we can handle
        # multiple root blocks in the file, while still returning a single
        # Property object which has all the methods.
        cur_block = Property(None, [])

        # A queue of the properties we are currently in (outside to inside).
        open_properties = [cur_block]
        for line_num, line in file_iter:
            if isinstance(line, bytes):
                # Decode bytes using utf-8
                line = line.decode('utf-8')
            freshline = line.strip()

            if not freshline or freshline[:2] == '//':
                # Skip blank lines and comments!
                continue

            if freshline.startswith('"'):   # data string
                line_contents = freshline.split('"')
                name = line_contents[1]
                try:
                    value = line_contents[3]
                except IndexError:  # It doesn't have a value, likely a block
                    value = None
                else:
                    # Special case - comment between name/value sections -
                    # it's a name block then.
                    if line_contents[2].lstrip().startswith('//'):
                        value = None
                        del line_contents[3:]
                    else:
                        if len(line_contents) < 5:
                            # It's a multiline value - no ending quote!
                            value += read_multiline_value(
                                file_iter,
                                line_num,
                                filename,
                            )
                        if value and '\\' in value:
                            for orig, new in REPLACE_CHARS.items():
                                value = value.replace(orig, new)
                # Line_contents[4] is the start of the comment, ensure that it's
                # blank or starts with a comment.
                if len(line_contents) >= 5:
                    comment = line_contents[4].lstrip()
                    # same as: not (comment or comment.startswith('//'))
                    if comment and not comment.startswith('//'):
                        raise KeyValError(
                            'Extra text after '
                            'line: "{}"'.format(line_contents[4]),
                            filename,
                            line_num,
                        )

                cur_block.append(Property(name, value))
            elif freshline.startswith('{'):
                # Open a new block.
                # If we're expecting a block, the value will be None.
                if cur_block[-1].value is not None:
                    raise KeyValError(
                        'Property cannot have sub-section if it already'
                        'has an in-line value.',
                        filename,
                        line_num,
                    )
                cur_block = cur_block[-1]
                cur_block.value = []
                open_properties.append(cur_block)
            elif freshline.startswith('}'):
                # Move back a block
                open_properties.pop()
                try:
                    cur_block = open_properties[-1].value
                except IndexError:
                    # No open blocks!
                    raise KeyValError(
                        'Too many closing brackets.',
                        filename,
                        line_num,
                    )

            # handle name bare on one line, will need a brace on
            # the next line
            elif is_identifier(freshline):
                cur_block.append(Property(freshline, None))
            else:
                raise KeyValError(
                    "Unexpected beginning character '"
                    + freshline[0]
                    + '"!',
                    filename,
                    line_num,
                )

        if len(open_properties) > 1:
            raise KeyValError(
                'End of text reached with remaining open sections.',
                filename,
                line=None,
            )
        return open_properties[0]

    def find_all(self, *keys) -> Iterator['Property']:
        """Search through a tree to obtain all properties that match a particular path.

        """
        depth = len(keys)
        if depth == 0:
            raise ValueError("Cannot find_all without commands!")

        targ_key = keys[0].casefold()
        for prop in self:
            if not isinstance(prop, Property):
                raise ValueError(
                    'Cannot find_all on a value that is not a Property!'
                )
            if prop._folded_name == targ_key is not None:
                if depth > 1:
                    if prop.has_children():
                        yield from Property.find_all(prop, *keys[1:])
                else:
                    yield prop

    def find_key(self, key, def_: _Prop_Value=_NO_KEY_FOUND):
        """Obtain the value of the child Property with a given name.

        - If no child is found with the given name, this will return the
          default value, or raise NoKeyError if none is provided.
        - This prefers keys located closer to the end of the value list.
        """
        key = key.casefold()
        for prop in reversed(self.value):  # type: Property
            if prop._folded_name == key:
                return prop
        if def_ is _NO_KEY_FOUND:
            raise NoKeyError(key)
        else:
            return Property(key, def_)
            # We were given a default, return it wrapped in a Property.

    def set_key(self, path, value):
        """Set the value of a key deep in the tree hierachy.

        -If any of the hierachy do not exist (or do not have children),
          blank properties will be added automatically
        - path should be a tuple of names, or a single string.
        """
        current_prop = self
        if isinstance(path, tuple):
            # Search through each item in the tree!
            for key in path[:-1]:
                folded_key = key.casefold()
                # We can't use find_key() here because we also
                # need to check that the property has chilren to search
                # through
                for prop in reversed(self.value):
                    if (prop.name is not None and
                            prop.name == folded_key and
                            prop.has_children()):
                        current_prop = prop
                        break
                else:
                    # No matching property found
                    new_prop = Property(key, [])
                    current_prop.append(new_prop)
                    current_prop = new_prop
            path = path[-1]
        try:
            current_prop.find_key(path).value = value
        except NoKeyError:
            current_prop.value.append(Property(path, value))

    def copy(self):
        """Deep copy this Property tree and return it."""
        if self.has_children():
            # This recurses if needed
            return Property(
                self.real_name,
                [
                    child.copy()
                    for child in
                    self.value
                ]
            )
        else:
            return Property(self.real_name, self.value)

    def as_dict(self):
        """Convert this property tree into a tree of dictionaries.

        This keeps only the last if multiple items have the same name.
        """
        if self.has_children():
            return {item._folded_name: item.as_dict() for item in self}
        else:
            return self.value

    def __eq__(self, other):
        """Compare two items and determine if they are equal.

        This ignores names.
        """
        if isinstance(other, Property):
            return self.value == other.value
        else:
            return self.value == other  # Just compare values

    def __ne__(self, other):
        """Not-Equal To comparison. This ignores names.
        """
        if isinstance(other, Property):
            return self.value != other.value
        else:
            return self.value != other # Just compare values

    def __lt__(self, other):
        """Less-Than comparison. This ignores names.
        """
        if isinstance(other, Property):
            return self.value < other.value
        else:
            return self.value < other

    def __gt__(self, other):
        "Greater-Than comparison. This ignores names."
        if isinstance(other, Property):
            return self.value > other.value
        else:
            return self.value > other

    def __le__(self, other):
        "Less-Than or Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return self.value <= other.value
        else:
            return self.value <= other

    def __ge__(self, other):
        "Greater-Than or Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return self.value >= other.value
        else:
            return self.value >= other

    def __len__(self):
        """Determine the number of child properties.

        Singluar Properties have a length of 1.
        """
        if self.has_children():
            return len(self.value)
        else:
            return 1

    def __iter__(self) -> Iterator['Property']:
        """Iterate through the value list.

        """
        if self.has_children():
            return iter(self.value)
        else:
            return iter((self.value,))

    def __contains__(self, key):
        """Check to see if a name is present in the children.

        If the Property has no children, this checks if the names match instead.
        """
        key = key.casefold()
        if self.has_children():
            for prop in self.value:  # type: Property
                if prop._folded_name == key:
                    return True
            return False
        else:
            return self._folded_name == key

    def __getitem__(
            self,
            index: Union[
                str,
                int,
                slice,
                Tuple[Union[str, int, slice], Union[_Prop_Value, Any]],
            ],
            ) -> str:
        """Allow indexing the children directly.

        - If given an index or slice, it will search by position.
        - If given a string, it will find the last Property with that name.
          (Default can be chosen by passing a 2-tuple like Prop[key, default])
        - If none are found, it raises IndexError.
        - [0] maps to the .value if the Property has no children.
        """
        if self.has_children():
            if isinstance(index, int) or isinstance(index, slice):
                return self.value[index]
            else:
                if isinstance(index, tuple):
                    # With default value
                    return self.find_key(index[0], def_=index[1]).value
                else:
                    try:
                        return self.find_key(index).value
                    except NoKeyError as no_key:
                        raise IndexError(no_key) from no_key
        elif index == 0:
            return self.value
        else:
            raise IndexError

    def __setitem__(
            self,
            index: Union[int, slice, str],
            value: _Prop_Value
            ):
        """Allow setting the values of the children directly.

        - If given an index or slice, it will search by position.
        - If given a string, it will set the last Property with that name.
        - If none are found, it appends the value to the tree.
        - If given a tuple of strings, it will search through that path,
          and set the value of the last matching Property.
        - [0] sets the .value if the Property has no children.
        """
        if self.has_children():
            if isinstance(index, int) or isinstance(index, slice):
                self.value[index] = value
            else:
                self.set_key(index, value)
        elif index == 0:
            self.value = value
        else:
            raise IndexError(
                'Cannot index a Property that does not have children!'
            )

    def __delitem__(self, index):
        """Delete the given property index.

        - If given an integer, it will delete by position.
        - If given a string, it will delete the last Property with that name.
        - If the Property has no children, it will blank the value instead.
        """
        if self.has_children():
            if isinstance(index, int):
                del self.value[index]
            else:
                try:
                    self.value.remove(self.find_key(index))
                except NoKeyError as no_key:
                    raise IndexError(no_key) from no_key
        else:
            self.value = ''  # type: _Prop_Value

    def __add__(self, other):
        """Allow appending other properties to this one.

        This deep-copies the Property tree first.
        Works with either a sequence of Properties or a single Property.
        """
        if self.has_children():
            copy = self.copy()
            if isinstance(other, Property):
                if other._folded_name is None:
                    copy.value.extend(other.value)
                else:
                    # We want to add the other property tree to our
                    # own, not its values.
                    copy.value.append(other)
            else: # Assume a sequence.
                copy.value += other # Add the values to ours.
            return copy
        else:
            return NotImplemented

    def __iadd__(self, other):
        """Allow appending other properties to this one.

        This is the += op, where it does not copy the object.
        """
        if self.has_children():
            if isinstance(other, Property):
                if other._folded_name is None:
                    self.value.extend(other.value)
                else:
                    self.value.append(other)
            else:
                self.value += other
            return self
        else:
            return NotImplemented

    append = __iadd__
    append.__doc__ = """Append another property to this one."""

    def merge_children(self, *names: str):
        """Merge together any children of ours with the given names.

        After execution, this tree will have only one sub-Property for
        each of the given names. This ignores leaf Properties.
        """
        folded_names = [name.casefold() for name in names]
        new_list = []
        merge = {
            name.casefold(): Property(name, [])
            for name in
            names
        }
        if self.has_children():
            for item in self.value[:]:  # type: Property
                if item._folded_name in folded_names:
                    merge[item._folded_name].value.extend(item.value)
                else:
                    new_list.append(item)
        for prop_name in names:
            prop = merge[prop_name.casefold()]
            if len(prop.value) > 0:
                new_list.append(prop)

        self.value = new_list

    def ensure_exists(self, key):
        """Ensure a Property group exists with this name."""
        if key not in self:
            self.value.append(Property(key, []))

    def has_children(self):
        """Does this have child properties?"""
        return isinstance(self.value, list)

    def __repr__(self):
        return 'Property(' + repr(self.real_name) + ', ' + repr(self.value) + ')'

    def __str__(self):
        return ''.join(self.export())

    def export(self):
        """Generate the set of strings for a property file.

        Recursively calls itself for all child properties.
        If the Property is marked invalid, it will immediately return.
        """
        if isinstance(self.value, list):
            if self.name is None:
                # If the name is None, we just output the chilren
                # without a "Name" { } surround. These Property
                # objects represent the root.
                for prop in self.value:
                    yield from prop.export()
            else:
                yield '"' + self.real_name + '"\n'
                yield '\t{\n'
                yield from (
                    '\t' + line
                    for prop in self.value
                    for line in prop.export()
                    )
                yield '\t}\n'
        else:
            yield '"' + self.real_name + '" "' + str(self.value) + '"\n'
