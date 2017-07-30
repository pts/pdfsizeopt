"""CFF (Adobe Compact Font Format) reading and writing in pure Python.

CFF file format documentation:
http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
"""

import re
import struct

class Error(Exception):
  """Comon base class for exceptions defined in this module."""


class CffUnsupportedError(Exception):
  """Raised if a CFF font program contains a feature we don't support."""

CFF_NON_FONTNAME_CHARS = '/[]{}()<>%\0\t\n\r\f '
"""Characters that shouldn't be part of a CFF font name.

5176.CFF.pdf says ``should not contain''.
"""

CFF_NON_FONTNAME_CHAR_RE = re.compile('[%s]' % re.escape(
    CFF_NON_FONTNAME_CHARS))

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
"""Contains CFF top dict operators containing absolute offsets: offset (0)."""

CFF_CHARSTRINGS_OP = 17
CFF_PRIVATE_OP = 18
CFF_SUBRS_OP = 19

CFF_TOP_OP_MAP = {
    0: 'version',  # SID --, FontInfo
    1: 'Notice',  # SID --, FontInfo
    12000: 'Copyright',  # SID --, FontInfo
    2: 'FullName',  # SID --, FontInfo
    3: 'FamilyName',  # SID --, FontInfo
    4: 'Weight',  # SID --, FontInfo
    12001: 'isFixedPitch',  # boolean 0 (false), FontInfo
    12002: 'ItalicAngle',  # number 0, FontInfo
    12003: 'UnderlinePosition',  # number -100, FontInfo
    12004: 'UnderlineThickness',  # number 50, FontInfo
    12005: 'PaintType',  # number 0
    12006: 'CharstringType',  # number 2
    12007: 'FontMatrix',  # array 0.001 0 0 0.001 0 0
    13: 'UniqueID',  # number --
    5: 'FontBBox',  # array 0 0 0 0
    12008: 'StrokeWidth',  # number 0
    14: 'XUID',  # array --
    15: 'charset',  # number 0, charset offset (0)
    16: 'Encoding',  # number 0, encoding offset (0)
    17: 'CharStrings',  # number --, CharStrings offset (0)
    18: 'Private',  # number number --, Private DICT size and offset (0)
    12021: 'PostScript',  # SID --, embedded PostScript language code
    12022: 'BaseFontName',  # SID --, (added as needed by Adobe-based technology)
    12023: 'BaseFontBlend',  # delta --, (added as needed by Adobe-based technology)
    12020: 'SyntheticBase',  # number --, synthetic base font index (starts)
    12030: 'ROS',  # SID SID number --, Registry Ordering Supplement (starts)
    12031: 'CIDFontVersion',  # number 0
    12032: 'CIDFontRevision',  # number 0
    12033: 'CIDFontType',  # number 0
    12034: 'CIDCount',  # number 8720
    12035: 'UIDBase',  # number --
    12036: 'FDArray',  # number --, Font DICT (FD) INDEX offset (0)
    12037: 'FDSelect',  # number --, FDSelect offset (0)
    12038: 'FDFontName',  # SID --, FD FontName; 5176.CFF.pdf says FontName, but we reserve FontName for something else.
    12040: 'unknown12040',  # (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
    12041: 'unknown12041',  # (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
}
"""Maps CFF top dict operator numbers to their names."""

CFF_TOP_DELTA_OPERATORS = (
    12023,  # 'BaseFontBlend',  # delta --, (added as needed by Adobe-based technology)
)
"""Contains CFF top dict operators with delta values."""

CFF_TOP_CIDFONT_OPERATORS = (
    12030,  # ROS, SID SID number --, Registry Ordering Supplement (starts)
    12031,  # CIDFontVersion, number 0
    12032,  # CIDFontRevision, number 0
    12033,  # CIDFontType, number 0
    12034,  # CIDCount, number 8720
    12035,  # UIDBase, number --
    12036,  # FDArray, number --, Font DICT (FD) INDEX offset (0)
    12037,  # FDSelect, number --, FDSelect offset (0)
    12038,  # FontName, SID --, FD FontName
)
"""Contains CFF top dict operators for CIDFonts."""

CFF_TOP_SID_OPERATORS = (
    0,  # 'version',  # SID --, FontInfo
    1,  # 'Notice',  # SID --, FontInfo
    12000,  # 'Copyright',  # SID --, FontInfo
    2,  # 'FullName',  # SID --, FontInfo
    3,  # 'FamilyName',  # SID --, FontInfo
    4,  # 'Weight',  # SID --, FontInfo
    12021,  # 'PostScript',  # SID --, embedded PostScript language code
    12022,  # 'BaseFontName',  # SID --, (added as needed by Adobe-based technology)
    #12030,  # 'ROS',  # SID SID number --, Registry Ordering Supplement (starts)
    12038,  # 'FontName',  # SID --, FD FontName
)
"""Contains CFF top dict operators with a single string (SID) value."""


