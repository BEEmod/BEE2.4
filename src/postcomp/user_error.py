"""Inject VScript if a user error occurs."""
import re
import subprocess

import trio
import sys
from urllib.request import urlopen

import srctools.logger

import utils
from hammeraddons.bsp_transform import Context, trans
from user_errors import SERVER_PORT

# Repeatedly show the URL whenever the user switches to the page.
# If it returns true, it has popped up the Steam Overlay.
# We then trigger the puzzlemaker command to switch in the background, behind the webpage.
# That pauses, so if you tab back it'll repeat.
SCRIPT_TEMPLATE = '''\
function Think() {
\tif (ScriptSteamShowURL("http:/127.0.0.1:%/")) SendToConsole("puzzlemaker_show 1");
}
'''

LOGGER = srctools.logger.get_logger(__name__)
ASYNC_PORT = trio.Path(SERVER_PORT)


@trans('BEE2: User Error')
async def start_error_server(ctx: Context) -> None:
    """If the map contains the marker entity indicating a user error, inject the VScript."""
    for ent in ctx.vmf.by_class['bee2_user_error']:
        ent['thinkfunction'] = 'Think'
        ent['classname'] = 'info_player_start'

        port = await load_server()
        LOGGER.info('Server at port {}', port)
        ctx.add_code(ent, SCRIPT_TEMPLATE.replace('%', str(port)))


async def load_server() -> int:
    """Load the webserver."""
    # We need to boot the web server.
    try:
        port = int(await ASYNC_PORT.read_text('utf8'))
    except (FileNotFoundError, ValueError):
        pass
    else:
        LOGGER.debug('Server port file = {}', port)
        # Server appears to be live. Connect to it, so we can make it reload + check it's alive.
        try:
            urlopen(f'http://127.0.0.1:{port}/reload', timeout=5.0)
        except OSError:  # No response, it's likely dead.
            LOGGER.debug('No response from server.')
            await ASYNC_PORT.unlink()  # This is invalid.
        else:
            LOGGER.debug('Server responded from localhost:{}', port)
            return port  # This is live and its timeout was just refreshed, good to go.

    if utils.FROZEN:
        args = [sys.executable]
    else:
        args = [sys.executable, sys.argv[0], 'vrad.exe']
    args.append('--errorserver')

    # On Windows, suppress the console window.
    if utils.WIN:
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
    else:
        startup_info = None

    proc: trio.Process = await trio.lowlevel.open_process(args, startupinfo=startup_info)
    LOGGER.debug('Launched server.')

    # Wait for it to boot, and update the ports file.
    with trio.move_on_after(5.0):
        while proc.returncode is None:
            try:
                port = int(await ASYNC_PORT.read_text('utf8'))
            except (FileNotFoundError, ValueError):
                await trio.sleep(0.1)
                continue
            else:
                # Successfully booted. Hack: set the return code of the subprocess.Process object,
                # so it thinks the server has already quit and doesn't try killing it when we exit.
                proc._proc.returncode = 0
                return port
    raise ValueError('Failed to start error server!')
