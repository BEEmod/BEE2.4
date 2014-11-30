from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
import webbrowser

import tkinter_png as png # png library for TKinter
import sound as snd
import itemPropWin

wid_sub = [0,0,0,0,0]
wid_spr = [0,0,0,0,0,0]

selected_item = None
selected_sub_item = None

def showItemProps():
    snd.fx('expand')
    itemPropWin.open(selected_item.get_properties(), wid_changedefaults, "ItemNameHere") # TODO: add real values for first/last args
    
def hideItemProps(vals):
    snd.fx('contract')
    print(vals)

def showMoreInfo():
    url = selected_item.data['url']
    if url != 'NONE':
        try:
            webbrowser.open(url, new=2, autoraise=True) # 2 = open in tab if possible
        except webbrowser.Error:
            if messagebox.askyesno(icon="error", title="BEE2 - Error", message="Failed to open a web browser. Do you wish for the URL to be copied to the clipboard instead?", detail="'" + str(url) + "'", parent=prop_window):
                print("saving " +url+ "to clipboard")
                root.clipboard_clear()
                root.clipboard_append(url)
        hideProps(None) # either the webbrowser or the messagebox could cause the properties to move behind the main window, so hide it so it doesn't appear there
        
def showProps(e):
    '''Show the properties window for an item.'''
    global selected_item, selected_sub_item
    snd.fx('expand')
    prop_window.deiconify()
    prop_window.vis=True
    prop_window.lift(root)
    
    selected_item = e.widget.item
    selected_sub_item = e.widget
    icon_widget = wid_sub[selected_sub_item.subKey]
    
    loc_x=e.widget.winfo_rootx() + prop_window.winfo_rootx() - icon_widget.winfo_rootx()
        #The pixel offset between the window and the subitem in the properties dialog
    loc_y=e.widget.winfo_rooty() + prop_window.winfo_rooty() - wid_sub[0].winfo_rooty()
    
    if loc_x<15: # adjust to fit inside the screen, + small boundary to not obstruct taskbars, menus etc
        loc_x=0
    if loc_y<45:
        loc_y=0
    if loc_x > prop_window.winfo_screenwidth()-prop_window.winfo_reqwidth()-15:
        loc_x=prop_window.winfo_screenwidth()-prop_window.winfo_reqwidth()-15
    if loc_y > prop_window.winfo_screenheight()-prop_window.winfo_reqheight()-45:
        loc_y=prop_window.winfo_screenheight()-prop_window.winfo_reqheight()-45
    prop_window.geometry('+'+str(loc_x)+'+'+str(loc_y))
    prop_window.relX=loc_x-root.winfo_x()
    prop_window.relY=loc_y-root.winfo_y()
    for pos in range(5):
        if pos >= selected_item.num_sub:
            wid_sub[pos]['image'] = png.loadIcon('_blank')
        else:
            wid_sub[pos]['image'] = selected_item.get_icon(pos)
        wid_sub[pos]['relief'] = 'flat'
    icon_widget['relief'] = 'raised'
    wid_author['text'] = ', '.join(selected_item.data['auth'])
    wid_name['text'] = selected_sub_item.dispName
    wid_desc['state']="normal"
    wid_desc.delete(1.0, END)
    wid_desc.insert("end", selected_item.data['desc']) 
    wid_desc['state']="disabled"

def hideProps(e):
    if prop_window.vis:
        snd.fx('contract')
        prop_window.withdraw()
        prop_window.vis=False

def init(win):
    '''Initiallise all the window components.'''
    global root, prop_window, wid_name, wid_ent_count, wid_author, sub_frame, wid_desc, wid_moreinfo, wid_variant, wid_changedefaults
    root = win
    prop_window=Toplevel(root)
    prop_window.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    prop_window.resizable(False, False)
    prop_window.transient(master=root)
    prop_window.vis=False
    prop_window.relX=0
    prop_window.relY=0
    prop_window.withdraw() # starts hidden


    f=ttk.Frame(prop_window, relief="raised", borderwidth="4")
    f.grid(row=0, column=0)

    ttk.Label(f, text="Properties:", anchor="center").grid(row=0, column=0, columnspan=3, sticky="EW")
    entSpr=png.loadSpr('gear_ent')

    wid_name=ttk.Label(f, text="", anchor="center")
    wid_name.grid(row=1, column=0, columnspan=3, sticky="EW")

    wid_ent_count=ttk.Label(f, text="2", anchor="e", compound="left", image=entSpr)
    wid_ent_count.img=entSpr
    wid_ent_count.grid(row=0, column=2, rowspan=2, sticky=E)

    wid_author=ttk.Label(f, text="", anchor="center", relief="sunken")
    wid_author.grid(row=2, column=0, columnspan=3, sticky="EW")

    sub_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    sub_frame.grid(column=0, columnspan=3, row=3)
    for i in range(len(wid_sub)):
        wid_sub[i]=ttk.Label(sub_frame, image=png.loadIcon('_blank'))
        wid_sub[i].grid(row=0, column=i)
    ttk.Label(f, text="Description:", anchor="sw").grid(row=4, column=0, sticky="SW")
    spr_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
    img=('in_none','out_norm','rot_0','space_occupy','surf_wall_floor_ceil','ap_black') # in order: inputs, outputs, rotation handle, occupied/embed state, desiredFacing, is a Valve item (+ other authors in future)
    for i, spr in enumerate(img):
        spr=png.loadSpr(spr)
        wid_spr[i]=ttk.Label(spr_frame, image=spr, relief="raised")
        wid_spr[i].grid(row=0, column=i)
        wid_spr[i].img=spr
    desc_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=5, column=0, columnspan=3, sticky="EW")
    wid_desc=Text(desc_frame, width=40, height=8, wrap="word")
    wid_desc.grid(row=0, column=0, sticky="EW")

    desc_scroll=ttk.Scrollbar(desc_frame, orient=VERTICAL, command=wid_desc.yview)
    wid_desc['yscrollcommand']=desc_scroll.set
    desc_scroll.grid(row=0, column=1, sticky="NS")
    wid_desc['state']="disabled" # need to set this to normal when editing text, then swap back

    wid_moreinfo=ttk.Button(f, text="More Info>>", command=showMoreInfo)
    wid_moreinfo.grid(row=6, column=2, sticky=E)

    wid_changedefaults=ttk.Button(f, text="Change Defaults...", command=showItemProps)
    wid_changedefaults.grid(row=6, column=1)

    wid_variant=ttk.Combobox(f, values=("Recessed","Compat (On Top)"))
    wid_variant.current(0)
    wid_variant.grid(row=6, column=0, sticky=W)
    
    itemPropWin.init(root, hideItemProps)
    