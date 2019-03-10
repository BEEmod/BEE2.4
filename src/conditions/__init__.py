"""Implements the Conditions system.

This system allows users to define transformations applied to
every instance.

In pseudocode:
    for cond in all_conditions:
        for inst in vmf:
            if all(flag() in cond):
                apply_results()

Both results and flags recieve configuration keyvalues, the vmf and the
current instance. Flags return a boolean to indicate if they are successful.
Results return None normally, but can return the special value RES_EXHAUSTED to
indicate calling the specific result again will have no effect. In this case the
result will be deleted.

Argument type annotations are used to allow flexibility in defining results and
flags. Each argument must be typed as one of the following to recieve a specific
value:
    * VMF to recieve the overall map.
    * Entity to recieve the current instance.
    * Property to recieve keyvalues configuration.
"""
import inspect
import io
import itertools
import math
import random
from collections import defaultdict
from decimal import Decimal
from enum import Enum

from typing import (
    Callable, Any, Iterable, Optional,
    Dict, List, Tuple, NamedTuple, TypeVar,
    Union,
    Set,
    TextIO,
)

import comp_consts as consts
import srctools.logger
import template_brush
import utils
import comp_consts as const
import instanceLocs
from srctools import (
    Property,
    Vec_tuple, Vec,
    Entity, Output, Solid, Side
)

COND_MOD_NAME = 'Main Conditions'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.core')

# Stuff we get from VBSP in init()
GLOBAL_INSTANCES = set()  # type: Set[str]
ALL_INST = set()  # type: Set[str]
VMF = None  # type: srctools.VMF

conditions = []
FLAG_LOOKUP = {}  # type: Dict[str, Callable[[srctools.VMF, Entity, Property], bool]]
RESULT_LOOKUP = {}  # type: Dict[str, Callable[[srctools.VMF, Entity, Property], object]]
RESULT_SETUP = {}  # type: Dict[str, Callable[[srctools.VMF, Property], object]]

# Used to dump a list of the flags, results, meta-conditions
ALL_FLAGS = []  # type: List[Tuple[str, Iterable[str], Callable[[srctools.VMF, Entity, Property], bool]]]
ALL_RESULTS = []  # type: List[Tuple[str, Iterable[str], Callable[[srctools.VMF, Entity, Property], bool]]]
ALL_META = []  # type: List[Tuple[str, Decimal, Callable[[srctools.VMF], None]]]

GOO_LOCS = {}  # A mapping from blocks containing goo to the top face
GOO_FACE_LOC = {}  # A mapping from face origin -> face for top faces.

# A template shaped like embeddedVoxel blocks
TEMP_EMBEDDED_VOXEL = 'BEE2_EMBEDDED_VOXEL'


class SWITCH_TYPE(Enum):
    """The methods useable for switch options."""
    FIRST = 'first'  # choose the first match
    LAST = 'last'  # choose the last match
    RANDOM = 'random'  # Randomly choose
    ALL = 'all'  # Run all matching commands


# A dictionary mapping origins to their brushes
solidGroup = NamedTuple('solidGroup', [
    ('face', Side),
    ('solid', Solid),
    ('normal', Vec),  # The normal of the face.
    ('color', template_brush.MAT_TYPES),
])
SOLIDS = {}  # type: Dict[Vec_tuple, solidGroup]


# For each class, a list of item IDs of that type.
ITEMS_WITH_CLASS = defaultdict(list)  # type: Dict[consts.ItemClass, List[str]]
# For each item Id, the item class for it.
CLASS_FOR_ITEM = {}  # type: Dict[str, consts.ItemClass]


xp = Vec_tuple(1, 0, 0)
xn = Vec_tuple(-1, 0, 0)
yp = Vec_tuple(0, 1, 0)
yn = Vec_tuple(0, -1, 0)
zp = Vec_tuple(0, 0, 1)
zn = Vec_tuple(0, 0, -1)

DIRECTIONS = {
    # Translate these words into a normal vector
    '+x': xp,
    '-x': xn,

    '+y': yp,
    '-y': yn,

    '+z': zp,
    '-z': zn,

    'x': xp,  # For with allow_inverse
    'y': yp,
    'z': zp,

    'up': zp,
    'dn': zn,
    'down': zn,
    'floor': zp,
    'ceiling': zn,
    'ceil': zn,

    'n': yp,
    'north': yp,
    's': yn,
    'south': yn,

    'e': xp,
    'east': xp,
    'w': xn,
    'west': xn,

    'wall': 'WALL',  # Special case, not floor/ceiling
    'walls': 'WALL',
}

INST_ANGLE = {
    # IE up = zp = floor
    zp: "0 0 0",
    zn: "0 0 0",

    xn: "0 0 0",
    yn: "0 90 0",
    xp: "0 180 0",
    yp: "0 270 0",

}

PETI_INST_ANGLE = {
    # The angles needed to point a PeTI instance in this direction
    # IE north = yn

    yn: "0 0 90",
    xp: "0 90 90",
    yp: "0 180 90",
    xn: "0 270 90",
}

del xp, xn, yp, yn, zp, zn


class NextInstance(Exception):
    """Raised to skip to the next instance, from the SkipInstance result."""
    pass


class EndCondition(Exception):
    """Raised to skip the condition entirely, from the EndCond result."""
    pass

# Flag to indicate a result doesn't need to be exectuted anymore,
# and can be cleaned up - adding a global instance, for example.
RES_EXHAUSTED = object()


