#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import sys
assert sys.version_info >= (3, 6, 0)

import re

from argparse import ArgumentParser
from html import escape as html_escape
from os.path import dirname as path_dir, exists as path_exists, join as path_join, basename as path_name, relpath as rel_path, splitext as split_ext
from sys import stdin, stdout, stderr
from typing import re as Re, Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Union, TextIO, Tuple


__all__ = ['main', 'writeup', 'writeup_dependencies']


def main() -> None:
  arg_parser = ArgumentParser(prog='writeup', description='Converts .wu files to html.')
  arg_parser.add_argument('src_path', nargs='?', help='Input .wu source path; defaults to <stdin>.')
  arg_parser.add_argument('dst_path', nargs='?', help='Output path: defaults to <stdout>.')
  arg_parser.add_argument('-deps', action='store_true',
    help='Print external file dependencies of the input, one per line. Does not output HTML.')
  arg_parser.add_argument('-css', nargs='+', default=(), help='paths to CSS.')
  arg_parser.add_argument('-no-css', action='store_true', help='Omit default CSS.')
  arg_parser.add_argument('-no-js', action='store_true', help='Omit default Javascript.')
  arg_parser.add_argument('-bare', action='store_true', help='Omit the top-level HTML document structure.')
  arg_parser.add_argument('-section', help='Emit only the specified section.')
  arg_parser.add_argument('-dbg', action='store_true', help='print debug info.')

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

  if args.deps:
    dependencies = writeup_dependencies(
      src_path=src_path,
      src_lines=f_in,
      dbg=args.dbg,
    )
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
    html_lines_gen = writeup(
      src_path=src_path,
      src_lines=f_in,
      title=split_ext(path_name(src_path))[0],
      description='', # TODO.
      author='', # TODO.
      css=minify_css('\n'.join(css)),
      js=(None if args.bare or args.no_js else minify_js(default_js)),
      emit_doc=(not args.bare),
      target_section=args.section,
      dbg=args.dbg,
    )
    for line in html_lines_gen:
      print(line, file=f_out)


def writeup(src_path: str, src_lines: Iterable[str], title: str, description: str, author: str,
  css: Optional[str], js: Optional[str], emit_doc: bool, target_section: Optional[str], dbg: bool) -> Iterable[str]:
  'generate a complete html document from a writeup file (or stream of lines).'

  ctx = Ctx(
    src_path=src_path,
    src_lines=src_lines,
    should_embed=True,
    dbg=dbg)

  if emit_doc:
    yield from [
      '<!DOCTYPE html>',
      '<html>',
      '<head>',
      '  <meta charset="utf-8" />',
      f' <title>{title}</title>',
      f' <meta name="description" content="{description}" />',
      f' <meta name="author" content="{author}" />',
      '  <link rel="icon" type="image/png" href="data:image/png;base64,iVBORw0KGgo=" />', # empty icon.
    ]
    if css:
      yield f'  <style type="text/css">{css}</style>'
    if js:
      yield f'  <script type="text/javascript"> "use strict";{js}</script>'
    yield '</head>'
    yield '<body id="body">'

  yield from ctx.emit_html(depth=0, target_section=target_section)

  if bool(js):
    # Generate tables.
    yield '<script type="text/javascript"> "use strict";'
    section_ids = ','.join(f"'s{sid}'" for sid in ctx.section_ids)
    yield f'section_ids = [{section_ids}];'
    paging_ids = ','.join(f"'s{pid}'" for pid in ctx.paging_ids)
    yield f"paging_ids = ['body', {paging_ids}];"
    yield '</script>'
  if emit_doc:
    if ctx.license_lines:
      yield '<footer id="footer">'
      yield '<br />\n'.join(ctx.license_lines)
      yield '</footer>'
    yield '</body>\n</html>'


def writeup_dependencies(src_path: str, src_lines: Iterable[str], dir_names: Optional[List[Any]]=None, dbg=False) -> List[str]:
  '''
  Return a list of dependencies from the writeup in `src_lines`.
  `dir_names` is an ignored argument passed by the external `muck` tool.
  '''
  ctx = Ctx(
    src_path=src_path,
    src_lines=src_lines,
    should_embed=False,
    dbg=dbg)
  return sorted(ctx.dependencies)


class Ctx: ...


class Span:
  'A tree node of inline HTML content.'
  def __init__(self, text: str):
    self.text = text

  def html(self, depth: int) -> str:
    return html_esc(self.text)

  def __repr__(self):
    return f'{self.__class__.__name__}({self.text!r})'

