"""Provides a shim which pretends to be a ZipFile, but really reads from a directory.

This is useful to allow using the same code for reading folders or zips of data.
"""
import shutil
import os

from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

class FakeZipInfo:
    """Analog to zipfile.ZipInfo, but for directories.

    Call with a mode to get a file object:
    """
    __slots__ = ['filename', 'comment']

    def __init__(self, filename):
        self.filename = filename
        self.comment = ''
    compress_type = ZIP_DEFLATED
    reserved = 0

    def __str__(self):
        return self.filename

    def __call__(self, m='r'):
        return open(self.filename, m)


class FakeZip:
    """A replica of zipfile.ZipFile which reads from a directory.

    It offers all the same functions, but instead reads grabs
    files from subfolders.
    """
    def __init__(self, folder, mode='w', compress_type=None):
        self.folder = folder
        self.wr_mode = 'a' if 'a' in mode else 'w'

        self.comment = ''
        self.debug = 0

    def close(self):
        pass

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Always re-raise exceptions
        return False

    def open(self, name, mode='r', pwd=None):
        try:
            return open(os.path.join(self.folder, name))
        except FileNotFoundError as err:
            raise KeyError from err  # This is what zips raise

    def names(self):
        base = self.folder
        for dirpath, dirnames, filenames in os.walk(base):
            for name in filenames:
                yield os.path.relpath(os.path.join(dirpath, name), base)

    def namelist(self):
        return list(self.names())

    def infolist(self):
        return map(FakeZipInfo, self.names())

    def getinfo(self, file):
        return FakeZipInfo(file)

    def extract(self, member, path=None, pwd=None):
        if path is None:
            path = os.getcwd()
        dest = os.path.join(path, member)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(
            os.path.join(self.folder, member),
            dest,
        )

    def write(self, filename, arcname=None, compress_type=None):
        """Save the given file into the directory.

        arcname is the destination if given,
        compress_type is ignored.
        """
        filename = str(filename)
        if arcname is None:
            arcname = os.getcwd()

        shutil.copy(filename, self.folder + arcname)

    def writestr(self, zinfo_or_arcname, data, *comp):
        dest = str(zinfo_or_arcname)
        with open(os.path.join(self.folder, dest), self.wr_mode) as f:
            f.write(data)

    def setpassword(self, pwd):
        """Fake ZipFiles don't care about the password."""
        pass
