"""The code for performing an export to the game folder."""
from enum import Enum, auto

import srctools.logger
from srctools import AtomicWriter, Keyvalues

import editoritems
from packages import ExportData
from step_order import StepOrder


LOGGER = srctools.logger.get_logger(__name__)


class StepResource(Enum):
    """Identifies types of files/data that is generated during export."""
    # Editoritems-related resources.
    EI_ITEMS = auto()  # Item definitions.
    EI_DATA = auto()  # Anything affecting the file.
    EI_FILE = auto()  # The file itself being written.

    # vbsp_config-related resources.
    VCONF_DATA = auto()  # Anything affecting the file.
    VCONF_FILE = auto()  # The file itself being written.

    STYLE = auto()  # Items must come after the style.


STEP_MANAGER = StepOrder(ExportData, StepResource)
