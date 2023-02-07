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
    * Keyvalues to recieve keyvalues configuration.

If the entity is not provided, the first time the result/flag is called it
can return a callable which will instead be called with each entity. This allows
only parsing configuration options once, and is expected to be used with a
closure.
"""
from __future__ import annotations
import functools
import inspect
import io
import importlib
import math
import pkgutil
import sys
import typing
import warnings
from collections.abc import Mapping
from collections import defaultdict
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar, Any, Callable, TextIO, Tuple, Type, overload, cast

import attrs
import srctools.logger
from srctools import (
    Keyvalues, FrozenVec, Vec, VMF, Entity, Output, Solid, Angle, Matrix,
)
from typing_extensions import Literal

from precomp import instanceLocs, rand, collisions
from precomp.corridor import Info as MapInfo
import consts
import utils


COND_MOD_NAME = 'Main Conditions'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.core')

# The global instance filenames we add.
GLOBAL_INSTANCES: set[str] = set()
# All instances that have been placed in the map at any point.
# Pretend empty-string is there, so we don't flag it.
ALL_INST: set[str] = {''}

conditions: list[Condition] = []
FLAG_LOOKUP: dict[str, CondCall[bool]] = {}
RESULT_LOOKUP: dict[str, CondCall[object]] = {}

# For legacy setup functions.
RESULT_SETUP: dict[str, Callable[..., Any]] = {}

# Used to dump a list of the flags, results, meta-conditions
ALL_FLAGS: list[tuple[str, tuple[str, ...], CondCall[bool]]] = []
ALL_RESULTS: list[tuple[str, tuple[str, ...], CondCall[object]]] = []
ALL_META: list[tuple[str, Decimal, CondCall[object]]] = []


CallableT = TypeVar('CallableT', bound=Callable)
# The return values for 2-stage results and flags.
FlagCallable = Callable[[Entity], bool]
ResultCallable = Callable[[Entity], object]


class SWITCH_TYPE(Enum):
    """The methods useable for switch options."""
    FIRST = 'first'  # choose the first match
    LAST = 'last'  # choose the last match
    RANDOM = 'random'  # Randomly choose
    ALL = 'all'  # Run all matching commands


xp = FrozenVec(1, 0, 0)
xn = FrozenVec(-1, 0, 0)
yp = FrozenVec(0, 1, 0)
yn = FrozenVec(0, -1, 0)
zp = FrozenVec(0, 0, 1)
zn = FrozenVec(0, 0, -1)

DIRECTIONS: Mapping[str, FrozenVec] = {
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
    zp: "0 0 0",
    zn: "180 0 0",

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


class Unsatisfiable(Exception):
    """Raised by flags to indicate they currently will always be false with all instances.

    For example, an instance result when that instance currently isn't present.
    """
    pass

# Flag to indicate a result doesn't need to be executed anymore,
# and can be cleaned up - adding a global instance, for example.
RES_EXHAUSTED = object()


@attrs.define
class Condition:
    """A single condition which may be evaluated."""
    flags: list[Keyvalues] = attrs.Factory(list)
    results: list[Keyvalues] = attrs.Factory(list)
    else_results: list[Keyvalues] = attrs.Factory(list)
    priority: Decimal = Decimal()
    source: str = None

    @classmethod
    def parse(cls, kv_block: Keyvalues, *, toplevel: bool) -> Condition:
        """Create a condition from a Keyvalues block."""
        flags: list[Keyvalues] = []
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
                flags.append(kv)

        return Condition(
            flags,
            results,
            else_results,
            priority,
            source,
        )

    @staticmethod
    def test_result(coll: collisions.Collisions, info: MapInfo, inst: Entity, res: Keyvalues) -> bool | object:
        """Execute the given result."""
        try:
            cond_call = RESULT_LOOKUP[res.name]
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
            return cond_call(coll, info, inst, res)

    def test(self, coll: collisions.Collisions, info: MapInfo, inst: Entity) -> None:
        """Try to satisfy this condition on the given instance.

        If we find that no instance will succeed, raise Unsatisfiable.
        """
        success = True
        # Only the first one can cause this condition to be skipped.
        # We could have a situation where the first flag modifies the map
        # such that it becomes satisfiable later, so this would be premature.
        # If we have else results, we also can't skip because those could modify state.
        for i, flag in enumerate(self.flags):
            if not check_flag(flag, coll, info, inst, can_skip=i==0 and not self.else_results):
                success = False
                break
        results = self.results if success else self.else_results
        for res in results[:]:
            should_del = self.test_result(coll, info, inst, res)
            if should_del is RES_EXHAUSTED:
                results.remove(res)


AnnResT = TypeVar('AnnResT')
# TODO: want TypeVarTuple, but can't specify Map[Type, AnnArgT]
AnnArg1T = TypeVar('AnnArg1T')
AnnArg2T = TypeVar('AnnArg2T')
AnnArg3T = TypeVar('AnnArg3T')
AnnArg4T = TypeVar('AnnArg4T')
AnnArg5T = TypeVar('AnnArg5T')


@overload
def annotation_caller(
    func: Callable[..., AnnResT],
    parm1: Type[AnnArg1T], /,
) -> tuple[
    Callable[[AnnArg1T], AnnResT],
    tuple[Type[AnnArg1T]]
]: ...
@overload
def annotation_caller(
    func: Callable[..., AnnResT],
    parm1: Type[AnnArg1T], parm2: Type[AnnArg2T],  /,
) -> tuple[
    Callable[[AnnArg1T, AnnArg2T], AnnResT],
    tuple[Type[AnnArg1T], Type[AnnArg2T]]
]: ...
@overload
def annotation_caller(
    func: Callable[..., AnnResT],
    parm1: Type[AnnArg1T], parm2: Type[AnnArg2T], parm3: Type[AnnArg3T], /,
) -> tuple[
    Callable[[AnnArg1T, AnnArg2T, AnnArg3T], AnnResT],
    tuple[Type[AnnArg1T], Type[AnnArg2T], Type[AnnArg3T]],
]: ...
@overload
def annotation_caller(
    func: Callable[..., AnnResT],
    parm1: Type[AnnArg1T], parm2: Type[AnnArg2T], parm3: Type[AnnArg3T], parm4: Type[AnnArg4T], /,
) -> tuple[
    Callable[[AnnArg1T, AnnArg2T, AnnArg3T, AnnArg4T], AnnResT],
    tuple[Type[AnnArg1T], Type[AnnArg2T], Type[AnnArg3T], Type[AnnArg4T]],
]: ...
@overload
def annotation_caller(
    func: Callable[..., AnnResT],
    parm1: Type[AnnArg1T], parm2: Type[AnnArg2T], parm3: Type[AnnArg3T],
    parm4: Type[AnnArg4T], parm5: Type[AnnArg5T], /,
) -> tuple[
    Callable[[AnnArg1T, AnnArg2T, AnnArg3T, AnnArg4T, AnnArg5T], AnnResT],
    tuple[Type[AnnArg1T], Type[AnnArg2T], Type[AnnArg3T], Type[AnnArg4T], Type[AnnArg5T]],
]: ...
def annotation_caller(
    func: Callable[..., AnnResT], /,
    *parms: type,
) -> tuple[Callable[..., AnnResT], Tuple[type, ...]]:
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
    # Remove 'return' temporarily so we don't parse that, since we don't care.
    ann_dict = getattr(func, '__annotations__', None)
    if ann_dict is not None:
        return_val = ann_dict.pop('return', allowed_kinds)  # Sentinel
    else:
        return_val = None
    try:
        hints = typing.get_type_hints(func)
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
            raise ValueError(f'Unknown potential type {ann!r}!')
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
    for var_name, parm_typ in zip(letters, parms):
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


@functools.lru_cache(maxsize=None)
def _make_reorderer(inputs: str, outputs: str) -> Callable[[Callable], Callable]:
    """Build a function that does reordering for annotation caller.

    This allows the code objects to be cached.
    It's a closure over the function, to allow reference to the function more directly.
    This also means it can be reused for other funcs with the same order.
    """
    return eval(f'lambda func: lambda {inputs}: func({outputs})')


CallResultT = TypeVar('CallResultT')


def conv_setup_pair(
    setup: Callable[..., Any],
    result: Callable[..., CallResultT],
) -> Callable[
    [srctools.VMF, Keyvalues],
    Callable[[Entity], CallResultT]
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

    def func(vmf: srctools.VMF, kv: Keyvalues) -> Callable[[Entity], CallResultT]:
        """Replacement function which performs the legacy behaviour."""
        # The old system for setup functions - smuggle them in by
        # setting Keyvalues.value to an arbitrary object.
        smuggle = Keyvalues(kv.real_name, setup_wrap(vmf, kv))

        def closure(ent: Entity) -> CallResultT:
            """Use the closure to store the smuggled setup data."""
            return result_wrap(vmf, ent, smuggle)

        return closure

    func.__doc__ = result.__doc__
    return func


class CondCall(Generic[CallResultT]):
    """A result or flag callback.

    This should be called to execute it.
    """
    __slots__ = ['func', 'group', '_cback', '_setup_data']
    _setup_data: dict[int, Callable[[Entity], CallResultT]] | None

    def __init__(
        self,
        func: Callable[..., CallResultT | Callable[[Entity], CallResultT]],
        group: str,
    ):
        self.func = func
        self.group = group
        cback, arg_order = annotation_caller(
            func,
            srctools.VMF, collisions.Collisions, MapInfo, Entity, Keyvalues,
        )
        self._cback: Callable[
            [srctools.VMF, collisions.Collisions, MapInfo, Entity, Keyvalues],
            CallResultT | Callable[[Entity], CallResultT],
        ] = cback
        if Entity not in arg_order:
            # We have setup functions.
            self._setup_data = {}
        else:
            self._setup_data = None

    @property
    def __doc__(self) -> str:  # type: ignore  # object.__doc__ is not a Keyvalues.
        return self.func.__doc__

    def __call__(self, coll: collisions.Collisions, info: MapInfo, ent: Entity, conf: Keyvalues) -> CallResultT:
        """Execute the callback."""
        if self._setup_data is None:
            return self._cback(ent.map, coll, info, ent, conf)  # type: ignore
        else:
            # Execute setup functions if required.
            try:
                cback = self._setup_data[id(conf)]
            except KeyError:
                # The entity should never be used in setup functions. Pass a dummy object
                # so errors occur if it's used.
                cback = self._setup_data[id(conf)] = self._cback(  # type: ignore
                    ent.map, coll, info,
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


def _get_cond_group(func: Any) -> str:
    """Get the condition group hint for a function."""
    try:
        return func.__globals__['COND_MOD_NAME']
    except KeyError:
        group = func.__globals__['__name__']
        LOGGER.warning('No name for module "{}"!', group)
        return group


def add_meta(func: Callable[..., object], priority: Decimal | int, only_once=True) -> None:
    """Add a metacondition, which executes a function at a priority level.

    Used to allow users to allow adding conditions before or after a
    transformation like the adding of quotes.
    """
    dec_priority = Decimal(priority)
    # This adds a condition result like "func" (with quotes), which cannot
    # be entered into keyvalues files.
    # The qualified name will be unique across modules.
    name = f'"{func.__qualname__}"'
    LOGGER.debug(
        "Adding metacondition ({}) with priority {!s}!",
        name,
        dec_priority,
    )

    # We don't care about setup functions for this.
    RESULT_LOOKUP[name] = wrapper = CondCall(func, _get_cond_group(func))

    cond = Condition(
        results=[Keyvalues(name, '')],
        priority=dec_priority,
        source='MetaCondition {}'.format(name)
    )

    if only_once:
        cond.results.append(
            Keyvalues('endCondition', '')
        )
    conditions.append(cond)
    ALL_META.append((name, dec_priority, wrapper))


def meta_cond(priority: int | Decimal=0, only_once: bool=True) -> Callable[[CallableT], CallableT]:
    """Decorator version of add_meta."""
    def x(func: CallableT) -> CallableT:
        add_meta(func, priority, only_once)
        return func
    return x


def make_flag(orig_name: str, *aliases: str) -> Callable[[CallableT], CallableT]:
    """Decorator to add flags to the lookup."""
    def x(func: CallableT) -> CallableT:
        wrapper: CondCall[bool] = CondCall(func, _get_cond_group(func))
        ALL_FLAGS.append((orig_name, aliases, wrapper))
        name = orig_name.casefold()
        if name in FLAG_LOOKUP:
            raise ValueError(f'Flag {orig_name} is a duplicate!')
        FLAG_LOOKUP[orig_name.casefold()] = wrapper
        for name in aliases:
            if name.casefold() in FLAG_LOOKUP:
                raise ValueError(f'Flag {orig_name} is a duplicate!')
            FLAG_LOOKUP[name.casefold()] = wrapper
        return func
    return x


def make_result(orig_name: str, *aliases: str) -> Callable[[CallableT], CallableT]:
    """Decorator to add results to the lookup."""
    folded_name = orig_name.casefold()
    # Discard the original name from aliases, if it's also there.
    aliases = tuple([
        name for name in aliases
        if name.casefold() != folded_name
    ])

    def x(result_func: CallableT) -> CallableT:
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
            func = conv_setup_pair(setup_func, result_func)

        wrapper: CondCall[object] = CondCall(func, _get_cond_group(result_func))
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
    return x


def make_result_setup(*names: str) -> Callable[[CallableT], CallableT]:
    """Legacy setup function for results. This is no longer used."""
    # Users can't do anything about this, don't bother them.
    if utils.DEV_MODE:
        warnings.warn('Use closure system instead.', DeprecationWarning, stacklevel=2)

    def x(func: CallableT) -> CallableT:
        for name in names:
            if name.casefold() in RESULT_LOOKUP:
                raise ValueError('Legacy setup called after making result!')
            RESULT_SETUP[name.casefold()] = func
        return func
    return x


def add(kv_block: Keyvalues) -> None:
    """Parse and add a condition to the list."""
    con = Condition.parse(kv_block, toplevel=True)
    if con.results or con.else_results:
        conditions.append(con)


def check_all(vmf: VMF, coll: collisions.Collisions, info: MapInfo) -> None:
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
                    condition.test(coll, info, inst)
                except NextInstance:
                    # NextInstance is raised to immediately stop running
                    # this condition, and skip to the next instance.
                    continue
                except Unsatisfiable:
                    # Unsatisfiable indicates this condition's flags will
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

    LOGGER.info('---------------------')
    LOGGER.info(
        'Conditions executed, {}/{} ({:.0%}) skipped!',
        skipped_cond, len(conditions),
        skipped_cond/len(conditions),
    )
    import vbsp
    LOGGER.info('Map has attributes: {}', [
        key
        for key, value in
        vbsp.settings['has_attr'].items()
        if value
    ])
    # '' is always present, which sorts first, conveniently adding a \n at the start.
    LOGGER.debug('All instances referenced:{}', '\n'.join(sorted(ALL_INST)))
    # Dynamically added by lru_cache()
    # noinspection PyUnresolvedReferences
    LOGGER.info('instanceLocs cache: {}', instanceLocs.resolve_cache_info())
    LOGGER.info('Style Vars: {}', dict(vbsp.settings['style_vars']))
    LOGGER.info('Global instances: {}', GLOBAL_INSTANCES)


def check_flag(
    flag: Keyvalues,
    coll: collisions.Collisions, info: MapInfo,
    inst: Entity, can_skip: bool = False,
) -> bool:
    """Determine the result for a condition flag.

    If can_skip is true, flags raising Unsatifiable will pass the exception through.
    """
    name = flag.name
    # If starting with '!', invert the result.
    if name[:1] == '!':
        desired_result = False
        can_skip = False  # This doesn't work.
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

    try:
        res = func(coll, info, inst, flag)
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
    # Find the modules in the conditions package.
    for module in pkgutil.iter_modules(__path__, 'precomp.conditions.'):
        # Import the module, then discard it. The module will run add_flag
        # or add_result() functions, which save the functions into our dicts.
        # We don't need a reference to the modules themselves.
        LOGGER.debug('Importing {} ...', module.name)
        importlib.import_module(module.name)
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
        file.write(f'#### `{flag_key}` ({priority}):\n\n')
        dump_func_docs(file, func)
        file.write('\n')

    all_cond_types: list[tuple[list[tuple[str, tuple[str, ...], CondCall]], str]] = [
        (ALL_FLAGS, 'Flags'),
        (ALL_RESULTS, 'Results'),
    ]
    for lookup, name in all_cond_types:
        print('<!------->', file=file)
        print(f'# {name}', file=file)
        print('<!------->', file=file)

        lookup_grouped: dict[str, list[
            tuple[str, tuple[str, ...], CondCall]
        ]] = defaultdict(list)

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
                print(f'### {group}\n', file=file)

            LOGGER.info('Doing {} group...', group)

            for flag_key, aliases, func in funcs:
                print(f'#### `{flag_key}`:\n', file=file)
                if aliases:
                    print(f'**Aliases:** `{"`, `".join(aliases)}`  \n', file=file)
                dump_func_docs(file, func)
                file.write('\n')


def dump_func_docs(file: TextIO, func: Callable):
    import inspect
    docs = inspect.getdoc(func)
    if docs:
        print(docs, file=file)
    else:
        print('**No documentation!**', file=file)


def add_inst(
    vmf: VMF,
    *,
    file: str,
    origin: Vec | str,
    angles: Angle | Matrix | str = '0 0 0',
    targetname: str='',
    fixup_style: int | str = '0',  # Default to Prefix.
    no_fixup: bool = False,
) -> Entity:
    """Create and add a new instance at the specified position.

    This provides defaults for parameters, and adds the filename to ALL_INST.
    Values accept str in addition so they can be copied from existing keyvalues.

    If no_fixup is set, it overrides fixup_style to None - this way it's a more clear
    parameter for code.
    """
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


def local_name(inst: Entity, name: str | Entity) -> str:
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


def widen_fizz_brush(brush: Solid, thickness: float, bounds: tuple[Vec, Vec]=None):
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
    ent: typing.MutableMapping[str, str],
    inst: Entity,
    kv_block: Keyvalues,
    block_name: str='Keys',
) -> None:
    """Copy the given key prop block to an entity.

    This uses the keys and 'localkeys' properties on the kv_block.
    Values with $fixup variables will be treated appropriately.
    LocalKeys keys will be changed to use instance-local names, where needed.
    block_name lets you change the 'keys' suffix on the kv_block name.
    ent can be any mapping.
    """
    for kv in kv_block.find_block(block_name, or_blank=True):
        ent[kv.real_name] = resolve_value(inst, kv.value)
    for kv in kv_block.find_block('Local' + block_name, or_blank=True):
        if kv.value.startswith('$'):
            val = inst.fixup[kv.value]
        else:
            val = kv.value
        if val.startswith('@'):
            ent[kv.real_name] = val
        else:
            ent[kv.real_name] = local_name(inst, val)

T = TypeVar('T')


def resolve_value(inst: Entity, value: str | T) -> str | T:
    """If a value contains '$', lookup the associated var.

    Non-string values are passed through unchanged.
    If it starts with '!$', invert boolean values.
    """
    if not isinstance(value, str):
        return value

    return inst.fixup.substitute(value, allow_invert=True)


def resolve_offset(inst, value: str, scale: float=1, zoff: float=0) -> Vec:
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


@make_flag('debug')
@make_result('debug')
def debug_flag(inst: Entity, kv: Keyvalues) -> bool:
    """Displays text when executed, for debugging conditions.

    If the text ends with an '=', the instance will also be displayed.
    As a flag, this always evaluates as true.
    """
    # Mark as a warning, so it's more easily seen.
    if kv.has_children():
        LOGGER.warning('Debug:\n{!s}\n{!s}', kv, inst)
    else:
        LOGGER.warning('Debug: {props}{inst!s}'.format(
            inst=inst,
            props=kv.value,
        ))
    return True  # The flag is always true


@make_result('dummy', 'nop', 'do_nothing')
def dummy_result(inst: Entity, kv: Keyvalues):
    """Dummy result that doesn't do anything."""
    pass


