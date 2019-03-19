"""Adds voicelines dynamically into the map."""
import itertools
import os
import random
from collections import namedtuple
from decimal import Decimal
from typing import List, Set

import conditions.monitor
import packing
import srctools.logger
import vbsp
import vbsp_options
from BEE2_config import ConfigFile
from srctools import Property, Vec, VMF, Output, Entity


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME = 'Voice Lines'

map_attr = {}
style_vars = {}

ADDED_BULLSEYES = set()

# Special quote instances assoicated with an item/style.
# These are only added if the condition executes.
QUOTE_EVENTS = {}  # id -> instance mapping

# The block of SP and coop voice data
QUOTE_DATA = Property('Quotes', [])

ALLOW_MID_VOICES = False
vmf_file = None  # type: VMF

# The prefix for all voiceline instances.
INST_PREFIX = 'instances/bee2/voice/'

# The location of the responses script.
RESP_LOC = 'bee2/inject/response_data.nut'

RESP_HAS_NAMES = {
    'death_goo': 'goo',
    'death_turret': 'turret',
    'death_laserfield': 'laserfield',
}

PossibleQuote = namedtuple('PossibleQuote', 'priority, lines')


# Create a fake instance to pass to condition flags. This way we can
# reuse all that logic, without breaking flags that check the instance.
fake_inst = VMF().create_ent(
    classname='func_instance',
    file='',
    angles='0 0 0',
    origin='0 0 0',
)


def has_responses():
    """Check if we have any valid 'response' data for Coop."""
    return vbsp.GAME_MODE == 'COOP' and 'CoopResponses' in QUOTE_DATA


def generate_resp_script(file, allow_dings):
    """Write the responses section into a file."""
    use_dings = allow_dings

    config = ConfigFile('bee2/resp_voice.cfg', in_conf_folder=False)
    file.write("BEE2_RESPONSES <- {\n")
    for section in QUOTE_DATA.find_key('CoopResponses', []):
        if not section.has_children() and section.name == 'use_dings':
            # Allow overriding specifically for the response script
            use_dings = srctools.conv_bool(section.value, allow_dings)
            continue

        voice_attr = RESP_HAS_NAMES.get(section.name, '')
        if voice_attr and not map_attr[voice_attr]:
            continue
            # This response catagory isn't present

        section_data = ['\t{} = [\n'.format(section.name)]
        for index, line in enumerate(section):
            if not config.getboolean(section.name, "line_" + str(index), True):
                # It's disabled!
                continue
            section_data.append(
                '\t\tCreateSceneEntity("{}"),\n'.format(line['choreo'])
            )
        if len(section_data) != 1:
            for line in section_data:
                file.write(line)
            file.write('\t],\n')
    file.write('}\n')

    file.write('BEE2_PLAY_DING = {};\n'.format(
        'true' if use_dings else 'false'
    ))


def mode_quotes(prop_block: Property, flag_set: Set[str]):
    """Get the quotes from a block which match the game mode."""

    for prop in prop_block:
        if prop.name == 'line':
            # Ones that apply to both modes
            yield prop
        elif prop.name.startswith('line_'):
            # Conditions applied to the name.
            # Check all are in the flags set.
            if flag_set.issuperset(prop.name.split('_')[1:]):
                yield prop


@conditions.make_result('QuoteEvent')
def res_quote_event(res: Property):
    """Enable a quote event. The given file is the default instance."""
    QUOTE_EVENTS[res['id'].casefold()] = res['file']

    return conditions.RES_EXHAUSTED


def find_group_quotes(group, mid_quotes, use_dings, conf, mid_name, player_flag_set):
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
            if not conditions.check_flag(flag, fake_inst):
                valid_quote = False
                break

        if not valid_quote:
            continue

        valid_quotes += 1

        poss_quotes = []
        line_mid_quotes = []
        for line in mode_quotes(quote, player_flag_set):
            line_id = line['id', line['name', '']].casefold()

            # Check if the ID is enabled!
            if conf.get_bool(group_id, line_id, True):
                if ALLOW_MID_VOICES and is_mid:
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
                quote['priority', '0'],
                poss_quotes,
            )

    LOGGER.info('"{}": {}/{} quotes..', group_id, valid_quotes, len(all_quotes))


def add_bullseye(quote_loc: Vec, name: str):
    """Add a bullseye to the map."""
    # Cave's voice lines require a special named bullseye to
    # work correctly.
    # Don't add the same one more than once.
    if name not in ADDED_BULLSEYES:
        vmf_file.create_ent(
            classname='npc_bullseye',
            # Not solid, Take No Damage, Think outside PVS
            spawnflags='222224',
            targetname=name,
            origin=quote_loc - (0, 0, 16),
            angles='0 0 0',
        )
        ADDED_BULLSEYES.add(name)


