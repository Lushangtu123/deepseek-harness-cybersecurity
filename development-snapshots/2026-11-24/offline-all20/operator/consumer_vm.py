'''Bounded offline full20 Linux VM admission controller. No target launcher.'''
from contextlib import contextmanager
import base64
import binascii
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import types
from pathlib import Path, PurePosixPath

CAP = 64 * 1024 ** 2
STOP_RESERVE = 4 * 1024 ** 2
FLOOR = 512 * 1024 ** 2
LOG_LIMIT = 1024 ** 2
FILE_LIMIT = 8 * 1024 ** 2
GUEST = Path('/home/purge/workspace/harness-new-script-acceptance-20261113/stdlib-cli-all20-fixture-lifecycle-20261124-r1')
BASELINE_SHA = 'fdeb973492f251cba0a9a7aaa0ee702afb76ba8c6b4768d057c6320b43880eb0'
FINAL_CASE_ID = 'public-compile-known-failure-is-diagnostic-3'
CONSUMER_CASE_IDS = (
    'settlement-parent-and-damaged-child-refused',
    'settlement-linked-child-unavailable-variants',
    'settlement-complete-scope-releases',
    'settlement-semantic-unknown-with-confirmed-cleanup-can-settle',
    'settlement-recompute-after-child-change',
    'recovery-settlement-refuses-stale-parent-success',
    'new-reservation-blocked-by-damaged-preparation',
    'new-reservation-blocked-by-unknown-plans-directory',
    'new-reservation-empty-directory-and-separate-batch',
    'compile-and-bind-preparation-blocked-before-writes',
    'query-status-available-with-damaged-batch',
    'public-compile-known-failure-is-diagnostic-3',
)
OPERATOR_FILES = (
    'operator/bounded.py',
    'operator/archive_helpers.py',
    'operator/linux_admission.py',
    'operator/consumer_vm.py',
    'operator/full20_batch.py',
    'operator/suite-plan.json',
    'operator/collect_independent.py',
    'operator/transfer.py',
    'operator/status_guest.py',
    'operator/blocked-bin/docker',
    'operator/blocked-bin/bpftrace',
)
CONTROLLED_EXECUTABLES = (
    'candidate/checks/shims/docker',
    'candidate/checks/shims/bpftrace',
    'operator/blocked-bin/docker',
    'operator/blocked-bin/bpftrace',
)
SANDBOX_RE = re.compile('checks/tmp/closure-public-compile-[0-9a-f]{8}')
PREFLIGHT_RE = re.compile('[0-9a-f]{32}')
HEX64_RE = re.compile('[a-f0-9]{64}')
EXTRA_FILES = {
 'checks/independent/independent-association.py': 'bdd413211dc82b96fc417d9470a66c04d36e4645e4693da9d46b43e46d5317fa',
 'checks/independent/independent-baseline-scripts/independent-direct-child-check.py': 'fd42b2e908ad7f83a2467731465188e3ba98e0cedb247d48f9945e21eda62b72',
 'checks/independent/independent-baseline-scripts/independent-directory-check.py': 'deb4e3b4133096e95cc770a34db5a7484a47c45e34e95ff2d273bed378f674a4',
 'checks/independent/independent-baseline-scripts/review-followup-checks.py': '48c268609922f2aa331ef0fe071a5e09b1eda99af08d555d1b26930999420646',
 'checks/independent/independent-component.py': '596333233046287665d6dbaf4fc5527123613933ab1ba98ac6c543bacb2140b5',
 'checks/independent/independent-consumers.py': '0df55bccd2457964e17735715a51f74db7a2608c2975dc0dfffd427faad2b47b',
 'checks/independent/independent-public-consumer.py': '45b20b2b9103babc3c1dd54fb237889700ae5910f181b4f20c7e16402c734d47',
 'checks/independent/independent-public-main.py': '1bc69e1a01815b364d0f863d108ab254a8b0ff6cc99bc85c6c8e38ec390ce923',
 'checks/independent/independent-recovery-refusal.py': '1ec741e8501ec2f927947cc594408243a9cf92dec5908dd0ca088bc6f8faf25a',
 'checks/independent/independent-recovery.py': 'e48968422f261b119cf6f9dc0743964f794ebe151317a27bd6a04add89bfbcf1',
 'checks/independent/independent-scope.py': '94716aa9c6db8e448bbdd2068d2020b63b78f09f32a60a744e334dfaf21b3ba7',
 'checks/independent/independent-settlement-scope.py': '74a44586f93f41373b636c32d7356fa34f5a56c6c859c2d3a3c34f5985f33e52',
 'checks/independent/independent-source.py': 'ac0aafbeb4fea78ab30eba092cbf39082e97fb9b5848195c2ad2db40d0a7a139',
 'checks/independent/independent-validation.py': '2a95df4396aa72e5c6d5dc98ee4e32de8666b288572ede8414077e7ed5cd438d',
 'references/stdlib-cli-record-validation/ASSOCIATION-RECOVERY-CONTRACT.md': 'd2cfe0375d73f4bb661bebc82e1ad4a76648405d0da59622f9a87f047e3df131',
 'references/stdlib-cli-record-validation/ASSOCIATION-RECOVERY-SUPPORT.md': '151d76f757bb99b6b815aab6336fee0a6c3b122af8a6a7151a8fe8b5641b1a51',
 'references/stdlib-cli-record-validation/BUFFER-PREFLIGHT-CONTRACT.md': '54b217be5675d197ddcecc945a9463769f24cfabce8c1061827da90c49676e7b',
 'references/stdlib-cli-record-validation/BUFFER-V2-CONTRACT.md': '56fdfb4cb327ceb5b42e3da08212ad29ba64cfd919845afa33662e3abd95da2b',
 'references/stdlib-cli-record-validation/DIAGNOSTICS-CONTRACT.md': '0e30a22c889b87cd138a33d58d977a17816cf12481e657cf676d5113fcc8447f',
 'references/stdlib-cli-record-validation/END-LF-CONTRACT.md': 'de0c01c8285ee383f7b44f8403eb299dde4cae7f52dfb0f66af1547d9c1d091e',
 'references/stdlib-cli-record-validation/FORMAL-ADMISSION-CONTRACT.md': 'e37f2975af9ffe646ce5e45413d9248021250e995c2f52498e675f23301d7695',
 'references/stdlib-cli-record-validation/FORMAL-ADMISSION-SUPPORT.md': 'b956fce3baef7b17377c1fa65b9654c72b8ae64653a37d6d2a3ddf3e30b4b4f6',
 'references/stdlib-cli-record-validation/RECORD-VALIDATION-CONTRACT.md': 'e02cd5bd1051e69d69095e7301a5c345507d917469c15b01bbaf72aba7edf100',
 'references/stdlib-cli-record-validation/RECORD-VALIDATION-SUPPORT.md': '4d41fbad3daaa36331ee5b1840f50861f95258db8342ce728cfdbe5272ddd37e',
 'references/stdlib-cli-record-validation/RECOVERY-CLOSE-CONTRACT.md': 'f3f2bdbfd9b492b1db3f9c5e63819ee6bfe069db386cb4c19d70bd8ae1f9e4af',
 'references/stdlib-cli-record-validation/RECOVERY-CLOSE-SUPPORT.md': 'd46b92292556783205d764dd3fb8eb29a77d910cb961f66088acb33e01963851',
 'references/stdlib-cli-record-validation/REPAIR-CONTRACT.md': '0f9c03fbaec4d5a410096e148d1a2e36df39b02b15f0be7e329ddf7a866a9956',
 'references/stdlib-cli-record-validation/UNIFIED-RECOVERY-CONTRACT.md': '88397be316b03706489aa147c719fcbd5b58653d7080fde49b5e19a06c1c645e',
 'references/stdlib-cli-record-validation/UNIFIED-RECOVERY-SUPPORT.md': '8cf33a020a4e1e6323a4ea97c1d8de2882681c0df18d46187d24338f443e1ed3',
 'references/stdlib-cli-record-validation/checks/capture_suite.py': 'bd5df92f48207bb77464d7831f1551f55cbfb7e57b273876d5a03628b74ac705',
 'references/stdlib-cli-record-validation/checks/checks_repro_support.py': 'd8765eeee62fd6cf160398cdd005bd55473049290aa3819b18f1d70b1300965a',
 'references/stdlib-cli-record-validation/checks/compile_check.py': '9e7e07ba79de07e16be6d857ca745f79aad19dc5b94924c4dac6bb8a46a1bf4a',
 'references/stdlib-cli-record-validation/checks/evidence_capture.py': 'ff47efbf043475c6c468e497fa9b6fe919b3268c55a754ab521c3e79a65fc632',
 'references/stdlib-cli-record-validation/checks/formal_admission/formal_support.py': '1643964024bfa3d140f0b3560306d54858f8b194c51efdb46ffb14ed267204cc',
 'references/stdlib-cli-record-validation/checks/formal_admission/make_evidence_index.py': '5a92645714f0e2221454bc0b525adbe2c7b752766775e94716a2ffe4f73d877c',
 'references/stdlib-cli-record-validation/checks/formal_admission/red_checks.py': 'df23cea3adecf930abb94b801e84b56c40cf0a2b14d5cd754ef0381210206e6c',
 'references/stdlib-cli-record-validation/checks/formal_admission/run_checks.py': '8fa49cb71c6cb84849b9c5da6384dc5c606ffe78bc2c9c264628cb86774e2e89',
 'references/stdlib-cli-record-validation/checks/make_association_evidence_index.py': '330b69edc2fbbd9df98174e1d9325f4f9707ba092d13013b54b5c6375ffb6c23',
 'references/stdlib-cli-record-validation/checks/make_end_lf_evidence_index.py': 'c5fb172c4f8c7d78923b4926a1aabb893750917bc651469c21e38af4d600bb48',
 'references/stdlib-cli-record-validation/checks/make_end_lf_manifest.py': '56bb25113b558050c424723365be9299df81aac3988742469bda9e6e81eedee2',
 'references/stdlib-cli-record-validation/checks/make_evidence_index.py': 'c458d1a0c902c98363b7b5bd8c93f2d843af37f2dc9f0349361c11e5e5576347',
 'references/stdlib-cli-record-validation/checks/make_manifest.py': 'e88297b36ca6211458cbaa1b09acbda6c5bd37d4e05268c9f4c7e003674cbbdb',
 'references/stdlib-cli-record-validation/checks/make_record_validation_evidence_index.py': '398daba09ee5d9363d83caff73d2b67db6575a66b73ee6da7b46ea759818b457',
 'references/stdlib-cli-record-validation/checks/make_recovery_close_evidence_index.py': '8158a8a701c0fee50fd5f71b0a4e6d83bfcdb1e56430946650f7d43698f709f5',
 'references/stdlib-cli-record-validation/checks/make_source_manifest.py': 'afc89c6feaa85b38b2da0eaacda402436a29ab99627b5c91791c7e5794389cca',
 'references/stdlib-cli-record-validation/checks/regression_lib.py': 'e7ae3fc22b532cbe78bc96cd82c14eeb6dc99e418360bdbe7318bc16a71c6613',
 'references/stdlib-cli-record-validation/checks/repro_recovery.py': '5946a832f4235301fc47404339b0bb55668d1cbd890e952384178ca5ae1826c0',
 'references/stdlib-cli-record-validation/checks/rev8_support.py': '44634a515b05bd4659c6b8b366c34a668d28a9bff0406d83cb03110d9521e133',
 'references/stdlib-cli-record-validation/checks/run_association_recovery_checks.py': 'be890d0268cd4e1fd171a6ba0805517038b6776e3147836f9c82fed52cfa42fd',
 'references/stdlib-cli-record-validation/checks/run_buffer_preflight_checks.py': 'd6d177bf6d10bb6988513b35c85297116efef02090585a0bf063e3f36ae4dd69',
 'references/stdlib-cli-record-validation/checks/run_buffer_v2_red.py': '620fcc3f0dae43c71f0130f6cdb7ce8d43e462667036ef2d979f5f4ce99bf26b',
 'references/stdlib-cli-record-validation/checks/run_diagnostics_checks.py': '1232e2cdea3360f6ea33d794bbf4e7c79d96d9101646349f0389e91c77a5d755',
 'references/stdlib-cli-record-validation/checks/run_end_lf_checks.py': 'e249cd7cbeec989a49039c5b5ccd2c6127db2c7edade70e0928564fc16a63b60',
 'references/stdlib-cli-record-validation/checks/run_end_lf_evidence.py': '836c670cb37c0654e21ab0da98ce3872a78abfb67deaea460283a5507c114e49',
 'references/stdlib-cli-record-validation/checks/run_evidence.py': '71edd9896f6b3ac9e544df943821d679a20b362cff2c71344a150de4e58c05be',
 'references/stdlib-cli-record-validation/checks/run_formal_admission_checks.py': '06e5b5b1e248fd2b8fc279a8e6821627854bc91694aeda95c4e60e3c15089cd6',
 'references/stdlib-cli-record-validation/checks/run_record_validation_checks.py': '70afad439db7db4effeab5f85f4fd8808ebc7479be7e3558e0a1b377495147d6',
 'references/stdlib-cli-record-validation/checks/run_recovery_close_checks.py': 'f19b07fa5f29c71891381ae100d5939f7ac8fbb747fd0d8c185a2f7768b64913',
 'references/stdlib-cli-record-validation/checks/run_regressions.py': '90759283e2f56a9aed8fea0c0f0c26cd5de74423c35b0b0ff6e04fad2dcf9c2d',
 'references/stdlib-cli-record-validation/checks/run_repair_checks.py': '37666940d934e9a82126fdaa855c8975478f0c0784aec9b511348cada541c3ae',
 'references/stdlib-cli-record-validation/checks/run_rev6_checks.py': '3f193e9a0852be55429e95e87d88eb80828a3344aac43c05ef6563bacbeb6c6b',
 'references/stdlib-cli-record-validation/checks/run_rev7_checks.py': 'a1c5a2b53913d6a2b935c0b31091aa3fb44795335133efb5dcb4201b2f50417e',
 'references/stdlib-cli-record-validation/checks/run_rev8_checks.py': 'd950abef29bd9c89e661d4621c568c2a28d9a5fca7fbf838142c83404b28a010',
 'references/stdlib-cli-record-validation/checks/run_unified_recovery_checks.py': 'd1ab033418c6d76ca39ac7ae12e9bde8d46b9ba42e21327dcc7f7ac4a69e24fc',
 'references/stdlib-cli-record-validation/checks/shim_common.py': '49bf7d41b3ae0e1a67cd13b0d80153c72133c1850b42ec7d3671fbf8c0fe81d6',
 'references/stdlib-cli-record-validation/checks/shims/bpftrace': '6104b989cabdd9675d124c5ce48ad2b36e5462f89a291ed298fea635f0c3cf79',
 'references/stdlib-cli-record-validation/checks/shims/docker': '2bc481cb094eaba100e8424c205adb5ebae9ae2c9c454571f02abde2dc0d7725',
 'references/stdlib-cli-record-validation/checks/static_check.py': 'ca5d026990ab40af2c3989192feb103965cb70f3c74fa743f26430fc5fe9dfe1',
 'references/stdlib-cli-record-validation/checks/verify_baseline.py': 'dac9015f3bb258c6ea1df1ca718ca274fedc7e6b3fda4cd1a6e234dc16331a79',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV3.md': '2b4b03d1cafb1ff840d093cb7e181979a8b24eb161cbb365be916bcb1b047562',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV4.md': '84c37ebeb36ddb917fa44062cf5fe2e69e8f53f4c0294c653622a7c29c3cc9b8',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV5.md': '855e77ce4b9e1e9e1b8df5cb4e1aec9d1f5052ef234c93c3f4cc08b671589fb0',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV6.md': '648a03f1a2537bd2021165bd5bc924b7b0837d1b99575ed14c281e200cf687b8',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV7.md': '6c30b0a58d7c3ace3c7d1ee132ea567cba9f6975c00b95a58a8d22af0511a808',
 'references/stdlib-cli-record-validation/docs/CONTRACTS-REV8.md': '246d3fef20ffbf436d48b2a149e818170475be593e64bf5c25cf230bd432730b',
 'references/stdlib-cli-record-validation/docs/EXPERIMENT-PROTOCOL.md': '9e823bae7640ccf6659858abcfe986c3c4001cd30cf2e951526fc729460870f5',
 'references/stdlib-cli-record-validation/experiment-plan.json': 'e7079c42e4b24ddd69003893a1de8ecae9be55a630a75e7fa619968ada48da4d',
 'references/stdlib-cli-record-validation/fixtures/echo/sce_echo_sink.py': '83b5e9cde7f5203571efb5cf8d5b24034d8816036140a1d23306c063ceb617b2',
 'references/stdlib-cli-record-validation/fixtures/safe-quoting/sce_quoted_sink.py': 'f03a1f1d698923b04e4b0a5a8709a8958c1cdc221d14c5969cde04c430afb47c',
 'references/stdlib-cli-record-validation/fixtures/structure-controlled/sce_raw_sink.py': 'fb799416a87ce896e747acd66618a98e3e349c6800a58843b196560399ca2dba',
 'references/stdlib-cli-record-validation/fixtures/wrong-function/sce_two_sites.py': '260f904b0f72b002fbd9b6be57df9ee18e4b65c36e10cefd4723fb28de4bac6b',
 'references/stdlib-cli-record-validation/protocol-manifest.json': 'fdeb973492f251cba0a9a7aaa0ee702afb76ba8c6b4768d057c6320b43880eb0',
 'references/stdlib-cli-record-validation/tools/buffer_protocol.py': '3ca271877d4123daa86cba81d3ee195af0a697ae05bc2b3cba3731f3e874de63',
 'references/stdlib-cli-record-validation/tools/buffer_protocol_v2.py': '99254927899fc52bce161d701d4f20872b92a9074eedf93fce30f91e3e4ec678',
 'references/stdlib-cli-record-validation/tools/collect_observer.py': 'bed70d59023a552ba8ae9717c52ff820bb583d08ce680831acc8376b7966bce3',
 'references/stdlib-cli-record-validation/tools/experiment_compile.py': '216c5bb7a006bfb6fd3b6b22d61d3a342e5ad5146f513baaf6d961130cd92219',
 'references/stdlib-cli-record-validation/tools/experiment_runner.py': '0f4e3e78e16ab5f07f6ab9833e9fdeb1164e02ec15222a9aa5f24899157b957a',
 'references/stdlib-cli-record-validation/tools/judge.py': 'cd54454d504c8f41c401b81dbce96c93b8956a5b8bb16aef55686c0389e24d20',
 'references/stdlib-cli-record-validation/tools/layout_probe.py': '0c8d5ce1bee2d8056788dfe77c1d24594fb0759da33152c6d065a83d681a8653',
 'references/stdlib-cli-record-validation/tools/observation_pure.py': '073653ba6ef7333c1365f49aed8fa79796274a61f93829d0fc1564714ebadec1',
 'references/stdlib-cli-record-validation/tools/observer-profile.lock.json': 'be4fac9697219f047d9d631006b10f3f0791ea0acec51ddc95b623412af295e8',
 'references/stdlib-cli-record-validation/tools/observer_render.py': '0fe71169852323eb990483cca55bf5d0fb06def86943895c81980b6471823a5b',
 'references/stdlib-cli-record-validation/tools/observer_template.bt': 'd21dc300b887c713fc07015c077a2dbf67c9f35f054f177e115fbbaae5a290f4',
 'references/stdlib-cli-record-validation/tools/observer_template_buffer.bt': '640255cab64d91dea08e27e793d592d55a250986b1eda5ce74587389e0c866d5',
 'references/stdlib-cli-record-validation/tools/observer_template_buffer_v2.bt': '99d0c902172a94c4c54613e7ac64a6a8aa2f53f3137cfadbff417f03232d207d',
 'references/stdlib-cli-record-validation/tools/preflight_diagnostics.py': '9281a9e2fdc4065494c01da7328db24f568af0b0de12e674893fc09ef291325c',
 'references/stdlib-cli-record-validation/tools/preflight_selfcheck.py': '53e142e3ca739ae19a9b9e856b0ea9f26209e18d484ee065c54bb30708b38369',
 'references/stdlib-cli-record-validation/tools/preflight_verify.py': '3ecefc73c87e3a9110f1b9f76224f940ce3c578ff5eae27706d57ba9e5be0cd6',
 'references/stdlib-cli-record-validation/tools/resource_guard.py': '704b9ce6f6f7c12085555d87bda3148d9e3224ea6d0397b9e92161e50687c828',
 'references/stdlib-cli-record-validation/tools/structure.py': 'a2350ec74b5d9c4f1f9be90c5c935a09a05a1229d29da9044aa8308e133f26e3',
 'references/stdlib-cli-record-validation/tools/target_launcher.py': 'fd34c6e5e674cf524f6fcf01a92cfe1566317f3a76899ccde7834fc38dc8b9b3',
 'references/stdlib-cli-record-validation/tools/zero_target_preflight.py': '820f1620add1fd0644d19a1bc8b1fd7a370ad985eeb85c459747669865aa8145',
 'candidate/proof/FINAL-REVIEW.md': '5fd641d324160a85c61ca56759054379f8302d375a8e992e77a5d7f4f26c715b',
 'candidate/proof/LIVE-RESULTS-FROZEN.md': 'c43a3f298cc5efe195691ba02301eb04e19a4650f01c68059a52a1722ae19c39',
 'candidate/proof/container-pid.json': '446da01b619f398f561fe31dc8d7e841885ad838fd9b786a6c8168cc30e9bd75',
 'candidate/proof/observer.raw': '5e61c6b689cf4e31905fb6e2863648a0c1d0376446d8dc237189b9cc8627806b',
 'candidate/proof/preflight-config.json': '52a919ea795b0038dfee9617ff0049aeb85eaec633241289696df00007ad9797',
 'candidate/proof/review-verification.json': 'aacefe4301e7fd10000368e4183e0a7b7633fc0604d239f7eaf3b5c9c39faa78',
 'candidate/proof/trailing-blank-diagnosis.json': '15f97980e4783fc58620bd81bb8dd382adcbd7a24e5e2cce4cbac0ae9d560ece',
}

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()

