"""Widget configs can be copied over directly, but need to ensure all defaults are filled in."""
import srctools.logger

from config.widgets import WidgetConfig
from packages.widgets import ConfigGroup
from . import STEPS, ExportData, StepResource

LOGGER = srctools.logger.get_logger(__name__)


@STEPS.add_step(prereq=[], results=[StepResource.CONFIG_DATA])
async def set_apply_widget_defaults(exp_data: ExportData) -> None:
    """Ensure default values are copied across."""
    for group in exp_data.packset.all_obj(ConfigGroup):
        for widget in group.widgets + group.multi_widgets:
            conf_id = widget.conf_id()
            try:
                exp_data.config.get(WidgetConfig, conf_id)
                continue
            except KeyError:
                # Apply defaults.
                LOGGER.debug('Applying default for {}', conf_id)
                exp_data.config = exp_data.config.with_value(widget.create_conf(), conf_id)
