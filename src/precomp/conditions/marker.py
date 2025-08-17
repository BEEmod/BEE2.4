"""Conditions that read/write a set of positional markers."""
from __future__ import annotations

import attrs
from srctools import Keyvalues, Entity, Vec, Matrix, VMF
import srctools.logger

from precomp import conditions
from precomp.lazy_value import LazyValue


COND_MOD_NAME = 'Markers'
# TODO: switch to R-tree etc.
MARKERS: list[Marker] = []
LOGGER = srctools.logger.get_logger(__name__)


@attrs.define
class Marker:
    """A marker placed in the map."""
    pos: Vec
    name: str
    inst: Entity = attrs.field(kw_only=True)
    # If dev mode is enabled, the info_target/_null to identify this.
    debug_ent: Entity = attrs.field(kw_only=True)


@conditions.make_result('SetMarker')
def res_set_marker(vmf: VMF, res: Keyvalues) -> conditions.ResultCallable:
    """Set a marker at a specific position.

    Parameters:
    * `global`: If true, the position is an absolute position, ignoring this instance.
    * `name`: A name to store to identify this marker/item.
    * `pos`: The absolute position or local offset from the instance to use for the marker.
    """
    is_global = LazyValue.parse(res['global', '0']).as_bool(False)
    conf_name = LazyValue.parse(res['name']).casefold()
    conf_pos = LazyValue.parse(res['pos']).as_vec()

    add_debug = conditions.fetch_debug_visgroup(vmf, 'Markers')

    def create(inst: Entity) -> None:
        """Create the marker."""
        origin = Vec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])

        name = conf_name(inst)
        pos = conf_pos(inst)
        if not is_global(inst):
            pos = pos @ orient + origin

        debug_ent = add_debug(
            'info_target',
            origin=pos,
            targetname=name,
            comment='Marker not used',
        )

        mark = Marker(pos, name, inst=inst, debug_ent=debug_ent)
        MARKERS.append(mark)
        LOGGER.debug('Marker added: {}', mark)

    return create


@conditions.make_test('CheckMarker')
def check_marker(vmf: VMF, inst: Entity, kv: Keyvalues) -> bool:
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

    name = inst.fixup.substitute(kv['name']).casefold()
    if '*' in name:
        try:
            prefix, suffix = name.split('*')
        except ValueError:
            raise ValueError(f'Name "{name}" must only have 1 *!') from None

        def match(val: str) -> bool:
            """Match a prefix or suffix."""
            val = val.casefold()
            return val.startswith(prefix) and val.endswith(suffix)
    else:
        def match(val: str) -> bool:
            """Match an exact name."""
            return val.casefold() == name

    try:
        is_global = srctools.conv_bool(inst.fixup.substitute(kv['global'], allow_invert=True))
    except LookupError:
        is_global = False

    pos = Vec.from_str(inst.fixup.substitute(kv['pos']))
    if not is_global:
        pos = pos @ orient + origin

    debug_ent = conditions.fetch_debug_visgroup(vmf, 'Markers')(
        'path_track',
        origin=pos,
        targetname=name,
        found='No',
    )

    radius: float | None
    if 'pos2' in kv:
        if 'radius' in kv:
            raise ValueError('Only one of pos2 or radius must be defined.')
        pos2 = Vec.from_str(inst.fixup.substitute(kv['pos2']))
        if not is_global:
            pos2 = pos2 @ orient + origin
        bb_min, bb_max = Vec.bbox(pos, pos2)
        radius = None
        debug_ent['classname'] = 'trigger_once'
        debug_ent.solids.append(vmf.make_prism(bb_min, bb_max, 'tools/toolstrigger').solid)
        LOGGER.debug('Searching for marker "{}" from ({})-({})', name, bb_min, bb_max)
    elif 'radius' in kv:
        radius = abs(srctools.conv_float(inst.fixup.substitute(kv['radius'])))
        bb_min = pos - (radius + 1.0)
        bb_max = pos + (radius + 1.0)
        debug_ent['radius'] = radius
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
        debug_ent['found'] = marker.pos
        debug_ent['target'] = marker.name
        debug_ent['parentname'] = marker.inst['targetname']
        debug_ent.comments = 'Next = marker name, parent = marker instance'
        marker.debug_ent.comments = 'Marker used'
        # Matched.
        if 'nameVar' in kv:
            inst.fixup[kv['namevar']] = marker.name
        if srctools.conv_bool(inst.fixup.substitute(kv['removeFound'], allow_invert=True)):
            LOGGER.debug('Removing found marker {}', marker)
            marker.debug_ent['classname'] = 'info_null'
            del MARKERS[i]

        for child in kv.find_all('copyto'):
            src, dest = child.value.split(' ', 1)
            marker.inst.fixup[dest] = inst.fixup[src]
        for child in kv.find_all('copyfrom'):
            src, dest = child.value.split(' ', 1)
            inst.fixup[dest] = marker.inst.fixup[src]
        return True
    return False