def _valid_rel(name):
    if not isinstance(name, str):
        return False
    parsed = PurePosixPath(name)
    return (not parsed.is_absolute() and str(parsed) == name and bool(parsed.parts)
            and all(part not in ('.', '..') for part in name.split('/')))

def _decode_files(rows):
    require(isinstance(rows, dict), 'payload-files')
    files = {}
    total = 0
    for name, row in rows.items():
        require(_valid_rel(name), 'payload-path')
        require(isinstance(row, dict), 'payload-row')
        try:
            raw = base64.b64decode(row['bytes'], validate=True)
        except (KeyError, TypeError, binascii.Error):
            raise ValueError('payload-base64')
        total += len(raw)
        require(total <= FILE_LIMIT, 'payload-size')
        require(len(raw) <= FILE_LIMIT, 'payload-file-cap')
        require(sha_bytes(raw) == row.get('sha256'), 'payload-digest')
        files[name] = raw
    return files

def _read_json(path):
    with open(path, 'rb') as handle:
        return json.loads(handle.read())

def _write_json_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + chr(10)).encode('utf-8')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())

def _lstat_absent(path):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False

def _is_regular(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)

def _is_directory(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)

def _no_symlink_components(base, rel):
    current = Path(base)
    if not _is_directory(current):
        return False
    for part in PurePosixPath(rel).parts:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
    return True

