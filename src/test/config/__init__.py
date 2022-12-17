"""Common code for testing configuration."""
import contextlib
from typing import Generator

import pytest

from BEE2_config import GEN_OPTS, ConfigFile


@contextlib.contextmanager
def isolate_conf(config: ConfigFile) -> Generator[ConfigFile, None, None]:
    """Inside the context, clear this config and prevent it from writing."""
    old_filename = config.filename
    config.filename = None
    old_data = {}
    try:
        for section in config.sections():
            old_data[section] = dict(config[section])
            config.remove_section(section)
        yield config
    finally:
        config.filename = old_filename
        for section, values in old_data.items():
            config[section] = values



@pytest.fixture
def isolate_gen_opts() -> Generator[None, None, None]:
    """Ensure GEN_OPTS cannot write to files, and is cleared of data."""
    with isolate_conf(GEN_OPTS):
        yield
