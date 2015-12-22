#!/usr/bin/env python

import os, sys
import shutil
import zipfile

def zipdir(path, ziph):
    if os.path.isfile(path):
        ziph.write(path)
        os.unlink(path)
        return
    for root, _, files in os.walk(path):
        for f in files:
            fpath = os.path.join(root, f)
            ziph.write(fpath)
    shutil.rmtree(path)

def main():
    if len(sys.argv)<3:
        print("Invalid number of arguments")
        print("Usage: %s ZIP-Filename FileOrDirectory [More FilesOrDirectories]", sys.argv[0])
        sys.exit(1)
    filename = sys.argv[1]
    if os.path.exists(filename):
        zipf = zipfile.ZipFile(filename, 'a')
    else:
        zipf = zipfile.ZipFile(filename, 'w')
    for v in sys.argv[2:]:
        zipdir(v, zipf)
    zipf.close()

if __name__ == '__main__':
    main()
