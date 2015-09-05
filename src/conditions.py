# coding: utf-8
from decimal import Decimal
from collections import namedtuple
from enum import Enum
import random

from utils import Vec
from property_parser import Property
from instanceLocs import resolve as resolve_inst
import vmfLib as VLib
import utils

# Stuff we get from VBSP in init()
GLOBAL_INSTANCES = set()
OPTIONS = {}
ALL_INST = set()


conditions = []
FLAG_LOOKUP = {}
RESULT_LOOKUP = {}
RESULT_SETUP = {}

# Used to dump a list of the flags, results, meta-conds
ALL_FLAGS = []
ALL_RESULTS = []
ALL_META = []

SOLIDS = {}  # A dictionary mapping origins to their brushes
solidGroup = namedtuple('solidGroup', 'face solid normal color')


class MAT_TYPES(Enum):
    """The values saved in the solidGroup.color attribute."""
    black = 0
    white = 1

    def __str__(self):
        if self is MAT_TYPES.black:
            return 'black'
        if self is MAT_TYPES.white:
            return 'white'


xp = utils.Vec_tuple(1, 0, 0)
xn = utils.Vec_tuple(-1, 0, 0)
yp = utils.Vec_tuple(0, 1, 0)
yn = utils.Vec_tuple(0, -1, 0)
zp = utils.Vec_tuple(0, 0, 1)
zn = utils.Vec_tuple(0, 0, -1)
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

    'wall': 'WALL',  # Special case, not wall/ceiling
    'walls': 'WALL',
}

INST_ANGLE = {
    # The angles needed to point a PeTI instance in this direction
    # IE up = zp = floor
    zp: "0 0 0",
    zn: "0 0 0",

    xn: "0 0 0",
    yn: "0 90 0",
    xp: "0 180 0",
    yp: "0 270 0",

}

del xp, xn, yp, yn, zp, zn


class NextInstance(Exception):
    """Raised to skip to the next instance, from the SkipInstance result."""
    pass


class EndCondition(Exception):
    """Raised to skip the condition entirely, from the EndCond result."""
    pass


class Condition:
    __slots__ = ['flags', 'results', 'else_results', 'priority']

    def __init__(
            self,
            flags=None,
            results=None,
            else_results=None,
            priority=Decimal('0'),
    ):
        self.flags = flags or []
        self.results = results or []
        self.else_results = else_results or []
        self.priority = priority
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
    def parse(cls, prop_block):
        """Create a condition from a Property block."""
        flags = []
        results = []
        else_results = []
        priority = Decimal('0')
        for prop in prop_block:
            if prop.name == 'result':
                results.extend(prop.value)  # join multiple ones together
            elif prop.name == 'else':
                else_results.extend(prop.value)
            elif prop.name == 'condition':
                # Shortcut to eliminate lots of Result - Condition pairs
                results.append(prop)
            elif prop.name == 'elsecondition':
                else_results.append(prop)
            elif prop.name == 'priority':
                try:
                    priority = Decimal(prop.value)
                except ArithmeticError:
                    pass
            else:
                flags.append(prop)

        return cls(
            flags=flags,
            results=results,
            else_results=else_results,
            priority=priority,
        )

    def setup(self):
        """Some results need some pre-processing before they can be used.

        """
        for res in self.results[:]:
            func = RESULT_SETUP.get(res.name)
            if func:
                res.value = func(res)
                if res.value is None:
                    self.results.remove(res)

        for res in self.else_results[:]:
            func = RESULT_SETUP.get(res.name)
            if func:
                res.value = func(res)
                if res.value is None:
                    self.else_results.remove(res)

    def test(self, inst):
        """Try to satisfy this condition on the given instance."""
        success = True
        for flag in self.flags:
            if not check_flag(flag, inst):
                success = False
                break
        results = self.results if success else self.else_results
        for res in results[:]:
            try:
                func = RESULT_LOOKUP[res.name]
            except KeyError:
                utils.con_log(
                    '"{}" is not a valid condition result!'.format(
                        res.real_name,
                    )
                )
            else:
                should_del = func(inst, res)
                if should_del is True:
                    results.remove(res)

    def __lt__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority < other.priority
        return NotImplemented

    def __le__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority <= other.priority
        return NotImplemented

    def __gt__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority > other.priority
        return NotImplemented

    def __ge__(self, other):
        """Condition items sort by priority."""
        if hasattr(other, 'priority'):
            return self.priority >= other.priority
        return NotImplemented


def add_meta(func, priority, only_once=True):
    """Add a metacondtion, which executes a function at a priority level.

    Used to allow users to allow adding conditions before or after a
    transformation like the adding of quotes.
    """
    # This adds a condition result like "func" (with quotes), which cannot
    # be entered into property files.
    # The qualname will be unique across modules.
    name = '"' + func.__qualname__ + '"'
    print("Adding metacondition ({}) with priority {!s}!".format(
        name,
        priority,
    ))

    # Don't pass the prop_block onto the function,
    # it doesn't contain any useful data.
    RESULT_LOOKUP[name] = lambda inst, val: func(inst)

    cond = Condition(
        results=[Property(name, '')],
        priority=priority,
    )

    if only_once:
        cond.results.append(
            Property('endCondition', '')
        )
    conditions.append(cond)
    ALL_META.append((name, priority, func))


def meta_cond(priority=0, only_once=True):
    """Decorator version of add_meta."""
    def x(func):
        add_meta(func, priority, only_once)
        return func
    return x


def make_flag(orig_name, *aliases):
    """Decorator to add flags to the lookup."""
    def x(func):
        ALL_FLAGS.append(
            (orig_name, aliases, func)
        )
        FLAG_LOOKUP[orig_name.casefold()] = func
        for name in aliases:
            FLAG_LOOKUP[name.casefold()] = func
        return func
    return x


def make_result(orig_name, *aliases):
    """Decorator to add results to the lookup."""
    def x(func):
        ALL_RESULTS.append(
            (orig_name, aliases, func)
        )
        RESULT_LOOKUP[orig_name.casefold()] = func
        for name in aliases:
            RESULT_LOOKUP[name.casefold()] = func
        return func
    return x


def make_result_setup(*names):
    """Decorator to do setup for this result."""
    def x(func):
        for name in names:
            RESULT_SETUP[name.casefold()] = func
        return func
    return x


def add(prop_block):
    """Parse and add a condition to the list."""
    con = Condition.parse(prop_block)
    if con.results or con.else_results:
        conditions.append(con)


def init(seed, inst_list, vmf_file):
    # Get a bunch of values from VBSP
    import vbsp
    global MAP_RAND_SEED, ALL_INST, VMF, STYLE_VARS, VOICE_ATTR, OPTIONS
    VMF = vmf_file
    MAP_RAND_SEED = seed
    ALL_INST = set(inst_list)
    OPTIONS = vbsp.settings
    STYLE_VARS = vbsp.settings['style_vars']
    VOICE_ATTR = vbsp.settings['has_attr']

    # Sort by priority, where higher = done later
    conditions.sort()

    build_solid_dict()


def check_all():
    """Check all conditions."""
    utils.con_log('Checking Conditions...')
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
                if not condition.results and not condition.else_results:
                    utils.con_log('Exiting empty condition!')
                    break  # Condition has run out of results, quit early

    utils.con_log('Map has attributes: ', [
        key
        for key, value in
        VOICE_ATTR.items()
        if value
    ])
    utils.con_log('Style Vars:', dict(STYLE_VARS.items()))
    utils.con_log('Global instances: ', GLOBAL_INSTANCES)


def check_inst(inst):
    """Run all conditions on a given instance."""
    for condition in conditions:
        condition.test(inst)


def check_flag(flag, inst):
    # print('Checking {type} ({val!s} on {inst}'.format(
    #     type=flag.real_name,
    #     val=flag.value,
    #     inst=inst['file'],
    # ))
    try:
        func = FLAG_LOOKUP[flag.name]
    except KeyError:
        utils.con_log('"' + flag.name + '" is not a valid condition flag!')
        return False
    else:
        res = func(inst, flag)
        return res