def _load_module(name, raw, filename=None):
    module = types.ModuleType(name)
    module.__file__ = filename or ('<' + name + '>')
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module

def _load_path_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@contextmanager
def _prepend_syspath(path):
    old = list(sys.path)
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    try:
        yield
    finally:
        sys.path[:] = old

@contextmanager
def _minimal_environment():
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update({
        'PATH': str(GUEST / 'operator/blocked-bin') + ':/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONNOUSERSITE': '1',
        'TMPDIR': str(GUEST / 'checks'),
        'HARNESS_SAMPLING_LOCK': str(GUEST / '.sampling.lock'),
        'HARNESS_BLOCKLOG': str(GUEST / 'evidence/unexpected-resource-calls.log'),
    })
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)

def _validate_parent_chain():
    current = GUEST.parent
    home = Path('/home')
    while current != current.parent and current != home:
        try:
            info = os.lstat(current)
        except OSError as error:
            raise ValueError('guest-parent-unreadable:' + type(error).__name__)
        require(not stat.S_ISLNK(info.st_mode), 'guest-parent-symlink')
        require(stat.S_ISDIR(info.st_mode), 'guest-parent-not-directory')
        require(info.st_uid == 1000, 'guest-parent-owner')
        current = current.parent
    require(current == home or current == current.parent, 'guest-parent-chain')

