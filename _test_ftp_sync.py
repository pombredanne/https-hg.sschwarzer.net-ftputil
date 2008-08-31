# Copyright (C) 2007, Stefan Schwarzer
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# - Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
# - Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#
# - Neither the name of the above author nor the names of the
#   contributors to the software may be used to endorse or promote
#   products derived from this software without specific prior written
#   permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# $Id$

import os
import shutil
import sys
import unittest

TEST_ROOT = "/home/schwa/sd/python/ftputil"
sys.path.insert(0, os.path.dirname(TEST_ROOT))

from ftputil import ftp_sync


class TestLocalToLocal(unittest.TestCase):
    def setUp(self):
        target_dir = os.path.join(TEST_ROOT, "test_target")
        shutil.rmtree(target_dir)
        os.mkdir(target_dir)

    def test_sync_empty_dir(self):
        source = ftp_sync.LocalHost()
        target = ftp_sync.LocalHost()
        syncer = ftp_sync.Syncer(source, target)
        source_dir = os.path.join(TEST_ROOT, "test_empty")
        target_dir = os.path.join(TEST_ROOT, "test_target")
        syncer.sync(source_dir, target_dir)


if __name__ == '__main__':
    unittest.main()