def build_solid_dict():
    """Build a dictionary mapping origins to brush faces.

    This allows easily finding brushes that are at certain locations.
    """
    import vbsp
    mat_types = {}
    for mat in vbsp.BLACK_PAN:
        mat_types[mat] = MAT_TYPES.black

    for mat in vbsp.WHITE_PAN:
        mat_types[mat] = MAT_TYPES.white

    for solid in VMF.brushes:
        for face in solid:
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
                    SOLIDS.pop(origin).face.mat = 'tools/toolsnodraw'
                    face.mat = 'tools/toolsnodraw'
                    continue

                SOLIDS[origin] = solidGroup(
                    color=mat_type,
                    face=face,
                    solid=solid,
                    normal=face.normal(),
                )


def dump_conditions():
    """Print a list of all the condition flags, results, metaconditions

    to the screen, and then quit.
    """

    utils.con_log('Dumping conditions:')
    utils.con_log('-------------------')

    for lookup, name in [
            (ALL_FLAGS, 'Flags'),
            (ALL_RESULTS, 'Results'),
            ]:
        utils.con_log(name + ':')
        utils.con_log('-'*len(name) + '-')
        lookup.sort()
        for flag_key, aliases, func in lookup:
            utils.con_log('"{}":'.format(flag_key))
            if aliases:
                utils.con_log('\tAliases: "' + '", "'.join(aliases) + '"')
            dump_func_docs(func)
        input('...')
        utils.con_log('')

    utils.con_log('MetaConditions:')
    utils.con_log('---------------')
    ALL_META.sort(key=lambda i: i[1]) # Sort by priority
    for flag_key, priority, func in ALL_META:
        utils.con_log('{} ({}):'.format(flag_key, priority))
        dump_func_docs(func)
        utils.con_log('')


def dump_func_docs(func):
    import inspect
    docs = inspect.getdoc(func)
    if docs:
        for line in docs.split('\n'):
            if line.strip():
                utils.con_log('\t'+line.rstrip('\n'))
    else:
        utils.con_log('\tNo documentation!')


@make_result_setup('variant')
def variant_weight(var):
    """Read variant commands from settings and create the weight list."""
    count = var['number', '']
    if count.isdecimal():
        count = int(count)
        weight = var['weights', '']
        if weight == '' or ',' not in weight:
            utils.con_log('Invalid weight! (' + weight + ')')
            weight = [str(i) for i in range(1, count + 1)]
        else:
            # Parse the weight
            vals = weight.split(',')
            weight = []
            if len(vals) == count:
                for i, val in enumerate(vals):
                    val = val.strip()
                    if val.isdecimal():
                        # repeat the index the correct number of times
                        weight.extend(
                            str(i+1)
                            for _ in
                            range(1, int(val)+1)
                        )
                    else:
                        # Abandon parsing
                        break
            if len(weight) == 0:
                utils.con_log('Failed parsing weight! ({!s})'.format(weight))
                weight = [str(i) for i in range(1, count + 1)]
        # random.choice(weight) will now give an index with the correct
        # probabilities.
        return weight
    else:
        return ['']  # This won't append anything to the file


def add_output(inst, prop, target):
    """Add a customisable output to an instance."""
    inst.add_out(VLib.Output(
        prop['output', ''],
        target,
        prop['input', ''],
        inst_in=prop['targ_in', ''],
        inst_out=prop['targ_out', ''],
        ))


def add_suffix(inst, suff):
    """Append the given suffix to the instance.
    """
    file = inst['file']
    old_name, dot, ext = file.partition('.')
    inst['file'] = ''.join((old_name, suff, dot, ext))


def widen_fizz_brush(brush, thickness, bounds=None):
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
    origin = (bound_max + bound_min) / 2  # type: Vec
    size = bound_max - bound_min
    for axis in 'xyz':
        # One of the directions will be thinner than 128, that's the fizzler
        # direction.
        if size[axis] < 128:
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


@make_flag('debug')
def debug_flag(inst, props):
    """Displays text when executed, for debugging conditions.

    If the text ends with an '=', the instance will also be displayed.
    As a flag, this always evaluates as true.
    """
    if props.has_children():
        utils.con_log('Debug:')
        utils.con_log(str(props))
        utils.con_log(str(inst))
    elif props.value.strip().endswith('='):
        utils.con_log('Debug: {props}{inst!s}'.format(
            inst=inst,
            props=props.value,
        ))
    else:
        utils.con_log('Debug: ' + props.value)
    return True  # The flag is always true


@make_result('debug')
def debug_result(inst, props):
    # Swallow the return value, so the flag isn't deleted
    debug_flag(inst, props)

debug_result.__doc__ = debug_flag.__doc__


@meta_cond(priority=1000, only_once=False)
def remove_blank_inst(inst):
    """Remove instances with a blank file keyvalue.

    This allows conditions to strip the instances when requested.
    """
    # If editoritems instances are set to "", PeTI will autocorrect it to
    # ".vmf" - we need to handle that too.
    if inst['file', ''] in ('', '.vmf'):
        VMF.remove_ent(inst)


@meta_cond(priority=0, only_once=True)
def fix_catapult_targets(inst):
    """Set faith plate targets to transmit to clients.

    This fixes some console spam in coop, and might improve trajectories
    for faith plates.
    """
    for targ in VMF.by_class['info_target']:
        targ['spawnflags'] = '3'  # Transmit to client, ignoring PVS

#########
# FLAGS #
#########


@make_flag('AND')
def flag_and(inst, flag):
    """The AND group evaluates True if all sub-flags are True."""
    for sub_flag in flag:
        if not check_flag(sub_flag, inst):
            return False
        # If the AND block is empty, return True
        return len(sub_flag.value) == 0


@make_flag('OR')
def flag_or(inst, flag):
    """The OR group evaluates True if any sub-flags are True."""
    for sub_flag in flag:
        if check_flag(sub_flag, inst):
            return True
    return False

@make_flag('NOT')
def flag_not(inst, flag):
    """The NOT group inverts the value of it's one sub-flag."""
    if len(flag.value) == 1:
        return not check_flag(flag[0], inst)
    return False


@make_flag('NOR')
def flag_nor(inst, flag):
    """The NOR group evaluates True if any sub-flags are False."""
    return not flag_or(inst, flag)


@make_flag('NAND')
def flag_nand(inst, flag):
    """The NAND group evaluates True if all sub-flags are False."""
    return not flag_and(inst, flag)


@make_flag('instance')
def flag_file_equal(inst, flag):
    """Evaluates True if the instance matches the given file."""
    return inst['file'].casefold() in resolve_inst(flag.value)


@make_flag('instFlag', 'InstPart')
def flag_file_cont(inst, flag):
    """Evaluates True if the instance contains the given portion."""
    return flag.value in inst['file'].casefold()


@make_flag('hasInst')
def flag_has_inst(_, flag):
    """Checks if the given instance is present anywhere in the map."""
    flags = resolve_inst(flag.value)
    return any(
        inst.casefold() in flags
        for inst in
        ALL_INST
    )


@make_flag('instVar')
def flag_instvar(inst, flag):
    """Checks if the $replace value matches the given value.

    The flag value follows the form "$start_enabled 1", with or without
    the $.
    """
    bits = flag.value.split(' ', 1)
    return inst.fixup[bits[0]] == bits[1]


@make_flag('styleVar')
def flag_stylevar(_, flag):
    """Checks if the given Style Var is true.

    Use the NOT flag to invert if needed.
    """
    return STYLE_VARS[flag.value.casefold()]


@make_flag('has')
def flag_voice_has(_, flag):
    """Checks if the given Voice Attribute is present.

    Use the NOT flag to invert if needed.
    """
    return VOICE_ATTR[flag.value.casefold()]


@make_flag('has_music')
def flag_music(_, flag):
    """Checks the selected music ID.

    Use "<NONE>" for no music.
    """
    return OPTIONS['music_id'] == flag.value


