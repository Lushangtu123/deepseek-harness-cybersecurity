import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('catalog_manager',Path(__file__).with_name('manage.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RecoveryCatalog(unittest.TestCase):
 def catalog(self,root,snapshots=None,fail=False,real_verify=False,after=None,snapshot_after=None,metadata_text=None):
  (root/'recoveries').mkdir(exist_ok=True)
  image=root/'Harness Purge Original.utm/Data/ubuntu.qcow2';image.parent.mkdir(parents=True,exist_ok=True);image.write_bytes(b'synthetic')
  verify=patch.object(m,'verify_recovery_bundle',wraps=m.verify_recovery_bundle) if real_verify else patch.object(m,'verify_recovery_bundle',return_value=(root,{'createdAt':'2026-10-27T00:00:00Z'}))
  with patch.object(m,'ROOT',root),patch.object(m,'VM',image.parent.parent),patch.object(m,'validate'),patch.object(m,'image_command',side_effect=OSError('private failure') if fail else None,return_value=MagicMock(stdout=metadata_text if metadata_text is not None else json.dumps({'snapshots':snapshots or []}))),verify:
   options={}
   if after is not None:options['after']=after
   if snapshot_after is not None:options['snapshot_after']=snapshot_after
   return m.recovery_catalog(**options)
 def test_catalog_protects_baselines_and_latest_three_without_deleting(self):
  self.assertTrue(callable(getattr(m,'recovery_catalog',None)),'Missing read-only recovery catalog')
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();(root/'recoveries').mkdir()
   for name in m.REVIEWED_RECOVERIES:(root/'recoveries'/name).mkdir()
   snapshots=[{'name':name} for name in ['ready-original','ready-toolchain-20261025',*m.REVIEWED_RECOVERIES]]
   result=self.catalog(root,snapshots)
   self.assertTrue(result['readOnly']);self.assertEqual(result['snapshotState'],'observed')
   by_name={row['name']:row for row in result['snapshots']}
   for name in ['ready-original','ready-toolchain-20261025',*m.REVIEWED_RECOVERIES[-3:]]:self.assertTrue(by_name[name]['protected'])
   self.assertTrue(by_name[m.REVIEWED_RECOVERIES[0]]['reviewCandidate'])
   self.assertTrue(all((root/'recoveries'/name).is_dir() for name in m.REVIEWED_RECOVERIES))
 def test_archives_never_follow_symlinks_or_claim_reclaimable_shared_blocks(self):
  self.assertTrue(callable(getattr(m,'recovery_catalog',None)))
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();archive=root/'archived-validation';archive.mkdir();good=archive/'restore-probe-workbench-v5-20261027/offline-image/Data/ubuntu.qcow2';good.parent.mkdir(parents=True);good.write_bytes(b'archive')
   outside=root/'outside';outside.mkdir();(outside/'private.qcow2').write_bytes(b'private')
   (archive/'linked-dir').symlink_to(outside,target_is_directory=True);(archive/'linked.qcow2').symlink_to(outside/'private.qcow2')
   result=self.catalog(root)
   self.assertEqual(len(result['images']),1);self.assertEqual(result['images'][0]['logicalBytes'],7)
   self.assertNotIn('private',json.dumps(result));self.assertNotIn('reclaimableBytes',json.dumps(result))
 def test_unavailable_disk_metadata_is_not_reported_as_no_snapshots(self):
  self.assertTrue(callable(getattr(m,'recovery_catalog',None)))
  with tempfile.TemporaryDirectory() as temp:
   result=self.catalog(Path(temp).resolve(),fail=True)
   self.assertEqual(result['snapshotState'],'unavailable');self.assertNotIn('private failure',json.dumps(result))
 def test_malformed_snapshot_structure_is_unknown_instead_of_empty(self):
  for value in [None,[],4,{'snapshots':{}},{'snapshots':'bad'},{'snapshots':3},{'snapshots':None},{'snapshots':[None]},{'snapshots':[{'name':None}]},{'snapshots':[{'name':'ready-original'},{}]}]:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as temp:
    result=self.catalog(Path(temp).resolve(),metadata_text=json.dumps(value));self.assertEqual(result['snapshotState'],'unavailable');self.assertTrue(all(row['present'] is None and not row['reviewCandidate'] for row in result['snapshots']))
 def test_valid_empty_or_omitted_snapshot_array_remains_an_observed_empty_disk(self):
  for value in [{'snapshots':[]},{'format':'qcow2'},{'snapshots':[{'name':'ready-original','id':'1'}]}]:
   with self.subTest(value=value),tempfile.TemporaryDirectory() as temp:
    result=self.catalog(Path(temp).resolve(),metadata_text=json.dumps(value));self.assertEqual(result['snapshotState'],'observed');row=next(row for row in result['snapshots'] if row['name']=='ready-original');self.assertEqual(row['present'],bool(value.get('snapshots')))
 def test_depth_and_read_error_limits_explicitly_mark_partial_results(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();deep=root/'archived-validation/a/b/c/d/e/f/image.qcow2';deep.parent.mkdir(parents=True);deep.write_bytes(b'deep')
   result=self.catalog(root);self.assertTrue(result['truncated']);self.assertEqual(result['images'],[])
   def unreadable(*args):raise PermissionError('synthetic unreadable directory')
   with patch.object(m,'archive_directory',side_effect=unreadable):self.assertTrue(self.catalog(root)['truncated'])
 def test_one_malformed_old_archive_does_not_hide_the_remaining_catalog(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();old=root/'recoveries'/m.REVIEWED_RECOVERIES[0];old.mkdir(parents=True);(old/'manifest.json').write_text('[]')
   result=self.catalog(root,[{'name':old.name}],real_verify=True)
   by_name={row['name']:row for row in result['snapshots']}
   self.assertEqual(by_name[old.name]['bundleState'],'invalid')
   self.assertIn(m.CURRENT_RECOVERY,by_name)
 def test_metadata_trees_do_not_hide_known_offline_images(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();archive=root/'archived-validation'
   for i in range(3):
    entry=archive/f'restore-probe-{i:02d}'
    for n in range(180):(entry/'host-tools'/f'cache-{n}').mkdir(parents=True)
    image=entry/'offline-image/Data/ubuntu.qcow2';image.parent.mkdir(parents=True);image.write_bytes(b'image')
   result=self.catalog(root)
   self.assertFalse(result['truncated']);self.assertEqual(len(result['images']),3)
   self.assertEqual(result['archiveScan']['skippedMetadataDirectories'],3)
 def test_archive_pages_cover_all_entries_without_duplicates(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();archive=root/'archived-validation'
   expected=[]
   for i in range(35):
    image=archive/f'probe-{i:02d}/offline-image/Data/ubuntu.qcow2';image.parent.mkdir(parents=True);image.write_bytes(b'image');expected.append(str(image.relative_to(archive)))
   after=None;seen=[];cursors=set()
   for page in range(4):
    result=self.catalog(root,after=after);self.assertFalse(result['truncated']);self.assertLessEqual(result['archiveScan']['entriesScanned'],16)
    seen.extend(row['id'] for row in result['images']);after=result['nextCursor']
    if after is None:break
    self.assertNotIn(after,cursors);cursors.add(after)
   self.assertEqual(seen,expected);self.assertEqual(len(cursors),2)
 def test_invalid_archive_cursor_cannot_escape_the_fixed_root(self):
  with tempfile.TemporaryDirectory() as temp:
   for cursor in ['../outside','a/b','.hidden','provider-name','x'*241]:
    with self.subTest(cursor=cursor),self.assertRaises(ValueError):self.catalog(Path(temp).resolve(),after=cursor)
 def test_depth_limit_is_named_and_not_silently_complete(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();image=root/'archived-validation/a/b/c/d/e/f/image.qcow2';image.parent.mkdir(parents=True);image.write_bytes(b'image')
   result=self.catalog(root);self.assertTrue(result['truncated']);self.assertIn('depth-limit',result['archiveScan']['reasons'])
 def test_exact_page_budgets_do_not_consume_the_next_unvisited_archive(self):
  for budget in ['directories','images']:
   with self.subTest(budget=budget),tempfile.TemporaryDirectory() as temp:
    root=Path(temp).resolve();archive=root/'archived-validation';large=archive/'a-large';large.mkdir(parents=True)
    if budget=='directories':
     for i in range(511):(large/f'dir-{i:03d}').mkdir()
    else:
     for i in range(80):(large/f'image-{i:02d}.qcow2').write_bytes(b'image')
    for name in ['b-image','c-image']:
     image=archive/name/'disk.qcow2';image.parent.mkdir();image.write_bytes(b'image')
    first=self.catalog(root);self.assertEqual(first['nextCursor'],'a-large');self.assertFalse(first['truncated'])
    second=self.catalog(root,after=first['nextCursor']);self.assertIsNone(second['nextCursor']);self.assertFalse(second['truncated'])
    self.assertEqual([row['id'] for row in second['images']],['b-image/disk.qcow2','c-image/disk.qcow2'])

 def test_snapshot_pages_pin_current_and_baselines_then_cover_every_snapshot(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();names=[f'a-extra-{i:03d}' for i in range(165)]+['ready-original','ready-toolchain-20261025',m.CURRENT_RECOVERY]
   inputs=[{'name':name} for name in names];first=self.catalog(root,inputs)
   shown={row['name'] for row in first['snapshots']}
   self.assertIn(m.CURRENT_RECOVERY,shown);self.assertIn('ready-original',shown);self.assertIn('ready-toolchain-20261025',shown)
   self.assertEqual(first['snapshots'][0]['name'],m.CURRENT_RECOVERY);self.assertFalse(first['truncated'])
   after=first.get('nextSnapshotCursor');self.assertTrue(after,'Snapshot continuation must be distinct from archive continuation')
   while after is not None:
    page=self.catalog(root,inputs,snapshot_after=after);self.assertFalse(page['truncated']);self.assertLessEqual(len(page['snapshots']),80)
    incoming={row['name'] for row in page['snapshots']};self.assertFalse(shown&incoming);shown|=incoming
    following=page['nextSnapshotCursor'];self.assertTrue(following is None or following>after);after=following
   self.assertEqual(shown,set(names)|set(m.REVIEWED_RECOVERIES))

 def test_snapshot_cursor_is_restricted_to_public_names(self):
  with tempfile.TemporaryDirectory() as temp:
   for cursor in ['../outside','a/b','.hidden','secret-name','x'*241]:
    with self.subTest(cursor=cursor):
     try:self.catalog(Path(temp).resolve(),snapshot_after=cursor)
     except ValueError:continue
     except Exception as error:self.fail('Invalid snapshot cursor must be a validation error, got '+type(error).__name__)
     self.fail('Invalid snapshot cursor accepted')

 def test_missing_baselines_are_still_explained_in_the_first_page(self):
  with tempfile.TemporaryDirectory() as temp:
   for fail in [False,True]:
    result=self.catalog(Path(temp).resolve(),fail=fail);rows={row['name']:row for row in result['snapshots']}
    for name in ['ready-original','ready-toolchain-20261025']:
     self.assertIn(name,rows);self.assertEqual(rows[name]['present'],None if fail else False);self.assertTrue(rows[name]['protected'])

 def test_nonpublic_long_snapshot_names_do_not_produce_unusable_cursors(self):
  with tempfile.TemporaryDirectory() as temp:
   names=[{'name':'a'*238+f'{i:03d}'} for i in range(100)]
   result=self.catalog(Path(temp).resolve(),names)
   self.assertTrue(result['truncated']);self.assertIn('snapshot-name-limit',result['archiveScan']['reasons'])
   self.assertTrue(result.get('nextSnapshotCursor') is None or len(result['nextSnapshotCursor'])<=240)

 def test_linked_current_recovery_is_an_invalid_row_not_a_failed_catalog(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();folder=root/'recoveries'/m.CURRENT_RECOVERY;folder.parent.mkdir();outside=root/'detached';outside.mkdir();folder.symlink_to(outside,target_is_directory=True)
   try:result=self.catalog(root,real_verify=True)
   except ValueError as error:self.fail('Linked recovery escaped row-level validation: '+str(error))
   row=next(row for row in result['snapshots'] if row['name']==m.CURRENT_RECOVERY);self.assertEqual(row['bundleState'],'invalid')

 def test_one_archive_continues_after_image_budget_without_losing_files(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();archive=root/'archived-validation';folder=archive/'one-large-archive';folder.mkdir(parents=True)
   for i in range(205):(folder/f'image-{i:03d}.qcow2').write_bytes(b'image')
   after=None;seen=[];cursors=set()
   for _ in range(8):
    result=self.catalog(root,after=after);seen.extend(row['id'] for row in result['images']);self.assertFalse(result['truncated']);after=result['nextCursor']
    if after is None:break
    self.assertNotIn(after,cursors);cursors.add(after)
   self.assertEqual(len(seen),205);self.assertEqual(len(set(seen)),205);self.assertEqual(len(cursors),2)

 def test_one_archive_continues_after_directory_budget(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();archive=root/'archived-validation';folder=archive/'one-large-archive'
   for group in ['a','b']:
    for i in range(300):(folder/group/f'dir-{i:03d}').mkdir(parents=True)
    (folder/group/'zz-disk.qcow2').write_bytes(b'image')
   first=self.catalog(root);self.assertTrue(first['nextCursor'],'An unfinished archive needs an internal cursor');self.assertFalse(first['truncated'])
   second=self.catalog(root,after=first['nextCursor']);self.assertIsNone(second['nextCursor']);self.assertFalse(second['truncated'])
   self.assertEqual({row['id'] for page in [first,second] for row in page['images']},{'one-large-archive/a/zz-disk.qcow2','one-large-archive/b/zz-disk.qcow2'})

 def test_resume_cannot_traverse_a_replaced_archive_link(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();folder=root/'archived-validation/one-large-archive';folder.mkdir(parents=True)
   for i in range(100):(folder/f'image-{i:03d}.qcow2').write_bytes(b'image')
   first=self.catalog(root);self.assertTrue(first['nextCursor']);folder.rename(folder.with_name('detached'))
   outside=root/'outside';outside.mkdir();(outside/'private.qcow2').write_bytes(b'private');folder.symlink_to(outside,target_is_directory=True)
   result=self.catalog(root,after=first['nextCursor']);self.assertNotIn('private.qcow2',json.dumps(result))

 def test_time_budget_within_one_archive_retains_an_internal_resume_position(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();folder=root/'archived-validation/large';folder.mkdir(parents=True)
   for name in ['a','b']:
    (folder/name).mkdir();(folder/name/'disk.qcow2').write_bytes(b'image')
   with patch.object(m.time,'monotonic',side_effect=[0,1,3]):first=self.catalog(root)
   self.assertTrue(first['nextCursor']);self.assertIn('time-limit',first['archiveScan']['continuationReasons']);self.assertFalse(first['truncated'])
   second=self.catalog(root,after=first['nextCursor']);self.assertIsNone(second['nextCursor'])
   rows=[row['id'] for page in [first,second] for row in page['images']];self.assertEqual(len(rows),2);self.assertEqual(len(set(rows)),2)

 def test_internal_cursor_frames_are_bounded_public_descendants(self):
  import base64
  with tempfile.TemporaryDirectory() as temp:
   for payload in [['a',[['../outside','']]],['a',[['a','b'],['a/c','']]],['a',[['a','token-name']]],['a',[]],['a',[['a','b']]*6]]:
    raw=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    with self.subTest(payload=payload),self.assertRaises(ValueError):self.catalog(Path(temp).resolve(),after='v1:'+raw)
 def test_undisplayable_snapshot_names_are_reported_as_incomplete(self):
  for name in ['x'*300,'secret-snapshot','folder/snapshot']:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
    value=self.catalog(Path(temp).resolve(),snapshots=[{'name':name}])
    self.assertIn('snapshot-name-limit',value['archiveScan']['reasons']);self.assertTrue(value['truncated'])
 def test_image_only_read_does_not_query_or_verify_snapshots(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve();disk=root/'vm/Data/ubuntu.qcow2';disk.parent.mkdir(parents=True);disk.write_bytes(b'synthetic')
   with patch.object(m,'ROOT',root),patch.object(m,'VM',disk.parent.parent),patch.object(m,'validate'),patch.object(m,'image_command') as image,patch.object(m,'verify_recovery_bundle') as verify:
    value=m.recovery_catalog(part='images')
   image.assert_not_called();verify.assert_not_called();self.assertEqual(value['part'],'images');self.assertNotIn('snapshots',value)
 def test_snapshot_only_read_does_not_scan_archives_or_query_disk_space(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve()
   with patch.object(m,'ROOT',root),patch.object(m,'validate'),patch.object(m,'image_command',return_value=MagicMock(stdout='{"snapshots":[]}')),patch.object(m,'verify_recovery_bundle',side_effect=ValueError('synthetic')),patch.object(m,'archive_directory') as archive,patch.object(m.shutil,'disk_usage') as space:
    value=m.recovery_catalog(part='snapshots')
   archive.assert_not_called();space.assert_not_called();self.assertEqual(value['part'],'snapshots');self.assertNotIn('images',value)
 def test_selected_read_rejects_unrelated_cursors_and_unknown_parts(self):
  with patch.object(m,'validate'):
   for options in [{'part':'other'},{'part':'images','snapshot_after':'snap-a'},{'part':'snapshots','after':'archive-a'}]:
    with self.subTest(options=options),self.assertRaises(ValueError):m.recovery_catalog(**options)
if __name__=='__main__':unittest.main()