Spans = Tuple[Span, ...]


class CodeSpan(Span):
  def html(self, depth: int) -> str:
    'convert backtick code span to html.'
    span_char_esc_fn = lambda m: m.group(0)[1:] # strip leading '\' escape.
    text_escaped = span_code_esc_re.sub(span_char_esc_fn, self.text)
    text_escaped_html = html_esc(text_escaped)
    text_spaced = text_escaped_html.replace(' ', '&nbsp;') # TODO: should this be breaking space for long strings?
    return f'<code class="inline">{text_spaced}</code>'


class AttrSpan(Span):
  def __init__(self, text: str, attrs: Dict[str, str]):
    super().__init__(text=text)
    self.attrs = attrs


class BoldSpan(AttrSpan):
  def html(self, depth: int) -> str:
    return f'<b>{html_esc(self.text)}</b>'


class EmbedSpan(AttrSpan):
  def __init__(self, text: str, attrs: Dict[str, str], path: str, contents: List[str]):
    super().__init__(text=text, attrs=attrs)
    self.path = path
    self.contents = contents

  def html(self, depth: int) -> str:
    if attrs_bool(self.attrs, 'titled'):
      label = f'<div class="embed-label">{html_esc(self.path)}</div>\n'
    else:
      label= ''

    j = '\n' + '  ' * (depth + 1)
    # TODO: migrate various embed html details up to here?
    return label + j.join(self.contents)


class GenericSpan(AttrSpan):
  def __init__(self, text: str, attrs: Dict[str, str]):
    super().__init__(text=text, attrs=attrs)

  def html(self, depth: int) -> str:
    attr_str = ' '.join(f'{html_esc_attr(k)}="{html_esc_attr(v)}"' for k, v in self.attrs.items())
    return f"<span {attr_str}>{html_esc(self.text)}</span>"


class LinkSpan(AttrSpan):
  def __init__(self, text: str, attrs: Dict[str, str], tag: str, words: [str]):
    super().__init__(text=text, attrs=attrs)
    self.tag = tag
    if not words:
      ctx.error(f'link is empty: {self.tag!r}')
    if tag == 'link':
      self.link = words[0]
    else:
      self.link = f'{self.tag}:{words[0]}'
    if len(words) == 1:
      self.visible = self.link
    else:
      self.visible = ' '.join(words[1:])

  def html(self, depth: int) -> str:
    return f'<a href="{html_esc_attr(self.link)}">{html_esc(self.visible)}</a>'


class Block:
  'A tree node of block-level HTML content.'
  def finish(self, ctx): pass
  def html(self, ctx: Ctx, depth: int) -> Iterable[str]: raise NotImplementedError


class Section(Block):
  def __init__(self, section_depth: int, quote_depth: int, index_path: Tuple[int, ...], title: Spans):
    self.section_depth = section_depth
    self.quote_depth = quote_depth
    self.index_path = index_path
    self.title = title
    self.blocks: List[Block] = []

  def __repr__(self): return f'Section({self.sid}, {self.title}, {len(self.blocks)} blocks)'

  @property
  def sid(self): return '.'.join(str(i) for i in self.index_path)

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    sid = self.sid
    ctx.section_ids.append(sid)
    if self.section_depth <= 2: ctx.paging_ids.append(sid)
    quote_prefix = f'q{self.quote_depth}' if self.quote_depth else ''
    yield indent(depth, f'<section class="S{self.section_depth}" id="{quote_prefix}s{sid}">')
    h_num = min(6, self.section_depth)
    yield indent(depth + 1, f'<h{h_num} id="h{sid}">{html_for_spans(self.title, depth=depth)}</h{h_num}>')
    for block in self.blocks:
      yield from block.html(ctx, depth + 1)
    yield indent(depth, '</section>')


class UList(Block):
  def __init__(self, list_level: int):
    super().__init__()
    self.list_level = list_level # 1-indexed (top-level list is 1; no lists is 0).
    self.items: List[ListItem] = []

  def __repr__(self): return f'UList({self.list_level}, {len(self.items)} items)'

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    yield indent(depth, f'<ul class="L{self.list_level}">')
    for item in self.items:
      yield from item.html(ctx, depth + 1)
    yield indent(depth, f'</ul>')


