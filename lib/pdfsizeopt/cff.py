"""CFF (Adobe Compact Font Format) reading and writing in pure Python.

CFF file format documentation:
http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
"""

import struct

CFF_REAL_CHARS = {
    0: '0', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7',
    8: '8', 9: '9', 10: '.', 11: 'E', 12: 'E-', 13: '?', 14: '-', 15: ''}

CFF_REAL_CHARS_REV = {
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
    '8': 8, '9': 9, '.': 10, 'E': 11, 'F': 12, '?': 13, '-': 14}

# The local subrs offset (19, Subrs) is relative to the
# beginning of the private dict data, so it's not offset (0).
CFF_OFFSET0_OPERATORS = (
    15,  # charset
    16,  # Encoding
    17,  # CharStrings
    18,  # Private (only last operand is offset)
    12036,  # FDArray
    12037,  # FDSelect
)
"""List of CFF DICT operators containing absolute offsets: offset (0).
"""


def ParseCffDict(data, start=0, end=None):
  """Parse CFF DICT data to a dict mapping operator to operand list.

  The format of the returned dict is the following. Keys are integers
  signifying operators (range 0..21 and 12000..12256). Values are arrays
  signifying operand lists. Each operand is an integer or a string of a
  floating point real number.

  Args:
    data: str or buffer.
    start: Start offset.
    end: End offset or None to mean end of data.
  """
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
      assert i < end  # TODO(pts): Raise proper exceptions here.
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
        real_chars.append(CFF_REAL_CHARS[b0 >> 4])
        real_chars.append(CFF_REAL_CHARS[b0 & 15])
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
      assert False, 'invalid CFF DICT operand/operator: %s' % b0

  return cff_dict


def SerializeCffDict(cff_dict):
  """Serialize a CFF DICT to a string. Inverse of ParseCffDict."""
  output = []
  for operator in sorted(cff_dict):
    for operand in cff_dict[operator]:
      if isinstance(operand, str):
        # TODO(pts): Test this.
        operand = operand.replace('E-', 'F')
        # TODO(pts): Raise proper exception instead of KeyError.
        nibbles = map(CFF_REAL_CHARS_REV.__getitem__, operand)
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
          output.append(
              '%c%c' %
              (((operand - 108) >> 8) + 247, (operand - 108) & 255))
          assert 247 <= ord(output[-1][0]) <= 250
        elif -1131 <= operand <= -108:
          output.append(
              '%c%c' %
              (((-operand - 108) >> 8) + 251, (-operand - 108) & 255))
          assert 251 <= ord(output[-1][0]) <= 254
        elif -32768 <= operand <= 32767:
          output.append(chr(28) + struct.pack('>H', operand & 0xffff))
        elif ~0x7fffffff <= operand <= 0x7fffffff:
          output.append(chr(29) + struct.pack('>L', operand & 0xffffffff))
        else:
          assert False, 'CFF DICT integer operand %r out of range' % operand
      else:
        assert False, 'invalid CFF DICT operand %r' % (operand,)
    if operator >= 12000:
      output.append('\014%c' % (operator - 12000))
    else:
      output.append(chr(operator))
  return ''.join(output)

