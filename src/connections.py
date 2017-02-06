"""Manages PeTI item connections."""
from enum import Enum
from collections import defaultdict
from srctools import VMF, Entity, Output
import instanceLocs
import conditions
import instance_traits

from typing import Iterable, Dict, List, Set


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 0  # Normal / unconfigured input
    # Becomes one of the others based on item preference.

    PRIMARY = TBEAM_IO = 1  # A Type, 'normal'
    SECONDARY = TBEAM_DIR = 2  # B Type, 'alt'

    BOTH = 3  # Trigger both simultaneously.


# Instance -> outputs from it.
OUTPUTS = defaultdict(set)  # type: Dict[Entity, Set[Connection]]
# Instance -> inputs to it.
INPUTS = defaultdict(set)  # type: Dict[Entity, Set[Connection]]
# instance -> Antline
ANTLINES = {}  # type: Dict[Entity, Antline]


class Connection:
    """Represents an item connection."""

    def __init__(
        self,
        in_inst: Entity,   # Instance this is triggering
        out_inst: Entity,  # Instance this comes from
        conn_type=ConnType.DEFAULT,
        timer_count: int=None,
        outputs: Iterable[Output]=(),
    ):
        self.in_inst = in_inst
        self.out_inst = out_inst
        self.type = conn_type
        self.timer_count = timer_count
        self.outputs = list(outputs)

    def add(self):
        """Add this to the directories."""
        OUTPUTS[self.in_inst].add(self)
        INPUTS[self.out_inst].add(self)

    def remove(self):
        """Remove this from the directories."""
        OUTPUTS[self.in_inst].discard(self)
        INPUTS[self.out_inst].discard(self)


class Antline:
    """Represents the antlines coming from an item."""
    def __init__(
        self,
        toggle: Entity=None,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Entity]=(),
        timer_count: int=None,
    ):
        self.ind_panels = list(panels)
        self.ind_toggle = toggle
        self.antlines = list(antlines)
        # None = checkmark
        self.timer_count = timer_count


def calc_connections(vmf: VMF):
    """Compute item connections from the map file.

    This also fixes cases where items have incorrect checkmark/timer signs.
    Instance Traits must have been calculated.
    """
    # First we want to match targetnames to item types.
    items = {}  # type: Dict[str, Entity]
    toggles = {}  # type: Dict[str, Entity]
    overlays = defaultdict(list)  # type: Dict[str, List[Entity]]
    panels = {}  # type: Dict[str, Entity]

    panel_timer = instanceLocs.resolve_one('[indPanTimer]', error=True)
    panel_check = instanceLocs.resolve_one('[indPanCheck]', error=True)

    tbeam_polarity = {
        conditions.TBEAM_CONN_ACT,
        conditions.TBEAM_CONN_DEACT,
    }
    tbeam_io = conditions.CONNECTIONS['item_tbeam']
    tbeam_io = {tbeam_io.in_act, tbeam_io.in_deact}

    for inst in vmf.by_class['func_instance']:
        if not inst['targetname']:
            continue
        filename = inst['file'].casefold()

        traits = instance_traits.get(inst)

        if 'toggle' in traits:
            inst_dict = toggles
        elif 'antline' in traits:
            inst_dict = panels
        else:
            inst_dict = items

        inst_dict[inst['targetname']] = inst

    for over in vmf.by_class['info_overlay']:
        overlays[over['targetname']].append(over)

    # Now build the connections.
    for inst in items.values():
        if not inst.outputs:
            # No outputs..
            continue

        inst_toggle = None
        inst_panels = []
        inst_overlays = []
        input_items = []  # Instances we trigger
        inputs = defaultdict(list)  # type: Dict[str, List[Output]]
        for out in inst.outputs:
            inputs[out.target].append(out)

        for out_name in inputs:
            # Fizzler base -> model outputs, skip.
            if out_name.endswith(('_modelStart', '_modelEnd')):
                continue

            if out_name in toggles:
                inst_toggle = toggles[out_name]
                inst_overlays = overlays[inst_toggle.fixup['indicator_name']]
            elif out_name in panels:
                inst_panels.append(panels[out_name])
            else:
                try:
                    input_items.append(items[out_name])
                except KeyError:
                    raise ValueError('"{}" is not a known instance!'.format(out_name))

        timer_delay = inst.fixup.int('timer_delay', -1)
        if 0 <= timer_delay <= 30:
            desired_panel_inst = panel_timer
        else:
            desired_panel_inst = panel_check
            timer_delay = None

        # Check/cross instances sometimes don't match the kind of timer delay.
        for pan in inst_panels:
            pan['file'] = desired_panel_inst

        antline = Antline(
            inst_toggle,
            inst_panels,
            inst_overlays,
            timer_delay
        )
        ANTLINES[inst] = antline

        for inp_inst in input_items:
            # Default A/B type.
            conn_type = ConnType.DEFAULT
            in_outputs = inputs[inp_inst['targetname']]

            if 'tbeam_emitter' in instance_traits.get(inp_inst):
                # It's a funnel - we need to figure out if this is polarity,
                # or normal on/off.
                for out in in_outputs:  # type: Output
                    input_tuple = (out.inst_in, out.input)
                    if input_tuple in tbeam_polarity:
                        conn_type = ConnType.TBEAM_DIR
                        break
                    elif input_tuple in tbeam_io:
                        conn_type = ConnType.TBEAM_IO
                        break
                else:
                    raise ValueError(
                        'Tbeam "{}" has inputs, but no valid types!'.format(
                            inp_inst['targetname']
                        )
                    )

            conn = Connection(
                inp_inst,
                inst,
                conn_type,
                timer_delay,
                in_outputs,
            )
            conn.add()
