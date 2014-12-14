from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from functools import partial as func_partial
import math
import random

import sound as snd
PROP_TYPES = { # all valid properties in editoritems, Valve probably isn't going to release a major update so it's fine to hardcode this.
  'toplevel'                : ('pistPlat', 'Start Position'),
  'bottomlevel'             : ('pistPlat', 'End Position'),
  'angledpanelanimation'    : ('panAngle', 'Panel Position'),
  'startenabled'            : ('checkbox', 'Start Enabled'),
  'startreversed'           : ('checkbox', 'Start Reversed'),
  'startdeployed'           : ('checkbox', 'Start Deployed'),
  'startactive'             : ('checkbox', 'Start Active'),
  'startopen'               : ('checkbox', 'Start Open'),
  'startlocked'             : ('checkbox', 'Start Locked'),
  'timerdelay'              : ('timerDel', 'Delay \n(0=infinite)'),
  'dropperenabled'          : ('checkbox', 'Dropper Enabled'),
  'autodrop'                : ('checkbox', 'Auto Drop'),
  'autorespawn'             : ('checkbox', 'Auto Respawn'),
  'oscillate'               : ('railLift', 'Oscillate'),
  'paintflowtype'           : ('gelType' , 'Flow Type'),
  'allowstreak'             : ('checkbox', 'Allow Streaks')
  # 'timersound'              : 'Timer Sound'),
  # 'connectioncount'         : 'Connection Count'),
  # 'connectioncountpolarity' : 'Polarity Connection Count'),
  # 'buttontype'              : 'Button Type'),
  # 'barriertype'             : 'Barrier Type'),
  # 'hazardtype'              : 'Hazard Type'),
  # 'cubetype'                : 'Cube Type'),
  # 'angledpaneltype'         : 'Angled Panel Type'),
  # 'portalable'              : 'Portalable'),
  # 'verticalalignment'       : 'Vertical Alignment'),
  # 'targetname'              : 'Target Name'),
  # 'catapultspeed'           : 'Catapult Speed'),
  # 'autotrigger'             : 'Auto Trigger'),
  # 'traveldistance'          : 'Travel Distance'),
  # 'speed'                   : 'Track Speed'),
  # 'traveldirection'         : 'Travel Direction'),
  # 'startingposition'        : 'Starting Position'),
  # 'istimer'                 : 'Is Timer?'),
  # 'itemfallstraightdown'    : 'Items Drop Straight Down?')
  }
# valid property types:
#  checkbox, timerDel, pistPlat, gelType, panAngle, railLift

# order of the different properties, 'special' are the larger controls like sliders or dropdown boxes
prop_pos_special= ['toplevel', 'bottomlevel', 'angledpanelanimation', 'paintflowtype', 'timerdelay']
prop_pos = ['allowstreak', 'startenabled', 'startreversed', 'startdeployed', 'startopen', 'startlocked', 'startactive','oscillate', 'dropperenabled', 'autodrop', 'autorespawn']

widgets={} # holds the checkbox or other item used to manipulate the box
labels={} # holds the descriptive labels for each property

propList=[]

values={}  # selected values for this items

paintOpts = [
  'Light',
  'Medium',
  'Heavy',
  'Drip',
  'Bomb'
  ]

defaults={ # default values for this item
  'startup'                 : False,
  'toplevel'                : 1,
  'bottomlevel'             : 0,
  'angledpanelanimation'    : 'ramp_45_deg_open',
  'startenabled'            : True,
  'startreversed'           : False,
  'startdeployed'           : True,
  'startactive'             : True,
  'startopen'               : True,
  'startlocked'             : False,
  'timerdelay'              : 3,
  'dropperenabled'          : True,
  'autodrop'                : True,
  'autorespawn'             : True,
  'oscillate'               : True,
  'paintflowtype'           : 1,
  'allowstreak'             : True
  }
  
last_angle = '0'
  
play_sound = False
is_open = False
  
  
def reset_sfx():
    global play_sound
    play_sound = True
  
def sfx(sound):
    '''Wait for a certain amount of time between retriggering sounds, so they don't overlap.'''
    global play_sound
    if play_sound is True:
        snd.fx(sound)
        play_sound = False
        win.after(75, reset_sfx)
        
