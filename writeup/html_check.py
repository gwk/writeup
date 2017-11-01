#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import re
from sys import stdin
from argparse import ArgumentParser
from html.parser import HTMLParser
from typing import *


def main():
  parser = ArgumentParser('Check the validity of HTML documents.')
  parser.add_argument('paths', nargs='*', help='paths to HTML documents (defaults to stdin).')
  args = parser.parse_args()

  try: files = [open(path) for path in args.paths]
  except FileNotFoundError as e: exit(f'file not found: {e.filename}')
  if not files: files = [stdin]

  for file in files:
    parser = Parser(path=file.name)
    parser.feed(file.read())
    parser.close()
    parser.check_completeness()


class Parser(HTMLParser):

  def __init__(self, path: str) -> None:
    super().__init__(convert_charrefs=True)
    self.path = path
    self.stack = []
    self.found_leading_doctype = False

  def check_completeness(self):
    if not self.found_leading_doctype:
      self.msg("did not find '<!DOCTYPE html>' declaration in leading position.", pos=(0,0))

  def handle_startendtag(self, tag, attrs):
    pass

  def handle_starttag(self, tag, attrs):
    self.stack.append((self.pos, tag))

  def handle_endtag(self, tag):
    if not self.stack:
      self.msg(f'unmatched closing tag at top level: {tag}')
      return
    if self.stack[-1][1] == tag:
      self.stack.pop()
      return
    for i in reversed(range(len(self.stack))):
      if self.stack[i][1] == tag: # found match.
        self.msg(f'unmatched closing tag: {tag}')
        for p, t in reversed(self.stack[i+1:]):
          self.msg(f'note: ignoring open `{t}` here', pos=p)
        self.msg(f'note: could match here', pos=self.stack[i][0])
        return
    self.msg(f'unmatched closing tag: {tag}')

  def handle_decl(self, decl):
    if decl == 'DOCTYPE html' and self.pos == (1, 1):
      self.found_leading_doctype = True
      return
    self.msg(f'decl: {decl!r}')

  def unknown_decl(data):
    self.msg(f'unknown decl: {data!r}')

  def handle_data(self, data): pass

  def handle_pi(self, data):
    self.msg(f'processing instruction: {data!r}')

  @property
  def pos(self):
    line1, col0 = self.getpos()
    return (line1-1, col0)

  def msg(self, msg, pos=None):
    if pos is None: pos = self.pos
    print(f'{self.path}:{pos[0]+1}:{pos[1]+1}: {msg}')


if __name__ == '__main__': main()
