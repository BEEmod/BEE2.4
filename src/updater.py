"""Handles downloading new copies of packages, and keeping them in sync."""
from datetime import datetime as DateTime, timedelta as TimeDelta
import os
import hashlib

from srctools import Property
import requests

from BEE2_config import GEN_OPTS
from loadScreen import LoadScreen
import utils

LOGGER = utils.getLogger(__name__)

USER_AGENT = 'BEEmod/BEE2.4 ver ' + utils.BEE_VERSION

PACKAGE_FOLDER = '../dl_packages/'
CACHED_MANIFEST = '../config/cached_manifest.txt'


PACKAGE_DL = LoadScreen(
    ('PACKAGES', 'Packages'),
    ('PACKAGE', 'Download Progress'),
    title_text='Updating Packages',
)


def get_release_date(rel):
    return DateTime.strptime(
        rel['published_at'],
        '%Y-%m-%dT%H:%M:%SZ',
    )


def hash_file(filename):
    """SHA1 the given file."""
    hasher = hashlib.sha1()
    try:
        file = open(filename, 'rb')
    except FileNotFoundError:
        # If not found, return an impossible
        # hash - that is != to others, so we
        # redownload.
        return ''
    with file:
        while True:
            # Read in parts.
            part = file.read(8*1024)
            if not part:
                return hasher.hexdigest()
            hasher.update(part)


def dl_manifest():
    """Retrieve the manifest from the web.
    
    Returns the text contents."""
    req = requests.get('https://api.github.com/repos/{}/{}/releases'.format(
        *GEN_OPTS.get_val('Packages', 'manifest_repro', 'BEEmod/BEE2-items').split('/')
    ))
    release = max(req.json(), key=get_release_date)
    
    for asset in release['assets']:
        if asset['name'] == 'manifest.txt':
            man_url = asset['browser_download_url']
            break
    else:
        raise ValueError('No manifest in latest release!')
    
    return man_url


def check_packages(force=False):
    """Check for new packages, and update if neccessary.
    
    If force is True, a new manifest will be downloaded and all packages
    updated.
    """
    cur_time = DateTime.now()
    last_check = DateTime.fromtimestamp(GEN_OPTS.get_float(
        'Packages', 'last_check', 0.0,
    ))
    if force or cur_time - last_check > TimeDelta(days=1):
        # Update now. If we fail, don't try again immediately.
        GEN_OPTS['Packages']['last_check'] = str(cur_time.timestamp())
        GEN_OPTS.save()
        
        # Grab a new manifest from the web, and check for changes.
        web_manifest = dl_manifest()
        if not force:
            web_hash = hashlib.sha1(web_manifest.encode('utf-8')).hexdigest()
            saved_hash = GEN_OPTS.get_val('Packages', 'manifest_sha1', '')
            if web_hash == saved_hash :
                # No changes, no need for a check.
                return

        with open(CACHED_MANIFEST, 'w') as f:
            f.write(web_manifest)

        manifest = Property.parse(web_manifest)
        
        if not utils.DEV_MODE: # No checks when running from source
            if manifest['BEE2_version', utils.BEE_VERSION] != utils.BEE_VERSION:
                # BEE2 version differs, recommend an update.
                # todo..
                pass
    else:
        with open(CACHED_MANIFEST) as f:
            manifest = Property.parse(f)
                
    os.makedirs(PACKAGE_FOLDER, exist_ok=True)
    # We remove any zips in the package folder
    # that aren't in the manifest.         
    zips_to_remove = {
        name.casefold()
        for name in
        os.listdir(PACKAGE_FOLDER)
    }
    
    package_list = list(manifest.find_children('Packages'))
    PACKAGE_DL.set_length('PACKAGES', len(package_list))
        
    for package_info in package_list:
        # It can't go into subfolders or parent ones.
        if '/' in package_info.name or '\\' in package_info.name:
            raise ValueError(
                'Invalid characters in package filename '
                '"{!r}"'.format(package_info.real_name)
            )
        zips_to_remove.discard(package_info.name)
        zip_loc = os.path.join(PACKAGE_FOLDER, package_info.real_name)
        desired_hash = package_info['sha1']
        cache_hash = hash_file(zip_loc)
        if cache_hash == desired_hash and not force:
            continue  # No update needed.
            
        file_len = package_info.int('length')
        downloaded = 0
        PACKAGE_DL.set_length('PACKAGES', file_len//1024)
        PACKAGE_DL.set_stage('PACKAGES', 0)
        with open(zip_loc, 'wb') as file:
            req = requests.get(package_info['url'], stream=True)
            for chunk in req.iter_content(chunk_size=1024):
                file.write(chunk)
                downloaded += len(chunk)
                PACKAGE_DL.set_length('PACKAGES', downloaded//1024)
    
    # Clean up package zips not in the list.
    for extra_package in zips_to_remove:
        LOGGER.info(('Extra package: "{}"', extra_package))
        os.unlink(os.path.join(PACKAGE_FOLDER, extra_package))

def update_bee2(url):
    """Download a new copy of the BEE2."""
    pass