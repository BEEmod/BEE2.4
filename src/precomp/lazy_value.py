"""A value read from configs, which defers applying fixups until later."""
from __future__ import annotations

from typing import Callable, ClassVar, Generic, Optional, TypeVar
from typing_extensions import override

import abc
import operator

from srctools import Entity, conv_int, conv_float, conv_bool, Vec, Angle, Matrix

__all__ = ['LazyValue']


U_co = TypeVar("U_co", covariant=True)
V_co = TypeVar("V_co", covariant=True)
W_co = TypeVar("W_co", covariant=True)
U = TypeVar("U")
V = TypeVar("V")

MutTypes = (Vec, Angle, Matrix)


class LazyValue(abc.ABC, Generic[U_co]):
    """A base value."""
    # If true, this may depend on inst.
    has_fixups: ClassVar[bool] = True

    def __call__(self, inst: Entity) -> U_co:
        """Resolve the value by substituting from the instance, if required."""
        result = self._resolve(inst)
        if isinstance(result, MutTypes):
            return result.copy()  # type: ignore  # Needs result = U & MutTypes
        return result

    def __repr__(self) -> str:
        return f'<Value: {self._repr_val()}>'

    @classmethod
    def parse(cls, value: str, default: Optional[str] = None, allow_invert: bool = True) -> LazyValue[str]:
        """Starting point, read a config value."""
        if '$' in value:
            return InstValue(value, default, allow_invert)
        else:
            return ConstValue(value)

    @classmethod
    def make(cls, value: U | LazyValue[U]) -> LazyValue[U]:
        """Make a value lazy. If it's already a LazyValue, just return it.

        Otherwise, treat as a constant and wrap it.
        """
        if isinstance(value, LazyValue):
            return value
        else:
            return ConstValue(value)

    @abc.abstractmethod
    def _repr_val(self) -> str:
        """Return the repr() for the computation, for the overall repr()."""
        raise NotImplementedError

    @abc.abstractmethod
    def _resolve(self, inst: Entity) -> U_co:
        """Resolve the value by substituting from the instance, if required."""
        raise NotImplementedError

    def map(self, func: Callable[[U_co], V], name: str = '') -> LazyValue[V]:
        """Map this map."""
        return UnaryMapValue(self, func, name)

    def as_int(self: LazyValue[str], default: int = 0) -> LazyValue[int]:
        """Call conv_int()."""
        return self.map(lambda x: conv_int(x, default), 'conv_int')

    def as_float(self: LazyValue[str], default: float = 0.0) -> LazyValue[float]:
        """Call conv_float()."""
        return self.map(lambda x: conv_float(x, default), 'conv_float')

    def as_bool(self: LazyValue[str], default: bool = False) -> LazyValue[bool]:
        """Call conv_bool()."""
        return self.map(lambda x: conv_bool(x, default), 'conv_bool')

    def as_vec(self: LazyValue[str], x: float = 0.0, y: float = 0.0, z: float = 0.0) -> LazyValue[Vec]:
        """Call Vec.from_str()."""
        return self.map(lambda val: Vec.from_str(val, x, y, z), 'Vec')

    def as_angle(self: LazyValue[str], pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0) -> LazyValue[Angle]:
        """Call Angle.from_str()."""
        return self.map(lambda val: Angle.from_str(val, pitch, yaw, roll), 'Angle')

    def as_matrix(self: LazyValue[str]) -> LazyValue[Matrix]:
        """Call Matrix.from_angstr()."""
        return self.map(Matrix.from_angstr, 'Matrix')

    def casefold(self: LazyValue[str]) -> LazyValue[str]:
        """Call str.casefold()."""
        return self.map(str.casefold, 'str.casefold')

    def __invert__(self: LazyValue[bool]) -> LazyValue[bool]:
        """Invert a boolean."""
        return self.map(operator.not_, 'not')

    def __matmul__(
        self: LazyValue[Vec],
        other: LazyValue[Angle] | LazyValue[Matrix] | Angle | Matrix,
    ) -> LazyValue[Vec]:
        """Rotate a vector by an angle."""
        return BinaryMapValue(self, LazyValue.make(other), operator.matmul, '@')

    def as_offset(
        self: LazyValue[str],
        scale: float | LazyValue[float] = 1,
        zoff: float | LazyValue[float] = 0,
    ) -> LazyValue[Vec]:
        """Call resolve_offset()."""
        return OffsetValue(self, scale, zoff)


