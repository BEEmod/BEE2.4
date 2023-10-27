"""Adds voicelines dynamically into the map."""
from typing import Dict, List, Optional, Set, NamedTuple, Iterator, Tuple
from typing_extensions import TypeAlias
from decimal import Decimal
import itertools
import pickle

import srctools.logger
import trio

import vbsp
from precomp import corridor, options as vbsp_options, packing, conditions, rand
from BEE2_config import ConfigFile
from srctools import Keyvalues, Vec, VMF, Output, Entity

from precomp.collisions import Collisions
from quote_pack import ExportedQuote


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME = 'Voice Lines'

ADDED_BULLSEYES: Set[str] = set()

MidQuote: TypeAlias = Tuple[Keyvalues, bool, str]

# Special quote instances assoicated with an item/style.
# These are only added if the condition executes.
QUOTE_EVENTS: Dict[str, str] = {}  # id -> instance mapping

# The block of SP and coop voice data
QUOTE_DATA = Keyvalues('Quotes', [])

# The prefix for all voiceline instances.
INST_PREFIX = 'instances/bee2/voice/'

RESP_HAS_NAMES = {
    'death_goo': 'goo',
    'death_turret': 'turret',
    'death_laserfield': 'laserfield',
}


class PossibleQuote(NamedTuple):
    priority: int
    lines: List[Keyvalues]


# Create a fake instance to pass to condition flags. This way we can
# reuse all that logic, without breaking flags that check the instance.
fake_inst = VMF().create_ent(
    classname='func_instance',
    file='',
    angles='0 0 0',
    origin='0 0 0',
)


def has_responses(info: corridor.Info) -> bool:
    """Check if we have any valid 'response' data for Coop."""
    return info.is_coop and 'CoopResponses' in QUOTE_DATA


async def load() -> ExportedQuote:
    """Load the data from disk."""
    return await trio.to_thread.run_sync(
        pickle.loads,
        await trio.Path('bee2/voice.bin').read_bytes(),
    )


def encode_coop_responses(vmf: VMF, pos: Vec, allow_dings: bool, info: corridor.Info) -> None:
    """Write the coop responses information into the map."""
    config = ConfigFile('bee2/resp_voice.cfg', in_conf_folder=False)
    response_block = QUOTE_DATA.find_key('CoopResponses', or_blank=True)

    # Pass in whether to include dings or not.
    vmf.create_ent(
        'comp_scriptvar_setter',
        origin=pos,
        target='@glados',
        variable='BEE2_PLAY_DING',
        mode='const',
        # Allow overriding specifically for the response script.
        const=response_block.bool('use_dings', allow_dings),
    )

    for section in response_block:
        if not section.has_children():
            continue

        voice_attr = RESP_HAS_NAMES.get(section.name, '')
        if voice_attr and not info.has_attr(voice_attr):
            # This response category isn't present.
            continue

        # Use a custom entity to encode our information.
        ent = vmf.create_ent(
            'bee2_coop_response',
            origin=pos,
            type=section.name,
        )

        # section_data = []
        for index, line in enumerate(section):
            if not config.getboolean(section.name, "line_" + str(index), True):
                # It's disabled!
                continue
            ent[f'choreo{index:02}'] = line['choreo']


def mode_quotes(kv_block: Keyvalues, flag_set: Set[str]):
    """Get the quotes from a block which match the game mode."""

    for kv in kv_block:
        if kv.name == 'line':
            # Ones that apply to both modes
            yield kv
        elif kv.name.startswith('line_'):
            # Conditions applied to the name.
            # Check all are in the flags set.
            if flag_set.issuperset(kv.name.split('_')[1:]):
                yield kv


@conditions.make_result('QuoteEvent', valid_before=conditions.MetaCond.VoiceLine)
def res_quote_event(res: Keyvalues):
    """Enable a quote event. The given file is the default instance."""
    QUOTE_EVENTS[res['id'].casefold()] = res['file']

    return conditions.RES_EXHAUSTED


