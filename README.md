[![BEE2.4 Releases](https://img.shields.io/github/downloads/BEEmod/BEE2.4/total.svg?label=App)](https://github.com/BEEmod/BEE2.4/releases)
[![BEE2-items Releases](https://img.shields.io/github/downloads/BEEmod/BEE2-items/total.svg?label=Packages)](https://github.com/BEEmod/BEE2-items/releases)

### Please read the [Contributing Guidelines](https://github.com/BEEmod/BEE2-items/blob/master/.github/contributing.md) and [FAQ](https://github.com/BEEmod/BEE2-items/wiki/FAQ) before opening an issue.

![BEE2 Icon](https://raw.githubusercontent.com/BEEmod/BEE2.4/master/bee2.ico)
# Better Extended Editor 2 version 4 #
## Portal 2  Mod Tool
The BEE2 allows reconfiguring Portal 2's Puzzlemaker editor to use additional items, reskin maps for
different eras, and configure many other aspects. All vanilla items have been upgraded with additional
bugfixes and improvements.

The packages (item, style, etc definitions) are in the [BEE2-Items](https://github.com/BEEmod/BEE2-items) repository.

[Discord Server](https://discord.gg/hnGFJrz)

## Download and Use
- Download the latest releases of the BEE2.4 and items from the following pages:
  - [Application](https://github.com/BEEmod/BEE2.4/releases)
  - [Item Packages](https://github.com/BEEmod/BEE2-items/releases)
- Extract the contents of the Application release anywhere you like. _e.g. `C:\BEE2.4`_
- Place extracted package folder in the root BEE2 folder. _e.g. `C:\BEE2.4\packages`_
- To run, locate the BEE2 application in the app folder and execute it. _e.g. `C:\BEE2.4\BEE2.exe`_

### Used Libraries ###
- [Python](https://www.python.org/)
- [TKinter/TTK](https://tcl.tk/)
- [pyglet](https://bitbucket.org/pyglet/pyglet/wiki/Home) and [AVBin](http://avbin.github.io/AVbin/Home/Home.html) (for sounds, not required)
- [Pillow](https://python-pillow.github.io/)
- [noise](https://pypi.python.org/pypi/noise/)  (For perlin/simplex noise, as `src/perlin.py`)
- [markdown](https://pythonhosted.org/Markdown/)
- [cython](https://cython.org/)
- [PyInstaller](http://www.pyinstaller.org/)
- [babel](http://babel.pocoo.org/en/latest/index.html)

## Building from Source ##

### PyPI list: ###
* pillow (On Linux this may need to be installed via system package manager with the TK component: `python-pillow`, `python-pillow.imagetk`)
* markdown
* pyglet
* PyInstaller
* cython
* babel

[AVBin](http://avbin.github.io/AVbin/Download.html) must also be installed, to provide codecs for pyglet.

### Compilation ###
First, grab the 2 git repositories you need:

	git clone https://github.com/TeamSpen210/srctools.git
	git clone https://github.com/BEEmod/BEE2.4.git
	
Switch to the srctools repo, and install the package:

	cd srctools/
	python setup.py install

Finally, switch to the BEE2.4 repo and build the compiler, then the application:

    cd BEE2.4/src/
	pyinstaller --distpath ../dist/ --workpath ../build_tmp compiler.spec
	pyinstaller --distpath ../dist/ --workpath ../build_tmp BEE2.spec
	
The built application is found in `BEE2.4/dist/BEE2/`.
Copy `BEE2.4/dist/BEE2/` into this folder as well.
To generate the packages zips, either manually zip the contents of each folder or 
use the `compile_packages` script in BEE2-items. 
This does the same thing, but additionally removes some unnessersary content 
to decrease file sizes - comments, blank lines, hidden visgroups.