class ListItem(Block):
  def __init__(self, list_level: int):
    self.list_level = list_level # 1-indexed (top-level list is 1; no lists is 0).
    self.blocks: List[Block] = []

  def __repr__(self): return f'ListItem({self.list_level}, {len(self.blocks)} blocks)'

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    if len(self.blocks) == 1 and isinstance(self.blocks[0], Text):
      if len(self.blocks[0].lines) == 1:
        yield indent(depth, f'<li>{html_for_spans(self.blocks[0].lines[0], depth=depth)}</li>')
      else:
        yield indent(depth, f'<li>')
        for i, line in enumerate(self.blocks[0].lines):
          if i: yield indent(depth, '<br />')
          yield indent(depth + 1, html_for_spans(line, depth=depth))
        yield indent(depth, f'</li>')
    else:
      yield indent(depth, f'<li>')
      for block in self.blocks:
        yield from block.html(ctx, depth + 1)
      yield indent(depth, f'</li>')


BranchBlock = Union[Section, UList, ListItem]


class LeafBlock(Block):
  def __init__(self):
    self.text_lines: List[str] = []

  def __repr__(self):
    head = f'{self.text_lines[0][0:64]!r}… {len(self.text_lines)} lines' if self.text_lines else ''
    return f'{type(self).__name__}({head})'


class Quote(LeafBlock):
  def __init__(self):
    super().__init__()
    self.quote_line_offset = -1
    self.blocks: List[Block] = []

  def finish(self, ctx: Ctx):
    assert self.quote_line_offset >= 0
    quote_ctx = Ctx(
      src_path=ctx.src_path,
      src_lines=self.text_lines,
      quote_depth=ctx.quote_depth + 1,
      line_offset=self.quote_line_offset,
      is_versioned=False,
      warn_missing_final_newline=False,
      should_embed=ctx.should_embed,
      dbg=ctx.dbg)
    self.blocks = quote_ctx.blocks

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    yield indent(depth, '<blockquote>')
    for block in self.blocks:
      yield from block.html(ctx, depth=depth + 1)
    yield indent(depth, '</blockquote>')


class Code(LeafBlock):

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    yield '<div class="code-block">'
    for line in self.text_lines:
      content = html_esc(line)
      yield f'<code class="line">{content}</code>'
    yield '</div>'


class Text(LeafBlock):
  def __init__(self):
    super().__init__()
    self.lines: List[Spans] = []

  def finish(self, ctx: Ctx):
    self.lines = [parse_spans(ctx, text=line) for line in self.text_lines]

  def html(self, ctx: Ctx, depth: int) -> Iterable[str]:
    yield indent(depth, '<p>')
    for i, line in enumerate(self.lines):
      if i: yield indent(depth, '<br />')
      yield indent(depth + 1, html_for_spans(line, depth=depth))
    yield indent(depth, '</p>')



