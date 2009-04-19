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
    e = pdfsizeopt.PDFObj.EscapeString
    self.assertEqual('()', e(''))
    self.assertEqual('(Hello, World!)', e('Hello, World!'))
    s = ''.join([c for c in map(chr, xrange(255, -1, -1)) if c not in '()\\'])
    self.assertEqual('(%s)' % s, e(s))
    self.assertEqual('(Hello, \\)\\(Wo\\\\rld!)', e('Hello, )(Wo\\rld!'))
    #!!self.assertEqual('((((foo\\\\))))', '(((foo\\)))')

  #def testBar(self):
  #  pass # !!print 'BAR'

if __name__ == '__main__':
  unittest.main(argv=[sys.argv[0], '-v'] + sys.argv[1:])
