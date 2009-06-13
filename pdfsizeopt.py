#! /usr/bin/python2.4
#
# pdfsizeopt.py: do various PDF size optimizations
# by pts@fazekas.hu at Sun Mar 29 13:42:05 CEST 2009
#
# !! rename this file to get image conversion
# TODO(pts): Proper whitespace parsing (as in PDF)
# TODO(pts): re.compile anywhere

"""pdfsizeopt.py: Convert PDF to PDF to optimize its size.

  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

This Python script implements some techniques for making PDF files smaller.
It should be used together with pdflatex and tool.pdf.Compress to get a minimal
PDF. See also !!

This script is work in progress.

This scripts needs a Unix system, with Ghostscript and pdftops (from xpdf),
sam2p and pngout. Future versions may relax the system requirements.

This script doesn't optimize the cross reference table (using cross reference
streams in PDF1.5) or the serialization of objects it doesn't modify. Use
tool.pdf.Compress in Multilvaent.jar from http://multivalent.sf.net/ for that.
"""

__author__ = 'pts@fazekas.hu (Peter Szabo)'

__id__ = '$Id$'

import getopt
import os
import os.path
import re
import struct
import sys
import time
import zlib


class Error(Exception):
  """Comon base class for exceptions defined in this file."""


def ShellQuote(string):
  # TODO(pts): Make it work on non-Unix systems.
  string = str(string)
  if string and not re.search('[^-_.+,:/a-zA-Z0-9]', string):
    return string
  else:
    return "'%s'" % string.replace("'", "'\\''")


def ShellQuoteFileName(string):
  # TODO(pts): Make it work on non-Unix systems.
  if string.startswith('-') and len(string) > 1:
    string = './' + string
  return ShellQuote(string)


