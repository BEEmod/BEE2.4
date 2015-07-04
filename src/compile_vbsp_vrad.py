from cx_Freeze import setup, Executable
import os
import utils

ico_path = os.path.join(os.getcwd(), "../bee2.ico")

setup(
    name='VBSP_VRAD',
    version='0.1',
    options={
        'build_exe':
            {
                'build_exe': '../compiler'
            }
    },
    description='BEE2 VBSP and VRAD compilation hooks, '
                'for modifying PeTI maps during compilation.',
    executables=[
        Executable(
            'vbsp_launch.py',
            base='Console',
            icon=ico_path,
            targetName='vbsp.exe' if utils.WIN else 'vbsp',
        ),
        Executable(
            'vrad.py',
            base='Console',
            icon=ico_path,
            targetName='vrad.exe' if utils.WIN else 'vrad',
        )
    ]
)