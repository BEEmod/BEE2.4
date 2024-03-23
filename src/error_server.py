"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
import attrs
import srctools.logger
LOGGER = srctools.logger.init_logging('bee2/error_server.log')

from typing import Any, Dict, List, Tuple
import functools
import http
import math
import pickle
import gettext
import json

from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import quart
import trio

import utils
from user_errors import (
    ErrorInfo, DATA_LOC, SERVER_INFO_FILE, ServerInfo,
    TOK_ERR_FAIL_LOAD, TOK_ERR_MISSING, TOK_COOP_SHOWURL,
)
import transtoken

root_path = utils.bins_path('error_display').absolute()
LOGGER.info('Root path: {!r}', root_path)

app = QuartTrio(
    __name__,
    root_path=str(root_path),
)
# Compile logs.
LOGS = {'vbsp': '', 'vrad': ''}
config = Config()
config.bind = ["localhost:0"]  # Use localhost, request any free port.
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
        context=current_error.context,
        log_vbsp=LOGS['vbsp'],
        log_vrad=LOGS['vrad'],
        # Start the render visible if it has annotations.
        start_render_open=bool(
            current_error.points
            or current_error.leakpoints
            or current_error.lines
            or current_error.barrier_holes
        ),
    )


@app.route('/displaydata')
async def route_render_data() -> Dict[str, Any]:
    """Return the geometry for rendering the current error."""
    return {
        'tiles': current_error.faces,
        'voxels': current_error.voxels,
        'points': current_error.points,
        'leak': current_error.leakpoints,
        'lines': current_error.lines,
        'barrier_holes': current_error.barrier_holes,
    }


@app.route('/heartbeat', methods=['GET', 'POST', 'HEAD'])
async def route_heartbeat() -> quart.ResponseReturnValue:
    """This route is continually accessed to keep the server alive while the page is visible."""
    update_deadline()
    resp = await app.make_response(('', http.HTTPStatus.NO_CONTENT))
    resp.mimetype = 'text/plain'
    return resp


@app.route('/reload')
async def route_reload() -> quart.ResponseReturnValue:
    """Called by our VRAD, to make existing servers reload their data."""
    update_deadline()
    await load_info()
    resp = await app.make_response(('', http.HTTPStatus.NO_CONTENT))
    resp.mimetype = 'text/plain'
    return resp


@app.route('/static/<path:filename>.js')
async def route_static_js(filename: str) -> quart.ResponseReturnValue:
    """Ensure javascript is returned with the right MIME type."""
    assert app.static_folder is not None
    return await quart.send_from_directory(
        directory=app.static_folder,
        file_name=filename + '.js',
        mimetype='text/javascript',
        # Disable cache. Steam Overlay doesn't easily let you clear cache, and it's local anyway.
        cache_timeout=1,
    )


@app.route('/shutdown')
async def route_shutdown() -> quart.ResponseReturnValue:
    """Called by the application to force us to shut down so this can be updated."""
    LOGGER.info('Recieved shutdown request!')
    TIMEOUT_CANCEL.cancel()
    return 'DONE'


def update_deadline() -> None:
    """When interacted with, the deadline is reset into the future."""
    TIMEOUT_CANCEL.deadline = trio.current_time() + DELAY
    LOGGER.info('Reset deadline!')


@attrs.define(eq=False)
class PackageLang(transtoken.GetText):
    """Simple Gettext implementation for tokens loaded by packages."""
    tokens: Dict[str, str]

    def gettext(self, token: str, /) -> str:
        """Perform simple translations."""
        # In this context, the tokens must be IDs not the actual string.
        return self.tokens.get(token.casefold(), token)

    def ngettext(self, single: str, plural: str, n: int, /) -> str:
        """We don't support plural translations yet, not required."""
        return self.tokens.get(single.casefold(), single)


async def load_info() -> None:
    """Load the error info from disk."""
    LOGGER.info('Loading data: {}', DATA_LOC)
    global current_error
    try:
        data = pickle.loads(await trio.Path(DATA_LOC).read_bytes())
        if not isinstance(data, ErrorInfo):
            raise ValueError
    except Exception:
        LOGGER.exception('Failed to load pickle!')
        current_error = ErrorInfo(message=TOK_ERR_FAIL_LOAD)
    else:
        current_error = data

    translations: Dict[str, transtoken.GetText] = {}
    try:
        package_data: List[Tuple[str, Dict[str, str]]] = pickle.loads(
            await trio.Path('bee2/pack_translation.bin').read_bytes()
        )
    except Exception:
        LOGGER.exception('Failed to load package translations pickle!')
    else:
        for pack_id, tokens in package_data:
            translations[pack_id] = PackageLang(tokens)

    if current_error.language_file is not None:
        try:
            with open(current_error.language_file, 'rb') as f:
                translations[transtoken.NS_UI] = gettext.GNUTranslations(f)
        except OSError:
            LOGGER.exception('Could not load UI translations file!')
            return
        transtoken.CURRENT_LANG.value = transtoken.Language(
            lang_code='',
            ui_filename=current_error.language_file,
            trans=translations,
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

    async def load_compiler(name: str) -> None:
        """Load a compiler log file."""
        try:
            LOGS[name] = await trio.Path(f'bee2/{name}.log').read_text('utf8')
        except OSError:
            LOGGER.warning('Could not read bee2/{}.log', name)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(load_compiler, 'vbsp')
        nursery.start_soon(load_compiler, 'vrad')
        nursery.start_soon(load_info)

    SERVER_INFO_FILE.unlink(missing_ok=True)
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
                with srctools.AtomicWriter(SERVER_INFO_FILE) as f:
                    json.dump(ServerInfo(
                        port=int(port),
                        coop_text=str(TOK_COOP_SHOWURL),
                    ), f)
            else:
                return  # No connection?
            with stop_sleeping:
                await trio.sleep_forever()
    finally:
        SERVER_INFO_FILE.unlink(missing_ok=True)  # We quit, indicate that.
    LOGGER.info('Shut down successfully.')