class Ctx:
  '''
  Parser context.
  Converts input writeup source text to output html lines and dependencies.
  '''

  def __init__(self, src_path: str, src_lines: Iterable[str], should_embed: bool,
   is_versioned=True, warn_missing_final_newline=True, quote_depth=0, line_offset=0, dbg=False) -> None:
    self.src_path = src_path
    self.src_lines = src_lines
    self.should_embed = should_embed
    self.is_versioned = is_versioned
    self.warn_missing_final_newline = warn_missing_final_newline
    self.quote_depth = quote_depth
    self.line_offset = line_offset
    self.dbg = dbg

    self.search_dir = path_dir(src_path) or '.'
    self.license_lines: List[str] = []
    self.stack: List[Block] = [] # stack of currently open content blocks.
    self.blocks: List[Block] = [] # top level blocks.
    self.dependencies: List[str] = []
    self.section_ids: List[str] = [] # accumulated list of all section ids.
    self.paging_ids: List[str] = [] # accumulated list of all paging (level 1 & 2) section ids.

    self.line = '' # updated per line.
    self.line_num = 0 # updated per line.

    parse(self)


  @property
  def depth(self) -> int:
    return len(self.stack)

  @property
  def list_level(self) -> int:
    for block in reversed(self.stack):
      if isinstance(block, (UList, ListItem)):
        return block.list_level
    return 0

  @property
  def top(self) -> Block:
    return self.stack[-1]

  def push(self, block: Block):
    self.dbgSL('PUSH', self.line_num, self.stack, block)
    if self.stack:
      self.top.blocks.append(block)
    else:
      self.blocks.append(block)
    self.stack.append(block)

  def pop(self) -> Block:
    self.dbgSL('POP', self.line_num, self.stack)
    popped = self.stack.pop()
    popped.finish(self)
    return popped

  def pop_to_section_depth(self, section_depth: int) -> int:
    prev_index = 0
    while self.depth > section_depth:
      prev = self.pop()
      prev_index = prev.index_path[section_depth]
    return prev_index

  def pop_to_list(self, list_level: int):
    self.dbgSL('POP TO LIST', list_level)
    while self.stack:
      top = self.top
      if isinstance(top, Section): return
      if isinstance(top, UList) and top.list_level <= list_level: return
      if isinstance(top, ListItem) and top.list_level < list_level: return
      self.pop()

  def append_to_leaf_block(self, list_level, block_type, line):
    self.dbgSL("APPEND", list_level, block_type.__name__, line)
    while self.stack:
      top = self.top
      if isinstance(top, Section): break
      if isinstance(top, ListItem) and top.list_level <= list_level: break
      if isinstance(top, block_type) and self.list_level == list_level: break
      self.pop()
    if self.stack and isinstance(self.top, block_type):
      leaf = self.top
    else:
      leaf = block_type()
      self.push(leaf)
    leaf.text_lines.append(line)
    self.dbgSL('-', self.stack)

  def close_leaf_block(self):
    if self.stack and isinstance(self.top, LeafBlock):
      self.pop()
      assert not self.stack or isinstance(self.top, (Section, ListItem))

  def emit_html(self, depth: int, target_section: Optional[str]=None):
    for block in self.blocks:
      if target_section:
        if not isinstance(block, Section) or text_for_spans(block.title) != target_section: continue
      yield from block.html(ctx=self, depth=depth)

  def add_dependency(self, dependency: str) -> None:
    self.dependencies.append(dependency)

  def warn(self, *items):
    errSL(f'writeup warning: {self.src_path}:{self.line_num+1}:', *items)
    errSL(f'  {self.line!r}')

  def error(self, *items):
    errSL(f'writeup error: {self.src_path}:{self.line_num+1}:', *items)
    errSL(f'  {self.line!r}')
    exit(1)

  def dbgSL(self, *items):
    if self.dbg: errSL(*items)


version_re = re.compile(r'writeup v(\d+)\n')
# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.

license_re = re.compile(r'(©|Copyright|Dedicated to the public domain).*')
# license pattern is is only applied to the first line (following the version line, if any).

# line states.
s_start, s_license, s_section, s_quote, s_code, s_text, s_blank = range(7)

state_letters = '^©SQCTB' # for debug output only.

line_re = re.compile(r'''(?x:
(?P<section_indents> \s* ) (?P<section_hashes>\#+) (?P<section_spaces> \s* ) (?P<section_title> .* )
|
(?P<indents> \s* )
( (?P<list_star> \* ) (?P<list_spaces> \s* ) )?
(?:
  >  \s? (?P<quote> .* )
| \| \s? (?P<code> .* )
| (?P<text> [^\s] .* )
| # blank.
)
)''')

line_groups_to_states = {
  'section_title' : s_section,
  'quote' : s_quote,
  'code': s_code,
  'text': s_text,
} # defaults to s_blank.


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
    #errSL('L', repr(line))
    #errSL('M', m)
    state = line_groups_to_states.get(m.lastgroup, s_blank)
    writeup_line(ctx=ctx, state=state, m=m)
    prev_state = state

  # Finish.
  while ctx.stack:
    ctx.pop()


