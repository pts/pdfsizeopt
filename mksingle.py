#! /usr/bin/python
# by pts@fazekas.hu at Fri Sep  1 16:34:46 CEST 2017

"""Build single-file script for Unix: pdfsizeopt.single."""

import cStringIO
import os
import os.path
import re
import subprocess
import sys
import time
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
      if pt in _NAME_OR_NUMBER and (tt in _NAME_OR_NUMBER or
          (tt == _STRING and ts[0] in 'rb')):
        output_func(' ')
      output_func(ts)
      pt, ps, is_empty_indent = tt, ts, 0
  if is_empty_indent:
    output_func(' ' * i)
    output_func('pass\n')


# We could support \r and \t outside strings, Minify would remove them.
UNSUPPORTED_CHARS_RE = re.compile(r'[^\na -~]+')


def MinifyFile(file_name, code_orig):
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
  compile(code_orig, file_name, 'exec')  # Check for syntax errors.
  output = []
  Minify(code_orig, output.append)
  code_mini = ''.join(output)
  compile(code_mini, file_name, 'exec')  # Check for syntax errors.
  return code_mini

# It's OK that this doesn't support the full PostScript syntax, it's enough to
# support whatever PostScript procsets in pdfsizeopt have.
#
# This doesn't support string literals with unescaped nested parens, e.g.
# '(())'.
#
# This doesn't support <0a> hex string literals or ASCII85 string literals.
POSTSCRIPT_TOKEN_RE = re.compile(
    r'%[^\r\n]*|'  # Comment.
    r'[\0\t\n\r\f ]+|' # Whitespace.
    r'(\((?:[^()\\]+|(?s)\\.)*\))|'  # 1: String literal.
    r'(<<|>>|[{}\[\]])|'  # 2: Token which stops the previous token.
    r'([^\0\t\n\r\f %(){}<>\[\]]+)|'  # 3. Multi-character token, '/' included.
    r'(?s)(.)')  # 4. Anything else we don't recognize.


def MinifyPostScript(pscode):
  output = [' ']  # Sentinel for output[-1][-1].
  for match in POSTSCRIPT_TOKEN_RE.finditer(pscode):
    if match.group(1):
      output.append(match.group(1))
    elif match.group(2):
      output.append(match.group(2))
    elif match.group(3):
      t = match.group(3)
      if t[0] != '/' and output[-1][-1] not in ')<>{}[]':
        output.append(' ')
      output.append(t)
    elif match.group(4):
      i = match.start()
      raise ValueError('Unknown PostScript syntax: %r' % pscode[i : i + 20])
  output[0] = ''  # Remove sentinel.
  return ''.join(output)


def MinifyPostScriptProcsets(file_name, code_orig):
  code_obj = compile(code_orig, file_name, 'exec')
  globals_dict = {}
  exec code_obj in globals_dict
  for name in sorted(globals_dict):
    if name.startswith('__'):
      del globals_dict[name]
  names, pscodes = [], []
  for name, pscode in sorted(globals_dict.iteritems()):
    names.append(name)
    if not isinstance(pscode, str):
      raise ValueError('Expected pscode as str, got: %r' % type(pscode))
    pscode = MinifyPostScript(pscode)
    if '%%' in pscode:
      raise ValueError('Unexpected %% in minified pscode.')
    pscodes.append(pscode)
  if not pscodes:
    return ''
  pscodes_str = '\n%%'.join(pscodes)
  assert "'''" not in pscodes_str
  return "%s=r'''%s\n'''.split('%%%%')" % (','.join(names), pscodes_str)


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

P="$(readlink "$0" 2>/dev/null)"
test "$P" && test "${P#/}" = "$P" && P="${0%/*}/$P"
test "$P" || P="$0"
Q="${P%/*}"/pdfsizeopt_libexec/python
test -f "$Q" && exec "$Q" -E -- "$P" ${1+"$@"}
type python2.7 >/dev/null 2>&1 && exec python2.7 -- "$P" ${1+"$@"}
type python2.6 >/dev/null 2>&1 && exec python2.6 -- "$P" ${1+"$@"}
type python2.5 >/dev/null 2>&1 && exec python2.5 -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$P" ${1+"$@"}
type python2.4 >/dev/null 2>&1 && exec python2.4 -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$P" ${1+"$@"}
exec python -c"import sys;del sys.argv[0];sys.path[0]=sys.argv[0];import m" "$P" ${1+"$@"}
exit 1

'''

def new_zipinfo(file_name, file_mtime, permission_bits=0644):
  zipinfo = zipfile.ZipInfo(file_name, file_mtime)
  zipinfo.external_attr = (0100000 | (permission_bits & 07777)) << 16
  return zipinfo


def main(argv):
  os.chdir(os.path.dirname(__file__))
  assert os.path.isfile('lib/pdfsizeopt/main.py')
  zip_output_file_name = 't.zip'
  single_output_file_name = 'pdfsizeopt.single'
  try:
    os.remove(zip_output_file_name)
  except OSError:
    pass

  zf = zipfile.ZipFile(zip_output_file_name, 'w', zipfile.ZIP_DEFLATED)
  time_now = time.localtime()[:6]
  try:
    for file_name in (
        # 'pdfsizeopt/pdfsizeopt_pargparse.py',  # Not needed.
        'pdfsizeopt/__init__.py',
        'pdfsizeopt/cff.py',
        'pdfsizeopt/float_util.py',
        'pdfsizeopt/main.py'):
      code_orig = open('lib/' + file_name, 'rb').read()
      # The zip(1) command also uses localtime. The ZIP file format doesn't
      # store the time zone.
      file_mtime = time.localtime(os.stat('lib/' + file_name).st_mtime)[:6]
      code_mini = MinifyFile(file_name, code_orig)
      # Compression effort doesn't matter, we run advzip below anyway.
      zf.writestr(new_zipinfo(file_name, file_mtime), code_mini)
      del code_orig, code_mini  # Save memory.

    # TODO(pts): Can we use `-m m'? Does it work in Python 2.0, 2.1, 2.2 and
    # 2.3? (So that we'd reach the proper error message.)
    zf.writestr(new_zipinfo('m.py', time_now),
                MinifyFile('m.py', M_PY_CODE))

    zf.writestr(new_zipinfo('__main__.py', time_now),
                'import m')

    file_name = 'pdfsizeopt/psproc.py'
    code_orig = open('lib/' + file_name, 'rb').read()
    file_mtime = time.localtime(os.stat('lib/' + file_name).st_mtime)[:6]
    code_mini = MinifyPostScriptProcsets(file_name, code_orig)
    zf.writestr(new_zipinfo(file_name, file_mtime), code_mini)
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

  # Size reductions of pdfsizeopt.single:
  #
  # * 115100 bytes: mksingle.sh, before this script.
  # *  68591 bytes: Python minification, advzip, SCRIPT_PREFIX improvements.
  # *  63989 bytes: PostScript minification.
  print >>sys.stderr, 'info: created %s (%d bytes)' % (
      single_output_file_name, os.stat(single_output_file_name).st_size)

if __name__ == '__main__':
  sys.exit(main(sys.argv))
