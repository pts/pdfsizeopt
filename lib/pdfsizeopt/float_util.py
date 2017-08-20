"""Floating point number utilities."""

def FormatFloatShort(f, is_int_ok=False):
  """Formats a float accurately as a string as short as possible.

  Args:
    f: A value of type float.
    is_int_ok: If false, int(result) will raise a ValueError, because the result
      always contains 'e' or '.'. If true, it's OK for the result to contain
      only digits and '-' (and thus parse as an int).
  Returns:
    An str, for which float(result) == f, and len(result) is as short as
    possible.
  """
  if not isinstance(f, float):
    raise TypeError
  r = repr(f)
  if r[-1] not in '0123456789':  # 'inf', '-inf', 'nan' etc.
    return r
  m = '-' * r.startswith('-')
  r = r.lstrip('-')
  es = r.split('e')
  assert len(es) in (1, 2)
  e0 = es[0].rstrip('0')
  assert e0[0] in '0123456789', e0  # Can start with 0, e.g. '0.00123'.
  i = e0.find('.') + 1
  if i > 0:
    e0 = e0[:i - 1] + e0[i:]
    i = (i - 1) - len(e0)
  e0 = e0.lstrip('0')
  if not e0:
    if is_int_ok:
      return m + '0'  # It's important that '-0' is different from '0'.
    return m + '0.'
  nd = len(e0)
  assert 1 <= nd <= 17, (r, es, nd)

  rr = ''
  if nd > 2:  # Try to format it with 2 fewer digits.
    rr = '%%.%dg' % (nd - 2) % f
    if float(rr) != f or len(rr) >= len(r):
      rr = ''
  if nd > 1 and not rr:  # Try to format it with 1 fewer digit.
    rr = '%%.%dg' % (nd - 1) % f
    if float(rr) != f or len(rr) >= len(r):
      rr = ''
  if rr:  # A shorter formatting has succeeded.
    r = rr
    m = '-' * r.startswith('-')
    r = r.lstrip('-')
    es = r.split('e')
    assert len(es) in (1, 2)
    e0 = es[0].rstrip('0')
    assert e0[0] in '0123456789', e0  # Can start with 0, e.g. '0.00123'
    i = e0.find('.') + 1
    if i > 0:
      e0 = e0[:i - 1] + e0[i:]
      i = (i - 1) - len(e0)
    e0 = e0.lstrip('0')
    nd = len(e0)
    assert 1 <= nd <= 17, (r, es, nd)

  assert i <= 0, (r, es, e0, i)
  if len(es) > 1:
    i += int(es[1])
  if e0.endswith('0'):
    j = len(e0)
    e0 = e0.rstrip('0')
    i += j - len(e0)
  # Now e0 is the formatted significand (as an integer, no dots, the dot is
  # implied in the end), i is the exponent, m is the sign.

  if i > 1 or i < -2 -len(e0):
    if i == 2 and is_int_ok:
      return '%s%s00' % (m, e0)
    return '%s%se%d' % (m, e0, i)
  elif 1 <= -i <= len(e0):
    return '%s%s.%s' % (m, e0[:i], e0[i:])
  elif 0 <= i <= 1:  # Number of '0's added below: 1 or 2.
    return '%s%s%s%s' % (m, e0, '0' * i, '.' * (not is_int_ok))
  else:  # Number of '0's added below: 1 or 2.
    return '%s.%s%s' % (m, '0' * (-i - len(e0)), e0)