def add_choreo(
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

    choreo = vmf_file.create_ent(
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


def add_quote(quote: Property, targetname, quote_loc: Vec, use_dings=False):
    """Add a quote to the map."""
    LOGGER.info('Adding quote: {}', quote)

    only_once = atomic = False
    cc_emit_name = None
    start_ents = []  # type: List[Entity]
    end_commands = []
    start_names = []

    # The OnUser1 outputs always play the quote (PlaySound/Start), so you can
    # mix ent types in the same pack.

    for prop in quote:
        name = prop.name.casefold()

        if name == 'file':
            vmf_file.create_ent(
                classname='func_instance',
                targetname='',
                file=INST_PREFIX + prop.value,
                origin=quote_loc,
                fixup_style='2',  # No fixup
            )
        elif name == 'choreo':
            # If the property has children, the children are a set of sequential
            # voice lines.
            # If the name is set to '@glados_line', the ents will be named
            # ('@glados_line', 'glados_line_2', 'glados_line_3', ...)
            start_names.append(targetname)
            if prop.has_children():
                secondary_name = targetname.lstrip('@') + '_'
                # Evenly distribute the choreo ents across the width of the
                # voice-line room.
                off = Vec(y=120 / (len(prop) + 1))
                start = quote_loc - (0, 60, 0) + off
                for ind, choreo_line in enumerate(prop, start=1):  # type: int, Property
                    is_first = (ind == 1)
                    is_last = (ind == len(prop))
                    name = (
                        targetname
                        if is_first else
                        secondary_name + str(ind)
                    )
                    choreo = add_choreo(
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
                    prop.value,
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

            snd = vmf_file.create_ent(
                classname='ambient_generic',
                spawnflags='49',  # Infinite Range, Starts Silent
                targetname=targetname,
                origin=quote_loc,
                message=prop.value,
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
            add_bullseye(quote_loc, prop.value)
        elif name == 'cc_emit':
            # In Aperture Tag, this additional console command is used
            # to add the closed captions.
            # Store in a variable, so we can be sure to add the output
            # regardless of the property order.
            cc_emit_name = prop.value
        elif name == 'setstylevar':
            # Set this stylevar to True
            # This is useful so some styles can react to which line was
            # chosen.
            style_vars[prop.value.casefold()] = True
        elif name == 'packlist':
            packing.pack_list(vmf_file, prop.value)
        elif name == 'pack':
            if prop.has_children():
                packing.pack_files(vmf_file, *[
                    subprop.value
                    for subprop in
                    prop
                ])
            else:
                packing.pack_files(vmf_file, prop.value)
        elif name == 'choreo_name':
            # Change the targetname used for subsequent entities
            targetname = prop.value
        elif name == 'onlyonce':
            only_once = srctools.conv_bool(prop.value)
        elif name == 'atomic':
            atomic = srctools.conv_bool(prop.value)
        elif name == 'endcommand':
            end_commands.append(Output(
                'OnCompletion',
                prop['target'],
                prop['input'],
                prop['parm', ''],
                prop.float('delay'),
                only_once=prop.bool('only_once'),
                times=prop.int('times', -1),
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
    except ValueError:
        # Default to priority 0
        return Decimal(0)


def get_studio_loc() -> Vec:
    """Return the location of the voice studio."""
    return Vec.from_str(QUOTE_DATA['quote_loc', '-10000 0 0'], x=-10000)


def add_voice(
        has_items: dict,
        style_vars_: dict,
        vmf_file_: VMF,
        map_seed: str,
        use_priority=True,
):
    """Add a voice line to the map."""
    global ALLOW_MID_VOICES, vmf_file, map_attr, style_vars
    LOGGER.info('Adding Voice Lines!')

    vmf_file = vmf_file_
    map_attr = has_items
    style_vars = style_vars_

    norm_config = ConfigFile('bee2/voice.cfg', in_conf_folder=False)
    mid_config = ConfigFile('bee2/mid_voice.cfg', in_conf_folder=False)

    quote_base = QUOTE_DATA['base', False]
    quote_loc = get_studio_loc()
    if quote_base:
        LOGGER.info('Adding Base instance!')
        vmf_file.create_ent(
            classname='func_instance',
            targetname='voice',
            file=INST_PREFIX + quote_base,
            angles='0 0 0',
            origin=quote_loc,
            fixup_style='0',
        )

    # Either box in with nodraw, or place the voiceline studio.
    has_studio = conditions.monitor.make_voice_studio(vmf_file)

    bullsye_actor = vbsp_options.get(str, 'voice_studio_actor')
    if bullsye_actor and has_studio:
        ADDED_BULLSEYES.add(bullsye_actor)

    global_bullseye = QUOTE_DATA['bullseye', '']
    if global_bullseye:
        add_bullseye(quote_loc, global_bullseye)

    ALLOW_MID_VOICES = not style_vars.get('nomidvoices', False)

    mid_quotes = []

    # Enable using the beep before and after choreo lines.
    allow_dings = srctools.conv_bool(QUOTE_DATA['use_dings', '0'])
    if allow_dings:
        vmf_file.create_ent(
            classname='logic_choreographed_scene',
            targetname='@ding_on',
            origin=quote_loc + (-8, -16, 0),
            scenefile='scenes/npc/glados_manual/ding_on.vcd',
            busyactor="1",  # Wait for actor to stop talking
            onplayerdeath='0',
        )
        vmf_file.create_ent(
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

    if has_responses():
        LOGGER.info('Generating responses data..')
        with open(RESP_LOC, 'w') as f:
            generate_resp_script(f, allow_dings)
    else:
        LOGGER.info('No responses data..')
        try:
            os.remove(RESP_LOC)
        except FileNotFoundError:
            pass

    for ind, file in enumerate(QUOTE_EVENTS.values()):
        if not file:
            continue
        vmf_file.create_ent(
            classname='func_instance',
            targetname='voice_event_' + str(ind),
            file=file,
            angles='0 0 0',
            origin=quote_loc,
            fixup_style='0',
        )

    # Determine the flags that enable/disable specific lines based on which
    # players are used.
    player_model = vbsp.BEE2_config.get_val(
        'General', 'player_model', 'PETI',
    ).casefold()

    is_coop = (vbsp.GAME_MODE == 'COOP')
    is_sp = (vbsp.GAME_MODE == 'SP')

    player_flags = {
        'sp': is_sp,
        'coop': is_coop,
        'atlas': is_coop or player_model == 'atlas',
        'pbody': is_coop or player_model == 'pbody',
        'bendy': is_sp and player_model == 'peti',
        'chell': is_sp and player_model == 'sp',
        'human': is_sp and player_model in ('peti', 'sp'),
        'robot': is_coop or player_model in ('atlas', 'pbody'),
    }
    # All which are True.
    player_flag_set = {val for val, flag in player_flags.items() if flag}

    # For each group, locate the voice lines.
    for group in itertools.chain(
        QUOTE_DATA.find_all('group'),
        QUOTE_DATA.find_all('midchamber'),
    ):  # type: Property

        quote_targetname = group['Choreo_Name', '@choreo']
        use_dings = group.bool('use_dings', allow_dings)

        possible_quotes = sorted(
            find_group_quotes(
                group,
                mid_quotes,
                use_dings,
                conf=mid_config if group.name == 'midchamber' else norm_config,
                mid_name=quote_targetname,
                player_flag_set=player_flag_set,
            ),
            key=sort_func,
            reverse=True,
        )

        if possible_quotes:
            choreo_loc = group.vec('choreo_loc', *quote_loc)

            if use_priority:
                chosen = possible_quotes[0].lines
            else:
                # Chose one of the quote blocks..
                random.seed('{}-VOICE_QUOTE_{}'.format(
                    map_seed,
                    len(possible_quotes),
                ))
                chosen = random.choice(possible_quotes).lines

            # Join the IDs for
            # the voice lines to the map seed,
            # so each quote block will chose different lines.
            random.seed(map_seed + '-VOICE_LINE_' + '|'.join(
                prop['id', 'ID']
                for prop in
                chosen
            ))

            # Add one of the associated quotes
            add_quote(
                random.choice(chosen),
                quote_targetname,
                choreo_loc,
                use_dings,
            )

    if ADDED_BULLSEYES or QUOTE_DATA.bool('UseMicrophones'):
        # Add microphones that broadcast audio directly at players.
        # This ensures it is heard regardless of location.
        # This is used for Cave and core Wheatley.
        LOGGER.info('Using microphones...')
        if vbsp.GAME_MODE == 'SP':
            vmf_file.create_ent(
                classname='env_microphone',
                targetname='player_speaker_sp',
                speakername='!player',
                maxRange='386',
                origin=quote_loc,
            )
        else:
            vmf_file.create_ent(
                classname='env_microphone',
                targetname='player_speaker_blue',
                speakername='!player_blue',
                maxRange='386',
                origin=quote_loc,
            )
            vmf_file.create_ent(
                classname='env_microphone',
                targetname='player_speaker_orange',
                speakername='!player_orange',
                maxRange='386',
                origin=quote_loc,
            )

    LOGGER.info('{} Mid quotes', len(mid_quotes))
    for mid_lines in mid_quotes:
        line = random.choice(mid_lines)
        mid_item, use_ding, mid_name = line
        add_quote(mid_item, mid_name, quote_loc, use_ding)

    LOGGER.info('Done!')
