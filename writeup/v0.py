#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import sys
assert sys.version_info >= (3, 6, 0)

import re

from argparse import ArgumentParser
from html import escape as html_escape
from os.path import dirname as path_dir, exists as path_exists, join as path_join, basename as path_name, splitext as split_ext
from sys import stdin, stdout, stderr
from typing import re as Re, Any, Callable, Dict, Iterable, List, Optional, Sequence, Union, Tuple


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
  arg_parser.add_argument('-frag', action='store_true', help='Omit the top-level HTML document structure.')

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

  css = [] if (args.frag or args.no_css) else [default_css]
  for path in args.css:
    try:
      with open(path) as f:
        css.append(f.read())
    except FileNotFoundError:
      exit(f'writeup: css file does not exist: {args.css!r}')

  else:
    html_lines = list(writeup(
      src_path=src_path,
      src_lines=f_in,
      title=split_ext(path_name(src_path))[0],
      description='', # TODO.
      author='', # TODO.
      css=minify_css('\n'.join(css)),
      js=(None if args.frag or args.no_js else minify_js(default_js)),
      emit_doc=(not args.frag),
    ))
    for line in html_lines:
      print(line, file=f_out)


def writeup(src_path: str, src_lines: Iterable[str], title: str, description: str, author: str,
  css: Optional[str], js: Optional[str], emit_doc: bool) -> Iterable[str]:
  'generate a complete html document from a writeup file (or stream of lines).'

  ctx = Ctx(
    src_path=src_path,
    src_lines=src_lines,
    embed=True,
    emit_js=bool(js),
    emit_doc=emit_doc)

  if emit_doc:
    yield from [
      '<html>',
      '<head>',
      '  <meta charset="utf-8">',
      f'  <title>{title}</title>',
      f'  <meta name="description" content="{description}">',
      f'  <meta name="author" content="{author}">',
      '  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgo=">', # empty icon.
    ]
    if css:
      yield f'  <style type="text/css">{css}</style>'
    if js:
      yield f'  <script type="text/javascript"> "use strict";{js}</script>'
    yield '</head>'
    yield '<body id="body">'

  yield from ctx.lines

  if emit_doc:
    yield '</body>\n</html>'


def writeup_dependencies(src_path: str, src_lines: Iterable[str], dir_names: Optional[List[Any]]=None) -> List[str]:
  '''
  Return a list of dependencies from the writeup in `src_lines`.
  `dir_names` is an ignored argument passed by the external `muck` tool.
  '''
  ctx = Ctx(
    src_path=src_path,
    src_lines=src_lines,
    embed=False,
    emit_js=False,
    emit_doc=False)
  return sorted(ctx.dependencies)


class Span:
  'A tree node of inline HTML content.'
  def __init__(self, attrs, text):
    self.attrs = attrs
    self.text = text


class Line:
  def __int__(self, spans: List[Span]):
    self.spans = spans


class Block:
  'A tree node of block-level HTML content.'


class Section(Block):
  def __init__(self, index_path: Tuple[int, ...], title: Line, blocks: List[Block]):
    self.index_path = index_path
    self.title = title
    self.blocks = blocks

  def __repr__(self): return f'Section({self.sid}, {self.title!r})'

  @property
  def sid(self): return '.'.join(str(i) for i in self.index_path)


class ListItem(Block):
  def __init__(self, items: List[Block]):
    self.items = items


class Quote(Block):
  def __init__(self, blocks: List[Block]):
    self.blocks = blocks


class Code(Block):
  def __init__(self, lines: List[str]):
    self.lines = lines


class Text(Block):
  def __init__(self, lines: List[Line]):
    self.lines = lines


