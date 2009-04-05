#! /usr/bin/python2.4
#
# type1cconv.py: convert Type1 fonts in a PDF to Type1C
# by pts@fazekas.hu at Sun Mar 29 13:42:05 CEST 2009
#
# TODO(pts): Proper whitespace parsing (as in PDF)
# TODO(pts): re.compile anywhere

import re
import sys

class PDFObj(object):
  """Contents of a PDF object.
  
  Attributes:
    head: stripped string between `obj' and (`stream' or `endobj')
    stream: stripped string between `stream' and `endstream', or None
  """
  __slots__ = ['head', 'stream']

  def __init__(self, other):
    """Initialize from other.
    
    If other is a PDFObj, copy everything. Otherwise, if other is a string,
    start parsing it from `X 0 obj' (ignoring the number) till endobj.
    """
    if isinstance(other, PDFObj):
      self.head = other.head
      self.stream = other.stream
    elif isinstance(other, str):
      # !! what if endobj is part of a string in the obj? -- parse properly
      match = re.match(r'(?s)\d+\s+0\s+obj\s*', other)
      assert match
      skip_obj_number_idx = len(match.group(0))
      match = re.search(r'\b(stream\s|endobj(?:\s|\Z))', other)
      assert match
      self.head = other[skip_obj_number_idx : match.start(0)].rstrip()
      if match.group(1).startswith('endobj'):
        self.stream = None
        # Implicit \s here. TODO(pts): Do with less copy.
      else:  # has 'stream'
        # TODO(pts): Proper parsing.
        #print repr(self.head), repr(match.group(1))
        stream_start_idx = match.end(1)
        match = re.search(r'/Length\s+(\d+)', self.head)
        assert match
        stream_end_idx = stream_start_idx + int(match.group(1))
        endstream_str = other[stream_end_idx : stream_end_idx + 30]
        assert re.match(
            r'\s*endstream\s+endobj(?:\s|\Z)', endstream_str), (
            'expected endstream+endobj in %r at %s' %
            (endstream_str, stream_end_idx))
        self.stream = other[stream_start_idx : stream_end_idx]

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

    for match in re.finditer(r'\n(?:(\d+)\s+(\d+)\s+obj|trailer)\s', data):
      if prev_obj_num is not None:
        obj_data[prev_obj_num] = data[prev_obj_start_idx : match.start(0)]
      if match.group(1) is not None:
        prev_obj_num = int(match.group(1))
        assert 0 == int(match.group(2))
      else:
        prev_obj_num = 'trailer'
      prev_obj_start_idx = match.start(0) + 1  # Skip over '\n'
    if prev_obj_num is not None:
      obj_data[prev_obj_num] = data[prev_obj_start_idx : ]

    assert prev_obj_num == 'trailer'
    trailer_data = obj_data.pop('trailer')
    print >>sys.stderr, 'info: separated to %s objs' % len(obj_data)
    assert obj_data

    match = re.match('(?s)trailer\s+(<<.*?>>)\s*startxref\s', trailer_data)
    assert match
    self.trailer = match.group(1)

    for obj_num in obj_data:
      self.objs[obj_num] = PDFObj(obj_data[obj_num])
    
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
        obj = self.objs[obj_num]
        obj_ofs[obj_num] = GetOutputSize()
        output.append('%s 0 obj\n' % int(obj_num))
        output.append(obj.head.strip())  # Implicit \s .
        if obj.stream is not None:
          output.append('\nstream\n')
          output.append(obj.stream)
          output.append('\nendstream\nendobj\n')
        else:
          output.append('\nendobj\n')

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
      output.append('\nstartxref %s\n' % xref_ofs)
      output.append('%%EOF\n')
      print >>sys.stderr, 'info: generated %s bytes' % GetOutputSize()

      # TODO(pts): Don't keep enverything in memory.
      f.write(''.join(output))
    finally:
      f.close()

def main(argv):
  if len(sys.argv) < 2:
    file_name = 'progalap_doku.pdf'
  else:
    file_name = sys.argv[1]
  pdf = PDF().Load(file_name).Save('type1c.pdf')

if __name__ == '__main__':
  main(sys.argv)
