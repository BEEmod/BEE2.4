''' VMF Library
Wraps property_parser tree in a set of classes which smartly handle specifics of VMF files.
'''
from collections import defaultdict
from property_parser import Property, KeyValError, NoKeyError
import utils

_ID_types = {
    'brush' : 'solid_id', 
    'face'  : 'face_id', 
    'ent'   : 'ent_id'
    }

class VMF:
    '''
    Represents a VMF file, and holds counters for various IDs used. Has functions for searching
    for specific entities or brushes, and converts to/from a property_parser tree.
    '''
    def __init__(self, spawn = None, entities = None, brushes = None):
        self.solid_id = [] # All occupied solid ids
        self.face_id = []
        self.ent_id = []
        self.entities = [] if entities is None else entities
        self.brushes = [] if brushes is None else brushes
        self.spawn = Entity(self, []) if spawn is None else spawn
        
    def add_brush(self, item):
        self.brushes.append(item)
        
    def add_ent(self, item):
        self.entities.append(item)
        
    def add_brushes(self, item):
        for i in item:
            self.add_brush(i)
        
    def add_ents(self, item):
        for i in item:
            self.add_ent(i)
    
    @staticmethod
    def parse(tree):
        "Convert a property_parser tree into VMF classes."
        if not isinstance(tree, list):
            # if not a tree, try to read the file
            with open(tree, "r") as file:
                tree = Property.parse(file)
        map = VMF()
        ents = []
        map.entities = [Entity.parse(map, ent) for ent in Property.find_all(tree, 'Entity')]
        
        map_spawn = Property.find_key(tree, 'world', None)
        if map_spawn is None:
            map_spawn = Property("world", [])
            
        map.spawn = Entity.parse(map, map_spawn)
        print(map.spawn)
        if map.spawn.solids is not None:
           map.brushes = map.spawn.solids
           # Wipe this from the ent, so we don't have two copies
           map.spawn.solids = None 
        return map
    pass
    
    def get_id(self, ids, desired=-1):
        "Get an unused ID of a type."
        if ids not in _ID_types:
            raise ValueError('Invalid ID type!')
        list_ = self.__dict__[_ID_types[ids]]
        if len(list_)==0 or desired not in list_ :
            if desired==-1:
                desired = 1
            list_.append(desired)
            return desired
        # Need it in ascending order
        list_.sort()
        for id in range(0, list_[-1]+1):
            if id not in list_:
                list_.append(id)
                return id
                
    def find_ent(self, vals = {}, tags = {}):
        "Return a list of entities with the given keyvalue values, and with keyvalues containing the tags."
        if len(vals) == 0 and len(tags) == 0:
            return self.entities[:]
        else:
            ret = []
            for ent in self.entities:
                for key,value in vals.items():
                    print(ent[key], value)
                    if not ent.has_key(key) or ent[key] != value:
                        continue # It failed!        
                for key,value in vals.items():
                    if not ent.has_key(key) or value not in ent[key]:
                        continue # It failed!
                ret.append(ent)
            return ret
class Solid:
    "A single brush, as a world brushes and brush entities."
    def __init__(self, map, des_id = -1, sides = None):
        self.map = map
        self.sides = [] if sides is None else sides
        self.id = map.get_id('brush', des_id)   
        
    @staticmethod    
    def parse(map, tree):
        "Parse a Property tree into a Solid object."
        id = tree.find_key("id", -1).value
        try: 
            id = int(id)
        except TypeError:
            id = -1
        sides = []
        for side in tree.find_all("side"):
            sides.append(Side.parse(map, side))
        return Solid(map, des_id = id, sides=sides)
    
    def __str__(self):
        "Return a description of our data."
        st = "<solid:" + str(self.id) + ">\n{\n"
        for s in self.sides:
            st += str(s) + "\n"
        st += "}"
        return st

class Side:
    "A brush face."
    def __init__(self, map, planes = [(0, 0, 0),(0, 0, 0),(0, 0, 0)], opt = {}):
        self.map = map
        self.planes = [0,0,0]
        for i,pln in enumerate(planes):
            self.planes[i]=dict(x=pln[0], y=pln[1], z=pln[2])
        self.lightmap = opt.get("lightmap", 16)
        try: 
            self.lightmap = int(self.lightmap)
        except TypeError:
            self.lightmap = 16
        try:
            self.smooth = bin(opt.get("smoothing", 0))
        except TypeError:
            self.smooth = bin(0)

        self.mat = opt.get("material", "")
        self.ham_rot = opt.get("rotation" , "0")
            
    @staticmethod    
    def parse(map, tree):
        "Parse the property tree into a Side object."
        # planes = "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
        verts = tree.find_key("plane", "(0 0 0) (0 0 0) (0 0 0)").value[1:-1].split(") (")
        planes = [0,0,0]
        for i,v in enumerate(verts):
            verts = v.split(" ")
            if len(verts) == 3:
                planes[i]=verts
            else:
                raise ValueError("Invalid planes in '" + plane + "'!")
        if not len(planes) == 3:
            raise ValueError("Wrong number of solid planes in '" + plane + "'!")
        opt = { 
            'material' : tree.find_key('material', '').value,
            'uaxis' : tree.find_key('uaxis', '[0 1  0 0] 0.25').value,
            'vaxis' : tree.find_key('vaxis', '[0 0 -1 0] 0.25').value,
            'rotation' : tree.find_key('rotation', '0').value,
            'lightmap' : tree.find_key('lightmapscale', '0').value,
            'smoothing' : tree.find_key('smoothing_groups', '0').value,
            }
        return Side(map, planes=planes, opt = opt)
        
    def __str__(self):
        st = "\tmat = " + self.mat
        st += "\n\trotation = " + self.ham_rot + '\n'
        pl_str = [("(" + str(p['x']) 
                 + " " + str(p['y']) 
                 + " " + str(p['z']) + ")") for p in self.planes]
        st += '\tplane: ' + ", ".join(pl_str) + '\n'
        return st
