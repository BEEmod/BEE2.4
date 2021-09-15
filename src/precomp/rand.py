"""Handles randomising values in a repeatable way."""
from __future__ import annotations
from random import Random
from struct import Struct
import hashlib

from precomp import instanceLocs
from srctools import VMF, Vec, Angle, Entity, logger, Matrix


# A hash object which we seed using the map layout, so it is somewhat unique.
# This should be copied to use for specific purposes, never modified.
MAP_HASH = hashlib.sha256()
THREE_FLOATS = Struct('<3f')
NINE_FLOATS = Struct('<9e')  # Half-precision float, don't need the accuracy.
THREE_INTS = Struct('<3i')
LOGGER = logger.get_logger(__name__)


def init_seed(vmf: VMF) -> str:
    """Seed with the map layout.

    We use the position of the ambient light instances, which is unique to any
    given layout, but small changes won't change since only every 4th grid pos
    is relevant.
    """
    amb_light = instanceLocs.resolve_one('<ITEM_POINT_LIGHT>', error=True)
    light_names = []
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() == amb_light:
            pos = Vec.from_str(inst['origin']) / 64
            light_names.append(THREE_INTS.pack(round(pos.x), round(pos.y), round(pos.z)))
    light_names.sort()  # Ensure consistent order!
    for name in light_names:
        MAP_HASH.update(name)

    return b'|'.join(light_names).decode()  # TODO Remove


def seed(name: bytes, *values: str | Entity | Vec | Angle | int | float | bytes | bytearray) -> Random:
    """Initialise a random number generator with these starting arguments.

    The name is used to make this unique among other calls, then the arguments
    are hashed in.
    """
    algo = MAP_HASH.copy()
    algo.update(name)
    for val in values:
        if isinstance(val, str):
            algo.update(val.encode('utf8'))
        elif isinstance(val, (Vec, Angle)):
            a, b, c = val
            algo.update(THREE_FLOATS.pack(round(a, 6), round(b, 6), round(c, 6)))
        elif isinstance(val, Matrix):
            algo.update(NINE_FLOATS.pack(
                val[0, 0], val[0, 1], val[0, 2],
                val[1, 0], val[1, 1], val[1, 2],
                val[2, 0], val[2, 1], val[2, 2],
            ))
        elif isinstance(val, Entity):
            algo.update(val['targetname'].encode('ascii', 'replace'))
            x, y, z = round(Vec.from_str(val['origin']), 6)
            algo.update(THREE_FLOATS.pack(x, y, z))
            p, y, r = Vec.from_str(val['origin'])
            algo.update(THREE_FLOATS.pack(round(p, 6), round(y, 6), round(r, 6)))
        else:
            algo.update(val)
    return Random(int.from_bytes(algo.digest(), 'little'))
