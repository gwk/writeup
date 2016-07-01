#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import argparse
import html
import re
import sys
import os.path


default_css = '''
a { background-color: transparent; }
a:active { outline: 0; }
a:hover { outline: 0; }
blockquote {
  border-left-color: #E0E0E0;
  border-left-style: solid;
  border-left-width: 0.333rem;
  margin: 0;
  padding: 0 0.677rem;
}
body {
  margin: 1rem;
  }
body footer {
  border-top-color: #E8E8E8;
  border-top-style: solid;
  border-top-width: 1px;
  color: #606060;
  font-size: .875rem;
  margin: 1rem 0 0 0;
}
code {
  background-color: rgba(0xF0, 0xF0, 0xF0, 0.2);
  border-radius: 3px;
  font-family: source code pro, menlo, terminal, monospace;
}
footer { display: block; }
h1 { font-size: 1.6rem; margin: 0.8rem 0; }
h2 { font-size: 1.4rem; margin: 0.7rem 0; }
h3 { font-size: 1.3rem; margin: 0.6rem 0; }
h4 { font-size: 1.2rem; margin: 0.5rem 0; }
h5 { font-size: 1.1rem; margin: 0.4rem 0; }
h6 { font-size: 1.0rem; margin: 0.3rem 0; }
header { display: block; }
html {
  background: white;
  color: black; 
  font-family: source sans pro, sans-serif;
  font-size: 1rem;
}
nav { display: block; }
p { margin: 0.5rem 0; }
pre {
  background: #F0F0F0;
  font-family: source code pro, menlo, terminal, monospace;
  font-size: 1rem;
  overflow: auto;
  padding: 0.1rem;
  border-radius: 4px;
}
section { display: block; }
section.S1 {
  border-top-color: #E8E8E8;
  border-top-style: solid;
  border-top-width: 1px;
  margin: 1.6rem 0;
}
section.S2 { margin: 1.4rem 0; }
section.S3 { margin: 1.3rem 0; }
section.S4 { margin: 1.2rem 0; }
section.S5 { margin: 1.1rem 0; }
section.S6 { margin: 1.0rem 0; }

section#s1 {
  border-top-width: 0;
}
ul {
  line-height: 1.333rem;
  list-style-position: inside;
  list-style-type: disc;
  margin: 0rem;
  padding-left: 0.1rem;
}
ul > ul {
  padding-left: 1.1rem;
}

@media print {
@page {
  margin: 2cm;
}
}
'''


js = '''
function scrollToElementId(id) {
  window.scrollTo(0, document.getElementById(id).offsetTop);
}

var in_pres_mode = false;
function togglePresentationMode() {
  in_pres_mode = !in_pres_mode;
  for (var sid of paging_ids) {
    var section = document.getElementById(sid);
    if (section.id == 'body') {
      // skip; not actually a section.
    } else {
      section.style['margin'] = in_pres_mode ? '100vh 0 0 0' : '0';
    }
  }
  var footer = document.getElementById('footer');
  footer.style['margin'] = in_pres_mode ? '100vh 0 0 0' : '0';
}

var section_ids = null;
var paging_ids = null;
var paging_idx = 0;

window.onkeydown = function(e) { 
  if (e.keyCode === 37) { // left.
    if (paging_idx > 0) {
      paging_idx -= 1;
    }
    scrollToElementId(paging_ids[paging_idx]);
  } else if (e.keyCode === 39) { // right.
    if (paging_idx < paging_ids.length - 1) {
      paging_idx += 1;
    }
    scrollToElementId(paging_ids[paging_idx]);
  }
};

window.onkeypress = function(e) {
  if (e.charCode === 112) { // 'p'.
    togglePresentationMode();
  }
};
'''


# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.
version_re = re.compile(r'writeup v(\d+)\n')

# license pattern is is only applied to the first line (following the version line, if any).
license_re = re.compile(r'(©|Copyright|Dedicated to the public domain).*\n')

# line states.
s_start, s_license, s_section, s_list, s_quote, s_code, s_blank, s_text, s_end = range(9)

# for debug output only.
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

def failF(fmt, *items):
  errFL(fmt, *items)
  sys.exit(1)


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