class Condition:
    __slots__ = ['flags', 'results', 'else_results', 'priority', 'source']

    def __init__(
        self,
        flags: List[Property]=None,
        results: List[Property]=None,
        else_results: List[Property]=None,
        priority: Decimal=Decimal(),
        source: str=None,
    ) -> None:
        self.flags = flags or []
        self.results = results or []
        self.else_results = else_results or []
        self.priority = priority
        self.source = source
        self.setup()

    def __repr__(self):
        return (
            'Condition(flags={!r}, '
            'results={!r}, else_results={!r}, '
            'priority={!r}'
        ).format(
            self.flags,
            self.results,
            self.else_results,
            self.priority,
        )

    @classmethod
    def parse(cls, prop_block: Property) -> 'Condition':
        """Create a condition from a Property block."""
        flags = []  # type: List[Property]
        results = []  # type: List[Property]
        else_results = []  # type: List[Property]
        priority = Decimal()
        source = None
        for prop in prop_block:
            if prop.name == 'result':
                results.extend(prop.value)  # join multiple ones together
            elif prop.name == 'else':
                else_results.extend(prop.value)
            elif prop.name == '__src__':
                # Value injected by the BEE2 export, this specifies
                # the original source of the config.
                source = prop.value

            elif prop.name in ('condition', 'switch'):
                # Shortcut to eliminate lots of Result - Condition pairs
                results.append(prop)
            elif prop.name == 'elsecondition':
                prop.name = 'condition'
                else_results.append(prop)
            elif prop.name == 'elseswitch':
                prop.name = 'switch'
                else_results.append(prop)
            elif prop.name == 'priority':
                try:
                    priority = Decimal(prop.value)
                except ArithmeticError:
                    pass
            else:
                flags.append(prop)

        return cls(
            flags,
            results,
            else_results,
            priority,
            source,
        )

    def setup(self) -> None:
        """Some results need some pre-processing before they can be used.

        """
        for res in self.results[:]:
            self.setup_result(self.results, res, self.source)

        for res in self.else_results[:]:
            self.setup_result(self.else_results, res, self.source)

    @staticmethod
    def setup_result(res_list: List[Property], result: Property, source: Optional[str]='') -> None:
        """Helper method to perform result setup."""
        func = RESULT_SETUP.get(result.name)
        if func:
            # noinspection PyBroadException
            try:
                result.value = func(VMF, result)
            except:
                # Print the source of the condition if if fails...
                LOGGER.exception(
                    'Error in {} setup:',
                    source or 'condition',
                )
                if utils.DEV_MODE:
                    # Crash so this is immediately noticable..
                    utils.quit_app(1)
                else:
                    # In release, just skip this one - that way it's
                    # still hopefully possible to run the game.
                    result.value = None
            if result.value is None:
                # This result is invalid, remove it.
                res_list.remove(result)

    @staticmethod
    def test_result(inst: Entity, res: Property) -> Union[bool, object]:
        """Execute the given result."""
        try:
            func = RESULT_LOOKUP[res.name]
        except KeyError:
            err_msg = '"{name}" is not a valid condition result!'.format(
                name=res.real_name,
            )
            if utils.DEV_MODE:
                # Crash here.
                raise ValueError(err_msg) from None
            else:
                LOGGER.warning(err_msg)
                # Delete this so it doesn't re-fire..
                return RES_EXHAUSTED
        else:
            return func(VMF, inst, res)

    def test(self, inst: Entity) -> None:
        """Try to satisfy this condition on the given instance."""
        success = True
        for flag in self.flags:
            if not check_flag(flag, inst):
                success = False
                break
        results = self.results if success else self.else_results
        for res in results[:]:
            should_del = self.test_result(inst, res)
            if should_del is RES_EXHAUSTED:
                results.remove(res)


AnnCallT = TypeVar('AnnCallT')


def annotation_caller(
    func: Callable[..., AnnCallT],
    *parms: type,
) -> Callable[..., AnnCallT]:
    """Reorders callback arguments to the requirements of the callback.

    parms should be the unique types of arguments in the order they will be
    called with. func's arguments should be positional, and be annotated
    with the same types. A wrapper will be returned which can be called
    with the parms arguments, but delegates to func. (This could be the
    function itself).
    """
    allowed_kinds = [
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ]
    type_to_parm = dict.fromkeys(parms, None)  # type: Dict[object, Optional[str]]
    sig = inspect.signature(func)
    for parm in sig.parameters.values():
        ann = parm.annotation
        if isinstance(ann, str):
            ann = eval(ann)
        if parm.kind not in allowed_kinds:
            raise ValueError('Parameter kind "{}" is not allowed!'.format(parm.kind))
        if ann is inspect.Parameter.empty:
            raise ValueError('Parameters must have value!')
        try:
            if type_to_parm[ann] is not None:
                raise ValueError('Parameter {} used twice!'.format(ann))
        except KeyError:
            raise ValueError('Unknown potential type {!r}'.format(ann))
        type_to_parm[ann] = parm.name
    inputs = []
    outputs = ['_'] * len(sig.parameters)
    # Parameter -> letter in func signature
    parm_order = {
        parm.name: ind
        for ind, parm in
        enumerate(sig.parameters.values())
    }
    letters = 'abcdefghijklmnopqrstuvwxyz'
    for var_name, parm_typ in zip(letters, parms):
        inputs.append(var_name)
        out_name = type_to_parm[parm_typ]
        if out_name is not None:
            outputs[parm_order[out_name]] = var_name

    assert '_' not in outputs, 'Need more variables!'

    if inputs == outputs:
        # Matches already, don't need to do anything.
        return func

    # Double function to make a closure, to allow reference to the function
    # more directly.
    # Lambdas are expressions, so we can return the result directly.
    return eval(
        '(lambda func: lambda {}: func({}))(func)'.format(
            ', '.join(inputs),
            ', '.join(outputs),
        ),
        {'func': func},
    )


