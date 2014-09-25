def clean_line(dirty_line):
    line = dirty_line.strip()
    if line.startswith("\\\\") or line.startswith("//"):
        line = ""
    # TODO: Actually strip comments off of the end of all lines
    return line