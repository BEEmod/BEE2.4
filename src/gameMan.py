"""
Does stuff related to the actual games.
- Adding and removing games
- Handles locating parts of a given game,
- Modifying GameInfo to support our special content folder.
- Generating and saving editoritems/vbsp_config
"""
from tkinter import *  # ui library
from tkinter import filedialog  # open/save as dialog creator
from tkinter import messagebox  # simple, standard modal dialogs
from tk_tools import TK_ROOT

import os
import os.path
import shutil
import math

from BEE2_config import ConfigFile, GEN_OPTS
from query_dialogs import ask_string
from srctools import (
    Vec, VPK,
    Property, NoKeyError,
    VMF, Output,
    FileSystemChain,
)
import backup
import loadScreen
import packageLoader
import utils
import srctools

from typing import List, Tuple

LOGGER = utils.getLogger(__name__)

all_games = []  # type: List[Game]
selected_game = None  # type: Game
selectedGame_radio = IntVar(value=0)
game_menu = None  # type: Menu

# Translated text from basemodui.txt.
TRANS_DATA = {}

CONFIG = ConfigFile('games.cfg')

FILES_TO_BACKUP = [
    ('Editoritems', 'portal2_dlc2/scripts/editoritems', '.txt'),
    ('VBSP',        'bin/vbsp',                         '.exe'),
    ('VRAD',        'bin/vrad',                         '.exe'),
    ('VBSP',        'bin/vbsp_osx',   ''),
    ('VRAD',        'bin/vrad_osx',   ''),
    ('VBSP',        'bin/vbsp_linux', ''),
    ('VRAD',        'bin/vrad_linux', ''),
]

_UNLOCK_ITEMS = [
    'ITEM_EXIT_DOOR',
    'ITEM_COOP_EXIT_DOOR',
    'ITEM_ENTRY_DOOR',
    'ITEM_COOP_ENTRY_DOOR',
    'ITEM_OBSERVATION_ROOM'
    ]

# The location of all the instances in the game directory
INST_PATH = 'sdk_content/maps/instances/BEE2'

# The line we inject to add our BEE2 folder into the game search path.
# We always add ours such that it's the highest priority, other
# than '|gameinfo_path|.'
GAMEINFO_LINE = 'Game\t"BEE2"'

# We inject this line to recognise where our sounds start, so we can modify
# them.
EDITOR_SOUND_LINE = '// BEE2 SOUNDS BELOW'

# The name given to standard connections - regular input/outputs in editoritems.
CONN_NORM = 'CONNECTION_STANDARD'
CONN_FUNNEL = 'CONNECTION_TBEAM_POLARITY'

# The progress bars used when exporting data into a game
export_screen = loadScreen.LoadScreen(
    ('BACK', 'Backup Original Files'),
    (backup.AUTO_BACKUP_STAGE, 'Backup Puzzles'),
    ('EXP', 'Export Configuration'),
    ('COMP', 'Copy Compiler'),
    ('RES', 'Copy Resources'),
    ('MUS', 'Copy Music'),
    title_text='Exporting',
)

EXE_SUFFIX = (
    '.exe' if utils.WIN else
    '_osx' if utils.MAC else
    '_linux' if utils.LINUX else
    ''
)

# The systems we need to copy to ingame resources
res_system = FileSystemChain()

# We search for Tag and Mel's music files, and copy them to games on export.
# That way they can use the files.
MUSIC_MEL_VPK = None  # type: VPK
MUSIC_TAG_LOC = None  # type: str
TAG_COOP_INST_VMF = None  # type: VMF

# The folder with the file...
MUSIC_MEL_DIR = 'Portal Stories Mel/portal_stories/pak01_dir.vpk'
MUSIC_TAG_DIR = 'aperture tag/aperturetag/sound/music'

# Location of coop instance for Tag gun
TAG_GUN_COOP_INST = ('aperture tag/sdk_content/maps/'
                     'instances/alatag/lp_paintgun_instance_coop.vmf')

