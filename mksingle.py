#! /usr/bin/python
# by pts@fazekas.hu at Fri Sep  1 16:34:46 CEST 2017

"""Build single-file script for Unix: pdfsizeopt.single."""

import cStringIO
import os
import os.path
import re
import subprocess
import sys
import token
import tokenize
import zipfile


def Minify(source, output_func):
  """Minifies Python (2.4, 2.5, 2.6 or 2.7) source code.

  This function was tested and it works identically (consistently) in Python
  2.4, 2.5, 2.6 and 2.7.

  The output will end with a newline, unless empty.

  This function does this:

  * Removes comments.
  * Compresses indentation to 1 space at a time.
  * Removes empty lines and consecutive duplicate newlines.
  * Removes newlines within expressions.
  * Removes unnecessary whitespace within a line (e.g. '1 + 2' to '1+2').
  * Removes strings at the beginning of the expression (including docstring).
  * Removes even the first comment line with '-*- coding '... .

  This function doesn't do these:

  * Removing the final newline ('\\n').
  * Shortening the names of local variables.
  * Making string literals shorter by better escaping etc.
  * Compressing compound statements to 1 line, e.g.
    'if x:\\ny=5\\n' to 'if x:y=5\\n'.
  * Removing unnecessery parentheses, e.g. '1+(2*3)' to '1+2*3'.
  * Constant folding, e.g. '1+(2*3)' to '7'.
  * Concantenation of string literals, e.g. '"a"+"b"' to '"ab"', or
    '"a""b"' to '"ab"'.
  * Seprating expressions with ';' instead of newline + indent.
  * Any obfuscation.
  * Any general compression (such as Flate, LZMA, bzip2).

  Args:
    source: Python source code to minify. Can be str, buffer (or anything
      convertible to a buffer, e.g. bytearray), a readline method of a
      file-object or an iterable of line strs.
    output_func: Function which will be called with str arguments for each
      output piece.
  """
  if isinstance(source, unicode):
    raise TypeError
  try:
    buf = buffer(source)
  except TypeError:
    buf = None
  if buf is not None:
    import cStringIO
    # This also works, except it's different at the end of the partial line:
    # source = iter(line + '\n' for line in str(buf).splitlines()).next
    source = cStringIO.StringIO(buf).readline
  elif not callable(source):
    # Treat source as an iterable of lines. Add trailing '\n' if needed.
    source = iter(
        line + '\n' * (not line.endswith('\n')) for line in source).next

  _COMMENT, _NL = tokenize.COMMENT, tokenize.NL
  _NAME, _NUMBER, _STRING = token.NAME, token.NUMBER, token.STRING
  _NEWLINE, _INDENT, _DEDENT = token.NEWLINE, token.INDENT, token.DEDENT
  _COMMENT_OR_NL = (_COMMENT, _NL)
  _NAME_OR_NUMBER = (_NAME, _NUMBER)

  i = 0  # Indentation.
  is_at_bol = is_at_bof = 1  # Beginning of line and file.
  is_empty_indent = 0
  pt, ps = -1, ''  # Previous token.
  # There are small differences in tokenize.generate_tokens in Python
  # versions, but they don't affect us, so we don't care:
  # * In Python <=2.4, the final DEDENTs and ENDMARKER are not yielded.
  # * In Python <=2.5, the COMMENT ts contains the '\n', and a separate
  #   NL is not generated.
  for tt, ts, _, _, _ in tokenize.generate_tokens(source):
    if tt == _INDENT:
      i += 1
      is_empty_indent = 1
    elif tt == _DEDENT:
      if is_empty_indent:
        output_func(' ' * i)  # TODO(pts): Merge with previous line.
        output_func('pass\n')
        is_empty_indent = 0
      i -= 1
    elif tt == _NEWLINE:
      if not is_at_bol:
        output_func('\n')
      is_at_bol, pt, ps = 1, -1, ''
    elif (tt == _STRING and is_at_bol or  # Module-level docstring etc.
          tt in _COMMENT_OR_NL):
      pass
    else:
      if is_at_bol:
        output_func(' ' * i)
        is_at_bol = is_at_bof = 0
      if pt in _NAME_OR_NUMBER and tt in _NAME_OR_NUMBER:
        output_func(' ')
      output_func(ts)
      pt, ps, is_empty_indent = tt, ts, 0
  if is_empty_indent:
    output_func(' ' * i)
    output_func('pass\n')


