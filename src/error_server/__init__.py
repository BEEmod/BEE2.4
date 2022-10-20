"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
import argparse
import functools
import http
import math
import socket
import sys
from typing import List

from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import quart
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
DELAY = 5 * 60
# This cancel scope is cancelled after no response from the client, to shut us down.
# It starts with an infinite deadline, to ensure there's time to boot the server.
TIMEOUT_CANCEL = trio.CancelScope(deadline=math.inf)

current_error = 'Your map has a leak! Check the area around the red line here, and try removing nearby items.'


def update_deadline() -> None:
    """When interacted with, the deadline is reset into the future."""
    TIMEOUT_CANCEL.deadline = trio.current_time() + DELAY
    print('Reset deadline!')


@app.route('/')
async def route_error_page() -> str:
    """Display the current error."""
    update_deadline()
    return await quart.render_template('index.html', error_text=current_error)


@app.route('/styles.css')
async def route_error_styles() -> quart.Response:
    """Return the error page stylesheet."""
    return await app.send_static_file('styles.css')


@app.route('/tile_bg.png')
async def route_error_bg() -> quart.Response:
    """Return the error page background image."""
    return await app.send_static_file('tile_bg.png')


@app.route('/script.js')
async def route_error_script() -> quart.Response:
    """Return the error page script file."""
    return await app.send_static_file('script.js')


@app.route('/heartbeat', methods=['GET', 'POST', 'HEAD'])
async def route_heartbeat() -> quart.Response:
    """This route is continually accessed to keep the server alive while the page is visible."""
    update_deadline()
    resp = await app.make_response(('', http.HTTPStatus.NO_CONTENT))
    resp.mimetype = 'text/plain'
    return resp


async def main() -> None:
    """Start up the server."""
    binds: List[socket.socket]
    stop_sleeping = trio.CancelScope()

    async def timeout_func() -> None:
        """Triggers the server to shut down with this cancel scope."""
        with TIMEOUT_CANCEL:
            await trio.sleep_forever()
        print('Timeout elapsed.')
        # Allow nursery to exit.
        stop_sleeping.cancel()

    async with trio.open_nursery() as nursery:
        binds = await nursery.start(functools.partial(
            serve,
            app, config,
            shutdown_trigger=timeout_func
        ))
        # Set deadline after app is ready.
        TIMEOUT_CANCEL.deadline = trio.current_time() + DELAY
        print('Current time: ', trio.current_time(), 'Deadline:', TIMEOUT_CANCEL.deadline)
        if len(binds):
            print('[BEE2] BIND =', binds[0])
        else:
            print('[BEE2] ERROR')
        with stop_sleeping:
            await trio.sleep_forever()
    print('Shut down successfully.')
