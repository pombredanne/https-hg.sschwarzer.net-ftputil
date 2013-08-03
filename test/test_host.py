# encoding: utf-8
# Copyright (C) 2002-2013, Stefan Schwarzer <sschwarzer@sschwarzer.net>
# See the file LICENSE for licensing terms.

from __future__ import unicode_literals

import ftplib
import itertools
import os
import posixpath
import random
import time
import unittest

import ftputil
import ftputil.compat
import ftputil.error
import ftputil.stat

from test import mock_ftplib
from test import test_base


#
# Helper functions to generate random data
#
def random_data(pool, size=10000):
    """
    Return a byte string of characters consisting of those from the
    pool of integer numbers.
    """
    ordinal_list = [random.choice(pool) for i in range(size)]
    return ftputil.compat.bytes_from_ints(ordinal_list)


def ascii_data():
    r"""
    Return a _byte_ string of "normal" ASCII characters, including `\n`.
    """
    pool = list(range(32, 128))
    pool.append(ord("\n"))
    return random_data(pool)


def binary_data():
    """Return a binary character byte string."""
    pool = list(range(0, 256))
    return random_data(pool)


#
# Several customized `MockSession` classes
#
class FailOnLoginSession(mock_ftplib.MockSession):

    def __init__(self, host='', user='', password=''):
        raise ftplib.error_perm


class FailOnKeepAliveSession(mock_ftplib.MockSession):

    def pwd(self):
        # Raise exception on second call to let the constructor work.
        if not hasattr(self, "pwd_called"):
            self.pwd_called = True
        else:
            raise ftplib.error_temp


class RecursiveListingForDotAsPathSession(mock_ftplib.MockSession):

    dir_contents = {
      ".": """\
lrwxrwxrwx   1 staff          7 Aug 13  2003 bin -> usr/bin

dev:
total 10

etc:
total 10

pub:
total 4
-rw-r--r--   1 staff         74 Sep 25  2000 .message
----------   1 staff          0 Aug 16  2003 .notar
drwxr-xr-x  12 ftp          512 Nov 23  2008 freeware

usr:
total 4""",

      "": """\
total 10
lrwxrwxrwx   1 staff          7 Aug 13  2003 bin -> usr/bin
d--x--x--x   2 staff        512 Sep 24  2000 dev
d--x--x--x   3 staff        512 Sep 25  2000 etc
dr-xr-xr-x   3 staff        512 Oct  3  2000 pub
d--x--x--x   5 staff        512 Oct  3  2000 usr"""}

    def _transform_path(self, path):
        return path


class BinaryDownloadMockSession(mock_ftplib.MockUnixFormatSession):

    mock_file_content = binary_data()


class TimeShiftMockSession(mock_ftplib.MockSession):

    def delete(self, file_name):
        pass

#
# Customized `FTPHost` class for conditional upload/download tests
# and time shift tests
#
class FailingUploadAndDownloadFTPHost(ftputil.FTPHost):

    def upload(self, source, target, mode=''):
        assert False, "`FTPHost.upload` should not have been called"

    def download(self, source, target, mode=''):
        assert False, "`FTPHost.download` should not have been called"


class TimeShiftFTPHost(ftputil.FTPHost):

    class _Path:
        def split(self, path):
            return posixpath.split(path)
        def set_mtime(self, mtime):
            self._mtime = mtime
        def getmtime(self, file_name):
            return self._mtime
        def join(self, *args):
            return posixpath.join(*args)
        def normpath(self, path):
            return posixpath.normpath(path)
        def isabs(self, path):
            return posixpath.isabs(path)
        def abspath(self, path):
            return "/home/sschwarzer/_ftputil_sync_"
        # Needed for `isdir` in `FTPHost.remove`
        def isfile(self, path):
            return True

    def __init__(self, *args, **kwargs):
        ftputil.FTPHost.__init__(self, *args, **kwargs)
        self.path = self._Path()

#
# Test cases
#
class TestInitAndClose(unittest.TestCase):
    """Test initialization and closure of `FTPHost` objects."""

    def test_open_and_close(self):
        host = test_base.ftp_host_factory()
        host.close()
        self.assertEqual(host.closed, True)
        self.assertEqual(host._children, [])


