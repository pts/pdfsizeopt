#! /usr/bin/python2.4
#
# type1cconv.py: convert Type1 fonts in a PDF to Type1C
# by pts@fazekas.hu at Sun Mar 29 13:42:05 CEST 2009
#
# !! rename this file to get image conversion
# TODO(pts): Proper whitespace parsing (as in PDF)
# TODO(pts): re.compile anywhere

import os
import os.path
import re
import struct
import sys
import time


def ShellQuote(string):
  # TODO(pts): Make it work on non-Unix systems.
  string = str(string)
  if string and not re.search('[^-_.+,:/a-zA-Z0-9]', string):
    return string
  else:
    return "'%s'" % string.replace("'", "'\\''")

def FormatPercent(num, den):
  return '%d%%' % int((num * 100 + (den / 2)) // den)


class PDFObj(object):
  """Contents of a PDF object.

  Attributes:
    head: stripped string between `obj' and (`stream' or `endobj')
    stream: stripped string between `stream' and `endstream', or None
  """
  __slots__ = ['head', 'stream']

  def __init__(self, other, objs=None, file_ofs=0):
    """Initialize from other.

    If other is a PDFObj, copy everything. Otherwise, if other is a string,
    start parsing it from `X 0 obj' (ignoring the number) till endobj.

    Args:
      objs: A dictionary mapping obj numbers to existing PDFObj objects. These
        can be used for resolving `R's to build self.
    """
    if isinstance(other, PDFObj):
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

  def GetScalar(self, key):
    """!!Return int, long, bool, float, None; or str if it's a ref or more complicated."""
    # !! autoresolve refs
    # !! proper PDF object parsing
    i = self.head.find('\n/' + key + ' ')
    if i < 0: return None
    i += len(key) + 3
    j = self.head.find('\n', i)
    value = self.head[i : j].strip()
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
    assert self.head.endswith('\n>>')
    i = self.head.find('\n/' + key + ' ')
    if i < 0:
      if value is not None:
        self.head = '%s/%s %s\n>>' % (self.head[:-2], key, value)
    else:
      j = self.head.find('\n', i + len(key) + 3)
      self.head = self.head[:i] + self.head[j:]
      if value is not None:
        self.head = '%s/%s %s\n>>' % (self.head[:-2], key, value)


class PNGData(object):
  """Partial PNG image data, undecompressed by default.

  Attributes:
    width: in pixels
    height: in pixels
    bpc: bit depth, BitsPerComponent value (1, 2, 4, 8 or 16)
    color_type: 'gray', 'rgb', 'indexed-rgb', 'gray-alpha', 'rgb-alpha'
    is_interlaced: boolean
    idat: compressed binary string containing the image data (i.e. the
      IDAT chunk), or None
    plte: binary string (R0, G0, B0, R1, G1, B1) containing the PLTE chunk,
      or none

  TODO(pts): Make this a more generic image object; possibly store /Filter
    and predictor.
  """
  __slots__ = ['width', 'height', 'bpc', 'color_type', 'is_interlaced',
               'idat', 'plte']

  def __init__(self, other=None):
    """Initialize from other.

    Args:
      other: A PNGData object or none.
    """
    if other is not None:
      if not isinstance(other, PNGData): raise TypeError
      self.width = other.width
      self.height = other.height
      self.bpc = other.bpc
      self.color_type = other.color_type
      self.is_interlaced = other.is_interlaced
      self.idat = other.idat
      self.plte = other.plte
    else:
      self.Clear()

  def Clear(self):
    self.width = self.height = self.bpc = self.color_type = None
    self.is_interlaced = self.idat = self.plte = None

  def __nonzero__(self):
    """Return true iff this object contains a valid image."""
    return (self.width and self.height and self.bpc and self.color_type and
            self.is_interlaced is not None and self.idat and (
            not self.color_type.startswith('indexed-') or self.plte))

  def CanBePDFImage(self):
    return (self and self.bpc in (1, 2, 4, 8) and
            self.color_type in ('gray', 'rgb', 'indexed-rgb') and
            not self.is_interlaced)

  SAMPLES_PER_PIXEL_DICT = {
      'gray': 1,
      'rgb': 3,
      'indexed-rgb': 1,
      'gray-alpha': 2,
      'rgb-alpha': 4,
  }

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
      # TODO(pts): Use less parens if they are nested.
      palette_dump1 = '(%s)' % re.sub(r'([()\\])', r'\\\1', self.plte)
      palette_dump2 = '<%s>' % str(self.plte).encode('hex')
      if len(palette_dump1) < len(palette_dump2):
        palette_dump = palette_dump1
      else:
        palette_dump = palette_dump2
      return '[/Indexed/DeviceRGB %d%s]' % (
          len(self.plte) / 3 - 1, palette_dump)
    else:
      assert 0, 'cannot convert to PDF color space'

  def GetPDFImageData(self):
    """Return a dictinary useful as a PDF image."""
    assert self.CanBePDFImage()
    return {
        'Width': self.width,
        'Height': self.height,
        'BitsPerComponent': self.bpc,
        'Filter': '/FlateDecode',
        'DecodeParms':
            '<</BitsPerComponent %d/Columns %d/Colors %d/Predictor 10>>' %
            (self.bpc, self.width, self.samples_per_pixel),
        'ColorSpace': self.GetPDFColorSpace(),
        '.stream': self.idat,
    }

  def UpdatePDFObj(self, pdf_obj, do_check_dimensions=True):
    """Update the /Subtype/Image PDF XObject from self."""
    if not isinstance(pdf_obj, PDFObj): raise TypeError
    pdf_image_data = self.GetPDFImageData()
    # !! parse pdf_obj., implement PDFObj.Get (with references?), .Set with None
    if do_check_dimensions:
      assert pdf_obj.GetScalar('Width') == pdf_image_data['Width']
      assert pdf_obj.GetScalar('Height') == pdf_image_data['Height']
    else:
      pdf_obj.Set('Width', pdf_image_data['Width'])
      pdf_obj.Set('Height', pdf_image_data['Height'])
    if pdf_obj.GetScalar('ImageMask') is True:
      assert pdf_image_data['BitsPerComponent'] == 1
      assert pdf_image_data['ColorSpace'] == '/DeviceGray'
    else:
      pdf_obj.Set('BitsPerComponent', pdf_image_data['BitsPerComponent'])
      pdf_obj.Set('ColorSpace', pdf_image_data['ColorSpace'])
    pdf_obj.Set('Filter', pdf_image_data['Filter'])
    pdf_obj.Set('DecodeParms', pdf_image_data['DecodeParms'])
    pdf_obj.Set('Length', len(pdf_image_data['.stream']))
    # Don't pdf_obj.Set('Decode', ...): it is goot as is.
    pdf_obj.stream = pdf_image_data['.stream']

  COLOR_TYPE_PARSE_DICT = {
     0: 'gray',
     2: 'rgb',
     3: 'indexed-rgb',
     4: 'gray-alpha',
     6: 'rgb-alpha',
  }
  """Map a PNG color type byte value to a color_type string."""

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
    print >>sys.stderr, 'info: loading PNG from: %s' % (file_name,)
    f = open(file_name, 'rb')
    try:
      signature = f.read(8)
      assert signature == '\x89PNG\r\n\x1A\n', 'bad PNG signature in file'
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
          if chunk_type == 'IHDR':
            assert self.width is None, 'duplicate IHDR chunk'
            # struct.unpack checks for len(chunk_data) == 5
            (self.width, self.height, self.bpc, color_type, compression_method,
             filter_method, interlace_method) = struct.unpack(
                '>LL5B', chunk_data)
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
    finally:
      f.close()
    self.idat = ''.join(idats)
    assert not need_plte, 'missing PLTE chunk'
    if self.plte:
      print >>sys.stderr, (
          'info: loaded PNG IDAT of %s bytes and PLTE of %s bytes' %
          (len(self.idat), len(self.plte)))
    else:
      print >>sys.stderr, 'info: loaded PNG IDAT of %s bytes' % len(self.idat)
    assert self.idat, 'image data empty'
    return self


class PDFData(object):
  def __init__(self):
    # Maps an object number to a PDFObj
    self.objs = {}
    # Stripped string dict. Must contain /Size (max # objs) and /Root ref.
    self.trailer = '<<>>'
    # PDF version string.
    self.version = '1.0'

  def Load(self, file_name):
    """Load PDF from file_name to self, return self."""
    # TODO(pts): Use the xref table to find objs
    # TODO(pts): Don't load the whole file to memory.
    print >>sys.stderr, 'info: loading PDF from: %s' % (file_name,)
    f = open(file_name, 'rb')
    try:
      data = f.read()
    finally:
      f.close()
    print >>sys.stderr, 'info: loaded PDF of %s bytes' % len(data)
    match = re.match(r'^%PDF-(1[.]\d)\s', data)
    assert match
    version = match.group(1)
    self.objs = {}
    self.trialer = ''
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
        self.objs[obj_num] = PDFObj(obj_data[obj_num],
                                    file_ofs=obj_start[obj_num], )

    # Second pass once we have all length numbers.
    for obj_num in obj_data:
      if obj_num not in self.objs:
        self.objs[obj_num] = PDFObj(obj_data[obj_num], objs=self.objs,
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
      print >>sys.stderr, 'info: generated %s bytes' % GetOutputSize()

      # TODO(pts): Don't keep enverything in memory.
      f.write(''.join(output))
    finally:
      f.close()
    return self

  def GetFonts(self, font_type=None, do_obj_num_from_font_name=False):
    """Return dictionary containing Type1 /FontFile* objs.

    Args:
      font_type: 'Type1' or 'Type1C' or None
      obj_num_from_font_name: Get the obj_num (key in the returned dict) from
        the /FontName, e.g. /FontName/Obj42 --> 42.
    Returns:
      A dictionary mapping the obj number of the /Type/FontDescriptor obj to
      the PDFObj of the /FontFile* obj. Please note that this dictionary is not
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
    output.append(r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
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

/DecompressString {  % <compressed-string> <decompression-filter-or-null> DecompressString <decompressed-string>
  % Example <decompression-filter>: /FlateDecode
  % TODO: support decompression filter arrays, e.g. [/ASCIIHexDecode/FlateDecode]
  % TODO: support /DecodeParams
  dup null eq {pop} {
    filter
    dup 32768 string readstring {% !!
      {
        % stack: <filter> <partial-decompressed-string>
        2 copy length string readstring not {concatstrings exit}if
        concatstrings
      } loop
    } if
    % stack: <filter> <decompressed-string>
    exch closefile
  } ifelse
} bind def

/obj {  % <objnumber> <gennumber> obj -
  pop
  /_ObjNumber exch def
  % Imp: read <streamdict> here (not with `token', but recursively), so
  %      don't redefine `stream'
} bind def

/stream {  % <streamdict> stream -
  dup /Length get string currentfile exch readstring
  not{/invalidfileaccess /ReadStreamData signalerror}if
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
  % stack: <streamdict> <compressed-string>
  exch
  dup /DecodeParams .knownget not {null} if null ne {
    /ivalidfileaccess /DecodeParamsFound signalerror
  }if
  /Filter .knownget not {null} if
  % stack: <compressed-string> <decompression-filter-or-null>
  DecompressString
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  % stack: <decompressed-string> (containing a Type1 font program)
  % Without /ReusablestreamDecode here, ``currentfile eexec'' wouldn't work
  % in the font program, becasue currentfile wasn't the font program file
  /ReusableStreamDecode filter cvx
  9 dict begin dup mark exch exec cleartomark cleartomark closefile end
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
    (\n) print
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
} bind def
% </ProcSet>

''')
    output_prefix_len = sum(map(len, output))
    type1_size = 0
    for obj_num in sorted(objs):
      type1_size += objs[obj_num].size
      objs[obj_num].AppendTo(output, obj_num)
    output.append(r'(Type1CConverter: all OK\n) print')
    output_str = ''.join(output)
    print >>sys.stderr, ('info: writing Type1CConverter (%s font bytes) to: %s'
        % (len(output_str) - output_prefix_len, ps_tmp_file_name))
    f = open(ps_tmp_file_name, 'wb')
    try:
      f.write(output_str)
    finally:
      f.close()

    try:
      os.remove(pdf_tmp_file_name)
    except OSError:
      assert not os.path.exists(pdf_tmp_file_name)
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
      print >>sys.stderr, 'info: Ghostcript has not created output: ' % (
          pdf_tmp_file_name)
      assert 0, 'Type1CConverter failed (no output)'
    os.remove(ps_tmp_file_name)
    pdf = PDFData().Load(pdf_tmp_file_name)
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

  def ConvertType1FontsToType1C(self):
    """Convert all Type1 fonts to Type1C in self, returns self."""
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
            obj_num, font_file_obj_num, old_size, new_size)

    return self

  def OptimizeImages(self):
    """Optimize image XObjects in the PDF."""
    # !! implement according to the plan
    for obj_num in self.objs:
      obj = self.objs[obj_num]
      # !! proper PDF object parsing, everywhere
      if (re.search(r'/Subtype\s*/Image\b', obj.head) and
          obj.stream is not None):  # !! more checks
        # !! check type of Width, Height
        print >>sys.stderr, (
            'info: optimizing image XObject %s; orig width=%s height=%s '
            'filter=%s size=%s' %
            (obj_num, obj.GetScalar('Width'), obj.GetScalar('Height'),
             obj.GetScalar('Filter'), obj.size))
        print obj.head
        # !! proper PDF object parsing
        obj.head = re.sub(
            r'(?sm)^/(\S+)[ \t]*<<(.*?)>>',
            lambda match: '/%s <<%s>>' % (match.group(1), match.group(2).strip().replace('\n', '')),
            obj.head)
        # !! sam2p emits pts3.png as imagemask. Optimize that.
        new_obj = PDFObj(obj)
        PNGData().Load('pts2.png').UpdatePDFObj(new_obj)  # !! export PNG, load that file
        if new_obj.size < obj.size:
          print >>sys.stderr, (
              'info: optimized image filter=%s size=%s (%s)' %
              (new_obj.GetScalar('Filter'), new_obj.size,
               FormatPercent(new_obj.size, obj.size)))
          self.objs[obj_num] = new_obj
        else:
          print >>sys.stderr, (
              'info: keeping original, replacement too large (%s bytes)',
              new_obj.size)
    return self


def main(argv):
  if len(sys.argv) < 2:
    file_name = 'progalap_doku.pdf'
  else:
    file_name = sys.argv[1]
  if len(sys.argv) < 3:
    if file_name.endswith('.pdf'):
      output_file_name = file_name[:-4] + '.type1c.pdf'
    else:
      output_file_name = file_name + '.type1c.pdf'
  (PDFData().Load(file_name)
   .ConvertType1FontsToType1C()
   .OptimizeImages()
   .Save(output_file_name))

if __name__ == '__main__':
  main(sys.argv)
