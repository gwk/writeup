#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import re

from argparse import ArgumentParser
from html import escape as html_escape
from os.path import dirname as dir_name, exists as path_exists, join as path_join, splitext as split_ext
from sys import stdin, stdout, stderr
from typing import Any, Callable, Iterable, List, Optional, Sequence, Union, Tuple


__all__ = ['main', 'writeup', 'writeup_dependencies']


def main() -> None:
  arg_parser = ArgumentParser(description='Converts .wu files to html.')
  arg_parser.add_argument('src_path', nargs='?', help='Input .wu source path; defaults to <stdin>.')
  arg_parser.add_argument('dst_path', nargs='?', help='Output .html path: defaults to <stdout>.')
  arg_parser.add_argument('-print-dependencies', action='store_true',
    help='Print external file dependencies of the input, one per line. Does not output HTML.')
  arg_parser.add_argument('-css', nargs='+', default=(), help='paths to CSS.')
  arg_parser.add_argument('-no-css', action='store_true', help='Omit default CSS.')
  arg_parser.add_argument('-no-js', action='store_true', help='Omit default Javascript.')
  arg_parser.add_argument('-bare', action='store_true', help='Omit all non-HTML output.')
  args = arg_parser.parse_args()

  if args.src_path == '': failF('src_path cannot be empty string')
  if args.dst_path == '': failF('dst_path cannot be empty string')
  if args.src_path == args.dst_path and args.src_path is not None:
    failF('src_path and dst_path cannot be the same path: {!r}', args.src_path)

  f_in  = open(args.src_path) if args.src_path else stdin
  f_out = open(args.dst_path, 'w') if args.dst_path else stdout
  src_path = f_in.name

  if f_in == stdin and f_in.isatty():
    print('writeup: reading from stdin...', file=stderr)

  if args.print_dependencies:
    dependencies = writeup_dependencies(
      src_path=src_path,
      src_lines=f_in)
    for dep in dependencies:
      print(dep, file=f_out)

  css = [] if (args.bare or args.no_css) else [default_css]
  for path in args.css:
    try:
      with open(path) as f:
        css.append(f.read())
    except FileNotFoundError:
      failF('writeup: css file does not exist: {!r}', args.css)

  else:
    html_lines = writeup(
      src_path=src_path,
      src_lines=f_in,
      title=src_path, # TODO.
      description='',
      author='',
      css=minify_css('\n'.join(css)),
      js=(None if args.bare or args.no_js else minify_js(default_js)),
    )
    for line in html_lines:
      print(line, file=f_out)


def writeup(src_path: str, src_lines: Iterable[str], title: str, description: str, author: str,
  css: Optional[str], js: Optional[str]) -> List[str]:
  'generate a complete html document from a writeup file (or stream of lines).'

  html_lines = [
    '<html>',
    '<head>',
    '  <meta charset="utf-8">',
    '  <title>{}</title>'.format(title),
    '  <meta name="description" content="{}">'.format(description),
    '  <meta name="author" content="{}">'.format(author),
    '  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgo=">', # empty icon.
  ]
  if css:
    html_lines.append('  <style type="text/css">{}</style>'.format(css))
  if js:
    html_lines.append('  <script type="text/javascript"> "use strict";{}</script>'.format(js))
  html_lines.append('</head>')
  html_lines.append('<body id="body">')

  writeup_body(
    out_lines=html_lines,
    out_dependencies=None,
    src_path=src_path,
    src_lines=src_lines,
    emit_js=bool(js))
  html_lines.append('</body>\n</html>')
  return html_lines


def writeup_dependencies(src_path: str, src_lines: Iterable[str], dir_names: Optional[List[Any]] = None) -> List[str]:
  '''
  Return a list of dependencies from the writeup in `src_lines`.
  `dir_names` is an ignored argument passed by the external `muck` tool.
  '''
  dependencies = [] # type: List[str]
  writeup_body(
    out_lines=None,
    out_dependencies=dependencies,
    src_path=src_path,
    src_lines=src_lines,
    emit_js=False)
  dependencies.sort()
  return dependencies


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
  (s_list,    re.compile(r'(\s*)\*(\s*)(.*)\n')),
  (s_quote,   re.compile(r'> ?(.*\n)')),
  (s_code,    re.compile(r'\| ?(.*)\n')),
  (s_blank,   re.compile(r'(\s*)\n')),
]