class TestLogin(unittest.TestCase):

    def test_invalid_login(self):
        """Login to invalid host must fail."""
        self.assertRaises(ftputil.error.FTPOSError, test_base.ftp_host_factory,
                          FailOnLoginSession)


class TestKeepAlive(unittest.TestCase):

    def test_succeeding_keep_alive(self):
        """Assume the connection is still alive."""
        host = test_base.ftp_host_factory()
        host.keep_alive()

    def test_failing_keep_alive(self):
        """Assume the connection has timed out, so `keep_alive` fails."""
        host = test_base.ftp_host_factory(
                 session_factory=FailOnKeepAliveSession)
        self.assertRaises(ftputil.error.TemporaryError, host.keep_alive)


class TestSetParser(unittest.TestCase):

    class TrivialParser(ftputil.stat.Parser):
        """
        An instance of this parser always returns the same result
        from its `parse_line` method. This is all we need to check
        if ftputil uses the set parser. No actual parsing code is
        required here.
        """

        def __init__(self):
            # We can't use `os.stat("/home")` directly because we
            # later need the object's `_st_name` attribute, which
            # we can't set on a `os.stat` stat value.
            default_stat_result = ftputil.stat.StatResult(os.stat("/home"))
            default_stat_result._st_name = "home"
            self.default_stat_result = default_stat_result

        def parse_line(self, line, time_shift=0.0):
            return self.default_stat_result

    def test_set_parser(self):
        """Test if the selected parser is used."""
        host = test_base.ftp_host_factory()
        self.assertEqual(host._stat._allow_parser_switching, True)
        trivial_parser = TestSetParser.TrivialParser()
        host.set_parser(trivial_parser)
        stat_result = host.stat("/home")
        self.assertEqual(stat_result, trivial_parser.default_stat_result)
        self.assertEqual(host._stat._allow_parser_switching, False)


class TestCommandNotImplementedError(unittest.TestCase):

    def test_command_not_implemented_error(self):
        """
        Test if we get the anticipated exception if a command isn't
        implemented by the server.
        """
        host = test_base.ftp_host_factory()
        self.assertRaises(ftputil.error.CommandNotImplementedError,
                          host.chmod, "nonexistent", 0o644)
        # `CommandNotImplementedError` is a subclass of `PermanentError`.
        self.assertRaises(ftputil.error.PermanentError,
                          host.chmod, "nonexistent", 0o644)


class TestRecursiveListingForDotAsPath(unittest.TestCase):
    """
    Return a recursive directory listing when the path to list
    is a dot. This is used to test for issue #33, see
    http://ftputil.sschwarzer.net/trac/ticket/33 .
    """

    def test_recursive_listing(self):
        host = test_base.ftp_host_factory(
                 session_factory=RecursiveListingForDotAsPathSession)
        lines = host._dir(host.curdir)
        self.assertEqual(lines[0], "total 10")
        self.assertTrue(lines[1].startswith("lrwxrwxrwx   1 staff"))
        self.assertTrue(lines[2].startswith("d--x--x--x   2 staff"))
        host.close()

    def test_plain_listing(self):
        host = test_base.ftp_host_factory(
                 session_factory=RecursiveListingForDotAsPathSession)
        lines = host._dir("")
        self.assertEqual(lines[0], "total 10")
        self.assertTrue(lines[1].startswith("lrwxrwxrwx   1 staff"))
        self.assertTrue(lines[2].startswith("d--x--x--x   2 staff"))
        host.close()

    def test_empty_string_instead_of_dot_workaround(self):
        host = test_base.ftp_host_factory(
                 session_factory=RecursiveListingForDotAsPathSession)
        files = host.listdir(host.curdir)
        self.assertEqual(files, ['bin', 'dev', 'etc', 'pub', 'usr'])
        host.close()


