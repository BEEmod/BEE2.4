"""Launches the correct compiler."""
import exceptiongroup  # noqa - Install its import hook
import os
import sys


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
    import trio

    import vbsp
    trio.run(vbsp.main)
elif app_name in ('vrad.exe', 'vrad_osx', 'vrad_linux'):
    if '--errorserver' in sys.argv:
        import trio

        import error_server
        trio.run(
            error_server.main,
            strict_exception_groups=True,  # Opt into 3.11-style semantics.
        )
    else:
        import trio

        import vrad
        trio.run(
            vrad.main, sys.argv,
            strict_exception_groups=True,
        )
elif 'original' in app_name:
    sys.exit('Original compilers replaced, verify game cache!')
else:
    sys.exit(f'Unknown application name "{app_name}"!')
