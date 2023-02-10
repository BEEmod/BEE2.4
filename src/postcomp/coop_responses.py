from typing import Dict, List, Optional

from srctools import Entity
import srctools.logger
from hammeraddons.bsp_transform import Context, trans

LOGGER = srctools.logger.get_logger(__name__)


@trans('BEE2: Coop Responses')
def generate_coop_responses(ctx: Context) -> None:
    """If the entities are present, add the coop response script."""
    responses: Dict[str, List[str]] = {}
    for response in ctx.vmf.by_class['bee2_coop_response']:
        responses[response['type']] = [
            value for key, value in response.items()
            if key.startswith('choreo')
        ]
        response.remove()
        
    if not responses:
        return
   
    script = ["BEE2_RESPONSES <- {"]
    for response_type, lines in sorted(responses.items()):
        script.append(f'\t{response_type} = [')
        for line in lines:
            script.append(f'\t\tCreateSceneEntity("{line}"),')
        script.append('\t],')
    script.append('};')

    # We want to write this onto the '@glados' entity.
    ent: Optional[Entity] = None
    for ent in ctx.vmf.by_target['@glados']:
        ctx.add_code(ent, '\n'.join(script))
        # Also include the actual script.
        split_script = ent['vscripts'].split()
        split_script.append('bee2/coop_responses.nut')
        ent['vscripts'] = ' '.join(split_script)

    if ent is None:
        LOGGER.warning('Response scripts present, but @glados is not!')
