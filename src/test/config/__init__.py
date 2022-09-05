"""Common code for testing configuration."""
import contextlib
from typing import Generator

import pytest

from BEE2_config import GEN_OPTS


@pytest.fixture
def isolate_gen_opts() -> Generator[None, None, None]:
    """Ensure GEN_OPTS cannot write to files, and is cleared of data."""
    old_filename = GEN_OPTS.filename
    GEN_OPTS.filename = None
    old_data = {}
    try:
        for section in GEN_OPTS.sections():
            old_data[section] = dict(GEN_OPTS[section])
            GEN_OPTS.remove_section(section)
        yield
    finally:
        GEN_OPTS.filename = old_filename
        for section, values in old_data.items():
            GEN_OPTS[section] = values
