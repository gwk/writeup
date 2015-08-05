#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import argparse
import html
import re
import sys


css = '''
a { background-color: transparent; }
a:active { outline: 0; }
a:hover { outline: 0; }
blockquote {
  border-left-color: #E0E0E0;
  border-left-style: solid;
  border-left-width: 0.333rem; /* matches width of ul bullets. */
  margin: 0;
  padding: 0 0.677rem; /* matches width of ul bullet margin; how can we set that explicitly?. */
}
body {
  margin: 1rem;
  }
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
h1 {
  border-top-color: #E8E8E8;
  border-top-style: solid;
  border-top-width: 1px;
}
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
  font-family: source sans pro, sans-serif;
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
  line-height: 1.333rem;
  list-style-type: none;
  margin: 0rem;
  padding: 0rem;
}
ul > ul {
  padding-left: 0.667rem;
}
'''

presentation_css = '''
.S1 {
  min-height: 100%;
}
'''

js = '''
window.onkeydown = function(e) { 
  //return !(e.keyCode == 32);
};

function scrollToSection(id){
    var section = document.getElementById(id);
    //section.style.display = 'block';
    section.scrollIntoView(true);
    return false;
}
'''

# onclick=esc_attr('return scrollToSection("{}")'.format(next_sid)
# '<... onclick="{onclick}">'.format(onclick=onclick)


# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.
version_pattern = r'writeup v(\d+)\n'
version_re = re.compile(version_pattern)

# license pattern is is only applied to the first line (following the version line, if any).
license_re = re.compile(r'(©|Copyright|Dedicated to the public domain).*\n')

# line states.
s_start, s_license, s_section, s_list, s_quote, s_code, s_blank, s_text, s_end = range(9)

state_letters = '_©SLQCBTE'

