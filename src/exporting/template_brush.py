"""Write the compressed list of templates to the game folder."""
import os

import trio.to_thread
from srctools import AtomicWriter
from srctools.dmx import Attribute as DMXAttr, Element as DMXElement, ValueType as DMXValue

from exporting import STEPS
import packages


@STEPS.add_step(prereq=[], results=[])
async def step_write_templates(exp_data: packages.ExportData) -> None:
    """Write out the location of all templates for the compiler to use."""
    root = DMXElement('Templates', 'DMERoot')
    template_list = root['temp'] = DMXAttr.array('list', DMXValue.ELEMENT)

    for temp_id, path in exp_data.packset.templates.items():
        pack_path = packages.PACKAGE_SYS[path.package].path
        temp_el = DMXElement(temp_id, 'DMETemplate')
        temp_el['package'] = os.path.abspath(pack_path).replace('\\', '/')
        temp_el['path'] = path.path
        template_list.append(temp_el)

    def write_file() -> None:
        """Write the file out."""
        with AtomicWriter(exp_data.game.abs_path('bin/bee2/templates.lst'), is_bytes=True) as f:
            root.export_binary(f, fmt_name='bee_templates', unicode='format')

    await trio.to_thread.run_sync(write_file)
