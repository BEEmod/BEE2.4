# Better Extended Editor 2 version 4

A Portal 2  Mod tool

# Modules:
- BEE2: Main application script, starts up the application.
- config: Subclass of ConfigParser, with some useful tweaks
- contextWin: Implements the rightclick context menu for items.
- gameMan: Manages adding and removing games as well as exporting editoritems.
- itemPropWin: A window which allows changing the default properties for an item.
- loadScreen: Shows a window with loading bars during the startup process.
- packageLoader: Reads packages and parses all data out of them.
- paletteLoader: Reads and writes palettes to disk.
- property_parser: Library to allow reading and writing Valve's KeyValues format.
- richTextBox: Subclassed version of Tkinter's Text widget, with options to allow easily adding special formating like bullet lists.
- selectorWin: Window class which allows picking items from a list, displaying various data about each option.
- sound: Handles playing sound effects, using PyGame.
- UI: Holds the majority of the UI code, tying the components together.
- utils: Various utility functions and a Vector class.
- VBSP: The BEE2's VBSP hook, which modifies a map VMF before it is compiled by the original VBSP.
- vmfLib: A library which parses a VMF file to allow easy modification.
- voiceLine: Parses quote pack data, and determines the appropriate quote to use for a given map.
- VRAD: The BEE2's VRAD hook, which switches to use fast lighting when not in preview mode, and packs files into the BSP after the compilation.

- png
- tkinter_png: Libraries to read PNG files into Tkinter-compatible formats.  
 Additionally contains some BEE2-specific helper functions that do the conversion, and cache calls so an image is only read once.

Intended features:

Back end:
* Start up
  - Check to see if VBSP / VRAD / particles_manifest / other files have been updated by Steam
	+ If updated, then rename to *_original (for VRAD/VBSP) and copy in modded versions, for others append extra entries from relevant locations.
  - Load config.cfg from root directory
  - Load *.Bee2Style files from configurable directory
  - Load *.Bee2Item files from configurable directory
	+ Load alternate versions if they exist (maybe have the same name + an "Alternate" keyvalue?)
  - Load *.Bee2Palette files from configurable directory
    + Extract Image
    + Determine groupings
    + Locate dependant style
  - Load *.Bee2Palette files from configurable directory
  - Locate all known supported games from Steam location (ie. Portal 2, Portal 2 Beta, Aperture Tag) for dropdown of which game desired for export.
* Export
  - Given a Palette (list of items with positions) and selected style, export the "editoritems.txt" to configured game
  - Save as last exported palette
  - Export all packaged files from [.Bee2Item]s to configured game directory
* Save/Load Palette
  - Save list of items and positions to file in configurable directory

Front End:
* Display list of all items 
  - Can be sorted by style, author, package, or supported games.
  - Shows palette preview of image
  - Either in right-click or other menu allow selecting alternate versions (style-dependant, will swap out with an alternate item block)
* Display exporting palette preview

VBSP Pre-Compiler:
* ~~(Using Stylechangers vbsp) -> On call~~
* ~~Call modular compiler operations~~
* See issue #6

VRAD Pre-Compiler:
* ~~Run Stylechanger's VRAD~~
  - ~~that runs PackBSP for us~~
* Use PackRat to pack files, this is cross-platform.
