"""Provides a shim which pretends to be a ZipFile, but really reads from a directory.

This is useful to allow using the same code for reading folders or zips of data.
"""
from typing import IO, Iterator, Literal, Optional, Set, TextIO, Union
from typing_extensions import Self
from zipfile import ZIP_STORED, ZipFile
import shutil
import os
import io



class FakeZipInfo:
    """Analog to zipfile.ZipInfo, but for directories.

    Call with a mode to get a file object:
    """
    __slots__ = ['filename', 'comment']

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.comment = ''

    compress_type = ZIP_STORED  # Files on disk are uncompressed..
    reserved = 0

    def __str__(self) -> str:
        return self.filename

    def __call__(self, m='r') -> TextIO:
        return open(self.filename, m)


class FakeZip:
    """A replica of zipfile.ZipFile which reads from a directory.

    It offers all the same functions, but instead reads grabs
    files from subfolders.
    """
    def __init__(self, folder: str, mode: str = 'w') -> None:
        self.folder = folder
        self.wr_mode = 'a' if 'a' in mode else 'w'

        self.comment = ''
        self.debug = 0

    def close(self) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> Literal[False]:
        # Always re-raise exceptions
        return False

    def open(self, name: str, mode: str = 'r', pwd: object=None):
        try:
            return open(os.path.join(self.folder, name), mode)
        except FileNotFoundError as err:
            raise KeyError from err  # This is what zips raise

    def names(self) -> Iterator[str]:
        base = self.folder
        rel_path = os.path.relpath
        for dirpath, dirnames, filenames in os.walk(base):
            for name in filenames:
                yield rel_path(dirpath + '/' + name, base)

    def namelist(self) -> Set[str]:
        """We actually return a set, since this is mainly used for 'in'
        testing.
        """
        return set(self.names())

    def infolist(self) -> Iterator[FakeZipInfo]:
        return map(FakeZipInfo, self.names())

    def getinfo(self, file) -> FakeZipInfo:
        return FakeZipInfo(file)

    def extract(self, member: str, path: Optional[str] = None, pwd: object=None) -> None:
        if path is None:
            path = os.getcwd()
        dest = os.path.join(path, member)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(
            os.path.join(self.folder, member),
            dest,
        )

    def write(self, filename: str, arcname: Optional[str] = None, compress_type: Optional[int] = None) -> None:
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

    def setpassword(self, pwd: object) -> None:
        """Fake ZipFiles don't care about the password."""
        pass


def zip_names(zip: Union[FakeZip, ZipFile]) -> Iterator[str]:
    """For FakeZips, use the generator instead of the zip file.

    """
    if hasattr(zip, 'names'):
        return zip.names()
    else:
        def zip_filter() -> Iterator[str]:
            # 'Fix' an issue where directories are also being listed...
            for name in zip.namelist():
                if name[-1] != '/':
                    yield name
        return zip_filter()


def zip_open_bin(zip: Union[FakeZip, ZipFile], filename: str) -> IO[bytes]:
    """Open zips and fake zips in binary mode."""
    if isinstance(zip, FakeZip):
        return zip.open(filename, 'rb')
    else:
        return zip.open(filename, 'r')


def zip_open_text(zip: Union[FakeZip, ZipFile], filename: str) -> IO[str]:
    """Open zips and fake zips in text mode."""
    if isinstance(zip, FakeZip):
        return zip.open(filename)
    else:
        # Wrap the zip file to decode.
        return io.TextIOWrapper(zip.open(filename, 'r'), encoding='utf8')