# All the PS:Mel track names - all the resources are in the VPK,
# this allows us to skip looking through all the other files..
MEL_MUSIC_NAMES = """\
portal2_background01.wav
sp_a1_garden.wav
sp_a1_lift.wav
sp_a1_mel_intro.wav
sp_a1_tramride.wav
sp_a2_dont_meet_virgil.wav
sp_a2_firestorm_exploration.wav
sp_a2_firestorm_explosion.wav
sp_a2_firestorm_openvault.wav
sp_a2_garden_destroyed_01.wav
sp_a2_garden_destroyed_02.wav
sp_a2_garden_destroyed_portalgun.wav
sp_a2_garden_destroyed_vault.wav
sp_a2_once_upon.wav
sp_a2_past_power_01.wav
sp_a2_past_power_02.wav
sp_a2_underbounce.wav
sp_a3_concepts.wav
sp_a3_concepts_funnel.wav
sp_a3_faith_plate.wav
sp_a3_faith_plate_funnel.wav
sp_a3_junkyard.wav
sp_a3_junkyard_offices.wav
sp_a3_paint_fling.wav
sp_a3_paint_fling_funnel.wav
sp_a3_transition.wav
sp_a3_transition_funnel.wav
sp_a4_destroyed.wav
sp_a4_destroyed_funnel.wav
sp_a4_factory.wav
sp_a4_factory_radio.wav
sp_a4_overgrown.wav
sp_a4_overgrown_funnel.wav
sp_a4_tb_over_goo.wav
sp_a4_tb_over_goo_funnel.wav
sp_a4_two_of_a_kind.wav
sp_a4_two_of_a_kind_funnel.wav
sp_a5_finale01_01.wav
sp_a5_finale01_02.wav
sp_a5_finale01_03.wav
sp_a5_finale01_funnel.wav
sp_a5_finale02_aegis_revealed.wav
sp_a5_finale02_lastserver.wav
sp_a5_finale02_room01.wav
sp_a5_finale02_room02.wav
sp_a5_finale02_room02_serious.wav
sp_a5_finale02_stage_00.wav
sp_a5_finale02_stage_01.wav
sp_a5_finale02_stage_02.wav
sp_a5_finale02_stage_end.wav\
""".split()
# Not used...
# sp_a1_garden_jukebox01.wav
# sp_a1_jazz.wav
# sp_a1_jazz_enterstation.wav
# sp_a1_jazz_tramride.wav
# still_alive_gutair_cover.wav
# want_you_gone_guitar_cover.wav


def load_filesystems(package_sys):
    """Load package filesystems into a chain."""
    for system in package_sys:
        res_system.add_sys(system, prefix='resources/')


def translate(string):
    """Translate the string using Portal 2's language files.

    This is needed for Valve items, since they translate automatically.
    """
    return TRANS_DATA.get(string, string)


def setgame_callback(selected_game):
    """Callback function run when games are selected."""
    pass


def quit_application():
    """Command run to quit the application.

    This is overwritten by UI later.
    """
    import sys
    sys.exit()