# We could support \r and \t outside strings, Minify would remove them.
UNSUPPORTED_CHARS_RE = re.compile(r'[^\na -~]+')


def MinifyFile(filename, code_orig):
  i = code_orig.find('\n')
  if i >= 0:
    line1 = code_orig[:i]
    if '-*- coding: ' in line1:
      # We could support them by keeping this comment, but instead we opt
      # for fully ASCII Python input files.
      raise ValueError('-*- coding declarations not supported.')
  match = UNSUPPORTED_CHARS_RE.search(code_orig)
  if match:
    raise ValueError('Unsupported chars in source: %r' % match.group(0))
  compile(code_orig, filename, 'exec')  # Check for syntax errors.
  output = []
  Minify(code_orig, output.append)
  code_mini = ''.join(output)
  compile(code_mini, filename, 'exec')  # Check for syntax errors.
  return code_mini


# We need a file other than __main__.py, because 'import __main__' in
# SCRIPT_PREFIX is a no-op, and it doesn't load __main__.py.
M_PY_CODE = r'''
import sys

if not ((2, 4) <= sys.version_info[:2] < (3, 0)):
  sys.stderr.write(
      'fatal: Python version 2.4, 2.5, 2.6 or 2.7 needed for: %s\n' % sys.path[0])
  sys.exit(1)

from pdfsizeopt import main
sys.exit(main.main(sys.argv, zip_file=sys.path[0]))
'''.strip()


SCRIPT_PREFIX = r'''#!/bin/sh --
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
type python2.5 >/dev/null 2>&1 && exec python2.5 -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$0" ${1+"$@"}
type python2.4 >/dev/null 2>&1 && exec python2.4 -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$0" ${1+"$@"}
exec python -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$0" ${1+"$@"}
exit 1
'''

def main(argv):
  assert os.path.isfile('lib/pdfsizeopt/main.py')
  zip_output_file_name = 't.zip'
  single_output_file_name = 'pdfsizeopt.single'
  try:
    os.remove(zip_output_file_name)
  except OSError:
    pass

  # TODO(pts): Also minify PostScript code in main.py.

  zf = zipfile.ZipFile(zip_output_file_name, 'w', zipfile.ZIP_DEFLATED)
  try:
    for filename in (
        # 'pdfsizeopt/pdfsizeopt_pargparse.py',  # Not needed.
        'pdfsizeopt/__init__.py',
        'pdfsizeopt/cff.py',
        'pdfsizeopt/float_util.py',
        'pdfsizeopt/main.py'):
      code_orig = open('lib/' + filename, 'rb').read()
      code_mini = MinifyFile(filename, code_orig)
      # !! add ZipInfo with mtime
      # Compression effort doesn't matter, we run advzip below anyway.
      zf.writestr(filename, code_mini)
      del code_orig, code_mini  # Save memory.
    zf.writestr('m.py', MinifyFile('m.py', M_PY_CODE))
    # TODO(pts): Can we use `-m m'? Does it work in Python 2.0, 2.1, 2.2 and
    # 2.3? (So that we'd reach the proper error message.)
    zf.writestr('__main__.py', 'import m')
  finally:
    zf.close()

  subprocess.check_call(('advzip', '-qz4', '--', zip_output_file_name))

  f = open(zip_output_file_name, 'rb')
  try:
    data = f.read()
  finally:
    f.close()
  os.remove(zip_output_file_name)

  f = open(single_output_file_name, 'wb')
  try:
    f.write(SCRIPT_PREFIX)
    f.write(data)
  finally:
    f.close()

  os.chmod(single_output_file_name, 0755)

  # The first run of this script reduced the size of pdfsizeopt.single from
  # 115100 bytes to 68591 bytes.
  print >>sys.stderr, 'info: created %s (%d bytes)' % (
      single_output_file_name, os.stat(single_output_file_name).st_size)

if __name__ == '__main__':
  sys.exit(main(sys.argv))
