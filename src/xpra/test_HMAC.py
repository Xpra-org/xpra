# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import hmac

def main():
    password = "71051d81d27745b59c1c56c6e9046c19697e452453e04aa5abbd52c8edc8c232"
    salt = "99ea464f-7117-4e38-95b3-d3aa80e7b806"
    hash = hmac.HMAC(password, salt)
    print("hash(%s,%s)=%s" % (password, salt, hash))
    print("hex(hash)=%s" % hash.hexdigest())
    assert hash.hexdigest()=="dc26a074c9378b1b5735a27563320a26"

if __name__ == "__main__":
    main()
