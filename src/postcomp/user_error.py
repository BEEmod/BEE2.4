"""Inject VScript if a user error occurs."""
from hammeraddons.bsp_transform import Context, trans
from utils import COMPILE_USER_ERROR_PAGE

# Repeatedly show the URL whenever the user switches to the page.
# If it returns true, it has popped up the Steam Overlay.
# We then trigger the puzzlemaker command to switch in the background, behind the webpage.
# That pauses, so if you tab back it'll repeat.
SCRIPT_TEMPLATE = '''\
function Think() {
\tif (ScriptSteamShowURL("%")) SendToConsole("puzzlemaker_show 1");
}
'''


@trans('BEE2: User Error')
def generate_coop_responses(ctx: Context) -> None:
    """If the map contains the marker entity indicating a user error, inject the VScript."""
    for ent in ctx.vmf.by_class['bee2_user_error']:
        ent['thinkfunction'] = 'Think'
        ent['classname'] = 'info_player_start'
        ctx.add_code(ent, SCRIPT_TEMPLATE.replace('%', COMPILE_USER_ERROR_PAGE.absolute().as_uri()))
