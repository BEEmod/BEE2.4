"""Implements the Conditions system.

This system allows users to define transformations applied to
every instance.

In pseudocode:
    for cond in all_conditions:
        for inst in vmf:
            if all(test() in cond):
                apply_results()

Both results and tests recieve configuration keyvalues, the vmf and the
current instance. Tests return a boolean to indicate if they are successful.
Results return None normally, but can return the special value RES_EXHAUSTED to
indicate calling the specific result again will have no effect. In this case the
result will be deleted.

Argument type annotations are used to allow flexibility in defining results and
tests. Each argument must be typed as one of the following to recieve a specific
value:
    * VMF to recieve the overall map.
    * Entity to recieve the current instance.
    * Keyvalues to recieve keyvalues configuration.

If the entity is not provided, the first time the result/test is called it
can return a callable which will instead be called with each entity. This allows
only parsing configuration options once, and is expected to be used with a
closure.
"""
from __future__ import annotations
from typing import Protocol, Any, Final, overload, cast, get_type_hints
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from collections import defaultdict
from decimal import Decimal
from enum import Enum
import functools
import inspect
import math
import pkgutil
import sys
import types
import warnings

from srctools.math import FrozenAngle, Vec, FrozenVec, AnyAngle, AnyMatrix, Angle
from srctools.vmf import EntityGroup, VMF, Entity, Output, Solid, ValidKVs
from srctools import Keyvalues
import attrs
import srctools.logger
import trio

from precomp import instanceLocs, rand
from precomp.collisions import Collisions
from precomp.corridor import Info as MapInfo
from quote_pack import QuoteInfo
import consts
import utils


__all__ = [
    'ALL_INST', 'DIRECTIONS', 'INST_ANGLE', 'PETI_INST_ANGLE', 'RES_EXHAUSTED',
    'MapInfo',
    'TestCallable', 'ResultCallable', 'make_test', 'make_result', 'make_result_setup', 'add_meta',
    'add', 'check_all', 'check_test', 'import_conditions', 'Unsatisfiable',
    'add_inst', 'add_suffix', 'add_output', 'local_name', 'fetch_debug_visgroup', 'set_ent_keys',
    'resolve_offset',
]
COND_MOD_NAME = 'Main Conditions'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.core')

# The global instance filenames we add.
GLOBAL_INSTANCES: set[str] = set()
# All instances that have been placed in the map at any point.
# Pretend empty-string is there, so we don't flag it.
ALL_INST: set[str] = {''}

conditions: list[Condition] = []
TEST_LOOKUP: dict[str, CondCall[bool]] = {}
RESULT_LOOKUP: dict[str, CondCall[object]] = {}

# For legacy setup functions.
RESULT_SETUP: dict[str, Callable[..., Any]] = {}

# Used to dump a list of the tests, results, meta-conditions
ALL_TESTS: list[tuple[str, tuple[str, ...], CondCall[bool]]] = []
ALL_RESULTS: list[tuple[str, tuple[str, ...], CondCall[object]]] = []
ALL_META: list[tuple[str, MetaCond, CondCall[object]]] = []

# The return values for 2-stage results and tests.
type TestCallable = Callable[[Entity], bool]
type ResultCallable = Callable[[Entity], object]


DIRECTIONS: Final[Mapping[str, FrozenVec]] = {
    # Translate these words into a normal vector
    '+x': FrozenVec.x_pos,
    '-x': FrozenVec.x_neg,

    '+y': FrozenVec.y_pos,
    '-y': FrozenVec.y_neg,

    '+z': FrozenVec.z_pos,
    '-z': FrozenVec.z_neg,

    'x': FrozenVec.x_pos,  # For with allow_inverse
    'y': FrozenVec.y_pos,
    'z': FrozenVec.z_pos,

    'up': FrozenVec.z_pos,
    'dn': FrozenVec.z_neg,
    'down': FrozenVec.z_neg,
    'floor': FrozenVec.z_pos,
    'ceiling': FrozenVec.z_neg,
    'ceil': FrozenVec.z_neg,

    'n': FrozenVec.y_pos,
    'north': FrozenVec.y_pos,
    's': FrozenVec.y_neg,
    'south': FrozenVec.y_neg,

    'e': FrozenVec.x_pos,
    'east': FrozenVec.x_pos,
    'w': FrozenVec.x_neg,
    'west': FrozenVec.x_neg,
}

INST_ANGLE: Final[Mapping[FrozenVec, FrozenAngle]] = {
    # IE up = zp = floor
    FrozenVec.z_pos: FrozenAngle(0, 0, 0),
    FrozenVec.z_neg: FrozenAngle(180, 0, 0),

    FrozenVec.x_neg: FrozenAngle(0, 0, 0),
    FrozenVec.y_neg: FrozenAngle(0, 90, 0),
    FrozenVec.x_pos: FrozenAngle(0, 180, 0),
    FrozenVec.y_pos: FrozenAngle(0, 270, 0),

}

PETI_INST_ANGLE: Final[Mapping[FrozenVec, FrozenAngle]] = {
    # The angles needed to point a PeTI instance in this direction
    # IE north = yn
    FrozenVec.z_pos: FrozenAngle(0, 0, 0),
    FrozenVec.z_neg: FrozenAngle(180, 0, 0),

    FrozenVec.y_neg: FrozenAngle(0, 0, 90),
    FrozenVec.x_pos: FrozenAngle(0, 90, 90),
    FrozenVec.y_pos: FrozenAngle(0, 180, 90),
    FrozenVec.x_neg: FrozenAngle(0, 270, 90),
}


class NextInstance(Exception):
    """Raised to skip to the next instance, from the SkipInstance result."""
    pass


class EndCondition(Exception):
    """Raised to skip the condition entirely, from the EndCond result."""
    pass


class Unsatisfiable(Exception):
    """Raised by tests to indicate they currently will always be false with all instances.

    For example, an instance result when that instance currently isn't present.
    """
    pass

# Flag to indicate a result doesn't need to be executed any more,
# and can be cleaned up - adding a global instance, for example.
RES_EXHAUSTED = object()