class TestUploadAndDownload(unittest.TestCase):
    """Test ASCII upload and binary download as examples."""

    def generate_ascii_file(self, data, filename):
        """Generate a local ASCII data file."""
        with open(filename, "w") as source_file:
            source_file.write(data)

    def test_ascii_upload(self):
        """Test ASCII mode upload."""
        local_source = '__test_source'
        data = ascii_data()
        self.generate_ascii_file(data, local_source)
        # Upload
        host = test_base.ftp_host_factory()
        host.upload(local_source, 'dummy')
        # Check uploaded content. The data which was uploaded has its
        # line endings converted so the conversion must also be
        # applied to `data`.
        data = data.replace('\n', '\r\n')
        remote_file_content = mock_ftplib.content_of('dummy')
        self.assertEqual(data, remote_file_content)
        # Clean up
        os.unlink(local_source)

    def test_binary_download(self):
        """Test binary mode download."""
        local_target = '__test_target'
        host = test_base.ftp_host_factory(
                 session_factory=BinaryDownloadMockSession)
        # Download
        host.download('dummy', local_target, 'b')
        # Read file and compare
        with open(local_target, 'rb') as fobj:
            data = fobj.read()
        remote_file_content = mock_ftplib.content_of('dummy')
        self.assertEqual(data, remote_file_content)
        # Clean up
        os.unlink(local_target)

    def test_conditional_upload(self):
        """Test conditional ASCII mode upload."""
        local_source = '__test_source'
        data = ascii_data()
        self.generate_ascii_file(data, local_source)
        # Target is newer, so don't upload.
        host = test_base.ftp_host_factory(
                 ftp_host_class=FailingUploadAndDownloadFTPHost)
        flag = host.upload_if_newer(local_source, '/home/newer')
        self.assertEqual(flag, False)
        # Target is older, so upload.
        host = test_base.ftp_host_factory()
        flag = host.upload_if_newer(local_source, '/home/older')
        self.assertEqual(flag, True)
        # Check uploaded content. The data which was uploaded has its
        # line endings converted so the conversion must also be
        # applied to 'data'.
        data = data.replace('\n', '\r\n')
        remote_file_content = mock_ftplib.content_of('older')
        self.assertEqual(data, remote_file_content)
        # Target doesn't exist, so upload
        host = test_base.ftp_host_factory()
        flag = host.upload_if_newer(local_source, '/home/notthere')
        self.assertEqual(flag, True)
        remote_file_content = mock_ftplib.content_of('notthere')
        self.assertEqual(data, remote_file_content)
        # Clean up
        os.unlink(local_source)

    def compare_and_delete_downloaded_data(self, filename):
        """
        Compare content of downloaded file with its source, then
        delete the local target file.
        """
        with open(filename, 'rb') as fobj:
            data = fobj.read()
        # The name `newer` is used by all callers, so use it here, too.
        remote_file_content = mock_ftplib.content_of('newer')
        self.assertEqual(data, remote_file_content)
        # Clean up
        os.unlink(filename)

    def test_conditional_download_without_target(self):
        """
        Test conditional binary mode download when no target file
        exists.
        """
        local_target = '__test_target'
        # Target does not exist, so download.
        host = test_base.ftp_host_factory(
                 session_factory=BinaryDownloadMockSession)
        flag = host.download_if_newer('/home/newer', local_target, 'b')
        self.assertEqual(flag, True)
        self.compare_and_delete_downloaded_data(local_target)

    def test_conditional_download_with_older_target(self):
        """Test conditional binary mode download with newer source file."""
        local_target = '__test_target'
        # Make target file.
        open(local_target, 'w').close()
        # Source is newer (date in 2020), so download.
        host = test_base.ftp_host_factory(
                 session_factory=BinaryDownloadMockSession)
        flag = host.download_if_newer('/home/newer', local_target, 'b')
        self.assertEqual(flag, True)
        self.compare_and_delete_downloaded_data(local_target)

    def test_conditional_download_with_newer_target(self):
        """Test conditional binary mode download with older source file."""
        local_target = '__test_target'
        # Make target file.
        open(local_target, 'w').close()
        # Source is older (date in 1970), so don't download.
        host = test_base.ftp_host_factory(
                 ftp_host_class=FailingUploadAndDownloadFTPHost,
                 session_factory=BinaryDownloadMockSession)
        flag = host.download_if_newer('/home/older', local_target, 'b')
        self.assertEqual(flag, False)
        # Remove target file
        os.unlink(local_target)