CFF_TOP_SYNTHETIC_FONT_OPERATORS = (
    12020,  # SyntheticBase, number --, synthetic base font index (starts)
)
"""Contains CFF top dict operators for synthetic fonts."""

CFF_TOP_WEIRD_OPERATORS = (
    12040,  # 'unknown12040',  # (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
    12041,  # 'unknown12041',  # (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
)
"""Contains CFF top dict operators found in the wild but unknown meaning."""

CFF_PRIVATE_OP_MAP = {
    6: 'BlueValues',  # delta --
    7: 'OtherBlues',  # delta --
    8: 'FamilyBlues',  # delta --
    9: 'FamilyOtherBlues',  # delta --
    12009: 'BlueScale',  # number 0.039625
    12010: 'BlueShift',  # number 7
    12011: 'BlueFuzz',  # number 1
    10: 'StdHW',  # number --
    11: 'StdVW',  # number --
    12012: 'StemSnapH',  # delta --
    12013: 'StemSnapV',  # delta --
    12014: 'ForceBold',  # boolean false
    12017: 'LanguageGroup',  # number 0
    12018: 'ExpansionFactor',  # number 0.06
    12019: 'initialRandomSeed',  # number 0
    19: 'Subrs',  # number --, Offset (self) to local subrs
    20: 'defaultWidthX',  # number 0, see below
    21: 'nominalWidthX',  # number 0, see below
    12015: 'unknown12015',  # Looks like a single number: .5, 0.5 or .569092.
}
"""Maps CFF private dict operator numbers to their names."""

CFF_PRIVATE_DELTA_OPERATORS = (
    6,  # 'BlueValues',  # delta --
    7,  # 'OtherBlues',  # delta --
    8,  # 'FamilyBlues',  # delta --
    9,  # 'FamilyOtherBlues',  # delta --
    12012,  # 'StemSnapH',  # delta --
    12013,  # 'StemSnapV',  # delta --
)
"""Contains CFF private dict operators with delta values."""