def _validate_packet(packet):
    require(isinstance(packet, dict), 'packet-object')
    require(packet.get('guestRoot') == str(GUEST), 'guest-root-mismatch')
    require(packet.get('caseIds') == list(CONSUMER_CASE_IDS), 'case-ids')
    source_sha = packet.get('sourceManifestSha256')
    require(isinstance(source_sha, str) and HEX64_RE.fullmatch(source_sha), 'source-manifest-sha')
    files = _decode_files(packet.get('files'))
    require('candidate/protocol-manifest.json' in files, 'source-manifest-missing')
    raw_manifest = files['candidate/protocol-manifest.json']
    require(sha_bytes(raw_manifest) == source_sha, 'source-manifest-digest')
    binding = _load_module('operator_full20_batch_binding', files['operator/full20_batch.py'])
    require(hasattr(binding, 'validate_binding') and callable(binding.validate_binding), 'binding-callable')
    binding_plan = binding.validate_binding(raw_manifest, files['operator/suite-plan.json'], source_sha)
    require(isinstance(binding_plan, dict) and binding_plan.get('sourceManifestSha256') == source_sha, 'binding-source')
    manifest = json.loads(raw_manifest)
    require(isinstance(manifest, dict), 'source-manifest-object')
    source_files = manifest.get('files')
    require(isinstance(source_files, dict) and len(source_files) == 92, 'source-file-count')
    for name, digest in source_files.items():
        require(_valid_rel(name), 'source-file-path')
        require(isinstance(digest, str) and HEX64_RE.fullmatch(digest), 'source-file-digest')
        key = 'candidate/' + name
        require(key in files, 'source-file-missing')
        require(sha_bytes(files[key]) == digest, 'source-file-changed')
    require('candidate/baseline/protocol-manifest.json' in files, 'baseline-manifest-missing')
    raw_baseline = files['candidate/baseline/protocol-manifest.json']
    require(sha_bytes(raw_baseline) == BASELINE_SHA, 'baseline-manifest-digest')
    baseline = json.loads(raw_baseline)
    require(isinstance(baseline, dict), 'baseline-manifest-object')
    baseline_files = baseline.get('files')
    require(isinstance(baseline_files, dict) and len(baseline_files) == 87, 'baseline-file-count')
    for name, digest in baseline_files.items():
        require(_valid_rel(name), 'baseline-file-path')
        require(isinstance(digest, str) and HEX64_RE.fullmatch(digest), 'baseline-file-digest')
        key = 'candidate/baseline/' + name
        require(key in files, 'baseline-file-missing')
        require(sha_bytes(files[key]) == digest, 'baseline-file-changed')
    expected = set('candidate/' + name for name in source_files)
    expected.add('candidate/protocol-manifest.json')
    expected.update('candidate/baseline/' + name for name in baseline_files)
    expected.add('candidate/baseline/protocol-manifest.json')
    expected.update(OPERATOR_FILES)
    expected.update(EXTRA_FILES)
    require(set(files) == expected, 'payload-set')
    for name, digest in EXTRA_FILES.items():
        require(name in files, 'extra-file-missing')
        require(sha_bytes(files[name]) == digest, 'extra-file-changed')
    for name in ('operator/blocked-bin/docker', 'operator/blocked-bin/bpftrace'):
        raw = files[name]
        require(b'exit 97' in raw, 'blocked-bin-exit')
        require(b'resource-call' in raw or b'unexpected-resource-calls' in raw, 'blocked-bin-marker')
    return files, manifest, baseline, source_sha

