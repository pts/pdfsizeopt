#! /usr/bin/python2.4

# pdfsizeopt_test.py: unit tests for pdfsizeopt.py
# by pts@fazekas.hu at Sun Apr 19 10:21:07 CEST 2009
#

__author__ = 'pts@fazekas.hu (Peter Szabo)'

import sys
import unittest

import pdfsizeopt


class PdfSizeOptTest(unittest.TestCase):
  def testEscapeString(self):
    e = pdfsizeopt.PdfObj.EscapeString
    self.assertEqual('()', e(''))
    self.assertEqual('(Hello, World!)', e('Hello, World!'))
    self.assertEqual('(\\\\Hello, \\(World!)', e('\\Hello, (World!'))
    self.assertEqual('(Hello, \\)World!\\\\)', e('Hello, )World!\\'))
    s = ''.join([c for c in map(chr, xrange(255, -1, -1)) if c not in '()\\'])
    self.assertEqual('(%s)' % s, e(s))
    self.assertEqual('(Hello, \\)\\(Wo\\\\rld!)', e('Hello, )(Wo\\rld!'))
    self.assertEqual('((((foo\\\\))))', e('(((foo\\)))'))
    self.assertEqual('(((foo)) (\\(bar)d)', e('((foo)) ((bar)d'))
    self.assertEqual('((foo)\\) (bar))', e('(foo)) (bar)'))

  def testRewriteParsable(self):
    e = pdfsizeopt.PdfObj.RewriteParsable
    self.assertEqual(' [ ]', e('[]'))
    self.assertEqual(' [ ]', e('[]<<'))
    self.assertEqual(' true', e('true '))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, 'hi ')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, 'true')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, 'hi')
    eo = []
    self.assertEqual(' false', e('\n\t\r \f\0false true ', end_ofs_out=eo))
    self.assertEqual([11], eo)
    self.assertEqual(' << true false null >>',
                     e('% hi\r<<%\ntrue false null>>baz'))
    self.assertEqual(' [ [ << [ << << >> >> ] >> ] ]',
                     e('[[<<[<<<<>>>>]>>]]'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError,
                      e, '[[<<[<<<<>>]>>>>]]')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '\t \n% foo')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, ' [\t')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '\n<\f')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '\t<<\n\r')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '[<<')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[<<]')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[>>]')
    self.assertEqual(' <>', e('()'))
    self.assertEqual(' <>', e('<>'))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '<<')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '>>')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '[')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, ']')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '(foo')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '(foo\\)bar')
    self.assertEqual(' <face654389210b7d>', e('< f\nAc\tE\r654389210B7d\f>'))
    self.assertEqual(' <48656c6c6f2c20576f726c6421>', e('(Hello, World!)'))
    self.assertEqual(' <2828666f6f2929296261725c>', e('(((foo))\\)bar\\\\)'))
    self.assertEqual(' <face422829>', e('(\xfa\xCE\x42())'))
    self.assertEqual(' <00210023>', e('(\0!\\0#)'))
    self.assertEqual(' <073839380a>', e('(\78\98\12)'))
    self.assertEqual(' <053031>', e('(\\501)'))
    self.assertEqual(' <0a0d09080c>', e('(\n\r\t\b\f)'))
    self.assertEqual(' <0a0d09080c>', e('(\\n\\r\\t\\b\\f)'))
    self.assertEqual(' <0a0d09080c>', e('(\n\r\t\b\f)'))
    self.assertEqual(' <236141>', e('(\\#\\a\\A)'))
    self.assertEqual(' <61275c>', e("(a'\\\\)"))
    self.assertEqual(' <314f5c60>', e('<\n3\t1\r4f5C6 >'))
    self.assertEqual(' <0006073839050e170338043805380638073838380a3913391f39>',
                     e('(\0\6\7\8\9\05\16\27\38\48\58\68\78\88\129\239\379)'))
    self.assertEqual(' <0006073839050e170338043805380638073838380a3913391f39'
                     '043031053031063031073031>',
                     e('(\\0\\6\\7\\8\\9\\05\\16\\27\\38\\48\\58\\68\\78\\88'
                       '\\129\\239\\379\\401\\501\\601\\701)'))
    # PDF doesn't have \x
    self.assertEqual(' <786661786243784445f8>', e('(\\xfa\\xbC\\xDE\xF8)'))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '42')
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

    end_ofs_out=[]
    self.assertEqual(' 5', e(' 5 endobj\t', end_ofs_out=end_ofs_out))
    self.assertEqual([2], end_ofs_out)
    end_ofs_out=[]
    self.assertEqual(' 5 endobz',
                     e(' 5 endobz\t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([10], end_ofs_out)
    end_ofs_out=[]
    self.assertEqual(' 5 STROZ',
                     e(' 5 STR#4FZ\r\n\t\t\t \t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([12], end_ofs_out)
    end_ofs_out=[]
    self.assertEqual(' /Size', e('/Size 42 ', end_ofs_out=end_ofs_out))
    self.assertEqual([5], end_ofs_out)
    self.assertEqual(' [ /Size 42 ]', e('[/Size 42]'))
    self.assertEqual(' [ true 42 ]', e('[true\n%korte\n42]'))
    self.assertEqual(' [ true 42 ]', e('[true%korte\n42]'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, 'hello \n\t world\n\t')
    self.assertEqual(' null', e('null \n\t false\n\t'))
    # This is invalid PDF (null is not a name), but we don't catch it.
    self.assertEqual(' << null false >>', e('\r<<null \n\t false\n\t>>'))
    self.assertEqual(' << true >>', e('<<true>>'))
    self.assertEqual(' true foo', e('true foo bar', do_terminate_obj=True))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e,
                      'true foo', do_terminate_obj=True)
    self.assertEqual(' <68656c296c6f0a0877286f72296c64>',
                     e('(hel\)lo\n\bw(or)ld)'))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '(hel\)lo\n\bw(orld)')
    self.assertEqual(' [ <68656c296c6f0a0877286f72296c64> ]',
                     e(' [ (hel\\051lo\\012\\010w\\050or\\051ld) ]<'))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '>')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '<')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '< ')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '< <')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '> >')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[ >>')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '[ (hel\\)lo\\n\\bw(or)ld) <');
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, "<\n3\t1\r4f5C5")
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, "<\n3\t1\r4f5C5]>")
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '%hello')

  def testGetParsableHead(self):
    self.assertEqual(
        '<<\n/DecodeParms <</Predictor 15 /Columns 640>>\n'
        '/Width 640\n/ColorSpace /DeviceGray\n/Height 480\n'
        '/Filter /FlateDecode\n/Subtype /Image\n/Length 6638\n'
        '/BitsPerComponent 8\n>>',
        pdfsizeopt.PdfObj.GetParsableHead(
            '<</Subtype/Image\n/ColorSpace/DeviceGray\n/Width 640\n'
            '/Height 480\n/BitsPerComponent 8\n/Filter/FlateDecode\n'
            '/DecodeParms <</Predictor 15\n/Columns 640>>/Length 6638>>'))

  def testIsGrayColorSpace(self):
    e = pdfsizeopt.PdfObj.IsGrayColorSpace
    self.assertEqual(False, e('/DeviceRGB'))
    self.assertEqual(False, e('/DeviceCMYK'))
    self.assertEqual(False, e('/DeviceN'))
    self.assertEqual(True, e('  /DeviceGray  \r'))
    self.assertEqual(False, e('\t[ /Indexed /DeviceGray'))
    self.assertEqual(True, e('\t[ /Indexed /DeviceGray 5 <]'))
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e,
                      '\t[ /Indexed /DeviceRGB 5 (]')
    self.assertEqual(True, e('\t[ /Indexed /DeviceRGB\f5 (A\101Azz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Bzz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Ayy\172)]'))

if __name__ == '__main__':
  unittest.main(argv=[sys.argv[0], '-v'] + sys.argv[1:])
