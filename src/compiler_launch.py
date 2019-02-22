"""Launches the correct compiler."""
import os
import sys

if hasattr(sys, 'frozen'):
    app_name = os.path.basename(sys.executable)
else:
    # Sourcecode-launch - check first sys arg.
    app_name = sys.argv.pop(1)

if app_name in ('vbsp.exe', 'vbsp_osx', 'vbsp_linux'):
    import vbsp
    vbsp.main()
elif app_name in ('vrad.exe', 'vrad_osx', 'vrad_linux'):
    import vrad
    vrad.main(sys.argv)
elif 'original' in app_name:
    sys.exit('Original compilers replaced, verify game cache!')
else:
    sys.exit('Unknown application name "{}"!'.format(app_name))
