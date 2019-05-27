#! /bin/sh

""":" # pdfsizeopt_test: Tests for pdfsizeopt.

type -p python2.7 >/dev/null 2>&1 && exec python2.7 -- "$0" ${1+"$@"}
type -p python2.6 >/dev/null 2>&1 && exec python2.6 -- "$0" ${1+"$@"}
type -p python2.5 >/dev/null 2>&1 && exec python2.5 -- "$0" ${1+"$@"}
type -p python2.4 >/dev/null 2>&1 && exec python2.4 -- "$0" ${1+"$@"}
exec python -- "$0" ${1+"$@"}

This is a Python 2.x script, it works with Python 2.4, 2.5, 2.6 and 2.7. It
doesn't work with Python 3.x. Feel free to replace the #! line with
`#! /usr/bin/python', `#! /usr/bin/env python' or whatever suits you best.
"""

#
# pdfsizeopt_test.py: unit tests for pdfsizeopt.py
# by pts@fazekas.hu at Sun Apr 19 10:21:07 CEST 2009
#

__author__ = 'pts@fazekas.hu (Peter Szabo)'

# --- Setting up the import path.

import os
import os.path
import sys

if not ((2, 4) <= sys.version_info[:2] < (3, 0)):
  sys.stderr.write(
      'fatal: Python version 2.4, 2.5, 2.6 or 2.7 needed for: %s\n' % __file__)
  sys.exit(1)

if os.path.isfile(os.path.join(
    os.path.dirname(__file__), 'lib', 'pdfsizeopt', 'main.py')):
  sys.path[:0] = [os.path.join(os.path.dirname(__file__), 'lib')]

# ---

import sys
import zlib
import unittest

from pdfsizeopt import cff
from pdfsizeopt import float_util
from pdfsizeopt import main


