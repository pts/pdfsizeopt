"""CFF (Adobe Compact Font Format) reading and writing in pure Python.

CFF file format documentation:
http://www.adobe.com/devnet/font/pdfs/5176.CFF.pdf
"""

import re
import struct

from pdfsizeopt import float_util


try:
  from itertools import izip
except ImportError:
  def izip(*iterables):  # Fallback for pythonmu2.7-static.
    iterables = map(iter, iterables)
    while 1:
      result = tuple(it.next() for it in iterables)  # Raises StopIteration.
      if not result:
        break
      yield result


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
    '8': 8, '9': 9, '.': 10, '?': 13, '-': 14,
    'E': 11, 'e': 11, 'F': 12, 'f': 12}

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

# !! Asked on StackOverflow: https://stackoverflow.com/q/45781734/97248
# *  Which fields affect PDF rendering in CFF?
#    /ItalicAngle ??
#    /UnderlinePosition ??
#    /UnderlineThickness ??
#    /FontBBox ??
#    /BaseFontName ??
#    /BaseFontBlend ??
#    /Private.ForceBold ??
#    /Private.LanguageGroup ??
#    /Private.ExpansionFactor ??
#    /Private.initialRandomSeed ??
#    /Private.unknown12015 ??
#    /StrokeWidth
#    /PaintType
#    /CharstringType
#    /FontMatrix
#    /Encoding
#    /CharStrings
#    /Private.BlueValues
#    /Private.OtherBlues
#    /Private.FamilyBlues
#    /Private.FamilyOtherBlues
#    /Private.BlueScale
#    /Private.BlueShift
#    /Private.BlueFuzz
#    /Private.StdHW
#    /Private.StdVW
#    /Private.StemSnapH
#    /Private.StemSnapV
#    /Private.Subrs
#    /Private.GlobalSubrs
#    /Private.defaultWidthX
#    /Private.nominalWidthX
# *  Which fields don't affect PDF rendering in CFF?
#    /FontName
#    /PostScript.FSType
#    /PostScript.OrigFontType
#    /PostScript.OrigFontName
#    /PostScript.OrigFontStyle
#    /version
#    /Notice
#    /Copyright
#    /FullName
#    /FamilyName
#    /Weight
#    /isFixedPitch
#    /UniqueID
#    /XUID

CFF_TOP_OP_MAP = {
    # The x/y values indicate: out of the y parsable CFF fonts in the cff.pgs
    # corpus, x had this field explicitly specified.
    # 'FontName': 8958/8958 (mandatory); .
    # 'ParsedPostScript': 216/8958; .
    0: ('version', 's', None),  # 688/8958; FontInfo
    1: ('Notice', 's', None),  # 7919/8958; FontInfo
    12000: ('Copyright', 's', None),  # 524/8958; FontInfo
    2: ('FullName', 's', None),  # 7281/8958; FontInfo
    3: ('FamilyName', 's', None),  # 7588/8958; FontInfo
    4: ('Weight', 's', None),  # 1325/8958; FontInfo
    12001: ('isFixedPitch', 'b', False),  # 343/8958; FontInfo
    12002: ('ItalicAngle', 'n', 0),  # 254/8958; .; FontInfo
    12003: ('UnderlinePosition', 'n', -100),  # 6618/8958; FontInfo
    12004: ('UnderlineThickness', 'n', 50),  # 6618/8958; FontInfo
    12005: ('PaintType', 'i', 0),  # 37/8958; .
    12006: ('CharstringType', 'i', 2),  # 0/8958; .
    12007: ('FontMatrix', 'm', ('0.001', 0, 0, '0.001', 0, 0)),  # 410/8958; .
    13: ('UniqueID', 'i', None),  # 1694/8958; .
    5: ('FontBBox', 'x', (0, 0, 0, 0)),  # 8863/8958 (!! almost mandatory); .
    12008: ('StrokeWidth', 'n', 0),  # 147/8958; .
    14: ('XUID', 'o', None),  # 306/8958; . Array of integer of at least 1 element.
    15: ('charset', 'i', 0),  # 8940/8958; charset offset (0) or std
    16: ('Encoding', 'i', 0),  # 8300/8958; encoding offset (0) or std
    17: ('CharStrings', 'i', None),  # 8958/8958 (mandatory!!); CharStrings offset (0)
    18: ('Private', 'j', None),  # 8958/8958 (mandatory!!); integer+integer
    12021: ('PostScript', 's', None),  # 216/8958; (in fact 0, because all moved to ParsedPostScript) embedded PostScript language code
    12022: ('BaseFontName', 's', None),  # 1214/8958; added as needed by Adobe-based technology
    12023: ('BaseFontBlend', 'd', None),  # 17/8958; added as needed by Adobe-based technology
    12020: ('SyntheticBase', 'n', None),  # synthetic base font index (starts)
    12030: ('ROS', 'o', None),  # 0/8958; SID+SID+number --, Registry Ordering Supplement (starts)
    12031: ('CIDFontVersion', 'i', 0),  # 0/8958; .
    12032: ('CIDFontRevision', 'i', 0),  # 0/8958; .
    12033: ('CIDFontType', 'i', 0),  # 0/8958; .
    12034: ('CIDCount', 'i', 8720),  # 0/8958; .
    12035: ('UIDBase', 'i', None),  # 0/8958; .
    12036: ('FDArray', 'i', None),  # 0/8958; Font DICT (FD) INDEX offset (0)
    12037: ('FDSelect', 'i', None),  # 0/8958; FDSelect offset (0)
    12038: ('FDFontName', 's', None),  # 0/8958; FD FontName; 5176.CFF.pdf says FontName, but we reserve FontName for something else.
    12040: ('unknown12040', 'o', None),  # 0/8958; 'j' would also work. (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
    12041: ('unknown12041', 'o', None),  # 0/8958; 'i' would also work. (Google doesn't know, Ghostscript 9.18 gdevpsf2.c or zfont2.c doesn't know.)
}
"""Maps CFF top dict operator numbers to their names.

Values are: (op_name, op_type, op_default).
"""

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