def scroll_angle(key, e):
    if e.delta > 0 and widgets[key].get() != '90':
        e.widget.invoke('buttonup')
    elif e.delta < 0 and widgets[key].get() != '0':
        e.widget.invoke('buttondown')
        

def savePaint(e, key):
    sfx('config')
    values[key]=paintOpts.index(widgets[key].get())
    

def saveAngle(key):
    global last_angle
    new_ang = widgets[key].get()
    if new_ang > last_angle:
        sfx('raise_' + random.choice(('1','2','3')))
    elif new_ang < last_angle:
        sfx('lower_' + random.choice(('1','2','3')))
    last_angle = new_ang
    values[key]='ramp_'+str(new_ang)+'_deg_open'

def saveTim(val, key):
    new_val = widgets[key].get()
    if new_val > values[key]:
        sfx('add')
    elif new_val < values[key]:
        sfx('subtract')
    else:
        sfx('config')
    values[key]=new_val

def savePist(val, key):
    if widgets['toplevel'].get()==widgets['bottomlevel'].get(): # user moved them to match, switch the other one around
        sfx('swap')
        widgets['toplevel' if key=='bottomlevel' else 'bottomlevel'].set(values['cust_'+key])
    else:
        sfx('move')

    startPos=widgets['toplevel'].get()
    endPos=widgets['bottomlevel'].get()

    values['startup']= startPos > endPos
    values['toplevel']=max(startPos,endPos)
    values['bottomlevel']=min(startPos,endPos)
    values['cust_toplevel']=startPos
    values['cust_bottomlevel']=endPos

def saveRail(key):
    if values[key].get()==0:
        widgets['startactive'].state(['disabled'])
        values['startactive'].set(False)
    else:
        widgets['startactive'].state(['!disabled'])
        
def toggleCheck(var, e=None):
    if var.get():
        var.set(0)
    else:
        var.set(1)
    sfx('config')
        
def checkFX():
    sfx('config')
    
def paintFX(e):
    sfx('config')

def exit():
    "Quit and return the new settings."
    global is_open
    win.grab_release()
    win.withdraw()
    is_open=False
    out={}
    for key in PROP_TYPES.keys():
        if key in propList:
            if PROP_TYPES[key][0] == 'checkbox' or PROP_TYPES[key][0]=='railLift':
                out[key]=(values[key].get())
            elif PROP_TYPES[key][0] == 'pistPlat':
                out[key]=values[key]
                out['startup']=values['startup']
            else:
                out[key]=values[key]
    callback(out)
    
def can_edit(prop_list):
    '''Determine if any of these properties are changeable.'''
    for prop in prop_list:
        if prop in PROP_TYPES:
            return True
    return False

def init(tk, cback):
    global callback, labels, win, is_open
    callback=cback
    is_open=False
    win=Toplevel(tk)
    win.title("BEE2")
    win.resizable(False, False)
    win.iconbitmap(r'BEE2.ico')
    win.protocol("WM_DELETE_WINDOW", exit)
    win.withdraw()
    labels['noOptions']=ttk.Label(win, text='No Properties avalible!')
    widgets['saveButton']=ttk.Button(win, text='Save', command=exit)
    widgets['titleLabel']=ttk.Label(win, text='')
    widgets['titleLabel'].grid(columnspan=9)
    
    widgets['div_1']=ttk.Separator(win, orient="vertical")
    widgets['div_2']=ttk.Separator(win, orient="vertical")
    widgets['div_h']=ttk.Separator(win, orient="horizontal")

    for key in PROP_TYPES.keys():
        labels[key]=ttk.Label(win, text=PROP_TYPES[key][1]+':')
        if PROP_TYPES[key][0] == 'checkbox':
            values[key] = IntVar(value=defaults[key])
            widgets[key] = ttk.Checkbutton(win, variable=values[key], command=checkFX)
            widgets[key].bind('<Return>', func_partial(toggleCheck, values[key]))
        elif PROP_TYPES[key][0] == 'railLift':
            values[key] = IntVar(value=defaults[key])
            widgets[key] = ttk.Checkbutton(win, variable=values[key], command=lambda k=key: saveRail(k))
        elif PROP_TYPES[key][0] == 'panAngle':
            widgets[key]=Spinbox(win, values=(30,45,60,90), command=func_partial(saveAngle, key))
            widgets[key].bind('<MouseWheel>', func_partial(scroll_angle, key))
            values[key]=defaults[key]
        elif PROP_TYPES[key][0] == 'gelType':
            widgets[key]=ttk.Combobox(win, values=paintOpts)
            widgets[key].set(paintOpts[defaults[key]])
            widgets[key].state(['readonly'])
            widgets[key].bind("<<ComboboxSelected>>", lambda e, key=key: savePaint(e,key))
            widgets[key].bind("<Button-1>", paintFX)
            values[key]=defaults[key]
        elif PROP_TYPES[key][0] == 'pistPlat':
            widgets[key]=Scale(win, from_=0, to=4, orient="horizontal", showvalue=False, command=lambda val, k=key: savePist(val,k))
            values[key]=defaults[key]
            if (key=='toplevel' and defaults['startup']==True) or (key=='bottomlevel' and defaults['startup']==False):
                widgets[key].set(max(defaults['toplevel'],defaults['bottomlevel']))
            if (key=='toplevel' and defaults['startup']==False) or (key=='bottomlevel' and defaults['startup']==True):
                widgets[key].set(min(defaults['toplevel'],defaults['bottomlevel']))
        elif PROP_TYPES[key][0] == 'timerDel':
            widgets[key]=Scale(win, from_=0, to=30, orient="horizontal", showvalue=True, command=lambda val, k=key: saveTim(val,k))
            values[key]=defaults[key]
        elif PROP_TYPES[key][0] == 'railPlat':
            widgets[key]=ttk.Checkbutton(win)
    values['startup']=defaults['startup']

