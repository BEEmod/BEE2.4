'''
Property: class
- Represents Property found in property files, like those used by valve.
name: string
- Name of the section or property.
value: string || Property[]
-  Value is single string when Property is in-line, Property array when Property is section.
parse: string[] => Property[]
- Returns a list of Property objects parsed from given text.
to_strings: => string
- Returns a string list representation of what the property appears as in the file.
'''

# TODO: Add comment support. Read in, and export comments.
# - Single comments should appear as properties with the name of '//'
# - A new member level property called 'comment' should be added when a
#   comment is tacked onto the end of a line.
# - Comments on bracketed lines should be separated into their own
#   comment properties.

import utils

__all__ = ['KeyValError', 'NoKeyError', 'Property', 'INVALID']

# various escape sequences that we allow
REPLACE_CHARS = {
    r'\n'  : '\n',
    r'\t'  : '\t',
    '\\\\' : '\\',
    r'\/'  : '/'
    }

INVALID = object()

_NO_KEY_FOUND = object() # Sentinel value to indicate that no default was given to find_key()

class KeyValError(Exception):
    '''An error that occured when parsing a Valve KeyValues file.
    
    mess = The error message that occured.
    file = The filename passed to Property.parse(), if it exists
    line_num = The line where the error occured.
    '''
    def __init__(self, message, file, line):
        super().__init__()
        self.mess = message
        self.file = file
        self.line_num = line

    def __str__(self):
        '''Generate the complete error message.
        
        This includes the line number and file, if avalible.
        '''
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
    '''Raised if a key is not found when searching from find_key().
    
    key = The missing key that was asked for.
    '''
    def __init__(self, key):
        super().__init__()
        self.key = key

    def __str__(self):
        return "No key " + self.key + "!"

