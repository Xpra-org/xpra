#!/usr/bin/env python

import os, sys
import shutil
import zipfile

def zipdir(ziph, sdir, path):
    #print("zipdir(%s, %s, %s)" % (ziph, sdir, path))
    fpath = os.path.join(sdir, path)
    if os.path.isfile(fpath):
        ziph.write(fpath, path)
        os.unlink(fpath)
        return
    for root, _, files in os.walk(fpath):
        for f in files:
            filename = os.path.join(root, f)
            arcname = filename.lstrip(sdir)
            #print("zipdir: root=%s, f=%s" % (root, f))
            ziph.write(filename, arcname)
    shutil.rmtree(fpath)

def main():
    if len(sys.argv)<4:
        print("Invalid number of arguments")
        print("Usage: %s ZIP-Filename Directory FileOrDirectory [More FilesOrDirectories]", sys.argv[0])
        sys.exit(1)
    filename = sys.argv[1]
    sdir = sys.argv[2]
    if os.path.exists(filename):
        zipf = zipfile.ZipFile(filename, 'a')
    else:
        zipf = zipfile.ZipFile(filename, 'w')
    for v in sys.argv[3:]:
        zipdir(zipf, sdir, v)
    zipf.close()

if __name__ == '__main__':
    main()
