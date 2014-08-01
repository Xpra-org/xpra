# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#class used to distinguish internal errors
#which should not be shown to the client,
#from useful messages we do want to pass on
class ClientException(Exception):
    pass