class Game:
    def __init__(self, name, steam_id: str, folder, mod_times):
        self.name = name
        self.steamID = steam_id
        self.root = folder
        # The last modified date of packages, so we know whether to copy it over.
        self.mod_times = mod_times

    @classmethod
    def parse(cls, gm_id, config: ConfigFile):
        steam_id = config.get_val(gm_id, 'SteamID', '<none>')
        if not steam_id.isdigit():
            raise ValueError(
                'Game {} has invalid Steam ID: {}'.format(gm_id, steam_id)
            )

        folder = config.get_val(gm_id, 'Dir', '')
        if not folder:
            raise ValueError(
                'Game {} has no folder!'.format(gm_id)
            )
        mod_times = {}

        for name, value in config.items(gm_id):
            if name.startswith('pack_mod_'):
                mod_times[name[9:].casefold()] = srctools.conv_int(value)

        return cls(gm_id, steam_id, folder, mod_times)

    def save(self):
        """Write a game into the config page."""
        # Wipe the original configs
        CONFIG[self.name] = {}
        CONFIG[self.name]['SteamID'] = self.steamID
        CONFIG[self.name]['Dir'] = self.root
        for pack, mod_time in self.mod_times.items():
            CONFIG[self.name]['pack_mod_' + pack] = str(mod_time)

    def dlc_priority(self):
        """Iterate through all subfolders, in order of high to low priority.

        We assume the priority follows:
        1. update,
        2. portal2_dlc99, ..., portal2_dlc2, portal2_dlc1
        3. portal2,
        4. <all others>
        """
        dlc_count = 1
        priority = ["portal2"]
        while os.path.isdir(self.abs_path("portal2_dlc" + str(dlc_count))):
            priority.append("portal2_dlc" + str(dlc_count))
            dlc_count += 1
        if os.path.isdir(self.abs_path("update")):
            priority.append("update")
        # files are definitely not here
        blacklist = ("bin", "Soundtrack", "sdk_tools", "sdk_content")
        yield from reversed(priority)
        for folder in os.listdir(self.root):
            if (os.path.isdir(self.abs_path(folder)) and
                    folder not in priority and
                    folder not in blacklist):
                yield folder

    def abs_path(self, path):
        return os.path.normcase(os.path.join(self.root, path))

    def add_editor_sounds(self, sounds):
        """Add soundscript items so they can be used in the editor."""
        # PeTI only loads game_sounds_editor, so we must modify that.
        # First find the highest-priority file
        for folder in self.dlc_priority():
            file = self.abs_path(os.path.join(
                folder,
                'scripts',
                'game_sounds_editor.txt'
            ))
            if os.path.isfile(file):
                break  # We found it
        else:
            # Assume it's in dlc2
            file = self.abs_path(os.path.join(
                'portal2_dlc2',
                'scripts',
                'game_sounds_editor.txt',
            ))
        try:
            with open(file, encoding='utf8') as f:
                file_data = list(f)
        except FileNotFoundError:
            # If the file doesn't exist, we'll just write our stuff in.
            file_data = []
        for i, line in enumerate(file_data):
            if line.strip() == EDITOR_SOUND_LINE:
                # Delete our marker line and everything after it
                del file_data[i:]

        # Then add our stuff!
        with open(file, 'w', encoding='utf8') as f:
            f.writelines(file_data)
            f.write(EDITOR_SOUND_LINE + '\n')
            for sound in sounds:
                for line in sound.data.export():
                    f.write(line)
                f.write('\n')  # Add a little spacing

    def edit_gameinfo(self, add_line=False):
        """Modify all gameinfo.txt files to add or remove our line.

        Add_line determines if we are adding or removing it.
        """

        for folder in self.dlc_priority():
            info_path = os.path.join(self.root, folder, 'gameinfo.txt')
            if os.path.isfile(info_path):
                with open(info_path, encoding='utf8') as file:
                    data = list(file)

                for line_num, line in reversed(list(enumerate(data))):
                    clean_line = srctools.clean_line(line)
                    if add_line:
                        if clean_line == GAMEINFO_LINE:
                            break  # Already added!
                        elif '|gameinfo_path|' in clean_line:
                            LOGGER.debug(
                                "Adding gameinfo hook to {}",
                                info_path,
                            )
                            # Match the line's indentation
                            data.insert(
                                line_num+1,
                                utils.get_indent(line) + GAMEINFO_LINE + '\n',
                                )
                            break
                    else:
                        if clean_line == GAMEINFO_LINE:
                            LOGGER.debug(
                                "Removing gameinfo hook from {}", info_path
                            )
                            data.pop(line_num)
                            break
                else:
                    if add_line:
                        LOGGER.warning(
                            'Failed editing "{}" to add our special folder!',
                            info_path,
                        )
                    continue

                with srctools.AtomicWriter(info_path) as file:
                    for line in data:
                        file.write(line)
        if not add_line:
            # Restore the original files!
            for name, file, ext in FILES_TO_BACKUP:
                item_path = self.abs_path(file + ext)
                backup_path = self.abs_path(file + '_original' + ext)
                old_version = self.abs_path(file + '_styles' + ext)
                if os.path.isfile(old_version):
                    LOGGER.info('Restoring Stylechanger version of "{}"!', name)
                    shutil.copy(old_version, item_path)
                elif os.path.isfile(backup_path):
                    LOGGER.info('Restoring original "{}"!', name)
                    shutil.move(backup_path, item_path)
            self.clear_cache()

    def cache_invalid(self):
        """Check to see if the cache is valid."""
        if GEN_OPTS.get_bool('General', 'preserve_bee2_resource_dir'):
            # Skipped always
            return False

        # Check lengths, to ensure we re-extract if packages were removed.
        if len(packageLoader.packages) != len(self.mod_times):
            LOGGER.info('Need to extract - package counts inconsistent!')
            return True

        if any(
            pack.is_stale(self.mod_times.get(pack_id.casefold(), 0))
            for pack_id, pack in
            packageLoader.packages.items()
        ):
            return True

    def refresh_cache(self):
        """Copy over the resource files into this game."""
        screen_func = export_screen.step

        with res_system:
            for file in res_system.walk_folder_repeat():
                try:
                    start_folder, path = file.path.split('/', 1)
                except ValueError:
                    LOGGER.warning('File in resources root: "{}"!', file.path)
                    continue

                start_folder = start_folder.casefold()

                if start_folder == 'instances':
                    dest = self.abs_path(INST_PATH + '/' + path)
                elif start_folder in ('bee2', 'music_samp'):
                    screen_func('RES')
                    continue  # Skip app icons
                else:
                    dest = self.abs_path(os.path.join('bee2', start_folder, path))

                # Already copied from another package.
                if os.path.exists(dest):
                    screen_func('RES')
                    continue

                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with file.open_bin() as fsrc, open(dest, 'wb') as fdest:
                    shutil.copyfileobj(fsrc, fdest)
                screen_func('RES')

        LOGGER.info('Cache copied.')
        # Save the new cache modification date.
        self.mod_times.clear()
        for pack_id, pack in packageLoader.packages.items():
            self.mod_times[pack_id.casefold()] = pack.get_modtime()
        self.save()
        CONFIG.save_check()

    def clear_cache(self):
        """Remove all resources from the game."""
        shutil.rmtree(self.abs_path(INST_PATH), ignore_errors=True)
        shutil.rmtree(self.abs_path('bee2/'), ignore_errors=True)
        shutil.rmtree(self.abs_path('bin/bee2/'), ignore_errors=True)

        try:
            packageLoader.StyleVPK.clear_vpk_files(self)
        except PermissionError:
            pass

        self.mod_times.clear()

    def export(
        self,
        style: packageLoader.Style,
        selected_objects: dict,
        should_refresh=False,
        ) -> Tuple[bool, bool]:
        """Generate the editoritems.txt and vbsp_config.

        - If no backup is present, the original editoritems is backed up.
        - For each object type, run its .export() function with the given
        - item.
        - Styles are a special case.
        """

        LOGGER.info('-' * 20)
        LOGGER.info('Exporting Items and Style for "{}"!', self.name)

        LOGGER.info('Style = {}', style.id)
        for obj, selected in selected_objects.items():
            # Skip lists and dicts etc - too long
            if selected is None or isinstance(selected, str):
                LOGGER.info('{} = {}', obj, selected)

        # VBSP, VRAD, editoritems
        export_screen.set_length('BACK', len(FILES_TO_BACKUP))
        # files in compiler/
        try:
            num_compiler_files = len(os.listdir('../compiler'))
        except FileNotFoundError:
            num_compiler_files = 0

        if self.steamID == utils.STEAM_IDS['APERTURE TAG']:
            # Coop paint gun instance
            num_compiler_files += 1

        if num_compiler_files == 0:
            LOGGER.warning('No compiler files!')
            export_screen.skip_stage('COMP')
        else:
            export_screen.set_length('COMP', num_compiler_files)

        LOGGER.info('Should refresh: {}', should_refresh)
        if should_refresh:
            # Check to ensure the cache needs to be copied over..
            should_refresh = self.cache_invalid()
            if should_refresh:
                LOGGER.info("Cache invalid - copying..")
            else:
                LOGGER.info("Skipped copying cache!")

        # The items, plus editoritems, vbsp_config and the instance list.
        export_screen.set_length('EXP', len(packageLoader.OBJ_TYPES) + 3)

        # Do this before setting music and resources,
        # those can take time to compute.

        export_screen.show()
        export_screen.grab_set_global()  # Stop interaction with other windows

        if should_refresh:
            # Count the files.
            export_screen.set_length(
                'RES',
                sum(1 for file in res_system.walk_folder_repeat()),
            )
        else:
            export_screen.skip_stage('RES')
            export_screen.skip_stage('MUS')

        # Make the folders we need to copy files to, if desired.
        os.makedirs(self.abs_path('bin/bee2/'), exist_ok=True)

        # Start off with the style's data.
        editoritems, vbsp_config = style.export()
        export_screen.step('EXP')

        vpk_success = True

        # Export each object type.
        for obj_name, obj_data in packageLoader.OBJ_TYPES.items():
            if obj_name == 'Style':
                continue  # Done above already

            LOGGER.info('Exporting "{}"', obj_name)
            selected = selected_objects.get(obj_name, None)

            try:
                obj_data.cls.export(packageLoader.ExportData(
                    game=self,
                    selected=selected,
                    editoritems=editoritems,
                    vbsp_conf=vbsp_config,
                    selected_style=style,
                ))
            except packageLoader.NoVPKExport:
                # Raised by StyleVPK to indicate it failed to copy.
                vpk_success = False

            export_screen.step('EXP')

        vbsp_config.set_key(
            ('Options', 'BEE2_loc'),
            os.path.dirname(os.getcwd())  # Go up one dir to our actual location
        )
        vbsp_config.set_key(
            ('Options', 'Game_ID'),
            self.steamID,
        )

        # If there are multiple of these blocks, merge them together.
        # They will end up in this order.
        vbsp_config.merge_children(
            'Textures',
            'Fizzler',
            'Options',
            'StyleVars',
            'Conditions',
            'Voice',
            'PackTriggers',
        )

        for name, file, ext in FILES_TO_BACKUP:
            item_path = self.abs_path(file + ext)
            backup_path = self.abs_path(file + '_original' + ext)
            if os.path.isfile(item_path) and not os.path.isfile(backup_path):
                LOGGER.info('Backing up original {}!', name)
                shutil.copy(item_path, backup_path)
            export_screen.step('BACK')

        # Backup puzzles, if desired
        backup.auto_backup(selected_game, export_screen)

        # This is the connection "heart" and "error" models.
        # These have to come last, so we need to special case it.
        editoritems += style.editor.find_key("Renderables", []).copy()

        # Special-case: implement the UnlockDefault stlylevar here,
        # so all items are modified.
        if selected_objects['StyleVar']['UnlockDefault']:
            LOGGER.info('Unlocking Items!')
            for item in editoritems.find_all('Item'):
                # If the Unlock Default Items stylevar is enabled, we
                # want to force the corridors and obs room to be
                # deletable and copyable
                # Also add DESIRES_UP, so they place in the correct orientation
                if item['type', ''] in _UNLOCK_ITEMS:
                    editor_section = item.find_key("Editor", [])
                    editor_section['deletable'] = '1'
                    editor_section['copyable'] = '1'
                    editor_section['DesiredFacing'] = 'DESIRES_UP'

        LOGGER.info('Editing Gameinfo!')
        self.edit_gameinfo(True)

        LOGGER.info('Writing instance list!')
        with open(self.abs_path('bin/bee2/instances.cfg'), 'w', encoding='utf8') as inst_file:
            for line in self.build_instance_data(editoritems):
                inst_file.write(line)
        export_screen.step('EXP')

        # AtomicWriter writes to a temporary file, then renames in one step.
        # This ensures editoritems won't be half-written.
        LOGGER.info('Writing Editoritems!')
        with srctools.AtomicWriter(self.abs_path(
                'portal2_dlc2/scripts/editoritems.txt')) as editor_file:
            for line in editoritems.export():
                editor_file.write(line)
        export_screen.step('EXP')

        LOGGER.info('Writing VBSP Config!')
        os.makedirs(self.abs_path('bin/bee2/'), exist_ok=True)
        with open(self.abs_path('bin/bee2/vbsp_config.cfg'), 'w', encoding='utf8') as vbsp_file:
            for line in vbsp_config.export():
                vbsp_file.write(line)
        export_screen.step('EXP')

        if num_compiler_files > 0:
            LOGGER.info('Copying Custom Compiler!')
            for file in os.listdir('../compiler'):
                src_path = os.path.join('../compiler', file)
                if not os.path.isfile(src_path):
                    continue

                dest = self.abs_path('bin/' + file)

                LOGGER.info('\t* compiler/{0} -> bin/{0}', file)

                try:
                    if os.path.isfile(dest):
                        # First try and give ourselves write-permission,
                        # if it's set read-only.
                        utils.unset_readonly(dest)
                    shutil.copy(
                        src_path,
                        self.abs_path('bin/')
                    )
                except PermissionError:
                    # We might not have permissions, if the compiler is currently
                    # running.
                    export_screen.grab_release()
                    export_screen.reset()
                    messagebox.showerror(
                        title=_('BEE2 - Export Failed!'),
                        message=_('Copying compiler file {file} failed.'
                                  'Ensure the {game} is not running.').format(
                                    file=file,
                                    game=self.name,
                                ),
                        master=TK_ROOT,
                    )
                    return False, vpk_success
                export_screen.step('COMP')


        if should_refresh:
            LOGGER.info('Copying Resources!')
            self.refresh_cache()

            self.copy_mod_music()

        if self.steamID == utils.STEAM_IDS['APERTURE TAG']:
            os.makedirs(self.abs_path('sdk_content/maps/instances/bee2/'), exist_ok=True)
            with open(self.abs_path('sdk_content/maps/instances/bee2/tag_coop_gun.vmf'), 'w') as f:
                TAG_COOP_INST_VMF.export(f)

        export_screen.grab_release()
        export_screen.reset()  # Hide loading screen, we're done
        return True, vpk_success

    @staticmethod
    def build_instance_data(editoritems: Property):
        """Build a property tree listing all of the instances for each item.
        as well as another listing the input and output commands.
        VBSP uses this to reduce duplication in VBSP_config files.

        This additionally strips custom instance definitions from the original
        list.
        """
        instance_locs = Property("AllInstances", [])
        cust_inst = Property("CustInstances", [])
        commands = Property("Connections", [])
        item_classes = Property("ItemClasses", [])
        root_block = Property(None, [
            instance_locs,
            item_classes,
            cust_inst,
            commands,
        ])

        for item in editoritems.find_all("Item"):
            instance_block = Property(item['Type'], [])
            instance_locs.append(instance_block)

            comm_block = Property(item['Type'], [])

            for inst_block in item.find_all("Exporting", "instances"):
                for inst in inst_block.value[:]:  # type: Property
                    if inst.name.isdigit():
                        # Direct Portal 2 value
                        instance_block.append(
                            Property('Instance', inst['Name'])
                        )
                    else:
                        # It's a custom definition, remove from editoritems
                        inst_block.value.remove(inst)

                        # Allow the name to start with 'bee2_' also to match
                        # the <> definitions - it's ignored though.
                        name = inst.name
                        if name[:5] == 'bee2_':
                            name = name[5:]

                        cust_inst.set_key(
                            (item['type'], name),
                            # Allow using either the normal block format,
                            # or just providing the file - we don't use the
                            # other values.
                            inst['name'] if inst.has_children() else inst.value,
                        )

            # Look in the Inputs and Outputs blocks to find the io definitions.
            # Copy them to property names like 'Input_Activate'.
            for io_type in ('Inputs', 'Outputs'):
                for block in item.find_all('Exporting', io_type, CONN_NORM):
                    for io_prop in block:
                        comm_block[
                            io_type[:-1] + '_' + io_prop.real_name
                        ] = io_prop.value

            # The funnel item type is special, having the additional input type.
            # Handle that specially.
            if item['type'].casefold() == 'item_tbeam':
                for block in item.find_all('Exporting', 'Inputs', CONN_FUNNEL):
                    for io_prop in block:
                        comm_block['TBeam_' + io_prop.real_name] = io_prop.value

            # Fizzlers don't work correctly with outputs. This is a signal to
            # conditions.fizzler, but it must be removed in editoritems.
            if item['ItemClass', ''].casefold() == 'itembarrierhazard':
                for block in item.find_all('Exporting', 'Outputs'):
                    if CONN_NORM in block:
                        del block[CONN_NORM]

            # Record the itemClass for each item type.
            item_classes[item['type']] = item['ItemClass', 'ItemBase']

            # Only add the block if the item actually has IO.
            if comm_block.value:
                commands.append(comm_block)

        return root_block.export()

    def launch(self):
        """Try and launch the game."""
        import webbrowser
        url = 'steam://rungameid/' + str(self.steamID)
        webbrowser.open(url)

    def copy_mod_music(self):
        """Copy music files from Tag and PS:Mel."""
        tag_dest = self.abs_path('bee2/sound/music/')
        # Mel's music has similar names to P2's, so put it in a subdir
        # to avoid confusion.
        mel_dest = self.abs_path('bee2/sound/music/mel/')
        # Obviously Tag has its music already...
        copy_tag = (
            self.steamID != utils.STEAM_IDS['APERTURE TAG'] and
            MUSIC_TAG_LOC is not None
        )

        file_count = 0
        if copy_tag:
            file_count += len(os.listdir(MUSIC_TAG_LOC))
        if MUSIC_MEL_VPK is not None:
            file_count += len(MEL_MUSIC_NAMES)

        export_screen.set_length('MUS', file_count)

        if copy_tag:
            os.makedirs(tag_dest, exist_ok=True)
            for filename in os.listdir(MUSIC_TAG_LOC):
                src_loc = os.path.join(MUSIC_TAG_LOC, filename)
                if os.path.isfile(src_loc):
                    shutil.copy(src_loc, tag_dest)
                    export_screen.step('MUS')

        if MUSIC_MEL_VPK is not None:
            os.makedirs(mel_dest, exist_ok=True)
            for filename in MEL_MUSIC_NAMES:
                with open(os.path.join(mel_dest, filename), 'wb') as dest:
                    dest.write(MUSIC_MEL_VPK['sound/music', filename].read())
                export_screen.step('MUS')

    def init_trans(self):
        """Try and load a copy of basemodui from Portal 2 to translate.

        Valve's items use special translation strings which would look ugly
        if we didn't convert them.
        """
        # Already loaded
        if TRANS_DATA:
            return

        # Allow overriding.
        try:
            lang = os.environ['BEE2_P2_LANG']
        except KeyError:
            pass
        else:
            self.load_trans(lang)
            return

        # We need to first figure out what language is used (if not English),
        # then load in the file. This is saved in the 'appmanifest',

        try:
            appman_file = open(self.abs_path('../../appmanifest_620.acf'))
        except FileNotFoundError:
            # Portal 2 isn't here...
            return

        with appman_file:
            appman = Property.parse(appman_file, 'appmanifest_620.acf')
        try:
            lang = appman.find_key('AppState').find_key('UserConfig')['language']
        except NoKeyError:
            return

        self.load_trans(lang)

    def load_trans(self, lang):
        """Actually load the translation."""
        # Already loaded
        if TRANS_DATA:
            return

        basemod_loc = self.abs_path(
            '../Portal 2/portal2_dlc2/resource/basemodui_' + lang + '.txt'
        )

        # Basemod files are encoded in UTF-16.
        try:
            basemod_file = open(basemod_loc, encoding='utf16')
        except FileNotFoundError:
            return
        with basemod_file:
            if lang == 'english':
                def filterer(file):
                    """The English language has some unused language text.

                    This needs to be skipped since it has invalid quotes."""
                    for line in file:
                        if line.count('"') <= 4:
                            yield line
                basemod_file = filterer(basemod_file)

            trans_prop = Property.parse(basemod_file, 'basemodui.txt')

        for item in trans_prop.find_key("lang", []).find_key("tokens", []):
            TRANS_DATA[item.real_name] = item.value