# span regexes.
# general pattern for quoting with escapes is Q([^EQ]|EQ|EE)*Q.
# it is crucial that the escape character E is excluded in the '[^EQ]' clause,
# or else when matching against 'QEQQ', the pattern greedily matches 'QEQ'.
# to allow a trailing escape character, the 'EE' clause is also required.

# backtick code span.
span_code_pat = r'`((?:[^\\`]|\\`|\\\\)*)`' # finds code spans.
span_code_esc_re = re.compile(r'\\`|\\\\') # escapes code strings.

# generic angle bracket span.
span_pat = r'<((?:[^\\>]|\\>|\\\\)*)>'
span_esc_re = re.compile(r'\\>|\\\\') # escapes span strings.


def dummy_fn(fmt, *items):
  'Never called; used as an initialization placeholder for Ctx.warn and Ctx.error.'
  raise Exception('unreachable')


class Ctx:
  '''
  Structure for contextual information needed by a variety of functions called from `writeup_body`.
  '''
  def __init__(self, search_dir: str, src_path: str, out: Callable[..., None], dependencies: Optional[list],
    emit_js: bool, line_offset: int, quote_depth: int) -> None:
    self.search_dir = search_dir
    self.src_path = src_path
    self.out = out
    self.dependencies = dependencies
    self.quote_depth = quote_depth
    self.section_ids = [] # type: List[str] # accumulated list of all section ids.
    self.paging_ids = [] # type: List[str] # accumulated list of all paging (level 1 & 2) section ids.
    self.section_stack = [] # type: List[int] # stack of currently open sections.
    self.list_depth = 0 # currently open list depth.
    self.license_lines = [] # type: List[str]
    self.pre_lines = [] # type: List[str]
    self.quote_line_num = 0
    self.quote_lines = [] # type: List[str]
    self.line_num = 0 # updated per line.
    self.warn = dummy_fn # type: Callable[..., None] # updated per line.
    self.error = dummy_fn # type: Callable[..., None] # updated per line.

  @property
  def section_depth(self) -> int:
    return len(self.section_stack)


def writeup_body(out_lines: Optional[list], out_dependencies: Optional[list],
  src_path: str, src_lines: Iterable[str], emit_js: bool, is_versioned=True,
  line_offset=0, quote_depth=0) -> None:
  'Convert input writeup in `src_lines` to output html lines and dependencies.'

  if out_lines is None:
    def out(depth: int, *items) -> None: pass
  else:
    def out(depth: int, *items) -> None:
      s = ' ' * (depth * 2) + ''.join(items)
      out_lines.append(s)

  ctx = Ctx(search_dir=dir_name(src_path) or '.',
   src_path=src_path, out=out, dependencies=out_dependencies,
   emit_js=emit_js, line_offset=line_offset, quote_depth=quote_depth)

  iter_src_lines = iter(src_lines)

  # Handle version line.
  if is_versioned:
    try:
      version_line = next(iter_src_lines)
    except StopIteration:
      version_line = ''
    m = version_re.fullmatch(version_line)
    if not m:
      failF('writeup error: first line must specify writeup version matching pattern: {!r}\n  found: {!r}',
        version_re.pattern, version_line)
    version = int(m.group(1))
    if version != 0: failF('unsupported version number: {}', version)
    line_offset += 1

  # Iterate over lines.
  prev_state = s_start
  ctx.line_num = line_offset
  for line_num, line in enumerate(iter_src_lines, line_offset):
    ctx.line_num = line_num
    # any license notice at top gets moved to a footer at the bottom of the html.
    if prev_state == s_start and license_re.fullmatch(line):
      ctx.license_lines.append(line.strip())
      prev_state = s_license
      continue
    if prev_state == s_license: # consume remaining license lines.
      l = line.strip()
      if l: # not empty.
        ctx.license_lines.append(l)
        continue # remain in s_license.

    # license has ended; determine state.
    state = s_text # default if no patterns match.
    groups = (line,) # type: Sequence[str] # hack for output_text.
    for s, r in matchers:
      m = r.fullmatch(line)
      if m:
        state = s
        groups = m.groups()
        break

    writeup_line(ctx=ctx, line=line, prev_state=prev_state, state=state, groups=groups)
    prev_state = state

  # Finish.
  ctx.line_num += 1
  writeup_line(ctx=ctx, line='\n', prev_state=prev_state, state=s_end, groups=None)

  if emit_js:
    # Generate tables.
    out(0, '<script type="text/javascript"> "use strict";')
    out(0, 'section_ids = [{}];'.format(','.join("'s{}'".format(sid) for sid in ctx.section_ids)))
    out(0, "paging_ids = ['body', {}];".format(','.join("'s{}'".format(pid) for pid in ctx.paging_ids)))
    out(0, '</script>')


