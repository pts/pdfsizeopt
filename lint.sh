#! /bin/sh
# by pts@fazekas.hu at Tue Oct  8 14:51:23 CEST 2013

PYTHON_FILES="$(find pdfsizeopt_test.py lib extra -name '*.py' |
    grep -v '^lib/pdfsizeopt/pdfsizeopt_argparse[.]py$')"
if ! test "$PYTHON_FILES"; then
  echo "No Python source files found." >&2
  exit 2
fi
#echo "$PYTHON_FILES"
pep8 $PYTHON_FILES | grep -vE '[0-9]: E(111|203) ' | tee pep8.out || :
if test -s pep8.out; then
  echo "Found pep8 warnings, see above." >&2
  exit 2
fi
echo "No lint warnings." >&2
