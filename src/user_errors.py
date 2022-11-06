"""Common data for the compile user error support.

UserError is imported all over, so this needs to have minimal imports to avoid cycles.
"""
from typing import ClassVar, Dict, Iterable, List, Literal, Tuple, TypedDict
import attrs
from srctools import Vec, logger

import utils
from transtoken import TransToken


Kind = Literal["white", "black", "goo", "goopartial", "goofull", "back"]


class SimpleTile(TypedDict):
    """A super simplified version of tiledef data for the error window. This can be converted right to JSON."""
    pos: Tuple[float, float, float]
    orient: Literal["n", "s", "e", "w", "u", "d"]


@attrs.frozen
class ErrorInfo:
    """Data to display to the user."""
    message: TransToken
    context: str  # Logging context
    faces: Dict[Kind, List[SimpleTile]]
    points: List[Tuple[float, float, float]]  # Points of interest in the map.


DATA_LOC = utils.conf_location('compile_error.pickle')
SERVER_PORT = utils.conf_location('error_server_url.txt')


class UserError(BaseException):
    """Special exception used to indicate a error in item placement, etc.

    This will result in the compile switching to compile a map which displays
    a HTML page to the user via the Steam Overlay.
    """
    _simple_tiles: ClassVar[Dict[Kind, List[SimpleTile]]] = {}

    def __init__(self, message: TransToken, points: Iterable[Vec]=()) -> None:
        """Specify the info to show to the user.

        * message is a translation token potentially containing HTML. Strings formatted into it
        will be escaped. TODO implement.
        * points is a list of offending map locations, which will be placed
          in a copy of the map for the user to see.
        """
        if utils.DEV_MODE:
            try:
                ctx = '<br><br>Error occured in: ' + ', '.join(logger.CTX_STACK.get())
            except LookupError:
                ctx = ''
        else:
            ctx = ''

        if isinstance(message, str):  # Temporary, prevent this breaking.
            message = TransToken.untranslated(message)

        self.info = ErrorInfo(
            message,
            ctx,
            self._simple_tiles,
            list(map(tuple, points)),
        )

    def __str__(self) -> str:
        return f'Error message: {self.info.message}'


# Define a translation token for every error message that can be produced. The app will translate
# them all during export, then store that for the compiler's use.


TOK_GLASS_FLOORBEAM_TEMPLATE = TransToken.ui(
    'Bad Glass Floorbeam template! The template must have a single brush, with one face '
    'pointing in the <var>+X</var> direction.'
)

TOK_CONNECTION_REQUIRED_ITEM = TransToken.ui(
    'No I/O configuration specified for special indicator item "<var>{item}</var>"! This is '
    'required for antlines to work.'
)

TOK_CONNECTIONS_UNKNOWN_INSTANCE = TransToken.ui(
    'The instance named "<var>{item}</var>" is not recognised! If you just swapped styles and '
    'exported, you will need to restart Portal 2. Otherwise check the relevant package.'
)

TOK_CONNECTIONS_INSTANCE_NO_IO = TransToken.ui(
    'The instance "<var>{inst}</var>" is reciving inputs, but none were configured in the item. '
    'Check for reuse of the instance in multiple items, or restart Portal 2 '
    'if you just exported.'
)

TOK_NO_CORRIDOR = TransToken.ui('No corridors available for {orient} {mode} {dir} group!')
