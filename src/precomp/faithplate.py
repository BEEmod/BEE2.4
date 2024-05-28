"""Implement Faith Plates and allow customising trigger sizes/shapes.

This also handles Bomb-type Paint Droppers.
"""
from __future__ import annotations
from typing import ClassVar
import collections

import attrs
from srctools import Entity, FrozenVec, Matrix, Vec, VMF, Angle, conv_float, logger

from precomp import tiling, brushLoc, instanceLocs, template_brush, conditions


COND_MOD_NAME: str | None = None
LOGGER = logger.get_logger(__name__)

# Targetname -> plate.
# Spell out the union to allow type narrowing.
PLATES: dict[str, AngledPlate | StraightPlate | PaintDropper] = {}


@attrs.define(kw_only=True, repr=False)
class FaithPlate:
    """A Faith Plate."""
    VISGROUP: ClassVar[str] = ''  # Visgroup name for the generated trigger.
    inst: Entity
    trig: Entity
    # The target to use. It's only absent for straight plates on the floor.
    target: Vec | tiling.TileDef | None

    trig_offset: Vec = attrs.field(init=False, factory=Vec().copy)
    template: template_brush.Template | None = attrs.field(init=False, default=None)

    @property
    def name(self) -> str:
        """Return the targetname of the item."""
        return self.inst['targetname']

    @name.setter
    def name(self, value: str) -> None:
        """Set the targetname of the item."""
        self.inst['targetname'] = value

    def __repr__(self) -> str:
        return f'<{type(self).__name__} "{vars(self)}">'


@attrs.define(kw_only=True)
class AngledPlate(FaithPlate):
    """A faith plate with an angled trajectory."""
    VISGROUP: ClassVar[str] = 'angled'


@attrs.define(kw_only=True)
class StraightPlate(FaithPlate):
    """A faith plate with a straight trajectory."""
    VISGROUP: ClassVar[str] = 'straight'
    helper_trig: Entity


@attrs.define(kw_only=True)
class PaintDropper(FaithPlate):
    """A special case - bomb-type Paint Droppers use this to aim the bomb."""
    VISGROUP: ClassVar[str] = 'paintdrop'


@conditions.MetaCond.FaithPlate.register
def associate_faith_plates(vmf: VMF) -> None:
    """Parse through the map, collecting all faithplate segments.

    Tiling, instancelocs and connections must have been parsed first.
    Once complete all targets have been removed.

    This is done as a meta-condition to allow placing tiles we will attach to.
    """

    # Find all the triggers and targets first.
    triggers: dict[str, Entity | None] = {}
    helper_trigs: dict[str, Entity] = {}
    paint_trigs: dict[str, Entity] = {}

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

    target_to_pos: dict[str, Vec | tiling.TileDef] = {}

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
        tile_pos = Vec.from_str(targ['origin'])

        grid_pos: Vec = origin // 128 * 128 + 64
        abs_norm = (origin - grid_pos).norm()

        # If we're on the floor above the top of goo, move down to the surface.
        block_type = brushLoc.POS.lookup_world(tile_pos - (0, 0, 64))
        if block_type.is_goo and block_type.is_top:
            tile_pos.z -= 32

        tile_or_pos: Vec | tiling.TileDef = tile_pos
        for norm in [abs_norm, -abs_norm]:
            # Try both directions.
            try:
                tile_or_pos = tiling.TILES[
                    (origin - 64 * norm).as_tuple(),
                    norm.as_tuple(),
                ]
                break
            except KeyError:
                pass

        # We don't need the entity any more, we'll regenerate them later.
        targ.remove()
        target_to_pos[name] = tile_or_pos

    # Loop over instances, recording plates and moving targets into the tiledefs.
    instances: dict[str, Entity] = {}

    faith_targ_files = instanceLocs.resolve_filter('<ITEM_CATAPULT_TARGET>')
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() in faith_targ_files:
            inst.remove()  # Don't keep the targets.
            origin = Vec.from_str(inst['origin'])
            norm = Vec(z=1) @ Angle.from_str(inst['angles'])
            try:
                tdef = tiling.TILES[(origin - 128 * norm).as_tuple(), norm.as_tuple()]
            except KeyError:
                LOGGER.warning('No tile for bullseye at {}!', origin - 64 * norm)
                continue
            tdef.bullseye_count += 1
            tdef.add_portal_helper()
        else:
            instances[inst['targetname']] = inst

    # Now, combine into plate objects for each.
    for name, trig in triggers.items():
        if trig is None:
            raise ValueError(
                f'Faith plate {name} has a helper '
                'trigger but no main trigger!'
            )
        # Angled plates must have a target, and never have a helper trig.
        # Straight plates have a helper trig, and might also have a target
        # if mounted to the ceiling.
        try:
            helper_trig = helper_trigs[name]
        except KeyError:
            pass
        else:
            PLATES[name] = StraightPlate(
                inst=instances[name],
                trig=trig,
                helper_trig=helper_trig,
                target=target_to_pos.get(name),
            )
            continue
        try:
            pos = target_to_pos[name]
        except KeyError:
            LOGGER.warning('Faith plate "{}" has no position or helper trig?')
        else:
            PLATES[name] = AngledPlate(
                inst=instances[name],
                trig=trig,
                target=pos,
            )

    # And paint droppers
    for name, trig in paint_trigs.items():
        try:
            pos = target_to_pos[name]
        except KeyError:
            LOGGER.warning('No target for paint dropper {}!', name)
            continue
        PLATES[name] = PaintDropper(
            inst=instances[name],
            trig=trig,
            target=pos,
        )

    LOGGER.debug('Plates:\n{}', '\n'.join([
        f'- {plate!r}' for plate in PLATES.values()
    ]))


def gen_faithplates(vmf: VMF, has_superpos: bool) -> None:
    """Place the targets and catapults into the map."""
    # Target positions -> list of triggers wanting to aim there.
    pos_to_trigs: dict[
        FrozenVec | tiling.TileDef,
        list[Entity]
    ] = collections.defaultdict(list)

    for plate in PLATES.values():
        plate_orient = Matrix.from_angstr(plate.inst['angles'])

        if plate.target is not None:
            targ_pos: FrozenVec | tiling.TileDef
            if isinstance(plate.target, tiling.TileDef):
                targ_pos = plate.target  # Use the ID directly.
            else:
                targ_pos = plate.target.freeze()
            # If the plate is straight, we want to aim the helper trig, not the regular one.
            # This only happens with ceiling plates.
            pos_to_trigs[targ_pos].append(
                plate.helper_trig
                if isinstance(plate, StraightPlate)
                else plate.trig
            )

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
                    plate_orient,
                    force_type=template_brush.TEMP_TYPES.world,
                    add_to_map=False,
                ).world
            elif plate.trig_offset:
                for solid in trig.solids:
                    solid.translate(plate.trig_offset)
            if has_superpos:
                trig['filtername'] = '@not_superpos_ghost_filter'
            # Safeguard - if the speed == 0, force it to be valid.
            for keyvalue in ['playerspeed', 'physicsspeed']:
                if conv_float(trig[keyvalue]) < 1.0:
                    trig[keyvalue] = 1.0

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
            target['origin'] = pos_or_tile

        target.make_unique('faith_target')

        for trig in trigs:
            trig['launchTarget'] = target['targetname']
