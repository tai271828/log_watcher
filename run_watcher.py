#!/usr/bin/env python3
"""
Real-time log files watcher supporting log rotation.
Works with Python >= 2.6 and >= 3.2, on both POSIX and Windows.

This code is based on Giampaolo Rodola' <g.rodola [AT] gmail [DOT] com> 's code.

Author: Taihsiang Ho (tai271828)
License: MIT

"""


import sys
import os
import time
import errno
import stat
import re

FLAG_DETECTION_USB = False
FLAG_DETECTION_INSERT = False
FLAG_DETECTION_UHCI = False
FLAG_DETECTION_XHCI = False
FLAG_MOUNT_DEVICE_CANDIDATES = False
FLAG_MOUNT_PARTITION = False
#FLAG_WHILE_LOOP = True

class LogWatcher(object):
    """Looks for changes in all files of a directory.
    This is useful for watching log file changes in real-time.
    It also supports files rotation.

    Example:

    >>> def callback(filename, lines):
    ...     print(filename, lines)
    ...
    >>> lw = LogWatcher("/var/log/", callback)
    >>> lw.loop()
    """

    def __init__(self, folder, callback,
                       extensions=None , logfile=None,
                       tail_lines=0,
                       sizehint=1048576):
        """Arguments:

        (str) @folder:
            the folder to watch

        (callable) @callback:
            a function which is called every time one of the file being
            watched is updated;
            this is called with "filename" and "lines" arguments.

        (list) @extensions:
            only watch files with these extensions

        (list) @logfile:
            only watch this file. if this var exists, it will override extention list above.

        (int) @tail_lines:
            read last N lines from files being watched before starting

        (int) @sizehint: passed to file.readlines(), represents an
            approximation of the maximum number of bytes to read from
            a file on every ieration (as opposed to load the entire
            file in memory until EOF is reached). Defaults to 1MB.
        """
        self.folder = os.path.realpath(folder)
        self.extensions = extensions
        self.logfile = logfile
        self._files_map = {}
        self._callback = callback
        self._sizehint = sizehint
        assert os.path.isdir(self.folder), self.folder
        assert callable(callback), repr(callback)
        self.update_files()
        for id, file in self._files_map.items():
            file.seek(os.path.getsize(file.name))  # EOF
            if tail_lines:
                try:
                    lines = self.tail(file.name, tail_lines)
                except IOError as err:
                    if err.errno != errno.ENOENT:
                        raise
                else:
                    if lines:
                        self._callback(file.name, lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()

    def loop(self, interval=0.1, blocking=True):
        """Start a busy loop checking for file changes every *interval*
        seconds. If *blocking* is False make one loop then return.
        """
        # May be overridden in order to use pyinotify lib and block
        # until the directory being watched is updated.
        # Note that directly calling readlines() as we do is faster
        # than first checking file's last modification times.
        while True:
            self.update_files()
            for fid, file in list(self._files_map.items()):
                self.readlines(file)
            if not blocking:
                return
            time.sleep(interval)

    def log(self, line):
        """Log when a file is un/watched"""
        print(line)

    def listdir(self):
        """List directory and filter files by extension.
        You may want to override this to add extra logic or globbing
        support.
        """
        ls = os.listdir(self.folder)
        if self.extensions:
            ls = [x for x in ls if os.path.splitext(x)[1][1:] \
                                           in self.extensions]
        if self.logfile in ls:
            ls = [self.logfile]

        return ls

    @classmethod
    def open(cls, file):
        """Wrapper around open().
        By default files are opened in binary mode and readlines()
        will return bytes on both Python 2 and 3.
        This means callback() will deal with a list of bytes.
        Can be overridden in order to deal with unicode strings
        instead, like this:

          import codecs, locale
          return codecs.open(file, 'r', encoding=locale.getpreferredencoding(),
                             errors='ignore')
        """
        return open(file, 'rb')

    @classmethod
    def tail(cls, fname, window):
        """Read last N lines from file fname."""
        if window <= 0:
            raise ValueError('invalid window value %r' % window)
        with cls.open(fname) as f:
            BUFSIZ = 1024
            # True if open() was overridden and file was opened in text
            # mode. In that case readlines() will return unicode strings
            # instead of bytes.
            encoded = getattr(f, 'encoding', False)
            CR = '\n' if encoded else b'\n'
            data = '' if encoded else b''
            f.seek(0, os.SEEK_END)
            fsize = f.tell()
            block = -1
            exit = False
            while not exit:
                step = (block * BUFSIZ)
                if abs(step) >= fsize:
                    f.seek(0)
                    newdata = f.read(BUFSIZ - (abs(step) - fsize))
                    exit = True
                else:
                    f.seek(step, os.SEEK_END)
                    newdata = f.read(BUFSIZ)
                data = newdata + data
                if data.count(CR) >= window:
                    break
                else:
                    block -= 1
            return data.splitlines()[-window:]

    def update_files(self):
        ls = []
        for name in self.listdir():
            absname = os.path.realpath(os.path.join(self.folder, name))
            try:
                st = os.stat(absname)
            except EnvironmentError as err:
                if err.errno != errno.ENOENT:
                    raise
            else:
                if not stat.S_ISREG(st.st_mode):
                    continue
                fid = self.get_file_id(st)
                ls.append((fid, absname))

        # check existent files
        for fid, file in list(self._files_map.items()):
            try:
                st = os.stat(file.name)
            except EnvironmentError as err:
                if err.errno == errno.ENOENT:
                    self.unwatch(file, fid)
                else:
                    raise
            else:
                if fid != self.get_file_id(st):
                    # same name but different file (rotation); reload it.
                    self.unwatch(file, fid)
                    self.watch(file.name)

        # add new ones
        for fid, fname in ls:
            if fid not in self._files_map:
                self.watch(fname)

    def readlines(self, file):
        """Read file lines since last access until EOF is reached and
        invoke callback.
        """
        while True:
            lines = file.readlines(self._sizehint)
            if not lines:
                break
            self._callback(file.name, lines)

    def watch(self, fname):
        try:
            file = self.open(fname)
            fid = self.get_file_id(os.stat(fname))
        except EnvironmentError as err:
            if err.errno != errno.ENOENT:
                raise
        else:
            self.log("watching logfile %s" % fname)
            self._files_map[fid] = file

    def unwatch(self, file, fid):
        # File no longer exists. If it has been renamed try to read it
        # for the last time in case we're dealing with a rotating log
        # file.
        self.log("un-watching logfile %s" % file.name)
        del self._files_map[fid]
        with file:
            lines = self.readlines(file)
            if lines:
                self._callback(file.name, lines)

    @staticmethod
    def get_file_id(st):
        if os.name == 'posix':
            return "%xg%x" % (st.st_dev, st.st_ino)
        else:
            return "%f" % st.st_ctime

    def close(self):
        for id, file in self._files_map.items():
            file.close()
        self._files_map.clear()

######################################################
# run the log watcher
######################################################

def callback(filename, lines):
    global FLAG_DETECTION_USB, FLAG_DETECTION_INSERT
    global FLAG_DETECTION_UHCI, FLAG_DETECTION_XHCI
    global FLAG_MOUNT_PARTITION
    global FLAG_WHILE_LOOP
    for line in lines:
        line_str = str(line)
        if detect_str(line_str, 'USB'): FLAG_DETECTION_USB = True
        if detect_str(line_str, 'uhci'): FLAG_DETECTION_UHCI = True
        if detect_str(line_str, 'xhci'): FLAG_DETECTION_XHCI = True
        if detect_str(line_str, 'USB Mass Storage device detected'): FLAG_DETECTION_INSERT = True
        FLAG_MOUNT_DEVICE_CANDIDIATES = detect_partition(line_str)
        if FLAG_MOUNT_DEVICE_CANDIDIATES and len(FLAG_MOUNT_DEVICE_CANDIDIATES) == 2:
            # hard code because I expect
            # FLAG_MOUNT_DEVICE_CANDIDIATES is something like ['sdb', ' sdb1']
            # This should be smarter if the device has multiple partitions.
            FLAG_MOUNT_PARTITION = FLAG_MOUNT_DEVICE_CANDIDIATES[1].strip()
    if FLAG_DETECTION_USB and FLAG_DETECTION_INSERT and FLAG_MOUNT_PARTITION:
        if FLAG_DETECTION_UHCI:
            print("An USB mass storage was inserted in a uhci controller")
            print(usable partition: FLAG_MOUNT_PARTITION)
            # stop the watcher loop
            #FLAG_WHILE_LOOP = False
            sys.exit()
        if FLAG_DETECTION_XHCI:
            print("An USB mass storage was inserted in a xhci controller")
            print(usable partition: FLAG_MOUNT_PARTITION)
            # stop the watcher loop
            #FLAG_WHILE_LOOP = False
            sys.exit()

def detect_str(line, str_2_detect):
    if str_2_detect in line:
        return True
    return False

def detect_partition(line):
    """ Arguments:

    (str) @line:
        line string from log file

    return a list denoting [device, partition1, partition2 ...]
    from syslog

    """
    # looking for string like
    # sdb: sdb1
    pattern = "sd.+sd.+"
    match = re.search(pattern, line)
    if match:
        # remove the trailing \n and quote
        match_string = match.group()[:-3]
        # will looks like
        # ['sdb', ' sdb1']
        match_list = match_string.split(":")
        return match_list

def write_usb_info():
    """
    write the info we got in this script to $PLAINBOX_SESSION_SHARE
    so the other jobs, e.g. read/write test, could know more information,
    for example the partition it want to try to mount.
    """



watcher = LogWatcher("/var/log", callback, logfile="syslog")

#while FLAG_WHILE_LOOP:
watcher.loop()
