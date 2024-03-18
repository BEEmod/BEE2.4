"""If enabled, export collisions into a VScript file."""
from collections import defaultdict
from io import StringIO

from srctools import Vec, conv_int
import srctools.logger
from srctools.math import format_float

from collisions import CollideType
from hammeraddons.bsp_transform import Context, trans


LOGGER = srctools.logger.get_logger(__name__)


@trans('BEE2: Write VScript collision data')
def write_vscript_collisions(ctx: Context) -> None:
    """If enabled, export collisions into a VScript file."""
    if conv_int(ctx.vmf.spawn['bee2_vscript_coll_mask']) == 0:
        return

    mask_to_volumes = defaultdict(list)

    for ent in ctx.vmf.by_class['bee2_vscript_collision']:
        coll_type = CollideType(conv_int(ent['contents']))
        mask_to_volumes[coll_type].append(ent)
        ent.remove()

    code = StringIO()
    code.write('IncludeScript("BEE2/collisions");\nVOLUMES <- [\n')

    for coll_type, ents in mask_to_volumes.items():

        code.write(f'\tEntry({coll_type.value}, [ // {coll_type.name}\n')
        for ent in ents:
            mins = Vec.from_str(ent['mins'])
            maxes = Vec.from_str(ent['maxs'])
            code.write(f'\t\tVolume({mins.join()}, {maxes.join()}, ')

            planes = [
                v
                for k, v in ent.items()
                if k.startswith('plane')
            ]
            if planes:
                code.write('[\n')
                for plane_str in planes:
                    try:
                        parts = plane_str.split()
                        x = float(parts[0])
                        y = float(parts[1])
                        z = float(parts[2])
                        dist = float(parts[3])
                    except ValueError as exc:
                        raise ValueError(
                            f'Invalid plane value "{plane_str}" in collision '
                            f'entity @ {ent["origin"]}'
                        ) from exc
                    code.write(
                        f'\t\t\tPlane({format_float(x)}, {format_float(y)}, '
                        f'{format_float(z)}, {format_float(dist)}),\n'
                    )
                code.write('\t\t]),\n')
            else:
                code.write('null),\n')
        code.write('\t]),\n')
    code.write(']\n')

    script = ctx.vmf.create_ent(
        'logic_script',
        targetname='@collision_script',
        origin='0 0 0',
    )
    ctx.add_code(script, code.getvalue())