def open(usedProps, parent, itemName):
    global propList, is_open    
    propList=[key.casefold() for key in usedProps]
    is_open=True
    spec_row=1
    
    for key in prop_pos_special:
        if key in propList:
            labels[key].grid( row=spec_row, column=0,   sticky=E, padx=2, pady=5)
            widgets[key].grid(row=spec_row, column=1, sticky="EW", padx=2, pady=5, columnspan=9)
            spec_row+=1
        else:
            labels[key].grid_remove()
            widgets[key].grid_remove()
            
    if spec_row>1: # if we have a 'special' prop, add the divider between the types
        widgets['div_h'].grid(row=spec_row+1, columnspan=9, sticky="EW")
        spec_row+=2
    else:
        widgets['div_h'].grid_remove()
    ind=0
    
    for key in prop_pos:
        # Position each widget
        if key in propList:
            labels[key].grid( row=(ind//3)+spec_row, column=(ind%3)*3,   sticky=E, padx=2, pady=5)
            widgets[key].grid(row=(ind//3)+spec_row, column=(ind%3)*3+1, sticky="EW", padx=2, pady=5)
            ind+=1
        else:
            labels[key].grid_remove()
            widgets[key].grid_remove()
            
    if ind>1: # is there more than 1 checkbox? (adds left divider)
        widgets['div_1'].grid(row=spec_row, column=2, sticky="NS", rowspan=(ind//3)+1)
    else:  
        widgets['div_1'].grid_remove()
    if ind>2: # are there more than 2 checkboxes? (adds right divider)
        widgets['div_2'].grid(row=spec_row, column=5, sticky="NS", rowspan=(ind//3)+1)
    else:  
        widgets['div_2'].grid_remove()
        
    if ind+spec_row==1:
        # There aren't any items, display error message
        labels['noOptions'].grid(row=1, columnspan=9)
        ind=1
    else:
        labels['noOptions'].grid_remove()
        
    widgets['saveButton'].grid(row=ind+spec_row, columnspan=9, sticky="EW")
    
    # Block sound for the first few millisec to stop excess sounds from playing
    play_sound=False
    win.after(25, reset_sfx)
    
    widgets['titleLabel'].configure(text='Settings for "' + itemName + '"')
    win.title('BEE2 - ' + itemName)
    win.transient(master=parent)
    win.deiconify()
    win.lift(parent)
    win.grab_set()
    win.geometry('+'+str(parent.winfo_rootx()-30)+'+'+str(parent.winfo_rooty()-win.winfo_reqheight()-30))

if __name__ == '__main__': # load the window if directly executing this file
    root=Tk()
    root.geometry("+250+250")
    init(root,print)
    open(prop_pos+prop_pos_special,root, "TestItemWithEveryProp")