class Ctx:
  '''
  Parser context.
  Converts input writeup source text to output html lines and dependencies.
  '''

  def __init__(self, src_path: str, src_lines: Iterable[str], embed: bool, emit_doc: bool, emit_js: bool,
   is_versioned=True, warn_missing_final_newline=True, line_offset=0, quote_depth=0) -> None:
    self.src_path = src_path
    self.src_lines = src_lines
    self.embed = embed
    self.emit_doc = emit_doc
    self.emit_js = emit_js
    self.is_versioned = is_versioned
    self.warn_missing_final_newline = warn_missing_final_newline
    self.line_offset = line_offset
    self.quote_depth = quote_depth

    self.search_dir = path_dir(src_path) or '.'
    self.lines = []
    self.dependencies = []
    self.section_ids = [] # type: List[str] # accumulated list of all section ids.
    self.paging_ids = [] # type: List[str] # accumulated list of all paging (level 1 & 2) section ids.
    self.section_stack = [] # type: List[int] # stack of currently open sections.
    self.list_depth = 0 # currently open list depth.
    self.license_lines = [] # type: List[str]
    self.code_lines = [] # type: List[str]
    self.quote_line_num = 0
    self.quote_lines = [] # type: List[str]
    self.text_lines = [] # type: List[str]
    self.line = '' # updated per line.
    self.line_num = 0 # updated per line.
    parse(self)

  @property
  def section_depth(self) -> int:
    return len(self.section_stack)

  def out(self, *items: str, indent=0) -> None:
    self.lines.append('  ' * (self.section_depth + self.list_depth + indent) + ''.join(items))

  def dep(self, dependency: str) -> None:
    self.dependencies.append(dependency)

  def warn(self, *items):
    errSL(f'writeup warning: {self.src_path}:{self.line_num+1}:', *items)
    errSL(f'  {self.line!r}')

  def error(self, *items):
    errSL(f'writeup error: {self.src_path}:{self.line_num+1}:', *items)
    errSL(f'  {self.line!r}')
    exit(1)


version_re = re.compile(r'writeup v(\d+)\n')
# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.

license_re = re.compile(r'(©|Copyright|Dedicated to the public domain).*')
# license pattern is is only applied to the first line (following the version line, if any).

# line states.
s_start, s_license, s_section, s_list, s_quote, s_code, s_text, s_blank, s_end = range(9)

state_letters = '_©SLQCTBE' # for debug output only.

line_re = re.compile(r'''(?x:
(?P<indents> \s* )
(?:
  (?P<section_hashes>\#+) (?P<section_spaces> \s* ) (?P<section_title> .* )
| \* (?P<list_spaces> \s* ) (?P<list_contents> .+ )
| >  \ ? (?P<quote> .* )
| \| \ ? (?P<code> .* )
| (?P<text> .+ )
| (?P<blank>)
)
)''')

line_groups_to_states = {
  'section_title' : s_section,
  'list_contents' : s_list,
  'quote' : s_quote,
  'code': s_code,
  'text': s_text,
  'blank': s_blank,
}


def parse(ctx: Ctx):
  iter_src_lines = iter(ctx.src_lines)

  # Handle version line.
  if ctx.is_versioned:
    try:
      version_line = next(iter_src_lines)
    except StopIteration:
      version_line = ''
    m = version_re.fullmatch(version_line)
    if not m:
      exit(f'writeup error: first line must specify writeup version matching pattern: {version_re.pattern!r}\n  found: {version_line!r}')
    version = int(m.group(1))
    if version != 0: exit(f'unsupported version number: {version}')
    ctx.line_offset += 1

  # Iterate over lines.
  prev_state = s_start
  ctx.line_num = ctx.line_offset
  for line_num, raw_line in enumerate(iter_src_lines, ctx.line_offset):
    line = raw_line.rstrip('\n')
    ctx.line = line
    ctx.line_num = line_num
    if ctx.warn_missing_final_newline and not raw_line.endswith('\n'):
      ctx.warn('missing final newline.')

    # any license notice at top gets moved to a footer at the bottom of the html.
    if prev_state == s_start and license_re.fullmatch(line):
      ctx.license_lines.append(line.strip())
      prev_state = s_license
      continue
    if prev_state == s_license: # consume remaining license lines.
      if line.strip(): # not blank.
        ctx.license_lines.append(line)
        continue # remain in s_license.

    # normal line.
    m = line_re.fullmatch(line)
    state = line_groups_to_states[m.lastgroup]
    writeup_line(ctx=ctx, prev_state=prev_state, state=state, indents=m['indents'], m=m)
    prev_state = state

  # Finish.
  ctx.line = ''
  ctx.line_num += 1
  writeup_line(ctx=ctx, prev_state=prev_state, state=s_end, indents='', m=None)

  if ctx.emit_js:
    # Generate tables.
    ctx.out('<script type="text/javascript"> "use strict";')
    section_ids = ','.join(f"'s{sid}'" for sid in ctx.section_ids)
    ctx.out(f'section_ids = [{section_ids}];')
    paging_ids = ','.join(f"'s{pid}'" for pid in ctx.paging_ids)
    ctx.out(f"paging_ids = ['body', {paging_ids}];")
    ctx.out('</script>')


