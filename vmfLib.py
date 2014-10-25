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
        
        map_spawn = Property.find_key(tree, 'World', None)
        if map_spawn is None:
            map_spawn = Property("entity", [])
            
        brush_tree = Property.find_key(map_spawn, 'solid', None)
        map.brushes = [Solid.parse(map, b) for b in brush_tree]
        if brush_tree.value is not None:
           map_spawn.value.remove(brush_tree)
        map.spawn = Entity(map, map_spawn)
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
class Solid:
    "A single brush, as a world brushes and brush entities."
    def __init__(self, map, des_id = -1, planes = None):
        self.map = map
        self.sides = [] if sides is None else sides
        self.id = map.get_id('brush', map.solid_id)   
        
    @staticmethod    
    def parse(map, tree):
        "Parse a Property tree into a Solid object."
        pass

class Side:
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
            
    @staticmethod    
    def parse(map, tree):
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
        solids = None
        keys = {}
        outputs = []
        for item in tree_list:
            if item.name == "id" and item.value.isnumeric():
                id = item.value
            elif item.name == "solid":
                solids = Solid.parse(map, item)
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
        
class Instance(Entity):
    "A special type of entity, these have some perculiarities with $replace values."
    def __init__(self, map):
        Entity.__init__(self, map)
        
class Output:
    "An output from this item pointing to another."
    __slots__ = ('output', 'inst_out', 'target', 'input', 'inst_in', 'params', 'delay', 'times', 'sep')
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
            st += " once" if self.times==1 else (" " + str(self.times) + " times")
            st += " only"
        return st
        
    def export(self):
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
    
for i,ent in enumerate(map.entities):
    print(str(i) + "--------------------------------------------")
    if i<20:
        print(ent)
    