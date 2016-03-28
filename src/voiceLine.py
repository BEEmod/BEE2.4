# coding=utf-8
from decimal import Decimal
import itertools
import random
import os

from BEE2_config import ConfigFile
from property_parser import Property
from utils import Vec
import conditions
import utils
import vmfLib
import vbsp

LOGGER = utils.getLogger(__name__)

map_attr = {}
style_vars = {}

ADDED_BULLSEYES = set()

# Special quote instances assoicated with an item/style.
# These are only added if the condition executes.
QUOTE_EVENTS = {}  # id -> instance mapping

# The block of SP and coop voice data
QUOTE_DATA = Property('Quotes', [])

ALLOW_MID_VOICES = False
VMF = None  # type: vmfLib.VMF

# The prefix for all voiceline instances.
INST_PREFIX = 'instances/BEE2/voice/'

# The location of the responses script.
RESP_LOC = 'bee2/inject/response_data.nut'

RESP_HAS_NAMES = {
    'death_goo': 'goo',
    'death_turret': 'turret',
    'death_laserfield': 'laserfield',
}


# Create a fake instance to pass to condition flags. This way we can
# reuse all that logic, without breaking flags that check the instance.
fake_inst = vmfLib.VMF().create_ent(
    classname='func_instance',
    file='',
    angles='0 0 0',
    origin='0 0 0',
)


def has_responses():
    """Check if we have any valid 'response' data for Coop."""
    LOGGER.info([prop.name for prop in QUOTE_DATA])
    return 'CoopResponses' in QUOTE_DATA


def generate_resp_script(file):
    """Write the responses section into a file."""
    config = ConfigFile('resp_voice.cfg', root='bee2')
    file.write("BEE2_RESPONSES <- {\n")
    for section in QUOTE_DATA.find_key('CoopResponses', []):
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


def mode_quotes(prop_block):
    """Get the quotes from a block which match the game mode."""
    is_sp = (vbsp.GAME_MODE == 'SP')
    for prop in prop_block:
        if prop.name == 'line':
            # Ones that apply to both modes
            yield prop
        elif prop.name == 'line_sp' and is_sp:
            yield prop
        elif prop.name == 'line_coop' and not is_sp:
            yield prop


@conditions.make_result('QuoteEvent')
def res_quote_event(inst, res):
    """Enable a quote event. The given file is the default instance."""
    QUOTE_EVENTS[res['id'].casefold()] = res['file']

    return conditions.RES_EXHAUSTED


def find_group_quotes(group, mid_quotes, use_dings, conf):
    """Scan through a group, looking for applicable quote options."""
    is_mid = (group.name == 'midinst')

    if is_mid:
        group_id = 'MIDCHAMBER'
    else:
        group_id = group['name'].upper()

    for quote in group.find_all('quote'):
        valid_quote = True
        for flag in quote:
            name = flag.name
            if name in ('priority', 'name', 'line', 'line_sp', 'line_coop'):
                # Not flags!
                continue
            if not conditions.check_flag(flag, fake_inst):
                valid_quote = False
                break

        if not valid_quote:
            continue

        poss_quotes = []
        for line in mode_quotes(quote):
            line_id = line['id', line['name', '']].casefold()

            # Check if the ID is enabled!
            if conf.get_bool(group_id, line_id, True):
                if ALLOW_MID_VOICES and is_mid:
                    mid_quotes.append((line, use_dings))
                else:
                    poss_quotes.append(line)
            else:
                LOGGER.info(
                    'Line "{}" is disabled..',
                    line['name', '??'],
                )

        if poss_quotes:
            yield (
                quote['priority', '0'],
                poss_quotes,
                )


def add_quote(quote, targetname, quote_loc, use_dings=False):
    """Add a quote to the map."""
    LOGGER.info('Adding quote: {}', quote)

    cc_emit_name = None
    added_ents = []

    # The OnUser1 outputs always play the quote (PlaySound/Start), so you can
    # mix ent types in the same pack.

    for prop in quote:
        name = prop.name.casefold()

        if name == 'file':
            added_ents.append(VMF.create_ent(
                classname='func_instance',
                targetname='',
                file=INST_PREFIX + prop.value,
                origin=quote_loc,
                fixup_style='2',  # No fixup
            ))
        elif name == 'choreo':
            c_line = prop.value
            # Add this to the beginning, since all scenes need it...
            if not c_line.startswith('scenes/'):
                c_line = 'scenes/' + c_line

            choreo = VMF.create_ent(
                classname='logic_choreographed_scene',
                targetname=targetname,
                origin=quote_loc,
                scenefile=c_line,
                busyactor="1",  # Wait for actor to stop talking
                onplayerdeath='0',
            )
            if use_dings:
                # Play ding_on/off before and after the line.
                choreo.add_out(
                    vmfLib.Output('OnUser1', '@ding_on', 'Start'),
                    vmfLib.Output('OnUser1', targetname, 'Start', delay=0.2),
                    vmfLib.Output('OnCompletion', '@ding_off', 'Start'),
                )
            else:
                choreo.add_out(
                    vmfLib.Output('OnUser1', targetname, 'Start',)
                )
            added_ents.append(choreo)
        elif name == 'snd':
            snd = VMF.create_ent(
                classname='ambient_generic',
                spawnflags='49',  # Infinite Range, Starts Silent
                targetname=targetname,
                origin=quote_loc,
                message=prop.value,
                health='10',  # Volume
            )
            snd.add_out(
                vmfLib.Output('OnUser1', targetname, 'PlaySound')
            )
            added_ents.append(snd)
        elif name == 'bullseye':
            # Cave's voice lines require a special named bullseye to
            # work correctly.

            # Don't add the same one more than once.
            if prop.value not in ADDED_BULLSEYES:
                VMF.create_ent(
                    classname='npc_bullseye',
                    # Not solid, Take No Damage, Think outside PVS
                    spawnflags='222224',
                    targetname=prop.value,
                    origin=quote_loc,
                    angles='0 0 0',
                )
                ADDED_BULLSEYES.add(prop.value)
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
            vbsp.TO_PACK.add(prop.value.casefold())
        elif name == 'pack':
            if prop.has_children():
                vbsp.PACK_FILES.update(
                    subprop.value
                    for subprop in
                    prop
                )
            else:
                vbsp.PACK_FILES.add(prop.value)

    if cc_emit_name:
        for ent in added_ents:
            ent.add_out(vmfLib.Output(
                'OnUser1',
                '@command',
                'Command',
                param='cc_emit ' + cc_emit_name,
            ))