matchers = [
  (s_section, re.compile(r'(#+)(\s*)(.*)\n')),
  (s_list, re.compile(r'(\s*)-(\s*)(.*)\n')),
  (s_quote, re.compile(r'> (.*\n)')),
  (s_code, re.compile(r'\| (.*)\n')),
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


def esc(text):
  return html.escape(text, quote=False)

def esc_attr(text):
  return html.escape(text, quote=True)


# inline span handling.

# general pattern for quoting with escapes is Q([^EQ]|EQ|EE)*Q.
# it is crucial that the escape character E is excluded in the '[^EQ]' clause,
# or else when matching against 'QEQQ', the pattern greedily matches 'QEQ'.
# to enable all inputs, the 'EE' clause is also required.

inline_code_pat = r'`(?:[^\\`]|\\`|\\\\)*`' # for splitting line.
inline_code_esc_re = re.compile(r'\\`|\\\\') # for escaping quoted code string.
inline_code_esc_fn = lambda m: m.group(0)[1:] # strip leading escape.

def inline_code_conv(text):
  text_inner = text[1:-1] # remove surrounding backquotes.
  text_escaped = inline_code_esc_re.sub(inline_code_esc_fn, text_inner)
  text_escaped1 = esc(text_escaped)
  text_spaced = text_escaped1.replace(' ', '&nbsp;')
  return '<code>{}</code>'.format(text_spaced)

# pattern and associated handler.
inline_elements = [
  (inline_code_pat, inline_code_conv)
]

# wrap each sub-pattern in capturing parentheses.
inline_split_re = re.compile('|'.join('({})'.format(p) for p, f in inline_elements))

def convert_inline_text(text):
  converted = []
  prev_idx = 0
  for m in inline_split_re.finditer(text):
    start_idx = m.start()
    if prev_idx < start_idx: # flush preceding text.
      converted.append(esc(text[prev_idx:start_idx]))
    prev_idx = m.end()
    for i, (p, f) in enumerate(inline_elements, 1): # groups are 1-indexed.
      g = m.group(i)
      if g is not None:
        converted.append(f(g))
        break
  if prev_idx < len(text):
    converted.append(esc(text[prev_idx:]))
  return ''.join(converted)


def writeup_body(out_lines, in_lines, line_offset):
  'from input writeup lines, output html lines.'
  def out(depth, *items):
    s = ' ' * (depth * 2) + ''.join(items)
    out_lines.append(s)

  # state variables used by writeup_line.
  section_stack = []
  list_depth = 0
  license_lines = []
  pre_lines = []
  quote_line_num = 0
  quote_lines = []

  def writeup_line(line_num, line, prev_state, state, groups):
    'process a line.'
    nonlocal section_stack
    nonlocal list_depth
    nonlocal quote_line_num

    section_depth = len(section_stack)

    #errF('{:03} {}{}: {}', line_num, state_letters[prev_state], state_letters[state], line)

    def warn(fmt, *items):
      errFL('warning: line {}: ' + fmt, line_num, *items)
      errFL("  '{}'", repr(line))

    def error(fmt, *items):
      fail('error: line {}: ' + fmt, line_num, *items)

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

    # transition.
    if prev_state == s_start:
      pass
    elif prev_state == s_license:
      pass
    elif prev_state == s_section:
      pass

    elif prev_state == s_list:
      if state != s_list:
        for i in range(list_depth, 0, -1):
          out(section_depth + (i - 1), '</ul>')
        list_depth = 0
    
    elif prev_state == s_code:
      if state != s_code:
        # a newline after the open tag looks ok,
        # but a final newline between pre content and the close tag looks bad.
        # therefore we must take care to format the pre contents without a final newline.
        out(0, '<pre>\n{}</pre>'.format('\n'.join(pre_lines)))
        pre_lines.clear()
    
    elif prev_state == s_quote:
      if state != s_quote:
        out(section_depth, '<blockquote>')
        quoted_lines = []
        writeup_body(quoted_lines, quote_lines, quote_line_num)
        for ql in quoted_lines:
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

    if state == s_section:
      hashes, spaces, text = groups
      check_whitespace(1, spaces)
      depth = len(hashes)
      h = min(6, depth)
      prev_index = 0
      while len(section_stack) >= depth: # close previous peer section and its children.
        sid = '.'.join(str(i) for i in section_stack)
        prev_index = section_stack.pop()
        out(len(section_stack), '</section>') # <!--s{}-->'.format(sid))
      while len(section_stack) < depth: # open new section and any children.
        index = prev_index + 1
        section_stack.append(index)
        d = len(section_stack)
        sid = '.'.join(str(i) for i in section_stack)
        out(d - 1, '<section class="S{}" id="s{}">'.format(d, sid))
        prev_index = 0
      # current.
      out(depth, '<h{} id="h{}">{}</h{}>'.format(h, sid, convert_inline_text(text), h))

    elif state == s_list:
      indents, spaces, text = groups
      check_whitespace(-1, indents, ' in indent')
      l = len(indents)
      if l % 2:
        warn('odd indentation: {}', l)
      depth = l // 2 + 1
      check_whitespace(1, spaces, ' following dash')
      for i in range(list_depth, depth, -1):
        out(section_depth + (i - 1), '</ul>')
      for i in range(list_depth, depth):
        out(section_depth + i, '<ul class="L{}">'.format(i + 1))
      # note: the bullet is inserted as part of the text,
      # so that a user select-and-copy preserves the bullet (indentation is still lost).
      out(section_depth + depth, '<li>• {}</li>'.format(convert_inline_text(text)))
      list_depth = depth

    elif state == s_code:
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
      out(section_depth + 1, convert_inline_text(text))

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

    writeup_line(line_offset + line_num, line, prev_state, state, groups)
    prev_state = state

  # finish.
  writeup_line(line_num + 1, '\n', prev_state, s_end, None)


def writeup(in_lines, line_offset, title, description, author, css, js):
  'generate a complete html document from a writeup file (or stream of lines).'

  html_lines = ['''\
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="author" content="{author}">
  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgo=">
  <style type="text/css">{css}</style>
  <script>{js}</script>
</head>
<body>\
'''.format(title=title, description=description, author=author, css=css, js=js)]

  writeup_body(html_lines, in_lines, line_offset)

  html_lines.append('</body>\n</html>')
  return html_lines


if __name__ == '__main__':
  
  arg_parser = argparse.ArgumentParser(description='convert .wu files to html')
  arg_parser.add_argument('-presentation', action='store_true', help='add presentation mode css')
  arg_parser.add_argument('src_path', nargs='?', help='input .wu source path (defaults to stdin)')
  arg_parser.add_argument('dst_path', nargs='?', help='output .html path (defaults to stdout)')

  args = arg_parser.parse_args()

  # paths.
  check(args.src_path or args.src_path is None, 'src_path cannot be empty string')
  check(args.dst_path or args.dst_path is None, 'dst_path cannot be empty string')

  f_in  = open(args.src_path) if args.src_path else sys.stdin
  f_out = open(args.dst_path) if args.dst_path else sys.stdout

  # version.
  version_line = f_in.readline()
  m = version_re.fullmatch(version_line)
  check(m, 'first line must specify writeup version matching pattern: {!r}\nfound: {!r}',
    version_pattern, version_line)
  version = int(m.group(1))
  check(version == 0, 'unsupported version number: {}', version)

  # css.
  if args.presentation:
    css += presentation_css
  css = minify_css(css)

  html_lines = writeup(f_in,
    line_offset=(1 + 1), # 1-indexed, account for version line.
    title=(args.src_path or 'stdin'),
    description='',
    author='',
    css=css,
    js=js)

  for line in html_lines:
    print(line, file=f_out)

