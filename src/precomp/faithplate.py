"""Implement Faith Plates and allow customising trigger sizes/shapes.

This also handles Bomb-type Paint Droppers.
"""
import collections

from precomp import tiling, brushLoc, instanceLocs, template_brush, conditions
from srctools import Entity, Vec, VMF
from srctools.logger import get_logger

from typing import Dict, Optional, List, Tuple, Union


LOGGER = get_logger(__name__)

# Targetname -> plate.
PLATES: Dict[str, Union['AngledPlate', 'StraightPlate', 'PaintDropper']] = {}


class FaithPlate:
    """A Faith Plate."""
    VISGROUP: str = ''  # Visgroup name for the generated trigger.
    def __init__(
        self,
        inst: Entity,
        trig: Entity,
    ) -> None:
        self.inst = inst
        self.trig = trig
        self.trig_offset = Vec()
        self.template: Optional[template_brush.Template] = None

    @property
    def name(self) -> str:
        """Return the targetname of the item."""
        return self.inst['targetname']

    @name.setter
    def name(self, value: str) -> None:
        """Set the targetname of the item."""
        self.inst['targetname'] = value

    def __repr__(self) -> str:
        return f'<{type(self).__name__} "{self.name}">'


class AngledPlate(FaithPlate):
    """A faith plate with an angled trajectory."""
    VISGROUP = 'angled'

    def __init__(
        self,
        inst: Entity,
        trig: Entity,
        target: Union[Vec, tiling.TileDef],
    ) -> None:
        super().__init__(inst, trig)
        self.target = target


class StraightPlate(FaithPlate):
    """A faith plate with a straight trajectory."""
    VISGROUP = 'straight'

    def __init__(
        self,
        inst: Entity,
        trig: Entity,
        helper_trig: Entity,
    ) -> None:
        super().__init__(inst, trig)
        self.helper_trig = helper_trig


class PaintDropper(FaithPlate):
    """A special case - bomb-type Paint Droppers use this to aim the bomb."""
    VISGROUP = 'paintdrop'

    def __init__(
        self,
        inst: Entity,
        trig: Entity,
        target: Union[Vec, tiling.TileDef],
    ) -> None:
        super().__init__(inst, trig)
        self.target = target


