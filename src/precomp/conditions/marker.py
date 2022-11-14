"""Conditions that read/write a set of positional markers."""
from __future__ import annotations

import attrs
from srctools import Keyvalues, Entity, Vec, Matrix
import srctools.logger

from precomp.conditions import make_flag, make_result

COND_MOD_NAME = 'Markers'
# TODO: switch to R-tree etc.
MARKERS: list[Marker] = []
LOGGER = srctools.logger.get_logger(__name__)


@attrs.define
class Marker:
    """A marker placed in the map."""
    pos: Vec
    name: str
    inst: Entity


@make_result('SetMarker')
def res_set_marker(inst: Entity, res: Keyvalues) -> None:
    """Set a marker at a specific position.

    Parameters:
        * `global`: If true, the position is an absolute position, ignoring this instance.
        * `name`: A name to store to identify this marker/item.
        * `pos`: The position or offset to use for the marker.
    """
    origin = Vec.from_str(inst['origin'])
    orient = Matrix.from_angstr(inst['angles'])

    try:
        is_global = srctools.conv_bool(inst.fixup.substitute(res['global'], allow_invert=True))
    except LookupError:
        is_global = False

    name = inst.fixup.substitute(res['name']).casefold()
    pos = Vec.from_str(inst.fixup.substitute(res['pos']))
    if not is_global:
        pos = pos @ orient + origin

    mark = Marker(pos, name, inst)
    MARKERS.append(mark)
    LOGGER.debug('Marker added: {}', mark)


@make_flag('CheckMarker')
def flag_check_marker(inst: Entity, flag: Keyvalues) -> bool:
    """Check if markers are present at a position.

    Parameters:
        * `name`: The name to look for. This can contain one `*` to match prefixes/suffixes.
        * `nameVar`: If found, set this variable to the actual name.
        * `pos`: The position to check.
        * `pos2`: If specified, the position is a bounding box from 1 to 2.
        * `radius`: Check markers within this distance. If this is specified, `pos2` is not permitted.
        * `global`: If true, positions are an absolute position, ignoring this instance.
        * `removeFound`: If true, remove the found marker. If you don't need it, this will improve
          performance.
        * `copyto`: Copies fixup vars from the searching instance to the one which set the
          marker. The value is in the form `$src $dest`.
        * `copyfrom`: Copies fixup vars from the one that set the marker to the searching instance.
          The value is in the form `$src $dest`.
    """
    origin = Vec.from_str(inst['origin'])
    orient = Matrix.from_angstr(inst['angles'])

    name = inst.fixup.substitute(flag['name']).casefold()
    if '*' in name:
        try:
            prefix, suffix = name.split('*')
        except ValueError:
            raise ValueError(f'Name "{name}" must only have 1 *!')

        def match(val: str) -> bool:
            """Match a prefix or suffix."""
            val = val.casefold()
            return val.startswith(prefix) and val.endswith(suffix)
    else:
        def match(val: str) -> bool:
            """Match an exact name."""
            return val.casefold() == name

    try:
        is_global = srctools.conv_bool(inst.fixup.substitute(flag['global'], allow_invert=True))
    except LookupError:
        is_global = False

    pos = Vec.from_str(inst.fixup.substitute(flag['pos']))
    if not is_global:
        pos = pos @ orient + origin

    radius: float | None
    if 'pos2' in flag:
        if 'radius' in flag:
            raise ValueError('Only one of pos2 or radius must be defined.')
        pos2 = Vec.from_str(inst.fixup.substitute(flag['pos2']))
        if not is_global:
            pos2 = pos2 @ orient + origin
        bb_min, bb_max = Vec.bbox(pos, pos2)
        radius = None
        LOGGER.debug('Searching for marker "{}" from ({})-({})', name, bb_min, bb_max)
    elif 'radius' in flag:
        radius = abs(srctools.conv_float(inst.fixup.substitute(flag['radius'])))
        bb_min = pos - (radius + 1.0)
        bb_max = pos + (radius + 1.0)
        LOGGER.debug('Searching for marker "{}" at ({}), radius={}', name, pos, radius)
    else:
        bb_min = pos - (1.0, 1.0, 1.0)
        bb_max = pos + (1.0, 1.0, 1.0)
        radius = 1e-6
        LOGGER.debug('Searching for marker "{}" at ({})', name, pos)

    for i, marker in enumerate(MARKERS):
        if not marker.pos.in_bbox(bb_min, bb_max):
            continue
        if radius is not None and (marker.pos - pos).mag() > radius:
            continue
        if not match(marker.name):
            continue
        # Matched.
        if 'nameVar' in flag:
            inst.fixup[flag['namevar']] = marker.name
        if srctools.conv_bool(inst.fixup.substitute(flag['removeFound'], allow_invert=True)):
            LOGGER.debug('Removing found marker {}', marker)
            del MARKERS[i]

        for prop in flag.find_all('copyto'):
            src, dest = prop.value.split(' ', 1)
            marker.inst.fixup[dest] = inst.fixup[src]
        for prop in flag.find_all('copyfrom'):
            src, dest = prop.value.split(' ', 1)
            inst.fixup[dest] = marker.inst.fixup[src]
        return True
    return False
