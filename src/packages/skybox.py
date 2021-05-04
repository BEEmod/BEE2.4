from srctools import Property
from packages import (
    PakObject, ExportData, ParseData, SelitemData,
    get_config, set_cond_source,
)


class Skybox(PakObject):
    """Configures skybox and fog settings."""
    def __init__(
        self,
        sky_id,
        selitem_data: SelitemData,
        config: Property,
        fog_opts: Property,
        mat,
    ) -> None:
        self.id = sky_id
        self.selitem_data = selitem_data
        self.material = mat
        self.config = config
        set_cond_source(config, 'Skybox <{}>'.format(sky_id))
        self.fog_opts = fog_opts

        # Extract this for selector windows to easily display
        self.fog_color = fog_opts.vec('primarycolor', 255, 255, 255)

    @classmethod
    def parse(cls, data: ParseData):
        """Parse a skybox definition."""
        selitem_data = SelitemData.parse(data.info, data.pak_id)
        mat = data.info['material', 'sky_black']
        config = get_config(
            data.info,
            data.fsys,
            'skybox',
            pak_id=data.pak_id,
        )

        fog_opts = data.info.find_key("Fog", [])

        return cls(
            data.id,
            selitem_data,
            config,
            fog_opts,
            mat,
        )

    def add_over(self, override: 'Skybox'):
        """Add the additional vbsp_config commands to ourselves."""
        self.selitem_data += override.selitem_data
        self.config += override.config
        self.fog_opts += override.fog_opts.copy()

    def __repr__(self) -> str:
        return f'<Skybox {self.id}>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected skybox."""
        if exp_data.selected is None:
            return  # No skybox..

        try:
            skybox = Skybox.by_id(exp_data.selected)  # type: Skybox
        except KeyError:
            raise Exception(
                "Selected skybox ({}) doesn't exist?".format(exp_data.selected)
            )

        exp_data.vbsp_conf.set_key(
            ('Options', 'Skybox'),
            skybox.material,
        )

        exp_data.vbsp_conf.append(skybox.config.copy())

        # Styles or other items shouldn't be able to set fog settings..
        if 'fog' in exp_data.vbsp_conf:
            del exp_data.vbsp_conf['fog']

        fog_opts = skybox.fog_opts.copy()
        fog_opts.name = 'Fog'

        exp_data.vbsp_conf.append(fog_opts)
