Better Extended Editor 2.4
====

A Portal 2  Mod tool

Intended features:

Back end:
* Start up
  - Load config.cfg from root directory
  - Load *.Bee2Style files from configurable directory
  - Load *.Bee2Item files from configurable directory
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
* Display exporting palette preview

VBSP Pre-Compiler:
* (Using Stylechangers vbsp) -> On call
* Call modular compiler operations
