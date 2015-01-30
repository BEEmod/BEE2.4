import random
import itertools
import operator

from property_parser import Property, KeyValError
from utils import Vec
import vmfLib as VLib
import utils

INST_PREFIX = 'instances/BEE2/voice/'

def add_voice(voice_data, map_attr, style_vars, VMF, config={}):
    '''Add a voice line to the map.'''
    print('Adding Voice!')
    if len(voice_data.value) == 0:
        print('No Data!')
        return
    
    quote_base = voice_data['base', False]
    quote_loc = voice_data['quote_loc', '-10000 0 0']
    if quote_base:
        print('Adding Base instance!')
        VMF.add_ent(VLib.Entity(VMF, keys={
            "classname": "func_instance",
            "targetname": 'voice',
            "file": INST_PREFIX + quote_base,
            "angles": '0 0 0',
            "origin": quote_loc,
            "fixup_style": "0",
            }))
            
    ALLOW_MID_VOICES = not style_vars.get('NoMidVoices', False)
    
    mid_quotes = []
    
    def sort_func(quote):
        '''The quotes will be sorted by their priority value.'''
        try:
            return float(quote[0])
        except ValueError:
            return 0.0
            
    for group in itertools.chain(
            voice_data.find_all('group'),
            voice_data.find_all('midinst'),
            ):
        QUOTE_TARGETNAME = group['Choreo_Name', '@choreo']
        possible_quotes = []
        for quote in group.find_all('quote'):
            valid_quote = True
            for flag in quote:
                name = flag.name.casefold()
                if name == 'instance':
                    continue
                # break out if a flag is unsatisfied
                if name == 'has' and map_attr[flag.value] is False:
                    valid_quote = False
                    break
                elif name == 'nothas' and map_attr[flag.value] is True:
                    valid_quote = False
                    break
                elif (name == 'stylevartrue' and 
                        style_vars[flag.value.casefold()] is False):
                    valid_quote = False
                    break
                elif (name == 'stylevarfalse' and 
                        style_vars[flag.value.casefold()] is True):
                    valid_quote = False
                    break
                    
            if valid_quote:
                if ALLOW_MID_VOICES and group.name.casefold() == 'midinst':
                    mid_quotes.extend(quote.find_all('instance', 'file'))
                else:
                    inst_list = list(quote.find_all('instance'))
                    if inst_list:
                        possible_quotes.append((
                            quote['priority', '0'],
                            inst_list,
                            ))        
        if possible_quotes:
            possible_quotes.sort(key=sort_func)
            timer_val = config.get(
                group['config', ''].casefold(),
                '0')
            try:
                timer_val = int(timer_val)
            except ValueError:
                timer_val = 0
                
            choreo_loc = group['choreo_loc', quote_loc]
                
            chosen = random.choice(possible_quotes[-1][1])
                
            for prop in chosen:
                name = prop.name.casefold()
                if name == 'file':
                    VMF.add_ent(VLib.Entity(VMF, keys={
                        "classname": "func_instance",
                        "targetname": "",
                        "file": INST_PREFIX + prop.value,
                        "origin": quote_loc,
                        "fixup_style": "2", # No fixup
                        }))
                elif name == 'choreo':
                    VMF.add_ent(VLib.Entity(VMF, keys={
                        "classname": "logic_choreographed_scene",
                        "targetname": QUOTE_TARGETNAME,
                        "origin": choreo_loc,
                        "scenefile": prop.value,
                        "busyactor": "1", # Wait for actor to stop talking
                        "onplayerdeath": "0",
                        }))
                elif name == 'snd':
                    VMF.add_ent(VLib.Entity(VMF, keys={
                        'classname': 'ambient_generic',
                        'spawnflags': '49', # Infinite Range, Starts Silent
                        "targetname": QUOTE_TARGETNAME,
                        "origin": choreo_loc,
                        'message': prop.value,
                        'health': '10', # Volume
                        }))
                
    for mid_item in mid_quotes:
        VMF.add_ent(VLib.Entity(VMF, keys={
            "classname": "func_instance",
            "targetname": "",
            "file": INST_PREFIX + mid_item,
            "origin": quote_loc,
            "fixup_style": "2", # No fixup
            }))
            
    utils.con_log('Done!')
