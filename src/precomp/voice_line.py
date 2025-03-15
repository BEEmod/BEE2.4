"""Adds voicelines dynamically into the map."""
from __future__ import annotations
from collections.abc import Iterator
from decimal import Decimal
import itertools
import pickle

from srctools import Keyvalues, Vec, VMF, Output, Entity
import srctools.logger
import attrs
import trio

from BEE2_config import ConfigFile
from precomp import corridor, conditions, rand
from precomp.collisions import Collisions
from precomp.conditions.monitor import make_voice_studio
from quote_pack import Line, Quote, QuoteInfo, LineCriteria, Response, MIDCHAMBER_ID
import config.player
import utils
import vbsp


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME = 'Voice Lines'

ADDED_BULLSEYES: set[str] = set()

# Special quote instances associated with an item/style.
# These are only added if the condition executes.
QUOTE_EVENTS: dict[str, str] = {}  # id -> instance mapping

# The prefix for all voice-line instances.
INST_PREFIX = 'instances/bee2/voice/'

RESP_HAS_NAMES = {
    Response.DEATH_GOO: 'goo',
    Response.DEATH_TURRET: 'turret',
    Response.DEATH_LASERFIELD: 'laserfield',
}


@attrs.frozen
class PossibleQuote:
    """Bundle up the priority together with a list of filtered lines."""
    priority: int
    lines: list[Line]


# Create a fake instance to pass to condition flags. This way we can
# reuse all that logic, without breaking flags that check the instance.
fake_inst = VMF().create_ent(
    classname='func_instance',
    file='',
    angles='0 0 0',
    origin='0 0 0',
)


async def load() -> QuoteInfo:
    """Load the data from disk."""
    return await trio.to_thread.run_sync(
        pickle.loads,
        await trio.Path('bee2/voice.bin').read_bytes(),
    )


def encode_coop_responses(vmf: VMF, pos: Vec, voice: QuoteInfo, info: corridor.Info) -> None:
    """Write the coop responses information into the map."""
    config = ConfigFile('bee2/resp_voice.cfg', in_conf_folder=False)

    # Pass in whether to include dings or not.
    vmf.create_ent(
        'comp_scriptvar_setter',
        origin=pos,
        target='@glados',
        variable='BEE2_PLAY_DING',
        mode='const',
        # Allow overriding specifically for the response script.
        const=voice.response_use_dings,
    )

    for response, lines in voice.responses.items():
        voice_attr = RESP_HAS_NAMES.get(response, '')
        if voice_attr and not info.has_attr(voice_attr):
            # This response category isn't present.
            continue

        # Use a custom entity to encode our information.
        ent = vmf.create_ent(
            'bee2_coop_response',
            origin=pos,
            type=response.name.casefold(),
        )

        index = 1
        for line_ind, line in enumerate(lines):
            if not config.getboolean(response.name, f"line_{line_ind}", True):
                # It's disabled!
                continue
            # TODO: Change this to use add_line(), so any kind can be used.
            for scene in line.scenes:
                for choreo in scene.scenes:
                    ent[f'choreo{index:02}'] = choreo
                    index += 1


@conditions.make_result('QuoteEvent', valid_before=conditions.MetaCond.VoiceLine)
def res_quote_event(res: Keyvalues) -> object:
    """Enable a quote event.

    Options:
    * `id`: The quote event ID to enable.
    * `file`: If no quote event is present with the specified ID, this instance is placed instead.
    """
    QUOTE_EVENTS[res['id'].casefold()] = res['file']

    return conditions.RES_EXHAUSTED


def find_group_quotes(
    coll: Collisions,
    info: corridor.Info,
    voice: QuoteInfo,
    quotes: list[Quote],
    group_id: str,
    conf: ConfigFile,
    player_flag_set: set[LineCriteria],
) -> Iterator[PossibleQuote]:
    """Scan through a group, looking for applicable quote options."""
    valid_quotes = 0

    for quote in quotes:
        valid_quote = True
        for test in quote.tests:
            if not conditions.check_test(test, coll, info, voice, fake_inst):
                valid_quote = False
                LOGGER.debug('Skip: {}', quote.name)
                break

        if not valid_quote:
            continue

        valid_quotes += 1

        poss_quotes: list[Line] = []
        for line in quote.filter_criteria(player_flag_set):
            # Check if the ID is enabled!
            if conf.get_bool(group_id, line.id, True):
                poss_quotes.append(line)
            else:
                LOGGER.info('Line "{}" is disabled..', line.name)

        if poss_quotes:
            yield PossibleQuote(quote.priority, poss_quotes)

    LOGGER.info('"{}": {}/{} quotes..', group_id, valid_quotes, len(quotes))


