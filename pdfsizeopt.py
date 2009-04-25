#! /usr/bin/python2.4
#
# pdfsizeopt.py: do various PDF size optimizations
# by pts@fazekas.hu at Sun Mar 29 13:42:05 CEST 2009
#
# !! rename this file to get image conversion
# TODO(pts): Proper whitespace parsing (as in PDF)
# TODO(pts): re.compile anywhere

"""pdfsizeopt.py: do various PDF size optimizations

This Python script implements some techniques for making PDF files smaller.
It should be used together with pdflatex and tool.pdf.Compress to get a minimal
PDF. See also !!

This script is work in progress.

This scripts needs a Unix system, with Ghostscript and pdftops (from xpdf),
sam2p and pngout. Future versions may relax the system requirements.
"""

__author__ = 'pts@fazekas.hu (Peter Szabo)'

import getopt
import os
import os.path
import re
import struct
import sys
import time
import zlib


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
  return '%d%%' % int((num * 100 + (den / 2)) // den)


def EnsureRemoved(file_name):
  try:
    os.remove(file_name)
  except OSError:
    assert not os.path.exists(file_name)


class PdfTokenParseError(Exception):
  """Raised if a string cannot be parsed to a PDF token sequence."""


class PdfTokenTruncated(Exception):
  """Raised if a string is only a prefix of a PDF token sequence."""


class PdfTokenNotString(Exception):
  """Raised if a PDF token sequence is not a single string."""


class PdfObj(object):
  """Contents of a PDF object.

  Attributes:
    head: stripped string between `obj' and (`stream' or `endobj')
    stream: stripped string between `stream' and `endstream', or None
  """
  __slots__ = ['head', 'stream']

  def __init__(self, other, objs=None, file_ofs=0):
    """Initialize from other.

    If other is a PdfObj, copy everything. Otherwise, if other is a string,
    start parsing it from `X 0 obj' (ignoring the number) till endobj.

    Args:
      objs: A dictionary mapping obj numbers to existing PdfObj objects. These
        can be used for resolving `R's to build self.
    """
    if isinstance(other, PdfObj):
      self.head = other.head
      self.stream = other.stream
    elif isinstance(other, str):
      # !! TODO(pts): what if endobj is part of a string in the obj? --
      # parse properly
      match = re.match(r'(?s)\d+\s+0\s+obj\b\s*', other)
      assert match
      skip_obj_number_idx = len(match.group(0))
      match = re.search(r'\b(stream(?:\r\n|\s)|endobj(?:\s|\Z))', other)
      assert match
      self.head = other[skip_obj_number_idx : match.start(0)].rstrip()
      if match.group(1).startswith('endobj'):
        self.stream = None
        # Implicit \s here. TODO(pts): Do with less copy.
      else:  # has 'stream'
        # TODO(pts): Proper parsing.
        #print repr(self.head), repr(match.group(1))
        stream_start_idx = match.end(1)
        match = re.search(r'/Length\s+(\d+)(?:\s+0\s+(R)\b)?', self.head)
        assert match
        if match.group(2) is None:
          stream_end_idx = stream_start_idx + int(match.group(1))
        else:
          stream_end_idx = stream_start_idx + int(
              objs[int(match.group(1))].head)
        endstream_str = other[stream_end_idx : stream_end_idx + 30]
        assert re.match(
            r'\s*endstream\s+endobj(?:\s|\Z)', endstream_str), (
            'expected endstream+endobj in %r at %s' %
            (endstream_str, file_ofs + stream_end_idx))
        self.stream = other[stream_start_idx : stream_end_idx]
    elif other is None:
      pass
    else:
      raise TypeError

  def AppendTo(self, output, obj_num):
    """Append serialized self to output list, using obj_num."""
    output.append('%s 0 obj\n' % int(obj_num))
    output.append(self.head.strip())  # Implicit \s .
    if self.stream is not None:
      output.append('\nstream\n')
      output.append(self.stream)
      output.append('\nendstream\nendobj\n')
    else:
      output.append('\nendobj\n')

  @property
  def size(self):
    if self.stream is None:
      return len(self.head) + 20
    else:
      return len(self.head) + len(self.stream) + 32

  @classmethod
  def GetParsableHead(cls, head):
    """Make head parsable for Get and Set, return the new head."""
    # !! stupid code here
    assert head.startswith('<<')
    assert head.endswith('>>')
    if not head.startswith('<<\n'):
      # !! avoid code duplication with self.Get()
      h = {}
      rest = re.sub(
          r'(?s)\s*/([-.#\w]+)\s*(\[.*?\]|<</XObject<<.*?>>.*?>>|<<.*?>>|\S[^/]*)',
          lambda match: h.__setitem__(match.group(1),
              re.sub('[\n\r]+', ' ', match.group(2).rstrip())),
          head[:-2])  # Without `>>'
      rest = rest.strip()
      assert re.match(r'<<\s*\Z', rest), (
          'could not parse PDF obj, left %r' % rest)
      if not h: return '<<\n>>'
      return '<<\n%s>>' % ''.join(
          ['/%s %s\n' % (key, value)
           for key, value in h.items()])  # TODO(pts): sorted
    else:
      return head

  def Get(self, key):
    """!!Return int, long, bool, float, None; or str if it's a ref or more complicated."""
    # !! autoresolve refs
    # !! proper PDF object parsing
    assert self.head.startswith('<<')
    assert self.head.endswith('>>')
    if self.head.startswith('<<\n'):
      i = self.head.find('\n/' + key + ' ')
      if i < 0: return None
      i += len(key) + 3
      j = self.head.find('\n', i)
      value = self.head[i : j].strip()
    else:
      # Parse dict from sam2p. This cannot parse a /DecodeParms<<...>> value
      # or a binary /Indexed palette
      # !! avoid code duplication
      h = {}
      rest = re.sub(
          r'(?s)\s*/([-.#\w]+)\s*(\[.*?\]|<</XObject<<.*?>>.*?>>|\S[^/]*)',
          lambda match: h.__setitem__(match.group(1), match.group(2).rstrip()),
          self.head[:-2])  # Without `>>'
      rest = rest.strip()
      assert re.match(r'<<\s*\Z', rest), (
          'could not parse PDF obj, left %r' % rest)
      value = h.get(key)
      if value is None: return None
          
    if value in ('true', 'false'):
      return value == 'true'
    elif value == 'null':
      return None
    elif re.match(r'\d+\Z', value):
      return int(value)
    elif re.match(r'\d[.\d]*\Z', value):  # !! proper PDF float parsing
      return float(value)
    else:
      return value

  def Set(self, key, value):
    """Set value to key or remove key if value is None."""
    # !! proper PDF object parsing
    # !! doc: slow because of string concatenation
    if not self.head.endswith('\n>>'):
      self.head = self.GetParsableHead(self.head)
    assert self.head.endswith('\n>>'), 'bad head: %r' % self.head
    assert self.head.startswith('<<')
    if isinstance(value, bool):
      value = str(value).lower()
    elif isinstance(value, int) or isinstance(value, long):
      value = str(value)
    elif isinstance(value, float):
      value = repr(value)  # !! better serialize for PDF
    elif value is None:
      pass
    else:
      assert isinstance(value, str)
    i = self.head.find('\n/' + key + ' ')
    if i < 0:
      if value is not None:
        self.head = '%s/%s %s\n>>' % (self.head[:-2], key, value)
    else:
      j = self.head.find('\n', i + len(key) + 3)
      self.head = self.head[:i] + self.head[j:]
      if value is not None:
        self.head = '%s/%s %s\n>>' % (self.head[:-2], key, value)

  @classmethod
  def EscapeString(cls, data):
    """Escape a string to the shortest possible PDF string literal."""
    if not isinstance(data, str): raise TypeError
    # We never emit hex strings (e.g. <face>), because they cannot ever be
    # shorter than the literal binary string.
    if '(' not in data or ')' not in data:
      # No way to match parens.
      return '(%s)' % re.sub(r'([()\\])', r'\\\1', data)
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
  def IsGrayColorSpace(cls, colorspace):
    if not isinstance(colorspace, str): raise TypeError
    colorspace = colorspace.strip()
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
    end_ofs_out = []
    pdf_data2 = cls.RewriteParsable(pdf_data, end_ofs_out=end_ofs_out)
    if pdf_data[end_ofs_out[0]:].strip():
      raise PdfTokenNotString
    if not pdf_data2.startswith(' <') or not pdf_data2.endswith('>'):
      raise PdfTokenNotString
    return pdf_data2[2 : -1].decode('hex')

  PDF_CLASSIFY = [40] * 256
  """Mapping a 0..255 byte to a character type used by RewriteParsable.

  * PDF whitespace(0) is  [\\000\\011\\012\\014\\015\\040]
  * PDF separators(10) are < > { } [ ] ( ) / %
  * PDF regular(40) character is any of [\\000-\\377] which is not whitespace
    or separator.
  """

  PDF_CLASSIFY[ord('\0')] = PDF_CLASSIFY[ord('\t')] = 0
  PDF_CLASSIFY[ord('\n')] = PDF_CLASSIFY[014] = 0
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
  def RewriteParsable(cls, data, start_ofs=0,
      end_ofs_out=None, do_terminate_obj=False):
    """Rewrite PDF token sequence so it will be easier to parse by regexps.

    Parsing stops at `stream', `endobj' or `startxref', which will also
    be returned at the end of the string.

    This code is based on pdf_rewrite in pdfdelimg.pl, which is based on
    pdfconcat.c . Lesson learned: Perl is more compact than Python; Python is
    easier to read than Perl.

    This method doesn't check the type of dict keys, the evenness of dict
    item size etc.
    
    Please don't change ``parsable'' to ``parseable'', see
    http://en.wiktionary.org/wiki/parsable .

    Args:
      data: String containing a PDF token sequence.
      start_ofs: Offset in data to start the parsing at.
      end_ofs_out: None or a list for the first output byte
        (which is unparsed) offset to be appended. Terminating whitespace is not included, except for
        a single withespace is only after the `stream'.
      do_terminate_obj: Boolean indicating whether look for and include the
        `stream' or `endobj' plus one whitespace (or \\r\\n) at end_ofs_out
        (and in the string). Any terminating name is accepted.
    Returns:
      Nonempty string containing a PDF token sequence which is easier to
      parse with regexps, because it has additional whitespace, it has no
      funny characters, and it has strings escaped as hex. The returned string
      starts with a single space.
    Raises:
      PdfTokenParseError: TODO(pts): Report the error offset as well.
      PdfTokenTruncated:
    """
    # !! inline regexps here
    data_size = len(data)
    i = start_ofs
    if data_size <= start_ofs:
      raise PdfTokenTruncated
    output = []
    # Stack of '[' (list) and '<' (dict)
    stack = ['-']
    if do_terminate_obj:
      stack[:0] = ['.']

    while stack:
      if i >= data_size:
        raise PdfTokenTruncated('structures open: %r' % stack)

      # TODO(pts): Faster parsing (skipping whitespace?) by regexp search.
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

        number_match = re.match(r'(?:([-])|[+]?)0*(\d+(?:[.]\d+)?)\Z', token)
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
          output.append(
              ' /' + re.sub(r'[^-A-Za-z0-9_.]',
                  lambda match: '#%02x' % ord(match.group(0)), token[1:]))
        else:
          output.append(
              ' ' + re.sub(r'[^-A-Za-z0-9_.]',
                  lambda match: '#%02x' % ord(match.group(0)), token))

        if (number_match or token[0] == '/' or
            token in ('true', 'false', 'null')):
          if stack[-1] == '-':
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
              raise PdfTokenTruncated
            if data[i] == '\n':  # Skip over \r\n.
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
              string_output.append("\\'")
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

  def GetDecompressedStream(self):
    if self.stream is None: return None
    filter = self.Get('Filter')
    if filter is None: return self.stream
    if filter != '/FlateDecode':
      raise NotImplementedError('filter not implemented: %s' + filter)
    decodeparms = self.Get('DecodeParms') or ''
    if '/Predictor' in decodeparms:
      raise NotImplementedError('/DecodeParms not implemented')
    return zlib.decompress(self.stream)


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

  def CanBePDFImage(self):
    return bool(self and self.bpc in (1, 2, 4, 8) and
                self.color_type in ('gray', 'rgb', 'indexed-rgb') and
                not self.is_interlaced)

  @property
  def samples_per_pixel(self):
    assert self.color_type
    return self.SAMPLES_PER_PIXEL_DICT[self.color_type]

  def GetPDFColorSpace(self):
    assert self.color_type
    assert not self.color_type.startswith('indexed-') or self.plte
    if self.color_type == 'gray':
      return '/DeviceGray'
    elif self.color_type == 'rgb':
      return '/DeviceRGB'
    elif self.color_type == 'indexed-rgb':
      assert self.plte
      assert len(self.plte) % 3 == 0
      palette_dump = PdfObj.EscapeString(self.plte)
      return '[/Indexed/DeviceRGB %d%s]' % (
          len(self.plte) / 3 - 1, palette_dump)
    else:
      assert 0, 'cannot convert to PDF color space'

  def GetPDFImageData(self):
    """Return a dictinary useful as a PDF image."""
    assert self.CanBePDFImage()  # asserts not interlaced
    pdf_image_data = {
        'Width': self.width,
        'Height': self.height,
        'BitsPerComponent': self.bpc,
        'ColorSpace': self.GetPDFColorSpace(),
        '.stream': self.idat,
    }
    if self.compression == 'none':
      pass
    elif self.compression == 'zip':
      pdf_image_data['Filter'] = '/FlateDecode'
    elif self.compression in ('zip-tiff', 'zip-png'):
      pdf_image_data['Filter'] = '/FlateDecode'
      pdf_image_data['DecodeParms'] = (
          '<</BitsPerComponent %d/Columns %d/Colors %d/Predictor %d>>' %
          (self.bpc, self.width, self.samples_per_pixel,
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
    pdf_image_data = self.GetPDFImageData()
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

  def SavePng(self, file_name, do_force_gray=False):
    """Save in PNG format to specified file, update file_name."""
    print >>sys.stderr, 'info: saving PNG to %s' % (file_name,)
    assert self
    assert self.compression == 'zip-png'
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
    # !! proper PDF object parsing
    image_obj_nums = [
        obj_num for obj_num in sorted(pdf.objs)
        if re.search(r'/Subtype\s*/Image\b', pdf.objs[obj_num].head)]
    # !! image_obj_nums is empty on empty page (by sam2p)
    assert len(image_obj_nums) == 1, (
        'no single image XObject in PDF, got %r' % image_obj_nums)
    obj = pdf.objs[image_obj_nums[0]]
    # !! support single-color image by sam2p
    filter = obj.Get('Filter')
    if filter is None:
      filter = '/FlateDecode'
      # TODO(pts): Would a smaller effort (compression level) suffice here?
      obj.stream = zlib.compress(obj.stream, 9)
      obj.Set('DecodeParms', None)
    assert filter == '/FlateDecode', 'image in PDF is not ZIP-compressed'
    width = int(obj.Get('Width'))
    height = int(obj.Get('Height'))
    palette = None
    if obj.Get('ImageMask'):
      colorspace = None
      # Convert imagemask generated by sam2p to indexed1
      page_objs = [pdf.objs[obj_num] for obj_num in sorted(pdf.objs) if
                   re.search(r'/Type\s*/Page\b', pdf.objs[obj_num].head)]
      if len(page_objs) == 1:
        contents = page_objs[0].Get('Contents')
        match = re.match(r'(\d+)\s+0\s+R\Z', contents)
        assert match
        content_obj = pdf.objs[int(match.group(1))]
        content_stream = content_obj.GetDecompressedStream()
        content_stream = ' '.join(content_stream.strip().split())
        number_re = r'\d+(?:[.]\d*)?'  # TODO(pts): Exact PDF number regexp.
        # Example content_stream, as emitted by sam2p-0.46:
        # q 0.2118 1 0 rg 0 0 m %(width)s 0 l %(width)s %(height)s l 0
        # %(height)s l F 1 1 1 rg %(width)s 0 0 %(height)s 0 0 cm /S Do Q
        content_re = (
            r'q (%(number_re)s) (%(number_re)s) (%(number_re)s) rg 0 0 m '
            r'%(width)s 0 l %(width)s %(height)s l 0 %(height)s l F '
            r'(%(number_re)s) (%(number_re)s) (%(number_re)s) rg %(width)s '
            r'0 0 %(height)s 0 0 cm /[-.#\w]+ Do Q\Z' % locals())
        match = re.match(content_re, content_stream)
        if match:
          # TODO(pts): Clip the floats to the interval [0..1]
          color1 = (chr(int(float(match.group(1)) * 255 + 0.5)) +
                    chr(int(float(match.group(2)) * 255 + 0.5)) +
                    chr(int(float(match.group(3)) * 255 + 0.5)))
          color2 = (chr(int(float(match.group(4)) * 255 + 0.5)) +
                    chr(int(float(match.group(5)) * 255 + 0.5)) +
                    chr(int(float(match.group(6)) * 255 + 0.5)))
          if not (obj.Get('Decode') or '[0 1]').startswith('[0'):
            palette = color2 + color1
          else:
            palette = color1 + color2
          colorspace = '.indexed'
      assert colorspace is not None, 'unrecognized sam2p /ImageMask'
    else:
      colorspace = obj.Get('ColorSpace')
      # !! gracefully fail if cannot parse
      # !! parse palette in full binary syntax
      match = re.match(r'\[\s*/Indexed\s*/DeviceRGB\s*\d+\s*<([\s0-9a-fA-F]*)>\s*\]\Z', colorspace)
      if match:
        # !! document error in `.decode'
        palette = re.sub(r'\s+', '', match.group(1)).decode('hex')
        assert palette
        assert len(palette) % 3 == 0
        colorspace = '.indexed'
      else:
        assert colorspace in ('/DeviceRGB', '/DeviceGray'), (
            'unrecognized ColorSpace %r' % colorspace)
    # Since we support only /FlateDecode, we don't have to support DecodeParms
    # being an array.
    decodeparms = PdfObj(None)
    decodeparms.head = obj.Get('DecodeParms') or '<<\n>>'
    if obj.Get('Decode') is not None:
      raise NotImplementederror('parsing PDF /Decode not implemented')

    predictor = decodeparms.Get('Predictor')
    assert predictor is None or isinstance(predictor, int), (
        'expected integer predictor, got %r' % predictor)
    if not predictor or predictor == 1:
      compression = 'zip'
    elif predictor == 2:
      compression = 'zip-tiff'
    elif 10 <= predictor <= 19:
      # TODO(pts): Test this.
      compression = 'zip-png'
    else:
      assert 0, 'expected valid predictor, got %r' % predictor
    if compression in ('zip-tiff', 'zip-png'):
      assert decodeparms.Get('BitsPerComponent') == obj.Get('BitsPerComponent')
      assert decodeparms.Get('Columns') == obj.Get('Width')
      if colorspace == '/DeviceRGB':
        colors = 3
      else:
        colors = 1
      assert decodeparms.Get('Colors') == colors

    self.Clear()
    self.width = width
    self.height = height
    self.bpc = int(obj.Get('BitsPerComponent'))
    if colorspace == '/DeviceRGB':
      assert palette is None
      self.color_type = 'rgb'
    elif colorspace == '/DeviceGray':
      assert palette is None
      self.color_type = 'gray'
    elif colorspace == '.indexed':
      self.color_type = 'indexed-rgb'
      assert isinstance(palette, str)
      assert len(palette) % 3 == 0
    else:
      assert 0, 'bad colorspace %r' % colorspace
    self.is_interlaced = False
    self.plte = palette
    self.compression = compression
    self.idat = str(obj.stream)

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


class PdfData(object):

  __slots__ = ['objs', 'trailer', 'version', 'file_name', 'file_size']

  def __init__(self):
    # Maps an object number to a PdfObj
    self.objs = {}
    # Stripped string dict. Must contain /Size (max # objs) and /Root ref.
    self.trailer = '<<>>'
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
    version = match.group(1)
    self.objs = {}
    self.trailer = ''
    # None, an int or 'trailer'.
    prev_obj_num = None
    prev_obj_start_idx = None
    obj_data = {}
    obj_start = {}

    for match in re.finditer(r'\n(?:(\d+)\s+(\d+)\s+obj|trailer)\s', data):
      if prev_obj_num is not None:
        obj_data[prev_obj_num] = data[prev_obj_start_idx : match.start(0)]
      if match.group(1) is not None:
        prev_obj_num = int(match.group(1))
        assert 0 == int(match.group(2))
      else:
        prev_obj_num = 'trailer'
      # Skip over '\n'
      obj_start[prev_obj_num] = prev_obj_start_idx = match.start(0) + 1
    if prev_obj_num is not None:
      obj_data[prev_obj_num] = data[prev_obj_start_idx : ]

    # SUXX: no trailer in  pdf_reference_1-7-o.pdf
    # TODO(pts): Learn to parse that as well.
    assert prev_obj_num == 'trailer'
    trailer_data = obj_data.pop('trailer')
    print >>sys.stderr, 'info: separated to %s objs' % len(obj_data)
    assert obj_data

    match = re.match('(?s)trailer\s+(<<.*?>>)\s*startxref\s', trailer_data)
    assert match
    self.trailer = match.group(1)

    # Get numbers first, so later we can resolve '/Length 42 0 R'.
    # TODO(pts): Add proper parsing, so this first pass is not needed.
    for obj_num in obj_data:
      this_obj_data = obj_data[obj_num]
      if 'endstream' not in this_obj_data and '<<' not in this_obj_data:
        self.objs[obj_num] = PdfObj(obj_data[obj_num],
                                    file_ofs=obj_start[obj_num], )

    # Second pass once we have all length numbers.
    for obj_num in obj_data:
      if obj_num not in self.objs:
        self.objs[obj_num] = PdfObj(obj_data[obj_num], objs=self.objs,
                                    file_ofs=obj_start[obj_num])

    return self

  def Save(self, file_name):
    """Save this PDf to file_name, return self."""
    print >>sys.stderr, 'info: saving PDF to: %s' % (file_name,)
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
      # Number of objects including missing ones.
      obj_size = obj_numbers[-1] + 1
      for obj_num in obj_numbers:
        obj_ofs[obj_num] = GetOutputSize()
        self.objs[obj_num].AppendTo(output, obj_num)

      # Emit xref.
      xref_ofs = GetOutputSize()
      output.append('xref\n0 %s\n' % obj_size)
      # TODO(pts): Compress spares obj_numbers list.
      for obj_num in xrange(obj_size):
        if obj_num in obj_ofs:
          output.append('%010d 00000 n \n' % obj_ofs[obj_num])
        else:
          output.append('0000000000 65535 f \n')

      # Emit trailer etc.
      output.append('trailer\n')
      output.append(self.trailer)
      output.append('\nstartxref\n%s\n' % xref_ofs)
      output.append('%%EOF\n')
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

/ReadStreamFile {  % <streamdict> ReadStream <streamdict> <compressed-file>
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

/obj {  % <objnumber> <gennumber> obj -
  pop
  save exch
  /_ObjNumber exch def
  % Imp: read <streamdict> here (not with `token', but recursively), so
  %      don't redefine `stream'
} bind def
% </ProcSet>

'''

  TYPE1_CONVERTER_PROCSET = r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

/stream {  % <streamdict> stream -
  ReadStreamFile
  % stack: <streamdict> <compressed-file>
  exch
  % TODO(pts): Give these parameters to th /ReusableStreamDecode in
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
  currentdict end
  % stack: <compressed-file> <streamdict> <reusabledict>
  exch pop /ReusableStreamDecode filter
  % stack: <decompressed-file> (containing a Type1 font program)
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  9 dict begin dup mark exch cvx exec cleartomark cleartomark closefile end
  systemdict /FontDirectory get
  dup length 0 eq {/invalidfileaccess /NoFontDefined signalerror} if
  dup length 1 gt {/invalidfileaccess /MultipleFontsDefined signalerror} if
  [exch {pop} forall] 0 get  % Convert FontDirectory to the name of our font
  dup /_OrigFontName exch def
  % stack: <fontname>
  findfont dup length dict copy
  % Let the font name be /Obj68 etc.
  % We have to unset /OrigFont here, because otherwise Ghostscript would put
  % the /FontName defined there to the PDF object /Type/FontDescriptor , thus
  % preventing us from identifying the output font by input object number.
  dup /FontName _ObjNumber 10 string cvs (Obj) exch concatstrings cvn put
  dup /FullName _ObjNumber 10 string cvs (Obj) exch concatstrings put
  %dup /FID undef  % undef not needed.
  dup /OrigFont undef  % This is OK eeven if /OrigFont doesn't exist.
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

  % We have to make sure that all characters are on the page -- otherwise
  % Ghostscript 8.61 becomes too smart and it won't embed the outlier
  % characters to to page.
  %0 20 translate  20 0 moveto
  500 500 moveto

  16 scalefont  dup setfont
  % We need at least one glypshow to get the font embedded
  % It makes a few bytes of difference if we include all glyphs or only one,
  % but it doesn't matter WRT the final result.
  % TODO(pts): Investigate how many glyphs to show.
  % 500 500 moveto is needed here, otherwise some characters would be too
  % far to the right so Ghostscript 8.61 would crop them from the page and
  % wouldn't include them to the fonts.
  %dup /CharStrings get {pop 500 500 moveto glyphshow} forall
  dup /CharStrings get [ exch {pop} forall ] 0 get glyphshow

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
      the PdfObj of the /FontFile* obj. Please note that this dictionary is not
      a subdictionary of self.objs, because of the different key--value
      mapping.
    """
    assert font_type in ('Type1', 'Type1C', None)
    font_file_tag = {'Type1': 'FontFile', 'Type1C': 'FontFile3',
                     None: None}[font_type]

    objs = {}
    font_count = 0
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]
      # TODO(pts): Proper parsing.
      if (re.search(r'/Type\s*/FontDescriptor\b', obj.head) and
          re.search(r'/FontName\s*/', obj.head)):
        # Type1C fonts have /FontFile3 instead of /FontFile.
        # TODO(pts): Do only Type1 fonts have /FontFile ?
        # What about Type3 fonts?
        match = re.search(r'/(FontFile\d*)\s+(\d+)\s+0 R\b', obj.head)
        if (match and (font_file_tag is None or
            match.group(1) == font_file_tag)):
          font_obj_num = int(match.group(2))
          if do_obj_num_from_font_name:
            match = re.search(r'/FontName\s*/([#-.\w]+)', obj.head)
            assert match
            assert re.match(r'Obj(\d+)\Z', match.group(1))
            objs[int(match.group(1)[3:])] = self.objs[font_obj_num]
          else:
            objs[obj_num] = self.objs[font_obj_num]
          font_count += 1
    if font_type is None:
      print >>sys.stderr, 'info: found %s fonts' % font_count
    else:
      print >>sys.stderr, 'info: found %s %s fonts' % (font_count, font_type)
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
    output.append(r'(Type1CConverter: all OK\n) print flush')
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
        '-sOutputFile=%s -c "<</CompatibilityLevel 1.4 /EmbedAllFonts true '
        # Ghostscript removes all characters from fonts outside this range.
        '/PageSize [1000 1000] '
        '/ImagingBBox null '  # No effect, characters get clipped.
        '/Optimize true /SubsetFonts false>>setpagedevice .setpdfwrite" -f %s'
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
    os.remove(pdf_tmp_file_name)
    # TODO(pts): Undo if no reduction in size.
    print >>sys.stderr, (
        'info: optimized total Type1 font size %s to Type1C font size %s '
        '(%s)' %
        (type1_size, type1c_size, FormatPercent(type1c_size, type1_size)))
    return type1c_objs

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
    ( colorspace=) print dup /ColorSpace get ===only
    ( filter=) print dup /Filter .knownget not {null} if ===only
    ( decodeparms=) print dup /DecodeParms .knownget not {null} if ===only
    ( device=) print currentpagedevice
      /OutputDevice get dup length string cvs print
    (\n) print flush
  pop
  
  % stack: <streamdict> <compressed-file>
  exch
  % TODO(pts): Give these parameters to th /ReusableStreamDecode in
  % ReadStreamFile.
  % !! reuse this code
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
    output.append(r'(ImageRenderer: all OK\n) print flush')
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

  def ConvertType1FontsToType1C(self):
    """Convert all Type1 fonts to Type1C in self, returns self."""
    # !! proper tmp prefix
    type1c_objs = self.GenerateType1CFontsFromType1(
        self.GetFonts('Type1'), 'type1cconv.tmp.ps', 'type1cconv.tmp.pdf')
    for obj_num in type1c_objs:
      obj = self.objs[obj_num]
      match = re.search(r'/FontFile\s+(\d+)\s+0 R\b', obj.head)
      assert match
      font_file_obj_num = int(match.group(1))
      new_obj_head = (
          obj.head[:match.start(0)] +
          '/FontFile3 %d 0 R' % font_file_obj_num +
          obj.head[match.end(0):])
      old_size = self.objs[font_file_obj_num].size + obj.size
      new_size = type1c_objs[obj_num].size + (
          obj.size + len(new_obj_head) - len(obj.head))
      if new_size < old_size:
        obj.head = new_obj_head
        self.objs[font_file_obj_num] = type1c_objs[obj_num]
        print >>sys.stderr, (
            'info: optimized Type1 font XObject %s,%s: new size=%s (%s)' %
            (obj_num, font_file_obj_num, new_size,
             FormatPercent(new_size, old_size)))
      else:
        print >>sys.stderr, (
            'info: keeping original Type1 font XObject %s,%s, '
            'replacement too large: old size=%s, new size=%s' %
            (obj_num, font_file_obj_num, old_size, new_size))

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
        return f.read()
      finally:
        f.close()
    else:
      return ImageData().Load(targetfn)

  def OptimizeImages(self, use_pngout=True, use_jbig2=True):
    """Optimize image XObjects in the PDF."""
    # TODO(pts): convert inline images to image XObject{}s.
    # Dictionary mapping Ghostscript -sDEVICE= names to dictionaries mapping
    # PDF object numbers to PdfObj instances.
    device_image_objs = {'png16m': {}, 'pnggray': {}, 'pngmono': {}}
    image_count = 0
    image_total_size = 0
    for obj_num in sorted(self.objs):
      obj = self.objs[obj_num]
      # !! proper PDF object parsing, everywhere
      if (not re.search(r'/Subtype\s*/Image\b', obj.head) or
          not obj.stream is not None): continue
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

      if obj.Get('ImageMask'):
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
      # !! proper PDF object parsing
      if '(' not in colorspace and '<' not in colorspace:
        # TODO(pts): Inline this to reduce PDF size.
        # pdftex emits: /ColorSpace [/Indexed /DeviceRGB <n> <obj_num> 0 R] 
        colorspace2 = re.sub(
            r'\b(\d+)\s+0\s+R\b',
            (lambda match:
             PdfObj.EscapeString(self.objs[int(match.group(1))].GetDecompressedStream())),
            colorspace)
        if colorspace2 != colorspace:
          colorspace = colorspace2
          obj = PdfObj(obj)
          obj.Set('ColorSpace', colorspace)
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

      width = obj.Get('Width')
      assert isinstance(width, int)
      assert width > 0
      height = obj.Get('Height')
      assert isinstance(height, int)
      assert height > 0

      if not PdfObj.IsGrayColorSpace(colorspace):
        gs_device = 'png16m'
      elif bpc > 1 or colorspace != '/DeviceGray':
        gs_device = 'pnggray'
      else:
        gs_device = 'pngmono'

      image_count += 1
      image_total_size += obj.size
      # TODO(pts): More accurate /DecodeParms reporting (remove if no
      # predictor).
      print >>sys.stderr, (
          'info: will optimize image XObject %s; orig width=%s height=%s '
          'colorspace=%s bpc=%s filter=%s dp=%s size=%s gs_device=%s' %
          (obj_num, obj.Get('Width'), obj.Get('Height'),
           colorspace_short, bpc, obj.Get('Filter'),
           int(bool(obj.Get('DecodeParms'))), obj.size, gs_device))
      device_image_objs[gs_device][obj_num] = obj
    if not image_count: return self # No images => no conversion.
    print >>sys.stderr, 'info: optimizing %s images of %s bytes in total' % (
        image_count, image_total_size)

    # !! try to convert some images to unoptimized PNG without Ghostscript,
    #    e.g.  uncompressed, /FlateDecode without predictor or with the
    #    appropriate PNG predictor
    rendered_images = {}
    for gs_device in sorted(device_image_objs):
      ps_tmp_file_name = 'type1cconv.%s.tmp.ps' % gs_device
      objs = device_image_objs[gs_device]
      if objs:
        rendered_images.update(self.RenderImages(
            objs=objs, ps_tmp_file_name=ps_tmp_file_name, gs_device=gs_device,
            png_tmp_file_pattern='type1cconv-%%04d.%s.tmp.png' % gs_device))
        os.remove(ps_tmp_file_name)

    # !! shortcut for sam2p (don't need pngtopnm)
    #    (add basic support for reading PNG to sam2p? -- just what GS produces)
    #    (or just add .gz support?)
    images = {}
    for obj_num in sorted(rendered_images):
      rendered_image_file_name = rendered_images[obj_num]
      # !! TODO(pts): Don't load all images to memory (maximum 2).
      images[obj_num] = obj_images = []
      # TODO(pts): use KZIP or something to further optimize the ZIP stream
      obj_images.append(ImageData().Load(rendered_image_file_name))
      obj_images.append(self.ConvertImage(
          sourcefn=rendered_image_file_name,
          targetfn='type1cconv-%d.sam2p-np.pdf' % obj_num,
          # We specify -s here to explicitly exclue SF_Opaque for single-color
          # images.
          # !! do we need /ImageMask parsing if we exclude SF_Mask here as well?
          # Original sam2p order: Opaque:Transparent:Gray1:Indexed1:Mask:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:Transparent2:Transparent4:Transparent8
          # !! reintroduce Opaque by hand (combine /FlateEncode and /RLEEncode; or /FlateEncode twice (!) to reduce zeroes in empty_page.pdf from !)
          cmd_pattern='sam2p -pdf:2 -c zip:1:9 -s Gray1:Indexed1:Gray2:Indexed2:Rgb1:Gray4:Indexed4:Rgb2:Gray8:Indexed8:Rgb4:Rgb8:stop -- %(sourcefnq)s %(targetfnq)s',
          cmd_name='sam2p_nopredictor_cmd'))
      obj_images.append(self.ConvertImage(
          sourcefn=rendered_image_file_name,
          targetfn='type1cconv-%d.sam2p-pr.png' % obj_num,
          cmd_pattern='sam2p -c zip:15:9 -- %(sourcefnq)s %(targetfnq)s',
          cmd_name='sam2p_predictor_cmd'))
      if (use_jbig2 and obj_images[-1].bpc == 1 and
          obj_images[-1].color_type in ('gray', 'indexed-rgb')):
        # !! autoconvert 1-bit indexed PNG to gray
        obj_images.append(ImageData(obj_images[-1]))
        if obj_images[-1].color_type != 'gray':
          # This changes obj_images[-1].file_name as well.
          obj_images[-1].SavePng(file_name='type1cconv-%d.gray.png' % obj_num,
                                 do_force_gray=True)
        obj_images[-1].idat = self.ConvertImage(
            sourcefn=obj_images[-1].file_name,
            targetfn='type1cconv-%d.jbig2' % obj_num,
            cmd_pattern='jbig2 -p %(sourcefnq)s >%(targetfnq)s',
            cmd_name='jbig2', do_just_read=True)
        obj_images[-1].compression = 'jbig2'
        obj_images[-1].file_name = 'type1cconv-%d.jbig2' % obj_num
      # !! add /FlateEncode to all obj_images to find the smallest
      #    (maybe to UpdatePdfObj)
      # !! rename type1cconv and .type1c in temporary filenames
      # !! TODO(pts): Find better pngout binary file name.
      # TODO(pts): Try optipng as well (-o5?)
      if use_pngout:
        images[obj_num].append(self.ConvertImage(
            sourcefn=rendered_image_file_name,
            targetfn='type1cconv-%d.pngout.png' % obj_num,
            cmd_pattern='pngout-linux-pentium4-static '
                        '%(sourcefnq)s %(targetfnq)s',
            cmd_name='pngout_cmd'))

    for obj_num in sorted(images):
      obj = self.objs[obj_num]
      # !! proper PDF object parsing
      obj.head = re.sub(
          r'(?sm)^/(\S+)[ \t]*<<(.*?)>>',
          lambda match: '/%s <<%s>>' % (match.group(1), match.group(2).strip().replace('\n', '')),
          obj.head)
      obj_infos = [(obj.size, 0, '', obj)]
      image_idx = 0
      for image_data in images[obj_num]:
        image_idx += 1
        new_obj = PdfObj(obj)
        if obj.Get('ImageMask') and not image_data.CanUpdateImageMask():
          if image_idx != 1:  # no warning for what was rendered by Ghostscript
            print >>sys.stderr, (
                'warning: skipping bpc=%s color_type=%s file_name=%r '
                'for image XObject %s because of source /ImageMask' %
                (image_data.bpc, image_data.color_type, image_data.file_name,
                 obj_num))
        else:
          image_data.UpdatePdfObj(new_obj)
          # !! cmd_name instead of len(obj_infos); also for 0 above
          obj_infos.append(
              [new_obj.size, len(obj_infos), image_data.file_name, new_obj])
      replacement_sizes = dict(
          [(obj_info[1], obj_info[0]) for obj_info in obj_infos[1:]])
      best_obj_info = min(obj_infos)  # Never empty.
      if best_obj_info[-1] is obj:
        print >>sys.stderr, (
            'info: keeping original image XObject %s, replacements too large (%r >= %s bytes)' %
            (obj_num, replacement_sizes, obj.size))
      else:
        print >>sys.stderr, (
            'info: optimized image XObject %s best_method=%s file_name=%s '
            'size=%s (%s)' %
            (obj_num, best_obj_info[1], best_obj_info[2],
             best_obj_info[0], FormatPercent(best_obj_info[0], obj.size))) 
        print >>sys.stderr, (
            'info: replacements are %r <= %s bytes' %
            (replacement_sizes, obj.size))
        self.objs[obj_num] = best_obj_info[-1]
    # !! unify identical images (don't even recompress them?)
    # !! compress PDF palette to a new object if appropriate
    # !! delete all optimized_image_file_name{}s
    # !! os.remove(images[obj_num][...]), also *.jbig2 and *.gray.png
    return self


def main(argv):
  # Find image converters in script dir first.
  os.environ['PATH'] = '%s:%s' % (
      os.path.dirname(os.path.abspath(argv[0])), os.getenv('PATH', ''))

  use_pngout = True
  use_jbig2 = True
  # TODO(pts): Don't allow long option prefixes, e.g. --use-pngo=foo
  opts, args = getopt.gnu_getopt(argv[1:], '+', [
      'use-pngout=', 'use-jbig2='])
  for key, value in opts:
    if key == '--use-pngout':
      # !! add =auto (detect binary on path)
      use_pngout = {'true': True, 'false': False}[value.lower()]
    if key == '--use-jbig2':
      # !! add =auto (detect binary on path)
      use_jbig2 = {'true': True, 'false': False}[value.lower()]
  if not args:
    print >>sys.stderr, 'error: missing filename in command-line\n'
    sys.exit(1)
  elif len(args) == 1:
    file_name = args[0]
    if file_name.endswith('.pdf'):
      output_file_name = file_name[:-4] + '.type1c.pdf'
    else:
      output_file_name = file_name + '.type1c.pdf'
  elif len(args) == 2:
    file_name = args[0]
    output_file_name = args[1]
  else:
    print >>sys.stderr, 'error: too many command-line args\n'
    sys.exit(1)

  (PdfData().Load(file_name)
   .ConvertType1FontsToType1C()
   .OptimizeImages(use_pngout=use_pngout, use_jbig2=use_jbig2)
   .Save(output_file_name))

if __name__ == '__main__':
  main(sys.argv)
