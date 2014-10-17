from cx_Freeze import setup, Executable
import os
exes = [
        Executable('vbsp.py', base='Console', icon=os.getcwd() + "/bee2.ico"), 
        Executable('vrad.py', base='Console', icon=os.getcwd() + "/bee2.ico")
       ]
setup(name='VBSP',
      version = '0.1',
      description = 'BEE2 VBSP replacement',
      executables = exes)