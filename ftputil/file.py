# Copyright (C) 2003-2013, Stefan Schwarzer <sschwarzer@sschwarzer.net>
# Copyright (C) 2008, Roger Demetrescu <roger.demetrescu@gmail.com>
# See the file LICENSE for licensing terms.

"""
ftputil.file - support for file-like objects on FTP servers
"""

from __future__ import unicode_literals

import io

import ftputil.compat
import ftputil.error


# This module shouldn't be used by clients of the ftputil library.
__all__ = []


class _FTPFile(object):
    """
    Represents a file-like object associated with an FTP host. File
    and socket are closed appropriately if the `close` method is
    called.
    """

    # Set timeout in seconds when closing file connections (see ticket #51).
    _close_timeout = 5

    def __init__(self, host):
        """Construct the file(-like) object."""
        self._host = host
        self._session = host._session
        # The file is still closed.
        self.closed = True
        self._conn = None
        self._fobj = None

    def _wrapped_file(self, fobj, is_readable=False, is_writable=False):
        """
        Return a new file-like object which wraps `fobj` and in
        addition has the `readable`, `readinto` and `writable` methods
        that `BufferedReader` or `BufferedWriter` require.
        """
        # The `socket.makefile` return value under Python 3 already
        # has all the required attributes.
        if ftputil.compat.python_version == 3:
            return fobj
        # I tried to assign the missing methods as bound methods
        # directly to `fobj`, but this seemingly isn't possible with
        # the file object returned from `socket.makefile`.
        class Wrapper(io.RawIOBase):
            def __init__(self, fobj):
                super(Wrapper, self).__setattr__("_fobj", fobj)
            def readable(self):
                return is_readable
            def writable(self):
                return is_writable
            def readinto(self, bytearray_):
                data = self._fobj.read(len(bytearray_))
                bytearray_[:len(data)] = data
                return len(data)
            def __getattr__(self, name):
                return getattr(self._fobj, name)
            def __setattr__(self, name, value):
                if name == "__IOBase_closed":
                    # Delegate to this (`RawIOBase`) instance.
                    return super(Wrapper, self).__setattr__(name, value)
                else:
                    return setattr(self._fobj, name, value)
        return Wrapper(fobj)

    def _open(self, path, mode, buffering=None, encoding=None, errors=None,
              newline=None):
        """
        Open the remote file with given path name and mode.

        Contrary to the `open` builtin, this method returns `None`,
        instead this file object is modified in-place.
        """
        # Python 3.x's `socket.makefile` supports the same interface
        # as the new `open` builtin, but Python 2.x supports a mode,
        # but neither buffering nor encoding/decoding. Therefore, to
        # make the code work on Python 2.x and 3.x, create an
        # unbuffered binary file and wrap it.
        #
        # Check mode.
        if "a" in mode:
            raise ftputil.error.FTPIOError("append mode not supported")
        if mode not in ("r", "rb", "rt", "w", "wb", "wt"):
            raise ftputil.error.FTPIOError("invalid mode '{0}'".format(mode))
        if "b" in mode and "t" in mode:
            # Raise a `ValueError` like Python would.
            raise ValueError("can't have text and binary mode at once")
        # Convenience variables
        is_bin_mode = "b" in mode
        is_read_mode = "r" in mode
        # Always use binary mode (see above).
        transfer_type = "I"
        command = 'TYPE {0}'.format(transfer_type)
        with ftputil.error.ftplib_error_to_ftp_io_error:
            self._session.voidcmd(command)
        # Make transfer command.
        command_type = ('STOR', 'RETR')[is_read_mode]
        command = '{0} {1}'.format(command_type, path)
        # Force to binary regardless of transfer type (see above).
        makefile_mode = mode
        if "t" in mode:
            makefile_mode = makefile_mode.replace("t", "")
        if not "b" in makefile_mode:
            makefile_mode += "b"
        # Get connection and file object.
        with ftputil.error.ftplib_error_to_ftp_io_error:
            self._conn = self._session.transfercmd(command)
        # The actual file object.
        fobj = self._conn.makefile(makefile_mode)
        if is_read_mode:
            # See implementation of `_wrapped_file`.
            fobj = self._wrapped_file(fobj, is_readable=True)
            fobj = io.BufferedReader(fobj)
        else:
            # See implementation of `_wrapped_file`.
            fobj = self._wrapped_file(fobj, is_writable=True)
            fobj = io.BufferedWriter(fobj)
        if not is_bin_mode:
            fobj = io.TextIOWrapper(fobj, encoding=encoding,
                                        errors=errors, newline=newline)
        self._fobj = fobj
        # This comes last so that `close` won't try to close `_FTPFile`
        # objects without `_conn` and `_fo` attributes in case of an error.
        self.closed = False

    def __iter__(self):
        """Return a file iterator."""
        return self

    def __next__(self):
        """
        Return the next line or raise `StopIteration`, if there are
        no more.
        """
        # Apply implicit line ending conversion.
        line = self.readline()
        if line:
            return line
        else:
            raise StopIteration

    # Although Python 2.6+ has the `next` builtin function already, it
    # still requires iterators to have a `next` method.
    next = __next__

    #
    # Context manager methods
    #
    def __enter__(self):
        # Return `self`, so it can be accessed as the variable
        # component of the `with` statement.
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # We don't need the `exc_*` arguments here
        # pylint: disable=W0613
        self.close()
        # Be explicit
        return False

    #
    # Other attributes
    #
    def __getattr__(self, attr_name):
        """
        Handle requests for attributes unknown to `_FTPFile` objects:
        delegate the requests to the contained file object.
        """
        if attr_name in ("encoding flush isatty fileno read readline "
                         "readlines seek tell truncate name softspace "
                         "write writelines".split()):
            return getattr(self._fobj, attr_name)
        raise AttributeError(
              "'FTPFile' object has no attribute '{0}'".format(attr_name))

    # TODO: Implement `__dir__`? (See
    # http://docs.python.org/py3k/whatsnew/2.6.html#other-language-changes )

    def close(self):
        """Close the `FTPFile`."""
        if self.closed:
            return
        # Timeout value to restore, see below.
        # Statement works only before the try/finally statement,
        # otherwise Python raises an `UnboundLocalError`.
        old_timeout = self._session.sock.gettimeout()
        try:
            self._fobj.close()
            self._fobj = None
            with ftputil.error.ftplib_error_to_ftp_io_error:
                self._conn.close()
            # Set a timeout to prevent waiting until server timeout
            # if we have a server blocking here like in ticket #51.
            self._session.sock.settimeout(self._close_timeout)
            try:
                with ftputil.error.ftplib_error_to_ftp_io_error:
                    self._session.voidresp()
            except ftputil.error.FTPIOError as exc:
                # Ignore some errors, see tickets #51 and #17 at
                # http://ftputil.sschwarzer.net/trac/ticket/51 and
                # http://ftputil.sschwarzer.net/trac/ticket/17,
                # respectively.
                exc = str(exc)
                error_code = exc[:3]
                if exc.splitlines()[0] != "timed out" and \
                  error_code not in ("150", "426", "450", "451"):
                    raise
        finally:
            # Restore timeout for socket of `_FTPFile`'s `ftplib.FTP`
            # object in case the connection is reused later.
            self._session.sock.settimeout(old_timeout)
            # If something went wrong before, the file is probably
            # defunct and subsequent calls to `close` won't help
            # either, so we consider the file closed for practical
            # purposes.
            self.closed = True
