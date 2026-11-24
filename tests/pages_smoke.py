"""The Pages site links to the live application; it must not maintain another balance."""
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
class Page(HTMLParser):
 def __init__(self):super().__init__();self.links=[];self.scripts=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag=='a':self.links.append(attrs.get('href'))
  if tag=='script':self.scripts.append(attrs.get('src'))
p=Page();p.feed((ROOT/'index.html').read_text())
assert 'http://87.228.63.164/' in p.links
assert not p.scripts
assert 'data-mode="browser"' not in (ROOT/'index.html').read_text()
print('PASS: Pages links to one live forum; no separate browser-only balance')