class ConstValue(LazyValue[U_co], Generic[U_co]):
    """A value which is known."""
    has_fixups: ClassVar[bool] = False

    value: U_co

    def __init__(self, value: U_co) -> None:
        self.value = value

    @override
    def _repr_val(self) -> str:
        return repr(self.value)

    @override
    def _resolve(self, inst: Entity) -> U_co:
        """No resolution is required."""
        return self.value

    @override
    def map(self, func: Callable[[U_co], V], name: str = '') -> LazyValue[V]:
        """Apply a function."""
        return ConstValue(func(self.value))


class UnaryMapValue(LazyValue[V_co], Generic[U_co, V_co]):
    """Maps an existing value to another."""
    def __init__(self, parent: LazyValue[U_co], func: Callable[[U_co], V_co], name: str) -> None:
        self.parent = parent
        self.func = func
        self.name = name or getattr(func, '__name__', repr(func))

    @override
    def _repr_val(self) -> str:
        return f'{self.name}({self.parent._repr_val()})'

    @override
    def _resolve(self, inst: Entity) -> V_co:
        """Resolve the parent, then call the function."""
        return self.func(self.parent._resolve(inst))


class BinaryMapValue(LazyValue[W_co], Generic[U_co, V_co, W_co]):
    """Maps two existing values to another."""
    def __init__(
        self,
        a: LazyValue[U_co], b: LazyValue[V_co],
        func: Callable[[U_co, V_co], W_co], name: str,
    ) -> None:
        self.a = a
        self.b = b
        self.func = func
        self.name = name or getattr(func, '__name__', repr(func))

    @override
    def _repr_val(self) -> str:
        return f'{self.name}({self.a._repr_val(), self.b._repr_val()})'

    @override
    def _resolve(self, inst: Entity) -> W_co:
        """Resolve the parents, then call the function."""
        return self.func(self.a._resolve(inst), self.b._resolve(inst))


class InstValue(LazyValue[str]):
    """A value which will be resolved from an instance."""
    variable: str
    default: Optional[str]
    allow_invert: bool

    def __init__(
        self,
        variable: str,
        default: Optional[str] = None,
        allow_invert: bool = True,
    ) -> None:
        self.variable = variable
        self.default = default
        self.allow_invert = allow_invert

    @override
    def _repr_val(self) -> str:
        """The operation to perform."""
        return f'${self.variable!r}'

    @override
    def _resolve(self, inst: Entity) -> str:
        """Resolve the parent, then call the function."""
        return inst.fixup.substitute(self.variable, self.default, allow_invert=self.allow_invert)


class OffsetValue(LazyValue[Vec]):
    """A wrapper around resolve_offset()."""
    parent: LazyValue[str]
    scale: LazyValue[float]
    zoff: LazyValue[float]

    def __init__(
        self,
        parent: LazyValue[str],
        scale: float | LazyValue[float],
        zoff: float | LazyValue[float],
    ) -> None:
        self.parent = parent
        self.scale = LazyValue.make(scale)
        self.zoff = LazyValue.make(zoff)

    @override
    def _repr_val(self) -> str:
        return f'resolve_offset({self.parent._repr_val()})'

    @override
    def _resolve(self, inst: Entity) -> Vec:
        """Localise this offset."""
        from .conditions import resolve_offset
        return resolve_offset(inst, self.parent(inst), self.scale(inst), self.zoff(inst))