@make_flag('ifOption')
def flag_option(_, flag):
    bits = flag.value.split(' ', 1)
    key = bits[0].casefold()
    if key in OPTIONS:
        return OPTIONS[key] == bits[1]
    else:
        return False


@make_flag('ifMode', 'iscoop', 'gamemode')
def flag_game_mode(_, flag):
    """Checks if the game mode is "SP" or "COOP".
    """
    import vbsp
    return vbsp.GAME_MODE.casefold() == flag.value.casefold()


@make_flag('ifPreview', 'preview')
def flag_is_preview(_, flag):
    """Checks if the preview mode status equals the given value.

    If preview mode is enabled, the player will start before the entry
    door, and restart the map after reaching the exit door. If false,
    they start in the elevator.

    Preview mode is always False when publishing.
    """
    import vbsp
    return vbsp.IS_PREVIEW == utils.conv_bool(flag.value, False)


@make_flag(
    'rotation',
    'angle',
    'angles',
    'orient',
    'orientation',
    'dir',
    'direction',
)
def flag_angles(inst, flag):
    """Check that a instance is pointed in a direction.

    The value should be either just the angle to check, or a block of
    options:
    - Angle: A unit vector (XYZ value) pointing in a direction, or some
        keywords: +z, -y, N/S/E/W, up/down, floor/ceiling, or walls
    - From_dir: The direction the unrotated instance is pointed in.
        This lets the flag check multiple directions
    - Allow_inverse: If true, this also returns True if the instance is
        pointed the opposite direction .
    """
    angle = inst['angles', '0 0 0']

    if flag.has_children():
        targ_angle = flag['direction', '0 0 0']
        from_dir = flag['from_dir', '0 0 1']
        if from_dir.casefold() in DIRECTIONS:
            from_dir = Vec(DIRECTIONS[from_dir.casefold()])
        else:
            from_dir = Vec.from_str(from_dir, 0, 0, 1)
        allow_inverse = utils.conv_bool(flag['allow_inverse', '0'])
    else:
        targ_angle = flag.value
        from_dir = Vec(0, 0, 1)
        allow_inverse = False

    if angle == targ_angle:
        return True  # Check for exact match

    normal = DIRECTIONS.get(targ_angle.casefold(), None)
    if normal is None:
        return False  # If it's not a special angle,
        # so it failed the exact match

    inst_normal = from_dir.rotate_by_str(angle)

    if normal == 'WALL':
        # Special case - it's not on the floor or ceiling
        return not (inst_normal == (0, 0, 1) or inst_normal == (0, 0, -1))
    else:
        return inst_normal == normal or (
            allow_inverse and -inst_normal == normal
        )