class Property:
    '''Represents Property found in property files, like those used by Valve.'''
    # Helps decrease memory footprint with lots of Property values.
    __slots__ = ('name', 'value', 'valid')
    def __init__(self, name, *values, **kargs):
        '''Create a new property instance.
        Values can be passed in 4 ways:
        - A single value for the Property
        - A number of Property objects for the tree
        - A set of keyword arguments which will be converted into Property objects
        - A single dictionary which will be converted into Property objects
        Values default to just ''.
        '''
        if name == INVALID:
            self.name = None
            self.value = None
            self.valid = False
        else:
            self.name = name
            if len(values) == 1:
                if isinstance(values[0], Property):
                    self.value = [values[0]]
                elif isinstance(values[0], dict):
                    self.value = [Property(key, val) for key, val in values[0].items()]
                else:
                    self.value = values[0]
            else:
                self.value = list(values)
                self.value.extend(Property(key, val) for key, val in kargs.items())
            if (values) == 0 and len(kargs) == 0:
                self.value = ''
            self.valid = True

    def edit(self, name=None, value=None):
        '''Simultaneously modify the name and value.'''
        if name is not None:
            self.name = name
        if value is not None:
            self.value = value

    @staticmethod
    def parse(file_contents, filename='') -> "List of Property objects":
        '''Returns list of Property objects parsed from given text'''
        open_properties = [Property(None, [])]
        values = None
        for line_num, line in enumerate(file_contents, start=1):
            values = open_properties[-1].value
            freshline = utils.clean_line(line)
            if not freshline:
                # Skip blank lines!
                continue
                
            if freshline.startswith('"'): # data string
                line_contents = freshline.split('"')
                name = line_contents[1]
                if not utils.is_identifier(name):
                    raise KeyValError(
                        'Invalid name ' + name + '!',
                        filename,
                        line_num,
                        )
                try:
                    value = line_contents[3]
                    if not freshline.endswith('"'):
                        raise KeyValError(
                            'Key has value, but incomplete quotes!',
                            filename,
                            line_num,
                            )
                    for orig, new in REPLACE_CHARS.items():
                        value = value.replace(orig, new)
                except IndexError:
                    value = None

                values.append(Property(name, value))
            # handle name bare on one line, will need a brace on
            # the next line
            elif utils.is_identifier(freshline):
                values.append(Property(freshline, []))
            elif freshline.startswith('{'):
                if values[-1].value:
                    raise KeyValError(
                        'Property cannot have sub-section if it already'
                        'has an in-line value.',
                        filename,
                        line_num,
                        )
                values[-1].value = []
                open_properties.append(values[-1])
            elif freshline.startswith('}'):
                open_properties.pop()
            else:
                raise KeyValError(
                    "Unexpected beginning character '"
                    + freshline[0]
                    + '"!',
                    filename,
                    line_num,
                    )

            if not open_properties:
                raise KeyValError(
                    'Too many closing brackets.',
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

    def find_all(self, *keys) -> "Generator for matching Property objects":
        '''Search through a tree to obtain all properties that match a particular path.
        
        '''
        depth = len(keys)
        if depth == 0:
            raise ValueError("Cannot find_all without commands!")

        for prop in self:
            if not isinstance(prop, Property):
                raise ValueError("Cannot find_all on a value that is not a Property!")
            if prop.name is not None and prop.name.casefold() == keys[0].casefold():
                if depth > 1:
                    if prop.has_children():
                        yield from Property.find_all(prop.value, *keys[1:])
                else:
                    yield prop

    def find_key(self, key, def_=_NO_KEY_FOUND) -> "Property":
        '''Obtain the value of the child Property with a given name.
        
        - If no child is found with the given name, this will return the
          default value, or raise NoKeyError if none is provided.
        - This prefers keys located closer to the end of the value list.
        '''
        key = key.casefold()
        for prop in reversed(self.value):
            if prop.name is not None and prop.name.casefold() == key:
                return prop
        if def_ is _NO_KEY_FOUND:
            raise NoKeyError(key)
        else:
            return Property(key, def_)
            # We were given a default, pretend that was in the original property list so code works

    def set_key(self, path, value):
        '''Set the value of a key deep in the tree hierachy.
        
        -If any of the hierachy do not exist (or do not have children),
          blank properties will be added automatically
        - path should be a tuple of names, or a single string.
        '''
        current_prop = self
        if isinstance(path, tuple):
            # Search through each item in the tree!
            for key in path[:-1]:
                print(key)
                folded_key = key.casefold()
                # We can't use find_key() here because we also
                # need to check that the property has chilren to search
                # through
                for prop in reversed(self.value):
                    if (prop.name is not None and
                            prop.name.casefold() == folded_key and
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
        '''Deep copy this Property tree and return it.'''
        if self.has_children():
            # This recurses if needed
            return Property(self.name, [child.copy() for child in self.value])
        else:
            return Property(self.name, self.value)

    def as_dict(self):
        '''Convert this property tree into a tree of dictionaries.
        
        This keeps only the last if multiple items have the same name.
        '''
        if self.has_children():
            return {item.name:item.as_dict() for item in self}
        else:
            return self.value

    def make_invalid(self):
        '''Soft delete this property tree, so it does not appear in any output.'''
        self.valid = False
        self.value = None # Dump this if it exists
        self.name = None

    def __eq__(self, other):
        '''Compare two items and determine if they are equal. This ignores names.'''
        if isinstance(other, Property):
            return self.value == other.value
        else:
            return self.value == other # Just compare values

    def __ne__(self, other):
        "Not-Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return self.value != other.value
        else:
            return self.value != other # Just compare values

    def __lt__(self, other):
        "Less-Than comparison. This ignores names."
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
        '''Determine the number of child properties.
        
        Singluar Properties have a length of 1.
        Invalid properties have a length of 0.
        '''
        if self.valid:
            if self.has_children():
                return len(self.value)
            else:
                return 1
        else:
            return 0

    def __iter__(self):
        '''Iterate through the value list, or loop once through the single value.'''
        if self.has_children():
            yield from self.value
        else:
            yield self.value

    def __contains__(self, key):
        '''Check to see if a name is present in the children.
        
        If the Property has no children, this checks if the names match instead.
        '''
        key = key.casefold()
        if self.has_children():
            for prop in self.value:
                if prop.name.casefold() == key:
                    return True
            return False
        else:
            return self.name.casefold() == key

    def __getitem__(self, index):
        '''Allow indexing the children directly.
        
        - If given an index or slice, it will search by position.
        - If given a string, it will find the last Property with that name.
          (Default can be chosen by passing a 2-tuple like Prop[key, default])
        - If none are found, it raises IndexError.
        - [0] maps to the .value if the Property has no children.
        '''
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

    def __setitem__(self, index, value):
        '''Allow setting the values of the children directly.
        
        - If given an index or slice, it will search by position.
        - If given a string, it will set the last Property with that name.
        - If none are found, it appends the value to the tree.
        - If given a tuple of strings, it will search through that path,
          and set the value of the last matching Property.
        - [0] sets the .value if the Property has no children.
        '''
        if self.has_children():
            if isinstance(index, int) or isinstance(index, slice):
                self.value[index] = value
            else:
                self.set_key(index, value)
        elif index == 0:
            self.value = value
        else:
            raise IndexError('Cannot index a Property that does not have children!')

    def __delitem__(self, index):
        '''Delete the given property index.
        
        - If given an integer, it will delete by position.
        - If given a string, it will delete the last Property with that name.
        - If the Property has no children, it will blank the value instead.
        '''
        if self.has_children():
            if isinstance(index, int):
                del self.value[index]
            else:
                try:
                    self.value.remove(self.find_key(index))
                except NoKeyError as no_key:
                    raise IndexError(no_key) from no_key
        else:
            self.value = ''

    def __add__(self, other):
        '''Allow appending other properties to this one.
        
        This deep-copies the Property tree first.
        Works with either a sequence of Properties or a single Property.
        '''
        if self.has_children():
            copy = self.copy()
            if isinstance(other, Property):
                if other.name is None:
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
        '''Allow appending other properties to this one.
        
        This is the += op, where it does not copy the object.
        '''
        if self.has_children():
            if isinstance(other, Property):
                if other.name is None:
                    self.value.extend(other.value)
                else:
                    self.value.append(other)
            else:
                self.value += other
            return self
        else:
            return NotImplemented

    append = __iadd__
    append.__doc__ = '''Append another property to this one.'''

    def merge_children(self, *names):
        '''Merge together any children of ours with the given names.
        
        After execution, this tree will have only one sub-Property for
        each of the given names. This ignores leaf Properties.
        '''
        folded_names = [name.casefold() for name in names]
        new_list = []
        merge = {name.casefold(): Property(name, []) for name in names}
        if self.has_children():
            for item in self.value[:]:
                if item.name.casefold() in folded_names:
                    merge[item.name.casefold()].value.extend(item.value)
                else:
                    new_list.append(item)
        for prop in merge.values():
            if len(prop.value) > 0:
                new_list.append(prop)

        self.value = new_list

    def ensure_exists(self, key):
        '''Ensure a Property group exists with this name.'''
        if key not in self:
            self.value.append(Property(key, []))

    def has_children(self):
        '''Does this have child properties?'''
        return isinstance(self.value, list)

    def __repr__(self):
        if self.valid:
            return 'Property(' + repr(self.name) + ', ' + repr(self.value) + ')'
        else:
            return 'Property(<INVALID>)'

    def __str__(self):
        return ''.join(self.export())

    def export(self):
        '''Iterates over a set of strings that represents the property as it appears in the file.'''
        if self.valid:
            out_val = '"' + str(self.name) + '"'
            if isinstance(self.value, list):
                if self.name is None:
                    # If the name is None, we just output the chilren
                    # without a "Name" { } surround. These Property
                    # objects represent the root.
                    yield from (
                        line
                        for prop in self.value
                        for line in prop.export()
                        if prop.valid == True
                        )
                else:
                    yield out_val + '\n'
                    yield '\t{\n'
                    yield from (
                        '\t'+line
                        for prop in self.value
                        for line in prop.export()
                        if prop.valid == True
                        )
                    yield '\t}\n'
            else:
                yield out_val + ' "' + str(self.value) + '"\n'
        else:
            yield ''
