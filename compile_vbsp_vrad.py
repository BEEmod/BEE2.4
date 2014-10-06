from cx_Freeze import setup, Executable
import os
# need to get the verson from http://www.lfd.uci.edu/~gohlke/pythonlibs/#cx_freeze for it to work with python 3.4 atm (as of 29/09/14)
exes = [
        Executable('vbsp.py', base='Console', icon=os.getcwd() + "/bee2.ico"), 
        Executable('vrad.py', base='Console', icon=os.getcwd() + "/bee2.ico")
       ]
setup(name='VBSP',
      version = '0.1',
      description = 'BEE2 VBSP replacement',
      executables = exes)