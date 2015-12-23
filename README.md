# Better Extended Editor 2 version 4 #
A Portal 2  Mod tool

[![forthebadge](http://forthebadge.com/images/badges/designed-in-ms-paint.svg)](http://forthebadge.com)
[![forthebadge](http://forthebadge.com/images/badges/made-with-crayons.svg)](http://forthebadge.com)

The BEE2 allows reconfiguring Portal 2's Puzzlemaker editor to use additional items, reskin maps for 
different eras, and configure many other aspects. All vanilla items have been upgraded with additional 
bugfixes and improvments.

The packages (item, style, etc definitions) are in the [BEE2-Items](https://github.com/TeamSpen210/BEE2-items) repository.

## Download
Download the BEE2.4 on the releases pages:
- [Application](https://github.com/BenVlodgi/BEE2.4/releases)
- [Packages](https://github.com/TeamSpen210/BEE2-items/releases)

## Dependencies: ##
- [pyGame](http://www.pygame.org/) (for sounds, not required)
- [Pillow](https://python-pillow.github.io/)

## Modules: ##
- Common:
	- `property_parser`: Library to allow reading and writing Valve's KeyValues format.
	- `utils`: Various utility functions and a Vector class.
- BEE Application:
	- `BEE2`: Main application script, starts up the application.
	- `BEE2_config`: Subclass of `ConfigParser`, with some useful tweaks
	- `compile_BEE2`: Cx-Freeze setup script to compile the BEE2 application.
	- `compilerPane`: Window pane which controls compiler options. This updates configs in real time.
	- `contextWin`: Implements the rightclick context menu for items.
	- `FakeZip`: simulates a ZipFile object based on a directory. Used to allow `packageLoader` to load either, without needing to check the type every time.
	- `gameMan`: Manages adding and removing games as well as exporting editoritems.
	- `img`: read PNG files into Tkinter-compatible formats. Caches calls so an image is only read once.
	- `itemPropWin`: A window which allows changing the default properties for an item.
	- `loadScreen`: Shows a window with loading bars during the startup process.
	- `optionWindow`: The BEE2 configuration window.
	- `packageLoader`: Reads packages and parses all data out of them.
	- `paletteLoader`: Reads and writes palettes to disk.
	- `query_dialogs`: A version of `tkinter.simpledialogs.ask_string`, which uses the BEE2 icon.
	- `richTextBox`: Subclassed version of Tkinter's Text widget, with options to allow easily adding special formating like bullet lists.
	- `selectorWin`: Window class which allows picking items from a list, displaying various data about each option.
	- `sound`: Handles playing sound effects, using PyGame. Gracefully fails if not present
	- `StyleVarPane`: Window Pane which sets Style Properties, controlling certain style options.
	- `SubPane`: Toplevel subclass which can be shown and hidden via a button, and follows the main window around.
	- `tagsPane`: The dropdown which allows filtering the item list by tags.
	- `tk_root`: Holds the singleton tkinter.Tk() instance, so the main window is only created once.
	- `tooltip`: Allows registering a tooltip to appear on top of a widget.
	- `UI`: Holds the majority of the UI code, tying the components together.
	- `voiceEditor`: Window for viewing voice pack lines, and enabling/disabling individual ones.
- VBSP and VRAD:
	- `BSP`: Library for reading and writing BSP files. Used to pack files during compile.
	- `compile_vbsp_vrad`: Cx-Freeze setup script to compile the VBSP and VRAD hooks.
	- `conditions`: Implements the conditions system, controlling item-specific transformations.
	- `cutoutTile`: Logic for the Cutout Tile item.
	- `instanceLocs`: Translates `<ITEM_ID:0,1>` text into the associated instance paths.
	- `vbsp`: The BEE2's VBSP hook, which modifies a map VMF before it is compiled by the original VBSP.
	- `vbsp_launch`: Wrapper around vbsp, to get around the renaming of scripts to `'__main__'`.
	- `vmfLib`: A library which parses a VMF file to allow easy modification.
	- `voiceLine`: Parses quote pack data, and determines the appropriate quote to use for a given map.
	- `vrad`: The BEE2's VRAD hook, which switches to use fast lighting when not in preview mode, and packs files into the BSP after the compilation.