class MetaCond(Enum):
    """Priority values for meta conditions."""
    FaithPlate = Decimal(-900)
    LinkCubes = Decimal(-750)
    LinkedItems = Decimal(-300)
    MonCameraLink = Decimal(-275)
    ScaffoldLinkOld = Decimal('-250.0001')
    Connections = Decimal(-250)
    ExitSigns = Decimal(-10)
    ElevatorVideos = Decimal(50)
    FogEnts = Decimal(100)
    VoiceLine = Decimal(100)
    Barriers = Decimal(150)
    ApertureTag = Decimal(200)
    AntiFizzBump = Decimal(200)
    PlayerModel = Decimal(400)
    Vactubes = Decimal(400)
    PlayerPortalGun = Decimal(500)
    Fizzler = Decimal(500)
    Screenshot = Decimal(750)
    GenerateCubes = Decimal(750)
    RemoveBlankInst = Decimal(1000)

    def register[Call: Callable[..., object]](self, func: Call) -> Call:
        """Register a meta-condition."""
        add_meta(func, self)
        return func


@attrs.define
class Condition:
    """A single condition which may be evaluated."""
    tests: list[Keyvalues] = attrs.Factory(list)
    results: list[Keyvalues] = attrs.Factory(list)
    else_results: list[Keyvalues] = attrs.Factory(list)
    priority: Decimal = Decimal()
    source: str | None = None

    # If set, this is a meta-condition, and this bypasses everything.
    meta_func: CondCall[object] | None = None

    @classmethod
    def parse(cls, kv_block: Keyvalues, *, toplevel: bool) -> Condition:
        """Create a condition from a Keyvalues block."""
        tests: list[Keyvalues] = []
        results: list[Keyvalues] = []
        else_results: list[Keyvalues] = []
        priority = Decimal()
        source = None
        for kv in kv_block:
            if kv.name == 'result':
                results.extend(kv)  # join multiple ones together
            elif kv.name == 'else':
                else_results.extend(kv)
            elif kv.name == '__src__':
                # Value injected by the BEE2 export, this specifies
                # the original source of the config.
                source = kv.value

            elif kv.name in ('condition', 'switch'):
                # Shortcut to eliminate lots of Result - Condition pairs
                results.append(kv)
            elif kv.name == 'elsecondition':
                kv.name = 'condition'
                else_results.append(kv)
            elif kv.name == 'elseswitch':
                kv.name = 'switch'
                else_results.append(kv)
            elif kv.name == 'priority':
                if not toplevel:
                    LOGGER.warning(
                        'Condition has priority definition, but is not at the toplevel! '
                        'This will not function:\n{}', kv_block
                    )
                try:
                    priority = Decimal(kv.value)
                except ArithmeticError:
                    pass
            else:
                tests.append(kv)

        return Condition(
            tests,
            results,
            else_results,
            priority,
            source,
        )

    @staticmethod
    def test_result(
        coll: Collisions, info: MapInfo, voice_data: QuoteInfo,
        inst: Entity,
        res: Keyvalues,
    ) -> bool | object:
        """Execute the given result."""
        try:
            cond_call = RESULT_LOOKUP[res.name]
        except KeyError:
            err_msg = f'"{res.real_name}" is not a valid condition result!'
            if utils.DEV_MODE:
                # Crash here.
                raise ValueError(err_msg) from None
            else:
                LOGGER.warning(err_msg)
                # Delete this so it doesn't re-fire...
                return RES_EXHAUSTED
        else:
            return cond_call(coll, info, voice_data, inst, res)

    def test(self, coll: Collisions, info: MapInfo, voice_data: QuoteInfo, inst: Entity) -> None:
        """Try to satisfy this condition on the given instance.

        If we find that no instance will succeed, raise Unsatisfiable.
        """
        if self.meta_func is not None:
            self.meta_func(coll, info, voice_data, inst, Keyvalues.root())
            raise EndCondition

        success = True
        # Only the first one can cause this condition to be skipped.
        # We could have a situation where the first test modifies the map
        # such that it becomes satisfiable later, so this would be premature.
        # If we have else results, we also can't skip because those could modify state.
        for i, test in enumerate(self.tests):
            if not check_test(
                test,
                coll, info, voice_data,
                inst,
                can_skip=(i == 0) and not self.else_results,
            ):
                success = False
                break
        results = self.results if success else self.else_results
        for res in results[:]:
            should_del = self.test_result(coll, info, voice_data, inst, res)
            if should_del is RES_EXHAUSTED:
                results.remove(res)


# TODO: want TypeVarTuple, but can't specify Map[Type, AnnArgT]