def html_esc(text):
  return html.escape(text, quote=False)

def html_esc_attr(text):
  return html.escape(text, quote=True)


class Ctx:
  def __init__(self, src_path, error, dependencies: list):
    self.src_path = src_path
    self.src_dir = os.path.dirname(src_path) or '.'
    self.error = error # error function.
    self.dependencies = dependencies
    self.emit_dependencies = (dependencies != None)

# inline span handling.

# general pattern for quoting with escapes is Q([^EQ]|EQ|EE)*Q.
# it is crucial that the escape character E is excluded in the '[^EQ]' clause,
# or else when matching against 'QEQQ', the pattern greedily matches 'QEQ'.
# to allow a trailing escape character, the 'EE' clause is also required.
span_char_esc_fn = lambda m: m.group(0)[1:] # strip leading '\' escape.

# backtick code span.

span_code_pat = r'`((?:[^\\`]|\\`|\\\\)*)`' # finds code spans.
span_code_esc_re = re.compile(r'\\`|\\\\') # escapes code strings.

def span_code_conv(text, ctx):
  'convert backtick code span to html.'
  text_escaped = span_code_esc_re.sub(span_char_esc_fn, text)
  text_escaped_html = html_esc(text_escaped)
  text_spaced = text_escaped_html.replace(' ', '&nbsp;')
  return '<code>{}</code>'.format(text_spaced)

# generic angle bracket spans.

span_pat = r'<((?:[^\\>]|\\>|\\\\)*)>'
span_esc_re = re.compile(r'\\>|\\\\') # escapes span strings.


def span_embed(text, ctx):
  'convert an embed span into html.'
  if ctx.emit_dependencies:
    ctx.dependencies.append(text)
    return ''
  try:
    target_path = text
    path = target_path if os.path.exists(target_path) else os.path.join('_build', target_path)
    with open(os.path.join(ctx.src_dir, path)) as f:
      return f.read()
  except FileNotFoundError:
    ctx.error('embedded file not found: {}; path: {}', text, path)

span_dispatch = {
  'embed' : span_embed
}

def span_conv(text, ctx):
  'convert generic angle bracket span to html.'
  tag, colon, body = text.partition(':')
  if colon is None: error('malformed span is missing colon after tag: `{}`'.format(text))
  try:
    f = span_dispatch[tag]
  except KeyError:
    ctx.error('malformed span has invalid tag: `{}`'.format(tag))
  return f(body.strip(), ctx)


# span patterns and associated handlers.
span_kinds = [
  (span_code_pat, span_code_conv),
  (span_pat, span_conv),
]

# single re, wrapping each span sub-pattern in capturing parentheses.
span_re = re.compile('|'.join(p for p, f in span_kinds))

def convert_text(text, ctx):
  'convert writeup span elements in a text string to html.'
  converted = []
  prev_idx = 0
  for m in span_re.finditer(text):
    start_idx = m.start()
    if prev_idx < start_idx: # flush preceding text.
      converted.append(html_esc(text[prev_idx:start_idx]))
    prev_idx = m.end()
    for i, (pattern, fn) in enumerate(span_kinds, 1): # groups are 1-indexed.
      group = m.group(i)
      if group is not None:
        converted.append(fn(group, ctx))
        break
  if prev_idx < len(text):
    converted.append(html_esc(text[prev_idx:]))
  return ''.join(converted)


