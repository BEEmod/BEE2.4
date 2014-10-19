''' VMF Library
Wraps property_parser tree in a set of classes which smartly handle specifics of VMF files.
'''
from property_parser import Property, KeyValError, NoKeyError
import utils

class VMF:
    '''
    Represents a VMF file, and holds counters for various IDs used. Has functions for searching
    for specific entities or brushes, and converts to/from a property_parser tree.
    '''
    pass
    
class Solid:
    '''
    A single brush, as a world brushes and brush entities.
    '''
    pass
    
class Entity(Property):
    '''
    Either a point or brush entity.
    '''
    pass
    
class Instance(Entity):
    '''
    A special type of entity, these have some perculiarities with $replace values.
    '''
    pass
    