@overload
def annotation_caller[A1, Res](
    func: Callable[..., Res],
    parm1: type[A1], /,
) -> tuple[
    Callable[[A1], Res],
    tuple[type[A1]]
]: ...
@overload
def annotation_caller[A1, A2, Res](
    func: Callable[..., Res],
    parm1: type[A1], parm2: type[A2], /,
) -> tuple[
    Callable[[A1, A2], Res],
    tuple[type[A1], type[A2]]
]: ...
@overload
def annotation_caller[A1, A2, A3, Res](
    func: Callable[..., Res],
    parm1: type[A1], parm2: type[A2], parm3: type[A3], /,
) -> tuple[
    Callable[[A1, A2, A3], Res],
    tuple[type[A1], type[A2], type[A3]],
]: ...
@overload
def annotation_caller[A1, A2, A3, A4, Res](
    func: Callable[..., Res],
    parm1: type[A1], parm2: type[A2], parm3: type[A3], parm4: type[A4], /,
) -> tuple[
    Callable[[A1, A2, A3, A4], Res],
    tuple[type[A1], type[A2], type[A3], type[A4]],
]: ...
@overload
def annotation_caller[A1, A2, A3, A4, A5, Res](
    func: Callable[..., Res],
    parm1: type[A1], parm2: type[A2], parm3: type[A3],
    parm4: type[A4], parm5: type[A5], /,
) -> tuple[
    Callable[[A1, A2, A3, A4, A5], Res],
    tuple[type[A1], type[A2], type[A3], type[A4], type[A5]],
]: ...
@overload
def annotation_caller[A1, A2, A3, A4, A5, A6, Res](
    func: Callable[..., Res],
    parm1: type[A1], parm2: type[A2], parm3: type[A3],
    parm4: type[A4], parm5: type[A5], param6: type[A6], /,
) -> tuple[
    Callable[[A1, A2, A3, A4, A5, A6], Res],
    tuple[type[A1], type[A2], type[A3], type[A4], type[A5], type[A6]],
]: ...
def annotation_caller[Res](
    func: Callable[..., Res], /,
    *parms: type,
) -> tuple[Callable[..., Res], tuple[type, ...]]:
    """Reorders callback arguments to the requirements of the callback.

    parms should be the unique types of arguments in the order they will be
    called with.

    func's arguments should be positional, and be annotated
    with the same types.

    A wrapper will be returned which can be called
    with arguments in order of parms, but delegates to func.
    The actual argument order is also returned.
    """
    # We can't take keyword arguments, or the varargs.
    allowed_kinds = [
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ]

    # For forward references and 3.7+ stringified arguments.
    # Since we don't care about the return value, temporarily remove it so that it isn't parsed.
    ann_dict = getattr(func, '__annotations__', None)
    if ann_dict is not None:
        return_val = ann_dict.pop('return', allowed_kinds)  # Sentinel
    else:
        return_val = None
    try:
        hints = get_type_hints(func)
    except Exception:
        LOGGER.exception(
            'Could not compute type hints for function {}.{}!',
            getattr(func, '__module__', '<no module>'),
            func.__qualname__,
        )
        sys.exit(1)  # Suppress duplicate exception capture.
    finally:
        if ann_dict is not None and return_val is not allowed_kinds:
            ann_dict['return'] = return_val

    ann_order: list[type] = []

    # type -> parameter name.
    type_to_parm: dict[type, str | None] = dict.fromkeys(parms, None)
    sig = inspect.signature(func)
    for parm in sig.parameters.values():
        ann = parm.annotation
        if isinstance(ann, str):
            ann = hints[parm.name]
        if parm.kind not in allowed_kinds:
            raise ValueError(f'Parameter kind "{parm.kind}" is not allowed!')
        if ann is inspect.Parameter.empty:
            raise ValueError('Parameters must have an annotation!')
        try:
            if type_to_parm[ann] is not None:
                raise ValueError(f'Parameter {ann} used twice!')
        except KeyError:
            raise ValueError(f'Unknown potential type {ann!r}!') from None
        type_to_parm[ann] = parm.name
        ann_order.append(ann)
    inputs = []
    outputs = ['_'] * len(sig.parameters)
    # Parameter -> letter in func signature
    parm_order = {
        parm.name: ind
        for ind, parm in
        enumerate(sig.parameters.values())
    }
    letters = 'abcdefghijklmnopqrstuvwxyz'
    for var_name, parm_typ in zip(letters, parms, strict=False):
        inputs.append(var_name)
        out_name = type_to_parm[parm_typ]
        if out_name is not None:
            outputs[parm_order[out_name]] = var_name

    assert '_' not in outputs, 'Need more variables!'

    comma_inp = ', '.join(inputs)
    comma_out = ', '.join(outputs)

    # Lambdas are expressions, so we can return the result directly.
    reorder_func = _make_reorderer(comma_inp, comma_out)(func)
    # Add some introspection attributes to this generated function.
    try:
        reorder_func.__name__ = func.__name__
    except AttributeError:
        pass
    try:
        reorder_func.__qualname__ = func.__qualname__
    except AttributeError:
        pass
    try:
        reorder_func.__wrapped__ = func  # type: ignore
    except AttributeError:
        pass
    try:
        reorder_func.__doc__ = f'{func.__name__}({comma_inp}) -> {func.__name__}({comma_out})'
    except AttributeError:
        pass
    return reorder_func, tuple(ann_order)


@functools.cache
def _make_reorderer(inputs: str, outputs: str) -> Callable[[Callable[..., object]], Callable[..., Any]]:
    """Build a function that does reordering for annotation caller.

    This allows the code objects to be cached.
    It's a closure over the function, to allow reference to the function more directly.
    This also means it can be reused for other funcs with the same order.
    """
    func = eval(f'lambda func: lambda {inputs}: func({outputs})')
    assert isinstance(func, types.FunctionType)
    return func


def conv_setup_pair[Ret](
    setup: Callable[..., Any],
    result: Callable[..., Ret],
) -> Callable[
    [srctools.VMF, Keyvalues],
    Callable[[Entity], Ret]
]:
    """Convert the old explict setup function into a new closure."""
    setup_wrap, _ = annotation_caller(
        setup,
        srctools.VMF, Keyvalues,
    )
    result_wrap, _ = annotation_caller(
        result,
        srctools.VMF, Entity, Keyvalues,
    )

    def func(vmf: srctools.VMF, kv: Keyvalues) -> Callable[[Entity], Ret]:
        """Replacement function which performs the legacy behaviour."""
        # The old system for setup functions - smuggle them in by
        # setting Keyvalues.value to an arbitrary object.
        smuggle = Keyvalues(kv.real_name, setup_wrap(vmf, kv))

        def closure(ent: Entity) -> Ret:
            """Use the closure to store the smuggled setup data."""
            return result_wrap(vmf, ent, smuggle)

        return closure

    func.__doc__ = result.__doc__
    return func


# Deduplicate the frozen sets.
_META_PRIORITY_CACHE: dict[frozenset[MetaCond], frozenset[MetaCond]] = {}


def meta_priority_converter(priorities: Iterable[MetaCond] | MetaCond) -> frozenset[MetaCond]:
    """Allow passing either a single enum, or any iterable."""
    if isinstance(priorities, MetaCond):
        result = frozenset([priorities])
    else:
        result = frozenset(priorities)
    return _META_PRIORITY_CACHE.setdefault(result, result)


