"""Implements callables which lazily parses and combines config files."""
from __future__ import annotations
from typing import Any, Final, Pattern
from collections.abc import Awaitable, Callable
import functools

from srctools import KeyValError, Keyvalues, logger
from srctools.filesys import File
import trio

import app
import packages
import utils


LOGGER = logger.get_logger(__name__)
type LazyConf = Callable[[], Awaitable[Keyvalues]]


async def _blank_prop() -> Keyvalues:
	"""An empty config. This is used as a singleton."""
	await trio.lowlevel.checkpoint()
	return Keyvalues.root()


BLANK: Final[LazyConf] = _blank_prop


def raw_prop(block: Keyvalues, source: str = '') -> LazyConf:
	"""Make an existing property conform to the interface."""
	if block or block.name is not None:
		if source:
			async def copy_with_source() -> Keyvalues:
				"""Copy the config, then apply the source."""
				await trio.lowlevel.checkpoint()
				copy = block.copy()
				packages.set_cond_source(copy, source)
				return copy
			return copy_with_source
		else:
			async def copy_no_source() -> Keyvalues:
				"""Just copy the block."""
				await trio.lowlevel.checkpoint()
				return block.copy()

			return copy_no_source
	else:  # If empty, source is irrelevant, and we can use the constant.
		return BLANK


async def from_file(
	packset: packages.PackagesSet,
	path: utils.PackagePath,
	*,
	missing_ok: bool = False, source: str = '',
) -> LazyConf:
	"""Lazily load the specified config."""
	try:
		# If package is a special ID, this will fail.
		pack = packset.packages[utils.ObjectID(path.package)]
	except KeyError:
		if not missing_ok:
			LOGGER.warning('Package does not exist: "{}"', path)
		return BLANK
	try:
		file = await trio.to_thread.run_sync(pack.fsys.__getitem__, path.path)
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

	if packset.devmode_filecheck_chan is not None:
		await packset.devmode_filecheck_chan.send((path, file))
	return loader


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
