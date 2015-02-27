#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import sys
import re
import html

default_css = '''
a { background-color: transparent; }
a:active { outline: 0; }
a:hover { outline: 0; }
body { margin: 1rem; }
body footer {
  margin: 1rem 0 0 0;
  font-size: .875rem;
  color: #606060;
}
footer { display: block; }
h1 { font-size: 2.0rem; margin: 1.20rem 0 0.6rem 0; }
h2 { font-size: 1.6rem; margin: 0.96rem 0 0.5rem 0; }
h3 { font-size: 1.4rem; margin: 0.84rem 0 0.5rem 0; }
h4 { font-size: 1.2rem; margin: 0.72rem 0 0.5rem 0; }
h5 { font-size: 1.1rem; margin: 0.66rem 0 0.5rem 0; }
h6 { font-size: 1.0rem; margin: 0.60rem 0 0.5rem 0; }
header { display: block; }
html {
  background: white;
  color: black; 
  font-family: sans-serif;
  font-size: 1rem;
}
section { display: block; }
nav { display: block; }
p { margin: 0; }
pre {
  background: #EEEEEE;
  font-family: source code pro, menlo, terminal, monospace;
  font-size: 1rem;
  overflow: auto;
  padding: 0.1rem;
}
ul {
  list-style-type: disc;
  margin: 0;
  padding: 0 1rem;
}
'''

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


# need to preserve spaces in between multiple words followed by semicolon,
# for cases like `margin: 0 0 0 0;`.
# the first option of this re is captures these chunks; other splits will return None.
# we could be more agressive but this is good enough for now.
minify_css_re = re.compile(r'(?<=: )(.+?;)|\s+|/\*.+?\*/', flags=re.S)

def minify_css(src):
  chunks = []
  for chunk in minify_css_re.split(src):
    if chunk: # discard empty chunks and splits that are None (not captured).
      chunks.append(chunk)
  return ' '.join(chunks) # use empty string joiner for more aggressive minification.


def writeup(in_lines, line_offset, title, description, author, css):
  'generate html from a writeup file (or stream of lines).'

  out_lines = []
  def out(depth, *items):
    s = ' ' * (depth * 2) + ''.join(items)
    out_lines.append(s)

  out(0, '''\
<html>
<head>
  <meta charset="utf-8">
  <title>{}</title>
  <meta name="description" content="{}">
  <meta name="author" content="{}">
  <style text="text/css">{}</style>
</head>
<body>\
'''.format(title, description, author, css))

  # state variables used by writeup_line.
  section_depth = 0
  list_depth = 0
  license_lines = []
  pre_lines = []

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
          out(section_depth + (i - 1), '</ul>')
        list_depth = 0
    elif prev_state == s_indent:
      if state != s_indent:
        # a newline after the open tag looks ok,
        # but a final newline between pre content and the close tag looks bad.
        out(0, '<pre>\n{}</pre>'.format('\n'.join(pre_lines)))
        pre_lines.clear()
    elif prev_state == s_text:
      if state != s_text:
        out(section_depth, '</p>')
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
          out(i, '<section class="s{}">'.format(i + 1))
      elif section_depth > depth: # surface; close prev child sections and open new peer.
        for i in range(section_depth, depth - 1, -1):
          out(i - 1, '</section>')
        out(depth - 1, '<section class="s{}">'.format(depth))
      else: # close current section and open new peer.
        out(depth - 1, '</section>')
        out(depth - 1, '<section class="s{}">'.format(depth))
      out(depth, '<h{}>{}</h{}>'.format(h, esc(text), h))
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
        out(section_depth + (i - 1), '</ul>')
      for i in range(list_depth, depth):
        out(section_depth + i, '<ul class="l{}">'.format(i + 1))
      out(section_depth + depth, '<li>{}</li>'.format(esc(text)))
      list_depth = depth

    elif state == s_indent:
      text, = groups
      pre_lines.append(esc(text))

    elif state == s_text:
      # TODO: check for strange characters that html will ignore.
      if not line.endswith('\n'):
        warn("missing newline ('\\n')")
      text = line.strip()
      if prev_state != s_text:
        out(section_depth, '<p>')
      out(section_depth + 1, esc(text))

    elif state == s_end:
      for i in range(section_depth, 0, -1):
        out(i - 1, '</section>')
      if license_lines:
        out(0, '<footer>\n', '<br />'.join(license_lines), '\n</footer>')
      out(0, '</body>\n</html>')

    else:
      fail('bad state: {}', state)


  prev_state = s_begin
  for line_num, line in enumerate(in_lines):
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
  return out_lines


if __name__ == '__main__':
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
  css = minify_css(default_css)
  lines = writeup(f_in, line_offset=1, title=('stdin' if len_args == 0 else args[0]),
    description='', author='', css=css)
  for line in lines:
    print(line, file=f_out)

