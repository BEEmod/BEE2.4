"""A value read from configs, which defers applying fixups until later."""
from __future__ import annotations

import abc
from typing import Callable, Generic, Optional, TypeVar

from srctools import Entity, conv_int, conv_float, conv_bool, Vec, Angle, Matrix

U = TypeVar("U", covariant=True)
V = TypeVar("V", covariant=True)
W = TypeVar("W")

MutTypes = (Vec, Angle, Matrix)


class Value(abc.ABC, Generic[U]):
    """A base value."""
    def __call__(self, inst: Entity) -> U:
        """Resolve the value by substituting from the instance, if required."""
        result = self._resolve(inst)
        if isinstance(result, MutTypes):
            return result.copy()  # type: ignore  # Needs result = U & MutTypes
        return result

    def __repr__(self) -> str:
        return f'<Value: {self._repr_val()}>'

    @abc.abstractmethod
    def _repr_val(self) -> str:
        """Return the repr() for the computation, for the overall repr()."""
        raise NotImplementedError

    @abc.abstractmethod
    def _resolve(self, inst: Entity) -> U:
        """Resolve the value by substituting from the instance, if required."""
        raise NotImplementedError

    @abc.abstractmethod
    def map(self, func: Callable[[U], V], name: str) -> Value[V]:
        """Apply a function."""
        raise NotImplementedError

    def as_int(self: Value[str], default: int = 0) -> Value[int]:
        """Call conv_int()."""
        return self.map(lambda x: conv_int(x, default), 'conv_int')

    def as_float(self: Value[str], default: float = 0.0) -> Value[float]:
        """Call conv_float()."""
        return self.map(lambda x: conv_float(x, default), 'conv_float')

    def as_bool(self: Value[str], default: bool = False) -> Value[bool]:
        """Call conv_bool()."""
        return self.map(lambda x: conv_bool(x, default), 'conv_bool')

    def as_vec(self: Value[str], x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Value[Vec]:
        """Call Vec.from_str()."""
        return self.map(lambda val: Vec.from_str(val, x, y, z), 'Vec')

    def as_angle(self: Value[str], pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0) -> Value[Angle]:
        """Call Angle.from_str()."""
        return self.map(lambda val: Angle.from_str(val, pitch, yaw, roll), 'Angle')

    def as_matrix(self: Value[str]) -> Value[Matrix]:
        """Call Matrix.from_angstr()."""
        return self.map(Matrix.from_angstr, 'Matrix')


class ConstValue(Value[U], Generic[U]):
    """A value which is known."""
    value: U

    def __init__(self, value: U) -> None:
        self.value = value

    def _repr_val(self) -> str:
        return repr(self.value)

    def _resolve(self, inst: Entity) -> U:
        """No resolution is required."""
        return self.value

    def map(self, func: Callable[[U], V], name: str) -> Value[V]:
        """Apply a function."""
        return ConstValue(func(self.value))


class UnaryMapValue(Value[V], Generic[U, V]):
    """Maps an existing value to another."""
    def __init__(self, parent: Value[U], func: Callable[[U], V], name: str) -> None:
        self.parent = parent
        self.func = func
        self.name = name

    def _repr_val(self) -> str:
        return f'{self.name}({self.parent._repr_val()})'

    def _resolve(self, inst: Entity) -> V:
        """Resolve the parent, then call the function."""
        return self.func(self.parent._resolve(inst))

    def map(self, func: Callable[[V], W], name: str) -> Value[W]:
        """Map this map."""
        return UnaryMapValue(self, func, name)


class InstValue(Value[str]):
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

    def _repr_val(self) -> str:
        """The operation to perform."""
        return f'${self.variable!r}'

    def _resolve(self, inst: Entity) -> str:
        """Resolve the parent, then call the function."""
        return inst.fixup.substitute(self.variable, self.default, allow_invert=self.allow_invert)

    def map(self, func: Callable[[str], V], name: str) -> Value[V]:
        """Resolve then map."""
        return UnaryMapValue(self, func, name)
