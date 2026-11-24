from pathlib import Path
from hashlib import sha256
import importlib.util,io,zipfile,unittest,stat,warnings
R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('archive_paths_gate',R/'operator/verify_delivery.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class ArchivePaths(unittest.TestCase):
 def check(self,names,reason,mode=None):
  out=io.BytesIO()
  with warnings.catch_warnings():
   warnings.simplefilter('ignore',UserWarning)
   with zipfile.ZipFile(out,'w') as z:
    for name in names:
     entry=zipfile.ZipInfo(name)
     if mode is not None:entry.external_attr=mode<<16
     z.writestr(entry,b'unit')
    z.writestr('LINKS.json',b'{}');z.writestr('ARCHIVE-ISSUES.json',b'[]')
  members={n:{'bytes':4,'sha256':sha256(b'unit').hexdigest()} for n in names}
  with zipfile.ZipFile(io.BytesIO(out.getvalue())) as z,self.assertRaisesRegex(ValueError,reason):m._f20_validate_archive(z,{'linksRecordedNotFollowed':{}},{},members,{})
 def test_parent_escape(self):self.check(['../outside'],'archive-path')
 def test_absolute(self):self.check(['/absolute'],'archive-path')
 def test_duplicate(self):self.check(['one','one'],'duplicate-member')
 def test_link(self):self.check(['one'],'archive-link',stat.S_IFLNK|0o600)
 def test_fifo(self):self.check(['one'],'special-member',stat.S_IFIFO|0o600)
if __name__=='__main__':unittest.main(verbosity=2)
