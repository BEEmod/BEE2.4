from property_parser import Property

def clean_line(dirty_line):
    "Removes extra spaces and comments from the input."
    if isinstance(dirty_line, bytes):
        dirty_line=dirty_line.decode() # convert bytes to strings if needed
    line = dirty_line.strip()
    if line.startswith("\\\\") or line.startswith("//"):
        line = ""
    # TODO: Actually strip comments off of the end of all lines
    return line
    
def is_identifier(name, forbidden='{}\'"'):
    "Check to see if any forbidden characters are part of a canidate name."
    for t in name:
        if t in forbidden:
            return False
    return True
    
def con_log(text):
    print(text, flush=True) 

def find_key(ent, key, norm=None):
    "Safely get a subkey from an entity (not lists of multiple). If it fails, throw an exception to crash the compiler safely."
    result = Property.find_all(ent, ent.name + '"' + key)
    if len(result) == 1:
        return result[0]
    elif len(result) == 0:
        if norm==None:
            raise Exception('No key "' + key + '"!')
        else:
            return Property(name=key, value=norm) # We were given a default, pretend that was in the original property list
    else:
        raise Exception('Duplicate keys "' + key + '"!')

# VMF specific        

def add_output(entity, output, target, input, params="", delay="0", times="-1"):
    "Add a new output to an entity with the given values, generating a connections part if needed."
    conn = Property.find_all(entity, 'entity"connections')
    if len(conn) == 0:
        conn = Property("connections", [])
        entity.value.append(conn)
    else:
        conn = conn[0]
    out=Property(output, chr(27).join((target, input, params, delay, times)))
    # character 27 (which is the ASCII escape control character) is the delimiter for VMF outputs. 
    log("adding output :" + out.value)
    conn.value.append(out)

def split_plane(plane):
    "Extract the plane from a brush into an array."
    # Plane looks like "(575 0 128) (575 768 128) (575 768 256)"
    verts = plane.value[1:-1].split(") (") # break into 3 groups of 3d vertexes
    for i,v in enumerate(verts):
        verts[i]=v.split(" ")
    return verts

def join_plane(verts):
    "Join the verts back into the proper string."
    plane=""
    for vert in verts:
        plane += ("(" + " ".join(vert) + ") ")
    return plane[:-1] # take off the last space
    
def get_bbox(planes):
    "Generate the highest and lowest points these planes form."
    bbox_max=[]
    bbox_min=[]
    preset=True
    for pl in planes:
        verts=split_plane(pl)
        if preset:
            preset=False
            bbox_max=[int(x)-99999 for x in verts[0][:]]
            bbox_min=[int(x)+99999 for x in verts[0][:]]
        for v in verts:
            for i in range(0,3):
                bbox_max[i] = max(int(v[i]), bbox_max[i])
                bbox_min[i] = min(int(v[i]), bbox_min[i])
    return bbox_max, bbox_min

_FIXUP_KEYS = ["replace0" + str(i) for i in range(1,10)] + ["replace" + str(i) for i in range(10,17)]
    # $replace01, $replace02, ..., $replace15, $replace16
    
def get_fixup(inst):
    "Generate a list of all fixup keys for this item."
    vals = [find_key(inst, fix, "") for fix in _FIXUP_KEYS] # loop through and get each replace key
    return [f.value for f in vals if not f.value==""] # return only set values, without the property wrapper