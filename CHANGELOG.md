# Changelog

# Version <dev>
* New corridor selection system
	* Each corridor can now be individually enabled/disabled, you can have any number active.
	* UCPs can easily add new corridors to the mix
	* Corridor designs can be added for the floor/ceiling.
	* Added `entryCorridor` and `exitCorridor` flags, for checking 
* Rebuilt config logic to provide a better config file system, improve internal code layout.
* Conditions will now exit early if the flags cannot be satisfied (for instance if the instance is not present at all). This reduces the amount of conditions which run.
* Added `AppendConnInputs` result, for adding additional outputs to an item.
* Add some menu options to allow opening folders - the game directory, puzzles folder, palettes, packages, etc.
* Fix #1776: Funnel light code didn't use the right fixup values.
* Fix P1 style not compiling, by ensuring `hammer_notes` is present in the FGD.
* Fix BEEmod/BEE2-items#3998: Signage appearing sideways on walls, instead of locking upright.
* Fix #1826: Make package-defined stylevars actually save/load settings.
* Fix #1784: Stylevars always show as being available for all styles.
* Fix #3238: Multiple catwalk items which intersect will now produce junctions as appropriate.
* Implement #1366: Add option to disable auto-packing.
* Fix #1799: Add a special warning if BEE is installed directly into the game folder.
* Fix #1453: Code in the clean style defaults when config is new.
* Fix #1782: Crash when trying to enable/disable packages.
* Fix #1785: Don't force context window to be topmost
* Fix #1854: Properly add a delay in inverted logic items.
* Add error if BEE2 is installed directly into the Portal 2 folder.
* Implement #452: Allow displaying which items inherit and are unstyled.
* Implement #1443: Allow hiding builtin palettes.
* Implement #1774: If the current palette is unchanged, don't switch to `<Last Export>`.
* Fix music not allowing hours in the `loop_len` option.
* Correct the order of Connection Signage.
* VRAD can be configured to not compile lighting at all, for faster (but awful looking) testing (via @SP2G50000).
* The Item Properties pane has been rearranged a bit, so it better handles heaps of widgets, and makes the old style properties window less prominent.
* A new collision system has been added, but it is currently not being used for anything.
	* Items can define collisions for BEE2 specifically, using new psuedo-entities.
	* Editoritem collisions and connectionpoints can also be specified with the new system.
* Fix BEEmod/BEE2-items#4044: Antlaser outputs not functioning.
* Fix locking buttons removing their target's timer signs, instead of their own.
* Fix Sendificators behaving incorrectly when multiple are connected to the same laser.
* With 'developer mode' enabled, the `PosIsSolid` condition will annotate the map to show measurement points.
* With 'developer mode' enabled, items will list their full I/O configuration in the tooltips.
* A "debug" option is now available on `bee2_template_conf`, which will cause the map to contain additional info about how it was placed.
* `ATLAS_SpawnPoint` and `addGlobal` now can use fixup values.
* A new "dropdown" `ConfigGroup` widget type is now available, which allows picking from a list of options.
* `ConfigGroup` widgets may now have a blank label, causing it to be hidden. This is useful if there's only one widget in the group.
# Version 4.41.0
