# Synthetic scanner input only; never execute this file.
import ast, os, pickle, subprocess, tempfile, requests, yaml, jwt
from subprocess import run as run_process
from yaml import SafeLoader

def examples(value, cursor):
    # ruleid: harness.python.eval
    eval(value)
    # ok: harness.python.eval
    ast.literal_eval(value)
    # ok: harness.python.eval
    eval("1 + 2")
    # ruleid: harness.python.pickle
    pickle.loads(value)
    # ruleid: harness.python.pickle
    pickle.load(value)
    # ok: harness.python.pickle
    json.loads(value)
    # ruleid: harness.python.shell
    subprocess.run(value, shell=True)
    # ruleid: harness.python.shell
    run_process(value, shell=True, check=True)
    # ok: harness.python.shell
    subprocess.run(["printf", value], shell=False)
    # ok: harness.python.shell
    custom_callback(value, shell=True)
    # ruleid: harness.python.yaml-load
    yaml.load(value)
    # ruleid: harness.python.yaml-load
    yaml.load(value, Loader=yaml.UnsafeLoader)
    # ok: harness.python.yaml-load
    yaml.load(value, Loader=yaml.SafeLoader)
    # ok: harness.python.yaml-load
    yaml.load(value, Loader=SafeLoader)
    # ok: harness.python.yaml-load
    yaml.safe_load(value)
    # ruleid: harness.python.sql-fstring
    cursor.execute(f"SELECT * FROM items WHERE name='{value}'")
    # ok: harness.python.sql-fstring
    cursor.execute("SELECT * FROM items WHERE name = ?", (value,))
    # ok: harness.python.sql-fstring
    cursor.execute(f"SELECT 1")
    # ruleid: harness.python.exec
    exec(value)
    # ok: harness.python.exec
    exec("answer = 42")
    # ruleid: harness.python.os-system
    os.system(value)
    # ok: harness.python.os-system
    os.system("printf hello")
    # ruleid: harness.python.requests-verify-false
    requests.get(value, verify=False)
    # ruleid: harness.python.requests-verify-false
    requests.post(value, data={}, verify=False)
    # ok: harness.python.requests-verify-false
    requests.get(value, verify=True)
    # ok: harness.python.requests-verify-false
    requests.get(value, verify="/etc/ssl/certs/custom.pem")
    # ruleid: harness.python.tempfile-mktemp
    tempfile.mktemp()
    # ok: harness.python.tempfile-mktemp
    tempfile.NamedTemporaryFile()
    # ruleid: harness.python.jwt-noverify
    jwt.decode(value, options={"verify_signature": False})
    # ok: harness.python.jwt-noverify
    jwt.decode(value, key=public_key, algorithms=["RS256"])
    # ok: harness.python.jwt-noverify
    jwt.decode(value, options={"verify_signature": True})
