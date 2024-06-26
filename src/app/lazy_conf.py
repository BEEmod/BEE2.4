"""Implements callables which lazily parses and combines config files."""
from __future__ import annotations
from typing import Any, Awaitable, Callable, Final, Pattern
from typing_extensions import TypeAliasType
import functools

from srctools import KeyValError, Keyvalues, logger
from srctools.filesys import File
import trio

import app
import packages
import utils


LOGGER = logger.get_logger(__name__)
LazyConf = TypeAliasType("LazyConf", Callable[[], Awaitable[Keyvalues]])


async def _blank_prop() -> Keyvalues:
	"""An empty config. This is used as a singleton."""
	return Keyvalues.root()


BLANK: Final[LazyConf] = _blank_prop


def raw_prop(block: Keyvalues, source: str = '') -> LazyConf:
	"""Make an existing property conform to the interface."""
	if block or block.name is not None:
		if source:
			async def copy_with_source() -> Keyvalues:
				"""Copy the config, then apply the source."""
				copy = block.copy()
				packages.set_cond_source(copy, source)
				return copy
			return copy_with_source
		else:
			async def copy_no_source() -> Keyvalues:
				"""Just copy the block."""
				return block.copy()

			return copy_no_source
	else:  # If empty, source is irrelevant, and we can use the constant.
		return BLANK


def from_file(path: utils.PackagePath, missing_ok: bool = False, source: str = '') -> LazyConf:
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

	async def loader() -> Keyvalues:
		"""Load and parse the specified file when called."""
		def worker() -> Keyvalues:
			"""Run this in a background thread."""
			with file.open_str() as f:
				kv = Keyvalues.parse(f)
			if source:
				packages.set_cond_source(kv, source)
			return kv
		try:
			kv = await trio.to_thread.run_sync(worker)
		except (KeyValError, FileNotFoundError, UnicodeDecodeError):
			LOGGER.exception('Unable to read "{}"', path)
			raise
		return kv

	if app.DEV_MODE.value:
		app.background_run(devmod_check, file, path)
	return loader


async def devmod_check(file: File[Any], path: utils.PackagePath) -> None:
	"""In dev mode, parse files in the background to ensure they exist and have valid syntax."""
	def worker() -> None:
		"""Parse immediately, to check the syntax."""
		with file.open_str() as f:
			Keyvalues.parse(f)

	try:
		await trio.to_thread.run_sync(worker, abandon_on_cancel=True)
	except (KeyValError, FileNotFoundError, UnicodeDecodeError):
		LOGGER.exception('Unable to read "{}"', path)


def concat(a: LazyConf, b: LazyConf) -> LazyConf:
	"""Concatenate the two configs together."""
	# Catch a raw property being passed in.
	assert callable(a) and callable(b), (a, b)  # type: ignore[redundant-expr]
	# If either is blank, this is a no-op, so avoid a pointless layer.
	if a is BLANK:
		return b
	if b is BLANK:
		return a

	async def concat_inner() -> Keyvalues:
		"""Resolve then merge the configs."""
		kv = Keyvalues.root()
		kv.extend(await a())
		kv.extend(await b())
		return kv
	return concat_inner


def replace(base: LazyConf, replacements: list[tuple[Pattern[str], str]]) -> LazyConf:
	"""Replace occurances of values in the base config."""
	rep_funcs = [
		functools.partial(pattern.sub, repl)
		for pattern, repl in replacements
	]

	async def replacer() -> Keyvalues:
		"""Replace values."""
		copy = await base()
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