def find_group_quotes(
    coll: Collisions,
    info: corridor.Info,
    voice: ExportedQuote,
    group: Keyvalues,
    mid_quotes: List[List[MidQuote]],
    allow_mid_voices: bool,
    use_dings: bool,
    conf: ConfigFile,
    mid_name: str,
    player_flag_set: Set[str],
) -> Iterator[PossibleQuote]:
    """Scan through a group, looking for applicable quote options."""
    is_mid = (group.name == 'midchamber')

    if is_mid:
        group_id = 'MIDCHAMBER'
    else:
        group_id = group['name'].upper()

    all_quotes = list(group.find_all('quote'))
    valid_quotes = 0

    for quote in all_quotes:
        valid_quote = True
        for flag in quote:
            name = flag.name
            if name in ('priority', 'name', 'id', 'line') or name.startswith('line_'):
                # Not flags!
                continue
            if not conditions.check_test(flag, coll, info, voice, fake_inst):
                valid_quote = False
                break

        if not valid_quote:
            continue

        valid_quotes += 1

        poss_quotes: List[Keyvalues] = []
        line_mid_quotes: List[MidQuote] = []
        for line in mode_quotes(quote, player_flag_set):
            line_id = line['id', line['name', '']].casefold()

            # Check if the ID is enabled!
            if conf.get_bool(group_id, line_id, True):
                if allow_mid_voices and is_mid:
                    line_mid_quotes.append((line, use_dings, mid_name))
                else:
                    poss_quotes.append(line)
            else:
                LOGGER.info(
                    'Line "{}" is disabled..',
                    line['name', '??'],
                )

        if line_mid_quotes:
            mid_quotes.append(line_mid_quotes)

        if poss_quotes:
            yield PossibleQuote(
                quote.int('priority'),
                poss_quotes,
            )

    LOGGER.info('"{}": {}/{} quotes..', group_id, valid_quotes, len(all_quotes))


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
    use_dings=False,
    is_first=True,
    is_last=True,
    only_once=False,
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