class TestTimeShift(unittest.TestCase):

    def test_rounded_time_shift(self):
        """Test if time shift is rounded correctly."""
        host = test_base.ftp_host_factory(session_factory=TimeShiftMockSession)
        # Use private bound method.
        rounded_time_shift = host._FTPHost__rounded_time_shift
        # Pairs consisting of original value and expected result
        test_data = [
          (      0,           0),
          (      0.1,         0),
          (     -0.1,         0),
          (   1500,           0),
          (  -1500,           0),
          (   1800,        3600),
          (  -1800,       -3600),
          (   2000,        3600),
          (  -2000,       -3600),
          ( 5*3600-100,  5*3600),
          (-5*3600+100, -5*3600)]
        for time_shift, expected_time_shift in test_data:
            calculated_time_shift = rounded_time_shift(time_shift)
            self.assertEqual(calculated_time_shift, expected_time_shift)

    def test_assert_valid_time_shift(self):
        """Test time shift sanity checks."""
        host = test_base.ftp_host_factory(session_factory=TimeShiftMockSession)
        # Use private bound method.
        assert_time_shift = host._FTPHost__assert_valid_time_shift
        # Valid time shifts
        test_data = [23*3600, -23*3600, 3600+30, -3600+30]
        for time_shift in test_data:
            self.assertTrue(assert_time_shift(time_shift) is None)
        # Invalid time shift (exceeds one day)
        self.assertRaises(ftputil.error.TimeShiftError, assert_time_shift,
                          25*3600)
        self.assertRaises(ftputil.error.TimeShiftError, assert_time_shift,
                          -25*3600)
        # Invalid time shift (too large deviation from full hours unacceptable)
        self.assertRaises(ftputil.error.TimeShiftError, assert_time_shift,
                          10*60)
        self.assertRaises(ftputil.error.TimeShiftError, assert_time_shift,
                          -3600-10*60)

    def test_synchronize_times(self):
        """Test time synchronization with server."""
        host = test_base.ftp_host_factory(ftp_host_class=TimeShiftFTPHost,
                                          session_factory=TimeShiftMockSession)
        # Valid time shift
        host.path.set_mtime(time.time() + 3630)
        host.synchronize_times()
        self.assertEqual(host.time_shift(), 3600)
        # Invalid time shift
        host.path.set_mtime(time.time() + 3600+10*60)
        self.assertRaises(ftputil.error.TimeShiftError, host.synchronize_times)

    def test_synchronize_times_for_server_in_east(self):
        """Test for timestamp correction (see ticket #55)."""
        host = test_base.ftp_host_factory(ftp_host_class=TimeShiftFTPHost,
                                          session_factory=TimeShiftMockSession)
        # Set this explicitly to emphasize the problem.
        host.set_time_shift(0.0)
        hour = 60 * 60
        # This could be any negative time shift.
        presumed_time_shift = -6 * hour
        # Set `mtime` to simulate a server east of us.
        # In case the `time_shift` value for this host instance is 0.0
        # (as is to be expected before the time shift is determined),
        # the directory parser (more specifically
        # `ftputil.stat.Parser.parse_unix_time`) will return a time which
        # is a year too far in the past. The `synchronize_times`
        # method needs to deal with this and add the year "back".
        # I don't think it's a bug in `parse_unix_time` because the
        # method should work once the time shift is set correctly.
        local_time = time.localtime()
        local_time_with_wrong_year = (local_time.tm_year-1,) + local_time[1:]
        presumed_server_time = \
          time.mktime(local_time_with_wrong_year) + presumed_time_shift
        host.path.set_mtime(presumed_server_time)
        host.synchronize_times()
        self.assertEqual(host.time_shift(), presumed_time_shift)