def sort_func(quote):
    """The quotes will be sorted by their priority value."""
    # We use Decimal so it will adjust to whatever precision a user sets,
    # Without floating-point error.
    try:
        return Decimal(quote[0])
    except ValueError:
        # Default to priority 0
        return Decimal()


def add_voice(
        has_items,
        style_vars_,
        vmf_file,
        map_seed,
        ):
    """Add a voice line to the map."""
    global ALLOW_MID_VOICES, VMF, map_attr, style_vars
    LOGGER.info('Adding Voice Lines!')

    VMF = vmf_file
    map_attr = has_items
    style_vars = style_vars_

    norm_config = ConfigFile('voice.cfg', root='bee2')
    mid_config = ConfigFile('mid_voice.cfg', root='bee2')

    quote_base = QUOTE_DATA['base', False]
    quote_loc = Vec.from_str(QUOTE_DATA['quote_loc', '-10000 0 0'], x=-10000)
    if quote_base:
        LOGGER.info('Adding Base instance!')
        VMF.create_ent(
            classname='func_instance',
            targetname='voice',
            file=INST_PREFIX + quote_base,
            angles='0 0 0',
            origin=quote_loc,
            fixup_style='0',
        )

    # Always add a box around the lines - it may be needed for quoteEvents.
    VMF.add_brushes(VMF.make_hollow(
        quote_loc - 64,
        quote_loc + 64,
        thick=32,
    ))

    ALLOW_MID_VOICES = not style_vars.get('NoMidVoices', False)

    mid_quotes = []

    # Enable using the beep before and after choreo lines.
    allow_dings = utils.conv_bool(QUOTE_DATA['use_dings', '0'])
    if allow_dings:
        VMF.create_ent(
            classname='logic_choreographed_scene',
            targetname='@ding_on',
            origin=quote_loc + (-8, -16, 0),
            scenefile='scenes/npc/glados_manual/ding_on.vcd',
            busyactor="1",  # Wait for actor to stop talking
            onplayerdeath='0',
        )
        VMF.create_ent(
            classname='logic_choreographed_scene',
            targetname='@ding_off',
            origin=quote_loc + (8, -16, 0),
            scenefile='scenes/npc/glados_manual/ding_off.vcd',
            busyactor="1",  # Wait for actor to stop talking
            onplayerdeath='0',
        )

    # QuoteEvents allows specifiying an instance for particular items,
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
            generate_resp_script(f)
    else:
        LOGGER.info('No responses data..')
        try:
            os.remove(RESP_LOC)
        except FileNotFoundError:
            pass

    for ind, file in enumerate(QUOTE_EVENTS.values()):
        VMF.create_ent(
            classname='func_instance',
            targetname='voice_event_' + str(ind),
            file=file,
            angles='0 0 0',
            origin=quote_loc,
            fixup_style='0',
        )

    # For each group, locate the voice lines.
    for group in itertools.chain(
            QUOTE_DATA.find_all('group'),
            QUOTE_DATA.find_all('midinst'),
            ):

        quote_targetname = group['Choreo_Name', '@choreo']
        use_dings = utils.conv_bool(group['use_dings', ''], allow_dings)

        possible_quotes = sorted(
            find_group_quotes(
                group,
                mid_quotes,
                use_dings,
                conf=mid_config if group.name == 'midinst' else norm_config,
            ),
            key=sort_func,
            reverse=True,
        )

        if possible_quotes:

            choreo_loc = group['choreo_loc', quote_loc]

            chosen = possible_quotes[0][1]

            LOGGER.info('Chosen: {}', '\n'.join(map(repr, chosen)))

            # Join the IDs for the voice lines to the map seed,
            # so each quote block will chose different lines.
            random.seed(map_seed + '-VOICE_' + '|'.join(
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

    if ADDED_BULLSEYES or utils.conv_bool(QUOTE_DATA['UseMicrophones', '']):
        # Add microphones that broadcast audio directly at players.
        # This ensures it is heard regardless of location.
        # This is used for Cave and core Wheatley.
        if vbsp.GAME_MODE == 'SP':
            VMF.create_ent(
                classname='env_microphone',
                targetname='player_speaker_sp',
                speakername='!player',
                maxRange='96',
                origin=quote_loc,
            )
        else:
            VMF.create_ent(
                classname='env_microphone',
                targetname='player_speaker_blue',
                speakername='!player_blue',
                maxRange='96',
                origin=quote_loc,
            )
            VMF.create_ent(
                classname='env_microphone',
                targetname='player_speaker_orange',
                speakername='!player_orange',
                maxRange='96',
                origin=quote_loc,
            )

    LOGGER.info('Mid quotes: {}', mid_quotes)
    for mid_item, use_ding in mid_quotes:
        # Add all the mid quotes
        target = mid_item['target', '']
        for prop in mid_item:
            add_quote(prop, target, quote_loc, use_ding)

    LOGGER.info('Done!')