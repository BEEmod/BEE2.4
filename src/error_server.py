"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
import srctools.logger
LOGGER = srctools.logger.init_logging('bee2/error_server.log')

import functools
import http
import math
import pickle
import gettext
from typing import List

from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import quart
import trio

import utils
from user_errors import ErrorInfo, DATA_LOC, SERVER_PORT, TOK_ERR_FAIL_LOAD, TOK_ERR_MISSING
import transtoken

root_path = utils.install_path('error_display').absolute()
LOGGER.info('Root path: ', root_path)

app = QuartTrio(
    __name__,
    root_path=str(root_path),
)
config = Config()
config.debug = True
config.bind = ["localhost:8080"]  # Use localhost, request any free port.
DELAY = 5 * 60  # After 5 minutes of no response, quit.
# This cancel scope is cancelled after no response from the client, to shut us down.
# It starts with an infinite deadline, to ensure there's time to boot the server.
TIMEOUT_CANCEL = trio.CancelScope(deadline=math.inf)

current_error = ErrorInfo(message=TOK_ERR_MISSING)


@app.route('/')
async def route_display_errors() -> str:
    """Display the current error."""
    update_deadline()
    return await quart.render_template(
        'index.html.jinja2',
        error_text=current_error.message.translate_html(),
        log_context=current_error.context,
    )


@app.route('/displaydata')
async def route_render_data() -> dict:
    """Return the geometry for rendering the current error."""
    return {
        'tiles': current_error.faces,
        'voxels': current_error.voxels,
        'points': current_error.points,
        'leak': current_error.leakpoints,
        'barrier_hole': current_error.barrier_hole,
    }


@app.route('/heartbeat', methods=['GET', 'POST', 'HEAD'])
async def route_heartbeat() -> quart.Response:
    """This route is continually accessed to keep the server alive while the page is visible."""
    update_deadline()
    resp = await app.make_response(('', http.HTTPStatus.NO_CONTENT))
    resp.mimetype = 'text/plain'
    return resp


@app.route('/reload')
async def route_reload() -> quart.Response:
    """Called by our VRAD, to make existing servers reload their data."""
    update_deadline()
    load_info()
    resp = await app.make_response(('', http.HTTPStatus.NO_CONTENT))
    resp.mimetype = 'text/plain'
    return resp


@app.route('/static/<path:filename>.js')
async def route_static_js(filename: str) -> quart.Response:
    """Ensure javascript is returned with the right MIME type."""
    return await quart.send_from_directory(
        directory=app.static_folder,
        file_name=filename + '.js',
        mimetype='text/javascript',
        # Disable cache. Steam Overlay doesn't easily let you clear cache, and it's local anyway.
        cache_timeout=1,
    )


def update_deadline() -> None:
    """When interacted with, the deadline is reset into the future."""
    TIMEOUT_CANCEL.deadline = trio.current_time() + DELAY
    LOGGER.info('Reset deadline!')


def load_info() -> None:
    """Load the error info from disk."""
    global current_error
    try:
        with open(DATA_LOC, 'rb') as f:
            data = pickle.load(f)
        if not isinstance(data, ErrorInfo):
            raise ValueError
    except Exception:
        LOGGER.exception('Failed to load pickle!')
        current_error = ErrorInfo(message=TOK_ERR_FAIL_LOAD)
    else:
        current_error = data
    if current_error.language_file is not None:
        try:
            with open(current_error.language_file, 'rb') as f:
                lang = gettext.GNUTranslations(f)
        except OSError:
            return
        transtoken.CURRENT_LANG = transtoken.Language(
            display_name='??',
            lang_code='',
            ui_filename=current_error.language_file,
            trans={transtoken.NS_UI: lang},
        )


async def main() -> None:
    """Start up the server."""
    binds: List[str]
    stop_sleeping = trio.CancelScope()

    async def timeout_func() -> None:
        """Triggers the server to shut down with this cancel scope."""
        with TIMEOUT_CANCEL:
            await trio.sleep_forever()
        LOGGER.info('Timeout elapsed.')
        # Allow nursery to exit.
        stop_sleeping.cancel()

    load_info()
    SERVER_PORT.unlink(missing_ok=True)
    try:
        async with trio.open_nursery() as nursery:
            binds = await nursery.start(functools.partial(
                serve,
                app, config,
                shutdown_trigger=timeout_func
            ))
            # Set deadline after app is ready.
            TIMEOUT_CANCEL.deadline = trio.current_time() + DELAY
            LOGGER.info('Current time: ', trio.current_time(), 'Deadline:', TIMEOUT_CANCEL.deadline)
            if len(binds):
                url, port = binds[0].rsplit(':', 1)
                with srctools.AtomicWriter(SERVER_PORT) as f:
                    f.write(f'{port}\n')
            else:
                return # No connection?
            with stop_sleeping:
                await trio.sleep_forever()
    finally:
        SERVER_PORT.unlink(missing_ok=True)  # We quit, indicate that.
    LOGGER.info('Shut down successfully.')
