"""This converts each folder in packages/ into a zip, saving the zips into zips/.

This way it's easy to edit them.
Additionally all resources are saved into zips/resources.zip.
"""
import os
import shutil
import sys
import itertools
from zipfile import ZipFile, ZIP_LZMA, ZIP_DEFLATED

from srctools import Property, KeyValError, VMF, Entity, conv_bool

OPTIMISE = False


def clean_vmf(vmf_path):
    """Optimise the VMFs, removing unneeded entities or objects."""
    inst = VMF.parse(vmf_path)

    for ent in itertools.chain([inst.spawn], inst.entities[:]):  # type: Entity
        # Remove comments
        ent.comments = ''

        # Remove entities that have their visgroups hidden.
        if ent.hidden or not ent.vis_shown:
            print('Removing hidden ent')
            inst.remove_ent(ent)
            continue

        # Remove info_null entities
        if ent['classname'] == 'info_null':
            print('Removing info_null...')
            inst.remove_ent(ent)
            continue
            
        # All instances must be in bee2/, so any reference outside there is a map error!
        # It's ok if it's in p2editor and not in a subfolder though.
        # There's also an exception needed for the Tag gun instance.
        if ent['classname'] == 'func_instance':
            inst_loc = ent['file'].casefold().replace('\\','/')
            if not inst_loc.startswith('instances/bee2/') and not (inst_loc.startswith('instances/p2editor/') and inst_loc.count('/') == 2) and 'alatag' not in inst_loc:
                input('Invalid instance path "{}" in\n"{}"! Press Enter to continue..'.format(ent['file'], vmf_path))
                yield from clean_vmf(vmf_path) # Re-run so we check again..

        for solid in ent.solids[:]:
            if all(face.mat.casefold() == 'tools/toolsskip' for face in solid):
                print('Removing SKIP brush')
                ent.solids.remove(solid)
                continue

            if solid.hidden or not solid.vis_shown:
                print('Removing hidden brush')
                ent.solids.remove(solid)
                continue

    for detail in inst.by_class['func_detail']:
        # Remove several unused default options from func_detail.
        # We're not on xbox!
        del detail['disableX360']
        # These aren't used in any instances, and it doesn't seem as if
        # VBSP preserves these values anyway.
        del detail['maxcpulevel'], detail['mincpulevel']
        del detail['maxgpulevel'], detail['mingpulevel']

    # Since all VMFs are instances or similar (not complete maps), we'll never
    # use worldspawn's settings. Keep mapversion though.
    del inst.spawn['maxblobcount'], inst.spawn['maxpropscreenwidth']
    del inst.spawn['maxblobcount'],
    del inst.spawn['detailvbsp'], inst.spawn['detailmaterial']

    lines = inst.export(inc_version=False, minimal=True).splitlines()
    for line in lines:
        yield line.lstrip()


# Text files we should clean up.
PROP_EXT = ('.cfg', '.txt', '.vmt', '.nut')
def clean_text(file_path):
    # Try and parse as a property file. If it succeeds,
    # write that out - it removes excess whitespace between lines
    with open(file_path, 'r') as f:
        try: 
            props = Property.parse(f)
        except KeyValError:
            pass
        else:
            for line in props.export():
                yield line.lstrip()
            return
    
    with open(file_path, 'r') as f:
        for line in f:
            if line.isspace():
                continue
            if line.lstrip().startswith('//'):
                continue
            # Remove // comments, but only if the comment doesn't have
            # a quote char after it - it could be part of the string,
            # so leave it just to be safe.
            if '//' in line and '"' not in line:
                yield line.split('//')[0] + '\n'
            else:
                yield line.lstrip()


# Delete these files, if they exist in the source folders.
# Users won't need them.
DELETE_EXTENSIONS = ['vmx', 'log', 'bsp', 'prt', 'lin']