def add_meta(func, priority: Union[Decimal, int], only_once=True):
    """Add a metacondition, which executes a function at a priority level.

    Used to allow users to allow adding conditions before or after a
    transformation like the adding of quotes.
    """
    dec_priority = Decimal(priority)
    # This adds a condition result like "func" (with quotes), which cannot
    # be entered into property files.
    # The qualname will be unique across modules.
    name = '"' + func.__qualname__ + '"'
    LOGGER.debug(
        "Adding metacondition ({}) with priority {!s}!",
        name,
        dec_priority,
    )

    RESULT_LOOKUP[name] = annotation_caller(func, srctools.VMF, Entity, Property)

    cond = Condition(
        results=[Property(name, '')],
        priority=Decimal(dec_priority),
        source='MetaCondition {}'.format(name)
    )

    if only_once:
        cond.results.append(
            Property('endCondition', '')
        )
    conditions.append(cond)
    ALL_META.append((name, dec_priority, func))


def meta_cond(priority=0, only_once=True):
    """Decorator version of add_meta."""
    def x(func):
        add_meta(func, priority, only_once)
        return func
    return x


def make_flag(orig_name: str, *aliases: str):
    """Decorator to add flags to the lookup."""
    def x(func):
        try:
            func.group = func.__globals__['COND_MOD_NAME']
        except KeyError:
            func.group = func.__globals__['__name__']
            LOGGER.info('No name for module "{}"!', func.group)

        wrapper = annotation_caller(func, srctools.VMF, Entity, Property)
        ALL_FLAGS.append(
            (orig_name, aliases, func)
        )
        FLAG_LOOKUP[orig_name.casefold()] = wrapper
        for name in aliases:
            FLAG_LOOKUP[name.casefold()] = wrapper
        return func
    return x


def make_result(orig_name: str, *aliases: str):
    """Decorator to add results to the lookup."""
    def x(func):
        try:
            func.group = func.__globals__['COND_MOD_NAME']
        except KeyError:
            func.group = func.__globals__['__name__']
            LOGGER.info('No name for module "{}"!', func.group)

        wrapper = annotation_caller(func, srctools.VMF, Entity, Property)
        ALL_RESULTS.append(
            (orig_name, aliases, func)
        )
        RESULT_LOOKUP[orig_name.casefold()] = wrapper
        for name in aliases:
            RESULT_LOOKUP[name.casefold()] = wrapper
        return func
    return x


def make_result_setup(*names: str):
    """Decorator to do setup for this result."""
    def x(func: Callable[..., Any]):
        wrapper = annotation_caller(func, srctools.VMF, Property)
        for name in names:
            RESULT_SETUP[name.casefold()] = wrapper
        return func
    return x


def add(prop_block):
    """Parse and add a condition to the list."""
    con = Condition.parse(prop_block)
    if con.results or con.else_results:
        conditions.append(con)


def init(seed: str, inst_list: Set[str], vmf_file: srctools.vmf.VMF) -> None:
    """Initialise the Conditions system."""
    # Get a bunch of values from VBSP
    global MAP_RAND_SEED, ALL_INST, VMF
    VMF = vmf_file
    MAP_RAND_SEED = seed
    ALL_INST.update(inst_list)

    # Sort by priority, where higher = done later
    zero = Decimal(0)
    conditions.sort(key=lambda cond: getattr(cond, 'priority', zero))

    build_solid_dict()


def check_all() -> None:
    """Check all conditions."""
    LOGGER.info('Checking Conditions...')
    for condition in conditions:
        for inst in VMF.by_class['func_instance']:
            try:
                condition.test(inst)
            except NextInstance:
                # This is raised to immediately stop running
                # this condition, and skip to the next instance.
                pass
            except EndCondition:
                # This is raised to immediately stop running
                # this condition, and skip to the next condtion.
                break
            except:
                # Print the source of the condition if if fails...
                LOGGER.exception(
                    'Error in {}:',
                    condition.source or 'condition',
                )
                # Exit directly, so we don't print it again in the exception
                # handler
                utils.quit_app(1)
            if not condition.results and not condition.else_results:
                break  # Condition has run out of results, quit early

    import vbsp
    LOGGER.info('Map has attributes: {}', [
        key
        for key, value in
        vbsp.settings['has_attr'].items()
        if value
    ])
    # Dynamically added by lru_cache()
    # noinspection PyUnresolvedReferences
    LOGGER.info('instanceLocs cache: {}', instanceLocs.resolve.cache_info())
    LOGGER.info('Style Vars: {}', dict(vbsp.settings['style_vars']))
    LOGGER.info('Global instances: {}', GLOBAL_INSTANCES)


def check_flag(flag: Property, inst: Entity):
    """Determine the result for a condition flag."""
    name = flag.name
    # If starting with '!', invert the result.
    if name[:1] == '!':
        desired_result = False
        name = name[1:]
    else:
        desired_result = True
    try:
        func = FLAG_LOOKUP[name]
    except KeyError:
        err_msg = '"{}" is not a valid condition flag!'.format(name)
        if utils.DEV_MODE:
            # Crash here.
            raise ValueError(err_msg) from None
        else:
            LOGGER.warning(err_msg)
            # Skip these conditions..
            return False

    res = func(VMF, inst, flag)
    return res == desired_result


def import_conditions() -> None:
    """Import all the components of the conditions package.

    This ensures everything gets registered.
    """
    import importlib
    import pkgutil
    # Find the modules in the conditions package.
    # PyInstaller messes this up a bit.

    if utils.FROZEN:
        # This is the PyInstaller loader injected during bootstrap.
        # See PyInstaller/loader/pyimod03_importers.py
        # toc is a PyInstaller-specific attribute containing a set of
        # all frozen modules.
        loader = pkgutil.get_loader('conditions')
        modules = [
            module
            for module in loader.toc
            if module.startswith('conditions.')
        ]  # type: List[str]
    else:
        # We can grab them properly.
        modules = [
            'conditions.' + module
            for loader, module, is_package in
            pkgutil.iter_modules(__path__)
        ]

    for module in modules:
        # Import the module, then discard it. The module will run add_flag
        # or add_result() functions, which save the functions into our dicts.
        # We don't need a reference to the modules themselves.
        LOGGER.debug('Importing {} ...', module)
        importlib.import_module(module)
    LOGGER.info('Imported all conditions modules!')