def _stage_files(files, helpers):
    for name in CONTROLLED_EXECUTABLES:
        require(name in files, 'controlled-executable-missing')
    candidate_shims = [name for name in files if name.startswith('candidate/checks/shims/')]
    require(set(candidate_shims) == {'candidate/checks/shims/docker', 'candidate/checks/shims/bpftrace'}, 'candidate-shim-set')
    for name, raw in files.items():
        target = GUEST / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(helpers.usage(GUEST) + len(raw) <= CAP - STOP_RESERVE, 'staging-capacity-limit')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        require(_is_regular(target), 'staging-not-regular')
        require(sha_bytes(target.read_bytes()) == sha_bytes(raw), 'staging-readback')
        if name in CONTROLLED_EXECUTABLES:
            os.chmod(target, 0o700)

def _source_unchanged(files):
    for name, raw in files.items():
        target = GUEST / name
        if not _is_regular(target):
            return False
        try:
            if sha_bytes(target.read_bytes()) != sha_bytes(raw):
                return False
        except OSError:
            return False
    return True

def _unexpected_log_empty():
    path = GUEST / 'evidence/unexpected-resource-calls.log'
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False, 'missing'
    except OSError as error:
        return False, type(error).__name__
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False, 'not-regular'
    return info.st_size == 0, None

def _budget_ok(record, helpers):
    try:
        used = helpers.usage(GUEST)
        stats = os.statvfs(GUEST)
        free = stats.f_bavail * stats.f_frsize
    except Exception as error:
        return False, type(error).__name__
    ok = used <= CAP - STOP_RESERVE and free >= FLOOR
    if isinstance(record, dict):
        peak = record.get('peakTreeBytes')
        minimum = record.get('minFreeBytes')
        if isinstance(peak, int):
            ok = ok and peak <= CAP - STOP_RESERVE
        if isinstance(minimum, int):
            ok = ok and minimum >= FLOOR
    return ok, None

