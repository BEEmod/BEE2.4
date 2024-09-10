"""The error server displays known compiler errors to the user in a friendly way.

If an error is detected in VBSP, the map is swapped with one which uses a VScript hook to pop open
the Steam Overlay and navigate to a webpage hosted by this server, which can show the error.

This has 3 endpoints:
- / displays the current error.
- /refresh causes it to reload the error from a text file on disk, if a new compile runs.
- /ping is triggered by the webpage repeatedly while open, to ensure the server stays alive.
"""
from __future__ import annotations


from typing_extensions import override
import functools
import gettext
import http
import io
import json
import math
import pickle
import sys

from hypercorn.config import Config
from hypercorn.trio import serve
from quart_trio import QuartTrio
import srctools.logger
import attrs
import psutil
import quart
import trio

from user_errors import (
    ErrorInfo, DATA_LOC, SERVER_INFO_FILE, ServerInfo, PackageTranslations,
    TOK_ERR_FAIL_LOAD, TOK_ERR_MISSING, TOK_COOP_SHOWURL,
)
import utils
import transtoken

LOGGER = srctools.logger.get_logger()

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
# This cancel scope is cancelled when the server should be shutdown.
# That happens either if Portal 2 is detected to quit, or if no response is heard from clients
# for DELAY seconds. It starts with an infinite deadline, to ensure there's time to boot the server.
SHUTDOWN_SCOPE = trio.CancelScope(deadline=math.inf)

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
async def route_render_data() -> dict[str, object]:
    """Return the geometry for rendering the current error."""
    await trio.lowlevel.checkpoint()
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


@app.route('/bee2_shutdown')
async def route_shutdown() -> quart.ResponseReturnValue:
    """Called by the application to force us to shut down so this can be updated."""
    LOGGER.info('Recieved shutdown request!')
    SHUTDOWN_SCOPE.cancel()
    await trio.lowlevel.checkpoint()
    return 'DONE'


async def check_portal2_running(allow_exit: trio.Event) -> None:
    """Check if Portal 2 is our parent process, and if so exit early when that dies."""
    try:
        try:
            proc_server = await trio.to_thread.run_sync(psutil.Process)
            parents = await trio.to_thread.run_sync(proc_server.parents)
            LOGGER.debug('Parents: {}', parents)
        except psutil.NoSuchProcess as exc:
            LOGGER.warning("We don't exist?", exc_info=exc)
            return
        for process in parents:
            if trio.Path(process.name()).stem.casefold() == 'portal2':
                LOGGER.info('Portal 2 = {}', process)
                proc_portal = process
                break
        else:
            LOGGER.info('No Portal 2 process found. Assuming a manual call...')
            # Don't immediately abort, we're run manually.
            return

        # Wait for the server to init, then wait for Portal 2 to quit. At that point
        # immediately stop the server.
        await allow_exit.wait()
        if proc_portal.is_running():
            # Since we can immediately quit when Portal 2 does, disable the timeout.
            SHUTDOWN_SCOPE.deadline = math.inf
            LOGGER.info('Waiting for Portal 2 to quit...')
            await trio.to_thread.run_sync(proc_portal.wait)
        LOGGER.info('Portal 2 quit!')
        SHUTDOWN_SCOPE.cancel()
    except psutil.AccessDenied as exc:
        LOGGER.warning('Failed to detect if Portal 2 is closed:', exc_info=exc)


def update_deadline() -> None:
    """When interacted with, the deadline is reset into the future."""
    if math.isfinite(SHUTDOWN_SCOPE.deadline):
        SHUTDOWN_SCOPE.deadline = trio.current_time() + DELAY
        LOGGER.info('Reset deadline!')


@attrs.define(eq=False)
class PackageLang(transtoken.GetText):
    """Simple Gettext implementation for tokens loaded by packages."""
    tokens: dict[str, str]

    @override
    def gettext(self, token: str, /) -> str:
        """Perform simple translations."""
        # In this context, the tokens must be IDs not the actual string.
        return self.tokens.get(token.casefold(), token)

    @override
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
        LOGGER.info('Loaded error info')

    translations: dict[str, transtoken.GetText] = {}
    try:
        package_data = pickle.loads(
            await trio.Path('bee2/pack_translation.bin').read_bytes()
        )
    except Exception:
        LOGGER.exception('Failed to load package translations pickle!')
    else:
        if isinstance(package_data, PackageTranslations):
            for pack_id, tokens in package_data.translations:
                translations[pack_id] = PackageLang(tokens)
        else:
            LOGGER.exception('Invalid package translations: got {!r}', package_data)
        LOGGER.info('Loaded package translations')

    if current_error.language_file is not None:
        try:
            lang_data = await trio.Path(current_error.language_file).read_bytes()
            # GNUTranslations immediately reads the whole thing, so this buffer doesn't change
            # anything.
            translations[transtoken.NS_UI] = gettext.GNUTranslations(io.BytesIO(lang_data))
        except OSError:
            LOGGER.exception('Could not load UI translations file!')
            return
        transtoken.CURRENT_LANG.value = transtoken.Language(
            lang_code='',
            ui_filename=current_error.language_file,
            trans=translations,
        )
        LOGGER.info('Loaded UI translations')


async def main(argv: list[str]) -> None:
    """Start up the server."""
    binds: list[str]
    stop_sleeping = trio.CancelScope()

    async def timeout_func() -> None:
        """Triggers the server to shut down with this cancel scope."""
        with SHUTDOWN_SCOPE:
            await trio.sleep_forever()
        LOGGER.info('Shutdown triggered.')
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

    allow_exit = trio.Event()

    SERVER_INFO_FILE.unlink(missing_ok=True)
    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(check_portal2_running, allow_exit)
            await trio.lowlevel.checkpoint()
            binds = await nursery.start(functools.partial(
                serve,
                app, config,
                shutdown_trigger=timeout_func,
            ))
            # Set deadline after app is ready, and let check_portal2 do checks.
            SHUTDOWN_SCOPE.deadline = trio.current_time() + DELAY
            LOGGER.info(
                'Current time= {}, deadline={}',
                trio.current_time(), SHUTDOWN_SCOPE.deadline,
            )
            if len(binds):
                url, port = binds[0].rsplit(':', 1)
                with srctools.AtomicWriter(SERVER_INFO_FILE) as f:
                    json.dump(ServerInfo(
                        port=int(port),
                        coop_text=str(TOK_COOP_SHOWURL),
                    ), f)
            else:
                sys.exit("Server didn't startup?")
            with stop_sleeping:
                allow_exit.set()
                await trio.sleep_forever()
    finally:
        SERVER_INFO_FILE.unlink(missing_ok=True)  # We quit, indicate that.
    LOGGER.info('Shutdown successfully.')
