# Better Extended Editor 2 version 4 #
A Portal 2  Mod tool

[![forthebadge](http://forthebadge.com/images/badges/designed-in-ms-paint.svg)](http://forthebadge.com)
[![forthebadge](http://forthebadge.com/images/badges/made-with-crayons.svg)](http://forthebadge.com)

The BEE2 allows reconfiguring Portal 2's Puzzlemaker editor to use additional items, reskin maps for
different eras, and configure many other aspects. All vanilla items have been upgraded with additional
bugfixes and improvments.

The packages (item, style, etc definitions) are in the [BEE2-Items](https://github.com/TeamSpen210/BEE2-items) repository.

## Download and Use
Download the BEE2.4 on the releases pages:
- [Application](https://github.com/BenVlodgi/BEE2.4/releases)
- [Packages](https://github.com/TeamSpen210/BEE2-items/releases)
Extract the contents of the Application release anywhere you like. 
Place extracted package folder in the root BEE2 folder.
To run, locate the BEE2.exe in the bin folder and exicute it.


## Dependencies: ##
- [pyGame](http://www.pygame.org/) (for sounds, not required)
- [Pillow](https://python-pillow.github.io/)
- [noise](https://pypi.python.org/pypi/noise/)  (For perlin/simplex noise, as `src/perlin.py`)
- TKinter/TTK (Standard Library)

## Compilation: ##
To build the executable versions of the BEE2, run the `compile_BEE2` and `compile_VBSP_VRAD` scripts with a command-line
argument of build:

    cd BEE2.4/src/
	python compile_BEE2 build
	...
	python compile_VBSP_VRAD build
	...

The application executables will be saved in `build_BEE2`, and the compilers in `compiler/`. To generate the packages
zips, either manually zip the contents of each folder or use the `compile_packages` script in BEE2-items. This does the same thing, but additionally removes some unnessersary content to decrease file sizes - comments, blank lines, hidden visgroups.

For the release copy, it should include:

* `build_BEE2` (renamed to `bin`)
* `compiler`
* `palettes`
* `packages` (from BEE2-items)
* `images` (without the `cache` subfolder)
* `sounds`
* `basemodui.txt`
* `BEE2.ico`

The various `cache` folders and `config` folders should not be included.

## Modules: ##
- Common:
	- `property_parser`: Library to allow reading and writing Valve's KeyValues format.
	- `utils`: Various utility functions and a Vector class.
	- `vmfLib`: A library which parses a VMF property tree to allow easy modification.
- BEE Application:
	- `BEE2`: Main application script, starts up the application.
	- `BEE2_config`: Subclass of `ConfigParser`, which keeps track of the config file it's read from.
	- `backup`: A window for backing up and restoring P2C files into zips.
	- `compile_BEE2`: Cx-Freeze setup script to compile the BEE2 application.
	- `compilerPane`: Window pane which controls compiler options. This updates configs in real time.
	- `contextWin`: Implements the rightclick context menu for items.
	- `FakeZip`: simulates a ZipFile object based on a directory. Used to allow `packageLoader` to load either, without needing to check the type every time.
	- `gameMan`: Manages adding and removing games as well as exporting editoritems.
	- `img`: read PNG files into Tkinter-compatible formats. Caches calls so an image is only read once.
	- `itemPropWin`: A window which allows changing the default properties for an item.
	- `loadScreen`: Shows a window with loading bars during the startup process.
	- `logWindow`: Displays log messages.
	- `optionWindow`: The BEE2 configuration window.
	- `packageLoader`: Reads packages and parses all data out of them.
	- `paletteLoader`: Reads and writes palettes to disk.
	- `query_dialogs`: A version of `tkinter.simpledialogs.ask_string`, which uses the BEE2 icon.
	- `richTextBox`: Subclassed version of Tkinter's Text widget, with options to allow easily adding special formating like bullet lists.
	- `selectorWin`: Window class which allows picking items from a list, displaying various data about each option.
	- `sound`: Handles playing sound effects, using PyGame. Gracefully fails if Pygame is not present.
	- `StyleVarPane`: Window Pane which sets Style Properties, controlling certain style options.
	- `SubPane`: Toplevel subclass which can be shown and hidden via a button, and follows the main window around.
	- `tagsPane`: The dropdown which allows filtering the item list by tags.
	- `tk_tools`: Holds the singleton tkinter.Tk() instance and several custom widget classes.
	- `tooltip`: Allows registering a tooltip to appear on top of a widget.
	- `UI`: Holds the majority of the UI code, tying the components together.
	- `voiceEditor`: Window for viewing voice pack lines, and enabling/disabling individual ones.
- VBSP and VRAD:
	- `BSP`: Library for reading and writing BSP files. Used to pack files during compile.
	- `compile_vbsp_vrad`: Cx-Freeze setup script to compile the VBSP and VRAD hooks.
	- `conditions`: Implements the conditions system, controlling item-specific transformations.
	    Submodules add the individual conditions:
	    - `addInstance`: Results which add additional instances.  
	        (_addGlobal_, _addOverlay_, _addCavePortrait_)
		- `brushes`: Results dealing with instances.  
			(_GenRotatingEnt_, _AlterFace_, _AddBrush_, _TemplateBrush_)
		- `fizzler`: Results for custom fizzler items.  
			(_CustFizzler_, _fizzlerModelPair_)
	    - `globals`: Global flags allowing reference to stylevars, voicelines, etc.  
	        (_styleVar_, _has*_, _Game_, _HasCavePortrait_, _isPreview_)
	    - `instances`: Flags and Results for instances - filenames, orientation, locations.  
	        (_instance_, _has\_inst_, _instVar_)
			(_clearOutputs_, _changeInstance_, _setInstVar_, _suffix_,  _localTarget_)
		- `positioning`: Flags/Results for dealing with the positioning of items.  
			(_rotation_, _posIsSolid_, _posIsGoo_, _forceUpright_, _OffsetInst_)
	    - `logical`: Flags like AND, OR and NOT. Used to comine with other flags.  
	        (_AND_, _OR_, _NOT_, _NOR_, _NAND_)
		- `randomise`: Results for randomising instances.  
			(_random_, _variant_, _randomNum_, _randomVec_)
		- `trackPlat`: Result for modifying track platforms. (_trackPlatform_)
	    - `cutoutTile`: Logic for the Cutout Tile item. (_CutoutTile_)
		- `catwalks`: Logic for Catwalk items (_MakeCatwalk_)
		- `scaffold`: Logic for Unstationary Scaffolds. (_UnstScaffold_)
	- `instanceLocs`: Translates `<ITEM_ID:0,1>` text into the associated instance paths.
	- `vbsp`: The BEE2's VBSP hook, which modifies a map VMF before it is compiled by the original VBSP.
	- `vbsp_launch`: Wrapper around vbsp, to get around the renaming of scripts to `'__main__'`.
	- `voiceLine`: Parses quote pack data, and determines the appropriate quote to use for a given map.
	- `vrad`: The BEE2's VRAD hook, which switches to use fast lighting when not in preview mode, and packs files into the BSP after the compilation.