@make_flag('posIsSolid')
def flag_brush_at_loc(inst, flag):
    """Checks to see if a wall is present at the given location.

    - Pos is the position of the brush, where `0 0 0` is the floor-position
       of the brush, in 16 unit increments.
    - Dir is the normal the face is pointing. (0 0 -1) is 'up'.
    - Type defines the type the brush must be:
      - "Any" requires either a black or white brush.
      - "None" means that no brush must be present.
      - "White" requires a portalable surface.
      - "Black" requires a non-portalable surface.
    - SetVar defines an instvar which will be given a value of "black",
      "white" or "none" to allow the result to be reused.
    - RemoveBrush: If set to 1, the brush will be removed if found.
      Only do this to EmbedFace brushes, since it will remove the other
      sides as well.
    """
    pos = Vec.from_str(flag['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos = pos.rotate_by_str(inst['angles', '0 0 0'])

    # Relative to the instance origin
    pos += Vec.from_str(inst['origin', '0 0 0'])

    norm = Vec.from_str(flag['dir', '0 0 -1']).rotate_by_str(
        inst['angles', '0 0 0']
    )

    result_var = flag['setVar', '']
    should_remove = utils.conv_bool(flag['RemoveBrush', False], False)
    des_type = flag['type', 'any'].casefold()

    brush = SOLIDS.get(pos.as_tuple(), None)
    ':type brush: solidGroup'

    if brush is None or brush.normal != norm:
        br_type = 'none'
    else:
        br_type = str(brush.color)
        if should_remove:
            VMF.remove_brush(
                brush.solid,
            )

    if result_var:
        inst.fixup[result_var] = br_type

    if des_type == 'any' and br_type != 'none':
        return True

    return des_type == br_type


###########
# RESULTS #
###########


@make_result('rename', 'changeInstance')
def res_change_instance(inst, res):
    """Set the file to a value."""
    inst['file'] = resolve_inst(res.value)[0]


@make_result('suffix', 'instSuffix')
def res_add_suffix(inst, res):
    """Add the specified suffix to the filename."""
    add_suffix(inst, '_' + res.value)


@make_result('styleVar')
def res_set_style_var(_, res):
    """Set Style Vars.

    The value should be set of "SetTrue" and "SetFalse" keyvalues.
    """
    for opt in res.value:
        if opt.name == 'settrue':
            STYLE_VARS[opt.value.casefold()] = True
        elif opt.name == 'setfalse':
            STYLE_VARS[opt.value.casefold()] = False
    return True  # Remove this result


@make_result('has')
def res_set_voice_attr(_, res):
    """Sets a number of Voice Attributes.

        Each child property will be set. The value is ignored, but must
        be present for syntax reasons.
    """
    if res.has_children():
        for opt in res.value:
            VOICE_ATTR[opt.name] = True
    else:
        VOICE_ATTR[res.value.casefold()] = 1
    return True  # Remove this result


@make_result('setOption')
def res_set_option(_, res):
    """Set a value in the "options" part of VBSP_config.

    Each child property will be set.
    """
    for opt in res.value:
        if opt.name in OPTIONS:
            OPTIONS[opt.name] = opt.value
    return True  # Remove this result


@make_result('instVar', 'instVarSuffix')
def res_add_inst_var(inst, res):
    """Append the value of an instance variable to the filename.

    Pass either the variable name, or a set of value->suffix pairs for a
    lookup.
    """
    if res.has_children():
        val = inst.fixup[res['variable', '']]
        for rep in res:  # lookup the number to determine the appending value
            if rep.name == 'variable':
                continue  # this isn't a lookup command!
            if rep.name == val:
                add_suffix(inst, '_' + rep.value)
                break
    else:  # append the value
        add_suffix(inst, '_' + inst.fixup[res.value, ''])


@make_result('setInstVar')
def res_set_inst_var(inst, res):
    """Set an instance variable to the given value.

    Values follow the format "$start_enabled 1", with or without the $.
    """
    var_name, val = res.value.split(' ', 1)
    inst.fixup[var_name] = val


@make_result('variant')
def res_add_variant(inst, res):
    """This allows using a random instance from a weighted group.

    A suffix will be added in the form "_var4".
    Two properties should be given:
        Number: The number of random instances.
        Weight: A comma-separated list of weights for each instance.
    Any variant has a chance of weight/sum(weights) of being chosen:
    A weight of "2, 1, 1" means the first instance has a 2/4 chance of
    being chosen, and the other 2 have a 1/4 chance of being chosen.
    The chosen variant depends on the position, direction and name of
    the instance.
    """
    if inst['targetname', ''] == '':
        # some instances don't get names, so use the global
        # seed instead for stuff like elevators.
        random.seed(MAP_RAND_SEED + inst['origin'] + inst['angles'])
    else:
        # We still need to use angles and origin, since things like
        # fizzlers might not get unique names.
        random.seed(inst['targetname'] + inst['origin'] + inst['angles'])
    add_suffix(inst, "_var" + random.choice(res.value))


@make_result('addGlobal')
def res_add_global_inst(_, res):
    """Add one instance in a location.

    Options:
        allow_multiple: Allow multiple copies of this instance. If 0, the
            instance will not be added if it was already added.
        name: The targetname of the instance. IF blank, the instance will
              be given a name of the form 'inst_1234'.
        file: The filename for the instance.
        Angles: The orientation of the instance (defaults to '0 0 0').
        Origin: The location of the instance (defaults to '0 0 -10000').
        Fixup_style: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
    """
    if res.value is not None:
        if (
                utils.conv_bool(res['allow_multiple', '0']) or
                res['file'] not in GLOBAL_INSTANCES):
            # By default we will skip adding the instance
            # if was already added - this is helpful for
            # items that add to original items, or to avoid
            # bugs.
            new_inst = VLib.Entity(VMF, keys={
                "classname": "func_instance",
                "targetname": res['name', ''],
                "file": resolve_inst(res['file'])[0],
                "angles": res['angles', '0 0 0'],
                "origin": res['position', '0 0 -10000'],
                "fixup_style": res['fixup_style', '0'],
                })
            GLOBAL_INSTANCES.add(res['file'])
            if new_inst['targetname'] == '':
                new_inst['targetname'] = "inst_"
                new_inst.make_unique()
            VMF.add_ent(new_inst)
    return True  # Remove this result


@make_result('addOverlay', 'overlayinst')
def res_add_overlay_inst(inst, res):
    """Add another instance on top of this one.

    Values:
        File: The filename.
        Fixup Style: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
        Copy_Fixup: If true, all the $replace values from the original
            instance will be copied over.
    """
    print('adding overlay', res['file'])
    overlay_inst = VMF.create_ent(
        classname='func_instance',
        targetname=inst['targetname', ''],
        file=resolve_inst(res['file', ''])[0],
        angles=inst['angles', '0 0 0'],
        origin=inst['origin'],
        fixup_style=res['fixup_style', '0'],
    )
    if utils.conv_bool(res['copy_fixup', '1']):
        # Copy the fixup values across from the original instance
        for fixup, value in inst.fixup.items():
            overlay_inst.fixup[fixup] = value


@make_result_setup('custOutput')
def res_cust_output_setup(res):
    for sub_res in res:
        if sub_res.name == 'targcondition':
            sub_res.value = Condition.parse(sub_res)
    return res.value


@make_result('custOutput')
def res_cust_output(inst, res):
    """Add an additional output to the instance with any values.

    Always points to the targeted item.
    """
    over_name = '@' + inst['targetname'] + '_indicator'
    for toggle in VMF.by_class['func_instance']:
        if toggle.fixup['indicator_name', ''] == over_name:
            toggle_name = toggle['targetname']
            break
    else:
        toggle_name = ''  # we want to ignore the toggle instance, if it exists

    # Make this a set to ignore repeated targetnames
    targets = {o.target for o in inst.outputs if o.target != toggle_name}

    kill_signs = utils.conv_bool(res["remIndSign", '0'], False)
    dec_con_count = utils.conv_bool(res["decConCount", '0'], False)
    targ_conditions = list(res.find_all("targCondition"))

    pan_files = resolve_inst('[indPan]')

    if kill_signs or dec_con_count or targ_conditions:
        for con_inst in VMF.by_class['func_instance']:
            if con_inst['targetname'] in targets:
                if kill_signs and con_inst in pan_files:
                    VMF.remove_ent(con_inst)
                if targ_conditions:
                    for cond in targ_conditions:
                        cond.value.test(con_inst)
                if dec_con_count and 'connectioncount' in con_inst.fixup:
                    # decrease ConnectionCount on the ents,
                    # so they can still process normal inputs
                    try:
                        val = int(con_inst.fixup['connectioncount'])
                        con_inst.fixup['connectioncount'] = str(val-1)
                    except ValueError:
                        # skip if it's invalid
                        utils.con_log(
                            con_inst['targetname'] +
                            ' has invalid ConnectionCount!'
                        )
    for targ in targets:
        for out in res.find_all('addOut'):
            add_output(inst, out, targ)


@make_result_setup('custAntline')
def res_cust_antline_setup(res):
    result = {
        'instance': res['instance', ''],
        'wall_str': [p.value for p in res.find_all('straight')],
        'wall_crn': [p.value for p in res.find_all('corner')],
        # If this isn't defined, None signals to use the above textures.
        'floor_str': [p.value for p in res.find_all('straightFloor')] or None,
        'floor_crn': [p.value for p in res.find_all('cornerFloor')] or None,
        'outputs': list(res.find_all('addOut')),
        }
    if (
            not result['wall_str'] or
            not result['wall_crn']
            ):
        # If we don't have two textures, something's wrong. Remove this result.
        utils.con_log('custAntline has missing values!')
        return None
    else:
        return result


@make_result('custAntline')
def res_cust_antline(inst, res):
    """Customise the output antline texture, toggle instances.

    This allows adding extra outputs between the instance and the toggle.
    Values:
        straight: The straight overlay texture.
        corner: The corner overlay texture.
        straightFloor: Alt texture used on straight floor segements (P1 style)
        cornerFloor: Alt texture for floor corners (P1 style)
          If these aren't set, the wall textures will be used.
        instance: Use the given indicator_toggle instance instead
        addOut: A set of additional ouputs to add, pointing at the
          toggle instance
    """
    import vbsp

    opts = res.value

    # The original textures for straight and corner antlines
    straight_ant = vbsp.ANTLINES['straight']
    corner_ant = vbsp.ANTLINES['corner']

    over_name = '@' + inst['targetname'] + '_indicator'
    for over in (
            VMF.by_class['info_overlay'] &
            VMF.by_target[over_name]
            ):
        folded_mat = over['material'].casefold()
        if folded_mat == straight_ant:
            vbsp.set_antline_mat(
                over,
                opts['wall_str'],
                opts['floor_str'],
            )
        elif folded_mat == corner_ant:
            vbsp.set_antline_mat(
                over,
                opts['wall_crn'],
                opts['floor_crn'],
            )

        # Ensure this isn't overriden later!
        vbsp.IGNORED_OVERLAYS.add(over)

    # allow replacing the indicator_toggle instance
    if opts['instance']:
        for toggle in VMF.by_class['func_instance']:
            if toggle.fixup['indicator_name', ''] == over_name:
                toggle['file'] = opts['instance']
                if len(opts['outputs']) > 0:
                    for out in inst.outputs[:]:
                        if out.target == toggle['targetname']:
                            # remove the original outputs
                            inst.outputs.remove(out)
                    for out in opts['outputs']:
                        # Allow adding extra outputs to customly
                        # trigger the toggle
                        add_output(inst, out, toggle['targetname'])
                break  # Stop looking!


@make_result('faithMods')
def res_faith_mods(inst, res):
    """Modify the trigger_catrapult that is created for ItemFaithPlate items.

    Values:
        - raise_trig: Raise or lower the trigger_catapults by this amount.
        - angled_targ, angled_in: Instance entity and input for angled plates
        - straight_targ, straight_in: Instance entity and input for
            straight plates
        - instvar: A $replace value to set to either 'angled' or '
            'straight'.
    """
    # Get data about the trigger this instance uses for flinging
    fixup_var = res['instvar', '']
    offset = utils.conv_int(res['raise_trig', '0'])
    if offset:
        offset = Vec(0, 0, offset).rotate_by_str(inst['angles', '0 0 0'])
        ':type offset Vec'
    for trig in VMF.by_class['trigger_catapult']:
        if inst['targetname'] in trig['targetname']:
            if offset:  # Edit both the normal and the helper trigger
                trig['origin'] = (
                    Vec.from_str(trig['origin']) +
                    offset
                ).join(' ')
                for solid in trig.solids:
                    solid.translate(offset)

            for out in trig.outputs:
                if out.inst_in == 'animate_angled_relay':
                    out.inst_in = res['angled_targ', 'animate_angled_relay']
                    out.input = res['angled_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'angled'
                    break
                elif out.inst_in == 'animate_straightup_relay':
                    out.inst_in = res[
                        'straight_targ', 'animate_straightup_relay'
                    ]
                    out.input = res['straight_in', 'Trigger']
                    if fixup_var:
                        inst.fixup[fixup_var] = 'straight'
                    break


@make_result('custFizzler')
def res_cust_fizzler(base_inst, res):
    """Customises the various components of a custom fizzler item.

    This should be executed on the base instance. Brush and MakeLaserField
    are ignored on laserfield barriers.
    Options:
        * ModelName: sets the targetname given to the model instances.
        * UniqueModel: If true, each model instance will get a suffix to
            allow unique targetnames.
        * Brush: A brush entity that will be generated (the original is
         deleted.)
            * Name is the instance name for the brush
            * Left/Right/Center/Short/Nodraw are the textures used
            * Keys are a block of keyvalues to be set. Targetname and
              Origin are auto-set.
            * Thickness will change the thickness of the fizzler if set.
              By default it is 2 units thick.
        * MakeLaserField generates a brush stretched across the whole
          area.
            * Name, keys and thickness are the same as the regular Brush.
            * Texture/Nodraw are the textures.
            * Width is the pixel width of the laser texture, used to
              scale it correctly.
    """
    from vbsp import TEX_FIZZLER
    model_name = res['modelname', None]
    make_unique = utils.conv_bool(res['UniqueModel', '0'])
    fizz_name = base_inst['targetname', '']

    # search for the model instances
    model_targetnames = (
        fizz_name + '_modelStart',
        fizz_name + '_modelEnd',
        )
    is_laser = False
    for inst in VMF.by_class['func_instance']:
        if inst['targetname', ''] in model_targetnames:
            if inst.fixup['skin', '0'] == '2':
                is_laser = True
            if model_name is not None:
                if model_name == '':
                    inst['targetname'] = base_inst['targetname']
                else:
                    inst['targetname'] = (
                        base_inst['targetname'] +
                        '-' +
                        model_name
                    )
            if make_unique:
                inst.make_unique()

            for key, value in base_inst.fixup.items():
                inst.fixup[key] = value

    new_brush_config = list(res.find_all('brush'))
    if len(new_brush_config) == 0:
        return  # No brush modifications

    if is_laser:
        # This is a laserfield! We can't edit those brushes!
        utils.con_log('CustFizzler excecuted on LaserField!')
        return

    for orig_brush in (
            VMF.by_class['trigger_portal_cleanser'] &
            VMF.by_target[fizz_name + '_brush']):
        print(orig_brush)
        VMF.remove_ent(orig_brush)
        for config in new_brush_config:
            new_brush = orig_brush.copy()
            VMF.add_ent(new_brush)
            new_brush.clear_keys()  # Wipe the original keyvalues
            new_brush['origin'] = orig_brush['origin']
            new_brush['targetname'] = (
                fizz_name +
                '-' +
                config['name', 'brush']
            )
            # All ents must have a classname!
            new_brush['classname'] = 'trigger_portal_cleanser'

            for prop in config['keys', []]:
                new_brush[prop.name] = prop.value

            laserfield_conf = config.find_key('MakeLaserField', None)
            if laserfield_conf.value is not None:
                # Resize the brush into a laserfield format, without
                # the 128*64 parts. If the brush is 128x128, we can
                # skip the resizing since it's already correct.
                laser_tex = laserfield_conf['texture', 'effects/laserplane']
                nodraw_tex = laserfield_conf['nodraw', 'tools/toolsnodraw']
                tex_width = utils.conv_int(
                    laserfield_conf['texwidth', '512'], 512
                )
                is_short = False
                for side in new_brush.sides():
                    if side.mat.casefold() == 'effects/fizzler':
                        is_short = True
                        break

                if is_short:
                    for side in new_brush.sides():
                        if side.mat.casefold() == 'effects/fizzler':
                            side.mat = laser_tex

                            side.uaxis.offset = 0
                            side.scale = 0.25
                        else:
                            side.mat = nodraw_tex
                else:
                    # The hard part - stretching the brush.
                    convert_to_laserfield(
                        new_brush,
                        laser_tex,
                        nodraw_tex,
                        tex_width,
                    )
            else:
                # Just change the textures
                for side in new_brush.sides():
                    try:
                        side.mat = config[
                            TEX_FIZZLER[side.mat.casefold()]
                        ]
                    except (KeyError, IndexError):
                        # If we fail, just use the original textures
                        pass

            widen_amount = utils.conv_float(config['thickness', '2'], 2.0)
            if widen_amount != 2:
                for brush in new_brush.solids:
                    widen_fizz_brush(
                        brush,
                        thickness=widen_amount,
                    )


def convert_to_laserfield(
        brush: VLib.Entity,
        laser_tex: str,
        nodraw_tex: str,
        tex_width: int,
        ):
    """Convert a fizzler into a laserfield func_brush.

    We need to stretch the brush to get rid of the side sections.
    This is the same as moving all the solids to match the
    bounding box. We first get the origin, used to figure out if
    a point should be set to the max or min axis.

    :param brush: The trigger_portal_cleanser to modify.
    :param tex_width: The pixel width of the laserfield texture, used
                       to rescale it appropriately.
    :param laser_tex: The replacement laserfield texture.
    :param nodraw_tex: A replacement version of tools/nodraw.
    """

    # Get the origin and bbox.
    # The origin isn't in the center, but it still works as long as it's
    # in-between the outermost coordinates
    origin = Vec(*[int(v) for v in brush['origin'].split(' ')])
    bbox_min, bbox_max = brush.get_bbox()

    # we only want the middle one with the center, the others are
    # useless. PeTI happens to always have that in the middle.
    brush.solids = [brush.solids[1]]

    for side in brush.solids[0].sides:
        # For every coordinate, set to the maximum if it's larger than the
        # origin.
        for v in side.planes:
            for ax in 'xyz':
                if int(v[ax]) > origin[ax]:
                    v[ax] = str(bbox_max[ax])
                else:
                    v[ax] = str(bbox_min[ax])

        # Determine the shape of this plane.
        bounds_min, bounds_max = side.get_bbox()
        dimensions = bounds_max - bounds_min

        if 2 in dimensions:  # The front/back won't have this dimension
            # This must be a side of the brush.
            side.mat = nodraw_tex
        else:
            side.mat = laser_tex
            # Now we figure out the corrrect u/vaxis values for the texture.

            size = 0
            offset = 0
            for i, wid in enumerate(dimensions):
                if wid > size:
                    size = int(wid)
                    offset = int(bounds_min[i])
            # texture offset to fit properly
            side.uaxis.offset= tex_width/size * -offset
            side.uaxis.scale= size/tex_width  # scaling

            # heightwise it's always the same
            side.vaxis.offset = 256
            side.vaxis.scale = 0.25


@make_result('condition')
def res_sub_condition(base_inst, res):
    """Check a different condition if the outer block is true."""
    res.value.test(base_inst)
make_result_setup('condition')(Condition.parse)


@make_result('nextInstance')
def res_break(base_inst, res):
    """Skip to the next instance.

    The value will be ignored.
    """
    raise NextInstance


@make_result('endCondition')
def res_end_condition(base_inst, res):
    """Skip to the next condition.

    The value will be ignored.
    """
    raise EndCondition

# For each direction, the two perpendicular axes and the axis it is pointing in.
PAIR_AXES = {
    (1, 0, 0):  'yz' 'x',
    (-1, 0, 0): 'yz' 'x',
    (0, 1, 0):  'xz' 'y',
    (0, -1, 0): 'xz' 'y',
    (0, 0, 1):  'xy' 'z',
    (0, 0, -1): 'xy' 'z',
}


@make_result('fizzlerModelPair')
def res_fizzler_pair(begin_inst, res):
    """Modify the instance of a fizzler to link with its pair.

    Each pair will be given a name along the lines of "fizz_name-model1334".
    Values:
        - StartInst, EndInst: The instances used for each end
        - MidInst: An instance placed every 128 units between emitters.
    """
    orig_target = begin_inst['targetname']

    if 'modelEnd' in orig_target:
        return  # We only execute starting from the start side.

    orig_target = orig_target[:-11]  # remove "_modelStart"
    end_name = orig_target + '_modelEnd'  # What we search for

    # The name all these instances get
    pair_name = orig_target + '-model' + str(begin_inst.id)

    orig_file = begin_inst['file']

    begin_file = res['StartInst', orig_file]
    end_file = res['EndInst', orig_file]
    mid_file = res['MidInst', '']

    begin_inst['file'] = begin_file
    begin_inst['targetname'] = pair_name

    direction = Vec(0, 0, 1).rotate_by_str(begin_inst['angles'])

    begin_pos = Vec.from_str(begin_inst['origin'])
    axis_1, axis_2, main_axis = PAIR_AXES[direction.as_tuple()]
    for end_inst in VMF.by_class['func_instance']:
        if end_inst['targetname', ''] != end_name:
            # Only examine this barrier hazard's instances!
            continue
        end_pos = Vec.from_str(end_inst['origin'])
        if (
                begin_pos[axis_1] == end_pos[axis_1] and
                begin_pos[axis_2] == end_pos[axis_2]
                ):
            length = int(end_pos[main_axis] - begin_pos[main_axis])
            break
    else:
        utils.con_log('No matching pair for {}!!'.format(orig_target))
        return
    end_inst['targetname'] = pair_name
    end_inst['file'] = end_file

    if mid_file != '':
        # Go 64 from each side, and always have at least 1 section
        # A 128 gap will have length = 0
        for dis in range(0, abs(length) + 1, 128):
            new_pos = begin_pos + direction*dis
            VMF.create_ent(
                classname='func_instance',
                targetname=pair_name,
                angles=begin_inst['angles'],
                file=mid_file,
                origin=new_pos.join(' '),
            )


@make_result('clearOutputs', 'clearOutput')
def res_clear_outputs(inst, res):
    """Remove the outputs from an instance."""
    inst.outputs.clear()


@make_result('removeFixup')
def res_rem_fixup(inst, res):
    """Remove a fixup from the instance."""
    del inst.fixup['res']


@make_result('setAngles')
def res_set_angles(inst, res):
    """Set the orientation of an instance to a certain angle."""
    inst['angles'] = res.value


CATWALK_TYPES = {
    utils.CONN_TYPES.straight: 'straight_128',
    utils.CONN_TYPES.corner: 'corner',
    utils.CONN_TYPES.all: 'crossjunction',
    utils.CONN_TYPES.side: 'end',
    utils.CONN_TYPES.triple: 'tjunction',
    utils.CONN_TYPES.none: 'NONE',
}


def place_catwalk_connections(instances, point_a, point_b):
    """Place catwalk sections to connect two straight points."""
    diff = point_b - point_a

    # The horizontal unit vector in the direction we are placing catwalks
    direction = diff.copy()
    direction.z = 0
    distance = direction.len() - 128
    direction = direction.norm()

    if diff.z > 0:
        angle = INST_ANGLE[direction.as_tuple()]
        # We need to add stairs
        for stair_pos in range(0, int(diff.z), 128):
            # Move twice the vertical horizontally
            # plus 128 so we don't start in point A
            loc = point_a + (2 * stair_pos + 128) * direction
            # Do the vertical offset
            loc.z += stair_pos
            VMF.create_ent(
                classname='func_instance',
                origin=loc.join(' '),
                angles=angle,
                file=instances['stair'],
            )
        # This is the location we start flat sections at
        point_a = loc + 128 * direction
        point_a.z += 128
    elif diff.z < 0:
        # We need to add downward stairs
        # They point opposite to normal ones
        utils.con_log('down from', point_a)
        angle = INST_ANGLE[(-direction).as_tuple()]
        for stair_pos in range(0, -int(diff.z), 128):
            utils.con_log(stair_pos)
            # Move twice the vertical horizontally
            loc = point_a + (2 * stair_pos + 256) * direction
            # Do the vertical offset plus additional 128 units
            # to account for the moved instance
            loc.z -= (stair_pos + 128)
            VMF.create_ent(
                classname='func_instance',
                origin=loc.join(' '),
                angles=angle,
                file=instances['stair'],
            )
        # Adjust point A to be at the end of the catwalks
        point_a = loc
    # Remove the space the stairs take up from the horiz distance
    distance -= abs(diff.z) * 2

    # Now do straight sections
    utils.con_log('Stretching ', distance, direction)
    angle = INST_ANGLE[direction.as_tuple()]
    loc = point_a + (direction * 128)

    # Figure out the most efficent number of sections
    for segment_len in utils.fit(
            distance,
            [512, 256, 128]
            ):
        VMF.create_ent(
            classname='func_instance',
            origin=loc.join(' '),
            angles=angle,
            file=instances['straight_' + str(segment_len)],
        )
        utils.con_log(loc)
        loc += (segment_len * direction)


@make_result('makeCatwalk')
def res_make_catwalk(_, res):
    """Speciallised result to generate catwalks from markers.

    Only runs once, and then quits the condition list.
    Instances:
        MarkerInst: The instance set in editoritems.
        Straight_128/256/512: Straight sections. Extends East
        Corner: A corner piece. Connects on N and W sides.
        TJunction; A T-piece. Connects on all but the East side.
        CrossJunction: A X-piece. Connects on all sides.
        End: An end piece. Connects on the East side.
        Stair: A stair. Starts East and goes Up and West.
        End_wall: Connects a West wall to a East catwalk.
        Support_Wall: A support extending from the East wall.
        Support_Ceil: A support extending from the ceiling.
        Support_Floor: A support extending from the floor.
        Single_Wall: A section connecting to an East wall.
    """
    utils.con_log("Starting catwalk generator...")
    marker = resolve_inst(res['markerInst'])
    output_target = res['output_name', 'MARKER']

    instances = {
        name: resolve_inst(res[name, ''])[0]
        for name in
        (
            'straight_128', 'straight_256', 'straight_512',
            'corner', 'tjunction', 'crossjunction', 'end', 'stair', 'end_wall',
            'support_wall', 'support_ceil', 'support_floor', 'single_wall',
            'markerInst',
        )
    }
    # If there are no attachments remove a catwalk piece
    instances['NONE'] = ''
    if instances['end_wall'] == '':
        instances['end_wall'] = instances['end']

    connections = {}  # The directions this instance is connected by (NSEW)
    markers = {}

    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in marker:
            continue
        #                   [North, South, East,  West ]
        connections[inst] = [False, False, False, False]
        markers[inst['targetname']] = inst

    if not markers:
        return True  # No catwalks!

    utils.con_log('Conn:', connections)
    utils.con_log('Markers:', markers)

    # First loop through all the markers, adding connecting sections
    for inst in markers.values():
        for conn in inst.outputs:
            if conn.output != output_target or conn.input != output_target:
                # Indicator toggles or similar, delete these
                print('Removing ', conn.target)
                for del_inst in VMF.by_target[conn.target]:
                    del_inst.remove()
                continue

            inst2 = markers[conn.target]
            print(inst['targetname'], '<->', inst2['targetname'])
            origin1 = Vec.from_str(inst['origin'])
            origin2 = Vec.from_str(inst2['origin'])
            if origin1.x != origin2.x and origin1.y != origin2.y:
                utils.con_log('Instances not aligned!')
                continue

            y_dir = origin1.x == origin2.x  # Which way the connection is
            if y_dir:
                dist = abs(origin1.y - origin2.y)
            else:
                dist = abs(origin1.x - origin2.x)
            vert_dist = origin1.z - origin2.z

            utils.con_log('Dist =', dist, ', Vert =', vert_dist)

            if dist//2 < vert_dist:
                # The stairs are 2 long, 1 high.
                utils.con_log('Not enough room for stairs!')
                continue

            if dist > 128:
                # add straight sections in between
                place_catwalk_connections(instances, origin1, origin2)

            # Update the lists based on the directions that were set
            conn_lst1 = connections[inst]
            conn_lst2 = connections[inst2]
            if origin1.x < origin2.x:
                conn_lst1[2] = True  # E
                conn_lst2[3] = True  # W
            elif origin2.x < origin1.x:
                conn_lst1[3] = True  # W
                conn_lst2[2] = True  # E

            if origin1.y < origin2.y:
                conn_lst1[0] = True  # N
                conn_lst2[1] = True  # S
            elif origin2.y < origin1.y:
                conn_lst1[1] = True  # S
                conn_lst2[0] = True  # N

        inst.outputs.clear()  # Remove the outputs now, they're useless

    for inst, dir_mask in connections.items():
        # Set the marker instances based on the attached walkways.
        print(inst['targetname'], dir_mask)
        new_type, inst['angles'] = utils.CONN_LOOKUP[tuple(dir_mask)]
        inst['file'] = instances[CATWALK_TYPES[new_type]]

        normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])
        ':type normal: Vec'

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if normal.z == 0:
                # Treat booleans as ints to get the direction the connection is
                # in - True == 1, False == 0
                conn_dir = Vec(
                    x=dir_mask[2] - dir_mask[3],  # +E, -W
                    y=dir_mask[0] - dir_mask[1],  # +N, -S,
                    z=0,
                )
                if normal == conn_dir:
                    inst['file'] = instances['end_wall']
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if normal.z == 0:
                inst['file'] = instances['single_wall']
                inst['angles'] = INST_ANGLE[normal.as_tuple()]
            else:
                inst.remove()
            continue  # These don't get supports otherwise

        # Add regular supports
        if normal == (0, 0, 1):
            supp = instances['support_floor']
        elif normal == (0, 0, -1):
            supp = instances['support_ceil']
        else:
            supp = instances['support_wall']

        if supp:
            VMF.create_ent(
                classname='func_instance',
                origin=inst['origin'],
                angles=INST_ANGLE[normal.as_tuple()],
                file=supp,
            )

    utils.con_log('Finished catwalk generation!')
    return True  # Don't run this again


@make_result_setup('staticPiston')
def make_static_pist_setup(res):
    return {
        name: resolve_inst(res[name, ''])[0]
        for name in
        (
            'bottom_1', 'bottom_2', 'bottom_3',
            'logic_0', 'logic_1', 'logic_2', 'logic_3',
            'static_0', 'static_1', 'static_2', 'static_3', 'static_4',
        )
    }


@make_result('staticPiston')
def make_static_pist(ent, res):
    """Convert a regular piston into a static version.

    This is done to save entities and improve lighting.
    Instances:
        Bottom_1/2/3: Moving piston with the given $bottom_level
        Logic_0/1/2/3: Additional logic instance for the given $bottom_level
        Static_0/1/2/3/4: A static piston at the given height.
    """

    bottom_pos = ent.fixup['bottom_level', '-1']

    if (ent.fixup['connectioncount', '0'] != "0" or
            ent.fixup['disable_autodrop', '0'] != "0"):  # can it move?
        if int(bottom_pos) > 0:
            # The piston doesn't go fully down, use alt instances.
            val = res.value['bottom_' + bottom_pos]
            if val:  # Only if defined
                ent['file'] = val
        logic_file = res.value['logic_' + bottom_pos]
        if logic_file:
            # Overlay an additional logic file on top of the original
            # piston. This allows easily splitting the piston logic
            # from the styled components
            logic_ent = ent.copy()
            logic_ent['file'] = logic_file
            VMF.add_ent(logic_ent)
            # If no connections are present, set the 'enable' value in
            # the logic to True so the piston can function
            logic_ent.fixup['manager_a'] = utils.bool_as_int(
                ent.fixup['connectioncount', '0'] == '0'
            )
    else:  # we are static
        val = res.value[
            'static_' + (
                ent.fixup['top_level', '1']
                if utils.conv_bool(ent.fixup['start_up'], False)
                else bottom_pos
            )
        ]
        if val:
            ent['file'] = val


@make_result('trackPlatform')
def res_track_plat(_, res):
    """Logic specific to Track Platforms.

    This allows switching the instances used depending on if the track
    is horizontal or vertical and sets the track
    targetnames to a useful value.
    Values:
        - Orig_item: The "<ITEM_ID>" for the track platform, with angle brackets
        - Single_plat: An instance used for platform with 1 rail
        - Track_name: The name to give to the tracks.
        - Vert_suffix: Add suffixes to vertical tracks
            (_vert, _vert_mirrored)
        - Horiz_suffix: Add suffixes to horizontal tracks
            (_horiz, _horiz_mirrored)
        - plat_suffix: Also add the above _vert or _horiz suffixes to
            the platform.
    """
    # Get the instances from editoritems
    (
        inst_bot_grate, inst_bottom, inst_middle,
        inst_top, inst_plat, inst_plat_oscil, inst_single
    ) = resolve_inst(res['orig_item'])
    single_plat_inst = res['single_plat', '']
    track_targets = res['track_name', '']

    track_files = [inst_bottom, inst_middle, inst_top, inst_single]
    platforms = [inst_plat, inst_plat_oscil]

    # All the track_set in the map, indexed by origin
    track_instances = {
        Vec.from_str(inst['origin']).as_tuple(): inst
        for inst in
        VMF.by_class['func_instance']
        if inst['file'].casefold() in track_files
    }
    utils.con_log('Track instances:')
    utils.con_log('\n'.join(
        '{!s}: {}'.format(k, v['file'])
        for k, v in
        track_instances.items()
    ))

    # Now we loop through all platforms in the map, and then locate their
    # track_set
    for plat_inst in VMF.by_class['func_instance']:
        if plat_inst['file'].casefold() not in platforms:
            continue  # Not a platform!

        utils.con_log('Modifying "' + plat_inst['targetname'] + '"!')

        plat_loc = Vec.from_str(plat_inst['origin'])
        # The direction away from the wall/floor/ceil
        normal = Vec(0, 0, 1).rotate_by_str(
            plat_inst['angles']
        )

        for tr_origin, first_track in track_instances.items():
            if plat_loc == tr_origin:
                # Check direction

                if normal == Vec(0, 0, 1).rotate(
                        *Vec.from_str(first_track['angles'])
                        ):
                    break
        else:
            raise Exception('Platform "{}" has no track!'.format(
                plat_inst['targetname']
            ))

        track_type = first_track['file'].casefold()
        if track_type == inst_single:
            # Track is one block long, use a single-only instance and
            # remove track!
            plat_inst['file'] = single_plat_inst
            first_track.remove()
            continue  # Next platform

        track_set = set()
        if track_type == inst_top or track_type == inst_middle:
            # search left
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=-1,
            )
        if track_type == inst_bottom or track_type == inst_middle:
            # search right
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=+1,
            )

        # Give every track a targetname matching the platform
        for ind, track in enumerate(track_set, start=1):
            if track_targets == '':
                track['targetname'] = plat_inst['targetname']
            else:
                track['targetname'] = (
                    plat_inst['targetname'] +
                    '-' +
                    track_targets + str(ind)
                )

        # Now figure out which way the track faces:

        # The direction horizontal track is offset
        side_dir = Vec(0, 1, 0).rotate_by_str(first_track['angles'])

        # The direction of the platform surface
        facing = Vec(-1, 0, 0).rotate_by_str(plat_inst['angles'])
        if side_dir == facing:
            track_facing = 'HORIZ'
        elif side_dir == -facing:
            track_facing = 'HORIZ_MIRR'
        else:
            track_facing = 'VERT'
        # Now add the suffixes
        if track_facing == 'VERT':
            if utils.conv_bool(res['vert_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_vert')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_vert')
        elif track_facing == 'HORIZ_MIRR':
            if utils.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_horiz_mirrored')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_horiz')
        else:  # == 'HORIZ'
            if utils.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    add_suffix(inst, '_horiz')
                if utils.conv_bool(res['plat_suffix', '']):
                    add_suffix(plat_inst, '_horiz')
    return True  # Only run once!


