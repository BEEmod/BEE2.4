# Property: class
# - Represents Property found in property files, like those used by valve.
# name: string 
# - Name of the section or property
# value: string || Property[]
# -  Value is single string when Property is in-line, Property array when Property is section
# parse: string[] => Property[]
# - Returns list of Property objects parsed from given text

import re

class Property:
  def __init__(self, name = None, value = ""):
    self.name = name
    self.value = value
    
  @staticmethod
  def parse(file_contents):
    open_properties = [Property(None, [])]
    values = None
    line_num = 0
    for line in file_contents:
      line_num += 1
      values = open_properties[-1].value
      freshline = clean_line(line)
      if freshline:
        if freshline.startswith('"'):
          line_contents = str.split(freshline, '"')
          name = line_contents[1]
          if len(line_contents)>3:
            value = line_contents[3]
          else:
            value = None
          values.append(Property(name, value))
        elif freshline.startswith('{'):
          if not values[-1].value:
            values[-1].value = []
          else:
            raise ValueError("Property cannot have sub-section if it already has an in-line value. Line " + str(line_num) + ".")
          open_properties.append(values[-1])
        elif(freshline.startswith('}')):
          open_properties.pop()
        else:
          raise ValueError("Unexpected beginning character. Line " + str(line_num) + ".")
      if not open_properties:
        raise ValueError("Too many closing brackets. Line " + str(line_num) + ".")
    if len(open_properties) > 1:
        raise ValueError("End of text reached with remaining open sections.")
    return open_properties[0].value

def clean_line(dirty_line):
  line = dirty_line.strip()
  if line.startswith("\\\\") or line.startswith("//"):
    line = ""
  # TODO: Actually strip comments off of the end of all lines
  return line
  
def to_strings(self):
  out_val = ['"' + self.name + '"']
  
  if self.value is []: 
    out_val.append('{')
    for property in self.value:
      for line in property.to_string():
        out_val.append('\t' + line)
    out_val.append('}')
  else:
    out_val[0] += ' "' + self.value + '"'
  return out_val
