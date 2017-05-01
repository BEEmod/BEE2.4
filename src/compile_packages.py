"""This converts each folder in packages/ into a zip, saving the zips into zips/.

This way it's easy to edit them.
Additionally all resources are saved into zips/resources.zip.
"""
from zipfile import ZipFile, ZIP_LZMA
from io import StringIO
import itertools
import os
import shutil

from srctools import Property, KeyValError, VMF, Entity, conv_bool
from uritemplate import URITemplate
import requests

import updater

OPTIMISE = False
PACKAGE_LOC = os.environ['BEE2_PACKAGE_LOC']


def build_manifest(
    zip_path,
    upload_url: URITemplate,
    download_url: str,
    bee2_version='',
):
    """Generate the manifest file needed to download packages."""
    manifest = Property(None, [])
    if bee2_version:
        manifest['BEE2_version'] = bee2_version
    man_packages = Property('Packages', [])
    manifest.append(man_packages)

    try:
        web_manifest = Property.parse(updater.dl_manifest())
    except ValueError:
        web_manifest = Property(None, [])

    orig_hashes = {}

    for prop in web_manifest.find_children('Packages'):
        orig_hashes[prop.real_name] = prop['sha1'], prop['url']

    for zip_name in os.listdir(zip_path):
        pack_loc = os.path.join(zip_path, zip_name)
        last_hash, last_url = orig_hashes.get(zip_name, 'xx')
        print('{}: {} -> '.format(zip_name, last_hash), end='', flush=True)
        cur_hash = updater.hash_file(pack_loc)
        print(cur_hash)

        if cur_hash == last_hash:
            cur_url = last_url
        else:
            # We need to upload to the release.
            print('Uploading "{}"...'.format(zip_name), end='')
            requests.post(
                upload_url.expand(name=zip_name),
                params=updater.GH_TOKEN_PARMS,
                data=open(pack_loc, 'rb'),
                headers={'Content-Type': 'application/zip'},
            )
            cur_url = download_url + zip_name
            print(' Done!')

        man_packages.append(Property(zip_name, [
            Property('SHA1', cur_hash),
            Property('URL', cur_url),
        ]))

    manifest_data = StringIO()
    for line in manifest.export():
        manifest_data.write(line)

    print('Uploading manifest...', end='')
    requests.post(
        upload_url.expand(name='manifest.txt', label='manifest'),
        params=updater.GH_TOKEN_PARMS,
        data=manifest_data.getvalue().encode('utf8'),
        headers={'Content-Type': 'text/plain'},
    )


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

    skip = input('Optimise zips or SKIP? ').casefold()
    item_version = input('Items Version: ')
    bee2_version = input(' BEE2 Version: ')
    OPTIMISE = conv_bool(skip)

    updater.GEN_OPTS.load()
    user, repro_name = updater.get_repro()

    release_resp = requests.post(
        'https://api.github.com/repos/{}/{}/releases'.format(user, repro_name),
        params=updater.GH_TOKEN_PARMS,
        json={
            'tag_name': 'v' + item_version,
            'target_commitish': 'dev',
            "name": 'Packages Version ' + item_version,
            'body': 'This release is incomplete. Do not download.',
            'draft': True,
            'prerelease': False,
        },
    )
    release_resp.raise_for_status()
    release_data = release_resp.json()
    keep_release = False
    try:
        print('Release made!')
        print('Remaining on limit: {}/{}'.format(
            release_resp.headers['X-RateLimit-Remaining'],
            release_resp.headers['X-RateLimit-Limit'],
        ))
        upload_url = URITemplate(release_data['upload_url'])
        download_url = 'https://github.com/{}/{}/releases/download/v{}/'.format(
            user, repro_name, item_version
        )

        zip_path = os.path.join(
            PACKAGE_LOC,
            'zips',
            'sml' if OPTIMISE else 'lrg',
        )

        if skip.casefold() != 'skip':
            if os.path.isdir(zip_path):
                for file in os.listdir(zip_path):
                    print('Deleting', file)
                    os.remove(os.path.join(zip_path, file))
            else:
                os.makedirs(zip_path, exist_ok=True)

            shutil.rmtree(os.path.join(PACKAGE_LOC, 'zips/hammer/'), ignore_errors=True)

            path = os.path.join(PACKAGE_LOC, 'packages\\')

            # A list of all the package zips.
            for package in search_folder(zip_path, path):
                build_package(*package)

        build_manifest(zip_path, upload_url, download_url, bee2_version)

        keep_release = True
    finally:
        # If we fail delete the release to clean up.
        if not keep_release:
            print('Deleting release!')
            requests.delete(
                'https://api.github.com/repos/{}/{}/releases/{}'.format(
                    user,
                    repro_name,
                    release_data['id'],
                ),
                params=updater.GH_TOKEN_PARMS,
            )
    print('Complete!')

if __name__ == '__main__':
    main()