def track_scan(
        tr_set,
        track_inst,
        start_track: VLib.Entity,
        middle_file: str,
        x_dir: int,
        ):
    """Build a set of track instances extending from a point.
    :param track_inst: A dictionary mapping origins to track instances
    :param start_track: The instance we start on
    :param middle_file: The file for the center track piece
    :param x_dir: The direction to look (-1 or 1)
    """
    track = start_track
    move_dir = Vec(x_dir*128, 0, 0).rotate_by_str(track['angles'])
    while track:
        tr_set.add(track)

        next_pos = Vec.from_str(track['origin']) + move_dir
        track = track_inst.get(next_pos.as_tuple(), None)
        if track is None:
            return
        if track['file'].casefold() != middle_file:
            # If the next piece is an end section, add it then quit
            tr_set.add(track)
            return


@make_result('AlterTexture', 'AlterTex', 'AlterFace')
def res_set_texture(inst, res):
    """Set the brush face at a location to a particular texture.

    pos is the position, relative to the instance
      (0 0 0 is the floor-surface).
    dir is the normal of the texture.
    If gridPos is true, the position will be snapped so it aligns with
     the 128 brushes (Useful with fizzler/light strip items).

    tex is the texture used.
    If tex begins and ends with '<>', certain
    textures will be used based on style:
    - If tex is '<special>', the brush will be given a special texture
      like angled and clear panels.
    - '<white>' and '<black>' will use the regular textures for the
      given color.
    - '<white-2x2>', '<white-4x4>', '<black-2x2>', '<black-4x4'> will use
      the given wall-sizes. If on floors or ceilings these always use 4x4.
    - '<2x2>' or '<4x4>' will force to the given wall-size, keeping color.
    - '<special-white>' and '<special-black>' will use a special texture
       of the given color.
    If tex begins and ends with '[]', it is an option in the 'Textures' list.
    These are composed of a group and texture, separated by '.'. 'white.wall'
    are the white wall textures; 'special.goo' is the goo texture.
    """
    import vbsp
    pos = Vec.from_str(res['pos', '0 0 0'])
    pos.z -= 64  # Subtract so origin is the floor-position
    pos = pos.rotate_by_str(inst['angles', '0 0 0'])

    # Relative to the instance origin
    pos += Vec.from_str(inst['origin', '0 0 0'])

    norm = Vec.from_str(res['dir', '0 0 -1']).rotate_by_str(
        inst['angles', '0 0 0']
    )

    if utils.conv_bool(res['gridpos', '0']):
        for axis in 'xyz':
            # Don't realign things in the normal's axis -
            # those are already fine.
            if not norm[axis]:
                pos[axis] //= 128
                pos[axis] *= 128
                pos[axis] += 64

    brush = SOLIDS.get(pos.as_tuple(), None)
    ':type brush: solidGroup'

    if not brush or brush.normal != norm:
        return

    tex = res['tex']

    if tex.startswith('[') and tex.endswith(']'):
        brush.face.mat = vbsp.get_tex(tex[1:-1])
        brush.face.mat = tex
    elif tex.startswith('<') and tex.endswith('>'):
        # Special texture names!
        tex = tex[1:-1].casefold()
        if tex == 'white':
            brush.face.mat = 'tile/white_wall_tile003a'
        elif tex == 'black':
            brush.face.mat = 'metal/black_wall_metal_002c'

        if tex == 'black' or tex == 'white':
            # For these two, run the regular logic to apply textures
            # correctly.
            vbsp.alter_mat(
                brush.face,
                vbsp.face_seed(brush.face),
                vbsp.get_bool_opt('tile_texture_lock', True),
            )

        if tex == 'special':
            vbsp.set_special_mat(brush.face, str(brush.color))
        elif tex == 'special-white':
            vbsp.set_special_mat(brush.face, 'white')
            return
        elif tex == 'special-black':
            vbsp.set_special_mat(brush.face, 'black')

        # Do <4x4>, <white-2x4>, etc
        color = str(brush.color)
        if tex.startswith('black') or tex.endswith('white'):
            # Override the color used for 2x2/4x4 brushes
            color = tex[:5]
        if tex.endswith('2x2') or tex.endswith('4x4'):
            # 4x4 and 2x2 instructions are ignored on floors and ceilings.
            orient = vbsp.get_face_orient(brush.face)
            if orient == vbsp.ORIENT.wall:
                brush.face.mat = vbsp.get_tex(
                    color + '.' + tex[-3:]
                )
            else:
                brush.face.mat = vbsp.get_tex(
                    color + '.' + str(orient)
                )
    else:
        brush.face.mat = tex

    # Don't allow this to get overwritten later.
    vbsp.IGNORED_FACES.add(brush.face)