CFF_STANDARD_STRINGS = (  # 391 strings.
    '.notdef', 'space', 'exclam', 'quotedbl', 'numbersign', 'dollar',
    'percent', 'ampersand', 'quoteright', 'parenleft', 'parenright',
    'asterisk', 'plus', 'comma', 'hyphen', 'period', 'slash', 'zero', 'one',
    'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'colon', 'semicolon', 'less', 'equal', 'greater', 'question', 'at', 'A',
    'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O',
    'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'bracketleft',
    'backslash', 'bracketright', 'asciicircum', 'underscore', 'quoteleft',
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n',
    'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', 'braceleft',
    'bar', 'braceright', 'asciitilde', 'exclamdown', 'cent', 'sterling',
    'fraction', 'yen', 'florin', 'section', 'currency', 'quotesingle',
    'quotedblleft', 'guillemotleft', 'guilsinglleft', 'guilsinglright',
    'fi', 'fl', 'endash', 'dagger', 'daggerdbl', 'periodcentered',
    'paragraph', 'bullet', 'quotesinglbase', 'quotedblbase',
    'quotedblright', 'guillemotright', 'ellipsis', 'perthousand',
    'questiondown', 'grave', 'acute', 'circumflex', 'tilde', 'macron',
    'breve', 'dotaccent', 'dieresis', 'ring', 'cedilla', 'hungarumlaut',
    'ogonek', 'caron', 'emdash', 'AE', 'ordfeminine', 'Lslash', 'Oslash',
    'OE', 'ordmasculine', 'ae', 'dotlessi', 'lslash', 'oslash', 'oe',
    'germandbls', 'onesuperior', 'logicalnot', 'mu', 'trademark', 'Eth',
    'onehalf', 'plusminus', 'Thorn', 'onequarter', 'divide', 'brokenbar',
    'degree', 'thorn', 'threequarters', 'twosuperior', 'registered',
    'minus', 'eth', 'multiply', 'threesuperior', 'copyright', 'Aacute',
    'Acircumflex', 'Adieresis', 'Agrave', 'Aring', 'Atilde', 'Ccedilla',
    'Eacute', 'Ecircumflex', 'Edieresis', 'Egrave', 'Iacute', 'Icircumflex',
    'Idieresis', 'Igrave', 'Ntilde', 'Oacute', 'Ocircumflex', 'Odieresis',
    'Ograve', 'Otilde', 'Scaron', 'Uacute', 'Ucircumflex', 'Udieresis',
    'Ugrave', 'Yacute', 'Ydieresis', 'Zcaron', 'aacute', 'acircumflex',
    'adieresis', 'agrave', 'aring', 'atilde', 'ccedilla', 'eacute',
    'ecircumflex', 'edieresis', 'egrave', 'iacute', 'icircumflex',
    'idieresis', 'igrave', 'ntilde', 'oacute', 'ocircumflex', 'odieresis',
    'ograve', 'otilde', 'scaron', 'uacute', 'ucircumflex', 'udieresis',
    'ugrave', 'yacute', 'ydieresis', 'zcaron', 'exclamsmall',
    'Hungarumlautsmall', 'dollaroldstyle', 'dollarsuperior',
    'ampersandsmall', 'Acutesmall', 'parenleftsuperior',
    'parenrightsuperior', 'twodotenleader', 'onedotenleader',
    'zerooldstyle', 'oneoldstyle', 'twooldstyle', 'threeoldstyle',
    'fouroldstyle', 'fiveoldstyle', 'sixoldstyle', 'sevenoldstyle',
    'eightoldstyle', 'nineoldstyle', 'commasuperior', 'threequartersemdash',
    'periodsuperior', 'questionsmall', 'asuperior', 'bsuperior',
    'centsuperior', 'dsuperior', 'esuperior', 'isuperior', 'lsuperior',
    'msuperior', 'nsuperior', 'osuperior', 'rsuperior', 'ssuperior',
    'tsuperior', 'ff', 'ffi', 'ffl', 'parenleftinferior',
    'parenrightinferior', 'Circumflexsmall', 'hyphensuperior', 'Gravesmall',
    'Asmall', 'Bsmall', 'Csmall', 'Dsmall', 'Esmall', 'Fsmall', 'Gsmall',
    'Hsmall', 'Ismall', 'Jsmall', 'Ksmall', 'Lsmall', 'Msmall', 'Nsmall',
    'Osmall', 'Psmall', 'Qsmall', 'Rsmall', 'Ssmall', 'Tsmall', 'Usmall',
    'Vsmall', 'Wsmall', 'Xsmall', 'Ysmall', 'Zsmall', 'colonmonetary',
    'onefitted', 'rupiah', 'Tildesmall', 'exclamdownsmall', 'centoldstyle',
    'Lslashsmall', 'Scaronsmall', 'Zcaronsmall', 'Dieresissmall',
    'Brevesmall', 'Caronsmall', 'Dotaccentsmall', 'Macronsmall',
    'figuredash', 'hypheninferior', 'Ogoneksmall', 'Ringsmall',
    'Cedillasmall', 'questiondownsmall', 'oneeighth', 'threeeighths',
    'fiveeighths', 'seveneighths', 'onethird', 'twothirds', 'zerosuperior',
    'foursuperior', 'fivesuperior', 'sixsuperior', 'sevensuperior',
    'eightsuperior', 'ninesuperior', 'zeroinferior', 'oneinferior',
    'twoinferior', 'threeinferior', 'fourinferior', 'fiveinferior',
    'sixinferior', 'seveninferior', 'eightinferior', 'nineinferior',
    'centinferior', 'dollarinferior', 'periodinferior', 'commainferior',
    'Agravesmall', 'Aacutesmall', 'Acircumflexsmall', 'Atildesmall',
    'Adieresissmall', 'Aringsmall', 'AEsmall', 'Ccedillasmall',
    'Egravesmall', 'Eacutesmall', 'Ecircumflexsmall', 'Edieresissmall',
    'Igravesmall', 'Iacutesmall', 'Icircumflexsmall', 'Idieresissmall',
    'Ethsmall', 'Ntildesmall', 'Ogravesmall', 'Oacutesmall',
    'Ocircumflexsmall', 'Otildesmall', 'Odieresissmall', 'OEsmall',
    'Oslashsmall', 'Ugravesmall', 'Uacutesmall', 'Ucircumflexsmall',
    'Udieresissmall', 'Yacutesmall', 'Thornsmall', 'Ydieresissmall',
    '001.000', '001.001', '001.002', '001.003', 'Black', 'Bold', 'Book',
    'Light', 'Medium', 'Regular', 'Roman', 'Semibold',
)
"""CFF standard strings."""

SIMPLE_POSTSCRIPT_TOKEN_RE = re.compile(
    r'(def)|'  # 1: def.
    r'(true|false|null)|'  # 2: Unique values.
    r'([-+]?(?:\d+(?:[.]\d*)?|[.]\d+)(?:[eE][+-]?\d+)?)|'  #  3: Decimal number literal.
    r'(/[^/\[\]{}()<>%\0\t\n\r\f ]+)|'  #  4. Name literal.
    r'\(([^\\()]*)\)|'  # 5. String literal (matches only a subset of strings).
    r'<([a-fA-F0-9\0\t\n\r\f ]*)>|'  # 6. Hex string literal.
    r'(%[^\r\n]*|[\0\t\n\r\f ]+)|'  #  7: Comment or whitespace.
    r'([-+_.a-zA-Z0-9]+)|'  # 8: Invalid ASCII command.
    r'([/(<])|' # 9: Invalid token.
    r'([^\0\t\n\r\f %])')  # 10: 1 character of anything else, invalid.
"""Matches a token of a simplified subset of PostScript."""

SIMPLE_POSTSCRIPT_UNIQUE_VALUES = {'true': True, 'false': False, 'null': None}
"""Maps string to Python representation of simple PostScript unique values."""

