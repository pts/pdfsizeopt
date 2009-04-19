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
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '(foo')
    self.assertRaises(pdfsizeopt.PdfTokenTruncated, e, '(foo\\)bar')
    self.assertEqual(' <face654389210b7d>', e('< f\nAc\tE\r654389210B7d\f>'))
    self.assertEqual(' <48656c6c6f2c20576f726c6421>', e('(Hello, World!)'))
    self.assertEqual(' <2828666f6f29295c296261725c>', e('(((foo))\\)bar\\\\)'))
    self.assertEqual(' <face422829>', e('(\xfa\xCE\x42())'))
    self.assertEqual(' 0', e('00000 '))
    self.assertEqual(' 0', e('+00000 '))
    self.assertEqual(' 0', e('-00000 '))
    self.assertEqual(' 0', e('00000.000 '))
    self.assertEqual(' 0', e('+00000.000 '))
    self.assertEqual(' 0', e('-00000.000 '))
    self.assertEqual(' 12', e('00012 '))
    self.assertEqual(' 12', e('+00012 '))
    self.assertEqual(' -12', e('-00012 '))
    self.assertEqual(' 12', e('00012.000 '))
    self.assertEqual(' 12', e('+00012.000 '))
    self.assertEqual(' -12', e('-00012.000 '))
    self.assertEqual(' 12.34', e('00012.340 '))
    self.assertEqual(' 12.34', e('+00012.340 '))
    self.assertEqual(' -12.34', e('-00012.340 '))
    # TODO(pts): More tests, especially strings.


if __name__ == '__main__':
  unittest.main(argv=[sys.argv[0], '-v'] + sys.argv[1:])
