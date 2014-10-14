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

class KeyValError(Exception):
    "An error that occured when parsing a Valve KeyValues file."
    pass
    
class NoKeyError(Exception):
    "Raised if a key is not found when searching from find_key."
    pass

class Property:
    '''Represents Property found in property files, like those used by Valve.'''
    def __init__(self, name = None, value = ""):
        self.name = name
        self.value = value

    def edit(self, name=None, value=None):
        if name is not None:
            self.name = name
        if value is not None:
            self.value = value
        
    @staticmethod
    def parse(file_contents) -> "List of Property objects":
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
                        raise KeyValError("Invalid name " + name + ". Line " + str(line_num) + ".")
                    try:
                        value = line_contents[3]
                    except IndexError:
                        value = None
                        
                    values.append(Property(name, value))
                elif utils.is_identifier(freshline): # handle name bare on one line, will need a brace on the nex line
                    values.append(Property(freshline, []))
                elif freshline.startswith('{'):
                    if values[-1].value:
                        raise KeyValError("Property cannot have sub-section if it already has an in-line value. Line " + str(line_num) + ".")
                    
                    values[-1].value = []
                    open_properties.append(values[-1])
                elif freshline.startswith('}'):
                    open_properties.pop()
                else:
                    raise KeyValError("Unexpected beginning character '"+freshline[0]+"'. Line " + str(line_num) + ".")
                    
            if not open_properties:
                raise KeyValError("Too many closing brackets. Line " + str(line_num) + ".")
        if len(open_properties) > 1:
            raise KeyValError("End of text reached with remaining open sections.")
            
        return open_properties[0].value
        
    def find_all(self: "list or Property", *keys) -> "List of matching Property objects":
        "Search through a tree to obtain all properties that match a particular path."
        run_on = []
        values = []
        depth = len(keys)
        if depth == 0:
            raise ValueError("Cannot find_all without commands!")
        if isinstance(self, list):
            run_on = self
        elif isinstance(self, Property):
            run_on.append(self)
            if not self.name == keys[0] and len(run_on)==1: # Add our name to the beginning if not present (otherwise this always fails)
                return Property.find_all(run_on[0], *((self.name,) + keys))
                
        for prop in run_on:
            if not isinstance(prop, Property):
                raise ValueError("Cannot find_all on a value that is not a Property!")
            if prop.name is not None and prop.name.casefold() == keys[0].casefold():
                if depth > 1:
                    if isinstance(prop.value, list):
                        values.extend(Property.find_all(prop.value, *keys[1:]))
                else:
                    values.append(prop)
        return values
        
    def find_key(self: "list or Property", key, def_=None) -> "Property":
        "Obtain the value of the child Property with a name, with an optional default value."
        run_on = []
        if isinstance(self, list):
            run_on = self
        elif isinstance(self, Property):
            run_on=self.value
        key=key.casefold()
            
        for prop in reversed(run_on):
            if prop.name is not None and prop.name.casefold() == key:
                return prop
        if def_==None:
            raise NoKeyError('No key "' + key + '"!')
        else:
            return Property(name=key, value=def_) 
            # We were given a default, pretend that was in the original property list so code works
        
    def __str__(self):
        return '\n'.join(self.to_strings())
        
    
    def to_strings(self):
        '''Returns a list of strings that represents the property as it appears in the file.'''
        out_val = ['"{}"'.format(self.name)]
        if isinstance(self.value, list):
            out_val.append('{')
            out_val.extend(['\t'+line for property in self.value for line in property.to_strings()])
            out_val.append('}')
        else:
            out_val[0] += ' "' + self.value + '"'
            
        return out_val

import utils