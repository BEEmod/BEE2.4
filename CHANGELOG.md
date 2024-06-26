# Changelog

# Version 4.45.2
* #2050, #2053: Fix gameinfo.txt not being modified during exports.

------------------------------------------

# Version 4.45.1
* Fix the application looking in the wrong location for the compiler.

------------------------------------------

# Version 4.45.0

## New Features:
* Glass/grating is now generated entirely by the compiler, allowing fully 
  custom items to be made. The original glass/grating frame is now also 
  generated slightly more efficiently.
* Added the ability to define variants for corridors. In Clean style this 
  allows specifying elevator directions, stair direction and the corridor's 
  light temperature. 

### Enhancements:
* Added the ability to show multiple warning messages or errors for problems 
  occurring during package loading and export.
* Added signage configuration option to the item's context menu, to help make it more visible.
* Shut down the error server automatically when Portal 2 quits.
* Added additional EXEs for `compiler_settings.exe` and `backup.exe`. These 
  allow quickly opening just these windows.
* The logic for detecting paint splats placed on cubes is improved to 
  prioritise gel placed directly on droppers. In particular a cleansing gel
  splat can be placed on the dropper to allow the floor below to still be painted.

### UCP-Relevant changes:
* Added `sky_draw_first` option to skyboxes, which can fix some rendering bugs 
  with certain materials.
* The barrier rework adds several new blocks to `vbsp_config`:
  * `BarrierFrames` in `vbsp_config` contains definitions for the frame of barriers.
  * `Barriers` in `vbsp_config` contains the definitions for the brushes to 
    produce, and then which frame IDs to use.
  * `BarrierHole` in `info.txt` defines a hole type. This is defined outside the
    item, because the different style
    variants can be independently specified by each barrier type.
  * The `CustomBarrier` result produces an item that converts attached glass/grating.
* As mentioned above, `CorridorGroup` now has `Options` blocks for specifying 
  corridor options.
  These ultimately just set fixups on the instance. `DefaultIndex` has been 
  replaced with just `Disabled` - all corridors will now be enabled by default.
* Music can now have a volume specified in the config.
* Added the `AttachInputOverlay` result, which adds an overlay instance, 
  but connects it to the original as an additional input. This significantly
  simplifies logic if an additional prerequisite is required for the item to turn
  on.
* Fix catwalk end segment being placed at the top of upwards-facing stairs.
* #2048: Fix ceiling Faith Plates not functioning correctly.
* #2040: Warn if no compiler files were found when exporting.
* #1343: Clone fizzler items if connected to multiple standing/reclined fizzlers.

------------------------------------------

# Version 4.44.1

### Enhancements
* Remove some now-outdated splash screens.

### Bugfixes:
* Fix add-game prompt failing to appear if installed fresh.

------------------------------------------

# Version 4.44.0

### Enhancements:
* If a duplicate package is present, include the paths of both in the error message.
* Change palette item format to permit "holes" in the position of items. This
  isn't exposed in the UI yet.
* Redo the selector on the Item Properties pane to make it more clear that it swaps pages.
* Display the authors of corridors.
* Rearranged the UI on the corridor picker display.
* Add some informative errors if Unstationary Scaffolds (or similar UCP items) 
  are connected in an invalid manner.
* Added "Compress Items" option, which hides all but one of each on the item list.
* Skip disabled packages when extracting resources.
* Timer-style indicator panels at the end of antlines can now have a custom 
  appearance for some items (Delayers). This allows them to show both count-down 
  and count-up displays.
* Moved various palette-related buttons, to group them with the other palette options.
* VPK files can be now placed into `vpk_override` to have them be combined with the built VPK. 
* Added a warning screen to the developer tab of the options window, indicating 
  that some of these options can temporarily break BEE if changed.
* #1984: The "save settings to palette" will now change to match the selected 
  palette. This means clicking "save" won't accidentally delete saved settings.
* #1893: Add compile logs to error display windows.
* Internal files are now placed in a `bin/` subfolder, instead of cluttering
  the folders containing `BEE2.exe`, `vbsp.exe` and `vrad.exe`.

### UCP-Relevant Changes:
* Terminology change: "Condition Flags" have been renamed to "Condition Tests" - I think that sounds a bit better.
* Added an `Inherit` option to Corridor Groups. This specifies the ID of another style, causing all
  corridors to be copied from that other style.
* Make several results properly permit options to use `$fixup` variables: `addOverlay`, `changeInstance`, `setKey`, `localTarget`.
* `properties.txt` for items is now optional, since most of these options can be set elsewhere.
* `PosIsSolid` and `ReadSurfType` now have a `debug` option. When "Developer Mode" is enabled,
  `info_target`s are generated to mark the locations being sampled, and the contents of this field
  is copied into those as a comment to help identify them.
