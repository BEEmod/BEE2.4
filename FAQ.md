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

### Do people playing my BEEmod maps need BEEmod installed to see the custom content, or play the map at all?

No. This was the case with the High Energy Pellet items in the original BEEmod, but the BEE2 packs all custom content into the map automatically. (It's supposed to, at least. If something doesn't get packed, it's a bug; report it on the issue tracker if it hasn't already been.)

### What games does BEE2.4 support?

BEE2.4 supports Portal 2 and Aperture Tag. Thinking With Time Machine support is planned, but not yet implemented. (BEE2.4 can be used with TWTM, but you will not have the time machine and several other things will be broken.) Destroyed Aperture support is also planned once that mod is released.

### Will BEE2.4 be compatible with Portal 2: Community Edition, will that make any new things possible?

Theoretically, P2CE would expand what is possible with BEEmod; however, the P2CE developers were unable to obtain the Puzzlemaker source code from Valve, so it won't be included. They will likely implement their own puzzlemaker from scratch at some point in the future, but it is not currently being worked on and would likely be incompatible with BEE.

### I have a pirated/cracked version of Portal 2, can I use BEE2.4?

We do not support cracked versions of Portal 2. While BEE2.4 may still work, we will not help you if you run into any problems. We highly recommend that you buy the game legally on Steam; Portal 2 only costs $10 USD by default, and is usually on sale for an even lower price.

### When is the next update for BEE2.4?

There are no set release dates for BEE2 updates. Sometimes they will be released every few weeks, and sometimes there will be months between updates. Instructions to run development versions of BEE2.4 can be found in the readme, if you want to test new features before they have been released.

### How do I use Catwalks/Vactubes/Unstationary Scaffolds?