@conditions.meta_cond(-900)
def associate_faith_plates(vmf: VMF) -> None:
    """Parse through the map, collecting all faithplate segments.

    Tiling, instancelocs and connections must have been parsed first.
    Once complete all targets have been removed.

    This is done as a meta-condition to allow placing tiles we will attach to.
    """

    # Find all the triggers and targets first.
    triggers: Dict[str, Entity] = {}
    helper_trigs: Dict[str, Entity] = {}
    paint_trigs: Dict[str, Entity] = {}

    for trig in vmf.by_class['trigger_catapult']:
        name = trig['targetname']
        # Conveniently, we can determine what sort of catapult was made by
        # examining the local name used.
        if name.endswith('-helperTrigger'):
            helper_trigs[name[:-14]] = trig
            # Also store None in the main trigger if no key is there,
            # so we can detect missing main triggers...
            triggers.setdefault(name[:-14], None)
        elif name.endswith('-trigger'):
            triggers[name[:-8]] = trig
            # Remove the original relay inputs. We need to keep the output
            # to the helper if necessary.
            trig.outputs[:] = [
                out
                for out in
                trig.outputs
                if not out.inst_in
            ]
        elif name.endswith('-catapult'):
            # Paint droppers.
            paint_trigs[name[:-9]] = trig
        else:
            LOGGER.warning('Unknown trigger "{}"?', name)

    target_to_pos: Dict[str, Union[Vec, tiling.TileDef]] = {}

    for targ in vmf.by_class['info_target']:
        name = targ['targetname']
        # All should be faith targets, with this name.
        if not name.endswith('-target'):
            LOGGER.warning('Unknown info_target "{}" @ {}?', name, targ['origin'])
            continue
        name = name[:-7]

        # Find the tile we're attached to. Unfortunately no angles, so we
        # have to try both directions.
        origin = Vec.from_str(targ['origin'])

        # If the plate isn't on a tile (placed on goo for example),
        # use the direct position.
        tile = Vec.from_str(targ['origin'])

        grid_pos: Vec = origin // 128 * 128 + 64
        norm = (origin - grid_pos).norm()

        # If we're on the floor above the top of goo, move down to the surface.
        block_type = brushLoc.POS['world': tile - (0, 0, 64)]
        if block_type.is_goo and block_type.is_top:
            tile.z -= 32

        for norm in [norm, -norm]:
            # Try both directions.
            try:
                tile = tiling.TILES[
                    (origin - 64 * norm).as_tuple(),
                    norm.as_tuple(),
                ]
                break
            except KeyError:
                pass

        # We don't need the entity anymore, we'll regenerate them later.
        targ.remove()
        target_to_pos[name] = tile

    # Loop over instances, recording plates and moving targets into the tiledefs.
    instances: Dict[str, Entity] = {}

    faith_targ_file = instanceLocs.resolve('<ITEM_CATAPULT_TARGET>')
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() in faith_targ_file:
            inst.remove()  # Don't keep the targets.
            origin = Vec.from_str(inst['origin'])
            norm = Vec(z=1).rotate_by_str(inst['angles'])
            try:
                tile = tiling.TILES[(origin - 128 * norm).as_tuple(), norm.as_tuple()]
            except KeyError:
                LOGGER.warning('No tile for bullseye at {}!', origin - 64 * norm)
                continue
            tile.bullseye_count += 1
            tile.add_portal_helper()
        else:
            instances[inst['targetname']] = inst

    # Now, combine into plate objects for each.
    for name, trig in triggers.items():
        if trig is None:
            raise ValueError(
                f'Faith plate {name} has a helper '
                'trigger but no main trigger!'
            )
        try:
            pos = target_to_pos[name]
        except KeyError:
            # No position, it's a straight plate.
            PLATES[name] = StraightPlate(instances[name], trig, helper_trigs[name])
        else:
            # Target position, angled plate.
            PLATES[name] = AngledPlate(instances[name], trig, pos)

    # And paint droppers
    for name, trig in paint_trigs.items():
        try:
            pos = target_to_pos[name]
        except KeyError:
            LOGGER.warning('No target for paint dropper {}!', name)
            continue
        # Target position, angled plate.
        PLATES[name] = PaintDropper(instances[name], trig, pos)


def gen_faithplates(vmf: VMF) -> None:
    """Place the targets and catapults into the map."""
    # Target positions -> list of triggers wanting to aim there.
    pos_to_trigs: Dict[
        Union[Tuple[float, float, float], tiling.TileDef],
        List[Entity]
    ] = collections.defaultdict(list)

    for plate in PLATES.values():
        if isinstance(plate, (AngledPlate, PaintDropper)):
            if isinstance(plate.target, tiling.TileDef):
                targ_pos = plate.target  # Use the ID directly.
            else:
                targ_pos = plate.target.as_tuple()
            pos_to_trigs[targ_pos].append(plate.trig)

        if isinstance(plate, StraightPlate):
            trigs = [plate.trig, plate.helper_trig]
        else:
            trigs = [plate.trig]

        for trig in trigs:
            trig_origin = trig.get_origin()
            if plate.template is not None:
                trig.solids = template_brush.import_template(
                    vmf,
                    plate.template,
                    trig_origin + plate.trig_offset,
                    Vec.from_str(plate.inst['angles']),
                    force_type=template_brush.TEMP_TYPES.world,
                    add_to_map=False,
                ).world
            elif plate.trig_offset:
                for solid in trig.solids:
                    solid.translate(plate.trig_offset)

    # Now, generate each target needed.
    for pos_or_tile, trigs in pos_to_trigs.items():
        target = vmf.create_ent(
            'info_target',
            angles='0 0 0',
            spawnflags='3',  # Transmit to PVS and always transmit.
        )

        if isinstance(pos_or_tile, tiling.TileDef):
            pos_or_tile.position_bullseye(target)
        else:
            # Static target.
            target['origin'] = Vec(pos_or_tile)

        target.make_unique('faith_target')

        for trig in trigs:
            trig['launchTarget'] = target['targetname']
