#!/bin/sh

""":" # pdfsizeopt: PDF file size optimizer

P="$(readlink "$0" 2>/dev/null)"
test "$P" && test "${P#/}" = "$P" && P="${0%/*}/$P"
test "$P" || P="$0"
Q="${P%/*}"/pdfsizeopt_libexec/python
test -f "$Q" && exec "$Q" -E -- "$P" ${1+"$@"}
type -p python2.7 >/dev/null 2>&1 && exec python2.7 -- "$P" ${1+"$@"}
type -p python2.6 >/dev/null 2>&1 && exec python2.6 -- "$P" ${1+"$@"}
type -p python2.5 >/dev/null 2>&1 && exec python2.5 -- "$P" ${1+"$@"}
type -p python2.4 >/dev/null 2>&1 && exec python2.4 -- "$P" ${1+"$@"}
exec python -- "$P" ${1+"$@"}; exit 1

This is a Python 2.x script, it works with Python 2.4, 2.5, 2.6 and 2.7. It
doesn't work with Python 3.x. Feel free to replace the #! line with
`#! /usr/bin/python', `#! /usr/bin/env python' or whatever suits you best.
"""

import os
import os.path
import sys

if not ((2, 4) <= sys.version_info[:2] < (3, 0)):
  sys.stderr.write(
      'fatal: Python version 2.4, 2.5, 2.6 or 2.7 needed for: %s\n' % __file__)
  sys.exit(1)

script_dir = os.path.dirname(__file__)
try:
  __file__ = os.path.join(script_dir, os.readlink(__file__))
  script_dir = os.path.dirname(__file__)
except (OSError, AttributeError, NotImplementedError):
  pass
if os.path.isfile(os.path.join(
    script_dir, 'lib', 'pdfsizeopt', 'main.py')):
  sys.path[0] = os.path.join(script_dir, 'lib')

from pdfsizeopt import main
sys.exit(main.main(sys.argv, script_dir=script_dir))
