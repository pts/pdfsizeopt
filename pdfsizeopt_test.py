#! /usr/bin/python2.4
#
# pdfsizeopt_test.py: unit tests for pdfsizeopt.py
# by pts@fazekas.hu at Sun Apr 19 10:21:07 CEST 2009
#

__author__ = 'pts@fazekas.hu (Peter Szabo)'

import sys
import zlib
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

  def testRewriteToParsable(self):
    e = pdfsizeopt.PdfObj.RewriteToParsable
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
    self.assertEqual(' << true >>',
                     e('<<true>>baz'))
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
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '42')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '.')
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

    end_ofs_out = []
    self.assertEqual(' 5', e(' 5 endobj\t', end_ofs_out=end_ofs_out))
    self.assertEqual([2], end_ofs_out)
    end_ofs_out = []
    self.assertEqual(' 5 endobz',
                     e(' 5 endobz\t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([10], end_ofs_out)
    end_ofs_out = []
    self.assertEqual(' 5 STROZ',
                     e(' 5 STR#4FZ\r\n\t\t\t \t',
                       end_ofs_out=end_ofs_out, do_terminate_obj=True))
    self.assertEqual([12], end_ofs_out)
    end_ofs_out = []
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
    # 'stream\r' is truncated, we're waiting for 'stream\r\n'.
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e,
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
    self.assertEqual(13, eo[0])  # spaces not included
    self.assertRaises(pdfsizeopt.PdfTokenParseError,
                      e, '<</Pages 333 -1 R\n>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError,
                      e, '<</Pages 0 55 R\n>>')

  def testSerializeDict(self):
    # Toplevel whitespace is removed, but the newline inside the /DecodeParms
    # value is kept.
    self.assertEqual(
        '<</BitsPerComponent 8/ColorSpace/DeviceGray/DecodeParms'
        '<</Predictor 15\n/Columns 640>>/Filter/FlateDecode/Height 480'
        '/Length 6638/Subtype/Image/Width 640/Z true>>',
        pdfsizeopt.PdfObj.SerializeDict(pdfsizeopt.PdfObj.ParseSimplestDict(
            '<</Subtype/Image\n/ColorSpace/DeviceGray\n/Width 640/Z  true\n'
            '/Height 480\n/BitsPerComponent 8\n/Filter/FlateDecode\n'
            '/DecodeParms <</Predictor 15\n/Columns 640>>/Length 6638>>')))

  def testIsGrayColorSpace(self):
    e = pdfsizeopt.PdfObj.IsGrayColorSpace
    self.assertEqual(False, e('/DeviceRGB'))
    self.assertEqual(False, e('/DeviceCMYK'))
    self.assertEqual(False, e('/DeviceN'))
    self.assertEqual(True, e('  /DeviceGray  \r'))
    self.assertEqual(False, e('\t[ /Indexed /DeviceGray'))
    self.assertEqual(True, e('\t[ /Indexed /DeviceGray 5 <]'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e,
                      '\t[ /Indexed /DeviceRGB 5 (]')
    self.assertEqual(True, e('\t[ /Indexed /DeviceRGB\f5 (A\101Azz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Bzz\172)]'))
    self.assertEqual(False, e('\t[ /Indexed\n/DeviceRGB 5 (A\101Ayy\172)]'))

  def testParseSimpleValue(self):
    e = pdfsizeopt.PdfObj.ParseSimpleValue
    self.assertEqual(True, e('true'))
    self.assertEqual(False, e('false'))
    self.assertEqual(True, e('true '))
    self.assertEqual(False, e('\nfalse'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, 'foo bar')
    self.assertEqual('[foo  bar]', e('\f[foo  bar]\n\r'))
    self.assertEqual('<<foo  bar\tbaz>>', e('\f<<foo  bar\tbaz>>\n\r'))
    self.assertEqual(None, e('null'))
    self.assertEqual(0, e('0'))
    self.assertEqual(42, e('42'))
    self.assertEqual(42, e('00042'))
    self.assertEqual(-137, e('-0137'))
    self.assertEqual('3.14', e('3.14'))
    self.assertEqual('5e6', e('5e6'))
    self.assertEqual('<48493f>', e('(HI?)'))
    self.assertEqual('<28295c>', e('(()\\\\)'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '(()\\\\)x')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '(()\\\\')
    self.assertEqual('<deadface>', e('<dea dF aCe>'))
    self.assertEqual('<deadfac0>', e('<\fdeadFaC\r>'))
    self.assertEqual('42 0 R', e('42\f\t0 \nR'))

  def DoTestParseSimplestDict(self, e):
    # e is either ParseSimplestDict or ParseDict, so (because the latter)
    # this method should not test for PdfTokenNotSimplest.
    self.assertEqual({}, e('<<\t\0>>'))
    self.assertEqual({}, e('<<\n>>'))
    self.assertEqual({'One': '/Two'}, e('<< /One/Two>>'))
    self.assertEqual({'One': 'Two'}, e('<</One Two>>'))
    self.assertEqual({'One': 234}, e('<</One 234>>'))
    self.assertEqual({'Five': '/Six', 'Three': 'Four', 'One': '/Two'},
                     e('<</One/Two/Three Four/Five/Six>>'))
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
    self.assertEqual({'D': '<<]42[\f\t?Foo>>'}, e('<<\n/D\n<<]42[\f\t?Foo>>>>'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</S<%\n>>>')

  def testParseSimplestDict(self):
    e = pdfsizeopt.PdfObj.ParseSimplestDict
    self.DoTestParseSimplestDict(e=e)
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest,
                      e, '<</Three[/Four()]>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</S\r(\\n)>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</A[()]>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</A[%\n]>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</D<<()>>>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</D<<%\n>>>>')
    self.assertRaises(pdfsizeopt.PdfTokenNotSimplest, e, '<</?Answer! 42>>')
  
  def testParseDict(self):
    e = pdfsizeopt.PdfObj.ParseDict
    self.DoTestParseSimplestDict(e=e)
    self.assertEqual({}, e('<<\0\r>>'))
    self.assertEqual({}, e('<<\n>>'))
    self.assertEqual({'I': 5}, e('<</I%\n5>>'))
    self.assertEqual({'N': '/Foo-42+_'}, e('<</N/Foo-42+_>>'))
    self.assertEqual({'N': '/Foo-42+_#2A'}, e('<</N/Foo-42+_*>>'))
    self.assertEqual({'N': '/Foo-42+_#2Ab'}, e('<</N/Foo-42+_#2Ab>>'))
    self.assertEqual({'Five': '/Six', 'Three': '[/Four]', 'One': '/Two'},
                     e('<</One/Two/Three[/Four]/Five/Six>>'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</Foo bar#3F>>')
    self.assertEqual({'#3FAnswer#21#20#0D': 42}, e('<</?Answer!#20#0d 42>>'))
    self.assertEqual({'S': '<0a>'}, e('<</S\r(\\n)>>'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</S\r(foo\\)>>')
    self.assertEqual({'S': '<666f6f29626172>'}, e('<</S(foo\\)bar)>>'))
    self.assertEqual({'S': '<2829>', 'T': '<42cab0>'}, e('<</S(())/T<42c Ab>>>'))
    self.assertEqual({'S': '<282929285c>', 'T': 8},
                     e('<</S(()\\)\\(\\\\)/T 8>>'))
    self.assertEqual({'A': '[\f()]'}, e('<</A[\f()]>>'))
    self.assertEqual({'A': '[\t5 \r6\f]'}, e('<</A[\t5 \r6\f]>>'))
    self.assertEqual({'A': '[12 34]'}, e('<</A[12%\n34]>>'))
    # \t removed because there was a comment in the array
    self.assertEqual({'A': '[]'}, e('<</A[\t%()\n]>>'))
    self.assertEqual({'A': '<2829>', 'B': '[<<]'}, e('<</A(())/B[<<]>>'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</A>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<<5/A>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</A(())/B[()<<]>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<</A[[>>]]>>')
    self.assertEqual({'A': '[[/hi 5]/lah]'}, e('<</A[[/hi%x\t]z\r5] /lah]>>'))
    self.assertEqual({'D': '<<()\t<>>>'}, e('<</D<<()\t<>>>>>'))
    self.assertEqual({'D': '<<>>', 'S': '<>'}, e('<</D<<%\n>>/S()>>'))
    # \t and \f removed because there was a comment in the dict
    self.assertEqual({'D': '<</E<<>>>>'}, e('<</D<</E\t\f<<%>>\n>>>>>>'))
    self.assertEqual({'A': '[[]]', 'q': '56 78 R'},
                     e('<</A[[]]/q\t56\r78%q\rR>>'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<<\r%>>')

  def testParseArray(self):
    e = pdfsizeopt.PdfObj.ParseArray
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[%]')
    self.assertEqual(['/Indexed', '/DeviceRGB', 42, '43 44 R'],
                     e('[\t/Indexed/DeviceRGB\f\r42\00043%42\n44\0R\n]')) 
    self.assertEqual(['[ ]', '[\t[\f]]', '<<\t [\f[ >>', True, False, None],
                     e('[[ ] [\t[\f]] <<\t [\f[ >> true%\nfalse\fnull]'))

  def testParseValueRecursive(self):
    e = pdfsizeopt.PdfObj.ParseValueRecursive
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
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '1 2')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[[]')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, ']')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '3]')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<<]')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '(')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '(()')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '(()))')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<12')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<12<>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<<1>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '<<%>>')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '[%]')

  def testCompressValue(self):
    e = pdfsizeopt.PdfObj.CompressValue
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
    self.assertEqual('(())', e(' <2829>\t'))
    self.assertEqual('(\\)\\()', e(' <2928>\t'))
    self.assertEqual('[12 34]', e('[12%\n34]'))
    self.assertEqual('[12 34]', e('[ 12 34 ]'))
    self.assertEqual('<</A[12 34]>>', e(' << \t/A\f[12%\n34]>>\r'))
    self.assertEqual('( hello\t\n)world', e(' ( hello\t\n)world'))
    self.assertEqual('(\\)((hi))\\\\)world', e(' (\\)(\\(hi\\))\\\\)world'))
    self.assertEqual('/#FAce#5BB', e('/\xface#5b#42\f'))
    s = '/Kids[041\t 0\rR\f43\n0% 96 0 R\rR 42 0 R 97 0 Rs 42 0 R]( 98 0 R )\f'
    t = '/Kids[041 0 R 43 0 R 42 0 R 97 0 Rs 42 0 R]( 98 0 R )'
    self.assertEqual(t, e(s))
    self.assertEqual(t, e(e(s)))
    old_obj_nums = ['']
    self.assertEqual(t, e(s, old_obj_nums_ret=old_obj_nums))
    self.assertEqual(['', 41, 43, 42, 42], old_obj_nums)
    u = '/Kids[41 0 R 53 0 R 52 0 R 97 0 Rs 52 0 R]( 98 0 R )'
    self.assertEqual(u, e(s, obj_num_map={43: 53, 42: 52}))
    old_obj_nums = [None]
    self.assertEqual(
        u, e(s, obj_num_map={43: 53, 42: 52}, old_obj_nums_ret=old_obj_nums))
    self.assertEqual([None, 41, 43, 42, 42], old_obj_nums)
    self.assertEqual('<</Length 68/Filter/FlateDecode>>',
                     e('<</Length 68/Filter/FlateDecode >>'))
    self.assertEqual('<</Type/Catalog/Pages 1 0 R>>',
                     e('<</Type/Catalog/Pages 1 0 R >>'))

  def testPdfObjParse(self):
    obj = pdfsizeopt.PdfObj(
        '42 0 obj<</Length  3>>stream\r\nABC endstream endobj')
    self.assertEqual('<</Length  3>>', obj.head)
    self.assertEqual('ABC', obj.stream)
    obj = pdfsizeopt.PdfObj(
        '42 0 obj<</Length  4>>stream\r\nABC endstream endobj')
    self.assertRaises(
        pdfsizeopt.PdfTokenParseError, pdfsizeopt.PdfObj,
        '42 0 obj<</Length 99>>stream\r\nABC endstream endobj')
    self.assertEqual('<</Length  4>>', obj.head)
    self.assertEqual('ABC ', obj.stream)
    obj = pdfsizeopt.PdfObj(
        '42 0 obj<</Length  4>>endobj')
    self.assertEqual('<</Length  4>>', obj.head)
    self.assertEqual(None, obj.stream)
    obj = pdfsizeopt.PdfObj(
        '42 0 obj<</T[/Length 99]/Length  3>>stream\r\nABC endstream endobj')
    self.assertEqual('ABC', obj.stream)
    obj = pdfsizeopt.PdfObj(
        '42 0 obj<</T()/Length  3>>stream\nABC endstream endobj')
    self.assertEqual('ABC', obj.stream)
    s = '41 0 obj<</T(>>\nendobj\n)/Length  3>>stream\nABD endstream endobj'
    t = '42 0 obj<</T 5%>>endobj\n/Length  3>>stream\nABE endstream endobj'
    end_ofs_out = []
    obj = pdfsizeopt.PdfObj(s, end_ofs_out=end_ofs_out)
    self.assertEqual([len(s)], end_ofs_out)
    self.assertEqual('ABD', obj.stream)
    end_ofs_out = []
    obj = pdfsizeopt.PdfObj(t + '\r\n\tANYTHING', end_ofs_out=end_ofs_out)
    self.assertEqual([len(t) + 1], end_ofs_out)
    end_ofs_out = []
    obj = pdfsizeopt.PdfObj(
        '%s\n%s' % (s, t), start=len(s) + 1, end_ofs_out=end_ofs_out)
    self.assertEqual('ABE', obj.stream)
    self.assertEqual([len(s) + 1 + len(t)], end_ofs_out)
    # Exception because start points to '\n', not an `X Y obj'.
    self.assertRaises(
        pdfsizeopt.PdfTokenParseError,
        pdfsizeopt.PdfObj, '%s\n%s' % (s, t), start=len(s))

    s = '22 0 obj<</Producer(A)/CreationDate(B)/Creator(C)>>\nendobj '
    t = '23 0 obj'
    end_ofs_out = []
    obj = pdfsizeopt.PdfObj(s + t, end_ofs_out=end_ofs_out)
    self.assertEqual('<</Producer(A)/CreationDate(B)/Creator(C)>>', obj.head)
    self.assertEqual([len(s)], end_ofs_out) 
    obj = pdfsizeopt.PdfObj(
        '42 0 obj[/Foo%]endobj\n42  43\t]\nendobj')
    # Parses the comment properly, but doesn't replace it with the non-comment
    # version.
    self.assertEqual('[/Foo%]endobj\n42  43\t]', obj.head)
    obj = pdfsizeopt.PdfObj('42 0 obj%hello\r  \t\f%more\n/Foo%bello\nendobj')
    # Leading comments are removed, but trailing comments aren't.
    self.assertEqual('/Foo%bello', obj.head)

    # TODO(pts): Add more tests.

  #def testPdfObjGetInt(self):
  #  

  def testPdfObjGetSet(self):
    obj = pdfsizeopt.PdfObj('42 0 obj<</Foo(hi)>>\t\f\rendobj junk stream\r\n')
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

  def testFindEndOfObj(self):
    def Rest(data, do_rewrite=False):
      return data[pdfsizeopt.PdfObj.FindEndOfObj(
          data, do_rewrite=do_rewrite):]
    self.assertRaises(pdfsizeopt.PdfTokenParseError, Rest, 'foo bar ')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, Rest, 'endobj ')
    self.assertEqual('after', Rest(' endobj after'))
    self.assertEqual('after', Rest('>endobj\rafter'))
    self.assertEqual('after', Rest('foo\t\tbar endobj\nafter'))
    self.assertEqual('after', Rest('foo%stream\r\nbar%baz\rendobj after'))
    self.assertEqual('after', Rest('(hi)endobj after'))
    self.assertEqual('after', Rest('foo bar >>endobj\nafter'))
    self.assertEqual('\n\tafter', Rest('foo bar >>endobj\n\n\tafter'))
    self.assertEqual('\n after', Rest('foo bar >>endobj\r\n after'))
    self.assertEqual('\fafter', Rest('foo bar >>stream\r\n\fafter'))
    self.assertRaises(
        pdfsizeopt.PdfTokenNotSimplest, Rest,
        '((\\)\\)endobj \\\\))endobj\nafter')
    self.assertEqual(
        'after', Rest('((\\)\\)endobj \\\\))endobj\nafter', do_rewrite=True))
    self.assertEqual('after', Rest('(%\nendobj\n)\tendobj\nafter'))
    self.assertEqual('after', Rest('(%)endobj\nafter'))
    self.assertEqual('after', Rest('%((()endobj\n)\tendobj\nafter'))

  def testFindEqclassesAllEquivalent(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual({3: ('<</S(q)/P 3 0 R>>', None)}, new_objs)

  def testFindEqclassesAllEquivalentAndUndefined(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 2 0 R /U 6 0 R>>endobj')
    pdf.objs[2] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 1 0 R /U 7 0 R>>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R /U 8 0 R>>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 3 0 R /U 9 0 R>>endobj')
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual({1: ('<</S(q)/P 1 0 R/U null>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsByHead(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsWithTrailer(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 3 0 R]>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = pdfsizeopt.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
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
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = pdfsizeopt.PdfObj('0 0 obj<</P 1 0 R/S(q)>>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R>>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</P 3 0 R  /S<71>>>endobj')
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None),
         2: ('<</P 1 0 R/S(q)>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsByStream(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 1 0 R >>endobj')
    pdf.objs[2].stream = 'foo';
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    pdf.objs[4].stream = 'foo';
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None),
         2: ('<</S(q)/P 1 0 R>>', 'foo')}, new_objs)

  def testFindEqclassesAllDifferentBecauseOfStream(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<>>endobj')
    pdf.objs[1] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 2 0 R>>endobj')
    pdf.objs[2] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 1 0 R >>endobj')
    pdf.objs[2].stream = 'foo';
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 3 0 R   >>endobj')
    pdf.objs[4].stream = 'fox';
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {1: ('<</S(q)/P 2 0 R>>', None), 2: ('<</S(q)/P 1 0 R>>', 'foo'),
         3: ('<</S(q)/P 4 0 R>>', None), 4: ('<</S(q)/P 3 0 R>>', 'fox')},
        new_objs)

  def testFindEqclassesTwoGroupsWithTrailer(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 3 0 R]>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = pdfsizeopt.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(pdf.objs)
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
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 4 0 R]>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = pdfsizeopt.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[3 0 R 4 0 R 3 0 R 4 0 R 4 0 R]>>', None),
         3: ('<</S(q)/P 4 0 R>>', None),
         4: ('<</S(q)/Q 3 0 R>>', None)}, new_objs)

  def testFindEqclassesTwoGroupsWithTrailerRenumber(self):
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj(
        '0 0 obj<</A[3 0 R 4 0 R 5 0 R 6 0 R 4 0 R]>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 6 0 R>>endobj')
    pdf.objs[6] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 5 0 R >>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/P 4 0 R  >>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</S(q)/Q 3 0 R   >>endobj')
    pdf.objs[10] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[11] = pdfsizeopt.PdfObj('0 0 obj[10 0 R]endobj')
    pdf.objs[12] = pdfsizeopt.PdfObj('0 0 obj[11 0 R]endobj')
    pdf.objs[12].stream = 'blah'
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True, do_renumber=True)
    del pdf.objs['trailer']
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[2 0 R 1 0 R 2 0 R 1 0 R 1 0 R]>>', None),
         2: ('<</S(q)/P 1 0 R>>', None),
         1: ('<</S(q)/Q 2 0 R>>', None)}, new_objs)

  def testFindEqclassesCircularReferences(self):
    pdf = pdfsizeopt.PdfData()
    # The Rs are needed in the trailer, otherwise objects would be discarded.
    pdf.trailer = pdfsizeopt.PdfObj('0 0 obj<<4 0 R 5 0 R 9 0 R 10 0 R>>endobj')
    pdf.objs[4] = pdfsizeopt.PdfObj('0 0 obj<</Parent  1 0 R/Type/Pages/Kids[9 0 R]/Count 1>>endobj')
    pdf.objs[5] = pdfsizeopt.PdfObj('0 0 obj<</Parent 1  0 R/Type/Pages/Kids[10 0 R]/Count 1>>endobj')
    pdf.objs[9] = pdfsizeopt.PdfObj('0 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]/Parent 4 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>/Contents 3 0 R>>endobj')
    pdf.objs[10] = pdfsizeopt.PdfObj('10 0 obj<</Type/Page/MediaBox[0 0 419 534]/CropBox[0 0 419 534]/Parent 5 0 R/Resources<</XObject<</S 2 0 R>>/ProcSet[/PDF/ImageB]>>/Contents 3 0 R>>endobj')
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(
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
    pdf = pdfsizeopt.PdfData()
    pdf.trailer = pdfsizeopt.PdfObj(
        '0 0 obj<</A[3 0 R]>>endobj')
    pdf.objs[3] = pdfsizeopt.PdfObj('0 0 obj<</A()/B<>/C(:)/D<3a3A4>>>endobj')
    pdf.objs['trailer'] = pdf.trailer
    new_objs = pdfsizeopt.PdfData.FindEqclasses(
        pdf.objs, do_remove_unused=True, do_renumber=True)
    for obj_num in new_objs:
      new_objs[obj_num] = (new_objs[obj_num].head, new_objs[obj_num].stream)
    self.assertEqual(
        {'trailer': ('<</A[1 0 R]>>', None),
         1: ('<</A()/B()/C(:)/D(::@)>>', None)}, new_objs)

  def testParseAndSerializeCffDict(self):
    # TODO(pts): Add more tests.
    # TODO(pts): Add test for PdfObj.ParseCffHeader.
    cff_dict = {
        12000: [394], 1: [391], 2: [392], 3: [393], 12004: [0],
        5: [0, -270, 812, 769],
        12007: ['0.001', 0, '0.000287', '0.001', 0, 0], 15: [281], 16: [245],
        17: [350], 18: [21, 6489], 12003: [0]
    }
    cff_str =  ('f81b01f81c02f81d038bfba2f9c0f99505f81e0c008b0c038b0c'
                '041e0a001f8b1e0a000287ff1e0a001f8b8b0c07a01c195912f7'
                'f211f7ad0ff78910'.decode('hex'))
    cff_str2 = ('f81b01f81c02f81d038bfba2f9c0f99505f7ad0ff78910f7f211'
                'a01c195912f81e0c008b0c038b0c041e0a001f8b1e0a000287ff'
                '1e0a001f8b8b0c07'.decode('hex'))
    self.assertEqual(cff_dict, pdfsizeopt.PdfObj.ParseCffDict(cff_str))
    self.assertEqual(cff_dict, pdfsizeopt.PdfObj.ParseCffDict(cff_str2))
    self.assertEqual(cff_str2, pdfsizeopt.PdfObj.SerializeCffDict(cff_dict))

  def testParseCffDifferent(self):
    # Different integer representations have different length.
    self.assertEqual({17: [410]}, pdfsizeopt.PdfObj.ParseCffDict(
        '\x1d\x00\x00\x01\x9a\x11'))
    self.assertEqual({17: [410]}, pdfsizeopt.PdfObj.ParseCffDict(
        '\xf8.\x11'))
    self.assertEqual('\xf8.\x11', pdfsizeopt.PdfObj.SerializeCffDict(
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
    cff_dict = pdfsizeopt.PdfObj.ParseCffDict(data=data, start=i, end=j)
    cff_ser = pdfsizeopt.PdfObj.SerializeCffDict(cff_dict=cff_dict)
    cff_dict2 = pdfsizeopt.PdfObj.ParseCffDict(cff_ser)
    cff_ser2 = pdfsizeopt.PdfObj.SerializeCffDict(cff_dict=cff_dict2)
    self.assertEqual(cff_dict, cff_dict2)
    self.assertEqual(cff_ser, cff_ser2)
    # We could emit an optiomal serialization.
    self.assertTrue(len(cff_ser) < len(data[i : j]))

  def testFixPdfFromMultivalent(self):
    e = pdfsizeopt.PdfData.FixPdfFromMultivalent
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
         '<</Type   /Catalog/Pages 1 0 R>>endobj\n'
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
         '\x00\x00\x00\x0f\x00W\x00\x86\x00\xd2\x01t\x01\xcf'
             'endstream endobj\n'
         'startxref\n'
         '463\n'
         '%%EOF\n')
    output = []
    e(s, output=output, do_generate_object_stream=False)
    self.assertEqual(t, ''.join(output))
    # !! test with xref ... trailer <</Size 6/Root 2 0 R/Compress<</LengthO 7677/SpecO/1.2>>/ID[(...)(...)]>> ... startxref

  def testPermissiveZlibDecompress(self):
    e = pdfsizeopt.PermissiveZlibDecompress
    data = 'Hello, World!' * 42
    compressed = zlib.compress(data, 9)
    self.assertEqual(data, e(compressed))
    self.assertEqual(data, e(compressed[:-1]))
    self.assertEqual(data, e(compressed[:-2]))
    self.assertEqual(data, e(compressed[:-3]))
    self.assertEqual(data, e(compressed[:-4]))
    self.assertRaises(zlib.error, e, compressed[:-5])

  def testResolveReferences(self):
    def NewObj(head, stream=None, do_compress=False):
      obj = pdfsizeopt.PdfObj(None)
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
    e = pdfsizeopt.PdfObj.ResolveReferences
    self.assertEqual(('/FooBar  true', False), e('/FooBar  true', objs))
    self.assertEqual(('/FooBaR  true', False), e('/FooBaR  true', objs))
    self.assertEqual(('foo  bar', True), e('12 0 R', objs))
    self.assertEqual(('\rfoo  bar\t', True), e('\r12 0 R\t', objs))
    self.assertEqual(('[true\ffoo  bar false\nfoo  bar]', True),
                     e('[true\f12 0 R false\n12 0 R]', objs))
    self.assertEqual(('foo  bar<>', True), e('12 0 R<>', objs))
    # A comment or a (string) in the referrer triggers full compression.
    self.assertEqual(('foo bar()', True), e('%9 0 R\n12 0 R<>', objs))
    # A `(string)' in the referrer triggers full compression.
    self.assertEqual(('(9 0 R[ ])foo bar', True),
                     e('(9 0 R[\040])12 0 R', objs))
    self.assertRaises(pdfsizeopt.PdfReferenceTargetMissing, e, '98 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfReferenceTargetMissing, e, '21 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '0 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '-1 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfTokenParseError, e, '1 12 R', objs)
    self.assertRaises(pdfsizeopt.PdfReferenceRecursiveError, e, '31 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfReferenceRecursiveError, e, '32 0 R', objs)
    self.assertRaises(pdfsizeopt.PdfReferenceRecursiveError, e, '33 0 R', objs)
    self.assertEqual(('(13  0 R)', False), e('(13  0 R)', objs))
    self.assertEqual(('<</A foo  bar>>', True), e('<</A 13  0 R>>', objs))
    self.assertEqual(('(12 0  R \0)', True), e('(12 0  R \\000)', objs))
    self.assertEqual(('foo bar  bat   baz', True), e('16 0 R   baz', objs))
    # Unexpected stream.
    self.assertRaises(pdfsizeopt.UnexpectedStreamError, e, '41 0 R', objs)
    self.assertRaises(pdfsizeopt.UnexpectedStreamError, e, '42 0 R', objs)
    self.assertEqual(('(hello)', True), e('41 0 R', objs, do_strings=True))
    self.assertEqual(('(xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx)', True),
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
    f = pdfsizeopt.PdfObj.ParseTokenList
    self.assertEqual(repr([42, True]), repr(f('42 true')))
    self.assertEqual([], f(''))
    self.assertEqual([], f(' \t'))
    self.assertEqual(['<666f6f>', 6, 7], f(' \n\r(foo)\t6%foo\n7'))
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7(')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7[')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7<<')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7)')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7]')
    self.assertRaises(pdfsizeopt.PdfTokenParseError, f, ' \n\r(foo)\t6\f7>>')
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

if __name__ == '__main__':
  unittest.main(argv=[sys.argv[0], '-v'] + sys.argv[1:])