These items effectively act as nodes, which need to be connected to each other in order to do anything. The exact way in which this works is different for each item, see their wiki pages for more details: [Vactubes](https://github.com/BEEmod/BEE2-items/wiki/Vactubes), [Catwalks](https://github.com/BEEmod/BEE2-items/wiki/Catwalks), and [Unstationary Scaffolds](https://github.com/BEEmod/BEE2-items/wiki/Unstationary-Scaffold)

### In the Bomb Cube's description it says it can destroy breakable glass, but the Breakable Glass item isn't in the BEE2.4. Where is it?

Breakable Glass hasn't been reimplemented yet, but it is planned, which is why it's mentioned in the Bomb Cube description.

### When I change the angle of Portal 1 panels it makes a high-pitched/corrupted noise, how do I fix it?

This is a known issue which seems to be related to audio caching, as the audio files themselves sound correct. One fix that seems to work is running the commands `snd_updateaudiocache` and `sv_soundemitter_flush` in the console, in that order. There's no way currently to make the mod apply this automatically, which is why the issue hasn't properly been fixed.

### Old versions of BEE2 had a lot more items, what happened to them and are they coming back?

BEE2.4 is a complete rewrite of the app with a different internal item format, so all of the old items need to be manually ported. This is in progress, see issue [#95](https://github.com/BEEmod/BEE2-items/issues/95) for more details.

### Can you add new style *x*?

Styles take a lot of work to create and maintain, so new ones are rarely added. For a new style to even be considered, it should make sense overall, work with most/all of Portal 2's test elements, and be possible to reasonably implement in the Puzzlemaker.

As an example, Portal 1 is a style that fits this criteria, as most of Portal 2's test elements can reasonably exist there and it has a block-based structure similar to Clean. On the other hand, BTS style typically doesn't use test elements like buttons and cubes, and it's very difficult to make it look good in the Puzzlemaker, hence why it was removed; had this been considered back in 2015, the style never would have been added to begin with.

If your suggested style is a simple variant of an existing style (e.g. Original Clean, which just changes wall textures), it may be added. Custom packages can also add their own styles, so feel free to implement a new style yourself.

### Can you add style mixing / changing of items to different styles?

We can, but we won't. You need the flexibility of Hammer to properly explain style mixing, and lots of combinations wouldn't make sense anyway.

### Why doesn't Portal 1 GLaDOS have any lines?

The P1 GLaDOS lines aren't in Portal 2 by default, and as stated below, it's not possible to pack voice lines into maps. In the next release, existing lines which are similar to the P1 dialogue will be used.

### Can you add Adhesion Gel/<some other custom gel\> to BEE2.4?

No. Adhesion Gel never functioned properly in any released version of Portal 2. It was replaced with Reflection Gel in the Peer Review update, keeping all the functional Adhesion Gel effects (this is why it can counteract Propulsion Gel). Gels are hardcoded into the game, so it's not possible to properly implement Adhesion Gel, or any other custom gel type. It is possible to re-create Adhesion Gel using tricks with rotating the map, but this can't reasonably work in the Puzzlemaker.

More recently, mods such as Desolation and Portal 2: Community Edition have obtained the source code from Valve and reimplemented Adhesion Gel properly. However, it's not possible to include this modified code in workshop maps, and these mods can't themselves include the Puzzlemaker for technical reasons.

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

The purpose of the cube colorizer is to make it easier to tell which cubes came from which droppers, if one of them needs to be respawned as part of the puzzle. In this case it's fine if they can't be distinguished, since the player can just keep track of that themselves (as if the cubes were uncolored). Most good puzzles don't need more than 2 cubes, so just the default cube and sphere types usually work fine. Additional unique cube types (such as a triangle cube) have also been discussed.

### Can you add the ability to colorize light strips?

This is also possible; however, the refraction shader used by light strips isn't compatible with the property used to color other things (e.g. cubes). The app would need to generate individual textures for each selected color, then those would be applied in-game. For this reason, the feature isn't currently being worked on, but could possibly be added in the future.

### Can you add lights that are toggled by an input?

The Source engine has very strict limits on toggleable lights. Only two dynamic lights can affect a single surface, and only 32 possible combinations of light states can exist across the entire map. This makes toggleable lights infeasible for a mod such as BEE2, as the majority of users are not going to be aware of these restrictions. Additionally, darkness is not meant to be used as a test element. It doesn't actually affect the puzzle in any way and is just annoying. So while this is technically possible to an extent, it's not going to be implemented either way.

### I exported my BEE2.4 map to Hammer and it won't compile/music won't play/<some other issue\>.

`puzzlemaker_export` does not work with BEEmod, as the custom compiler isn't able to modify the map and make it actually functional. Before reading on however, keep in mind that exporting Puzzlemaker maps to Hammer is usually not the best idea. If you want to make extensive modifications to a map, or are just starting out learning Hammer, it's generally easier to build a map from scratch, as Puzzlemaker maps are generated in a complex way making them difficult to edit by hand. Only consider exporting if you just want to make small adjustments to a map, and already have experience using Hammer.

If this is still what you want to do, first go into the BEE2 app and set Spawn Point to Elevator and disable Restart When Reaching Exit. Compile your map in Puzzlemaker, then open `maps/styled/preview.vmf` in Hammer and resave it to a different location so it doesn't get overwritten. Additionally, check your Build Programs settings to make sure that you're using the BEE2 version of VRAD (simply called `vrad.exe`), as this is needed for some features such as music to work.

### How do I use bottomless pits/what happened to 3D Factory?

The bottomless pits originally featured in BEEmod had significant problems, so they've been removed for the time being. The plan is to implement a "chamber exterior" system which would allow generating areas surrounding the map, including improved bottomless pits. However, this feature is not yet being worked on.

### What happened to BTS style?

The BTS style was made in the early days of the BEE2, before we had really figured out our scope. We made the decision to remove BTS because it's fundamentally incompatible with the way normal test chambers (and by extension Puzzlemaker maps) are built. Test chambers are made up of modular, reusable test elements; BTS on the other hand has much more specialized machines, such as the turret production line from the campaign. In some ways, BTS maps are more similar to Half-Life's environmental puzzles than Portal's test chambers.

Building a BTS map following the structure of a test chamber results in something which doesn't feel like a BTS map, it just feels like a test chamber with a skin on top of it - which is really all BEEmod styles are. That works fine when the skin is also a test chamber (or an equivalent), but if it's not, then the fact that it's just a skin becomes extremely obvious.

### Will you add Desolation's Industrial style to BEE2.4?

No. The Industrial style is fairly complex and would be difficult to implement in the Puzzlemaker, requiring lots of compiler modifications. It also relies on many custom assets which would need to be packed into the map, increasing its file size substantially. Even if ways around both of these things were found, the style also makes use of custom features of Desolation's engine, which can't be replicated in standard Portal 2.

Implementing the style within Desolation itself would solve the latter two issues, but Desolation won't be able to use Valve's puzzlemaker for technical reasons, and the developers currently have no plans to write their own. It also wouldn't solve the first problem, which is actually generating Industrial maps.

Additionally, see the question above about new styles in general.