def FormatPercent(num, den):
  if den == 0:
    return '?%'
  return '%d%%' % int((num * 100 + (den / 2)) // den)


def EnsureRemoved(file_name):
  try:
    os.remove(file_name)
  except OSError:
    assert not os.path.exists(file_name)


class PdfTokenParseError(Error):
  """Raised if a string cannot be parsed to a PDF token sequence."""


class PdfTokenTruncated(Error):
  """Raised if a string is only a prefix of a PDF token sequence."""


class PdfTokenNotString(Error):
  """Raised if a PDF token sequence is not a single string."""


class PdfTokenNotSimplest(Error):
  """Raised if ParseSimplestDict cannot parse the PDF token sequence."""


class FormatUnsupported(Error):
  """Raised if a file/data to be loaded is valid, but not supported."""


class PdfXrefError(Error):
  """Raised if the PDF file doesn't contain a valid cross-reference table."""


class FontsNotMergeable(Error):
  """Raised if the specified fonts cannot be merged.

  Please not the `Parsable' and `Mergeable' are correct spellings.
  """

class FilterNotImplementedError(Error):
  """Raised if a stream filter is not implemented."""


class PdfObj(object):
  """Contents of a PDF object (head and stream data).

  PdfObj provides convenience methods Set and Get for manipulating PDF objects
  of type dict and stream.

  Attributes:
    _head: stripped string between `obj' and (`stream' or `endobj')
    _cache: ParseDict(self._head) or None.
    stream: stripped string between `stream' and `endstream', or None
  """
  __slots__ = ['_head', 'stream', '_cache']

  PDF_WHITESPACE_CHARS = '\0\t\n\r\f '
  """String containing all PDF whitespace characters."""

  PDF_STREAM_OR_ENDOBJ_RE_STR = (
      r'[\0\t\n\r\f )>\]](stream(?:\r\n|[\0\t\n\r\f ])|'
      r'endobj(?:[\0\t\n\r\f /]|\Z))')
  PDF_STREAM_OR_ENDOBJ_RE = re.compile(PDF_STREAM_OR_ENDOBJ_RE_STR)
  """Matches stream or endobj in a PDF obj."""

  REST_OF_R_RE = re.compile(
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+R(?=[\0\t\n\r\f /%<>\[\](])')
  """Matches the generation number and the 'R'."""

  LENGTH_OF_STREAM_RE = re.compile(
      r'/Length(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?=[\0\t\n\r\f /%(<>\[\]])(?:'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+R'
      r'(?=[\0\t\n\r\f /%(<>\[\]]))?')
  """Matches `/Length <x>' or `/Length <x> <y> R'."""

  def __init__(self, other, objs=None, file_ofs=0):
    """Initialize from other.

    If other is a PdfObj, copy everything. Otherwise, if other is a string,
    start parsing it from `X 0 obj' (ignoring the number) till endobj.

    This method is optimized, because it is called for each PDF object read.
    (Some PDF files have 100000 objects.) Most of the time we try a simple
    parser first (using a regexp), and if it cannot parse the object, then
    we revert to a generic, but slower parser.

    This method doesn't implement a validating PDF parser.

    Args:
      other: PdfObj or string (with full obj, stream, endstream, endobj +
        garbage) or None
      objs: A dictionary mapping obj numbers to existing PdfObj objects. These
        can be used for resolving `R's to build self.
    """
    self._cache = None
    if isinstance(other, PdfObj):
      self._head = other.head
      self.stream = other.stream
    elif isinstance(other, str):
      assert other, 'empty PDF obj to parse'
      match = re.match(
          r'(?s)\d+[\0\t\n\r\f ]+0[\0\t\n\r\f ]+obj\b[\0\t\n\r\f ]*', other)
      assert match
      skip_obj_number_idx = match.end()
      stream_start_idx = None

      # We do the simplest and fastest parsing approach first to find
      # endobj/endstream. This covers about 90% of the objs. Notable
      # exceptions are the /Producer, /CreationDate and /CharSet strings.
      match = self.PDF_STREAM_OR_ENDOBJ_RE.search(other)
      if not match:
        raise PdfTokenParseError(
            'endobj/stream not found from ofs=%s to ofs=%s' %
            (file_ofs, file_ofs + len(other)))
      head = other[skip_obj_number_idx : match.start(1)].rstrip(
          self.PDF_WHITESPACE_CHARS)
      if '%' in head or '(' in head:
        # Our simple parsing approach failed, maybe because we've found
        # the wrong (early) 'endobj' in e.g. '(endobj rest) endobj'.
        #
        # Now we do the little bit slower parsing approach, which can parse any valid PDF
        # obj. Please note that we still don't have to call RewriteParsable
        # on `other'.
        i = self.FindEndOfObj(other, skip_obj_number_idx, len(other))
        j = max(i - 16, 0)
        head_suffix = other[j : i]
        #print '\n%r from %r + %r' % (head_suffix, other[:i], other[i:])
        match = self.PDF_STREAM_OR_ENDOBJ_RE.search(head_suffix)
        if not match:
          raise PdfTokenParseError(
              'full endobj/stream not found from ofs=%s to ofs=%s' %
              (file_ofs, file_ofs + len(other)))
        if match.group(1).startswith('stream'):
          stream_start_idx = j + match.end(1)
        i = j + match.start(1)
        while other[i - 1] in self.PDF_WHITESPACE_CHARS:
          i -= 1
        head = other[skip_obj_number_idx : i]
      else:
        if match.group(1).startswith('stream'):
          stream_start_idx = match.end(1)

      self._head = head
      if stream_start_idx is None:
        self.stream = None
      else:  # has 'stream'
        if not head.startswith('<<') and head.endswith('>>'):
          raise PdfTokenParseError(
              'stream must have a dict head at ofs=%s' % file_ofs)
        scanner = self.LENGTH_OF_STREAM_RE.scanner(head)
        match = scanner.search()
        if not match:
          # We happlily accept the invalid PDF obj
          # `<</Foo[/Length 42]>>stream...endstream' above. This is OK, since
          # we don't implement a validating PDF parser.
          raise PdfTokenParseError(
              'stream /Length not found at ofs=%s' % file_ofs)
        if scanner.search():
          # Duplicate /Length found. We need a full parsing to figure out
          # which one we need.
          stream_length = self.Get('Length')
          if stream_length is None:
            raise PdfTokenParseError(
                'proper stream /Length not found at ofs=%s' % file_ofs)
          match = self.LENGTH_OF_STREAM_RE.match('/Length %s ' % stream_length)
          assert match
        if match.group(2) is None:
          stream_end_idx = stream_start_idx + int(match.group(1))
        else:
          # For testing: lme_v6.pdf
          if int(match.group(2)) != 0:
            raise NotImplementedError('generation refs not implemented')
          obj_num = int(match.group(1))
          if obj_num <= 0:
            raise PdfTokenParseError(
                'obj num %d >= 0 expected for indirect /Length at ofs=%s' %
                (obj_num, file_ofs))
          try:
            stream_length = int(objs[obj_num].head)
          except KeyError:
            raise PdfTokenParseError(
                'indirect /Length not found at ofs=%s' % file_ofs)
          except ValueError:
            raise PdfTokenParseError(
                'indirect /Length not an integer at ofs=%s' % file_ofs)
          stream_end_idx = stream_start_idx + stream_length
          # Inline the reference to /Length
          self._head = '%s/Length %d%s' % (
              self._head[:match.start(0)], stream_length,
              self._head[match.end(0):]) 
        endstream_str = other[stream_end_idx : stream_end_idx + 30]
        if not re.match(
            r'[\0\t\n\r\f ]*endstream[\0\t\n\r\f ]+endobj(?:[\s/]|\Z)',
            endstream_str):
          raise PdfTokenParseError(
            'expected endstream+endobj in %r at %s' %
            (endstream_str, file_ofs + stream_end_idx))
        self.stream = other[stream_start_idx : stream_end_idx]
    elif other is None:
      self._head = None
      self.stream = None
    else:
      raise TypeError

  def AppendTo(self, output, obj_num):
    """Append serialized self to output list, using obj_num."""
    # TODO(pts): Test this method.
    output.append('%s 0 obj\n' % int(obj_num))
    head = self.head.strip(self.PDF_WHITESPACE_CHARS)
    output.append(head)  # Implicit \s later .
    space = ' ' * int(head[-1] not in '>])}')
    if self.stream is not None:
      if self._cache:
        assert self.Get('Length') == len(self.stream)
      else:
        # Don't waste time on the proper check.
        assert '/Length' in head
      output.append('%sstream\n' % space)
      output.append(self.stream)
      # We don't need '\nendstream' after a non-compressed content stream,
      # 'Qendstream endobj' is perfectly fine (accepted by gs and xpdf).
      output.append('endstream endobj\n')
    else:
      output.append('%sendobj\n' % space)

  def __GetHead(self):
    if self._head is None and self._cache is not None:
      self._head = self.SerializeDict(self._cache)
    return self._head

  def __SetHead(self, head):
    if head != self._head:  # works for None as well
      self._head = head
      self._cache = None

  head = property(__GetHead, __SetHead)

  @property
  def size(self):
    # + 20 for obj...endobj, + 20 for the xref entry
    if self.stream is None:
      return len(self.head) + 40
    else:
      return len(self.head) + len(self.stream) + 52

  @classmethod
  def GetBadNumbersFixed(cls, data):
    if data == '.':
      return '0'
    # Just convert '.' to 0 in an array.
    # We don't convert `42.' to '42.0' here.
    return re.sub(
        r'([\0\t\n\r\f \[])[.](?=[\0\t\n\r\f \]])',
        lambda match: match.group(1) + '0', data)

  @classmethod
  def GetNumber(cls, data):
    """Return an int, log, float or None."""
    if isinstance(data, int) or isinstance(data, long):
      return int(data)
    elif isinstance(data, float):
      pass
    elif not isinstance(data, str):
      return None
    elif data == '.':
      return 0
    elif re.match(r'-?\d+[.]', data):
      data = float(data[:-1])
    else:
      try:
        if '.' in data:
          data = float(data)
        else:
          return int(data)
      except ValueError:
        return None
    if isinstance(data, float) and int(data) == data:
      return int(data)
    else:
      return data

  def Get(self, key, default=None):
    """Get value for key if self.head is a PDF dict.
    
    Use PdfData.Resolve(obj.Get(...)) to resolve indirect refs.
    TODO(pts): Implement PdfData.Resolve.
    
    Args:
      key: A PDF name literal without a slash, e.g. 'ColorSpace'
    Returns:
      An str, bool, int, long or None value, as returned by
      self.ParseSimpleValue, default, if key was not found.
    """
    if key.startswith('/'):
      raise TypeError('slash in the key= argument')
    if self._cache is None:
      assert self._head is not None
      assert self.head.startswith('<<') and self.head.endswith('>>'), (
          'expected a dict or stream obj')
      if ('/' + key) not in self._head:
        # Quick return False, without having to parse.
        # TODO(pts): Special casing for /Length, we don't want to parse that.
        return None
      self._cache = self.ParseDict(self._head)
    return self._cache.get(key, default)

  def Set(self, key, value, do_keep_null=False):
    """Set value to key or remove key if value is None.
    
    To set key to 'null', specify value='null' or value=None,
    do_keep_null=True.

    To remove key, specify value=None (and do_keep_null=False by default).
    """
    if key.startswith('/'):
      raise TypeError('slash in the key= argument')
    if value is None:
      if do_keep_null:
        value = 'null'
    elif value == 'null':
      pass
    elif isinstance(value, str):
      value = self.ParseSimpleValue(value)
    else:
      self.SerializeSimpleValue(value)  # just for the TypeError
    if self._cache is None:
      assert self._head is not None
      assert self.head.startswith('<<') and self.head.endswith('>>'), (
          'expected a dict or stream obj')
      self._cache = self.ParseDict(self._head)
    if value is None:
      if key in self._cache:
        del self._cache[key]
        self._head = None  # self.__GetHead will regenerate it.
    else:
      # It's good that we don't support isinstance(value, float), because
      # comparing NaNs would fail here.
      if self._cache.get(key) != value:
        self._cache[key] = value
        self._head = None  # self.__GetHead will regenerate it.

  PDF_SIMPLE_VALUE_RE = re.compile(
      r'(?s)[\0\t\n\r\f ]*('
      r'\[.*?\]|<<.*?>>|<[^>]*>|\(.*?\)|%[^\n\r]*|'
      r'/?[^\[\]()<>{}/\0\t\n\r\f %]+)')
  """Matches a single PDF token or comment in a simplistic way.

  For [...], <<...>> and (...) which contain nested delimiters, only a prefix
  of the token will be matched.  
  """

  PDF_SIMPLEST_KEY_VALUE_RE = re.compile(
      r'[\0\t\n\r\f ]*/([-+A-Za-z0-9_.]+)(?=[\0\t\n\r\f /\[(<])'
      r'[\0\t\n\r\f ]*('
      r'\d+[\0\t\n\r\f ]+\d+[\0\t\n\r\f ]+R|'
      r'\([^()\\]*\)|(?s)<(?!<).*?>|'
      r'\[[^%(\[\]]*\]|<<[^%(<>]*>>|/?[-+A-Za-z0-9_.]+)')
  """Matches a very simple PDF key--value pair, in a most simplistic way."""
  # TODO(pts): How to prevent backtracking if the regexp doesn't match?
  # TODO(pts): Replace \s with [\0...], because \0 is not in Python \s.

  PDF_WHITESPACE_AT_EOS_RE = re.compile(r'[\0\t\n\r\f ]*\Z')
  """Matches whitespace (0 or more) at end of string."""

  PDF_WHITESPACE_RE = re.compile(r'[\0\t\n\r\f ]+')
  """Matches whitespace (1 or more)."""

  PDF_WHITESPACE_OR_HEX_STRING_RE = re.compile(
      r'[\0\t\n\r\f ]+|(<<)|<(?!<)([^>]*)>')
  """Matches whitespace (1 or more) or a hex string constant or <<."""

  PDF_NAME_LITERAL_TO_EOS_RE = re.compile(r'/?[^\[\]{}()<>%\0\t\n\r\f ]+\Z')
  """Matches a PDF /name or name literal."""

  PDF_INVALID_NAME_CHAR_RE = re.compile(r'[^-+A-Za-z0-9_.]')
  """Matches a PDF data character which is not valid in a plain name."""

  PDF_NAME_HASHMARK_HEX_RE = re.compile(r'#([0-9a-f-A-F]{2})')
  """Matches a hashmark hex escape in a PDF name token."""

  PDF_INT_RE = re.compile(r'-?\d+\Z')
  """Matches a PDF integer token."""

  PDF_STRING_SPECIAL_CHAR_RE = re.compile(r'([()\\])')
  """Matches PDF string literal special chars ( ) \\ ."""

  PDF_HEX_STRING_LITERAL_RE = re.compile(r'<[\0\t\n\r\f 0-9a-fA-F]+>\Z')
  """Matches a PDF hex <...> string literal."""
  
  PDF_REF_AT_EOS_RE = re.compile(r'(\d+)[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+R\Z')
  """Matches a PDF indirect reference at end-of-string."""

  PDF_COMMENT_OR_STRING_RE = re.compile(
      r'%[^\r\n]*|\(([^()\\]*)\)|(\()')
  """Matches a comment, a string simple literal or a string literal opener."""

  PDF_FIND_END_OBJ_RE = re.compile(
      r'%[^\r\n]*|\([^()\\]*(?=\))|(\()|'
      + PDF_STREAM_OR_ENDOBJ_RE_STR)
  """Matches a substring interesting for FindEndOfObj."""

  PDF_CHAR_TO_HEX_ESCAPE_RE = re.compile(
      r'[^-+A-Za-z0-9_./#\[\]()<>{}\0\t\n\r\f ]')
  """Matches a single character which needs a hex escape."""

  PDF_CHAR_TO_HEX_KEEP_ESCAPED_RE = re.compile(
      r'[^-+A-Za-z0-9_.]')
  """Matches a single character which should be kept escaped."""

  PDF_COMMENT_RE = re.compile(r'%[^\r\n]*')
  """Matches a single comment line without a terminator."""

  PDF_HEX_CHAR_RE = re.compile('#([0-9a-fA-F]{2})')
  """Matches a character escaped as # + hex."""

  PDF_SIMPLE_REF_RE = re.compile(r'(\d+)[\0\t\n\r\f ]+0[\0\t\n\r\f ]+R\b')
  """Matches `<obj> 0 R', not allowing comments."""

  PDF_HEX_STRING_OR_DICT_RE = re.compile(r'<<|<(?!<)([^>]*)>')
  """Matches a hex string or <<."""

  PDF_SIMPLE_TOKEN_RE = re.compile(
      ' |(/?[^/{}\[\]()<>\0\t\n\r\f %]+)|<<|>>|[\[\]]|<([a-f0-9]*)>')
  """Matches a simple PDF token.
  
  PdfObj.CompressValue(data, do_emit_strings_as_hex=True emits) a string of
  simple tokens, possibly concatenated by a single space.
  """

  @classmethod
  def FindEndOfObj(cls, data, start=0, end=None, do_rewrite=True):
    """Find the right endobj/endstream from data[start : end].
    
    Args:
      data: PDF token sequence (with or without `<x> <y> obj' from `start').
      start: Offset to start parsing at.
      end: Offset to stop parsing at.
      do_rewrite: Bool indicating whether to call cls.ReweriteToParsable if
        needed.
    Returns:
      Index in data right after the right 'endobj\n' or 'stream\r\n' (any
      other whitespace is also OK).
    Raises:
      PdfTokenParseError: if `endobj' or `stream' was not found.
    """
    if end is None:
      end = len(data)
    scanner = cls.PDF_FIND_END_OBJ_RE.scanner(data, start, end)
    while True:
      match = scanner.search()
      if not match:
        raise PdfTokenParseError(
            'could not find endobj/stream in %r...' % data[: 256])
      if match.group(1):  # a (...) string we were not able to parse
        if not do_rewrite:
          raise PdfTokenNotSimplest
        end_ofs_out = []
        try:
          # Ignore return value (the parsable string).
          cls.RewriteToParsable(
              data=data, start=match.start(1), end_ofs_out=end_ofs_out)
        except PdfTokenTruncated, exc:
          raise PdfTokenParseError(
              'could not find end of string in %r: %s' %
              (data[match.start(1) : match.start(1) + 256], exc))
        # We subtract one below so we don't match ')', and we could match
        # ')endobj' later.
        scanner = cls.PDF_FIND_END_OBJ_RE.scanner(
            data, end_ofs_out[0] - 1, end)
      elif match.group(2):  # endobj or stream
        return match.end(2)

  @classmethod
  def ParseSimpleValue(cls, data):
    """Parse a simple (non-composite) PDF value (or keep it as a string).
    
    Args:
      data: String containing a PDF token to parse (no whitespace around it).
    Returns:
      Parsed value: True, False, None, an int (or long) or an str (for
      anything else).
    Raises:
      PdfTokenParseError:
    """
    if not isinstance(data, str):
      raise TypeError
    data = data.strip(cls.PDF_WHITESPACE_CHARS)
    if data in ('true', 'false'):
      return data == 'true'
    elif data == 'null':
      return None
    elif cls.PDF_INT_RE.match(data):
      return int(data)
    elif data.startswith('('):
      if not data.endswith(')'):
        raise PdfTokenParseError('bad string %r' % data)
      if cls.PDF_STRING_SPECIAL_CHAR_RE.scanner(
          data, 1, len(data) - 1).search():
        end_ofs_out = []
        data2 = cls.RewriteToParsable(data, end_ofs_out=end_ofs_out)
        if data[end_ofs_out[0]:].strip(cls.PDF_WHITESPACE_CHARS):
          raise PdfTokenParseError('bad string %r' % data)
        assert data2.startswith(' <') and data2.endswith('>')
        return data2[1:]
      else:
        return '<%s>' % data[1 : -1].encode('hex')
    elif data.startswith('<<'):
      if not data.endswith('>>'):
        raise PdfTokenParseError('unclosed dict in %r' % data)
      return data
    elif data.startswith('['):
      if not data.endswith(']'):
        raise PdfTokenParseError('unclosed array in %r' % data)
      return data
    elif data.startswith('<'):  # see also data.startswith('<<') above
      if not cls.PDF_HEX_STRING_LITERAL_RE.match(data):
        raise PdfTokenParseError('bad hex string %r' % data)
      data = cls.PDF_WHITESPACE_RE.sub('', data).lower()
      if (len(data) & 1) != 0:
        return data[:-1] + '0>'
      else:
        return data
    # Don't parse floats, we usually don't need them parsed.
    elif cls.PDF_NAME_LITERAL_TO_EOS_RE.match(data):
      return data
    elif data.endswith('R'):
      match = cls.PDF_REF_AT_EOS_RE.match(data)
      if match:
        return '%d %d R' % (int(match.group(1)), int(match.group(2))) 
      return data
    else:
      raise PdfTokenParseError('syntax error in %r' % data)

  @classmethod
  def ParseSimplestDict(cls, data):
    """Parse simplest PDF token sequence to a dict mapping strings to values.

    This method returns a PDF token sequence without comments (%).

    The simplest approach involves a regexp match over the PDF token sequence.
    This cannot parse e.g. nested arrays or strings inside arrays (but
    `[' inside a string is OK). PdfTokenNotSimplest gets raised in this case,
    and parsing should be retried with ParseDict.

    Parsing of dict values is not recursive (i.e. if the value is composite,
    it is left as is as a string).

    Please note that this method doesn't implement a validating parser: it
    happily accepts some invalid PDF constructs.

    For duplicate keys, only the last key--value pair is kept.

    Args:
      data: String containing a PDF token sequence for a dict, like '<<...>>'.
    Returns:
      A dict mapping strings to values (usually strings).
    Raises:
      PdfTokenNotSimplest: If `data' cannot be parsed with this simplest
        approach.
    """
    # TODO(pts): Measure what percentage can be parsed.
    assert data.startswith('<<')
    assert data.endswith('>>')
    start = 2
    end = len(data) - 2
    dict_obj = {}
    scanner = cls.PDF_SIMPLEST_KEY_VALUE_RE.scanner(data, start, end)
    while True:
      match = scanner.match()
      if not match: break
      start = match.end()
      dict_obj[match.group(1)] = cls.ParseSimpleValue(match.group(2))
    if not cls.PDF_WHITESPACE_AT_EOS_RE.scanner(data, start, end).match():
      raise PdfTokenNotSimplest(
          'not simplest at %d, got %r' % (start, data[start : start + 16]))
    return dict_obj

  @classmethod
  def ParseDict(cls, data):
    """Parse any PDF token sequence to a dict mapping strings to values.

    This method returns values without comments (%).

    Parsing of dict values is not recursive (i.e. if the value is composite,
    it is left as is as a string).

    Please note that this method doesn't implement a validating parser: it
    happily accepts some invalid PDF constructs.

    Please note that this method involves a ParseSimplestDict call, to parse
    the simplest PDF token sequences the fastest way possible.

    For duplicate keys, only the last key--value pair is kept.
    
    Whitespace is not stripped from the inner sides of [...] or <<...>>, to
    remain compatible with ParseSimplestDict.

    Args:
      data: String containing a PDF token sequence for a dict, like '<<...>>'.
        There must be no leading or trailing whitespace.
    Returns:
      A dict mapping strings to values (usually strings).
    Raises:
      PdfTokenParseError:
    """
    # TODO(pts): Integate this with Get(), Set() and output optimization
    assert data.startswith('<<')
    assert data.endswith('>>')
    start = 2
    end = len(data) - 2    

    dict_obj = {}
    scanner = cls.PDF_SIMPLEST_KEY_VALUE_RE.scanner(data, start, end)
    while True:
      match = scanner.match()
      if not match: break # Match the rest with PDF_SIMPLE_VALUE_RE.
      start = match.end()
      dict_obj[match.group(1)] = cls.ParseSimpleValue(match.group(2))

    if not cls.PDF_WHITESPACE_AT_EOS_RE.scanner(data, start, end).match():
      scanner = cls.PDF_SIMPLE_VALUE_RE.scanner(data, start, end)
      match = scanner.match()
      if not match or match.group(1)[0] != '/':
        # cls.PDF_SIMPLEST_KEY_VALUE_RE above matched only a prefix of a
        # token. Restart from the beginning to match everything properly.
        # TODO(pts): Cancel only the last key.
        dict_obj.clear()
        list_obj = cls._ParseArrayContents(data=data, start=2, end=end)
      else:
        list_obj = cls._ParseArrayContents(
            data=data, start=start, end=end, scanner=scanner, match=match)
      if 0 != (len(list_obj) & 1):
        raise PdfTokenParseError('odd item count in dict')
      for i in xrange(0, len(list_obj), 2):
        key = list_obj[i]
        if not isinstance(key, str) or not key.startswith('/'):
          # TODO(pts): Report the offset as well.
          raise PdfTokenParseError(
              'dict key expected, got %r... ' %
              (str(key)[0 : 16]))
        dict_obj[key[1:]] = list_obj[i + 1]

    return dict_obj    

  @classmethod
  def ParseArray(cls, data):
    """Parse any PDF array token sequence to a Python list.

    This method returns values without comments (%).

    Parsing of values is not recursive (i.e. if the value is composite,
    it is left as is as a string).

    Please note that this method doesn't implement a validating parser: it
    happily accepts some invalid PDF constructs.

    There is no corresponding super fast ParseSimplestArray call implemented,
    because parsing arrays is not a common operation.

    For duplicate keys, only the last key--value pair is kept.

    Whitespace is not stripped from the inner sides of [...] or <<...>>, to
    remain compatible with ParseSimplestDict.

    Args:
      data: String containing a PDF token sequence for a dict, like '<<...>>'.
        There must be no leading or trailing whitespace.
    Returns:
      A dict mapping strings to values (usually strings).
    Raises:
      PdfTokenParseError:
    """
    assert data.startswith('[')
    assert data.endswith(']')
    start = 1
    end = len(data) - 1
    return cls._ParseArrayContents(data, start, end)

  @classmethod
  def _ParseArrayContents(cls, data, start, end, scanner=None, match=None):
    """Helper method to scan token list in data[start : end]."""
    list_obj = []
    if scanner is None:
      scanner = cls.PDF_SIMPLE_VALUE_RE.scanner(data, start, end)
    if match is None:
      match = scanner.match()
    while match:
      start = match.end()
      value = match.group(1)
      kind = value[0]
      if kind == '%':
        if start >= end:
          raise PdfTokenParseError(
              'unterminated comment %r at %d' % (value, start))
        match = scanner.match()
        continue
      if kind == '/':
        # It's OK that we don't apply this normalization recursively to
        # [/?Foo] etc.
        if '#' in value:
          value = cls.PDF_NAME_HASHMARK_HEX_RE.sub(
              lambda match: chr(int(match.group(1), 16)), value)
          if '#' in value:
            raise PdfTokenParseError(
                'hex error in literal name %r at %d' %
                (value, match.start(1)))
        if cls.PDF_INVALID_NAME_CHAR_RE.search(value):
          value = '/' + cls.PDF_INVALID_NAME_CHAR_RE.sub(
              lambda match: '#%02X' % ord(match.group(0)), value[1:])
      elif kind == '(':
        if cls.PDF_STRING_SPECIAL_CHAR_RE.scanner(
            value, 1, len(value) - 1).search():
          # Parse the string in a slow way.
          end_ofs_out = []
          value1 = data[match.start(1):]  # Add more chars if needed.
          try:
            value2 = cls.RewriteToParsable(value1, end_ofs_out=end_ofs_out)
          except PdfTokenTruncated, exc:
            raise PdfTokenParseError(
                'truncated string literal at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          except PdfTokenParseError, exc:
            raise PdfTokenParseError(
                'bad string literal at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          assert value2.startswith(' <') and value2.endswith('>')
          value = value2[1:]
          start = match.start(1) + end_ofs_out[0]
          scanner = cls.PDF_SIMPLE_VALUE_RE.scanner(data, start, end)
          match = None
        else:
          value = cls.ParseSimpleValue(value)
      elif kind == '[':
        value1 = value[1 : -1]
        if '%' in value1 or '[' in value1 or '(' in value1:
          # !! TODO(pts): Implement a faster solution if no % or (
          end_ofs_out = []
          value1 = data[match.start(1):]  # Add more chars if needed.
          try:
            value2 = cls.RewriteToParsable(value1, end_ofs_out=end_ofs_out)
          except PdfTokenTruncated, exc:
            raise PdfTokenParseError(
                'truncated array at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          except PdfTokenParseError, exc:
            raise PdfTokenParseError(
                'bad array at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          assert value2.startswith(' [') and value2.endswith(']')
          start = match.start(1) + end_ofs_out[0]
          # If we had `value = value2[1:] instead of the following
          # assignment, we would get the clean, pre-parsed value.
          # But we don't want that because that would be inconsistent with
          # the ('[' in value) above.
          if '%' in value:
            value = cls.CompressValue(value2[1:])
          else:
            value = data[match.start(1) : start]
          scanner = cls.PDF_SIMPLE_VALUE_RE.scanner(data, start, end)
          match = None
      elif value.startswith('<<'):
        value1 = value[2 : -2]
        if '%' in value1 or '<' in value1 or '(' in value1:
          # !! TODO(pts): Implement a faster solution if no % or (
          end_ofs_out = []
          value1 = data[match.start(1):]  # Add more chars if needed.
          try:
            value2 = cls.RewriteToParsable(value1, end_ofs_out=end_ofs_out)
          except PdfTokenTruncated, exc:
            raise PdfTokenParseError(
                'truncated array at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          except PdfTokenParseError, exc:
            raise PdfTokenParseError(
                'bad array at %d, got %r...: %s' %
                (match.start(1), value1[0 : 16], exc))
          assert value2.startswith(' <<') and value2.endswith('>>')
          start = match.start(1) + end_ofs_out[0]
          if '%' in value:
            value = cls.CompressValue(value2[1:])
          else:
            value = data[match.start(1) : start]
          scanner = cls.PDF_SIMPLE_VALUE_RE.scanner(data, start, end)
          match = None
      elif kind == '<':  # '<<' is handled above
        value = cls.ParseSimpleValue(value)
      else:
        match0 = match
        if value.endswith('R'):
          match = cls.PDF_REF_AT_EOS_RE.match(value)
          if match:
            value = '%d %d R' % (int(match.group(1)), int(match.group(2)))
        else:
          match = None
        if not match:
          if cls.PDF_INVALID_NAME_CHAR_RE.search(value):
            raise PdfTokenParseError(
                'syntax error in non-literal name %r at %d' %
                (value, match0.start(1)))
          value = cls.ParseSimpleValue(value)
      if value == 'R':
        if (len(list_obj) < 2 or
            not isinstance(list_obj[-1], int) or list_obj[-1] < 0 or
            not isinstance(list_obj[-2], int) or list_obj[-2] <= 0):
          raise PdfTokenParseError(
              'bad indirect ref at %d, got %r after %r' %
              (start, data[start : start + 16], list_obj))
        list_obj[-2] = '%d %d R' % (list_obj[-2], list_obj[-1])
        list_obj.pop()
      else:
        list_obj.append(value)
      match = scanner.match()
    if not cls.PDF_WHITESPACE_AT_EOS_RE.scanner(data, start, end).match():
      # TODO(pts): Be more specific, e.g. if we get this in a truncated
      # string literal `(foo'.
      raise PdfTokenParseError(
          'parse error at %d, got %r' % (start, data[start : start + 16]))
    return list_obj

  @classmethod
  def GetReferenceTarget(cls, data):
    """Convert `5 0 R' to 5. Return None if data is not a reference."""
    # TODO(pts): Allow comments in `data'.
    match = cls.PDF_REF_AT_EOS_RE.match(data)
    if match and int(match.group(2)) == 0:
      return int(match.group(1))
    else:
      return None

  @classmethod
  def CompressValue(cls, data, obj_num_map=None, old_obj_nums_ret=None,
                    do_emit_strings_as_hex=False):
    """Return shorter representation of a PDF token sequence.

    This method doesn't optimize integer constants starting with 0.

    Args:
      data: A PDF token sequence.
      obj_num_map: Optional dictionary mapping ints to ints; or a nonempty
        string (to force a specific obj_num placeholder), or None. It instructs
        this method to change all occurrences of `<key> 0 R' to `<value> 0 R'
        in data.
      old_obj_nums_ret: Optional list to which this method will append
        num for all occurrences of `<num> 0 R' in data.
        TODO(pts): Write a simpler method which returns only this.
      do_emit_strings_as_hex: Boolean indicating whether to emit strings as
        hex <...>.
    Returns:
      The most compact PDF token sequence form of data: without superfluous
      whitespce; with '(' string literals. It may contain \n only in
      string literals.
    Raises:
      PdfTokenParseError
    """
    if '(' in data:
      output = []
      i = 0
      scanner = cls.PDF_COMMENT_OR_STRING_RE.scanner(data, 0, len(data))
      match = scanner.search()
      while match:
        if i < match.start():
          output.append(data[i : match.start()])
        i = match.end()
        if match.group(1) is not None:  # simple string literal
          output.append('<%s>' % match.group(1).encode('hex'))
        elif match.group(2):  # complicated string literal
          end_ofs_out = []
          try:
            # Ignore return value (the parsable string).
            output.append(cls.RewriteToParsable(
                data=data, start=match.start(), end_ofs_out=end_ofs_out))
          except PdfTokenTruncated, exc:
            raise PdfTokenParseError(
                'could not find end of string in %r: %s' %
                (data[match.start() : match.start() + 256], exc))
          i = end_ofs_out[0]
          scanner = cls.PDF_COMMENT_OR_STRING_RE.scanner(
              data, i, len(data))
        else:  # comment
          output.append(' ')
        match = scanner.search()
      output.append(data[i:])
      data = ''.join(output)
    else:
      data = cls.PDF_COMMENT_RE.sub(' ', data)

    def ReplacementHexEscape(match):
      char = chr(int(match.group(1), 16))
      if cls.PDF_CHAR_TO_HEX_KEEP_ESCAPED_RE.match(char):
        return match.group(0).upper()  # keep escaped
      else:
        return char

    data = cls.PDF_HEX_CHAR_RE.sub(ReplacementHexEscape, data)
    data = cls.PDF_CHAR_TO_HEX_ESCAPE_RE.sub(
        lambda match: '#%02X' % ord(match.group(0)), data)
    # TODO(pts): Optimize integer constants starting with 0.

    if obj_num_map:  # nonempty dict

      def ReplacementRef(match):
        obj_num = int(match.group(1))
        if old_obj_nums_ret is not None:
          old_obj_nums_ret.append(obj_num)
        if isinstance(obj_num_map, str):
          obj_num = obj_num_map
        else:
          obj_num = obj_num_map.get(obj_num, obj_num)
        if obj_num is None:
          return 'null'
        else:
          return '%s 0 R' % obj_num

      data = cls.PDF_SIMPLE_REF_RE.sub(ReplacementRef, data)
    elif old_obj_nums_ret is not None:
      for match in cls.PDF_SIMPLE_REF_RE.finditer(data):
        old_obj_nums_ret.append(int(match.group(1)))
    
    def ReplacementWhiteString(match):
      """Return replacement for whitespace or hex string `match'.

      This function assumes that match is in data.
      """
      if match.group(2) is not None:  # hex string
        s = cls.PDF_WHITESPACE_RE.sub('', match.group(2))
        if len(s) % 2 != 0:
          s += '0'
        try:
          s = s.decode('hex')
        except TypeError:
          raise PdfTokenParseError('invalid hex string %r' % s)
        if do_emit_strings_as_hex:
          return '<%s>' % s.encode('hex')
        else:
          return cls.EscapeString(s)
      elif match.group(1):  # '<<'
        return match.group(1)
      else:  # whitespace: remove unless needed
        if (match.start() == 0 or match.end() == len(data) or
            data[match.start() - 1] in '<>)[]{}' or 
            data[match.end()] in '/<>([]{}'):
          return ''
        else:
          return ' '

    return cls.PDF_WHITESPACE_OR_HEX_STRING_RE.sub(
        ReplacementWhiteString, data)

  @classmethod
  def SerializeSimpleValue(cls, value):
    if isinstance(value, str):
      if (value.startswith('(') or
          (value.startswith('<') and not value.startswith('<<'))):
        return cls.EscapeString(cls.ParseString(value))
      else:
        return value
    elif isinstance(value, bool):  # must be above int and long
      return str(value).lower()
    elif isinstance(value, int) or isinstance(value, long):
      return str(value)
    elif value is None:
      return 'null'
    # We deliberately don't serialize float because of precision and
    # representation issues (PDF doesn't support exponential notation).
    else:
      raise TypeError

  @classmethod
  def SerializeDict(cls, dict_obj):
    """Serialize a dict (such as in PdfObj.head) to a PDF dict string.

    Please note that this method doesn't normalize or optimize the dict values
    (it doesn't even remove leading and trailing whitespace). To get that, use
    cls.CompressValue(cls.RewriteToParsable(cls.SerializeDict(dict_obj))),
    of which cls.RewriteToParsable is slow.
    """
    output = ['<<']
    for key in sorted(dict_obj):
      output.append('/' + key)
      value = cls.SerializeSimpleValue(dict_obj[key])
      if value[0] not in '<({[/\0\t\n\r\f %':
        output.append(' ')
      output.append(value)
    output.append('>>')
    return ''.join(output)

  @classmethod
  def EscapeString(cls, data):
    """Escape a string to the shortest possible PDF string literal."""
    if not isinstance(data, str): raise TypeError
    # We never emit hex strings (e.g. <face>), because they cannot ever be
    # shorter than the literal binary string.
    no_open = '(' not in data
    no_close = ')' not in data
    if no_open or no_close:
      # No way to match parens.
      if no_open and no_close:
        return '(%s)' % data.replace('\\', '\\\\')
      else:
        return '(%s)' % cls.PDF_STRING_SPECIAL_CHAR_RE.sub(r'\\\1', data)
    else:
      close_remaining = 0
      for c in data:
        if c == ')': close_remaining += 1
      depth = 0
      output = ['(']
      i = j = 0
      while j < len(data):
        c = data[j]
        if (c == '\\' or
            (c == ')' and depth == 0) or
            (c == '(' and close_remaining <= depth)):
          output.append(data[i : j])  # Flush unescaped.
          output.append('\\' + c)
          if c == ')':
            close_remaining -= 1
          j += 1
          i = j
        else:
          if c == '(':
            depth += 1
          elif c == ')':
            depth -= 1
            close_remaining -= 1
          j += 1
      output.append(data[i:])
      output.append(')')
      assert depth == 0
      assert close_remaining == 0
      return ''.join(output)

  @classmethod
  def ParseValueRecursive(cls, data):
    """Parse PDF token sequence data to a recursive Python structure.

    As a relaxation, numbers are allowed as dict keys.
    
    Args:
      data: PDF token sequence
    Returns:
      A recursive Python data structure.
    Raises:
      PdfTokenParseError
    """
    data = PdfObj.CompressValue(data, do_emit_strings_as_hex=True)
    scanner = PdfObj.PDF_SIMPLE_TOKEN_RE.scanner(data)
    match = scanner.match()
    last_end = 0
    stack = [[]]
    # TODO(pts): Reimplement this using a stack.
    while match:
      last_end = match.end()
      token = match.group(0)
      if token == '<<':
        stack.append({})
        match = scanner.match()
        continue
      elif token == '[':
        stack.append([])
        match = scanner.match()
        continue
      elif token == ' ':
        match = scanner.match()
        continue
      elif match.group(1):
        try:
          token = int(token)
        except ValueError:
          if token == 'true':
            token = True
          elif token == 'false':
            token = False
          elif token == 'null':
            token = None
      elif token == '>>':
        if not isinstance(stack[-1], dict):
          raise PdfTokenParseError('unexpected dict-close')
        token = stack.pop()
      elif token == ']':
        if not isinstance(stack[-1], list):
          raise PdfTokenParseError('unexpected array-close')
        token = stack.pop()
        if not stack:
          raise PdfTokenParseError('unexpected array-close at top level')
      # Otherwise token is a hex string constant. Keep it as is (in hex).
      if stack[-1] is None:  # token is a value in a dict
        stack.pop()
        stack[-2][stack[-1]] = token
        stack.pop()
      elif isinstance(stack[-1], dict):  # token is a key in a dict
        if isinstance(token, str) and token[0] == '/':
          stack.append(token[1:])
        else:
          stack.append(token)
        stack.append(None)
      else:  # token is an item in an array
        stack[-1].append(token)
      match = scanner.match()

    if last_end != len(data):
      raise PdfTokenParseError(
         'syntax error at %r...' % data[last_end : last_end + 32])
    if len(stack) != 1:
      raise PdfTokenParseError('data structures not closed')
    token = stack.pop()
    if not token:
      raise PdfTokenParseError('no values received')
    if len(token) > 1:
      raise PdfTokenParseError('multiple value received')
    return token[0]

  @classmethod
  def IsGrayColorSpace(cls, colorspace):
    if not isinstance(colorspace, str): raise TypeError
    colorspace = colorspace.strip(cls.PDF_WHITESPACE_CHARS)
    if colorspace == '/DeviceGray':
      return True
    match = re.match(r'\[\s*/Indexed\s*(/DeviceRGB|/DeviceGray)'
                     r'\s+\d+\s*(?s)([<(].*)]\Z', colorspace)
    if not match:
      return False
    if match.group(1) == '/DeviceGray':
      return True
    palette = cls.ParseString(match.group(2))
    assert len(palette) % 3 == 0
    i = 0
    while i < len(palette):
      if palette[i] != palette[i + 1] or palette[i] != palette[i + 2]:
        return False  # non-gray color in the palette
      i += 3
    return True

  @classmethod
  def IsIndexedRgbColorSpace(cls, colorspace):
    return colorspace and re.match(
        r'\[\s*/Indexed\s*/DeviceRGB\s+\d', colorspace)

  @classmethod
  def ParseRgbPalette(cls, colorspace):
    match = re.match(r'\[\s*/Indexed\s*/DeviceRGB\s+\d+\s*([<(](?s).*)\]\Z',
                     colorspace)
    assert match, 'syntax error in /ColorSpace %r' % colorspace
    palette = cls.ParseString(match.group(1))
    assert len(palette) % 3 == 0
    return palette

  @classmethod
  def ParseString(cls, pdf_data):
    """Parse a PDF string data to a Python string.

    Args:
      pdf_data: `(...)' or `<...>' PDF string data
    Returns:
      Python string.
    Raises:
      PdfTokenParseError:
      PdfTokenTruncated:
      PdfTokenNotString:
    """
    pdf_data2 = cls.ParseSimpleValue(pdf_data)
    if not pdf_data2.startswith('<') or not pdf_data2.endswith('>'):
      raise PdfTokenNotString
    return pdf_data2[1 : -1].decode('hex')

  PDF_CLASSIFY = [40] * 256
  """Mapping a 0..255 byte to a character type used by RewriteToParsable.

  * PDF whitespace(0) is  [\\000\\011\\012\\014\\015\\040]
  * PDF separators(10) are < > { } [ ] ( ) / %
  * PDF regular(40) character is any of [\\000-\\377] which is not whitespace
    or separator.
  """

  PDF_CLASSIFY[ord('\0')] = PDF_CLASSIFY[ord('\t')] = 0
  PDF_CLASSIFY[ord('\n')] = PDF_CLASSIFY[ord('\f')] = 0
  PDF_CLASSIFY[ord('\r')] = PDF_CLASSIFY[ord(' ')] = 0
  PDF_CLASSIFY[ord('<')] = 10
  PDF_CLASSIFY[ord('>')] = 11
  PDF_CLASSIFY[ord('{')] = 12
  PDF_CLASSIFY[ord('}')] = 13
  PDF_CLASSIFY[ord('[')] = 14
  PDF_CLASSIFY[ord(']')] = 15
  PDF_CLASSIFY[ord('(')] = 16
  PDF_CLASSIFY[ord(')')] = 17
  PDF_CLASSIFY[ord('/')] = 18
  PDF_CLASSIFY[ord('%')] = 19

  @classmethod
  def RewriteToParsable(cls, data, start=0,
      end_ofs_out=None, do_terminate_obj=False):
    """Rewrite PDF token sequence so it will be easier to parse by regexps.

    Please note that this method is very slow. Use ParseSimpleValue or
    ParseDict (or Get) or ParseValueRecursive to get faster results most of
    the time. In the complicated case, those methods will call
    RewriteToParsable to do the hard work of proper parsing. You can avoid the
    complicated case if you don't have comments or `(...)' string constants in
    the token stream. Hex string constants (<...>) are OK.

    Parsing stops at `stream', `endobj' or `startxref', which will also
    be returned at the end of the string.

    This code is based on pdf_rewrite in pdfdelimg.pl, which is based on
    pdfconcat.c . Lesson learned: Perl is more compact than Python; Python is
    easier to read than Perl.

    This method doesn't check the type of dict keys, the evenness of dict
    item size (i.e. it accepts dicts of odd length, e.g. `<<42>>') etc.
    
    Please don't change ``parsable'' to ``parsable'', see
    http://en.wiktionary.org/wiki/parsable .

    Args:
      data: String containing a PDF token sequence.
      start: Offset in data to start the parsing at.
      end_ofs_out: None or a list for the first output byte
        (which is unparsed) offset to be appended. Terminating whitespace is
        not included, except for a single withespace is only after
        do_terminate_obj.
      do_terminate_obj: Boolean indicating whether look for and include the
        `stream' or `endobj' (or any other non-literal name)
        plus one whitespace (or \\r\\n) at end_ofs_out
        (and in the string).
    Returns:
      Nonempty string containing a PDF token sequence which is easier to
      parse with regexps, because it has additional whitespace, it has no
      funny characters, and it has strings escaped as hex. The returned string
      starts with a single space. An extra \\n is inserted in front of each
      name key of a top-level dict.
    Raises:
      PdfTokenParseError: TODO(pts): Report the error offset as well.
      PdfTokenTruncated:
    """
    # !! precompile regexps in this method (although sre._compile uses cache,
    # but if flushes the cache after 100 regexps)
    data_size = len(data)
    i = start
    if data_size <= start:
      raise PdfTokenTruncated
    output = []
    # Stack of '[' (list) and '<' (dict)
    stack = ['-']
    if do_terminate_obj:
      stack[:0] = ['.']

    while stack:
      if i >= data_size:
        raise PdfTokenTruncated('structures open: %r' % stack)

      o = cls.PDF_CLASSIFY[ord(data[i])]
      if o == 0:  # whitespace
        i += 1
        while i < data_size and cls.PDF_CLASSIFY[ord(data[i])] == 0:
          i += 1
      elif o == 14:  # [
        stack.append('[')
        output.append(' [')
        i += 1
      elif o == 15:  # ]
        item = stack.pop()
        if item != '[':
          raise PdfTokenParseError('got list-close, expected %r' % item)
        output.append(' ]')
        i += 1
        if stack[-1] == '-':
          stack.pop()
      elif o in (18, 40):  # name or /name or number
        # TODO(pts): Be more strict on PDF token names.
        j = i
        p = o == 18
        i += 1
        if p:
          if i >= data_size:
            raise PdfTokenTruncated
          i += 1  # Accept e.g. /% as a token.
        while i < data_size and cls.PDF_CLASSIFY[ord(data[i])] == 40:
          i += 1
        if i == data_size:
          raise PdfTokenTruncated
        token = re.sub(
            r'#([0-9a-f-A-F]{2})',
            lambda match: chr(int(match.group(1), 16)), data[j : i])
        if token[0] == '/' and data[j] != '/':
          raise PdfTokenParseError('bad slash-name token')

        # `42.' is a valid float in both Python and PDF.
        number_match = re.match(r'(?:([-])|[+]?)0*(\d+(?:[.]\d*)?)\Z', token)
        if number_match:
          # From the PDF reference: Note: PDF does not support the PostScript
          # syntax for numbers with nondecimal radices (such as 16#FFFE) or in
          # exponential format (such as 6.02E23).

          # Convert the number to canonical (shortest) form.
          token = (number_match.group(1) or '') + number_match.group(2)
          if '.' in token:
            token = token.rstrip('0')
            if token.endswith('.'):
              token = token[:-1]  # Convert real to integer.
          if token == '-0':
            token = '0'

        # Append token with special characters escaped.
        if token[0] == '/':
          # TODO(pts): test this
          output.append(
              ' /' + re.sub(r'[^-+A-Za-z0-9_.]',
                  lambda match: '#%02X' % ord(match.group(0)), token[1:]))
        else:
          # TODO(pts): test this
          output.append(
              ' ' + re.sub(r'[^-+A-Za-z0-9_.]',
                  lambda match: '#%02X' % ord(match.group(0)), token))

        if (number_match or token[0] == '/' or
            token in ('true', 'false', 'null', 'R')):
          if token == 'R' and (
             len(output) < 3 or
             output[-3] == ' 0' or
             not re.match(r' \d+\Z', output[-2]) or
             not re.match(r' \d+\Z', output[-3])):
            raise PdfTokenParseError(
                'invalid R after %r' % output[-2:])
          if stack[-1] == '-':
            if re.match(' -?\d+\Z', output[-1]):
              # We have parsed `5' from `5 6 R', try to find the rest.
              # TODO(pts): raise PdfTokenTruncated if not available?
              match = cls.REST_OF_R_RE.scanner(data, i, len(data)).match()
              if match:
                num2 = int(match.group(1))
                if int(output[-1]) <= 0 or num2 < 0:
                  raise PdfTokenParseError(
                      'invalid R: %s %s' % (output[-1], num2))
                output.append(' %s R' % num2)
                i = match.end()
            stack.pop()
        else:
          # TODO(pts): Support parsing PDF content streams.
          if stack[-1] != '.':
            raise PdfTokenParseError(
                'invalid name %r with stack %r' % (token, stack))
          stack.pop()
          if data[i] == '\r':
            i += 1
            if i == data_size:
              if output[-1] == ' stream':
                raise PdfTokenTruncated, 'missing \\n after \\r'
            elif data[i] == '\n':  # Skip over \r\n.
              i += 1
          elif cls.PDF_CLASSIFY[ord(data[i])] == 0:
            i += 1  # Skip over whitespace.
      elif o == 11:  # >
        i += 1
        if i == data_size:
          raise PdfTokenTruncated
        if data[i] != '>':
          raise PdfTokenParseError('dict-close expected')
        item = stack.pop()
        if item != '<':
          raise PdfTokenParseError('got dict-close, expected %r' % item)
        output.append(' >>')
        i += 1
        if stack[-1] == '-':
          stack.pop()
      elif o == 10:  # <
        i += 1
        if i == data_size:
          raise PdfTokenTruncated
        if data[i] == '<':
          stack.append('<')
          output.append(' <<')
          i += 1
        else:  # hex string
          j = data.find('>', i)
          if j < 0:
            hex_data = data[i :]
          else:
            hex_data = data[i : j]
          hex_data = re.sub(r'[\0\t\n\r \014]+', '', hex_data)
          if not re.match('[0-9a-fA-F]*\Z', hex_data):
            raise PdfTokenParseError('invalid hex data')
          if j < 0:
            raise PdfTokenTruncated
          if len(hex_data) % 2 != 0:
            hex_data += '0'  # <def> --> <def0>
          i = j + 1
          output.append(' <%s>' % hex_data.lower())
          if stack[-1] == '-':
            stack.pop()
      elif o == 16:  # string
        depth = 1
        i += 1
        j = data.find(')', i)
        if j > 0:
          s = data[i : j]
        else:
          s = '('
        if '(' not in s and ')' not in s and '\\' not in s:
          output.append(' <%s>' % s.encode('hex'))
          i = j + 1
        else:
          # Compose a Python eval()able string in string_output.
          string_output = ["'"]
          j = i
          while True:
            if j == data_size:
              raise PdfTokenTruncated
            c = data[j]
            if c == '(':
              depth += 1
              j += 1
            elif c == ')':
              depth -= 1
              if not depth:
                string_output.append(data[i : j])
                j += 1
                i = j
                break
              j += 1
            elif c == "'":
              string_output.append(data[i : j])
              string_output.append("\\'")
              j += 1
              i = j
            elif c == '\\':
              if j + 1 == data_size:
                raise PdfTokenTruncated
              c = data[j + 1]
              if c in '0123nrtbf"\\\'':
                j += 2
              elif c in '4567':
                string_output.append(data[i : j])
                string_output.append('\\00' + c)
                j += 2
                i = j
              else:
                string_output.append(data[i : j])
                string_output.append(c)  # without the backslash
                j += 2
                i = j
            elif c == '\0':
              string_output.append(data[i : j])
              string_output.append('\\000')  # for eval() below
              j += 1
              i = j
            elif c == '\n':
              string_output.append(data[i : j])
              string_output.append('\\n')  # for eval() below
              j += 1
              i = j
            else:
              j += 1
          string_output.append("'")
          # eval() works for all 8-bit strings.
          output.append(
              ' <%s>' % eval(''.join(string_output), {}).encode('hex'))
          i = j
        if stack[-1] == '-':
          stack.pop()
      elif o == 19:  # single-line comment
        while i < data_size and data[i] != '\r' and data[i] != '\n':
          i += 1
        if i < data_size:
          i += 1  # Don't increase it further.
      else:
        raise PdfTokenParseError('syntax error, expecing PDF token, got %r' %
                                 data[i])

    assert i <= data_size
    output_data = ''.join(output)
    assert output_data
    if end_ofs_out is not None:
      end_ofs_out.append(i)
    return output_data

  # !! def OptimizeSource()

  def GetUncompressedStream(self, is_gs_ok=False):
    assert self.stream is not None
    filter = self.Get('Filter')
    if filter is None: return self.stream
    decodeparms = self.Get('DecodeParms') or ''
    if filter == '/FlateDecode' and '/Predictor' not in decodeparms:
      return zlib.decompress(self.stream)
    if not is_gs_ok:
      raise FilterNotImplementedError('filter not implemented: ' + filter)
    tmp_file_name = 'type1cconf.filter.tmp.bin'
    f = open(tmp_file_name, 'w')
    write_ok = False
    try:
      f.write(self.stream)
      write_ok = True
    finally:
      f.close()
      if not write_ok:
        os.remove(tmp_file_name)
    decodeparms_pair = ''
    if decodeparms:
      decodeparms_pair = '/DecodeParms ' + decodeparms
    # !! batch all decompressions, so we don't have to run gs again.
    gs_defilter_cmd = (
        'gs -dNODISPLAY -q -sINFN=%s -c \'/i INFN(r)file<</CloseSource true '
        '/Intent 2/Filter %s%s>>/ReusableStreamDecode filter def '
        '/o(%%stdout)(w)file def/s 4096 string def '
        '{i s readstring exch o exch writestring not{exit}if}loop '
        'o closefile quit\'' %
        (ShellQuote(tmp_file_name), filter, decodeparms_pair))
    print >>sys.stderr, (
        'info: decomressing %d bytes with Ghostscript '
        '/Filter%s%s' % (len(self.stream), filter, decodeparms_pair))
    f = os.popen(gs_defilter_cmd)
    data = f.read()  # TODO(pts): Handle IOError etc.
    assert not f.close(), 'Ghostscript decompression failed: %s' % (
        gs_defilter_cmd)
    os.remove(tmp_file_name)
    return data

  CFF_REAL_CHARS = {
      0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7',
      8: '8', 9: '9', 10: '.', 11: 'E', 12: 'E-', 13: '?', 14: '-', 15: ''}

  CFF_REAL_CHARS_REV = {
      '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
      '8': 8, '9': 9, '.': 10, 'E': 11, 'F': 12, '?': 13, '-': 14}

  CFF_OFFSET0_OPERATORS = (
      15,  # charset
      16,  # Encoding
      17,  # CharStrings
      18,  # Private (only last operand is offset)
      12036,  # FDArray
      12037,  # FDSelect
  )
  """List of CFF DICT operators containing absolute offsets: (0).
  """

  @classmethod
  def ParseCffDict(cls, data, start=0, end=None):
    """Parse CFF DICT data to a dict mapping operator to operand list.
    
    The format of the returned dict is the following. Keys are integers
    signifying operators (range 0..21 and 12000..12256). Values are arrays
    signifying operand lists. Each operand is an integer or a string of a
    floating point real number.
    """
    # The documentation http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
    # was used to write this function.
    #print 'PPP', data[start: end].encode('hex')
    cff_dict = {}
    if end is None:
      end = len(data)
    i = start
    operands = []
    while i < end:
      b0 = ord(data[i])
      #print (i, b0)
      i += 1
      if 32 <= b0 <= 246:
        operands.append(b0 - 139)
      elif 247 <= b0 <= 250:
        assert i < end  # TODO(pts): Proper exceptions here
        b1 = ord(data[i])
        i += 1
        operands.append((b0 - 247) * 256 + b1 + 108)
      elif 251 <= b0 <= 254:
        assert i < end
        b1 = ord(data[i])
        i += 1
        operands.append(-(b0 - 251) * 256 - b1 - 108)
      elif b0 == 28:
        assert i + 2 <= end
        operands.append(ord(data[i]) << 8 | ord(data[i + 1]))
        i += 2
        if operands[-1] >= 0x8000:
          operands[-1] -= 0x10000
      elif b0 == 29:
        assert i + 4 <= end
        operands.append(ord(data[i]) << 24 | ord(data[i + 1]) << 16 |
                        ord(data[i + 2]) << 8 | ord(data[i + 3]))
        if operands[-1] >= 0x80000000:
          operands[-1] = int(operands[-1] & 0x100000000)
        i += 4
      elif b0 == 30:
        # TODO(pts): Test this.
        real_chars = []
        while True:
          assert i < end
          b0 = ord(data[i])
          #print 'F 0x%02x' % b0
          i += 1
          real_chars.append(cls.CFF_REAL_CHARS[b0 >> 4])
          real_chars.append(cls.CFF_REAL_CHARS[b0 & 15])
          if (b0 & 0xf) == 0xf:
            break
        operands.append(''.join(real_chars))
      elif 0 <= b0 <= 21:
        if b0 == 12:
          assert i < end
          b0 = 12000 + ord(data[i])
          i += 1
        cff_dict[b0] = operands
        operands = []
      else:
        # TODO(pts): Raise proper exception here and above.
        assert 0, 'invalid CFF DICT operand/operator: %s' % b0
    return cff_dict

  @classmethod
  def SerializeCffDict(cls, cff_dict):
    """Parse CFF DICT to a string. Inverse of ParseCffDict."""
    # The documentation http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
    # was used to write this function.
    # TODO(pts): Test this.
    output = []
    for operator in sorted(cff_dict):
      for operand in cff_dict[operator]:
        if isinstance(operand, str):
          # TODO(pts): Test this.
          operand = operand.replace('E-', 'F')
          # TODO(pts): Raise proper exception instead of KeyError.
          nibbles = map(cls.CFF_REAL_CHARS_REV.__getitem__, operand)
          nibbles.append(0xf)
          if (len(nibbles) & 1) != 0:
            nibbles.append(0xf)
          output.append(chr(30) + ''.join([
              chr(nibbles[i] << 4 | nibbles[i + 1])
              for i in xrange(0, len(nibbles), 2)]))
        elif isinstance(operand, int) or isinstance(operand, long):
          if -107 <= operand <= 107:
            output.append(chr(operand + 139))
            assert 32 <= ord(output[-1][0]) <= 246
          elif 108 <= operand <= 1131:
            output.append('%c%c' %
                (((operand - 108) >> 8) + 247, (operand - 108) & 255))
            assert 247 <= ord(output[-1][0]) <= 250
          elif -1131 <= operand <= -108:
            output.append('%c%c' %
                (((-operand - 108) >> 8) + 251, (-operand - 108) & 255))
            assert 251 <= ord(output[-1][0]) <= 254
          elif -32768 <= operand <= 32767:
            output.append(chr(28) + struct.pack('>H', operand))
          elif ~0x7fffffff <= operand <= 0x7fffffff:
            output.append(chr(29) + struct.pack('>L', operand))
          else:
            assert 0, 'CFF DICT integer operand %r out of range' % operand
        else:
          assert 0, 'invalid CFF DICT operand %r' % (operand,)
      if operator >= 12000:
        output.append('\014%c' % (operator - 12000))
      else:
        output.append(chr(operator))
    return ''.join(output)

  @classmethod
  def ParseCffHeader(self, data):
    """Parse the (single) font name and the top DICT of a CFF font."""
    # TODO(pts): Test this.
    # !! unify this with FixFontNameInType1C.
    assert ord(data[2]) >= 4
    i0 = i = ord(data[2])  # skip header
    count, off_size = struct.unpack('>HB', data[i : i + 3])
    assert count == 1, 'Type1C name index count should be 1, got ' % count
    if off_size == 1:
      i += 5
      offset1 = ord(data[i - 2])
      offset2 = ord(data[i - 1])
    elif off_size == 2:
      i += 7
      offset1, offset2 = struct.unpack('>HH', data[i - 4 : i])
    assert offset1 >= 1
    assert offset2 > offset1
    i += offset1 - 1
    j = i + offset2 - offset1
    assert j < 255, 'font name %r... too long' % data[i : i + 20]
    font_name = data[i : j]
    i = j
    count, off_size = struct.unpack('>HB', data[i : i + 3])
    assert count == 1, 'Type1C top dict index count should be 1, got ' % (
        count)
    if off_size == 1:
      i += 5
      offset1 = ord(data[i - 2])
      offset2 = ord(data[i - 1])
    elif off_size == 2:
      i += 7
      offset1, offset2 = struct.unpack('>HH', data[i - 4 : i])
    assert offset1 >= 1
    assert offset2 > offset1
    i += offset1 - 1
    j = i + offset2 - offset1
    cff_dict = self.ParseCffDict(data=data, start=i, end=j)
    return (data[:ord(data[2])], font_name, cff_dict, data[j:])

  def FixFontNameInType1C(self, new_font_name='F', do_always_recompress=False):
    """Fix the FontName in a /Subtype/Type1C object."""
    # The documentation http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
    # was used to write this function.
    assert self.Get('Subtype') == '/Type1C'
    data = self.GetUncompressedStream(is_gs_ok=do_always_recompress)
    do_recompress = self.Get('Filter') != '/FlateDecode'
    assert ord(data[2]) >= 4
    i0 = i = ord(data[2])  # skip header
    count, off_size = struct.unpack('>HB', data[i : i + 3])
    assert count == 1, 'Type1C name index count should be 1, got ' % count
    if off_size == 1:
      i += 5
      offset1 = ord(data[i - 2])
      offset2 = ord(data[i - 1])
    elif off_size == 2:
      i += 7
      offset1, offset2 = struct.unpack('>HH', data[i - 4 : i])
    assert offset1 == 1  # TODO(pts): Shrink this to 1.
    assert offset2 > offset1
    i += offset1 - 1
    j = i + offset2 - offset1
    assert j < 255, 'font name %r... too long' % data[i : i + 20]
    old_font_name = data[i : j]
    #print 'OLD', old_font_name, data.encode('hex')
    #new_font_name = 'Obj' + data[i + 7 : j]
    assert len(new_font_name) < 255, 'new font name %r too long' % (
        new_font_name,)
    # TODO(pts): What if off_size has to be increased because new_font_name is
    # too long?
    # !! test all branches of this
    if old_font_name != new_font_name:
      len_delta = len(new_font_name) - (j - i)
      if len_delta == 0:
        output = [data[:i], new_font_name, data[j:]]
      else:
        # !! test multiple iterations with: REN Obj000009 01000402000101010a4f626a3030303030390001010128f81b02f81c038bfb61f9d5f961051d004e31850df7190ff610f74a11961c0e10128b0c038b0c04000201011625436f6d7075746572204d6f6465726e20526f6d616e436f6d7075746572204d6f6465726e0000001801170f18100506081309140a150b0c0d020e041112070316000022005a004f005b005000450046004700530048005400490055004a004c004d0042004e000d00d8000f00cf00c800e0001902000100070093012d01ae021a02910314038803fc04620567061d06a9070a075e0814084e08ee09ad09fa0aa60ad40b870c680d24ff015682000eff03027d008caaf75aaaf85c7701adab156c07c98e05f72ca7066e6098b098909890971f9cba99ca9e8b08f782069d8b9753957094709f648b78086d548b701e6cf7a6aa6f07758b738d7f977e98879e859b43f75548f75844f75583a018879687947b8b768b8773857b4efb3e4efb404dfb3d795818764c6277548b08f75ff77915f70af7dbf70afbdb050eff021e4e00fb60a472f711f873aa1213a0a0f843156c9907b08b9d819969a05818a748a84ba748ac3d188e8393808b828b7d7e77857e7f6f18785e6c515389798b7b907d96a390979a8ba0081360a37b9e6d707f73775abb6bb8f2b5f71dd5a91eb6f2b6f0b8f19db6a1b7c88b08aafb376c07a28aa07d8d728b7074647f6e72517152745164e069e365e1899286928b9308a5ac8ca01eaa070eff023ad9008fa78176f834a412f704cf47d5f766d51713b4aef843156c9b07a9aa885c1ffba80762718a581e13746c0713acd28e05f731a774066e728fb01ff74807d8b8e2eac19b594d1efb7f07676e896a1e7c0613746c0713b4d28e05f731a778066e6e8eaf1ff776078ba98aa87ca672ba57975a8b4d8b4c6275518aee180eff01c8ad008ca7f80da401c1f8431580fb3805a7068dae8db4a1a7a4abb98eb48b08f703066c6670646e654a374a374c36868485838b8208809588931ef7f1069cf752056f068862875a736b6e6659885f8b08fb0306e9f70de8f70de6f70f909192938b940895848f811e0eff0201c30081a7f829a58a7712a9e1f7ade21713b8f786f85415fb087f2b2d8bfb140824d8fb0df72af709f702e8f7161e13d8f70b2ef709fb1b1e13b886878a861bfb12fb9515b60713d8daa4f702f708dbbc4c3c941e8d768b768b768b5688516761726c647b658b428b58c27edb8a988b978998080eff023ad90081a4f825a5f7917701ade2f7a3d203f7cff940156c9607b3a589501ffb65076ab25c9f598b08fb102323fb0ffb06e8fb03f711bacba2b4a41f8c4bf72b9605aa7c076a6e8eba1ff8f907fbeafc8a159907dc9ff714f712bed3654d7e8a7f8b7e1efb38078b7e8682848170645e6f5c8b648b679f73aa6eb087b886b8080eff01c9100081a7f768a3f73da401a7e3f787d003f707f77a15f7bc0697909196f7113ed721fb0e2c21fb0efb0fec20f71dd2d3bdd09f1f8c8e8c8f8b8f0892869183798a6d7d811e73615a6e5a8b088406578d5dae75ba78b389b88bb6088ca3158ccda7d8d3a2938d938c938b08e1ab323b1f0eff0139f7008fa78176f823aaf733f70872a412f705d21713b4f705f843153b6cdbfbde06676e896a1e7c0613746c0713acd28e05f741a76a0667708fb61ff7d5f708aafb0be607cc9be9d795968987941e7b83817c8b790813b4729e78a4a99a9fa4ba58a361454d5e49751e86788a798b78080eff0191e8008fa78176f834a412f6cc4ad21713b0a9f843156c9b07a9aa885c1ffba80762718a581e13706c0713a8d18e05f742a76906696f8fb11ff73c0792d09ef5f08b088a077d84857c8b7c0870a07aa3a49da0a3b462a0684e5a58537d1e13b08af6050eff0201c300fb61a6f74dc9dba7f781a7967712a8c373d9f747d8acc31713ed80f700f756158a07777780698b6f8b6a9966a8795d785e6f8b560826f73170d3e0f721a9f0f70cfb10a2261e3006698f75a98bab089891a7941e8d069988988099879e859f889f8b08dae2c3e3ae7eb36fa21f8c07aca2a698b18b838585838b80087a997d9ba0959c99ac6e9c711e83066c876c81727688888786868b088a06848b759a7c910813f3809378768e761b39335330669c62a9741f13f58074fba8159207c0bfa8ba95968a8b951ebe06c68be886954308840734fb267e704b2ba5d1811e13f380c1f7fc159607c298d1d7c9a757445271524b727295a07a1e7b9f88a488a4080eff01954d0081a4f82fa112adbef77ba76fc11713e8e6ad15ab6bb47fb68b08dddcb5ec1f960787c35fb6599e72946f8f7190619349978bc508c5d499b6cab96644911e838c81971e13f0928b928f8c9208f70d07928894827c80728b7f1e8906848d8491858e7695718f738b08442b742526f7097ad37d1fb783bb718f5a08434f76561e8106428f63c27ad088968b9b7c8b08808883821ffb15078b878a868b8608818d819694939791911e9091919291919092190eff023ad9008fa78176f834a4f7917712f704d2f769d51713bcaef940156c9c07aaa8875b1ffc8c078b848c848b8308616e8a601e8506137c6c0713bcd28e05f731a774066e728fb01ff74807d8b8e2eac19b594d1efb7f07676e896a1e7c06137c6c0713bcd28e05f731a778066e6e8eaf1ff776078ba98aa97ca673b758995c8b538b466b744e8af7ee180eff018f97009676f82ea472aaf74d7712f5d56fa7f71ba61713d6f72cf8fc154269fb0a281e720713bae2fb9c068b6c8d6d9b70a361bd7bb98b089406d79898de8bc608b06f078b7d8c7c8b7c085f813f50557fcabc1ef7a2f725aafb25f74d070eff011d6c008caaf9127712daf444d21713d0b3f843156c9b07aba4865e1ffba90763708a591e6cf76daa7b0770718eab1ff80b0751f7781513e0718776766f1a6ea373a91e9206a58fa0a08ba708a873a36d1e0eff021e4e008fa78176f823aaf79c7712f6d21713b8a9f940156c9c07aaa8875b1ffc8c078b848c848b8308616e8a601e850613786c0713b8d18e05f72ca772066d758fb61fd4078b908a908b908b9a979094939a97999a9b95a85ab55dad5a9182947d8b7f087b78867c1e13786cf75a0713b8aa076a8b749273a67c9c7e9e7d9e66bf64bd66bf928f90909190a6a118bab3c1bccd8b08aafb4b6c0796889a878b7b8b6e6674757a4752187e807d817f7f08f871070eff011d6c008caaf92b7701f705d203aff940156c9707afa889591ffc8c078b848c848b8308616e8a601e856cf775aa720670728fae1ff904070eff0201c30081a472b3f79df72d72a412b4def765d5d3a717135ef70ef81815a6a4b495af8baf8baa789f6d9e6f8c6c8b6b0879073982398b46576a7271648b62083aed6fcdc9b9aabfa81e9362a366b98b08c7a6bec21fb86f59076f85656c6a89b7a11ef75707f431bf324d2e713c1e13ae709b76af1ea48c9ba28ba28ba67699749008f767fb27152807475a50461e83065c9067ae8bb808eaf706b9ea1e0eff035845008fa78176f834a412f704cf47d5f767d5f767d51713b6aef843156c9b07a9aa885c1ffba80762718a581e13766c0713aed28e05f731a774066e728fb01ff75d0791d2bbd3e18b08cb924a5c1ffb7f07676e896a1e7c0613766c0713b6d28e05f731a774066e728fb01ff75d0791d2bbd3e18b08cb924a5c1ffb7f07676e896a1e7c0613766cf7780713b6aa78076e6e8eaf1ff776078ba98aa97ca671ba57965a8b4f8b4b637654088a0682d04aa54f8b4a8b4c67734c8aee180eff011d6c00fb3f76f7c17712e3f70b72a41713e0f74a9c158b48784b5959878784858b8508849286909ca3af9e971ea5b499bc8bbc08b681cb506d776e726da273a91e13d09b8b99909696080eff0201c30081a7f829a5f75877a07712a9e1f7ade21713ecf786f85415fb087f2b2d8bfb140824d8fb0df72af709f702e8f716f70b2ef709fb1b86878a8b861efb12fb9515b607daa4f702f708dbbc4c3c941e8d768b768b768b5688516761726c647b658b428b58c27edb8a988b97899808f756f85a157a897a767f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac8bae1913dc9f7b9f761e13ec89898a891b0eff011d6c00a176f7007701e3f70003f71af70015728876758b6f08719f6faba4aa9dafa676a66a88898b8a881e0eff01c9100081a7f768a3f73da4f75977a07712a7e3f787d01713f6f707f77a15f7bc0697909196f7113ed721fb0e2c21fb0efb0fec20f71dd2d3bdd09f1f8c8e8c8f8b8f0892869183798a6d7d811e73615a6e5a8b088406578d5dae75ba78b389b88bb6088ca3158ccda7d8d3a2938d938c938b08e1ab323b1f3ef81b157a897a767f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac8bae1913ee9f7b9f761e13f689898a891b0eff0201c30081a472b3f79df72d72a4f75977a07712b4def765d5d3a717135780f70ef81815a6a4b495af8baf8baa789f6d9e6f8c6c8b6b0879073982398b46576a7271648b62083aed6fcdc9b9aabfa81e9362a366b98b08c7a6bec21fb86f59076f85656c6a89b7a11ef75707f431bf324d2e713c1e13ab80709b76af1ea48c9ba28ba28ba67699749008f767fb27152807475a50461e83065c9067ae8bb808eaf706b9ea1e74f828157a897a767f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac8bae1913a7809f7b9f761e13ab8089898a891b0eff023ad90081a4f815aff70af7008a7712f704d5f766d51713dcaef843156c9407a6b2896e1f8d808b818b8008fb5c078b6d8c6e9a70a759c880c08bc38bc0ac9ebf8c3618f7289605aa7a076d6d8eb81ff7fe07fb2b80056c9907aaab885d1ffb5a07854a64423d8b638b679582bf899e8b9d8b9e08f7c907f759f76f15708778758b710813ec729f6daaaea0a6a6a279aa6a1e13dc88878a881bfb5b166e877a718b740813ec749d6caca8a6a1aaa577a86b1e13dc88888a881b0eef0abd0b1e0a03963f0c090000
        output = [data[:i0]]
        output.append('\x00\x01%s\x01\x01%c' %  # CFF INDEX header
                      ('\x00' * (off_size - 1), 1 + len(new_font_name)))
        output.append(new_font_name)
        i = j
        count, off_size = struct.unpack('>HB', data[i : i + 3])
        assert count == 1, 'Type1C top dict index count should be 1, got ' % (
            count)
        if off_size == 1:
          i += 5
          offset1 = ord(data[i - 2])
          offset2 = ord(data[i - 1])
        elif off_size == 2:
          i += 7
          offset1, offset2 = struct.unpack('>HH', data[i - 4 : i])
        assert offset1 == 1  # TODO(pts): Shrink this to 1.
        assert offset2 > offset1
        i += offset1 - 1
        j = i + offset2 - offset1
        cff_dict = self.ParseCffDict(data=data, start=i, end=j)

        old_cff_dict_data_len = j - i
        while True:
          # Add len_data to the appropriate fields.
          for cff_operator in sorted(cff_dict):
            if cff_operator in self.CFF_OFFSET0_OPERATORS:
              assert isinstance(cff_dict[cff_operator][-1], int)
              cff_dict[cff_operator][-1] += len_delta

          # Append the modified CFF dict and the rest to output.
          cff_dict_data = self.SerializeCffDict(cff_dict=cff_dict)
          cff_dict_parsed2 = self.ParseCffDict(data=cff_dict_data)
          assert cff_dict == cff_dict_parsed2, (
              'CFF dict serialize mismatch: new=%r parsed=%r' %
              (cff_dict, cff_dict_parsed2))
          len_delta = len(cff_dict_data) - old_cff_dict_data_len
          if len_delta == 0:
            break
          # Since cff_dict_data is shorter than the old dict data,
          # we have to decrease the offsets even more.
          old_cff_dict_data_len = len(cff_dict_data)

        assert (off_size >= 4 or
                (1 << (off_size << 3)) > len(cff_dict_data) + 1), (
            'new CFF dict too large, length=%d off_size=%d' % (
                len(cff_dict_data, off_size)))
        offset2_str = struct.pack('>L', len(cff_dict_data) + 1)[-off_size:]
        output.append('\x00\x01%s\x01\x01%c' %  # CFF INDEX header
                      ('\x00' * (off_size - 1), offset2_str))
        output.append(cff_dict_data)
        output.append(data[j:])
                      
      data = ''.join(output)
      do_recompress = True
      #print 'REN', new_font_name, data.encode('hex')

    if do_recompress:
      # Since in Ghostscript 6.54 it is not possible to specify the ZIP
      # compression level in -sDEVICE=pdfwrite, we recompress with maximum
      # effort here.
      # !! generic recompress all /FlateDecode filters (because Ghostscript is
      # suboptimal everywhere)
      self.stream = zlib.compress(data, 9)
      self.Set('Filter', '/FlateDecode')
      self.Set('DecodeParms', None)
      self.Set('Length', len(self.stream))


class ImageData(object):
  """Partial PNG image data, undecompressed by default.

  Attributes:  (any of them can be None if not initialized yet)
    width: in pixels
    height: in pixels
    bpc: bit depth, BitsPerComponent value (1, 2, 4, 8 or 16)
    color_type: 'gray', 'rgb', 'indexed-rgb', 'gray-alpha', 'rgb-alpha'
    is_interlaced: boolean
    idat: compressed binary string containing the image data (i.e. the
      IDAT chunk), or None
    plte: binary string (R0, G0, B0, R1, G1, B1) containing the PLTE chunk,
      or none
    compression: 'none', 'zip', 'zip-tiff' (ZIP compression with TIFF
      predictor), 'zip-png' (ZIP compression with PNG predictor),
      'jbig2'.
    file_name: name of the file originally loaded

  TODO(pts): Make this a more generic image object; possibly store /Filter
    and predictor.
  """
  __slots__ = ['width', 'height', 'bpc', 'color_type', 'is_interlaced',
               'idat', 'plte', 'compression', 'file_name']

  SAMPLES_PER_PIXEL_DICT = {
      'gray': 1,
      'rgb': 3,
      'indexed-rgb': 1,
      'gray-alpha': 2,
      'rgb-alpha': 4,
  }
  """Map a .color_type value to the number of samples per pixel."""
  
  COMPRESSION_TO_PREDICTOR = {
      'zip-tiff': 2,
      'zip-png': 10,
  }
  """Map a .compression value with preditor to the PDF predictor number."""
  
  COLOR_TYPE_PARSE_DICT = {
     0: 'gray',
     2: 'rgb',
     3: 'indexed-rgb',
     4: 'gray-alpha',
     6: 'rgb-alpha',
  }
  """Map a PNG color type byte value to a color_type string."""

  def __init__(self, other=None):
    """Initialize from other.

    Args:
      other: A ImageData object or none.
    """
    if other is not None:
      if not isinstance(other, ImageData): raise TypeError
      self.width = other.width
      self.height = other.height
      self.bpc = other.bpc
      self.color_type = other.color_type
      self.is_interlaced = other.is_interlaced
      self.idat = other.idat
      self.plte = other.plte
      self.compression = other.compression
      self.file_name = other.file_name
    else:
      self.Clear()

  def Clear(self):
    self.width = self.height = self.bpc = self.color_type = None
    self.is_interlaced = self.idat = self.plte = self.compression = None
    self.file_name = None

  def __nonzero__(self):
    """Return true iff this object contains a valid image."""
    return bool(isinstance(self.width, int) and self.width > 0 and
                isinstance(self.height, int) and self.height > 0 and
                isinstance(self.bpc, int) and
                self.bpc in (1, 2, 4, 8, 12, 16) and
                self.color_type in ('gray', 'rgb', 'indexed-rgb', 'gray-alpha',
                                    'rgb-alpha') and
                self.compression in ('none', 'zip', 'zip-tiff', 'zip-png',
                                     'jbig2') and
                isinstance(self.is_interlaced, bool) and
                self.is_interlaced in (True, False) and
                (self.color_type.startswith('indexed-') or
                 self.plte is None) and
                isinstance(self.idat, str) and self.idat and
                (not self.color_type.startswith('indexed-') or (
                 isinstance(self.plte, str) and len(self.plte) % 3 == 0)))

  def ToDataTuple(self):
    """Return the data in self as __hash__{}able tuple."""
    return (self.width, self.height, self.bpc, self.color_type,
            self.is_interlaced, self.idat, self.plte, self.compression)

  def CanBePdfImage(self):
    return bool(self and self.bpc in (1, 2, 4, 8) and
                self.color_type in ('gray', 'rgb', 'indexed-rgb') and
                not self.is_interlaced)

  def CanBePngImage(self, do_ignore_compression=False):
    # It's OK to have self.is_interlaced == True.
    return bool(self and self.bpc in (1, 2, 4, 8) and
                self.color_type in ('gray', 'rgb', 'indexed-rgb') and
                (self.color_type != 'rgb' or self.bpc == 8) and
                (do_ignore_compression or self.compression == 'zip-png'))

  @property
  def samples_per_pixel(self):
    assert self.color_type
    return self.SAMPLES_PER_PIXEL_DICT[self.color_type]

  @property
  def bytes_per_row(self):
    """Return the number of bytes per uncompressed, unpredicted row."""
    return (self.width * self.samples_per_pixel * self.bpc + 7) >> 3

  def GetPdfColorSpace(self):
    assert self.color_type
    assert not self.color_type.startswith('indexed-') or self.plte
    if self.color_type == 'gray':
      return '/DeviceGray'
    elif self.color_type == 'rgb':
      return '/DeviceRGB'
    elif self.color_type == 'indexed-rgb':
      assert self.plte
      assert len(self.plte) % 3 == 0
      return '[/Indexed/DeviceRGB %d%s]' % (
          len(self.plte) / 3 - 1, PdfObj.EscapeString(self.plte))
    else:
      assert 0, 'cannot convert to PDF color space'

  def GetPdfImageData(self):
    """Return a dictinary useful as a PDF image."""
    assert self.CanBePdfImage()  # asserts not interlaced
    pdf_image_data = {
        'Width': self.width,
        'Height': self.height,
        'BitsPerComponent': self.bpc,
        'ColorSpace': self.GetPdfColorSpace(),
        '.stream': self.idat,
    }
    if self.compression == 'none':
      pass
    elif self.compression == 'zip':
      pdf_image_data['Filter'] = '/FlateDecode'
    elif self.compression in ('zip-tiff', 'zip-png'):
      pdf_image_data['Filter'] = '/FlateDecode'
      if self.samples_per_pixel > 1:
        prs_colors = '/Colors %d' % self.samples_per_pixel
      else:
        prs_colors = ''
      if self.bpc != 8:
        prs_bpc = '/BitsPerComponent %d' % self.bpc
      else:
        prs_bpc = ''
      pdf_image_data['DecodeParms'] = (
          '<<%s%s/Columns %d/Predictor %d>>' %
          (prs_colors, prs_bpc, self.width,
           self.COMPRESSION_TO_PREDICTOR[self.compression]))
    elif self.compression == 'jbig2':
      pdf_image_data['Filter'] = '/JBIG2Decode'
    if self.bpc == 1 and self.color_type == 'indexed-rgb':
      # Such images are emitted by PNGOUT.
      if self.plte in ('\0\0\0\xff\xff\xff', '\0\0\0'):
        pdf_image_data['ColorSpace'] = '/DeviceGray'
      elif self.plte in ('\xff\xff\xff\0\0\0', '\xff\xff\xff'):
        # TODO(pts): Test this.
        pdf_image_data['ColorSpace'] = '/DeviceGray'
        pdf_image_data['Decode'] = '[1 0]'

    return pdf_image_data

  def CanUpdateImageMask(self):
    """Return bool saying whether self.UpdatePdfObj works on an /ImageMask."""
    if self.bpc != 1: return False
    if (self.color_type == 'indexed-rgb' and
        self.plte in ('\0\0\0\xff\xff\xff', '\0\0\0',
                      '\xff\xff\xff\0\0\0', '\xff\xff\xff')):
      return True
    return self.color_type == 'gray'

  def UpdatePdfObj(self, pdf_obj, do_check_dimensions=True):
    """Update the /Subtype/Image PDF XObject from self."""
    if not isinstance(pdf_obj, PdfObj): raise TypeError
    pdf_image_data = self.GetPdfImageData()
    # !! parse pdf_obj., implement PdfObj.Get (with references?), .Set with None
    if do_check_dimensions:
      assert pdf_obj.Get('Width') == pdf_image_data['Width']
      assert pdf_obj.Get('Height') == pdf_image_data['Height']
    else:
      pdf_obj.Set('Width', pdf_image_data['Width'])
      pdf_obj.Set('Height', pdf_image_data['Height'])
    if pdf_obj.Get('ImageMask'):
      assert self.CanUpdateImageMask()
      assert pdf_image_data['BitsPerComponent'] == 1
      assert pdf_image_data['ColorSpace'] == '/DeviceGray'
      pdf_obj.Set('ColorSpace', None)
      image_decode = pdf_image_data.get('Decode')
      if image_decode in (None, '[0 1]'):
        if pdf_obj.Get('Decode') == '[0 1]':
          pdf_obj.Set('Decode', None)
      elif image_decode == '[1 0]':
        # Imp: test this
        decode = pdf_obj.Get('Decode')
        if decode in (None, '[0 1]'):
          pdf_obj.Set('Decode', '[1 0]')
        elif decode == '[1 0]':
          pdf_obj.Set('Decode', None)
        else:
          assert 0, 'unknown decode value in PDF: %r' % decode
      else:
        assert 0, 'unknown decode value: %r' % image_decode
    else:
      pdf_obj.Set('BitsPerComponent', pdf_image_data['BitsPerComponent'])
      pdf_obj.Set('ColorSpace', pdf_image_data['ColorSpace'])
      pdf_obj.Set('Decode', pdf_image_data.get('Decode'))
    pdf_obj.Set('Filter', pdf_image_data['Filter'])
    pdf_obj.Set('DecodeParms', pdf_image_data.get('DecodeParms'))
    pdf_obj.Set('Length', len(pdf_image_data['.stream']))
    # Don't pdf_obj.Set('Decode', ...): it is goot as is.
    pdf_obj.stream = pdf_image_data['.stream']

  def CompressToZipPng(self):
    """Compress self.idat to self.compresson = 'zip-png'."""
    assert self
    if self.compression == 'zip-png':
      # For testing: ./pdfsizeopt.py --use-jbig2=false --use-pngout=false pts2ep.pdf 
      return self
    elif self.compression == 'zip':
      idat = zlib.decompress(self.idat)
    elif self.compression == 'none':
      idat = self.idat
    else:
      # 'zip-tiff' is too complicated now, especially for self.bpc != 8, where
      # we have fetch previous samples with bitwise operations.
      raise FormatUnsupported(
          'cannot compress %s to zip-png' % self.compression)

    # For testing: ./pdfsizeopt.py --use-jbig2=false --use-pngout=false pts2ep.pdf 
    bytes_per_row = self.bytes_per_row
    assert len(idat) % bytes_per_row == 0
    output = []
    for i in xrange(0, len(idat), bytes_per_row):
      # We don't want to optimize here (like how libpng does) by picking the
      # best predictor, i.e. the one which probably yields the smallest output.
      # PdfData.OptimizeImages has much better and faster algorithms for that.
      # For testing \0 vs \1: ./pdfsizeopt.py --use-pngout=false pts3.pdf
      output.append('\0')  # Select PNG None predictor for this row.
      output.append(idat[i : i + bytes_per_row])

    # TODO(pts): Maybe use a smaller effort? We're not optimizing anyway.
    self.idat = zlib.compress(''.join(output), 6)
    self.compression = 'zip-png'
    assert self

    return self

  def SavePng(self, file_name, do_force_gray=False):
    """Save in PNG format to specified file, update file_name."""
    print >>sys.stderr, 'info: saving PNG to %s' % (file_name,)
    assert self.CanBePngImage()
    output = ['\x89PNG\r\n\x1A\n']  # PNG signature.

    def AppendChunk(chunk_type, chunk_data):
      output.append(struct.pack('>L', len(chunk_data)))
      # This wastes memory on the string concatenation.
      # TODO(pts): Optimize memory use.
      chunk_type += chunk_data
      output.append(chunk_type)
      output.append(struct.pack('>L', zlib.crc32(chunk_type)))

    if do_force_gray:
      assert (self.color_type.startswith('indexed-') or
              self.color_type == 'gray')
      color_type_to_find = 'gray'
    else:
      color_type_to_find = self.color_type
    color_type_found = None
    for color_type in self.COLOR_TYPE_PARSE_DICT:
      if self.COLOR_TYPE_PARSE_DICT[color_type] == color_type_to_find:
        color_type_found = color_type
    assert color_type_found is not None

    AppendChunk(
        'IHDR', struct.pack(
            '>LL5B', self.width, self.height, self.bpc, color_type_found,
            0, 0, int(self.is_interlaced)))
    if self.plte is not None and color_type_to_find.startswith('indexed-'):
      AppendChunk('PLTE', self.plte)
    AppendChunk('IDAT', self.idat)
    AppendChunk('IEND', '')

    output_data = ''.join(output)
    f = open(file_name, 'wb')
    try:
      f.write(output_data)
    finally:
      f.close()
    print >>sys.stderr, 'info: written %s bytes to PNG' % len(output_data)
    self.file_name = file_name
    return self

  def Load(self, file_name):
    """Load (parts of) a PNG file to self, return self.

    Please note that this method discards possibly important PNG chunks.

    Please note that this method doesn't verify chunk CRC.

    Returns:
      self
    Raises:
      KeyError, ValueError, AssertionError, FileError, struct.error etc.:
        On error, self is possibly left in an inconsistent state, use
        self.Clear() to clean up.
    """
    print >>sys.stderr, 'info: loading image from: %s' % (file_name,)
    f = open(file_name, 'rb')
    try:
      signature = f.read(8)
      f.seek(0, 0)
      if signature.startswith('%PDF-1.'):
        self.LoadPdf(f)
      elif signature.startswith('\x89PNG\r\n\x1A\n'):
        self.LoadPng(f)
      else:
        assert 0, 'bad PNG/PDF signature in file'
    finally:
      f.close()
    self.file_name = file_name
    assert self, 'could not load valid image'
    assert not self.color_type.startswith('indexed-') or self.plte, (
        'missing PLTE data')
    if self.plte:
      print >>sys.stderr, (
          'info: loaded PNG IDAT of %s bytes and PLTE of %s bytes' %
          (len(self.idat), len(self.plte)))
    else:
      print >>sys.stderr, 'info: loaded PNG IDAT of %s bytes' % len(self.idat)
    assert self.idat, 'image data empty'
    return self

  def LoadPdf(self, f):
    """Load image data from single ZIP-compressed image in PDF.

    The features of this method is rather limited: it can load the output of
    `sam2p -c zip' and alike, but not much more.
    """
    pdf = PdfData().Load(f)
    # !! TODO(pts): proper PDF token sequence parsing
    image_obj_nums = [
        obj_num for obj_num in sorted(pdf.objs)
        if re.search(r'/Subtype\s*/Image\b', pdf.objs[obj_num].head)]
    # !! support single-color image by sam2p
    # !! image_obj_nums is empty on empty page (by sam2p)
    assert len(image_obj_nums) == 1, (
        'no single image XObject in PDF, got %r' % image_obj_nums)
    obj = pdf.objs[image_obj_nums[0]]
    if obj.Get('ImageMask'):
      colorspace = None
      # Convert imagemask generated by sam2p to indexed1
      page_objs = [pdf.objs[obj_num] for obj_num in sorted(pdf.objs) if
                   re.search(r'/Type\s*/Page\b', pdf.objs[obj_num].head)]
      assert len(page_objs) == 1, 'Page object not found for sam2p ImageMask'
      contents = page_objs[0].Get('Contents')
      match = re.match(r'(\d+)\s+0\s+R\Z', contents)
      assert match
      content_obj = pdf.objs[int(match.group(1))]
      content_stream = content_obj.GetUncompressedStream()
      content_stream = ' '.join(
          content_stream.strip(PdfObj.PDF_WHITESPACE_CHARS).split())
      number_re = r'\d+(?:[.]\d*)?'  # TODO(pts): Exact PDF number regexp.
      width = obj.Get('Width')
      height = obj.Get('Height')
      # Example content_stream, as emitted by sam2p-0.46:
      # q 0.2118 1 0 rg 0 0 m %(width)s 0 l %(width)s %(height)s l 0
      # %(height)s l F 1 1 1 rg %(width)s 0 0 %(height)s 0 0 cm /S Do Q
      content_re = (
          r'q (%(number_re)s) (%(number_re)s) (%(number_re)s) rg 0 0 m '
          r'%(width)s 0 l %(width)s %(height)s l 0 %(height)s l F '
          r'(%(number_re)s) (%(number_re)s) (%(number_re)s) rg %(width)s '
          r'0 0 %(height)s 0 0 cm\s*/[-.#\w]+ Do Q\Z' % locals())
      match = re.match(content_re, content_stream)
      assert match, 'unrecognized content stream for sam2p ImageMask'
      # TODO(pts): Clip the floats to the interval [0..1]
      color1 = (chr(int(float(match.group(1)) * 255 + 0.5)) +
                chr(int(float(match.group(2)) * 255 + 0.5)) +
                chr(int(float(match.group(3)) * 255 + 0.5)))
      color2 = (chr(int(float(match.group(4)) * 255 + 0.5)) +
                chr(int(float(match.group(5)) * 255 + 0.5)) +
                chr(int(float(match.group(6)) * 255 + 0.5)))
      # For testing:  ./pdfsizeopt.py --use-jbig2=false --use-pngout=false pts3.pdf 
      if (obj.Get('Decode') or '[0 1]').startswith('[0'):
        palette = color2 + color1
      else:
        palette = color1 + color2
      colorspace = '[/Indexed/DeviceRGB %d%s]' % (
          len(palette) / 3 - 1, PdfObj.EscapeString(palette))
      obj.Set('ColorSpace', colorspace)
      obj.Set('ImageMask', None)

    return self.LoadPdfImageObj(obj=obj, do_zip=True)

  def LoadPdfImageObj(self, obj, do_zip):
    """Load image from PDF obj to self. Doesn't modify `obj'."""
    assert obj.Get('Subtype') == '/Image'
    assert isinstance(obj.stream, str)
    idat = obj.stream
    filter = obj.Get('Filter')
    if filter not in ('/FlateDecode', None):
      raise FormatUnsupported('image in PDF is not ZIP-compressed')
    width = int(obj.Get('Width'))
    height = int(obj.Get('Height'))
    palette = None
    if obj.Get('ImageMask'):
      raise FormatUnsupported('unsupported /ImageMask')
    colorspace = obj.Get('ColorSpace')
    assert colorspace
    if colorspace in ('/DeviceRGB', '/DeviceGray'):
      pass
    elif obj.IsIndexedRgbColorSpace(colorspace):
      # Testing info: this code is run in `1591 0 obj' eurotex2006.final.pdf
      palette = obj.ParseRgbPalette(colorspace)
    else:
      raise FormatUnsupported('unsupported /ColorSpace %r' % colorspace)

    decodeparms = PdfObj(None)
    decodeparms.head = obj.Get('DecodeParms') or '<<\n>>'
    # Since we support only /FlateDecode, we don't have to support DecodeParms
    # being an array.
    assert not decodeparms.head.startswith('[')

    predictor = decodeparms.Get('Predictor')
    assert predictor is None or isinstance(predictor, int), (
        'expected integer predictor, got %r' % predictor)
    if filter is None:
      compression = 'none'
      # We ignore the predictor setting here.
      if do_zip:
        compression = 'zip'
        # TODO(pts): Would a smaller effort (compression level) suffice here?
        idat = zlib.compress(idat, 9)
    elif predictor in (1, None):
      compression = 'zip'
    elif predictor == 2:
      compression = 'zip-tiff'
    elif 10 <= predictor <= 19:
      # TODO(pts): Test this.
      compression = 'zip-png'
    else:
      assert 0, 'expected valid predictor, got %r' % predictor
    if compression in ('zip-tiff', 'zip-png'):
      pr_bpc_ok = [obj.Get('BitsPerComponent')]
      if pr_bpc_ok[-1] == 8:
        pr_bpc_ok.append(None)
      if decodeparms.Get('BitsPerComponent') not in pr_bpc_ok:
        raise FormatUnsupported('unsupported predictor /BitsPerComponent')
      if decodeparms.Get('Columns') != obj.Get('Width'):
        raise FormatUnsupported('unsupported predictor /Columns')
      if colorspace == '/DeviceRGB':
        pr_colors_ok = [3]
      else:
        pr_colors_ok = [1, None]
      if decodeparms.Get('Colors') not in pr_colors_ok:
        raise FormatUnsupported('unsupported predictor /Colors')

    self.Clear()
    self.width = width
    self.height = height
    self.bpc = obj.Get('BitsPerComponent')
    assert isinstance(self.bpc, int)
    if colorspace == '/DeviceRGB':
      assert palette is None
      self.color_type = 'rgb'
    elif colorspace == '/DeviceGray':
      assert palette is None
      self.color_type = 'gray'
    else:
      assert isinstance(palette, str)
      self.color_type = 'indexed-rgb'
      assert len(palette) % 3 == 0
    self.is_interlaced = False
    self.plte = palette
    self.compression = compression
    self.idat = idat
    assert self, 'could not load valid PDF image'
    return self

  def LoadPng(self, f):
    signature = f.read(8)
    assert signature == '\x89PNG\r\n\x1A\n', 'bad PNG/PDF signature in file'
    self.Clear()
    ihdr = None
    idats = []
    need_plte = False
    while True:
      data = f.read(8)
      if not data: break  # EOF
      assert len(data) == 8
      chunk_data_size, chunk_type = struct.unpack('>L4s', data)
      if not (chunk_type in ('IHDR', 'IDAT', 'IEND') or
              (chunk_type == 'PLTE' and need_plte)):
        # The chunk is not interesting so we skip through it.
        try:
          ofs = f.tell()
          target_ofs = ofs + chunk_data_size + 4
          f.seek(chunk_data_size + 4, 1)
          if f.tell() != target_ofs:
            raise IOError(
                'could not seek from %s to %s' % target_ofs)
        except IOError:
          # Can't seek => read.
          left = chunk_data_size + 4  # 4: length of CRC
          while left > 0:
            to_read = min(left, 65536)
            assert to_read == len(f.read(to_read))
            left -= to_read
      else:
        chunk_data = f.read(chunk_data_size)
        assert len(chunk_data) == chunk_data_size
        chunk_crc = f.read(4)
        assert len(chunk_crc) == 4
        computed_crc = struct.pack('>L', zlib.crc32(chunk_type + chunk_data))
        assert chunk_crc == computed_crc, (
            'chunk %r checksum mismatch' % chunk_type)
        if chunk_type == 'IHDR':
          assert self.width is None, 'duplicate IHDR chunk'
          # struct.unpack checks for len(chunk_data) == 5
          (self.width, self.height, self.bpc, color_type, compression_method,
           filter_method, interlace_method) = struct.unpack(
              '>LL5B', chunk_data)
          self.width = int(self.width)
          self.height = int(self.height)
          # Raise KeyError.
          self.color_type = self.COLOR_TYPE_PARSE_DICT[color_type]
          assert compression_method == 0
          assert filter_method == 0
          assert interlace_method in (0, 1)
          self.is_interlaced = bool(interlace_method)
          need_plte = self.color_type.startswith('indexed-')
        elif chunk_type == 'PLTE':
          assert need_plte, 'unexpected PLTE chunk'
          assert self.color_type == 'indexed-rgb'
          assert len(chunk_data) % 3 == 0
          assert chunk_data
          self.plte = chunk_data
          need_plte = False
        elif chunk_type == 'IDAT':
          idats.append(chunk_data)
        elif chunk_type == 'IEND':
          break  # Don't read till EOF.
        else:
          assert 0, 'not ignored chunk of type %r' % chunk_type
    self.idat = ''.join(idats)
    assert not need_plte, 'missing PLTE chunk'
    self.compression = 'zip-png'
    assert self, 'could not load valid PNG image'
    return self


class PdfData(object):

  __slots__ = ['objs', 'trailer', 'version', 'file_name', 'file_size']

  def __init__(self):
    # Maps an object number to a PdfObj
    self.objs = {}
    # None or a PdfObj of type dict. Must contain /Size (max # objs) and
    # /Root ref.
    self.trailer = None
    # PDF version string.
    self.version = '1.0'
    self.file_name = None
    self.file_size = None

  def Load(self, file_data):
    """Load PDF from file_name to self, return self."""
    # TODO(pts): Use the xref table to find objs
    # TODO(pts): Don't load the whole file to memory.
    if isinstance(file_data, str):
      print >>sys.stderr, 'info: loading PDF from: %s' % (file_data,)
      f = open(file_data, 'rb')
      try:
        data = f.read()
      finally:
        f.close()
    elif isinstance(file_data, file):
      f = file_data
      print >>sys.stderr, 'info: loading PDF from: %s' % (f.name,)
      f.seek(0, 0)
      data = f.read()  # Don't close.
    print >>sys.stderr, 'info: loaded PDF of %s bytes' % len(data)
    self.file_name = f.name
    self.file_size = len(data)
    match = re.match(r'^%PDF-(1[.]\d)\s', data)
    assert match, 'uncrecognized PDF signature'
    self.version = match.group(1)
    self.objs = {}
    self.trailer = None

    try:
      obj_starts = self.ParseUsingXref(data)
    except PdfXrefError, exc:
      print >>sys.stderr, (
          'warning: problem with xref table, finding objs anyway: %s' % exc)
      obj_starts = self.ParseWithoutXref(data)

    assert 'trailer' in obj_starts, 'no PDF trailer'
    assert len(obj_starts) > 1, 'no objects found in PDF (file corrupt?)'
    print >>sys.stderr, 'info: separated to %s objs' % (len(obj_starts) - 1)
    last_ofs = trailer_ofs = obj_starts.pop('trailer')
    trailer_data = data[trailer_ofs: trailer_ofs + 8192]
    match = re.match('(?s)trailer\s+<<(.*?)>>\s*startxref\s', trailer_data)
    assert match, 'bad trailer data: %r' % trailer_data
    self.trailer = PdfObj(None)
    # TODO(pts): No need to strip with proper PDF token sequence parsing
    self.trailer.head = '<<%s>>' % match.group(1).strip(
        PdfObj.PDF_WHITESPACE_CHARS)
    self.trailer.Set('Prev', None)
    self.trailer.Set('XRefStm', None)
    if 'xref' in obj_starts:
      last_ofs = min(trailer_ofs, obj_starts.pop('xref'))

    def ComparePair(a, b):
      return a[0].__cmp__(b[0]) or a[1].__cmp__(b[1])

    obj_items = sorted(
        [(obj_starts[obj_num], obj_num) for obj_num in obj_starts],
        ComparePair)
    if last_ofs <= obj_items[-1][0]:
      last_ofs = len(data)
    obj_items.append((last_ofs, 'last'))
    # Dictionary mapping object numbers to strings of format ``X Y obj ...
    # endobj' (+ junk).
    obj_data = dict([(obj_items[i - 1][1],
                     data[obj_items[i - 1][0] : obj_items[i][0]])
                     for i in xrange(1, len(obj_items))])
    # !! we get this for pdf_reference_1-7.pdf
    assert '' not in obj_data.values(), 'duplicate object start offset'

    # Get numbers first, so later we can resolve '/Length 42 0 R'.
    # !! TODO(pts): proper PDF token sequence parsing
    # TODO(pts): Add proper parsing, so this first pass is not needed.
    # !!
    for obj_num in obj_data:
      this_obj_data = obj_data[obj_num]
      if ('endstream' not in this_obj_data and
          '<' not in this_obj_data and
          '(' not in this_obj_data):
        self.objs[obj_num] = PdfObj(obj_data[obj_num],
                                    file_ofs=obj_starts[obj_num], )

    # Second pass once we have all length numbers.
    for obj_num in obj_data:
      if obj_num not in self.objs:
        self.objs[obj_num] = PdfObj(obj_data[obj_num], objs=self.objs,
                                    file_ofs=obj_starts[obj_num])

    return self

  @classmethod
  def ParseUsingXref(cls, data):
    """Parse a PDF file using the cross-reference table.
    
    This method doesn't consult the cross-reference table (`xref'): it just
    searches for objects looking at '\nX Y obj' strings in `data'. 

    Args:
      data: String containing the PDF file.
    Returns:
      obj_starts dicitionary, which maps object numbers (and the string
      'trailer', possibly also 'xref') to their start offsets within a file.
    Raises:
      PdfXrefError: If the cross-reference table is corrupt, but there is
        a chance to parse the file without it.
      AssertionError: If the PDF file us totally unparsable.
      NotImplementedError: If the PDF file needs parsing code not implemented.
    """
    match = re.search(r'[>\s]startxref\s+(\d+)(?:\s+%%EOF\s*)?\Z', data[-128:])
    if not match:
      raise PdfXrefError('startxref+%%EOF not found')
    xref_ofs = int(match.group(1))
    xref_head = data[xref_ofs : xref_ofs + 128]
    match = re.match(r'(\d+)\s+(\d+)\s+obj\b', xref_head)
    if match:
      raise NotImplementedError(
          'PDF-1.5 cross reference streams not implemented')
    obj_starts = {'xref': xref_ofs}
    obj_starts_rev = {}
    while True:
      xref_head = data[xref_ofs : xref_ofs + 128]
      # Maybe PDF doesn't allow multiple consecutive `xref's,
      # but we accept that.
      match = re.match(r'(xref\s+)\d+\s+\d+\s+', xref_head)
      if not match:
        raise PdfXrefError('xref table not found at %s' % xref_ofs)
      xref_ofs += match.end(1)
      while True:
        xref_head = data[xref_ofs : xref_ofs + 128]
        # Start a new subsection.
        match = re.match(r'(\d+)\s+([1-9]\d*)\s+|(xref|trailer)\s',
            xref_head)
        if not match:
          raise PdfXrefError('xref subsection syntax error')
        if match.group(3) is not None:
          break
        obj_num = int(match.group(1))
        obj_count = int(match.group(2))
        xref_ofs = xref_ofs + match.end(0)
        while obj_count > 0:
          match = re.match(
              r'(\d{10})\s\d{5}\s([nf])\s\s', data[xref_ofs : xref_ofs + 20])
          if not match:
            raise PdfXrefError('syntax error in xref entry at %s' % xref_ofs)
          if match.group(2) == 'n':
            if obj_num in obj_starts:
              raise PdfXrefError('duplicate obj %s' % obj_num)
            obj_ofs = int(match.group(1))
            if obj_ofs in obj_starts_rev:
              raise PdfXrefError('duplicate use of obj offset %s: %s and %s' %
                                 (obj_ofs, obj_starts_rev[obj_ofs], obj_num))
            obj_starts_rev[obj_ofs] = obj_num
            obj_starts[obj_num] = obj_ofs
          obj_num += 1
          obj_count -= 1
          xref_ofs += 20
      if match.group(2) == 'xref':
        # TODO(pts): Test this.
        raise NotImplementedError(
            'multiple xref sections (with generation numbers) not implemented')
      # Keep only the very first trailer.
      obj_starts.setdefault('trailer', xref_ofs)

      trailer_data = data[xref_ofs: xref_ofs + 8192]
      match = re.match('(?s)trailer\s+(<<.*?>>)\s*startxref\s', trailer_data)
      assert match, 'bad trailer data: %r' % trailer_data
      match = re.search('/Prev\s+(\d+)', match.group(1))
      if not match: break
      xref_ofs = int(match.group(1))
    return obj_starts

  @classmethod
  def ParseWithoutXref(cls, data):
    """Parse a PDF file without having a look at the cross-reference table.
    
    This method doesn't consult the cross-reference table (`xref'): it just
    searches for objects looking at '\nX Y obj' strings in `data'. 

    Args:
      data: String containing the PDF file.
    Returns:
      obj_starts dicitionary, which maps object numbers (and the string
      'trailer', possibly also 'xref') to their start offsets within a file.
    """
    # None, an int or 'trailer'.
    prev_obj_num = None
    obj_starts = {}

    for match in re.finditer(
        r'[\n\r](?:(\d+)[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+obj\b|'
        r'trailer(?=[\0\t\n\r\f ]))',
        data):
      if match.group(1) is not None:
        prev_obj_num = int(match.group(1))
        assert 0 == int(match.group(2))
      else:
        prev_obj_num = 'trailer'
      assert prev_obj_num not in obj_starts, 'duplicate obj ' + prev_obj_num
      # Skip over '\n'
      obj_starts[prev_obj_num] = match.start(0) + 1

    # TODO(pts): Learn to parse no trailer in PDF-1.5
    # (e.g. pdf_reference_1-7-o.pdf)
    assert prev_obj_num == 'trailer'
    return obj_starts

  def Save(self, file_name):
    """Save this PDf to file_name, return self."""
    obj_count = len(self.objs)
    print >>sys.stderr, 'info: saving PDF with %s objs to: %s' % (
        obj_count, file_name)
    assert obj_count
    assert self.trailer.head.startswith('<<')
    assert self.trailer.head.endswith('>>')
    f = open(file_name, 'wb')
    try:
      # Emit header.
      output = ['%PDF-', self.version, '\n%\xD0\xD4\xC5\xD0\n']

      output_size = [0]
      output_size_idx = [0]
      def GetOutputSize():
        if output_size_idx[0] < len(output):
          for i in xrange(output_size_idx[0], len(output)):
            output_size[0] += len(output[i])
          output_size_idx[0] = len(output)
        return output_size[0]

      # Dictionary mapping object numbers to 0-based offsets in the output file.
      obj_ofs = {}

      # Emit objs.
      obj_numbers = sorted(self.objs)
      assert obj_count == len(obj_numbers)
      # Number of objects including missing ones.
      for obj_num in obj_numbers:
        obj_ofs[obj_num] = GetOutputSize()
        self.objs[obj_num].AppendTo(output, obj_num)

      # Emit xref.
      xref_ofs = GetOutputSize()
      if obj_numbers[0] == 1:
        i = 0
        j = i + 1
        while j < obj_count and obj_numbers[j] - 1 == obj_numbers[j - 1]:
          j += 1
        output.append('xref\n0 %s\n0000000000 65535 f \n' % (j + 1))
        while i < j:
          output.append('%010d 00000 n \n' % obj_ofs[obj_numbers[i]])
          i += 1
      else:
        output.append('xref\n0 1\n0000000000 65535 f \n')
        i = 0

      # Add subsequent xref subsections.
      while i < obj_count:
        j = i + 1
        while j < obj_count and obj_numbers[j] - 1 == obj_numbers[j - 1]:
          j += 1
        output.append('%s %s\n' % (obj_numbers[i], j - i))
        while i < j:
          output.append('%010d 00000 n \n' % obj_ofs[obj_numbers[i]])
          i += 1

      # Emit trailer etc.
      trailer_obj = PdfObj(self.trailer)
      trailer_obj.Set('Size', obj_numbers[-1] + 1)
      trailer_obj.Set('Prev', None)
      trailer_obj.Set('XRefStm', None)
      trailer_obj.Set('Compress', None)  # emitted by Multivalent.jar
      assert trailer_obj.head.startswith('<<')
      assert trailer_obj.head.endswith('>>')
      output.append('trailer\n%s\n' % trailer_obj.head)
      output.append('startxref\n%d\n' % xref_ofs)
      output.append('%%EOF\n')  # Avoid doubling % in printf().
      print >>sys.stderr, 'info: generated %s bytes (%s)' % (
          GetOutputSize(), FormatPercent(GetOutputSize(), self.file_size))

      # TODO(pts): Don't keep enverything in memory.
      f.write(''.join(output))
    finally:
      f.close()
    # TODO(pts): Flag not to update these.
    self.file_size = GetOutputSize()
    self.file_name = file_name
    return self

  GENERIC_PROCSET = r'''
% <ProcSet>
% PostScript procset of generic PDF parsing routines
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

% TODO: use standard PDF whitespace
/_WhitespaceCharCodes << 10 true 13 true 32 true 9 true 0 true >> def

/SkipWhitespaceRead {  % <file> SkipWhitespaceRead <charcode>
  {
    dup read
    not{/invalidfileaccess /SkipWhitespaceRead signalerror}if
    dup _WhitespaceCharCodes exch known not{exit}if
    pop
  } loop
  exch pop
} bind def

/ReadWhitespaceChar {  % <file> SkipWhitespaceRead <charcode>
  read not{/invalidfileaccess /ReadWhitespaceChar signalerror}if
  dup _WhitespaceCharCodes exch known not {
    /invalidfileaccess /WhitespaceCharExpected signalerror
  } if
} bind def

/ReadStreamFile {  % <streamdict> ReadStreamFile <streamdict> <compressed-file>
  dup /Length get
  % Reading to a string would fail for >65535 bytes (this is the maximum
  % string size in PostScript)
  %string currentfile exch readstring
  %not{/invalidfileaccess /ReadStreamData signalerror}if
  currentfile exch () /SubFileDecode filter
  << /CloseSource true /Intent 0 >> /ReusableStreamDecode filter
  %dup 0 setfileposition % by default

  currentfile SkipWhitespaceRead
  (.) dup 0 3 index put exch pop  % Convert char to 1-char string.
  currentfile 8 string readstring
  not{/invalidfileaccess /ReadEndStream signalerror}if
  concatstrings  % concat (e) and (ndstream)
  (endstream) ne{/invalidfileaccess /CompareEndStream signalerror}if
  currentfile ReadWhitespaceChar pop
  currentfile 6 string readstring
  not{/invalidfileaccess /ReadEndObj signalerror}if
  (endobj) ne{/invalidfileaccess /CompareEndObj signalerror}if
  currentfile ReadWhitespaceChar pop
} bind def

% <streamdict> <compressed-file> DecompressStreamFile
% <streamdict> <decompressed-file>
/DecompressStreamFile {
  exch
  % TODO(pts): Give these parameters to the /ReusableStreamDecode in
  % ReadStreamFile.
  9 dict begin
    /Intent 2 def  % sequential access
    /CloseSource true def
    dup /Filter .knownget not {null} if dup null ne {
      dup /Filter exch def
    } if pop
    dup /DecodeParms .knownget not {null} if dup null ne {
      dup /DecodeParms exch def
    } if pop
  exch currentdict end
  % stack: <streamdict> <compressed-file> <reusabledict>
  /ReusableStreamDecode filter
} bind def

/obj {  % <objnumber> <gennumber> obj -
  pop
  save exch
  /_ObjNumber exch def
  % Imp: read <streamdict> here (not with `token', but recursively), so
  %      don't redefine `stream'
} bind def

% Sort an array, from Ghostscript's prfont.ps.
/Sort {			% <array> <lt-proc> Sort <array>
	% Heapsort (algorithm 5.2.3H, Knuth vol. 2, p. 146),
	% modified for 0-origin indexing. */
  10 dict begin
  /LT exch def
  /recs exch def
  /N recs length def
  N 1 gt {
    /l N 2 idiv def
    /r N 1 sub def {
      l 0 gt {
	/l l 1 sub def
	/R recs l get def
      } {
	/R recs r get def
	recs r recs 0 get put
	/r r 1 sub def
	r 0 eq { recs 0 R put exit } if
      } ifelse
      /j l def {
	/i j def
	/j j dup add 1 add def
	j r lt {
	  recs j get recs j 1 add get LT { /j j 1 add def } if
	} if
	j r gt { recs i R put exit } if
	R recs j get LT not { recs i R put exit } if
	recs i recs j get put
      } loop
    } loop
  } if recs end
} bind def

/NameSort {
  {dup length string cvs exch dup length string cvs gt} Sort
} bind def

% </ProcSet>

'''

  TYPE1_CONVERTER_PROCSET = r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

<<
  /CompatibilityLevel 1.4
  /SubsetFonts false   % GS ignores this for some fonts, no problem.
  /EmbedAllFonts true
  /Optimize true
>> setdistillerparams
.setpdfwrite

/stream {  % <streamdict> stream -
  ReadStreamFile DecompressStreamFile
  % <streamdict> <decompressed-file>
  exch pop
  % stack: <decompressed-file> (containing a Type1 font program)
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  count /_Count exch def  % remember stack depth instead of mark depth
  9 dict begin dup mark exch cvx exec end
  count -1 _Count 1 add {pop pop}for  % more reliable than cleartomark
  closefile
  systemdict /FontDirectory get
  dup length 0 eq {/invalidfileaccess /NoFontDefined signalerror} if
  dup length 1 gt {/invalidfileaccess /MultipleFontsDefined signalerror} if
  [exch {pop} forall] 0 get  % Convert FontDirectory to the name of our font
  dup /_OrigFontName exch def
  % stack: <fontname>
  findfont dup length dict copy
  % Let the font name be /Obj68 etc.
  dup /FullName _ObjNumber 10 string cvs
      % pad to 10 digits for object unification in FixFontNameInType1C.
      dup (0000000000) exch length neg 10 add 0 exch
      getinterval exch concatstrings
      (Obj) exch concatstrings put
  dup dup /FullName get cvn /FontName exch put

  % Replace the /Encoding array with the glyph names in /CharStrings, padded
  % with /.notdef{}s. This hack is needed for Ghostscript 8.54, which would
  % sometimes generate two (or more?) PDF font objects if not all characters
  % are encoded.
  dup /CharStrings get dup length 256 le {
    [exch {pop} forall] NameSort
    [exch aload length 1 255 {pop/.notdef} for]
    1 index exch /Encoding exch put
  } {pop} ifelse

  %dup /FID undef  % undef not needed.
  % We have to unset /OrigFont (for Ghostscript 8.61) and /.OrigFont
  % (for GhostScript 8.54) here, because otherwise Ghostscript would put
  % the /FontName defined there to the PDF object /Type/FontDescriptor , thus
  % preventing us from identifying the output font by input object number.
  dup /OrigFont undef  % undef is OK even if /OrigFont doesn't exist
  dup /.OrigFont undef  % undef is OK even if /.OrigFont doesn't exist
  dup /FontName get exch definefont
  % stack: <fake-font>
  (Type1CConverter: converting font /) print
    _OrigFontName =only
    ( to /) print
    dup /FontName get =only
    (\n) print flush
  dup /FontName get dup length string cvs
  systemdict /FontDirectory get {  % Undefine all fonts except for <fake-font>
    pop dup
    dup length string cvs 2 index eq  % Need cvs for eq comparison.
    {pop} {undefinefont} ifelse
  } forall
  pop % <fake-fontname-string>
  %systemdict /FontDirectory get {pop ===} forall

  dup setfont
  % TODO(pts): Check for embedding the base 14 fonts.
  %
  % * It is not enough to show only a few glyphs, because Ghostscript
  %   sometimes ignores /SubsetFonts=false .
  % * 200 200 moveto is needed here, otherwise some characters would be too
  %   far to the right so Ghostscript 8.61 would crop them from the page and
  %   wouldn't include them to the fonts.
  % * We have to make sure that all glyphs are on the page -- otherwise
  %   Ghostscript 8.61 becomes too smart by clipping the page and not embedding
  %   the outliers.
  dup /CharStrings get [exch {pop} forall] NameSort {
    newpath 200 200 moveto glyphshow} forall
  pop % <fake-font>
  restore
} bind def
% </ProcSet>

'''

  def GetFonts(self, font_type=None, do_obj_num_from_font_name=False):
    """Return dictionary containing Type1 /FontFile* objs.

    Args:
      font_type: 'Type1' or 'Type1C' or None
      obj_num_from_font_name: Get the obj_num (key in the returned dict) from
        the /FontName, e.g. /FontName/Obj42 --> 42.
    Returns:
      A dictionary mapping the obj number of the /Type/FontDescriptor obj to
      the PdfObj of the /FontFile* obj (with /Subtype/Type1C etc.). Please note
      that this dictionary is not a subdictionary of self.objs, because of the
      different key--value mapping.
    """
    assert font_type in ('Type1', 'Type1C', None)
    # Also: TrueType fonts have /FontFile2.
    good_font_file_tag = {'Type1': 'FontFile', 'Type1C': 'FontFile3',
                          None: None}[font_type]

    objs = {}
    font_count = 0
    duplicate_count = 0
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]
      # !! TODO(pts): proper PDF token sequence parsing
      if (#re.search(r'/Type\s*/FontDescriptor\b', obj.head) and  # !! (nonstandard) eurotex2006.final.pdf has /Type/FontDescriptor missing
          re.search(r'/FontName\s*/', obj.head) and
          '/FontFile' in obj.head and # /FontFile, /FontFile2 or /FontFile3
          '/Flags' in obj.head):
        # Type1C fonts have /FontFile3 instead of /FontFile.
        # TODO(pts): Do only Type1 fonts have /FontFile ?
        # What about Type3 fonts?
        match = re.search(r'/(FontFile[23]?)\s+(\d+)\s+0 R\b', obj.head)
        if (match and (good_font_file_tag is None or
            match.group(1) == good_font_file_tag)):
          font_file_tag = match.group(1)
          font_obj_num = int(match.group(2))
          font_obj = self.objs[font_obj_num]
          # Known values: /Type1, /Type1C, /CIDFontType0C.
          subtype = font_obj.Get('Subtype')
          if subtype is not None:
            pass
          elif font_file_tag == 'FontFile':
            subtype = '/Type1'
          elif font_file_tag == 'FontFile2':
            subtype = '/TrueType'  # TODO(pts): Find PDF standard name for this.
          assert str(subtype).startswith('/'), (
              'expected font /Subtype, got %r in obj %s' %
              (subtype, font_obj_num))
          if font_type is not None and font_type != subtype[1:]:
            pass
          elif do_obj_num_from_font_name:
            font_name = obj.Get('FontName')
            assert font_name is not None
            match = re.match(r'/(?:[A-Z]{6}[+])?Obj(\d+)\Z', font_name)
            assert match, 'GS generated non-Obj FontName: %s' % font_name
            name_obj_num = int(match.group(1))
            if name_obj_num in objs:
              print >>sys.stderr, 'error: duplicate font %s obj %d' % (
                  font_name, name_obj_num)
              duplicate_count += 1
            objs[name_obj_num] = font_obj
          else:
            objs[obj_num] = font_obj
          font_count += 1
    if font_type is None:
      print >>sys.stderr, 'info: found %s fonts' % font_count
    else:
      print >>sys.stderr, 'info: found %s %s fonts' % (font_count, font_type)
    assert not duplicate_count, (
        'found %d duplicate font objs in GS output' % duplicate_count)
    return objs

  @classmethod
  def GenerateType1CFontsFromType1(cls, objs, ps_tmp_file_name,
                                   pdf_tmp_file_name):
    if not objs: return {}
    output = ['%!PS-Adobe-3.0\n',
              '% Ghostscript helper for converting Type1 fonts to Type1C\n',
              '%% autogenerated by %s at %s\n' % (__file__, time.time())]
    output.append(cls.GENERIC_PROCSET)
    output.append(cls.TYPE1_CONVERTER_PROCSET)
    output_prefix_len = sum(map(len, output))
    type1_size = 0
    for obj_num in sorted(objs):
      type1_size += objs[obj_num].size
      objs[obj_num].AppendTo(output, obj_num)
    output.append('(Type1CConverter: all OK\\n) print flush\n%%EOF\n')
    output_str = ''.join(output)
    print >>sys.stderr, ('info: writing Type1CConverter (%s font bytes) to: %s'
        % (len(output_str) - output_prefix_len, ps_tmp_file_name))
    f = open(ps_tmp_file_name, 'wb')
    try:
      f.write(output_str)
    finally:
      f.close()

    EnsureRemoved(pdf_tmp_file_name)
    gs_cmd = (
        'gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dPDFSETTINGS=/printer '
        '-dColorConversionStrategy=/LeaveColorUnchanged '  # suppress warning
        '-sOutputFile=%s -f %s'
        % (ShellQuote(pdf_tmp_file_name), ShellQuote(ps_tmp_file_name)))
    print >>sys.stderr, ('info: executing Type1CConverter with Ghostscript'
        ': %s' % gs_cmd)
    status = os.system(gs_cmd)
    if status:
      print >>sys.stderr, 'info: Type1CConverter failed, status=0x%x' % status
      assert 0, 'Type1CConverter failed (status)'
    try:
      stat = os.stat(pdf_tmp_file_name)
    except OSError:
      print >>sys.stderr, 'info: Type1CConverter has not created output: ' % (
          pdf_tmp_file_name)
      assert 0, 'Type1CConverter failed (no output)'
    os.remove(ps_tmp_file_name)
    pdf = PdfData().Load(pdf_tmp_file_name)
    # TODO(pts): Better error reporting if the font name is wrong.
    type1c_objs = pdf.GetFonts(do_obj_num_from_font_name=True)
    assert sorted(type1c_objs) == sorted(objs), 'font obj number list mismatch'
    type1c_size = 0
    for obj_num in type1c_objs:
      # TODO(pts): Cross-check /FontFile3 with pdf.GetFonts.
      assert re.search(r'/Subtype\s*/Type1C\b', type1c_objs[obj_num].head), (
          'could not convert font %s to Type1C' % obj_num)
      type1c_size += type1c_objs[obj_num].size
    # TODO(pts): Don't remove if command-line flag.
    os.remove(pdf_tmp_file_name)
    # TODO(pts): Undo if no reduction in size.
    print >>sys.stderr, (
        'info: optimized total Type1 font size %s to Type1C font size %s '
        '(%s)' %
        (type1_size, type1c_size, FormatPercent(type1c_size, type1_size)))
    return type1c_objs

  TYPE1C_PARSER_PROCSET = r'''
% <ProcSet>
% Type1C font (CFF) parser procset
% by pts@fazekas.hu at Tue May 19 22:46:15 CEST 2009

% keys to omit from the font dictionary dump
/OMIT << /FontName 1 /FID 1 /Encoding 1 /.OrigFont 1
         /OrigFont 1 >> def

/_DataFile DataFile (w) file def  % -sDataFile=... on the command line

% Dump the specified value to the specified stream in a parable form.
% Dumps strings as hex (<...>). Dumps all arrays as [...], never {...}. The
% motivation is to dump quickly, and read it back from Python quicly. Since
% PdfObj.CompressValue called from PdfObj.ParseValueRecursive is slow on
% (...) strings, we dump strings as <...>.
/Dump { % <stream> <value> Dump -
  dup type /dicttype eq {
    1 index (<<) writestring
    { exch 2 index exch Dump
      1 index ( ) writestring
      1 index exch Dump
      dup ( ) writestring
    } forall
    (>>) writestring
  } {
    dup type /arraytype eq {
      1 index ([) writestring
      { 1 index exch Dump
        dup ( ) writestring
      } forall
      (]) writestring
    } {
      dup type /stringtype eq {
        1 index (<) writestring
        1 index exch writehexstring
        (>) writestring
      } {
        write===only
      } ifelse
    } ifelse
  } ifelse
} bind def

/stream {  % <streamdict> stream -
  ReadStreamFile DecompressStreamFile
  % <streamdict> <decompressed-file>
  systemdict /FontDirectory get {pop undefinefont} forall
  dup /MY exch /FontSetInit /ProcSet findresource begin //true ReadData
  closefile  % is this needed?
  % <streamdict>
  pop
  /MY findfont
  dup /FontType get 2 ne {/invalidfileaccess /NotType2Font signalerror} if
  _DataFile _ObjNumber write===only
  _DataFile ( <<\n) writestring
  % SUXX: the CFF /FontName got lost (overwritten by /MY above)
  {
    exch dup OMIT exch known not
    { _DataFile exch write===only
      _DataFile ( ) writestring
      _DataFile exch Dump
      _DataFile (\n) writestring} {pop pop} ifelse
  } forall
  _DataFile (>>\n) writestring
  systemdict /FontDirectory get {pop undefinefont} forall
  restore  % save created by /obj
} bind def
% </ProcSet>

'''

  TYPE1C_GENERATOR_PROCSET = r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

<<
  /CompatibilityLevel 1.4
  /SubsetFonts false   % GS ignores this for some fonts, no problem.
  /EmbedAllFonts true
  /Optimize true
>> setdistillerparams
.setpdfwrite

/endobj {  % <streamdict> endobj -
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  /_FontName _ObjNumber 10 string cvs
      % pad to 10 digits for object unification in FixFontNameInType1C.
      dup (0000000000) exch length neg 10 add 0 exch
      getinterval exch concatstrings
      (Obj) exch concatstrings cvn def
  dup /FontName _FontName put

  % Replace the /Encoding array with the glyph names in /CharStrings, padded
  % with /.notdef{}s. This hack is needed for Ghostscript 8.54, which would
  % sometimes generate two (or more?) PDF font objects if not all characters
  % are encoded.
  % TODO(pts): What if /Encoding longer than 256?
  dup /CharStrings get
      [exch {pop} forall] NameSort
      [exch aload length 1 255 {pop/.notdef} for]
      1 index exch /Encoding exch put

  _FontName exch definefont  % includes findfont
  % TODO: (Type1Generator: ...) print
  dup setfont
  % * It is not enough to show only a few glyphs, because Ghostscript
  %   sometimes ignores /SubsetFonts=false .
  % * 200 200 moveto is needed here, otherwise some characters would be too
  %   far to the right so Ghostscript 8.61 would crop them from the page and
  %   wouldn't include them to the fonts.
  % * We have to make sure that all glyphs are on the page -- otherwise
  %   Ghostscript 8.61 becomes too smart by clipping the page and not embedding
  %   the outliers.
  dup /CharStrings get [exch {pop} forall] NameSort {
    newpath 200 200 moveto glyphshow} forall
  %dup /CharStrings get {pop dup === glyphshow} forall
  %dup /CharStrings get [ exch {pop} forall ] 0 get glyphshow
  pop % <font>
  %showpage % not needed
  restore
} bind def
% </ProcSet>

'''
  @classmethod
  def ParseType1CFonts(cls, objs, ps_tmp_file_name, data_tmp_file_name):
    """Converts /Subtype/Type1C objs to data structure representation."""
    if not objs: return {}
    output = ['%!PS-Adobe-3.0\n',
              '% Ghostscript helper parsing Type1C fonts\n',
              '%% autogenerated by %s at %s\n' % (__file__, time.time())]
    output.append(cls.GENERIC_PROCSET)
    output.append(cls.TYPE1C_PARSER_PROCSET)
    output_prefix_len = sum(map(len, output))
    type1_size = 0
    for obj_num in sorted(objs):
      type1_size += objs[obj_num].size
      objs[obj_num].AppendTo(output, obj_num)
    output.append('(Type1CParser: all OK\\n) print flush\n%%EOF\n')
    output_str = ''.join(output)
    print >>sys.stderr, ('info: writing Type1CParser (%s font bytes) to: %s'
        % (len(output_str) - output_prefix_len, ps_tmp_file_name))
    f = open(ps_tmp_file_name, 'wb')
    try:
      f.write(output_str)
    finally:
      f.close()

    EnsureRemoved(data_tmp_file_name)
    gs_cmd = (
        'gs -q -dNOPAUSE -dBATCH -sDEVICE=nullpage '
        '-sDataFile=%s -f %s'
        % (ShellQuote(data_tmp_file_name), ShellQuote(ps_tmp_file_name)))
    print >>sys.stderr, ('info: executing Type1CParser with Ghostscript'
        ': %s' % gs_cmd)
    status = os.system(gs_cmd)
    if status:
      print >>sys.stderr, 'info: Type1CParser failed, status=0x%x' % status
      assert 0, 'Type1CParser failed (status)'
    try:
      stat = os.stat(data_tmp_file_name)
    except OSError:
      print >>sys.stderr, 'info: Type1CParser has not created output: ' % (
          data_tmp_file_name)
      assert 0, 'Type1CParser failed (no output)'
    # ps_tmp_file_name is usually about 5 times as large as the input of
    # Type1CParse (pdf_tmp_file_name)
    os.remove(ps_tmp_file_name)
    f = open(data_tmp_file_name)
    try:
      data = f.read()
    finally:
      f.close()
    # Dict keys are numbers, which is not valid PDF, but ParseValueRecursive
    # accepts it.
    # TODO(pts): This ParseValueRecursive call is a bit slow, speed it up.
    data_objs = PdfObj.ParseValueRecursive('<<%s>>' % data)
    assert isinstance(data_objs, dict)
    print >>sys.stderr, 'info: parsed %s Type1C fonts' % len(data_objs)
    assert sorted(data_objs) == sorted(objs), 'data obj number list mismatch'
    os.remove(data_tmp_file_name)
    return data_objs

  def ConvertType1FontsToType1C(self):
    """Convert all Type1 fonts to Type1C in self, returns self."""
    # !! proper tmp prefix
    type1c_objs = self.GenerateType1CFontsFromType1(
        self.GetFonts('Type1'), 'type1cconv.tmp.ps', 'type1cconv.tmp.pdf')
    for obj_num in type1c_objs:
      obj = self.objs[obj_num]
      assert str(obj.Get('FontName')).startswith('/')
      type1c_obj = type1c_objs[obj_num]
      # !! fix in genuine Type1C objects as well
      type1c_obj.FixFontNameInType1C()
      match = re.search(r'/FontFile\s+(\d+)\s+0 R\b', obj.head)
      assert match
      font_file_obj_num = int(match.group(1))
      new_obj_head = (
          obj.head[:match.start(0)] +
          '/FontFile3 %d 0 R' % font_file_obj_num +
          obj.head[match.end(0):])
      old_size = self.objs[font_file_obj_num].size + obj.size
      new_size = type1c_obj.size + (
          obj.size + len(new_obj_head) - len(obj.head))
      if new_size < old_size:
        obj.head = new_obj_head
        self.objs[font_file_obj_num] = type1c_obj
        print >>sys.stderr, (
            'info: optimized Type1 font XObject %s,%s: new size=%s (%s)' %
            (obj_num, font_file_obj_num, new_size,
             FormatPercent(new_size, old_size)))
      else:
        # TODO(pts): How to optimize/unify these?
        print >>sys.stderr, (
            'info: keeping original Type1 font XObject %s,%s, '
            'replacement too large: old size=%s, new size=%s' %
            (obj_num, font_file_obj_num, old_size, new_size))
    return self

  @classmethod
  def MergeTwoType1CFontDescriptors(cls, target_fd, source_fd):
    """Merge two /FontDescriptor objs.

    The entry for /CharSet and some other optional or unimportant entries
    are left untouched in target_fd.

    Raise:
      target_font: A PdfObj of /Type/FontDescriptor, will be modified in place.
      source_font: A PdfObj of /Type/FontDescriptor.
    Raises:
      FontsNotMergeable:
    """
    for key in ('Flags', 'StemH'):
      target_value = target_fd.Get(key)
      source_value = source_fd.Get(key)
      if target_value != source_value:
        # TODO(pts): Show the object numbers in the exception.
        raise FontsNotMergeable(
            'different /%s values: target=%s source=%s' %
            (key, target_value, source_value))

    source_bbox_str = PdfObj.ParseArray(source_fd.Get('FontBBox'))
    target_bbox_str = PdfObj.ParseArray(target_fd.Get('FontBBox'))
    if source_bbox_str != target_bbox_str:
      source_bbox = map(PdfObj.GetNumber, source_bbox_str)
      target_bbox = map(PdfObj.GetNumber, target_bbox_str)
      if source_bbox != target_bbox:
        # For testing: font GaramondNo8Reg in eurotex2006.final.pdf 
        target_bbox[0] = min(target_bbox[0], source_bbox[0])  # llx
        target_bbox[1] = min(target_bbox[1], source_bbox[1])  # lly
        target_bbox[2] = max(target_bbox[2], source_bbox[2])  # urx
        target_bbox[3] = max(target_bbox[3], source_bbox[3])  # ury

    for key in ('ItalicAngle', 'Ascent', 'Descent', 'MissingWidth'):
      # It is not important for these required entries to match, so we just
      # copy from source if the value is missing from destination.
      target_value = target_fd.Get(key)
      if target_value is None:
        source_value = source_fd.Get(key)
        if source_value is not None:
          target_fd.Set(key, source_value)

  @classmethod
  def MergeTwoType1CFonts(cls, target_font, source_font):
    """Merge source_font to target_font, modifying the latter in place.

    Example parsed Type1C font dictionary:

      {'FontName': '/LNJXBX+GaramondNo8-Reg',
       'FontMatrix': ['0.001', 0, 0, '0.001', 0, 0],
       'Private': {'StemSnapH': [33, 39], 'StdHW': [33], 'BlueValues': [-20, 0, 420, 440, 689, 709], 'StemSnapV': [75, 89], 'StdVW': [75]},
       'FontType': 2,
       'PaintType': 0,
       'FontInfo': {
           'Notice': '...',
           'Copyright': '...',
           'FamilyName': 'GaramondNo8',
           'UnderlinePosition': 0,
           'UnderlineThickness': 0,
           'FullName': 'GaramondNo8 Regular'},
       'CharStrings': {'udieresis': '...' ...}}
    
    Raise:
      target_font: A parsed Type1C font dictionary, will be modified in place.
      source_font: A parsed Type1C font dictionary.
    Raises:
      FontsNotMergeable:
    """
    assert 'Subrs' not in target_font
    assert 'Subrs' not in target_font['Private']  # !! not mergeable
    assert 'Subrs' not in source_font
    assert 'Subrs' not in source_font['Private']  # !! not mergeable
    # Our caller should take care of removing FontBBox.
    assert 'FontBBox' not in source_font
    assert 'FontBBox' not in target_font
    # !! proper check for FontMatrix floats.
    # We ignore FontInfo and UniqueID.
    for key in ('FontMatrix', 'Private', 'FontType', 'PaintType'):
      target_value = target_font[key]
      source_value = source_font[key]
      if target_value != source_value:
        raise FontsNotMergeable('mismatch in key %s: target=%r source=%r' %
            (key, target_value, source_value))
    target_cs = target_font['CharStrings']
    source_cs = source_font['CharStrings']
    for name in sorted(source_cs):
      if name in target_cs and source_cs[name] != target_cs[name]:
        raise FontsNotMergeable('mismatch on char /%s' % name)

    # Only modify after doing all the checks.
    target_cs.update(source_cs)

  def UnifyType1CFonts(self, do_keep_font_optionals,
                       do_double_check_missing_glyphs,
                       do_regenerate_all_fonts):
    """Unify different subsets of the same Type1C font.

    Returns:
      self.
    """
    type1c_objs = self.GetFonts(font_type='Type1C')
    if not type1c_objs:
      return self

    orig_type1c_size = 0
    for obj_num in sorted(type1c_objs):
      obj = self.objs[obj_num]  # /Type/FontDescriptor
      assert obj.stream is None
      assert obj.Get('Flags') is not None
      assert obj.Get('StemV') is not None
      assert str(obj.Get('FontName')).startswith('/')
      assert str(obj.Get('FontBBox')).startswith('[')
      # These entries are important only for finding substitute fonts, so
      # we can get rid of them.
      obj.Set('FontFamily', None)
      obj.Set('FontStretch', None)
      obj.Set('FontWeight', None)
      obj.Set('Leading', None)
      obj.Set('XHeight', None)
      obj.Set('StemH', None)
      obj.Set('AvgWidth', None)
      obj.Set('MaxWidth', None)
      orig_type1c_size += type1c_objs[obj_num].size + obj.size

    # Merge byte-by-byte identical fonts.
    duplicate_count = 0
    h = {}
    for obj_num in sorted(type1c_objs):
      type1c_obj = type1c_objs[obj_num]
      head_dict = PdfObj.ParseDict(type1c_obj.head)
      assert head_dict['Subtype'] == '/Type1C'
      try:
        stream = type1c_obj.GetUncompressedStream()
        head_dict.clear()
      except FilterNotImplementedError:
        stream = type1c_obj.stream
        for key in sorted(head_dict):
          if key != 'Filter' and key != 'DecodeParms':
            del head_dict[key]
      key = (PdfObj.SerializeDict(head_dict), stream)
      data_len = len(key[0]) + len(key[1])
      if key in h:
        h[key].append((data_len, obj_num))
      else:
        h[key] = [(data_len, obj_num)]
    for key in h:
      same_type1c_objs = h[key]
      if len(same_type1c_objs) < 2:
        continue
      # For testing: tuzv.pdf
      # Use sort() instead of min(...) to find the smallest tuple, min(...)
      # is buggy on tuples.
      same_type1c_objs.sort()  # smallest first
      master_obj_num = None
      for data_len, obj_num in same_type1c_objs:
        obj = self.objs[obj_num]
        target_obj_num = PdfObj.GetReferenceTarget(obj.Get('FontFile3'))
        assert (
            target_obj_num is not None and
            self.objs[target_obj_num] is type1c_objs[obj_num]), (
            'bad /FontFile3 target in %s' % obj_num)
        if master_obj_num is None:
          master_obj_num = target_obj_num
        elif master_obj_num != target_obj_num:
          obj.Set('FontFile3', '%s 0 R' % master_obj_num)
          # TODO(pts): What if self.objs has another reference to
          # target_obj_num, which is not coming from /FontDescriptor{}s?
          del self.objs[target_obj_num]
          duplicate_count += 1
    h.clear()
    if duplicate_count:
      print >>sys.stderr, 'info: eliminated %s duplicate /Type1C font data' % (
          duplicate_count)

    parsed_fonts = self.ParseType1CFonts(
        objs=type1c_objs, ps_tmp_file_name='type1cconv.parse.tmp.ps',
        data_tmp_file_name='type1cconv.parsedata.tmp.ps')
    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    garas = []  # !!!
    gara_obj_nums = []
    for obj_num in sorted(parsed_fonts):
      obj = self.objs[obj_num]  # /Type/FontDescriptor
      assert obj.stream is None
      parsed_font = parsed_fonts[obj_num]
      parsed_font['FontName'] = obj.Get('FontName')
      assert parsed_font['FontType'] == 2
      assert 'CharStrings' in parsed_font
      assert 'FontMatrix' in parsed_font
      assert 'Private' in parsed_font
      assert 'PaintType' in parsed_font
      assert 'FontInfo' in parsed_font  # !! delete eventually
      assert 'CharStrings' in parsed_font
      assert 'Subrs' not in parsed_font  # !! add a test for Subrs, maybe not in toplevel dict; maybe not dumped (because of noexec? -- but other parts of private are dumped)
      assert 'Subrs' not in parsed_font['Private']
      if 'FontBBox' in parsed_font:
        # This is part of the /FontDescriptor, we don't need it in the Type1C
        # font.
        del parsed_font['FontBBox']
      if parsed_font['FontName'].endswith('+GaramondNo8-Reg'):
        gara_obj_nums.append(obj_num)
        garas.append(parsed_font)
      # Extra, not checked: 'UniqueID'
      #print parsed_font['FontName']
    if len(garas) < 2:  # !!!
      for obj_num in sorted(type1c_objs):
        type1c_objs[obj_num].FixFontNameInType1C(do_always_recompress=True)
      return self
    assert len(gara_obj_nums) >= 2
    merged_font = garas[0]
    # /Type/FontDescriptor
    merged_fontdesc_obj = PdfObj(self.objs[gara_obj_nums[0]])
    orig_char_count = len(merged_font['CharStrings'])
    for i in xrange(1, len(garas)):
      obj = self.objs[gara_obj_nums[i]]  # /Type/FontDescriptor
      orig_char_count += len(garas[i]['CharStrings'])
      print 'MERGING', garas[i]['FontName']  # !!!
      # !!! handle exceptions (FontsNotMergeable)
      self.MergeTwoType1CFontDescriptors(merged_fontdesc_obj, obj)
      self.MergeTwoType1CFonts(merged_font, garas[i])
    # pdf_reference_1-7.pdf requires /type/FontDescriptor.
    merged_fontdesc_obj.Set('Type' , '/FontDescriptor')
    if do_keep_font_optionals:
      # !! remove more optionals
      # New Ghostscript doesn't generate /CharSet. We don't generate it either,
      # unless the user asks for it.
      merged_fontdesc_obj.Set(
          'CharSet', PdfObj.EscapeString(''.join(
              ['/' + name for name in sorted(merged_font['CharStrings'])])))
    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    if do_regenerate_all_fonts:
      unified_obj_nums = set(type1c_objs)
    else:
      unified_obj_nums = set()
    unified_obj_nums.add(gara_obj_nums[0])
    for i in xrange(1, len(garas)):
      gara_obj_num = gara_obj_nums[i]
      obj = self.objs[gara_obj_num]  # /Type/FontDescriptor
      # !! merge /Type/Font objects (including /FirstChar, /LastChar and
      # /Widths)
      obj.head = merged_fontdesc_obj.head
      assert obj.stream is None
      del type1c_objs[gara_obj_num]
      del parsed_fonts[gara_obj_num]
      if gara_obj_num in unified_obj_nums:
        unified_obj_nums.remove(gara_obj_num)
      # Don't del `self.objs[gara_obj_nums[i]]' yet, because that object may
      # be referenced from another /Font. self.OptimizeObjs() will clean up
      # unreachable objs safely.
    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    new_char_count = len(merged_font['CharStrings'])
    print >>sys.stderr, ('info: merged fonts like %s from %s to %s chars (%s)' 
        % (merged_font['FontName'], orig_char_count, new_char_count,
           FormatPercent(new_char_count, orig_char_count)))
    self.objs[gara_obj_nums[0]].head = merged_fontdesc_obj.head

    if not unified_obj_nums:
      print >>sys.stderr, 'info: no fonts to regenerate or unify'
      # TODO(pts): Don't recompress if already recompressed (e.g. when
      # converted from Type1).
      for obj_num in sorted(type1c_objs):
        type1c_objs[obj_num].FixFontNameInType1C(do_always_recompress=True)
      return self

    def AppendSerialized(value, output):
      if isinstance(value, list):
        output.append('[')
        for item in value:
          AppendSerialized(item, output)
          output.append(' ')
        output.append(']')
      elif isinstance(value, dict):
        output.append('<<')
        for item in sorted(value):
          if isinstance(item, str):
            output.append('/' + item)
          else:
            AppendSerialized(item, output)
          output.append(' ')
          AppendSerialized(value[item], output)
          output.append(' ')
        output.append('>>')
      elif value is None:
        output.append('null ')
      elif value is True:
        output.append('true ')
      elif value is False:
        output.append('false ')
      else:
        output.append(str(value))
        output.append(' ')

    # !! fix the /BaseFont in /Font (PDF spec says they must be identical)
    output = ['%!PS-Adobe-3.0\n',
              '% Ghostscript helper generating Type1C fonts\n',
              '%% autogenerated by %s at %s\n' % (__file__, time.time())]
    output.append(self.GENERIC_PROCSET)
    output.append(self.TYPE1C_GENERATOR_PROCSET)
    output_prefix_len = sum(map(len, output))
    for obj_num in sorted(unified_obj_nums):
      output.append('%s 0 obj' % obj_num)
      if gara_obj_nums[0] == obj_num:
        assert merged_font is parsed_fonts[obj_num]
      AppendSerialized(parsed_fonts[obj_num], output)
      output.append('endobj\n')
    output.append('(Type1CGenerator: all OK\\n) print flush\n%%EOF\n')
    ps_tmp_file_name = 'type1cconv.type1cgen.tmp.ps'
    pdf_tmp_file_name = 'type1cconv.type1cgen.tmp.pdf'
    output_str = ''.join(output)
    print >>sys.stderr, ('info: writing Type1CGenerator (%s font bytes) to: %s'
        % (len(output_str) - output_prefix_len, ps_tmp_file_name))
    f = open(ps_tmp_file_name, 'wb')
    try:
      f.write(output_str)
    finally:
      f.close()

    EnsureRemoved(pdf_tmp_file_name)
    gs_cmd = (
        'gs -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dPDFSETTINGS=/printer '
        '-dColorConversionStrategy=/LeaveColorUnchanged '  # suppress warning
        '-sOutputFile=%s -f %s'
        % (ShellQuote(pdf_tmp_file_name), ShellQuote(ps_tmp_file_name)))
    print >>sys.stderr, ('info: executing Type1CGenerator with Ghostscript'
        ': %s' % gs_cmd)
    status = os.system(gs_cmd)
    if status:
      print >>sys.stderr, 'info: Type1CGenerator failed, status=0x%x' % status
      assert 0, 'Type1CGenerator failed (status)'
    try:
      stat = os.stat(pdf_tmp_file_name)
    except OSError:
      print >>sys.stderr, 'info: Type1CGenerator has not created output: ' % (
          pdf_tmp_file_name)
      assert 0, 'Type1CGenerator failed (no output)'
    pdf = PdfData().Load(pdf_tmp_file_name)
    # TODO(pts): Better error reporting if the font name is wrong.
    loaded_objs = pdf.GetFonts(do_obj_num_from_font_name=True)
    assert sorted(loaded_objs) == sorted(unified_obj_nums), (
        'font obj number list mismatch: loaded=%r expected=%s' %
        (sorted(loaded_objs), sorted(type1c_objs)))
    for obj_num in loaded_objs:
      loaded_obj = loaded_objs[obj_num]
      # TODO(pts): Cross-check /FontFile3 with pdf.GetFonts.
      assert re.search(r'/Subtype\s*/Type1C\b', loaded_obj.head), (
          'could not convert font %s to Type1C' % obj_num)
      loaded_obj.FixFontNameInType1C(do_always_recompress=True)
      type1c_objs[obj_num].head = loaded_obj.head
      type1c_objs[obj_num].stream = loaded_obj.stream
    for obj_num in sorted(set(type1c_objs).difference(loaded_objs)):
      type1c_objs[obj_num].FixFontNameInType1C(do_always_recompress=True)

    new_type1c_size = 0
    for obj_num in type1c_objs:
      new_type1c_size += type1c_objs[obj_num].size + self.objs[obj_num].size

    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    if do_double_check_missing_glyphs:
      parsed2_fonts = self.ParseType1CFonts(
          objs=loaded_objs, ps_tmp_file_name='type1cconv.parse2.tmp.ps',
          data_tmp_file_name='type1cconv.parse2data.tmp.ps')
      assert sorted(parsed_fonts) == sorted(type1c_objs), (
          'font obj number list mismatch: loaded=%r expected=%s' %
          (sorted(parsed_fonts), sorted(type1c_objs)))
      for obj_num in sorted(loaded_objs):
        parsed_font = parsed_fonts[obj_num]
        parsed2_font = parsed2_fonts[obj_num]
        cs = sorted(parsed_font['CharStrings'])
        cs2 = sorted(parsed2_font['CharStrings'])
        assert not set(cs2).difference(cs)
        assert cs == cs2, (
            'missing glyphs from font %s: %r --> %r' %
            (self.objs[obj_num].Get('FontName'), cs, cs2))

    # TODO(pts): Don't remove if command-line flag.
    os.remove(ps_tmp_file_name)
    os.remove(pdf_tmp_file_name)
    # TODO(pts): Undo if no reduction in size.
    print >>sys.stderr, (
        'info: optimized Type1C fonts to size %s (%s)' % (
        (new_type1c_size, FormatPercent(new_type1c_size, orig_type1c_size))))
    return self

  @classmethod
  def ConvertImage(cls, sourcefn, targetfn, cmd_pattern, cmd_name,
                   do_just_read=False):
    """Converts sourcefn to targetfn using cmd_pattern, returns ImageData."""
    if not isinstance(sourcefn, str): raise TypeError
    if not isinstance(targetfn, str): raise TypeError
    if not isinstance(cmd_pattern, str): raise TypeError
    if not isinstance(cmd_name, str): raise TypeError
    sourcefnq = ShellQuoteFileName(sourcefn)
    targetfnq = ShellQuoteFileName(targetfn)
    cmd = cmd_pattern % locals()
    EnsureRemoved(targetfn)
    assert os.path.isfile(sourcefn)

    print >>sys.stderr, ('info: executing image optimizer %s: %s' %
        (cmd_name, cmd))
    status = os.system(cmd)
    if status:
      print >>sys.stderr, 'info: %s failed, status=0x%x' % (cmd_name, status)
      assert 0, '%s failed (status)' % cmd_name
    assert os.path.exists(targetfn), (
        '%s has not created the output image %r' % (cmd_name, targetfn))
    if do_just_read:
      f = open(targetfn)
      try:
        return cmd_name, f.read()
      finally:
        f.close()
    else:
      return cmd_name, ImageData().Load(targetfn)

  def AddObj(self, obj):
    """Add PdfObj to self.objs, return its object number."""
    if not isinstance(obj, PdfObj):
      raise TypeError
    obj_num = len(self.objs) + 1
    if obj_num in self.objs:
      obj_num = max(self.objs) + 1
    self.objs[obj_num] = obj
    return obj_num

  INLINE_IMAGE_UNABBREVIATIONS = {
      'BPC': 'BitsPerComponent',
      'CS': 'ColorSpace',
      'D': 'Decode',
      'DP': 'DecodeParms',
      'F': 'Filter',
      'H': 'Height',
      'W': 'Width',
      'IM': 'ImageMask',
      'I': 'Interpolate',  # ambiguous for Indexed
      'G': 'DeviceGray',
      'RGB': 'DeviceRGB',
      'CMYK': 'DeviceCMYK',
      'AHx': 'ASCIIHexDecode',
      'A85': 'ASCII85Decode',
      'LZW': 'LZWDecode',
      'Fl': 'FlateDecode',
      'RL': 'RunLengthDecode',
      'CCF': 'CCITTFaxDecode',
      'DCT': 'DCTDecode',
  }
  """Maps an abbreviated name (in an inline image) to its full equivalent.

  From table 4.43, 4.44, ++ on page 353 of pdf_reference_1-7.pdf .
  """

  def ConvertInlineImagesToXObjects(self):
    """Convert embedded inline images to Image XObject{}s.

    This method finds only Form XObject{}s which contain a single inline
    image, and converts them to Image XObject{}s. Such Form XObject{}s are
    created by sam2p with the default config (e.g. without `sam2p -pdf:2').

    The reason why we want to have Image XObject{}s is so that we can
    optimize them and unify them in self.OptimizeImages(). Embedded Image
    XObject{}s are usually a few dozen bytes smaller than their corresponding
    Form XObject{}s.

    !! TODO(pts): Do this for single content-streams of a sam2p-generated
    .pdf image. (pts2a.pdf)

    TODO(pts): Convert all kinds of inline images.
    
    Returns:
      self.
    """
    uninline_count = 0
    uninline_bytes_saved = 0
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]

      # TODO(pts): Is re.search here fast enough?; PDF comments?
      if (not re.search(r'/Subtype[\0\t\n\r\f ]*/Form\b', obj.head) or
          not obj.head.startswith('<<') or
          not obj.stream is not None or
          obj.Get('Subtype') != '/Form' or
          obj.Get('FormType', 1) != 1 or
          obj.Get('Filter') not in (None, '/FlateDecode') or
          obj.Get('DecodeParms') is not None or
          not str(obj.Get('BBox')).startswith('[')): continue

      bbox = map(PdfObj.GetNumber, PdfObj.ParseArray(obj.Get('BBox')))
      if (len(bbox) != 4 or bbox[0] != 0 or bbox[1] != 0 or
          bbox[2] is None or bbox[2] < 1 or bbox[2] != int(bbox[2]) or
          bbox[3] is None or bbox[3] < 1 or bbox[3] != int(bbox[3])):
        continue
      width = int(bbox[2])
      height = int(bbox[3])

      stream = obj.GetUncompressedStream()
      # TODO(pts): Match comments etc.
      match = re.match(
          r'q[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+0[\0\t\n\r\f ]+0[\0\t\n\r\f ]+'
          r'(\d+)[\0\t\n\r\f ]+0[\0\t\n\r\f ]+0[\0\t\n\r\f ]+cm[\0\t\n\r\f ]+'
          r'BI[\0\t\n\r\f ]*(/(?s).*?)ID(?:\r\n|[\0\t\n\r\f ])', stream)
      if not match: continue
      if int(match.group(1)) != width or int(match.group(2)) != height:
        continue
      # Run CompressValue so we get it normalized, and we can do easier
      # regexp matches and substring searches.
      inline_dict = PdfObj.CompressValue(
          match.group(3), do_emit_strings_as_hex=True)
      stream_start = match.end()

      stream_tail = stream[-16:]
      # TODO(pts): What if \r\n in front of EI? We don't support that.
      match = re.search(
          r'[\0\t\n\r\f ]EI[\0\t\n\r\f ]+Q[\0\t\n\r\f ]*\Z', stream_tail)
      if not match: continue
      stream_end = len(stream) - len(stream_tail) + match.start()
      stream = stream[stream_start : stream_end]

      inline_dict = re.sub(
          r'/([A-Za-z]+)\b',
          lambda match: '/' + self.INLINE_IMAGE_UNABBREVIATIONS.get(
              match.group(1), match.group(1)), inline_dict)
      image_obj = PdfObj('0 0 obj<<%s>>endobj' % inline_dict)
      if (image_obj.Get('Width') != width or
          image_obj.Get('Height') != height):
        continue

      # For testing: obj 2 in pts2e.pdf
      uninline_count += 1
      colorspace = image_obj.Get('ColorSpace')
      assert colorspace is not None
      assert (image_obj.Get('BitsPerComponent') is not None or
              image_obj.Get('ImageMask', False) is True)
      #if image_obj.Get('Filter') == '/FlateDecode':
      # If we do a zlib.decompress(stream) now, it will succeed even if stream
      # has trailing garbage. But zlib.decompress(steram[:-1]) would fail. In
      # Python, there is no way the get te real end on the compressed zlib
      # stream (see also http://www.faqs.org/rfcs/rfc1950.html and
      # http://www.faqs.org/rfcs/rfc1951.html). We may just check the last
      # 4 bytes (adler32).
      if colorspace.startswith('[/Interpolate/'):
        # Fix bad decoding in INLINE_IMAGE_UNABBREVIATIONS
        colorspace = '[/Indexed' + colorspace[13:]
        image_obj.Set('ColorSpace', colorspace)
      # TODO(pts): Get rid of /Type/XObject etc. from other objects as well
      image_obj.Set('Type', None)  # /XObject, but optimized
      image_obj.Set('Subtype', '/Image')
      image_obj.Set('Length', len(stream))
      image_obj.head = PdfObj.CompressValue(image_obj.head)
      image_obj.stream = stream
      # We cannot just replace obj by image_obj here, because we have to scale
      # (with the `cm' operator).
      image_obj_num = self.AddObj(image_obj)
      resources_obj = PdfObj(
          '0 0 obj %s endobj' % obj.Get('Resources', '<<>>'))
      assert resources_obj.Get('XObject') is None
      resources_obj.Set('XObject', '<</S %s 0 R>>'% image_obj_num)
      form_obj = PdfObj('0 0 obj<</Subtype/Form>>endobj')
      form_obj.stream = 'q %s 0 0 %s 0 0 cm/S Do Q' % (width, height)
      form_obj.Set('BBox', '[0 0 %s %s]' % (width, height))
      form_obj.Set('Resources', resources_obj.head)
      form_obj.Set('Length', len(form_obj.stream))
      form_obj.head = PdfObj.CompressValue(form_obj.head)
      uninline_bytes_saved += obj.size - form_obj.size - image_obj.size
      # Throw away /Type, /Subtype/Form, /FormType, /PTEX.FileName,
      # /PTEX.PageNumber, /BBox and /Resources (and many others).
      self.objs[obj_num] = form_obj
      self.objs[image_obj_num] = image_obj

    if uninline_count > 0:
      # Usually a little negative, like -50 for each image. But since
      # self.OptimizeImages() will recompress the image, we'll gain more than
      # 50 bytes.
      print >>sys.stderr, 'info: uninlined %s images, saved %s bytes' % (
          uninline_count, uninline_bytes_saved)
    return self

  # For testing: pts2.lzw.pdf
  IMAGE_RENDERER_PROCSET = r'''
% <ProcSet>
% PDF image renderer procset
% Sun Apr  5 15:58:02 CEST 2009

/stream {  % <streamdict> stream -
  ReadStreamFile
  % stack: <streamdict> <compressed-file>

  1 index
    (ImageRenderer: rendering image XObject ) print _ObjNumber =only
    ( width=) print dup /Width get =only
    ( height=) print dup /Height get =only
    ( bpc=) print dup /BitsPerComponent get =only
    ( colorspace=) print dup /ColorSpace get
       % Show [/Indexed /DeviceRGB] instead of longer array.
       dup type /arraytype eq {dup length 2 gt {0 2 getinterval}if }if ===only
    ( filter=) print dup /Filter .knownget not {null} if ===only
    ( decodeparms=) print dup /DecodeParms .knownget not {null} if ===only
    ( device=) print currentpagedevice
      /OutputDevice get dup length string cvs print
    (\n) print flush
  pop
  % stack: <streamdict> <compressed-file>
  DecompressStreamFile
  % stack: <streamdict> <decompressed-file> (containing image /DataSource)

  9 dict begin  % Image dictionary
  /DataSource exch def
  % Stack: <streamdict>
  dup /BitsPerComponent get /BitsPerComponent exch def
  dup /Width get /Width exch def
  dup /Height get /Height exch def
  %dup /Decode .knownget {/Decode exch def} if
  dup /ColorSpace get dup type /arraytype eq {
    dup 0 get /Indexed eq {
      % For /Indexed, set /Decode [0 x], where x == (1 << BitsPerComponent) - 1
      /Decode [0 4 index /BitsPerComponent get 1 exch bitshift 1 sub] def
    } if
  } if pop
  % We cannot affect the file name of -sOutputFile=%d.png , doing a
  % ``<< /PageCount ... >> setpagedevice'' has no effect.
  % It's OK to change /PageSize for each page.
  << /PageSize [Width Height] >> setpagedevice
  % This must come after setpagedevice to take effect.
  dup /ColorSpace get setcolorspace
  /ImageType 1 def
  dup /Height get [1 0 0 -1 0 0] exch 5 exch 3 copy put pop pop
      /ImageMatrix exch def
  DataSource
  currentdict end
  % Stack: <streamdict> <datasource> <psimagedict>
  image showpage
  closefile
  % Stack: <streamdict>
  pop restore
} bind def
% </ProcSet>

'''

  @classmethod
  def RenderImages(cls, objs, ps_tmp_file_name, png_tmp_file_pattern,
                   gs_device):
    """Returns: dictionary mapping obj_num to PNG filename."""
    if not objs: return {}
    output = ['%!PS-Adobe-3.0\n',
              '% Ghostscript helper rendering PDF images as PNG\n',
              '%% autogenerated by %s at %s\n' % (__file__, time.time())]
    output.append(cls.GENERIC_PROCSET)
    output.append(cls.IMAGE_RENDERER_PROCSET)
    output_prefix_len = sum(map(len, output))
    image_size = 0
    sorted_objs = sorted(objs)
    for obj_num in sorted_objs:
      image_size += objs[obj_num].size
      objs[obj_num].AppendTo(output, obj_num)
    output.append('(ImageRenderer: all OK\\n) print flush\n%%EOF\n')
    output_str = ''.join(output)
    print >>sys.stderr, ('info: writing ImageRenderer (%s image bytes) to: %s'
        % (len(output_str) - output_prefix_len, ps_tmp_file_name))
    f = open(ps_tmp_file_name, 'wb')
    try:
      f.write(output_str)
    finally:
      f.close()

    # Remove old PNG output files.
    i = 0
    while True:
      i += 1
      png_tmp_file_name = png_tmp_file_pattern % i
      if not os.path.exists(png_tmp_file_name): break
      EnsureRemoved(png_tmp_file_name)
      assert not os.path.exists(png_tmp_file_name)

    gs_cmd = (
        'gs -q -dNOPAUSE -dBATCH -sDEVICE=%s '
        '-sOutputFile=%s -f %s'
        % (ShellQuote(gs_device),
           ShellQuote(png_tmp_file_pattern), ShellQuote(ps_tmp_file_name)))
    print >>sys.stderr, ('info: executing ImageRenderer with Ghostscript'
        ': %s' % gs_cmd)
    status = os.system(gs_cmd)
    if status:
      print >>sys.stderr, 'info: ImageRenderer failed, status=0x%x' % status
      assert 0, 'ImageRenderer failed (status)'
    assert not os.path.exists(png_tmp_file_pattern % (len(objs) + 1)), (
        'ImageRenderer created too many PNGs')

    png_files = {}
    i = 0
    for obj_num in sorted_objs:
      i += 1
      png_tmp_file_name = png_tmp_file_pattern % i
      try:
        stat = os.stat(png_tmp_file_name)
      except OSError:
        print >>sys.stderr, 'info: ImageRenderer has not created output: ' % (
            pdf_tmp_file_name)
        assert 0, 'ImageRenderer failed (missing output PNG)'
      png_files[obj_num] = png_tmp_file_name

    return png_files

  def OptimizeImages(self, use_pngout=True, use_jbig2=True):
    """Optimize image XObjects in the PDF."""
    # TODO(pts): convert inline images to image XObject{}s.
    # Dictionary mapping Ghostscript -sDEVICE= names to dictionaries mapping
    # PDF object numbers to PdfObj instances.
    # TODO(pts): Remove key PTEX.* from all dicts (trailer and form xobjects)
    device_image_objs = {'png16m': {}, 'pnggray': {}, 'pngmono': {}}
    image_count = 0
    image_total_size = 0
    images = {}
    # Maps /XImage (head, stream) pairs to object numbers.
    by_orig_data = {}
    # Maps obj_nums (to be modified) to obj_nums (to be modified to).
    modify_obj_nums = {}
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]

      # TODO(pts): Is re.search here fast enough?; PDF comments?
      if (not re.search(r'/Subtype[\0\t\n\r\f ]*/Image\b', obj.head) or
          not obj.head.startswith('<<') or
          not obj.stream is not None or
          obj.Get('Subtype') != '/Image'): continue
      filter = (obj.Get('Filter') or '').replace(']', ' ]') + ' '

      # Don't touch lossy-compressed images.
      # TODO(pts): Read lossy-compressed images, maybe a small, uncompressed
      # representation would be smaller.
      if ('/JPXDecode ' in filter or '/DCTDecode ' in filter):
        continue

      # TODO(pts): Support color key mask for /DeviceRGB and /DeviceGray:
      # convert the /Mask to RGB8, remove it, and add it back (properly
      # converted back) to the final PDF; pay attention to /Decode
      # differences as well.
      mask = obj.Get('Mask')
      if (isinstance(mask, str) and '[' in mask and
          not re.match(r'\[\s*\]\Z', mask)):
        continue

      data_pair = (obj.head, obj.stream)
      target_obj_num = by_orig_data.get(data_pair)
      if target_obj_num is not None: 
        # For testing: pts2.zip.4times.pdf
        # This is just a speed optimization so we don't have to parse the
        # image again.
        print >>sys.stderr, (
            'info: using identical image obj %s for obj %s' %
            (target_obj_num, obj_num))
        modify_obj_nums[obj_num] = target_obj_num
        continue
      by_orig_data[data_pair] = obj_num

      obj0 = obj

      if obj.Get('ImageMask'):
        if obj is obj0:
          obj = PdfObj(obj)
        obj.Set('ImageMask', None)
        obj.Set('Decode', None)
        obj.Set('ColorSpace', '/DeviceGray')
        obj.Set('BitsPerComponent', 1)

      bpc = obj.Get('BitsPerComponent')
      if bpc not in (1, 2, 4, 8):
        continue

      colorspace = obj.Get('ColorSpace')
      assert isinstance(colorspace, str)
      # !! TODO(pts): proper PDF token sequence parsing
      # !! use ParseArray
      if '(' not in colorspace and '<' not in colorspace:
        # TODO(pts): Inline this to reduce PDF size.
        # pdftex emits: /ColorSpace [/Indexed /DeviceRGB <n> <obj_num> 0 R] 
        # !! generic reference resolver
        colorspace0 = colorspace
        match = re.match(r'(\d+)\s+0\s+R\Z', colorspace)
        if match:
          colorspace = self.objs[int(match.group(1))].head
        colorspace = re.sub(
            r'\b(\d+)\s+0\s+R\s*(?=\]\Z)',
            (lambda match:
             obj.EscapeString(self.objs[int(match.group(1))]
             .GetUncompressedStream())),
            colorspace)
        if colorspace != colorspace0:
          if obj is obj0:
            obj = PdfObj(obj)
          obj.Set('ColorSpace', colorspace)
      assert not re.match(r'\b\d+\s+\d+\s+R\b', colorspace)
      colorspace_short = re.sub(r'\A\[\s*/Indexed\s*/([^\s/<(]+)(?s).*',
                         '/Indexed/\\1', colorspace)
      if re.search(r'[^/\w]', colorspace_short):
        colorspace_short = '?'

      # Ignore images with exotic color spaces (e.g. DeviceCMYK, CalGray,
      # DeviceN).
      # TODO(pts): Support more color spaces. DeviceCMYK would be tricky,
      # because neither PNG nor sam2p supports it. We can convert it to
      # RGB, though.
      if not re.match(r'(?:/Device(?:RGB|Gray)\Z|\[\s*/Indexed\s*'
                      r'/Device(?:RGB|Gray)\s)', colorspace):
        continue

      obj = PdfObj(obj)
      # !! TODO(pts): proper PDF token sequence parsing
      # !! add resolving of references
      if re.match(r'\b\d+\s+\d+\s+R\b', obj.head):
        continue

      width = obj.Get('Width')
      assert isinstance(width, int)
      assert width > 0
      height = obj.Get('Height')
      assert isinstance(height, int)
      assert height > 0

      if not PdfObj.IsGrayColorSpace(colorspace):
        gs_device = 'png16m'
      elif bpc > 1 or colorspace != '/DeviceGray':
        # TODO(pts): Make it work for 1-bit grayscale palette.
        gs_device = 'pnggray'
      else:
        gs_device = 'pngmono'

      image_count += 1
      image_total_size += obj.size
      images[obj_num] = []
      # TODO(pts): More accurate /DecodeParms reporting (remove if no
      # predictor).
      print >>sys.stderr, (
          'info: will optimize image XObject %s; orig width=%s height=%s '
          'colorspace=%s bpc=%s filter=%s dp=%s size=%s gs_device=%s' %
          (obj_num, obj.Get('Width'), obj.Get('Height'),
           colorspace_short, bpc, obj.Get('Filter'),
           int(bool(obj.Get('DecodeParms'))), obj.size, gs_device))

      # Try to convert to PNG in-process. If we can't, schedule rendering with
      # Ghostscript. 
      try:
        # Both LoadPdfImageObj and CompressToZipPng an raise FormatUnsupported.
        image1 = ImageData().LoadPdfImageObj(obj=obj, do_zip=False)
        if not image1.CanBePngImage(do_ignore_compression=True):
          raise FormatUnsupported('cannot save to PNG')
        image2 = ImageData(image1).CompressToZipPng()
      except FormatUnsupported:
        image1 = image2 = None

      if image1 is None:
        device_image_objs[gs_device][obj_num] = obj
      else:
        images[obj_num].append(('parse', (image2.SavePng(
            file_name='type1cconv-%d.parse.png' % obj_num))))
        if image1.compression == 'none':
          image1.idat = zlib.compress(image1.idat, 9)
          image1.compression = 'zip'
        if len(image1.idat) < len(image2.idat):
          # For testing: ./pdfsizeopt.py -use-pngout=false PLRM.pdf
          # Hack to use the smaller image1 as the 'parse' image, but let
          # other images (generated below) be generated from the image2 PNG.
          images[obj_num][-1] = ('parse', image1)
          image1.file_name = image2.file_name
  
    if not images: return self # No images => no conversion.
    print >>sys.stderr, 'info: optimizing %s images of %s bytes in total' % (
        image_count, image_total_size)

    # Render images which we couldn't convert in-process.
    for gs_device in sorted(device_image_objs):
      ps_tmp_file_name = 'type1cconv.%s.tmp.ps' % gs_device
      objs = device_image_objs[gs_device]
      if objs:
        # Dictionary mapping object numbers to /Image PdfObj{}s.
        rendered_images = self.RenderImages(
            objs=objs, ps_tmp_file_name=ps_tmp_file_name, gs_device=gs_device,
            png_tmp_file_pattern='type1cconv-%%04d.%s.tmp.png' % gs_device)
        os.remove(ps_tmp_file_name)
        for obj_num in sorted(rendered_images):
          images[obj_num].append(
              ('gs', ImageData().Load(file_name=rendered_images[obj_num])))

    # Optimize images.
    bytes_saved = 0
    # Maps image data tuples to obj_num.
    by_image_tuple = {}
    # Maps image data tuples to an ImageData.
    by_rendered_tuple = {}
    for obj_num in sorted(images):
      # !! TODO(pts): Don't load all images to memory (maximum 2).
      obj = self.objs[obj_num]
      obj_images = images[obj_num]

      rendered_tuple = obj_images[-1][1].ToDataTuple()
      target_image = by_rendered_tuple.get(rendered_tuple)
      if target_image is not None:  # We have already rendered this image.
        # For testing: pts2.zip.4timesb.pdf
        # This is just a speed optimization so we don't have to run
        # sam2p again.
        print >>sys.stderr, (
            'info: using already rendered image for obj %s' % obj_num)
        if target_image is None:
          continue  # keep original image
        obj_images.append(('#prev-rendered-best', target_image))
      else:
        rendered_image_file_name = obj_images[-1][1].file_name
        # TODO(pts): use KZIP or something to further optimize the ZIP stream
        # !! shortcut for sam2p (don't need pngtopnm)
        #    (add basic support for reading PNG to sam2p? -- just what GS produces)
        #    (or just add .gz support?)
        obj_images.append(self.ConvertImage(
            sourcefn=rendered_image_file_name,
            targetfn='type1cconv-%d.sam2p-np.pdf' % obj_num,
            # We specify -s here to explicitly exclue SF_Opaque for single-color
            # images.
            # !! do we need /ImageMask parsing if we exclude SF_Mask here as well?
            # Original sam2p order: Opaque:Transparent:Gray1:Indexed1:Mask:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:Transparent2:Transparent4:Transparent8
            # !! reintroduce Opaque by hand (combine /FlateEncode and /RLEEncode; or /FlateEncode twice (!) to reduce zeroes in empty_page.pdf from !)
            cmd_pattern='sam2p -pdf:2 -c zip:1:9 -s Gray1:Indexed1:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:stop -- %(sourcefnq)s %(targetfnq)s',
            cmd_name='sam2p_np'))

        image_tuple = obj_images[-1][1].ToDataTuple()
        target_image = by_image_tuple.get(image_tuple)
        if target_image is not None:  # We have already optimized this image.
          # For testing: pts2.ziplzw.pdf
          # The latest sam2p is deterministic, so the bytes of the file
          # produced by sam2p depends only on the RGB image data.
          print >>sys.stderr, (
              'info: using already processed image for obj %s' % obj_num)
          if target_image is None:
            continue  # keep original image
          obj_images.append(('#prev-sam2p-best', target_image))
        else:
          obj_images.append(self.ConvertImage(
              sourcefn=rendered_image_file_name,
              targetfn='type1cconv-%d.sam2p-pr.png' % obj_num,
              cmd_pattern='sam2p -c zip:15:9 -- %(sourcefnq)s %(targetfnq)s',
              cmd_name='sam2p_pr'))
          if (use_jbig2 and obj_images[-1][1].bpc == 1 and
              obj_images[-1][1].color_type in ('gray', 'indexed-rgb')):
            # !! autoconvert 1-bit indexed PNG to gray
            obj_images.append(('jbig2', ImageData(obj_images[-1][1])))
            if obj_images[-1][1].color_type != 'gray':
              # This changes obj_images[-1].file_name as well.
              obj_images[-1][1].SavePng(
                  file_name='type1cconv-%d.gray.png' % obj_num, do_force_gray=True)
            obj_images[-1][1].idat = self.ConvertImage(
                sourcefn=obj_images[-1][1].file_name,
                targetfn='type1cconv-%d.jbig2' % obj_num,
                cmd_pattern='jbig2 -p %(sourcefnq)s >%(targetfnq)s',
                cmd_name='jbig2', do_just_read=True)[1]
            obj_images[-1][1].compression = 'jbig2'
            obj_images[-1][1].file_name = 'type1cconv-%d.jbig2' % obj_num
          # !! add /FlateEncode again to all obj_images to find the smallest
          #    (maybe to UpdatePdfObj)
          # !! rename type1cconv and .type1c in temporary filenames
          # !! TODO(pts): Find better pngout binary file name.
          # TODO(pts): Try optipng as well (-o5?)
          if use_pngout:
            obj_images.append(self.ConvertImage(
                sourcefn=rendered_image_file_name,
                targetfn='type1cconv-%d.pngout.png' % obj_num,
                cmd_pattern='pngout-linux-pentium4-static '
                            '%(sourcefnq)s %(targetfnq)s',
                cmd_name='pngout'))

      obj_infos = [(obj.size, '#orig', '', obj, None)]
      for cmd_name, image_data in obj_images:
        new_obj = PdfObj(obj)
        if obj.Get('ImageMask') and not image_data.CanUpdateImageMask():
          if cmd_name != 'gs':  # no warning for what was rendered by Ghostscript
            print >>sys.stderr, (
                'warning: skipping bpc=%s color_type=%s file_name=%r '
                'for image XObject %s because of source /ImageMask' %
                (image_data.bpc, image_data.color_type, image_data.file_name,
                 obj_num))
        else:
          image_data.UpdatePdfObj(new_obj)
          obj_infos.append([new_obj.size, cmd_name, image_data.file_name,
                            new_obj, image_data])

      # SUXX: Python2.4 min(...) and sorted(...) doesn't compare tuples
      # properly ([0] first)) if one of them is an object. So we implement
      # our own comparator.
      def CompareStr(a, b):
        return (a < b and -1) or (a > b and 1) or 0
      def CompareObjInfo(a, b):
        # Compare first by byte size, then by command name.
        return a[0].__cmp__(b[0]) or CompareStr(a[1], b[1])

      obj_infos.sort(CompareObjInfo)
      method_sizes = ','.join(
          ['%s:%s' % (obj_info[1], obj_info[0]) for obj_info in obj_infos])

      if obj_infos[0][3] is obj:
        # TODO(pts): Diagnose this: why can't we generate a smaller image?
        # !! Originals in eurotex2006.final.pdf tend to be smaller here because
        #    they have ColorSpace in a separate XObject.
        print >>sys.stderr, (
            'info: keeping original image XObject %s, '
            'replacements too large: %s' %
            (obj_num, method_sizes))
      else:
        print >>sys.stderr, (
            'info: optimized image XObject %s file_name=%s '
            'size=%s (%s) methods=%s' %
            (obj_num, obj_infos[0][2], obj_infos[0][0],
             FormatPercent(obj_infos[0][0], obj.size), method_sizes)) 
        bytes_saved += self.objs[obj_num].size - obj_infos[0][0]
        if ('/JBIG2Decode' in (obj_infos[0][3].Get('Filter') or '') and
            self.version < '1.4'):
          self.version = '1.4'
        self.objs[obj_num] = obj_infos[0][3]
      by_rendered_tuple[rendered_tuple] = obj_infos[0][4]
      by_image_tuple[image_tuple] = obj_infos[0][4]
      del obj_images[:]  # free memory occupied by unchosen images
    print >>sys.stderr, 'info: saved %s bytes (%s) on images' % (
        bytes_saved, FormatPercent(bytes_saved, image_total_size))
    # !! compress PDF palette to a new object if appropriate
    # !! delete all optimized_image_file_name{}s
    # !! os.remove(obj_images[...]), also *.jbig2 and *.gray.png

    for obj_num in modify_obj_nums:
      self.objs[obj_num] = PdfObj(self.objs[modify_obj_nums[obj_num]])

    return self

  def FixAllBadNumbers(self):
    # buggy pdfTeX-1.21a generated
    # /Matrix[1. . . 1. . .]/BBox[. . 612. 792.]
    # in eurotex2006.final.bad.pdf . Fix: convert `.' to 0.
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]
      if (obj.head.startswith('<<') and
          # !! TODO(pts): proper PDF token sequence parsing
          re.search(r'/Subtype\s*/Form\b', obj.head) and
          obj.Get('Subtype') == '/Form'):
        matrix = obj.Get('Matrix')
        if isinstance(matrix, str):
          obj.Set('Matrix', obj.GetBadNumbersFixed(matrix))
        bbox = obj.Get('BBox')
        if isinstance(bbox, str):
          obj.Set('BBox', obj.GetBadNumbersFixed(bbox))
    return self

  @classmethod
  def FindEqclasses(cls, objs, do_remove_unused=False, do_renumber=False):
    """Find equivalence classes in objs, return new objs.
    
    Args:
      objs: A dict mapping object numbers (or strings such as 'trailer') to
        PdfObj instances.
      do_remove_unused: A boolean indicating whether to remove all objects
        not reachable from 'trailer' etc.
      do_renumber: A boolean indicating whether to renumber all objects,
        ordered by decreasing number of referrers.
    Returns:
      A new dict mapping object numbers to PdfObj instances.
    """
    # List of list of desc ([obj_num, head_minus, stream, refs_to,
    # inrefs_count]). Each list of eqclasses is an eqivalence class of
    # object descs.
    eqclasses = []
    # Maps object numbers to an element of eqclasses.
    eqclass_of = {}

    # Maps (head_minus, stream) to a list of desc.
    by_form = {}
    # List of desc.
    search_todo = []
    for obj_num in sorted(objs):
      refs_to = []  # List of object numbers obj_num refers to).
      head = objs[obj_num].head
      # TODO(pts): reorder dicts etc.
      head_minus = PdfObj.CompressValue(
          head, obj_num_map='0', old_obj_nums_ret=refs_to,
          do_emit_strings_as_hex=True)
      stream = objs[obj_num].stream
      desc = [obj_num, head_minus, stream, refs_to, 0]
      if isinstance(obj_num, str):  # for 'trailer'
        eqclasses.append([desc])
        eqclass_of[obj_num] = eqclasses[-1]
        if do_remove_unused:
          search_todo.append(desc)
      else:
        form = (head_minus, stream)
        form_desc = by_form.get(form)
        if form_desc is not None:
          form_desc.append(desc)
          eqclass_of[obj_num] = form_desc
        else:
          eqclasses.append([desc])
          eqclass_of[obj_num] = by_form[form] = eqclasses[-1]
    del by_form  # save memory

    #for eqclass in eqclasses:
    #  for desc in eqclass:
    #    print desc
    #  print

    had_split = True
    while had_split:
      had_split = False
      for eqclass in eqclasses:
        assert eqclass
        if len(eqclass) > 1:
          desc = eqclass[0]
          refs_to = desc[3]
          eqlist = [desc]
          nelist = []
          for i in xrange(1, len(eqclass)):
            descb = eqclass[i]
            refs_tob = descb[3]
            has_ne = False
            j = 0
            while (j < len(refs_to) and
                   eqclass_of.get(refs_to[j]) is eqclass_of.get(refs_tob[j])):
              j += 1
            if j == len(refs_to):
              eqlist.append(descb)
            else:
              nelist.append(descb)
          if nelist:  # everybody in eqclass is equivalent to desc
            had_split = True
            eqclasses.append(nelist)
            for descb in nelist:
              assert eqclass_of[descb[0]] is eqclass
              eqclass_of[descb[0]] = nelist
            eqclass[:] = eqlist

    eliminated_count = len(objs) - len(eqclasses)
    assert eliminated_count >= 0
    if eliminated_count > 0:
      print >>sys.stderr, 'info: eliminated %s duplicate objs' % (
          eliminated_count)

    # Set of eqclass-leader object numbers.
    unused_obj_nums = set()
    if do_remove_unused or do_renumber:
      unused_obj_nums = set([eqclass[0][0] for eqclass in eqclasses])
      for desc in search_todo:
        unused_obj_nums.remove(desc[0])
      for desc in search_todo:  # breadth-first search from trailer
        for obj_num in desc[3]:  # refs_to
          target_class = eqclass_of.get(obj_num)
          if target_class is not None:
            target_class[0][4] += 1  # inrefs_count
            target_obj_num = target_class[0][0]
            if target_obj_num in unused_obj_nums:
              search_todo.append(target_class[0])
              unused_obj_nums.remove(target_obj_num)
      if not do_remove_unused:
        unused_obj_nums.clear()
      elif unused_obj_nums:
        print >>sys.stderr, 'info: eliminated %s unused objs in %s classes' % (
            sum([len(eqclass_of[obj_num]) for obj_num in unused_obj_nums]),
            len(unused_obj_nums))

    # Maps eqclass-leader object number to object number.
    obj_num_map = {}
    if do_renumber:

      def CompareDesc(desc_a, desc_b):
        """Order by decreasing inrefs_count, then increasing obj_num."""
        return (desc_b[4].__cmp__(desc_a[4]) or  # inrefs_count
                desc_a[0].__cmp__(desc_b[0]))    # original obj_num

      descs = [eqclass[0] for eqclass in eqclasses
               if not isinstance(eqclass[0][0], str) and
               eqclass[0][0] not in unused_obj_nums]
      descs.sort(CompareDesc)
      i = 0
      for desc in descs:
        i += 1
        obj_num_map[desc[0]] = i

    objs_ret = {}
    for eqclass in eqclasses:
      obj_num, head_minus, stream, refs_to, _ = eqclass[0]
      if obj_num in unused_obj_nums:
        continue

      refs_to_rev = refs_to[:]
      refs_to_rev.reverse()

      def ReplacementRef(match):
        match_obj_num = int(match.group(1))
        assert match_obj_num == 0
        assert refs_to_rev
        target_obj_num = refs_to_rev.pop()
        new_class = eqclass_of.get(target_obj_num)
        if new_class is None:
          print >>sys.stderr, (
              'warning: obj %s missing, referenced by objs %r...' %
              (target_obj_num, [desc[0] for desc in eqclass]))
          return 'null'
        else:
          new_obj_num = new_class[0][0]
          return '%s 0 R'  % obj_num_map.get(new_obj_num, new_obj_num)

      head = PdfObj.PDF_SIMPLE_REF_RE.sub(ReplacementRef, head_minus)
      assert not refs_to_rev
      
      head = PdfObj.PDF_HEX_STRING_OR_DICT_RE.sub(
          lambda match: (match.group(1) and PdfObj.EscapeString(
              match.group(1).decode('hex')) or '<<'), head)
      obj = PdfObj(None)
      obj.head = head
      obj.stream = stream
      objs_ret[obj_num_map.get(obj_num, obj_num)] = obj
      # !! fix CFF as well (ObjNNN is part of the CFF)

    return objs_ret

  def OptimizeObjs(self):
    """Optimize PDF objects.

    This method does the following:

    * Calls PdfObj.CompressValue for all obj.head
    * Removes unused objs.
    * Removes duplicate objs.
    * In multiple iterations, removes duplicate trees.
    * Removes gaps between obj numbers.
    * Reorders objs so most-referenced objs come early.

    This method doesn't unify equivalent sets with circular references, e.g.
      4 0 obj<</Parent 1 0 R/Type/Pages/Kids[9 0 R]/Count 1>>endobj 
      5 0 obj<</Parent 1 0 R/Type/Pages/Kids[10 0 R]/Count 1>>endobj
      9 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]/Parent 4 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>/Contents 3 0 R>>endobj
      10 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]/Parent 5 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>/Contents 3 0 R>>endobj
    Use Multivalent.jar for that.
    TODO(pts): Implement this, using equivalence class separation.
    For testing: pts2.zip.4times.pdf and tuzv.pdf

    Return:
      self.
    """
    # TODO(pts): Inline ``obj null endobj'' and ``obj<<>>endobj'' etc.

    self.objs['trailer'] = self.trailer
    new_objs = self.FindEqclasses(
        self.objs, do_remove_unused=True, do_renumber=True)
    self.trailer = new_objs.pop('trailer')
    self.objs.clear()
    self.objs.update(new_objs)
    return self


BOOL_VALUES = {
    'on': True,
    'off': False,
    'yes': True,
    'no': False,
    '1': True,
    '0': False,
    'true': True,
    'false': False
}


def ParseBoolFlag(flag_name, flag_value):
  flag_value_lower = flag_value.lower()
  if flag_value_lower not in BOOL_VALUES:
    raise getopt.GetoptError('option %s=%s needs a bool value' %
                             (flag_name, flag_value))
  return BOOL_VALUES[flag_value_lower]


def main(argv):
  print >>sys.stderr, 'info: This is %s v%s.' % (
      os.path.basename(__file__), __id__.split(' ', 3)[2])
  # Find image converters in script dir first.
  os.environ['PATH'] = '%s:%s' % (
      os.path.dirname(os.path.abspath(argv[0])), os.getenv('PATH', ''))

  try:
    use_pngout = True
    use_jbig2 = True
    do_optimize_images = True
    do_optimize_objs = True
    do_unify_fonts = True
    # Keep optional information about fonts in the PDF?
    do_keep_font_optionals = False
    # It is not much slower (and it's actually faster if some fonts need
    # /LZWDecode), and we can gain a few bytes by converting all Type1C fonts
    # with Ghostscript.
    do_regenerate_all_fonts = True
    # TODO(pts): Don't allow long option prefixes, e.g. --use-pngo=foo
    opts, args = getopt.gnu_getopt(argv[1:], '+', [
        'version', 'help',
        'use-pngout=', 'use-jbig2=',
        'do-keep-font-optionals=',
        'do-double-check-missing-glyphs=',
        'do-regenerate-all-fonts=',
        'do-optimize-images=', 'do-optimize-objs=', 'do-unify-fonts='])
    for key, value in opts:
      if key == '--use-pngout':
        # !! add =auto (detect binary on path)
        use_pngout = ParseBoolFlag(key, value)
      elif key == '--use-jbig2':
        # !! add =auto (detect binary on path)
        use_jbig2 = ParseBoolFlag(key, value)
      elif key == '--do-optimize-images':
        do_optimize_images = ParseBoolFlag(key, value)
      elif key == '--do-optimize-objs':
        do_optimize_objs = ParseBoolFlag(key, value)
      elif key == '--do-unify-fonts':
        do_unify_fonts = ParseBoolFlag(key, value)
      elif key == '--do-keep-font-optionals':
        do_keep_font_optionals = ParseBoolFlag(key, value)
      elif key == '--do-double-check-missing-glyphs':
        do_double_check_missing_glyphs = ParseBoolFlag(key, value)
      elif key == '--do-regenerate-all-fonts':
        do_regenerate_all_fonts = ParseBoolFlag(key, value)
      elif key == '--help':
        # TODO(pts): Implement this.
        print >>sys.stderr, 'error: --help not implemented'
        sys.exit(2)
      elif key == '--version':
        sys.exit(0)  # printed above
      else:
        assert 0, 'unknown option %s' % key
    if not args:
      raise getopt.GetoptError('missing filename in command-line')
    elif len(args) == 1:
      file_name = args[0]
      if file_name.endswith('.pdf'):
        # !! different filename
        output_file_name = file_name[:-4] + '.type1c.pdf'
      else:
        output_file_name = file_name + '.type1c.pdf'
    elif len(args) == 2:
      file_name = args[0]
      output_file_name = args[1]
    else:
      raise getopt.GetoptError('too many command-line args')
  except getopt.GetoptError, exc:
    print >>sys.stderr, 'error: in command line: %s' % exc
    sys.exit(1)

  pdf = PdfData().Load(file_name)
  pdf.FixAllBadNumbers()
  pdf.ConvertType1FontsToType1C()
  if do_unify_fonts:
    pdf.UnifyType1CFonts(
        do_keep_font_optionals=do_keep_font_optionals,
        do_double_check_missing_glyphs=do_double_check_missing_glyphs,
        do_regenerate_all_fonts=do_regenerate_all_fonts)
  if do_optimize_images:
    pdf.ConvertInlineImagesToXObjects()
    pdf.OptimizeImages(use_pngout=use_pngout, use_jbig2=use_jbig2)
  if do_optimize_objs:
    pdf.OptimizeObjs()
  pdf.Save(output_file_name)


if __name__ == '__main__':
  main(sys.argv)