def build_solid_dict() -> None:
    """Build a dictionary mapping origins to brush faces.

    This allows easily finding brushes that are at certain locations.
    """
    import vbsp
    mat_types = {}
    for mat in vbsp.BLACK_PAN:
        mat_types[mat] = template_brush.MAT_TYPES.black

    for mat in vbsp.WHITE_PAN:
        mat_types[mat] = template_brush.MAT_TYPES.white

    for solid in VMF.brushes:
        for face in solid:
            if face.mat.casefold in consts.Goo:
                # Record all locations containing goo.
                bbox_min, bbox_max = solid.get_bbox()
                x = bbox_min.x + 64
                y = bbox_min.y + 64
                # If goo is multi-level, we want to record all pos!
                for z in range(int(bbox_min.z) + 64, int(bbox_max.z), 128):
                    GOO_LOCS[Vec_tuple(x, y, z)] = face

                # Add the location of the top face
                GOO_FACE_LOC[Vec_tuple(x, y, bbox_max.z)] = face

                # Indicate that this map contains goo...
                vbsp.settings['has_attr']['goo'] = True
                continue

            try:
                mat_type = mat_types[face.mat]
            except KeyError:
                continue
            else:
                origin = face.get_origin().as_tuple()
                if origin in SOLIDS:
                    # The only time two textures will be in the same
                    # place is if they are covering each other -
                    # nodraw them both and ignore them
                    SOLIDS.pop(origin).face.mat = consts.Tools.NODRAW
                    face.mat = consts.Tools.NODRAW
                    continue

                SOLIDS[origin] = solidGroup(
                    color=mat_type,
                    face=face,
                    solid=solid,
                    normal=face.normal(),
                )


def build_itemclass_dict(prop_block: Property):
    """Load in the dictionary mapping item classes to item ids"""
    for prop in prop_block.find_children('ItemClasses'):
        try:
            it_class = consts.ItemClass(prop.value)
        except KeyError:
            LOGGER.warning('Unknown item class "{}"', prop.value)
            continue

        ITEMS_WITH_CLASS[it_class].append(prop.name)
        CLASS_FOR_ITEM[prop.name] = it_class


DOC_MARKER = '''<!-- Only edit above this line. This is generated from text in the compiler code. -->'''

DOC_META_COND = '''

### Meta-Conditions

Metaconditions are conditions run automatically by the compiler. These exist
so package conditions can choose a priority to run before or after these 
operations.


'''

DOC_SPECIAL_GROUP = '''\
### Specialized Conditions

These are used to implement complex items which need their own code.
They have limited utility otherwise.

'''


def dump_conditions(file: TextIO) -> None:
    """Dump docs for all the condition flags, results and metaconditions."""

    LOGGER.info('Dumping conditions...')

    # Delete existing data, after the marker.
    file.seek(0, io.SEEK_SET)

    prelude = []

    for line in file:
        if DOC_MARKER in line:
            break
        prelude.append(line)

    file.seek(0, io.SEEK_SET)
    file.truncate(0)

    if not prelude:
        # No marker, blank the whole thing.
        LOGGER.warning('No intro text before marker!')

    for line in prelude:
        file.write(line)
    file.write(DOC_MARKER + '\n\n')

    file.write(DOC_META_COND)

    ALL_META.sort(key=lambda i: i[1])  # Sort by priority
    for flag_key, priority, func in ALL_META:
        file.write('#### `{}` ({}):\n\n'.format(flag_key, priority))
        dump_func_docs(file, func)
        file.write('\n')

    for lookup, name in [
            (ALL_FLAGS, 'Flags'),
            (ALL_RESULTS, 'Results'),
            ]:
        print('<!------->', file=file)
        print('# ' + name, file=file)
        print('<!------->', file=file)

        lookup_grouped = defaultdict(list)  # type: Dict[str, List[Tuple[str, Tuple[str, ...], Callable]]]

        for flag_key, aliases, func in lookup:
            group = getattr(func, 'group', 'ERROR')
            if group is None:
                group = '00special'
            lookup_grouped[group].append((flag_key, aliases, func))

        # Collapse 1-large groups into Ungrouped.
        for group in list(lookup_grouped):
            if len(lookup_grouped[group]) < 2:
                lookup_grouped[''].extend(lookup_grouped[group])
                del lookup_grouped[group]

        if not lookup_grouped['']:
            del lookup_grouped['']

        for header_ind, (group, funcs) in enumerate(sorted(lookup_grouped.items())):
            if group == '':
                group = 'Ungrouped Conditions'

            if header_ind:
                # Not before the first one...
                print('---------\n', file=file)

            if group == '00special':
                print(DOC_SPECIAL_GROUP, file=file)
            else:
                print('### ' + group + '\n', file=file)

            LOGGER.info('Doing {} group...', group)

            for flag_key, aliases, func in funcs:
                print('#### `{}`:\n'.format(flag_key), file=file)
                if aliases:
                    print('**Aliases:** `' + '`, `'.join(aliases) + '`' + '  \n', file=file)
                dump_func_docs(file, func)
                file.write('\n')


def dump_func_docs(file: TextIO, func: Callable):
    import inspect
    docs = inspect.getdoc(func)
    if docs:
        print(docs, file=file)
    else:
        print('**No documentation!**', file=file)


