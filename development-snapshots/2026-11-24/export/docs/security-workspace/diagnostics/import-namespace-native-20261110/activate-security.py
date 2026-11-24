"""Give the unchanged candidate service the same socket activation contract."""
import os
import socket
import sys

listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind('/run/user/1000/harness-security.sock')
os.chmod('/run/user/1000/harness-security.sock', 0o600)
listener.listen(16)
if listener.fileno() != 3:
    os.dup2(listener.fileno(), 3)
os.set_inheritable(3, True)
env = {**os.environ, 'LISTEN_PID': str(os.getpid()), 'LISTEN_FDS': '1'}
os.execve('/home/purge/.local/node/bin/node', ['/home/purge/.local/node/bin/node',
          sys.argv[1] + '/test-service.mjs', sys.argv[1]], env)