def writeup_line(ctx: Ctx, line: str, prev_state: int, state: int, groups) -> None:
  'Inner function to process a line.'

  #errF('{:03} {}{}: {}', ctx.line_num, state_letters[prev_state], state_letters[state], line)

  def warn(fmt, *items):
    errFL('writeup warning: {}: line {}: ' + fmt, ctx.src_path, ctx.line_num + 1, *items)
    errFL("  '{}'", repr(line))

  def error(fmt, *items):
    failF('writeup error: {}: line {}: ' + fmt, ctx.src_path, ctx.line_num + 1, *items)

  ctx.error = error

  if not line.endswith('\n'):
    warn("missing newline ('\\n')")

  # Some transitions between states result in actions.

  if prev_state == s_list and state != s_list: finish_list(ctx)
  elif prev_state == s_code and state != s_code: finish_code(ctx)
  elif prev_state == s_quote and state != s_quote: finish_quote(ctx)

  elif prev_state == s_text:
    if state == s_text:
      ctx.out(ctx.section_depth, '<br />')
    else:
      ctx.out(ctx.section_depth, '</p>')

  # output text.
  is_first = (prev_state != state)

  if state == s_section: output_section(ctx, groups, is_first)
  elif state == s_list: output_list(ctx, groups, is_first)
  elif state == s_code: output_code(ctx, groups, is_first)
  elif state == s_quote: output_quote(ctx, groups, is_first)
  elif state == s_blank: output_blank(ctx, groups, is_first)
  elif state == s_text: output_text(ctx, groups, is_first)
  elif state == s_end: output_end(ctx, groups, is_first)
  else: error('bad state: {}', state)


def finish_list(ctx: Ctx) -> None:
  for i in range(ctx.list_depth, 0, -1):
    ctx.out(ctx.section_depth + (i - 1), '</ul>')
  ctx.list_depth = 0


def finish_code(ctx: Ctx) -> None:
  # a newline after the `pre` open tag looks ok,
  # but a final newline between content and the `pre` close tag looks bad.
  # therefore we must take care to format the contents without a final newline.
  ctx.out(0, '<pre>\n{}</pre>'.format('\n'.join(ctx.pre_lines)))
  ctx.pre_lines.clear()


def finish_quote(ctx: Ctx) -> None:
  ctx.out(ctx.section_depth, '<blockquote>')
  quoted_lines = [] # type: List[str]
  writeup_body(
    out_lines=quoted_lines,
    out_dependencies=ctx.dependencies,
    src_path=ctx.src_path,
    src_lines=ctx.quote_lines,
    line_offset=ctx.quote_line_num,
    is_versioned=False,
    emit_js=False,
    quote_depth=ctx.quote_depth + 1)
  for ql in quoted_lines:
    ctx.out(ctx.section_depth + 1, ql)
  ctx.out(ctx.section_depth, '</blockquote>')
  ctx.quote_lines.clear()


def output_section(ctx: Ctx, groups: Sequence[str], is_first: bool):
  hashes, spaces, text = groups
  check_whitespace(ctx.warn, 1, spaces)
  depth = len(hashes)
  h_num = min(6, depth)
  prev_index = 0
  while ctx.section_depth >= depth: # close previous peer section and its children.
    sid = '.'.join(str(i) for i in ctx.section_stack)
    prev_index = ctx.section_stack.pop()
    ctx.out(ctx.section_depth, '</section>') # <!--s{}-->'.format(sid))
  while ctx.section_depth < depth: # open new section and any children.
    index = prev_index + 1
    ctx.section_stack.append(index)
    d = ctx.section_depth
    sid = '.'.join(str(i) for i in ctx.section_stack)
    quote_prefix = 'q{}'.format(ctx.quote_depth) if ctx.quote_depth else ''
    ctx.out(d - 1, '<section class="S{}" id="{}s{}">'.format(d, quote_prefix, sid))
    prev_index = 0
  # current.
  ctx.out(depth, '<h{} id="h{}">{}</h{}>'.format(h_num, sid, convert_text(ctx, text), h_num))
  ctx.section_ids.append(sid)
  if depth <= 2:
    ctx.paging_ids.append(sid)


