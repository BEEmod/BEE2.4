"""Widget configs can be copied over directly, but need to ensure all defaults are filled in."""
import srctools.logger
import trio.lowlevel

from config.widgets import WidgetConfig
from packages.widgets import ConfigGroup
from . import STEPS, ExportData, StepResource

LOGGER = srctools.logger.get_logger(__name__)


@STEPS.add_step(prereq=[], results=[StepResource.CONFIG_DATA])
async def set_apply_widget_defaults(exp_data: ExportData) -> None:
    """Ensure default values are copied across."""
    await trio.lowlevel.checkpoint()
    for group in exp_data.packset.all_obj(ConfigGroup):
        await trio.lowlevel.checkpoint()
        for widget in group.widgets + group.multi_widgets:
            conf_id = widget.conf_id()
            if widget.has_values:
                try:
                    exp_data.config.get(WidgetConfig, conf_id)
                    continue
                except KeyError:
                    # Apply defaults.
                    LOGGER.debug('Applying default for {}', conf_id)
                    exp_data.config = exp_data.config.with_value(widget.create_conf(), conf_id)
            else:
                # Strip item variants if present.
                exp_data.config, value = exp_data.config.discard(WidgetConfig, conf_id)
                if value is not None:
                    LOGGER.debug('Discarding config for {}', conf_id)
