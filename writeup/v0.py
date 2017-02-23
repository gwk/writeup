#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import sys
assert sys.version_info >= (3, 6, 0)

import re

from argparse import ArgumentParser
from html import escape as html_escape
from os.path import dirname as path_dir, exists as path_exists, join as path_join, splitext as split_ext
from sys import stdin, stdout, stderr
from typing import Any, Callable, Iterable, List, Optional, Sequence, Union, Tuple


__all__ = ['main', 'writeup', 'writeup_dependencies']


def main() -> None:
  arg_parser = ArgumentParser(prog='writeup', description='Converts .wu files to html.')
  arg_parser.add_argument('src_path', nargs='?', help='Input .wu source path; defaults to <stdin>.')
  arg_parser.add_argument('dst_path', nargs='?', help='Output path: defaults to <stdout>.')
  arg_parser.add_argument('-print-dependencies', action='store_true',
    help='Print external file dependencies of the input, one per line. Does not output HTML.')
  arg_parser.add_argument('-css', nargs='+', default=(), help='paths to CSS.')
  arg_parser.add_argument('-no-css', action='store_true', help='Omit default CSS.')
  arg_parser.add_argument('-no-js', action='store_true', help='Omit default Javascript.')
  arg_parser.add_argument('-bare', action='store_true', help='Omit all non-HTML output.')
  args = arg_parser.parse_args()

  if args.src_path == '': exit('source path cannot be empty string.')
  if args.dst_path == '': exit('destination path cannot be empty string.')
  if args.src_path == args.dst_path and args.src_path is not None:
    exit(f'source path and destination path cannot be the same path: {args.src_path!r}')

  f_in  = open(args.src_path) if args.src_path else stdin
  f_out = open(args.dst_path, 'w') if args.dst_path else stdout
  src_path = f_in.name

  if f_in == stdin and f_in.isatty():
    errSL('writeup: reading from stdin...')

  if args.print_dependencies:
    dependencies = writeup_dependencies(
      src_path=src_path,
      src_lines=f_in)
    for dep in dependencies:
      print(dep, file=f_out)
    exit(0)

  css = [] if (args.bare or args.no_css) else [default_css]
  for path in args.css:
    try:
      with open(path) as f:
        css.append(f.read())
    except FileNotFoundError:
      exit(f'writeup: css file does not exist: {args.css!r}')

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
    f'  <title>{title}</title>',
    f'  <meta name="description" content="{description}">',
    f'  <meta name="author" content="{author}">',
    '  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgo=">', # empty icon.
  ]
  if css:
    html_lines.append(f'  <style type="text/css">{css}</style>')
  if js:
    html_lines.append(f'  <script type="text/javascript"> "use strict";{js}</script>')
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

  ctx = Ctx(search_dir=path_dir(src_path) or '.',
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
      exit(f'writeup error: first line must specify writeup version matching pattern: {version_re.pattern!r}\n  found: {version_line!r}')
    version = int(m.group(1))
    if version != 0: exit(f'unsupported version number: {version}')
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
    section_ids = ','.join(f"'s{sid}'" for sid in ctx.section_ids)
    out(0, f'section_ids = [{section_ids}];')
    paging_ids = ','.join(f"'s{pid}'" for pid in ctx.paging_ids)
    out(0, f"paging_ids = ['body', {paging_ids}];")
    out(0, '</script>')


def writeup_line(ctx: Ctx, line: str, prev_state: int, state: int, groups) -> None:
  'Inner function to process a line.'

  #errZ(f'{ctx.line_num:03} {state_letters[prev_state]}{state_letters[state]}: {line}')

  def warn(*items):
    errSL(f'writeup warning: {ctx.src_path}:{ctx.line_num+1}: ', *items)
    errSL(f'  {line!r}')

  def error(*items):
    errSL(f'writeup error: {ctx.src_path}:{ctx.line_num+1}: ', *items)
    errSL(f'  {line!r}')
    exit(1)

  ctx.warn = warn
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
  else: error(f'bad state: {state}')


def finish_list(ctx: Ctx) -> None:
  for i in range(ctx.list_depth, 0, -1):
    ctx.out(ctx.section_depth + (i - 1), '</ul>')
  ctx.list_depth = 0


def finish_code(ctx: Ctx) -> None:
  # a newline after the `pre` open tag looks ok,
  # but a final newline between content and the `pre` close tag looks bad.
  # therefore we must take care to format the contents without a final newline.
  contents = '\n'.join(ctx.pre_lines)
  ctx.out(0, f'<pre>\n{contents}</pre>')
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
    ctx.out(ctx.section_depth, '</section>')
  while ctx.section_depth < depth: # open new section and any children.
    index = prev_index + 1
    ctx.section_stack.append(index)
    d = ctx.section_depth
    sid = '.'.join(str(i) for i in ctx.section_stack)
    quote_prefix = f'q{ctx.quote_depth}' if ctx.quote_depth else ''
    ctx.out(d - 1, f'<section class="S{d}" id="{quote_prefix}s{sid}">')
    prev_index = 0
  # current.
  ctx.out(depth, f'<h{h_num} id="h{sid}">{convert_text(ctx, text)}</h{h_num}>')
  ctx.section_ids.append(sid)
  if depth <= 2:
    ctx.paging_ids.append(sid)


def output_list(ctx: Ctx, groups: Sequence[str], is_first: bool):
  indents, spaces, text = groups
  check_whitespace(ctx, -1, indents, ' in indent')
  l = len(indents)
  if l % 2:
    ctx.warn(f'odd indentation: {l}')
  depth = l // 2 + 1
  check_whitespace(ctx, 1, spaces, ' following dash')
  for i in range(ctx.list_depth, depth, -1):
    ctx.out(ctx.section_depth + (i - 1), '</ul>')
  for i in range(ctx.list_depth, depth):
    ctx.out(ctx.section_depth + i, f'<ul class="L{i+1}">')
  ctx.out(ctx.section_depth + depth, f'<li>{convert_text(ctx, text)}</li>')
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
      ctx.warn(f'invalid whitespace character at position {i+1}{msg_suffix}: {c!r}')
      return False
  if len_exp >= 0 and len(string) != len_exp:
    ctx.warn(f'expected exactly {len_exp} space{"" if len_exp == 1 else "s"}{msg_suffix}; found: {len(string)}')
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
  if colon is None: ctx.error(f'malformed span is missing colon after tag: {text!r}')
  try:
    f = span_dispatch[tag]
  except KeyError:
    ctx.error(f'span has invalid tag: {tag!r}')
  return f(ctx, tag, body.strip())


def span_code_conv(ctx: Ctx, text: str):
  'convert backtick code span to html.'
  span_char_esc_fn = lambda m: m.group(0)[1:] # strip leading '\' escape.
  text_escaped = span_code_esc_re.sub(span_char_esc_fn, text)
  text_escaped_html = html_esc(text_escaped)
  text_spaced = text_escaped_html.replace(' ', '&nbsp;')
  return f'<code>{text_spaced}</code>'


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
  return f'<b>{html_esc(text)}</b>'

def span_embed(ctx: Ctx, tag: str, text: str):
  'convert an `embed` span into html.'
  target_path = path_join(ctx.search_dir, text)
  if target_path.startswith('./'):
    target_path = target_path[2:]
  if ctx.dependencies is not None:
    ctx.dependencies.append(target_path)
    return ''
  try: f = open(target_path)
  except FileNotFoundError:
    ctx.error(f'embedded file not found: {target_path!r}')
  ext = split_ext(target_path)[1]
  try: fn = embed_dispatch[ext]
  except KeyError:
    ctx.error(f'embedded file has unknown extension type: {target_path!r}')
  return fn(ctx, f)


def span_link(ctx: Ctx, tag: str, text: str):
  'convert a `link` span into html.'
  words = text.split()
  if not words:
    ctx.error(f'link is empty: {tag!r}: {text!r}')
  if tag == 'link':
    link = words[0]
    if ctx.dependencies is not None:
      ctx.dependencies.append(words[0])
  else:
    link = f'{tag}:{words[0]}'
  if len(words) == 1:
    visible = link
  else:
    visible = ' '.join(words[1:])
  return f'<a href={html_esc_attr(link)}>{html_esc(visible)}</a>'


def span_span(ctx: Ctx, tag: str, text: str):
  'convert a `span` span into html.'
  attrs = []
  body = []
  found_semicolon = False
  for word in text.split(' '):
    if found_semicolon: body.append(word)
    elif word == ';': found_semicolon = True
    else:
      if word.endswith(';'):
        found_semicolon = True
        word = word[:-1]
      key, eq, val = word.partition('=')
      if not eq: ctx.error(f'span attribute is missing `=`; word: {word!r}')
      if not key.isalnum(): ctx.error(f'span attribute name is not alphanumeric: {word!r}')
      if not val: ctx.error(f'span attribute value is empty; word: {word!r}')
      if val[0] in ('"', "'") and (len(val) < 2 or val[0] != val[-1]):
        ctx.error('span attribute value has mismatched quotes (possibly due to writeup doing naive splitting on whitespace);' \
          f'word: {word!r}; val: {val!r}')
      attrs.append(word)
  if not found_semicolon: ctx.error(f'span attributes must be terminated with semicolon')
  return f"<span {' '.join(attrs)}>{' '.join(body)}</span>"


span_dispatch = {
  'b' : span_bold,
  'embed' : span_embed,
  'http': span_link,
  'https': span_link,
  'link': span_link,
  'mailto': span_link,
  'span': span_span,
}


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
        out(f'<th>{html_esc(col)}</th>')
    out('</tr>', '</thead>\n', '<tbody>\n')
    for row in it:
      out('<tr>')
      for cell in row:
        out(f'<td>{html_esc(cell)}</td>')
      out('</tr>\n')
  out('</tbody>', '</table>\n')
  return ''.join(table)


def embed_txt(ctx, f):
  return f'<pre>\n{f.read()}</pre>'


embed_dispatch = {
  '.csv'  : embed_csv,
  '.txt'  : embed_txt,
}

def bind_exts(fn, *exts):
  embed_dispatch.update((ext, fn) for ext in exts)


def embed_direct(ctx, f):
  return f.read()


def embed_img(ctx, f):
  return f'<img src={f.name}>'


bind_exts(embed_direct, '.htm', '.html', '.svg')
bind_exts(embed_img, '.gif', '.jpeg', '.jpg', '.png')

# HTML escaping.

def html_esc(text: str):
  return html_escape(text, quote=False)

def html_esc_attr(text: str):
  return html_escape(text, quote=True)


# Error reporting.

def errZ(*items):
  print(*items, sep='', end='', file=stderr) #!cov-ignore.

def errSL(*items):
  print(*items, file=stderr)


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
  text-align: left;
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
