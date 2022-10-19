"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
import socket
from typing import List
from importlib_resources import files

import quart
from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import trio

from srctools.dmx import Element


app = QuartTrio(__name__)
config = Config()
config.bind = ["localhost:0"]  # Use localhost, request any free port.


TEMPLATE_ERROR = (files(__name__) / 'index.html').read_text('utf8')

current_error = ''


@app.route('/')
async def route_errorpage() -> str:
    """Display the current error."""
    return await quart.render_template_string(TEMPLATE_ERROR, error=current_error)


async def main(args: List[str]) -> None:
    """Start up the server."""
    binds: List[socket.socket]
    async with trio.open_nursery() as nursery:
        binds = await nursery.start(serve, app, config)
        if len(binds):
            print('[BEE2] BIND =', binds[0])
        else:
            print('[BEE2] ERROR')