CFF_TOP_SYNTHETIC_FONT_OPERATORS = (
    12020,  # SyntheticBase, number --, synthetic base font index (starts)
)
"""Contains CFF top dict operators for synthetic fonts."""

CFF_TOP_FONTINFO_KEYS = (
    'version',
    'Notice',
    'Copyright',
    'FullName',
    'FamilyName',
    'Weight',
    'isFixedPitch',
    'ItalicAngle',
    'UnderlinePosition',
    'UnderlineThickness')
"""List of CFF_TOP_OP_MAP operator names part of FontInfo."""

CFF_PRIVATE_OP_MAP = {
    # 'GlobalSubrs': 61/8958; .
    6: ('BlueValues', 'd', None),  # 7956/8958; .
    7: ('OtherBlues', 'd', None),  # 5271/8958; .
    8: ('FamilyBlues', 'd', None),  # 442/8958; .
    9: ('FamilyOtherBlues', 'd', None),  # 443/8958; .
    12009: ('BlueScale', 'n', '0.039625'),  # 5133/8958; .
    12010: ('BlueShift', 'n', 7),  # 1433/8958; .
    12011: ('BlueFuzz', 'n', 1),  # 877/8958; .
    10: ('StdHW', 'n', None),  # 7664/8958; .
    11: ('StdVW', 'n', None),  # 7758/8958; .
    12012: ('StemSnapH', 'd', None),  # 6455/8958; .
    12013: ('StemSnapV', 'd', None),  # 5577/8958; .
    12014: ('ForceBold', 'b', False),  # 943/8958; .
    12017: ('LanguageGroup', 'i', 0),  # 0/8958; .
    12018: ('ExpansionFactor', 'n', '.06'),  # 0/8958; .
    12019: ('initialRandomSeed', 'i', 0),  # 0/8958; .
    19: ('Subrs', 'i', None),  # 1347/8958; Offset (self) to local subrs.
    20: ('defaultWidthX', 'n', 0),  # 3307/8958; .
    21: ('nominalWidthX', 'n', 0),  # 3119/8958; .
    12015: ('unknown12015', 'n', None),  # 54/8958; Looks like a single number: .5, 0.5 or .569092.
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
      real_chars = ''.join(real_chars)
      if '?' in real_chars:
        raise ValueError('Unknown char in CFF real: %s' % real_chars)
      # if '.' not in real_chars and 'E' not in real_chars:
      #   raise ValueError('CFF real looks like an integer: %s' % real_chars)
      #
      # This happens in cff.pgs i=3310, i=8194, i=8195, i=8538, i=8539,
      # i=8540, i=8891, i=8892, i=8893, i=8894, i=8895 etc.
      #
      # ParseType1CFonts emits an integer in this case (even though
      # write===only emits 0.0 for a float 0).
      try:
        real_chars = float(real_chars)
      except ValueError:
        raise ValueError('Invalid CFF real: %s' % real_chars)
      real_chars = float_util.FormatFloatShort(real_chars, is_int_ok=False)
      operands.append(real_chars)
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
        try:
          operand = float(operand)
        except ValueError:
          raise ValueError('Invalid CFF float value to serialize: %r' % operand)

      if isinstance(operand, float):  # TODO(pts): Test this.
        # is_int_ok=True here, because many CFF fonts in cff.pgs are already
        # missing the '.' and 'e' in floating point literals.
        operand = float_util.FormatFloatShort(operand, is_int_ok=True)
        operand = operand.replace('e-', 'f')
        nibbles = map(CFF_REAL_CHARS_REV.__getitem__, operand)
        nibbles.append(0xf)
        if (len(nibbles) & 1) != 0:
          nibbles.append(0xf)
        output.append('\x1e')
        output.append(''.join(
            chr(nibbles[i] << 4 | nibbles[i + 1])
            for i in xrange(0, len(nibbles), 2)))
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
          tuple(izip(font_name_bufs, top_dict_bufs)),
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


def IsCffValueEqual(a, b):
  if a == b:
    return True
  elif isinstance(a, (list, tuple)):
    if not isinstance(b, (list, tuple)) or len(a) != len(b):
      return False
    for av, bv in izip(a, b):
      if not IsCffValueEqual(av, bv):
        return False
    return True
  elif isinstance(a, bool) or isinstance(b, bool):
    return False
  elif (isinstance(a, str) and isinstance(b, str) and
        (a.startswith('<') or b.startswith('<'))):
    return False
  elif (isinstance(a, (str, float, int, long)) and
        isinstance(b, (str, float, int, long))):
    # !!! '42.9139' vs '42.913898'
    return (float(a) - float(b)) < 1e-3  # !!! pGS has 0.04379, ParseCff1 has .043790001. for /Private.BlueScale in i=1.
    return float(a) == float(b)
  else:
    return False


CFF_TOP_OP_DEFAULTS = [
    (op_name, op_default)
    for op, (op_name, op_type, op_default) in
       sorted(CFF_TOP_OP_MAP.iteritems())
    if op_name not in ('charset', 'Encoding', 'CharStrings', 'Private') and
        op_default is not None]
del op, op_name, op_type, op_default

CFF_PRIVATE_OP_DEFAULTS = [
    (op_name, op_default)
    for op, (op_name, op_type, op_default) in
       sorted(CFF_PRIVATE_OP_MAP.iteritems())
    if op_name not in ('Subrs', 'GlobalSubrs') and op_default is not None]
del op, op_name, op_type, op_default


def RemoveCffDefaults(parsed_dict):
  """Returns a new parsed_dict dict with default values for fields removed."""
  if not isinstance(parsed_dict, dict):
    raise TypeError
  if not isinstance(parsed_dict.get('Private'), dict):
    raise TypeError
  if not isinstance(parsed_dict.get('CharStrings'), dict):
    raise TypeError
  if not isinstance(parsed_dict.get('Encoding'), list):
    raise TypeError
  parsed_dict2 = dict(parsed_dict)
  parsed_dict2.update(parsed_dict2.pop('FontInfo', {}))  # !!! not here
  parsed_dict2['CharStrings'] = dict(parsed_dict2['CharStrings'])
  # Don't remove, even though it has a default in CFF.
  parsed_dict2['Encoding'] = list(parsed_dict2['Encoding'])
  private2 = parsed_dict2['Private'] = dict(parsed_dict2['Private'])

  # !!!
  if isinstance(private2.get('StdHW'), list) and len(private2['StdHW']):  # !!! In pGS.
    private2['StdHW'] = private2['StdHW'][0]
  if isinstance(private2.get('StdVW'), list) and len(private2['StdVW']):  # !!! In pGS.
    private2['StdVW'] = private2['StdVW'][0]
  parsed_dict2.pop('FamilyName', None)  # !!! Missing from pGS.
  private2.pop('unknown12015', None)  # !!! Missing from pGS.
  parsed_dict2.pop('unknown12040', None)  # !!! Missing from pGS.
  parsed_dict2.pop('unknown12041', None)  # !!! Missing from pGS.
  #if parsed_dict2.get('Weight') == '<4d656469756d>':  # 'Medium'.  Default (?) in pGS i=25.
  #  del parsed_dict2['Weight']
  # i=66 pGS has /Weight <42656c7765> 'Belwe'.
  parsed_dict2.pop('Weight', None)  # !! Unreliable.

  if private2.get('Subrs'):
    if not isinstance(private2['Subrs'], list):
      raise TypeError
    private2['Subrs'] = list(private2['Subrs'])
  else:
    private2.pop('Subrs', None)
  if private2.get('GlobalSubrs'):
    if not isinstance(private2['GlobalSubrs'], list):
      raise TypeError
    private2['GlobalSubrs'] = list(private2['GlobalSubrs'])
  else:
    private2.pop('GlobalSubrs', None)
  if parsed_dict2.get('ParsedPostScript'):
    if not isinstance(parsed_dict2['ParsedPostScript'], dict):
      raise TypeError
    # TODO(pts): Do more copying if mutable values are possible.
    parsed_dict2['ParsedPostScript'] = dict(parsed_dict2['ParsedPostScript'])
  else:
    parsed_dict2.pop('ParsedPostScript', None)

  for op_name, op_default in CFF_TOP_OP_DEFAULTS:
    if op_name in parsed_dict2 and IsCffValueEqual(parsed_dict2[op_name], op_default):
      del parsed_dict2[op_name]
  for op_name, op_default in CFF_PRIVATE_OP_DEFAULTS:
    if op_name in private2 and IsCffValueEqual(private2[op_name], op_default):
      del private2[op_name]

  return parsed_dict2


def GetParsedCffDifferences(a, b):
  """Detects if two parsed CFF fonts are equivalent.

  CFF fonts differing only in default values are equivalent.

  Args:
    a: First parsed CFF font to compare, must be a dict. Typically it comes
        from ParseCff1 or ParseType1CFonts.
    b: Other parsed CFF font to compare, must be a dict.
  Returns:
    list of str describing the differences.
  """

  def NormalizeEncoding(encoding, charset_set):
    encoding = list(encoding)
    for i, glyph_name in enumerate(encoding):
      if glyph_name != '/.notdef' and glyph_name[1:] not in charset_set:
        encoding[i] = '/.notdef'
    return encoding

  def IsDictOptEqual(a, b):
    if a is None and b is None:
      return True
    if type(a) != dict or type(b) != dict:
      return false
    # !! Better compare floats etc.
    return sorted(a.iteritems()) == sorted(b.iteritems())

  diff = []
  if type(a.get('Private')) != dict or type(b.get('Private')) != dict:
    diff.append('/Private')
    return diff
  if a['CharStrings'] != b['CharStrings']:
    print a['CharStrings']
    print b['CharStrings']
    diff.append('/CharStrings')
  if a['Encoding'] != b['Encoding']:
    a_encoding = NormalizeEncoding(a['Encoding'], set(a['CharStrings']))
    b_encoding = NormalizeEncoding(b['Encoding'], set(b['CharStrings']))
    if a_encoding != b_encoding:
      print a_encoding
      print b_encoding
      diff.append('/Encoding')
  if a['FontName'] != b['FontName']:
    print a['FontName']
    print b['FontName']
    diff.append('/FontName')

  for op, (op_name, op_type, op_default) in sorted(CFF_TOP_OP_MAP.iteritems()):
    if op_name not in ('charset', 'Encoding', 'CharStrings', 'Private'):
      if not IsCffValueEqual(a.get(op_name), b.get(op_name)):
        print '-- /%s' % op_name
        print a.get(op_name)
        print b.get(op_name)
        diff.append('/%s' % op_name)
  for op, (op_name, op_type, op_default) in sorted(CFF_PRIVATE_OP_MAP.iteritems()):
    if op_name not in ('Subrs', 'GlobalSubrs'):
      if not IsCffValueEqual(a['Private'].get(op_name), b['Private'].get(op_name)):
        print '-- /Private.%s' % op_name
        print a['Private'].get(op_name)
        print b['Private'].get(op_name)
        diff.append('/Private.%s' % op_name)
  if a['Private'].get('Subrs') != b['Private'].get('Subrs'):
    print a['Private'].get('Subrs')
    print b['Private'].get('Subrs')
    diff.append('/Subrs')
  if a['Private'].get('GlobalSubrs') != b['Private'].get('GlobalSubrs'):
    print a['Private'].get('GlobalSubrs')
    print b['Private'].get('GlobalSubrs')
    diff.append('/GlobalSubrs')
  if not IsDictOptEqual(a['Private'].get('ParsedPostScript'), b['Private'].get('ParsedPostScript')):
    print a['Private'].get('ParsedPostScript')
    print b['Private'].get('ParsedPostScript')
    diff.append('/ParsedPostScript')
  # !! Compare all other fields as well.
  # !! Apply defaults to missing fields.
  return diff


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
        try:
          f = float(match.group(3))
        except ValueError:
          raise ValueError('Invalid PostScript number: %r' % match.group(3))
        yield float_util.FormatFloatShort(f, is_int_ok=False)
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


def ParseCffNumber(op, number):
  if isinstance(number, float):
    return float_util.FormatFloatShort(number, is_int_ok=False)
  elif isinstance(number, str):
    try:
      number = float(number)
    except ValueError:
      raise ValueError('Invalid CFF float value for op %d: %r' %
                       (op, number))
    return float_util.FormatFloatShort(number, is_int_ok=False)
  elif isinstance(number, (int, long)):
    return int(number)
  else:
    raise ValueError('Invalid CFF number value for op %d: %r' %
                     (op, number))


def CffStringToName(
    data, _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE=NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE):
  """Prepends '/', hex-escapes the rest."""
  if data == '.notdef':  # Intern it to optimize for memory.
    return '/.notdef'
  if _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE.search(data):
    data = _NAME_CHAR_TO_HEX_KEEP_ESCAPED_RE.sub(
        lambda match: '#%02X' % ord(match.group(0)), data)
  if data.startswith('/'):
    raise ValueError('CFF name string starts with /: %s' % data)
  return '/' + data


_CFF_EXPERT_CHARSET_SIDS = (
    0, 1, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 13, 14, 15, 99, 239,
    240, 241, 242, 243, 244, 245, 246, 247, 248, 27, 28, 249, 250, 251, 252,
    253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 109,
    110, 267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280,
    281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295,
    296, 297, 298, 299, 300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310,
    311, 312, 313, 314, 315, 316, 317, 318, 158, 155, 163, 319, 320, 321, 322,
    323, 324, 325, 326, 150, 164, 169, 327, 328, 329, 330, 331, 332, 333, 334,
    335, 336, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349,
    350, 351, 352, 353, 354, 355, 356, 357, 358, 359, 360, 361, 362, 363, 364,
    365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378)
# TODO(pts): Intern the strings generated, especially '.notdef', also below.
CFF_EXPERT_CHARSET = tuple(CffStringToName(CFF_STANDARD_STRINGS[i])
                           for i in _CFF_EXPERT_CHARSET_SIDS)

_CFF_EXPERT_SUBSET_CHARSET_SIDS = (
    0, 1, 231, 232, 235, 236, 237, 238, 13, 14, 15, 99, 239, 240, 241, 242, 243,
    244, 245, 246, 247, 248, 27, 28, 249, 250, 251, 253, 254, 255, 256, 257,
    258, 259, 260, 261, 262, 263, 264, 265, 266, 109, 110, 267, 268, 269, 270,
    272, 300, 301, 302, 305, 314, 315, 158, 155, 163, 320, 321, 322, 323, 324,
    325, 326, 150, 164, 169, 327, 328, 329, 330, 331, 332, 333, 334, 335, 336,
    337, 338, 339, 340, 341, 342, 343, 344, 345, 346)
CFF_EXPERT_SUBSET_CHARSET = tuple(CffStringToName(CFF_STANDARD_STRINGS[i])
                                  for i in _CFF_EXPERT_SUBSET_CHARSET_SIDS)


_CFF_ISO_ADOBE_CHARSET_SIDS = xrange(229)
CFF_ISO_ADOBE_CHARSET = tuple(CffStringToName(CFF_STANDARD_STRINGS[i])
                              for i in _CFF_ISO_ADOBE_CHARSET_SIDS)


def ParseCffCharset(charset_value, data, len_charstrings, cff_all_string_bufs):
  """Parses a CFF /charset array.

  Args:
    charset_value: a small int containing the standard charset index.
    data: str or data containing the /Encoding array as a prefix.
    len_charstrings: Number of elements in /CharStrings.
    cff_all_string_bufs: Sequence of buffer or str objects containing the
        standard and file-specific strings.
  Returns:
    A new list of name strings, each not starting with a '/', and
    not hex-escaped, starting with '.notdef'. The length is the same as
    len_charstrings.
  """
  if not isinstance(charset_value, (int, long)):
    raise TypeError
  if not isinstance(len_charstrings, int):
    raise TypeError
  if len_charstrings < 1:
    raise ValueError('No charstrings in CFF, missing /.notdef')
  if charset_value < 10:
    if charset_value == 0:  # 18/8958; ISOAdobe.
      charset = list(CFF_ISO_ADOBE_CHARSET)
    elif charset_value == 1:  # 3/8958; Expert.
      charset = list(CFF_EXPERT_CHARSET)
    elif charset_value == 2:  # 1/8958; ExpertSubset.
      charset = list(CFF_EXPERT_SUBSET_CHARSET)
    else:
      raise ValueError('Invalid small CFF /charset value: %d' % charset_value)
    if len(charset) < len_charstrings:
      raise ValueError('Standard CFF /charset too short.')
    return charset[:len_charstrings]
  if not data:
    raise ValueError('CFF /charset too short for format.')
  format = ord(data[0])
  charset = ['.notdef']
  if format == 0:  # 7920/8958; .
    if (len_charstrings << 1) - 1 > len(data):
      raise ValueError('CFF /charset too short for format 0.')
    charset.extend(str(cff_all_string_bufs[sid]) for sid in struct.unpack(
        '>%dH' % (len_charstrings - 1),
        buffer(data, 1, (len_charstrings - 1) << 1)))
  elif format == 1:  # 1007/8958; .
    i = 1
    while len(charset) < len_charstrings:
      if i + 3 > len(data):
        raise ValueError('CFF /charset too short for format 1.')
      first_sid, count1 = struct.unpack('>HB', buffer(data, i, 3))
      i += 3
      count = count1 + 1
      if len(charset) + count > len_charstrings:
        raise ValueError('CFF /charset format 1 contains a too long range.')
      charset.extend(str(cff_all_string_bufs[sid]) for sid in
                     xrange(first_sid, first_sid + count))
  elif format == 2:  # 9/8958; .
    i = 1
    while len(charset) < len_charstrings:
      if i + 4 > len(data):
        raise ValueError('CFF /charset too short for format 1.')
      first_sid, count1 = struct.unpack('>HH', buffer(data, i, 4))
      i += 4
      count = count1 + 1
      if len(charset) + count > len_charstrings:
        raise ValueError('CFF /charset format 1 contains a too long range.')
      charset.extend(str(cff_all_string_bufs[sid]) for sid in
                     xrange(first_sid, first_sid + count))
  else:
    raise ValueError('Invalid CFF /charset format: %d' % format)
  assert len(charset) == len_charstrings
  return map(CffStringToName, charset)


_CFF_STANDARD_ENCODING_SIDS = (
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
    36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54,
    55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73,
    74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92,
    93, 94, 95, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 96, 97, 98, 99, 100, 101, 102, 103,
    104, 105, 106, 107, 108, 109, 110, 0, 111, 112, 113, 114, 0, 115, 116, 117,
    118, 119, 120, 121, 122, 0, 123, 0, 124, 125, 126, 127, 128, 129, 130, 131,
    0, 132, 133, 0, 134, 135, 136, 137, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 138, 0, 139, 0, 0, 0, 0, 140, 141, 142, 143, 0, 0, 0, 0, 0, 144, 0,
    0, 0, 145, 0, 0, 146, 147, 148, 149, 0, 0, 0, 0)
CFF_STANDARD_ENCODING = tuple(CffStringToName(CFF_STANDARD_STRINGS[i])
                              for i in _CFF_STANDARD_ENCODING_SIDS)
assert len(CFF_STANDARD_ENCODING) == 256

_CFF_EXPERT_ENCODING_SIDS = (
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 1, 229, 230, 0, 231, 232, 233, 234, 235, 236, 237, 238,
    13, 14, 15, 99, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 27, 28,
    249, 250, 251, 252, 0, 253, 254, 255, 256, 257, 0, 0, 0, 258, 0, 0, 259,
    260, 261, 262, 0, 0, 263, 264, 265, 0, 266, 109, 110, 267, 268, 269, 0, 270,
    271, 272, 273, 274, 275, 276, 277, 278, 279, 280, 281, 282, 283, 284, 285,
    286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296, 297, 298, 299, 300,
    301, 302, 303, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 304, 305, 306, 0, 0, 307, 308,
    309, 310, 311, 0, 312, 0, 0, 313, 0, 0, 314, 315, 0, 0, 316, 317, 318, 0, 0,
    0, 158, 155, 163, 319, 320, 321, 322, 323, 324, 325, 0, 0, 326, 150, 164,
    169, 327, 328, 329, 330, 331, 332, 333, 334, 335, 336, 337, 338, 339, 340,
    341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355,
    356, 357, 358, 359, 360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370,
    371, 372, 373, 374, 375, 376, 377, 378)
CFF_EXPERT_ENCODING = tuple(CffStringToName(CFF_STANDARD_STRINGS[i])
                              for i in _CFF_EXPERT_ENCODING_SIDS)
assert len(CFF_EXPERT_ENCODING) == 256


def ParseCffEncoding(encoding_value, data, charset, cff_all_string_bufs):
  """Parses a CFF /Encoding array.

  Args:
    encoding_value: a small int containing the standard encoding index.
    data: str or data containing the /Encoding array as a prefix.
    charset: List of glyph names, e.g. '/exclam'.
    cff_all_string_bufs: Sequence of buffer or str objects containing the
        standard and file-specific strings.
  Returns:
    A list of 256 glyph name strings, each starting with a '/', and
    hex-escaped.
  """
  if not isinstance(encoding_value, (int, long)):
    raise TypeError
  _CffStringToName = CffStringToName
  if encoding_value < 10:
    if encoding_value == 0:  # 659/8958; StandardEncoding.
      encoding = list(CFF_STANDARD_ENCODING)
    elif encoding_value == 1:  # 25/8958; ExpertEncoding.
      encoding = list(CFF_EXPERT_ENCODING)
    else:
      raise ValueError('Invalid small CFF /Encoding value: %d' % encoding_value)
  else:
    if not data:
      raise ValueError('CFF /Encoding too short for format.')
    # 0: 7626/8958; .
    # 1: 402/8958; .
    # 128: 174/8958; .
    # 129: 22/8958; .
    format_hi = ord(data[0])
    has_supplement = bool(format_hi & 128)
    format = format_hi & 127
    i = 1
    if format == 0:  # 7800/8958; .
      if i >= len(data):
        raise ValueError('CFF /Encoding too short for format 0 code_count.')
      code_count = ord(data[i])
      i += 1
      if i + code_count > len(data):
        raise ValueError('CFF /Encoding too short for format 0 codes.')
      if code_count >= len(charset):
        raise ValueError(
            'CFF /Encoding with format 0 longer than /CharStrings.')
      encoding = ['/.notdef'] * 256
      for j, code in enumerate(struct.unpack(
          '>%dB' % code_count, buffer(data, i, code_count))):
        assert code < len(encoding)
        encoding[code] = charset[j + 1]
      i += code_count
    elif format == 1:  # 524/8958; .
      if i >= len(data):
        raise ValueError('CFF /Encoding too short for format 1 range_count.')
      range_count = ord(data[i])
      i += 1
      if i + (range_count << 1) > len(data):
        raise ValueError('CFF /Encoding too short for format 0 codes.')
      encoding = ['/.notdef'] * 256
      j = 1
      for _ in xrange(range_count):
        first_code, count1 = struct.unpack('>BB', buffer(data, i, 2))
        if j + count1 >= len(charset):
          raise ValueError(
              'CFF /Encoding with format 1 longer than /CharStrings.')
        i += 2
        for code in xrange(first_code, first_code + count1 + 1):
          encoding[code] = charset[j]
          j += 1
    else:
      raise ValueError('Invalid CFF /Encoding format: %d' % format)
    assert len(encoding) == 256
    if has_supplement:
      if i >= len(data):
        raise ValueError('CFF /Encoding too short for supplement length.')
      count = ord(data[i])
      i += 1
      if i + 3 * count > len(data):
        raise ValueError('CFF /Encoding too short for supplement.')
      for _ in xrange(count):
        code, sid = struct.unpack('>BH', buffer(data, i, 3))
        i += 3
        encoding[code] = _CffStringToName(str(cff_all_string_bufs[sid]))
  assert len(encoding) == 256
  charset_set = set(charset)
  for i, glyph_name in enumerate(encoding):
    if glyph_name != '/.notdef' and glyph_name not in charset_set:
      encoding[i] = '/.notdef'
  return encoding


def ParseCffOp(op, op_value, op_name, op_type, op_default):
  """Parses a single CFF operator value.

  Args:
    op: Operator number, key in the result of ParseCffDict.
    op_value; Value to parse, value in the result of ParseCffDict.
    op_name: Name of the dict entry, without the leading '/'.
    op_type: Expected type of the value:
      'd': delta
      'x': bbox: number+number+number+number
      'm': matrix: number+number+number+number+number+number
      'n': number  !! which number must be an integer?
      'i': integer
      'j': integer+integer
      'b': boolean
      's': SID  (Will fail with AssertionError.)
      'u': unknown  (Will fail with AssertionError.)
      'o': original  (Keep op_value.)
    op_default: Default value if entry missing. Unused here.
  Returns:
    The parsed value.
  Raises:
    ValueError: .
  """
  # !! Apply op_default somewhere.
  if op_type == 'd':  # A delta.
    assert op_default is None, repr(op_default)
    result = []
    prev_number = 0
    for number in op_value:
      if isinstance(number, float):
        prev_number += number
      elif isinstance(number, str):
        try:
          prev_number += float(number)
        except ValueError:
          raise ValueError('Invalid CFF float delta value for op %d: %r' %
                           (op, number))
      elif isinstance(number, (int, long)):
        prev_number += int(number)
      else:
        raise ValueError('Invalid CFF number delta value for op %d: %r' %
                         (op, number))
      if isinstance(prev_number, float):
        result.append(float_util.FormatFloatShort(prev_number, is_int_ok=False))
      else:  # prev_number is int or long.
        result.append(prev_number)
    return result
  elif op_type == 'n':  # A number.
    if len(op_value) != 1:
      raise ValueError('Invalid size for CFF number value for op %d: %d' %
                       (op, op_value))
    return ParseCffNumber(op, str(op_value[0]))
  elif op_type == 'x':  # A bbox.
    if len(op_value) != 4:
      raise ValueError('Invalid size for CFF bbox value for op %d: %d' %
                       (op, op_value))
    return [ParseCffNumber(op, number) for number in op_value]
  elif op_type == 'm':  # A matrix.
    if len(op_value) != 6:
      raise ValueError('Invalid size for CFF matrix value for op %d: %d' %
                       (op, op_value))
    return [ParseCffNumber(op, number) for number in op_value]
  elif op_type == 'i':  # An integer.
    if len(op_value) != 1:
      raise ValueError('Invalid size for CFF integer value for op %d: %d' %
                       (op, op_value))
    op_value = op_value[0]
    if not isinstance(op_value, (int, long)):
      raise ValueError('Invalid CFF integer value for op %d: %r' %
                       (op, op_value))
    return int(op_value)
  elif op_type == 'j':  # Two integers.
    if len(op_value) != 2:
      raise ValueError('Invalid size for CFF integer2 value for op %d: %d' %
                       (op, op_value))
    result = []
    for number in op_value:
      if not isinstance(number, (int, long)):
        raise ValueError('Invalid CFF integer value for op %d: %r' %
                         (op, number))
      result.append(int(number))
    return result
  elif op_type == 'b':  # A boolean.
    if len(op_value) != 1:
      raise ValueError('Invalid size for CFF boolean value for op %d: %d' %
                       (op, op_value))
    op_value = op_value[0]
    if op_value == 0:
      return False
    elif op_value == 1:
      return True
    else:
      raise ValueError('Invalid CFF boolean value for op %d: %r' %
                       (op, op_value))
  elif op_type == 'o':  # An original.
    assert op_default is None, repr(op_default)
    return list(op_value)  # Create a new list.
  else:
    assert 0, 'Unknown CFF op_type=%r op_value=%r' % (op_type, op_value)


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
    assert top_dict == top_dict2, (top_dict, top_dict2)
    del top_dict_ser, top_dict2
  # !! remove /BaseFontName and /BaseFontBlend? are they optional? Does cff.pgs have it?
  # !! font merge fail on GlobalSubrs, Subrs and defaultWidthX and nominalWidthX

  # Make it faster for the loops below.
  _CFF_STANDARD_STRINGS = CFF_STANDARD_STRINGS
  _CFF_TOP_CIDFONT_OPERATORS = CFF_TOP_CIDFONT_OPERATORS
  _CFF_TOP_SYNTHETIC_FONT_OPERATORS = CFF_TOP_SYNTHETIC_FONT_OPERATORS
  _CFF_TOP_OP_MAP = CFF_TOP_OP_MAP
  _CFF_PRIVATE_OP_MAP = CFF_PRIVATE_OP_MAP
  _ParseCffOp = ParseCffOp

  parsed_dict = {'FontName': CffStringToName(cff_font_name)}
  cff_all_string_bufs = list(_CFF_STANDARD_STRINGS)
  cff_all_string_bufs.extend(cff_string_bufs)
  string_index_limit = len(cff_all_string_bufs)
  del cff_string_bufs
  for op, op_value in sorted(top_dict.iteritems()):
    if op in _CFF_TOP_CIDFONT_OPERATORS:
      # First such operator must be /ROS in the top dict, but we don't care
      # about the order.
      #
      # Untested, the cff.pgs corpus doesn't have a CIDFont.
      raise CffUnsupportedError('CFF CIDFont not supported.')
    if op in _CFF_TOP_SYNTHETIC_FONT_OPERATORS:
      # First such operator must be /SyntheticBase in the top dict, but we
      # don't care about the order.
      #
      # The Top DICT may contain the following operators: FullName,
      # ItalicAngle, FontMatrix, SyntheticBase, and Encoding.
      #
      # Untested, the cff.pgs corpus doesn't have a synthetic font.
      raise CffUnsupportedError('CFF synthetic font not supported.')
    op_entry = _CFF_TOP_OP_MAP.get(op)
    if op_entry is None:
      raise ValueError('Unknown CFF top dict op: %d' % op)
    op_name = op_entry[0]
    if op_entry[1] == 's':  # SID.
      assert op_entry[2] is None  # op_default.
      if (len(op_value) != 1 or not isinstance(op_value[0], int) or
          op_value[0] <= 0):
        raise ValueError('Invalid SID value for CFF /%s: %r' %
                         (op_name, value))
      op_value = op_value[0]
      if op_value < string_index_limit:
        # TODO(pts): Deduplicate these values as both hex and regular strings.
        #            For hex only if used as hex in the end (not for glyph
        #            names.)
        #            Is it worth it?
        op_value = str(cff_all_string_bufs[op_value])
      else:
        raise ValueError('CFF string index value too large: %d' % op_value)
      parsed_dict[op_name] = '<%s>' % op_value.encode('hex')
    else:
      parsed_dict[op_name] = _ParseCffOp(op, op_value, *op_entry)
  del top_dict
  # !!! Move CFF_TOP_FONTINFO_KEYS to parsed_dict['FontInfo'].

  op_value = parsed_dict.get('Private')
  if op_value is None:
    raise ValueError('Missing /Private dict from CFF font.')
  private_size, private_ofs = op_value
  if not isinstance(private_size, int) or private_size < 0:
    raise ValueError('Invalid CFF /Private size.')
  parsed_private_dict = {}
  if private_size:
    if not (isinstance(private_ofs, int) and
            cff_rest2_ofs <= private_ofs < len(data)):
      raise ValueError('Invalid CFF /Private offset %d, expected at least %d.' %
                       (private_ofs, cff_rest2_ofs))
    private_dict = ParseCffDict(data, private_ofs, private_ofs + private_size)
    if is_careful:
      private_dict_ser = SerializeCffDict(private_dict)
      private_dict2 = ParseCffDict(private_dict_ser)
      assert private_dict == private_dict2, (private_dict, private_dict2)
      del private_dict_ser, private_dict2
    for op, op_value in sorted(private_dict.iteritems()):
      op_entry = _CFF_PRIVATE_OP_MAP.get(op)
      op_name = op_entry[0]
      if op_entry is None:
        raise ValueError('Unknown CFF private dict op: %d' % op)
      parsed_private_dict[op_name] = _ParseCffOp(op, op_value, *op_entry)
    del private_dict
    if 'Subrs' in parsed_private_dict:
      subrs_ofs = parsed_private_dict['Subrs'] + private_ofs
      if not (isinstance(subrs_ofs, int) and
              cff_rest2_ofs <= subrs_ofs < len(data)):
        raise ValueError(
            'Invalid CFF /Subrs offset %d, expected at least %d.' %
            (subrs_ofs, cff_rest2_ofs))
      _, subr_bufs = ParseCffIndex(buffer(data, subrs_ofs))
      op_value = ['<%s>' % str(buf).encode('hex') for buf in subr_bufs]
      del subr_bufs
      if op_value:
        # Ghostscript also puts /Subrs into /Private.
        #
        # Minimum /Subrs subr str length is 3 in cff.pgs.
        parsed_private_dict['Subrs'] = op_value
      else:
        del parsed_private_dict['Subrs']
  # Ghostscript also puts /GlobalSubrs into /Private.
  op_value = ['<%s>' % str(buf).encode('hex') for buf in cff_global_subr_bufs]
  if op_value:
    # Minimum /GlobalSubrs subr str length is 3 in cff.pgs.
    parsed_private_dict['GlobalSubrs'] = op_value
  parsed_dict['Private'] = parsed_private_dict

  op_value = parsed_dict.get('CharStrings')
  if op_value is None:
    raise ValueError('Missing /CharStrings index from CFF font.')
  charstrings_ofs = op_value
  if not (isinstance(charstrings_ofs, int) and
          cff_rest2_ofs <= charstrings_ofs < len(data)):
    raise ValueError(
        'Invalid CFF /CharStrings offset %d, expected at least %d.' %
        (charstrings_ofs, cff_rest2_ofs))
  _, charstring_bufs = ParseCffIndex(buffer(data, charstrings_ofs))
  if [1 for c in charstring_bufs if not c]:
    raise ValueError('Empty string found in CFF /CharStrings.')
  charset = parsed_dict.get('charset', 0)  # Default same as _CFF_TOP_OP_MAP.
  charset = ParseCffCharset(
      charset, buffer(data, charset), len(charstring_bufs), cff_all_string_bufs)
  parsed_dict['CharStrings'] = dict(izip(
      (glyph_name[1:] for glyph_name in charset),
      ('<%s>' % str(buf).encode('hex') for buf in charstring_bufs)))
  del charstring_bufs
  encoding = parsed_dict.get('Encoding', 0)  # Default same as _CFF_TOP_OP_MAP.
  parsed_dict['Encoding'] = ParseCffEncoding(
      encoding, buffer(data, encoding), charset, cff_all_string_bufs)

  if parsed_dict.get('PostScript'):
    # Statistics from the cff.pgs corpus (all tested in pdfsizeopt_test.py):
    #
    # * 'FSType': 215//8958; an integer (nonnegative, bit field).
    # * 'OrigFontType': 1/8958; a name literal or string (?).
    # * 'OrigFontName': 0/8958; a string.
    # * 'OrigFontStyle': 0//8958; a string.
    #
    # !! In general, these fields can be removed from an optimized CFF:
    #    /FSType, /OrigFontType, /OrigFontName, /OrigFontStyle.
    #    If not removed, at least merge them if they are the same.
    try:
      # Silently ignore parse errors in /PostScript.
      # !! Do the same parsing in main.ParseType1CFonts.
      parsed_ps = ParsePostScriptDefs(
          parsed_dict['PostScript'][1 : -1].decode('hex'))
    except ValueError:
      parsed_ps = ()
    if parsed_ps is not ():
      if parsed_ps:
        parsed_dict['ParsedPostScript'] = parsed_ps
      parsed_dict.pop('PostScript')

  # !! pdfsizeopt_test: fix CFF_FONT_PROGRAM, make it parseable; why?
  # !! Convert integer-valued op_value floats to int. Should we?
  # !! convert floats: 'BlueScale': ['.0526316'], to 0.0526316.
  # !! when serializing: /OtherBlues must occur right after /BlueValues
  # !! when serializing: /FamilyOtherBlues must occur right after /FamilyBlues
  # !!! why? pGS (ParseType1CFonts) emits /Weight as 'FamilyName', and doesn't emit /FamilyName. This is compensated in cff.pgs by renaming to 'Weight'.

  #print parsed_dict
  return parsed_dict
  # !! Add unit tests for code coverage on everything cff.pgs covers.
