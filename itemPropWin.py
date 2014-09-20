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
  'startactive'             : ('railPlat', 'Start Active'),
  'startopen'               : ('checkbox', 'Start Open'),
  'startlocked'             : ('checkbox', 'Start Locked'),
  'timerdelay'              : ('timerDel', 'Delay'),
  'dropperenabled'          : ('checkbox', 'Dropper Enabled'),
  'autodrop'                : ('checkbox', 'Auto Drop'),
  'autorespawn'             : ('checkbox', 'Auto Respawn'),
  'oscillate'               : ('railPlat', 'Oscillate'),
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
#  = hide, locked, checkbox, timerDel, pistonPlat, gelType, panAngle, railPlat
prop_pos_special= ['toplevel', 'bottomlevel', 'angledpanelanimation', 'paintflowtype', 'timerdelay']
prop_pos = ['allowstreak', 'startenabled', 'startreversed', 'startdeployed', 'startactive', 'startopen', 'startlocked', 'dropperenabled', 'autodrop', 'autorespawn', 'oscillate']

widgets={} # holds the checkbox or other item used to manipulate the box
labels={} # holds the descriptive labels for each property 

values={}  # selected values for this item
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
  
paintOpts = [
  'Light',
  'Medium',
  'Heavy',
  'Drip',
  'Bomb'
  ]

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
def init(tk):
  global win
  win=Toplevel(tk)
  win.transient(master=tk)
  win.resizable(False, False)
  win.title("Default Properties")
  win.iconbitmap(r'BEE2.ico')
  win.protocol("WM_DELETE_WINDOW", lambda: win.withdraw())
  win.withdraw()

  for key in props.keys():
      labels[key]=ttk.Label(win, text=props[key][1]+':')
      if props[key][0] == 'checkbox':
        values[key] = IntVar(value=defaults[key])
        widgets[key] = ttk.Checkbutton(win, variable=values[key])
      elif props[key][0] == 'panAngle':
        widgets[key]=Spinbox(win, values=(30,45,60,90), command=lambda key=key: saveAngle(key))
      elif props[key][0] == 'gelType':
        widgets[key]=ttk.Combobox(win, values=paintOpts)
        widgets[key].set(paintOpts[defaults[key]])
        widgets[key].state(['readonly'])
        widgets[key].bind("<<ComboboxSelected>>", lambda e, key=key: savePaint(e,key))
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
  
  
def open(propList, defaults=defaults):
  spec_row=0
  for key in prop_pos_special:
    labels[key].grid( row=spec_row, column=0,   sticky=E, padx=2, pady=5)
    widgets[key].grid(row=spec_row, column=1, sticky="EW", padx=2, pady=5, columnspan=5)
    spec_row+=1
  ind=0
  for key in prop_pos:
    if key in propList:
      labels[key].grid( row=ind%5+spec_row, column=(ind//5)*2,   sticky=E, padx=2, pady=5)
      widgets[key].grid(row=ind%5+spec_row, column=(ind//5)*2+1, sticky="EW", padx=2, pady=5)
      ind+=1
    else:
      labels[key].grid_remove()
      widgets[key].grid_remove()
  win.deiconify()
  

#init(Tk())
#open(widgets.keys())