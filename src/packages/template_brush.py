import math
from typing import Iterator, Tuple, List

import srctools.logger
from packages import (
    PakObject, ParseData, get_config,
    ExportData,
)
from srctools import VMF, Vec, Solid

LOGGER = srctools.logger.get_logger(__name__)

# Don't change face IDs when copying to here.
# This allows users to refer to the stuff in templates specifically.
# The combined VMF isn't to be compiled or edited outside of us, so it's fine
# to have overlapping IDs between templates.
TEMPLATE_FILE = VMF(preserve_ids=True)


class BrushTemplate(PakObject, allow_mult=True):
    """A template brush which will be copied into the map, then retextured.

    This allows the sides of the brush to swap between wall/floor textures
    based on orientation.
    All world and detail brushes from the given VMF will be copied.
    """
    # For scaling templates, maps normals to the prefix to use in the ent.
    NORMAL_TO_NAME = {
        (0, 0, 1): 'up',
        (0, 0, -1): 'dn',
        (0, 1, 0): 'n',
        (0, -1, 0): 's',
        (1, 0, 0): 'e',
        (-1, 0, 0): 'w',
    }

    def __init__(
        self,
        temp_id: str,
        vmf_file: VMF,
        force: str=None,
        keep_brushes: bool=True,
    ) -> None:
        """Import in a BrushTemplate object.

        This copies the solids out of VMF_FILE and into TEMPLATE_FILE.
        If force is set to 'world' or 'detail', the other type will be converted.
        If keep_brushes is false brushes will be skipped (for TemplateOverlay).
        """
        self.id = temp_id
        # We don't actually store the solids here - put them in
        # the TEMPLATE_FILE VMF. That way the original VMF object can vanish.

        self.temp_world = {}
        self.temp_detail = {}

        visgroup_names = {
            vis.id: vis.name
            for vis in
            vmf_file.vis_tree
        }

        # For each template, give them a visgroup to match - that
        # makes it easier to swap between them.
        temp_visgroup_id = TEMPLATE_FILE.create_visgroup(temp_id).id

        if force.casefold() == 'detail':
            force_is_detail = True
        elif force.casefold() == 'world':
            force_is_detail = False
        else:
            force_is_detail = None

        # If we don't have anything warn people.
        has_conf_data = False

        # Parse through a config entity in the template file.
        conf_ents = list(vmf_file.by_class['bee2_template_conf'])
        if len(conf_ents) > 1:
            raise ValueError(
                'Template "{}" has multiple configuration entities!'.format(temp_id)
            )
        elif len(conf_ents) == 1:
            config = conf_ents[0]
            config_id = config['template_id']
            if config_id and temp_id:
                if config['template_id'].casefold() != temp_id.casefold():
                    raise ValueError('VMF and info.txt have different ids:\n conf = {}, info.txt = {}'.format(
                        config['template_id'],
                        temp_id,
                    ))
            # Override passed ID with the one in the VMF.
            elif config_id and not temp_id:
                self.id = temp_id = config_id
            elif not config_id:
                LOGGER.warning('"{}" has no conf ID!', temp_id)
            conf_auto_visgroup = int(srctools.conv_bool(config['detail_auto_visgroup']))
            if srctools.conv_bool(config['discard_brushes']):
                keep_brushes = False
            is_scaling = srctools.conv_bool(config['is_scaling'])
            if config['temp_type'] == 'detail':
                force_is_detail = True
            elif config['temp_type'] == 'world':
                force_is_detail = False
            # Add to the exported map as well.
            export_config = config.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
            # Remove the configs we've parsed
            for key in (
                'temp_type',
                'is_scaling',
                'discard_brushes',
                'template_id',
                'detail_auto_visgroup',
                # Not used, but might be added by Hammer.
                'origin',
                'angles',
            ):
                del export_config[key]
            # Only add if it has useful settings, and we're not a scaling
            # template.
            if export_config.keys and not is_scaling:
                TEMPLATE_FILE.add_ent(export_config)
                export_config['template_id'] = temp_id

        else:
            conf_auto_visgroup = is_scaling = False
            if not temp_id:
                raise ValueError('No template ID passed in!')
            LOGGER.warning('Template "{}" has no config entity! In a future version this will be required.', temp_id)

        if is_scaling:
            # Make a scaling template config.
            scaling_conf = TEMPLATE_FILE.create_ent(
                classname='bee2_template_scaling',
                template_id=temp_id,
            )
            scale_brush = None
            for brushes, is_detail, vis_ids in self.yield_world_detail(vmf_file):
                for brush in brushes:
                    if scale_brush is None:
                        scale_brush = brush
                    else:
                        raise ValueError(
                            'Too many brushes in scaling '
                            'template "{}"!'.format(temp_id),
                        )
            if scale_brush is None:
                raise ValueError(
                    'No brushes in scaling template "{}"!'.format(temp_id)
                )
            has_conf_data = True

            for face in scale_brush:
                try:
                    prefix = BrushTemplate.NORMAL_TO_NAME[face.normal().as_tuple()]
                except KeyError:
                    raise ValueError(
                        'Non Axis-Aligned face in '
                        'scaling template "{}"!'.format(temp_id),
                    )
                scaling_conf[prefix + '_tex'] = face.mat
                scaling_conf[prefix + '_uaxis'] = face.uaxis
                scaling_conf[prefix + '_vaxis'] = face.vaxis
                scaling_conf[prefix + '_rotation'] = face.ham_rot

        elif keep_brushes:
            for brushes, is_detail, vis_ids in self.yield_world_detail(vmf_file):
                has_conf_data = True
                if force_is_detail is not None:
                    export_detail = force_is_detail
                else:
                    export_detail = is_detail
                visgroups = [
                    visgroup_names[vis_id]
                    for vis_id in
                    vis_ids
                ]
                if len(visgroups) > 1:
                    raise ValueError(
                        'Template "{}" has brush with two '
                        'visgroups! ({})'.format(temp_id, ', '.join(visgroups))
                    )
                # No visgroup = ''
                visgroup = visgroups[0] if visgroups else ''

                # Auto-visgroup puts func_detail ents in unique visgroups.
                if is_detail and not visgroup and conf_auto_visgroup:
                    visgroup = '__auto_group_{}__'.format(conf_auto_visgroup)
                    # Reuse as the unique index, >0 are True too..
                    conf_auto_visgroup += 1

                targ_dict = self.temp_detail if export_detail else self.temp_world
                try:
                    ent = targ_dict[temp_id, visgroup, export_detail]
                except KeyError:
                    ent = targ_dict[temp_id, visgroup, export_detail] = TEMPLATE_FILE.create_ent(
                        classname=(
                            'bee2_template_detail' if
                            export_detail
                            else 'bee2_template_world'
                        ),
                        template_id=temp_id,
                        visgroup=visgroup,
                    )
                ent.visgroup_ids.add(temp_visgroup_id)
                for brush in brushes:
                    ent.solids.append(
                        brush.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
                    )

        self.temp_overlays = []

        # Transfer these configuration ents over.
        conf_classes = (
            vmf_file.by_class['bee2_template_colorpicker'] |
            vmf_file.by_class['bee2_template_tilesetter']
        )
        for conf_ent in conf_classes:
            new_ent = conf_ent.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
            new_ent['template_id'] = temp_id
            new_ent['visgroups'] = ' '.join([
                visgroup_names[vis_id]
                for vis_id in
                conf_ent.visgroup_ids
            ])

            TEMPLATE_FILE.add_ent(new_ent)
            has_conf_data = True

        for overlay in vmf_file.by_class['info_overlay']:  # type: Entity
            has_conf_data = True
            visgroups = [
                visgroup_names[vis_id]
                for vis_id in
                overlay.visgroup_ids
                ]
            if len(visgroups) > 1:
                raise ValueError(
                    'Template "{}" has overlay with two '
                    'visgroups!'.format(self.id)
                )
            new_overlay = overlay.copy(
                vmf_file=TEMPLATE_FILE,
                keep_vis=False
            )
            new_overlay.visgroup_ids.add(temp_visgroup_id)
            new_overlay['template_id'] = self.id
            new_overlay['visgroup'] = visgroups[0] if visgroups else ''
            new_overlay['classname'] = 'bee2_template_overlay'
            TEMPLATE_FILE.add_ent(new_overlay)

            self.temp_overlays.append(new_overlay)

        if not has_conf_data:
            LOGGER.warning('BrushTemplate "{}" has no data!', temp_id)

    @classmethod
    def parse(cls, data: ParseData):
        """Read templates from a package."""
        file = get_config(
            prop_block=data.info,
            fsys=data.fsys,
            folder='templates',
            pak_id=data.pak_id,
            prop_name='file',
            extension='.vmf',
        )
        file = VMF.parse(file)
        return cls(
            data.id,
            file,
            force=data.info['force', ''],
            keep_brushes=srctools.conv_bool(data.info['keep_brushes', '1'], True),
        )

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Write the template VMF file."""
        # Sort the visgroup list by name, to make it easier to search through.
        TEMPLATE_FILE.vis_tree.sort(key=lambda vis: vis.name)

        # Place the config entities in a nice grid.
        for conf_class, height in (
            ('bee2_template_conf', 256),
            ('bee2_template_scaling', 256 + 16),
        ):
            conf_ents = list(TEMPLATE_FILE.by_class[conf_class])
            dist = math.floor(math.sqrt(len(conf_ents)))
            half_dist = dist / 2
            for i, ent in enumerate(conf_ents):
                ent['origin'] = Vec(
                    16 * ((i // dist) - half_dist),
                    16 * ((i % dist) - half_dist),
                    height,
                )

        path = exp_data.game.abs_path('bin/bee2/templates.vmf')
        with open(path, 'w') as temp_file:
            TEMPLATE_FILE.export(temp_file, inc_version=False)

    @staticmethod
    def yield_world_detail(vmf: VMF) -> Iterator[Tuple[List[Solid], bool, set]]:
        """Yield all world/detail solids in the map.

        This also indicates if it's a func_detail, and the visgroup IDs.
        (Those are stored in the ent for detail, and the solid for world.)
        """
        for brush in vmf.brushes:
            yield [brush], False, brush.visgroup_ids
        for ent in vmf.by_class['func_detail']:
            yield ent.solids.copy(), True, ent.visgroup_ids