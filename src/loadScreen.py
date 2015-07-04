"""Displays a loading menu while packages, palettes, etc are being loaded."""
from tkinter import *  # ui library
from tk_root import TK_ROOT
from tkinter import ttk  # themed ui components that match the OS

class LoadScreen(Toplevel):

    def __init__(self, *stages):
        self.stages = list(stages)
        self.widgets = {}
        self.labels = {}
        self.bar_var = {}
        self.bar_val = {}
        self.maxes = {}
        self.num_images = 0

        self.active = True
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything.

        super().__init__(TK_ROOT, cursor='watch') # Initialise the window

        # this prevents stuff like the title bar, normal borders etc from
        # appearing in this window.
        self.overrideredirect(1)
        self.resizable(False, False)
        self.attributes('-topmost', 1)
        self.geometry('+200+200')
        self.deiconify()

        ttk.Label(
            self,
            text='Loading...',
            font=("Helvetica", 12, "bold"),
            ).grid(columnspan=2)
        ttk.Separator(
            self,
            orient=HORIZONTAL,
            ).grid(row=1, sticky="EW", columnspan=2)

        for ind, (st_id, stage_name) in enumerate(self.stages):
            ttk.Label(
                self,
                text=stage_name + ':',
                ).grid(
                    row=ind*2+2,
                    columnspan=2,
                    sticky="W",
                    )
            self.bar_var[st_id] = IntVar()
            self.bar_val[st_id] = 0
            self.maxes[st_id] = 10

            self.widgets[st_id] = ttk.Progressbar(
                self,
                length=210,
                maximum=1000,
                variable=self.bar_var[st_id],
                )
            self.labels[st_id] = ttk.Label(self, text='0/??')
            self.widgets[st_id].grid(row=ind*2+3, column=0, columnspan=2)
            self.labels[st_id].grid(row=ind*2+2, column=1, sticky="E")

    def show(self):
        """Display this loading screen."""
        self.update()  # Force an update so the reqwidth is correct
        loc_x = (self.winfo_screenwidth()-self.winfo_reqwidth())//2
        loc_y = (self.winfo_screenheight()-self.winfo_reqheight())//2
        self.geometry('+' + str(loc_x) + '+' + str(loc_y))
        self.update()  # Force an update of the window to position it

    def set_length(self, stage, num):
        """Set the number of items in a stage."""
        if self.active:
            self.maxes[stage] = num
            self.set_nums(stage)

    def step(self, stage):
        """Increment a step by one."""
        if self.active:
            self.bar_val[stage] += 1
            self.bar_var[stage].set(
                1000 * self.bar_val[stage] / self.maxes[stage]
            )
            self.widgets[stage].update()
            self.set_nums(stage)

    def set_nums(self, stage):
        self.labels[stage]['text'] = '{!s}/{!s}'.format(
            self.bar_val[stage],
            self.maxes[stage],
        )

    def skip_stage(self, stage):
        """Skip over this stage of the loading process."""
        if self.active:
            self.labels[stage]['text'] = 'Skipped!'
            self.bar_var[stage].set(1000)  # Make sure it fills to max
            self.widgets[stage].update()

    def reset(self):
        """Hide the loading screen and reset all the progress bars."""
        self.withdraw()
        for stage, _ in self.stages:
            self.maxes[stage] = 10
            self.bar_val[stage] = 0
            self.bar_var[stage].set(0)
            self.labels[stage]['text'] = '0/??'
            self.set_nums(stage)

    def destroy(self):
        """Delete all parts of the loading screen."""
        if self.active:
            super().destroy()
            del self.widgets
            del self.maxes
            del self.bar_var
            del self.bar_val
            self.active = False

main_loader = LoadScreen(
    ('PAK', 'Packages'),
    ('OBJ', 'Loading Objects'),
    ('IMG_EX', 'Extracting Images'),
    ('IMG', 'Loading Images'),
    ('UI', 'Initialising UI'),
)