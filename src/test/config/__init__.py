"""Common code for testing configuration."""
from typing import Generator
import contextlib

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