class Entity():
    "Either a point or brush entity."
    def __init__(self, map, keys = None, id=-1, outputs = None, solids = None):
        self.map = map
        self.keys = {} if keys is None else keys
        self.outputs = outputs
        self.solids = solids
        self.id = map.get_id('ent', desired = id)
        
    @staticmethod
    def parse(map, tree_list):
        "Parse a property tree into an Entity object."
        id = -1
        solids = []
        keys = {}
        outputs = []
        for item in tree_list:
            if item.name == "id" and item.value.isnumeric():
                id = item.value
            elif item.name == "solid":
                solids.append(Solid.parse(map, item))
            elif item.name == "connections" and item.has_children():
                for out in item:
                    outputs.append(Output.parse(out))
            else:
                keys[item.name] = item.value
        return Entity(map, keys = keys, id = id, solids = solids, outputs=outputs)
    
    def remove(self):
        "Remove this entity from the map."
        self.map.entities.remove(self)
        self.map.ent_id.remove(self.id)
        
    def __str__(self):
        st ="<Entity>: \n{\n"
        for k,v in self.keys.items():
            if not isinstance(v, list):
                st+="\t " + k + ' = "' + v + '"\n'
        for out in self.outputs:
            st+='\t' + str(out) +'\n'
        st += "}\n"
        return st
        
    def __getitem__(self, key, default = None):
        if key in self.keys:
            return self.keys[key]
        else:
            return default
        
    def has_key(self, key):
        return key in self.keys
        
class Instance(Entity):
    "A special type of entity, these have some perculiarities with $replace values."
    def __init__(self, map):
        Entity.__init__(self, map)
        
class Output:
    "An output from this item pointing to another."
    __slots__ = ('output', 'inst_out', 'target', 
                 'input', 'inst_in', 'params', 'delay', 
                 'times', 'sep')
    def __init__(self,
                 out,
                 targ,
                 inp,
                 param = '',
                 delay = 0.0,
                 times = -1,
                 inst_out = None,
                 inst_in = None,
                 comma_sep = False):
        self.output = out
        self.inst_out = inst_out
        self.target = targ
        self.input = inp
        self.inst_in = inst_in
        self.params = param
        self.delay = delay 
        self.times = times
        self.sep = ',' if comma_sep else chr(27)
    
    @staticmethod
    def parse(prop):
        "Convert the VMF Property into an Output object."
        if ',' in prop.value:
            sep = True
            vals = prop.value.split(',')
        else:
            sep = False
            vals = prop.value.split(chr(27))
        if len(vals) == 5:
            if prop.name.startswith('instance:'):
                out = prop.name.split(';')
                inst_out = out[1]
                out = out[0][9:]
            else:
                inst_out = None
                out = prop.name
                
            if vals[1].startswith('instance:'):
                inp = vals[1].split(';')
                inst_inp = inp[1]
                inp = inp[0][9:]
            else:
                inst_inp = None
                inp = vals[1]
            return Output(
                out, 
                vals[0], 
                inp, 
                param = vals[2], 
                delay = float(vals[3]), 
                times=int(vals[4]), 
                inst_out = inst_out, 
                inst_in = inst_inp, 
                comma_sep = sep)
                
    def exp_out(self):
        if self.inst_out:
            return 'instance:' + self.inst_out + ';' + self.output
        else:
            return self.output
            
    def exp_in(self):
        if self.inst_in:
            return 'instance:' + self.inst_in + ';' + self.input
        else:
            return self.input
            
    def __str__(self):
        st = "<Output> "
        if self.inst_out:
            st += self.inst_out + ":" 
        st += self.output + " -> " + self.target
        if self.inst_in:
            st += "-" + self.inst_in
        st += " -> " + self.input
        
        if self.params and not self.inst_in:
            st += " (" + self.params + ")"
        if self.delay != 0:
            st += " after " + str(self.delay) + " seconds"
        if self.times != -1:
            st += " (once" if self.times==1 else (" (" + str(self.times) + " times")
            st += " only)"
        return st
        
    def export(self):
        "Generate the text required to define this output in the VMF."
        if self.inst_out:
            out = 'instance:' + self.inst_out + ';' + self.output
        else:
            out = self.output
            
        if self.inst_in:
            params = self.params
            inp = 'instance:' + self.inst_in + ';' + self.input
        else:
            inp = self.input
            params = self.params
            
        return '"' + out + '" "' + self.sep.join(
        (self.target, inp, self.params, str(self.delay), str(self.times))) + '"'
        
if __name__ == '__main__':
    map = VMF.parse('test.vmf')
    
for i,brush in enumerate(map.brushes):
    if i<20:
        print(brush)
    