* Behaviour change: in Fizzlers, `model_mid` will now be affected by the `NameType` value.
* Added the `Error` result, which allows producing a custom error message from a package.
* #1313: Allow disabling the triggers produced by `CustVactube`.
* When Dev Mode is on, `SetTile` now dumps the tiles it's trying to set into the final map.
* `ConfigGroup` slider widgets can now be set to display "Off" when set to zero, also fixed them not snapping to values.

### Bugfixes:
* BEE will detect `portal2_dlc3` being in use and pick another DLC folder for its VPKs.
* Properly pick free port for error server.
* Set a title for the corridor selector window.
* Always pack generated resources even if packing is disabled in options.
* Parse game translation files in an even more lenient way, to handle some Portal 2 files correctly.
* Fix potential z-fighting near the hinge of static angled panels.
* Add a scrollbar if required to the corridor selection window.
* Fix single-dot antlines sometimes failing to be placed.
* BEEmod/BEE2-items#4325: Set corridors to force upright even if vertical corridors are not available.
* Piston Platforms will now correctly accept Surface Lacquer, if placed on their base.
* Paint Splats will correctly rotate to aint Angled Panels they are placed on top of.
* Removed the "Prevent Portal Bump (fizzler)" stylevar. It is useless and never worked.
* #1955: Fix some situations causing incorrect catwalk placement.

------------------------------------------

# Version 4.43.0

## New features:

* New error display system: If a known error occurs during compilation (leaks, items 
  used incorrectly, etc), the Steam Overlay will be opened, and a webpage opened with
  information on the error, as well as a interactive view of the chamber to show the
  location of the issue and relevant items.
* Languages can now be selected in the options menu, and packages now have more usable
  translation support.

### Enhancements
* If funnel music is disabled, keep the base music playing while inside funnels.
* Tweak the naming for the chamber thumbnail options to be a little more clear.
* Add option to disable modifying the FGD file.

