"""Manages the list of textures used for brushes, and how they are applied."""
from enum import Enum

import random

from srctools import Property
from srctools import Vec

import comp_consts as consts

from typing import Dict, List, Tuple, Union, Optional, Iterable

import utils


LOGGER = utils.getLogger(__name__)
