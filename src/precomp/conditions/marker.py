"""Conditions that read/write a set of positional markers."""
from __future__ import annotations

import attrs
from srctools import Keyvalues, Entity, Vec, Matrix, VMF
import srctools.logger

from precomp import conditions, connections
from precomp.lazy_value import LazyValue


COND_MOD_NAME = 'Markers'
# TODO: switch to R-tree etc.
MARKERS: list[Marker] = []
LOGGER = srctools.logger.get_logger(__name__)

ENT_MARKERS: dict[Entity,list[Marker]] = {}


@attrs.define
class Marker:
    """A marker placed in the map."""
    pos: Vec
    name: str
    inst: Entity = attrs.field(kw_only=True)
    # If dev mode is enabled, the info_target/_null to identify this.
    debug_ent: Entity = attrs.field(kw_only=True)
    
    def remove(self) -> None:
        self.debug_ent['classname'] = 'info_null'
        MARKERS.remove(self)
        ENT_MARKERS[self.inst].remove(self)


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
        ENT_MARKERS[inst] = [mark] if inst not in ENT_MARKERS else ENT_MARKERS[inst].append(mark)
        LOGGER.debug('Marker added: {}', mark)

    return create

#Perhaps this should use a regex
def name_matcher(name: str) -> Callable[[str],bool]:
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
    return match

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
    match = name_matcher(name)

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
            marker.remove()

        for child in kv.find_all('copyto'):
            src, dest = child.value.split(' ', 1)
            marker.inst.fixup[dest] = inst.fixup[src]
        for child in kv.find_all('copyfrom'):
            src, dest = child.value.split(' ', 1)
            inst.fixup[dest] = marker.inst.fixup[src]
        return True
    return False

def check_io(inst: Entity, kv: Keyvalues, input: bool) -> bool:
    """Called by check_inputs and check_outputs"""
    marker_name = (kv['marker'] if kv.has_children() else kv.value).casefold()
    match = name_matcher(marker_name)
    conns = connections.ITEMS[inst['targetname']]
    
    def match_inst(ent: Entity) -> None | Marker:
        if ent not in ENT_MARKERS:
            return None
        for marker in ENT_MARKERS[ent]:
            if match(marker.name):
                return marker
        return None
    
    for conn in list(conns.inputs if input else conns.outputs):
        targ_item = conn.from_item if input else conn.to_item
        if (marker := match_inst(targ_item.inst)) is None:
            continue
        if not kv.has_children():
            return True
        if kv.bool('removeConnection',False):
            conn.remove()
        if kv.bool('removeMarker',False):
            ENT_MARKERS[targ_item.inst].remove(marker)
        for child in kv.find_all('copyto'):
            src, dest = child.value.split(' ', 1)
            targ_item.inst.fixup[dest] = inst.fixup[src]
        for child in kv.find_all('copyfrom'):
            src, dest = child.value.split(' ', 1)
            inst.fixup[dest] = targ_item.inst.fixup[src]
        return True
    return False

@conditions.make_test('OutputsTo',valid_before=conditions.MetaCond.LinkedItems)
def check_outputs(inst: Entity, kv: Keyvalues) -> bool:
    """Check if this instance outputs to an instance with the specified marker. 
    
    The value should be the name of a marker, or a block of options:
    * `marker`: The name of the marker that was set by an item this item outputs to.
    * `removeConnection`: If true, removes the connection. Defaults to false. 
    * `removeMarker`: If true, remove the found marker. If you don't need it, this will improve
      performance. Defaults to false. 
    * `copyto`: Copies fixup vars from the searching instance to the output instance. The value is in the form `$src $dest`.
    * `copyfrom`: Copies fixup vars from the output instance to the searching instance.
      The value is in the form `$src $dest`.
    """
    return check_io(inst, kv, input = False)

@conditions.make_test('InputsFrom',valid_before=conditions.MetaCond.LinkedItems)
def check_inputs(inst: Entity, kv: Keyvalues) -> bool:
    """Check if this instance takes inputs from an instance with the specified marker. 
    
    The value should be the name of a marker, or a block of options:
    * `marker`: The name of the marker that was set by an item that outputs to this item.
    * `removeConnection`: If true, removes the connection. Defaults to false. 
    * `removeMarker`: If true, remove the found marker. If you don't need it, this will improve
      performance. Defaults to false. 
    * `copyto`: Copies fixup vars from the searching instance to the input instance. The value is in the form `$src $dest`.
    * `copyfrom`: Copies fixup vars from the input instance to the searching instance.
      The value is in the form `$src $dest`.
    """
    return check_io(inst, kv, input = True)