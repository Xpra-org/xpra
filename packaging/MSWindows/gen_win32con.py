import win32con        #@UnresolvedImport

print("# win32 constants definitions generated using gen_win32con.py")
print()
for x in dir(win32con):
    if x.startswith("_"):
        continue
    v = getattr(win32con, x)
    if callable(v):
        continue
    if isinstance(v, (int, str)):
        # use repr() so values are always valid python literals:
        # string constants can contain quotes, backslashes or newlines
        # (eg: IMAGE_ARCHIVE_END, IMAGE_ARCHIVE_START) which need escaping.
        # (repr of an int is unchanged, eg: `1024`)
        print("%s=%r" % (x, v))
    else:
        # keep the output importable: comment out anything we can't represent:
        print("# unknown type %s=%r (%s)" % (x, v, type(v)))
