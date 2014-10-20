# Better Extended Editor 2 version 4

A Portal 2  Mod tool

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