@attrs.define(eq=False)
class CondCall[CallResultT]:
    """A result or test callback.

    This should be called to execute it.
    """
    func: Callable[..., CallResultT | Callable[[Entity], CallResultT]]
    group: str | None
    valid_before: frozenset[MetaCond] = attrs.field(kw_only=True, converter=meta_priority_converter)
    valid_after: frozenset[MetaCond] = attrs.field(kw_only=True, converter=meta_priority_converter)

    _setup_data: dict[int, Callable[[Entity], CallResultT]] | None = attrs.field(init=False, repr=False)
    _cback: Callable[
        [srctools.VMF, Collisions, MapInfo, QuoteInfo, Entity, Keyvalues],
        CallResultT | Callable[[Entity], CallResultT],
    ] = attrs.field(init=False)

    def __attrs_post_init__(self) -> None:
        cback, arg_order = annotation_caller(
            self.func,
            srctools.VMF, Collisions, MapInfo, QuoteInfo,
            Entity, Keyvalues,
        )
        self._cback = cback
        if Entity not in arg_order:
            # We have setup functions.
            self._setup_data = {}
        else:
            self._setup_data = None

    @property
    def __doc__(self) -> str | None:
        """Pass through __doc__ to the wrapped function."""
        return self.func.__doc__

    @__doc__.setter
    def __doc__(self, value: str) -> None:
        self.func.__doc__ = value

    def __call__(
        self,
        coll: Collisions, info: MapInfo, voice: QuoteInfo,
        ent: Entity,
        conf: Keyvalues,
    ) -> CallResultT:
        """Execute the callback."""
        if self._setup_data is None:
            return self._cback(ent.map, coll, info, voice, ent, conf)  # type: ignore
        else:
            # Execute setup functions if required.
            if id(conf) in self._setup_data:
                cback = self._setup_data[id(conf)]
            else:
                # The entity should never be used in setup functions. Pass a dummy object
                # so errors occur if it's used.
                cback = self._setup_data[id(conf)] = self._cback(  # type: ignore
                    ent.map, coll, info, voice,
                    cast(Entity, object()),
                    conf,
                )

            if not callable(cback):
                # We don't actually have a setup func,
                # this func just doesn't care about entities.
                # Fix this incorrect assumption, then return
                # the result.
                self._setup_data = None
                return cback

            return cback(ent)


def _get_cond_group(func: Any) -> str | None:
    """Get the condition group hint for a function.

    None means that the condition is "ungrouped".
    """
    try:
        group = func.__globals__['COND_MOD_NAME']
    except KeyError:
        group = func.__globals__['__name__']
        LOGGER.warning('No name for module "{}"!', group)
    if group is None or type(group) is str:
        return group
    LOGGER.warning(
        'Module "{}" defines COND_MOD_NAME = {!r}, which is not Optional[str]!',
        func.__globals__['__name__'],
        group,
    )
    return str(group)


def add_meta(func: Callable[..., object], priority: MetaCond) -> None:
    """Add a metacondition, which executes a function at a priority level.

    Used to allow users to allow adding conditions before or after a
    transformation like the adding of quotes.
    """
    name = f'{getattr(func, "__module__", "???")}.{func.__qualname__}()'
    LOGGER.debug(
        "Adding metacondition {} with priority: {!r}",
        name,
        priority,
    )

    # We don't care about setup functions for this, and valid before/after is also useless.
    wrapper = CondCall(func, _get_cond_group(func), valid_before=(), valid_after=())

    cond = Condition(
        priority=priority.value,
        source=f'MetaCondition {name}',
        # Special attribute, overrides results when present.
        meta_func=wrapper,
    )

    conditions.append(cond)
    ALL_META.append((func.__qualname__, priority, wrapper))


def make_test[TestCallT: Callable[..., bool | TestCallable]](
    orig_name: str, *aliases: str,
    valid_before: Iterable[MetaCond] | MetaCond = (),
    valid_after: Iterable[MetaCond] | MetaCond = (),
) -> Callable[[TestCallT], TestCallT]:
    """Decorator to add tests to the lookup."""
    def x(func: TestCallT) -> TestCallT:
        wrapper: CondCall[bool] = CondCall(
            func, _get_cond_group(func),
            valid_before=valid_before,
            valid_after=valid_after,
        )
        ALL_TESTS.append((orig_name, aliases, wrapper))
        name = orig_name.casefold()
        if name in TEST_LOOKUP:
            raise ValueError(f'Test {orig_name} is a duplicate!')
        TEST_LOOKUP[orig_name.casefold()] = wrapper
        for name in aliases:
            if name.casefold() in TEST_LOOKUP:
                raise ValueError(f'Test {orig_name} is a duplicate!')
            TEST_LOOKUP[name.casefold()] = wrapper
        return func
    return x


def make_result(
    orig_name: str, *aliases: str,
    valid_before: Iterable[MetaCond] | MetaCond = (),
    valid_after: Iterable[MetaCond] | MetaCond = (),
) -> utils.DecoratorProto:
    """Decorator to add results to the lookup."""
    folded_name = orig_name.casefold()
    # Discard the original name from aliases, if it's also there.
    aliases = tuple([
        name for name in aliases
        if name.casefold() != folded_name
    ])

    def x[ResultT](result_func: Callable[..., ResultT]) -> Callable[..., ResultT]:
        """Create the result when the function is supplied."""
        # Legacy setup func support.
        func: Callable[..., Callable[[Entity], object] | object]
        try:
            setup_func = RESULT_SETUP.pop(orig_name.casefold())
        except KeyError:
            func = result_func
            setup_func = None
        else:
            # Combine the legacy functions into one using a closure.
            assert setup_func is not None
            func = conv_setup_pair(setup_func, result_func)

        wrapper: CondCall[object] = CondCall(
            func, _get_cond_group(result_func),
            valid_before=valid_before,
            valid_after=valid_after,
        )
        if orig_name.casefold() in RESULT_LOOKUP:
            raise ValueError(f'Result {orig_name} is a duplicate!')
        RESULT_LOOKUP[orig_name.casefold()] = wrapper
        for name in aliases:
            if name.casefold() in RESULT_LOOKUP:
                raise ValueError(f'Result {orig_name} is a duplicate!')
            RESULT_LOOKUP[name.casefold()] = wrapper
        if setup_func is not None:
            for name in aliases:
                alias_setup = RESULT_SETUP.pop(name.casefold())
                assert alias_setup is setup_func, alias_setup
        ALL_RESULTS.append((orig_name, aliases, wrapper))
        return result_func
    return x  # type: ignore[return-value]  # Callable[..., T] -> TypeVar(bound=Callable)