def writeup_body(out_lines, out_dependencies, src_path, src_lines,
  line_offset=0, is_versioned=True, dependency_map=None):
  'from input writeup lines, output html lines and dependencies.'

  def out(depth, *items):
    s = ' ' * (depth * 2) + ''.join(items)
    out_lines.append(s)

  # state variables used by writeup_line.
  section_ids = [] # accumulated list of all section ids.
  paging_ids = [] # accumulated list of all paging (level 1 & 2) section ids.
  section_stack = [] # stack of currently open sections.
  list_depth = 0 # currently open list depth.
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
      errFL('writeup warning: {}: line {}: ' + fmt, src_path, line_num + 1, *items)
      errFL("  '{}'", repr(line))

    def error(fmt, *items):
      failF('writeup error: {}: line {}: ' + fmt, src_path, line_num + 1, *items)

    ctx = Ctx(src_path, error, out_dependencies)

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
        writeup_body(
          out_lines=quoted_lines,
          out_dependencies=out_dependencies,
          src_path=src_path,
          src_lines=quote_lines,
          line_offset=quote_line_num,
          is_versioned=False)
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
      h_num = min(6, depth)
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
      out(depth, '<h{} id="h{}">{}</h{}>'.format(h_num, sid, convert_text(text, ctx), h_num))
      section_ids.append(sid)
      if depth <= 2:
        paging_ids.append(sid)

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
      out(section_depth + depth, '<li>{}</li>'.format(convert_text(text, ctx)))
      list_depth = depth

    elif state == s_code:
      text, = groups
      pre_lines.append(html_esc(text))

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
      out(section_depth + 1, convert_text(text, ctx))

    elif state == s_end:
      for i in range(section_depth, 0, -1):
        out(i - 1, '</section>')
      if license_lines:
        out(0, '<footer id="footer">\n', '<br />\n'.join(license_lines), '\n</footer>')

    else:
      error('bad state: {}', state)

  if is_versioned:
    try:
      version_line = next(src_lines)
    except StopIteration:
      version_line = ''
    m = version_re.fullmatch(version_line)
    if not m:
      failF('writeup error: first line must specify writeup version matching pattern: {!r}\n  found: {!r}',
        version_re.pattern, version_line)
    version = int(m.group(1))
    if version != 0: failF('unsupported version number: {}', version)
    line_offset += 1

  prev_state = s_start
  line_num = 0
  for line_num, line in enumerate(src_lines, line_offset):
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
  writeup_line(line_num + 1, '\n', prev_state, s_end, None)

  # generate tables.
  out(0, '<script type="text/javascript"> "use strict";')
  out(0, 'section_ids = [{}];'.format(','.join("'s{}'".format(sid) for sid in section_ids)))
  out(0, "paging_ids = ['body', {}];".format(','.join("'s{}'".format(sid) for sid in paging_ids)))
  out(0, '</script>')


def writeup(src_path, src_lines, title, description, author, css, js):
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
  <script type="text/javascript"> "use strict";{js}</script>
</head>
<body id="body">\
'''.format(title=title, description=description, author=author, css=css, js=js)]

  writeup_body(
    out_lines=html_lines,
    out_dependencies=None,
    src_path=src_path,
    src_lines=src_lines)
  html_lines.append('</body>\n</html>')
  return html_lines


def writeup_dependencies(src_path, src_lines, dir_names):
  dependencies = []
  writeup_body(
    out_lines=[],
    out_dependencies=dependencies,
    src_path=src_path,
    src_lines=src_lines)
  dependencies.sort()
  return dependencies


def main():
  arg_parser = argparse.ArgumentParser(description='convert .wu files to html')
  arg_parser.add_argument('src_path', nargs='?', help='input .wu source path (defaults to stdin)')
  arg_parser.add_argument('dst_path', nargs='?', help='output .html path (defaults to stdout)')
  arg_parser.add_argument('-print-dependencies', action='store_true')
  args = arg_parser.parse_args()

  # paths.
  if not (args.src_path or args.src_path is None): failF('src_path cannot be empty string')
  if not (args.dst_path or args.dst_path is None): failF('dst_path cannot be empty string')

  f_in  = open(args.src_path) if args.src_path else sys.stdin
  f_out = open(args.dst_path, 'w') if args.dst_path else sys.stdout
  src_lines = iter(f_in)

  src_path = (args.src_path or '(stdin)')

  if args.print_dependencies:
    dependencies = writeup_dependencies(
      src_path=src_path,
      src_lines=src_lines)
    for dep in dependencies:
      print(dep, file=f_out)
  else:
    css = minify_css(default_css)
    html_lines = writeup(
      src_path=src_path,
      src_lines=src_lines,
      title=src_path, # TODO.
      description='',
      author='',
      css=css,
      js=js)
    for line in html_lines:
      print(line, file=f_out)


__all__ = ['writeup', 'writeup_dependencies', 'main']


if __name__ == '__main__':
  main()
