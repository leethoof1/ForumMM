"""Build the GitHub Pages link to the live forum (no second balance database)."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]
out=root/'dist'
if out.exists(): shutil.rmtree(out)
(out/'public').mkdir(parents=True)
shutil.copyfile(root/'index.html',out/'index.html')
for name in ['style.css','logo.svg','district.svg']:
 shutil.copyfile(root/'public'/name,out/'public'/name)
(out/'.nojekyll').touch()
print('Pages landing built: links to the live forum')