def make_result_setup(*names: str) -> utils.DecoratorProto:
    """Legacy setup function for results. This is no longer used."""
    # Users can't do anything about this, don't bother them.
    if utils.DEV_MODE:
        warnings.warn('Use closure system instead.', DeprecationWarning, stacklevel=2)

    def deco[Func: Callable[..., object]](func: Func, /) -> Func:
        for name in names:
            if name.casefold() in RESULT_LOOKUP:
                raise ValueError('Legacy setup called after making result!')
            RESULT_SETUP[name.casefold()] = func
        return func
    return deco


def add(kv_block: Keyvalues) -> None:
    """Parse and add a condition to the list."""
    con = Condition.parse(kv_block, toplevel=True)
    if con.results or con.else_results:
        conditions.append(con)


def check_all(
    vmf: VMF,
    coll: Collisions,
    info: MapInfo,
    voice_data: QuoteInfo,
) -> None:
    """Check all conditions."""
    ALL_INST.update({
        inst['file'].casefold()
        for inst in vmf.by_class['func_instance']
    })

    # Sort by priority, where higher = done later
    zero = Decimal(0)
    conditions.sort(key=lambda cond: getattr(cond, 'priority', zero))
    # Check if any make_result_setup calls were done with no matching result.
    if utils.DEV_MODE and RESULT_SETUP:
        raise ValueError('Extra result_setup calls:\n' + '\n'.join([
            f' - "{name}": {getattr(func, "__module__", "?")}.{func.__qualname__}()'
            for name, func in RESULT_SETUP.items()
        ]))

    LOGGER.info('Checking Conditions...')
    LOGGER.info('-----------------------')
    skipped_cond = 0
    for condition in conditions:
        with srctools.logger.context(condition.source or ''):
            for inst in vmf.by_class['func_instance']:
                try:
                    condition.test(coll, info, voice_data, inst)
                except NextInstance:
                    # NextInstance is raised to immediately stop running
                    # this condition, and skip to the next instance.
                    continue
                except Unsatisfiable:
                    # Unsatisfiable indicates this condition's tests will
                    # never succeed, so just skip.
                    skipped_cond += 1
                    break
                except EndCondition:
                    # EndCondition is raised to immediately stop running
                    # this condition, and skip to the next condition.
                    break
                except Exception:
                    # Print the source of the condition if it fails...
                    LOGGER.exception('Error in {}:', condition.source or 'condition')
                    # Exit directly, so we don't print it again in the exception
                    # handler
                    utils.quit_app(1)
                if not condition.results and not condition.else_results:
                    break  # Condition has run out of results, quit early

        if utils.DEV_MODE:
            # Check ALL_INST is correct.
            extra = GLOBAL_INSTANCES - ALL_INST
            if extra:
                LOGGER.warning('Extra global inst not in all inst: {}', extra)
            for inst in vmf.by_class['func_instance']:
                if inst['file'].casefold() not in ALL_INST:
                    LOGGER.warning(
                        'Condition "{}" doesn\'t add "{}" to all_inst!',
                        condition.source,
                        inst['file'],
                    )
                    extra.add(inst['file'].casefold())
            # Suppress errors for future conditions.
            ALL_INST.update(extra)

    # Clear out any blank instances. This allows code elsewhere to have a convenient way
    # to just delete instances.
    for inst in vmf.by_class['func_instance']:
        # If editoritems instances are set to "", PeTI will autocorrect it to
        # ".vmf" - we need to handle that too.
        if inst['file'].casefold() in ('', '.vmf'):
            inst.remove()

    LOGGER.info('---------------------')
    LOGGER.info(
        'Conditions executed, {}/{} ({:.0%}) skipped!',
        skipped_cond, len(conditions),
        skipped_cond/len(conditions),
    )
    import vbsp
    LOGGER.info('Map has attributes: {}', sorted(info.iter_attrs()))
    # '' is always present, which sorts first, conveniently adding a \n at the start.
    LOGGER.debug('All instances referenced:{}', '\n'.join(sorted(ALL_INST)))
    LOGGER.info(
        'instanceLocs cache: {} & {}',
        instanceLocs.resolve_cache_info(),
        instanceLocs.resolve_filter.cache_info(),
    )
    LOGGER.info('Style Vars: {}', dict(vbsp.settings['style_vars']))
    LOGGER.info('Global instances: {}', GLOBAL_INSTANCES)


def check_test(
    test: Keyvalues,
    coll: Collisions, info: MapInfo, voice: QuoteInfo,
    inst: Entity, can_skip: bool = False,
) -> bool:
    """Determine the result for a condition test.

    If can_skip is true, testd raising Unsatifiable will pass the exception through.
    """
    name = test.name
    # If starting with '!', invert the result.
    if name[:1] == '!':
        desired_result = False
        can_skip = False  # This doesn't work.
        name = name[1:]
    else:
        desired_result = True
    try:
        func = TEST_LOOKUP[name]
    except KeyError:
        err_msg = f'"{name}" is not a valid condition flag!'
        if utils.DEV_MODE:
            # Crash here.
            raise ValueError(err_msg) from None
        else:
            LOGGER.warning(err_msg)
            # Skip these conditions...
            return False

    try:
        res = func(coll, info, voice, inst, test)
    except Unsatisfiable:
        if can_skip:
            raise
        else:
            return not desired_result
    else:
        return res is desired_result


