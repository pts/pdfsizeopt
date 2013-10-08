#! /usr/bin/python2.4
# by pts@fazekas.hu at Tue Jul 21 16:14:10 CEST 2009

import re
import sys
import os


def main(argv):
  map_list = []

  cfg_kname = (os.popen('kpsewhich --progname=dvipdfmx dvipdfmx.cfg')
              .read().rstrip('\n'))
  for cfg_line in open(cfg_kname).xreadlines():
    cfg_items = cfg_line.strip().split(None, 1)
    if len(cfg_items) == 2 and cfg_items[0] == 'f':
      map_list.append(cfg_items[1])

  i = 1
  while i < len(argv):
    if argv[i] == '-f' and i < len(argv) - 1:
      map_list.append(argv[i + 1])
      i += 2
    elif argv[i].startswith('-f'):
      map_list.append(argv[i][2:])
    else:
      break

  f = open('dvipdfmx_base.map', 'w')

  for map_name in map_list:
    assert '$' not in map_name
    assert '"' not in map_name
    assert '\\' not in map_name
    assert '%' not in map_name
    map_kname = (os.popen('kpsewhich "%s"' % map_name)
                .read().rstrip('\n'))
    assert map_kname, 'font map not found: %s' % map_name
 
    for map_line in open(map_kname).xreadlines():
      # A to-be-reencoded base font. Example:
      # ptmr8r Times-Roman "TeXBase1Encoding ReEncodeFont" <8r.enc
      match = re.match(r'\s*([^%\s]\S*)\s+(\S+)\s+(?:\d+\s+)?"([^"]*)"\s+'
                       r'<(\S+)[.]enc\s*\Z', map_line)
      if match:
        #print map_line,
        tex_font_name = match.group(1)
        ps_font_name = match.group(2)
        ps_instructions = ' %s ' % re.sub('\s+', ' ', match.group(3).strip())
        enc_file_name = match.group(4)
        dvipdfm_instructions = []
        # TODO(pts): Obey the order
        match = re.match(' (\S+) SlantFont ', ps_instructions)
        if match:
          dvipdfm_instructions.append(' -s %s' % match.group(1))
        match = re.match(' (\S+) ExtendFont ', ps_instructions)
        if match:
          dvipdfm_instructions.append(' -e %s' % match.group(1))
        f.write('%s %s %s%s\n' %
                (tex_font_name, enc_file_name, ps_font_name,
                 ' '.join(dvipdfm_instructions)))

  f.close()
  args = ['dvipdfmx', '-f', 'dvipdfmx_base.map'] + argv[1:]
  sys.stdout.flush()
  sys.stderr.flush()
  os.execlp(args[0], *args)

if __name__ == '__main__':
  sys.exit(main(sys.argv) or 0)
