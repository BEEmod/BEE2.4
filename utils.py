import math

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
    
def con_log(*text):
    print(*text, flush=True) 

# VMF specific        

def add_output(entity, output, target, input, params="", delay="0", times="-1"):
    "Add a new output to an entity with the given values, generating a connections part if needed."
    conn = entity.find_all('entity', 'connections')
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
            bbox_max=[int(x.split('.')[0])-99999 for x in verts[0][:]]
            bbox_min=[int(x.split('.')[0])+99999 for x in verts[0][:]]
        for v in verts:
            for i in range(0,3):
                bbox_max[i] = max(int(v[i].split('.')[0]), bbox_max[i])
                bbox_min[i] = min(int(v[i].split('.')[0]), bbox_min[i])
    return bbox_max, bbox_min

_FIXUP_KEYS = ["replace0" + str(i) for i in range(1,10)] + ["replace" + str(i) for i in range(10,17)]
    # $replace01, $replace02, ..., $replace15, $replace16
    
def get_fixup(inst):
    "Generate a list of all fixup keys for this item."
    vals = [inst.find_key(fix, "") for fix in _FIXUP_KEYS] # loop through and get each replace key
    return [f.value for f in vals if not f.value==""] # return only set values, without the property wrapper

class vec:
    "A 3D vector. This is immutable, and has most standard functions."
    __slots__ = ('x', 'y', 'z')
    
    def __init__(self, x = 0, y=0, z=0):
        # use this to let us set these, but not others
        object.__setattr__(self,'x', x)
        object.__setattr__(self,'y', y)
        object.__setattr__(self,'z', z)
        
    def copy(self):
        return vec(self.x, self.y, self.z)
    
    def __add__(self,other):
        "+ operation. This works on numbers (adds to all axes), or other vectors (adds to just our one)."
        if isinstance(other, vec):
            return vec(self.x+other.x, self.y+other.y)
        else:
            return vec(self.x+other, self.y+other,self.z+other)

            
    def __sub__(self,other):
        "- operation. This works on numbers (adds to all axes), or other vectors (adds to just our one)."
        if isinstance(other, vec):
            return vec(self.x-other.x, self.y-other.y)
        else:
            return vec(self.x-other, self.y-other)
    
    
    def __mul__(self, other):
        "Multiply the vector by a scalar."
        if isinstance(other, vec):
            return NotImplemented
        else:
            return vec(self.x * other, self.y * other, self.z * other)
            
    def __div__(self, other):
        "Divide the vector by a scalar."
        if isinstance(other, vec):
            return NotImplemented
        else:
            return vec(self.x / other, self.y / other, self.z / other)
            
    def __floordiv__(self, other):
        "Divide the vector by a scalar, discarding the remainder."
        if isinstance(other, vec):
            return NotImplemented
        else:
            return vec(self.x // other, self.y // other, self.z // other)
            
    def __mod__(self, other):
        "Compute the remainder of the vector divided by a scalar."
        if isinstance(other, vec):
            return NotImplemented
        else:
            return vec(self.x % other, self.y % other, self.z % other)
            
    def __divmod__(self, other):
        if isinstance(other, vec):
            return NotImplemented
        else:
            return self // other, self % other
            
    def __eq__(self, other):
        if isinstance(other, vec):
            return other.x==self.x and other.y==self.y and other.z==self.z
        
    def __len__(self):
        "Length gives the magnitude."
        if self.z == 0:
            return math.sqrt(self.x**2+self.y**2)
        else:
            return math.sqrt(self.x**2 + self.y**2 + self.z**2)
            
    def __iter__(self):
        "Allow iterating through the dimensions."
        yield self.x
        yield self.y
        yield sely.z
        
    def __getitem__(self, ind):
        "Allow referencing by index instead of name if desired."
        if index == 0 or index == "x":
            return self.x
        elif index == 1 or index == "y":
            return self.y
        elif index == 2 or index == "z":
            return self.z
    
    def __setattr__(self, key, val):
        "This is immutable, don't let people set the values."
        raise NotImplementedError
            
    def len_sq(self):
        "Return the magnitude squared, which is slightly faster."
        if self.z == 0:
            return self.x**2 + self.y**2
        else:
            return self.x**2 + self.y**2 + self.z**2
            
    def keys(self):
        return "x", "y", "z"
        
    def norm(self):
        "Normalise the vector by transforming it to have a magnitude of 1 but the same direction."
        if self.x == 0 and self.y==0 and self.z == 0:
            # Don't do anything for this, and don't copy
            return self
        else:
            return self / len(self)
    
    def dot(a, b):
        "Return the dot product of both vectors."
        return a.x*b.x + a.y*b.y + a.z*b.z
        
    def cross(a,b):
        "Return the cross product of both vectors."
        return vec(a.y*b.z - a.z*b.y,
                   a.z*b.x - a.x*b.z,
                   a.x*b.y - a.y*b.x)
    mag = __len__
    mag_sq = len_sq
    __iadd__ = __add__
    __isub__ = __sub__
    __idiv__ = __div__
    __truediv__ = __div__
    __itruediv__ = __div__
    __delattr__ = __setattr__