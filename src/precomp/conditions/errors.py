"""A result which causes a custom error to be raised."""
from srctools import Keyvalues, Entity, Vec
import srctools.logger

import utils
from precomp import conditions
from transtoken import TransToken
import user_errors


COND_MOD_NAME = 'errors'
LOGGER = srctools.logger.get_logger(__name__, alias='cond.errors')


@conditions.make_result('Error')
def res_user_error(inst: Entity, res: Keyvalues) -> None:
    """When executed, this causes the compilation to immediately fail with a custom message.

    This can be used when an item is configured in an incorrect manner.

    Parameters:
    * `ID`: A `package:id` pair specifying a `TransToken` in `info.txt`, containing the actual
      base message to display. HTML can be used to mark up things like specific keywords or fixups.
    * `Marker`: Each of these blocks adds a highlight for a specific location in the map.
        * `Type`: Either `voxel` (to label the whole voxel), or `point` (for a smaller location).
        * `Offset`: Specifies the position, relative to this instance.
    * `Parameters`: This allows substituting fixup values into the message. In this block, each
      key is a name which should match a `{field}` in the original message. The value is then
      substituted for that field, if present. These values will always be HTML-escaped.
    """
    token_id = res['ID']
    try:
        tok_package, token_id = token_id.split(':', 1)
    except ValueError:
        raise ValueError('No colon in token ID "{}"!', token_id) from None
    package_id = utils.obj_id(tok_package)

    points: list[Vec] = []
    voxels: list[Vec] = []

    for kv in res.find_all('Marker'):
        mark_type = kv['type', 'point'].casefold()
        pos = conditions.resolve_offset(inst, kv['offset'])
        if mark_type == 'voxel':
            # Round to middle of the grid.
            voxels.append((pos // 128.0) * 128.0 + 64.0)
        else:
            points.append(pos)

    params: dict[str, str] = {
        kv.real_name: inst.fixup.substitute(kv.value)
        for kv in res.find_children('Parameters')
    }

    raise user_errors.UserError(
        TransToken(package_id, package_id, token_id, params),
        voxels=voxels, points=points,
    )
