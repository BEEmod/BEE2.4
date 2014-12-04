from cx_Freeze import setup, Executable
import os

ico_path = os.path.join(os.getcwd(), "bee2.ico")

setup(name='VBSP',
      version = '0.1',
      options = {'build_exe': {'build_exe':'build_compiler'}},
      description = 'BEE2 VBSP replacement',
      executables = [Executable('vbsp.py', base='Console', icon=ico_path)])
      
setup(name='VRAD',
      version = '0.1',
      options = {'build_exe': {'build_exe':'build_compiler'}},
      description = 'BEE2 VRAD replacement',
      executables = [Executable('vrad.py', base='Console', icon=ico_path)])