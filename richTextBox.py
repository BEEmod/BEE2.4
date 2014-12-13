from tkinter import * # ui library
from tkinter.font import Font as tkFont
from tkinter import ttk

class tkRichText(Text):
    '''A version of the TK Text widget with some options to allow writing with special formatting.
    
    The format for the text is a list of tuples, where each tuple is (type, text).
    Types:
     - "line" : standard line, with carriage return after.
     - "bullet" : indented with a bullet at the beginning
     - "list" : indented with "1. " at the beggining, the number increasing
     - "hrule" : A horizontal line. This ignores the text part.
    '''
    def __init__(self, parent, width=10, height=4, font="TkDefaultFont"):
        super().__init__(parent, width=width, height=height, wrap="word", font=font)
        self.tag_config("indent", lmargin1="10", lmargin2="25")
        self.tag_config("hrule", relief="sunken", borderwidth=1, font=tkFont(size=1))
        self['state'] = "disabled"
    
    _insert = Text.insert
    
    def insert(*args, **kwargs):
        pass
        
    def set_text(self, desc):
        '''Write the rich-text into the textbox.'''
        self['state']="normal"
        self.delete(1.0, END)
        list_ind = 1
        for data in desc:
            lineType=data[0].casefold()
            if lineType == "line":
                self._insert("end", data[1] + "\n") 
            elif lineType == "bullet":
                self._insert("end", '\x07 ' + data[1] + "\n", "indent") 
            elif lineType == "list":
                self._insert("end", str(list_ind) + ". " + data[1] + "\n", "indent")
                list_ind += 1
            elif lineType == "rule":
                self.insert("end", " \n", "hrule")
                # Horizontal rules are created by applying a tag to a space + newline (which affects the whole line)
                # It decreases the text size (to shrink it vertically, and gives a border
            else:
                print('Unknown description type "' + lineType + '"!')     
        self['state']="disabled"