def writeup_line(ctx: Ctx, state: int, m: Re.Match) -> None:
  'Inner function to process a line.'

  ctx.dbgSL(f'DBG {ctx.line_num:03} {state_letters[state]}: {ctx.line}')

  if state == s_section:
    ctx.pop_to_list(0)
    if m['section_indents']: ctx.error(f'section header cannot be indented.')
    check_whitespace(ctx, 1, m['section_spaces'], 'following `#`')
    section_depth = len(m['section_hashes'])
    if not ctx.stack: # first/intro case only.
      index_path = (0,) # intro section is indexed 0; everything else is 1-indexed.
    elif section_depth > ctx.depth + 1:
        ctx.error(f'missing parent section of depth {ctx.depth + 1}')
    else: # normal case.
      prev_index = ctx.pop_to_section_depth(section_depth - 1)
      parent_path = ctx.top.index_path if ctx.stack else ()
      index_path = parent_path + (prev_index+1,)
    title = parse_spans(ctx, text=m['section_title'])
    section = Section(section_depth=section_depth, quote_depth=ctx.quote_depth, index_path=index_path, title=title)
    ctx.push(section)
    return

  indents = m['indents']
  check_whitespace(ctx, -1, indents, ' in indent')
  l = len(indents)
  if l % 2: ctx.error(f'odd indentation length: {l}.')
  list_level = l // 2
  if ctx.list_level < list_level:
    errSL(ctx.stack)
    ctx.error(f'indent implies missing parent list at indent depth {ctx.list_level+1}.')

  if m['list_star']:
    check_whitespace(ctx, 1, m['list_spaces'], ' following `*`')
    goal_level = list_level + 1
    ctx.pop_to_list(goal_level)
    if ctx.list_level < goal_level:
      assert ctx.list_level + 1 == goal_level
      ulist = UList(list_level=goal_level)
      ctx.push(ulist)
    else:
      ulist = ctx.top
      assert isinstance(ulist, UList)
    item = ListItem(list_level=goal_level)
    ulist.items.append(item)
    ctx.stack.append(item)
    list_level = goal_level

  if state == s_code:
    ctx.append_to_leaf_block(list_level, Code, m['code'])

  elif state == s_quote:
    ctx.append_to_leaf_block(list_level, Quote, m['quote'])
    if len(ctx.top.text_lines) == 1: # this is the first line.
      ctx.stack[-1].quote_line_offset = ctx.line_num

  elif state == s_text:
    ctx.append_to_leaf_block(list_level, Text, m['text'])

  elif state == s_blank:
    if len(indents): ctx.warn('blank line is not empty.')
    ctx.close_leaf_block()

  else: ctx.error(f'bad state: {state}')


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


def parse_spans(ctx: Ctx, text: str) -> Spans:
  spans = []
  prev_idx = 0
  def flush(curr_idx):
    if prev_idx < curr_idx:
      spans.append(Span(text=text[prev_idx:curr_idx]))
  for m in span_re.finditer(text):
    start_idx = m.start()
    flush(start_idx)
    prev_idx = m.end()
    i = m.lastindex or 0
    span_fn = span_fns[i]
    group_text = m.group(i)
    spans.append(span_fn(ctx, group_text))
  flush(len(text))
  return tuple(spans)


def span_angle_conv(ctx: Ctx, text: str) -> Span:
  'convert angle bracket span to html.'
  tag, colon, post_tag_text = text.partition(':')
  if colon is None: ctx.error(f'malformed span is missing colon after tag: {text!r}')

  attrs_list = []
  body_words = []
  in_body = False
  # TODO: better escaping syntax for equals.
  for i, word in enumerate(post_tag_text.split(' ')):
    if in_body or (i == 0 and tag in span_link_tags):
      # hack: for URLs; do not partition first word because URL might contain '='.
      body_words.append(word); continue
    if word == '': continue
    if word == ';': in_body = True; continue
    key, eq, val = word.partition('=')
    if not eq:
      body_words.append(word)
      continue
    if val.endswith(';'):
      in_body = True
      val = val[:-1]
    if not sym_re.fullmatch(key): ctx.error(f'span attribute name is invalid: {word!r}')
    if not val: ctx.error(f'span attribute value is empty; word: {word!r}')
    if val[0] in ('"', "'") and (len(val) < 2 or val[0] != val[-1]):
      ctx.error('span attribute value has mismatched quotes (possibly due to writeup doing naive splitting on whitespace);' \
        f'word: {word!r}; val: {val!r}')
    attrs_list.append((key, val))
  if not body_words: ctx.error(f'span has no body (missing colon after the tag?)')
  body_text = ' '.join(body_words)

  attrs = dict(attrs_list)
  if tag == 'b':
    return BoldSpan(text=body_text, attrs=attrs)
  if tag == 'embed':
    return embed(ctx, text=body_text, attrs=attrs)
  if tag in span_link_tags:
    span = LinkSpan(text=body_text, attrs=attrs, tag=tag, words=body_words)
    if tag == 'link':
      ctx.add_dependency(span.link)
    return span
  if tag == 'span':
    return GenericSpan(text=body_text, attrs=attrs)
  ctx.error(f'span has invalid tag: {tag!r}')


span_link_tags = { 'http', 'https', 'link', 'mailto' }


