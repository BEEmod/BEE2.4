"""Implements callables which lazily parses and combines config files."""
from __future__ import annotations
from typing import Callable, Pattern
import functools

import trio
from srctools import Property, logger, KeyValError
from srctools.filesys import File

import app
import packages
import utils


LOGGER = logger.get_logger(__name__)
LazyConf = Callable[[], Property]
# Empty property.
BLANK: LazyConf = lambda: Property.root()


def raw_prop(block: Property, source: str= '') -> LazyConf:
	"""Make an existing property conform to the interface."""
	if block or block.name is not None:
		if source:
			def copier() -> Property:
				"""Copy the config, then apply the source."""
				copy = block.copy()
				packages.set_cond_source(copy, source)
				return copy
			return copier
		else:  # We can just use the bound method.
			return block.copy
	else:  # If empty, source is irrelevant, and we can use the constant.
		return BLANK


def from_file(path: utils.PackagePath, missing_ok: bool=False, source: str= '') -> LazyConf:
	"""Lazily load the specified config."""
	try:
		fsys = packages.PACKAGE_SYS[path.package]
	except KeyError:
		if not missing_ok:
			LOGGER.warning('Package does not exist: "{}"', path)
		return BLANK
	try:
		file = fsys[path.path]
	except FileNotFoundError:
		if not missing_ok:
			LOGGER.warning('File does not exist: "{}"', path)
		return BLANK

	def loader() -> Property:
		"""Load and parse the specified file when called."""
		try:
			with file.open_str() as f:
				props = Property.parse(f)
		except (KeyValError, FileNotFoundError, UnicodeDecodeError):
			LOGGER.exception('Unable to read "{}"', path)
			raise
		if source:
			packages.set_cond_source(props, source)
		return props

	if app.DEV_MODE.get():
		app.background_run(devmod_check, file, path)
	return loader


async def devmod_check(file: File, path: utils.PackagePath) -> None:
	"""In dev mode, parse files in the background to ensure they exist and have valid syntax."""
	# Parse immediately, to check syntax.
	try:
		with file.open_str() as f:
			await trio.to_thread.run_sync(Property.parse, f, cancellable=True)
	except (KeyValError, FileNotFoundError, UnicodeDecodeError):
		LOGGER.exception('Unable to read "{}"', path)


def concat(a: LazyConf, b: LazyConf) -> LazyConf:
	"""Concatenate the two configs together."""
	# Catch a raw property being passed in.
	assert callable(a) and callable(b), (a, b)
	# If either is blank, this is a no-op, so avoid a pointless layer.
	if a is BLANK:
		return b
	if b is BLANK:
		return a

	def concat_inner() -> Property:
		"""Resolve then merge the configs."""
		prop = Property.root()
		prop.extend(a())
		prop.extend(b())
		return prop
	return concat_inner


def replace(base: LazyConf, replacements: list[tuple[Pattern[str], str]]) -> LazyConf:
	"""Replace occurances of values in the base config."""
	rep_funcs = [
		functools.partial(pattern.sub, repl)
		for pattern, repl in replacements
	]

	def replacer() -> Property:
		"""Replace values."""
		copy = base()
		for prop in copy.iter_tree():
			name = prop.real_name
			if name is not None:
				for func in rep_funcs:
					name = func(name)
				prop.name = name
			if not prop.has_children():
				value = prop.value
				for func in rep_funcs:
					value = func(value)
				prop.value = value
		return copy
	return replacer
