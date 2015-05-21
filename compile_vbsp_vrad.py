from cx_Freeze import setup, Executable
import os

ico_path = os.path.join(os.getcwd(), "bee2.ico")

setup(name='VBSP_VRAD',
      version = '0.1',
      options = {'build_exe': {'build_exe': 'build_compiler'}},
      description = 'BEE2 VBSP and VRAD compilation hooks, for modifying PeTI maps during compilation.',
      executables = [Executable('src/vbsp.py', base='Console', icon=ico_path),
                     Executable('src/vrad.py', base='Console', icon=ico_path)])