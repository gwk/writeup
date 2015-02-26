#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/

import sys
import re
import html


def errF(fmt, *items):
  print(fmt.format(*items), end='', file=sys.stderr)

def errFL(fmt, *items):
  print(fmt.format(*items), file=sys.stderr)

def fail(fmt, *items):
  errFL(fmt, *items)
  sys.exit(1)

def check(cond, fmt, *items):
  if not cond:
    fail(fmt, *items)


# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.
version_pattern = r'writeup v(\d+)\n'
version_re = re.compile(version_pattern)

# license pattern is is only applied to the first line (following the version line, if any).
license_re = re.compile(r'(©|Copyright|Dedicated to the public domain).*\n')

# line states.
s_begin, s_license, s_blank, s_hash, s_bullet, s_indent, s_text, s_end = range(8)

matchers = [
  (s_blank, re.compile(r'(\s*)\n')),
  (s_hash, re.compile(r'(#+)(\s*)(.*)\n')),
  (s_bullet, re.compile(r'(\s*)•(\s*)(.*)\n')),
  (s_indent, re.compile(r'  (.*)\n'))]


def writeup(f_in, f_out, line_offset):
  'generate html from a writeup file (or stream of lines).'

  def out(depth, *items):
    print(' ' * (depth * 2), *items, sep='', end='', file=f_out)

  def outL(depth, *items):
    print(' ' * (depth * 2), *items, sep='', file=f_out)

  outL(0, '''\
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/> 
  <style text="text/css">
    body {
      color: black; 
      background: white;
      font-family: sans-serif;
      font-size: 1em;
    }
    body footer {
      margin: 1em 0 0 0;
      font-size: .875em;
      color: #606060;
    }
    h1 { font-size: 1.802032470703125em; }
    h2 { font-size: 1.601806640625em; }
    h3 { font-size: 1.423828125em; }
    h4 { font-size: 1.265625em; }
    h5 { font-size: 1.125em; }
    h6 { font-size: 1.0em; }
    pre {
      background: #EEEEEE;
      font-family: source code pro, menlo, terminal, monospace;
      font-size: 1em;
    }
    ul {
      list-style-type: disc;
      padding: 0 1em;
    }
''')

  # TODO: custom CSS here?

  outL(0, '''\
  </style>
</head>
<body>
''')

  # state variables used by writeup_line.
  section_depth = 0
  list_depth = 0
  license_lines = []

  def writeup_line(line_num, line, prev_state, state, groups):
    'process a line.'
    nonlocal section_depth
    nonlocal list_depth
    nonlocal license_lines

    def warn(fmt, *items):
      errFL('warning: line {}: ' + fmt, line_offset + line_num + 1, *items)
      errFL("  '{}'", repr(line))

    def check_whitespace(len_exp, string, msg_suffix=''):
      for i, c in enumerate(string):
        if c != ' ':
          warn("invalid whitespace character at position {}{}: {}",
            i + 1, msg_suffix, repr(c))
          return False
      if len_exp >= 0 and len(string) != len_exp:
        warn('expected exactly {} space{}{}; found: {}',
          len_exp, '' if len_exp == 1 else 's', msg_suffix, len(string))
        return False
      return True

    def esc(text):
      return html.escape(text, quote=False)

    # transition.
    if prev_state == s_begin:
      pass
    if prev_state == s_license:
      pass
    elif prev_state == s_blank:
      pass
    elif prev_state == s_hash:
      pass
    elif prev_state == s_bullet:
      if state != s_bullet:
        for i in range(list_depth, 0, -1):
          outL(section_depth + (i - 1), '</ul>')
        list_depth = 0
    elif prev_state == s_indent:
      if state != s_indent:
        outL(0, '</pre>')
    elif prev_state == s_text:
      if state != s_text:
        outL(section_depth, '</p>')
    else:
      fail('bad prev_state: {}', prev_state)

    # output text.

    if state == s_blank:
      spaces, = groups
      if len(spaces):
        warn("blank line is not empty: spaces: '{}'", repr(spaces))

    elif state == s_hash:
      hashes, spaces, text = groups
      check_whitespace(1, spaces)
      depth = len(hashes)
      h = min(6, depth)
      if section_depth < depth: # deepen.
        for i in range(section_depth, depth):
          outL(i, '<section class="s{}">'.format(i + 1))
      elif section_depth > depth: # surface; close prev child sections and open new peer.
        for i in range(section_depth, depth - 1, -1):
          outL(i - 1, '</section>')
        outL(depth - 1, '<section class="s{}">'.format(depth))
      else: # close current section and open new peer.
        outL(depth - 1, '</section>')
        outL(depth - 1, '<section class="s{}">'.format(depth))
      outL(depth, '<h{}>{}</h{}>'.format(h, esc(text), h))
      section_depth = depth

    elif state == s_bullet:
      indents, spaces, text = groups
      check_whitespace(-1, indents, ' in indent')
      l = len(indents)
      if l % 2:
        warn('odd indentation: {}', l)
      depth = l // 2 + 1
      check_whitespace(1, spaces, ' following bullet')
      for i in range(list_depth, depth, -1):
        outL(section_depth + (i - 1), '</ul>')
      for i in range(list_depth, depth):
        outL(section_depth + i, '<ul class="l{}">'.format(i + 1))
      outL(section_depth + depth, '<li>{}</li>'.format(esc(text)))
      list_depth = depth

    elif state == s_indent:
      text, = groups
      if prev_state != s_indent:
        out(section_depth, '<pre>')
      out(0, '\n', esc(text))

    elif state == s_text:
      # TODO: check for strange characters that html will ignore.
      if not line.endswith('\n'):
        warn("missing newline ('\\n')")
      text = line.strip()
      if prev_state != s_text:
        outL(section_depth, '<p>')
      outL(section_depth + 1, esc(text))

    elif state == s_end:
      for i in range(section_depth, 0, -1):
        outL(i - 1, '</section>')
      if license_lines:
        outL(0, '<footer>\n', '<br />'.join(license_lines), '\n</footer>')
      outL(0, '</body>\n</html>')

    else:
      fail('bad state: {}', state)


  prev_state = s_begin
  for line_num, line in enumerate(f_in):
    # any license notice at top gets moved to a footer at the bottom of the html.
    if prev_state == s_begin and license_re.fullmatch(line):
      license_lines.append(line.strip())
      prev_state = s_license
      continue
    if prev_state == s_license: # consume remaining license lines.
      l = line.strip()
      if l: # not empty.
        license_lines.append(l)
        continue # remain in s_license.

    # license has ended; determine state.
    state = s_text # default if no patterns match.
    groups = None
    for s, r in matchers:
      m = r.fullmatch(line)
      if m:
        state = s
        groups = m.groups()
        break

    writeup_line(line_num, line, prev_state, state, groups)
    prev_state = state

  # finish.
  writeup_line(None, None, prev_state, s_end, None)


def main():
  len_args = len(sys.argv) - 1
  args = sys.argv[1:]
  check(len_args <= 2, 
    'expects 0 args (stdin -> stdout), 1 arg (path -> stdout), or 2 args (path -> path)')
  f_in  = sys.stdin if len_args == 0 else open(args[0])
  f_out = sys.stdout if len_args < 2 else open(args[1], 'w')
  version_line = f_in.readline()
  m = version_re.fullmatch(version_line)
  check(m, 'first line must specify writeup version matching pattern: {}\nfound: {}',
    repr(version_pattern), repr(version_line))
  v = int(m.group(1))
  check(v == 0, 'unsupported version number: {}', v)
  version = int(m.group(1))
  writeup(f_in, f_out, line_offset=1)


main()
