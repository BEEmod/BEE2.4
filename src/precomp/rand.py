"""Handles randomising values in a repeatable way."""
from __future__ import annotations
from random import Random
from struct import Struct
import hashlib

from srctools import (
    VMF, Angle, Entity, FrozenAngle, FrozenMatrix, FrozenVec, Matrix, Vec,
    logger,
)

from precomp import instanceLocs


# A hash object which we seed using the map layout, so it is unique.
# This should be copied to use for specific purposes, never modified.
MAP_HASH = hashlib.sha256()
ONE_FLOAT = Struct('f')
ONE_INT = Struct('<i')
THREE_FLOATS = Struct('<3f')
NINE_FLOATS = Struct('<9e')  # Half-precision float, don't need the accuracy.
THREE_INTS = Struct('<3i')
LOGGER = logger.get_logger(__name__)


def parse_weights(count: int, weights: str) -> list[int]:
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
        LOGGER.warning('Failed parsing weight: {!r} for {} items', weights, count)
        weight = list(range(count))
    # random.choice(weight) will now give an index with the correct
    # probabilities.
    return weight


def init_seed(vmf: VMF) -> None:
    """Seed with the map layout.

    We use the position of the ambient light instances, which is unique to any
    given layout, but small changes won't change since only every 4th grid pos
    is relevant.
    """
    amb_light = instanceLocs.resolve_one('<ITEM_POINT_LIGHT>', error=True)
    light_names: list[bytes] = []
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() == amb_light:
            pos = Vec.from_str(inst['origin']) / 64
            light_names.append(THREE_INTS.pack(round(pos.x), round(pos.y), round(pos.z)))
    light_names.sort()  # Ensure consistent order!
    for name in light_names:
        MAP_HASH.update(name)
    LOGGER.debug('Map random seed: {}', MAP_HASH.hexdigest())


def seed(
    name: bytes,
    *values: str | Entity | float | bytes | bytearray |
        Vec | FrozenVec | Angle | FrozenAngle | Matrix | FrozenMatrix,
) -> Random:
    """Initialise a random number generator with these starting arguments.

    The name is used to make this unique among other calls, then the arguments
    are hashed in.
    """
    algo = MAP_HASH.copy()
    algo.update(name)
    for val in values:
        match val:
            case str():
                algo.update(val.encode('utf8'))
            case Vec() | FrozenVec() | Angle() | FrozenAngle():
                a, b, c = val
                algo.update(THREE_FLOATS.pack(round(a, 6), round(b, 6), round(c, 6)))
            case float():
                algo.update(ONE_FLOAT.pack(val))
            case int():
                # If multi-digit, hashing puts it back into valid range.
                algo.update(ONE_INT.pack(hash(val)))
            case Matrix() | FrozenMatrix():
                algo.update(NINE_FLOATS.pack(
                    val[0, 0], val[0, 1], val[0, 2],
                    val[1, 0], val[1, 1], val[1, 2],
                    val[2, 0], val[2, 1], val[2, 2],
                ))
            case Entity():
                algo.update(val['targetname'].encode('ascii', 'replace'))
                x, y, z = round(Vec.from_str(val['origin']), 6)
                algo.update(THREE_FLOATS.pack(x, y, z))
                p, y, r = Vec.from_str(val['origin'])
                algo.update(THREE_FLOATS.pack(round(p, 6), round(y, 6), round(r, 6)))
            case _:
                try:
                    algo.update(val)
                except TypeError as exc:
                    raise TypeError(values) from exc
    return Random(int.from_bytes(algo.digest(), 'little'))
