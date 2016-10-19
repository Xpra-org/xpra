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
 * - the input can be a string or byte array
 * - we do not sort lists or dictionaries (the existing order is preserved)
 * - error out instead of writing "null" and generating a broken stream
 * - handle booleans as ints (0, 1)
 */


// bencode an object
function bencode(obj) {
    if (obj === null || obj === undefined) {
        throw "invalid: cannot encode null";
    }
    switch(btypeof(obj)) {
        case "string":     return bstring(obj);
        case "number":     return bint(obj);
        case "list":       return blist(obj);
        case "dictionary": return bdict(obj);
        case "boolean":    return bint(obj?1:0);
        default:           throw "invalid object type in source: "+btypeof(obj);
    }
}

function uintToString(uintArray) {
    // apply in chunks of 10400 to avoid call stack overflow
    // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Function/apply
    var s = "";
    var skip = 10400;
    var slice = uintArray.slice;
    for (var i=0, len=uintArray.length; i<len; i+=skip) {
        if(!slice) {
            s += String.fromCharCode.apply(null, uintArray.subarray(i, Math.min(i + skip, len)));
        } else {
            s += String.fromCharCode.apply(null, uintArray.slice(i, Math.min(i + skip, len)));
        }
    }
    return s;
}

// decode a bencoded string or bytearray into a javascript object
function bdecode(buf) {
    if(!buf.substr) {
        // if we have a byte array as input, its more efficient to convert the whole
        // thing into a string at once
        buf = uintToString(buf);
    }
    var dec = bparse(buf);
    return dec[0];
}

// parse a bencoded string; bdecode is really just a wrapper for this one.
// all bparse* functions return an array in the form
// [parsed object, remaining buffer to parse]
function bparse(str) {
    switch(str.charAt(0)) {
        case "d": return bparseDict(str.substr(1));
        case "l": return bparseList(str.substr(1));
        case "i": return bparseInt(str.substr(1));
        default:  return bparseString(str);
    }
}

// javascript equivallent of ord()
// returns the numeric value of the character
function ord(c) {
    return c.charCodeAt(0);
}

// parse a bencoded string
function bparseString(str) {
    str2 = str.split(":", 1)[0];
    if(isNum(str2)) {
        len = parseInt(str2);
        return [str.substr(str2.length+1, len),
                str.substr(str2.length+1+len)];
    }
    return null;
}

// parse a bencoded integer
function bparseInt(str) {
    var str2 = str.split("e", 1)[0];
    if(!isNum(str2)) {
        return null;
    }
    return [parseInt(str2), str.substr(str2.length+1)];
}

// parse a bencoded list
function bparseList(str) {
    var p, list = [];
    while(str.charAt(0) !== "e" && str.length > 0) {
        p = bparse(str);
        if(null === p) {
            return null;
        }
        list[list.length] = p[0];
        str = p[1];
    }
    if(str.length <= 0) {
        throw "unexpected end of buffer reading list";
    }
    return [list, str.substr(1)];
}

// parse a bencoded dictionary
function bparseDict(str) {
    var key, val, dict = {};
    while(str.charAt(0) !== "e" && str.length > 0) {
        key = bparseString(str);
        if(null === key) {
            return;
        }
        val = bparse(key[1]);
        if(null === val) {
            return null;
        }
        dict[key[0]] = val[0];
        str = val[1];
    }
    if(str.length <= 0) {
        return null;
    }
    return [dict, str.substr(1)];
}

// is the given string numeric?
function isNum(str) {
    return !isNaN(str.toString());
}

// returns the bencoding type of the given object
function btypeof(obj) {
    var type = typeof obj;
    if(type === 'object') {
        if(typeof obj.length === 'undefined') {
            return "dictionary";
        }
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
