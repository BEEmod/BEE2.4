"""Generate fizzler side materials."""
from __future__ import annotations
from pathlib import Path

from srctools.math import FrozenVec, format_float
import trio

from . import ExportData, STEPS, StepResource


# Material file used for fizzler sides.
# We use $decal because that ensures it's displayed over brushes,
# if there's base slabs or the like.
# We have to use SolidEnergy, so it fades out with fizzlers.
FIZZLER_EDGE_MAT = '''\
SolidEnergy
{{
$basetexture "sprites/laserbeam"
$flowmap "effects/fizzler_flow"
$flowbounds "BEE2/fizz/fizz_side"
$flow_noise_texture "effects/fizzler_noise"
$additive 1
$translucent 1
$decal 1
$flow_color "[{}]"
$flow_vortex_color "[{}]"
'''

# Non-changing components.
FIZZLER_EDGE_MAT_PROXY = '''\
$offset "[0 0]"
Proxies
{
FizzlerVortex
{
}
MaterialModify
{
}
}
}
'''


@STEPS.add_step(
    prereq=[StepResource.VCONF_DATA],
    results=[StepResource.RES_SPECIAL],
)
async def generate_fizzler_sides(exp_data: ExportData) -> None:
    """Create the VMTs used for fizzler sides."""
    fizz_colors: dict[FrozenVec, tuple[float, str]] = {}
    mat_path = trio.Path(exp_data.game.abs_path('bee2/materials/bee2/fizz_sides/'))
    for brush_conf in exp_data.vbsp_conf.find_all('Fizzlers', 'Fizzler', 'Brush'):
        fizz_color = brush_conf['Side_color', '']
        if fizz_color:
            fizz_colors[FrozenVec.from_str(fizz_color)] = (
                brush_conf.float('side_alpha', 1.0),
                brush_conf['side_vortex', fizz_color]
            )

    if fizz_colors:
        await mat_path.mkdir(parents=True, exist_ok=True)

    async def make_mat(color: FrozenVec, alpha: float, vortex_color: str) -> None:
        """Create a material."""
        r = round(color.x * 255)
        g = round(color.y * 255)
        b = round(color.z * 255)
        dest = mat_path / f'side_color_{r:02X}{g:02X}{b:02X}.vmt'
        exp_data.resources.add(Path(dest))

        async with await dest.open('w') as f:
            await f.write(FIZZLER_EDGE_MAT.format(color, vortex_color))
            if alpha != 1:
                # Add the alpha value, but replace 0.5 -> .5 to save a char.
                await f.write(f'$outputintensity {format_float(alpha)}\n')
            await f.write(FIZZLER_EDGE_MAT_PROXY)

    async with trio.open_nursery() as nursery:
        for fizz_color_vec, (alpha, fizz_vortex_color) in fizz_colors.items():
            nursery.start_soon(make_mat, fizz_color_vec, alpha, fizz_vortex_color)
