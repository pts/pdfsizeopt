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
tool.pdf.Compress in Multivaent.jar from http://multivalent.sf.net/ for that.
"""

__author__ = 'pts@fazekas.hu (Peter Szabo)'

# We don't want to have a '$' + 'Id' in this file, because downloading the
# script from http://pdfsizeopt.googlecode.com/svn/trunk/pdfsizeopt.py
# won't expand that to a useful version number.

import array
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


def GetGsCommand():
  """Return shell command-line prefix for running Ghostscript (gs)."""
  gs_cmd = os.getenv('PDFSIZEOPT_GS', None)
  if gs_cmd is None:
    if sys.platform.startswith('win'):  # Windows: win32 or win64
      return 'gswin32c'  # gswin32c.exe in Ghostscript.
    return 'gs'
  return gs_cmd


def ShellQuote(string):
  # TODO(pts): Make it work properly on non-Unix systems.
  string = str(string)
  if string and not re.search('[^-_.+,:/a-zA-Z0-9]', string):
    return string
  elif sys.platform.startswith('win'):
    # TODO(pts): Does this replace make sense?
    return '"%s"' % string.replace('"', '""')
  else:
    return "'%s'" % string.replace("'", "'\\''")


def ShellQuoteFileName(string):
  # TODO(pts): Make it work on non-Unix systems.
  if string.startswith('-') and len(string) > 1:
    string = '.%s%s' % (os.sep, string)
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


def FindOnPath(file_name):
  """Find file_name on $PATH, and return the full pathname or None."""
  # TODO(pts): Make this work on non-Unix systems.
  for item in os.getenv('PATH', '/bin:/usr/bin').split(os.pathsep):
    if not item:
      item = '.'
    path_name = os.path.join(item, file_name)
    try:
      os.stat(path_name)
      return path_name
    except OSError:
      pass
  return None


def PermissiveZlibDecompress(data):
  """Decompress (inflate) an RFC 1950 deflated string, maybe w/o checksum.

  Args:
    data: String containing RFC 1950 deflated data, the 4-byte ADLER32 checksum
      being possibly truncated (to 0, 1, 2, 3 or 4 bytes).
  Returns:
    String containing the uncompressed data.
  Raises:
    zlib.error:
  """
  try:
    return zlib.decompress(data)
  except zlib.error:
    # This works if the ADLER32 is truncated, but it raises zlib.error on any
    # other error.
    uncompressed = zlib.decompressobj().decompress(data)
    adler32_data = struct.pack('>L', zlib.adler32(uncompressed))
    try:
      return zlib.decompress(data + adler32_data[3:])
    except zlib.error:
      try:
        return zlib.decompress(data + adler32_data[2:])
      except zlib.error:
        try:
          return zlib.decompress(data + adler32_data[1:])
        except zlib.error:
          return zlib.decompress(data + adler32_data)


class PdfOptimizeError(Error):
  """Raised if an expected optimization couldn't be performed."""


class PdfTokenParseError(Error):
  """Raised if a string cannot be parsed to a PDF token sequence."""

class UnexpectedStreamError(Error):
  """Raised when ResolveReferences gets a ref to an obj with stream."""


class PdfReferenceTargetMissing(Error):
  """Raised if the target obj for an <x> <y> R is missing."""

class PdfReferenceRecursiveError(Error):
  """Raised if a PDF object reference is recursive."""


class PdfIndirectLengthError(PdfTokenParseError):
  """Raised if an obj stream /Length is an unresolvable indirect reference.

  The attribute length_obj_num might be set to the object number holding the
  length.  
  """

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

class PdfXrefStreamError(PdfXrefError):
  """Raised if the PDF file doesn't contain a valid cross-reference stream."""