def add_bullseye(vmf: VMF, quote_loc: Vec, name: str) -> None:
    """Add a bullseye to the map."""
    # Cave's voice lines require a special named bullseye to
    # work correctly.
    # Don't add the same one more than once.
    if name not in ADDED_BULLSEYES:
        vmf.create_ent(
            classname='npc_bullseye',
            # Not solid, Take No Damage, Think outside PVS
            spawnflags='222224',
            targetname=name,
            origin=quote_loc - (0, 0, 16),
            angles='0 0 0',
        )
        ADDED_BULLSEYES.add(name)


def add_choreo(
    vmf: VMF,
    c_line: str,
    targetname: str,
    loc: Vec,
    use_dings: bool = False,
    is_first: bool = True,
    is_last: bool = True,
    only_once: bool = False,
) -> Entity:
    """Create a choreo scene."""
    # Add this to the beginning, since all scenes need it...
    if not c_line.startswith('scenes/'):
        c_line = 'scenes/' + c_line

    choreo = vmf.create_ent(
        classname='logic_choreographed_scene',
        targetname=targetname,
        origin=loc,
        scenefile=c_line,
        busyactor="1",  # Wait for actor to stop talking
        onplayerdeath='0',
    )

    if use_dings:
        # Play ding_on/off before and after the line.
        if is_first:
            choreo.add_out(
                Output('OnUser1', '@ding_on', 'Start', only_once=only_once),
                Output('OnUser1', targetname, 'Start', delay=0.2, only_once=only_once),
            )
        if is_last:
            choreo.add_out(
                Output('OnCompletion', '@ding_off', 'Start'),
            )
    elif is_first:
        choreo.add_out(
            Output('OnUser1', targetname, 'Start', only_once=only_once)
        )

    if only_once:
        # Remove each section after it's played..
        choreo.add_out(
            Output('OnCompletion', '!self', 'Kill'),
        )

    return choreo


def add_line(
    vmf: VMF,
    line: Line,
    targetname: str,
    quote_loc: Vec,
    style_vars: dict[str, bool],
    use_dings: bool,
) -> None:
    """Add a line to the map."""
    LOGGER.info('Adding quote: {}', line)

    start_ents: list[Entity] = []
    start_names: list[str] = []

    # The OnUser1 outputs always play the quote (PlaySound/Start), so you can
    # mix ent types in the same pack.

    for bullsye in line.bullseyes:
        add_bullseye(vmf, quote_loc, bullsye)
    for inst in line.instances:
        conditions.add_inst(
            vmf,
            file=INST_PREFIX + inst,
            origin=quote_loc,
            no_fixup=True,
        )
    for scene in line.scenes:
        # If the property has children, the children are a set of sequential
        # voice lines.
        # If the name is set to '@glados_line', the ents will be named
        # ('@glados_line', 'glados_line_2', 'glados_line_3', ...)
        primary_name = scene.name or targetname

        start_names.append(primary_name)
        secondary_name = primary_name.lstrip('@') + '_'
        # Evenly distribute the choreo ents across the width of the
        # voice-line room.
        off = Vec(y=120 / (len(line.scenes) + 1))
        start = quote_loc - (0, 60, 0) + off
        for ind, choreo_line in enumerate(scene.scenes, start=1):
            is_first = (ind == 1)
            is_last = (ind == len(scene.scenes))
            name = (
                primary_name
                if is_first else
                f"{secondary_name}{ind}"
            )
            choreo = add_choreo(
                vmf,
                choreo_line,
                targetname=name,
                loc=start + off * (ind - 1),
                use_dings=use_dings,
                is_first=is_first,
                is_last=is_last,
                only_once=line.only_once,
            )
            # Add a IO command to start the next one.
            if not is_last:
                choreo.add_out(Output(
                    'OnCompletion',
                    secondary_name + str(ind + 1),
                    'Start',
                    delay=0.1,
                ))
            if is_first:  # Ensure this works with cc_emit
                start_ents.append(choreo)
            if is_last:
                for out in scene.end_commands:
                    choreo.add_out(out.copy())

    for snd_name in line.sounds:
        start_names.append(targetname)

        snd = vmf.create_ent(
            classname='ambient_generic',
            spawnflags='49',  # Infinite Range, Starts Silent
            targetname=targetname,
            origin=quote_loc,
            message=snd_name,
            health='10',  # Volume
        )
        snd.add_out(
            Output(
                'OnUser1',
                targetname,
                'PlaySound',
                only_once=line.only_once,
            )
        )
        start_ents.append(snd)
    for var_name in line.set_stylevars:
        # Set this stylevar to True
        # This is useful so some styles can react to which line was
        # chosen.
        style_vars[var_name] = True

    # In Aperture Tag, this additional console command is used
    # to add the closed captions.
    if line.caption_name:
        for ent in start_ents:
            ent.add_out(Output(
                'OnUser1',
                '@command',
                'Command',
                param=f'cc_emit {line.caption_name}',
            ))

    # If Atomic is true, after a line is started all variants
    # are blocked from playing.
    if line.atomic:
        for ent, name in itertools.product(start_ents, start_names):
            if ent['targetname'] == name:
                # Don't block yourself.
                continue
            ent.add_out(Output('OnUser1', name, 'Kill', only_once=True))