class PdfSizeOptTest(unittest.TestCase):
  def assertRaisesX(self, exc_class, callable_obj, *args, **kwargs):
    """Like assertRaises, but rejects subclasses."""
    try:
      callable_obj(*args, **kwargs)
    except exc_class, e:
      # type(e) doesn't work instead of e.__class__ in Python 2.4. In Python
      # >=2.5 they work equivalently.
      if e.__class__ != exc_class:  # True if exc_class is a superclass.
        raise
      return
    self.fail('%s not raised.' % exc_class.__name__)

  def testAssertRaisesX(self):
    class C(ZeroDivisionError): pass
    def RaiseC():
      raise C()
    self.assertRaisesX(ZeroDivisionError, lambda: 1 / 0)
    self.assertRaisesX(C, RaiseC)
    self.assertRaises(ZeroDivisionError, RaiseC)
    try:
      self.assertRaisesX(ZeroDivisionError, RaiseC)
      self.fail('C was caught.')
    except C:
      pass
    try:
      self.assertRaisesX(C, lambda: 1 / 0)
      self.fail('ZeroDivisionError was caught.')
    except ZeroDivisionError:
      pass

  def testSerializePdfStringUnsafeAndParsePdfString(self):
    e = main.PdfObj.SerializePdfStringUnsafe
    p = lambda *args: main.PdfObj.ParsePdfString(*args)[0]
    def Check(pdf_string_literal, data):
      self.assertEqual(pdf_string_literal, e(data))
      self.assertEqual(data, p(buffer(pdf_string_literal)))
    def CheckParse(pdf_string_literal, data):
      self.assertEqual(data, p(buffer(pdf_string_literal)))
    Check('()', '')
    Check('(Hello, World!)', 'Hello, World!')
    Check('(\\\\Hello, \\(World!)', '\\Hello, (World!')
    Check('(Hello, \\)World!\\\\)', 'Hello, )World!\\')
    Check('(hi\\r)', 'hi\r')
    Check('(hi\n)', 'hi\n')
    Check('(hi\\r\n)', 'hi\r\n')
    Check('(hir%\'"a)', 'hir%\'"a')
    Check('(//)', '//')
    Check('(\\r\\()', '\r(')
    Check('(\\(\\\\\\r)', '(\\\r')
    CheckParse('(hi\\\nr\\%\\\'\\"\\a)', 'hir%\'"a')
    CheckParse('(hi\\\r\nx)', 'hix')
    CheckParse('(hi\\\r\\nx)', 'hi\nx')  # Same as in PostScript.
    CheckParse('(hi\\n\\r\\t\\b\\f\\400\\500\\600\\700)',
               'hi\n\r\t\b\f\00400\00500\00600\00700')
    CheckParse('(hi\\08\\18\\28\\38\\079\\179\\279\\379)',
               'hi\0008\0018\0028\0038\0079\0179\0279\0379')
    CheckParse('(hi\\076\\154\\232\\310\\0123\\1234\\2345\\3000)',
               'hi\076\154\232\310\0123\1234\2345\3000')
    CheckParse('<>', '')
    CheckParse('<\t\f>', '')
    CheckParse('<fA3>', '\xfa\x30')
    CheckParse('(\\0576\\057)', '/6/')
    s = ''.join([c for c in map(chr, xrange(255, -1, -1)) if c not in '()\\\r'])
    Check('(%s)' % s, s)
    Check('(Hello, \\)\\(Wo\\\\rld!)', 'Hello, )(Wo\\rld!')
    Check('((((foo\\\\))))', '(((foo\\)))')
    Check('(((foo)) (\\(bar)d)', '((foo)) ((bar)d')
    Check('((foo)\\) (bar))', '(foo)) (bar)')
    # We escape \r\n as \\r\n, to prevent it from being parsed as just \n.
    Check('(\nbar\\rbaz\\r\nquux\n\\rfoo)',
          '\nbar\rbaz\r\nquux\n\rfoo')
    self.assertRaisesX(TypeError, p, None)
    self.assertRaisesX(TypeError, p, 42)
    self.assertRaisesX(main.PdfTokenNotString, p, '/foo')
    self.assertRaisesX(main.PdfTokenTruncated, p, '(')
    self.assertRaisesX(main.PdfTokenTruncated, p, '(foo')
    self.assertRaisesX(main.PdfTokenTruncated, p, '<f00')
    self.assertRaisesX(main.PdfTokenTruncated, p, '(foo\\')
    self.assertRaisesX(main.PdfTokenTruncated, p, '()', 2)
    self.assertEqual('', p('?()/', 1, 3))
    self.assertRaisesX(main.PdfTokenParseError, p, '()/', 0, 3)
    self.assertRaisesX(main.PdfTokenParseError, p, '(\\n)/', 0, 5)
    self.assertEqual(('', 2), main.PdfObj.ParsePdfString(
        '()/', 0, 3, is_partial_ok=True))
    self.assertEqual(('\n', 5), main.PdfObj.ParsePdfString(
        '?(\\n)/', 1, 5, is_partial_ok=True))
    self.assertRaisesX(ValueError, p, '()', 3)  # Bad offsets.
    self.assertEqual(('', 2), main.PdfObj.ParsePdfString(
        '<>>>>>', is_partial_ok=True))
    self.assertEqual(('', 3), main.PdfObj.ParsePdfString(
        '?<>>>>>', start=1, is_partial_ok=True))
    self.assertEqual(('\x8d\x50', 5), main.PdfObj.ParsePdfString(
        '<8d5>]/', is_partial_ok=True))
    self.assertRaisesX(main.PdfTokenTruncated, main.PdfObj.ParsePdfString,
                      '<8d5', is_partial_ok=True)
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj.ParsePdfString,
                      '<6?', is_partial_ok=True)
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj.ParsePdfString,
                      '<\n3\t1\r4f5C5]>')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj.ParsePdfString,
                      '<\n3\t1\r4f5C5]')
    self.assertRaisesX(main.PdfTokenTruncated, main.PdfObj.ParsePdfString,
                      '<\n3\t1\r4f5C5')

  def testRewriteToParsable(self):
    e = main.PdfObj.RewriteToParsable
    self.assertEqual(' [ ]', e('[]'))
    self.assertEqual(' [ ]', e('[]<<'))
    self.assertEqual(' true', e('true '))
    self.assertEqual(' true', e('true'))
    self.assertRaisesX(main.PdfTokenParseError, e, 'hi ')
    eo = []
    self.assertEqual(' false', e('\n\t\r \f\0false true ', end_ofs_out=eo))
    self.assertEqual([11], eo)
    self.assertEqual(' << true false null >>',
                     e('% hi\r<<%\ntrue false null>>baz'))
    self.assertEqual(' << true >>',
                     e('<<true>>baz'))
    self.assertEqual(' [ [ << [ << << >> >> ] >> ] ]',
                     e('[[<<[<<<<>>>>]>>]]'))
    self.assertRaisesX(main.PdfTokenParseError,
                      e, '[[<<[<<<<>>]>>>>]]')
    self.assertRaisesX(main.PdfTokenTruncated, e, '\t \n% foo')
    self.assertRaisesX(main.PdfTokenTruncated, e, ' [\t')
    self.assertRaisesX(main.PdfTokenTruncated, e, '\n<\f')
    self.assertRaisesX(main.PdfTokenTruncated, e, '\t<<\n\r')
    self.assertRaisesX(main.PdfTokenTruncated, e, '[<<')
    self.assertRaisesX(main.PdfTokenParseError, e, '[<<]')
    self.assertRaisesX(main.PdfTokenParseError, e, '[>>]')
    self.assertEqual(' <>', e('()'))
    self.assertEqual(' <>', e('<>'))
    self.assertRaisesX(main.PdfTokenTruncated, e, '<<')
    self.assertRaisesX(main.PdfTokenParseError, e, '>>')
    self.assertRaisesX(main.PdfTokenTruncated, e, '[')
    self.assertRaisesX(main.PdfTokenParseError, e, ']')
    self.assertRaisesX(main.PdfTokenTruncated, e, '(foo')
    self.assertRaisesX(main.PdfTokenTruncated, e, '(foo\\)bar')
    self.assertEqual(' <face654389210b7d>', e('< f\nAc\tE\r654389210B7d\f>'))
    self.assertEqual(' <48656c6c6f2c20576f726c6421>', e('(Hello, World!)'))
    self.assertEqual(' <2828666f6f2929296261725c>', e('(((foo))\\)bar\\\\)'))
    self.assertEqual(' <410a420a430a440a0a45>', e('(A\rB\nC\r\nD\n\rE)'))
    self.assertEqual(' <0a280d2900>', e('(\\n(\\r)\\0)'))
    self.assertEqual(' <0a280a2900780a790a0a7a>', e('(\n(\r)\0x\r\ny\n\rz)'))
    self.assertEqual(' <466f6f42617242617a>', e('(Foo\\\nBar\\\rBaz)'))
    self.assertEqual(' <466f6f4261720a42617a>', e('(Foo\\\r\nBar\\\n\rBaz)'))
    self.assertEqual(' <2829%s>' % ''.join(['%02x' % {13: 10}.get(i, i)
                                            for i in xrange(33)]),
                     e('(()%s)' % ''.join(map(chr, xrange(33)))))
    self.assertEqual(' <face422829>', e('(\xfa\xCE\x42())'))
    self.assertEqual(' <00210023>', e('(\0!\\0#)'))
    self.assertEqual(' <073839380a>', e('(\78\98\12)'))
    self.assertEqual(' <053031>', e('(\\501)'))
    self.assertEqual(' <0a0a09080c>', e('(\n\r\t\b\f)'))
    self.assertEqual(' <0a0d09080c>', e('(\\n\\r\\t\\b\\f)'))
    self.assertEqual(' <236141>', e('(\\#\\a\\A)'))
    self.assertEqual(' <61275c>', e("(a'\\\\)"))
    self.assertEqual(' <314f5c60>', e('<\n3\t1\r4f5C6 >'))
    self.assertEqual(' <0006073839050e170338043805380638073838380a3913391f39>',
                     e('(\0\6\7\8\9\05\16\27\38\48\58\68\78\88\129\239\379)'))
    self.assertEqual(' <666f6f0a626172>', e('(foo\nbar)'))
    self.assertEqual(' <666f6f0a626172>', e('(foo\\nbar)'))
    self.assertEqual(' <666f6f626172>', e('(foo\\\nbar)'))
    self.assertEqual(' <0006073839050e170338043805380638073838380a3913391f39'
                     '043031053031063031073031>',
                     e('(\\0\\6\\7\\8\\9\\05\\16\\27\\38\\48\\58\\68\\78\\88'
                       '\\129\\239\\379\\401\\501\\601\\701)'))
    # PDF doesn't have \x
    self.assertEqual(' <786661786243784445f8>', e('(\\xfa\\xbC\\xDE\xF8)'))
    self.assertEqual(' 0', e('.'))
    self.assertEqual(' 42', e('42'))
    self.assertEqual(' 42', e('42 '))
    self.assertEqual(' 0', e('00000 '))
    self.assertEqual(' 0', e('+00000 '))
    self.assertEqual(' 0', e('-00000 '))
    self.assertEqual(' 0', e('00000.000 '))
    self.assertEqual(' 0', e('+00000.000 '))
    self.assertEqual(' 0', e('-00000.000 '))
    self.assertEqual(' 12', e('00012 '))
    self.assertEqual(' 12', e('+00012 '))
    self.assertEqual(' -12', e('-00012 '))
    self.assertEqual(' 12', e('00012. '))
    self.assertEqual(' 12', e('00012.000 '))
    self.assertEqual(' 12', e('+00012.000 '))
    self.assertEqual(' -12', e('-12.000 '))
    self.assertEqual(' 12.34', e('00012.340 '))
    self.assertEqual(' 12.34', e('+00012.34 '))
    self.assertEqual(' -12.34', e('-12.340 '))
    self.assertEqual(' [ .34 -.34 .34 ]', e('[.34 -.34 +.34]'))
    self.assertEqual(' [ .34 -.34 .34 ]', e('[00.34 -00.34 +00.34]'))
    self.assertEqual(' [ 34 -34 34 ]', e('[34. -34. +34.]'))
    self.assertEqual(' [ 34 -34 34 ]', e('[0034. -0034. +0034.]'))
    self.assertEqual(' [ 34 -34 34 ]', e('[34.00 -34.00 +34.00]'))
    self.assertEqual(' [ 34 -34 34 ]', e('[0034.00 -0034.00 +0034.00]'))
    self.assertEqual(' [ 0 0 0 ]', e('[0. -0. +0.]'))
    self.assertEqual(' [ 0 0 0 ]', e('[000. -000. +000.]'))
    self.assertEqual(' [ 0 0 0 ]', e('[.0 -.0 +.0]'))
    self.assertEqual(' [ 0 0 0 ]', e('[.000 -.000 +.000]'))
    self.assertEqual(' [ 0 0 0 ]', e('[00.000 -00.000 +00.000]'))
    self.assertEqual(' 12 345 R', e(' 12 345 R '))

    end_ofs_out = []
    self.assertEqual(' 5', e(' 5 endobj\t', end_ofs_out=end_ofs_out))
    self.assertEqual([2], end_ofs_out)
    end_ofs_out = []
    self.assertEqual(' 5 endobz',
                     e(' 5 endobz\t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([10], end_ofs_out)
    self.assertRaisesX(main.PdfTokenParseError, e, '/#')
    self.assertRaisesX(main.PdfTokenTruncated, e, '/')
    self.assertRaisesX(main.PdfTokenTruncated, e, '/ ')
    # TODO(pts): PdfTokenParseError instead?
    self.assertRaisesX(main.PdfTokenTruncated, e, '/%')
    self.assertEqual(' /#2A', e('/*'))
    self.assertEqual(' /STROZ#2F', e('/STR#4fZ#2f'))
    self.assertEqual(' /STROZ', e('/STR#4FZ\r\n\t\t\t \t'))
    end_ofs_out = []
    self.assertEqual(' 5 /STROZ hi',
                     e(' 5 /STR#4FZ hi\r\n\t\t\t \t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([16], end_ofs_out)
    end_ofs_out = []
    self.assertRaisesX(main.PdfTokenParseError, e,
                      ' 5 STR#4FZ\r\n\t\t\t \t',
                      end_ofs_out=end_ofs_out, do_terminate_obj=True)
    end_ofs_out = []
    self.assertEqual(' /Size', e('/Size 42 ', end_ofs_out=end_ofs_out))
    self.assertEqual([5], end_ofs_out)
    self.assertEqual(' [ /Size 42 ]', e('[/Size 42]'))
    self.assertEqual(' [ true 42 ]', e('[true\n%korte\n42]'))
    self.assertEqual(' [ true 42 ]', e('[true%korte\n42]'))
    self.assertRaisesX(main.PdfTokenParseError, e, 'hello \n\t world\n\t')
    self.assertEqual(' null', e('null \n\t false\n\t'))
    # This is invalid PDF (null is not a name), but we don't catch it.
    self.assertEqual(' << null false >>', e('\r<<null \n\t false\n\t>>'))
    self.assertEqual(' << true >>', e('<<true>>'))
    self.assertEqual(' true foo', e('true foo bar', do_terminate_obj=True))
    self.assertRaisesX(main.PdfTokenTruncated, e,
                      'true foo', do_terminate_obj=True)
    self.assertEqual(' <68656c296c6f0a0877286f72296c64>',
                     e('(hel\)lo\n\bw(or)ld)'))
    self.assertRaisesX(main.PdfTokenTruncated, e, '(hel\)lo\n\bw(orld)')
    self.assertEqual(' [ <68656c296c6f0a0877286f72296c64> ]',
                     e(' [ (hel\\051lo\\012\\010w\\050or\\051ld) ]<'))
    self.assertRaisesX(main.PdfTokenTruncated, e, '>')
    self.assertRaisesX(main.PdfTokenTruncated, e, '<')
    self.assertRaisesX(main.PdfTokenTruncated, e, '< ')
    self.assertRaisesX(main.PdfTokenParseError, e, '< <')
    self.assertRaisesX(main.PdfTokenParseError, e, '> >')
    self.assertRaisesX(main.PdfTokenParseError, e, '[ >>')
    self.assertRaisesX(main.PdfTokenTruncated, e,
                      '[ (hel\\)lo\\n\\bw(or)ld) <')
    self.assertRaisesX(main.PdfTokenTruncated, e, '<\n3\t1\r4f5C5')
    self.assertRaisesX(main.PdfTokenParseError, e, '<\n3\t1\r4f5C5]>')
    self.assertRaisesX(main.PdfTokenTruncated, e, '')
    self.assertRaisesX(main.PdfTokenTruncated, e, '%hello')
    # 'stream\r' is truncated, we're waiting for 'stream\r\n'.
    self.assertRaisesX(main.PdfTokenTruncated, e,
                      '<<>>stream\r', do_terminate_obj=True)
    self.assertEqual(' << >> blah', e('<<>>blah\r', do_terminate_obj=True))
    self.assertEqual(' << >> stream', e('<<>>stream\n', do_terminate_obj=True))
    self.assertEqual(' << >> stream',
                     e('<<>>stream\r\n', do_terminate_obj=True))

    self.assertEqual(' << /Type /Catalog /Pages 3 0 R >>',
                     e('<</Type /Catalog /Pages 3 0 R\n>>'))
    self.assertEqual(' 42', e(' 42 true R'))
    eo = []
    self.assertEqual(' 442 43 R', e('\t442%foo\r43\fR   ', end_ofs_out=eo))
    self.assertEqual(13, eo[0])  # spaces not included
    eo = []
    self.assertEqual(' 442 43 R', e('\t442%foo\r43\fR/', end_ofs_out=eo))
    self.assertEqual(' 442 43 R', e('\t+442%foo\r+43\fR/', end_ofs_out=eo))
    self.assertEqual(13, eo[0])  # spaces not included
    self.assertEqual(' << /Pages -333 -1 R >>', e('<</Pages -333 -1 R\n>>'))
    self.assertEqual(' << /Pages 0 55 R >>', e('<</Pages 0 55 R\n>>'))

  def testSerializeDict(self):
    # Toplevel whitespace is removed, but the newline inside the /DecodeParms
    # value is kept.
    self.assertEqual(
        '<</BitsPerComponent 8/ColorSpace/DeviceGray/DecodeParms'
        '<</Predictor 15\n/Columns 640>>/Filter/FlateDecode/Height 480'
        '/Length 6638/Subtype/Image/Width 640/Z true>>',
        main.PdfObj.SerializeDict(main.PdfObj.ParseSimplestDict(
            '<</Subtype/Image\n/ColorSpace/DeviceGray\n/Width 640/Z  true\n'
            '/Height 480\n/BitsPerComponent 8\n/Filter/FlateDecode\n'
            '/DecodeParms <</Predictor 15\n/Columns 640>>/Length 6638>>')))

  def testIsGrayColorSpace(self):
    e = main.PdfObj.IsGrayColorSpace
    self.assertEqual(False, e('/DeviceRGB'))
    self.assertEqual(False, e('/DeviceCMYK'))
    self.assertEqual(False, e('/DeviceN'))
    self.assertEqual(True, e('  /DeviceGray  \r'))
    self.assertEqual(False, e('\t[ /Indexed /DeviceGray'))
    self.assertEqual(True, e('\t[ /Indexed /DeviceGray 5 <]'))
    self.assertRaisesX(main.PdfTokenTruncated, e,
                      '\t[ /Indexed /DeviceRGB 5 (]')
    self.assertEqual(True, e('\t[ /Indexed /DeviceRGB\f5 (A\101Azz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Bzz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Ayy\172)]'))

  def testParseSimpleValue(self):
    e = main.PdfObj.ParseSimpleValue
    self.assertRaisesX(main.PdfTokenParseError, e, '')
    self.assertRaisesX(main.PdfTokenParseError, e, '%hello\nworld')
    self.assertRaisesX(main.PdfTokenParseError, e, 'win')  # Unknown keyword.
    self.assertRaisesX(main.PdfTokenParseError, e, 'foo bar')
    self.assertRaisesX(main.PdfTokenParseError, e, '/foo bar')
    self.assertEqual(True, e('true'))
    self.assertEqual(False, e('false'))
    self.assertEqual(True, e('true '))
    self.assertEqual(False, e('\nfalse'))
    self.assertEqual('[foo  bar]', e('\f[foo  bar]\n\r'))
    self.assertEqual('<<foo  bar\tbaz>>', e('\f<<foo  bar\tbaz>>\n\r'))
    self.assertEqual(None, e('null'))
    self.assertEqual(0, e('0'))
    self.assertEqual(42, e('42'))
    self.assertEqual(42, e('00042'))
    self.assertEqual(-137, e('-0137'))
    self.assertEqual(137, e('+0137'))
    self.assertEqual('3.14', e('3.14'))
    self.assertEqual('5', e('5.'))
    self.assertEqual('.5', e('+.5'))
    self.assertEqual('0', e('.'))
    self.assertEqual('0', e('-.'))
    self.assertRaisesX(main.PdfTokenParseError, e, '5e6')
    self.assertEqual('<48493f>', e('(HI?)'))
    self.assertEqual('<28295c>', e('(()\\\\)'))
    self.assertRaisesX(main.PdfTokenParseError, e, '(()\\\\)x')
    self.assertRaisesX(main.PdfTokenTruncated, e, '(()\\\\')
    self.assertEqual('<deadface>', e('<dea dF aCe>'))
    self.assertEqual('<deadfac0>', e('<\fdeadFaC\r>'))
    self.assertEqual('42 0 R', e('42\f\t0 \nR'))
    self.assertRaisesX(main.PdfTokenParseError, e, '42 R')
    self.assertRaisesX(main.PdfTokenParseError, e, 'foo#')
    self.assertRaisesX(main.PdfTokenParseError, e, 'foo#a')
    self.assertRaisesX(main.PdfTokenParseError, e, 'foo#ab')
    self.assertEqual('/foo', e('/foo'))
    self.assertRaisesX(main.PdfTokenParseError, e, '/foo#')
    self.assertRaisesX(main.PdfTokenParseError, e, '/foo#a')
    self.assertEqual('/foo#AB', e('/foo#ab'))
    self.assertEqual('/foo42', e('/foo#34#32'))
    self.assertEqual('/foo#2A', e('/foo*'))  # Normalized.
    self.assertEqual('/#FAce#5BB', e('/\xface#5b#42\f'))

  def DoTestParseSimplestDict(self, e):
    # e is either ParseSimplestDict or ParseDict, so (because the latter)
    # this method should not test for PdfTokenNotSimplest.
    self.assertEqual({}, e('<<\t\0>>'))
    self.assertEqual({}, e('<<\n>>'))
    self.assertEqual({'One': '/Two'}, e('<< /One/Two>>'))
    self.assertEqual({'One': '2.2'}, e('<</One +2.2>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<</One Two>>')
    self.assertEqual({'One': 234}, e('<</One 234>>'))
    self.assertRaisesX(main.PdfTokenParseError, e,
                      '<</One/Two/Three Four/Five/Six>>')
    self.assertEqual({'Five': '/Six', 'Three': '-4', 'One': '/Two'},
                     e('<</One/Two/Three -4.000/Five/Six>>'))
    self.assertEqual({'A': True, 'C': None, 'B': False, 'E': '42.5', 'D': 42},
                     e('<<\n\r/A true/B\f\0false/C null/D\t42/E 42.5\r>>'))
    self.assertEqual({'Data': '42 137 R'}, e('<</Data 42\t\t137\nR >>'))
    self.assertEqual({'S': '<68656c6c6f2c20776f726c6421>'},
                     e('<</S(hello, world!)>>'))
    self.assertEqual({'S': '<>'}, e('<</S()>>'))
    self.assertEqual({'S': '<0a>'}, e('<</S\r(\n)>>'))
    self.assertEqual({'S': '<3c3c5d3e3e5b>'}, e('<</S  (<<]>>[)\n>>'))
    self.assertEqual({'S': '<deadface50>'}, e('<</S<dEA Dfa CE5>>>'))
    self.assertEqual({'A': '[42 \t?Foo>><<]'}, e('<</A[42 \t?Foo>><<]>>'))
    self.assertEqual(
        {'D': '<<]42[\f\t?Foo>>'}, e('<<\n/D\n<<]42[\f\t?Foo>>>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<</S<%\n>>>')

  def testParseSimplestDict(self):
    e = main.PdfObj.ParseSimplestDict
    self.DoTestParseSimplestDict(e=e)
    self.assertRaisesX(main.PdfTokenNotSimplest,
                      e, '<</Three[/Four()]>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</S\r(\\n)>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</A[()]>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</A[%\n]>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</D<<()>>>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</D<<%\n>>>>')
    self.assertRaisesX(main.PdfTokenNotSimplest, e, '<</?Answer! 42>>')

  def testParseDict(self):
    e = main.PdfObj.ParseDict
    self.DoTestParseSimplestDict(e=e)
    self.assertEqual({}, e('<<\0\r>>'))
    self.assertEqual({}, e('<<\n>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<<')
    self.assertEqual({'I': 5}, e('<</I%\n5>>'))
    self.assertEqual({'N': '/Foo-42+_'}, e('<</N/Foo-42+_>>'))
    self.assertEqual({'N': '/Foo-42+_#2A'}, e('<</N/Foo-42+_*>>'))
    self.assertEqual({'N': '/Foo-42+_#2Ab'}, e('<</N/Foo-42+_#2ab>>'))
    self.assertEqual({'Five': '/Six', 'Three': '[/Four]', 'One': '/Two'},
                     e('<</One/Two/Three[/Four]/Five/Six>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<</Foo bar#3f>>')
    self.assertEqual({'#3FAnswer#21#20#0D': 42}, e('<</?Answer!#20#0d 42>>'))
    self.assertEqual({'S': '<0a>'}, e('<</S\r(\\n)>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<</S\r(foo\\)>>')
    self.assertEqual({'S': '<666f6f29626172>'}, e('<</S(foo\\)bar)>>'))
    self.assertEqual(
        {'S': '<2829>', 'T': '<42cab0>'}, e('<</S(())/T<42c Ab>>>'))
    self.assertEqual({'S': '<282929285c>', 'T': 8},
                     e('<</S(()\\)\\(\\\\)/T 8>>'))
    self.assertEqual({'A': '[\f()]'}, e('<</A[\f()]>>'))
    self.assertEqual({'A': '[\t5 \r6\f]'}, e('<</A[\t5 \r6\f]>>'))
    self.assertEqual({'A': '[12 34]'}, e('<</A[12%\n34]>>'))
    # \t removed because there was a comment in the array
    self.assertEqual({'A': '[]'}, e('<</A[\t%()\n]>>'))
    self.assertEqual({'A': '<2829>', 'B': '[<<]'}, e('<</A(())/B[<<]>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<</A>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<<5/A>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<</A(())/B[()<<]>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<</A[[>>]]>>')
    self.assertEqual({'A': '[[/hi 5]/lah]'}, e('<</A[[/hi%x\t]z\r5] /lah]>>'))
    self.assertEqual({'D': '<<()\t<>>>'}, e('<</D<<()\t<>>>>>'))
    self.assertEqual({'D': '<<>>', 'S': '<>'}, e('<</D<<%\n>>/S()>>'))
    # \t and \f removed because there was a comment in the dict
    self.assertEqual({'D': '<</E<<>>>>'}, e('<</D<</E\t\f<<%>>\n>>>>>>'))
    self.assertEqual({'A': '[[]]', 'q': '56 78 R'},
                     e('<</A[[]]/q\t56\r78%q\rR>>'))
    self.assertRaisesX(main.PdfTokenParseError, e, '<<\r%>>')

  def testParseArray(self):
    e = main.PdfObj.ParseArray
    self.assertRaisesX(main.PdfTokenParseError, e, '[%]')
    self.assertEqual(['/Indexed', '/DeviceRGB', 42, '43 44 R'],
                     e('[\t/Indexed/DeviceRGB\f\r42\00043%42\n44\0R\n]'))
    self.assertEqual(['[ ]', '[\t[\f]]', '<<\t [\f[ >>', True, False, None],
                     e('[[ ] [\t[\f]] <<\t [\f[ >> true%\nfalse\fnull]'))

  def testParseValueRecursive(self):
    e = main.PdfObj.ParseValueRecursive
    self.assertEqual(None, e('null'))
    self.assertEqual(True, e('true'))
    self.assertEqual(False, e('false'))
    self.assertEqual('foo', e(' foo % true\n\r '))
    self.assertEqual(42, e('000042'))
    self.assertEqual('0042.0', e('0042.0'))
    self.assertEqual('/Font', e('\t/Font\f'))
    self.assertEqual('<28282929>', e('((()))'))
    self.assertEqual('<25>', e('(%)'))
    self.assertEqual('<29282868656c292929296c6f295c>',
                     e('(\\)((hel\\)\\))\\)lo)\\\\)'))
    self.assertEqual([], e('[]'))
    self.assertEqual({}, e('<<>>'))
    self.assertEqual({1: 2}, e('<<1 2>>'))
    self.assertEqual({'bar': '/baz', 5: {'A': [67, '<>', 'foo']}},
                     e('<<5<</A[67()foo]>>bar /baz>>'))
    self.assertEqual(['/pedal.#2A', '/pedal.#2A'], e('[/pedal.*/pedal.#2a]'))
    self.assertEqual(
        ['/pedal.#2A', '/pedal.#232a'],
        e('[/pedal.*/pedal.#2a]', do_expect_postscript_name_input=True))
    self.assertEqual(
        ['/pedal.#2A', '<>', '/pedal.#232a'],
        e('[/pedal.*()/pedal.#2a]', do_expect_postscript_name_input=True))
    self.assertRaisesX(main.PdfTokenParseError, e, '1 2')
    self.assertRaisesX(main.PdfTokenParseError, e, '[')
    self.assertRaisesX(main.PdfTokenParseError, e, '[[]')
    self.assertRaisesX(main.PdfTokenParseError, e, ']')
    self.assertRaisesX(main.PdfTokenParseError, e, '3]')
    self.assertRaisesX(main.PdfTokenParseError, e, '>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<<]')
    self.assertRaisesX(main.PdfTokenParseError, e, '[>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '(')
    self.assertRaisesX(main.PdfTokenParseError, e, '(()')
    self.assertRaisesX(main.PdfTokenParseError, e, '(()))')
    self.assertRaisesX(main.PdfTokenParseError, e, '<12')
    self.assertRaisesX(main.PdfTokenParseError, e, '<12<>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<<1>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '<<%>>')
    self.assertRaisesX(main.PdfTokenParseError, e, '[%]')
    self.assertRaisesX(main.PdfTokenParseError, e, '/')
    self.assertRaisesX(main.PdfTokenParseError, e, '//')
    self.assertRaisesX(main.PdfTokenParseError, e, '//foo')

  def testCompressValue(self):
    e = main.PdfObj.CompressValue
    self.assertEqual('', e('\t\f\0\r \n'))
    self.assertEqual('foo bar', e('   foo\n\t  bar\f'))
    self.assertEqual('foo 123', e('foo%bar\r123'))
    self.assertEqual('foo 123', e('foo%bar\n123'))
    self.assertEqual(']foo/bar(\xba\xd0)>>', e(' ]  foo\n\t  /bar\f <bAd>>>'))
    self.assertEqual('<<bAd CAFE>>', e('<<bAd  CAFE>>'))
    self.assertEqual('<<(\xba\xdc\xaf\xe0)>>', e('<<<bad CAFE>>>'))
    self.assertEqual('()', e('()'))
    self.assertEqual('<>', e('()', do_emit_strings_as_hex=True))
    self.assertEqual('<fa>', e('(\xFa)', do_emit_strings_as_hex=True))
    self.assertEqual('<7e>', e('(\\176)', do_emit_strings_as_hex=True))
    self.assertEqual('(())', e(' <2829>\t', do_emit_safe_strings=False))
    self.assertEqual('<2829>', e(' <2829>\t'))
    self.assertEqual('<2829>', e(' (())\t'))
    self.assertEqual('(\\)\\()', e(' <2928>\t', do_emit_safe_strings=False))
    self.assertEqual('<2928>', e(' <2928>\t'))
    self.assertEqual('[12 34]', e('[12%\n34]'))
    self.assertEqual('[12 34]', e('[ 12 34 ]'))
    self.assertEqual('<</A[12 34]>>', e(' << \t/A\f[12%\n34]>>\r'))
    self.assertEqual('<2068656c6c6f090a>world', e(' ( hello\\t\n)world'))
    self.assertEqual('( hello\t\n)world',
                     e(' ( hello\\t\n)world', do_emit_safe_strings=False))
    self.assertEqual('<292828686929295c>world', e(' (\\)(\\(hi\\))\\\\)world'))
    self.assertEqual('(\\)((hi))\\\\)world',
                     e(' (\\)(\\(hi\\))\\\\)world', do_emit_safe_strings=False))
    self.assertEqual('/#FAce#5BB', e('/\xface#5b#42\f'))
    self.assertEqual('/\xface#5BB', e('/\xface#5b#42\f', do_emit_safe_names=False))
    self.assertRaisesX(main.PdfTokenParseError, e, '/#')
    s = '/Kids[041\t 0\rR\f43\n0% 96 0 R\rR 42 0 R 97 0 Rs 42 0 R]( 98 0 R )\f'
    t = '/Kids[041 0 R 43 0 R 42 0 R 97 0 Rs 42 0 R]<2039382030205220>'
    self.assertEqual(t, e(s))
    self.assertEqual(t, e(e(s)))
    old_obj_nums = ['']
    self.assertEqual(t, e(s, old_obj_nums_ret=old_obj_nums))
    self.assertEqual(['', 41, 43, 42, 42], old_obj_nums)
    uu = '/Kids[41 0 R 53 0 R 52 0 R 97 0 Rs 52 0 R]( 98 0 R )'
    u = '/Kids[41 0 R 53 0 R 52 0 R 97 0 Rs 52 0 R]<2039382030205220>'
    self.assertEqual(u, e(s, obj_num_map={43: 53, 42: 52}))
    self.assertEqual(uu, e(s, obj_num_map={43: 53, 42: 52},
                           do_emit_safe_strings=False))
    old_obj_nums = [None]
    self.assertEqual(
        u, e(s, obj_num_map={43: 53, 42: 52}, old_obj_nums_ret=old_obj_nums))
    self.assertEqual([None, 41, 43, 42, 42], old_obj_nums)
    self.assertEqual('<</Length 68/Filter/FlateDecode>>',
                     e('<</Length 68/Filter/FlateDecode >>'))
    self.assertEqual('<</Type/Catalog/Pages 1 0 R>>',
                     e('<</Type/Catalog/Pages 1 0 R >>'))
    self.assertEqual('[/Zoo#3C#3E 1]', e('[/Zoo#3c#3e 1]'))
    self.assertEqual('[/Zoo#3C#3E(a)/foo#2A/bar#2A#5B/pedal.#2A]',
                     e('[/Zoo#3c#3e(a\\\n)/foo*/bar#2a#5b/pedal.#2a]'))
    self.assertEqual('[/Zoo#3C#3E<0a>/foo#2A/bar#2A#5B/pedal.#2A]',
                     e('[/Zoo#3c#3e(\r\\\n)/foo*/bar#2a#5b/pedal.#2a]'))
    self.assertEqual('[/Zoo#3C#3E<0d>/foo#2A/bar#2A#5B/pedal.#2A]',
                     e('[/Zoo#3c#3e(\\r\\\n)/foo*/bar#2a#5b/pedal.#2a]'))
    self.assertEqual('[/Zoo#3C#3E<0a>/foo*/bar*#5B/pedal.*]',
                     e('[/Zoo#3c#3e(\n\\\n)/foo*/bar#2a#5b/pedal.#2a]',
                       do_emit_safe_names=False))

  def testPdfObjParse(self):
    obj = main.PdfObj(
        '42 0 obj<</Length  3>>stream\r\nABC endstream endobj')
    self.assertEqual('<</Length 3>>', obj.head)
    self.assertEqual('ABC', obj.stream)
    obj = main.PdfObj(
        '42 0 obj<</Length%5 6\n3\r>>\t\f\0stream\r\nABC endstream endobj')
    self.assertEqual('<</Length 3>>', obj.head)
    self.assertEqual('ABC', obj.stream)
    obj = main.PdfObj(
        '42 0 obj<</Length 4>>stream\r\nABC endstream endobj')
    self.assertEqual(
        'ABC ', main.PdfObj(
            '42 0 obj<</Length 99>>stream\r\nABC endstream endobj').stream)
    self.assertEqual('<</Length 4>>', obj.head)
    self.assertEqual('ABC ', obj.stream)
    obj = main.PdfObj('42 0 obj<</Length  4>>endobj')
    self.assertEqual('<<>>', obj.head)
    self.assertEqual(None, obj.stream)
    obj = main.PdfObj(
        '42 0 obj<</T[/Length 99]/Length  3>>stream\r\nABC endstream endobj')
    self.assertEqual('ABC', obj.stream)
    obj = main.PdfObj(
        '42 0 obj<</T()/Length  3>>stream\nABC endstream endobj')
    self.assertEqual('ABC', obj.stream)
    s = '41 0 obj<</T(>>\nendobj\n)/Length  3>>stream\nABD endstream endobj'
    t = '42 0 obj<</T 5%>>endobj\n/Length  3>>stream\nABE endstream endobj'
    end_ofs_out = []
    obj = main.PdfObj(s, end_ofs_out=end_ofs_out)
    self.assertEqual('<</T<3e3e0a656e646f626a0a>/Length 3>>', obj.head)
    self.assertEqual([43, len(s)], end_ofs_out)
    self.assertEqual('ABD', obj.stream)
    end_ofs_out = []
    obj = main.PdfObj(t + '\r\n\tANYTHING', end_ofs_out=end_ofs_out)
    self.assertEqual('<</T 5/Length 3>>', obj.head)
    self.assertEqual([43, len(t) + 1], end_ofs_out)
    end_ofs_out = []
    obj = main.PdfObj(
        '%s\n%s' % (s, t), start=len(s) + 1, end_ofs_out=end_ofs_out)
    self.assertEqual('ABE', obj.stream)
    self.assertEqual([107, len(s) + 1 + len(t)], end_ofs_out)
    obj = main.PdfObj('%s\n%s' % (s, t), start=len(s))
    self.assertEqual('ABE', obj.stream)
    self.assertEqual([107, len(s) + 1 + len(t)], end_ofs_out)
    # Exception because start points to '#', not an `X Y obj'.
    self.assertRaisesX(
        main.PdfTokenParseError,
        main.PdfObj, '%s#%s' % (s, t), start=len(s))

    s = '22 0 obj<</Producer(A)/CreationDate(B)/Creator(C)>>\nendobj '
    t = '23 0 obj'
    end_ofs_out = []
    obj = main.PdfObj(s + t, end_ofs_out=end_ofs_out)
    self.assertEqual('<</Producer(A)/CreationDate(B)/Creator(C)>>', obj.head)
    self.assertEqual([len(s)], end_ofs_out)
    obj = main.PdfObj(
        '42 0 obj[/Foo%]endobj\n42  43\t]\nendobj')
    self.assertEqual('[/Foo 42 43]', obj.head)
    obj = main.PdfObj('42 0 obj%hello\r  \t\f%more\n/Foo%bello\nendobj')
    self.assertEqual('/Foo', obj.head)
    obj = main.PdfObj('42 0 obj/S()/Type/XObendobj endobj')
    self.assertEqual('/S()/Type/XObendobj', obj.head)
    obj = main.PdfObj('42 0 obj/Type/XObendobj endobj')
    self.assertEqual('/Type/XObendobj', obj.head)
    obj = main.PdfObj('42 0 obj/Type/XOb#6Aec#74#1a#20endobj endobj')
    self.assertEqual('/Type/XObject#1A#20endobj', obj.head)
    obj = main.PdfObj('42 0 obj(endobj+rest) endobj')
    self.assertEqual('(endobj+rest)', obj.head)
    obj = main.PdfObj('42 0 obj(endobj rest) endobj')
    self.assertEqual('<656e646f626a2072657374>', obj.head)
    obj = main.PdfObj('42 0 obj<</Type\n\n/XObject >>\n\rendobj')
    self.assertEqual('<</Type/XObject>>', obj.head)
    obj = main.PdfObj('42 0 obj<</Type\n%\n/XObject >>\n\rendobj')
    self.assertEqual('<</Type/XObject>>', obj.head)
    obj = main.PdfObj('42 0 obj<</BitsPerComponent\n\n4 \f>>\t\tendobj')
    self.assertEqual('<</BitsPerComponent 4>>', obj.head)
    obj = main.PdfObj('42 0 obj<</BitsPerComponent\n\n4\f/A ( ) >>\t\tendobj')
    self.assertEqual('<</BitsPerComponent 4/A<20>>>', obj.head)
    obj = main.PdfObj('42 0 obj<</BitsPerComponent\n\n4\f'
                      '/A ((\)\)endobj)x) >>\t\tendobj')
    self.assertEqual('<</BitsPerComponent 4/A<282929656e646f626a2978>>>',
                     obj.head)
    self.assertRaisesX(  # An empty name token.
        main.PdfTokenParseError, main.PdfObj, '42 0 obj<</A()/B/>>endobj')
    self.assertRaisesX(  # An empty name token.
        main.PdfTokenParseError, main.PdfObj, '42 0 obj<</A/>>endobj')
    obj = main.PdfObj('42 0 obj/foo\\bar endobj')
    self.assertEqual('/foo#5Cbar', obj.head)
    obj = main.PdfObj('42 0 obj/foo\vbar endobj')
    self.assertEqual('/foo#0Bbar', obj.head)
    obj = main.PdfObj('42 0 obj<</f*oo\\$ (*Length$) >>endobj')
    self.assertEqual('<</f#2Aoo#5C#24(*Length$)>>', obj.head)
    obj = main.PdfObj('42 0 obj<</A (/Length) >>endobj')
    self.assertEqual('<</A<2f4c656e677468>>>', obj.head)
    obj = main.PdfObj('42 0 obj<</A (/Length 5) >>endobj')
    self.assertEqual('<</A<2f4c656e6774682035>>>', obj.head)
    obj = main.PdfObj('42 0 obj<</A()/B<686a>>>endobj')
    self.assertEqual('<</A()/B(hj)>>', obj.head)
    obj = main.PdfObj('42 0 obj<</B<686a5>>>endobj')
    self.assertEqual('<</B(hjP)>>', obj.head)
    obj = main.PdfObj('0 0 obj<</A()/B<>/C(:)/D<3a3A4>>>endobj')
    self.assertEqual('<</A()/B()/C(:)/D(::@)>>', obj.head)
    obj = main.PdfObj('42 0 obj(}{)endobj')
    self.assertEqual('<7d7b>', obj.head)
    obj = main.PdfObj('42 0 obj/f*oo$ endobj')
    self.assertEqual('/f#2Aoo#24', obj.head)
    obj = main.PdfObj('42 0 obj(())endobj')
    self.assertEqual('<2829>', obj.head)
    obj = main.PdfObj('42 0 obj(\\n)endobj')
    self.assertEqual('<0a>', obj.head)
    obj = main.PdfObj('42 0 obj(\\100)endobj')
    self.assertEqual('(@)', obj.head)
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj /foo# endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj /foo#b endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj /foo#bxar endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj [()<a endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj [()<g> endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj [<a endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj [<g> endobj')
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                      '42 0 obj %\n\nendobj')
    end_ofs_out = []
    obj = main.PdfObj('42 0 obj 5  endobj\r\n x', end_ofs_out=end_ofs_out)
    self.assertEqual('5', obj.head)
    self.assertEqual([20], end_ofs_out)
    end_ofs_out = []
    obj = main.PdfObj('42 0 obj () endobj\r\n x', end_ofs_out=end_ofs_out)
    self.assertEqual('()', obj.head)
    self.assertEqual([20], end_ofs_out)
    # !!! TODO(pts): Fix bad numbers, all this to 0.
    obj = main.PdfObj('42 0 obj[. -. . .]endobj')
    self.assertEqual('[. -. . .]', obj.head)
    expected_head = '<</Filter[/LZWDecode/ASCIIHexDecode]/Length 0>>'
    # Syntax error, stream must be followed by a EOL according to
    # pdf_reference_1-7.pdf.
    self.assertRaisesX(main.PdfTokenParseError, main.PdfObj,
                       '42 0 obj<</Filter [/LZW /AHx]/Length 0>>'
                       'stream%\nendstream endobj')
    obj = main.PdfObj('42 0 obj<</Filter [/LZW /AHx]/Length 0>>'
                      'stream\nendstream endobj')
    self.assertEqual(expected_head, obj.head)
    # Not allowed by pdf_reference_1-7.pdf, we are permissive.
    obj = main.PdfObj('42 0 obj<</Filter [/LZW /AHx]/Length 0>>'
                      'stream endstream endobj')
    self.assertEqual(expected_head, obj.head)
    obj = main.PdfObj('42 0 obj<</Filter [/LZW /AHx]/Length 0>>'
                      'stream\r\nendstream endobj')
    self.assertEqual(expected_head, obj.head)
    self.assertEqual('', obj.stream)
    obj = main.PdfObj('42 0 obj<</Filter [/LZW /AHx]/Length 0>>'
                      'stream \t\0\f \r\nendstream endobj')
    self.assertEqual(expected_head, obj.head)
    obj = main.PdfObj('42 0 obj<</Filter [/LZW /AHx]/Length 42'
                      '/DecodeParms 43/Foo /Bar>>endobj')
    self.assertEqual('<</Foo/Bar>>', obj.head)

    # TODO(pts): Add more tests.

  def testParseTrailer(self):
    F = main.PdfObj.ParseTrailer
    self.assertEqual('<</Root 4 0 R>>',
                     F('trailer<</Root 4 0 R>>startxref ').head)
    self.assertEqual('<</Root 4 0 R>>',
                     F('trailer<</Root 4 0 R>>xref ').head)
    end_ofs_out = []
    trailer = 'footrailer\t<< /Root\n4\n0\nR\r>>\fstartxref '
    self.assertEqual('<</Root 4 0 R>>',
                     F(trailer, start=3, end_ofs_out=end_ofs_out).head)
    self.assertEqual('startxref ', trailer[end_ofs_out[0]:])
    end_ofs_out = []
    trailer = 'footrailer\t<< /Root\n4\n0\nR/Hi(\\041>>xref )\r>>%hi\n\fxref\t'
    self.assertEqual('<</Root 4 0 R/Hi<213e3e7872656620>>>',
                     F(trailer, start=3, end_ofs_out=end_ofs_out).head)
    self.assertEqual('xref\t', trailer[end_ofs_out[0]:])

  def testExpandAbbreviatoins(self):
    F = main.PdfObj.ExpandAbbreviations
    self.assertEqual('', F(''))
    self.assertEqual('/Foo', F('/Foo'))
    self.assertEqual(' /AHxy ', F(' /AHxy '))
    self.assertEqual(' /ASCIIHexDecode ', F(' /AHx '))
    self.assertEqual(' /ASCIIHexDecode ', F(' /ASCIIHexDecode '))
    self.assertEqual('\t/ImageMask\f', F('\t/IM\f'))
    self.assertEqual('[/ASCIIHexDecode/ASCII85Decode/LZWDecode '
                     '/FlateDecode/RunLengthDecode/CCITTFaxDecode/DCTDecode]',
                     F('[/AHx/A85/LZW /Fl/RL/CCF/DCT]'))

  def testCheckSafePdfTokens(self):
    F = main.PdfObj.CheckSafePdfTokens
    F('')
    F('<<')
    F(']][<<[]>>-12.34 fooBar /Foo#2a (hello) <a>')
    self.assertRaisesX(main.PdfTokenParseError, F, '\n')
    self.assertRaisesX(main.PdfTokenParseError, F, 'foo\n')
    self.assertRaisesX(main.PdfTokenParseError, F, '%')
    self.assertRaisesX(main.PdfTokenParseError, F, '\1')
    F('(\200)')
    self.assertRaisesX(main.PdfTokenParseError, F, '\200')
    self.assertRaisesX(main.PdfTokenParseError, F, '(\\200)')
    self.assertRaisesX(main.PdfTokenParseError, F, '(\\101)')
    self.assertRaisesX(main.PdfTokenParseError, F, '/pedal.*')
    self.assertRaisesX(main.PdfTokenParseError, F, '<a')
    self.assertRaisesX(main.PdfTokenParseError, F, '<ag>')
    F('x<ab>y')
    self.assertRaisesX(main.PdfTokenParseError, F, 'x<ag>y')
    self.assertRaisesX(main.PdfTokenParseError, F, '< <')
    self.assertRaisesX(main.PdfTokenParseError, F, '> >')
    self.assertRaisesX(main.PdfTokenParseError, F, '<<<')
    self.assertRaisesX(main.PdfTokenParseError, F, '>>>')

  def testParseTokensToSafeSimple(self, is_simple_ok=True):
    def F(data, **kwargs):
      return main.PdfObj.ParseTokensToSafe(
          buffer(data), is_simple_ok=is_simple_ok, **kwargs)[0]

    self.assertEqual('hello world', F('hello  world'))
    self.assertEqual('foo', F('foo\t\f\0\r \n'))
    self.assertEqual('world', F('%hello\rworld'))
    self.assertEqual('($)', F('($)'))
    self.assertEqual('<23>', F('(#)'))
    self.assertEqual('', F(''))
    self.assertEqual('', F('%hello'))
    self.assertEqual('', F('%hello\n'))
    self.assertEqual('/Foo#2C#2C 42', F('/Foo,, 42'))
    self.assertEqual('/Foo#2C#2C 42', F('/Foo#2c#2C 42'))
    self.assertEqual('/Foo#2C#2C 42', F('/Foo,#2c 42'))
    self.assertRaisesX(main.PdfTokenParseError, F, '/')
    # PdfTokenTruncated would be better.
    self.assertRaisesX(main.PdfTokenParseError, F, '/#')
    # PdfTokenTruncated would be better.
    self.assertRaisesX(main.PdfTokenParseError, F, '/#2')
    # PdfTokenTruncated would be better.
    self.assertRaisesX(main.PdfTokenParseError, F, '#')
    # PdfTokenTruncated would be better.
    self.assertRaisesX(main.PdfTokenParseError, F, '#2')
    self.assertRaisesX(main.PdfTokenTruncated, F, '(')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<')
    self.assertEqual('[', F('['))
    self.assertEqual('/#2A', F('/#2a'))
    self.assertEqual('/J', F('/#4a'))
    self.assertEqual('#2A', F('#2a'))
    self.assertEqual('J', F('#4a'))

    self.assertEqual('', F('\x00'))
    self.assertEqual('\x01', F('\x01'))  # !!! #01
    self.assertEqual('\x7f', F('\x7f'))  # !!! #7F
    self.assertEqual('\x80', F('\x80'))  # !!! #80
    self.assertEqual('\xff', F('\xff'))  # !!! #FF
    self.assertEqual('#01', F('#01'))
    self.assertEqual('#7F', F('#7f'))
    self.assertEqual('#80', F('#80'))
    self.assertEqual('#FF', F('#fF'))
    self.assertRaisesX(main.PdfTokenParseError, F, '/')
    self.assertRaisesX(main.PdfTokenParseError, F, '/\x00')
    self.assertEqual('/#01', F('/\x01'))
    self.assertEqual('/#7F', F('/\x7f'))
    self.assertEqual('/#80', F('/\x80'))
    self.assertEqual('/#FF', F('/\xff'))
    self.assertEqual('/#00', F('/#00'))
    self.assertEqual('/#01', F('/#01'))
    self.assertEqual('/#7F', F('/#7f'))
    self.assertEqual('/#80', F('/#80'))
    self.assertEqual('/#FF', F('/#fF'))

    # Most of these tests copied from testCompressValue. (Not everything was
    # copied.)
    self.assertEqual('', F('\t\f\0\r \n'))
    self.assertEqual('foo bar', F('   foo\n\t  bar\f'))
    self.assertEqual('foo 123', F('foo%bar\r123'))
    self.assertEqual('foo 123', F('foo%bar\n123'))
    self.assertEqual(']foo/bar(\xba\xd0)>>', F(' ]  foo\n\t  /bar\f <bAd>>>'))
    self.assertEqual('<<bAd CAFE>>', F('<<bAd  CAFE>>'))
    self.assertEqual('<<(\xba\xdc\xaf\xe0)>>', F('<<<bad CAFE>>>'))
    self.assertEqual('()', F('()'))
    self.assertEqual('<2829>', F(' <2829>\t'))
    self.assertEqual('<2829>', F(' (())%hi'))
    self.assertEqual('<2829>', F(' (())\t'))
    self.assertEqual('<2928>', F(' <2928>\t'))
    self.assertEqual('[12 34]', F('[12%\n34]'))
    self.assertEqual('[12 34]', F('[ 12 34 ]'))
    self.assertEqual('<</A[12 34]>>', F(' << \t/A\f[12%\n34]>>\r'))
    self.assertEqual('<2068656c6c6f090a>world', F(' ( hello\\t\n)world'))
    self.assertEqual('<292828686929295c>world', F(' (\\)(\\(hi\\))\\\\)world'))
    self.assertEqual('/#FAce#5BB', F('/\xface#5b#42\f'))
    self.assertRaisesX(main.PdfTokenParseError, F, '/#')
    s = '/Kids[041\t 0\rR\f43\n0% 96 0 R\rR 42 0 R 97 0 Rs 42 0 R]( 98 0 R )\f'
    t = '/Kids[041 0 R 43 0 R 42 0 R 97 0 Rs 42 0 R]<2039382030205220>'
    self.assertEqual(t, F(s))
    self.assertEqual(t, F(F(s)))
    uu = '/Kids[41 0 R 53 0 R 52 0 R 97 0 Rs 52 0 R]( 98 0 R )'
    u = '/Kids[41 0 R 53 0 R 52 0 R 97 0 Rs 52 0 R]<2039382030205220>'
    self.assertEqual(u, F(u))
    self.assertEqual(u, F(uu))
    self.assertEqual('<</Length 68/Filter/FlateDecode>>',
                     F('<</Length 68/Filter/FlateDecode >>'))
    self.assertEqual('<</Type/Catalog/Pages 1 0 R>>',
                     F('<</Type/Catalog/Pages 1 0 R >>'))
    self.assertEqual('[/Zoo#3C#3E 1]', F('[/Zoo#3c#3e 1]'))
    self.assertEqual('[/Zoo#3C#3E(a)/foo#2A/bar#2A#5B/pedal.#2A]',
                     F('[/Zoo#3c#3e(a\\\n)/foo*/bar#2a#5b/pedal.#2a]'))
    self.assertEqual('[/Zoo#3C#3E<0a>/foo#2A/bar#2A#5B/pedal.#2A]',
                     F('[/Zoo#3c#3e(\r\\\n)/foo*/bar#2a#5b/pedal.#2a]'))
    self.assertEqual('[/Zoo#3C#3E<0d>/foo#2A/bar#2A#5B/pedal.#2A]',
                     F('[/Zoo#3c#3e(\\r\\\n)/foo*/bar#2a#5b/pedal.#2a]'))

    # Most of these tests copied from testRewriteToParsable. (Not everything
    # was copied.)
    self.assertEqual('[]', F('[]'))
    self.assertEqual('[]<<', F('[]<<'))
    self.assertEqual('true', F('true '))
    self.assertEqual('true', F('true'))
    self.assertEqual('hi', F('hi '))
    eo = []
    self.assertEqual('false true', F('\n\t\r \f\0false true ', end_ofs_out=eo))
    self.assertEqual([17], eo)
    self.assertEqual('<<true false null>>baz',
                     F('% hi\r<<%\ntrue false null>>baz'))
    self.assertEqual('<<true>>baz',
                     F('<<true>>baz'))
    self.assertEqual('[[<<[<<<<>>>>]>>]]', F('[[<<[<<<<>>>>]>>]]'))
    # Unbalanced << and [. It's OK.
    self.assertEqual('[[<<[<<<<>>]>>>>]]', F('[[<<[<<<<>>]>>>>]]'))
    self.assertEqual('', F('\t \n% foo'))
    self.assertEqual('[', F(' [\t'))
    self.assertRaisesX(main.PdfTokenTruncated, F, '\n<\f')
    self.assertEqual('<<', F('\t<<\n\r'))
    self.assertEqual('[<<', F('[<<'))
    self.assertEqual('[<<]', F('[<<]'))
    self.assertEqual('[>>]', F('[>>]'))
    self.assertEqual('()', F('()'))  # Different from RewriteToParsable.
    self.assertEqual('()', F('<>'))  # Different from RewriteToParsable.
    self.assertEqual('<<', F('<<'))
    self.assertEqual('>>', F('>>'))
    self.assertEqual('[', F('['))
    self.assertEqual(']', F(']'))
    self.assertRaisesX(main.PdfTokenTruncated, F, '(foo')
    self.assertRaisesX(main.PdfTokenTruncated, F, '(foo\\)bar')
    self.assertEqual('<face654389210b7d>', F('< f\nAc\tE\r654389210B7d\f>'))
    self.assertEqual('<48656c6c6f2c20576f726c6421>', F('(Hello, World!)'))
    self.assertEqual('<2828666f6f2929296261725c>', F('(((foo))\\)bar\\\\)'))
    self.assertEqual('<410a420a430a440a0a45>', F('(A\rB\nC\r\nD\n\rE)'))
    self.assertEqual('<0a280d2900>', F('(\\n(\\r)\\0)'))
    self.assertEqual('<0a280a2900780a790a0a7a>', F('(\n(\r)\0x\r\ny\n\rz)'))
    self.assertEqual('(FooBarBaz)', F('(Foo\\\nBar\\\rBa\\\r\nz)'))
    self.assertEqual('<466f6f4261720a42617a>', F('(Foo\\\r\nBar\\\n\rBaz)'))
    self.assertEqual('<2829%s>' % ''.join(['%02x' % {13: 10}.get(i, i)
                                            for i in xrange(33)]),
                     F('(()%s)' % ''.join(map(chr, xrange(33)))))
    self.assertEqual('<face422829>', F('(\xfa\xCE\x42())'))
    self.assertEqual('<00210023>', F('(\0!\\0#)'))
    self.assertEqual('<073839380a>', F('(\78\98\12)'))
    self.assertEqual('(\x0501)', F('(\\501)'))
    self.assertEqual('<0a0a09080c>', F('(\n\r\t\b\f)'))
    self.assertEqual('<0a0d09080c>', F('(\\n\\r\\t\\b\\f)'))
    self.assertEqual('<236141>', F('(\\#\\a\\A)'))
    self.assertEqual('<61275c>', F("(a'\\\\)"))
    self.assertEqual('<314f5c60>', F('<\n3\t1\r4f5C6 >'))
    self.assertEqual('<0006073839050e170338043805380638073838380a3913391f39>',
                     F('(\0\6\7\8\9\05\16\27\38\48\58\68\78\88\129\239\379)'))
    self.assertEqual('<666f6f0a626172>', F('(foo\nbar)'))
    self.assertEqual('<666f6f0a626172>', F('(foo\\nbar)'))
    self.assertEqual('(foobar)', F('(foo\\\nbar)'))
    self.assertEqual('<0006073839050e170338043805380638073838380a3913391f39'
                     '043031053031063031073031>',
                     F('(\\0\\6\\7\\8\\9\\05\\16\\27\\38\\48\\58\\68\\78\\88'
                       '\\129\\239\\379\\401\\501\\601\\701)'))
    # PDF doesn't have \x
    self.assertEqual('(xfaxbCxDE\xf8)', F('(\\xfa\\xbC\\xDE\xF8)'))
    self.assertEqual('0', F('0'))
    self.assertEqual('.', F('.'))
    self.assertEqual('42', F('42'))
    self.assertEqual('42', F('42 '))

    # Different from RewriteToParsable.
    #self.assertEqual('0', F('00000 '))
    #self.assertEqual('0', F('+00000 '))
    #self.assertEqual('0', F('-00000 '))
    #self.assertEqual('0', F('00000.000 '))
    #self.assertEqual('0', F('+00000.000 '))
    #self.assertEqual('0', F('-00000.000 '))
    #self.assertEqual('12', F('00012 '))
    #self.assertEqual('12', F('+00012 '))
    #self.assertEqual('-12', F('-00012 '))
    #self.assertEqual('12', F('00012. '))
    #self.assertEqual('12', F('00012.000 '))
    #self.assertEqual('12', F('+00012.000 '))
    #self.assertEqual('-12', F('-12.000 '))
    #self.assertEqual('12.34', F('00012.340 '))
    #self.assertEqual('12.34', F('+00012.34 '))
    #self.assertEqual('-12.34', F('-12.340 '))
    #self.assertEqual('[ .34 -.34 .34 ]', F('[.34 -.34 +.34]'))
    #self.assertEqual('[ .34 -.34 .34 ]', F('[00.34 -00.34 +00.34]'))
    #self.assertEqual('[ 34 -34 34 ]', F('[34. -34. +34.]'))
    #self.assertEqual('[ 34 -34 34 ]', F('[0034. -0034. +0034.]'))
    #self.assertEqual('[ 34 -34 34 ]', F('[34.00 -34.00 +34.00]'))
    #self.assertEqual('[ 34 -34 34 ]', F('[0034.00 -0034.00 +0034.00]'))
    #self.assertEqual('[ 0 0 0 ]', F('[0. -0. +0.]'))
    #self.assertEqual('[ 0 0 0 ]', F('[000. -000. +000.]'))
    #self.assertEqual('[ 0 0 0 ]', F('[.0 -.0 +.0]'))
    #self.assertEqual('[ 0 0 0 ]', F('[.000 -.000 +.000]'))
    #self.assertEqual('[ 0 0 0 ]', F('[00.000 -00.000 +00.000]'))

    self.assertEqual('12 345 R', F(' 12 345 R '))

    end_ofs_out = []
    self.assertEqual('5 endobj', F(' 5 endobj\t', end_ofs_out=end_ofs_out))
    self.assertEqual([10], end_ofs_out)
    end_ofs_out = []
    self.assertEqual('5 endobj 6', F(' 5 endobj\t6', end_ofs_out=end_ofs_out))
    self.assertEqual([11], end_ofs_out)
    end_ofs_out = []
    self.assertEqual('5()endobj', F(' 5() endobj\t', end_ofs_out=end_ofs_out))
    self.assertEqual([12], end_ofs_out)
    self.assertRaisesX(main.PdfTokenParseError, F, '/#')
    self.assertRaisesX(main.PdfTokenParseError, F, '/ ')
    self.assertRaisesX(main.PdfTokenParseError, F, '/')
    self.assertRaisesX(main.PdfTokenParseError, F, '/%')
    self.assertEqual('/#2A', F('/*'))
    self.assertEqual('/STROZ#2F', F('/STR#4fZ#2f'))
    self.assertEqual('/STROZ', F('/STR#4FZ\r\n\t\t\t \t'))
    end_ofs_out = []
    self.assertEqual('5/STROZ hi',
                     F(' 5 /STR#4FZ hi\r\n\t\t\t \t',
                       end_ofs_out=end_ofs_out))
    self.assertEqual([21], end_ofs_out)
    self.assertEqual('5 STROZ', F(' 5 STR#4FZ\r\n\t\t\t \t'))
    # It could be PdfTokenTruncated as well.
    self.assertRaisesX(main.PdfTokenParseError, F, '#')
    self.assertRaisesX(main.PdfTokenParseError, F, '()#')
    end_ofs_out = []
    self.assertEqual('/Size 42', F('/Size 42 ', end_ofs_out=end_ofs_out))
    self.assertEqual([9], end_ofs_out)
    self.assertEqual('[/Size 42]', F('[/Size 42]'))
    self.assertEqual('<</Size 42>>', F('<</Size 42>>'))
    self.assertEqual('[true 42]', F('[true\n%korte\n42]'))
    self.assertEqual('[true 42]', F('[true%korte\n42]'))
    self.assertEqual('hello world', F('hello \n\t world\n\t'))
    self.assertEqual('null false', F('null \n\t false\n\t'))
    # This is invalid PDF (null is not a name), but we don't catch it.
    self.assertEqual('<<null false>>', F('\r<<null \n\t false\n\t>>'))
    self.assertEqual('<<true>>', F('<<true>>'))
    self.assertEqual('true foo bar', F('true foo bar'))
    self.assertEqual('true foo', F('true foo'))
    self.assertEqual('<68656c296c6f0a0877286f72296c64>',
                     F('(hel\)lo\n\bw(or)ld)'))
    self.assertRaisesX(main.PdfTokenTruncated, F, '(hel\)lo\n\bw(orld)')
    self.assertEqual('[<68656c296c6f0a0877286f72296c64>]',
                     F(' [ (hel\\051lo\\012\\010w\\050or\\051ld) ]'))
    self.assertRaisesX(main.PdfTokenTruncated,
                     F, ' [ (hel\\051lo\\012\\010w\\050or\\051ld) ]<')
    self.assertEqual('<<<5c>', F('<< <5C>'))
    self.assertEqual('<5c>>>', F('<5C> >>'))
    self.assertEqual('()<<<5c>', F('()<< <5C>'))
    self.assertEqual('()<5c>>>', F('()<5C> >>'))
    self.assertRaisesX(main.PdfTokenParseError, F, '{')
    self.assertRaisesX(main.PdfTokenParseError, F, '}')
    self.assertRaisesX(main.PdfTokenParseError, F, '{}')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<')
    self.assertRaisesX(main.PdfTokenTruncated, F, '< ')
    self.assertRaisesX(main.PdfTokenParseError, F, '>')
    self.assertRaisesX(main.PdfTokenParseError, F, '> >')
    self.assertRaisesX(main.PdfTokenParseError, F, '>>>')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<<<')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<<<ff')
    self.assertRaisesX(main.PdfTokenParseError, F, '<<<foo')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<<<')
    self.assertRaisesX(main.PdfTokenParseError, F, '()>')
    self.assertRaisesX(main.PdfTokenParseError, F, '()< <')
    self.assertRaisesX(main.PdfTokenParseError, F, '()> >')
    self.assertRaisesX(main.PdfTokenParseError, F, '()>>>')
    self.assertRaisesX(main.PdfTokenTruncated, F, '()<<<')
    self.assertEqual('[>>', F('[ >>'))
    self.assertRaisesX(main.PdfTokenTruncated,
                      F, '[ (hel\\)lo\\n\\bw(or)ld) <')
    self.assertRaisesX(main.PdfTokenTruncated, F, '<\n3\t1\r4f5C5')
    self.assertRaisesX(main.PdfTokenParseError, F, '<\n3\t1\r4f5C5]>')
    # 'stream\r' is truncated, we're waiting for 'stream\r\n'.
    self.assertEqual('<<>>stream', F('<< >>stream\r'))
    self.assertEqual('<<>>blah', F('<<>>blah\r'))
    self.assertEqual('<<>>stream', F('<<>>stream\n'))
    self.assertEqual('<<>>stream', F('<<>>stream\r\n'))
    self.assertEqual('<</Type/Catalog/Pages 3 0 R>>',
                     F('<</Type /Catalog /Pages 3 0 R\n>>'))
    self.assertEqual('42 true R', F(' 42 true R'))
    eo = []
    self.assertEqual('442 43 R', F('\t442%foo\r43\fR   ', end_ofs_out=eo))
    self.assertEqual(16, eo[0])  # spaces not included
    eo = []
    self.assertEqual('442 43 R/n', F('\t442%foo\r43\fR/n', end_ofs_out=eo))
    self.assertEqual('+442 +43 R/n', F('\t+442%foo\r+43\fR/n', end_ofs_out=eo))
    self.assertEqual(15, eo[0])  # spaces not included
    self.assertEqual('<</Pages -333 -1 R>>', F('<</Pages -333 -1 R\n>>'))
    self.assertEqual('<</Pages 0 55 R>>', F('<</Pages 0 55 R\n>>'))

    self.assertEqual('<313220332052>', F('(12 3 R)'))
    # It's important that this returns a hex string, so that it doesn't trigger a false match on
    # PDF_SIMPLE_REF_RE.
    self.assertEqual('<61312031322030205273>', F('(a1 12 0 Rs)'))

    # !!! Copy tests from testPdfObjParse.

  def testParseTokensToSafeComplicated(self):
    self.testParseTokensToSafeSimple(is_simple_ok=False)

  def testPdfUnsafeRegexpSubsets(self):
    a_re = main.PdfObj.PDF_TOKENS_UNSAFE_CHARS_RE
    b_re = main.PdfObj.PDF_SAFE_KEEP_HEX_ESCAPED_RE
    self.assertFalse(a_re.match('*'))
    self.assertTrue(b_re.match('*'))
    for i in xrange(256):  # Test that b_re is a subset of a_re.
      self.assertTrue(not a_re.match(chr(i)) or b_re.match(chr(i)), i)

    a_re = main.PdfObj.PDF_STRING_UNSAFE_CHAR_RE
    b_re = main.PdfObj.PDF_SAFE_KEEP_HEX_ESCAPED_RE
    self.assertFalse(a_re.match('*'))
    self.assertTrue(b_re.match('*'))
    for i in xrange(256):  # Test that b_re is a subset of a_re.
      self.assertTrue(not a_re.match(chr(i)) or b_re.match(chr(i)), i)

    a_re = main.PdfObj.PDF_TOKENS_UNSAFE_CHARS_RE
    b_re = main.PdfObj.PDF_STRING_UNSAFE_CHAR_RE
    self.assertFalse(a_re.match('('))
    self.assertTrue(b_re.match('('))
    for i in xrange(256):  # Test that b_re is a subset of a_re.
      self.assertTrue(not a_re.match(chr(i)) or b_re.match(chr(i)), i)

  def testPdfObjGetSet(self):
    obj = main.PdfObj('42 0 obj<</Foo(hi)>>\t\f\rendobj junk stream\r\n')
    self.assertEqual('<</Foo(hi)>>', obj._head)
    self.assertEqual(None, obj._cache)
    self.assertEqual('<</Foo(hi)>>', obj.head)
    self.assertEqual(None, obj._cache)
    self.assertEqual(None, obj.Get('Bar'))
    self.assertEqual(None, obj._cache)
    self.assertEqual(None, obj.Get('Fo'))
    self.assertEqual({'Foo': '<6869>'}, obj._cache)
    self.assertEqual('<6869>', obj.Get('Foo'))
    self.assertEqual('<</Foo(hi)>>', obj._head)
    obj.Set('Foo', ' \t<6869>\f \r ')
    self.assertEqual('<6869>', obj.Get('Foo'))
    self.assertEqual({'Foo': '<6869>'}, obj._cache)
    self.assertEqual('<</Foo(hi)>>', obj._head)
    obj.Set('Foo', ' \t(hi)\f \r ')
    self.assertEqual('<6869>', obj.Get('Foo'))
    self.assertEqual({'Foo': '<6869>'}, obj._cache)
    self.assertEqual('<</Foo(hi)>>', obj._head)  # still valid
    obj.Set('Foo', '(*)')
    self.assertEqual('<2a>', obj.Get('Foo'))
    self.assertEqual(None, obj._head)
    self.assertEqual({'Foo': '<2a>'}, obj._cache)
    obj.Set('Bar', '0042')
    self.assertEqual({'Foo': '<2a>', 'Bar': 42}, obj._cache)
    self.assertEqual(None, obj._head)
    self.assertEqual('<</Bar 42/Foo(*)>>', obj.head)
    self.assertEqual('<</Bar 42/Foo(*)>>', obj._head)
    obj.Set('Bar', 'null')
    self.assertEqual({'Foo': '<2a>', 'Bar': 'null'}, obj._cache)
    self.assertEqual(None, obj._head)
    self.assertEqual('<</Bar null/Foo(*)>>', obj.head)
    self.assertEqual('<</Bar null/Foo(*)>>', obj._head)
    obj.Set('Bar', None, do_keep_null=True)
    self.assertEqual({'Foo': '<2a>', 'Bar': 'null'}, obj._cache)
    self.assertEqual('<</Bar null/Foo(*)>>', obj._head)
    obj.Set('Bar', None)
    self.assertEqual({'Foo': '<2a>'}, obj._cache)
    self.assertEqual(None, obj._head)
    self.assertEqual(len('<</Foo(*)>>') + 40, obj.size)
    self.assertEqual('<</Foo(*)>>', obj._head)
    self.assertEqual('<</Foo(*)>>', obj.head)
    obj.head = '<</Foo(*)>>'
    self.assertEqual({'Foo': '<2a>'}, obj._cache)
    obj.head = '<</Foo<2a>>>'  # invalidates the cache
    self.assertEqual(None, obj._cache)
    self.assertEqual(None, obj.Get('Food'))
    self.assertEqual(None, obj._cache)
    self.assertEqual('<2a>', obj.Get('Foo'))
    self.assertEqual({'Foo': '<2a>'}, obj._cache)

  def testFindEqclassesAllEquivalent(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/P 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual({3: ('<</S(q)/P 3 0 R>>', None)}, new_objs)

  def testFindEqclassesAllEquivalentAndUndefined(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = main.PdfObj('0 0 obj<</S(q)/P 2 0 R /U 6 0 R>>endobj')
    pdf.objs[2] = main.PdfObj('0 0 obj<</S(q)/P 1 0 R /U 7 0 R>>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R /U 8 0 R>>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/P 3 0 R /U 9 0 R>>endobj')
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual({1: ('<</S(q)/P 1 0 R/U null>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsByHead(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsWithTrailer(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 3 0 R]>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = main.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[3 0 R 4 0 R 3 0 R 4 0 R 3 0 R]>>', None),
         10: ('[10 0 R]', None),
         12: ('[10 0 R]', 'blah'),
         3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsByOrder(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = main.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = main.PdfObj('0 0 obj<</P 1 0 R/S(q)>>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R>>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</P 3 0 R  /S<71>>>endobj')
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None),
         2: ('<</P 1 0 R/S(q)>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsByStream(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = main.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = main.PdfObj('0 0 obj<</S(q)/P 1 0 R >>endobj')
    pdf.objs[2].stream = 'foo'
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    pdf.objs[4].stream = 'foo'
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None),
         2: ('<</S(q)/P 1 0 R>>', 'foo')}, new_objs)

  def testFindEqclassesAllDifferentBecauseOfStream(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = main.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = main.PdfObj('0 0 obj<</S(q)/P 1 0 R >>endobj')
    pdf.objs[2].stream = 'foo'
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    pdf.objs[4].stream = 'fox'
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None), 2: ('<</S(q)/P 1 0 R>>', 'foo'),
         3: ('<</S(q)/P 4 0 R>>', None), 4: ('<</S(q)/P 3 0 R>>', 'fox')},
        new_objs)

  def testFindEqclassesTwoGroupsWithTrailer(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 3 0 R]>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = main.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(pdf.objs)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[3 0 R 4 0 R 3 0 R 4 0 R 3 0 R]>>', None),
         10: ('[10 0 R]', None),
         12: ('[10 0 R]', 'blah'),
         3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsWithTrailerUnused(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 4 0 R]>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = main.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[3 0 R 4 0 R 3 0 R 4 0 R 4 0 R]>>', None),
         3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsWithTrailerRenumber(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 4 0 R]>>endobj')
    pdf.objs[5] = main.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = main.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = main.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = main.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = main.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True, do_renumber=True)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[2 0 R 1 0 R 2 0 R 1 0 R 1 0 R]>>', None),
         2: ('<</S(q)/P 1 0 R>>', None),
         1: ('<</S(q)/Q 2 0 R>>', None)}, new_objs)

  def testFindEqclassesCircularReferences(self):
    pdf = main.PdfData()
    # The Rs are needed in the trailer, otherwise objects would be discarded.
    pdf.trailer = main.PdfObj(
        '0 0 obj<<4 0 R 5 0 R 9 0 R 10 0 R>>endobj')
    pdf.objs[4] = main.PdfObj(
        '0 0 obj<</Parent  1 0 R/Type/Pages/Kids[9 0 R]/Count 1>>endobj')
    pdf.objs[5] = main.PdfObj(
        '0 0 obj<</Parent 1  0 R/Type/Pages/Kids[10 0 R]/Count 1>>endobj')
    pdf.objs[9] = main.PdfObj(
        '0 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]'
        '/Parent 4 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>'
        '/Contents 3 0 R>>endobj')
    pdf.objs[10] = main.PdfObj(
        '10 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]'
        '/Parent 5 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>'
        '/Contents 3 0 R>>endobj')
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True, do_renumber=True)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</Parent null/Type/Pages/Kids[2 0 R]/Count 1>>', None),
         2: ('<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]'
             '/Parent 1 0 R/Resources<</XObject<</S null>>'
             '/ProcSet[/PDF/ImageB]>>/Contents null>>', None),
         'trailer': ('<<1 0 R 1 0 R 2 0 R 2 0 R>>', None)}, new_objs)

  def testFindEqclassesString(self):
    pdf = main.PdfData()
    pdf.trailer = main.PdfObj(
        '0 0 obj<</A[3 0 R]>>endobj')
    pdf.objs[3] = main.PdfObj('0 0 obj<</A()/B<>/C(:)/D<3a3A4>>>endobj')
    pdf.objs['trailer'] = pdf.trailer
    new_objs = main.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True, do_renumber=True)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[1 0 R]>>', None),
         1: ('<</A()/B()/C(:)/D(::@)>>', None)}, new_objs)

  def testParseAndSerializeCffDict(self):
    cff_dict = {
        12000: [394], 1: [391], 2: [392], 3: [393], 12004: [0],
        5: [0, -270, 812, 769],
        12007: ['0.001', 0, '0.000287', '0.001', 0, 0], 15: [281], 16: [245],
        17: [350], 18: [21, 6489], 12003: [0]
    }
    cff_dict_b = dict(cff_dict)
    cff_dict_b[12007] = ['.001', 0, '287e-6', '.001', 0, 0]
    cff_str1 = ('f81b01f81c02f81d038bfba2f9c0f99505f81e0c008b0c038b0c'
                '041e0a001f8b1e0a000287ff1e0a001f8b8b0c07a01c195912f7'
                'f211f7ad0ff78910'.decode('hex'))
    cff_str2 = ('f81b01f81c02f81d038bfba2f9c0f99505f7ad0ff78910f7f211'
                'a01c195912f81e0c008b0c038b0c041ea001ff8b1e287c6f1ea0'
                '01ff8b8b0c07'.decode('hex'))
    self.assertEqual(cff_dict_b, cff.ParseCffDict(cff_str1))
    self.assertEqual(cff_dict_b, cff.ParseCffDict(cff_str2))
    self.assertEqual(cff_str2, cff.SerializeCffDict(cff_dict))

  def testParseCffDifferent(self):
    # Different integer representations have different length.
    self.assertEqual({17: [410]}, cff.ParseCffDict(
        '\x1d\x00\x00\x01\x9a\x11'))
    self.assertEqual({17: [410]}, cff.ParseCffDict(
        '\xf8.\x11'))
    self.assertEqual('\xf8.\x11', cff.SerializeCffDict(
        {17: [410]}))

    # The same, but longer.
    data = 'XY%sZT' % (
        #'\xf8!\x00\xf8"\x01\xf8#\x02\xf8#\x03\xf8\x18\x04<\xfbl\xfa\x85\xfa)'
        #'\x05\xf7\x87\x0f\xf7\x83\x10\xf8.\x11\x91\x1c$\xcb\x12\x1e\n\x00\x1f'
        #'\x8b\x8b\x1e\n\x00\x1f\x8b\x8b\x0c\x07')
        '\xf8!\x00\xf8"\x01\xf8#\x02\xf8#\x03\xf8\x18\x04<\xfbl\xfa\x85\xfa)'
        '\x05\x1e\n\x00\x1f\x8b\x8b\x1e\n\x00\x1f\x8b\x8b\x0c\x07\x1d\x00\x00'
        '\x00\xf3\x0f\x1d\x00\x00\x00\xef\x10\x1d\x00\x00\x01\x9a\x11\x91\x1d'
        '\x00\x00$\xcb\x12')
    expected_cff_dict = {
        0: [397], 1: [398], 2: [399], 3: [399], 4: [388],
        5: [-79, -216, 1009, 917], 12007: ['0.001', 0, 0, '0.001', 0, 0],
        15: [243], 16: [239], 17: [410], 18: [6, 9419]}
    i = 2
    j = len(data) - 2
    cff_dict = cff.ParseCffDict(data=data, start=i, end=j)
    cff_ser = cff.SerializeCffDict(cff_dict=cff_dict)
    cff_dict2 = cff.ParseCffDict(cff_ser)
    cff_ser2 = cff.SerializeCffDict(cff_dict=cff_dict2)
    self.assertEqual(cff_dict, cff_dict2)
    self.assertEqual(cff_ser, cff_ser2)
    # We could emit an optiomal serialization.
    self.assertTrue(len(cff_ser) < len(data[i : j]))

  def testFixPdfFromMultivalent(self):
    e = main.PdfData.FixPdfFromMultivalent
    s = ('%PDF-1.5\n'
         '%\x90\x84\x86\x8f\n'
         '1 0 obj<</Type/Pages/Kids[5 0 R]/MediaBox[0 0 419 534]/Count 1>>\n'
         'endobj\n'
         '2 0 obj<</Type   /Catalog/Pages 1 0 R>>\n'
         'endobj\n'
         '3 0 obj<</Length 30>>stream\n'
         '\n'
         'q\n'
         '419 0 0 534 0 0 cm /S Do\n'
         'Q\n'
         '\n'
         'endstream\n'
         'endobj\n'
         '4 0 obj<</Subtype/ImagE/Width 419/Height    534/FilteR/FlateDecode'
             '/Interpolate false/BitsPerComponent 1/ColorSpace/DeviceGray'
             '/Length 4/Filter/JPXDecode>>stream\n'
         'BLAH\n'
         'endstream\n'
         'endobj\n'
         '5 0 obj<</Type/Page/Contents 3 0 R/Resources<</XObject<</S 4 0 R>>>>'
             '/Parent 1 0 R>>\n'
         'endobj\n'
         '6 0 obj<</Type/XRef/W[0 2 0]/Size 7/Root 2 0 R/Compress<<'
             '/LengthO 7677/SpecO/1.2>>/ID['
             '(\x87\xfa\x8d\xcdc\x80\xf4y\xa9\x9e\tI\xa0b\xad3)'
             '(\x8d\\\\\x87\xa1\xbb\t\xae\xe6sU<\x10\x90*I\xf1)'
             ']/Length 14>>stream\n'
         '\x00\x00\x00\x0f\x00W\x00\x86\x00\xd2\x01\x88\x01\xe3\n'
         'endstream\n'
         'endobj\n'
         'startxref\n'
         '483\n'
         '%%EOF\n')
    t = ('%PDF-1.5\n'
         '%\xd0\xd4\xc5\xd0\n'
         '1 0 obj\n'
         '<</Type/Pages/Kids[5 0 R]/MediaBox[0 0 419 534]/Count 1>>endobj\n'
         '2 0 obj\n'
         '<</Type/Catalog/Pages 1 0 R>>endobj\n'
         '3 0 obj\n'
         '<</Length 30>>stream\n'
         '\n'
         'q\n'
         '419 0 0 534 0 0 cm /S Do\n'
         'Q\n'
         'endstream endobj\n'
         '4 0 obj\n'
         '<</BitsPerComponent 1/ColorSpace/DeviceGray/Filter/FlateDecode'
             '/Height 534/Interpolate false/Length 4/Subtype/Image/Width 419'
             '>>stream\n'
         'BLAHendstream endobj\n'
         '5 0 obj\n'
         '<</Type/Page/Contents 3 0 R/Resources<</XObject<</S 4 0 R>>>>'
             '/Parent 1 0 R>>endobj\n'
         '6 0 obj\n'
         '<</Length 14/Root 2 0 R/Size 7/Type/XRef/W[0 2 0]>>stream\n'
         '\x00\x00\x00\x0f\x00W\x00\x83\x00\xcf\x01q\x01\xcc'
             'endstream endobj\n'
         'startxref\n'
         '460\n'
         '%%EOF\n')
    output = []
    e(s, output=output, do_generate_object_stream=False)
    self.assertEqual(t, ''.join(output))
    # !! test with xref ... trailer <</Size 6/Root 2 0 R/Compress<</LengthO
    # 7677/SpecO/1.2>>/ID[(...)(...)]>> ... startxref

  def testPermissiveZlibDecompress(self):
    e = main.PermissiveZlibDecompress
    data = 'Hello, World!' * 42
    compressed = zlib.compress(data, 9)
    self.assertEqual(data, e(compressed))
    self.assertEqual(data, e(compressed[:-1]))
    self.assertEqual(data, e(compressed[:-2]))
    self.assertEqual(data, e(compressed[:-3]))
    self.assertEqual(data, e(compressed[:-4]))
    self.assertRaisesX(zlib.error, e, compressed[:-5])

  def testResolveReferencesChanged(self):
    def NewObj(head, stream=None, do_compress=False):
      obj = main.PdfObj(None)
      if stream is None:
        obj.head = head or ''
      else:
        if not isinstance(stream, str):
          raise TypeError
        obj.head = head or '<<>>'
        if do_compress:
          obj.SetStreamAndCompress(stream)
        else:
          obj.Set('Length', len(stream))
          obj.stream = stream
      return obj

    objs = {
        12: NewObj('foo  bar'),
        13: NewObj(' 12  0  R\t'),
        14: NewObj('\0(12  0  R \\040)'),
        15: NewObj('foo  bar %skip'),
        16: NewObj('15 0 R  bat'),
        17: NewObj('/foobar'),
        18: NewObj('\t42  '),
        21: NewObj('9 0 R'),
        31: NewObj('<</Foo 32 0 R>>'),
        32: NewObj('<</Bar 31 0 R>>'),
        33: NewObj('<</Bar 33 0 R>>'),
        41: NewObj('', 'hello'),
        42: NewObj('', 'x' * 42, do_compress=True),
    }
    self.assertTrue('/Length 5' in objs[41].head)
    self.assertTrue('/Filter/FlateDecode' in objs[42].head)
    self.assertFalse('/Length 42' in objs[42].head)
    e = main.PdfObj.ResolveReferencesChanged
    self.assertEqual(('/FooBar  true', False), e('/FooBar  true', objs))
    self.assertEqual(('/FooBaR  true', False), e('/FooBaR  true', objs))
    self.assertRaisesX(main.PdfTokenParseError, e, '12 0 R', objs)
    self.assertEqual(('/foobar', True), e('17 0 R', objs))
    self.assertEqual((42, True), e('18 0 R', objs))
    self.assertEqual(('\rfoo  bar\t', True), e('\r12 0 R\t', objs))
    self.assertEqual(('[true\ffoo  bar false\nfoo  bar]', True),
                     e('[true\f12 0 R false\n12 0 R]', objs))
    self.assertEqual(('foo  bar<>', True), e('12 0 R<>', objs))
    # A comment or a (string) in the referrer triggers full compression.
    self.assertEqual(('foo bar()', True), e('%9 0 R\n12 0 R<>', objs))
    # A `(string)' in the referrer triggers full compression.
    self.assertEqual(('<39203020525b205d>foo bar', True),
                     e('(9 0 R[\\040])12 0 R', objs))
    self.assertRaisesX(main.PdfReferenceTargetMissing, e, '98 0 R', objs)
    self.assertRaisesX(main.PdfReferenceTargetMissing, e, '21 0 R', objs)
    self.assertRaisesX(main.PdfTokenParseError, e, '0 0 R', objs)
    self.assertRaisesX(main.PdfTokenParseError, e, '-1 0 R', objs)
    self.assertRaisesX(main.PdfTokenParseError, e, '1 12 R', objs)
    self.assertRaisesX(main.PdfReferenceRecursiveError, e, '31 0 R', objs)
    self.assertRaisesX(main.PdfReferenceRecursiveError, e, '32 0 R', objs)
    self.assertRaisesX(main.PdfReferenceRecursiveError, e, '33 0 R', objs)
    self.assertEqual(('(13  0 R)', False), e('(13  0 R)', objs))
    self.assertEqual(('<</A foo  bar>>', True), e('<</A 13  0 R>>', objs))
    self.assertEqual(('<313220302020522000>', True), e('(12 0  R \\000)', objs))
    self.assertEqual(('foo bar  bat   baz', True), e('16 0 R   baz', objs))
    # Unexpected stream.
    self.assertRaisesX(main.UnexpectedStreamError, e, '41 0 R', objs)
    self.assertRaisesX(main.UnexpectedStreamError, e, '42 0 R', objs)
    self.assertEqual(('<68656c6c6f>', True),
                     e('41 0 R', objs, do_strings=True))
    self.assertEqual(('<787878787878787878787878787878787878787878787878787878787878787878787878787878787878>', True),
                      e('42 0 R', objs, do_strings=True))
    self.assertEqual(
        ('/ColorSpace[/Indexed/DeviceRGB 14 (%s)]' % ('x' * 42), True),
        e('/ColorSpace[/Indexed/DeviceRGB 14 42 0 R]', objs, do_strings=True))
    self.assertEqual((None, False), e(None, objs))
    self.assertEqual((True, False), e(True, objs))
    self.assertEqual((False, False), e(False, objs))
    self.assertEqual((42, False), e(42, objs))
    self.assertEqual((42.5, False), e(42.5, objs))

  def testParseTokenList(self):
    f = main.PdfObj.ParseTokenList
    self.assertEqual(repr([42, True]), repr(f('42 true')))
    self.assertEqual([], f(''))
    self.assertEqual([], f(' \t'))
    self.assertEqual(['<666f6f>', 6, 7], f(' \n\r(foo)\t6%foo\n7'))
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7(')
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7[')
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7<<')
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7)')
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7]')
    self.assertRaisesX(main.PdfTokenParseError, f, ' \n\r(foo)\t6\f7>>')
    end_ofs_ary = []
    self.assertEqual(['<666f6f>', 6, 7],
                     f(' \n\r(foo)\t6\f7\f', 3, end_ofs_out=end_ofs_ary))
    self.assertEqual([len(' \n\r(foo)\t6\f7')], end_ofs_ary)  # No whitespace.
    end_ofs_ary = []
    self.assertEqual(['<666f6f>', 6, 7],
                     f(' \n\r(foo)\t6\f7\f', end_ofs_out=end_ofs_ary))
    self.assertEqual([len(' \n\r(foo)\t6\f7')], end_ofs_ary)  # No whitespace.
    self.assertEqual(['<666f6f>', 6], f(' \n\r(foo)\t6(', 2))
    self.assertEqual(['<666f6f>'], f(' \n\r(foo)]', 1))
    self.assertEqual([], f('<<', 0))
    self.assertEqual(['<<>>', 51], f('<<%]\r>>51'))
    self.assertEqual(['[]', -3], f('[%<<\n]-3'))

    self.assertRaisesX(main.PdfTokenParseError, f, '//')
    self.assertRaisesX(main.PdfTokenParseError, f, '/')
    self.assertRaisesX(main.PdfTokenParseError, f, '/#xy')
    self.assertRaisesX(main.PdfTokenParseError, f, '/#')
    self.assertEqual(['/pedal.#2A', '/pedal.#2A'], f('/pedal.*/pedal.#2a'))
    self.assertEqual(['/#2F#23'], f('/#2f#23'))

  def testPdfToPsName(self):
    f = main.PdfObj.PdfToPsName
    self.assertEqual('/foo!', f('/foo#21'))
    self.assertEqual('pedal.*', f('pedal.*'))
    self.assertEqual('/pedal.*', f('/pedal.*'))
    self.assertEqual('/pedal.*', f('/pedal.#2A'))
    self.assertEqual('/pedal.*', f('/pedal.#2a'))
    self.assertEqual('pedal.*', f('pedal.#2A'))
    self.assertEqual('/pedal.*B+', f('/pedal.#2AB#2b'))
    self.assertEqual('/pedal.#2A', f('/peda#6c.#232A'))
    self.assertEqual('/\xFEeD', f('/#fEeD'))
    self.assertRaisesX(ValueError, f, '')
    self.assertRaisesX(ValueError, f, '/')
    self.assertRaisesX(main.PdfTokenParseError, f, '//')
    self.assertRaisesX(main.PdfTokenParseError, f, '//foo')
    self.assertRaisesX(main.PdfTokenParseError, f, '/#')
    # Starts with double /. Will raise: Char not allowed in PostScript name
    self.assertRaisesX(ValueError, f, '/#2F')
    self.assertRaisesX(ValueError, f, '/foo#20')  # PDF_NONNAME_CHARS.
    self.assertRaisesX(ValueError, f, '/foo#28')  # PDF_NONNAME_CHARS.
    self.assertRaisesX(ValueError, f, '/foo#25')  # PDF_NONNAME_CHARS.
    self.assertRaisesX(ValueError, f, 'foo/bar')
    self.assertRaisesX(ValueError, f, '/foo#7b#7d')
    self.assertRaisesX(ValueError, f, 'foo#7b#7d', is_nonname_char_ok=True)
    self.assertEqual('<666f6f7b7d>cvn',
                     f('/foo#7b#7d', is_nonname_char_ok=True))

  def testIsFontBuiltInEncodingUsed(self):
    f = main.PdfData.IsFontBuiltInEncodingUsed
    self.assertEqual(True, f(None))
    self.assertEqual(None, f(True))
    self.assertEqual(None, f(42))
    self.assertRaisesX(ValueError, f, '42 0 R')
    self.assertEqual(None, f('42 0 R foo'))
    self.assertEqual(False, f('/WinAnsiEncoding'))
    self.assertEqual(None, f('[]'))
    self.assertRaisesX(main.PdfTokenParseError, f, '<<')
    self.assertEqual(False, f('<</BaseEncoding/MacRomanEncoding>>'))
    self.assertEqual(
        False, f('<</BaseEncoding/MaxRomanEncoding/Differences[5/foo]>>'))
    self.assertEqual(True, f('<<>>'))
    self.assertEqual(True, f('<</Differences[5/foo]>>'))

  def testClassifyImageDecode(self):
    f = main.PdfObj.ClassifyImageDecode
    self.assertEqual('normal', f(None, 0))
    self.assertEqual('non-array', f(42, 0))
    self.assertEqual('non-array', f('', 0))
    self.assertEqual('non-float', f('[/a 5]', 0))
    self.assertEqual('empty', f('[]', 0))
    self.assertEqual('empty', f('[\r]', 0))
    self.assertEqual('inverted', f('[  1\t0\n]', 0))
    self.assertEqual('normal', f('[  0\f1\n]', 0))
    self.assertEqual('normal', f('[  0\f1\0 0 1\n]', 0))
    self.assertEqual('inverted', f('[  7\t0\n]', 3))
    self.assertEqual('normal', f('[  0\f7\n]', 3))
    self.assertEqual('strange', f('[  7\t0\n]', 4))
    self.assertEqual('strange', f('[  0\f7\n]', 4))
    self.assertEqual('inverted', f('[1.0 0 1 0.]', 0))
    self.assertRaisesX(main.PdfTokenParseError, f, '[1.0 0 1 0e5]', 0)
    self.assertRaisesX(main.PdfTokenParseError, f, '[1.0 0 1 0e5 1]', 0)
    self.assertEqual('strange', f('[1.0 0 1 .0 1]', 0))
    self.assertEqual('strange', f('[0]', 0))
    self.assertEqual('strange', f('[1 0 0 1]', 0))

  def testGenerateImageDecode(self):
    f = main.PdfObj.GenerateImageDecode
    self.assertEqual('[]', f(0, 0, 0))
    self.assertEqual('[0 1]', f(False, 1, 0))
    self.assertEqual('[0 1 0 1 0 1]', f(False, 3, 0))
    self.assertEqual('[0 15 0 15 0 15]', f(False, 3, 4))
    self.assertEqual('[15 0 15 0]', f(True, 2, 4))

  def testMergeBaseEncodingToFontObj(self):
    base_encoding = (
        ['/.notdef'] * 65 +
        ['/AAA', '/B', '/C', '/D', '/E', '/F', '/G', '/H', '/I', '/J', '/K', '/L',
         '/M', '/N', '/O', '/P'] +
        ['/.notdef'] * 175)
    objs = {}

    def F(obj_str):
      font_obj = main.PdfObj(obj_str)
      main.PdfData._MergeBaseEncodingToFontObj(
          font_obj, base_encoding, objs)
      return font_obj.Get('Encoding')

    # Unchanged.
    self.assertEqual('/Foo', F('1 0 obj<</Encoding/Foo>>endobj'))
    self.assertEqual('<</Differences[65/AAA]/BaseEncoding/WinAnsiEncoding>>',
                     F('1 0 obj<<>>endobj'))
    # Unchanged.
    self.assertEqual('<</BaseEncoding/Foo>>',
                     F('1 0 obj<</Encoding<</BaseEncoding  /Foo>>>>endobj'))
    # Unchanged.
    self.assertEqual('<</BaseEncoding/Foo'
                     '/Differences[66/BB/CC 100/dd 101/ee]>>',
                     F('1 0 obj<</Encoding<</BaseEncoding/Foo/Differences'
                       '[66/BB/CC 100/dd  101/ee]>>>>endobj'))
    self.assertEqual('<</Differences[65/AAA/BB/CC'
                     '/D/E/F/G/H/I/J/K/L/M/N/O/P 100/dd/ee]>>',
                     F('1 0 obj<</Encoding<</Differences'
                       '[66/BB/CC 100/dd 101/ee]>>>>endobj'))

  def testShellQuoteUnix(self):
    F = main.ShellQuoteUnix
    self.assertEqual("''", F(''))
    self.assertEqual('/usr/BIN/i686-w64-mingw32-g++',
                     F('/usr/BIN/i686-w64-mingw32-g++'))
    self.assertEqual('_.,:', F('_.,:'))
    self.assertEqual("'Hello, World!'", F('Hello, World!'))
    self.assertEqual("'foo\'\\\'\'b\'\\\'\'ar\\baz\"x\\\"y\\\\'",
                     F('foo\'b\'ar\\baz"x\\"y\\\\'))
    self.assertEqual("' '", F(' '))
    self.assertEqual("'\t'", F('\t'))
    self.assertEqual("'%PROMPT%'", F('%PROMPT%'))
    self.assertEqual("'\"'", F('"'))
    self.assertEqual("'<'", F('<'))
    self.assertEqual("'>'", F('>'))
    self.assertEqual("'&'", F('&'))
    self.assertEqual("'|'", F('|'))
    self.assertEqual("'\\'", F('\\'))
    self.assertEqual("'\\\\'", F('\\\\'))
    self.assertEqual("'C:\\pdfsizeopt\\pdfsizeopt.exe'",
                     F('C:\\pdfsizeopt\\pdfsizeopt.exe'))
    self.assertEqual("'|\\'", F('|\\'))

  def testShellQuoteWindows(self):
    F = main.ShellQuoteWindows
    self.assertEqual('""', F(''))
    self.assertEqual('/usr/BIN/i686-w64-mingw32-g++',
                     F('/usr/BIN/i686-w64-mingw32-g++'))
    self.assertEqual('_.,:', F('_.,:'))
    self.assertEqual('"Hello, World!"', F('Hello, World!'))
    self.assertEqual('"foo\'b\'ar\\baz\\"x\\\\\\"y\\\\\\\\"',
                     F('foo\'b\'ar\\baz"x\\"y\\\\'))
    self.assertEqual('" "', F(' '))
    self.assertEqual('"\t"', F('\t'))
    self.assertEqual('"%PROMPT%"', F('%PROMPT%'))
    self.assertEqual('"\\""', F('"'))
    self.assertEqual('"<"', F('<'))
    self.assertEqual('">"', F('>'))
    self.assertEqual('"&"', F('&'))
    self.assertEqual('"|"', F('|'))
    self.assertEqual('\\', F('\\'))
    self.assertEqual('\\\\', F('\\\\'))
    self.assertEqual('C:\\pdfsizeopt\\pdfsizeopt.exe',
                     F('C:\\pdfsizeopt\\pdfsizeopt.exe'))
    self.assertEqual('"|\\\\"', F('|\\'))

  def testRedirectOutputUnix(self):
    F = main.RedirectOutputUnix
    self.assertEqual('exec>&2;\nfoo bar  baz\nby\t', F('\nfoo bar  baz\nby\t'))
    self.assertEqual('exec 2>&1;\nfoo bar  baz\nby>o\t',
                     F('\nfoo bar  baz\nby>o\t', mode=True))

  def testRedirectOutputWindows(self):
    F = main.RedirectOutputWindows
    self.assertEqual('foo bar  baz>&2\nbye>&2', F('\nfoo bar  baz\nbye\t'))
    self.assertEqual('foo bar  baz>&2', F('foo bar  baz'))
    self.assertEqual('foo bar  baz 2>&1', F('foo bar  baz', mode=True))
    self.assertEqual('foo "bar  baz">&2', F('foo "bar  baz"'))
    self.assertEqual('foo "bar & baz &&">&2&by>&2', F('foo "bar & baz &&"&by'))
    self.assertEqual(r'foo "bar & \\baz &&"&by>&2',
                     F(r'foo "bar & \\baz &&"&by'))  # Too complicated.
    self.assertEqual(r'c1 2>f1 & c2 2>f2>&2',
                     F(r'c1 2>f1 & c2 2>f2'))  # Too complicated.
    self.assertEqual('foo bar  >&2& baz  >&2&&>&2', F('foo bar  & baz  &&'))
    self.assertEqual('foo bar   2>&1& baz   2>&1&& 2>&1',
                     F('foo bar  & baz  &&', mode=True))
    self.assertEqual('c1  2>&1>f1 & c2  2>&1&& "&c3"  2>&1>f3',
                     F('c1 >f1 & c2 && "&c3" >f3', mode=True))
    self.assertEqual('foo bar  >nul 2>&1& baz  >nul 2>&1&&>nul 2>&1',
                     F('foo bar  & baz  &&', mode=None))
    self.assertEqual('c1  2>nul >f1 & c2 >nul 2>&1&& "&c3"  2>nul >f3',
                     F('c1 >f1 & c2 && "&c3" >f3', mode=None))
    self.assertEqual('c1 >f1 & c2 >&2&& "&c3" >f3',  # Don't change c1 and c3.
                     F('c1 >f1 & c2 && "&c3" >f3'))

  def testGetBadNumbersFixed(self):
    F = main.PdfObj.GetBadNumbersFixed
    self.assertEqual('/Hello/World', F('/Hello/World'))
    self.assertEqual('0', F('.'))
    self.assertEqual('1.', F('1.'))
    self.assertEqual('.2', F('.2'))
    self.assertEqual('[1. 0 0 1. 0 0]', F('[1. . . 1. . .]'))
    self.assertEqual('[0 0 612. 792.]', F('[. . 612. 792.]'))

  def testEscapePdfNames(self):
    f1 = main.PdfObj._EscapePdfNamesInHexTokensSafe
    f2 = main.PdfObj.NormalizePdfName
    self.assertEqual('', f1(''))
    self.assertRaises(main.PdfTokenParseError, f2, '')
    self.assertEqual('/', f1('/'))
    self.assertRaises(main.PdfTokenParseError, f2, '/')
    self.assertEqual('a', f1('a'))
    self.assertRaises(main.PdfTokenParseError, f2, 'a')
    self.assertEqual('ab', f1('ab'))
    self.assertRaises(main.PdfTokenParseError, f2, 'ab')
    self.assertEqual('/a', f1(buffer('/a')))
    self.assertEqual('/a', f2(buffer('/a')))
    for i in xrange(256):
      c = '/#%02x' % i
      e1 = f1(c)
      e2 = f2(c)
      self.assertEqual(e1, e2, [e1, e2, c])
      c = '/%c' % i
      if chr(i) == '#':
        self.assertRaises(main.PdfTokenParseError, f1, c)
        self.assertRaises(main.PdfTokenParseError, f2, c)
        continue
      if chr(i) in '\0\t\n\f\r %()/<>[]{}':
        f1(c)  # Succeeds.
        self.assertRaises(main.PdfTokenParseError, f2, c)
        continue
      e1 = f1(c)
      e2 = f2(c)
      self.assertEqual(e1, e2, [e1, e2, c])

  # ---

  CFF_FONT_PROGRAM_FONT_NAME = 'Obj000009'
  CFF_FONT_PROGRAM_STRINGS = ['Computer Modern Roman', 'Computer Modern']
  # This is font `i: 5556' in cff.pgs, Ghostscript has failed to parse it,
  # probably because it has incorrect CharStrings offset (hence the `- 1' in
  # CheckFont).
  #
  # By the way, this is an invalid CFF font program. But it's very useful for
  # testing here, because offset sizes in indexes in it grow as the FontName
  # gets longer.
  CFF_FONT_PROGRAM = '''
      01000402000101010a4f626a3030303030390001010128f81b02f81c038bfb61
      f9d5f961051d004e31850df7190ff610f74a11961c0e10128b0c038b0c040002
      01011625436f6d7075746572204d6f6465726e20526f6d616e436f6d70757465
      72204d6f6465726e0000001801170f18100506081309140a150b0c0d020e0411
      12070316000022005a004f005b00500045004600470053004800540049005500
      4a004c004d0042004e000d00d8000f00cf00c800e0001902000100070093012d
      01ae021a02910314038803fc04620567061d06a9070a075e0814084e08ee09ad
      09fa0aa60ad40b870c680d24ff015682000eff03027d008caaf75aaaf85c7701
      adab156c07c98e05f72ca7066e6098b098909890971f9cba99ca9e8b08f78206
      9d8b9753957094709f648b78086d548b701e6cf7a6aa6f07758b738d7f977e98
      879e859b43f75548f75844f75583a018879687947b8b768b8773857b4efb3e4e
      fb404dfb3d795818764c6277548b08f75ff77915f70af7dbf70afbdb050eff02
      1e4e00fb60a472f711f873aa1213a0a0f843156c9907b08b9d819969a05818a7
      48a84ba748ac3d188e8393808b828b7d7e77857e7f6f18785e6c515389798b7b
      907d96a390979a8ba0081360a37b9e6d707f73775abb6bb8f2b5f71dd5a91eb6
      f2b6f0b8f19db6a1b7c88b08aafb376c07a28aa07d8d728b7074647f6e725171
      52745164e069e365e1899286928b9308a5ac8ca01eaa070eff023ad9008fa781
      76f834a412f704cf47d5f766d51713b4aef843156c9b07a9aa885c1ffba80762
      718a581e13746c0713acd28e05f731a774066e728fb01ff74807d8b8e2eac19b
      594d1efb7f07676e896a1e7c0613746c0713b4d28e05f731a778066e6e8eaf1f
      f776078ba98aa87ca672ba57975a8b4d8b4c6275518aee180eff01c8ad008ca7
      f80da401c1f8431580fb3805a7068dae8db4a1a7a4abb98eb48b08f703066c66
      70646e654a374a374c36868485838b8208809588931ef7f1069cf752056f0688
      62875a736b6e6659885f8b08fb0306e9f70de8f70de6f70f909192938b940895
      848f811e0eff0201c30081a7f829a58a7712a9e1f7ade21713b8f786f85415fb
      087f2b2d8bfb140824d8fb0df72af709f702e8f7161e13d8f70b2ef709fb1b1e
      13b886878a861bfb12fb9515b60713d8daa4f702f708dbbc4c3c941e8d768b76
      8b768b5688516761726c647b658b428b58c27edb8a988b978998080eff023ad9
      0081a4f825a5f7917701ade2f7a3d203f7cff940156c9607b3a589501ffb6507
      6ab25c9f598b08fb102323fb0ffb06e8fb03f711bacba2b4a41f8c4bf72b9605
      aa7c076a6e8eba1ff8f907fbeafc8a159907dc9ff714f712bed3654d7e8a7f8b
      7e1efb38078b7e8682848170645e6f5c8b648b679f73aa6eb087b886b8080eff
      01c9100081a7f768a3f73da401a7e3f787d003f707f77a15f7bc0697909196f7
      113ed721fb0e2c21fb0efb0fec20f71dd2d3bdd09f1f8c8e8c8f8b8f08928691
      83798a6d7d811e73615a6e5a8b088406578d5dae75ba78b389b88bb6088ca315
      8ccda7d8d3a2938d938c938b08e1ab323b1f0eff0139f7008fa78176f823aaf7
      33f70872a412f705d21713b4f705f843153b6cdbfbde06676e896a1e7c061374
      6c0713acd28e05f741a76a0667708fb61ff7d5f708aafb0be607cc9be9d79596
      8987941e7b83817c8b790813b4729e78a4a99a9fa4ba58a361454d5e49751e86
      788a798b78080eff0191e8008fa78176f834a412f6cc4ad21713b0a9f843156c
      9b07a9aa885c1ffba80762718a581e13706c0713a8d18e05f742a76906696f8f
      b11ff73c0792d09ef5f08b088a077d84857c8b7c0870a07aa3a49da0a3b462a0
      684e5a58537d1e13b08af6050eff0201c300fb61a6f74dc9dba7f781a7967712
      a8c373d9f747d8acc31713ed80f700f756158a07777780698b6f8b6a9966a879
      5d785e6f8b560826f73170d3e0f721a9f0f70cfb10a2261e3006698f75a98bab
      089891a7941e8d069988988099879e859f889f8b08dae2c3e3ae7eb36fa21f8c
      07aca2a698b18b838585838b80087a997d9ba0959c99ac6e9c711e83066c876c
      81727688888786868b088a06848b759a7c910813f3809378768e761b39335330
      669c62a9741f13f58074fba8159207c0bfa8ba95968a8b951ebe06c68be88695
      4308840734fb267e704b2ba5d1811e13f380c1f7fc159607c298d1d7c9a75744
      5271524b727295a07a1e7b9f88a488a4080eff01954d0081a4f82fa112adbef7
      7ba76fc11713e8e6ad15ab6bb47fb68b08dddcb5ec1f960787c35fb6599e7294
      6f8f7190619349978bc508c5d499b6cab96644911e838c81971e13f0928b928f
      8c9208f70d07928894827c80728b7f1e8906848d8491858e7695718f738b0844
      2b742526f7097ad37d1fb783bb718f5a08434f76561e8106428f63c27ad08896
      8b9b7c8b08808883821ffb15078b878a868b8608818d819694939791911e9091
      919291919092190eff023ad9008fa78176f834a4f7917712f704d2f769d51713
      bcaef940156c9c07aaa8875b1ffc8c078b848c848b8308616e8a601e8506137c
      6c0713bcd28e05f731a774066e728fb01ff74807d8b8e2eac19b594d1efb7f07
      676e896a1e7c06137c6c0713bcd28e05f731a778066e6e8eaf1ff776078ba98a
      a97ca673b758995c8b538b466b744e8af7ee180eff018f97009676f82ea472aa
      f74d7712f5d56fa7f71ba61713d6f72cf8fc154269fb0a281e720713bae2fb9c
      068b6c8d6d9b70a361bd7bb98b089406d79898de8bc608b06f078b7d8c7c8b7c
      085f813f50557fcabc1ef7a2f725aafb25f74d070eff011d6c008caaf9127712
      daf444d21713d0b3f843156c9b07aba4865e1ffba90763708a591e6cf76daa7b
      0770718eab1ff80b0751f7781513e0718776766f1a6ea373a91e9206a58fa0a0
      8ba708a873a36d1e0eff021e4e008fa78176f823aaf79c7712f6d21713b8a9f9
      40156c9c07aaa8875b1ffc8c078b848c848b8308616e8a601e850613786c0713
      b8d18e05f72ca772066d758fb61fd4078b908a908b908b9a979094939a97999a
      9b95a85ab55dad5a9182947d8b7f087b78867c1e13786cf75a0713b8aa076a8b
      749273a67c9c7e9e7d9e66bf64bd66bf928f90909190a6a118bab3c1bccd8b08
      aafb4b6c0796889a878b7b8b6e6674757a4752187e807d817f7f08f871070eff
      011d6c008caaf92b7701f705d203aff940156c9707afa889591ffc8c078b848c
      848b8308616e8a601e856cf775aa720670728fae1ff904070eff0201c30081a4
      72b3f79df72d72a412b4def765d5d3a717135ef70ef81815a6a4b495af8baf8b
      aa789f6d9e6f8c6c8b6b0879073982398b46576a7271648b62083aed6fcdc9b9
      aabfa81e9362a366b98b08c7a6bec21fb86f59076f85656c6a89b7a11ef75707
      f431bf324d2e713c1e13ae709b76af1ea48c9ba28ba28ba67699749008f767fb
      27152807475a50461e83065c9067ae8bb808eaf706b9ea1e0eff035845008fa7
      8176f834a412f704cf47d5f767d5f767d51713b6aef843156c9b07a9aa885c1f
      fba80762718a581e13766c0713aed28e05f731a774066e728fb01ff75d0791d2
      bbd3e18b08cb924a5c1ffb7f07676e896a1e7c0613766c0713b6d28e05f731a7
      74066e728fb01ff75d0791d2bbd3e18b08cb924a5c1ffb7f07676e896a1e7c06
      13766cf7780713b6aa78076e6e8eaf1ff776078ba98aa97ca671ba57965a8b4f
      8b4b637654088a0682d04aa54f8b4a8b4c67734c8aee180eff011d6c00fb3f76
      f7c17712e3f70b72a41713e0f74a9c158b48784b5959878784858b8508849286
      909ca3af9e971ea5b499bc8bbc08b681cb506d776e726da273a91e13d09b8b99
      909696080eff0201c30081a7f829a5f75877a07712a9e1f7ade21713ecf786f8
      5415fb087f2b2d8bfb140824d8fb0df72af709f702e8f716f70b2ef709fb1b86
      878a8b861efb12fb9515b607daa4f702f708dbbc4c3c941e8d768b768b768b56
      88516761726c647b658b428b58c27edb8a988b97899808f756f85a157a897a76
      7f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac8b
      ae1913dc9f7b9f761e13ec89898a891b0eff011d6c00a176f7007701e3f70003
      f71af70015728876758b6f08719f6faba4aa9dafa676a66a88898b8a881e0eff
      01c9100081a7f768a3f73da4f75977a07712a7e3f787d01713f6f707f77a15f7
      bc0697909196f7113ed721fb0e2c21fb0efb0fec20f71dd2d3bdd09f1f8c8e8c
      8f8b8f0892869183798a6d7d811e73615a6e5a8b088406578d5dae75ba78b389
      b88bb6088ca3158ccda7d8d3a2938d938c938b08e1ab323b1f3ef81b157a897a
      767f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac
      8bae1913ee9f7b9f761e13f689898a891b0eff0201c30081a472b3f79df72d72
      a4f75977a07712b4def765d5d3a717135780f70ef81815a6a4b495af8baf8baa
      789f6d9e6f8c6c8b6b0879073982398b46576a7271648b62083aed6fcdc9b9aa
      bfa81e9362a366b98b08c7a6bec21fb86f59076f85656c6a89b7a11ef75707f4
      31bf324d2e713c1e13ab80709b76af1ea48c9ba28ba28ba67699749008f767fb
      27152807475a50461e83065c9067ae8bb808eaf706b9ea1e74f828157a897a76
      7f7f6b6b6a6e6b6b8a898a8a8b890885957d9190908f8d8f1ea79bb7a3e1ac8b
      ae1913a7809f7b9f761e13ab8089898a891b0eff023ad90081a4f815aff70af7
      008a7712f704d5f766d51713dcaef843156c9407a6b2896e1f8d808b818b8008
      fb5c078b6d8c6e9a70a759c880c08bc38bc0ac9ebf8c3618f7289605aa7a076d
      6d8eb81ff7fe07fb2b80056c9907aaab885d1ffb5a07854a64423d8b638b6795
      82bf899e8b9d8b9e08f7c907f759f76f15708778758b710813ec729f6daaaea0
      a6a6a279aa6a1e13dc88878a881bfb5b166e877a718b740813ec749d6caca8a6
      a1aaa577a86b1e13dc88888a881b0eef0abd0b1e0a03963f0c090000
  '''.replace(' ', '').replace('\n', '').decode('hex')

  def testCffFontNameOfs(self):
    cff_header = '\1\0\4\1'
    fontname = 'MyFontName'
    for off_size in (1, 2, 3, 4):
      cff_data = ''.join((
          cff_header,
          cff.SerializeCffIndexHeader(off_size, (fontname,))[1],
          fontname))
      cff_font_name_ofs = cff.GetCffFontNameOfs(cff_data)
      self.assertEqual(
          fontname,
          cff_data[cff_font_name_ofs : cff_font_name_ofs + len(fontname)])

  def testParseCffIndex(self):
    def Check(items):
      header = cff.SerializeCffIndexHeader(None, items)[1]
      eoi = 'EOI'
      index = header + ''.join(items) + eoi
      after_index_ofs, items2 = cff.ParseCffIndex(index)
      items_strlist = list(items)
      items2_strlist = map(str, items2)
      self.assertEqual(items_strlist, items2_strlist)
      self.assertEqual(len(index) - len(eoi), after_index_ofs)
      self.assertEqual(after_index_ofs == 2, len(items) == 0)
      if len(index) < 256 and items:  # True in general.
        self.assertTrue(ord(header[2]) == 1)
      if len(index) > 270 and items:  # Not true in general, but true here.
        self.assertTrue(ord(header[2]) > 1)

    Check(())
    Check(('foo',))
    Check(('foo', 'barbaz'))
    Check(('', 'foo', '', '', 'barbaz', '', '', ''))
    Check(('', '', ''))
    Check(('',))
    Check(('foo', 'barbaz' * 100))

  def testYieldParsePostScriptTokenList(self):
    def F(data):
      return list(cff.YieldParsePostScriptTokenList(data))

    self.assertEqual([], F(''))
    self.assertEqual([], F(' \t\r\n\f\0\t  '))
    self.assertEqual(['/Foo', '/Bar'], F('/Foo/Bar'))
    self.assertEqual(['/Foo', '/B#24a#2Ar'], F('\n/Foo \t/B$a*r\f'))
    # Treat #2A as PostScript (not escaped) in the input token name.
    self.assertEqual(['/pedal.#2A', '/pedal.#232a', '/pedal.#232A'],
                      F('/pedal.*/pedal.#2a/pedal.#2A'))
    self.assertRaisesX(ValueError, F, '/')  # OK in regular PostScript
    self.assertRaisesX(ValueError, F, '<')
    self.assertRaisesX(ValueError, F, '>')
    self.assertRaisesX(ValueError, F, '<xy>')
    self.assertRaisesX(ValueError, F, '<a')
    self.assertRaisesX(ValueError, F, '<a>')
    self.assertRaisesX(ValueError, F, '<ab')
    self.assertRaisesX(ValueError, F, '<ab ')
    self.assertRaisesX(ValueError, F, 'quit')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '(')
    self.assertRaisesX(ValueError, F, ')')
    self.assertRaisesX(ValueError, F, '{}')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '[]')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '(())')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '(\\n)')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '8#77')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '16#ab')  # OK in regular PostScript.
    self.assertRaisesX(ValueError, F, '<~ab~>')  # OK in regular PostScript.
    self.assertEqual(repr(['def', True, False, None]),
                     repr(F('def true false null')))
    self.assertEqual(repr([42, 5, -42, '425.', '-4.25']),
                     repr(F('42 +5 -42 +42.5e+1 -42.5E-1')))
    self.assertEqual(repr(['def', True, '/false', '<>', None, 42]),
                     repr(F('def true/false<>null%foo\r42%')))
    self.assertEqual(['<>', '<>', '<202a>', '<2a3b>'],
                     F('()<\f\t>( *)<\r2 A\t3\nb\r>'))

  def testParsePostScriptDefs(self):
    F = cff.ParsePostScriptDefs
    self.assertEqual({}, F('\t'))
    self.assertEqual({'FSType': 14}, F('/FSType 14 def'))
    self.assertRaisesX(ValueError, F, '/FSType')
    self.assertRaisesX(ValueError, F, '/FSType 14')
    self.assertRaisesX(ValueError, F, '/FSType 14 def /OrigFontType')
    self.assertRaisesX(ValueError, F, '/FSType 14 15')
    self.assertRaisesX(ValueError, F, '13 14 def')
    self.assertEqual({'FSType': 8, 'OrigFontType': '/TrueType',
                      'OrigFontName': '<33307b686a>', 'OrigFontStyle': '<>'},
                     F('/FSType 8 def\n/OrigFontType /TrueType def\n'
                       '/OrigFontName <33307B686a> def/OrigFontStyle () def'))

  def testFixFontNameInType1C(self):
    new_font_name = 'Hello'
    font_obj = main.PdfObj('1 0 obj<</Subtype/Type1C>>endobj')
    font_obj.stream = self.CFF_FONT_PROGRAM
    old_font_name = cff.ParseCffHeader(font_obj.stream)[1]
    self.assertEqual(self.CFF_FONT_PROGRAM_FONT_NAME, old_font_name)
    len_deltas = []
    font_obj.FixFontNameInType1C(new_font_name, len_deltas_out=len_deltas)
    self.assertEqual([-4], len_deltas)
    self.assertEqual(
        new_font_name,
        cff.ParseCffHeader(font_obj.GetUncompressedStream())[1])
    self.assertEqual('/FlateDecode', font_obj.Get('Filter'))

  def testFixFontNameInCff(self):
    def CheckFont(font_program, font_name):
      charstrings_op = 17
      (cff_version, cff_font_name, cff_font_items, cff_string_bufs,
       cff_global_subr_bufs, cff_rest_buf, cff_off_size, cff_rest2_ofs,
      ) = cff.ParseCffHeader(font_program)
      cff_top_dict_buf = cff_font_items[0][1]
      self.assertEqual(font_name, cff_font_name)
      cff_top_dict = cff.ParseCffDict(cff_top_dict_buf)
      self.assertEqual(self.CFF_FONT_PROGRAM_STRINGS, map(str, cff_string_bufs))
      # TODO(pts): Why do we have to subtract 1 here? Is CFF file offset
      # 1-based? Probably so, but we need to run this on other fonts. The test
      # font has CharStrings at offset 181 in the file, but the op says 182.
      # Nothing else (other than the string index) looks like an index.
      _, charstring_bufs = cff.ParseCffIndex(
          buffer(font_program, cff_top_dict[charstrings_op][-1] - 1))
      self.assertEqual(25, len(charstring_bufs))

    def Check(new_font_name, expected_len_deltas):
      CheckFont(self.CFF_FONT_PROGRAM, self.CFF_FONT_PROGRAM_FONT_NAME)

      len_deltas = []
      new_font_program = cff.FixFontNameInCff(
          self.CFF_FONT_PROGRAM, new_font_name, len_deltas_out=len_deltas)
      new_font_program2 = cff.FixFontNameInCff(
          new_font_program, new_font_name, len_deltas_out=len_deltas)
      self.assertEqual(new_font_program, new_font_program2)
      self.assertEqual(expected_len_deltas, len_deltas)
      CheckFont(new_font_program, new_font_name)

    Check('N', [-8])
    Check('N' + 'a' * 7, [-1])
    Check('N' + 'a' * 8, [])
    # It's a pity unforunate that we have to do 2 iterations here below when
    # the font name gets just a bit longer.
    #
    # TODO(pts): Check with real-world CFF fonts that typically 1 iteration is
    #            sufficient.
    Check('N' + 'a' * 9, [1, 2])
    Check('N' + 'a' * 10, [2, 3])
    Check('N' + 'a' * 11, [3, 4])
    Check('N' + 'a' * 12, [4, 5])
    Check('N' + 'a' * 13, [5, 6])
    Check('N' + 'a' * 99, [91, 92])
    Check('B' * 260, [251, 254])
    Check('B' * 100000, [99991, 100007])

  def testFormatFloatShort(self):
    for f, expected in (
        (float('inf'), 'inf'),
        (float('-inf'), '-inf'),
        (float('nan'), 'nan'),
        (1234., '1234.'),
        (430., '430.'),
        (-4300., '-43e2'),
        (43000., '43e3'),
        (1.0 / 10, '.1'),
        (3.0 / 10, '.3'),
        (1.0 / 3, '.3333333333333333'),
        (1e42 / 3, '33333333333333336e25'),
        (0.3, '.3'),
        (-0.9, '-.9'),
        (0.09, '.09'),
        (-0.009, '-.009'),
        (0.0009, '9e-4'),
        (0.00009, '9e-5'),
        (3e24, '3e24'),
        (-3.0 / 10 * 1e25, '-3e24'),
        (3.0 / 10 * 1e-25, '3e-26'),
        (7., '7.'),
        (0., '0.'),
        (-0., '-0.'),
        (42., '42.'),
        (-42., '-42.'),
        (.123, '.123'),
        (12.3, '12.3'),
        (1.23, '1.23'),
        (123., '123.'),
        (.0123, '.0123'),
        (.00123, '.00123'),
        (.000123, '123e-6'),
        (0.0001234, '1234e-7'),
        ):
      got = float_util.FormatFloatShort(f)
      assert repr(float(got)) == repr(f), (f, got, expected)
      assert got == expected, (got, expected)


    for f, expected in (
        (3.0 / 10, '.3'),
        (12.3, '12.3'),
        (1234., '1234'),
        (430., '430'),
        (-4300., '-4300'),
        (7., '7'),
        (0., '0'),
        (-0., '-0'),
        (42., '42'),
        (-42., '-42'),
        (123., '123'),
        ):
      got = float_util.FormatFloatShort(f, is_int_ok=True)
      assert repr(float(got)) == repr(f), (f, got, expected)
      assert got == expected, (got, expected)


if __name__ == '__main__':
  unittest.main(argv=[sys.argv[0], '-v'] + sys.argv[1:])