def weighted_random(count: int, weights: str) -> List[int]:
    """Generate random indexes with weights.

    This produces a list intended to be fed to random.choice(), with
    repeated indexes corresponding to the comma-separated weight values.
    """
    if weights == '':
        # Empty = equal weighting.
        return list(range(count))
    if ',' not in weights:
        LOGGER.warning('Invalid weight! ({})', weights)
        return list(range(count))

    # Parse the weight
    vals = weights.split(',')
    weight = []
    if len(vals) == count:
        for i, val in enumerate(vals):
            val = val.strip()
            if val.isdecimal():
                # repeat the index the correct number of times
                weight.extend(
                    [i] * int(val)
                )
            else:
                # Abandon parsing
                break
    if len(weight) == 0:
        LOGGER.warning('Failed parsing weight! ({!s})',weight)
        weight = list(range(count))
    # random.choice(weight) will now give an index with the correct
    # probabilities.
    return weight


def add_output(inst: Entity, prop: Property, target: str) -> None:
    """Add a customisable output to an instance."""
    inst.add_out(Output(
        prop['output', ''],
        target,
        prop['input', ''],
        inst_in=prop['targ_in', ''],
        inst_out=prop['targ_out', ''],
        ))


def add_suffix(inst: Entity, suff: str) -> None:
    """Append the given suffix to the instance.
    """
    file = inst['file']
    old_name, dot, ext = file.partition('.')
    inst['file'] = ''.join((old_name, suff, dot, ext))


def local_name(inst: Entity, name: Union[str, Entity]) -> str:
    """Fixup the given name for inside an instance.

    This handles @names, !activator, and obeys the fixup_style option.

    If the name is an entity, that entity's name is passed through unchanged.
    """
    # Don't translate direct entity names - it's already the entity's full
    # name.
    if isinstance(name, Entity):
        return name['targetname']

    # If blank, keep it blank, and don't fix special or global names
    if not name or name.startswith(('!', '@')):
        return name

    fixup = inst['fixup_style', '0']
    targ_name = inst['targetname', '']

    if fixup == '2' or not targ_name:
        # We can't do fixup..
        return name
    elif fixup == '0':
        # Prefix
        return targ_name + '-' + name
    elif fixup == '1':
        # Postfix
        return name + '-' + targ_name
    else:
        raise ValueError('Unknown fixup style {}!'.format(fixup))


def widen_fizz_brush(brush: Solid, thickness: float, bounds: Tuple[Vec, Vec]=None):
    """Move the two faces of a fizzler brush outward.

    This is good to make fizzlers which are thicker than 2 units.
    bounds is the output of .get_bbox(), if this should be overriden
    """

    # Subtract 2 for the fizzler width, and divide
    # to get the difference for each face.
    offset = (thickness-2)/2

    if bounds is None:
        bound_min, bound_max = brush.get_bbox()
    else:
        # Allow passing these in
        bound_min, bound_max = bounds
    origin = (bound_max + bound_min) / 2
    size = bound_max - bound_min
    for axis in 'xyz':
        # One of the directions will be thinner than 32, that's the fizzler
        # direction.
        if size[axis] < 32:
            bound_min[axis] -= offset
            bound_max[axis] += offset

    for face in brush:
        # For every coordinate, set to the maximum if it's larger than the
        # origin. This will expand the two sides.
        for v in face.planes:
            for axis in 'xyz':
                if v[axis] > origin[axis]:
                    v[axis] = bound_max[axis]
                else:
                    v[axis] = bound_min[axis]


def remove_ant_toggle(toggle_ent: Entity):
    """Remove a texture_toggle instance , plus the associated antline.

    For non-toggle instances, they will just be removed.
    """
    toggle_ent.remove()

    # Assume anything with '$indicator_name' is a toggle instance
    # This will likely be called on the signs too, if present.
    overlay_name = toggle_ent.fixup[consts.FixupVars.TOGGLE_OVERLAY, '']
    if overlay_name != '':
        for ent in VMF.by_target[overlay_name]:
            ent.remove()


def reallocate_overlays(mapping: Dict[str, Optional[List[str]]]):
    """Replace one side ID with others in all overlays.

    The IDs should be strings.
    """
    for overlay in VMF.by_class['info_overlay']:
        sides = overlay['sides', ''].split(' ')
        for side in sides[:]:
            try:
                new_ids = mapping[side]
            except KeyError:
                continue
            sides.remove(side)
            if new_ids is not None:
                sides.extend(new_ids)
        if not sides:
            # The overlay doesn't have any sides at all!
            VMF.remove_ent(overlay)
        else:
            overlay['sides'] = ' '.join(sides)


def steal_from_brush(
    temp_data: template_brush.ExportedTemplate,
    brush_group: 'solidGroup',
    rem_brush=True,
    additional: Iterable[int]=(),
    transfer_overlays=True,
):
    """Copy IDs from a brush to a template."""
    temp_brushes = temp_data.world.copy()
    # Overlays can't be applied to entities (other than func_detail).
    if temp_data.detail is not None and temp_data.detail['classname'] == 'func_detail':
        temp_brushes.extend(temp_data.detail.solids)

    if rem_brush:
        VMF.remove_brush(brush_group.solid)
    else:
        # Switch it to nodraw if still in the map, since it must be
        # covered.
        brush_group.face.mat = 'tools/toolsnodraw'

    # Additional is a list of IDs in the template VMF, not the final one.
    additional = {
        temp_data.orig_ids.get(int(face_id), -1)
        for face_id in
        additional
    }
    new_ids = []  # type: List[str]

    for brush in temp_brushes:
        for face in brush.sides:
            # Only faces pointing the same way!
            if face.normal() == brush_group.normal:
                # Skip tool brushes in the template (nodraw, player clips..)
                if face.mat.casefold().startswith('tools/'):
                    continue
                new_ids.append(str(face.id))
            # If the original ID is present in the 'additional' values
            # use it. This allows specifying specific faces.
            elif face.id in additional:
                new_ids.append(str(face.id))

    if new_ids:
        if not transfer_overlays:
            new_ids = None
        reallocate_overlays({
            str(brush_group.face.id): new_ids,
        })


