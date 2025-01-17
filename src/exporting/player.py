"""Export player model configuration."""
from config.player import ExportPlayer
from exporting import ExportData, STEPS, StepResource
from packages import PlayerModel


@STEPS.add_step(prereq=[], results=[StepResource.CONFIG_DATA])
async def step_player_model(exp_data: ExportData) -> None:
    """Export player models."""
    conf: dict[str, ExportPlayer] = {}

    for player in exp_data.packset.all_obj(PlayerModel):
        conf[player.id] = ExportPlayer(
            model=player.model,
            pgun_skin=player.pgun_skin,
            voice_options=player.voice_options
        )
    exp_data.config = exp_data.config.with_cls_map(ExportPlayer, conf)