def _audit_containers(box):
    directory = box / 'state/containers'
    if _lstat_absent(directory):
        return True, {'count': 0}
    require(_is_directory(directory), 'containers-directory')
    try:
        names = sorted(os.listdir(directory))
    except OSError as error:
        raise ValueError('containers-list:' + type(error).__name__)
    for name in names:
        require(name.endswith('.json'), 'containers-entry')
        path = directory / name
        require(_is_regular(path), 'containers-file')
        record = _read_json(path)
        require(isinstance(record, dict) and record.get('removed') is True and record.get('status') == 'removed', 'unconfirmed-fake-container')
    return True, {'count': len(names)}

def _find_preflight_receipt(box):
    evidence_root = box / 'preflight/evidence'
    require(_is_directory(evidence_root), 'preflight-evidence-directory')
    try:
        names = sorted(os.listdir(evidence_root))
    except OSError as error:
        raise ValueError('preflight-evidence-list:' + type(error).__name__)
    for name in names:
        require(PREFLIGHT_RE.fullmatch(name) is not None, 'preflight-evidence-entry')
        require(_is_directory(evidence_root / name), 'preflight-evidence-not-directory')
    require(len(names) == 1, 'preflight-evidence-count')
    evidence = evidence_root / names[0]
    receipt = evidence / 'preflight-receipt.json'
    require(_is_regular(receipt), 'preflight-receipt')
    return receipt, evidence

def _cleanup_stage_confirmed(cleanup, box):
    if not isinstance(cleanup, dict):
        return False, None
    if cleanup.get('kind') != 'zero-target-preflight-cleanup':
        return False, None
    inner = cleanup.get('cleanup')
    if not isinstance(inner, dict) or inner.get('confirmed') is not True:
        return False, None
    stage = inner.get('stage')
    if not isinstance(stage, dict):
        return False, None
    if stage.get('removed') is not True or stage.get('lstatAfter') != 'absent':
        return False, None
    stage_path = stage.get('path')
    if not isinstance(stage_path, str) or not stage_path:
        return False, None
    path = Path(stage_path)
    if not path.is_absolute() or '..' in path.parts or path == box:
        return False, None
    try:
        path.relative_to(box)
    except ValueError:
        return False, None
    return _lstat_absent(path), path

def _audit_inner(result, files):
    details = {}
    errors = []
    try:
        require(isinstance(result, dict), 'result-object')
        retained = result.get('retainedSandboxes')
        require(isinstance(retained, list) and len(retained) == 1, 'retained-count')
        entry = retained[0]
        require(isinstance(entry, dict), 'retained-object')
        require(entry.get('caseId') == FINAL_CASE_ID, 'retained-case')
        rel = entry.get('relativePath')
        require(isinstance(rel, str) and SANDBOX_RE.fullmatch(rel) is not None, 'retained-path')
        base = GUEST / 'candidate'
        require(_no_symlink_components(base, rel), 'retained-symlink')
        box = base / rel
        require(_is_directory(box), 'retained-not-directory')
        receipt, evidence = _find_preflight_receipt(box)
        require(_is_regular(GUEST / 'candidate/tools/resource_guard.py'), 'guard-missing')
        require(_is_regular(GUEST / 'candidate/tools/preflight_verify.py'), 'verify-missing')
        guard = _load_module('resource_guard', files['candidate/tools/resource_guard.py'], str(GUEST / 'candidate/tools/resource_guard.py'))
        sys.modules['resource_guard'] = guard
        with _prepend_syspath(GUEST / 'candidate/tools'):
            verify = _load_module('preflight_verify', files['candidate/tools/preflight_verify.py'], str(GUEST / 'candidate/tools/preflight_verify.py'))
            bundle = verify.verify_preflight_evidence(
                root=box,
                receipt_path=receipt,
                license_path=box / 'codex-review/preflight-admission.json',
                review_path=box / 'codex-review/source-review-receipt.json',
                manifest_path=box / 'protocol-manifest.json',
                profile_path=box / 'tools/observer-profile.lock.json',
            )
        require(bundle is not None, 'verify-preflight-empty')
        if isinstance(bundle, dict):
            require(bundle.get('ok') is not False, 'verify-preflight-false')
            require(bundle.get('verified') is not False, 'verify-preflight-false')
        role_states = {}
        for role in ('client', 'observer'):
            path = evidence / ('process-' + role + '-identity.json')
            require(_is_regular(path), 'identity-file')
            record = _read_json(path)
            require(record.get('role') == role, 'identity-role')
            require(isinstance(record.get('preflightId'), str) and record.get('preflightId') == evidence.name, 'identity-id')
            spawn = guard.spawn_group_state(record)
            role_states[role] = spawn
            require(isinstance(spawn, dict) and spawn.get('state') == 'exited', 'identity-not-exited')
        cleanup_path = evidence / 'cleanup.json'
        require(_is_regular(cleanup_path), 'cleanup-file')
        cleanup = _read_json(cleanup_path)
        require(isinstance(cleanup, dict) and cleanup.get('preflightId') == evidence.name, 'cleanup-preflight-id')
        cleanup_ok, stage_path = _cleanup_stage_confirmed(cleanup, box)
        require(cleanup_ok and stage_path is not None, 'cleanup-stage')
        containers_ok, containers = _audit_containers(box)
        require(containers_ok, 'containers-active')
        details.update({
            'box': rel,
            'preflightEvidence': evidence.name,
            'receipt': str(receipt.relative_to(GUEST)),
            'stagePath': str(stage_path),
            'roleStates': role_states,
            'containers': containers,
        })
        return True, details, errors
    except Exception as error:
        row = {'reason': 'inner-audit', 'errorType': type(error).__name__, 'message': str(error)[:300]}
        errors.append(row)
        details['error'] = row
        return False, details, errors

