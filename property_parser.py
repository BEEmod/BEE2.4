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
# Single comments should appear as properties with the name of //
# A new member level property called 'comment' should be added when a comment is tacked onto the end of a line
# Comments on bracketed lines should be separated into their own comment properties


import re

__all__ = ["KeyValError", "NoKeyError", "Property"]

# various escape sequences that we allow
replace_chars = {
    r'\n'  : '\n',
    r'\t'  : '\t',
    '\\\\' : '\\',
    r'\/'  : '/'
    }

class KeyValError(Exception):
    '''An error that occured when parsing a Valve KeyValues file.'''
    def __init__(self, message, file):
        self.mess = message
        self.file = file
        
    def __str__(self):
        if self.file:
            return self.mess + "\n(" + self.file + ")"
        else:
            return self.mess
    
class NoKeyError(Exception):
    '''Raised if a key is not found when searching from find_key().
    
    key = The missing key that was asked for
    all_keys = The names of all valid keys for the Property
    '''
    def __init__(self, key, all_keys):
        self.key = key
        self.all_keys = all_keys
        
    def __str__(self):
        return "No key " + self.key + "!"
    pass
    
_NO_KEY_FOUND = object() # Sentinel value to indicate that no default was given to find_key()

class Property:
    '''Represents Property found in property files, like those used by Valve.'''
    __slots__ = ('name', 'value', 'valid') # Helps decrease memory footprint with lots of Property values.
    def __init__(self, name = None, value = ""):
        self.name = name
        self.value = value
        self.valid = True

    def edit(self, name=None, value=None):
        '''Simultanously modify the name and value.'''
        if name is not None:
            self.name = name
        if value is not None:
            self.value = value
        
    @staticmethod
    def parse(file_contents, filename='') -> "List of Property objects":
        '''Returns list of Property objects parsed from given text'''
        open_properties = [Property(None, [])]
        values = None
        for line_num, line in enumerate(file_contents):
            values = open_properties[-1].value
            freshline = utils.clean_line(line)
            if freshline:
                if freshline.startswith('"'): # data string
                    line_contents = freshline.split('"')
                    name = line_contents[1]
                    if not utils.is_identifier(name):
                        raise KeyValError("Invalid name " + name + ". Line " + str(line_num) + ".", filename)
                    try:
                        value = line_contents[3]
                        if not freshline.endswith('"'):
                            raise KeyValError("Line " + str(line_num) + " has value, but incomplete quotes!", filename)
                        for orig, new in replace_chars.items():
                            value=value.replace(orig, new)
                    except IndexError:
                        value = None
                        
                    values.append(Property(name, value))
                elif utils.is_identifier(freshline): # handle name bare on one line, will need a brace on the nex line
                    values.append(Property(freshline, []))
                elif freshline.startswith('{'):
                    if values[-1].value:
                        raise KeyValError("Property cannot have sub-section if it already has an in-line value. Line " + str(line_num) + ".", filename)
                    values[-1].value = []
                    open_properties.append(values[-1])
                elif freshline.startswith('}'):
                    open_properties.pop()
                else:
                    raise KeyValError("Unexpected beginning character '"+freshline[0]+"'. Line " + str(line_num) + ".", filename)
                    
            if not open_properties:
                raise KeyValError("Too many closing brackets. Line " + str(line_num) + ".", filename)
        if len(open_properties) > 1:
            raise KeyValError("End of text reached with remaining open sections.", filename)
            
        return open_properties[0].value
        
    def find_all(self: "list or Property", *keys) -> "Generator for of matching Property objects":
        "Search through a tree to obtain all properties that match a particular path."
        run_on = []
        depth = len(keys)
        if depth == 0:
            raise ValueError("Cannot find_all without commands!")
        if isinstance(self, list):
            run_on = self
        elif isinstance(self, Property):
            run_on.append(self)
            if not self.name == keys[0] and len(run_on)==1: # Add our name to the beginning if not present (otherwise this always fails)
                yield from Property.find_all(run_on[0], *((self.name,) + keys))
                
        for prop in run_on:
            if not isinstance(prop, Property):
                raise ValueError("Cannot find_all on a value that is not a Property!")
            if prop.name is not None and prop.name.casefold() == keys[0].casefold():
                if depth > 1:
                    if isinstance(prop.value, list):
                        yield from Property.find_all(prop.value, *keys[1:])
                else:
                    yield prop
        
    def find_key(self: "list or Property", key, def_=_NO_KEY_FOUND) -> "Property":
        '''Obtain the value of the child Property with a name, with an optional default value.
        
        If no default value is given, this will raise NoKeyError.
        '''
        run_on = []
        if isinstance(key, tuple) and len(key) == 2:
            # Allow using Prop[val, default] to get values
            def_=key[1]
            key=key[0]
        if isinstance(self, list):
            run_on = self
        elif isinstance(self, Property):
            run_on=self.value
        key=key.casefold()
            
        for prop in reversed(run_on):
            if prop.name is not None and prop.name.casefold() == key:
                return prop
        if def_ is _NO_KEY_FOUND:
            raise NoKeyError(key, [prop.name for prop in run_on])
        else:
            return Property(name=key, value=def_) 
            # We were given a default, pretend that was in the original property list so code works
    
    def copy(self):
        "Deep copy this Property tree and return it."
        if isinstance(self.value, list):
            new_children = [] # we need to duplicate children...
            for child in self.value:
                new_children.append(child.copy()) # so recurse
            return Property(self.name, new_children)
        else:
            return Property(self.name, self.value)
            
    def as_dict(self):
        "Convert this property tree into a tree of dictionaries, "
        "keeping the last if multiple items have the smae name."
        if self.has_children():
            return {item.name:item.as_dict() for item in self}
        else:
            return self.value
            
    def make_invalid(self):
        "Soft delete this property tree, so it does not appear in any output."
        self.valid = False
        self.value = "" # Dump this if it exists
        self.name = None
        
    def __eq__(self,other):
        "Compare two items and determine if they are equal. This ignores names."
        if isinstance(other, Property):
            return (self.value == other.value)
        else:
            return self.value == other # Just compare values
                
    def __eq__(self,other):
        "Not-Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return (self.value != other.value)
        else:
            return self.value != other # Just compare values
                
    def __lt__(self,other):
        "Less-Than comparison. This ignores names."
        if isinstance(other, Property):
            return (self.value < other.value)
        else:
            return self.value < other

    def __gt__(self,other):
        "Greater-Than comparison. This ignores names."
        if isinstance(other, Property):
            return (self.value > other.value)
        else:
            return self.value > other  
                
    def __le__(self,other):
        "Less-Than or Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return (self.value <= other.value)
        else:
            return self.value <= other
    
    def __ge__(self,other):
        "Greater-Than or Equal To comparison. This ignores names."
        if isinstance(other, Property):
            return (self.value >= other.value)
        else:
            return self.value >= other 
                
    def __len__(self):
        if self.valid:
            if self.has_children():
                return len(self.value)
            else:
                return 1
        else:
            return 0
    
    def __iter__(self):
        "Iterate through the value list, or loop once through the single value."
        if self.has_children():
            for item in self.value:
                yield item
        else:
            yield self.value
    
    def __getitem__(self, index):
        '''Allow indexing the children directly.
        
        - If given an integer, it will search by position.
        - If given a string, it will find the last Property with that name.
          (Default can be chosen by passing a 2-tuple like Prop[key, default]
        - If none are found, it raises IndexError
        - [0] maps to the .value if the Property has no children
        '''
        if self.has_children():
            if isinstance(index, int):
                return self.value[index]
            else:
                try:
                    return self.find_key(index).value
                except NoKeyError as no_key:
                    raise IndexError(str(no_key)) from no_key
        elif index == 0:
            return self.value
        else:
            raise IndexError
            
    def __setitem__(self, index, value):
        '''Allow setting the values of the children directly.
        
        - If given an integer, it will search by position.
        - If given a string, it will set the last Property with that name.
        - If none are found, it raises IndexError
        - [0] is the same as .value if the Property has no children, all others fail
        '''
        if self.has_children():
            if isinstance(index, int):
                self.value[index] = value
            else:
                try:
                    self.find_key(index).value = value
                except NoKeyError as no_key:
                    raise IndexError(str(no_key)) from no_key
        elif index == 0:
            self.value = value
        else:
            raise IndexError
            
    def _delitem__(self, index):
        if self.has_children():
            del self.value[index]
                
    def __add__(self, other):
        "Allow appending other properties to this one."
        if self.has_children():
            copy = self.copy()
            if isinstance(other, Property):
                copy.value.append(other) # we want to add the other property tree to our own, not its values.
            else: # assume a list/iteratable thing
                copy.value += other # add the values to ours.
            return copy
            
        else:
            return NotImplemented
    
    def __iadd__(self, other):
        "Allow appending other properties to this one. This is the += op, where it does not copy the object."
        if self.has_children():
            if isinstance(other, Property):
                self.value.append(other)
            else:
                self.value += other
            return self
        else:
            return NotImplemented
  
    def append(self, val):
        "Append the passed property to the list of items."
        if isinstance(val, Property):
            if self.has_children():
                self.value.append(val)
            else:
                self.value=[self.value, val]
        else:
            return NotImplemented
            
    def has_children(self):
        "Does this have child properties?"
        return isinstance(self.value, list)
        
    def __repr__(self):
        return 'Property(' + repr(self.name) + ', ' + repr(self.value) + ')'
        
    def __str__(self):
        if self.valid:
            return '\n'.join(self.to_strings())
        else:
            return ''
    def to_strings(self):
        '''Returns a list of strings that represents the property as it appears in the file.'''
        if self.valid:
            out_val = '"' + str(self.name) + '"'
            if isinstance(self.value, list):
                yield out_val
                yield '{'
                yield from ('\t'+line for property in self.value for line in property.to_strings() if property.valid==True)
                yield '}'
            else:
                yield out_val + ' "' + str(self.value) + '"'
        else:
            yield ''

import utils