### Bugfixes
* Do not composite signage VTFs with PeTI backgrounds.
* Fix signage not exporting if the UI was not opened at least once before exporting.
* [#4252](https://github.com/BEEmod/BEE2-items/issues/4252): Correctly place Tag Fizzler signage 
  when on walls.
* Display the absolute location of the package location if empty.
* Handle unparsable existing antigel materials gracefully.
* Fix issues with P1 Track Platforms not generating correctly.
* Fix export of corridor configuration in some cases when picking default corridors.
* Warn and handle duplicate definitions in both the style and item packages. 
  This fixes an issue where older style definitions would cause errors if checkmark/timer panels
  were present in the map.

------------------------------------------

# Version 4.42.0

### New features:
* New corridor selection system
	* Each corridor can now be individually enabled/disabled, you can have any number active.
	* UCPs can easily add new corridors to the mix
	* Corridor designs can be added for the floor/ceiling. Some have been added to Clean, but not other styles yet.

### Enhancements
* The Item Properties pane has been rearranged a bit, so it better handles heaps of widgets, and 
  makes the old style properties window less prominent.
* Conditions will now exit early if the flags cannot be satisfied (for instance if the instance is 
  not present at all). This reduces the amount of conditions which run.
* Add some menu options to allow opening folders - the game directory, puzzles folder, palettes, 
  packages, etc.
* #3238: Multiple catwalk items which intersect will now produce junctions as appropriate.
* #1799: Add a special warning if BEE is installed directly into the Portal 2 folder.
* #1366: Add option to disable auto-packing.
* #452: Allow displaying which items inherit and are unstyled.
* #1443: Allow hiding builtin palettes.
* #1774: If the current palette is unchanged, don't switch to `<Last Export>`.
* VRAD can be configured to not compile lighting at all, for faster (but awful looking) 
  testing (via @SP2G50000).
* Rebuilt config logic to provide a better config file system, improve internal code layout.
* BEEmod/BEE2-items#558: Concave frame corners will now be generated for glass/grating items, fixing
  holes in the framework. 

### UCP-Relevant Enhancements
* A new collision system has been added, but it is currently not being used for anything.
	* Items can define collisions for BEE2 specifically, using new psuedo-entities.
	* Editoritem collisions and connectionpoints can also be specified with the new system.
* New [`CorridorGroup`](https://github.com/BEEmod/BEE2-items/wiki/Corridors) object type, for 
  corridors.
* Added `entryCorridor` and `exitCorridor` flags, for checking which corridors were chosen.
* Added `AppendConnInputs` result, for adding additional outputs to an item.
* With 'developer mode' enabled, the `PosIsSolid` condition will annotate the map to show 
  measurement points.
* With 'developer mode' enabled, items will list their full I/O configuration in the tooltips.
* A "debug" option is now available on `bee2_template_conf`, which will cause the map to contain 
  additional info about how it was placed.
* `ATLAS_SpawnPoint` and `addGlobal` now can use fixup values.
* A new "dropdown" `ConfigGroup` widget type is now available, which allows picking from a list of 
  options.
* Icons may now be transparent - they will automatically be blended with the PeTI palette icon 
  background.
* `ConfigGroup` widgets may now have a blank label, causing it to be hidden. This is useful if 
  there's only one widget in the group.

### Bugfixes
* Fixed help menu Discord invite being temporary, added system to allow updating these retroactively
  in future.
* #1776: Fix funnel light code didn't use the right fixup values.
* Fix P1 style not compiling, by ensuring `hammer_notes` is present in the FGD.
* Fix BEEmod/BEE2-items#3998: Signage appearing sideways on walls, instead of locking upright.
* #1826: Make package-defined stylevars actually save/load settings.
* #1784: Fix stylevars always showing as being available for all styles.
* #1453: When config is new, default to that of the clean style.
* #1782: Fix crash when trying to enable/disable packages.
* #1785: Don't force context window to be topmost.
* #1854: Properly add a delay in inverted logic items.
* Fix music not allowing hours in the `loop_len` option.
* Correct the order of Connection Signage.
* Fix BEEmod/BEE2-items#4044: Antlaser outputs not functioning.
* Fix locking buttons removing their target's timer signs, instead of their own.
* Fix Sendificators behaving incorrectly when multiple are connected to the same laser.
* Fix Conveyors potentially leaking in "oscillating" mode.

------------------------------------------

# Version 4.41.0

### New features:
* The BTS style has been removed, due to it being rather substandard and not really possible to 
  function in the puzzlemaker.
* New Item: Antline Corner item, which allows for manually placing antlines anywhere. Place two 
  down with a straight line between them, then link with antlines. A contiguous section is treated 
  as one item, which acts like an OR gate.
* New Item: Half Obs Room, a half-voxel wide Observation Room. The P1 room has switched to be a 
  full voxel like other styles.
* P1 style light strips now are a rectangular lamp like other styles, with the square hole split 
  into a new item.
* Add brand new versions of Old Aperture SP spheres, and 50s+60s entry corridors all by @Critfish.
* Old Aperture and P1 Gel Droppers now have new custom models.
* P1 and Old Aperture exit signs will now reposition themselves like other styles.
* Vactubes now have P1 and Old Aperture styles.
* Remake some P1 entry corridors.
* Add new option for making fizzlers force black tiles on adjacient tiles to discourage portal 
  bumping.
* Implement ability to hold shift to force load in elevator or compile with full lighting.
* Multiple suggestions can now be set.
* Redo randomisation logic, so now it properly reproduces the same result when recompiled.
* Remake the entire palette window, allowing palettes to be put into groups and have duplicate names.
* Selector windows now save/load their position and group expand/contract state.
* The BEE postcompiler is no longer run at all on Hammer maps, install Hammer Addons for this.
* The pipes in Enrichment Spheres now can appear in several random positions.

### Bugfixes:
* Fix app music/sound FX not playing on Windows 7/8.1 systems (#1520).
* #1624: Fix crash on startup: "FileNotFoundError: [Errno 2] No such file or directory".
* #1660: Fix occasional crash when exporting: "NotImplementedError: Saving DXT1 not implemented!".
* Fix crash when keyboard navigating in a closed selectorwin group.
* #1375: Fix issue where the item name in selector windows would be vertical.
* Downgrade some editoritems checks to warnings, to allow packages to load.
* Make Flip Panels flip in the same direction as the editor model suggests.
* Fix misleading placement of the 'turret shoot monitor' voiceline attribute.
* #1564: Fix ATLAS keeps respawning from the default spawn room instead of the Coop Checkopint.
* #2518: Fix players can get stuck inside the "Coop Droppers".
* #3835: Fix Auto-Portals don't work in Portal 1 style.
* #3894: Fix Portal Magnets don't work.
* #3797: Fix Half Grate can cause map leaks.
* #3925: Fix Futbol respawn sound has infinite range.
* #3572: Fix placing Light Bridges on certain spots can cause map leaks in Old Aperture.
* #3457: Fix Faith Plates having a bad lighting origin.
* #3966: Fix Clean and Overgrown Observation Room can be portalled.
* Fix placement helpers on angled panels not preserving their rotation.
* Fix some crashes involving destroyed images.
* Fix various issues with vactubes.
* Fix A LOT of more bugs!

### UCP-Relevant Enhancements
* Add addShuffleGroup result, for picking from a pool of instances to randomise decoration.
* Replace Unstationary Scaffold-specific condition with a more general version (LinkedItem).
* Fix Switch ``<default>`` not working.
* Multiple locations may now be specified in the config for package locations - add package1, 
  package2 etc. This allows your user stuff to be elsewhere from the default packages.
* All configuration files except for info.txt and editoritems.txt are now lazily loaded, meaning 
  that you can modify them and re-export to apply the changes without needing to restart BEE2. This 
  also should speed up startup.
* Selector windows may now have the small thumbnail definition omitted, to make it automatically 
  crop down the larger icon.

------------------------------------------