class TestAcceptEitherBytesOrUnicode(unittest.TestCase):

    def setUp(self):
        self.host = test_base.ftp_host_factory()

    def test_upload(self):
        """Test whether `upload` accepts either unicode or bytes."""
        pass

    def test_download(self):
        """Test whether `download` accepts either unicode or bytes."""
        pass

    def test_chdir(self):
        """Test whether `chdir` accepts either unicode or bytes."""
        self.host.chdir("/home/file_name_test/ö")
        self.host.chdir(ftputil.tool.as_bytes("/home/file_name_test/ö"))

    def test_mkdir(self):
        """Test whether `mkdir` accepts either unicode or bytes."""
        host = self.host
        # This directory exists already, but this shouldn't matter
        # for the test.
        host.mkdir("/home/file_name_test/ä")
        host.mkdir(ftputil.tool.as_bytes("/home/file_name_test/ä"))

    def test_makedirs(self):
        """Test whether `makedirs` accepts either unicode or bytes."""
        host = self.host
        host.makedirs("/home/file_name_test/ä")
        host.makedirs(ftputil.tool.as_bytes("/home/file_name_test/ä"))

    def test_rmdir(self):
        """Test whether `rmdir` accepts either unicode or bytes."""
        host = self.host
        empty_directory_as_required_by_rmdir = "/home/file_name_test/empty_ä"
        host.rmdir(empty_directory_as_required_by_rmdir)
        host.rmdir(ftputil.tool.as_bytes(empty_directory_as_required_by_rmdir))

    def test_remove(self):
        """Test whether `remove` accepts either unicode or bytes."""
        host = self.host
        host.remove("/home/file_name_test/ö")
        host.remove(ftputil.tool.as_bytes("/home/file_name_test/ö"))

    def test_rmtree(self):
        """Test whether `rmtree` accepts either unicode or bytes."""
        host = self.host
        empty_directory_as_required_by_rmtree = "/home/file_name_test/empty_ä"
        host.rmtree(empty_directory_as_required_by_rmtree)
        host.rmtree(ftputil.tool.as_bytes(
                      empty_directory_as_required_by_rmtree))

    def test_rename(self):
        """Test whether `rename` accepts either unicode or bytes."""
        # It's possible to mix argument types, as for `os.rename`.
        path_as_unicode = "/home/file_name_test/ä"
        path_as_bytes = ftputil.tool.as_bytes(path_as_unicode)
        paths = [path_as_unicode, path_as_bytes]
        for source_path, target_path in itertools.product(paths, paths):
            self.host.rename(source_path, target_path)

    def test_listdir(self):
        """Test whether `listdir` accepts either unicode or bytes."""
        host = self.host
        as_bytes = ftputil.tool.as_bytes
        host.chdir("/home/file_name_test")
        # Unicode
        items = host.listdir("ä")
        self.assertEqual(items, ["ö", "o"])
        #  Need explicit type check for Python 2
        for item in items:
            self.assertTrue(isinstance(item, ftputil.compat.unicode_type))
        # Bytes
        items = host.listdir(as_bytes("ä"))
        self.assertEqual(items, [as_bytes("ö"), as_bytes("o")])
        #  Need explicit type check for Python 2
        for item in items:
            self.assertTrue(isinstance(item, ftputil.compat.bytes_type))

    def test_lstat(self):
        """Test whether `lstat` accepts either unicode or bytes."""
        host = self.host
        host.lstat("/home/file_name_test/ä")
        host.lstat(ftputil.tool.as_bytes("/home/file_name_test/ä"))

    def test_stat(self):
        """Test whether `stat` accepts either unicode or bytes."""
        host = self.host
        host.stat("/home/file_name_test/ä")
        host.stat(ftputil.tool.as_bytes("/home/file_name_test/ä"))

    def test_walk(self):
        """Test whether `walk` accepts either unicode or bytes."""
        pass

    def test_chmod(self):
        """Test whether `chmod` accepts either unicode or bytes."""
        host = self.host
        # The `voidcmd` implementation in `MockSession` would raise an
        # exception for the `CHMOD` command.
        host._session.voidcmd = host._session._ignore_arguments
        host.chmod("/home/file_name_test/ä", 0o755)
        host.chmod(ftputil.tool.as_bytes("/home/file_name_test/ä"), 0o755)


if __name__ == '__main__':
    unittest.main()
    import __main__
    # unittest.main(__main__,
    #   "TestTimeShift.test_synchronize_times")