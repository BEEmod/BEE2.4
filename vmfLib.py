''' VMF Library
Wraps property_parser tree in a set of classes which smartly handle specifics of VMF files.
'''
from collections import defaultdict
from property_parser import Property, KeyValError, NoKeyError
import utils

class VMF(object):
    '''
    Represents a VMF file, and holds counters for various IDs used. Has functions for searching
    for specific entities or brushes, and converts to/from a property_parser tree.
    '''
    def __init__(self, spawn = None, entities = None):
        self.solid_id = [] # All occupied solid ids
        self.face_id = []
        self.ent_id = []
        self.entities = [] if entities is None else entities
        self.spawn = Entity(self, []) if spawn is None else spawn
    def parse(tree):
        "Convert a property_parser tree into VMF classes."
        pass
    pass
    
    def get_id(ids):
        "Get an unused ID of a type."
        list.sort() # Need it in ascending order
        for id in xrange(0, list[-1]+1):
            if id not in list:
                list.insert(id)
                return id
class Solid(object):
    "A single brush, as a world brushes and brush entities."
    def __init__(self, map, des_id = -1, planes = None):
        self.map = map
        self.sides = [] if sides is None else sides
        if des_id == -1 or des_id in map.solid_id:
            self.id = map.get_id(map.solid_id)
        else:
            self.id = des_id
        
    def parse(tree):
        "Parse a Property tree into a Solid object."
        pass
class Side(object):
    "A brush face."
    def __init__(self, map, planes = [(0, 0, 0),(0, 0, 0),(0, 0, 0)], opt = {}):
        self.map = maps
        self.planes = []
        for i in planes:
            self.planes[i]=dict(x=planes[0], y=planes[1], z=planes[2])
        self.lightmap = opt.get("lightmap", 16),
        smooth = str(bin(opt.get("smoothing", 0))).split("0b")[1][::-1]
        # convert to binary and back to get the digits individually, and then produce a list.
        self.smoothing = defaultdict(lambda: False)
        for i,val in reversed(enumerate(smooth)):
            self.smoothing[i] = (val=='1')
        
    def parse(tree):
        "Parse the property tree into a Side object."
        # planes = "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
        planes = plane.value[1:-1].split(") (")
        for i,v in enumerate(verts):
            verts = v.split(" ")
            if len(verts) == 3:
                planes[i]=verts
            else:
                raise ValueError("Invalid planes in '" + plane + "'!")
        if not len(planes) == 3:
            raise ValueError("Wrong number of solid planes in '" + plane + "'!")
    
class Entity(Property):
    "Either a point or brush entity."
    def __init__(self, map):
        pass
    def load(self, tree):
        "Parse a property tree into an Entity object."
        pass
    
class Instance(Entity):
    "A special type of entity, these have some perculiarities with $replace values."
    pass
    def __init__(self, map):
        self.map = map