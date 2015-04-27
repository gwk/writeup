#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import sys
import re
import html

default_css = '''
a { background-color: transparent; }
a:active { outline: 0; }
a:hover { outline: 0; }
blockquote {
  border-left-color: #E0E0E0;
  border-left-style: solid;
  border-left-width: 0.25rem;
  margin: 0;
  padding: 0 1rem;
}
body { margin: 1rem; }
body footer {
  margin: 1rem 0 0 0;
  font-size: .875rem;
  color: #606060;
}
code {
  background-color: rgba(0, 0, 0, 0.1);
  border-radius: 3px;
  font-family: source code pro, menlo, terminal, monospace;
}
footer { display: block; }
h1 { font-size: 2.0rem; margin: 1.4rem 0 0.6rem 0; }
h2 { font-size: 1.6rem; margin: 1.2rem 0 0.5rem 0; }
h3 { font-size: 1.4rem; margin: 1.1rem 0 0.5rem 0; }
h4 { font-size: 1.2rem; margin: 1.0rem 0 0.5rem 0; }
h5 { font-size: 1.1rem; margin: 1.0rem 0 0.5rem 0; }
h6 { font-size: 1.0rem; margin: 1.0rem 0 0.5rem 0; }
header { display: block; }
html {
  background: white;
  color: black; 
  font-family: sans-serif;
  font-size: 1rem;
}
section { display: block; }
nav { display: block; }
p { margin: 0.5rem 0; }
pre {
  background: #F0F0F0;
  font-family: source code pro, menlo, terminal, monospace;
  font-size: 1rem;
  overflow: auto;
  padding: 0.1rem;
}
ul {
  line-height: 1.2;
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
s_start, s_license, s_hash, s_bullet, s_quote, s_indent, s_blank, s_text, s_end = range(9)

state_letters = 'SLHBQIKTE'

matchers = [
  (s_hash, re.compile(r'(#+)(\s*)(.*)\n')),
  (s_bullet, re.compile(r'(\s*)•(\s*)(.*)\n')),
  (s_quote, re.compile(r'> (.*\n)')),
  (s_indent, re.compile(r'  (.*)\n')),
  (s_blank, re.compile(r'(\s*)\n')),
]


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
# the first choice clause captures these chunks in group 1;
# other choice clauses cause group 1 to hold None.
# we could do more agressive minification but this is good enough for now.
minify_css_re = re.compile(r'(?<=: )(.+?;)|\s+|/\*.*?\*/', flags=re.S)

def minify_css(src):
  chunks = []
  for chunk in minify_css_re.split(src):
    if chunk: # discard empty chunks and splits that are None (not captured).
      chunks.append(chunk)
  return ' '.join(chunks) # use empty string joiner for more aggressive minification.


def writeup_body(in_lines, line_offset):
  'from input writeup lines, generate a list of html lines.'
  out_lines = []
  def out(depth, *items):
    s = ' ' * (depth * 2) + ''.join(items)
    out_lines.append(s)

  # state variables used by writeup_line.
  section_depth = 0
  list_depth = 0
  license_lines = []
  pre_lines = []
  quote_line_num = 0
  quote_lines = []

  def writeup_line(line_num, line, prev_state, state, groups):
    'process a line.'
    nonlocal section_depth
    nonlocal list_depth
    nonlocal quote_line_num

    #errF('{:03}{}{}: {}', line_num + 1, state_letters[prev_state], state_letters[state], line)

    def warn(fmt, *items):
      errFL('warning: line {}: ' + fmt, line_offset + line_num + 1, *items)
      errFL("  '{}'", repr(line))

    def error(fmt, *items):
      fail('error: line {}: ' + fmt, line_offset + line_num + 1, *items)

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

    inline_split_re = re.compile(r'(`(?:[^`]|\\`)*`)')
    inline_chunk_re = re.compile(r'`((?:[^`]|\\`)*)`')
    inline_space_re = re.compile(r'( +)')
    def conv(text):
      # lame that we have to split, then match again to tell what kind of chunk we have.
      chunks = inline_split_re.split(text)
      converted = []
      for c in chunks:
        m = inline_chunk_re.fullmatch(c)
        if m:
          g = m.group(1)
          code = inline_space_re.sub(lambda sm: '&nbsp;' * len(sm.group(1)), esc(g))
          converted.append('<code>{}</code>'.format(code))
        else:
          converted.append(esc(c))
      return ''.join(converted)

    # transition.
    if prev_state == s_start:
      pass
    elif prev_state == s_license:
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
        # therefore we must take care to format the pre contents without a final newline.
        out(0, '<pre>\n{}</pre>'.format('\n'.join(pre_lines)))
        pre_lines.clear()
    
    elif prev_state == s_quote:
      if state != s_quote:
        out(section_depth, '<blockquote>')
        for ql in writeup_body(quote_lines, quote_line_num):
          out(section_depth + 1, ql)
        out(section_depth, '</blockquote>')
        quote_lines.clear()
    
    elif prev_state == s_blank:
      pass

    elif prev_state == s_text:
      if state == s_text:
        out(section_depth, '<br />')
      else:
        out(section_depth, '</p>')
    
    else:
      error('bad prev_state: {}', prev_state)

    # output text.

    if state == s_hash:
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
      out(depth, '<h{}>{}</h{}>'.format(h, conv(text), h))
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
      out(section_depth + depth, '<li>{}</li>'.format(conv(text)))
      list_depth = depth

    elif state == s_indent:
      text, = groups
      pre_lines.append(esc(text))

    elif state == s_quote:
      quoted_line, = groups
      if state != s_quote:
        quote_line_num = line_num
      quote_lines.append(quoted_line) # not converted here; text is fully transformed later.

    elif state == s_blank:
      spaces, = groups
      if len(spaces):
        warn('blank line is not empty')

    elif state == s_text:
      # TODO: check for strange characters that html will ignore.
      if not line.endswith('\n'):
        warn("missing newline ('\\n')")
      text = line.strip()
      if prev_state != s_text:
        out(section_depth, '<p>')
      out(section_depth + 1, conv(text))

    elif state == s_end:
      for i in range(section_depth, 0, -1):
        out(i - 1, '</section>')
      if license_lines:
        out(0, '<footer>\n', '<br />'.join(license_lines), '\n</footer>')

    else:
      error('bad state: {}', state)


  prev_state = s_start
  for line_num, line in enumerate(in_lines):
    # any license notice at top gets moved to a footer at the bottom of the html.
    if prev_state == s_start and license_re.fullmatch(line):
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


def writeup(in_lines, line_offset, title, description, author, css):
  'generate a complete html document from a writeup file (or stream of lines).'

  lines = writeup_body(in_lines, line_offset)
  lines.insert(0, '''\
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
  lines.append('</body>\n</html>')
  return lines


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