def find_steam_info(game_dir):
    """Determine the steam ID and game name of this folder, if it has one.

    This only works on Source games!
    """
    game_id = None
    name = None
    found_name = False
    found_id = False
    for folder in os.listdir(game_dir):
        info_path = os.path.join(game_dir, folder, 'gameinfo.txt')
        if os.path.isfile(info_path):
            with open(info_path) as file:
                for line in file:
                    clean_line = srctools.clean_line(line).replace('\t', ' ')
                    if not found_id and 'steamappid' in clean_line.casefold():
                        raw_id = clean_line.casefold().replace(
                            'steamappid', '').strip()
                        if raw_id.isdigit():
                            game_id = raw_id
                    elif not found_name and 'game ' in clean_line.casefold():
                        found_name = True
                        ind = clean_line.casefold().rfind('game') + 4
                        name = clean_line[ind:].strip().strip('"')
                    if found_name and found_id:
                        break
        if found_name and found_id:
            break
    return game_id, name


def scan_music_locs():
    """Try and determine the location of Aperture Tag and PS:Mel.

    If successful we can export the music to games.
    """
    global MUSIC_TAG_LOC, MUSIC_MEL_VPK
    steamapp_locs = set()
    for gm in all_games:
        steamapp_locs.add(os.path.normpath(gm.abs_path('../')))

    for loc in steamapp_locs:
        tag_loc = os.path.join(loc, MUSIC_TAG_DIR)
        mel_loc = os.path.join(loc, MUSIC_MEL_DIR)
        if os.path.exists(tag_loc) and MUSIC_TAG_LOC is None:
            make_tag_coop_inst(loc)
            MUSIC_TAG_LOC = tag_loc
            LOGGER.info('Ap-Tag dir: {}', tag_loc)

        if os.path.exists(mel_loc) and MUSIC_MEL_VPK is None:
            MUSIC_MEL_VPK = VPK(mel_loc)
            LOGGER.info('PS-Mel dir: {}', mel_loc)

        if MUSIC_MEL_VPK is not None and MUSIC_TAG_LOC is not None:
            break


