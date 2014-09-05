import re
import string

class Property:
  quote_wrap = None
  
  def __init():
    with open("bin/quote-wrap") as file:
      quote_wrap = re.compile(file.read())
  
  def __init__(self):
    self.name = None
    self.value = None
    
  def __init__(self, name, value):
    self.name = name
    self.value = value
  
  def parse(file_contents):
    open_properties = []
    open_properties.append(Property(None, []))
    values = None
    line_num = 0
    for line in file_contents:
      line_num += 1
      values = open_properties[-1].value
      freshline = clean_line(line)
      if(freshline != ""):
        if(freshline.startswith('"')):
          line_contents = quote_wrap.findall(freshline)
          name = line_contents[0]
          value = line_contents[2]
          values.append(Property(name, value))
        elif(freshline.startswith('{')):
          if(values[-1].value is None):
            values[-1].value = []
          else:
            raise ValueError("Property cannot have sub-section if it already has an in-line value. Line " + str(line_num) + ".")
          open_properties.append(values[-1])
        elif(freshline.startswith('}')):
          open_properties.pop()
        else:
          raise ValueError("Unexpected beginning character. Line " + str(line_num) + ".")
      if(len(open_properties) == 0):
        raise ValueError("Too many closing brackets. Line " + str(line_num) + ".")
    if(len(open_properties) > 1):
        raise ValueError("End of text reached with remaining open sections.")  
    return values

def clean_line(dirty_line):
  line = dirty_line.strip()
  if(line.startswith("\\\\")):
    line = ""
  return dirty_line