def add_quote(
    vmf: VMF,
    quote: Keyvalues,
    targetname: str,
    quote_loc: Vec,
    style_vars: dict,
    use_dings: bool,
) -> None:
    """Add a quote to the map."""
    LOGGER.info('Adding quote: {}', quote)

    only_once = atomic = False
    cc_emit_name: Optional[str] = None
    start_ents: List[Entity] = []
    end_commands: List[Output] = []
    start_names: List[str] = []

    # The OnUser1 outputs always play the quote (PlaySound/Start), so you can
    # mix ent types in the same pack.

    for kv in quote:
        name = kv.name.casefold()

        if name == 'file':
            conditions.add_inst(
                vmf,
                file=INST_PREFIX + kv.value,
                origin=quote_loc,
                no_fixup=True,
            )
        elif name == 'choreo':
            # If the property has children, the children are a set of sequential
            # voice lines.
            # If the name is set to '@glados_line', the ents will be named
            # ('@glados_line', 'glados_line_2', 'glados_line_3', ...)
            start_names.append(targetname)
            if kv.has_children():
                secondary_name = targetname.lstrip('@') + '_'
                # Evenly distribute the choreo ents across the width of the
                # voice-line room.
                off = Vec(y=120 / (len(kv) + 1))
                start = quote_loc - (0, 60, 0) + off
                for ind, choreo_line in enumerate(kv, start=1):
                    is_first = (ind == 1)
                    is_last = (ind == len(kv))
                    name = (
                        targetname
                        if is_first else
                        secondary_name + str(ind)
                    )
                    choreo = add_choreo(
                        vmf,
                        choreo_line.value,
                        targetname=name,
                        loc=start + off * (ind - 1),
                        use_dings=use_dings,
                        is_first=is_first,
                        is_last=is_last,
                        only_once=only_once,
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
                        for out in end_commands:
                            choreo.add_out(out.copy())
                        end_commands.clear()
            else:
                # Add a single choreo command.
                choreo = add_choreo(
                    vmf,
                    kv.value,
                    targetname,
                    quote_loc,
                    use_dings=use_dings,
                    only_once=only_once,
                )
                start_ents.append(choreo)
                for out in end_commands:
                    choreo.add_out(out.copy())
                end_commands.clear()
        elif name == 'snd':
            start_names.append(targetname)

            snd = vmf.create_ent(
                classname='ambient_generic',
                spawnflags='49',  # Infinite Range, Starts Silent
                targetname=targetname,
                origin=quote_loc,
                message=kv.value,
                health='10',  # Volume
            )
            snd.add_out(
                Output(
                    'OnUser1',
                    targetname,
                    'PlaySound',
                    only_once=only_once,
                )
            )
            start_ents.append(snd)
        elif name == 'bullseye':
            add_bullseye(vmf, quote_loc, kv.value)
        elif name == 'cc_emit':
            # In Aperture Tag, this additional console command is used
            # to add the closed captions.
            # Store in a variable, so we can be sure to add the output
            # regardless of the property order.
            cc_emit_name = kv.value
        elif name == 'setstylevar':
            # Set this stylevar to True
            # This is useful so some styles can react to which line was
            # chosen.
            style_vars[kv.value.casefold()] = True
        elif name == 'packlist':
            packing.pack_list(vmf, kv.value)
        elif name == 'pack':
            if kv.has_children():
                packing.pack_files(vmf, *[
                    subprop.value
                    for subprop in
                    kv
                ])
            else:
                packing.pack_files(vmf, kv.value)
        elif name == 'choreo_name':
            # Change the targetname used for subsequent entities
            targetname = kv.value
        elif name == 'onlyonce':
            only_once = srctools.conv_bool(kv.value)
        elif name == 'atomic':
            atomic = srctools.conv_bool(kv.value)
        elif name == 'endcommand':
            if kv.bool('only_once'):
                end_commands.append(Output(
                    'OnCompletion',
                    kv['target'],
                    kv['input'],
                    kv['parm', ''],
                    kv.float('delay'),
                    only_once=True,
                ))
            else:
                end_commands.append(Output(
                    'OnCompletion',
                    kv['target'],
                    kv['input'],
                    kv['parm', ''],
                    kv.float('delay'),
                    times=kv.int('times', -1),
                ))

    if cc_emit_name:
        for ent in start_ents:
            ent.add_out(Output(
                'OnUser1',
                '@command',
                'Command',
                param='cc_emit ' + cc_emit_name,
            ))

    # If Atomic is true, after a line is started all variants
    # are blocked from playing.
    if atomic:
        for ent in start_ents:
            for name in start_names:
                if ent['targetname'] == name:
                    # Don't block yourself.
                    continue
                ent.add_out(Output(
                    'OnUser1',
                    name,
                    'Kill',
                    only_once=True,
                ))


def sort_func(quote: PossibleQuote):
    """The quotes will be sorted by their priority value."""
    # We use Decimal so it will adjust to whatever precision a user sets,
    # Without floating-point error.
    try:
        return Decimal(quote.priority)
    except ArithmeticError:
        # Default to priority 0
        return Decimal(0)


def get_studio_loc() -> Vec:
    """Return the location of the voice studio."""
    return Vec.from_str(QUOTE_DATA['quote_loc', '-10000 0 0'], x=-10000)


def add_voice(
    style_vars: dict,
    vmf: VMF,
    coll: Collisions,
    info: corridor.Info,
    voice: ExportedQuote,
    use_priority=True,
) -> None:
    """Add a voice line to the map."""
    from precomp.conditions.monitor import make_voice_studio
    LOGGER.info('Adding Voice Lines!')

    norm_config = ConfigFile('bee2/voice.cfg', in_conf_folder=False)
    mid_config = ConfigFile('bee2/mid_voice.cfg', in_conf_folder=False)

    quote_base = QUOTE_DATA['base', '']
    quote_loc = get_studio_loc()
    if quote_base:
        LOGGER.info('Adding Base instance!')
        conditions.add_inst(
            vmf,
            targetname='voice',
            file=INST_PREFIX + quote_base,
            origin=quote_loc,
        )

    # Either box in with nodraw, or place the voiceline studio.
    has_studio = make_voice_studio(vmf)

    bullsye_actor = vbsp_options.VOICE_STUDIO_ACTOR()
    if bullsye_actor and has_studio:
        ADDED_BULLSEYES.add(bullsye_actor)

    global_bullseye = QUOTE_DATA['bullseye', '']
    if global_bullseye:
        add_bullseye(vmf, quote_loc, global_bullseye)

    allow_mid_voices = not style_vars.get('nomidvoices', False)

    mid_quotes: List[List[MidQuote]] = []

    # Enable using the beep before and after choreo lines.
    allow_dings = srctools.conv_bool(QUOTE_DATA['use_dings', '0'])
    if allow_dings:
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

    # QuoteEvents allows specifying an instance for particular items,
    # so a voice line can be played at a certain time. It's only active
    # in certain styles, but uses the default if not set.
    for event in QUOTE_DATA.find_all('QuoteEvents', 'Event'):
        event_id = event['id', ''].casefold()
        # We ignore the config if no result was executed.
        if event_id and event_id in QUOTE_EVENTS:
            # Instances from the voiceline config are in this subfolder,
            # but not the default item - that's set from the conditions
            QUOTE_EVENTS[event_id] = INST_PREFIX + event['file']

    LOGGER.info('Quote events: {}', list(QUOTE_EVENTS.keys()))

    if has_responses(info):
        LOGGER.info('Generating responses data..')
        encode_coop_responses(vmf, quote_loc, allow_dings, info)

    for ind, file in enumerate(QUOTE_EVENTS.values()):
        if not file:
            continue
        conditions.add_inst(
            vmf,
            targetname='voice_event_' + str(ind),
            file=file,
            origin=quote_loc,
        )

    # Determine the flags that enable/disable specific lines based on which
    # players are used.
    player_model = vbsp.BEE2_config.get_val(
        'General', 'player_model', 'PETI',
    ).casefold()

    player_flags = {
        'sp': info.is_sp,
        'coop': info.is_coop,
        'atlas': info.is_coop or player_model == 'atlas',
        'pbody': info.is_coop or player_model == 'pbody',
        'bendy': info.is_sp and player_model == 'peti',
        'chell': info.is_sp and player_model == 'sp',
        'human': info.is_sp and player_model in ('peti', 'sp'),
        'robot': info.is_coop or player_model in ('atlas', 'pbody'),
    }
    # All which are True.
    player_flag_set = {val for val, flag in player_flags.items() if flag}

    # For each group, locate the voice lines.
    for group in itertools.chain(
        QUOTE_DATA.find_all('group'),
        QUOTE_DATA.find_all('midchamber'),
    ):

        quote_targetname = group['Choreo_Name', '@choreo']
        use_dings = group.bool('use_dings', allow_dings)

        possible_quotes = sorted(
            find_group_quotes(
                coll, info, voice,
                group,
                mid_quotes,
                use_dings=use_dings,
                allow_mid_voices=allow_mid_voices,
                conf=mid_config if group.name == 'midchamber' else norm_config,
                mid_name=quote_targetname,
                player_flag_set=player_flag_set,
            ),
            key=sort_func,
            reverse=True,
        )

        LOGGER.debug('Possible {}quotes:', 'mid ' if group.name == 'midchamber' else '')
        for quot in possible_quotes:
            LOGGER.debug('- {}', quot)

        if possible_quotes:
            choreo_loc = group.vec('choreo_loc', *quote_loc)

            if use_priority:
                chosen = possible_quotes[0].lines
            else:
                # Chose one of the quote blocks.
                chosen = rand.seed(b'VOICE_QUOTE_BLOCK', *[
                    prop['id', 'ID'] for quoteblock in possible_quotes
                    for prop in quoteblock.lines
                ]).choice(possible_quotes).lines

            # Use the IDs for the voice lines, so each quote block will chose different lines.
            rng = rand.seed(b'VOICE_QUOTE', *[
                prop['id', 'ID']
                for prop in
                chosen
            ])

            # Add one of the associated quotes
            add_quote(
                vmf,
                rng.choice(chosen),
                quote_targetname,
                choreo_loc,
                style_vars,
                use_dings,
            )

    if ADDED_BULLSEYES or QUOTE_DATA.bool('UseMicrophones'):
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

    LOGGER.info('{} Mid quotes', len(mid_quotes))
    for mid_lines in mid_quotes:
        line = rand.seed(b'mid_quote', *[name for item, ding, name in mid_lines]).choice(mid_lines)
        mid_item, use_ding, mid_name = line
        add_quote(vmf, mid_item, mid_name, quote_loc, style_vars, use_ding)

    LOGGER.info('Done!')
