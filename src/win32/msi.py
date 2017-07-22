#!/usr/bin/env python

# BATch files are useless,
# all we want is sed,
# but is is MSWindows so it's easier to re-invent the wheel, sigh

import sys

def main():
    if len(sys.argv)<3:
        print("Invalid number of arguments")
        print("Usage: %s source-msi.xml destination-msi.xml TOKEN1=VALUE1 [TOKEN2=VALUE2 [..]]", sys.argv[0])
        sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2]
    print("replacing tokens from file '%s' and saving to '%s'" % (src, dst))
    data = open(src, 'rb').read().decode()
    print("data=%i bytes %s" % (len(data), type(data)))
    for kv in sys.argv[3:]:
        try:
            token, value = kv.split("=")
        except ValueError:
            print("skipping invalid token string '%s'" % kv)
            continue
        print("replacing %s with '%s' %s" % (token, value, type(token)))
        data = data.replace("$%s" % token, value)
        data = data.replace("${%s}" % token, value)
    open(dst, 'wb').write(data.encode())

if __name__ == '__main__':
    main()
