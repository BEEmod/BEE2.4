from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
import math
props = { # all valid properties in editoritems, Valve probably isn't going to release a major update so it's fine to hardcode this.
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
  # 'timersound'              : ('locked',     'Timer Sound'),
  # 'connectioncount'         : ('locked',     'Connection Count'),
  # 'connectioncountpolarity' : ('locked',     'Polarity Connection Count'),
  # 'buttontype'              : ('locked',     'Button Type'),
  # 'barriertype'             : ('locked',     'Barrier Type'),
  # 'hazardtype'              : ('locked',     'Hazard Type'),
  # 'cubetype'                : ('locked',     'Cube Type'),
  # 'angledpaneltype'         : ('locked',     'Angled Panel Type'),
  # 'portalable'              : ('locked',     'Portalable'),
  # 'verticalalignment'       : ('locked',     'Vertical Alignment'),
  # 'targetname'              : ('locked',     'Target Name'),
  # 'catapultspeed'           : ('locked',     'Catapult Speed'),
  # 'autotrigger'             : ('locked',     'Auto Trigger'),
  # 'traveldistance'          : ('locked',     'Travel Distance'),
  # 'speed'                   : ('locked',     'Track Speed'),
  # 'traveldirection'         : ('locked',     'Travel Direction'),
  # 'startingposition'        : ('locked',     'Starting Position'),
  # 'istimer'                 : ('locked',     'Is Timer?'),
  # 'itemfallstraightdown'    : ('locked',     'Items Drop Straight Down?')
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
  'angledpanelanimation'    : 1,
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

def savePaint(e, key):
    values[key]=paintOpts.index(e.widget.get())

def saveAngle(key):
    values[key]='ramp_'+widgets[key].get()+'_deg_open'

def saveTim(val, key):
    values[key]=widgets[key].get()

def savePist(val, key):
    if widgets['toplevel'].get()==widgets['bottomlevel'].get(): # user moved them to match, switch the other one around
        widgets['toplevel' if key=='bottomlevel' else 'bottomlevel'].set(values['cust_'+key])

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

def exit():
    "Quit and return the new settings"
    win.grab_release()
    win.withdraw()
    out={}
    for key in props.keys():
        if key in propList:
            if props[key][0] == 'checkbox' or props[key][0]=='railLift':
                out[key]=(values[key].get())
            elif props[key][0] == 'pistPlat':
                out[key]=values[key]
                out['startup']=values['startup']
            else:
                out[key]=values[key]
    callback(out)

def init(tk, cback):
    global callback, labels
    callback=cback
    global win
    win=Toplevel(tk)
    win.title("BEE2")
    win.resizable(False, False)
    win.iconbitmap(r'BEE2.ico')
    win.protocol("WM_DELETE_WINDOW", exit)
    win.withdraw()
    labels['noOptions']=ttk.Label(win, text='No Properties avalible!')
    widgets['saveButton']=ttk.Button(win, text='Save', command=exit)
    widgets['titleLabel']=ttk.Label(win, text='')
    widgets['titleLabel'].grid(row=0, column=0, columnspan=9)
    
    widgets['div_1']=ttk.Separator(win, orient="vertical")
    widgets['div_2']=ttk.Separator(win, orient="vertical")
    widgets['div_h']=ttk.Separator(win, orient="horizontal")

    for key in props.keys():
        labels[key]=ttk.Label(win, text=props[key][1]+':')
        if props[key][0] == 'checkbox':
            values[key] = IntVar(value=defaults[key])
            widgets[key] = ttk.Checkbutton(win, variable=values[key])
        elif props[key][0] == 'railLift':
            values[key] = IntVar(value=defaults[key])
            widgets[key] = ttk.Checkbutton(win, variable=values[key], command=lambda k=key: saveRail(k))
        elif props[key][0] == 'panAngle':
            widgets[key]=Spinbox(win, values=(30,45,60,90), command=lambda key=key: saveAngle(key))
            values[key]=defaults[key]
        elif props[key][0] == 'gelType':
            widgets[key]=ttk.Combobox(win, values=paintOpts)
            widgets[key].set(paintOpts[defaults[key]])
            widgets[key].state(['readonly'])
            widgets[key].bind("<<ComboboxSelected>>", lambda e, key=key: savePaint(e,key))
            values[key]=defaults[key]
        elif props[key][0] == 'pistPlat':
            widgets[key]=Scale(win, from_=0, to=4, orient="horizontal", showvalue=False, command=lambda val, k=key: savePist(val,k))
            values[key]=defaults[key]
            if (key=='toplevel' and defaults['startup']==True) or (key=='bottomlevel' and defaults['startup']==False):
                widgets[key].set(max(defaults['toplevel'],defaults['bottomlevel']))
            if (key=='toplevel' and defaults['startup']==False) or (key=='bottomlevel' and defaults['startup']==True):
                widgets[key].set(min(defaults['toplevel'],defaults['bottomlevel']))
        elif props[key][0] == 'timerDel':
            widgets[key]=Scale(win, from_=0, to=30, orient="horizontal", showvalue=True, command=lambda val, k=key: saveTim(val,k))
            values[key]=defaults[key]
        elif props[key][0] == 'railPlat':
            widgets[key]=ttk.Checkbutton(win)
        elif props[key][0] == 'timerDel':
            widgets[key]=ttk.Checkbutton(win)
    values['startup']=defaults['startup']


def open(usedProps, parent, itemName):
    widgets['titleLabel'].configure(text='Settings for "' + itemName + '"')
    global propList
    propList=usedProps
    win.transient(master=parent)
    for i,key in enumerate(propList):
        propList[i]=key.casefold()
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
        widgets['div_h'].grid(row=spec_row+1, column=0, columnspan=9, sticky="EW")
        spec_row+=2
    else:
        widgets['div_h'].grid_remove()
    ind=0
    for key in prop_pos:
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
    if ind+spec_row==0:
        labels['noOptions'].grid(row=0, column=0, columnspan=9)
        ind=1
    else:
        labels['noOptions'].grid_remove()
    widgets['saveButton'].grid(row=ind+spec_row, column=0, columnspan=9, sticky="EW")
    win.deiconify()
    win.lift(parent)
    win.grab_set()
    win.geometry('+'+str(parent.winfo_rootx()-30)+'+'+str(parent.winfo_rooty()-win.winfo_reqheight()-30))

if __name__ == '__main__': # load the window if directly executing this file
    root=Tk()
    root.geometry("+250+250")
    init(root,print)
    open(prop_pos+prop_pos_special,root, "TestItemWithEveryProp")
