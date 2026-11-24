"""Fetch exact archived PyPI wheels into local staging; never install them."""
from pathlib import Path
from hashlib import sha256
import json,urllib.request
w=Path(__file__).resolve().parent;target=w/'wheels';target.mkdir(exist_ok=True)
for row in json.loads((w/'runtime-wheels.json').read_text()):
 name=row['filename'];assert Path(name).name==name and name.endswith('.whl') and row['sourceUrl'].startswith('https://files.pythonhosted.org/')
 p=target/name
 if not p.is_file():
  raw=urllib.request.urlopen(row['sourceUrl'],timeout=40).read(25*1024*1024+1);assert len(raw)==row['bytes'] and sha256(raw).hexdigest()==row['sha256'];p.write_bytes(raw)
 assert p.stat().st_size==row['bytes'] and sha256(p.read_bytes()).hexdigest()==row['sha256']
print('Exact dependency archives matched; nothing installed')
