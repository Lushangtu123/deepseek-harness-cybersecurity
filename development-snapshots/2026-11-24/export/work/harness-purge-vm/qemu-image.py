# Use the signed QEMU image utility bundled by UTM; never shell out supplied commands.
import ctypes,sys
args=['qemu-img',*sys.argv[1:]]
if len(args)<3 or args[1] not in ['info','resize','check','snapshot']:raise SystemExit('Unsupported image operation')
lib=ctypes.CDLL('/Applications/UTM.app/Contents/Frameworks/qemu-img.framework/Versions/A/qemu-img')
main=lib.main;main.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_char_p)]
raw=[a.encode() for a in args];raise SystemExit(main(len(raw),(ctypes.c_char_p*(len(raw)+1))(*raw,None)))