POSTSCRIPT_WHITESPACE_RE = re.compile('[\0\t\n\r\f ]+')
"""Matches 1 or more PostScript whitespace."""

NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE = re.compile(r'[^-+A-Za-z0-9_.]')
"""Matches a single character to be kept escaped internally to pdfsizeopt."""


def ParseCffDict(data, start=0, end=None):
  """Parses a CFF dict data to a dict mapping operator to operand list.

  The format of the returned dict is the following. Keys are integers
  signifying operators (range 0..21 and 12000..12256). Values are arrays
  signifying operand lists. Each operand is an integer or a string of a
  floating point real number.

  Args:
    data: str or buffer.
    start: Start offset.
    end: End offset or None to mean end of data.
  """
  # TODO(pts): Take a buffer rather than start and end.
  cff_dict = {}
  if end is None:
    end = len(data)
  else:
    if end > len(data):
      raise ValueError('Too small dict end specified.')
  i = start
  operands = []
  while i < end:
    b0 = ord(data[i])
    i += 1
    if 32 <= b0 <= 246:
      operands.append(b0 - 139)
    elif 247 <= b0 <= 250:
      if i >= end:
        raise ValueError('Unexpected EOF in CFF dict t247.')
      b1 = ord(data[i])
      i += 1
      operands.append((b0 - 247) * 256 + b1 + 108)
    elif 251 <= b0 <= 254:
      if i >= end:
        raise ValueError('Unexpected EOF in CFF dict t251.')
      b1 = ord(data[i])
      i += 1
      operands.append(-(b0 - 251) * 256 - b1 - 108)
    elif b0 == 28:
      if i + 2 > end:
        raise ValueError('Unexpected EOF in CFF dict t28.')
      operands.append(ord(data[i]) << 8 | ord(data[i + 1]))
      i += 2
      if operands[-1] >= 0x8000:
        operands[-1] -= 0x10000
    elif b0 == 29:
      if i + 4 > end:
        raise ValueError('Unexpected EOF in CFF dict t29.')
      operands.append(ord(data[i]) << 24 | ord(data[i + 1]) << 16 |
                      ord(data[i + 2]) << 8 | ord(data[i + 3]))
      if operands[-1] >= 0x80000000:
        operands[-1] = int(operands[-1] & 0x100000000)
      i += 4
    elif b0 == 30:
      real_chars = []
      while 1:
        if i >= end:
          raise ValueError('Unexpected EOF in CFF dict t30.')
        b0 = ord(data[i])
        i += 1
        real_chars.append(CFF_REAL_CHARS[b0 >> 4])
        real_chars.append(CFF_REAL_CHARS[b0 & 15])
        if (b0 & 0xf) == 0xf:
          break
      operands.append(''.join(real_chars))
    elif 0 <= b0 <= 21:
      if b0 == 12:
        if i >= end:
          raise ValueError('Unexpected EOF in CFF dict t12.')
        b0 = 12000 + ord(data[i])
        i += 1
      # Possible b0 (operator) values here are: 0..11, 13..21,
      # 12000..12255.
      cff_dict[b0] = operands
      operands = []
    else:
      raise ValueError('Invalid CFF dict operand/operator type: %d' % b0)

  return cff_dict