def writeup_line(ctx: Ctx, prev_state: int, state: int, indents: str, m=Optional[Re.Match]) -> None:
  'Inner function to process a line.'

  #errSL(f'{ctx.line_num:03} {state_letters[prev_state]}{state_letters[state]}: {ctx.line}')

  check_whitespace(ctx, -1, indents, ' in indent')
  l = len(indents)
  if l % 2: ctx.warn(f'odd indentation length: {l}.')
  list_depth = l // 2
  if ctx.list_depth < list_depth:
    ctx.error(f'indent implies missing parent list of depth {ctx.list_depth+1}')
  list_depth_changed = (ctx.list_depth != list_depth and state != s_blank)

  # Some transitions between states/depths require handling.
  if prev_state == s_code:
    if state != s_code or list_depth_changed:
      finish_code(ctx)
  elif prev_state == s_quote:
    if state != s_quote or list_depth_changed:
      finish_quote(ctx)
  elif prev_state == s_text:
    if state != s_text or list_depth_changed:
      finish_text(ctx)

  if state not in (s_list, s_blank):
    pop_lists_to_depth(ctx, list_depth)


  if state == s_section:
    output_section(ctx, hashes=m['section_hashes'], spaces=m['section_spaces'], title=m['section_title'])
  elif state == s_list:
    output_list(ctx, list_depth, spaces=m['list_spaces'], contents=m['list_contents'])
  elif state == s_code:
    output_code(ctx, code=m['code'])
  elif state == s_quote:
    is_first = (prev_state != state) or list_depth_changed
    output_quote(ctx, is_first, quote=m['quote'])
  elif state == s_text:
    output_text(ctx, text=m['text'])
  elif state == s_blank:
    if len(indents): ctx.warn('blank line is not empty')
  elif state == s_end:
    output_end(ctx)
  else: ctx.error(f'bad state: {state}')


def pop_lists_to_depth(ctx: Ctx, depth: int):
  while ctx.list_depth > depth:
    ctx.list_depth -= 1
    ctx.out('</ul>')


def pop_sections_to_depth(ctx: Ctx, depth: int):
  prev_index = 0
  while ctx.section_depth > depth:
    prev = ctx.section_stack.pop()
    ctx.out('</section>')
    prev_index = prev.index_path[depth]
  return prev_index


def finish_code(ctx: Ctx) -> None:
  # a newline after the `pre` open tag looks ok,
  # but a final newline between content and the `pre` close tag looks bad.
  # therefore we must take care to format the contents without a final newline.
  contents = '\n'.join(ctx.code_lines)
  ctx.out(f'<pre>\n{contents}</pre>')
  ctx.code_lines.clear()


def finish_quote(ctx: Ctx) -> None:
  ctx.out('<blockquote>')
  quote_ctx = Ctx(
    src_path=ctx.src_path,
    src_lines=ctx.quote_lines,
    line_offset=ctx.quote_line_num,
    is_versioned=False,
    warn_missing_final_newline=False,
    embed=ctx.embed,
    emit_js=False,
    emit_doc=False,
    quote_depth=ctx.quote_depth + 1)
  for ql in quote_ctx.lines:
    ctx.out(ql, indent=1)
  ctx.out('</blockquote>')
  ctx.quote_lines.clear()


