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
import utils

class Property:
    '''Represents Property found in property files, like those used by Valve.'''
    def __init__(self, name = None, value = ""):
        self.name = name
        self.value = value

    @staticmethod
    def parse(file_contents):
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
                        raise ValueError("Invalid name " + name + ". Line " + str(line_num) + ".")
                    try:
                        value = line_contents[3]
                    except IndexError:
                        value = None
                        
                    values.append(Property(name, value))
                elif utils.is_identifier(freshline): # handle name bare on one line, will need a brace on the nex line
                    values.append(Property(freshline, []))
                elif freshline.startswith('{'):
                    if values[-1].value:
                        raise ValueError("Property cannot have sub-section if it already has an in-line value. Line " + str(line_num) + ".")
                    
                    values[-1].value = []
                    open_properties.append(values[-1])
                elif freshline.startswith('}'):
                    open_properties.pop()
                else:
                    raise ValueError("Unexpected beginning character '"+freshline[0]+"'. Line " + str(line_num) + ".")
                    
            if not open_properties:
                raise ValueError("Too many closing brackets. Line " + str(line_num) + ".")
        if len(open_properties) > 1:
            raise ValueError("End of text reached with remaining open sections.")
            
        return open_properties[0].value
        
    def find_all(self, key_path):
        run_on = []
        values = []
        depth = key_path.count('"')
        keys = key_path.split('"', 1)
        print ('====keys')
        if depth >0:
            print(keys[1])
        
        if isinstance(self, list):
            run_on = self
        elif isinstance(self, Property):
            run_on.append(self)
        for prop in run_on:
            if not isinstance(prop, Property):
                raise ValueError("Cannot find_all on a value that is not a Property")
            print('{}'.format('keys[0] = ', keys[0]))
            if prop.name.casefold() == keys[0].casefold():
                if depth > 0:
                    if isinstance(prop.value, list):
                        values.extend(Property.find_all(prop.value,keys[1]))
                else:
                    values.append(prop)
        return values
        
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