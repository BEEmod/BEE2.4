from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from functools import partial as func_partial
import webbrowser

from property_parser import Property
import tkinter_png as png # png library for TKinter
import sound as snd
import itemPropWin

wid_sub = [0,0,0,0,0]
wid_spr = [0,0,0,0,0]

selected_item = None
selected_sub_item = None
is_open = False

SUBITEM_POS = {
# Positions of subitems depending on the number of subitems that exist
# This way they appear nicely centered on the list
    1: (-1, -1,  0, -1, -1), #__0__
    2: (-1,  0, -1,  1, -1), #_0_0_
    3: (-1,  0,  1,  2, -1), #_000_
    4: ( 0,  1, -1,  2,  3), #00_00
    5: ( 0,  1,  2,  3,  4)  #00000
}

ROT_TYPES = {
    #Image names that correspond to editoritems values
    "handle_none"          : "rot_0",
    "handle_4_directions"  : "rot_4",
    "handle_5_positions"   : "rot_5",
    "handle_6_positions"   : "rot_6",
    "handle_8_positions"   : "rot_8",
    "handle_36_directions" : "rot_36",
    "handle_catapult"      : "rot_catapult"
}

def pos_for_item(sub):
    pos = SUBITEM_POS[selected_item.num_sub]
    for ind, sub_loc in enumerate(pos):
        if sub == sub_loc:
            return ind
    else:
        return None

def showItemProps():
    snd.fx('expand')
    itemPropWin.open(selected_item.get_properties(), wid_changedefaults, selected_sub_item.name)
    
def hideItemProps(vals):
    snd.fx('contract')
    print(vals)
    
def sub_sel_enter(ind, e=None):
    if SUBITEM_POS[selected_item.num_sub][ind] != -1:   
        snd.fx('select')
    
def sub_sel(ind, e=None):
    '''Change the currently-selected sub-item.'''
    if selected_sub_item.is_pre: # Can only change the subitem on the preview window
        pos = SUBITEM_POS[selected_item.num_sub][ind]
        if pos != -1:
            snd.fx('config')
            selected_sub_item.change_subtype(pos)
            # Redisplay the window to refresh data and move it to match
            showProps(selected_sub_item) 

def showMoreInfo():
    url = selected_item.url
    if url is not None:
        try:
            webbrowser.open(url, new=2, autoraise=True) # 2 = open in tab if possible
        except webbrowser.Error:
            if messagebox.askyesno(icon="error", title="BEE2 - Error", message="Failed to open a web browser. Do you wish for the URL to be copied to the clipboard instead?", detail="'" + str(url) + "'", parent=prop_window):
                print("saving " +url+ "to clipboard")
                root.clipboard_clear()
                root.clipboard_append(url)
        hideProps(None) # either the webbrowser or the messagebox could cause the properties to move behind the main window, so hide it so it doesn't appear there
        
def moreInfo_showURL(e):
    if selected_item.url is not None:
        moreinfo_lbl['text'] = selected_item.url
        moreinfo_win.deiconify()
        moreinfo_win.update_idletasks()
        x = wid_moreinfo.winfo_rootx() - (moreinfo_win.winfo_reqwidth() - wid_moreinfo.winfo_reqwidth()) // 2
        y = wid_moreinfo.winfo_rooty() + wid_moreinfo.winfo_reqheight()
        moreinfo_win.geometry('+' + str(x) + '+' + str(y))
    
def moreInfo_hideURL(e):
    moreinfo_win.withdraw()
    
def open_event(e):
    '''Read data from the event, and show the window.'''
    wid = e.widget
    snd.fx('expand')
    showProps(wid)
        
def showProps(wid):
    '''Show the properties window for an item.'''
    global selected_item, selected_sub_item, is_open
    is_open = True
    prop_window.deiconify()
    prop_window.lift(root)
    
    selected_item = wid.item
    selected_sub_item = wid
    icon_widget = wid_sub[pos_for_item(selected_sub_item.subKey)]
    
    loc_x=wid.winfo_rootx() + prop_window.winfo_rootx() - icon_widget.winfo_rootx()
        #The pixel offset between the window and the subitem in the properties dialog
    loc_y=wid.winfo_rooty() + prop_window.winfo_rooty() - wid_sub[0].winfo_rooty()
    
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
    
    for ind, pos in enumerate(SUBITEM_POS[selected_item.num_sub]):
        if pos == -1:
            wid_sub[ind]['image'] = png.loadPng('BEE2/alpha_64')
        else:
            wid_sub[ind]['image'] = selected_item.get_icon(pos)
        wid_sub[ind]['relief'] = 'flat'
    icon_widget['relief'] = 'raised'
    
    wid_author['text'] = ', '.join(selected_item.data['auth'])
    wid_name['text'] = selected_sub_item.name
    wid_ent_count['text'] = selected_item.data['ent']
    
    wid_desc['state']="normal"
    wid_desc.delete(1.0, END)
    wid_desc.insert("end", selected_item.data['desc'], "all") 
    wid_desc['state']="disabled"
    
    if selected_item.url is None:
        wid_moreinfo.state(('disabled',))
    else:
        wid_moreinfo.state(('!disabled',))
    set_sprites(selected_item)
    
            