def sort_func(quote: PossibleQuote) -> Decimal:
    """The quotes will be sorted by their priority value."""
    # We use Decimal so that it will adjust to whatever precision a user sets,
    # Without floating-point error.
    try:
        return Decimal(quote.priority)
    except ArithmeticError:
        # Default to priority 0
        return Decimal(0)


def add_voice(
    style_vars: dict[str, bool],
    vmf: VMF,
    coll: Collisions,
    info: corridor.Info,
    voice: QuoteInfo,
    use_priority: bool = True,
) -> None:
    """Add a voice line to the map."""
    if not voice.id:
        LOGGER.info('No voiceline set!')
        return
    LOGGER.info('Adding Voice Line: {}', voice.id)

    norm_config = ConfigFile('bee2/voice.cfg', in_conf_folder=False)
    mid_config = ConfigFile('bee2/mid_voice.cfg', in_conf_folder=False)

    quote_loc = voice.position
    if voice.base_inst:
        LOGGER.info('Adding Base instance!')
        conditions.add_inst(
            vmf,
            targetname='voice',
            file=INST_PREFIX + voice.base_inst,
            origin=quote_loc,
        )

    # Either box in with nodraw, or place the voice-line studio.
    has_studio = make_voice_studio(vmf, voice)

    if has_studio and voice.monitor is not None and voice.monitor.studio_actor:
        ADDED_BULLSEYES.add(voice.monitor.studio_actor)

    if voice.global_bullseye:
        add_bullseye(vmf, quote_loc, voice.global_bullseye)

    allow_mid_voices = not style_vars.get('nomidvoices', False)

    # Enable using the beep before and after choreo lines.
    if voice.use_dings or voice.response_use_dings:
        vmf.create_ent(
            classname='logic_choreographed_scene',
            targetname='@ding_on',
            origin=quote_loc + (-8, -16, 0),
            scenefile='scenes/npc/glados_manual/ding_on.vcd',
            busyactor="1",  # Wait for actor to stop talking
            onplayerdeath='0',
        )
        vmf.create_ent(
            classname='logic_choreographed_scene',
            targetname='@ding_off',
            origin=quote_loc + (8, -16, 0),
            scenefile='scenes/npc/glados_manual/ding_off.vcd',
            busyactor="1",  # Wait for actor to stop talking
            onplayerdeath='0',
        )

    if info.is_coop and voice.responses:
        LOGGER.info('Generating responses data..')
        encode_coop_responses(vmf, quote_loc, voice, info)

    # QuoteEvents allows specifying an instance for particular items,
    # so a voice line can be played at a certain time. It's only active
    # in certain styles, but uses the default if not set.
    for ind, (event_id, filename) in enumerate(QUOTE_EVENTS.items(), start=1):
        try:
            event = voice.events[event_id.casefold()]
        except KeyError:
            pass  # No override, use default from condition.
        else:
            # Instances from the voiceline config are in this subfolder,
            # but not the default item - that's set from the conditions.
            filename = INST_PREFIX + event.file
        conditions.add_inst(
            vmf,
            targetname=f'voice_event_{ind}',
            file=filename,
            origin=quote_loc,
        )

    # Determine the flags that enable/disable specific lines based on which
    # players are used. Silently ignore if this isn't found, the player-model-setter
    # has already warned.
    player_flags = {
        LineCriteria.SP: info.is_sp,
        LineCriteria.COOP: info.is_coop,
    }
    if info.is_coop:
        # No player model setting for coop, so this is hardcoded.
        player_flags |= {
            LineCriteria.ATLAS: True,
            LineCriteria.PBODY: True,
            LineCriteria.ROBOT: True,

            LineCriteria.BENDY: False,
            LineCriteria.CHELL: False,
            LineCriteria.HUMAN: False,
        }
    else:
        try:
            player_id = utils.obj_id(vbsp.BEE2_config.get_val(
                'General', 'player_model_id', 'PETI',
            ))
            player = config.COMPILER.get_cur_conf(config.player.ExportPlayer, player_id, ValueError)
        except ValueError:
            # Not found, hardcode SP defaults.
            player_flags |= {
                LineCriteria.BENDY: True,
                LineCriteria.HUMAN: True,

                LineCriteria.ATLAS: False,
                LineCriteria.PBODY: False,
                LineCriteria.CHELL: False,
                LineCriteria.ROBOT: False,
            }
        else:
            player_flags |= player.voice_options
    LOGGER.info('Player voice flags: {}', player_flags)
    # All which are True.
    player_flag_set = {val for val, flag in player_flags.items() if flag}

    # For each group, locate the voice lines.
    for group in voice.groups.values():
        possible_quotes = sorted(
            find_group_quotes(
                coll, info, voice,
                group.quotes,
                group_id=group.id,
                conf=norm_config,
                player_flag_set=player_flag_set,
            ),
            key=sort_func,
            reverse=True,
        )

        LOGGER.debug('Possible quotes:')
        for quot in possible_quotes:
            LOGGER.debug('- {}', quot)

        if possible_quotes:
            if use_priority:
                chosen = possible_quotes[0].lines
            else:
                # Chose one of the quote blocks.
                chosen = rand.seed(b'VOICE_QUOTE_BLOCK', *[
                    line.id
                    for quoteblock in possible_quotes
                    for line in quoteblock.lines
                ]).choice(possible_quotes).lines

            # Use the IDs for the voice lines, so each quote block will choose different lines.
            rng = rand.seed(b'VOICE_QUOTE', *[
                line.id
                for line in chosen
            ])

            # Add one of the associated quotes
            add_line(
                vmf,
                rng.choice(chosen),
                group.ent_name,
                group.loc_override if group.loc_override is not None else quote_loc,
                style_vars,
                group.use_dings_override if group.use_dings_override is not None else voice.use_dings,
            )

    if allow_mid_voices:
        for mid_lines in find_group_quotes(
            coll, info, voice, voice.midchamber,
            group_id=MIDCHAMBER_ID,
            conf=mid_config,
            player_flag_set=player_flag_set,
        ):
            rng = rand.seed(b'mid_quote', *[line.id for line in mid_lines.lines])
            add_line(
                vmf,
                rng.choice(mid_lines.lines),
                '@midchamber',
                quote_loc,
                style_vars,
                voice.use_dings,
            )

    if ADDED_BULLSEYES or voice.use_microphones:
        # Add microphones that broadcast audio directly at players.
        # This ensures it is heard regardless of location.
        # This is used for Cave and core Wheatley.
        LOGGER.info('Using microphones...')
        if info.is_sp:
            vmf.create_ent(
                classname='env_microphone',
                targetname='player_speaker_sp',
                speakername='!player',
                maxRange='386',
                origin=quote_loc,
            )
        else:
            vmf.create_ent(
                classname='env_microphone',
                targetname='player_speaker_blue',
                speakername='!player_blue',
                maxRange='386',
                origin=quote_loc,
            )
            vmf.create_ent(
                classname='env_microphone',
                targetname='player_speaker_orange',
                speakername='!player_orange',
                maxRange='386',
                origin=quote_loc,
            )

    LOGGER.info('Done!')
