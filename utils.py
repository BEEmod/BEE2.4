def clean_line(dirty_line):
    if isinstance(dirty_line, bytes):
        dirty_line=dirty_line.decode()
    line = dirty_line.strip()
    if line.startswith("\\\\") or line.startswith("//"):
        line = ""
    # TODO: Actually strip comments off of the end of all lines
    return line