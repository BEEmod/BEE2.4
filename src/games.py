"""Manages and identifies the state of all games."""
from enum import Enum
from pathlib import Path
from typing import Iterator, Iterable, Set

from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain, VPKFileSystem
from srctools import Property, VPK, GameID, AtomicWriter


class State(Enum):
    """Modding state of the game."""
    UNMODDABLE = 'nomod'  # Not Source, not something we care about.

    RES_ONLY = 'resource'  # No PeTI, but we want to use resources (Mel, P1)

    VANILLA = 'vanilla'  # Not modded yet.
    BEEMOD = 'beemod'  # We're installed.

    @property
    def moddable(self) -> bool:
        """Are we able to mod this game?"""
        return self.value in ('vanilla', 'beemod')

    @property
    def has_res(self) -> bool:
        """Do we want to mount this for resources?"""
        return self.value in ('resource', 'vanilla', 'beemod')

    @staticmethod
    def initial_state(game_id: GameID) -> 'State':
        """Find the initial state for a game."""
        if game_id in MODDABLE_GAMES:
            return State.VANILLA
        elif game_id in RESOURCE_GAMES:
            return State.RES_ONLY
        else:
            return State.UNMODDABLE

MODDABLE_GAMES = {
    GameID.PORTAL_2,
    GameID.APERTURE_TAG,
}

RESOURCE_GAMES = {
    GameID.PORTAL,
    GameID.MEL,
    GameID.REXAURA,
}

# Locations of Steam installs in various systems.
DEFAULT_STEAM = [
    Path('C:/Program Files (x86)/Steam/'),  # Win64
    Path('C:/Program Files/Steam/'),  # Win32
    Path('~/Library/Application Support/Steam/'),  # OS X
    Path('~/.local/share/Steam/'),  # Linux
    Path('~/.steam/steam/'),  # Linux, older.
]


class Game:
    def __init__(
        self,
        steam_id: GameID,
        path: Path,
        state: State,
    ) -> None:
        self.steam_id = steam_id
        self.state = state
        self.path = path.resolve()

    def __repr__(self):
        return '<{} Game {} "{!s}">'.format(
            self.state.name.title(),
            self.steam_id.name,
            self.path,
        )


def conf_read(cls, fname: Path) -> Iterator[Game]:
    """Parse games from config files."""
    with open(fname, 'r') as f:
        props = Property.parse(f)

    for prop in props.find_all('Game'):
        yield Game(
            GameID(prop.int('steam')),
            Path(prop['path']),
            State(prop['state']),
        )


def conf_write(fname: Path, games: Iterable[Game]) -> None:
    """Write games into a config file."""
    with AtomicWriter(str(fname), is_bytes=False) as f:
        for game in games:
            prop = Property('Game', [
                Property('steam', game.steam_id.value),
                Property('path', str(game.path).replace('\\', '/')),
                Property('state', game.state.value)
            ])
            for line in prop.export():
                f.write(line)


def find_steamapps() -> Iterator[Path]:
    """Guess the user's Steam folders."""
    for path in DEFAULT_STEAM:
        if path.exists():
            yield path
            # Try to find secondary folders.
            try:
                with open(path / 'SteamApps/libraryfolders.vdf') as f:
                    conf = Property.parse(f)
            except FileNotFoundError:
                pass
            else:
                # Has "1"/"2"/"3" keys.
                for prop in conf.find_key('LibraryFolders'):
                    if prop.name.isdigit():
                        yield Path(prop.value)


def scan_games(steam: Iterable[Path], games: Set[Game]):
    """Look through the user's Steam folders for additional games.

    This updates the games list as required.
    steam is a list of Steam folders.
    """
    existing = {
        (game.path, game.steam_id): game
        for game in games
    }

    for lib_folder in steam:
        # SteamApps/ has a pile of 'acf' files, which each specify game
        # IDs and then locations.
        for acf_path in lib_folder.glob('SteamApps/*.acf'):
            with open(acf_path) as f:
                acf = Property.parse(f, acf_path).find_key('AppState')
            try:
                steam_id = GameID(acf['appid', ''])
            except ValueError:
                continue  # Not a Source game.

            inst_path = lib_folder.joinpath('SteamApps', acf['installdir']).resolve()

            if (inst_path, steam_id) not in existing:
                existing[inst_path, steam_id] = game = Game(
                    steam_id,
                    inst_path,
                    State.initial_state(steam_id),
                )
                games.add(game)
