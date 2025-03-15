"""Inject VScript if a user error occurs."""
from urllib.request import urlopen
import json
import subprocess
import sys

from hammeraddons.bsp_transform import Context, trans
import srctools.logger
import trio

from user_errors import SERVER_INFO_FILE, ServerInfo
import utils


# Repeatedly show the URL whenever the user switches to the page.
# If it returns true, it has popped up the Steam Overlay.
# We then trigger the puzzlemaker command to switch in the background, behind the webpage.
# That pauses, so if you tab back it'll repeat.
# In Coop though, there's no URL show function, so we just display a hud message.
SCRIPT_TEMPLATE = '''\
function Think() {
    if (IsMultiplayer()) {
        // EntFireByHandle(self, "RunScriptCode", "MapPostLoaded()", 0.0, self, self);
        SendToConsole("ss_force_primary_fullscreen 1");
        EntFire("coop_disp", "Display", "");
        return 1.0;
    }
    if (ScriptSteamShowURL("http://127.0.0.1:%/")) {
        SendToConsole("puzzlemaker_show 1");
    }
}
'''

LOGGER = srctools.logger.get_logger(__name__)
ASYNC_SERVER_INFO = trio.Path(SERVER_INFO_FILE)


@trans('BEE2: User Error')
async def start_error_server(ctx: Context) -> None:
    """If the map contains the marker entity indicating a user error, inject the VScript."""
    for ent in ctx.vmf.by_class['bee2_user_error']:
        ent['thinkfunction'] = 'Think'
        # Load the coop script, so we don't disconnect.
        ent['vscripts'] = 'debug_scripts/mp_coop_transition_list.nut'
        ent['classname'] = 'info_player_start'

        port, error_text = await load_server()
        LOGGER.info('Server at port {}', port)
        ctx.add_code(ent, SCRIPT_TEMPLATE.replace('%', str(port)))

        try:
            error_1, error_2 = error_text.splitlines()
        except ValueError:
            LOGGER.warning('Bad translation for error text: {}', error_text)
            error_1 = 'Compile Error. Open the following URL'
            error_2 = 'in a browser on this computer to see:'

        for channel, y, text in [
            # 4,5,6 are the same size.
            (4, 0.45, error_1),
            (5, 0.5, error_2),
            (6, 0.55, f'http://localhost:{port}/'),
        ]:
            ctx.vmf.create_ent(
                'game_text',
                targetname='coop_disp',
                message=text,
                effect=0,
                color='200 0 0',
                holdtime=9999.0,
                autobreak=1,
                fadein=1.5,
                fadeout=0.5,
                fxtime=0.25,
                spawnflags=1,  # All players
                channel=channel,
                x=-1,
                y=y,
            )

        if not utils.FROZEN:
            # We're running outside Portal 2, pop it open in regular Chrome.
            import webbrowser
            webbrowser.get('chrome').open(f'http://127.0.0.1:{port}/')


async def load_server() -> tuple[int, str]:
    """Load the webserver, then return the port and the localised error text."""
    # We need to boot the web server.
    try:
        data: ServerInfo = json.loads(await ASYNC_SERVER_INFO.read_text('utf8'))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    else:
        port = data['port']
        coop_text = data.get('coop_text', '')
        LOGGER.debug('Server port file = {}', port)
        # Server appears to be live. Connect to it, so we can make it reload + check it's alive.
        try:
            urlopen(f'http://127.0.0.1:{port}/reload', timeout=5.0)
        except OSError:  # No response, it's likely dead.
            LOGGER.debug('No response from server.')
            await ASYNC_SERVER_INFO.unlink()  # This is invalid.
        else:
            LOGGER.debug('Server responded from localhost:{}', port)
            return port, coop_text  # This is live and its timeout was just refreshed, good to go.

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
        await trio.lowlevel.checkpoint()
        while proc.returncode is None:
            await trio.lowlevel.checkpoint()
            try:
                data = json.loads(await ASYNC_SERVER_INFO.read_text('utf8'))
            except (FileNotFoundError, json.JSONDecodeError):
                await trio.sleep(0.1)
                continue
            else:
                await trio.lowlevel.checkpoint()
                port = data['port']
                coop_text = data.get('coop_text', '')
                assert isinstance(port, int), data
                assert isinstance(coop_text, str), data
                # Successfully booted. Hack: set the return code of the subprocess.Process object,
                # so it thinks the server has already quit and doesn't try killing it when we exit.
                # TODO: Move upstream?
                proc._proc.returncode = 0  # noqa
                return port, coop_text
    raise ValueError('Failed to start error server!')