def output_list(ctx: Ctx, groups: Sequence[str], is_first: bool):
  indents, spaces, text = groups
  check_whitespace(ctx, -1, indents, ' in indent')
  l = len(indents)
  if l % 2:
    ctx.warn('odd indentation: {}', l)
  depth = l // 2 + 1
  check_whitespace(ctx, 1, spaces, ' following dash')
  for i in range(ctx.list_depth, depth, -1):
    ctx.out(ctx.section_depth + (i - 1), '</ul>')
  for i in range(ctx.list_depth, depth):
    ctx.out(ctx.section_depth + i, '<ul class="L{}">'.format(i + 1))
  ctx.out(ctx.section_depth + depth, '<li>{}</li>'.format(convert_text(ctx, text)))
  ctx.list_depth = depth


def output_code(ctx: Ctx, groups: Sequence[str], is_first: bool):
  text, = groups
  ctx.pre_lines.append(html_esc(text))


def output_quote(ctx: Ctx, groups: Sequence[str], is_first: bool):
  quoted_line, = groups
  if is_first:
    ctx.quote_line_num = ctx.line_num
  ctx.quote_lines.append(quoted_line) # not converted here; text is fully transformed by finish_quote.


def output_text(ctx: Ctx, groups: Sequence[str], is_first: bool):
  # TODO: check for strange characters that html will ignore.
  text, = groups
  if is_first:
    ctx.out(ctx.section_depth, '<p>')
  ctx.out(ctx.section_depth + 1, convert_text(ctx, text))


def output_blank(ctx: Ctx, groups: Sequence[str], is_first: bool):
  spaces, = groups
  if len(spaces): ctx.warn('blank line is not empty')


def output_end(ctx: Ctx, groups: Sequence[str], is_first: bool):
  for i in range(ctx.section_depth, 0, -1):
    ctx.out(i - 1, '</section>')
  if ctx.license_lines:
    ctx.out(0, '<footer id="footer">\n', '<br />\n'.join(ctx.license_lines), '\n</footer>')


def check_whitespace(ctx, len_exp, string, msg_suffix=''):
  for i, c in enumerate(string):
    if c != ' ':
      ctx.warn("invalid whitespace character at position {}{}: {}", i + 1, msg_suffix, repr(c))
      return False
  if len_exp >= 0 and len(string) != len_exp:
    ctx.warn('expected exactly {} space{}{}; found: {}',
      len_exp, ('' if len_exp == 1 else 's'), msg_suffix, len(string))
    return False
  return True


def convert_text(ctx: Ctx, text: str):
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
        converted.append(fn(ctx, group))
        break
  if prev_idx < len(text):
    converted.append(html_esc(text[prev_idx:]))
  return ''.join(converted)


def span_conv(ctx: Ctx, text: str):
  'convert generic angle bracket span to html.'
  tag, colon, body = text.partition(':')
  if colon is None: ctx.error('malformed span is missing colon after tag: `{}`'.format(text))
  try:
    f = span_dispatch[tag]
  except KeyError:
    ctx.error('span has invalid tag: `{}`'.format(tag))
  return f(ctx, tag, body.strip())


def span_code_conv(ctx: Ctx, text: str):
  'convert backtick code span to html.'
  span_char_esc_fn = lambda m: m.group(0)[1:] # strip leading '\' escape.
  text_escaped = span_code_esc_re.sub(span_char_esc_fn, text)
  text_escaped_html = html_esc(text_escaped)
  text_spaced = text_escaped_html.replace(' ', '&nbsp;')
  return '<code>{}</code>'.format(text_spaced)


# span patterns and associated handlers.
span_kinds = [
  (span_code_pat, span_code_conv),
  (span_pat,      span_conv),
]

# single re, wrapping each span sub-pattern in capturing parentheses.
span_re = re.compile('|'.join(p for p, _, in span_kinds))


# generic angle bracket spans.

def span_bold(ctx: Ctx, tag: str, text: str):
  'convert a `bold` span into html.'
  return '<b>{}</b>'.format(html_esc(text))

def span_embed(ctx: Ctx, tag: str, text: str):
  'convert an `embed` span into html.'
  target_path = path_join(ctx.search_dir, text)
  if ctx.dependencies is not None:
    ctx.dependencies.append(target_path)
    return ''
  actual_path = target_path if path_exists(target_path) else path_join('_build', target_path)
  try: f = open(actual_path)
  except FileNotFoundError:
    ctx.error('embedded file not found: {!r}; inferred path: {!r}', target_path, path)
  ext = split_ext(target_path)[1]
  try: fn = embed_dispatch[ext]
  except KeyError:
    ctx.error('embedded file has unknown extension type: {!r}:', path)
  return fn(ctx, f)