def span_code_conv(ctx: Ctx, text: str) -> Span:
  return CodeSpan(text=text)


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


# Embed.


def embed(ctx: Ctx, text: str, attrs: Dict[str, str]) -> Span:
  'convert an `embed` span into html.'
  path = path_join(ctx.search_dir, text)
  if path.startswith('./'):
    path = path[2:]
  ctx.add_dependency(path)
  if ctx.should_embed:
    try: f = open(path)
    except FileNotFoundError:
      ctx.error(f'embedded file not found: {path!r}')
    ext = attrs.get('ext')
    if not ext:
      ext = split_ext(path)[1]
    try: embed_fn = embed_dispatch[ext]
    except KeyError:
      ctx.error(f'embedded file has unknown extension type: {path!r}')
    contents = tuple(embed_fn(ctx, f))
  else:
    contents = []
  return EmbedSpan(text=text, attrs=attrs, path=path, contents=contents)


def embed_css(ctx: Ctx, f: TextIO) -> List[str]:
  css = f.read()
  return [f'<style type="text/css">{html_esc(css)}</style>']


def embed_csv(ctx: Ctx, f: TextIO) -> List[str]:
  from csv import reader
  csv_reader = reader(f)
  it = iter(csv_reader)
  lines = ['<table>']

  def append(*els): lines.append(''.join(els))

  try: header = next(it)
  except StopIteration: pass
  else:
    append('<thead>', '<tr>')
    append('  ', *[f'<th>{html_esc(col)}</th>' for col in header])
    append('</tr>', '</thead>', '<tbody>')
    for row in it:
      append('  <tr>', *[f'<td>{html_esc(cell)}</td>' for cell in row], '</tr>')
    append('</tbody>')
  append('</table>')
  return lines


def embed_code(ctx: Ctx, f: TextIO) -> Iterator[str]:
  yield '<div class="code-block">'
  for line in f:
    content = html_esc(line)
    yield f'<code class="line">{content}</code>'
  yield '</div>'


def embed_direct(ctx: Ctx, f: TextIO) -> List[str]:
  return list(filter(None, (xml_processing_instruction_re.sub('', line.rstrip()) for line in f)))

xml_processing_instruction_re = re.compile(r'<\?[^>]*>')


def embed_html(ctx: Ctx, f: TextIO) -> List[str]:
  src_dir = path_dir(ctx.src_path) or '.'
  lines = list(f)
  head = ''
  for head in lines:
    if head.strip(): break
  if html_doc_re.match(head): # looks like a complete html doc.
    # TODO: we shouldn't just leave a cryptic error message here.
    # Use an iframe? Or does object tag work for this purpose?
    path = rel_path(f.name, start=src_dir)
    msg = f'<error: missing object: {path!r}>'
    return [f'<object data="{html_esc_attr(path)}" type="text/html">{html_esc(msg)}</object>']
  else:
    return list(line.rstrip() for line in lines)

html_doc_re = re.compile(r'''(?xi)
\s* < \s* (!doctype \s+)? html
''')


def embed_img(ctx: Ctx, f: TextIO) -> List[str]:
  return [f'<img src={html_esc(f.name)}>']


def embed_wu(ctx: Ctx, f: TextIO) -> List[str]:
  embed_ctx = Ctx(
    src_path=f.name,
    src_lines=f,
    quote_depth=ctx.quote_depth,
    line_offset=0,
    is_versioned=True,
    should_embed=ctx.should_embed)
  return list(embed_ctx.emit_html(depth=0))


embed_dispatch: Dict[str, Callable[[Ctx, TextIO], Iterable[str]]] = {
  '.css'  : embed_css,
  '.csv'  : embed_csv,
  '.wu'   : embed_wu,
}

def _add_embed(fn, *exts):
  embed_dispatch.update((ext, fn) for ext in exts)


_add_embed(embed_code, '.bash', '.js', '.py', '.sh', '.sql', '.swift', '.txt')
_add_embed(embed_direct, '.svg')
_add_embed(embed_html, '.htm', '.html')
_add_embed(embed_img, '.gif', '.jpeg', '.jpg', '.png')


sym_re = re.compile(r'[-_\w]+')


def attrs_bool(attrs: Dict[str, str], key: str) -> bool:
  return attrs.get(key) in {'true', 'yes'}


# HTML output.

def html_esc(text: str):
  # TODO: check for strange characters that html will ignore.
  return html_escape(text, quote=False)


def html_esc_attr(text: str):
  return html_escape(text, quote=True)