class PdfXrefStreamWidthsError(PdfXrefStreamError):
  """Raised if the xref stream trailer does not contain a valid /W value."""


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

  #PDF_WHITESPACES_RE = re.compile('[' + PDF_WHITESPACE_CHARS + ']+')
  #"""Matches one or more PDF whitespace characters."""

  PDF_STREAM_OR_ENDOBJ_RE_STR = (
      r'[\0\t\n\r\f )>\]](stream(?:\r\n|[\0\t\n\r\f ])|'
      r'endobj(?:[\0\t\n\r\f /]|\Z))')
  PDF_STREAM_OR_ENDOBJ_RE = re.compile(PDF_STREAM_OR_ENDOBJ_RE_STR)
  """Matches stream or endobj in a PDF obj."""

  REST_OF_R_RE = re.compile(
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+R(?=[\0\t\n\r\f /%<>\[\](])')
  """Matches the generation number and the 'R' (followed by a char)."""

  PDF_NUMBER_OR_REF_RE_STR = (
      r'(-?\d+)(?=[\0\t\n\r\f /%(<>\[\]])(?:'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+R'
      r'(?=[\0\t\n\r\f /%(<>\[\]]|\Z))?')
  PDF_NUMBER_OR_REF_RE = re.compile(PDF_NUMBER_OR_REF_RE_STR)
  """Matches a number or an <x> <y> R."""

  PDF_END_OF_REF_RE = re.compile(
      r'[\0\t\n\r\f ]R(?=[\0\t\n\r\f /%(<>\[\]]|\Z)')
  """Matches the whitespace, the 'R' and looks ahead 1 char."""

  PDF_REF_RE = re.compile(
      r'(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+(-?\d+)'
      r'(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+R'
      r'(?=[\0\t\n\r\f /%(<>\[\]]|\Z)')
  """Matches a number or an <x> <y> R."""

  LENGTH_OF_STREAM_RE = re.compile(
      r'/Length(?:[\0\t\n\r\f ]|%[^\r\n]*[\r\n])+' + PDF_NUMBER_OR_REF_RE_STR)
  """Matches `/Length <x>' or `/Length <x> <y> R'."""

  SUBSET_FONT_NAME_PREFIX_RE = re.compile(r'/[A-Z]{6}[+]')
  """Matches the beginning of a subset font name (starting with slash)."""

  PDF_OBJ_DEF_RE_STR = (
      r'\d+[\0\t\n\r\f ]+\d+[\0\t\n\r\f ]+obj'
      r'(?=[\0\t\n\r\f /<\[({])[\0\t\n\r\f ]*')
  PDF_OBJ_DEF_RE = re.compile(PDF_OBJ_DEF_RE_STR)
  """Matches an `obj' definition no leading, with trailing whitespace."""

  PDF_OBJ_DEF_CAPTURE_RE_STR = (
      r'(\d+)[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+obj'
      r'(?=[\0\t\n\r\f /<\[({])[\0\t\n\r\f ]*')
  PDF_OBJ_DEF_CAPTURE_RE = re.compile(PDF_OBJ_DEF_CAPTURE_RE_STR)
  """Matches an `obj' definition no leading, with trailing whitespace.

  Captures the object number and the generation number."""

  PDF_OBJ_DEF_OR_XREF_RE = re.compile(
      PDF_OBJ_DEF_RE_STR + r'|xref[\0\t\n\r\f]*|startxref[\0\t\n\r\f]*')
  """Matches an `obj' definition, xref or startxref."""

  NONNEGATIVE_INT_RE = re.compile(r'(-?\d+)')
  """Matches and captures a nonnegative integer."""

  PDF_STARTXREF_EOF_RE = re.compile(
      r'[>\0\t\n\r\f ]startxref\s+(\d+)(?:\s+%%EOF\s*)?\Z')
  """Matches whitespace (or >), startxref, offset, then EOF at EOS."""

  PDF_VERSION_HEADER_RE = re.compile(r'\A%PDF-(1[.]\d)\s')
  """Matches the header with the version at the beginning of the PDF."""

  PDF_TRAILER_RE = re.compile(
      r'(?s)trailer[\0\t\n\r\f ]*(<<.*?>>'
      r'[\0\t\n\r\f ]*)(?:startxref|xref)[\0\t\n\r\f ]')
  """Matches from 'trailer' to 'startxref' or 'xref'.
  
  TODO(pts): Match more generally, see multiple trailers for testing in:
  pdf.a9p4/5176.CFF.a9p4.pdf
  """

  PDF_TRAILER_WORD_RE = re.compile(r'[\0\t\n\r\f ](trailer[\0\t\n\r\f ]*<<)')
  """Matches whitespace, the wirt 'trailer' and some more chars."""

  PDF_FONT_FILE_KEYS = ('FontFile', 'FontFile2', 'FontFile3')
  """Tuple of keys in /Type/FontDescriptor referring to the font data obj."""

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


  def __init__(self, other, objs=None, file_ofs=0, start=0, end_ofs_out=None,
               do_ignore_generation_numbers=False):
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
      file_ofs: Offset of other + start in the file. Used for error message
        generation.
      start: Offset in other (if a string) to start parsing from.
      end_ofs_out: None or an empty array output parameter for the end offset
        (i.e.. after `endobj' + whitespace).
      do_ignore_generation_numbers: Boolean indicating whether to ignore
        generation numbers in references when parsing this object.
    Raises:
      PdfTokenParseError:
      Exception: Many others.
    """
    self._cache = None
    if isinstance(other, PdfObj):
      self._head = other.head
      self.stream = other.stream
    elif isinstance(other, str):
      if not other:
        raise PdfTokenParseError('empty PDF obj to parse at ofs=%s' % file_ofs)
      scanner = self.PDF_OBJ_DEF_RE.scanner(other, start)
      match = scanner.match()
      if not match:
        raise PdfTokenParseError(
            'X Y obj expected, got %r at ofs=%s' %
            (other[start : start + 32], file_ofs))
      skip_obj_number_idx = match.end()
      stream_start_idx = None

      # We do the simplest and fastest parsing approach first to find
      # endobj/endstream. This covers about 90% of the objs. Notable
      # exceptions are the /Producer, /CreationDate and /CharSet strings.
      scanner = self.PDF_STREAM_OR_ENDOBJ_RE.scanner(
          other, skip_obj_number_idx)
      match = scanner.search()
      if not match:
        raise PdfTokenParseError(
            'endobj/stream not found from ofs=%s to ofs=%s' %
            (file_ofs, file_ofs + len(other) - start))
      head = other[skip_obj_number_idx : match.start(1)].rstrip(
          self.PDF_WHITESPACE_CHARS)
      if '%' in head or '(' in head:
        # Our simple parsing approach may have failed, maybe because we've
        # found the wrong (early) 'endobj' in e.g. '(endobj rest) endobj'.
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
              (file_ofs, file_ofs + len(other) - start))
        if match.group(1).startswith('stream'):
          stream_start_idx = j + match.end(1)
        i = j + match.start(1)
        end_ofs = j + match.end()
        while other[i - 1] in self.PDF_WHITESPACE_CHARS:
          i -= 1
        head = other[skip_obj_number_idx : i]
      else:
        if match.group(1).startswith('stream'):
          stream_start_idx = match.end(1)
        end_ofs = match.end()

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
          if (int(match.group(2)) != 0 and
              not do_ignore_generation_numbers):
            raise NotImplementedError(
                'generational refs (in /Length %s %s R) not implemented '
                'at ofs=%s' % (match.group(1), match.group(2), file_ofs))
          obj_num = int(match.group(1))
          if obj_num <= 0:
            raise PdfTokenParseError(
                'obj num %d >= 0 expected for indirect /Length at ofs=%s' %
                (obj_num, file_ofs))
          if not objs or obj_num not in objs:
            exc = PdfIndirectLengthError(
                'missing obj for indirect /Length %d 0 R at ofs=%s' %
                (obj_num, file_ofs))
            exc.length_obj_num = obj_num
            raise exc
          try:
            stream_length = int(objs[obj_num].head)
          except ValueError:
            raise PdfTokenParseError(
                'indirect /Length not an integer at ofs=%s' % file_ofs)
          stream_end_idx = stream_start_idx + stream_length
          # Inline the reference to /Length
          self._head = '%s/Length %d%s' % (
              self._head[:match.start(0)], stream_length,
              self._head[match.end(0):]) 
        endstream_str = other[stream_end_idx : stream_end_idx + 30]
        match = re.match(  # TODO(pts): Create objs for regexps.
            r'[\0\t\n\r\f ]*endstream[\0\t\n\r\f ]+'
            r'endobj(?:[\0\t\n\r\f /]|\Z)',
            endstream_str)
        if not match:
          raise PdfTokenParseError(
            'expected endstream+endobj in %r at %s' %
            (endstream_str, file_ofs + stream_end_idx))
        end_ofs = stream_end_idx + match.end()
        self.stream = other[stream_start_idx : stream_end_idx]
      if end_ofs_out is not None:
        end_ofs_out.append(end_ofs)
    elif other is None:
      self._head = None
      self.stream = None
    else:
      raise TypeError(type(other))

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
    
    Use self.ResolveReferences(obj.Get(...)) to resolve indirect refs.
    
    Args:
      key: A PDF name literal without a slash, e.g. 'ColorSpace'
      default: The value to return if key was not found. None by default.
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

  def SetStreamAndCompress(self, data, may_keep_old=False,
                           predictor_width=None, pdf=None):
    """Set self.stream, compress it and set Length, Filter and DecodeParms).

    This method tries all the following compression methods, and picks the
    one which produces the smallest output: original, uncompressed, ZIP, ZIP
    with the PNG y-predictor, ZIP with the TIFF predictor acting as an
    y-predictor.
    """
    if not isinstance(data, str):
      raise TypeError

    items = [[None, 'uncompressed', PdfObj(self)]]
    items[-1][2].stream = data
    items[-1][2].Set('Length', len(items[-1][2].stream))
    items[-1][2].Set('Filter', None)
    items[-1][2].Set('DecodeParms', None)
    items[-1][0] = items[-1][2].size

    if data:
      items.append([None, 'zip', PdfObj(self)])
      items[-1][2].stream = zlib.compress(data, 9)
      items[-1][2].Set('Length', len(items[-1][2].stream))
      items[-1][2].Set('Filter', '/FlateDecode')
      items[-1][2].Set('DecodeParms', None)
      items[-1][0] = items[-1][2].size

      if predictor_width is not None:
        assert isinstance(predictor_width, int)
        assert len(data) % predictor_width == 0

        output = []
        output.append('\x00')  # no-predictor mark
        output.append(data[:predictor_width])
        i = predictor_width
        while i < len(data):
          output.append('\x02')  # y-predictor mark
          b = array.array('B', data[i : i + predictor_width])
          k = i - predictor_width
          for j in xrange(predictor_width):  # Implement the y predictor.
            b[j] = (b[j] - ord(data[k + j])) & 255
          output.append(b.tostring())
          i += predictor_width
        items.append([None, 'zip-pred10', PdfObj(self)])
        items[-1][2].stream = zlib.compress(''.join(output), 9)
        items[-1][2].Set('Length', len(items[-1][2].stream))
        items[-1][2].Set('Filter', '/FlateDecode')
        items[-1][2].Set('DecodeParms',
                         '<</Predictor 10/Columns %d>>' % predictor_width)
        items[-1][0] = items[-1][2].size

        output = []
        output.append(data[:predictor_width])
        i = predictor_width
        while i < len(data):
          b = array.array('B', data[i : i + predictor_width])
          k = i - predictor_width
          for j in xrange(predictor_width):  # Implement the y predictor.
            b[j] = (b[j] - ord(data[k + j])) & 255
          output.append(b.tostring())
          i += predictor_width
        items.append([None, 'zip-pred2', PdfObj(self)])
        items[-1][2].stream = zlib.compress(''.join(output), 9)
        items[-1][2].Set('Length', len(items[-1][2].stream))
        items[-1][2].Set('Filter', '/FlateDecode')
        items[-1][2].Set('DecodeParms',
                         '<</Predictor 2/Colors %d/Columns %d>>' %
                         (predictor_width, len(data) / predictor_width))
        items[-1][0] = items[-1][2].size

      if may_keep_old:
        items.append([self.size, '0old', self])

    def CompareStr(a, b):
      return (a < b and -1) or (a > b and 1) or 0
    def CompareSize(a, b):
      # Compare first by byte size, then by command name.
      return a[0].__cmp__(b[0]) or CompareStr(a[1], b[1])

    items.sort(CompareSize)
    if items[0][2] is not self:
      self.stream = items[0][2].stream
      self.Set('Length', len(self.stream))
      self.Set('Filter', items[0][2].Get('Filter'))
      self.Set('DecodeParms', items[0][2].Get('DecodeParms'))
      if (pdf and items[0][1] == 'zip-pred2' and predictor_width > 4 and
          pdf.version < '1.3'):
        pdf.version = '1.3'

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

  PDF_COMMENTS_OR_WHITESPACE_RE = re.compile(
      r'[\0\t\n\r\f ]*(?:%[^\r\n]*(?:[\r\n]|\Z)[\0\t\n\r\f ]*)*')
  """Matches any number of terminated comments and whitespace."""

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

  PDF_SIMPLE_REF_RE = re.compile(r'(\d+)[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+R\b')
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
  def ParseTrailer(cls, data, start=0, end_ofs_out=None):
    """Parse PDF trailer at offset start."""
    # TODO(pts): Add unit test.
    # TODO(pts): Proper PDF token sequence parsing, for the end of the dict.
    scanner = PdfObj.PDF_TRAILER_RE.scanner(data, start)
    match = scanner.match()
    if not match:
      raise PdfTokenParseError(
          'bad trailer data: %r' % data[start : start + 256])
    if end_ofs_out is not None:
      end_ofs_out.append(match.end(1))
    trailer_obj = PdfObj(None)
    # TODO(pts): No need to strip with proper PDF token sequence parsing.
    trailer_obj.head = match.group(1).strip(
        PdfObj.PDF_WHITESPACE_CHARS)
    trailer_obj.Set('XRefStm', None)
    # We don't remove 'Prev' here, the caller might be interested.
    return trailer_obj

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
        list_obj = cls._ParseTokens(
            data=data, start=2, end=end, count_limit=end)
      else:
        list_obj = cls._ParseTokens(
            data=data, start=start, end=end, scanner=scanner, match=match,
            count_limit=end)
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
    return cls._ParseTokens(data, start, end, end)

  @classmethod
  def ParseTokenList(cls, data, count_limit=None, start=0, end=None,
                     end_ofs_out=None):
    """Return an array of parsed PDF values.

    Limitation: If the object end with `x y R', then count_limit is enforced
    at `x'. This is not a problem for object streams, because uncontained
    reference values are forbidden there.

    As soon as count_limit is reached, the rest of the string is not parsed,
    and it is not even checked for syntax errors.

    Args:
      data: String containing a PDF token sequence. It might contain leading
        or trailing whitespace.
    Returns:
      A list of parsed PDF values (None, int, bool or str).
    Raises:
      PdfTokenParseError:
    """
    if end is None:
      end = len(data)
    if count_limit is None:
      count_limit = end
    return cls._ParseTokens(data, start, end, count_limit,
                            end_ofs_out=end_ofs_out)

  @classmethod
  def _ParseTokens(cls, data, start, end, count_limit,
                   scanner=None, match=None, end_ofs_out=None):
    """Helper method to scan tokens and build values in data[start : end].

    Limitation: If the object end with `x y R', then count_limit is enforced
    at `x'. This is not a problem for object streams, because uncontained
    reference values are forbidden there.

    As soon as count_limit is reached, the rest of the string is not parsed,
    and it is not even checked for syntax errors.

    Raises:
      PdfTokenParseError:
    """
    if count_limit <= 0:
      return []
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
        if len(list_obj) >= count_limit:
          if end_ofs_out is not None:
            end_ofs_out.append(start)
          return list_obj
      match = scanner.match()
    if not cls.PDF_WHITESPACE_AT_EOS_RE.scanner(data, start, end).match():
      # TODO(pts): Be more specific, e.g. if we get this in a truncated
      # string literal `(foo'.
      raise PdfTokenParseError(
          'token list parse error at %d, got %r' %
          (start, data[start : start + 16]))
    if end_ofs_out is not None:
      end_ofs_out.append(start)
    return list_obj

  @classmethod
  def ParseXrefStreamWidths(cls, w_value):
    """Parse the /W key of a PDF cross-reference stream.

    Args:
      w_value: Result of trailer_obj.Get('W').
    Returns:
      A tuple of 3 integers.
    Raises:
      PdfXrefStreamWidthsError:
    """
    if w_value is None:
      raise PdfTokenParseError('missing /W in xref object')
    if not isinstance(w_value, str) or not w_value.startswith('['):
      raise PdfTokenParseError('item /W in xref object is not an array')
    widths = PdfObj.ParseArray(w_value)
    if (len(widths) != 3 or
        [1 for item in widths if not isinstance(item, int) or
         item < 0 or item > 10] or
        widths[1] < 1):
      raise PdfTokenParseError('bad /W array: %r' % widths)
    return tuple(widths)

  def GetXrefStream(self):
    """Parse and return the xref stream data and its parameters.
    
    Returns:
      Tuple (w0, w1, w2, index0, index1, xref_data), where w0, w1 and w2 are
      the field lengths; index is a tuple of an even number of values:
      startidx, count for each subsection; and xref_data is the uncompressed
      xref stream data,
    Raises:
      PdfXrefStreamError:
    """
    if self.Get('Type') != '/XRef':
      raise PdfXrefStreamError('expected /Type/XRef for xref stream')
    widths = list(self.ParseXrefStreamWidths(self.Get('W')))
    index_value = self.Get('Index')
    if index_value is None:
      size = self.Get('Size')
      if not isinstance(size, int) or size < 0:
        raise PdfXrefStreamError('bad or missing /Size for xref stream')
      index = [0, size]
    else:
      if not isinstance(index_value, str) or not index_value.startswith('['):
        raise PdfTokenParseError('item /Index in xref object is not an array')
      index = tuple(PdfObj.ParseArray(index_value))
      if (not index or len(index) % 2 != 0 or
          [1 for item in index if not isinstance(item, int) or item < 0] or
          [1 for i in xrange(1, len(index), 2) if index[i] <= 0]):
        raise PdfTokenParseError('bad /Index array: %r' % (index,))
    xref_data = self.GetUncompressedStream()
    if len(xref_data) % sum(widths) != 0:
      raise PdfXrefStreamError('data length does not match /W: %r' % widths)
    if len(xref_data) / sum(widths) != sum(
        index[i] for i in xrange(1, len(index), 2)):
      raise PdfXrefStreamError('data length does not match /Index: '
                               'widths=%r index=%r' % (withds, index))
    widths.append(index)
    widths.append(xref_data)
    return tuple(widths)

  def GetAndClearXrefStream(self):
    """Like GetXrefStream, and removes xref stream entries from self.head."""
    xref_tuple = self.GetXrefStream()
    self.stream = None
    self.Set('Type', None)
    self.Set('W', None)
    self.Set('Index', None)
    self.Set('Filter', None)
    self.Set('Length', None)
    self.Set('DecodeParms', None)
    return xref_tuple

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
      whitespace; with '(' string literals. It may contain \n only in
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
          # TODO(pts): Keep the original generation number (match.group(2))
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
  def SimpleValueToString(cls, value):
    if isinstance(value, str):
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

  def HasImageToHide(self):
    """Return bool indicating if we contain /Image to hide from Multivalent."""
    head = self._head
    if head is not None:
      if ('/Subtype' not in head or
          '/Image' not in head or 
          '/Filter' not in head):
        return False
    if self.Get('Subtype') != '/Image':
      return False
    filter = self.Get('Filter')
    return isinstance(filter, str) and filter[0] in '[/'

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
    palette_size = cls.GetRgbPaletteSize(palette)
    i = 0
    while i < palette_size:
      if palette[i] != palette[i + 1] or palette[i] != palette[i + 2]:
        return False  # non-gray color in the palette
      i += 3
    return True

  @classmethod
  def GetRgbPaletteSize(cls, palette):
    """Retrun len(palette) // 3 * 3, doing some checks."""
    palette_size = len(palette)
    palette_mod = len(palette) % 3
    # Some buggy PDF generators create a palette which is 1 byte longer.
    # For testing palette_mod == 1: /mnt/mandel/warez/tmp/vrabimintest2.pdf
    assert palette_mod == 0 or (palette_mod == 1 and palette[-1] == '\n'), (
         'invalid palette size: %s' % palette_size)
    return palette_size - palette_mod

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
    palette_size = cls.GetRgbPaletteSize(palette)
    if palette_size < len(palette):
      return palette[:palette_size]
    else:
      return palette

  def DetectInlineImage(self, objs=None):
    """Detect whether self is a form XObject with an inline image.

    As an implementation limitation, this detects only inline
    images created by sam2p.
    TODO(pts): Add support for more.

    Args:
      objs: None or a dict mapping object numbers to PdfObj objects. It will be
        passed to ResolveReferences.
    Returns:
      None if not an inline images, or the tuple
      (width, height, image_obj), where image_obj.stream is valid,
      but keys are not, they might still come from self.
    """
    # TODO(pts): Is re.search here fast enough?; PDF comments?
    if (not re.search(r'/Subtype[\0\t\n\r\f ]*/Form\b', self.head) or
        not self.head.startswith('<<') or
        not self.stream is not None or
        self.Get('Subtype') != '/Form' or
        self.Get('FormType', 1) != 1 or
        # !! get rid of these checks once we can decompress anything
        self.Get('Filter') not in (None, '/FlateDecode') or
        self.Get('DecodeParms') is not None or
        not str(self.Get('BBox')).startswith('[')): return None

    bbox = map(PdfObj.GetNumber, PdfObj.ParseArray(self.Get('BBox')))
    if (len(bbox) != 4 or bbox[0] != 0 or bbox[1] != 0 or
        bbox[2] is None or bbox[2] < 1 or bbox[2] != int(bbox[2]) or
        bbox[3] is None or bbox[3] < 1 or bbox[3] != int(bbox[3])):
      return None
    width = int(bbox[2])
    height = int(bbox[3])

    stream = self.GetUncompressedStream(objs=objs)
    # TODO(pts): Match comments etc.
    match = re.match(
        r'q[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+0[\0\t\n\r\f ]+0[\0\t\n\r\f ]+'
        r'(\d+)[\0\t\n\r\f ]+0[\0\t\n\r\f ]+0[\0\t\n\r\f ]+cm[\0\t\n\r\f ]+'
        r'BI[\0\t\n\r\f ]*(/(?s).*?)ID(?:\r\n|[\0\t\n\r\f ])', stream)
    if not match: return None
    if int(match.group(1)) != width or int(match.group(2)) != height:
      return None
    # Run CompressValue so we get it normalized, and we can do easier
    # regexp matches and substring searches.
    inline_dict = PdfObj.CompressValue(
        match.group(3), do_emit_strings_as_hex=True)
    stream_start = match.end()

    stream_tail = stream[-16:]
    # TODO(pts): What if \r\n in front of EI? We don't support that.
    match = re.search(
        r'[\0\t\n\r\f ]EI[\0\t\n\r\f ]+Q[\0\t\n\r\f ]*\Z', stream_tail)
    if not match: return None
    stream_end = len(stream) - len(stream_tail) + match.start()
    stream = stream[stream_start : stream_end]

    inline_dict = re.sub(
        r'/([A-Za-z]+)\b',
        lambda match: '/' + self.INLINE_IMAGE_UNABBREVIATIONS.get(
            match.group(1), match.group(1)), inline_dict)
    image_obj = PdfObj('0 0 obj<<%s>>endobj' % inline_dict)
    if (image_obj.Get('Width') != width or
        image_obj.Get('Height') != height):
      return None
    image_obj.Set('Length', len(stream))
    image_obj.stream = stream
    return width, height, image_obj

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
        not included, except for a single whitespace is only after
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
              elif c == '\n':
                string_output.append(data[i : j])
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
        raise PdfTokenParseError('syntax error, expecting PDF token, got %r' %
                                 data[i])

    assert i <= data_size
    output_data = ''.join(output)
    assert output_data
    if end_ofs_out is not None:
      end_ofs_out.append(i)
    return output_data

  def GetUncompressedStream(self, objs=None):
    """Return the uncompressed stream data in this obj.

    Args:
      objs: None or a dict mapping object numbers to PdfObj objects. It will be
        passed to ResolveReferences.
    Returns:
      A string containing the stream data in this obj uncompressed.
    """
    assert self.stream is not None
    filter = self.Get('Filter')
    if filter is None: return self.stream
    decodeparms = self.Get('DecodeParms') or ''
    if objs is None:
      objs = {}
    filter, _ = self.ResolveReferences(filter, objs)
    decodeparms, _ = self.ResolveReferences(decodeparms, objs)
    if filter == '/FlateDecode' and '/Predictor' not in decodeparms:
      return PermissiveZlibDecompress(self.stream)
    is_gs_ok = True  # TODO(pts): Add command-line flag to disable.
    if not is_gs_ok:
      raise FilterNotImplementedError('filter not implemented: ' + filter)
    tmp_file_name = 'pso.filter.tmp.bin'
    f = open(tmp_file_name, 'wb')
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
        '%s -dNODISPLAY -q -sINFN=%s -c \'/i INFN(r)file<</CloseSource true '
        '/Intent 2/Filter %s%s>>/ReusableStreamDecode filter def '
        '/o(%%stdout)(w)file def/s 4096 string def '
        '{i s readstring exch o exch writestring not{exit}if}loop '
        'o closefile quit\'' %
        (GetGsCommand(),
         ShellQuoteFileName(tmp_file_name), filter, decodeparms_pair))
    print >>sys.stderr, (
        'info: decompressing %d bytes with Ghostscript '
        '/Filter%s%s' % (len(self.stream), filter, decodeparms_pair))
    f = os.popen(gs_defilter_cmd, 'rb')
    data = f.read()  # TODO(pts): Handle IOError etc.
    assert not f.close(), 'Ghostscript decompression failed: %s' % (
        gs_defilter_cmd)
    os.remove(tmp_file_name)
    return data

  @classmethod
  def ResolveReferences(cls, data, objs, do_strings=False):
    """Resolve references (<x> <y> R) in a PDF token sequence.

    As a side effect, this function may remove comments and whitespace
    from data.

    Args:
      data: A string containing a PDF token sequence; or None, or an int
        or a float or True or False.
      objs: Dictionary mapping object numbers to PdfObj instances.
      do_strings: Boolean indicating whether to embed the referred
        streams as strings.
    Returns:
      (new_data, has_changed). has_changed may be True even if there
      were no references found, but comments were removed.
    Raises:
      PdfTokenParseError:
      PdfReferenceTargetMissing:
      TypeError:
    """
    # !! always do a ResolveReferences to flatten /Filter and /DecodeParms.
    if not isinstance(objs, dict):
      raise TypeError
    if (data is None or isinstance(data, int) or isinstance(data, long) or
        isinstance(data, float) or isinstance(data, bool)):
      return data, False
    if not isinstance(data, str):
      raise TypeError
    if not ('R' in data and #cls.PDF_END_OF_REF_RE.search(data) and
            cls.PDF_REF_RE.search(data)):
      # Shortcut if there are no references in data.
      return data, False

    current_obj_nums = []

    def Replacement(match):
      obj_num = int(match.group(1))
      if obj_num < 1:
        raise PdfTokenParseError('invalid object number: %d' % obj_num)
      gen_num = int(match.group(2))
      if gen_num != 0:
        raise PdfTokenParseError('invalid generation number: %d' % gen_num)
      obj = objs.get(obj_num)
      if obj is None:
        raise PdfReferenceTargetMissing(
            'missing object: %d 0 obj' % obj_num)
      if obj.stream is None:
        new_data = obj.head.strip(cls.PDF_WHITESPACE_CHARS)
        if ('R' in new_data and cls.PDF_END_OF_REF_RE.search(new_data) and
            cls.PDF_REF_RE.search(new_data)):
          # Do the recursive replacement in new_data.
          if obj_num in current_obj_nums:
            current_obj_nums.append(obj_num)
            raise PdfReferenceRecursiveError(
                'recursive reference chain: %r' % current_obj_nums)
          current_obj_nums.append(obj_num)
          if '%' in new_data or '(' in new_data:
            new_data = cls.CompressValue(new_data, do_emit_strings_as_hex=True)
            new_data = cls.PDF_REF_RE.sub(Replacement, new_data)
            new_data = cls.CompressValue(new_data)
          else:
            new_data = cls.PDF_REF_RE.sub(Replacement, new_data)
          current_obj_nums.pop()
        elif '%' in new_data:
          # Remove trailing comment.
          new_data = cls.CompressValue(new_data)
        return new_data
      else:
        if not do_strings:
          raise UnexpectedStreamError(
              'unexpected stream in: %d 0 obj' % obj_num)
        return obj.EscapeString(obj.GetUncompressedStream(objs=objs))

    data0 = data
    if '(' in data or '%' in data:
      data = cls.CompressValue(data, do_emit_strings_as_hex=True)
      # Compress strings back to non-hex once the references are
      # resolved.
      do_compress = True
    else:
      do_compress = False
    # There is no need to add whitespace around the replacement, good.
    # TODO(pts): If the replacement for a reference is a `(string)' (or an
    # array etc.), then remove the whitespace around the `<x> <y> R'.
    data = cls.PDF_REF_RE.sub(Replacement, data)
    if do_compress:
      data = cls.CompressValue(data)
    return data, data0 != data

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
    """Serialize a CFF DICT to a string. Inverse of ParseCffDict."""
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
            output.append(chr(28) + struct.pack('>H', operand & 0xffff))
          elif ~0x7fffffff <= operand <= 0x7fffffff:
            output.append(chr(29) + struct.pack('>L', operand & 0xffffffff))
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

  def FixFontNameInType1C(self, new_font_name='F', objs=None):
    """Fix the FontName in a /Subtype/Type1C object.

    Args:
      objs: None or a dict mapping object numbers to PdfObj objects. It will be
        passed to ResolveReferences.
    """
    # The documentation http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
    # was used to write this function.
    assert self.Get('Subtype') == '/Type1C'
    data = self.GetUncompressedStream(objs=objs)
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
    """Return a dictionary useful as a PDF image."""
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
    if do_check_dimensions:
      assert pdf_obj.Get('Width') == pdf_image_data['Width'], (
          'image Width mismatch: %r vs %r' % (pdf_obj.head, pdf_image_data))
      assert pdf_obj.Get('Height') == pdf_image_data['Height'], (
          'image Height mismatch: %r vs %r' % (pdf_obj.head, pdf_image_data))
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
    # Don't pdf_obj.Set('Decode', ...): it is good as is.
    pdf_obj.stream = pdf_image_data['.stream']

  def CompressToZipPng(self):
    """Compress self.idat to self.compression == 'zip-png'."""
    assert self
    if self.compression == 'zip-png':
      # For testing: ./pdfsizeopt.py --use-jbig2=false --use-pngout=false pts2ep.pdf 
      return self
    elif self.compression == 'zip':
      idat = PermissiveZlibDecompress(self.idat)  # raises zlib.error
    elif self.compression == 'none':
      idat = self.idat
    else:
      # 'zip-tiff' is too complicated now, especially for self.bpc != 8, where
      # we have fetch previous samples with bitwise operations.
      raise FormatUnsupported(
          'cannot compress %s to zip-png' % self.compression)

    bytes_per_row = self.bytes_per_row
    useful_idat_size = bytes_per_row * self.height
    assert len(idat) >= useful_idat_size, 'PNG IDAT too short (truncated?)'

    # For testing: ./pdfsizeopt.py --use-jbig2=false --use-pngout=false pts2ep.pdf 
    # For testing: http://code.google.com/p/pdfsizeopt/issues/detail?id=26
    # For testing: idat_size_mod == 1 in vrabimintest.pdf
    output = []
    for i in xrange(0, useful_idat_size, bytes_per_row):
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
      output.append(struct.pack('>l', zlib.crc32(chunk_type)))

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
      content_stream = content_obj.GetUncompressedStream(objs=pdf.objs)
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
        computed_crc = struct.pack('>l', zlib.crc32(chunk_type + chunk_data))
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

  __slots__ = ['objs', 'trailer', 'version', 'file_name', 'file_size',
               'do_ignore_generation_numbers', 'has_generational_objs']

  def __init__(self, do_ignore_generation_numbers=False):
    self.do_ignore_generation_numbers = bool(do_ignore_generation_numbers)
    self.has_generational_objs = False
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
    if isinstance(file_data, str):
      # Treat file_data as file name.
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
    self.has_generational_objs = False
    self.file_name = f.name
    self.file_size = len(data)
    match = PdfObj.PDF_VERSION_HEADER_RE.match(data)
    if not match:
      raise PdfTokenParseError('unrecognized PDF signature %r' % data[0: 16])
    self.version = match.group(1)
    self.objs = {}
    self.trailer = None

    try:
      obj_starts, self.has_generational_objs = self.ParseUsingXref(
          data, do_ignore_generation_numbers=self.do_ignore_generation_numbers)
    except PdfXrefStreamError, exc:
      # !! TODO(pts): Implement a fallback, uncompress /Type/ObjStm etc.
      raise
    except PdfXrefError, exc:
      print >>sys.stderr, 'warning: problem with xref table: %s' % exc
      print >>sys.stderr, (
          'warning: trying to load objs without the xref table')
      obj_starts, self.has_generational_objs = self.ParseWithoutXref(
          data, do_ignore_generation_numbers=self.do_ignore_generation_numbers)

    assert 'trailer' in obj_starts, 'no PDF trailer'
    assert len(obj_starts) > 1, 'no objects found in PDF (file corrupt?)'
    obj_count = len(obj_starts)
    obj_count_extra = ''
    if 'xref' in obj_starts:
      obj_count_extra += ' + xref'
      obj_count -= 1
    if 'trailer' in obj_starts:
      obj_count_extra += ' + trailer'
      obj_count -= 1
    print >>sys.stderr, 'info: separated to %s objs%s' %  (
        obj_count, obj_count_extra)
    last_ofs = trailer_ofs = obj_starts.pop('trailer')
    if isinstance(trailer_ofs, PdfObj):
      self.trailer = trailer_ofs
      trailer_ofs = None
      last_ofs = len(data)
      obj_starts.pop('xref', None)
    else:
      self.trailer = PdfObj.ParseTrailer(data, start=trailer_ofs)
      self.trailer.Set('Prev', None)
      if 'xref' in obj_starts:
        last_ofs = min(trailer_ofs, obj_starts.pop('xref'))

    def ComparePair(a, b):
      return a[0].__cmp__(b[0]) or a[1].__cmp__(b[1])

    obj_items = []
    preparsed_objs = {}
    for obj_num in obj_starts:
      obj_ofs = obj_starts[obj_num]
      if isinstance(obj_ofs, PdfObj):
        preparsed_objs[obj_num] = obj_ofs
      else:
        obj_items.append((obj_ofs, obj_num))
    obj_items.sort(ComparePair)

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
    for obj_num in obj_data:
      this_obj_data = obj_data[obj_num]
      if ('endstream' not in this_obj_data and
          '<' not in this_obj_data and
          '(' not in this_obj_data):
        try:
          self.objs[obj_num] = PdfObj(
              obj_data[obj_num],
              file_ofs=obj_starts[obj_num],
              do_ignore_generation_numbers=self.do_ignore_generation_numbers)
        except PdfTokenParseError, e:
          print >>sys.stderr, (
              'warning: cannot parse obj %d: %s.%s: %s' % (
              obj_num, e.__class__.__module__, e.__class__.__name__, e))

    # Second pass once we have all length numbers.
    for obj_num in obj_data:
      if obj_num not in self.objs:
        try:
          self.objs[obj_num] = PdfObj(
              obj_data[obj_num], objs=self.objs, file_ofs=obj_starts[obj_num],
              do_ignore_generation_numbers=self.do_ignore_generation_numbers)
        except PdfTokenParseError, e:
          print >>sys.stderr, (
              'warning: cannot parse obj %d: %s.%s: %s' % (
              obj_num, e.__class__.__module__, e.__class__.__name__, e))

    self.objs.update(preparsed_objs)
    return self

  @classmethod
  def ParseUsingXrefStream(cls, data, do_ignore_generation_numbers,
                           xref_ofs, match):
    """Determine obj offsets in a  PDF file using the cross-reference stream.

    Args:
      data: String containing the PDF file.
    Returns:
      (obj_starts, has_generational_objs)
      obj_starts is a dict mapping object numbers (and the string
      'trailer', possibly also 'xref') to pre-parsed PdfObj instances.
    Raises:
      PdfXrefStreamError: If the cross-reference stream is corrupt.
      PdfXrefError: If the cross-reference table is corrupt, but there is
        a chance to parse the file without it.
      AssertionError: If the PDF file us totally unparsable.
      NotImplementedError: If the PDF file needs parsing code not implemented.
      other: If the PDF file us totally unparsable.
    """
    has_generational_objs = False
    # Parse the cross-reference stream (xref stream).
    # Maps object numbers to offset or (objstm_obj_num, index) values.
    obj_starts = {'xref': xref_ofs}  # 'xref' is just informational.
    # Maps /Type/ObjStm object numbers to inner_obj_headbufs, or
    # None if that object stream is not loaded yet.
    obj_streams = {}
    trailer_obj = None
    xref_obj_nums = set()

    while True:
      xref_obj_num = int(match.group(1))
      xref_generation = int(match.group(2))
      if xref_generation:
        if not do_ignore_generation_numbers:
          raise NotImplementedError(
              'generational objects (in xref %s %s) not supported at %d' %
              (xref_obj_num, xref_generation, xref_ofs))
        has_generational_objs = True
      if xref_obj_num in xref_obj_nums:
        raise PdfXrefStreamError('duplicate xref obj %d' % xref_obj_num)
      xref_obj_nums.add(xref_obj_num)
      try:
        xref_obj = PdfObj(data, start=xref_ofs, file_ofs=xref_ofs)
      except PdfTokenParseError, e:
        raise PdfXrefStreamError('parse xref obj %d: %s' % (xref_obj_num, e))
      if trailer_obj is None:
        trailer_obj = xref_obj

      # Parse the xref stream data.
      # TODO(pts): Handle the various exceptions raised by
      #            trailer_obj.GetUncompressedStream().
      w0, w1, w2, index, xref_data = trailer_obj.GetAndClearXrefStream()
      w01 = w0 + w1
      w012 = w01 + w2
      ii = 0
      obj_num = None
      ii_remaining = 0
      for i in xrange(0, len(xref_data), w012):
        if not ii_remaining:
          # PdfObj.GetXrefStream() guarantees that we get a positive
          # ii_remaining and we don't exhaust the index array below.
          obj_num = index[ii]
          ii_remaining = index[ii + 1]
          ii += 2
        else:
          obj_num += 1
          ii_remaining -= 1
        if w0:
          f0 = cls.MSBFirstToInteger(xref_data[i : i + w0])
        else:
          f0 = 1
        f1 = cls.MSBFirstToInteger(xref_data[i + w0 : i + w01])
        if w2:
          f2 = cls.MSBFirstToInteger(xref_data[i + w01 : i + w012])
        else:
          f2 = 0
        if not f0:  # A free object, ignore it.
          continue
        if obj_num in obj_starts:
          raise PdfXrefStreamError('duplicate obj %d' % obj_num)
        if f0 == 1:  # f1 is the object offset in the file.
          if f2:
            if not do_ignore_generation_numbers:
              raise NotImplementedError(
                  'generational objects (in %s %s) not supported at %d' %
                  (obj_num, f2, xref_ofs))
            has_generational_objs = True
          if f1 < 9:
            raise PdfXrefStreamError('offset of obj %d too small: %d' %
                               (obj_num, f1))
          obj_starts[obj_num] = f1
        elif f0 == 2:
          # f1: Object number of the object stream of obj_num.
          # f2: Index of obj_num within its object stream.
          obj_starts[obj_num] = (f1, f2)
          obj_streams.setdefault(f1, None)
      trailer_obj.Set('Prev', None)
      if xref_obj is not trailer_obj:
        dict_obj = xref_obj._cache
        assert dict_obj is not None, '/Type/ObjStm obj not parsed yet.'
        # TODO(pts): Is this the correct way to merge the trailer part of
        # xref objects?
        for name in sorted(dict_obj):
          if name in ('Prev', 'Size'):
            continue
          if trailer_obj.Get(name) is not None:
            raise PdfXrefStreamError(
                'duplicate name in xref streams: /%s' % name)
          trailer_obj.Set(name, dict_obj[name])
      prev = xref_obj.Get('Prev')
      if prev is None:
        break
      # TODO(pts): Test this.
      if not isinstance(prev, int) or prev < 9:
        raise PdfXrefStreamError('invalid /Prev at %d: %r' % (xref_ofs, prev))
      match = PdfObj.PDF_OBJ_DEF_CAPTURE_RE.scanner(data, xref_ofs).match()
      if not match:
        raise PdfXrefStreamError('could not find obj at /Prev at %d: %d' %
                                 (xref_ofs, prev))
      xref_ofs = prev
    print >>sys.stderr, (
        'info: found %d obj offsets and %d obj streams in xref stream' %
        (len(obj_starts) - 1,  # `- 1' for the key 'xref' itself.
         len(obj_streams)))
    for xref_obj_num in sorted(xref_obj_nums):
      obj_start = obj_starts.get(xref_obj_num)
      if obj_start is None:
        print >>sys.stderr, (
            'warning: missing offset for xref stream obj %d' % xref_obj_num)  
      else:
        if not isinstance(obj_start, int):
          print >>sys.stderr, (
              'warning: in-object-stream xref stream obj %d' % xref_obj_num)
        del obj_starts[xref_obj_num]

    # Load the object streams.
    for obj_num in sorted(obj_streams):
      obj_start = obj_starts.get(obj_num)
      if obj_start is None:
        raise PdfXrefStreamError('missing obj stream %d' % obj_num)
      if not isinstance(obj_start, int):
        raise PdfXrefStreamError('in-object-stream obj stream %d' % obj_num)
      try:
        objstm_obj = PdfObj(data, start=obj_start, file_ofs=obj_start)
      except PdfTokenParseError, e:
        raise PdfXrefStreamError('parse objstm obj %d: %s' % (obj_num, e))
      if objstm_obj.Get('Type') != '/ObjStm':
        raise PdfXrefStreamError(
            'expected /Type/ObjStm for obj %d' % obj_num)
      n = objstm_obj.Get('N')  # Number of objects in objstm_obj.
      if n is None:
        raise PdfXrefStreamError('missing /N in objstm obj %d' % obj_num)
      if not isinstance(n, int) or n <= 1:
        raise PdfXrefStreamError('invalid /N in objstm obj %d' % obj_num)
      first = objstm_obj.Get('First')  # Offset of the first object.
      if first is None:
        raise PdfXrefStreamError('missing /First in objstm obj %d' % obj_num)
      if not isinstance(first, int) or first <= 0:
        raise PdfXrefStreamError('invalid /First in objstm obj %d' % obj_num)
      if objstm_obj.Get('Extends') is not None:
        # TODO(pts): Implement this.
        raise NotImplementedError('/Extends in /Type/ObjStm not implemented')
      # TODO(pts): Handle the various exceptions raised by
      #            trailer_obj.GetUncompressedStream().
      objstm_data = objstm_obj.GetUncompressedStream()
      objstm_obj = None  # Save memory.
      end_ofs_ary = []
      numbers = PdfObj.ParseTokenList(
          objstm_data, 2 * n, end_ofs_out=end_ofs_ary)
      end_ofs = end_ofs_ary[0]
      match = PdfObj.PDF_COMMENTS_OR_WHITESPACE_RE.scanner(
          objstm_data, end_ofs).match()
      if match:  # Skip whitespace and comments after the last number.
        # TODO(pts): Maybe skip only one character of whitespace?
        end_ofs = match.end()
      if first < end_ofs:
        print >>sys.stderr, (
            'warning: first too early in objstm obj %d: first=%d end_ofs=%d'
            % (obj_num, first, end_ofs))
      if len(numbers) != 2 * n:
        raise PdfXrefStreamError(
            'expected %d, but got %d values in token list objstm obj %d' %
            (2 * n, len(numbers), obj_num))
      inner_obj_nums = []
      # List of (str) buffer objects corresponding to the PDF token stream
      # string in the respective inner_obj_nums item.
      inner_obj_headbufs = []
      prev_offset = -1
      for i in xrange(0, len(numbers), 2):
        inner_obj_num = numbers[i]
        inner_obj_ofs = numbers[i + 1]
        if not isinstance(inner_obj_num, int):
          raise PdfXrefStreamError(
              'expected int inner_obj_num in objstm obj %d' % obj_num)
        if not isinstance(inner_obj_ofs, int):
          raise PdfXrefStreamError(
              'expected int inner_obj_ofs in objstm obj %d' % obj_num)
        if inner_obj_num < 1:
          raise PdfXrefStreamError(
              'bad inner_obj_num %d in objstm obj %d' % obj_num)
        if inner_obj_ofs < 0 or inner_obj_ofs + first >= len(objstm_data):
          raise PdfXrefStreamError(
              'bad inner_obj_obs %d in objstm obj %d' % obj_num)
        inner_obj_ofs += first
        inner_obj_nums.append(inner_obj_num)
        # Although the PDF spec doesn't say, we assume that inner
        # (compressed) objects don't overlap. This is reasonable, because
        # the PDF spec requires increasing offsets.
        if prev_offset > 0:
          inner_obj_headbufs.append(
              buffer(objstm_data, prev_offset, inner_obj_ofs - prev_offset))
        prev_offset = inner_obj_ofs
      if prev_offset > 0:
        inner_obj_headbufs.append(
            buffer(objstm_data, prev_offset, len(objstm_data) - prev_offset))
      assert len(inner_obj_nums) == len(inner_obj_headbufs)
      for i in xrange(0, len(inner_obj_nums), 2):
        inner_obj_num = inner_obj_nums[i]
        inner_obj_start = obj_starts.get(inner_obj_num)
        if inner_obj_start is not None and inner_obj_start != (obj_num, i):
          raise PdfXrefStreamError(
              'location mismatch for compressed obj %d: '
              'objstm obj %d has index %d, xref stream has %r' %
              (inner_obj_num, obj_num, i, obj_starts.get(inner_obj_num)))
        obj_streams[obj_num] = inner_obj_headbufs

    # Parse used compressed objects, and add them to obj_starts with the
    # PdfObj (instead of the offset) as a value.
    for obj_num in sorted(obj_starts):
      obj_start = obj_starts.get(obj_num)
      if not isinstance(obj_start, int):
        objstm_obj_num, i = obj_start
        inner_obj_headbufs = obj_streams.get(objstm_obj_num)
        assert inner_obj_headbufs  # Already set above.
        if i >= len(inner_obj_headbufs):
          raise PdfXrefStreamError(
              'too few compressed objs (%d) in objstm obj %d, '
              'needed index %d for obj %d' %
              (len(inner_obj_headbufs), objstm_obj_num, i, obj_num))
        if isinstance(inner_obj_headbufs[i], PdfObj):
          obj_starts[obj_num] = inner_obj_headbufs[i]
        else:
          obj_starts[obj_num] = inner_obj_headbufs[i] = PdfObj(
              '%d 0 obj\n%s\nendobj\n' % (obj_num, inner_obj_headbufs[i]))

    for obj_num in sorted(obj_streams):
      del obj_starts[obj_num]
    obj_starts['trailer'] = trailer_obj
    return obj_starts, has_generational_objs

  @classmethod
  def ParseUsingXref(cls, data, do_ignore_generation_numbers):
    """Determine obj offsets in a  PDF file using the cross-reference table.

    If this method detects a cross-reference stream, it calls
    cls.ParseUsingXrefStream instead.

    Args:
      data: String containing the PDF file.
    Returns:
      (obj_starts, has_generational_objs)
      obj_starts is a dict mapping object numbers (and the string
      'trailer', possibly also 'xref') to their start offsets (or to
      pre-parsed PdfObj instances) within a file.
    Raises:
      PdfXrefStreamError: If the cross-reference stream is corrupt.
      PdfXrefError: If the cross-reference table is corrupt, but there is
        a chance to parse the file without it.
      AssertionError: If the PDF file us totally unparsable.
      NotImplementedError: If the PDF file needs parsing code not implemented.
      other: If the PDF file us totally unparsable. Example: zlib.error.
    """
    match = PdfObj.PDF_STARTXREF_EOF_RE.search(data[-128:])
    if not match:
      raise PdfXrefError('startxref+%%EOF not found')
    xref_ofs = int(match.group(1))
    match = PdfObj.PDF_OBJ_DEF_CAPTURE_RE.scanner(data, xref_ofs).match()
    if match:
      return cls.ParseUsingXrefStream(data, do_ignore_generation_numbers,
                                      xref_ofs, match)

    has_generational_objs = False
    obj_starts = {'xref': xref_ofs}  # 'xref' is just informational.
    obj_starts_rev = {}
    # Set of object numbers not to be overwritten.
    keep_obj_nums = set()
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
        # For testing whitespace before trailer: enc.pdf
        # obj_count == 0 is fine, see
        # http://code.google.com/p/pdfsizeopt/issues/detail?id=25
        match = re.match(
            r'(\d+)\s+(\d+)\s+|[\0\t\n\r\f ]*(xref|trailer)\s', xref_head)
        if not match:
          raise PdfXrefError('xref subsection syntax error at %d' % xref_ofs)
        if match.group(3) is not None:
          xref_ofs += match.start(3)
          break
        obj_num = int(match.group(1))
        obj_count = int(match.group(2))
        xref_ofs += match.end(0)
        while obj_count > 0:
          match = re.match(
              r'(\d{10})\s(\d{5})\s([nf])\s\s', data[xref_ofs : xref_ofs + 20])
          if not match:
            raise PdfXrefError('syntax error in xref entry at %s' % xref_ofs)
          if match.group(3) == 'n':
            generation = int(match.group(2))
            if generation != 0:
              if not do_ignore_generation_numbers:
                raise NotImplementedError(
                    'generational objects (in %s %s n) not supported at %d' %
                    (match.group(1), match.group(2), xref_ofs))
              has_generational_objs = True
            obj_ofs = int(match.group(1))
            if obj_num in obj_starts:
              if obj_num in keep_obj_nums:
                # for testing: obj 5 in bfilter.pdf
                # It is not tested if this assignment is replaced by `pass',
                # to make /Prev override.
                obj_ofs = 0
              else:
                raise PdfXrefError('duplicate obj %s' % obj_num)
            if obj_ofs != 0:
              # for testing: obj 10 in pdfsizeopt_charts.pdf has offset 0:
              # "0000000000 00000 n \n"
              if obj_ofs in obj_starts_rev:
                raise PdfXrefError('duplicate use of obj offset %s: %s and %s' %
                                   (obj_ofs, obj_starts_rev[obj_ofs], obj_num))
              obj_starts_rev[obj_ofs] = obj_num
              # TODO(pts): Check that we match PdfObj.OBJ_DEF_RE at obj_ofs.
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

      # TODO(pts): How to test this?
      try:
        xref_ofs = PdfObj.ParseTrailer(data, start=xref_ofs).Get('Prev')
      except PdfTokenParseError, exc:
        raise PdfXrefError(str(exc))
      if xref_ofs is None:
        break
      if not isinstance(xref_ofs, int) and not isinstance(xref_ofs, long):
        raise PdfXrefError('/Prev xref offset not an int: %r' % xref_ofs)
      # Subsequent /Prev xref tables are not allowed to modify objects
      # we've already created.
      # for testing: obj 5 in bfilter.pdf
      keep_obj_nums.update(obj_starts)
    return obj_starts, has_generational_objs

  @classmethod
  def ParseWithoutXref(cls, data, do_ignore_generation_numbers=False):
    """Parse a PDF file without having a look at the cross-reference table.

    This method doesn't consult the cross-reference table (`xref'): it just
    searches for objects looking at '\nX Y obj' strings in `data'. 

    This method may find a false match, such as `( 1 0 obj )'.
    TODO(pts): Get rid of false matches. The problem is that we might have
    /Length of a stream as an indirect forward reference (usually if it's
    indirect, then it's forward), so we cannot be fully reliable this way.

    Args:
      data: String containing the PDF file.
    Returns:
      (obj_starts, has_generational_objs)
      objs_starts is adict mapping object numbers (and the string
      'trailer', possibly also 'xref') to their start offsets within a file.
    """
    # None, an int or 'trailer'.
    prev_obj_num = None
    obj_starts = {}
    has_generational_objs = False

    for match in re.finditer(
        r'[\n\r](?:(\d+)[\0\t\n\r\f ]+(\d+)[\0\t\n\r\f ]+obj\b|'
        r'trailer(?=[\0\t\n\r\f ]))',
        data):
      if match.group(1) is not None:
        prev_obj_num = int(match.group(1))
        generation = int(match.group(2))
        if generation != 0:
          if not do_ignore_generation_numbers:
            raise NotImplementedError(
                'generational objects (in %s %s n) not supported at %d' %
                (match.group(1), match.group(2), xref_ofs))
          has_generational_objs = True
        assert prev_obj_num not in obj_starts, 'duplicate obj %d' % prev_obj_num
        # Skip over '\n'
        obj_starts[prev_obj_num] = match.start(0) + 1
      else:
        prev_obj_num = 'trailer'
        # Allow multiple trailers. Keep the last one. This heuristic works
        # for http://code.google.com/p/pdfsizeopt/issues/detail?id=25 .
        # TODO(pts): Test multiple trailers with: pdf.a9p4/5176.CFF.a9p4.pdf
        # Skip over '\n'
        obj_starts[prev_obj_num] = match.start(0) + 1

    # TODO(pts): Learn to parse no trailer in PDF-1.5
    # (e.g. pdf_reference_1-7-o.pdf)
    assert prev_obj_num == 'trailer'
    return obj_starts, has_generational_objs

  @classmethod
  def GenerateXrefStream(cls, obj_numbers, obj_ofs, xref_ofs, trailer_obj):
    """Generate the xref stream for the specified trailer object.

    Add the appropriate, size-optimized trailer_obj.stream, add the
    following names: /Size, /Type, /W, add or remove some names: /Index.

    Please note that xref streams were introduced in PDF 1.5.

    Args:
      obj_numbers: List of object numbers the PDF contains. Generation
        numbers are all 0.
      obj_ofs: Dict mapping object numbers to object file offsets.
      xref_ofs: File offset of the xref stream (trailer_obj)
      trailer_obj: PdfObj whose .head contains the PDF trailer. Will be
        modified in place: .stream and some names added.
    """
    assert obj_numbers
    assert trailer_obj.head.startswith('<<')
    assert trailer_obj.stream is None
    trailer_obj.Set('Size', obj_numbers[-1] + 2)
    trailer_obj.Set('Type', '/XRef')
    has_free_obj = False
    max_ofs = xref_ofs
    max_ofs_size = 1
    if obj_numbers[0] != 0:
      trailer_obj.Set('Index', '[%d %d]' % (
          obj_numbers[0], obj_numbers[-1] - obj_numbers[0] + 2))
    else:
      trailer_obj.Set('Index', None)
    ofs_list = [obj_ofs[obj_num] for obj_num in obj_numbers]
    assert not ofs_list or ofs_list[-1] != xref_ofs
    ofs_list.append(xref_ofs)
    for i in xrange(1, len(obj_numbers)):
      if obj_numbers[i] - 1 != obj_numbers[i - 1]:
        has_free_obj = True
      max_ofs = max(max_ofs, ofs_list[i])
    
    while max_ofs >= 1 << (8 * max_ofs_size):
      max_ofs_size += 1
    if max_ofs_size > 8:
      raise NotImplementedError(
          'unsupported max_ofs_size=%d for max_ofs=%d' %
          (max_ofs_size, max_ofs))
    if has_free_obj:
      # TODO(pts): Consider encoding free objects as multiple ranges in
      # /Index instead of the direct encoding below. Maybe the result
      # will be smaller.
      ofs_output = []
      trailer_obj.Set('W', '[1 %d 0]' % max_ofs_size)
      free_entry = '\x00' * (max_ofs_size + 1)
      done_obj_num = 0
      if obj_numbers[0] == 1:  # Encode free obj 0 with an offset.
        trailer_obj.Set('Index', None)
        ofs_output.append(free_entry)
        done_obj_num = 1
      i = 0
      for ofs in ofs_list:
        if i < len(obj_numbers):
          while done_obj_num < obj_numbers[i]:
            ofs_output.append(free_entry)
            done_obj_num += 1
          i += 1
        ofs_output.append('\x01')
        if max_ofs_size <= 4:
          ofs_output.append(struct.pack('>L', ofs)[4 - max_ofs_size:])
        else:
          ofs_output.append(struct.pack('>Q', ofs)[8 - max_ofs_size:])
        done_obj_num += 1
      trailer_obj.SetStreamAndCompress(
          ''.join(ofs_output), predictor_width=max_ofs_size + 1)
      del ofs_output
    else:
      trailer_obj.Set('W', '[0 %d 0]' % max_ofs_size)
      if max_ofs_size == 1:
        data = struct.pack('>%dB' % len(ofs_list), *ofs_list)
      elif max_ofs_size == 2:
        data = struct.pack('>%dH' % len(ofs_list), *ofs_list)
      elif max_ofs_size == 3:
        data = ''.join(struct.pack('>L', ofs)[1:] for ofs in ofs_list)
      elif max_ofs_size == 4:
        data = struct.pack('>%dL' % len(ofs_list), *ofs_list)
      else:
        i = 8 - max_ofs_size
        data = ''.join(struct.pack('>Q', ofs)[i:] for ofs in ofs_list)
      trailer_obj.SetStreamAndCompress(data, predictor_width=max_ofs_size)

  def Save(self, file_name, do_update_file_name=True, do_hide_images=False,
           do_generate_xref_stream=True):
    """Save this PDF to file_name, return self.
    
    Args:
      file_name: PDF file name to save self to.
      do_update_file_name: Bool indicating whether to update self.file_name
        and self.file_size.
      do_hide_images: Bool indicating whether to hide images from Multivalent.
    Returns:
      self."""
    obj_count = len(self.objs)
    print >>sys.stderr, 'info: saving PDF with %s objs to: %s' % (
        obj_count, file_name)
    assert obj_count
    assert self.trailer.head.startswith('<<')
    assert self.trailer.head.endswith('>>')
    if do_generate_xref_stream:
      version = max(self.version, '1.5')
    else:
      version = self.version
    f = open(file_name, 'wb')
    try:
      # Emit header.
      output = ['%PDF-', version, '\n%\xD0\xD4\xC5\xD0\n']

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
        pdf_obj = self.objs[obj_num]
        if do_hide_images and pdf_obj.HasImageToHide():
          pdf_obj = PdfObj(pdf_obj)
          # We convert /Subtype/Image to /Subtype/ImagE and /Filter
          # to /FilteR and /DecodeParms to /DecodeParmS. This way we force
          # Multivalent not to treat the obj as image, i.e. not to recompress
          # it (suboptimally).
          assert pdf_obj.Get('FilteR') is None
          assert pdf_obj.Get('DecodeParmS') is None
          pdf_obj.Set('Subtype', 'ImagE')
          filter = pdf_obj.Get('Filter')
          if filter is not None:
            pdf_obj.Set('FilteR', filter)
            pdf_obj.Set('Filter', None)
          decodeparms = pdf_obj.Get('DecodeParms')
          if decodeparms is not None:
            pdf_obj.Set('DecodeParmS', decodeparms)
            pdf_obj.Set('DecodeParms', None)

          # Trick to force Multivalent not to uncompress + compress the
          # object.
          # For testing: multivalent_filter_test.pdf
          pdf_obj.Set('Filter', '/JPXDecode')
        pdf_obj.AppendTo(output, obj_num)

      trailer_obj = PdfObj(self.trailer)
      trailer_obj.Set('Size', obj_numbers[-1] + 1)
      trailer_obj.Set('Prev', None)
      trailer_obj.Set('XRefStm', None)
      trailer_obj.Set('Compress', None)  # emitted by Multivalent.jar
      # Emitted by Multivalent.jar etc., see section 10.3 in
      # pdf_reference_1-7.pdf .
      trailer_obj.Set('ID', None)
      assert trailer_obj.head.startswith('<<')
      assert trailer_obj.head.endswith('>>')
      assert trailer_obj.stream is None

      xref_ofs = GetOutputSize()
      if do_generate_xref_stream:  # Emit xref stream containing trailer.
        # TODO(pts): Please note that one more size optimization would also
        # be possible (which GenerateXrefStream doesn't do): converting small
        # objects to a (compressed) object stream (/Type/ObjStm). Multivalent
        # does that already.
        self.GenerateXrefStream(obj_numbers=obj_numbers, obj_ofs=obj_ofs,
                                xref_ofs=xref_ofs, trailer_obj=trailer_obj)
        trailer_obj.AppendTo(output, obj_numbers[-1] + 1)
      else:  # Emit xref and trailer.
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

        output.append('trailer\n%s\n' % trailer_obj.head)

      output.append('startxref\n%d\n' % xref_ofs)
      output.append('%%EOF\n')  # Avoid doubling % in printf().
      print >>sys.stderr, 'info: generated %s bytes (%s)' % (
          GetOutputSize(), FormatPercent(GetOutputSize(), self.file_size))

      # TODO(pts): Don't keep everything in memory.
      f.write(''.join(output))
    finally:
      f.close()
    if do_update_file_name:
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

/Map { % <array> <code> Map <array>
  [ 3 1 roll forall ]
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
      /Filter exch def
      dup /DecodeParms .knownget not {null} if dup null ne {
        % Ghostscript 8.61 (or earlier) raises
        % ``/typecheck in --.reusablestreamdecode--''
        % if /Filter is not an array.
        % For testing: pdf.a9p4/lme_v6.a9p4.pdf
        Filter type /arraytype ne { /Filter [ Filter ] def } if

        % Ghostscript 8.61 (or earlier) raises
        % ``/typecheck in --.reusablestreamdecode--''
        % if /DecodeParms is not an array.
        dup type /arraytype ne { [ exch ] } if

        % Ghostscript 8.61 (or earlier) raises ``/undefined in --filter--''
        % if there is a null in the DecodeParms.
        { dup null eq {pop << >>} if } Map

        dup /DecodeParms exch def
      } if pop
    } {
      pop
    } ifelse
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

% Find an item in an array (using `eq' -- so the executable bit is discarded,
% i.e. /foo and foo are equal). The index -1 is returned if item not found.
/FindItem { % <array> <item> FindItem <index>
  exch dup 0 exch
  { 3 index eq { exit } if 1 add } forall
  exch length 1 index eq { pop -1 } if exch pop
} bind def

/_S1 1 string def

% Like `glyphshow' but uses `show' if the glyph name is in /Encoding.
% This is useful because gs -sDEVICE=pdfwrite autodetects the /Encoding of
% the emitted CFF fonts if /glyphshow is used, possibly emitting two CFF
% fonts
% if there is a character position conflict (e.g. /G and /Phi). No such
% splitting happens with if `show' is used instead of `glyphshow'.
% Stack use: <glyph> <_EncodingDict> GlyphShowWithEncodingDict -
/GlyphShowWithEncodingDict {
  1 index .knownget {
    _S1 exch 0 exch put _S1 show
    pop  % pop the glyph name
  } {
    (warning: using glyphshow for unencoded glyph: /) print dup =
    glyphshow
  } ifelse
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
  % stack: <font-name>
  findfont dup length dict copy
  % Let the font name be /Obj68 etc.
  dup /FullName _ObjNumber 10 string cvs
      % pad to 10 digits for object unification in FixFontNameInType1C.
      dup (0000000000) exch length neg 10 add 0 exch
      getinterval exch concatstrings
      (Obj) exch concatstrings put
  dup dup /FullName get cvn /FontName exch put

  % We want to make sure that:
  %
  % S1. All glyphs in /CharStrings are part of the /Encoding array. This is
  %     needed for Ghostscript 8.54, which would sometimes generate two (or
  %     more?) PDF font objects if not all glyphs are encoded.
  %
  % S2. All non-/.notdef elements of the /Encoding array remain unchanged.
  %     This is needed because Adobe Actobat uses the /Encoding in the CFF
  %     if /BaseEncoding was not specified in the /Type/Encoding for
  %     /Type/Font. This is according to pdf_reference_1.7.pdf. (xpdf and
  %     evince use /BaseEncoding/StandardEncoding.)
  %
  % To do this, we first check that all glyphs in /CharStrings are part of
  % /Encoding. If not, we extend /Encoding to 256 elements (by adding
  % /.notdef{}s), and we start replacing /.notdef{}s at the end of /Encoding
  % by the missing keys from /CharStrings.

  % stack: <fake-font>
  dup /Encoding .knownget not {[]} if

  % Convert all null entries to /.notdef
  % For testing: lshort-kr.pdf
  [ exch { dup null eq { pop /.notdef } if } forall ]
  dup 2 index exch /Encoding exch put

  % stack: <fake-font> <encoding-array>
  << exch -1 exch { exch 1 add dup } forall pop >>
  dup /.notdef undef
  % _EncodingDict maps glyph names in th /Encoding to their last encoded
  % value. Example: << /space 32 /A 65 >>
  /_EncodingDict exch def
  % stack: <fake-font>
  [ 1 index /CharStrings get {
    pop dup _EncodingDict exch known {
      pop
    } {
      dup /.notdef eq { pop } if
    } ifelse
  } forall ]
  % stack: <fake-font> <unencoded-list>
  dup length 0 ne {
    NameSort
    1 index /Encoding .knownget not {[]} if
    % stack: <fake-font> <sorted-unencoded-list> <encoding>
    dup length 256 lt {
      [exch aload length 1 255 {pop/.notdef} for]
    } {
      dup length array copy
    } ifelse
    exch
    /_TargetI 2 index length 1 sub def  % length(Encoding) - 1 (usually 255)
    % stack: <fake-font> <encoding-padded-to-256> <sorted-unencoded-list>
    {
      % stack: <fake-font> <encoding> <unencoded-glyphname>
      { _TargetI 0 lt { exit } if
        1 index _TargetI get /.notdef eq { exit } if
        /_TargetI _TargetI 1 sub def
      } loop
      _TargetI 0 lt {
        % Failed to add all missing glyphs to /Encoding. Give up silently.
        pop exit  % from forall
      } if
      1 index exch _TargetI exch put
      /_TargetI _TargetI 1 sub def
    } forall
    1 index exch /Encoding exch put
    currentdict /_TargetI undef
  } {
    pop
  } ifelse

  % Regenerate _EncodingDict, now with /.notdef
  dup /Encoding .knownget not {[]} if
    << exch -1 exch { exch 1 add dup } forall pop >>
    /_EncodingDict exch def

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
  pop % <fake-font-name-string>
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
  % * Using `show' instead of `glyphshow' to prevent Ghostscript from
  %   splitting the output CFF font to two (or more) on auto-guessed
  %   Encoding position conflict (such as /G and /Phi).
  dup /CharStrings get [exch {pop} forall] NameSort {
    newpath 200 200 moveto
    _EncodingDict GlyphShowWithEncodingDict
  } forall
  currentdict /_EncodingDict undef
  pop % <fake-font>
  restore
} bind def
% </ProcSet>

(Type1CConverter: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
'''

  def GetFonts(self, font_type=None,
               do_obj_num_from_font_name=False, where='loaded'):
    """Return dictionary containing Type1 /FontFile* objs.

    Args:
      font_type: 'Type1' or 'Type1C' or None
      obj_num_from_font_name: Get the obj_num (key in the returned dict) from
        the /FontName, e.g. /FontName/Obj42 --> 42.
    Returns:
      A dictionary mapping the obj number of the /Type/FontDescriptor obj to
      the PdfObj of the /FontFile* obj (with /Subtype/Type1C etc.) whose
      stream contains the font program. Please note that this dictionary is
      not a subdictionary of self.objs, because of the different key--value
      mapping.
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
              print >>sys.stderr, (
                  'error: duplicate font %s obj old=%d new=%d' %
                  (font_name, name_obj_num, font_obj_num))  # TODO(pts): old=37 instead of 11
              duplicate_count += 1
            objs[name_obj_num] = font_obj
          else:
            objs[obj_num] = font_obj
          font_count += 1
    if font_type is None:
      print >>sys.stderr, 'info: found %s fonts %s' % (font_count, where)
    else:
      print >>sys.stderr, 'info: found %s %s fonts %s' % (
          font_count, font_type, where)
    assert not duplicate_count, (
        'found %d duplicate font objs %s' % (duplicate_count, where))
    return objs

  @classmethod
  def GenerateType1CFontsFromType1(cls, objs, ref_objs, ps_tmp_file_name,
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
      obj = objs[obj_num]
      new_obj = None
      type1_size += obj.size
      # TODO(pts): Add whitespace instead.

      # We're a bit to cautious here. Ghostscript 8.61 and 8.71 doen't need
      # /Length1, /Length2 or /Length3 for parsing Type1 fonts, but they are
      # required by the PDF spec.
      for key in ('Length1', 'Length2', 'Length3', 'Subtype'):
        data, has_changed = obj.ResolveReferences(obj.Get(key), ref_objs)
        if data is not None and has_changed:
          if not new_obj:
            new_obj = obj = PdfObj(obj)
          obj.Set(key, data)

      # We don't need it, and if we kept it, it may do harm if it
      # contains indirect references.
      if obj.Get('Metadata') is not None:
        if not new_obj:
          new_obj = obj = PdfObj(obj)
        obj.Set('Metadata', None)

      obj.AppendTo(output, obj_num)
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
        '%s -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dPDFSETTINGS=/printer '
        '-dColorConversionStrategy=/LeaveColorUnchanged '  # suppress warning
        '-sOutputFile=%s -f %s'
        % (GetGsCommand(), ShellQuoteFileName(pdf_tmp_file_name),
           ShellQuoteFileName(ps_tmp_file_name)))
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
    pdf = PdfData().Load(pdf_tmp_file_name)
    # TODO(pts): Better error reporting if the font name is wrong.
    type1c_objs = pdf.GetFonts(
        do_obj_num_from_font_name=True, where='in GS output')
    # Remove only if pdf.GetFonts has not found any duplicate fonts.
    os.remove(ps_tmp_file_name)
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

% /LoadCff {
%   /FontSetInit /ProcSet findresource begin //true //false ReadData } bind def
% but some autodetection of `//false'' above based on the Ghostscript version:
% Since gs 8.64:
%   pdfdict /readType1C get -->
%   {1 --index-- --exch-- PDFfile --fileposition-- 3 1 --roll-- --dup-- true resolvestream --dup-- readfontfilter 3 --index-- /FontDescriptor oget /FontName oget 1 --index-- /FontSetInit /ProcSet --findresource-- --begin-- true false ReadData {--exch-- --pop-- --exit--} --forall-- 7 1 --roll-- --closefile-- --closefile-- --pop-- PDFfile 3 -1 --roll-- --setfileposition-- --pop-- --pop--}
% Till gs 8.61:
%   GS_PDF_ProcSet /FRD get -->
%   {/FontSetInit /ProcSet findresource begin //true ReadData}
GS_PDF_ProcSet /FRD .knownget not { pdfdict /readType1C get } if
dup /FontSetInit FindItem
  dup 0 lt { /invalidfileaccess /MissingFontSetInit signalerror } if
1 index /ReadData FindItem
  dup 0 lt { /invalidfileaccess /MissingReadData signalerror } if
1 index sub 1 add getinterval
cvx bind /LoadCff exch def
% Now we have one of these:
% /LoadCff { /FontSetInit /ProcSet findresource begin //true         ReadData pop } bind def  % gs 8.62 or earlier
% /LoadCff { /FontSetInit /ProcSet findresource begin //true //false ReadData pop } bind def  % gs 8.63 or later

/stream {  % <streamdict> stream -
  ReadStreamFile DecompressStreamFile
  % <streamdict> <decompressed-file>
  systemdict /FontDirectory get {pop undefinefont} forall
  dup /MY exch LoadCff
  % The last command in LoadCff is ReadData, which pushes the <fontset> dict
  % to the stack for gs 8.63 or later, and doesn't push anything in gs 8.62
  % or earlier. We just check the type and pop the value if it is a dict.
  % There is a /filetype above.
  dup type /dicttype eq { pop } if
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

(Type1CParser: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
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

  % Regenerate _EncodingDict, now with /.notdef
  dup /Encoding .knownget not {[]} if
    << exch -1 exch { dup null eq { pop /.notdef } if
                      exch 1 add dup } forall pop >>
    /_EncodingDict exch def

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
  % * Using `show' instead of `glyphshow' to prevent Ghostscript from
  %   splitting the output CFF font to two (or more) on auto-guessed
  %   Encoding position conflict (such as /G and /Phi).
  dup /CharStrings get [exch {pop} forall] NameSort {
    newpath 200 200 moveto
    _EncodingDict GlyphShowWithEncodingDict
  } forall
  currentdict /_EncodingDict undef
  %dup /CharStrings get {pop dup === glyphshow} forall
  %dup /CharStrings get [ exch {pop} forall ] 0 get glyphshow
  pop % <font>
  %showpage % not needed
  restore
} bind def

(Type1CGenerator: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
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
        '%s -q -dNOPAUSE -dBATCH -sDEVICE=nullpage '
        '-sDataFile=%s -f %s'
        % (GetGsCommand(), ShellQuoteFileName(data_tmp_file_name),
           ShellQuoteFileName(ps_tmp_file_name)))
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
    f = open(data_tmp_file_name, 'rb')
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
        self.GetFonts('Type1'), self.objs,
        'pso.conv.tmp.ps', 'pso.conv.tmp.pdf')
    for obj_num in type1c_objs:
      obj = self.objs[obj_num]
      assert str(obj.Get('FontName')).startswith('/')
      type1c_obj = type1c_objs[obj_num]
      # !! fix in genuine Type1C objects as well
      type1c_obj.FixFontNameInType1C(objs=self.objs)
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
      target_fd: A PdfObj of /Type/FontDescriptor, will be modified in place.
      source_fd: A PdfObj of /Type/FontDescriptor.
    Raises:
      FontsNotMergeable: If cannot be merged. In that case, target_fd is not
        modified.
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
  def GetStrippedPrivate(cls, private_dict):
    if private_dict is None:
      return None
    private_dict = dict(private_dict)
    # TODO(pts): Unify these meaningfully.
    # Example:
    #  target={'StemSnapH': [33, 36, 39, 40, 41, 43, 47, 48, 55, 62, 96, 156],
    #          'StdVW': [114],
    #          'StdHW': [47],
    #          'StemSnapV': [47, 53, 95, 108, 114, 117, 125, 128, 136, 142, 153, 156]}
    #  source={'StemSnapH': [33, 36, 39, 40, 43, 47, 48, 53, 55, 96, 117, 156],
    #          'StdVW': [47],
    #          'StdHW': [47],
    #          'StemSnapV': [47, 53, 95, 108, 114, 117, 125, 128, 136, 142, 153, 156]}
    for key in ('StemSnapH', 'StdVW', 'StdHW', 'StemSnapV'):
      if key in private_dict:
        del private_dict[key]
    return private_dict

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
      FontsNotMergeable: If cannot be merged. In that case, target_fd is not
        modified.
    """
    # A /Subrs list prevents easy merging, because then we would have to
    # renumber to calling instructions in the /CharStrings values.
    # TODO(pts): Implement this refactoring.
    #
    # Our callers should make sure that we are not called with fonts with
    # /Subrs.
    assert 'Subrs' not in target_font
    assert 'Subrs' not in target_font.get('Private', ())
    assert 'Subrs' not in source_font
    assert 'Subrs' not in source_font.get('Private', ())
    # Our caller should take care of removing FontBBox.
    assert 'FontBBox' not in source_font
    assert 'FontBBox' not in target_font
    assert source_font['FontType'] == 2
    assert target_font['FontType'] == 2
    # !! proper check for FontMatrix floats.
    # We ignore FontInfo and UniqueID.
    for key in ('FontMatrix', 'PaintType'):
      target_value = target_font[key]
      source_value = source_font[key]
      if target_value != source_value:
        raise FontsNotMergeable('mismatch in key %s: target=%r source=%r' %
            (key, target_value, source_value))
    # This works even if target_font or source_font doesn't contain 'Private'.
    target_value = cls.GetStrippedPrivate(target_font.get('Private'))
    source_value = cls.GetStrippedPrivate(source_font.get('Private'))
    if target_value != source_value:
      raise FontsNotMergeable('mismatch in Private: target=%r source=%r' %
          (target_value, source_value))
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
        stream = type1c_obj.GetUncompressedStream(self.objs)
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
        objs=type1c_objs, ps_tmp_file_name='pso.conv.parse.tmp.ps',
        data_tmp_file_name='pso.conv.parsedata.tmp.ps')
    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))

    # Dictionary mapping a font group name to a list of obj_nums
    # (in parsed_fonts).
    font_groups = {}
    # Dictionary mapping a font group name to a list of font names in it.
    font_group_names = {}
    if do_regenerate_all_fonts:
      unified_obj_nums = set(type1c_objs)
    else:
      unified_obj_nums = set()

    for obj_num in sorted(parsed_fonts):  # !! sort by font name to get exacts
      obj = self.objs[obj_num]  # /Type/FontDescriptor
      assert obj.stream is None
      parsed_font = parsed_fonts[obj_num]
      parsed_font['FontName'] = obj.Get('FontName')
      if (parsed_font.get('FontType') != 2 or 
          not isinstance(parsed_font.get('CharStrings'), dict) or
          'FontMatrix' not in parsed_font or
          'PaintType' not in parsed_font):
        print >>sys.stderr, (
            'warning: strange Type1 font obj %d, not attempting to merge; '
            'CharStrings=%s FontType=%r FontMatrix=%r PaintType=%r' %
            (obj_num, type(parsed_font.get('CharStrings')),
             parsed_font.get('FontType'),
             parsed_font.get('FontMatrix'),
             parsed_font.get('PaintType')))
        continue

      if ('Subrs' in parsed_font or
          'Subrs' in parsed_font.get('Private', ())):
        # for testing: pdfsizeopt_charts.pdf has this for /Subrs (list of hex strings:
        # ['<abc42>', ...]).
        # See also self.MergeTwoType1CFonts why we can't merge fonts with /Subrs.
        print >>sys.stderr, (
            'info: not merging Type1C font obj %d because it has /Subrs' % obj_num)
        continue

      # Extra, not checked: 'UniqueID'
      if 'FontBBox' in parsed_font:
        # This is part of the /FontDescriptor, we don't need it in the Type1C
        # font.
        del parsed_font['FontBBox']
      font_name = parsed_font['FontName']
      # TODO(pts): Smarter initial grouping, even if name doesn't match.
      match = PdfObj.SUBSET_FONT_NAME_PREFIX_RE.match(font_name)
      if match:
        font_group = font_name[match.end():]
      else:
        font_group = font_name[1:]
      if font_group in font_groups:
        font_groups[font_group].append(obj_num)
      else:
        font_groups[font_group] = [obj_num]      

    for font_group in sorted(font_groups):
      group_obj_nums = font_groups[font_group]
      if len(group_obj_nums) < 2:
        del font_groups[font_group]
        continue
      merged_font = parsed_fonts[group_obj_nums[0]]
      # /Type/FontDescriptor
      merged_fontdesc_obj = PdfObj(self.objs[group_obj_nums[0]])
      assert merged_fontdesc_obj.stream is None
      orig_char_count = len(merged_font['CharStrings'])
      #print 'GROUP', font_group, len(group_obj_nums)
      #print 'BASE   ', merged_font['FontName']
      i = 1
      while i < len(group_obj_nums):
        obj = self.objs[group_obj_nums[i]]  # /Type/FontDescriptor
        parsed_font = parsed_fonts[group_obj_nums[i]]
        new_fontdesc_obj = PdfObj(merged_fontdesc_obj)
        try:
          self.MergeTwoType1CFontDescriptors(new_fontdesc_obj, obj)
        except FontsNotMergeable, exc:
          print >>sys.stderr, (
              'info: could not merge descs from %s to %s: %s' %
              (exc, parsed_font['FontName'], merged_font['FontName']))
          # !! don't just throw away this font, merge with others
          group_obj_nums.pop(i)
          continue
        try:
          self.MergeTwoType1CFonts(merged_font, parsed_font)
        except FontsNotMergeable, exc:
          print >>sys.stderr, (
              'info: could not merge fonts from %s to %s: %s' %
              (exc, parsed_font['FontName'], merged_font['FontName']))
          # !! don't just throw away this font, merge with others
          group_obj_nums.pop(i)
          continue
        merged_fontdesc_obj.head = new_fontdesc_obj.head
        orig_char_count += len(parsed_font['CharStrings'])
        i += 1

      if len(group_obj_nums) < 2:  # Just to be sure.
        del font_groups[font_group]
        continue

      # pdf_reference_1-7.pdf says /Type/FontDescriptor is required (even if
      # some software omits it).
      merged_fontdesc_obj.Set('Type' , '/FontDescriptor')
      if do_keep_font_optionals:
        # !! remove more optionals
        # New Ghostscript doesn't generate /CharSet. We don't generate it
        # either, unless the user asks for it.
        merged_fontdesc_obj.Set(
            'CharSet', PdfObj.EscapeString(''.join(
                ['/' + name for name in sorted(merged_font['CharStrings'])])))

      self.objs[group_obj_nums[0]].head = merged_fontdesc_obj.head
      font_group_names[font_group] = [merged_font['FontName']]
      for i in xrange(1, len(group_obj_nums)):
        group_obj_num = group_obj_nums[i]
        obj = self.objs[group_obj_num]  # /Type/FontDescriptor
        # !! merge /Type/Font objects (including /FirstChar, /LastChar and
        # /Widths)
        obj.head = merged_fontdesc_obj.head
        assert obj.stream is None
        font_group_names[font_group].append(
            parsed_fonts[group_obj_nums[i]]['FontName'])
        del type1c_objs[group_obj_num]
        del parsed_fonts[group_obj_num]
        if group_obj_num in unified_obj_nums:
          unified_obj_nums.remove(group_obj_num)
        # Don't del `self.objs[group_obj_nums[i]]' yet, because that object may
        # be referenced from another /Font. self.OptimizeObjs() will clean up
        # unreachable objs safely.
      new_char_count = len(merged_font['CharStrings'])
      unified_obj_nums.add(group_obj_nums[0])
      print >>sys.stderr, (
          'info: merged fonts %r, reduced char count from %d  to %d (%s)' %
          (font_group_names[font_group], orig_char_count, new_char_count,
           FormatPercent(new_char_count, orig_char_count)))

    if not font_groups:
      # Could not unify any fonts.
      for obj_num in sorted(type1c_objs):
        type1c_objs[obj_num].FixFontNameInType1C(objs=self.objs)
      return self

    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    if not unified_obj_nums:
      print >>sys.stderr, 'info: no fonts to regenerate or unify'
      # TODO(pts): Don't recompress if already recompressed (e.g. when
      # converted from Type1).
      for obj_num in sorted(type1c_objs):
        type1c_objs[obj_num].FixFontNameInType1C(objs=self.objs)
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
      AppendSerialized(parsed_fonts[obj_num], output)
      output.append('endobj\n')
    output.append('(Type1CGenerator: all OK\\n) print flush\n%%EOF\n')
    ps_tmp_file_name = 'pso.conv.gen.tmp.ps'
    pdf_tmp_file_name = 'pso.conv.gen.tmp.pdf'
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
        '%s -q -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -dPDFSETTINGS=/printer '
        '-dColorConversionStrategy=/LeaveColorUnchanged '  # suppress warning
        '-sOutputFile=%s -f %s'
        % (GetGsCommand(), ShellQuoteFileName(pdf_tmp_file_name),
           ShellQuoteFileName(ps_tmp_file_name)))
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
      loaded_obj.FixFontNameInType1C(objs=self.objs)
      type1c_objs[obj_num].head = loaded_obj.head
      type1c_objs[obj_num].stream = loaded_obj.stream
    for obj_num in sorted(set(type1c_objs).difference(loaded_objs)):
      type1c_objs[obj_num].FixFontNameInType1C(objs=self.objs)

    new_type1c_size = 0
    for obj_num in type1c_objs:
      new_type1c_size += type1c_objs[obj_num].size + self.objs[obj_num].size

    assert sorted(parsed_fonts) == sorted(type1c_objs), (
        (sorted(parsed_fonts), sorted(type1c_objs)))
    if do_double_check_missing_glyphs:
      parsed2_fonts = self.ParseType1CFonts(
          objs=loaded_objs, ps_tmp_file_name='pso.conv.parse2.tmp.ps',
          data_tmp_file_name='pso.conv.parse2data.tmp.ps')
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
                   do_just_read=False, return_none_if_status=None):
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
    if (return_none_if_status is not None and
        status == return_none_if_status):
      return None
    if status:
      print >>sys.stderr, 'info: %s failed, status=0x%x' % (cmd_name, status)
      assert 0, '%s failed (status)' % cmd_name
    assert os.path.exists(targetfn), (
        '%s has not created the output image %r' % (cmd_name, targetfn))
    if do_just_read:
      f = open(targetfn, 'rb')
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
      detect_ret = obj.DetectInlineImage(objs=self.objs)
      if not detect_ret:
        continue
      width, height, image_obj = detect_ret
      # For testing: test_pts2e.pdf
      uninline_count += 1
      colorspace = image_obj.Get('ColorSpace')
      assert colorspace is not None
      assert (image_obj.Get('BitsPerComponent') is not None or
              image_obj.Get('ImageMask', False) is True)
      #if image_obj.Get('Filter') == '/FlateDecode':
      # If we do a zlib.decompress(stream) now, it will succeed even if stream
      # has trailing garbage. But zlib.decompress(stream[:-1]) would fail. In
      # Python, there is no way to get te real end on the compressed zlib
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
      image_obj.head = PdfObj.CompressValue(image_obj.head)
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
        '%s -q -dNOPAUSE -dBATCH -sDEVICE=%s '
        '-sOutputFile=%s -f %s'
        % (GetGsCommand(), ShellQuote(gs_device),
           ShellQuoteFileName(png_tmp_file_pattern),
           ShellQuoteFileName(ps_tmp_file_name)))
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

  SAM2P_GRAYSCALE_MODE = 'Gray1:Gray2:Gray4:Gray8:stop'

  def OptimizeImages(self, use_pngout=True, use_jbig2=True):
    """Optimize image XObjects in the PDF."""
    # TODO(pts): Keep output of pngout between runs, to reduce time.
    # Dictionary mapping Ghostscript -sDEVICE= names to dictionaries mapping
    # PDF object numbers to PdfObj instances.
    # TODO(pts): Remove key PTEX.* from all dicts (trailer and form xobjects)
    device_image_objs = {'png16m': {}, 'pnggray': {}, 'pngmono': {}}
    image_count = 0
    image_total_size = 0
    # Maps object numbers to ('method', ImageData) tuples.
    images = {}
    # Maps /XImage (head, stream) pairs to object numbers.
    by_orig_data = {}
    # Maps obj_nums (to be modified) to obj_nums (to be modified to).
    modify_obj_nums = {}
    force_grayscale_obj_nums = set()
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]

      # TODO(pts): Is re.search here fast enough?; PDF comments?
      if (not re.search(r'/Subtype[\0\t\n\r\f ]*/Image\b', obj.head) or
          not obj.head.startswith('<<') or
          not obj.stream is not None or
          obj.Get('Subtype') != '/Image'): continue
      filter, filter_has_changed = PdfObj.ResolveReferences(
          obj.Get('Filter'), objs=self.objs)
      filter2 = (filter or '').replace(']', ' ]') + ' '

      # Don't touch lossy-compressed images.
      # TODO(pts): Read lossy-compressed images, maybe a small, uncompressed
      # representation would be smaller.
      if ('/JPXDecode ' in filter2 or '/DCTDecode ' in filter2):
        continue

      # TODO(pts): Support color key mask for /DeviceRGB and /DeviceGray:
      # convert the /Mask to RGB8, remove it, and add it back (properly
      # converted back) to the final PDF; pay attention to /Decode
      # differences as well.
      # TODO(pts): Support an image mask (with /Mask x 0 R pointing to
      # an obj << /Subtype/Image /ImageMask true >>).
      mask = obj.Get('Mask')
      do_remove_mask = False
      try:
        mask, _ = PdfObj.ResolveReferences(mask, objs=self.objs)
      except UnexpectedStreamError:
        assert isinstance(mask, str)
        mask = PdfObj.ParseSimpleValue(mask)
        do_remove_mask = True
      if (isinstance(mask, str) and mask and
          not do_remove_mask and
          not re.match(r'\[\s*\]\Z', mask)):
        continue

      smask = obj.Get('SMask')
      if isinstance(smask, str):
        try:
          smask = PdfObj.ParseSimpleValue(smask)
        except PdfTokenParseError:
          pass
      if isinstance(smask, str):
        match = re.match(r'(\d+) (\d+) R\Z', smask)
        if match:
          # The target image of an /SMask must be /ColorSpace /DeviceGray.
          force_grayscale_obj_nums.add(int(match.group(1)))

      bpc, bpc_has_changed = PdfObj.ResolveReferences(
          obj.Get('BitsPerComponent'), objs=self.objs)
      if obj.Get('ImageMask'):
        if bpc != 1:
          bpc_has_changed = True
          bpc = 1
      if bpc not in (1, 2, 4, 8):
        continue

      decodeparms = obj.Get('DecodeParms') or ''
      if isinstance(decodeparms, str) and '/JBIG2Globals' in decodeparms:
        # We don't support optimizing JBIG2 images with global references.
        # For testing: /mnt/mandel/warez/tmp/linux.pdf
        continue
      del decodeparms

      data_pair = (obj.head, obj.stream)
      target_obj_num = by_orig_data.get(data_pair)
      if target_obj_num is not None: 
        # For testing: pts2.zip.4times.pdf
        # This is just a speed optimization so we don't have to parse the
        # image again.
        # TODO(pts): Set the result of ResolveReferences back before doing
        # the identity check.
        print >>sys.stderr, (
            'info: using identical image obj %s for obj %s' %
            (target_obj_num, obj_num))
        modify_obj_nums[obj_num] = target_obj_num
        continue

      by_orig_data[data_pair] = obj_num
      obj0 = obj

      # TODO(pts): Inline this to reduce PDF size.
      # pdftex emits: /ColorSpace [/Indexed /DeviceRGB <n> <obj_num> 0 R]
      colorspace, colorspace_has_changed = PdfObj.ResolveReferences(
          obj.Get('ColorSpace'), objs=self.objs, do_strings=True)
      if obj.Get('ImageMask'):
        if colorspace != '/DeviceGray':  # can be None
          colorspace = '/DeviceGray'
          colorspace_has_changed = True
      assert not re.match(PdfObj.PDF_REF_RE, colorspace)
      colorspace_short = re.sub(r'\A\[\s*/Indexed\s*/([^\s/<(]+)(?s).*',
                         '/Indexed/\\1', colorspace)
      if re.search(r'[^/\w]', colorspace_short):
        colorspace_short = '?'

      if filter_has_changed:
        if obj is obj0:
          obj = PdfObj(obj)
        obj.Set('Filter', filter)
      if bpc_has_changed:
        if obj is obj0:
          obj = PdfObj(obj)
        obj.Set('BitsPerComponent', bpc)
      if colorspace_has_changed:
        if obj is obj0:
          obj = PdfObj(obj)
        obj.Set('ColorSpace', colorspace)
      for name in ('Width', 'Height', 'Decode', 'DecodeParms'): 
        value = obj.Get(name)
        value, value_has_changed = PdfObj.ResolveReferences(
          value, objs=self.objs)
        if value_has_changed:
          if obj is obj0:
            obj = PdfObj(obj)
          obj.Set(name, value)

      if obj.Get('ImageMask'):
        if obj is obj0:
          obj = PdfObj(obj)
        colorspace = '/DeviceGray'
        obj.Set('ImageMask', None)
        obj.Set('Decode', None)
        obj.Set('ColorSpace', colorspace)
        obj.Set('BitsPerComponent', 1)

      # Ignore images with exotic color spaces (e.g. DeviceCMYK, CalGray,
      # DeviceN).
      # TODO(pts): Support more color spaces. DeviceCMYK would be tricky,
      # because neither PNG nor sam2p supports it. We can convert it to
      # RGB, though.
      if not re.match(r'(?:/Device(?:RGB|Gray)\Z|\[\s*/Indexed\s*'
                      r'/Device(?:RGB|Gray)\s)', colorspace):
        continue

      if obj.Get('Mask') and do_remove_mask:
        if obj is obj0:
          obj = PdfObj(obj)
        obj.Set('Mask', None)

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

      # TODO(pts): Is this necessary? If so, add it back.
      #obj = PdfObj(obj)

      # Try to convert to PNG in-process. If we can't, schedule rendering with
      # Ghostscript. 
      image1 = image2 = None
      try:
        # Both LoadPdfImageObj and CompressToZipPng raise FormatUnsupported.
        image1 = ImageData().LoadPdfImageObj(obj=obj, do_zip=False)
        if not image1.CanBePngImage(do_ignore_compression=True):
          raise FormatUnsupported('cannot save to PNG')
        image2 = ImageData(image1).CompressToZipPng()
        # image2 won't be None here.
      except FormatUnsupported:
        image1 = image2 = None

      if image1 is None:  # Impossible to save obj as PNG.
        # Keep only whitelisted names, others such as /SMask may contain
        # references.
        # For testing: bt9.pdf
        obj2 = PdfObj(None)
        obj2.head = '<<>>'
        obj2.stream = obj.stream
        if len(obj2.stream) > int(obj.Get('Length')):
           obj2.stream = obj2.stream[:int(obj.Get('Length'))]
        obj2.Set('Length', len(obj2.stream))
        obj2.Set('Subtype', '/Image')
        for name in ('Width', 'Height', 'ColorSpace', 'Decode', 'Filter',
                     'DecodeParms', 'BitsPerComponent'):
          obj2.Set(name, obj.Get(name))
        device_image_objs[gs_device][obj_num] = obj2
      else:
        images[obj_num].append(('parse', (image2.SavePng(
            file_name='pso.conv-%d.parse.png' % obj_num))))
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
      ps_tmp_file_name = 'pso.conv.%s.tmp.ps' % gs_device
      objs = device_image_objs[gs_device]
      if objs:
        # Dictionary mapping object numbers to /Image PdfObj{}s.
        rendered_images = self.RenderImages(
            objs=objs, ps_tmp_file_name=ps_tmp_file_name, gs_device=gs_device,
            png_tmp_file_pattern='pso.conv-%%04d.%s.tmp.png' % gs_device)
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
      for method, image in obj_images:
        assert obj.Get('Width') == image.width
        assert obj.Get('Height') == image.height
      rendered_tuple = obj_images[-1][1].ToDataTuple()
      target_image = by_rendered_tuple.get(rendered_tuple)
      if target_image is not None:  # We have already rendered this image.
        # For testing: pts2.zip.4timesb.pdf
        # This is just a speed optimization so we don't have to run
        # sam2p again.
        print >>sys.stderr, (
            'info: using already rendered image for obj %s' % obj_num)
        assert obj.Get('Width') == target_image.width
        assert obj.Get('Height') == target_image.height
        obj_images.append(('#prev-rendered-best', target_image))
        image_tuple = target_image.ToDataTuple()
      else:
        rendered_image_file_name = obj_images[-1][1].file_name
        # TODO(pts): use KZIP or something to further optimize the ZIP stream
        # !! shortcut for sam2p (don't need pngtopnm)
        #    (add basic support for reading PNG to sam2p? -- just what GS produces)
        #    (or just add .gz support?)
        if obj_num in force_grayscale_obj_nums:
          sam2p_mode = self.SAM2P_GRAYSCALE_MODE
        else:
          sam2p_mode = 'Gray1:Indexed1:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:stop'
        obj_images.append(self.ConvertImage(
            sourcefn=rendered_image_file_name,
            targetfn='pso.conv-%d.sam2p-np.pdf' % obj_num,
            # We specify -s here to explicitly exclude SF_Opaque for single-color
            # images.
            # !! do we need /ImageMask parsing if we exclude SF_Mask here as well?
            # Original sam2p order: Opaque:Transparent:Gray1:Indexed1:Mask:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:Transparent2:Transparent4:Transparent8
            # !! reintroduce Opaque by hand (combine /FlateEncode and /RLEEncode; or /FlateEncode twice (!) to reduce zeroes in empty_page.pdf from !)
            cmd_pattern='sam2p -pdf:2 -c zip:1:9 -s ' + ShellQuote(sam2p_mode) + ' -- %(sourcefnq)s %(targetfnq)s',
            cmd_name='sam2p_np'))

        image_tuple = obj_images[-1][1].ToDataTuple()
        target_image = by_image_tuple.get(image_tuple)
        assert image_tuple[00] == obj.Get('Width')
        assert image_tuple[01] == obj.Get('Height')
        target_image = by_image_tuple.get(image_tuple)
        if target_image is not None:  # We have already optimized this image.
          # For testing: pts2.ziplzw.pdf
          # The latest sam2p is deterministic, so the bytes of the file
          # produced by sam2p depends only on the RGB image data.
          print >>sys.stderr, (
              'info: using already processed image for obj %s' % obj_num)
          obj_images.append(('#prev-sam2p-best', target_image))
        else:
          if obj_num in force_grayscale_obj_nums:
            sam2p_s_flags = '-s %s ' % ShellQuote(self.SAM2P_GRAYSCALE_MODE)
          else:
            sam2p_s_flags = ''
          obj_images.append(self.ConvertImage(
              sourcefn=rendered_image_file_name,
              targetfn='pso.conv-%d.sam2p-pr.png' % obj_num,
              cmd_pattern='sam2p ' + sam2p_s_flags+ '-c zip:15:9 -- %(sourcefnq)s %(targetfnq)s',
              cmd_name='sam2p_pr'))
          if (use_jbig2 and obj_images[-1][1].bpc == 1 and
              obj_images[-1][1].color_type in ('gray', 'indexed-rgb')):
            # !! autoconvert 1-bit indexed PNG to gray
            obj_images.append(('jbig2', ImageData(obj_images[-1][1])))
            if obj_images[-1][1].color_type != 'gray':
              # This changes obj_images[-1].file_name as well.
              obj_images[-1][1].SavePng(
                  file_name='pso.conv-%d.gray.png' % obj_num, do_force_gray=True)
            obj_images[-1][1].idat = self.ConvertImage(
                sourcefn=obj_images[-1][1].file_name,
                targetfn='pso.conv-%d.jbig2' % obj_num,
                cmd_pattern='jbig2 -p %(sourcefnq)s >%(targetfnq)s',
                cmd_name='jbig2', do_just_read=True)[1]
            obj_images[-1][1].compression = 'jbig2'
            obj_images[-1][1].file_name = 'pso.conv-%d.jbig2' % obj_num
          # !! add /FlateEncode again to all obj_images to find the smallest
          #    (maybe to UpdatePdfObj)
          # !! TODO(pts): Find better pngout binary file name.
          # TODO(pts): Try optipng as well (-o5?)
          if use_pngout:
            if obj_num in force_grayscale_obj_nums:
              pngout_gray_flags = '-c0 '
            else:
              pngout_gray_flags = ''
            image = self.ConvertImage(
                sourcefn=rendered_image_file_name,
                targetfn='pso.conv-%d.pngout.png' % obj_num,
                cmd_pattern='pngout ' + pngout_gray_flags +
                            '%(sourcefnq)s %(targetfnq)s',
                cmd_name='pngout',
                # New pngout if: 'Unable to compress further: copying
                # original file'
                return_none_if_status=0x200)
            if image is not None:
              obj_images.append(image)
              image = None
          # TODO(pts): For very small (10x10) images, try uncompressed too.

      obj_infos = [(obj.size, '#orig', '', obj, None)]
      for cmd_name, image_data in obj_images:
        if obj.Get('ImageMask') and not image_data.CanUpdateImageMask():
          # We can't use this optimized image, so we skip it.
          if cmd_name != 'gs':  # no warning for what was rendered by Ghostscript
            print >>sys.stderr, (
                'warning: skipping bpc=%s color_type=%s file_name=%r '
                'for image XObject %s because of source /ImageMask' %
                (image_data.bpc, image_data.color_type, image_data.file_name,
                 obj_num))
          continue
        if obj_num in force_grayscale_obj_nums and image_data.color_type != 'gray':
          if cmd_name != 'gs':
            print >>sys.stderr, (
                'warning: skipping bpc=%s color_type=%s file_name=%r '
                'for image XObject %s because grayscale is needed' %
                (image_data.bpc, image_data.color_type, image_data.file_name,
                 obj_num))
          continue
        new_obj = PdfObj(obj)
        image_data.UpdatePdfObj(new_obj)
        obj_infos.append([new_obj.size, cmd_name, image_data.file_name,
                          new_obj, image_data])

      assert obj.Get('Width') == image_tuple[0]
      assert obj.Get('Height') == image_tuple[1]
      assert obj.Get('Width') == rendered_tuple[0]
      assert obj.Get('Height') == rendered_tuple[1]
      for obj_info in obj_infos:
        if obj_info[4] is not None:
          assert obj_info[4].width == obj.Get('Width')
          assert obj_info[4].height == obj.Get('Height')

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

      if obj_infos[0][4] is None:
        # TODO(pts): Diagnose this: why can't we generate a smaller image?
        # !! Originals in eurotex2006.final.pdf tend to be smaller here because
        #    they have ColorSpace in a separate XObject.
        print >>sys.stderr, (
            'info: keeping original image XObject %s, '
            'replacements too large: %s' %
            (obj_num, method_sizes))
      else:
        assert obj_infos[0][3] is not obj
        print >>sys.stderr, (
            'info: optimized image XObject %s file_name=%s '
            'size=%s (%s) methods=%s' %
            (obj_num, obj_infos[0][2], obj_infos[0][0],
             FormatPercent(obj_infos[0][0], obj.size), method_sizes)) 
        bytes_saved += self.objs[obj_num].size - obj_infos[0][0]
        if ('/JBIG2Decode' in (obj_infos[0][3].Get('Filter') or '') and
            self.version < '1.4'):
          self.version = '1.4'
        assert obj_infos[0][3].Get('Width') == obj.Get('Width')
        assert obj_infos[0][3].Get('Height') == obj.Get('Height')
        self.objs[obj_num] = obj = obj_infos[0][3]
        # At this point, obj.Get('Mask') contains `x y R' if it contained it
        # before.

      if obj_infos[0][4] is not None:
        by_rendered_tuple[rendered_tuple] = obj_infos[0][4]
        by_image_tuple[image_tuple] = obj_infos[0][4]
        # TODO(pts): !! Cache something if obj_infos[0][4] is None, seperate
        # case for len(obj_info) == 1.
        # TODO(pts): Investigate why the original image can be the smallest.
      del obj_images[:]  # free memory occupied by unchosen images
    print >>sys.stderr, 'info: saved %s bytes (%s) on optimizable images' % (
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
  def FindEqclasses(cls, objs, do_remove_unused=False, do_renumber=False,
                    do_unify_pages=True):
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
    # inrefs_count]). Each list of eqclasses is an eqiuvalence class of
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
      # !! TODO(pts): reorder dicts to canonical order
      # CompressValue changes all generational refs to generation 0.
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
      elif (not do_unify_pages and
            stream is None and head_minus.startswith('<<') and
            objs[obj_num].Get('Type') == '/Page'):
        # Make sure that /Page objects are not unified. xpdf and evince
        # display the error message `Loop in Pages tree' (but still display
        # the PDF) if we unify equivalent pages, but since the PDF spec
        # doesn't say that it's not allowed to unify equivalent pages, we do
        # unify (by avoiding this code block) by default, but the user can
        # say --do-unify-pages=false to disable /Page object unification.
        eqclasses.append([desc])
        eqclass_of[obj_num] = eqclasses[-1]
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
          lambda match: (match.group(1) is not None and PdfObj.EscapeString(
              match.group(1).decode('hex')) or '<<'), head)
      obj = PdfObj(None)
      obj.head = head
      obj.stream = stream
      objs_ret[obj_num_map.get(obj_num, obj_num)] = obj

    return objs_ret

  def OptimizeObjs(self, do_unify_pages):
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

    Args:
      do_unify_pages: Unify equivalent /Type/Page objects to a single object.
    Returns:
      self.
    """
    # TODO(pts): Inline ``obj null endobj'' and ``obj<<>>endobj'' etc.
    self.objs['trailer'] = self.trailer
    new_objs = self.FindEqclasses(
        self.objs, do_remove_unused=True, do_renumber=True,
        do_unify_pages=do_unify_pages)
    self.trailer = new_objs.pop('trailer')
    self.objs.clear()
    self.objs.update(new_objs)
    return self

  def ParseSequentially(self, data, file_name=None, offsets_out=None,
                        obj_num_by_ofs_out=None, setitem_callback=None):
    """Load a PDF by parsing the file data sequentially.

    This method overrides the old contents of self from data.

    This method is a bit smarter (and more relaxed) than Load, because it
    can parse a PDF with a cross reference stream (/Type/XRef; instead of a cross
    reference table). It doesn't understand the cross reference stream,
    however. It also doesn't decode object streams (/Type/ObjStm).

    Args:
      data: String containing PDF file data.
      file_name: File name of the PDF, or None.
      offsets_out: None or list to append object offsets, the xref offset
        (if any) and the trailer offset.
      obj_num_by_ofs_out: None or dict that will be populated with object
        offsets mapped by object numbers.
      setitem_callback: None or function taking obj_num, pdf_obj and enf_ofs
        as arguments. The default implementation extends self.objs.
    Returns:
      self.
    Raises:
      PdfTokenParseError: On error, the state of self is unknown, it may be
        partially filled.
      TypeError:
    """
    if obj_num_by_ofs_out is None:
      obj_num_by_ofs_out = {}
    elif not isinstance(obj_num_by_ofs_out, dict):
      raise TypeError

    def DefaultSetItem(obj_num, pdf_obj, unused_end_ofs):
      if obj_num is not None:
        if obj_num in self.objs:
          raise PdfTokenParseError('duplicate object number %s' % obj_num)
        self.objs[obj_num] = pdf_obj

    if setitem_callback is None:
      setitem_callback = DefaultSetItem

    match = PdfObj.PDF_VERSION_HEADER_RE.match(data)
    if not match:
      raise PdfTokenParseError('unrecognized PDF signature %r' % data[0: 16])
    version = match.group(1)

    # We set startxref ofs if available. It is not an error not to have it
    # (e.g. with a broken PDF with xref + trailer).
    trailer_ofs = None
    i = data.rfind('startxref')
    if i >= 0:
      scanner = PdfObj.PDF_STARTXREF_EOF_RE.scanner(data, i - 1)
      match = scanner.match()
      if match:
        trailer_ofs = int(match.group(1))

    self.has_generational_objs = False
    self.version = version
    self.objs.clear()
    self.trailer = None
    self.file_name = file_name
    self.file_size = len(data)
    i = 0
    end_ofs_out = []
    # None or a dict mapping object numbers to their start offsets in data.
    obj_starts = None
    length_objs = {}

    while True:
      if i >= len(data):
        raise PdfTokenParseError('unexpeted EOF in PDF')
      i0 = i
      if data[i] == '%' or data[i] in PdfObj.PDF_WHITESPACE_CHARS:
        scanner = PdfObj.PDF_COMMENTS_OR_WHITESPACE_RE.scanner(data, i)
        i = scanner.match().end()  # always matches

      scanner = PdfObj.PDF_OBJ_DEF_OR_XREF_RE.scanner(data, i)
      match = scanner.search()
      if not match:
        raise PdfTokenParseError(
            'next obj or xref or startxref not found at ofs=%d' % i)
      i = match.start()
      if i0 != i:
        # Report wasted bytes between objs.
        setitem_callback(None, data[i0 : i], None)

      del end_ofs_out[:]
      prefix = data[i : i + 16]
      if prefix.startswith('startxref'):
        offsets_out.append(i)  # startxref
        scanner = PdfObj.PDF_STARTXREF_EOF_RE.scanner(data, i - 1)
        match = scanner.match()
        if not match:
          raise PdfTokenParseError('startxref syntax error at ofs=%d' % i)
        assert trailer_ofs == int(match.group(1))
        if self.trailer is None:
          raise PdfTokenParseError('trailer/xref obj not found')
        if self.trailer.Get('Type') != '/XRef':
          raise PdfTokenParseError('no cross reference stream or table')
        break
      if prefix.startswith('xref'):
        i0 = i
        scanner = PdfObj.PDF_TRAILER_WORD_RE.scanner(data, i)
        match = scanner.search()
        if not match:
          raise PdfTokenParseError('cannot find trailer after xref')
        if offsets_out is not None:
          offsets_out.append(i)  # xref
          i = match.start(1)
          del end_ofs_out[:]
          self.trailer = PdfObj.ParseTrailer(
              data, start=i, end_ofs_out=end_ofs_out)
          offsets_out.append(i)  # trailer
          offsets_out.append(end_ofs_out[0])  # startxref
        else:
          i = match.start(1)
          del end_ofs_out[:]
          self.trailer = PdfObj.ParseTrailer(
              data, start=i, end_ofs_out=end_ofs_out)
        self.trailer.Set('Prev', None)
        i = end_ofs_out[0]
        scanner = PdfObj.PDF_STARTXREF_EOF_RE.scanner(data, i - 1)
        if scanner.match():
          break
        # We reach this point in case of a linearized PDF. We usually have
        # `startxref <offset> %%EOF' here, and then we get new objs.
        if data[i : i + 9].startswith('startxref'):
          # TODO(pts): Add more, till `%%EOF'.
          i += 9
        setitem_callback(None, data[i0 : i], 'linearized')
        continue
      if prefix.startswith('trailer'):
        raise PdfTokenParseError(
            'unexpected trailer at ofs=%d' % i)
      try:
        pdf_obj = PdfObj(data, start=i, end_ofs_out=end_ofs_out, file_ofs=i,
                         objs=length_objs)
      except PdfIndirectLengthError, exc:
        # For testing: eurotex2006.final.pdf and lme_v6.pdf
        if obj_starts is None:
          obj_starts, self.has_generational_objs = self.ParseUsingXref(
              data,
              do_ignore_generation_numbers=self.do_ignore_generation_numbers)
        # TODO(pts): Cache length_objs.
        j = obj_starts[exc.length_obj_num]
        if exc.length_obj_num not in length_objs:
          length_objs[exc.length_obj_num] = PdfObj(
              data, start=j, file_ofs=j)
        pdf_obj = PdfObj(data, start=i, end_ofs_out=end_ofs_out, file_ofs=i,
                         objs=length_objs)
      if offsets_out is not None:
        offsets_out.append(i)
      scanner = PdfObj.NONNEGATIVE_INT_RE.scanner(data, i)
      match = scanner.match()
      assert match
      obj_num = int(match.group(1))
      # !! set self.has_generational_objs
      obj_num_by_ofs_out[i] = obj_num
      if trailer_ofs == i:
        self.trailer = pdf_obj
      assert end_ofs_out[0] > i
      i = end_ofs_out[0]
      setitem_callback(obj_num, pdf_obj, i)  # self.objs[obj_num] = pdf_obj

    # !! add support for `/Length X 0 R' by parsing the xref table first (for testing: lme_v6.pdf).
    # !! test this
    return self

  @classmethod
  def ComputePdfStatistics(cls, file_name):
    """Compute statistics for the specified PDF file."""
    print >>sys.stderr, 'info: computing statistics for PDF: %s' % file_name
    f = open(file_name, 'rb')
    try:
      data = f.read()
    finally:
      f.close()
    print >>sys.stderr, 'info: PDF size is %s bytes' % len(data)

    offsets_out = []
    offsets_idx = [0]
    obj_num_by_ofs_out = {}
    trailer_obj_num = [None]
    trailer_size = [None]
    # All values are in bytes.
    stats = {
        'image_objs': 0,
        # This includes the PDF header, `startxref' and what follows, plus
        # space wasted in comments between objs. 
        'separator_data': len(data),
        'xref': 0,
        'trailer': 0,
        # TODO(pts): Count hyperlinks seperately, but they may be part of
        # content streams, and we don't have the infrastructure to inspect
        # that.
        'other_objs': 0,
        'wasted_between_objs': 0,
        'header': 0,
        'contents_objs': 0,
        'font_data_objs': 0,
        'linearized_xref': 0,
    }
    obj_size_by_num = {}
    contents_obj_nums = set()
    font_data_obj_nums = set()
    image_obj_nums = set()

    def AddRefToSet(ref_data, set_obj):
      if not isinstance(ref_data, str):
        raise PdfTokenParseError('not a reference (in a string)')
      if ref_data.startswith('['):
        ref_items = PdfObj.ParseArray(ref_data)
      else:
        ref_items = [ref_data]
      for ref_data in ref_items:
        match = PdfObj.PDF_NUMBER_OR_REF_RE.match(ref_data)
        if not match:
          raise PdfTokenParseError(
              'not a reference (or number) for %r' % (ref_data,))
        assert match.group(1) is not None
        if match.group(2) is None:
          raise PdfTokenParseError('invalid ref %r' % (ref_data,))
        if int(match.group(2)) != 0:
          raise PdfTokenParseError(
              'invalid ref generation in %r' % (ref_data,))
        set_obj.add(int(match.group(1)))

    pdf = PdfData()

    def SetItemCallback(obj_num, pdf_obj, end_ofs):
      if obj_num is None:
        assert isinstance(pdf_obj, str)
        if not offsets_out:
          stats['header'] += len(pdf_obj)
        elif end_ofs == 'linearized':
          # For testing: inkscape_manual.pdf
          stats['linearized_xref'] += len(pdf_obj)
        else:
          stats['wasted_between_objs'] += len(pdf_obj)
        stats['separator_data'] -= len(pdf_obj)
        return
      obj_ofs = offsets_out[-1]
      offsets_idx[0] = len(offsets_out)
      obj_size_by_num[obj_num] = obj_size = end_ofs - obj_ofs
      # The object spans from start_ofs to end_ofs.
      stats['separator_data'] -= obj_size
      if pdf.trailer is pdf_obj:
        assert pdf.trailer.stream is not None
        trailer_obj_num[0] = obj_num
        xref_size = len(pdf.trailer.stream) + 20
        stats['xref'] += xref_size
        stats['trailer'] += obj_size - xref_size
        return
      stats['other_objs'] += obj_size
      if pdf_obj.head.startswith('<<'):
        if pdf_obj.Get('Type') == '/ObjStm':
          # We have to parse this to find /Contents and /FontFile*
          # references.

          # Object stream parsing makes statting pdf_reference_1-7.pdf very
          # slow.
          # TODO(pts): Figure out why other_objs consume more than 50% in
          # pdf_reference_1-7.pdf.

          obj_data = pdf_obj.GetUncompressedStream()
          for head in PdfObj.ParseArray('[%s]' % obj_data):
            if isinstance(head, str) and head.startswith('<<'):
              dict_obj = PdfObj.ParseDict(head)
              if (dict_obj.get('Type') == '/Page' and
                  'Contents' in dict_obj):
                AddRefToSet(dict_obj['Contents'], contents_obj_nums)
              if dict_obj.get('Type') in ('/FontDescriptor', None):
                for key in PdfObj.PDF_FONT_FILE_KEYS:
                  ref_data = dict_obj.get(key)
                  if isinstance(ref_data, str):
                    try:
                      AddRefToSet(ref_data, font_data_obj_nums)
                    except PdfTokenParseError:
                      pass
        elif (pdf_obj.Get('Type') == '/Page' and
              pdf_obj.Get('Contents') is not None):
          AddRefToSet(pdf_obj.Get('Contents'), contents_obj_nums)
        elif pdf_obj.Get('Subtype') == '/Form':
          contents_obj_nums.add(obj_num)

        # Some PDFs generated by early pdftexs have /Type/FontDescriptor
        # missing.
        if pdf_obj.Get('Type') in ('/FontDescriptor', None):
          for key in PdfObj.PDF_FONT_FILE_KEYS:
            ref_data = pdf_obj.Get(key)
            if isinstance(ref_data, str):
              try:
                AddRefToSet(ref_data, font_data_obj_nums)
              except PdfTokenParseError:
                pass

        # TODO(pts): reorder parsing to resolve future objects in
        # objs=pdf.objs below.
        if (pdf_obj.Get('Subtype') == '/Image' or
            pdf_obj.DetectInlineImage(objs=pdf.objs)):
          if obj_num in contents_obj_nums:
            contents_obj_nums.remove(obj_num)
          image_obj_nums.add(obj_num)

    pdf.ParseSequentially(
        data=data, file_name=file_name, offsets_out=offsets_out,
        obj_num_by_ofs_out=obj_num_by_ofs_out,
        setitem_callback=SetItemCallback)

    for obj_num in sorted(image_obj_nums):
      assert obj_num not in contents_obj_nums
      assert obj_num not in font_data_obj_nums
      obj_size = obj_size_by_num.get(obj_num)
      if obj_size is not None:
        stats['image_objs'] += obj_size
        stats['other_objs'] -= obj_size

    for obj_num in sorted(contents_obj_nums):
      assert obj_num not in font_data_obj_nums
      obj_size = obj_size_by_num.get(obj_num)
      if obj_size is not None:
        stats['contents_objs'] += obj_size
        stats['other_objs'] -= obj_size

    for obj_num in sorted(font_data_obj_nums):
      obj_size = obj_size_by_num.get(obj_num)
      if obj_size is not None:
        stats['font_data_objs'] += obj_size
        stats['other_objs'] -= obj_size

    assert stats['other_objs'] > 0  # We must have a page catalog etc.

    if trailer_obj_num[0] is None:
      assert len(offsets_out) == offsets_idx[0] + 3
      assert stats['trailer'] == 0
      assert stats['xref'] == 0
      stats['xref'] += offsets_out[-2] - offsets_out[-3]
      stats['separator_data'] -= offsets_out[-2] - offsets_out[-3]
      stats['trailer'] += offsets_out[-1] - offsets_out[-2]
      stats['separator_data'] -= offsets_out[-1] - offsets_out[-2]
    else:
      # With cross reference stream.
      # For testing: any Multivalent output
      assert len(offsets_out) == offsets_idx[0] + 1
      assert stats['trailer'] > 0
      assert stats['xref'] > 0

    for key in sorted(stats):
      print >>sys.stderr, 'info: stat %s = %s bytes (%s)' % (
          key, stats[key], FormatPercent(stats[key], len(data)))
    print >>sys.stderr, 'info: end of stats'
    sum_stats = sum(stats.values())
    assert sum_stats == len(data), (
        'stats size mismatch: total_stats_size=%r, file_size=%r' %
        (sum_stats, len(data)))
    return stats

  @classmethod
  def MSBFirstToInteger(cls, s):
    """Convert a string containing a base-256 MSBFirst number to an integer."""
    # TODO(pts): Optimize this, including calls.
    assert isinstance(s, str)
    assert s
    if len(s) == 1:
      return ord(s)
    elif len(s) == 2:
      return struct.unpack('>H', s)[0]
    elif len(s) == 4:
      return struct.unpack('>L', s)[0]
    else:
      ret = 0
      for c in s:
        ret = ret << 8 | ord(c)
      return ret

  @classmethod
  def FixPdfFromMultivalent(cls, data, do_generate_xref_stream=True):
    """Fix PDF contents file in data, generated by Mulitvalent.jar.
    
    Raises:
      PdfXrefStreamError:
      many:
    """
    in_offsets = []
    obj_num_by_in_ofs = {}
    # TODO(pts): Use a setitem_callback here to save memory.
    pdf = PdfData().ParseSequentially(
        data=data, offsets_out=in_offsets,
        obj_num_by_ofs_out=obj_num_by_in_ofs)
    # in_offsets[-1] is the offset of `startxref'
    if pdf.trailer.stream is None:
      raise PdfTokenParseError('expected xref stream from Multivalent')
    if pdf.trailer.Get('Type') != '/XRef':
      raise PdfTokenParseError('expected /Type/XRef from Multivalent')
    if do_generate_xref_stream:
      version = max(pdf.version, '1.5')
    else:
      version = pdf.version
    pdf_objs = pdf.objs

    # Keep initial comments, including the '%PDF-' header.
    output = ['%PDF-', version, '\n%\xD0\xD4\xC5\xD0\n']
    output_size = 0
    output_size_idx = 0
    total_padding_size = 0
    out_ofs_by_num = {}

    in_ofs_by_num = {}
    for offsets_idx in xrange(len(in_offsets) - 1):
      obj_ofs = in_offsets[offsets_idx]
      obj_num = obj_num_by_in_ofs[obj_ofs]
      if type(obj_num) not in (int, long):
        raise PdfTokenParseError
      if obj_num < 1:
        raise PdfTokenParseError
      in_ofs_by_num[obj_num] = obj_ofs
    #assert 0, in_ofs_by_num
      
    trailer_ofs = trailer_obj_num = None
    for offsets_idx in xrange(len(in_offsets) - 1):
      obj_ofs = in_offsets[offsets_idx]
      obj_num = obj_num_by_in_ofs[obj_ofs]
      obj_size = in_offsets[offsets_idx + 1] - obj_ofs
      pdf_obj = pdf_objs[obj_num]
      head = pdf_obj.head

      while output_size_idx < len(output):
        output_size += len(output[output_size_idx])
        output_size_idx += 1
      out_ofs_by_num[obj_num] = old_output_size = output_size

      # We use substring search only to speed up the real match with Get.
      if (head.startswith('<<') and
          '/Subtype/ImagE' in head and
          ('/FilteR/' in head or '/FilteR[' in head)):
        subtype = pdf_obj.Get('Subtype')
        filtercap = pdf_obj.Get('FilteR')
        decodeparmscap = pdf_obj.Get('DecodeParmS')
        if subtype == '/ImagE' and isinstance(filtercap, str):
          pdf_obj.Set('Subtype', '/Image')
          assert pdf_obj.Get('Filter') == '/JPXDecode'
          pdf_obj.Set('Filter', filtercap)
          pdf_obj.Set('FilteR', None)
          pdf_obj.Set('DecodeParms', decodeparmscap)
          pdf_obj.Set('DecodeParmS', None)
      elif pdf_obj is pdf.trailer:
        trailer_ofs = obj_ofs
        trailer_obj_num = obj_num
        # TODO(pts): Update the cross-reference table (/W and stream), so
        # we can remove additional whitespace.
        # Please note that we save the space of the removed /ID and /Compress
        # below, because /Type/XRef is usually the last object, so we don't
        # need to add padding.
        pdf_obj.Set('ID', None)
        pdf_obj.Set('Compress', None)
        if pdf_obj.Get('Index') != None:
          # Multivalent doesn't generate /Index.
          raise NotImplementedError('unexpected /Index in xref object')
        if pdf_obj.Get('Prev') != None:
          raise NotImplementedError('unexpected /Prev in xref object')

        # Please note that Multivalent generates a PDF which uses
        # /Type/ObjStm object stream objects holding small objects
        # (f0=2 in xref_data). We won't touch those in xref_data.

        w0, w1, w2, unused_index, xref_data = pdf_obj.GetXrefStream()
        xref_out = array.array('B', xref_data)
        i = 0
        ref_obj_num = -1
        # Maps /Type/ObjStm obj num to the list of strings (or other basic
        # values suitable for a PdfObj._head) it contains.
        objstm_cache = {}
        while i < len(xref_data):
          # See Table 3.16 Entries in a cross-reference stream in
          # pdf_reference_1-7.pdf.
          if w0:
            f0 = cls.MSBFirstToInteger(xref_data[i : i + w0])
            i += w0
          else:
            f0 = 1
          f1 = cls.MSBFirstToInteger(xref_data[i : i + w1])
          i += w1
          if w2:
            f2 = cls.MSBFirstToInteger(xref_data[i : i + w2])
            i += w2
          else:
            f2 = 0
          ref_obj_num += 1
          if f0 == 1 and f1 > 0:
            # For testing: pgfmanual.pdf has generation number == 255 here:
            #assert f2 == 0  # generation number
            fx = in_ofs_by_num[ref_obj_num]
            # TODO(pts): Make it work for w1 > 8 ('Q' is max 8)
            assert  fx == f1, (
                 'expected %d (%r), read %d (%r) in xref stream at %d' %
                 (fx, struct.pack('>Q', fx)[-w1:],
                  f1, struct.pack('>Q', f1)[-w1:], i - w2 - w1))
            fo = out_ofs_by_num[ref_obj_num]
            if do_generate_xref_stream:
              if f1 != fo:  # Update the object offset in the xref stream.
                # TODO(pts): Optimize this.
                j = i - w2 - 1
                k = j - w1
                while j > k:
                  xref_out[j] = fo & 255
                  fo >>= 8
                  j -= 1
          elif not do_generate_xref_stream and f0 == 2 and f1 > 0:
            # Obj ref_obj_num can be fetched from /Type/ObjStm obj f1, index
            # f2.
            objstm_items = objstm_cache.get(f1)
            if objstm_items is None:
              objstm_items = objstm_cache[f1] = PdfObj.ParseArray(
                  '[%s]' % pdf_objs[f1].GetUncompressedStream(objs=pdf_objs))
              assert len(objstm_items) % 3 == 0
              del objstm_items[:len(objstm_items) * 2 / 3]
            pdf_objs[ref_obj_num] = PdfObj(
                '%d 0 obj\n%s\nendobj' %
                (ref_obj_num, PdfObj.SimpleValueToString(objstm_items[f2])),
                objs=pdf_objs)
            while output_size_idx < len(output):
              output_size += len(output[output_size_idx])
              output_size_idx += 1
            out_ofs_by_num[ref_obj_num] = output_size
            pdf_objs[ref_obj_num].AppendTo(output, ref_obj_num)

        if do_generate_xref_stream:
          xref_out = xref_out.tostring()
          # For testing: Multivalent generates
          # /DecodeParms<</Predictor 12/Columns 5>>
          # for agilerails3.pdf, which is 9K, instead of 22K without predictor.
          # TODO(pts): 5176.CFF.pso.pdf has
          # /Filter/FlateDecode/DecodeParms <</Predictor 12/Columns 5>>
          pdf_obj.SetStreamAndCompress(
              xref_out, may_keep_old=(xref_out == xref_data),
              predictor_width=(w0 + w1 + w2), pdf=None)
          print >>sys.stderr, (
              'info: compressed xref stream from %s to %s bytes (%s)' %
              (len(xref_out), pdf_obj.size,
               FormatPercent(pdf_obj.size, len(xref_out))))
          del xref_out
        else:
          while output_size_idx < len(output):
            output_size += len(output[output_size_idx])
            output_size_idx += 1
          out_ofs_by_num[trailer_obj_num] = output_size
          # Don't add 1, because this trailer is also counted.
          output.append('xref\n0 %d\n' % len(pdf.objs))
          done_obj_num = 0
          assert trailer_obj_num in pdf.objs
          for ref_obj_num in sorted(pdf.objs):
            if ref_obj_num == trailer_obj_num:
              continue
            while done_obj_num < ref_obj_num:
              output.append('0000000000 65535 f \n')
              done_obj_num += 1
            output.append('%010d 00000 n \n' % out_ofs_by_num[ref_obj_num])
            done_obj_num += 1
          pdf_obj.Set('Type', None)
          pdf_obj.Set('W', None)
          pdf_obj.Set('Filter', None)
          pdf_obj.Set('Length', None)
          pdf_obj.Set('DecodeParms', None)
          pdf_obj.Set('Index', None)
          pdf_obj.Set('Prev', None)
          pdf_obj.Set('Size', len(pdf_objs))
          output.append('trailer\n%s\n' % pdf_obj.head)
          pdf_obj = None

      if pdf_obj:
        pdf_obj.AppendTo(output, obj_num)
        while output_size_idx < len(output):
          output_size += len(output[output_size_idx])
          output_size_idx += 1
        obj_out_size = output_size - old_output_size
        if obj_out_size > obj_size:
          raise PdfOptimizeError('size of obj %s has grown from %s to %s bytes' %
                                 (obj_num, obj_size, obj_out_size))

    if pdf.version != output[1]:  # upgraded because of the xref
      assert len(pdf.version) == len(output[1])
      output[1] = pdf.version
    assert trailer_ofs == in_offsets[-2]
    output.append('startxref\n%d\n' % out_ofs_by_num[trailer_obj_num])
    output.append('%%EOF\n')
    while output_size_idx < len(output):
      output_size += len(output[output_size_idx])
      output_size_idx += 1
    print >>sys.stderr, (
        'info: optimized to %s bytes after Multivalent (%s)' %
        (output_size, FormatPercent(output_size, len(data))))
    if do_generate_xref_stream and output_size > len(data):
      raise PdfOptimizeError('PDF size has grown from %s to %s bytes' %
                             (len(data), output_size))
    return ''.join(output)

  def FindMultivalentJar(self, file_name):
    """Find Multivalent.jar
    
    Args:
      file_name: e.g. 'Multivalent.jar'
    Returns:
      Pathname to Multivalent.jar or None.
    """
    assert os.sep not in file_name
    multivalent_jar = FindOnPath(file_name)
    if multivalent_jar is None:
      slash_file_name = os.sep + file_name
      for item in os.getenv('CLASSPATH', '').split(os.pathsep):
        if not item:
          continue
        if item.endswith(slash_file_name):
          multivalent_jar = item
          break
    return multivalent_jar

  def SaveWithMultivalent(self, file_name, do_escape_images,
                          do_generate_xref_stream):
    """Save this PDF to file_name, return self."""
    # TODO(pts): Specify args to Multivalent.jar.
    # TODO(pts): Specify right $CLASSPATH for Multivalent.jar
    in_pdf_tmp_file_name = 'pso.conv.mi.tmp.pdf'

    assert in_pdf_tmp_file_name.endswith('.pdf')
    # This is what Multivalent.jar generates.
    out_pdf_tmp_file_name = re.sub(
        r'[.][^.]+\Z', '', in_pdf_tmp_file_name) + '-o.pdf'

    print >>sys.stderr, (
        'info: writing Multivalent input PDF: %s' % in_pdf_tmp_file_name)
    orig_file_name = self.file_name
    orig_file_size = self.file_size
    self.Save(in_pdf_tmp_file_name, do_hide_images=do_escape_images)
    in_data_size = self.file_size
    self.file_name = orig_file_name
    self.file_size = orig_file_size
    EnsureRemoved(out_pdf_tmp_file_name)

    multivalent_jar = self.FindMultivalentJar('Multivalent.jar')
    if multivalent_jar is None:
      multivalent_jar = self.FindMultivalentJar('Multivalent20060102.jar')
    if not multivalent_jar:
      print >>sys.stderr, (
          'error: Multivalent.jar not found. Make sure it is on the $PATH, '
          'or it is one of the files on the $CLASSPATH.')
      assert 0, 'Multivalent.jar not found, see above'
    assert os.pathsep not in multivalent_jar  # $CLASSPATH separator

    # See http://code.google.com/p/pdfsizeopt/issues/detail?id=30
    # and http://multivalent.sourceforge.net/Tools/pdf/Compress.html .   
    # TODO(pts): Implement -nocore14 (unembewdding the core 14 fonts) as a
    # pdfsizeopt feature, also implement it if Multivalent is not used.
    multivalent_flags = '-nopagepiece -noalt'

    multivalent_cmd = 'java -cp %s tool.pdf.Compress %s %s' % (
        ShellQuoteFileName(multivalent_jar),
        multivalent_flags,
        ShellQuoteFileName(in_pdf_tmp_file_name))
    print >>sys.stderr, (
        'info: executing Multivalent to optimize PDF: %s' % multivalent_cmd)
    status = os.system(multivalent_cmd)

    if status:
      print >>sys.stderr, 'info: Multivalent failed, status=0x%x' % status
      assert 0, 'Multivalent failed (status)'
    try:
      stat = os.stat(out_pdf_tmp_file_name)
    except OSError:
      print >>sys.stderr, 'info: Multivalent has not created output: ' % (
          out_pdf_tmp_file_name)
      assert 0, 'Multivalent failed (no output)'

    f = open(out_pdf_tmp_file_name, 'rb')
    try:
      data = f.read()
    finally:
      f.close()
    out_data_size = len(data)
    print >>sys.stderr, (
        'info: Multivalent generated %s of %d bytes (%s)' %
        (out_pdf_tmp_file_name,
         out_data_size, FormatPercent(out_data_size, in_data_size)))
    assert out_data_size, (
        'Multivalent generated empty output (see its error above)')
    data = self.FixPdfFromMultivalent(
        data, do_generate_xref_stream=do_generate_xref_stream)
    os.remove(in_pdf_tmp_file_name)
    os.remove(out_pdf_tmp_file_name)

    print >>sys.stderr, 'info: saving PDF to: %s' % (
        file_name)
    f = open(file_name, 'wb')
    try:
      f.write(data)
    finally:
      f.close()
    print >>sys.stderr, 'info: generated %s bytes (%s)' % (
        len(data), FormatPercent(len(data), self.file_size))
    self.file_size = len(data)
    self.file_name = file_name
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
  try:
    size = os.stat(__file__).st_size
  except OSError:
    # We'll get this if __file__ is within a .zip file (on $PYTHONPATH).
    # Since the built-in linecache.py doesn't attempt to read such files,
    # we don't do that either, and keep size = None for simplicity.
    size = None
  try:
    match = re.search(
        r'\npdfsizeopt[.]py\r?\nfile\r?\n(?:(?:[^\r\n]*\r?\n){7})??(\d+)\r?\n',
        open(os.path.join(os.path.dirname(__file__), '.svn', 'entries'), 'rb'
            ).read())
    if match:
      rev = int(match.group(1))
    else:
      rev = None
  except IOError:
    rev = None
  print >>sys.stderr, 'info: This is %s r%s size=%s.' % (
      os.path.basename(__file__), rev or 'UNKNOWN', size)
      
  # Find image converters in script dir first.
  script_dir = os.path.dirname(os.path.abspath(__file__))
  os.environ['PATH'] = '%s%s%s' % (
      script_dir, os.pathsep, os.getenv('PATH', ''))
  if (not os.getenv('PDFSIZEOPT_GS', '') and
      os.path.isfile(script_dir + '/gs-pdfsizeopt/gs')):
    os.environ['PDFSIZEOPT_GS'] = ShellQuote(script_dir + '/gs-pdfsizeopt/gs')
  if not argv:
    argv = [__file__]
  if len(argv) == 1:
    argv.append('--help')

  try:
    use_pngout = True
    use_jbig2 = True
    use_multivalent = True
    do_optimize_images = True
    do_optimize_objs = True
    do_unify_fonts = True
    # Keep optional information about fonts in the PDF?
    do_keep_font_optionals = False
    # It is not much slower (and it's actually faster if some fonts need
    # /LZWDecode), and we can gain a few bytes by converting all Type1C fonts
    # with Ghostscript.
    do_regenerate_all_fonts = True
    do_double_check_missing_glyphs = False
    do_ignore_generation_numbers = True
    # Escaping (i.e. hiding images from Multivalent) is the safe choice
    # since Multivalent handles some predictors in buggy way, thus garbling
    # images data with /Predictor.
    do_escape_images_from_multivalent = True
    do_generate_xref_stream = True
    do_unify_pages = True
    mode = 'optimize'

    # TODO(pts): Don't allow long option prefixes, e.g. --use-pngo=foo
    opts, args = getopt.gnu_getopt(argv[1:], '+', [
        'version', 'help', 'stats',
        'use-pngout=', 'use-jbig2=', 'use-multivalent=',
        'do-ignore-generation-numbers=',
        'do-keep-font-optionals=',
        'do-double-check-missing-glyphs=',
        'do-regenerate-all-fonts=',
        'do-escape-images-from-multivalent=',
        'do-generate-xref-stream=',
        'do-unify-pages=',
        'do-optimize-images=', 'do-optimize-objs=', 'do-unify-fonts='])

    for key, value in opts:
      if key == '--stats':
        mode = 'stats'
      elif key == '--use-pngout':
        # !! add =auto (detect binary on path)
        use_pngout = ParseBoolFlag(key, value)
      elif key == '--use-jbig2':
        # !! add =auto (detect binary on path)
        use_jbig2 = ParseBoolFlag(key, value)
      elif key == '--use-multivalent':
        # !! add =auto (detect Multivalent.jar on $CLASSPATH and $PATH)
        use_multivalent = ParseBoolFlag(key, value)
      elif key == '--do-ignore-generation-numbers':
        do_ignore_generation_numbers = ParseBoolFlag(key, value)
      elif key == '--do-escape-images-from-multivalent':
        do_optimize_images = ParseBoolFlag(key, value)
      elif key == '--do-generate-xref-stream':
        do_generate_xref_stream = ParseBoolFlag(key, value)
      elif key == '--do-unify-pages':
        do_unify_pages = ParseBoolFlag(key, value)
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
        print >>sys.stderr, (
            'info: usage for statistics computation: %s --stats <input.pdf>' %
            argv[0])
        print >>sys.stderr, (
            'info: usage for size optimization: %s [<flag>...] '
            '<input.pdf> [<output.pdf>]' % argv[0])
        # TODO(pts): Implement this.
        print >>sys.stderr, 'error: --help not implemented'
        sys.exit(2)
      elif key == '--version':
        sys.exit(0)  # printed above
      else:
        assert 0, 'unknown option %s' % key

    if mode == 'stats':
      if not args:
        raise getopt.GetoptError('missing filename in command-line')
      elif len(args) > 1:
        raise getopt.GetoptError('too many arguments')
      PdfData.ComputePdfStatistics(file_name=args[0])
      return

    if not args:
      raise getopt.GetoptError('missing filename in command-line')
    elif len(args) == 1:
      file_name = args[0]
      if file_name[-4:].lower() == '.pdf':
        output_file_name = file_name[:-4]
      else:
        output_file_name = file_name
      if use_multivalent:
        output_file_name += '.psom.pdf'
      else:
        output_file_name += '.pso.pdf'
    elif len(args) == 2:
      file_name = args[0]
      output_file_name = args[1]
    else:
      raise getopt.GetoptError('too many command-line args')
  except getopt.GetoptError, exc:
    print >>sys.stderr, 'error: in command line: %s' % exc
    sys.exit(1)

  # It's OK that file_name == output_file_name.
  pdf = PdfData(
      do_ignore_generation_numbers=do_ignore_generation_numbers,
      ).Load(file_name)
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
    pdf.OptimizeObjs(do_unify_pages=do_unify_pages)
  elif pdf.has_generational_objs:
    # TODO(pts): Do only a simpler optimization with renumbering.
    pdf.OptimizeObjs(do_unify_pages=do_unify_pages)
  if use_multivalent:
    pdf.SaveWithMultivalent(
        output_file_name, do_escape_images=do_escape_images_from_multivalent,
        do_generate_xref_stream=do_generate_xref_stream)
  else:
    # !! emit a warning if we have an image with a predictor
    pdf.Save(output_file_name,
             do_generate_xref_stream=do_generate_xref_stream)


if __name__ == '__main__':
  main(sys.argv)
