/* Copyright (c) 2009 Anton Ekblad
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software. */

/*
 * This is a modified version, suitable for xpra wire encoding:
 * - the input must be a buffer (a byte array or native JS array)
 * - we do not sort lists or dictionaries (the existing order is preserved)
 * - error out instead of writing "null" and generating a broken stream
 * - handle booleans as ints (0, 1)
 */

function debug(args) {
    console.log(args);
}

// bencode an object
function bencode(obj) {
    if (obj==null || obj==undefined)
        throw "invalid: cannot encode null";
    switch(btypeof(obj)) {
        case "string":     return bstring(obj);
        case "number":     return bint(obj);
        case "list":       return blist(obj);
        case "dictionary": return bdict(obj);
        case "boolean":    return bint(obj?1:0);
        default:           throw "invalid object type in source: "+btypeof(obj);
    }
}

// decode a bencoded string into a javascript object
function bdecode(buf) {
    var dec = bparse(buf);
    if(dec != null && dec[1].length==0) {
        return dec[0];
    }
    return null;
}


// parse a bencoded string; bdecode is really just a wrapper for this one.
// all bparse* functions return an array in the form
// [parsed object, remaining buffer to parse]
function bparse(buf) {
    if(buf.subarray) {
        switch(buf[0]) {
            case ord("d"): return bparseDict(buf.subarray(1));
            case ord("l"): return bparseList(buf.subarray(1));
            case ord("i"): return bparseInt(buf.subarray(1));
            default:  return bparseString(buf);
        }
    } else {
        //assume normal js array and use slice
        switch(buf[0]) {
            case ord("d"): return bparseDict(buf.slice(1));
            case ord("l"): return bparseList(buf.slice(1));
            case ord("i"): return bparseInt(buf.slice(1));
            default:  return bparseString(buf);
        }
    }
}

function uintToString(uintArray) {
    // apply in chunks of 10400 to avoid call stack overflow
    // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Function/apply
    var s = "";
    var skip = 10400;
    if (uintArray.subarray) {
        for (var i=0, len=uintArray.length; i<len; i+=skip) {
            s += String.fromCharCode.apply(null, uintArray.subarray(i, Math.min(i + skip, len)));
        }
    } else {
        for (var i=0, len=uintArray.length; i<len; i+=skip) {
            s += String.fromCharCode.apply(null, uintArray.slice(i, Math.min(i + skip, len)));
        }
    }
    return s;
}


// javascript equivallent of ord()
// returns the numeric value of the character
function ord(c) {
    return c.charCodeAt(0);
}
// returns the part of the buffer
// before character c
function subto(buf, c) {
    var i = 0;
    var o = ord(c);
    while (buf[i]!=o) {
        if (i>=buf.length)
            return buf;
        i++;
    }
    if(buf.subarray) {
       return buf.subarray(0, i);
    } else {
        return buf.slice(0, i);
    }
}
// splits the buffer into two parts:
// before and after the first occurrence of c
function split1(buf, c) {
    var i = 0;
    var o = ord(c);
    while (buf[i]!=o) {
        if (i>=buf.length)
            return [buf];
        i++;
    }
    if(buf.subarray) {
       return [buf.subarray(0, i), buf.subarray(i+1)];
    } else {
        return [buf.slice(0, i), buf.slice(i+1)];
    }
}

// parse a bencoded string
function bparseString(buf) {
    var len = 0;
    var buf2 = subto(buf, ":");
    if(isNum(buf2)) {
        len = parseInt(uintToString(buf2));
        if(buf.subarray) {
            var str = buf.subarray(buf2.length+1, buf2.length+1+len);
            var r = buf.subarray(buf2.length+1+len);
        } else {
            var str = buf.slice(buf2.length+1, buf2.length+1+len);
            var r = buf.slice(buf2.length+1+len);
        }
        return [uintToString(str), r];
    }
    return null;
}

// parse a bencoded integer
function bparseInt(buf) {
    var buf2 = subto(buf, "e");
    if(!isNum(buf2)) {
        return null;
    }
    if(buf.subarray) {
        return [parseInt(uintToString(buf2)), buf.subarray(buf2.length+1)];
    } else {
        return [parseInt(uintToString(buf2)), buf.slice(buf2.length+1)];
    }
}

// parse a bencoded list
function bparseList(buf) {
    var p, list = [];
    var e = ord("e");
    while(buf[0] != e && buf.length > 0) {
        p = bparse(buf);
        if(null == p)
            return null;
        list.push(p[0]);
        buf = p[1];
    }
    if(buf.length <= 0) {
        debug("unexpected end of buffer reading list");
        return null;
    }
    if(buf.subarray) {
        return [list, buf.subarray(1)];
    } else {
        return [list, buf.slice(1)];
    }
}

// parse a bencoded dictionary
function bparseDict(buf) {
    var key, val, dict = {};
    var e = ord("e");
    while(buf[0] != e && buf.length > 0) {
        key = bparse(buf);
        if(null == key)
            return;

        val = bparse(key[1]);
        if(null == val)
            return null;

        dict[key[0]] = val[0];
        buf = val[1];
    }
    if(buf.length <= 0)
        return null;
    if(buf.subarray) {
        return [dict, buf.subarray(1)];
    } else {
        return [dict, buf.slice(1)];
    }
}

// is the given string numeric?
function isNum(buf) {
    var i, c;
    if(buf.length==0)
        return false;
    if(buf[0] == ord('-'))
        i = 1;
    else
        i = 0;

    for(; i < buf.length; i++) {
        c = buf[i];
        if(c < 48 || c > 57) {
            return false;
        }
    }
    return true;
}

// returns the bencoding type of the given object
function btypeof(obj) {
    var type = typeof obj;
    if(type == "object") {
        if(typeof obj.length == "undefined")
            return "dictionary";
        return "list";
    }
    return type;
}

// bencode a string
function bstring(str) {
    return (str.length + ":" + str);
}

// bencode an integer
function bint(num) {
    return "i" + num + "e";
}

// bencode a list
function blist(list) {
    var str;
    str = "l";
    for(key in list) {
        str += bencode(list[key]);
    }
    return str + "e";
}

// bencode a dictionary
function bdict(dict) {
    var str;
    str = "d";
    for(key in dict) {
        str += bencode(key) + bencode(dict[key]);
    }
    return str + "e";
}
