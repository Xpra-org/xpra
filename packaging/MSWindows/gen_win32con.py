import win32con        #@UnresolvedImport

print("# win32 constants definitions generated using gen_win32con.py")
print()
for x in dir(win32con):
    v = getattr(win32con, x)
    if x.startswith("_"):
        continue
    if callable(v):
        continue
    if isinstance(v, int):
        print("%s=%s" % (x, v))
    elif isinstance(v, str):
        print("%s='%s'" % (x, v))
    else:
        print("unknown type %s=%s (%s)" % (x, v, type(v)))