def html_for_spans(spans: Spans, depth: int) -> str:
  return ''.join(span.html(depth=depth) for span in spans).strip()


def text_for_spans(spans: Spans) -> str:
  return ''.join(span.text for span in spans).strip()


def indent(depth: int, *items: str) -> str:
  return '  ' * depth + ''.join(items)


# Error reporting.

def errSL(*items):
  print(*items, file=stderr)


# CSS.

minify_css_re = re.compile(r'(?s)(?<=: )(.+?;)|\s+|/\*.*?\*/|//[^\n]*\n?')
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
a:link { color: #1010A0; }
a:visited { color: #301080; border-bottom: 3px solid;  }
blockquote {
  border-left-color: #E0E0E0;
  border-left-style: solid;
  border-left-width: 0.333rem;
  margin: 0;
  padding: 0 0.667rem;
}
body {
  margin: 0 auto;
  max-width: 64rem;
  border: transparent solid 0.5rem; // hack to get horizontal minimum margin.
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
  font-family: source code pro, terminal, monospace;
}
code.inline {
  background-color: #F0F0F0;
  border-color: #D0D0D0;
  border-radius: 2px;
  border-style: solid;
  border-width: 0.5px;
  overflow-wrap: break-word;
  white-space: pre-wrap;
}
code.line {
  display: block;
  margin: 0;
  overflow-wrap: break-word;
  padding: 0 0 0 0.5rem;
  text-indent: -0.5rem;
  white-space: pre-wrap;
}
div.code-block {
  background-color: #F0F0F0;
  border-color: #D0D0D0;
  border-radius: 4px;
  border-style: solid;
  border-width: 0.5px;
  font-size: 1rem;
  margin: 1rem 0;
  padding: 0.1rem;
}
div.embed-label {
  background-color: #FFFFFF;
  border-bottom-style: none;
  border-color: #E0E0E0;
  border-style: solid solid none solid;
  border-top-left-radius: 4px;
  border-top-right-radius: 4px;
  border-width: 0.5px;
  color: #404040;
  display: inline-block;
  font-family: source code pro, terminal, monospace;
  font-size: 0.8rem;
  margin-top: 1rem;
}
div.embed-label + * {
  border-top-left-radius: 0;
  margin-top: 0.5px;
}
footer { display: block; }
h1 { font-size: 1.8rem; margin: 0.9rem 0; }
h2 { font-size: 1.6rem; margin: 0.8rem 0; }
h3 { font-size: 1.4rem; margin: 0.7rem 0; }
h4 { font-size: 1.3rem; margin: 0.65rem 0; }
h5 { font-size: 1.2rem; margin: 0.6rem 0; }
h6 { font-size: 1.1rem; margin: 0.55rem 0; }
header { display: block; }
html {
  background: white;
  color: black;
  font-family: source sans pro, sans-serif;
  font-size: 1rem;
}
nav { display: block; }
p { margin: 0.5rem 0; }
section { display: block; }
section.S1 {
  border-top-color: #E8E8E8;
  border-top-style: solid;
  border-top-width: 1px;
  margin: 1.8rem 0;
}
section.S2 { margin: 1.6rem 0; }
section.S3 { margin: 1.4rem 0; }
section.S4 { margin: 1.3rem 0; }
section.S5 { margin: 1.2rem 0; }
section.S6 { margin: 1.1rem 0; }
section#s0 {
  border-top-width: 0;
}
table {
  background: #F0F0F0;
  border-radius: 4px;
  border: #D0D0D0 0.5px solid;
}
table th {
  padding: 0.25rem 0.25rem;
}
table th:first-child {
  padding-left: 0.25rem;
  text-align: left;
}
table td {
  background: #FAFAFA;
  font-family: monospace;
  padding:0.25rem;
  white-space: pre;
}
table td:first-child {
  border-left: 0;
  padding-left: 0.25rem;
  text-align: left;
}
table tr {
  padding-left: 0.25rem;
  text-align: left;
}
table tr:last-child td {
  border-bottom: 0;
}
table tr:last-child td:first-child {
  border-bottom-left-radius: 2px;
}
table tr:last-child td:last-child {
  border-bottom-right-radius: 2px;
}
table tr:nth-child(odd) td {
  background: #FFFFFF;
}
table tr:nth-child(even) td {
  background: #FBFBFB;
}
table tr:hover td {
  background: #F0F0F0;
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
