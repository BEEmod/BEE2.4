"""Launches the correct compiler."""
import os
import sys
import trio  # Install its import hook

if hasattr(sys, 'frozen'):
    app_name = os.path.basename(sys.executable).casefold()
    # On Linux, we're in bin/linux32/, not bin/. So everything else works as expected,
    # move back.
    folder = os.path.basename(os.getcwd())
    if folder.casefold() == 'linux32':
        os.chdir(os.path.dirname(os.getcwd()))
else:
    # Sourcecode-launch - check first sys arg.
    app_name = sys.argv.pop(1).casefold()

if app_name in ('vbsp.exe', 'vbsp_osx', 'vbsp_linux'):
    if '--errorserver' in sys.argv:
        import error_server
        trio.run(error_server.main)
    else:
        import vbsp
        vbsp.main()
elif app_name in ('vrad.exe', 'vrad_osx', 'vrad_linux'):
    import vrad
    trio.run(vrad.main, sys.argv)
elif 'original' in app_name:
    sys.exit('Original compilers replaced, verify game cache!')
else:
    sys.exit('Unknown application name "{}"!'.format(app_name))
