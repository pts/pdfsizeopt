#! /usr/bin/python2.4
#
# type1cconv.py: convert Type1 fonts in a PDF to Type1C
# by pts@fazekas.hu at Sun Mar 29 13:42:05 CEST 2009
#
# TODO(pts): Proper whitespace parsing (as in PDF)
# TODO(pts): re.compile anywhere

import os
import os.path
import re
import sys
import time


def ShellQuote(string):
  # TODO(pts): Make it work on non-Unix systems.
  string = str(string)
  if string and not re.search('[^-_.+,:/a-zA-Z0-9]', string):
    return string
  else:
    return "'%s'" % string.replace("'", "'\\''")


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

class PDF(object):
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
  exch /Filter .knownget not {null} if
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
    pdf = PDF().Load(pdf_tmp_file_name)
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
        'info: reduced total Type1 font size %s to Type1C font size %s' %
        (type1_size, type1c_size))
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
      obj.head = (
          obj.head[:match.start(0)] +
          '/FontFile3 %d 0 R' % font_file_obj_num +
          obj.head[match.end(0):])
      self.objs[font_file_obj_num] = type1c_objs[obj_num]
      
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
  PDF().Load(file_name).ConvertType1FontsToType1C().Save(output_file_name)

if __name__ == '__main__':
  main(sys.argv)
