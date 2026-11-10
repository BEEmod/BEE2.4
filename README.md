[![BEE2-items Releases](https://img.shields.io/github/downloads/BEEmod/BEE2-items/total.svg?label=Packages)](https://github.com/BEEmod/BEE2-items/releases)
[![BEE2.4 Releases](https://img.shields.io/github/downloads/BEEmod/BEE2.4/total.svg?label=App)](https://github.com/BEEmod/BEE2.4/releases)
[![Discord Server](https://img.shields.io/discord/293435914598744064?color=%235865F2&label=Discord)](https://discord.gg/hnGFJrz)

![BEE2 Icon](https://raw.githubusercontent.com/BEEmod/BEE2.4/master/BEE2.ico)
# Better Extended Editor 2 version 4 #
## Portal 2  Mod Tool
The BEE2 allows reconfiguring Portal 2's Puzzlemaker editor to use additional items, reskin maps for
different eras, and configure many other aspects. All vanilla items have been upgraded with additional
bugfixes and improvements.

The packages (item, style, etc definitions) are in the [BEE2-Items](https://github.com/BEEmod/BEE2-items) repository.

[Discussion Forums](https://github.com/BEEmod/BEE2-items/discussions)
[Discord Server](https://discord.gg/hnGFJrz)

## Download and Use
### Windows
- Download the latest releases of the BEE2.4 and items from the following pages:
  - [Application](https://github.com/BEEmod/BEE2.4/releases)
  - [Item Packages](https://github.com/BEEmod/BEE2-items/releases)
- Extract the contents of the Application release anywhere you like. _e.g. `C:\BEE2.4`_
- Place extracted package folder in the root BEE2 folder. _e.g. `C:\BEE2.4\packages`_
- To run, locate the BEE2 application in the app folder and execute it. _e.g. `C:\BEE2.4\BEE2.exe`_

### Linux
Linux support exists, but is experimental. We do not currently provide precompiled releases. See the [BEE2.4 on Linux](https://github.com/BEEmod/BEE2-items/wiki/BEE2.4-on-Linux) wiki article for more information.

### macOS
BEE2.4 no longer supports macOS, and Portal 2 has not been able to run natively on the platform for many years at this point. See the [BEE2.4 on macOS](https://github.com/BEEmod/BEE2-items/wiki/BEE2.4-on-macOS) wiki article for more information.

## Technical Info ##

### Building from Source ###

* You'll need Python 3.12 or later.
* First, grab the repo and then clone the HammerAddons submodule:

	    git clone --recurse-submodules https://github.com/BEEmod/BEE2.4.git
	    cd BEE2.4
	    git submodule update --init

* Run `python -m pip install -r requirements.txt` to install the required packages. On Linux, 
Pillow, TK and IDLE might need to be installed via the system package manager:
`python-pillow`, `python-pillow.imagetk`, `python-tkinter`, `python-idle`, etc.

* To allow sound effects in the app, you need a copy of FFmpeg:
	* In the `BEE2.4` folder, add `lib-32` and/or `lib-64/` folders.
	* Download the [32-bit](https://github.com/sudo-nautilus/FFmpeg-Builds-Win32/releases) or [64-bit](https://github.com/BtbN/FFmpeg-Builds/releases) builds (`winXX-lgpl-shared`), then copy the contents of the `bin` folder into the appropriate `lib-XX` folder mentioned.

* Finally, switch to the BEE2.4 repo and build the compiler, then the application (You should be in the BEE2.4 folder already):

	    cd src/
	    pyinstaller --distpath ../dist/64bit/ --workpath ../build_tmp compiler.spec
	    pyinstaller --distpath ../dist/64bit/ --workpath ../build_tmp BEE2.spec
	
* The built application is found in `BEE2.4/dist/64bit/BEE2/`.
To generate the packages zips, either manually zip the contents of each folder or 
use the `compile_packages` script in BEE2-items. 
This does the same thing, but additionally removes some unnessary content 
to decrease file sizes - comments, blank lines, hidden visgroups.

* For Linux Compilation check out this wiki entry [Building from Source](https://github.com/BEEmod/BEE2-items/wiki/Building-from-source) 

### Used Libraries ###
- [Python](https://www.python.org/) 3.12 or later
- [TKinter/TTK](https://tcl.tk/)
- [pyglet](https://bitbucket.org/pyglet/pyglet/wiki/Home) (for sounds, not required)
- [Pillow](https://python-pillow.github.io/)
- [noise](https://pypi.python.org/pypi/noise/)  (For perlin/simplex noise, as `src/perlin.py`)
- [mistletoe](https://github.com/miyuchina/mistletoe)
- [cython](https://cython.org/)
- [PyInstaller](http://www.pyinstaller.org/)
- [babel](http://babel.pocoo.org/en/latest/index.html)
