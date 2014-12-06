copy /B/Y "F:\Git\BEE2.4\vbsp_config.cfg" "F:\SteamLibrary\SteamApps\common\Portal 2\bin\vbsp_config.cfg"
python compile_vbsp_vrad.py build
copy /B/Y "F:\Git\BEE2.4\build_compiler\library.zip" "F:\SteamLibrary\SteamApps\common\Portal 2\bin\library.zip"