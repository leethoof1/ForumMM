"""Build the browser-only demo; never package server state or real code words."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
out=root/'dist';out.mkdir(exist_ok=True)
for name in ('index.html','app.js','style.css'):
 shutil.copyfile(root/'public'/name,out/name)
p=out/'index.html';p.write_text(p.read_text().replace('<body>','<body data-mode="browser">'))
shutil.copyfile(root/'data.json',out/'data.json')
(out/'.nojekyll').touch()
print('Built dist/: browser demo, progress resets on reload')
