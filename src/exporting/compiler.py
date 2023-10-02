"""Controls exporting the compiler files."""
import json
import urllib.error
import urllib.request

import srctools.logger
import trio

import user_errors
from exporting import STEPS, StepResource
from packages import ExportData


LOGGER = srctools.logger.get_logger(__name__)


async def terminate_error_server() -> bool:
    """If the error server is running, send it a message to get it to terminate.

    :returns: If we think it could be running.
    """
    try:
        json_text = await trio.to_thread.run_sync(user_errors.SERVER_INFO_FILE.read_text)
    except FileNotFoundError:
        LOGGER.info("No error server file, it's not running.")
        return False
    data: user_errors.ServerInfo = await trio.to_thread.run_sync(json.loads, json_text)
    del json_text

    with trio.move_on_after(10.0):
        port = data['port']
        LOGGER.info('Error server port: {}', port)
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/shutdown') as response:
                response.read()
        except urllib.error.URLError as exc:
            LOGGER.info("No response from error server, assuming it's dead: {}", exc.reason)
            return False
        else:
            # Wait for the file to be deleted.
            while user_errors.SERVER_INFO_FILE.exists():
                await trio.sleep(0.125)
            return False
    # noinspection PyUnreachableCode
    LOGGER.warning('Hit error server timeout, may still be running!')
    return True  # Hit our timeout.


@STEPS.add_step(prereq=[], results=[StepResource.ERROR_SERVER_TERMINATE])
async def step_terminate_error(exp_data: ExportData) -> None:
    """The error server must be terminated before copying the compiler."""
    maybe_running = await terminate_error_server()
    if maybe_running:
        pass   # TODO: Add warning message here.
