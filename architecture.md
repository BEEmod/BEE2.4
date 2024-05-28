BEEmod is frozen into two major components - the configuration application, and then the compilers. Excluding a few shared modules, code is either intended for the application or compiler and avoids importing stuff from the other components.

## Entry Points: 
Execution starts in the `BEE2_launch.py` and `compiler_launch.py` scripts. These do some setup, then import and run the rest of the code under the Trio event loop. For the compiler, whether to run the pre- (vbsp) or post- (vrad) compiler is determined by the executable name.

For the application, it spawns a subprocess running the `bg_daemon` module, which displays the log window and loading screens. This way these continue to operate even if the main application is busy for whatever reason.

If an error occurs, the postcompiler launches `error_server`, which hosts a web server displaying information about the error for viewing in the Steam Overlay.

## Core Packages:
* `app`: Contains code for the application, which will eventually no longer directly depend on `tkinter`.
	* For most of these modules, an abstract class is defined and then inherited from in `ui_tk`. For those the convention is `ui_XXX` funcs are to be overridden in the Tkinter-specific code.
* `config`: The configuration system for the application, allowing saving/loading versioned classes in a consistent way. 
* `packages`: The code for finding and reading all items in packages. 
* `exporting`: All the logic for exporting configuration to a game. This uses the `step_order` module to define "steps" which are re-ordered depending on their prerequisites.
* `precomp`: Code specific to the VBSP precompiler.
* `postcomp`: Code for the VRAD postcompiler, mostly in the form of HammerAddons "transforms".
* `ui_tk`: Code that extends/implements/builds upon `app` to use Tkinter-specific widgets. 


# Usual dataflow
For any given feature, the implementation is usually spread out in different modules, which flow together as follows:
* `someFeature`: A top-level module defines the data structures (enumerations, attrs classes) that are used in both the app and compiler.
* `packages.someFeature`: A module is present here to define the package object to configure the feature with.
* `config.someFeature`: A class is defined here to represent it in config files, for restoring the previous state when launched, saving in palettes and potentially sending to the compiler.
* `app.someFeature`: The code for configuring this item in the app, arranged to be GUI library-agnostic.
* `ui_tk.someFeature`: Subclasses the `app` code to implement Tk-specific logic.
* `exporting.someFeature`: Implements a "step" to control how the feature is written out to the game configuration.
* `precomp.someFeature`: For complex features, the code which parses items out of the map into more useful data structures, then generates the final logic after other items have manipulated it.
* `precomp.conditions.someFeature`: Defines tests and results to allow packages to manipulate the state in `precomp.someFeature`. For simpler things it might be entirely implemented in the conditions.
* `postcomp.someFeature`: Some things might require postcompiler intervention, in which case they're present here.


## Core Shared Modules:
* `connections`: Data structures and parsing for the I/O connections configuration for items. 
* `editoritems`: Classes for parsing the editoritems configuration format.
* `consts`: Enums and other constants used throughout the codebase.
* `transtoken`: Translation token classes for defining translatable strings. This is separate from `app.localisation` to allow data structures containing translatable text to be used in the compiler as well.
* `utils`: Common utility code shared by everything. 

## Core Precompiler Modules:
* `user_errors`: The `UserError` class defined here triggers the error display system to display an error if raised. 
* `precomp.collisions`: Maintains a set of volumes for each item representing the space they occupy. Similar to `occupiedVoxels`, but expanded and improved for our custom items. Currently the results aren't used, since most items don't fill this in.
* `precomp.conditions`: Defines the Conditions system, through which most customisation of things in the level is performed.
* `precomp.connections`: All the I/O connections between items are parsed here, allowing manipulating links before this produces the final optimised I/O outputs.
* `precomp.instanceLocs`: This stores a database of item IDs and their associated instances, allowing lookup of the instances an item uses.
* `precomp.tiling`: The TileDef classes here store the layout of white/black tiles in the map, so they can be manipulated with a 32-unit grid precision. This is parsed from the original editor brushwork, then at the end new brushes are constructed.
* `precomp.template_brush`: The templating system allows copying a set of brushes and certain entities into the map, adjusting dynamically to fit the location. 
* `precomp.texturing`: Has configuration for the various textures, and allows fetching random ones as required.
* `precomp.rand`: Seeds RNG instances from the layout of the map, allowing reproducibility.

## Core Application Modules:
* `app.img`: This defines the imaging subsystem, which defines lightweight handles that can be parsed from configs. Once these are applied to widgets, the actual image will be loaded and unloaded in the background.
* `app.UI`: Defines the main window and initialisation code pulling together all other windows. Originally all the UI code was here, so it's not organised well.
* `ui_tk.tk_tools`: Combinations of widgets and other utilities for UI code.
* `gameMan`: Contains the classes for describing the games which BEE knows about.