def search_folder(zip_path, path):
    """Search the given folder for packages.
    
    zip_path is the folder the zips will be saved in, 
    and path is the location to search.
    """
    for package in os.listdir(path):
        package_path = os.path.join(path, package)
        if not os.path.isdir(package_path):
            continue
        if 'info.txt' not in os.listdir(package_path):
            yield from search_folder(zip_path, package_path)
            continue

        print('| ' + package + '.zip')
        pack_zip_path = os.path.join(zip_path, package) + '.zip'

        yield package_path, pack_zip_path, zip_path

        
def build_package(package_path, pack_zip_path, zip_path):
    """Build the packages in a given folder."""
    
    zip_file = ZipFile(
        pack_zip_path,
        'w',
        compression=ZIP_LZMA,
    )

    print('Starting on "{}"'.format(package_path))
    with zip_file:
        for base, dirs, files in os.walk(package_path):
            for file in files:
                full_path = os.path.normpath(os.path.join(base, file))
                rel_path = os.path.relpath(full_path, package_path)
                if file[-3:] in DELETE_EXTENSIONS:
                    print('\nX   \\' + rel_path)
                    os.remove(full_path)
                    continue

                hammer_path = os.path.relpath(rel_path, 'resources/')
                if hammer_path.startswith('..'):
                    hammer_path = None
                elif hammer_path.casefold().startswith(('bee2', 'instances')):
                    # Skip icons and instances
                    hammer_path = None
                elif 'props_map_editor' in hammer_path:
                    # Skip editor models
                    hammer_path = None
                elif 'puzzlemaker' in hammer_path:
                    # Skip editor models
                    hammer_path = None
                elif 'music' in rel_path.casefold():
                    # Skip music files..
                    hammer_path = None
                else:
                    hammer_path = os.path.join('zips/hammer/', hammer_path)
                    os.makedirs(os.path.dirname(hammer_path), exist_ok=True)

                print('.', end='', flush=True)
                
                if OPTIMISE and file.endswith('.vmf'):
                    print(rel_path)
                    data = '\r\n'.join(clean_vmf(full_path))
                    zip_file.writestr(rel_path, data)

                    if hammer_path:
                        with open(hammer_path, 'w') as f:
                            f.write(data)
                elif OPTIMISE and file.endswith(PROP_EXT):
                    print(rel_path)
                    data = ''.join(clean_text(full_path))
                    zip_file.writestr(rel_path, data)

                    if hammer_path:
                        with open(hammer_path, 'w') as f:
                            f.write(data)
                else:
                    zip_file.write(full_path, rel_path)

                    if hammer_path:
                        shutil.copy(full_path, hammer_path)

        print('')
    print('Finished "{}"'.format(package_path))


def main():
    global OPTIMISE
    
    OPTIMISE = conv_bool(input('Optimise zips? '))
    
    print('Optimising: ', OPTIMISE)

    zip_path = os.path.join(
        os.getcwd(),
        'zips',
        'sml' if OPTIMISE else 'lrg',
    )
    if os.path.isdir(zip_path):
        for file in os.listdir(zip_path):
            print('Deleting', file)
            os.remove(os.path.join(zip_path, file))
    else:
        os.makedirs(zip_path, exist_ok=True)

    shutil.rmtree('zips/hammer/', ignore_errors=True)

    path = os.path.join(os.getcwd(), 'packages\\', )
    
    # A list of all the package zips.
    for package in search_folder(zip_path, path):
        build_package(*package)

    print('Building main zip...')

    pack_name = 'BEE{}_packages.zip'.format(input('Version: '))
    
    with ZipFile(os.path.join('zips', pack_name), 'w', compression=ZIP_DEFLATED) as zip_file:
        for file in os.listdir(zip_path):
            zip_file.write(os.path.join(zip_path, file), os.path.join('packages/', file))
            print('.', end='', flush=True)
    print('Done!')

if __name__ == '__main__':
    main()