def finish_text(ctx: Ctx) -> None:
  lines = [convert_text(ctx, line) for line in ctx.text_lines]
  if len(lines) == 1 and ctx.list_depth > 0:
    ctx.out(lines[0])
    return
  p = (ctx.list_depth == 0)
  if p: ctx.out('<p>')
  for i, line in enumerate(lines):
    if i: ctx.out('<br />')
    ctx.out(line, indent=1)
  if p: ctx.out('</p>')
  ctx.text_lines.clear()


def output_section(ctx: Ctx, hashes: str, spaces: str, title: str):
  check_whitespace(ctx, 1, spaces, 'following `#`')
  depth = len(hashes)
  if ctx.section_stack == []: # first/intro case only.
    index_path = (0,) # intro section is indexed 0; everything else is 1-indexed.
  elif depth > ctx.section_depth + 1:
      ctx.error(f'missing parent section of depth {ctx.section_depth+1}')
  else: # normal case.
    prev_index = pop_sections_to_depth(ctx, depth - 1)
    parent_path = ctx.section_stack[-1].index_path if ctx.section_depth else ()
    index_path = parent_path + (prev_index+1,)
  section = Section(index_path=index_path, title=title, blocks=[])
  ctx.section_stack.append(section)
  d = ctx.section_depth
  sid = section.sid
  quote_prefix = f'q{ctx.quote_depth}' if ctx.quote_depth else ''
  ctx.out(f'<section class="S{d}" id="{quote_prefix}s{sid}">', indent=-1)
  h_num = min(6, depth)
  ctx.out(f'<h{h_num} id="h{sid}">{convert_text(ctx, title)}</h{h_num}>')
  ctx.section_ids.append(sid)
  if depth <= 2:
    ctx.paging_ids.append(sid)


def output_list(ctx: Ctx, list_depth: int, spaces: str, contents: str):
  check_whitespace(ctx, 1, spaces, ' following `*`')
  depth = list_depth + 1
  pop_lists_to_depth(ctx, depth)
  while ctx.list_depth < depth:
    i = ctx.list_depth + 1
    ctx.out(f'<ul class="L{i}">')
    ctx.list_depth += 1
  ctx.out(f'<li>{convert_text(ctx, contents)}</li>')


def output_code(ctx: Ctx, code: str):
  ctx.code_lines.append(html_esc(code))


def output_quote(ctx: Ctx, is_first: bool, quote: str):
  if is_first:
    ctx.quote_line_num = ctx.line_num
  ctx.quote_lines.append(quote) # not converted here; text is fully transformed by finish_quote.


def output_text(ctx: Ctx, text: str):
  ctx.text_lines.append(text)


def output_end(ctx: Ctx):
  pop_sections_to_depth(ctx, 0)
  if ctx.emit_doc and ctx.license_lines:
    ctx.out('<footer id="footer">\n', '<br />\n'.join(ctx.license_lines), '\n</footer>')


def check_whitespace(ctx, len_exp, string, msg_suffix=''):
  for i, c in enumerate(string):
    if c != ' ':
      ctx.warn(f'invalid whitespace character at position {i+1}{msg_suffix}: {c!r}')
      return False
  if len_exp >= 0 and len(string) != len_exp:
    s = '' if len_exp == 1 else 's'
    ctx.warn(f'expected exactly {len_exp} space{s}{msg_suffix}; found: {len(string)}')
    return False
  return True


def convert_text(ctx: Ctx, text: str):
  'convert writeup span elements in a text string to html.'
  converted = []
  prev_idx = 0
  def flush(curr_idx):
    if prev_idx < curr_idx:
      converted.append(html_esc(text[prev_idx:curr_idx]))
  for m in span_re.finditer(text):
    start_idx = m.start()
    flush(start_idx)
    prev_idx = m.end()
    i = m.lastindex or 0
    fn = span_fns[i]
    group = m.group(i)
    converted.append(fn(ctx, group))
  flush(len(text))
  return ''.join(converted).strip()


def span_angle_conv(ctx: Ctx, text: str):
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