def SerializeCffDict(cff_dict):
  """Serializes a CFF dict to a string. Inverse of ParseCffDict."""
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
        # This also covers bool (with False==0 and True==1). Good.

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
          raise ValueError(
              'CFF dict integer operand %r out of range.' % operand)
      else:
        raise ValueError('Invalid CFF dict operand type: %r' % type(operand))
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
    (offset_after_the_cff_index, list_of_buffers).
  """
  if data[:2] == '\0\0':  # Empty index. (No need to check len(data).)
    return 2, []
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
    # 5176.CFF.pdf requires 1, 2, 3 or 4.
    raise ValueError('Invalid CFF index off_size: %d' % off_size)
  if len(data) < j + offsets[count]:
    raise ValueError('CFF index too short for strings.')
  buffers = []
  for i in xrange(count):
    if not (1 <= offsets[i] <= offsets[i + 1]):
      raise ValueError('Invalid CFF index offset: %d' % offsets[i])
    buffers.append(buffer(data, j + offsets[i], offsets[i + 1] - offsets[i]))
  return j + offsets[count], buffers


def GetCffFontNameOfs(data):
  """Returns the offset in CFF data where the (first) font name starts.

  Error reporting in this function is sparse.

  Args:
    data: str or buffer containing a CFF font program.
  Returns:
    Offset of the first font name.
  """
  ai0 = ord(data[2])  # Skip header.
  count, off_size = struct.unpack('>HB', buffer(data, ai0, 3))
  ai3 = ai0 + 3
  if count <= 0:
    raise ValueError('Found count == 0.')
  if off_size == 1:
    return ai3 + count + struct.unpack('>B', buffer(data, ai3, 1))[0]
  elif off_size == 2:
    return ai3 + (count << 1) + 1 + struct.unpack('>H', buffer(data, ai3, 2))[0]
  elif off_size == 3:
    a, b = struct.unpack('>BH', buffer(data, ai3, 3))
    return ai3 + (count * 3) + 2 + (a << 16 | b)
  elif off_size == 4:
    return ai3 + (count << 2) + 3 + struct.unpack('>L', buffer(data, ai3, 4))[0]
  else:
    raise ValueError('Invalid CFF index off_size: %d' % off_size)


def ParseCffHeader(data, do_need_single_font=True, do_parse_rest=True):
  """Parse first font name, top dicts and string index of a CFF font."""
  if len(data) < 4:
    raise ValueError('CFF too short.')
  major, minor, hdr_size, cff_off_size = struct.unpack(
      '>BBBB', buffer(data, 0, 4))
  if not (1 <= cff_off_size <= 4):
    raise ValueError('Invalid CFF off_size: %d' % cff_off_size)
  if hdr_size < 4:
    raise ValueError('CFF header too short, got: %d' % header_size)
  ai1, font_name_bufs = ParseCffIndex(buffer(data, hdr_size))
  if not font_name_bufs:
    raise ValueError('CFF contains no fonts.')
  if len(font_name_bufs) != 1 and do_need_single_font:
    raise ValueError(
        'CFF name index count should be 1, got %d' % len(font_name_bufs))
  cff_font_name = str(font_name_bufs[0])
  if not cff_font_name:
    raise ValueError('Empty CFF font name.')
  ai2, top_dict_bufs = ParseCffIndex(buffer(data, hdr_size + ai1))
  if len(font_name_bufs) != len(top_dict_bufs):
     raise ValueError(
         'CFF font count mismatch: font_name=%d top_dict=%d' %
         (len(font_name_bufs), len(top_dict_bufs)))
  rest_ofs = hdr_size + ai1 + ai2
  cff_rest_buf = buffer(data, rest_ofs)
  if do_parse_rest:
    ai3, cff_string_bufs = ParseCffIndex(cff_rest_buf)
    ai4, cff_global_subr_bufs = ParseCffIndex(buffer(cff_rest_buf, ai3))
    cff_rest2_ofs = rest_ofs + ai3 + ai4
  else:
    cff_string_bufs = cff_global_subr_bufs = None
    cff_rest2_ofs = rest_ofs
  return ((major, minor),
          cff_font_name,
          tuple(zip(font_name_bufs, top_dict_bufs)),
          cff_string_bufs,
          cff_global_subr_bufs,
          cff_rest_buf,
          cff_off_size,
          cff_rest2_ofs)


def SerializeCffIndexHeader(off_size, buffers):
  """Returns (off_size, serialized_cff_index_header)."""
  offsets = [1]
  for buf in buffers:
    offsets.append(offsets[-1] + len(buf))
  count = len(offsets) - 1
  if count >= 65535:
    raise ValueError('CFF index too long: %d' % count)
  largest_offset = offsets[-1]

  if off_size is None:
    if len(offsets) == 1:  # Empty index.
      off_size = 0
    elif largest_offset < (1 << 8):
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
  elif off_size in (0, 1, 2, 3, 4):
    if largest_offset >> (off_size * 8) and len(offsets) > 1:
      raise ValueError('CFF index too large (%d) for off_size %d' %
                       (largest_offset, off_size))
  else:
    raise ValueError('Invalid off_size: %d' % off_size)

  if off_size == 0:
    assert len(offsets) == 1  # Empty index, guaranteed above.
    data = '\0\0'
  elif off_size == 1:
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
    raise ValueError('Unexpected CFF off_size: %d' % off_size)

  return off_size, data


def FixFontNameInCff(data, new_font_name, len_deltas_out=None):
  """Returns the new CFF font program data."""
  (cff_version, cff_font_name, cff_font_items, cff_string_bufs,
   cff_global_subr_bufs, cff_rest_buf, cff_off_size, cff_rest2_ofs,
  ) = ParseCffHeader(data, do_need_single_font=True, do_parse_rest=False)
  cff_header_buf = data[:ord(data[2])]
  cff_top_dict_buf = cff_font_items[0][1]

  if cff_font_name == new_font_name:
    return data
  len_delta = len(new_font_name) - len(cff_font_name)
  if len_delta == 0:
    cff_font_name_ofs = GetCffFontNameOfs(data)
    assert data[cff_font_name_ofs : cff_font_name_ofs + len(cff_font_name)] == (
        cff_font_name)  # Guaranteed by GetCffFontNameOfs.
    return ''.join((
        data[:cff_font_name_ofs], new_font_name,
        data[cff_font_name_ofs + len(cff_font_name):]))
  old_rest_ofs = len(data) - len(cff_rest_buf)
  top_dict = ParseCffDict(cff_top_dict_buf)
  # It doesn't matter how we set this as long as it's nonnegative. A value of
  # 0 or a very high (e.g. multi-billion) value would also work.
  estimated_rest_ofs = old_rest_ofs + len_delta
  for op in sorted(top_dict):
    if op in CFF_OFFSET0_OPERATORS:
      # Except for op == 18, the number of operands are 1.
      assert isinstance(top_dict[op][-1], int)
      assert top_dict[op][-1] >= old_rest_ofs
      # We need to modify the `offset (0)' fields, because old_rest_ofs is
      # changing to rest_ofs (which is not finalized yet).
      top_dict[op][-1] += estimated_rest_ofs - old_rest_ofs
  off_size1, idxhdrfn = SerializeCffIndexHeader(None, (new_font_name,))
  base_ofs = len(cff_header_buf) + len(idxhdrfn) + len(new_font_name)

  while 1:  # Compute rest_ofs iteratively.
    if len_deltas_out is not None:
      len_deltas_out.append(estimated_rest_ofs - old_rest_ofs)
    top_dict_data = SerializeCffDict(cff_dict=top_dict)
    off_size2, idxhdrtd = SerializeCffIndexHeader(None, (top_dict_data,))
    rest_ofs = base_ofs + len(idxhdrtd) + len(top_dict_data)
    if rest_ofs == estimated_rest_ofs:
      break
    # `rest_ofs >= estimated_rest_ofs' is usually true, except if
    # estimated_rest_ofs was too high, because old_rest_ofs was too high,
    # probably because the input font had too large off_size values. We just
    # don't check it here:
    #
    #   assert rest_ofs >= estimated_rest_ofs
    for op in sorted(top_dict):
      if op in CFF_OFFSET0_OPERATORS:
        top_dict[op][-1] += rest_ofs - estimated_rest_ofs
    estimated_rest_ofs = rest_ofs

  top_dict_parsed2 = ParseCffDict(data=top_dict_data)
  assert top_dict == top_dict_parsed2, (
      'CFF dict serialize mismatch: new=%r parsed=%r' %
      (top_dict, top_dict_parsed2))
  return ''.join((str(cff_header_buf),  # CFF header.
                  idxhdrfn, new_font_name,  # CFF name index.
                  idxhdrtd, top_dict_data,  # CFF top dict index.
                  str(cff_rest_buf)))


def YieldParsePostScriptTokenList(data):
  """Returns a list of tokens, similar types as PdfObj token values."""
  scanner = SIMPLE_POSTSCRIPT_TOKEN_RE.scanner(data)
  _SIMPLE_POSTSCRIPT_UNIQUE_VALUES = SIMPLE_POSTSCRIPT_UNIQUE_VALUES
  _POSTSCRIPT_WHITESPACE_RE = POSTSCRIPT_WHITESPACE_RE
  _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE = NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE
  i, len_data, result = 0, len(data), []
  while i < len_data:
    match  = scanner.match()
    assert match, 'Unexpected char: %r' % data[i]
    i = match.end()
    if match.group(1):
      yield match.group(1)
    elif match.group(2):
      yield _SIMPLE_POSTSCRIPT_UNIQUE_VALUES[match.group(2)]
    elif match.group(3):
      try:
        yield int(match.group(3))
      except ValueError:
        # !! TODO(pts): Better than repr on float.
        try:
          yield repr(float(match.group(3)))
        except ValueError:
          raise ValueError('Invalid PostScript number: %r' % match.group(3))
    elif match.group(4):
      # PostScript supports the empty name literal (/), but we don't, because
      # it's hard to convert it to a PDF name, and then to omit the subsequent
      # whitespace.
      if _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE.search(match.group(4), 1):
        yield '/' + _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE.sub(
            lambda match: '#%02X' % ord(match.group(0)), match.group(4)[1:])
      else:
        yield match.group(4)
    elif match.group(5) is not None:
      yield '<%s>' % str(match.group(5)).encode('hex')
    elif match.group(6) is not None:
      value = _POSTSCRIPT_WHITESPACE_RE.sub('', match.group(6))
      if len(value) % 2:
        raise ValueError('Odd number of PostScript hex nibbles.')
      yield '<%s>' % value.lower()
      del value
    elif match.group(7):
      pass
    elif match.group(8):
      raise ValueError(
         'Invalid ASCII PostScript command: %r' % match.group(8))
    elif match.group(9):
      raise ValueError('Invalid PostScript token, starts with: %r' %
                       match.group(9))
    elif match.group(10):
      raise ValueError('Invalid PostScript char: %r' % match.group(10))
    else:
      assert 0, 'Unexpected token: %r' % match.group()


def ParsePostScriptDefs(data):
  """Returns a dict of tokens, similar types as PdfObj token values."""
  result = {}
  state, key, = 0, ''
  for token in YieldParsePostScriptTokenList(data):
    if state == 0:
      if not isinstance(token, str) or not token.startswith('/'):
        raise ValueError('Unexpected PostScript key: %r' % token)
      key, state = token[1:], 1
    elif state == 1:
      result[key], state = token, 2
    else:
      if token != 'def':
        raise ValueError('Expected def in PostScript, got: %r' % token)
      state = 0
  if state:
    raise ValueError('PostScript token list ended in the middle of def.')
  return result


def ParseCff1(data, is_careful=False):
  """Parses a CFF font program.

  Args:
    data: str or buffer containing the CFF font program.
    is_careful: bool indicating whether extra consistency checks should be done
        on the implementation. These are not input validation checks.
  Returns:
    dict (recursive) containing parsed CFF data. Similar to what
    ParseType1CFonts returns. (Eventually it should be exactly the same.)
  Raises:
    ValueError: If the font program contains an error (that could be detected),
        thus it's definitely invalid.
    CffUnsupportedError: If the font program uses a feature not supported by
        this parser.
  """
  (cff_version, cff_font_name, cff_font_items, cff_string_bufs,
   cff_global_subr_bufs, cff_rest_buf, cff_off_size, cff_rest2_ofs,
  ) = ParseCffHeader(data, do_need_single_font=False, do_parse_rest=True)
  if len(cff_font_items) != 1:
    raise CffUnsupportedError('CFF with multiple fonts not supported.')
  if cff_version != (1, 0):
    raise CffUnsupportedError('CFF version %d.%d not supported.' % cff_version)
  # It's OK to have long font names. 5176.CFF.pdf says that the maximum
  # ``should be'' 127, but we don't check it.
  if CFF_NON_FONTNAME_CHAR_RE.search(cff_font_name):
    raise ValueError('CFF font name %r contains invalid chars.' % font_name)
  cff_top_dict_buf = cff_font_items[0][1]
  top_dict = ParseCffDict(cff_top_dict_buf)
  if is_careful:
    top_dict_ser = SerializeCffDict(top_dict)
    top_dict2 = ParseCffDict(top_dict_ser)
    assert top_dict == top_dict2, (top_dict, top_dict_2)
    del top_dict_ser, top_dict2
  # !! remove /BaseFontName and /BaseFontBlend? are they optional? Does cff.pgs have it?
  # !! List operators missin from cff.pgs
  # !! font merge fail on GlobalSubrs, Subrs and defaultWidthX and nominalWidthX

  # Make it faster for the loops below.
  _CFF_STANDARD_STRINGS = CFF_STANDARD_STRINGS
  _CFF_TOP_CIDFONT_OPERATORS = CFF_TOP_CIDFONT_OPERATORS
  _CFF_TOP_SYNTHETIC_FONT_OPERATORS = CFF_TOP_SYNTHETIC_FONT_OPERATORS
  _CFF_TOP_WEIRD_OPERATORS = CFF_TOP_WEIRD_OPERATORS
  _CFF_TOP_OP_MAP = CFF_TOP_OP_MAP
  _CFF_TOP_SID_OPERATORS = CFF_TOP_SID_OPERATORS
  _CFF_PRIVATE_OP_MAP = CFF_PRIVATE_OP_MAP

  string_index_limit = len(cff_string_bufs) + len(_CFF_STANDARD_STRINGS)
  parsed_dict = {'FontName': '/' + cff_font_name}
  for op, op_value in sorted(top_dict.iteritems()):
    if op in _CFF_TOP_CIDFONT_OPERATORS:
      # First such operator must be /ROS in the top dict, but we don't care
      # about the order.
      raise CffUnsupportedError('CFF CIDFont not supported.')
    if op in _CFF_TOP_SYNTHETIC_FONT_OPERATORS:
      # First such operator must be /SyntheticBase in the top dict, but we
      # don't care about the order.
      #
      # The Top DICT may contain the following operators: FullName,
      # ItalicAngle, FontMatrix, SyntheticBase, and Encoding.
      raise CffUnsupportedError('CFF synthetic font not supported.')
    if op in _CFF_TOP_WEIRD_OPERATORS:
      raise CffUnsupportedError('Weird CFF operator not supported.')
    op_name = _CFF_TOP_OP_MAP.get(op)
    if op_name is None:
      raise ValueError('Unknown CFF top dict op: %d' % op)
    if op in _CFF_TOP_SID_OPERATORS:
      if (len(op_value) != 1 or not isinstance(op_value[0], int) or
          op_value[0] <= 0):
        raise ValueError('Invalid SID value for CFF /%s: %r' %
                         (op_name, value))
      op_value = op_value[0]  # !! Parse SID.
      if op_value < len(_CFF_STANDARD_STRINGS):
        op_value = _CFF_STANDARD_STRINGS[op_value]
      elif op_value < string_index_limit:
        # TODO(pts): Deduplicate these values as both hex and regular strings.
        #            Is it worth it?
        op_value = str(cff_string_bufs[op_value - len(_CFF_STANDARD_STRINGS)])
      else:
        raise ValueError('CFF string index value too large.')
      op_value = '<%s>' % op_value.encode('hex')
    parsed_dict[op_name] = op_value

  if CFF_PRIVATE_OP not in top_dict:
    raise ValueError('Missing /Private dict from CFF font.')
  if len(top_dict[CFF_PRIVATE_OP]) != 2:
    raise ValueError(
        'Invalid /Private dict op size in CFF font: %d' %
        len(top_dict[CFF_PRIVATE_OP]))
  private_size, private_ofs = top_dict[CFF_PRIVATE_OP]
  if not isinstance(private_size, int) or private_size < 0:
    raise ValueError('Invalid CFF /Private size.')
  parsed_private_dict = {}
  if private_size:
    if not (isinstance(private_ofs, int) and
            cff_rest2_ofs <= private_ofs < len(data)):
      raise ValueError('Invalid CFF /Private offset %d, expected at least %d.' %
                       (private_ofs, cff_rest2_ofs))
    private_dict = ParseCffDict(data, private_ofs, private_ofs + private_size)
    for op, op_value in sorted(private_dict.iteritems()):
      op_name = _CFF_PRIVATE_OP_MAP.get(op)
      if op_name is None:
        raise ValueError('Unknown CFF private dict op: %d' % op)
      parsed_private_dict[op_name] = op_value
    # !! decode numbers, deltas, etc.
    # !! Decode deltas (_CFF_PRIVATE_DELTA_OPERATORS).
    # !! how many fonts have 12015? 54 of 8961 in cff.pgs
    if CFF_SUBRS_OP in private_dict:
      if len(private_dict[CFF_SUBRS_OP]) != 1:
        raise ValueError(
            'Invalid /Subrs dict op size in CFF font: %d' %
            len(private_dict[CFF_SUBRS_OP]))
      subrs_ofs, = private_dict[CFF_SUBRS_OP]
      subrs_ofs += private_ofs
      if not (isinstance(subrs_ofs, int) and
              cff_rest2_ofs <= subrs_ofs < len(data)):
        raise ValueError(
            'Invalid CFF /Subrs offset %d, expected at least %d.' %
            (subrs_ofs, cff_rest2_ofs))
      _, subr_bufs = ParseCffIndex(buffer(data, subrs_ofs))
      # Ghostscript also puts /Subrs into /Private.
      parsed_private_dict['Subrs'] = [
          '<%s>' % str(buf).encode('hex') for buf in subr_bufs]
      del subr_bufs
  # Ghostscript also puts /GlobalSubrs into /Private.
  parsed_private_dict['GlobalSubrs'] = [
      '<%s>' % str(buf).encode('hex') for buf in cff_global_subr_bufs]
  parsed_dict['Private'] = parsed_private_dict

  if CFF_CHARSTRINGS_OP not in top_dict:
    raise ValueError('Missing /CharStrings index from CFF font.')
  if len(top_dict[CFF_CHARSTRINGS_OP]) != 1:
    raise ValueError(
        'Invalid /CharStrings dict op size in CFF font: %d' %
        len(top_dict[CFF_CHARSTRINGS_OP]))
  charstrings_ofs, = top_dict[CFF_CHARSTRINGS_OP]
  if not (isinstance(charstrings_ofs, int) and
          cff_rest2_ofs <= charstrings_ofs < len(data)):
    raise ValueError(
        'Invalid CFF /CharStrings offset %d, expected at least %d.' %
        (charstrings_ofs, cff_rest2_ofs))
  _, charstring_bufs = ParseCffIndex(buffer(data, charstrings_ofs))
  parsed_dict['CharStrings'] = [
      '<%s>' % str(buf).encode('hex') for buf in charstring_bufs]
  del charstring_bufs
  # !! convert from GID to glyph name

  if parsed_dict.get('PostScript'):  # !! catch ValueError
    #    !! In general, these fields can be removed from an optimized CFF:
    #       /FSType, /OrigFontType, /OrigFontName, /OrigFontStyle.
    #       If not removed, at least merge them if they are the same.
    try:
      # Silently ignore parse errors in /PostScript.
      # !! Do the same parsing in main.ParseType1CFonts.
      parsed_ps = ParsePostScriptDefs(
          parsed_dict['PostScript'][1 : -1].decode('hex'))
    except ValueError:
      parsed_ps = ()
    if parsed_ps is not ():
      parsed_dict['ParsedPostScript'] = parsed_ps
      parsed_dict.pop('PostScript')

  # !! test that glyph name /pedal.* is converted to /pedal.#2A
  #    apply the reverse of PdfToPsName in /Encoding etc.
  #    PdfObj.ParseValueRecursive
  # !! Decode deltas (_CFF_TOP_DELTA_OPERATORS).
  # !! Parse /Encoding.
  # !! Convert integer-valued op_value floats to int.
  # !! Parse everything.
  # !! convert floats: 'BlueScale': ['.0526316'], to 0.0526316.

  #print parsed_dict
  return parsed_dict
  # !! Add unit tests for code coverage on everything cff.pgs covers.
