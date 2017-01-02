import types
import win32con		#@UnresolvedImport

print("# win32 constants definitions generated using gen_win32con.py")
print()
for x in dir(win32con):
	v = getattr(win32con, x)
	if x.startswith("_"):
		continue
	elif type(v)==int:
		print("%s=%s" % (x, v))
	elif type(v)==str:
		print("%s='%s'" % (x, v))
	elif type(v)==types.FunctionType:
		pass
		#print("skipping function %s" % x)
	else:
		print("unknown type %s=%s (%s)" % (x, v, type(v)))
