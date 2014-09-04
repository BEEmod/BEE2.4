class Property:
  def __init__(self):
    self.name = None
    self.value = None
    
  def __init__(self, name, value):
    self.name = name
    self.value = value
    
  def parse(file_contents):
    open_properties = []
    open_properties.add(Property(None, []))
    values = None
    for line in file_contents:
      values = open_properties.last.value
      # TODO: Need data validation below
      strippedline = line.strip().
      if(strippedline.beginswith('"'):
        # It is a Property. Make a new property and add it to the values, if it has a value in line: assign it
        line_contents = strippedline.regex()()()
        name = line_contents[0]
        value = line_contents[1]
        values.add(Property(name, value))
      elif(strippedline.beginswith('{'):
        # It is the beginning of a property section. Add the latest added properties to the list of open properties
        if(values.last.value is not None):
          # Throw a fit. We cant add to this if there is already something in there
        else:
          values.last.value = []
        open_properties.add(values.last)
      elif(strippedline.beginswith('}'):
        # It is the end of a property section. Close section by pop the property off the open properties list
        open_properties.pop
      elif(strippedline == "")
        # Ignore blank lines.
      else:
        # Throw a fit, It is unknown.
      if(open_properties.len == 0):
        # Throw a fit, there should always be atleast the fake Property on the stack
    if(open_properties.len > 1)
      # Throw a fit, there should only be one Property on the stack (the fake one), not all Properties were closed.    
    return values



def remove_comments(string)
  # Stub to be implemented later
  return string
  