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
* Export
  - Given a Palette (list of items with positions) and selected style, export the "editoritems.txt"
  - Save as last exported palette
* Save/Load Palette
  - Save list of items and positions to file in configurable directory

Front End:
* Display list of all items 
  - Can be sorted by style, author, or package
  - Shows palette preview of image
* Display exporting palette preview

VBSP Pre-Compiler:
* (Using Stylechangers vbsp) -> On call
* Move VMF to temp location
* Call modular compiler operations
* Move VMF back