def ParseCffIndex(data):
  """Parses a CFF index.

  A CFF index is just a fancy name for a list of byte strings.

  Args:
    data: str or buffer starting with the CFF index.
  Returns:
    (offset_after_the_cff_index, offset_of_item_0, list_of_buffers).
  """
  if len(data) < 3:
    raise ValueError('CFF index too short for header.')
  count, off_size = struct.unpack('>HB', buffer(data, 0, 3))
  if len(data) < 3 + (count + 1) * off_size:
    raise ValueError('CFF index too short for offsets.')
  if off_size == 1:
    offsets = struct.unpack('>%dB' % (count + 1), buffer(data, 3, count + 1))
    j = count + 3
  elif off_size == 2:
    offsets = struct.unpack('>%dH' % (count + 1),
                            buffer(data, 3, (count + 1) << 1))
    j = ((count + 1) << 1) + 2
  elif off_size == 3:
    j, offsets = 3, []
    for i in xrange(count + 1):
      a, b = struct.unpack('>BH', buffer(data, j, 3))
      offsets.append(a << 16 | b)
      j += 3
    j -= 1
  elif off_size == 4:
    offsets = struct.unpack('>%dL' % (count + 1),
                            buffer(data, 3, (count + 1) << 2))
    j = ((count + 1) << 2) + 2
  else:
    raise ValueError('CFF off_size not supported: %d' % off_size)
  if len(data) < j + offsets[count]:
    raise ValueError('CFF index too short for strings.')
  buffers = []
  for i in xrange(count):
    if not (1 <= offsets[i] <= offsets[i + 1]):
      raise ValueError('Invalid CFF index offset: %d' % offsets[i])
    buffers.append(buffer(data, j + offsets[i], offsets[i + 1] - offsets[i]))
  return j + offsets[count], j + offsets[0], buffers

def ParseCffHeader(data):
  """Parse the (single) font name and the top DICT of a CFF font."""
  ai0 = header_size = ord(data[2])  # Skip header.
  if header_size < 4:
    raise ValueError('CFF header too short, got: %d' % header_size)
  ai1, ai1i0, font_name_bufs = ParseCffIndex(buffer(data, ai0))
  if len(font_name_bufs) != 1:
    raise ValueError(
        'CFF name index count should be 1, got %d' % len(font_name_bufs))
  font_name = str(font_name_bufs[0])
  # It's OK to have long font names. 5176.CFF.pdf says that the maximum
  # ``should be'' 127.
  #
  # assert j - i < 255, 'font name %r... too long' % data[i : i + 20]
  #
  # TODO(pts): Check that fontname doesn't contain '[](){}<>/%\0 \t\r\n\f',
  #            5176.CFF.pdf says ``should not contain''.
  ai2, ai2i0, top_dict_bufs = ParseCffIndex(buffer(data, ai0 + ai1))
  if len(top_dict_bufs) != 1:
     raise ValueError(
         'CFF top dict index count should be 1, got %d' % len(top_dict_bufs))
  cff_rest_buf = buffer(data, ai0 + ai1 + ai2)
  ai3, ai3i0, cff_string_bufs = ParseCffIndex(cff_rest_buf)
  return (buffer(data, 0, ai0),  # CFF header.
          font_name,
          ai0 + ai1i0,
          top_dict_bufs[0],  # CFF top dict.
          cff_string_bufs,
          cff_rest_buf)

def SerializeCffIndexHeader(off_size, buffers):
  offsets = [1]
  for buf in buffers:
    offsets.append(offsets[-1] + len(buf))
  count = len(offsets) - 1
  if count >= 65535:
    raise ValueError('CFF index too long: %d' % count)
  largest_offset = offsets[-1]

  if off_size is None:
    if largest_offset < (1 << 8):
      off_size = 1
    elif largest_offset < (1 << 16):
      off_size = 2
    elif largest_offset < (1 << 24):
      off_size = 3
    elif largest_offset < (1 << 32):
      off_size = 4
    else:
      raise ValueError('CFF index too large: %d' % largest_offset)
    # This can be used here for testFixFontNameInCff to see whether
    # FixFontNameInCff converges with larger off_size values:
    #
    #   off_size = max(off_size, 2)
  elif off_size in (1, 2, 3, 4):
    if largest_offset >> (off_size * 8):
      raise ValueError('CFF index too large (%d) for off_size %d' %
                       (largest_offset, off_size))
  else:
    raise ValueError('Invalid off_size: %d' % off_size)

  if off_size == 1:
    data = struct.pack('>HB%dB' % len(offsets), count, 1, *offsets)
  elif off_size == 2:
    data = struct.pack('>HB%dH' % len(offsets), count, 2, *offsets)
  elif off_size == 3:
    def emit3():
      yield struct.pack('>HB', count, 3)
      for offset in offsets:
        yield struct.pack('>BH', offset >> 16, offset & 65535)
    data = ''.join(emit3())
  elif off_size == 4:
    data = struct.pack('>HB%dL' % len(offsets), count, 4, *offsets)
  else:
    raise ValueError

  return off_size, data


