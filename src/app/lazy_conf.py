"""Implements callables which lazily parses and combines config files."""
from __future__ import annotations
from typing import Callable, Pattern, Optional

from srctools import Property, logger
from utils import PackagePath
import packages


LOGGER = logger.get_logger(__name__)
LazyConf = Callable[[], Property]


def conf_direct(block: Property) -> LazyConf:
	"""Make an existing property conform to the interface."""
	return block.copy


def conf_file(path: PackagePath) -> LazyConf:
	"""Lazily load the specified config."""
	try:
		fsys = packages.PACKAGE_SYS[path.package]
	except KeyError:
		LOGGER.warning('Package does not exist: "{}"', path)
		return lambda: Property(None, [])
	try:
		file = fsys[path.path]
	except FileNotFoundError:
		LOGGER.warning('File does not exist: "{}"', path)
		return lambda: Property(None, [])

	cache: Optional[Property] = None

	def loader() -> Property:
		"""Load the file if required, and return a copy."""
		nonlocal cache
		if cache is None:
			with file.open_str() as f:
				cache = Property.parse(f)
		return cache.copy()
	return loader


def conf_concat(a: LazyConf, b: LazyConf) -> LazyConf:
	"""Concatenate the two configs together."""
	return lambda: a() + b()


def conf_replace(base: LazyConf, replacements: list[tuple[Pattern[str], str]]) -> LazyConf:
	"""Replace occurances of values in the base config."""
	def replacer() -> Property:
		"""Replace values."""
		copy = base()
		for prop in copy.iter_tree():
			name = orig = prop.real_name
			for pattern, result in replacements:
				name = pattern.sub(name, result)
			prop.name = name
			if not prop.has_children():
				value = prop.value
				for pattern, result in replacements:
					value = pattern.sub(value, result)
				prop.value = value
		return copy
	return replacer
