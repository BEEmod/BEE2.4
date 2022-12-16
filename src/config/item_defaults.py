"""Store overridden defaults for items."""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict

import attrs
from srctools import Property
from srctools.dmx import Element

from BEE2_config import ConfigFile
import config
from editoritems_props import ItemPropKind


@config.APP.register
@attrs.frozen(slots=False)
class ItemDefault(config.Data, conf_name='ItemDefault', uses_id=True):
    """Overrides the defaults for item properties."""
    defaults: Dict[ItemPropKind, str]

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> ItemDefault:
        """Parse keyvalues1 data."""

    def export_kv1(self) -> Property:
        """Export as keyvalues1 data."""

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> ItemDefault:
        """Parse DMX configuration."""

    def export_dmx(self) -> Element:
        """Export as DMX data."""
