def clean_line(dirty_line):
    "Removes extra spaces and comments from the input."
    if isinstance(dirty_line, bytes):
        dirty_line=dirty_line.decode() # convert bytes to strings if needed
    line = dirty_line.strip()
    if line.startswith("\\\\") or line.startswith("//"):
        line = ""
    # TODO: Actually strip comments off of the end of all lines
    return line
    
def is_identifier(name, forbidden='{} "\''):
    "Check to see if any forbidden characters are part of a canidate name."
    for t in name:
        if t in forbidden:
            return False
    return True
