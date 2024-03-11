"""Write translation data for the compiler to use."""
import pickle
import pickletools

import trio.to_thread

from . import ExportData, STEPS, StepResource
import packages
import transtoken


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_set_error_translations(exp_data: ExportData) -> None:
    """Pass along the location of the current language file, for translating error messages."""
    filename = transtoken.CURRENT_LANG.value.ui_filename
    if filename is not None:
        exp_data.vbsp_conf.set_key(('Options', 'error_translations'), filename.as_posix())


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_dump_package_translations(exp_data: ExportData) -> None:
    """Write out all tokens defined in packages, for use in error messages."""
    def build_file(packset: packages.PackagesSet) -> bytes:
        """Build the pickle."""
        return pickletools.optimize(pickle.dumps([
            (pack.id, {
                tok_id: str(tok)
                for tok_id, tok in pack.additional_tokens.items()
            })
            for pack in packset.packages.values()
            if pack.additional_tokens  # Skip empty packages, saving some space.
        ], pickle.HIGHEST_PROTOCOL))

    pick = await trio.to_thread.run_sync(build_file, exp_data.packset)
    await trio.Path(exp_data.game.abs_path('bin/bee2/pack_translation.bin')).write_bytes(pick)