def make_tag_coop_inst(tag_loc: str):
    """Make the coop version of the tag instances.

    This needs to be shrunk, so all the logic entities are not spread
    out so much (coop tubes are small).

    This way we avoid distributing the logic.
    """
    global TAG_COOP_INST_VMF
    TAG_COOP_INST_VMF = vmf = VMF.parse(
        os.path.join(tag_loc, TAG_GUN_COOP_INST)
    )

    def logic_pos():
        """Put the entities in a nice circle..."""
        while True:
            for ang in range(0, 44):
                ang *= 360/44
                yield Vec(16*math.sin(ang), 16*math.cos(ang), 32)
    pos = logic_pos()
    # Move all entities that don't care about position to the base of the player
    for ent in TAG_COOP_INST_VMF.iter_ents():
        if ent['classname'] == 'info_coop_spawn':
            # Remove the original spawn point from the instance.
            # That way it can overlay over other dropper instances.
            ent.remove()
        elif ent['classname'] in ('info_target', 'info_paint_sprayer'):
            pass
        else:
            ent['origin'] = next(pos)

            # These originally use the coop spawn point, but this doesn't
            # always work. Switch to the name of the player, which is much
            # more reliable.
            if ent['classname'] == 'logic_measure_movement':
                ent['measuretarget'] = '!player_blue'

    # Add in a trigger to start the gel gun, and reset the activated
    # gel whenever the player spawns.
    trig_brush = vmf.make_prism(
        Vec(-32, -32, 0),
        Vec(32, 32, 16),
        mat='tools/toolstrigger',
    ).solid
    start_trig = vmf.create_ent(
        classname='trigger_playerteam',
        target_team=3,  # ATLAS
        spawnflags=1,  # Clients only
        origin='0 0 8',
    )
    start_trig.solids = [trig_brush]
    start_trig.add_out(
        # This uses the !activator as the target player so it must be via trigger.
        Output('OnStartTouchBluePlayer', '@gel_ui', 'Activate', delay=0, only_once=True),
        # Reset the gun to fire nothing.
        Output('OnStartTouchBluePlayer', '@blueisenabled', 'SetValue', 0, delay=0.1),
        Output('OnStartTouchBluePlayer', '@orangeisenabled', 'SetValue', 0, delay=0.1),
    )


