"""Build a deterministic, inventory-bound candidate for VM rehearsal."""
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

work = Path(__file__).resolve().parent
repo = work.parents[1] / 'exports/deepseek-harness-vm'
area = repo / 'work/harness-purge-improved'
package = area / 'package'
inventory = json.loads((area / 'package-files.json').read_text())
assert isinstance(inventory, dict) and inventory
def digest(raw):
    return sha256(raw).hexdigest()

def build():
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            for name, expected in sorted(inventory.items()):
                relative = PurePosixPath(name)
                assert not relative.is_absolute() and '..' not in relative.parts
                path = package / relative
                assert path.is_file() and path.resolve() == path
                raw = path.read_bytes()
                assert digest(raw) == expected, name
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                entry.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                archive.addfile(entry, io.BytesIO(raw))
    return buffer.getvalue()

archive = build()
assert archive == build()
out = work / 'harness-vm-candidate.tar.gz'
out.write_bytes(archive)
summary = {'archiveSha256':digest(archive),'archiveBytes':len(archive),'files':len(inventory),
           'inventorySha256':digest((area/'package-files.json').read_bytes()),'deterministicRebuild':True}
(work/'archive.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary))