def set_ent_keys(
    ent: Entity,
    inst: Entity,
    prop_block: Property,
    block_name: str='Keys',
) -> None:
    """Copy the given key prop block to an entity.

    This uses the keys and 'localkeys' properties on the prop_block.
    Values with $fixup variables will be treated appropriately.
    LocalKeys keys will be changed to use instance-local names, where needed.
    block_name lets you change the 'keys' suffix on the prop_block name.
    ent can be any mapping.
    """
    for prop in prop_block.find_key(block_name, []):
        ent[prop.real_name] = resolve_value(inst, prop.value)
    for prop in prop_block.find_key('Local' + block_name, []):
        if prop.value.startswith('$'):
            val = inst.fixup[prop.value]
        else:
            val = prop.value
        if val.startswith('@'):
            ent[prop.real_name] = val
        else:
            ent[prop.real_name] = local_name(inst, val)

T = TypeVar('T')


def resolve_value(inst: Entity, value: Union[str, T]) -> Union[str, T]:
    """If a value starts with '$', lookup the associated var.

    Non-string values are passed through unchanged.
    If it starts with '!' (before '$'), invert boolean values.
    """
    if not isinstance(value, str):
        return value

    if value.startswith('!$'):
        inverted = True
        value = value[1:]
    else:
        inverted = False

    if value.startswith('$'):
        if value in inst.fixup:
            value = inst.fixup[value]
        else:
            LOGGER.warning(
                'Invalid fixup ({}) in the "{}" instance:\n{}\n{}',
                value,
                inst['targetname'],
                inst,
                inst.fixup._fixup
            )
            value = ''

    if inverted:
        return srctools.bool_as_int(not srctools.conv_bool(value))
    else:
        return value


def resolve_offset(inst, value: str, scale: float=1, zoff: float=0) -> Vec:
    """Retrieve an offset from an instance var. This allows several special values:

    * $var to read from a variable
    * <piston_start> or <piston> to get the unpowered position of a piston plat
    * <piston_end> to get the powered position of a piston plat
    * <piston_top> to get the extended position of a piston plat
    * <piston_bottom> to get the retracted position of a piston plat

    If scale is set, read values are multiplied by this, and zoff is added to Z.
    """
    value = value.casefold()
    # Offset the overlay by the given distance
    # Some special placeholder values:
    if value == '<piston_start>' or value == '<piston>':
        if inst.fixup.bool(const.FixupVars.PIST_IS_UP):
            value = '<piston_top>'
        else:
            value = '<piston_bottom>'
    elif value == '<piston_end>':
        if inst.fixup.bool(const.FixupVars.PIST_IS_UP):
            value = '<piston_bottom>'
        else:
            value = '<piston_top>'

    if value == '<piston_bottom>':
        offset = Vec(
            z=inst.fixup.int(const.FixupVars.PIST_BTM) * 128,
        )
    elif value == '<piston_top>':
        offset = Vec(
            z=inst.fixup.int(const.FixupVars.PIST_TOP) * 128,
        )
    else:
        # Regular vector
        offset = Vec.from_str(resolve_value(inst, value)) * scale
    offset.z += zoff

    offset.localise(
        Vec.from_str(inst['origin']),
        Vec.from_str(inst['angles']),
    )

    return offset


def hollow_block(solid_group: solidGroup, remove_orig_face=False):
    """Convert a solid into a embeddedVoxel-style block.

    The original brushes must be in the SOLIDS dict. They will be replaced.
    This returns a dict mapping normals to the new solidGroups.
    If remove_orig_face is true, the starting face will not be kept.
    """
    import vbsp
    orig_solid = solid_group.solid  # type: Solid

    bbox_min, bbox_max = orig_solid.get_bbox()
    if 4 in (bbox_max - bbox_min):
        # If it's 4 units thick, skip hollowing - PeTI did it already.
        if remove_orig_face:
            VMF.remove_brush(orig_solid)
            del SOLIDS[solid_group.face.get_origin().as_tuple()]
        return

    VMF.remove_brush(orig_solid)

    for face in orig_solid.sides:
        if remove_orig_face and face is solid_group.face:
            # Skip readding the original face, which removes it.
            continue

        solid_key = face.get_origin().as_tuple()

        if face.mat.casefold() == 'tools/toolsnodraw' and face not in vbsp.IGNORED_FACES:
            # If it's nodraw, we can skip it. If it's also in IGNORED_FACES
            # though a condition has set it, so recreate it (it might be sealing
            # the void behind a func_detail or model).
            continue

        # Remove this face from the solids list, and get the group.
        face_group = SOLIDS.pop(solid_key, None)

        normal = face.normal()

        # Generate our new brush.
        new_brushes = template_brush.import_template(
            TEMP_EMBEDDED_VOXEL,
            face.get_origin(),
            # The normal Z is swapped...
            normal.to_angle(),
            force_type=template_brush.TEMP_TYPES.world,
        ).world

        # Texture the new brush..
        for brush in new_brushes:  # type: Solid
            for new_face in brush.sides:
                # The SKIP brush is the surface, all the others are nodraw.
                if new_face.mat.casefold() != 'tools/toolsskip':
                     continue

                # Overwrite all the properties, to make the new brush
                # the same as the original.
                new_face.mat = face.mat
                new_face.uaxis = face.uaxis
                new_face.vaxis = face.vaxis
                new_face.planes = face.planes
                new_face.ham_rot = 0

                # Swap the two IDs - that way when the original face gets
                # deleted the auto-set ID will vanish, leaving the original
                # ID.
                new_face.id, face.id = face.id, new_face.id

                # Remove the new face, if the original wasn't in IGNORED_FACES.
                if face not in vbsp.IGNORED_FACES:
                    vbsp.IGNORED_FACES.remove(new_face)

                # Make a new SolidGroup to match the face.
                if face_group is not None:
                    SOLIDS[solid_key] = solidGroup(
                        new_face,
                        brush,
                        face_group.normal,
                        face_group.color,
                    )


