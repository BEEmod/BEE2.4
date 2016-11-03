"""Take a VMF file with special entities, and generate the exporting section
of editoritems.
"""
import sys
import webbrowser

from srctools import Property, Vec, VMF, Entity
import utils

LOGGER = utils.init_logging('../logs/editoritems_gen.log')


def make_connections(props, vmf: VMF):
    embed_voxel = Property('ConnectionPoints', [])


def make_embeddedvoxel(props, vmf: VMF):
    embed_voxel = Property('EmbeddedVoxels', [])



def main(filename):
    output = filename[:-3] + 'editor.txt'

    vmf = VMF.parse(filename)

    exp_props = Property('Exporting', [])
    props = Property('Item', [exp_props])

    for name, func in globals():
        if name.startswith('make_'):
            LOGGER.info('Generating "{}"', name[5:])
            func(exp_props, vmf)

    with open(output, 'w') as f:
        for line in props.export():
            f.write(line)

if __name__ == '__main__':
    main(sys.argv[-1])