def save():
    for gm in all_games:
        gm.save()
    CONFIG.save_check()


def load():
    global selected_game
    all_games.clear()
    for gm in CONFIG:
        if gm != 'DEFAULT':
            try:
                new_game = Game.parse(
                    gm,
                    CONFIG,
                )
            except ValueError:
                continue
            all_games.append(new_game)
            new_game.edit_gameinfo(True)
    if len(all_games) == 0:
        # Hide the loading screen, since it appears on top
        loadScreen.main_loader.suppress()

        # Ask the user for Portal 2's location...
        if not add_game(refresh_menu=False):
            # they cancelled, quit
            quit_application()
        loadScreen.main_loader.unsuppress()  # Show it again
    selected_game = all_games[0]


def add_game(e=None, refresh_menu=True):
    """Ask for, and load in a game to export to."""

    messagebox.showinfo(
        message=_('Select the folder where the game executable is located '
                  '({appname})...').format(appname='portal2' + EXE_SUFFIX),
        parent=TK_ROOT,
        title=_('BEE2 - Add Game'),
        )
    exe_loc = filedialog.askopenfilename(
        title=_('Find Game Exe'),
        filetypes=[(_('Executable'), '.exe')],
        initialdir='C:',
        )
    if exe_loc:
        folder = os.path.dirname(exe_loc)
        gm_id, name = find_steam_info(folder)
        if name is None or gm_id is None:
            messagebox.showinfo(
                message=_('This does not appear to be a valid game folder!'),
                parent=TK_ROOT,
                icon=messagebox.ERROR,
                title=_('BEE2 - Add Game'),
                )
            return False

        # Mel doesn't use PeTI, so that won't make much sense...
        if gm_id == utils.STEAM_IDS['MEL']:
            messagebox.showinfo(
                message=_("Portal Stories: Mel doesn't have an editor!"),
                parent=TK_ROOT,
                icon=messagebox.ERROR,
                title=_('BEE2 - Add Game'),
            )
            return False

        invalid_names = [gm.name for gm in all_games]
        while True:
            name = ask_string(
                prompt=_("Enter the name of this game:"),
                title=_('BEE2 - Add Game'),
                initialvalue=name,
                )
            if name in invalid_names:
                messagebox.showinfo(
                    icon=messagebox.ERROR,
                    parent=TK_ROOT,
                    message=_('This name is already taken!'),
                    title=_('BEE2 - Add Game'),
                    )
            elif name is None:
                return False
            elif name == '':
                messagebox.showinfo(
                    icon=messagebox.ERROR,
                    parent=TK_ROOT,
                    message=_('Please enter a name for this game!'),
                    title=_('BEE2 - Add Game'),
                    )
            else:
                break

        new_game = Game(name, gm_id, folder, {})
        new_game.edit_gameinfo(add_line=True)
        all_games.append(new_game)
        if refresh_menu:
            add_menu_opts(game_menu)
        save()
        return True