def status():
    result = {'guestRoot': str(GUEST), 'rootState': 'absent'}
    try:
        info = os.lstat(GUEST)
    except FileNotFoundError:
        return result
    except OSError as error:
        result['rootState'] = 'unknown'
        result['error'] = type(error).__name__
        return result
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        result['rootState'] = 'not-directory'
        return result
    result['rootState'] = 'present'
    for name in ('attempt.json', 'final.json', 'stopped.json'):
        path = GUEST / name
        if _is_regular(path):
            try:
                result[name] = _read_json(path)
            except Exception as error:
                result[name] = {'error': type(error).__name__}
    process = GUEST / 'evidence/consumer-12/process.json'
    if _is_regular(process):
        try:
            result['process'] = _read_json(process)
        except Exception as error:
            result['process'] = {'error': type(error).__name__}
    return result

def main(packet):
    files = None
    helpers = None
    runtime = None
    root_created = False
    lock_fd = None
    sampling_fd = None
    errors = []
    try:
        files, manifest, baseline, source_sha = _validate_packet(packet)
        admission = _load_module('operator_linux_admission', files['operator/linux_admission.py'])
        require(hasattr(admission, 'check_runtime') and callable(admission.check_runtime), 'admission-callable')
        runtime = admission.check_runtime()
        require(isinstance(runtime, dict), 'admission-runtime')
        sys.modules['linux_admission'] = admission
        bounded = _load_module('operator_bounded', files['operator/bounded.py'])
        helpers = _load_module('operator_archive_helpers', files['operator/archive_helpers.py'])
        require(hasattr(bounded, 'run_one') and callable(bounded.run_one), 'bounded-run-one')
        require(hasattr(helpers, 'collect_artifacts') and callable(helpers.collect_artifacts), 'collect-artifacts')
        sys.modules['bounded'] = bounded
        sys.modules['archive_helpers'] = helpers
        _validate_parent_chain()
        require(_lstat_absent(GUEST), 'guest-root-exists')
        stats = os.statvfs(GUEST.parent)
        require(stats.f_bavail * stats.f_frsize >= FLOOR + CAP, 'fresh-capacity-not-ready')
        GUEST.mkdir(mode=0o700)
        root_created = True
        lock_fd = os.open(GUEST / '.batch.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sampling_fd = os.open(GUEST / '.sampling.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(sampling_fd)
        sampling_fd = None
        (GUEST / 'evidence').mkdir(mode=0o700)
        (GUEST / 'checks').mkdir(mode=0o700)
        log_fd = os.open(GUEST / 'evidence/unexpected-resource-calls.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(log_fd)
        attempt = {
            'kind': 'full20-linux-attempt',
            'state': 'staging',
            'guestRoot': str(GUEST),
            'sourceManifestSha256': source_sha,
            'caseIds': list(packet['caseIds']),
            'pid': runtime.get('pid'),
            'pgid': runtime.get('pgid'),
            'starttime': runtime.get('starttime'),
            'bootId': runtime.get('bootId'),
            'admission': runtime,
            'noAutomaticReplay': True,
            'actualVMApplicationWrites': True,
            'full20': True,
        }
        _write_json_new(GUEST / 'attempt.json', attempt)
        _stage_files(files, helpers)
        _write_json_new(GUEST / 'staging-verified.json', {
            'files': {name: sha_bytes(raw) for name, raw in sorted(files.items())},
            'logicalInputBytes': sum(len(raw) for raw in files.values()),
            'candidateFiles': 92,
            'baselineFiles': 87,
            'operatorFiles': len(OPERATOR_FILES),
            'extraFiles': len(EXTRA_FILES),
            'newScopeOnly': True,
            'full20': True,
        })
        require(_is_regular(GUEST / 'candidate/checks/evidence_capture.py'), 'capture-missing')
        require(_is_regular(GUEST / 'candidate/checks/finalize_closure.py'), 'closure-missing')
        require(_is_regular(GUEST / 'operator/full20_batch.py'), 'batch-missing')
        batch = _load_module('operator_full20_batch', files['operator/full20_batch.py'], str(GUEST / 'operator/full20_batch.py'))
        require(hasattr(batch, 'run_batch') and callable(batch.run_batch), 'batch-callable')
        batch_error = None
        try:
            with _minimal_environment():
                batch_result = batch.run_batch(GUEST, packet, files, bounded, helpers, _audit_inner)
        except BaseException as error:
            batch_error = {'type': type(error).__name__, 'message': str(error)[:700]}
            batch_result = {
                'kind': 'full20-linux-batch-result', 'full20': True, 'complete': False,
                'state': 'stopped', 'rows': [], 'captures': [], 'groups': [],
                'problem': batch_error, 'failedGroup': None, 'consumerAudit': None,
                'publication': None, 'allReturnedGroupsExited': False,
                'sourceUnchanged': False, 'resourceQuiescent': False,
                'actualProcessQuiescence': {'state': 'unknown'},
            }
        if not isinstance(batch_result, dict):
            batch_error = {'type': 'ValueError', 'message': 'batch-result-shape'}
            batch_result = {'complete': False, 'rows': [], 'captures': [], 'groups': [], 'problem': batch_error, 'consumerAudit': None, 'publication': None, 'allReturnedGroupsExited': False, 'sourceUnchanged': False, 'resourceQuiescent': False, 'actualProcessQuiescence': {'state': 'unknown'}}
        rows = batch_result.get('rows') if isinstance(batch_result.get('rows'), list) else []
        attempted_suites = batch_result.get('attemptedSuites') if isinstance(batch_result.get('attemptedSuites'), list) else []
        consumer_audit = batch_result.get('consumerAudit') if isinstance(batch_result.get('consumerAudit'), dict) else {'ok': False}
        inner_ok = consumer_audit.get('ok') is True
        returned_exited = batch_result.get('allReturnedGroupsExited') is True
        source_ok = bool(batch_result.get('sourceUnchanged') is True and _source_unchanged(files))
        budget_ok, budget_error = _budget_ok(None, helpers)
        used = batch_result.get('usedBytes')
        if type(used) is int:
            budget_ok = budget_ok and used <= CAP - STOP_RESERVE
        if budget_error:
            errors.append({'reason': 'budget', 'errorType': budget_error})
        log_empty, log_error = _unexpected_log_empty()
        if log_error:
            errors.append({'reason': 'resource-call-log', 'errorType': log_error})
        quiescent = False
        resources_predicate = getattr(batch, 'resources_confirmed', None)
        if not callable(resources_predicate):
            errors.append({'reason': 'resource-predicate-missing'})
        else:
            try:
                quiescent = resources_predicate(batch_result) is True
            except BaseException as error:
                quiescent = False
                errors.append({'reason': 'resource-predicate', 'errorType': type(error).__name__, 'message': str(error)[:300]})
            if not quiescent:
                errors.append({'reason': 'resource-quiescence-unconfirmed'})
        if batch_error:
            errors.append({'reason': 'batch', 'errorType': batch_error.get('type'), 'message': batch_error.get('message')})
        if isinstance(batch_result.get('problem'), dict):
            errors.append({'reason': 'batch-problem', **batch_result['problem']})
        for row in consumer_audit.get('errors', []) if isinstance(consumer_audit.get('errors'), list) else []:
            errors.append({'reason': 'consumer-audit', 'detail': row})
        complete = bool(batch_result.get('complete') is True and inner_ok and returned_exited and source_ok and budget_ok and log_empty and quiescent and not batch_error)
        outer = {}
        if rows and isinstance(rows[0], dict):
            outer = {key: rows[0].get(key) for key in ('passed', 'problem', 'returncode', 'cleanupConfirmed', 'immutableFilesUnchanged', 'peakTreeBytes', 'minFreeBytes', 'resultPath', 'outputBytes')}
        final = {
            'kind': 'full20-linux-controller-final',
            'full20': True,
            'expectedGroups': 20,
            'batchState': batch_result.get('state'),
            'suitePassed': batch_result.get('complete') is True,
            'targetChecksAllTrue': inner_ok,
            'outerGroupExited': returned_exited,
            'innerCleanupConfirmed': inner_ok,
            'sourceUnchanged': source_ok,
            'budgetOk': budget_ok,
            'unexpectedResourceCallLogEmpty': log_empty,
            'actualProcessQuiescent': quiescent,
            'complete': complete,
            'caseIds': list(packet['caseIds']),
            'selectedCaseId': FINAL_CASE_ID,
            'sourceManifestSha256': source_sha,
            'rows': rows,
            'attemptedSuites': attempted_suites,
            'failedGroup': batch_result.get('failedGroup'),
            'captures': batch_result.get('captures'),
            'groups': batch_result.get('groups'),
            'publication': batch_result.get('publication'),
            'consumerAudit': consumer_audit,
            'actualProcessQuiescence': batch_result.get('actualProcessQuiescence'),
            'outer': outer,
            'inner': consumer_audit.get('details') if isinstance(consumer_audit.get('details'), dict) else {},
            'errors': errors,
            'actualVMApplicationWrites': True,
            'noAutomaticReplay': True,
            'noHistoricalDirectoryCleanup': True,
            'formalTargets': '0/16',
            'r3': 'blocked',
        }
        _write_json_new(GUEST / 'final.json', final)
        collected = None
        collection_issues = []
        if quiescent and log_empty and source_ok and budget_ok:
            try:
                collected = helpers.collect_artifacts(GUEST)
            except Exception as error:
                collection_issues.append({'reason': 'collect', 'errorType': type(error).__name__, 'message': str(error)[:300]})
        else:
            collection_issues.append({'reason': 'resource-quiescence-unconfirmed'})
        archive_complete = bool(complete and collected and collected.get('archiveComplete') is True)
        diagnostic_archive_complete = bool((not complete) and collected and collected.get('archiveComplete') is True)
        return {
            'kind': 'bounded-VM-full20-linux-delivery',
            'full20': True,
            'guestRoot': str(GUEST),
            'result': final,
            'controllerFinalWritten': True,
            'archiveComplete': archive_complete,
            'diagnosticArchiveComplete': diagnostic_archive_complete,
            'archiveBytesPayload': collected.get('archiveBytesPayload') if collected else b'',
            'archiveSha256': collected.get('archiveSha256') if collected else sha_bytes(b''),
            'members': collected.get('members') if collected else {},
            'linksRecordedNotFollowed': collected.get('linksRecordedNotFollowed') if collected else [],
            'collectionIssues': collection_issues + errors,
            'VMTreeBytes': collected.get('VMTreeBytes') if collected else None,
            'originalAttemptRetained': True,
            'noHistoricalDirectoryCleanup': True,
            'formalTargets': '0/16',
            'r3': 'blocked',
        }
    except BaseException as error:
        if root_created:
            try:
                if _lstat_absent(GUEST / 'stopped.json'):
                    _write_json_new(GUEST / 'stopped.json', {
                        'state': 'incomplete',
                        'errorType': type(error).__name__,
                        'reason': str(error)[:300],
                        'pid': os.getpid(),
                        'originalAttemptRetained': True,
                        'noReplay': True,
                        'uncertainty': 'post-staging',
                        'full20': True,
                    })
            except Exception:
                pass
        return {
            'kind': 'bounded-VM-full20-linux-delivery',
            'full20': True,
            'guestRoot': str(GUEST),
            'result': {'complete': False, 'state': 'pre-staging-failure' if not root_created else 'stopped-or-uncertain'},
            'controllerFinalWritten': False,
            'archiveComplete': False,
            'diagnosticArchiveComplete': False,
            'archiveBytesPayload': b'',
            'archiveSha256': sha_bytes(b''),
            'members': {},
            'linksRecordedNotFollowed': [],
            'collectionIssues': [{'reason': 'controller-error', 'errorType': type(error).__name__, 'message': str(error)[:300]}],
            'originalAttemptRetained': True,
            'formalTargets': '0/16',
            'r3': 'blocked',
        }
    finally:
        if sampling_fd is not None:
            try:
                fcntl.flock(sampling_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(sampling_fd)
            except OSError:
                pass
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_fd)
            except OSError:
                pass