@make_flag('debug')
@make_result('debug')
def debug_flag(inst: Entity, props: Property):
    """Displays text when executed, for debugging conditions.

    If the text ends with an '=', the instance will also be displayed.
    As a flag, this always evaluates as true.
    """
    # Mark as a warning so it's more easily seen.
    if props.has_children():
        LOGGER.warning('Debug:')
        LOGGER.warning(str(props))
        LOGGER.warning(str(inst))
    elif props.value.strip().endswith('='):
        LOGGER.warning('Debug: {props}{inst!s}'.format(
            inst=inst,
            props=props.value,
        ))
    else:
        LOGGER.warning('Debug: ' + props.value)
    return True  # The flag is always true


@make_result('dummy', 'nop', 'do_nothing')
def dummy_result(inst: Entity, props: Property):
    """Dummy result that doesn't do anything."""
    pass


@meta_cond(priority=1000, only_once=False)
def remove_blank_inst(inst: Entity):
    """Remove instances with a blank file keyvalue.

    This allows conditions to strip the instances when requested.
    """
    # If editoritems instances are set to "", PeTI will autocorrect it to
    # ".vmf" - we need to handle that too.
    if inst['file', ''] in ('', '.vmf'):
        VMF.remove_ent(inst)


@meta_cond(priority=0, only_once=True)
def fix_catapult_targets(inst: Entity):
    """Set faith plate targets to transmit to clients.

    This fixes some console spam in coop, and might improve trajectories
    for faith plates.
    """
    for targ in VMF.by_class['info_target']:
        targ['spawnflags'] = '3'  # Transmit to client, ignoring PVS


@make_result_setup('timedRelay')
def res_timed_relay_setup(res: Property):
    var = res['variable', consts.FixupVars.TIM_DELAY]
    name = res['targetname']
    disabled = res['disabled', '0']
    flags = res['spawnflags', '0']

    final_outs = [
        Output.parse(subprop)
        for prop in res.find_all('FinalOutputs')
        for subprop in prop
    ]

    rep_outs = [
        Output.parse(subprop)
        for prop in res.find_all('RepOutputs')
        for subprop in prop
    ]

    # Never use the comma seperator in the final output for consistency.
    for out in itertools.chain(rep_outs, final_outs):
        out.comma_sep = False

    return var, name, disabled, flags, final_outs, rep_outs


@make_result('timedRelay')
def res_timed_relay(inst: Entity, res: Property):
    """Generate a logic_relay with outputs delayed by a certain amount.

    This allows triggering outputs based $timer_delay values.
    """
    var, name, disabled, flags, final_outs, rep_outs = res.value

    relay = VMF.create_ent(
        classname='logic_relay',
        spawnflags=flags,
        origin=inst['origin'],
        targetname=local_name(inst, name),
    )

    relay['StartDisabled'] = (
        inst.fixup[disabled]
        if disabled.startswith('$') else
        disabled
    )

    delay = srctools.conv_float(
        inst.fixup[var, '0']
        if var.startswith('$') else
        var
    )

    for off in range(int(math.ceil(delay))):
        for out in rep_outs:
            new_out = out.copy()  # type: Output
            new_out.target = local_name(inst, new_out.target)
            new_out.delay += off
            new_out.comma_sep = False
            relay.add_out(new_out)

    for out in final_outs:
        new_out = out.copy()
        new_out.target = local_name(inst, new_out.target)
        new_out.delay += delay
        new_out.comma_sep = False
        relay.add_out(new_out)


@make_result('condition')
def res_sub_condition(base_inst: Entity, res: Property):
    """Check a different condition if the outer block is true."""
    res.value.test(base_inst)
make_result_setup('condition')(Condition.parse)


@make_result('nextInstance')
def res_break():
    """Skip to the next instance.

    The value will be ignored.
    """
    raise NextInstance


@make_result('endCondition', 'nextCondition')
def res_end_condition():
    """Skip to the next condition.

    The value will be ignored.
    """
    raise EndCondition


@make_result_setup('switch')
def res_switch_setup(res: Property):
    flag = None
    method = SWITCH_TYPE.FIRST
    cases = []
    for prop in res:
        if prop.has_children():
            cases.append(prop)
        else:
            if prop.name == 'flag':
                flag = prop.value
                continue
            if prop.name == 'method':
                try:
                    method = SWITCH_TYPE(prop.value.casefold())
                except ValueError:
                    pass

    for prop in cases:
        for result in prop.value:
            Condition.setup_result(
                prop.value,
                result,
                'switch: {} -> {}'.format(flag, prop.real_name),
            )

    if method is SWITCH_TYPE.LAST:
        cases[:] = cases[::-1]

    return (
        flag,
        cases,
        method,
    )


@make_result('switch')
def res_switch(inst: Entity, res: Property):
    """Run the same flag multiple times with different arguments.

    'method' is the way the search is done - first, last, random, or all.
    'flag' is the name of the flag.
    Each property group is a case to check - the property name is the flag
    argument, and the contents are the results to execute in that case.
    For 'random' mode, you can omit the flag to choose from all objects. In
    this case the flag arguments are ignored.
    """
    flag_name, cases, method = res.value

    if method is SWITCH_TYPE.RANDOM:
        cases = cases[:]
        random.shuffle(cases)

    for case in cases:
        if flag_name is not None:
            flag = Property(flag_name, case.real_name)
            if not check_flag(flag, inst):
                continue
        for res in case:
            Condition.test_result(inst, res)
        if method is not SWITCH_TYPE.ALL:
            # All does them all, otherwise we quit now.
            break


