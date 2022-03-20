"""Map info is a collection of global information about the current map."""
from collections import defaultdict
from enum import Enum
from typing import Dict, Set

import attrs
from srctools import VMF


@attrs.define
class Info:
    """Information about the map."""
    is_publishing: bool
    start_at_elevator: bool
    is_coop: bool
    _attrs: Dict[str, bool] = attrs.Factory(lambda: defaultdict(bool))

    @property
    def is_sp(self) -> bool:
        """Check if this is in singleplayer mode."""
        return not self.is_coop

    def has_attr(self, name: str) -> bool:
        """Check if this attribute is present in the map."""
        return self._attrs[name.casefold()]

    def set_attr(self, name: str):
        """Set this attribute to true."""
        self._attrs[name.casefold()] = True