def import_conditions() -> None:
    """Import all the components of the conditions package.

    This ensures everything gets registered.
    """
    # Import all the condition modules. The module will run add_test()
    # or add_result() functions, which save the functions into our dicts.
    from . import ( # noqa
        _scaffold_compat, addInstance, antlines, apTag, brushes, catwalks, collisions, connections,
        conveyorBelt, custItems, cutoutTile, entities, errors, faithplate, fizzler, barriers, globals,
        instances, linked_items, logical, marker, monitor, piston_platform, positioning, python,
        randomise, removed, resizableTrigger, sendificator, signage, trackPlat, vactubes,
    )

    # If not frozen, check none are missing.
    if not utils.FROZEN:
        import builtins
        ns = builtins.globals()
        # Verify none are missing.
        for mod_info in pkgutil.iter_modules(__path__, 'precomp.conditions.'):
            stem = mod_info.name.rsplit('.', 1)[-1]
            try:
                found = ns[stem]
            except KeyError as exc:
                raise Exception(mod_info) from exc
            # Verify that we didn't shadow the import by importing in this __init__ module.
            if not isinstance(found, types.ModuleType) or found.__name__ != mod_info.name:
                raise Exception(mod_info, found)
    LOGGER.info('Imported all conditions modules!')

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


async def dump_conditions(filename: trio.Path) -> None:
    """Dump docs for all the condition tests, results and metaconditions."""

    LOGGER.info('Dumping conditions...')

    # Extract the text before the marker line.
    prelude = []
    async with await filename.open('r') as file_prelude:
        async for line in file_prelude:
            prelude.append(line)
            if DOC_MARKER in line:
                break
        else:
            raise ValueError('No marker text!')

    ALL_META.sort(key=lambda tup: tup[1].value)  # Sort by priority

    async with await filename.open('w') as file:
        for line in prelude:
            await file.write(line)
        await file.write('\n')

        for test_key, priority, func in ALL_META:
            await file.write(f'#### `{test_key}` ({priority.value}):\n\n')
            await file.write(dump_func_docs(func))
            await file.write('\n\n')

        all_cond_types: list[tuple[list[tuple[str, tuple[str, ...], CondCall[Any]]], str]] = [
            (ALL_TESTS, 'Tests'),
            (ALL_RESULTS, 'Results'),
        ]
        for lookup, name in all_cond_types:
            await file.write('<!------->\n')
            await file.write(f'# {name}\n')
            await file.write('<!------->\n')

            lookup_grouped: dict[str, list[
                tuple[str, tuple[str, ...], CondCall[Any]]
            ]] = defaultdict(list)

            for test_key, aliases, func in lookup:
                group = getattr(func, 'group', 'ERROR')
                if group is None:
                    group = '00special'
                lookup_grouped[group].append((test_key, aliases, func))

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
                    await file.write('---------\n\n')

                if group == '00special':
                    await file.write(DOC_SPECIAL_GROUP)
                else:
                    await file.write(f'### {group}\n\n')

                LOGGER.info('Doing {} group...', group)

                for test_key, aliases, func in funcs:
                    await file.write(f'#### `{test_key}`:\n\n')
                    if aliases:
                        await file.write(f'**Aliases:** `{"`, `".join(aliases)}`  \n')
                    if func.valid_after or func.valid_before:
                        await file.write('**Valid Priority Levels:** ')
                        before = [meta.value for meta in func.valid_before]
                        after = [meta.value for meta in func.valid_after]
                        if before and after:
                            await file.write(f'between `{min(after):+}` \N{EN DASH} `{max(before):+}` (inclusive)\n')
                        elif before:
                            await file.write(f'less than `{min(before):+}`\n')
                        elif after:
                            await file.write(f'greater than `{max(after):+}`\n')
                        else:
                            raise AssertionError(func)
                    await file.write(dump_func_docs(func))
                    await file.write('\n\n')


def dump_func_docs(func: Callable[..., object]) -> str:
    """Extract the documentation for a function."""
    import inspect
    return inspect.getdoc(func) or '**No documentation!'


def add_inst(
    vmf: VMF,
    *,
    file: str,
    origin: Vec | FrozenVec | str,
    angles: AnyAngle | AnyMatrix | str = '0 0 0',
    targetname: str = '',
    fixup_style: int | str = '0',  # Default to Prefix.
    no_fixup: bool = False,
) -> Entity:
    """Create and add a new instance at the specified position.

    This provides defaults for parameters, and adds the filename to ALL_INST.
    Values accept str in addition so that they can be copied from existing keyvalues.

    If no_fixup is set, it overrides fixup_style to None - this way it's a more clear
    parameter for code.
    """
    if no_fixup:
        fixup_style = '2'
    ALL_INST.add(file.casefold())
    return vmf.create_ent(
        'func_instance',
        origin=origin,
        angles=angles,
        targetname=targetname,
        file=file,
        fixup_style=fixup_style,
    )


def add_output(inst: Entity, kv: Keyvalues, target: str) -> None:
    """Add a customisable output to an instance."""
    inst.add_out(Output(
        kv['output', ''],
        target,
        kv['input', ''],
        inst_in=kv['targ_in', ''],
        inst_out=kv['targ_out', ''],
        ))


def add_suffix(inst: Entity, suff: str) -> None:
    """Append the given suffix to the instance.
    """
    file = inst['file']
    old_name, dot, ext = file.partition('.')
    inst['file'] = new_filename = ''.join((old_name, suff, dot, ext))
    ALL_INST.add(new_filename.casefold())


def local_name(inst: Entity, name: str | Entity | None) -> str:
    """Fixup the given name for inside an instance.

    This handles @names, !activator, and obeys the fixup_style option.

    If the name is an entity, that entity's name is passed through unchanged.
    If the name is blank or None, the instance's name is returned.
    """
    # Don't translate direct entity names - it's already the entity's full
    # name.
    if isinstance(name, Entity):
        return name['targetname']

    targ_name = inst['targetname', '']

    # If blank, keep it blank, and don't fix special or global names
    if name is None:
        return targ_name
    if not name or name.startswith(('!', '@')):
        return name

    fixup = inst['fixup_style', '0']

    if fixup == '2' or not targ_name:
        # We can't do fixup...
        return name
    elif fixup == '0':
        # Prefix
        return f'{targ_name}-{name}'
    elif fixup == '1':
        # Postfix
        return f'{name}-{targ_name}'
    else:
        raise ValueError(f'Unknown fixup style {fixup}!')