@make_result_setup('staticPiston')
def make_static_pist_setup(res: Property):
    instances = (
        'bottom_0', 'bottom_1', 'bottom_2', 'bottom_3',
        'logic_0', 'logic_1', 'logic_2', 'logic_3',
        'static_0', 'static_1', 'static_2', 'static_3', 'static_4',
        'grate_low', 'grate_high',
    )

    if res.has_children():
        # Pull from config
        return {
            name: instanceLocs.resolve_one(
                res[name, ''],
                error=False,
            ) for name in instances
        }
    else:
        # Pull from editoritems
        if ':' in res.value:
            from_item, prefix = res.value.split(':', 1)
        else:
            from_item = res.value
            prefix = ''
        return {
            name: instanceLocs.resolve_one(
                '<{}:bee2_{}{}>'.format(from_item, prefix, name),
                error=False,
            ) for name in instances
        }


@make_result('staticPiston')
def make_static_pist(vmf: srctools.VMF, ent: Entity, res: Property):
    """Convert a regular piston into a static version.

    This is done to save entities and improve lighting.
    If changed to static pistons, the $bottom and $top level become equal.
    Instances:
        Bottom_1/2/3: Moving piston with the given $bottom_level
        Logic_0/1/2/3: Additional logic instance for the given $bottom_level
        Static_0/1/2/3/4: A static piston at the given height.
    Alternatively, specify all instances via editoritems, by setting the value
    to the item ID optionally followed by a :prefix.
    """

    bottom_pos = ent.fixup.int(consts.FixupVars.PIST_BTM, 0)

    if (
        ent.fixup.int(consts.FixupVars.CONN_COUNT) > 0 or
        ent.fixup.bool(consts.FixupVars.DIS_AUTO_DROP)
    ):  # can it move?
        ent.fixup[consts.FixupVars.BEE_PIST_IS_STATIC] = True

        # Use instances based on the height of the bottom position.
        val = res.value['bottom_' + str(bottom_pos)]
        if val:  # Only if defined
            ent['file'] = val

        logic_file = res.value['logic_' + str(bottom_pos)]
        if logic_file:
            # Overlay an additional logic file on top of the original
            # piston. This allows easily splitting the piston logic
            # from the styled components
            logic_ent = ent.copy()
            logic_ent['file'] = logic_file
            vmf.add_ent(logic_ent)
            # If no connections are present, set the 'enable' value in
            # the logic to True so the piston can function
            logic_ent.fixup[consts.FixupVars.BEE_PIST_MANAGER_A] = (
                ent.fixup.int(consts.FixupVars.CONN_COUNT) == 0
            )
    else:  # we are static
        ent.fixup[consts.FixupVars.BEE_PIST_IS_STATIC] = False
        if ent.fixup.bool(consts.FixupVars.PIST_IS_UP):
            pos = bottom_pos = ent.fixup.int(consts.FixupVars.PIST_TOP, 1)
        else:
            pos = bottom_pos
        ent.fixup[consts.FixupVars.PIST_TOP] = ent.fixup[consts.FixupVars.PIST_BTM] = pos

        val = res.value['static_' + str(pos)]
        if val:
            ent['file'] = val

    # Add in the grating for the bottom as an overlay.
    # It's low to fit the piston at minimum, or higher if needed.
    grate = res.value[
        'grate_high'
        if bottom_pos > 0 else
        'grate_low'
    ]
    if grate:
        grate_ent = ent.copy()
        grate_ent['file'] = grate
        vmf.add_ent(grate_ent)


@make_result('GooDebris')
def res_goo_debris(res: Property):
    """Add random instances to goo squares.

    Options:
        - file: The filename for the instance. The variant files should be
            suffixed with `_1.vmf`, `_2.vmf`, etc.
        - space: the number of border squares which must be filled with goo
                 for a square to be eligible - defaults to 1.
        - weight, number: see the `Variant` result, a set of weights for the
                options
        - chance: The percentage chance a square will have a debris item
        - offset: A random xy offset applied to the instances.
    """
    import brushLoc

    space = res.int('spacing', 1)
    rand_count = res.int('number', None)
    if rand_count:
        rand_list = weighted_random(
            rand_count,
            res['weights', ''],
        )
    else:
        rand_list = None  # type: Optional[List[int]]
    chance = res.int('chance', 30) / 100
    file = res['file']
    offset = res.int('offset', 0)

    if file.endswith('.vmf'):
        file = file[:-4]

    goo_top_locs = {
        pos.as_tuple()
        for pos, block in
        brushLoc.POS.items()
        if block.is_goo and block.is_top
    }

    if space == 0:
        # No spacing needed, just copy
        possible_locs = [Vec(loc) for loc in goo_top_locs]
    else:
        possible_locs = []
        for x, y, z in goo_top_locs:
            # Check to ensure the neighbouring blocks are also
            # goo brushes (depending on spacing).
            for x_off, y_off in utils.iter_grid(
                min_x=-space,
                max_x=space + 1,
                min_y=-space,
                max_y=space + 1,
                stride=1,
            ):
                if x_off == y_off == 0:
                    continue  # We already know this is a goo location
                if (x + x_off, y + y_off, z) not in goo_top_locs:
                    break  # This doesn't qualify
            else:
                possible_locs.append(brushLoc.grid_to_world(Vec(x,y,z)))

    LOGGER.info(
        'GooDebris: {}/{} locations',
        len(possible_locs),
        len(goo_top_locs),
    )

    suff = ''
    for loc in possible_locs:
        random.seed('goo_debris_{}_{}_{}'.format(loc.x, loc.y, loc.z))
        if random.random() > chance:
            continue

        if rand_list is not None:
            suff = '_' + str(random.choice(rand_list) + 1)

        if offset > 0:
            loc.x += random.randint(-offset, offset)
            loc.y += random.randint(-offset, offset)
        loc.z -= 32  # Position the instances in the center of the 128 grid.
        VMF.create_ent(
            classname='func_instance',
            file=file + suff + '.vmf',
            origin=loc.join(' '),
            angles='0 {} 0'.format(random.randrange(0, 3600)/10)
        )

    return RES_EXHAUSTED