@make_result('AddBrush')
def res_add_brush(inst, res):
    """Spawn in a brush at the indicated points.

    - point1 and point2 are locations local to the instance, with '0 0 0'
      as the floor-position.
    - type is either 'black' or 'white'.
    - detail should be set to True/False. If true the brush will be a
      func_detail instead of a world brush.

    The sides will be textured with 1x1, 2x2 or 4x4 wall, ceiling and floor
    textures as needed.
    """
    import vbsp

    point1 = Vec.from_str(res['point1'])
    point2 = Vec.from_str(res['point2'])

    point1.z -= 64 # Offset to the location of the floor
    point2.z -= 64

    point1.rotate_by_str(inst['angles']) # Rotate to match the instance
    point2.rotate_by_str(inst['angles'])

    origin = Vec.from_str(inst['origin'])
    point1 += origin # Then offset to the location of the instance
    point2 += origin

    tex_type = res['type', None]
    if tex_type not in ('white', 'black'):
        utils.con_log(
            'AddBrush: "{}" is not a valid brush '
            'color! (white or black)'.format(tex_type)
        )
        tex_type = 'black'

    # We need to rescale black walls and ceilings
    rescale = vbsp.get_bool_opt('random_blackwall_scale') and tex_type == 'black'

    dim = point2 - point1
    dim.max(-dim)

    # Figure out what grid size and scale is needed
    # Check the dimensions in two axes to figure out the largest
    # tile size that can fit in it.
    x_maxsize = min(dim.y, dim.z)
    y_maxsize = min(dim.x, dim.z)
    if x_maxsize <= 32:
        x_grid = '4x4'
        x_scale = 0.25
    elif x_maxsize <= 64:
        x_grid = '2x2'
        x_scale = 0.5
    else:
        x_grid = 'wall'
        x_scale = 1

    if y_maxsize <= 32:
        y_grid = '4x4'
        y_scale = 0.25
    elif y_maxsize <= 64:
        y_grid = '2x2'
        y_scale = 0.5
    else:
        y_grid = 'wall'
        y_scale = 1

    grid_offset = (origin // 128)

    # All brushes in each grid have the same textures for each side.
    random.seed(grid_offset.join(' ') + '-partial_block')

    solids = VMF.make_prism(point1, point2)
    ':type solids: VLib.PrismFace'

    # Ensure the faces aren't re-textured later
    vbsp.IGNORED_FACES.update(solids.solid.sides)

    solids.north.mat = vbsp.get_tex(tex_type + '.' + y_grid)
    solids.south.mat = vbsp.get_tex(tex_type + '.' + y_grid)
    solids.east.mat = vbsp.get_tex(tex_type + '.' + x_grid)
    solids.west.mat = vbsp.get_tex(tex_type + '.' + x_grid)
    solids.top.mat = vbsp.get_tex(tex_type + '.floor')
    solids.bottom.mat = vbsp.get_tex(tex_type + '.ceiling')

    if rescale:
        z_maxsize = min(dim.x, dim.y)
        # randomised black wall scale applies to the ceiling too
        if z_maxsize <= 32:
            z_scale = 0.25
        elif z_maxsize <= 64:
            z_scale = random.choice((0.5, 0.5, 0.25))
        else:
            z_scale = random.choice((1, 1, 0.5, 0.5, 0.25))
    else:
        z_scale = 0.25

    if rescale:
        solids.north.scale = y_scale
        solids.south.scale = y_scale
        solids.east.scale = x_scale
        solids.west.scale = x_scale
        solids.bottom.scale = z_scale

    if utils.conv_bool(res['detail', False], False):
        # Add the brush to a func_detail entity
        VMF.create_ent(
            classname='func_detail'
        ).solids = [
            solids.solid
        ]
    else:
        # Add to the world
        VMF.add_brush(solids.solid)
