"""Transformations related to entity filters."""
from io import BytesIO
from typing import Dict

from hammeraddons.bsp_transform import Context, trans
import srctools.logger
from srctools.packlist import FileType


LOGGER = srctools.logger.get_logger(__name__)


# For filtering, we use this class. It stores the table of values, and then
# provides a __call__()-style method to check if an ent matches the models.

VSCRIPT_CLOSURE = b'''\
class __BEE2_CUBE_FUNC__{
\ttable = null;
\tconstructor(table) {
\t\tthis.table = table;
\t}
\tfunction _call(this2, ent) {
\t\treturn ent.GetModelName().tolower() in this.table;
\t}
}
'''


@trans('BEE2: Cube VScript Filters')
def cube_filter(ctx: Context) -> None:
    """Generate and pack scripts duplicating the filter functionality for VScript."""
    # Build it up as a binary buffer, since we don't need to do difficult
    # encoding.
    script_buffers: Dict[str, BytesIO] = {}

    for ent in ctx.vmf.by_class['bee2_cube_filter_script']:
        ent.remove()
        filename = ent['filename']
        try:
            buffer = script_buffers[filename]
        except KeyError:
            buffer = script_buffers[filename] = BytesIO()
            buffer.write(VSCRIPT_CLOSURE)

        buffer.write(ent['function'].encode() + b' <- __BEE2_CUBE_FUNC__({\n')
        for key, value in ent.items():
            if key.startswith('mdl'):
                buffer.write(b' ["%s"]=1,\n' % value.encode())
        buffer.write(b'});\n')

    LOGGER.info('Script buffers: {}', list(script_buffers))

    for filename, buffer in script_buffers.items():
        ctx.pack.pack_file(
            'scripts/vscripts/' + filename,
            FileType.VSCRIPT_SQUIRREL,
            buffer.getvalue(),
        )
