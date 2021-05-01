# FAQ

This is a list of answers to questions that have been frequently asked by users. If you are having problems with BEE2.4 or want to ask about a feature, check here.

If you can't find the answer to your question, ask on [Discord](https://discord.gg/hnGFJrz). Do not open an issue to ask a question.

---

### Where is the executable?

The executable is located in the root of the extracted folder. If it's not there, you probably downloaded the wrong file. Make sure you download the mod from the [releases page](https://github.com/BEEmod/BEE2.4/releases), and not using the "Clone or download" button on the main page, as this will download the mod's source code rather than a compiled release.

### My anti-virus program flagged BEE2.4 as malware?

This is a known issue, and happens for a number of reasons that are mostly out of our control. Antivirus software will often assume that if a file isn't commonly downloaded, it must be malware. *Real* viruses are also sometimes written in Python, meaning they would share many of the same libraries and files. Additionally, BEE2.4 does several things which could cause it to be seen as a virus - copying a bunch of files into the folder for another program (Portal 2), and replacing executables with its own versions (the compilers). However, we can assure you that BEE2.4 does not contain any malicious code. If you don't believe us, [check for yourself](https://github.com/BEEmod/BEE2.4/tree/master/src); the entire project is open-source.

### How do I uninstall BEE2.4 from a game?

The most common answer to this question would be "verify the game files". However, this is **not** the correct way of uninstalling - although the editor items and style will be restored to default, editor textures will not be reverted and many custom assets added by BEE2.4 will be left in the game files. To fully uninstall BEE2.4, select the game you want to uninstall it from and choose *File > Uninstall from Selected Game*. This will completely remove BEE2.4 from the game, including editor textures and custom assets.

To uninstall the BEE2 app itself, perform the above steps, then simply delete the application folder.

### BEE2 immediately crashes on startup with an error about `basemodui.txt`. How do I fix it?

Valve broke the syntax of this file in a Portal 2 update, causing BEEmod to be unable to properly read the file and crash. On Windows, this has been fixed in [v4.36.0](https://github.com/BEEmod/BEE2.4/releases/tag/2.4.36.1_) and later, so just updating will solve the problem. If you are using BEE2 on Mac, or need to keep using an old version of the mod for some reason, you'll want to open up `Portal 2/portal2_dlc2/resource/basemodui_english.txt` (regardless of your language) and add an extra `}` on a new line at the end of the file.

### Do people playing my BEEmod maps need BEEmod installed to see the custom content, or play the map at all?

No. This was the case with the High Energy Pellet items in the original BEEmod, but the BEE2 packs all custom content into the map automatically. (It's supposed to, at least. If something doesn't get packed, it's a bug; report it on the issue tracker if it hasn't already been.)

### What games does BEE2.4 support?

BEE2.4 supports Portal 2 and Aperture Tag. Thinking With Time Machine support is planned, but not yet implemented. (BEE2.4 can be used with TWTM, but you will not have the time machine and several other things will be broken.) Destroyed Aperture support will also be added sometime after its release.

### What about Portal 2: Community Edition? Will BEE2.4 be compatible with that, will it make any new things possible?

Theoretically, P2CE would expand what is possible with BEEmod; however, the P2CE developers were unable to obtain the Puzzlemaker source code from Valve, so it won't be included. They will likely implement their own puzzlemaker from scratch at some point in the future, but it is not currently being worked on and would likely be incompatible with BEE.

### I have a pirated/cracked version of Portal 2, can I use BEE2.4?

We do not support cracked versions of Portal 2. While BEE2.4 may still work, we will not help you if you run into any problems. We highly recommend that you buy the game legally on Steam; Portal 2 only costs $10 USD by default, and is usually on sale for an even lower price.

### When is the next update for BEE2.4?

There are no set release dates for BEE2 updates. Sometimes they will be released every few weeks, and sometimes there will be months between updates. Instructions to run development versions of BEE2.4 can be found in the readme, if you want to test new features before they have been released.

### How do I use Catwalks/Vactubes/Unstationary Scaffolds?

These items effectively act as "nodes", and need to be linked together to do anything. See the items' wiki pages for more details: [Vactubes](https://github.com/BEEmod/BEE2-items/wiki/Vactubes), [Catwalks](https://github.com/BEEmod/BEE2-items/wiki/Catwalks), and [Unstationary Scaffold](https://github.com/BEEmod/BEE2-items/wiki/Unstationary-Scaffold)

### In the Bomb Cube's description it says it can destroy breakable glass, but the Breakable Glass item isn't in the BEE2.4. Where is it?

Breakable Glass hasn't been reimplemented yet, it is planned though which is why it's mentioned in the Bomb Cube description.

### When I change the angle of Portal 1 panels it makes a high-pitched/corrupted noise, how do I fix it?

This is a known issue which seems to be related to audio caching, as the audio files themselves sound correct. One fix that seems to work is running the commands `snd_updateaudiocache` and `sv_soundemitter_flush` in the console, in that order. There's no way currently to make the mod apply this automatically, which is why the issue hasn't properly been fixed.

### Can you add BEE2.2/tspenAddons items to BEE2.4?

This is in progress. See issue [#95](https://github.com/BEEmod/BEE2-items/issues/95).

### When will the new style *x* be released?

Styles take a lot of work to create and maintain. A list of planned styles can be found on the [Upcoming Features](https://github.com/BEEmod/BEE2-items/wiki/Upcoming-features) page, though these have no set release dates.

### What happened to the signage list that appeared when right-clicking it, how do I know what timer value corresponds to what sign?

It's now possible to customize the available signages. In the Style/Item Properties window, go to the Items tab and choose Customize Signage. This shows a list of every signage with its timer value, and allows you to customize them.

### Why doesn't Portal 1 GLaDOS have any lines?

The P1 GLaDOS lines aren't in Portal 2 by default, and as stated below, it's not possible to pack voice lines into maps. The plan is to use existing lines that are similar to the P1 dialogue, but this hasn't been implemented yet.

### Can you add Adhesion Gel/<some other custom gel\> to BEE2.4?

No. Adhesion Gel never functioned properly in any released version of Portal 2. It was replaced with Reflection Gel in the Peer Review update, keeping all the functional Adhesion Gel effects (this is why it is "slightly sticky"). Gels are hard-coded into the game, so it's not possible to properly implement Adhesion Gel, or any other custom gel type. It is possible to [re-create Adhesion Gel](https://steamcommunity.com/sharedfiles/filedetails/?id=860192232) using various entities and scripts, but this involves tricks with rotating the map and can't be implemented in the Puzzlemaker.

### Can you change the color of Reflection Gel to be different than Conversion Gel?

Once again, no. Reflection Gel is hardcoded to use the color of Conversion Gel (`portal_paint_color`) when on a surface, and the color of Propulsion Gel (`speed_paint_color`) on light bridges and when splashed on the screen. We can separately change the color of the blobs though, which has been done, making them a dark gray.

### Can you expand the palette/add <feature\> to puzzlemaker?

No. Most of the Puzzlemaker is hard-coded and outside our reach. While we can add new test elements and modify the compiler or in-game appearances, we cannot change how the editor itself behaves. This includes expanding the palette, adding custom labels to item settings (hence "Button Type", "Start Reversed", etc. on many items), creating new UIs, increasing connection limits, or merging non-compatible items.

### Can you add custom voicelines / voicelines from mod *x* to BEE2.4?

It's not possible to properly pack voice lines into maps; while we can pack the actual sounds easily, we can't pack the choreo files that are used for localization, subtitles, and chaining lines. Additionally, the developers of most mods (including Portal Stories: Mel) have said that they do not want people using their custom voice lines in maps.

### Can you add the ability to colorize buttons, so that they can only be activated by a matching cube?

This is possible, but it isn't going to be implemented because:

- It would be somewhat complicated to get working properly and doesn't have much use.
- Cube colors can be customized, so the mapper could choose two colors that were so close together that they were indistinguishable but didn't work together.
- Some players may have colorblindness, again making the cubes hard to distinguish.

The purpose of the cube colorizer is to make it easier to tell which cubes came from which droppers, if one of them needs to be respawned as part of the puzzle. In this case it's fine if they can't be distinguished, since the player can just keep track of that themselves (as if the cubes were uncolored).

### Can you add the ability to colorize light strips?

This is also possible; however, the refraction shader used by light strips isn't compatible with the property used to color other things (e.g. cubes). The app would need to generate individual textures for each selected color, then those would be applied in-game. For this reason, the feature isn't currently being worked on, but could possibly be added in the future.

### Can you add lights that are toggled by an input?

The Source engine has very strict limits on toggleable lights. Only two dynamic lights can affect a single surface, and only 32 possible combinations of light states can exist across the entire map. This makes toggleable lights infeasible for a mod such as BEE2, as the majority of users are not going to be aware of these restrictions. Additionally, darkness is not meant to be used as a test element. It doesn't actually affect the puzzle in any way and is just annoying. So while this is technically possible to an extent, it's not going to be implemented either way.

### I exported my BEE2.4 map to Hammer and it won't compile/music won't play/<some other issue\>.

`puzzlemaker_export` does not work with BEE2.4, as the custom compiler is not able to modify the map and make it actually able to compile. To use BEE2 maps in Hammer, set Spawn Point to Elevator and disable Restart When Reaching Exit. Compile your map in Puzzlemaker, then open `maps/styled/preview.vmf` in Hammer and resave it under a different filename so it doesn't get overwritten. This method still has issues, however, and it's generally better to recreate the map from scratch in Hammer even if you're not using BEE2.

If you just want to make a few small edits, another option is to put those things into instances, then import them into BEE as custom items. This allows you to place them directly into your Puzzlemaker map, instead of having to modify it. The process of creating custom items won't be fully described here, but you can read up on the [package format](https://github.com/BEEmod/BEE2-items/wiki/Package-Format) and the [custom item tutorial](https://github.com/BEEmod/BEE2-items/wiki/itemstutorial) to get started. If you need help with anything, feel free to ask for help in #ucp-development on the Discord server.