def remove_game(e=None):
    """Remove the currently-chosen game from the game list."""
    global selected_game
    lastgame_mess = (
        _("\n (BEE2 will quit, this is the last game set!)")
        if len(all_games) == 1 else
        ""
    )
    confirm = messagebox.askyesno(
        title="BEE2",
        message=_('Are you sure you want to delete "{}"?').format(
                selected_game.name
            ) + lastgame_mess,
        )
    if confirm:
        selected_game.edit_gameinfo(add_line=False)

        all_games.remove(selected_game)
        CONFIG.remove_section(selected_game.name)
        CONFIG.save()

        if not all_games:
            quit_application()  # If we have no games, nothing can be done

        selected_game = all_games[0]
        selectedGame_radio.set(0)
        add_menu_opts(game_menu)


def add_menu_opts(menu: Menu, callback=None):
    """Add the various games to the menu."""
    global selectedGame_radio, setgame_callback
    if callback is not None:
        setgame_callback = callback

    for ind in range(menu.index(END), 0, -1):
        # Delete all the old radiobutton
        # Iterate backward to ensure indexes stay the same.
        if menu.type(ind) == RADIOBUTTON:
            menu.delete(ind)

    for val, game in enumerate(all_games):
        menu.add_radiobutton(
            label=game.name,
            variable=selectedGame_radio,
            value=val,
            command=setGame,
        )
    setGame()


def setGame():
    global selected_game
    selected_game = all_games[selectedGame_radio.get()]
    setgame_callback(selected_game)


def set_game_by_name(name):
    global selected_game, selectedGame_radio
    for game in all_games:
        if game.name == name:
            selected_game = game
            selectedGame_radio.set(all_games.index(game))
            setgame_callback(selected_game)
            break

if __name__ == '__main__':
    Button(TK_ROOT, text='Add', command=add_game).grid(row=0, column=0)
    Button(TK_ROOT, text='Remove', command=remove_game).grid(row=0, column=1)
    test_menu = Menu(TK_ROOT)
    dropdown = Menu(test_menu)
    test_menu.add_cascade(menu=dropdown, label='Game')
    dropdown.game_pos = 0
    TK_ROOT['menu'] = test_menu

    load()
    add_menu_opts(dropdown, setgame_callback)
