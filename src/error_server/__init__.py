"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
import argparse
import socket
import sys
from typing import List

from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import quart
import jinja2
import trio

from srctools.dmx import Element
import utils


parser = argparse.ArgumentParser(description='Error display for BEE2 compilers.')
parser.add_argument(
    '--errorserver', help='Required to run the server.',
    action='store_true',
    required=True,
)
parser.add_argument(
    '--contentroot', help='Location of the webpage content.',
    action='store',
    required=True,
)
parsed_args = parser.parse_args(sys.argv[1:])

app = QuartTrio(
    __name__,
    root_path=parsed_args.contentroot,
)
config = Config()
config.bind = ["localhost:0"]  # Use localhost, request any free port.

current_error = 'Your map has a leak! Check the area around the red line here, and try removing nearby items.'


@app.route('/')
async def route_error_page():
    """Display the current error."""
    return await quart.stream_template('index.html', error_text=current_error)


@app.route('/styles.css')
async def route_error_styles():
    """Return the error page stylesheet."""
    print('Get styles:')
    return await app.send_static_file('styles.css')


async def main() -> None:
    """Start up the server."""
    binds: List[socket.socket]
    async with trio.open_nursery() as nursery:
        binds = await nursery.start(serve, app, config)
        if len(binds):
            print('[BEE2] BIND =', binds[0])
        else:
            print('[BEE2] ERROR')