def span_link(ctx: Ctx, tag: str, text: str):
  'convert a `link` span into html.'
  words = text.split()
  if not words:
    ctx.error('link is empty: {!r}: {!r}', tag, text)
  link = '{}:{}'.format(tag, text)
  if len(words) == 1:
    visible = link
  else:
    visible = ' '.join(words[1:])
  return '<a href={}>{}</a>'.format(link, html_esc(visible))

span_dispatch = {
  'b' : span_bold,
  'embed' : span_embed,
  'http': span_link,
  'https': span_link,
  'mailto': span_link,
}


def embed_html(ctx, f):
  return f.read()


def embed_csv(ctx, f):
  from csv import reader
  csv_reader = reader(f)
  it = iter(csv_reader)
  table = ['<table>\n']

  def out(*els): table.extend(els)

  try: header = next(it)
  except StopIteration: pass
  else:
    out('<thead>', '<tr>')
    for col in header:
        out('<th>{}</th>'.format(html_esc(col)))
    out('</tr>', '</thead>\n', '<tbody>\n')
    for row in it:
      out('<tr>')
      for cell in row:
        out('<td>{}</td>'.format(html_esc(cell)))
      out('</tr>')
  out('</tbody>', '</table>\n')
  return ''.join(table)


def embed_txt(ctx, f):
  return '<pre>\n{}</pre>'.format(f.read())


def embed_svg(ctx, f):
  return f.read()


embed_dispatch = {
  '.html' : embed_html,
  '.csv' : embed_csv,
  '.svg' : embed_svg,
  '.txt' : embed_txt,
}


# HTML escaping.

def html_esc(text: str):
  return html_escape(text, quote=False)

def html_esc_attr(text: str):
  return html_escape(text, quote=True)


# Error reporting.

def errF(fmt: str, *items):
  print(fmt.format(*items), end='', file=stderr)

def errFL(fmt: str, *items):
  print(fmt.format(*items), file=stderr)

def failF(fmt:str, *items):
  errFL(fmt, *items)
  exit(1)


# CSS.

minify_css_re = re.compile(r'(?<=: )(.+?;)|\s+|/\*.*?\*/', flags=re.S)
# need to preserve spaces in between multiple words followed by semicolon,
# for cases like `margin: 0 0 0 0;`.
# the first choice clause captures these chunks in group 1;
# other choice clauses cause group 1 to hold None.
# we could do more agressive minification but this is good enough for now.

def minify_css(src: str):
  chunks = []
  for chunk in minify_css_re.split(src):
    if chunk: # discard empty chunks and splits that are None (not captured).
      chunks.append(chunk)
  return ' '.join(chunks) # use empty string joiner for more aggressive minification.


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
  background-color: rgb(240, 240, 240);
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

table {
  font-family: sans-serif;
  color:#666;
  background:#eaebec;
  margin:16px;
  border:#ccc 1px solid;
  border-radius:3px;
  box-shadow: 0 1px 2px #d1d1d1;
}

table th {
  padding:20px 24px 20px 24px;
  border-top:1px solid #fafafa;
  border-bottom:1px solid #e0e0e0;
  background: #ededed;
}
table th:first-child {
  text-align: left;
  padding-left:20px;
}
table tr:first-child th:first-child {
  border-top-left-radius:3px;
}
table tr:first-child th:last-child {
  border-top-right-radius:3px;
}
table tr {
  text-align: center;
  padding-left:20px;
}
table td:first-child {
  text-align: left;
  padding-left:20px;
  border-left: 0;
}
table td {
  padding:8px;
  border-top: 1px solid #ffffff;
  border-bottom:1px solid #e0e0e0;
  border-left: 1px solid #e0e0e0;

  background: #fafafa;
}
table tr.even td {
  background: #f6f6f6;
}
table tr:last-child td {
  border-bottom:0;
}
table tr:last-child td:first-child {
  border-bottom-left-radius:3px;
}
table tr:last-child td:last-child {
  border-bottom-right-radius:3px;
}
table tr:hover td {
  background: #f2f2f2;
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


# Javascript.

def minify_js(js):
  return js

default_js = '''
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


if __name__ == '__main__': main()