def span_text_conv(ctx: Ctx, text: str):
  return html_esc(text)


# span regexes.
# general pattern for quoting with escapes is Q([^EQ]|EQ|EE)*Q.
# it is crucial that the escape character E is excluded in the '[^EQ]' clause,
# or else when matching against 'QEQQ', the pattern greedily matches 'QEQ'.
# to allow a trailing escape character, the 'EE' clause is also required.

# backtick code span.
span_code_pat = r'`((?:[^\\`]|\\`|\\\\)*)`' # finds code spans.
span_code_esc_re = re.compile(r'\\`|\\\\') # escapes code strings.

# generic angle bracket span.
span_angle_pat = r'<((?:[^\\>]|\\>|\\\\)*)>'
span_angle_esc_re = re.compile(r'\\>|\\\\') # escapes span strings.

# span patterns and associated handlers.
span_pairs = (
  (span_code_pat, span_code_conv),
  (span_angle_pat, span_angle_conv),
)

span_fns = (None,) + tuple(f for _, f in span_pairs) # Match.group() is 1-indexed.

span_re = re.compile('|'.join(p for p, _ in span_pairs))
#^ wraps each span sub-pattern in capturing parentheses.

# generic angle bracket spans.

def span_bold(ctx: Ctx, tag: str, text: str) -> str:
  'convert a `bold` span into html.'
  return f'<b>{html_esc(text)}</b>'

def span_embed(ctx: Ctx, tag: str, text: str) -> str:
  'convert an `embed` span into html.'
  target_path = path_join(ctx.search_dir, text)
  if target_path.startswith('./'):
    target_path = target_path[2:]
  ctx.dep(target_path)
  if not ctx.embed: return ''
  try: f = open(target_path)
  except FileNotFoundError:
    ctx.error(f'embedded file not found: {target_path!r}')
  ext = split_ext(target_path)[1]
  try: fn = embed_dispatch[ext]
  except KeyError:
    ctx.error(f'embedded file has unknown extension type: {target_path!r}')
  return fn(ctx, f)


def span_link(ctx: Ctx, tag: str, text: str) -> str:
  'convert a `link` span into html.'
  words = text.split()
  if not words:
    ctx.error(f'link is empty: {tag!r}: {text!r}')
  if tag == 'link':
    link = words[0]
    ctx.dep(words[0])
  else:
    link = f'{tag}:{words[0]}'
  if len(words) == 1:
    visible = link
  else:
    visible = ' '.join(words[1:])
  return f'<a href={html_esc_attr(link)}>{html_esc(visible)}</a>'


def span_span(ctx: Ctx, tag: str, text: str) -> str:
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


def embed_direct(ctx, f):
  return f.read()


def embed_img(ctx, f):
  return f'<img src={f.name}>'


def embed_txt(ctx, f):
  return f'<pre>\n{f.read()}</pre>'


def embed_wu(ctx, f):
  lines: List[str] = []
  embed_ctx = Ctx(
    out_lines=lines,
    out_dependencies=ctx.dependencies,
    src_path=f.name,
    src_lines=f,
    line_offset=0,
    is_versioned=True,
    emit_js=False,
    emit_doc=False,
    quote_depth=ctx.quote_depth)
  return '\n'.join(embed_ctx.lines)


embed_dispatch = {
  '.csv'  : embed_csv,
  '.txt'  : embed_txt,
  '.wu'   : embed_wu,
}

def _add_embed(fn, *exts):
  embed_dispatch.update((ext, fn) for ext in exts)


_add_embed(embed_direct, '.htm', '.html', '.svg')
_add_embed(embed_img, '.gif', '.jpeg', '.jpg', '.png')

# HTML escaping.

def html_esc(text: str):
  # TODO: check for strange characters that html will ignore.
  return html_escape(text, quote=False)

def html_esc_attr(text: str):
  return html_escape(text, quote=True)


# Error reporting.

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

section#s0 {
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
  list-style-position: outside;
  list-style-type: disc;
  margin-left: 1rem;
  padding-left: 0.1rem;
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
