"""Take a VMF file with special entities, and generate the exporting section
of editoritems.
"""
import sys

from srctools import Property, Vec, VMF
import utils

LOGGER = utils.init_logging('../logs/editoritems_gen.log')

CONNECTION_OFFSETS = {
    # Skin -> antline offset.
    '1': Vec(-0.5, +0.5),
    '2': Vec(-0.5, -0.5),
    '3': Vec(+0.5, +0.5),
    '4': Vec(+0.5, -0.5),
}


def make_connections(props, vmf: VMF):
    """Generate ConnectionPoints blocks, the data for antlines."""
    # Note - ConnectionPoints has an inverted Y compared to the game.

    conn_points = Property('ConnectionPoints', [])
    for ent in vmf.by_class['bee2_editor_connectionpoint']:
        prop = Property('Point', [])
        conn_points.append(prop)
        norm = Vec(x=1).rotate_by_str(ent['angles'])
        norm.y = - norm.y
        prop['Dir'] = str(norm)

        origin = (Vec.from_str(ent['origin']) - (-64, 64, 0)) // 16 + Vec(-0.5, 0.5, 0)
        origin.z = 0
        origin.y = -origin.y

        try:
            offset = CONNECTION_OFFSETS[ent['skin', '1']].copy()
        except KeyError:
            offset = CONNECTION_OFFSETS['1'].copy()
        offset.rotate_by_str(ent['angles'])

        offset.z = 0
        offset.y = -offset.y

        prop['Pos'] = str(origin + offset)
        prop['SignageOffset'] = str(origin - offset)

        prop['Priority'] = ent['priority', '0']
        group_id = ent['group_id']
        if group_id:
            prop['GroupID'] = group_id

    if conn_points:
        props.append(conn_points)


def make_embeddedvoxel(props, vmf: VMF):
    """Generate the embeddedvoxel blocks."""
    embed_voxel = Property('EmbeddedVoxels', [])


def main(filename):
    output = filename[:-3] + 'editor.txt'

    vmf = VMF.parse(filename)

    exp_props = Property('Exporting', [])
    props = Property('Item', [exp_props])

    for name, func in globals().items():
        if name.startswith('make_'):
            LOGGER.info('Generating "{}"', name[5:])
            func(exp_props, vmf)

    with open(output, 'w') as f:
        for line in props.export():
            f.write(line)

if __name__ == '__main__':
    main(sys.argv[-1])