class DebugAdder(Protocol):
    """Result of fetch_debug_visgroup()."""
    @overload
    def __call__(self, ent: Entity, /) -> Entity:
        """Add this entity to the map, the visgroup and make it hidden."""

    @overload
    def __call__(self, brush: Solid, /) -> Entity:
        """Add this brush to the map, the visgroup and make it hidden."""

    @overload
    def __call__(self, classname: str, /, *, comment: str = '', **kwargs: ValidKVs) -> Entity:
        """Create an entity with the specified keyvalues."""


def fetch_debug_visgroup(
    vmf: VMF,
    vis_name: str,
    r: int = 113, g: int = 113, b: int = 0,
    force: bool | None = None,
) -> DebugAdder:
    """If debugging is enabled, return a function that adds entities to the specified visgroup.

    * vis_name: The name of the visgroup to use. If already present the existing one is used.
    * r, g, b: Color to use, if creating.
    * force: If set, forces this to be present/absent. Otherwise, this only adds if Dev Mode is enabled.

    The returned function can either be called with a classname + keyvalues to create an ent,
    or given an existing ent/brush to add. If given an existing ent/brush, it should not be
    already added to the VMF - this will skip doing so if debugging is disabled. In that case
    the ent/brush will just be discarded harmlessly.
    """
    if force is None:
        force = utils.DEV_MODE
    if not force:
        def func(target: str | Entity | Solid, /, **kwargs: ValidKVs) -> Entity | Solid:
            """Do nothing."""
            if isinstance(target, str):
                # Create a dummy entity, which will be discarded.
                return Entity(vmf, keys={'classname': target})
            return target

        return func  # type: ignore[return-value]

    for visgroup in vmf.vis_tree:
        if visgroup.name == vis_name:
            break
    else:
        # Create the visgroup.
        visgroup = vmf.create_visgroup(vis_name, (r, g, b))

    group = EntityGroup(vmf, color=Vec(r, g, b), shown=False)

    def adder(target: str | Entity | Solid, /, **kwargs: ValidKVs) -> Entity | Solid:
        """Add a marker to the map."""
        if isinstance(target, str):
            comment = kwargs.pop('comments', kwargs.pop('comment', ''))
            target = vmf.create_ent(target, **kwargs)
            target.comments = str(comment)
        elif isinstance(target, Solid):
            vmf.add_brush(target)
        elif isinstance(target, Entity):
            vmf.add_ent(target)

        target.visgroup_ids.add(visgroup.id)
        if isinstance(target, Solid):
            target.group_id = group.id
        else:
            target.groups.add(group.id)
        target.vis_shown = False
        target.hidden = True
        return target

    return adder  # type: ignore[return-value]


def widen_fizz_brush(brush: Solid, thickness: float, bounds: tuple[Vec, Vec] | None = None) -> None:
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


def set_ent_keys(
    ent: MutableMapping[str, str],
    inst: Entity,
    kv_block: Keyvalues,
    block_name: str = 'Keys',
) -> None:
    """Copy the given key prop block to an entity.

    This uses the keys and 'localkeys' properties on the kv_block.
    Values with $fixup variables will be treated appropriately.
    LocalKeys keys will be changed to use instance-local names, where needed.
    block_name lets you change the 'keys' suffix on the kv_block name.
    ent can be any mapping.
    """
    for kv in kv_block.find_block(block_name, or_blank=True):
        ent[kv.real_name] = inst.fixup.substitute(kv.value)
    for kv in kv_block.find_block('Local' + block_name, or_blank=True):
        ent[kv.real_name] = local_name(inst, inst.fixup.substitute(kv.value))


def resolve_offset(inst: Entity, value: str, scale: float = 1.0, zoff: float = 0.0) -> Vec:
    """Retrieve an offset from an instance var. This allows several special values:

    * Any $replace variables
    * <piston_start> or <piston> to get the unpowered position of a piston plat
    * <piston_end> to get the powered position of a piston plat
    * <piston_top> to get the extended position of a piston plat
    * <piston_bottom> to get the retracted position of a piston plat

    If scale is set, read values are multiplied by this, and zoff is added to Z.
    """
    value = inst.fixup.substitute(value).casefold()
    # Offset the overlay by the given distance
    # Some special placeholder values:
    if value == '<piston_start>' or value == '<piston>':
        if inst.fixup.bool(consts.FixupVars.PIST_IS_UP):
            value = '<piston_top>'
        else:
            value = '<piston_bottom>'
    elif value == '<piston_end>':
        if inst.fixup.bool(consts.FixupVars.PIST_IS_UP):
            value = '<piston_bottom>'
        else:
            value = '<piston_top>'

    if value == '<piston_bottom>':
        offset = Vec(
            z=inst.fixup.int(consts.FixupVars.PIST_BTM) * 128,
        )
    elif value == '<piston_top>':
        offset = Vec(
            z=inst.fixup.int(consts.FixupVars.PIST_TOP) * 128,
        )
    else:
        # Regular vector
        offset = Vec.from_str(value) * scale
    offset.z += zoff

    offset.localise(
        Vec.from_str(inst['origin']),
        Angle.from_str(inst['angles']),
    )

    return offset


@make_test('debug')
@make_result('debug')
def debug_test_result(inst: Entity, kv: Keyvalues) -> bool:
    """Displays text when executed, for debugging conditions.

    If the text ends with an '=', the instance will also be displayed.
    As a test, this always evaluates as true.
    """
    # Mark as a warning, so it's more easily seen.
    if kv.has_children():
        LOGGER.warning('Debug:\n{!s}\n{!s}', kv, inst)
    else:
        LOGGER.warning('Debug: {}\n{!s}', kv.value, inst)
    return True  # The test is always true