@meta_cond(priority=1000, only_once=False)
def remove_blank_inst(inst: Entity) -> None:
    """Remove instances with a blank file keyvalue.

    This allows conditions to strip the instances when requested.
    """
    # If editoritems instances are set to "", PeTI will autocorrect it to
    # ".vmf" - we need to handle that too.
    if inst['file', ''] in ('', '.vmf'):
        inst.remove()


@make_result('timedRelay')
def res_timed_relay(vmf: VMF, res: Keyvalues) -> Callable[[Entity], None]:
    """Generate a logic_relay with outputs delayed by a certain amount.

    This allows triggering outputs based $timer_delay values.
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


@make_result('condition')
def res_sub_condition(coll: collisions.Collisions, info: MapInfo, res: Keyvalues) -> ResultCallable:
    """Check a different condition if the outer block is true."""
    cond = Condition.parse(res, toplevel=False)

    def test_cond(inst: Entity) -> None:
        """For child conditions, we need to check every time."""
        try:
            cond.test(coll, info, inst)
        except Unsatisfiable:
            pass
    return test_cond


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


@make_result('switch')
def res_switch(coll: collisions.Collisions, info: MapInfo, res: Keyvalues) -> ResultCallable:
    """Run the same flag multiple times with different arguments.

    `method` is the way the search is done - `first`, `last`, `random`, or `all`.
    `flag` is the name of the flag.
    `seed` sets the randomisation seed for this block, for the random mode.
    Each keyvalues group is a case to check - the Keyvalues name is the flag
    argument, and the contents are the results to execute in that case.
    The special group `"<default>"` is only run if no other flag is valid.
    For `random` mode, you can omit the flag to choose from all objects. In
    this case the flag arguments are ignored.
    """
    flag_name = ''
    method = SWITCH_TYPE.FIRST
    raw_cases: list[Keyvalues] = []
    default: list[Keyvalues] = []
    rand_seed = ''
    for kv in res:
        if kv.has_children():
            if kv.name == '<default>':
                default.extend(kv)
            else:
                raw_cases.append(kv)
        else:
            if kv.name == 'flag':
                flag_name = kv.value
                continue
            if kv.name == 'method':
                try:
                    method = SWITCH_TYPE(kv.value.casefold())
                except ValueError:
                    pass
            elif kv.name == 'seed':
                rand_seed = kv.value

    if method is SWITCH_TYPE.LAST:
        raw_cases.reverse()

    conf_cases: list[tuple[Keyvalues, list[Keyvalues]]] = [
        (Keyvalues(flag_name, case.real_name), list(case))
        for case in raw_cases
    ]

    def apply_switch(inst: Entity) -> None:
        """Execute a switch."""
        if method is SWITCH_TYPE.RANDOM:
            cases = conf_cases.copy()
            rand.seed(b'switch', rand_seed, inst).shuffle(cases)
        else:  # Won't change.
            cases = conf_cases

        run_default = True
        for flag, results in cases:
            # If not set, always succeed for the random situation.
            if flag.real_name and not check_flag(flag, coll, info, inst):
                continue
            for sub_res in results:
                Condition.test_result(coll, info, inst, sub_res)
            run_default = False
            if method is not SWITCH_TYPE.ALL:
                # All does them all, otherwise we quit now.
                break
        if run_default:
            for sub_res in default:
                Condition.test_result(coll, info, inst, sub_res)
    return apply_switch


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
            name: instanceLocs.resolve_one(
                '<{}:bee2_{}{}>'.format(from_item, prefix, name),
                error=False,
            ) for name in inst_keys
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