def FixFontNameInCff(data, new_font_name, len_deltas_out=None):
  """Returns the new CFF font program data."""
  (cff_header_buf, cff_font_name, cff_font_name_idx, cff_top_dict_buf,
   cff_string_bufs, cff_rest_buf) = ParseCffHeader(data)
  assert data[cff_font_name_idx : cff_font_name_idx + len(cff_font_name)] == cff_font_name

  if cff_font_name == new_font_name:
    return data
  len_delta = len(new_font_name) - len(cff_font_name)
  if len_delta == 0:
    return ''.join((
        data[:cff_font_name_idx], new_font_name,
        data[cff_font_name_idx + len(cff_font_name):]))
  old_rest_ofs = len(data) - len(cff_rest_buf)
  cff_dict = ParseCffDict(cff_top_dict_buf)
  # It doesn't matter how we set this as long as it's nonnegative. A value of
  # 0 or a very high (e.g. multi-billion) value would also work.
  estimated_rest_ofs = old_rest_ofs + len_delta
  for cff_operator in sorted(cff_dict):
    if cff_operator in CFF_OFFSET0_OPERATORS:
      # Except for cff_operator == 18.
      # assert len(cff_dict[cff_operator]) == 1,
      #     (cff_operator, len(cff_dict[cff_operator]))
      assert isinstance(cff_dict[cff_operator][-1], int)
      assert cff_dict[cff_operator][-1] >= old_rest_ofs
      # We need to modify the `offset (0)' fields, because old_rest_ofs is
      # changing to rest_ofs (which is not finalized yet).
      cff_dict[cff_operator][-1] += estimated_rest_ofs - old_rest_ofs
  off_size1, idxhdrfn = SerializeCffIndexHeader(None, [new_font_name])
  base_ofs = len(cff_header_buf) + len(idxhdrfn) + len(new_font_name)

  while 1:  # Compute rest_ofs iteratively.
    if len_deltas_out is not None:
      len_deltas_out.append(estimated_rest_ofs - old_rest_ofs)
    cff_dict_data = SerializeCffDict(cff_dict=cff_dict)
    off_size2, idxhdrtd = SerializeCffIndexHeader(None, [cff_dict_data])
    rest_ofs = base_ofs + len(idxhdrtd) + len(cff_dict_data)
    if rest_ofs == estimated_rest_ofs:
      break
    # `rest_ofs >= estimated_rest_ofs' is usually true, except if
    # estimated_rest_ofs was too high, because old_rest_ofs was too high,
    # probably because the input font had too large off_size values. We just
    # don't check it here:
    #
    #   assert rest_ofs >= estimated_rest_ofs
    for cff_operator in sorted(cff_dict):
      if cff_operator in CFF_OFFSET0_OPERATORS:
        cff_dict[cff_operator][-1] += rest_ofs - estimated_rest_ofs
    estimated_rest_ofs = rest_ofs

  cff_dict_parsed2 = ParseCffDict(data=cff_dict_data)
  assert cff_dict == cff_dict_parsed2, (
      'CFF dict serialize mismatch: new=%r parsed=%r' %
      (cff_dict, cff_dict_parsed2))
  return ''.join((str(cff_header_buf),  # CFF header.
                  idxhdrfn, new_font_name,  # CFF name index.
                  idxhdrtd, cff_dict_data,  # CFF top dict index.
                  str(cff_rest_buf)))