@make_result('dummy', 'nop', 'do_nothing')
def dummy_result() -> None:
    """Dummy result that doesn't do anything."""
    pass


@make_result('timedRelay')
def res_timed_relay(vmf: VMF, res: Keyvalues) -> Callable[[Entity], None]:
    """Generate a `logic_relay` with outputs delayed by a certain amount.

    This allows triggering outputs based on `$timer_delay` values.
    """
    delay_var = res['variable', consts.FixupVars.TIM_DELAY]
    name = res['targetname']
    disabled_var = res['disabled', '0']
    flags = res['spawnflags', '0']

    final_outs = [
        Output.parse(prop)
        for prop in res.find_children('FinalOutputs')
    ]

    rep_outs = [
        Output.parse(prop)
        for prop in res.find_children('RepOutputs')
    ]

    def make_relay(inst: Entity) -> None:
        """Places the relay."""
        relay = vmf.create_ent(
            classname='logic_relay',
            spawnflags=flags,
            origin=inst['origin'],
            targetname=local_name(inst, name),
        )

        relay['StartDisabled'] = inst.fixup.substitute(disabled_var, allow_invert=True)

        delay = srctools.conv_float(inst.fixup.substitute(delay_var))

        for off in range(int(math.ceil(delay))):
            for out in rep_outs:
                new_out = out.copy()
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

    return make_relay


@make_result('nextInstance')
def res_break() -> None:
    """Skip to the next instance.

    The value will be ignored.
    """
    raise NextInstance


@make_result('endCondition', 'nextCondition')
def res_end_condition() -> None:
    """Skip to the next condition.

    The value will be ignored.
    """
    raise EndCondition


@make_result('staticPiston')
def make_static_pist(vmf: srctools.VMF, res: Keyvalues) -> Callable[[Entity], None]:
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
    inst_keys = (
        'bottom_0', 'bottom_1', 'bottom_2', 'bottom_3',
        'logic_0', 'logic_1', 'logic_2', 'logic_3',
        'static_0', 'static_1', 'static_2', 'static_3', 'static_4',
        'grate_low', 'grate_high',
    )

    if res.has_children():
        # Pull from config
        instances = {
            name: instanceLocs.resolve_one(
                res[name, ''],
                error=False,
            ) for name in inst_keys
        }
    else:
        # Pull from editoritems
        if ':' in res.value:
            from_item, prefix = res.value.split(':', 1)
        else:
            from_item = res.value
            prefix = ''
        instances = {
            name: instanceLocs.resolve_one(f'<{from_item}:bee2_{prefix}{name}>', error=False)
            for name in inst_keys
        }

    def make_static(ent: Entity) -> None:
        """Make a piston static."""
        bottom_pos = ent.fixup.int(consts.FixupVars.PIST_BTM, 0)

        if (
            ent.fixup.int(consts.FixupVars.CONN_COUNT) > 0 or
            ent.fixup.bool(consts.FixupVars.DIS_AUTO_DROP)
        ):  # can it move?
            ent.fixup[consts.FixupVars.BEE_PIST_IS_STATIC] = True

            # Use instances based on the height of the bottom position.
            val = instances['bottom_' + str(bottom_pos)]
            if val:  # Only if defined
                ent['file'] = val
                ALL_INST.add(val.casefold())

            logic_file = instances['logic_' + str(bottom_pos)]
            if logic_file:
                # Overlay an additional logic file on top of the original
                # piston. This allows easily splitting the piston logic
                # from the styled components
                logic_ent = ent.copy()
                logic_ent['file'] = logic_file
                vmf.add_ent(logic_ent)
                ALL_INST.add(logic_file.casefold())
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

            val = instances['static_' + str(pos)]
            if val:
                ent['file'] = val
                ALL_INST.add(val.casefold())

        # Add in the grating for the bottom as an overlay.
        # It's low to fit the piston at minimum, or higher if needed.
        grate = instances[
            'grate_high'
            if bottom_pos > 0 else
            'grate_low'
        ]
        if grate:
            grate_ent = ent.copy()
            grate_ent['file'] = grate
            ALL_INST.add(grate.casefold())
            vmf.add_ent(grate_ent)
    return make_static


@make_result('GooDebris')
def res_goo_debris(vmf: VMF, res: Keyvalues) -> object:
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
    from precomp import brushLoc

    space = res.int('spacing', 1)
    rand_count = res.int('number', None)
    rand_list: list[int] | None
    if rand_count:
        rand_list = rand.parse_weights(
            rand_count,
            res['weights', ''],
        )
    else:
        rand_list = None
    chance = res.int('chance', 30) / 100
    file = res['file'].removesuffix('.vmf')
    offset = res.int('offset', 0)

    goo_top_locs = {
        pos
        for pos, block in
        brushLoc.POS.items()
        if block.is_goo and block.is_top
    }

    if space == 0:
        # No spacing needed, just copy
        possible_locs = [loc.thaw() for loc in goo_top_locs]
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
                if FrozenVec(x + x_off, y + y_off, z) not in goo_top_locs:
                    break  # This doesn't qualify
            else:
                possible_locs.append(brushLoc.grid_to_world(Vec(x, y, z)))

    LOGGER.info(
        'GooDebris: {}/{} locations',
        len(possible_locs),
        len(goo_top_locs),
    )

    for loc in possible_locs:
        rng = rand.seed(b'goo_debris', loc)
        if rng.random() > chance:
            continue

        if rand_list is not None:
            rand_fname = f'{file}_{rng.choice(rand_list) + 1}.vmf'
        else:
            rand_fname = file + '.vmf'

        if offset > 0:
            loc.x += rng.randint(-offset, offset)
            loc.y += rng.randint(-offset, offset)
        loc.z -= 32  # Position the instances in the center of the 128 grid.
        add_inst(
            vmf,
            file=rand_fname,
            origin=loc,
            angles=Angle(yaw=rng.randrange(0, 3600) / 10),
        )

    return RES_EXHAUSTED
