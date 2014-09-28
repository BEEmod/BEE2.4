from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
buildOptions = dict(packages = [], excludes = [])

base = 'Console'

executables = [
    Executable('F:\\Git\\BEE2.4\\vbsp.py', base=base, targetName = 'vbsp.exe')
]

setup(name='VBSP',
      version = '0.1',
      description = 'BEE2 VBSP replacement',
      options = dict(build_exe = buildOptions),
      executables = executables)