def set_sprites(item):
    editor_data = item.data['editor']
    has_inputs = False
    has_polarity = False
    has_outputs = False
    for inp_list in Property.find_all(editor_data, "Item", "Exporting", "Inputs"):
        for inp in inp_list:
            if inp.name == "CONNECTION_STANDARD":
                has_inputs = True
            elif inp.name == "CONNECTION_TBEAM_POLARITY":
                has_polarity = True
    for out_list in Property.find_all(editor_data, "Item", "Exporting", "Outputs"):
        for out in out_list:
            if out.name == "CONNECTION_STANDARD":
                has_outputs = True
                break
    has_timer = any(Property.find_all(editor_data, "Item", "Properties", "TimerDelay"))
    
    editor_bit = next(Property.find_all(editor_data, "Item", "Editor"))
    rot_type = editor_bit["MovementHandle", "HANDLE_NONE"].casefold()
    
    facing_type = editor_bit["InvalidSurface", ""].casefold()
    surf_wall = "wall" in facing_type
    surf_floor = "floor" in facing_type
    surf_ceil = "ceiling" in facing_type

    is_embed = any(Property.find_all(editor_data, "Item", "Exporting", "EmbeddedVoxels"))
            
    if has_inputs:
        if has_polarity:
            wid_spr[0]['image'] = png.loadSpr('in_polarity')
        else:
            wid_spr[0]['image'] = png.loadSpr('in_norm')
    else:
        wid_spr[0]['image'] = png.loadSpr('in_none')
    
    if has_outputs:
        if has_timer:
            wid_spr[1]['image'] = png.loadSpr('out_tim')
        else:
            wid_spr[1]['image'] = png.loadSpr('out_norm')
    else:
        wid_spr[1]['image'] = png.loadSpr('out_none')
        
    wid_spr[2]['image'] = png.loadSpr(ROT_TYPES.get(rot_type.casefold(), 'rot_none'))
         
    if is_embed:
        wid_spr[3]['image'] = png.loadSpr('space_embed')
    else:
        wid_spr[3]['image'] = png.loadSpr('space_none')
       
    face_spr = "surf"
    if not surf_wall:
        face_spr += "_wall"
    if not surf_floor:
        face_spr += "_floor"
    if not surf_ceil:
        face_spr += "_ceil"
    if face_spr == "surf":
        face_spr += "_none"
    wid_spr[4]['image'] = png.loadSpr(face_spr)
    
def follow_main():
    '''Move the properties window to keep a relative offset to the main window.'''
    prop_window.geometry('+'+str(prop_window.relX+root.winfo_x())+
                         '+'+str(prop_window.relY+root.winfo_y()))

def hideProps(e=None):
    '''Hide the properties window, if it's open.'''
    global is_open
    if is_open:
        is_open=False
        prop_window.withdraw()
        snd.fx('contract')

def init(win):
    '''Initiallise all the window components.'''
    global root, prop_window, wid_name, wid_ent_count, wid_author, sub_frame, wid_desc, wid_moreinfo, wid_variant, wid_changedefaults, moreinfo_win, moreinfo_lbl
    root = win
    prop_window=Toplevel(root)
    prop_window.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    prop_window.resizable(False, False)
    prop_window.transient(master=root)
    prop_window.attributes('-topmost', 1)
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
        wid_sub[i]=ttk.Label(sub_frame, image=png.loadPng('BEE2/alpha_64'))
        wid_sub[i].grid(row=0, column=i)
        wid_sub[i].bind('<Button-1>', func_partial(sub_sel, i))
        wid_sub[i].bind('<Enter>', func_partial(sub_sel_enter, i))
    ttk.Label(f, text="Description:", anchor="sw").grid(row=4, column=0, sticky="SW")
    spr_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
    # sprites: inputs, outputs, rotation handle, occupied/embed state, desiredFacing
    for i in range(5):
        spr=png.loadSpr('ap_grey')
        wid_spr[i]=ttk.Label(spr_frame, image=spr, relief="raised")
        wid_spr[i].grid(row=0, column=i)
    desc_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    desc_frame.grid(row=5, column=0, columnspan=3, sticky="EW")
    wid_desc=Text(desc_frame, width=40, height=8, wrap="word")
    wid_desc.tag_config("all", lmargin2="10") # Add a hanging indent to wrapped lines
    wid_desc.grid(row=0, column=0, sticky="EW")

    desc_scroll=ttk.Scrollbar(desc_frame, orient=VERTICAL, command=wid_desc.yview)
    wid_desc['yscrollcommand']=desc_scroll.set
    desc_scroll.grid(row=0, column=1, sticky="NS")
    wid_desc['state']="disabled" # need to set this to normal when editing text, then swap back

    wid_moreinfo=ttk.Button(f, text="More Info>>", command=showMoreInfo)
    wid_moreinfo.grid(row=6, column=2, sticky=E)
    
    moreinfo_win = Toplevel(win)
    moreinfo_win.withdraw()
    moreinfo_win.transient(master=win)
    moreinfo_win.overrideredirect(1)
    moreinfo_win.resizable(False, False)
    
    moreinfo_lbl = ttk.Label(moreinfo_win, text='', relief="groove")
    moreinfo_lbl.grid(row=0, column=0, padx=1, pady=1)
    
    wid_moreinfo.bind('<Enter>', moreInfo_showURL)
    wid_moreinfo.bind('<Leave>', moreInfo_hideURL)

    
    menu_info = Menu(wid_moreinfo)
    menu_info.add_command(label='', state='disabled')

    wid_changedefaults=ttk.Button(f, text="Change Defaults...", command=showItemProps)
    wid_changedefaults.grid(row=6, column=1)

    wid_variant=ttk.Combobox(f, values=("Recessed","Compat (On Top)"))
    wid_variant.current(0)
    wid_variant.grid(row=6, column=0, sticky=W)
    
    itemPropWin.init(root, hideItemProps)
    