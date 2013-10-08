#! /bin/sh
#
# mksingle.sh: Creates a single-file script for pdfsizeopt.
# by pts@fazekas.hu at Tue Oct  8 13:49:31 CEST 2013
#

set -ex
rm -f pdfsizeopt.zip lib/__main__.py lib/mainrun.py

# In dash-0.5.5.1 as /bin/sh, \n is converted to a newline in single quotes, even
# if we do it the tricy way, so we just use chr(10) instead.
echo "import sys

if not ((2, 4) <= sys.version_info[:2] < (3, 0)):
  sys.stderr.write(
      'fatal: Python version 2.4, 2.5, 2.6 or 2.7 needed for: %s%c' % (sys.path[0], 10))
  sys.exit(1)

from pdfsizeopt import main
main.zip_file = sys.path[0]
sys.exit(main.main(sys.argv))" >lib/mainrun.py
# We need a file other than __main__.py, because 'import __main__' below
# doesn't load __main__.py.
# TODO(pts): Can we use `-m mainrun'? Does it work in Python 2.0, 2.1, 2.2
# and 2.3? (So that we'd reach the proper error message.)
echo 'import mainrun' >lib/__main__.py

(cd lib && zip -9r ../pdfsizeopt.zip \
    __main__.py mainrun.py \
    pdfsizeopt/__init__.py \
    pdfsizeopt/main.py \
    pdfsizeopt/pdfsizeopt_argparse.py\
 ;) || exit "$?"
test -f pdfsizeopt.zip
( echo '#! /bin/sh
#
# pdfsizeopt: PDF file size optimizer (single-file script for Unix)
#
# You need Python 2.4, 2.5, 2.6 or 2.7 to run this script. The shell script
# below tries to find such an interpreter and then runs it.
#
# If you have Python 2.6 or Python 2.7, you can also run it directly with
# Python, otherwise you have to run it as a shell script.
#

type python2.7 >/dev/null 2>&1 && exec python2.7 -- "$0" ${1+"$@"}
type python2.6 >/dev/null 2>&1 && exec python2.6 -- "$0" ${1+"$@"}
type python2.5 >/dev/null 2>&1 && PYTHONPATH="$0:$PYTHONPATH" exec python2.5 -c '\''import sys; del sys.path[0]; import mainrun'\'' ${1+"$@"}
type python2.4 >/dev/null 2>&1 && PYTHONPATH="$0:$PYTHONPATH" exec python2.4 -c '\''import sys; del sys.path[0]; import mainrun'\'' ${1+"$@"}
PYTHONPATH="$0:$PYTHONPATH" exec python -c '\''import sys; del sys.path[0]; import mainrun'\'' ${1+"$@"}
exit 1
' && cat pdfsizeopt.zip
) >pdfsizeopt.single || exit "$?"
chmod 755 pdfsizeopt.single
rm -f pdfsizeopt.zip lib/__main__.py lib/mainrun.py
ls -l pdfsizeopt.single

: mksingle.sh OK
