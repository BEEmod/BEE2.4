# coding=utf-8
from decimal import Decimal
import itertools
import random

from BEE2_config import ConfigFile
import conditions
import utils
import vmfLib

map_attr = {}
style_vars = {}

ALLOW_MID_VOICES = False
VMF = None

INST_PREFIX = 'instances/BEE2/voice/'

# Create a fake instance to pass to condition flags. This way we can
# reuse all that logic, without breaking flags that check the instance.
fake_inst = vmfLib.VMF().create_ent(
    classname='func_instance',
    file='',
    angles='0 0 0',
    origin='0 0 0',
)


def find_group_quotes(group, mid_quotes, conf):
    is_mid = group.name == 'midinst'
    group_id = group['name']

    for quote in group.find_all('quote'):
        valid_quote = True
        for flag in quote:
            name = flag.name
            if name in ('instance', 'priority', 'name'):
                # Not flags!
                continue
            if not conditions.check_flag(flag, fake_inst):
                valid_quote = False
                break

        quote_id = quote['id', quote['name', '']]

        utils.con_log(quote_id, valid_quote)

        if valid_quote:
            # Check if the ID is enabled!
            if conf.get_bool(group_id, quote_id, True):
                if ALLOW_MID_VOICES and is_mid:
                    mid_quotes.extend(quote.find_all('instance'))
                else:
                    inst_list = list(quote.find_all('instance'))
                    if inst_list:
                        yield (
                            quote['priority', '0'],
                            inst_list,
                            )


def add_quote(quote, targetname, quote_loc):
    """Add a quote to the map."""
    utils.con_log('Adding quote: ', quote)

    for prop in quote:
        name = prop.name.casefold()
        if name == 'file':
            VMF.create_ent(
                classname='func_instance',
                targetname='',
                file=INST_PREFIX + prop.value,
                origin=quote_loc,
                fixup_style='2',  # No fixup
            )
        elif name == 'choreo':
            VMF.create_ent(
                classname='logic_choreographed_scene',
                targetname=targetname,
                origin=quote_loc,
                scenefile=prop.value,
                busyactor="1",  # Wait for actor to stop talking
                onplayerdeath='0',
            )
        elif name == 'snd':
            VMF.create_ent(
                classname='ambient_generic',
                spawnflags='49',  # Infinite Range, Starts Silent
                targetname=targetname,
                origin=quote_loc,
                message=prop.value,
                health='10',  # Volume
            )


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
        voice_data,
        has_items,
        style_vars_,
        vmf_file,
        map_seed,
        mode='SP',
        ):
    """Add a voice line to the map."""
    global ALLOW_MID_VOICES, VMF, map_attr, style_vars
    print('Adding Voice!')

    if len(voice_data.value) == 0:
        print('No Data!')
        return

    VMF = vmf_file
    map_attr = has_items
    style_vars = style_vars_

    if mode == 'SP':
        norm_config = ConfigFile('SP.cfg', root='bee2')
        mid_config = ConfigFile('MID_SP.cfg', root='bee2')
    else:
        norm_config = ConfigFile('COOP.cfg', root='bee2')
        mid_config = ConfigFile('MID_COOP.cfg', root='bee2')

    quote_base = voice_data['base', False]
    quote_loc = voice_data['quote_loc', '-10000 0 0']
    if quote_base:
        print('Adding Base instance!')
        VMF.create_ent(
            classname='func_instance',
            targetname='voice',
            file=INST_PREFIX + quote_base,
            angles='0 0 0',
            origin=quote_loc,
            fixup_style='0',
        )

    ALLOW_MID_VOICES = not style_vars.get('NoMidVoices', False)

    mid_quotes = []

    for group in itertools.chain(
            voice_data.find_all('group'),
            voice_data.find_all('midinst'),
            ):

        quote_targetname = group['Choreo_Name', '@choreo']

        possible_quotes = sorted(
            find_group_quotes(
                group,
                mid_quotes,
                conf=mid_config if group.name == 'midinst' else norm_config,
            ),
            key=sort_func,
            reverse=True,
        )

        if possible_quotes:

            choreo_loc = group['choreo_loc', quote_loc]

            chosen = possible_quotes[0][1]

            utils.con_log('Chosen:', '\n'.join(map(repr, chosen)))

            # Join the IDs for the voice lines to the map seed,
            # so each quote block will chose different lines.
            random.seed(map_seed + '-VOICE_' + '|'.join(
                prop['id', 'ID']
                for prop in
                chosen
            ))
            # Add one of the associated quotes
            add_quote(random.choice(chosen), quote_targetname, choreo_loc)

    print('mid quotes: ', mid_quotes)
    for mid_item in mid_quotes:
        # Add all the mid quotes
        target = mid_item['target', '']
        for prop in mid_item:
            add_quote(prop, target, quote_loc)

    utils.con_log('Done!')
