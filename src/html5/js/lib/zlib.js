/** @license zlib.js 2012 - imaya [ https://github.com/imaya/zlib.js ] The MIT License */(function() {'use strict';var COMPILED = false;
var goog = goog || {};
goog.global = this;
goog.DEBUG = true;
goog.LOCALE = "en";
goog.provide = function(name) {
  if(!COMPILED) {
    if(goog.isProvided_(name)) {
      throw Error('Namespace "' + name + '" already declared.');
    }
    delete goog.implicitNamespaces_[name];
    var namespace = name;
    while(namespace = namespace.substring(0, namespace.lastIndexOf("."))) {
      if(goog.getObjectByName(namespace)) {
        break
      }
      goog.implicitNamespaces_[namespace] = true
    }
  }
  goog.exportPath_(name)
};
goog.setTestOnly = function(opt_message) {
  if(COMPILED && !goog.DEBUG) {
    opt_message = opt_message || "";
    throw Error("Importing test-only code into non-debug environment" + opt_message ? ": " + opt_message : ".");
  }
};
if(!COMPILED) {
  goog.isProvided_ = function(name) {
    return!goog.implicitNamespaces_[name] && !!goog.getObjectByName(name)
  };
  goog.implicitNamespaces_ = {}
}
goog.exportPath_ = function(name, opt_object, opt_objectToExportTo) {
  var parts = name.split(".");
  var cur = opt_objectToExportTo || goog.global;
  if(!(parts[0] in cur) && cur.execScript) {
    cur.execScript("var " + parts[0])
  }
  for(var part;parts.length && (part = parts.shift());) {
    if(!parts.length && goog.isDef(opt_object)) {
      cur[part] = opt_object
    }else {
      if(cur[part]) {
        cur = cur[part]
      }else {
        cur = cur[part] = {}
      }
    }
  }
};
goog.getObjectByName = function(name, opt_obj) {
  var parts = name.split(".");
  var cur = opt_obj || goog.global;
  for(var part;part = parts.shift();) {
    if(goog.isDefAndNotNull(cur[part])) {
      cur = cur[part]
    }else {
      return null
    }
  }
  return cur
};
goog.globalize = function(obj, opt_global) {
  var global = opt_global || goog.global;
  for(var x in obj) {
    global[x] = obj[x]
  }
};
goog.addDependency = function(relPath, provides, requires) {
  if(!COMPILED) {
    var provide, require;
    var path = relPath.replace(/\\/g, "/");
    var deps = goog.dependencies_;
    for(var i = 0;provide = provides[i];i++) {
      deps.nameToPath[provide] = path;
      if(!(path in deps.pathToNames)) {
        deps.pathToNames[path] = {}
      }
      deps.pathToNames[path][provide] = true
    }
    for(var j = 0;require = requires[j];j++) {
      if(!(path in deps.requires)) {
        deps.requires[path] = {}
      }
      deps.requires[path][require] = true
    }
  }
};
goog.ENABLE_DEBUG_LOADER = true;
goog.require = function(name) {
  if(!COMPILED) {
    if(goog.isProvided_(name)) {
      return
    }
    if(goog.ENABLE_DEBUG_LOADER) {
      var path = goog.getPathFromDeps_(name);
      if(path) {
        goog.included_[path] = true;
        goog.writeScripts_();
        return
      }
    }
    var errorMessage = "goog.require could not find: " + name;
    if(goog.global.console) {
      goog.global.console["error"](errorMessage)
    }
    throw Error(errorMessage);
  }
};
goog.basePath = "";
goog.global.CLOSURE_BASE_PATH;
goog.global.CLOSURE_NO_DEPS;
goog.global.CLOSURE_IMPORT_SCRIPT;
goog.nullFunction = function() {
};
goog.identityFunction = function(opt_returnValue, var_args) {
  return opt_returnValue
};
goog.abstractMethod = function() {
  throw Error("unimplemented abstract method");
};
goog.addSingletonGetter = function(ctor) {
  ctor.getInstance = function() {
    if(ctor.instance_) {
      return ctor.instance_
    }
    if(goog.DEBUG) {
      goog.instantiatedSingletons_[goog.instantiatedSingletons_.length] = ctor
    }
    return ctor.instance_ = new ctor
  }
};
goog.instantiatedSingletons_ = [];
if(!COMPILED && goog.ENABLE_DEBUG_LOADER) {
  goog.included_ = {};
  goog.dependencies_ = {pathToNames:{}, nameToPath:{}, requires:{}, visited:{}, written:{}};
  goog.inHtmlDocument_ = function() {
    var doc = goog.global.document;
    return typeof doc != "undefined" && "write" in doc
  };
  goog.findBasePath_ = function() {
    if(goog.global.CLOSURE_BASE_PATH) {
      goog.basePath = goog.global.CLOSURE_BASE_PATH;
      return
    }else {
      if(!goog.inHtmlDocument_()) {
        return
      }
    }
    var doc = goog.global.document;
    var scripts = doc.getElementsByTagName("script");
    for(var i = scripts.length - 1;i >= 0;--i) {
      var src = scripts[i].src;
      var qmark = src.lastIndexOf("?");
      var l = qmark == -1 ? src.length : qmark;
      if(src.substr(l - 7, 7) == "base.js") {
        goog.basePath = src.substr(0, l - 7);
        return
      }
    }
  };
  goog.importScript_ = function(src) {
    var importScript = goog.global.CLOSURE_IMPORT_SCRIPT || goog.writeScriptTag_;
    if(!goog.dependencies_.written[src] && importScript(src)) {
      goog.dependencies_.written[src] = true
    }
  };
  goog.writeScriptTag_ = function(src) {
    if(goog.inHtmlDocument_()) {
      var doc = goog.global.document;
      doc.write('<script type="text/javascript" src="' + src + '"></' + "script>");
      return true
    }else {
      return false
    }
  };
  goog.writeScripts_ = function() {
    var scripts = [];
    var seenScript = {};
    var deps = goog.dependencies_;
    function visitNode(path) {
      if(path in deps.written) {
        return
      }
      if(path in deps.visited) {
        if(!(path in seenScript)) {
          seenScript[path] = true;
          scripts.push(path)
        }
        return
      }
      deps.visited[path] = true;
      if(path in deps.requires) {
        for(var requireName in deps.requires[path]) {
          if(!goog.isProvided_(requireName)) {
            if(requireName in deps.nameToPath) {
              visitNode(deps.nameToPath[requireName])
            }else {
              throw Error("Undefined nameToPath for " + requireName);
            }
          }
        }
      }
      if(!(path in seenScript)) {
        seenScript[path] = true;
        scripts.push(path)
      }
    }
    for(var path in goog.included_) {
      if(!deps.written[path]) {
        visitNode(path)
      }
    }
    for(var i = 0;i < scripts.length;i++) {
      if(scripts[i]) {
        goog.importScript_(goog.basePath + scripts[i])
      }else {
        throw Error("Undefined script input");
      }
    }
  };
  goog.getPathFromDeps_ = function(rule) {
    if(rule in goog.dependencies_.nameToPath) {
      return goog.dependencies_.nameToPath[rule]
    }else {
      return null
    }
  };
  goog.findBasePath_();
}
goog.typeOf = function(value) {
  var s = typeof value;
  if(s == "object") {
    if(value) {
      if(value instanceof Array) {
        return"array"
      }else {
        if(value instanceof Object) {
          return s
        }
      }
      var className = Object.prototype.toString.call((value));
      if(className == "[object Window]") {
        return"object"
      }
      if(className == "[object Array]" || typeof value.length == "number" && typeof value.splice != "undefined" && typeof value.propertyIsEnumerable != "undefined" && !value.propertyIsEnumerable("splice")) {
        return"array"
      }
      if(className == "[object Function]" || typeof value.call != "undefined" && typeof value.propertyIsEnumerable != "undefined" && !value.propertyIsEnumerable("call")) {
        return"function"
      }
    }else {
      return"null"
    }
  }else {
    if(s == "function" && typeof value.call == "undefined") {
      return"object"
    }
  }
  return s
};
goog.isDef = function(val) {
  return val !== undefined
};
goog.isNull = function(val) {
  return val === null
};
goog.isDefAndNotNull = function(val) {
  return val != null
};
goog.isArray = function(val) {
  return goog.typeOf(val) == "array"
};
goog.isArrayLike = function(val) {
  var type = goog.typeOf(val);
  return type == "array" || type == "object" && typeof val.length == "number"
};
goog.isDateLike = function(val) {
  return goog.isObject(val) && typeof val.getFullYear == "function"
};
goog.isString = function(val) {
  return typeof val == "string"
};
goog.isBoolean = function(val) {
  return typeof val == "boolean"
};
goog.isNumber = function(val) {
  return typeof val == "number"
};
goog.isFunction = function(val) {
  return goog.typeOf(val) == "function"
};
goog.isObject = function(val) {
  var type = typeof val;
  return type == "object" && val != null || type == "function"
};
goog.getUid = function(obj) {
  return obj[goog.UID_PROPERTY_] || (obj[goog.UID_PROPERTY_] = ++goog.uidCounter_)
};
goog.removeUid = function(obj) {
  if("removeAttribute" in obj) {
    obj.removeAttribute(goog.UID_PROPERTY_)
  }
  try {
    delete obj[goog.UID_PROPERTY_]
  }catch(ex) {
  }
};
goog.UID_PROPERTY_ = "closure_uid_" + Math.floor(Math.random() * 2147483648).toString(36);
goog.uidCounter_ = 0;
goog.getHashCode = goog.getUid;
goog.removeHashCode = goog.removeUid;
goog.cloneObject = function(obj) {
  var type = goog.typeOf(obj);
  if(type == "object" || type == "array") {
    if(obj.clone) {
      return obj.clone()
    }
    var clone = type == "array" ? [] : {};
    for(var key in obj) {
      clone[key] = goog.cloneObject(obj[key])
    }
    return clone
  }
  return obj
};
Object.prototype.clone;
goog.bindNative_ = function(fn, selfObj, var_args) {
  return(fn.call.apply(fn.bind, arguments))
};
goog.bindJs_ = function(fn, selfObj, var_args) {
  if(!fn) {
    throw new Error;
  }
  if(arguments.length > 2) {
    var boundArgs = Array.prototype.slice.call(arguments, 2);
    return function() {
      var newArgs = Array.prototype.slice.call(arguments);
      Array.prototype.unshift.apply(newArgs, boundArgs);
      return fn.apply(selfObj, newArgs)
    }
  }else {
    return function() {
      return fn.apply(selfObj, arguments)
    }
  }
};
goog.bind = function(fn, selfObj, var_args) {
  if(Function.prototype.bind && Function.prototype.bind.toString().indexOf("native code") != -1) {
    goog.bind = goog.bindNative_
  }else {
    goog.bind = goog.bindJs_
  }
  return goog.bind.apply(null, arguments)
};
goog.partial = function(fn, var_args) {
  var args = Array.prototype.slice.call(arguments, 1);
  return function() {
    var newArgs = Array.prototype.slice.call(arguments);
    newArgs.unshift.apply(newArgs, args);
    return fn.apply(this, newArgs)
  }
};
goog.mixin = function(target, source) {
  for(var x in source) {
    target[x] = source[x]
  }
};
goog.now = Date.now || function() {
  return+new Date
};
goog.globalEval = function(script) {
  if(goog.global.execScript) {
    goog.global.execScript(script, "JavaScript")
  }else {
    if(goog.global.eval) {
      if(goog.evalWorksForGlobals_ == null) {
        goog.global.eval("var _et_ = 1;");
        if(typeof goog.global["_et_"] != "undefined") {
          delete goog.global["_et_"];
          goog.evalWorksForGlobals_ = true
        }else {
          goog.evalWorksForGlobals_ = false
        }
      }
      if(goog.evalWorksForGlobals_) {
        goog.global.eval(script)
      }else {
        var doc = goog.global.document;
        var scriptElt = doc.createElement("script");
        scriptElt.type = "text/javascript";
        scriptElt.defer = false;
        scriptElt.appendChild(doc.createTextNode(script));
        doc.body.appendChild(scriptElt);
        doc.body.removeChild(scriptElt)
      }
    }else {
      throw Error("goog.globalEval not available");
    }
  }
};
goog.evalWorksForGlobals_ = null;
goog.cssNameMapping_;
goog.cssNameMappingStyle_;
goog.getCssName = function(className, opt_modifier) {
  var getMapping = function(cssName) {
    return goog.cssNameMapping_[cssName] || cssName
  };
  var renameByParts = function(cssName) {
    var parts = cssName.split("-");
    var mapped = [];
    for(var i = 0;i < parts.length;i++) {
      mapped.push(getMapping(parts[i]))
    }
    return mapped.join("-")
  };
  var rename;
  if(goog.cssNameMapping_) {
    rename = goog.cssNameMappingStyle_ == "BY_WHOLE" ? getMapping : renameByParts
  }else {
    rename = function(a) {
      return a
    }
  }
  if(opt_modifier) {
    return className + "-" + rename(opt_modifier)
  }else {
    return rename(className)
  }
};
goog.setCssNameMapping = function(mapping, opt_style) {
  goog.cssNameMapping_ = mapping;
  goog.cssNameMappingStyle_ = opt_style
};
goog.global.CLOSURE_CSS_NAME_MAPPING;
if(!COMPILED && goog.global.CLOSURE_CSS_NAME_MAPPING) {
  goog.cssNameMapping_ = goog.global.CLOSURE_CSS_NAME_MAPPING
}
goog.getMsg = function(str, opt_values) {
  var values = opt_values || {};
  for(var key in values) {
    var value = ("" + values[key]).replace(/\$/g, "$$$$");
    str = str.replace(new RegExp("\\{\\$" + key + "\\}", "gi"), value)
  }
  return str
};
goog.exportSymbol = function(publicPath, object, opt_objectToExportTo) {
  goog.exportPath_(publicPath, object, opt_objectToExportTo)
};
goog.exportProperty = function(object, publicName, symbol) {
  object[publicName] = symbol
};
goog.inherits = function(childCtor, parentCtor) {
  function tempCtor() {
  }
  tempCtor.prototype = parentCtor.prototype;
  childCtor.superClass_ = parentCtor.prototype;
  childCtor.prototype = new tempCtor;
  childCtor.prototype.constructor = childCtor
};
goog.base = function(me, opt_methodName, var_args) {
  var caller = arguments.callee.caller;
  if(caller.superClass_) {
    return caller.superClass_.constructor.apply(me, Array.prototype.slice.call(arguments, 1))
  }
  var args = Array.prototype.slice.call(arguments, 2);
  var foundCaller = false;
  for(var ctor = me.constructor;ctor;ctor = ctor.superClass_ && ctor.superClass_.constructor) {
    if(ctor.prototype[opt_methodName] === caller) {
      foundCaller = true
    }else {
      if(foundCaller) {
        return ctor.prototype[opt_methodName].apply(me, args)
      }
    }
  }
  if(me[opt_methodName] === caller) {
    return me.constructor.prototype[opt_methodName].apply(me, args)
  }else {
    throw Error("goog.base called from a method of one name " + "to a method of a different name");
  }
};
goog.scope = function(fn) {
  fn.call(goog.global)
};
goog.provide("USE_TYPEDARRAY");
var USE_TYPEDARRAY = typeof Uint8Array !== "undefined" && typeof Uint16Array !== "undefined" && typeof Uint32Array !== "undefined" && typeof DataView !== "undefined";
goog.provide("Zlib.BitStream");
goog.require("USE_TYPEDARRAY");
goog.scope(function() {
  Zlib.BitStream = function(buffer, bufferPosition) {
    this.index = typeof bufferPosition === "number" ? bufferPosition : 0;
    this.bitindex = 0;
    this.buffer = buffer instanceof (USE_TYPEDARRAY ? Uint8Array : Array) ? buffer : new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.BitStream.DefaultBlockSize);
    if(this.buffer.length * 2 <= this.index) {
      throw new Error("invalid index");
    }else {
      if(this.buffer.length <= this.index) {
        this.expandBuffer()
      }
    }
  };
  Zlib.BitStream.DefaultBlockSize = 32768;
  Zlib.BitStream.prototype.expandBuffer = function() {
    var oldbuf = this.buffer;
    var i;
    var il = oldbuf.length;
    var buffer = new (USE_TYPEDARRAY ? Uint8Array : Array)(il << 1);
    if(USE_TYPEDARRAY) {
      buffer.set(oldbuf)
    }else {
      for(i = 0;i < il;++i) {
        buffer[i] = oldbuf[i]
      }
    }
    return this.buffer = buffer
  };
  Zlib.BitStream.prototype.writeBits = function(number, n, reverse) {
    var buffer = this.buffer;
    var index = this.index;
    var bitindex = this.bitindex;
    var current = buffer[index];
    var i;
    function rev32_(n) {
      return Zlib.BitStream.ReverseTable[n & 255] << 24 | Zlib.BitStream.ReverseTable[n >>> 8 & 255] << 16 | Zlib.BitStream.ReverseTable[n >>> 16 & 255] << 8 | Zlib.BitStream.ReverseTable[n >>> 24 & 255]
    }
    if(reverse && n > 1) {
      number = n > 8 ? rev32_(number) >> 32 - n : Zlib.BitStream.ReverseTable[number] >> 8 - n
    }
    if(n + bitindex < 8) {
      current = current << n | number;
      bitindex += n
    }else {
      for(i = 0;i < n;++i) {
        current = current << 1 | number >> n - i - 1 & 1;
        if(++bitindex === 8) {
          bitindex = 0;
          buffer[index++] = Zlib.BitStream.ReverseTable[current];
          current = 0;
          if(index === buffer.length) {
            buffer = this.expandBuffer()
          }
        }
      }
    }
    buffer[index] = current;
    this.buffer = buffer;
    this.bitindex = bitindex;
    this.index = index
  };
  Zlib.BitStream.prototype.finish = function() {
    var buffer = this.buffer;
    var index = this.index;
    var output;
    if(this.bitindex > 0) {
      buffer[index] <<= 8 - this.bitindex;
      buffer[index] = Zlib.BitStream.ReverseTable[buffer[index]];
      index++
    }
    if(USE_TYPEDARRAY) {
      output = buffer.subarray(0, index)
    }else {
      buffer.length = index;
      output = buffer
    }
    return output
  };
  Zlib.BitStream.ReverseTable = function(table) {
    return table
  }(function() {
    var table = new (USE_TYPEDARRAY ? Uint8Array : Array)(256);
    var i;
    for(i = 0;i < 256;++i) {
      table[i] = function(n) {
        var r = n;
        var s = 7;
        for(n >>>= 1;n;n >>>= 1) {
          r <<= 1;
          r |= n & 1;
          --s
        }
        return(r << s & 255) >>> 0
      }(i)
    }
    return table
  }())
});
goog.provide("Zlib.CRC32");
goog.require("USE_TYPEDARRAY");
var ZLIB_CRC32_COMPACT = false;
goog.scope(function() {
  Zlib.CRC32.calc = function(data, pos, length) {
    return Zlib.CRC32.update(data, 0, pos, length)
  };
  Zlib.CRC32.update = function(data, crc, pos, length) {
    var table = Zlib.CRC32.Table;
    var i = typeof pos === "number" ? pos : pos = 0;
    var il = typeof length === "number" ? length : data.length;
    crc ^= 4294967295;
    for(i = il & 7;i--;++pos) {
      crc = crc >>> 8 ^ table[(crc ^ data[pos]) & 255]
    }
    for(i = il >> 3;i--;pos += 8) {
      crc = crc >>> 8 ^ table[(crc ^ data[pos]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 1]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 2]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 3]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 4]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 5]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 6]) & 255];
      crc = crc >>> 8 ^ table[(crc ^ data[pos + 7]) & 255]
    }
    return(crc ^ 4294967295) >>> 0
  };
  Zlib.CRC32.single = function(num, crc) {
    return(Zlib.CRC32.Table[(num ^ crc) & 255] ^ num >>> 8) >>> 0
  };
  Zlib.CRC32.Table_ = [0, 1996959894, 3993919788, 2567524794, 124634137, 1886057615, 3915621685, 2657392035, 249268274, 2044508324, 3772115230, 2547177864, 162941995, 2125561021, 3887607047, 2428444049, 498536548, 1789927666, 4089016648, 2227061214, 450548861, 1843258603, 4107580753, 2211677639, 325883990, 1684777152, 4251122042, 2321926636, 335633487, 1661365465, 4195302755, 2366115317, 997073096, 1281953886, 3579855332, 2724688242, 1006888145, 1258607687, 3524101629, 2768942443, 901097722, 1119000684, 
  3686517206, 2898065728, 853044451, 1172266101, 3705015759, 2882616665, 651767980, 1373503546, 3369554304, 3218104598, 565507253, 1454621731, 3485111705, 3099436303, 671266974, 1594198024, 3322730930, 2970347812, 795835527, 1483230225, 3244367275, 3060149565, 1994146192, 31158534, 2563907772, 4023717930, 1907459465, 112637215, 2680153253, 3904427059, 2013776290, 251722036, 2517215374, 3775830040, 2137656763, 141376813, 2439277719, 3865271297, 1802195444, 476864866, 2238001368, 4066508878, 1812370925, 
  453092731, 2181625025, 4111451223, 1706088902, 314042704, 2344532202, 4240017532, 1658658271, 366619977, 2362670323, 4224994405, 1303535960, 984961486, 2747007092, 3569037538, 1256170817, 1037604311, 2765210733, 3554079995, 1131014506, 879679996, 2909243462, 3663771856, 1141124467, 855842277, 2852801631, 3708648649, 1342533948, 654459306, 3188396048, 3373015174, 1466479909, 544179635, 3110523913, 3462522015, 1591671054, 702138776, 2966460450, 3352799412, 1504918807, 783551873, 3082640443, 3233442989, 
  3988292384, 2596254646, 62317068, 1957810842, 3939845945, 2647816111, 81470997, 1943803523, 3814918930, 2489596804, 225274430, 2053790376, 3826175755, 2466906013, 167816743, 2097651377, 4027552580, 2265490386, 503444072, 1762050814, 4150417245, 2154129355, 426522225, 1852507879, 4275313526, 2312317920, 282753626, 1742555852, 4189708143, 2394877945, 397917763, 1622183637, 3604390888, 2714866558, 953729732, 1340076626, 3518719985, 2797360999, 1068828381, 1219638859, 3624741850, 2936675148, 906185462, 
  1090812512, 3747672003, 2825379669, 829329135, 1181335161, 3412177804, 3160834842, 628085408, 1382605366, 3423369109, 3138078467, 570562233, 1426400815, 3317316542, 2998733608, 733239954, 1555261956, 3268935591, 3050360625, 752459403, 1541320221, 2607071920, 3965973030, 1969922972, 40735498, 2617837225, 3943577151, 1913087877, 83908371, 2512341634, 3803740692, 2075208622, 213261112, 2463272603, 3855990285, 2094854071, 198958881, 2262029012, 4057260610, 1759359992, 534414190, 2176718541, 4139329115, 
  1873836001, 414664567, 2282248934, 4279200368, 1711684554, 285281116, 2405801727, 4167216745, 1634467795, 376229701, 2685067896, 3608007406, 1308918612, 956543938, 2808555105, 3495958263, 1231636301, 1047427035, 2932959818, 3654703836, 1088359270, 936918E3, 2847714899, 3736837829, 1202900863, 817233897, 3183342108, 3401237130, 1404277552, 615818150, 3134207493, 3453421203, 1423857449, 601450431, 3009837614, 3294710456, 1567103746, 711928724, 3020668471, 3272380065, 1510334235, 755167117];
  Zlib.CRC32.Table = ZLIB_CRC32_COMPACT ? function() {
    var table = new (USE_TYPEDARRAY ? Uint32Array : Array)(256);
    var c;
    var i;
    var j;
    for(i = 0;i < 256;++i) {
      c = i;
      for(j = 0;j < 8;++j) {
        c = c & 1 ? 3988292384 ^ c >>> 1 : c >>> 1
      }
      table[i] = c >>> 0
    }
    return table
  }() : USE_TYPEDARRAY ? new Uint32Array(Zlib.CRC32.Table_) : Zlib.CRC32.Table_
});
goog.provide("Zlib.GunzipMember");
goog.scope(function() {
  Zlib.GunzipMember = function() {
    this.id1;
    this.id2;
    this.cm;
    this.flg;
    this.mtime;
    this.xfl;
    this.os;
    this.crc16;
    this.xlen;
    this.crc32;
    this.isize;
    this.name;
    this.comment;
    this.data
  };
  Zlib.GunzipMember.prototype.getName = function() {
    return this.name
  };
  Zlib.GunzipMember.prototype.getData = function() {
    return this.data
  };
  Zlib.GunzipMember.prototype.getMtime = function() {
    return this.mtime
  }
});
goog.provide("Zlib.Heap");
goog.require("USE_TYPEDARRAY");
goog.scope(function() {
  Zlib.Heap = function(length) {
    this.buffer = new (USE_TYPEDARRAY ? Uint16Array : Array)(length * 2);
    this.length = 0
  };
  Zlib.Heap.prototype.getParent = function(index) {
    return((index - 2) / 4 | 0) * 2
  };
  Zlib.Heap.prototype.getChild = function(index) {
    return 2 * index + 2
  };
  Zlib.Heap.prototype.push = function(index, value) {
    var current, parent, heap = this.buffer, swap;
    current = this.length;
    heap[this.length++] = value;
    heap[this.length++] = index;
    while(current > 0) {
      parent = this.getParent(current);
      if(heap[current] > heap[parent]) {
        swap = heap[current];
        heap[current] = heap[parent];
        heap[parent] = swap;
        swap = heap[current + 1];
        heap[current + 1] = heap[parent + 1];
        heap[parent + 1] = swap;
        current = parent
      }else {
        break
      }
    }
    return this.length
  };
  Zlib.Heap.prototype.pop = function() {
    var index, value, heap = this.buffer, swap, current, parent;
    value = heap[0];
    index = heap[1];
    this.length -= 2;
    heap[0] = heap[this.length];
    heap[1] = heap[this.length + 1];
    parent = 0;
    while(true) {
      current = this.getChild(parent);
      if(current >= this.length) {
        break
      }
      if(current + 2 < this.length && heap[current + 2] > heap[current]) {
        current += 2
      }
      if(heap[current] > heap[parent]) {
        swap = heap[parent];
        heap[parent] = heap[current];
        heap[current] = swap;
        swap = heap[parent + 1];
        heap[parent + 1] = heap[current + 1];
        heap[current + 1] = swap
      }else {
        break
      }
      parent = current
    }
    return{index:index, value:value, length:this.length}
  }
});
goog.provide("Zlib.Huffman");
goog.require("USE_TYPEDARRAY");
goog.scope(function() {
  Zlib.Huffman.buildHuffmanTable = function(lengths) {
    var listSize = lengths.length;
    var maxCodeLength = 0;
    var minCodeLength = Number.POSITIVE_INFINITY;
    var size;
    var table;
    var bitLength;
    var code;
    var skip;
    var reversed;
    var rtemp;
    var i;
    var il;
    var j;
    var value;
    for(i = 0, il = listSize;i < il;++i) {
      if(lengths[i] > maxCodeLength) {
        maxCodeLength = lengths[i]
      }
      if(lengths[i] < minCodeLength) {
        minCodeLength = lengths[i]
      }
    }
    size = 1 << maxCodeLength;
    table = new (USE_TYPEDARRAY ? Uint32Array : Array)(size);
    for(bitLength = 1, code = 0, skip = 2;bitLength <= maxCodeLength;) {
      for(i = 0;i < listSize;++i) {
        if(lengths[i] === bitLength) {
          for(reversed = 0, rtemp = code, j = 0;j < bitLength;++j) {
            reversed = reversed << 1 | rtemp & 1;
            rtemp >>= 1
          }
          value = bitLength << 16 | i;
          for(j = reversed;j < size;j += skip) {
            table[j] = value
          }
          ++code
        }
      }
      ++bitLength;
      code <<= 1;
      skip <<= 1
    }
    return[table, maxCodeLength, minCodeLength]
  }
});
goog.provide("Zlib.RawDeflate");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.BitStream");
goog.require("Zlib.Heap");
goog.scope(function() {
  Zlib.RawDeflate = function(input, opt_params) {
    this.compressionType = Zlib.RawDeflate.CompressionType.DYNAMIC;
    this.lazy = 0;
    this.freqsLitLen;
    this.freqsDist;
    this.input = USE_TYPEDARRAY && input instanceof Array ? new Uint8Array(input) : input;
    this.output;
    this.op = 0;
    if(opt_params) {
      if(opt_params["lazy"]) {
        this.lazy = opt_params["lazy"]
      }
      if(typeof opt_params["compressionType"] === "number") {
        this.compressionType = opt_params["compressionType"]
      }
      if(opt_params["outputBuffer"]) {
        this.output = USE_TYPEDARRAY && opt_params["outputBuffer"] instanceof Array ? new Uint8Array(opt_params["outputBuffer"]) : opt_params["outputBuffer"]
      }
      if(typeof opt_params["outputIndex"] === "number") {
        this.op = opt_params["outputIndex"]
      }
    }
    if(!this.output) {
      this.output = new (USE_TYPEDARRAY ? Uint8Array : Array)(32768)
    }
  };
  Zlib.RawDeflate.CompressionType = {NONE:0, FIXED:1, DYNAMIC:2, RESERVED:3};
  Zlib.RawDeflate.Lz77MinLength = 3;
  Zlib.RawDeflate.Lz77MaxLength = 258;
  Zlib.RawDeflate.WindowSize = 32768;
  Zlib.RawDeflate.MaxCodeLength = 16;
  Zlib.RawDeflate.HUFMAX = 286;
  Zlib.RawDeflate.FixedHuffmanTable = function() {
    var table = [], i;
    for(i = 0;i < 288;i++) {
      switch(true) {
        case i <= 143:
          table.push([i + 48, 8]);
          break;
        case i <= 255:
          table.push([i - 144 + 400, 9]);
          break;
        case i <= 279:
          table.push([i - 256 + 0, 7]);
          break;
        case i <= 287:
          table.push([i - 280 + 192, 8]);
          break;
        default:
          throw"invalid literal: " + i;
      }
    }
    return table
  }();
  Zlib.RawDeflate.prototype.compress = function() {
    var blockArray;
    var position;
    var length;
    var input = this.input;
    switch(this.compressionType) {
      case Zlib.RawDeflate.CompressionType.NONE:
        for(position = 0, length = input.length;position < length;) {
          blockArray = USE_TYPEDARRAY ? input.subarray(position, position + 65535) : input.slice(position, position + 65535);
          position += blockArray.length;
          this.makeNocompressBlock(blockArray, position === length)
        }
        break;
      case Zlib.RawDeflate.CompressionType.FIXED:
        this.output = this.makeFixedHuffmanBlock(input, true);
        this.op = this.output.length;
        break;
      case Zlib.RawDeflate.CompressionType.DYNAMIC:
        this.output = this.makeDynamicHuffmanBlock(input, true);
        this.op = this.output.length;
        break;
      default:
        throw"invalid compression type";
    }
    return this.output
  };
  Zlib.RawDeflate.prototype.makeNocompressBlock = function(blockArray, isFinalBlock) {
    var bfinal;
    var btype;
    var len;
    var nlen;
    var i;
    var il;
    var output = this.output;
    var op = this.op;
    if(USE_TYPEDARRAY) {
      output = new Uint8Array(this.output.buffer);
      while(output.length <= op + blockArray.length + 5) {
        output = new Uint8Array(output.length << 1)
      }
      output.set(this.output)
    }
    bfinal = isFinalBlock ? 1 : 0;
    btype = Zlib.RawDeflate.CompressionType.NONE;
    output[op++] = bfinal | btype << 1;
    len = blockArray.length;
    nlen = ~len + 65536 & 65535;
    output[op++] = len & 255;
    output[op++] = len >>> 8 & 255;
    output[op++] = nlen & 255;
    output[op++] = nlen >>> 8 & 255;
    if(USE_TYPEDARRAY) {
      output.set(blockArray, op);
      op += blockArray.length;
      output = output.subarray(0, op)
    }else {
      for(i = 0, il = blockArray.length;i < il;++i) {
        output[op++] = blockArray[i]
      }
      output.length = op
    }
    this.op = op;
    this.output = output;
    return output
  };
  Zlib.RawDeflate.prototype.makeFixedHuffmanBlock = function(blockArray, isFinalBlock) {
    var stream = new Zlib.BitStream(USE_TYPEDARRAY ? new Uint8Array(this.output.buffer) : this.output, this.op);
    var bfinal;
    var btype;
    var data;
    bfinal = isFinalBlock ? 1 : 0;
    btype = Zlib.RawDeflate.CompressionType.FIXED;
    stream.writeBits(bfinal, 1, true);
    stream.writeBits(btype, 2, true);
    data = this.lz77(blockArray);
    this.fixedHuffman(data, stream);
    return stream.finish()
  };
  Zlib.RawDeflate.prototype.makeDynamicHuffmanBlock = function(blockArray, isFinalBlock) {
    var stream = new Zlib.BitStream(USE_TYPEDARRAY ? new Uint8Array(this.output.buffer) : this.output, this.op);
    var bfinal;
    var btype;
    var data;
    var hlit;
    var hdist;
    var hclen;
    var hclenOrder = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];
    var litLenLengths;
    var litLenCodes;
    var distLengths;
    var distCodes;
    var treeSymbols;
    var treeLengths;
    var transLengths = new Array(19);
    var treeCodes;
    var code;
    var bitlen;
    var i;
    var il;
    bfinal = isFinalBlock ? 1 : 0;
    btype = Zlib.RawDeflate.CompressionType.DYNAMIC;
    stream.writeBits(bfinal, 1, true);
    stream.writeBits(btype, 2, true);
    data = this.lz77(blockArray);
    litLenLengths = this.getLengths_(this.freqsLitLen, 15);
    litLenCodes = this.getCodesFromLengths_(litLenLengths);
    distLengths = this.getLengths_(this.freqsDist, 7);
    distCodes = this.getCodesFromLengths_(distLengths);
    for(hlit = 286;hlit > 257 && litLenLengths[hlit - 1] === 0;hlit--) {
    }
    for(hdist = 30;hdist > 1 && distLengths[hdist - 1] === 0;hdist--) {
    }
    treeSymbols = this.getTreeSymbols_(hlit, litLenLengths, hdist, distLengths);
    treeLengths = this.getLengths_(treeSymbols.freqs, 7);
    for(i = 0;i < 19;i++) {
      transLengths[i] = treeLengths[hclenOrder[i]]
    }
    for(hclen = 19;hclen > 4 && transLengths[hclen - 1] === 0;hclen--) {
    }
    treeCodes = this.getCodesFromLengths_(treeLengths);
    stream.writeBits(hlit - 257, 5, true);
    stream.writeBits(hdist - 1, 5, true);
    stream.writeBits(hclen - 4, 4, true);
    for(i = 0;i < hclen;i++) {
      stream.writeBits(transLengths[i], 3, true)
    }
    for(i = 0, il = treeSymbols.codes.length;i < il;i++) {
      code = treeSymbols.codes[i];
      stream.writeBits(treeCodes[code], treeLengths[code], true);
      if(code >= 16) {
        i++;
        switch(code) {
          case 16:
            bitlen = 2;
            break;
          case 17:
            bitlen = 3;
            break;
          case 18:
            bitlen = 7;
            break;
          default:
            throw"invalid code: " + code;
        }
        stream.writeBits(treeSymbols.codes[i], bitlen, true)
      }
    }
    this.dynamicHuffman(data, [litLenCodes, litLenLengths], [distCodes, distLengths], stream);
    return stream.finish()
  };
  Zlib.RawDeflate.prototype.dynamicHuffman = function(dataArray, litLen, dist, stream) {
    var index;
    var length;
    var literal;
    var code;
    var litLenCodes;
    var litLenLengths;
    var distCodes;
    var distLengths;
    litLenCodes = litLen[0];
    litLenLengths = litLen[1];
    distCodes = dist[0];
    distLengths = dist[1];
    for(index = 0, length = dataArray.length;index < length;++index) {
      literal = dataArray[index];
      stream.writeBits(litLenCodes[literal], litLenLengths[literal], true);
      if(literal > 256) {
        stream.writeBits(dataArray[++index], dataArray[++index], true);
        code = dataArray[++index];
        stream.writeBits(distCodes[code], distLengths[code], true);
        stream.writeBits(dataArray[++index], dataArray[++index], true)
      }else {
        if(literal === 256) {
          break
        }
      }
    }
    return stream
  };
  Zlib.RawDeflate.prototype.fixedHuffman = function(dataArray, stream) {
    var index;
    var length;
    var literal;
    for(index = 0, length = dataArray.length;index < length;index++) {
      literal = dataArray[index];
      Zlib.BitStream.prototype.writeBits.apply(stream, Zlib.RawDeflate.FixedHuffmanTable[literal]);
      if(literal > 256) {
        stream.writeBits(dataArray[++index], dataArray[++index], true);
        stream.writeBits(dataArray[++index], 5);
        stream.writeBits(dataArray[++index], dataArray[++index], true)
      }else {
        if(literal === 256) {
          break
        }
      }
    }
    return stream
  };
  Zlib.RawDeflate.Lz77Match = function(length, backwardDistance) {
    this.length = length;
    this.backwardDistance = backwardDistance
  };
  Zlib.RawDeflate.Lz77Match.LengthCodeTable = function(table) {
    return USE_TYPEDARRAY ? new Uint32Array(table) : table
  }(function() {
    var table = [];
    var i;
    var c;
    for(i = 3;i <= 258;i++) {
      c = code(i);
      table[i] = c[2] << 24 | c[1] << 16 | c[0]
    }
    function code(length) {
      switch(true) {
        case length === 3:
          return[257, length - 3, 0];
          break;
        case length === 4:
          return[258, length - 4, 0];
          break;
        case length === 5:
          return[259, length - 5, 0];
          break;
        case length === 6:
          return[260, length - 6, 0];
          break;
        case length === 7:
          return[261, length - 7, 0];
          break;
        case length === 8:
          return[262, length - 8, 0];
          break;
        case length === 9:
          return[263, length - 9, 0];
          break;
        case length === 10:
          return[264, length - 10, 0];
          break;
        case length <= 12:
          return[265, length - 11, 1];
          break;
        case length <= 14:
          return[266, length - 13, 1];
          break;
        case length <= 16:
          return[267, length - 15, 1];
          break;
        case length <= 18:
          return[268, length - 17, 1];
          break;
        case length <= 22:
          return[269, length - 19, 2];
          break;
        case length <= 26:
          return[270, length - 23, 2];
          break;
        case length <= 30:
          return[271, length - 27, 2];
          break;
        case length <= 34:
          return[272, length - 31, 2];
          break;
        case length <= 42:
          return[273, length - 35, 3];
          break;
        case length <= 50:
          return[274, length - 43, 3];
          break;
        case length <= 58:
          return[275, length - 51, 3];
          break;
        case length <= 66:
          return[276, length - 59, 3];
          break;
        case length <= 82:
          return[277, length - 67, 4];
          break;
        case length <= 98:
          return[278, length - 83, 4];
          break;
        case length <= 114:
          return[279, length - 99, 4];
          break;
        case length <= 130:
          return[280, length - 115, 4];
          break;
        case length <= 162:
          return[281, length - 131, 5];
          break;
        case length <= 194:
          return[282, length - 163, 5];
          break;
        case length <= 226:
          return[283, length - 195, 5];
          break;
        case length <= 257:
          return[284, length - 227, 5];
          break;
        case length === 258:
          return[285, length - 258, 0];
          break;
        default:
          throw"invalid length: " + length;
      }
    }
    return table
  }());
  Zlib.RawDeflate.Lz77Match.prototype.getDistanceCode_ = function(dist) {
    var r;
    switch(true) {
      case dist === 1:
        r = [0, dist - 1, 0];
        break;
      case dist === 2:
        r = [1, dist - 2, 0];
        break;
      case dist === 3:
        r = [2, dist - 3, 0];
        break;
      case dist === 4:
        r = [3, dist - 4, 0];
        break;
      case dist <= 6:
        r = [4, dist - 5, 1];
        break;
      case dist <= 8:
        r = [5, dist - 7, 1];
        break;
      case dist <= 12:
        r = [6, dist - 9, 2];
        break;
      case dist <= 16:
        r = [7, dist - 13, 2];
        break;
      case dist <= 24:
        r = [8, dist - 17, 3];
        break;
      case dist <= 32:
        r = [9, dist - 25, 3];
        break;
      case dist <= 48:
        r = [10, dist - 33, 4];
        break;
      case dist <= 64:
        r = [11, dist - 49, 4];
        break;
      case dist <= 96:
        r = [12, dist - 65, 5];
        break;
      case dist <= 128:
        r = [13, dist - 97, 5];
        break;
      case dist <= 192:
        r = [14, dist - 129, 6];
        break;
      case dist <= 256:
        r = [15, dist - 193, 6];
        break;
      case dist <= 384:
        r = [16, dist - 257, 7];
        break;
      case dist <= 512:
        r = [17, dist - 385, 7];
        break;
      case dist <= 768:
        r = [18, dist - 513, 8];
        break;
      case dist <= 1024:
        r = [19, dist - 769, 8];
        break;
      case dist <= 1536:
        r = [20, dist - 1025, 9];
        break;
      case dist <= 2048:
        r = [21, dist - 1537, 9];
        break;
      case dist <= 3072:
        r = [22, dist - 2049, 10];
        break;
      case dist <= 4096:
        r = [23, dist - 3073, 10];
        break;
      case dist <= 6144:
        r = [24, dist - 4097, 11];
        break;
      case dist <= 8192:
        r = [25, dist - 6145, 11];
        break;
      case dist <= 12288:
        r = [26, dist - 8193, 12];
        break;
      case dist <= 16384:
        r = [27, dist - 12289, 12];
        break;
      case dist <= 24576:
        r = [28, dist - 16385, 13];
        break;
      case dist <= 32768:
        r = [29, dist - 24577, 13];
        break;
      default:
        throw"invalid distance";
    }
    return r
  };
  Zlib.RawDeflate.Lz77Match.prototype.toLz77Array = function() {
    var length = this.length;
    var dist = this.backwardDistance;
    var codeArray = [];
    var pos = 0;
    var code;
    code = Zlib.RawDeflate.Lz77Match.LengthCodeTable[length];
    codeArray[pos++] = code & 65535;
    codeArray[pos++] = code >> 16 & 255;
    codeArray[pos++] = code >> 24;
    code = this.getDistanceCode_(dist);
    codeArray[pos++] = code[0];
    codeArray[pos++] = code[1];
    codeArray[pos++] = code[2];
    return codeArray
  };
  Zlib.RawDeflate.prototype.lz77 = function(dataArray) {
    var position;
    var length;
    var i;
    var il;
    var matchKey;
    var table = {};
    var windowSize = Zlib.RawDeflate.WindowSize;
    var matchList;
    var longestMatch;
    var prevMatch;
    var lz77buf = USE_TYPEDARRAY ? new Uint16Array(dataArray.length * 2) : [];
    var pos = 0;
    var skipLength = 0;
    var freqsLitLen = new (USE_TYPEDARRAY ? Uint32Array : Array)(286);
    var freqsDist = new (USE_TYPEDARRAY ? Uint32Array : Array)(30);
    var lazy = this.lazy;
    var tmp;
    if(!USE_TYPEDARRAY) {
      for(i = 0;i <= 285;) {
        freqsLitLen[i++] = 0
      }
      for(i = 0;i <= 29;) {
        freqsDist[i++] = 0
      }
    }
    freqsLitLen[256] = 1;
    function writeMatch(match, offset) {
      var lz77Array = match.toLz77Array();
      var i;
      var il;
      for(i = 0, il = lz77Array.length;i < il;++i) {
        lz77buf[pos++] = lz77Array[i]
      }
      freqsLitLen[lz77Array[0]]++;
      freqsDist[lz77Array[3]]++;
      skipLength = match.length + offset - 1;
      prevMatch = null
    }
    for(position = 0, length = dataArray.length;position < length;++position) {
      for(matchKey = 0, i = 0, il = Zlib.RawDeflate.Lz77MinLength;i < il;++i) {
        if(position + i === length) {
          break
        }
        matchKey = matchKey << 8 | dataArray[position + i]
      }
      if(table[matchKey] === void 0) {
        table[matchKey] = []
      }
      matchList = table[matchKey];
      if(skipLength-- > 0) {
        matchList.push(position);
        continue
      }
      while(matchList.length > 0 && position - matchList[0] > windowSize) {
        matchList.shift()
      }
      if(position + Zlib.RawDeflate.Lz77MinLength >= length) {
        if(prevMatch) {
          writeMatch(prevMatch, -1)
        }
        for(i = 0, il = length - position;i < il;++i) {
          tmp = dataArray[position + i];
          lz77buf[pos++] = tmp;
          ++freqsLitLen[tmp]
        }
        break
      }
      if(matchList.length > 0) {
        longestMatch = this.searchLongestMatch_(dataArray, position, matchList);
        if(prevMatch) {
          if(prevMatch.length < longestMatch.length) {
            tmp = dataArray[position - 1];
            lz77buf[pos++] = tmp;
            ++freqsLitLen[tmp];
            writeMatch(longestMatch, 0)
          }else {
            writeMatch(prevMatch, -1)
          }
        }else {
          if(longestMatch.length < lazy) {
            prevMatch = longestMatch
          }else {
            writeMatch(longestMatch, 0)
          }
        }
      }else {
        if(prevMatch) {
          writeMatch(prevMatch, -1)
        }else {
          tmp = dataArray[position];
          lz77buf[pos++] = tmp;
          ++freqsLitLen[tmp]
        }
      }
      matchList.push(position)
    }
    lz77buf[pos++] = 256;
    freqsLitLen[256]++;
    this.freqsLitLen = freqsLitLen;
    this.freqsDist = freqsDist;
    return(USE_TYPEDARRAY ? lz77buf.subarray(0, pos) : lz77buf)
  };
  Zlib.RawDeflate.prototype.searchLongestMatch_ = function(data, position, matchList) {
    var match, currentMatch, matchMax = 0, matchLength, i, j, l, dl = data.length;
    permatch:for(i = 0, l = matchList.length;i < l;i++) {
      match = matchList[l - i - 1];
      matchLength = Zlib.RawDeflate.Lz77MinLength;
      if(matchMax > Zlib.RawDeflate.Lz77MinLength) {
        for(j = matchMax;j > Zlib.RawDeflate.Lz77MinLength;j--) {
          if(data[match + j - 1] !== data[position + j - 1]) {
            continue permatch
          }
        }
        matchLength = matchMax
      }
      while(matchLength < Zlib.RawDeflate.Lz77MaxLength && position + matchLength < dl && data[match + matchLength] === data[position + matchLength]) {
        ++matchLength
      }
      if(matchLength > matchMax) {
        currentMatch = match;
        matchMax = matchLength
      }
      if(matchLength === Zlib.RawDeflate.Lz77MaxLength) {
        break
      }
    }
    return new Zlib.RawDeflate.Lz77Match(matchMax, position - currentMatch)
  };
  Zlib.RawDeflate.prototype.getTreeSymbols_ = function(hlit, litlenLengths, hdist, distLengths) {
    var src = new (USE_TYPEDARRAY ? Uint32Array : Array)(hlit + hdist), i, j, runLength, l, result = new (USE_TYPEDARRAY ? Uint32Array : Array)(286 + 30), nResult, rpt, freqs = new (USE_TYPEDARRAY ? Uint8Array : Array)(19);
    j = 0;
    for(i = 0;i < hlit;i++) {
      src[j++] = litlenLengths[i]
    }
    for(i = 0;i < hdist;i++) {
      src[j++] = distLengths[i]
    }
    if(!USE_TYPEDARRAY) {
      for(i = 0, l = freqs.length;i < l;++i) {
        freqs[i] = 0
      }
    }
    nResult = 0;
    for(i = 0, l = src.length;i < l;i += j) {
      for(j = 1;i + j < l && src[i + j] === src[i];++j) {
      }
      runLength = j;
      if(src[i] === 0) {
        if(runLength < 3) {
          while(runLength-- > 0) {
            result[nResult++] = 0;
            freqs[0]++
          }
        }else {
          while(runLength > 0) {
            rpt = runLength < 138 ? runLength : 138;
            if(rpt > runLength - 3 && rpt < runLength) {
              rpt = runLength - 3
            }
            if(rpt <= 10) {
              result[nResult++] = 17;
              result[nResult++] = rpt - 3;
              freqs[17]++
            }else {
              result[nResult++] = 18;
              result[nResult++] = rpt - 11;
              freqs[18]++
            }
            runLength -= rpt
          }
        }
      }else {
        result[nResult++] = src[i];
        freqs[src[i]]++;
        runLength--;
        if(runLength < 3) {
          while(runLength-- > 0) {
            result[nResult++] = src[i];
            freqs[src[i]]++
          }
        }else {
          while(runLength > 0) {
            rpt = runLength < 6 ? runLength : 6;
            if(rpt > runLength - 3 && rpt < runLength) {
              rpt = runLength - 3
            }
            result[nResult++] = 16;
            result[nResult++] = rpt - 3;
            freqs[16]++;
            runLength -= rpt
          }
        }
      }
    }
    return{codes:USE_TYPEDARRAY ? result.subarray(0, nResult) : result.slice(0, nResult), freqs:freqs}
  };
  Zlib.RawDeflate.prototype.getLengths_ = function(freqs, limit) {
    var nSymbols = freqs.length;
    var heap = new Zlib.Heap(2 * Zlib.RawDeflate.HUFMAX);
    var length = new (USE_TYPEDARRAY ? Uint8Array : Array)(nSymbols);
    var nodes;
    var values;
    var codeLength;
    var i;
    var il;
    if(!USE_TYPEDARRAY) {
      for(i = 0;i < nSymbols;i++) {
        length[i] = 0
      }
    }
    for(i = 0;i < nSymbols;++i) {
      if(freqs[i] > 0) {
        heap.push(i, freqs[i])
      }
    }
    nodes = new Array(heap.length / 2);
    values = new (USE_TYPEDARRAY ? Uint32Array : Array)(heap.length / 2);
    if(nodes.length === 1) {
      length[heap.pop().index] = 1;
      return length
    }
    for(i = 0, il = heap.length / 2;i < il;++i) {
      nodes[i] = heap.pop();
      values[i] = nodes[i].value
    }
    codeLength = this.reversePackageMerge_(values, values.length, limit);
    for(i = 0, il = nodes.length;i < il;++i) {
      length[nodes[i].index] = codeLength[i]
    }
    return length
  };
  Zlib.RawDeflate.prototype.reversePackageMerge_ = function(freqs, symbols, limit) {
    var minimumCost = new (USE_TYPEDARRAY ? Uint16Array : Array)(limit);
    var flag = new (USE_TYPEDARRAY ? Uint8Array : Array)(limit);
    var codeLength = new (USE_TYPEDARRAY ? Uint8Array : Array)(symbols);
    var value = new Array(limit);
    var type = new Array(limit);
    var currentPosition = new Array(limit);
    var excess = (1 << limit) - symbols;
    var half = 1 << limit - 1;
    var i;
    var j;
    var t;
    var weight;
    var next;
    function takePackage(j) {
      var x = type[j][currentPosition[j]];
      if(x === symbols) {
        takePackage(j + 1);
        takePackage(j + 1)
      }else {
        --codeLength[x]
      }
      ++currentPosition[j]
    }
    minimumCost[limit - 1] = symbols;
    for(j = 0;j < limit;++j) {
      if(excess < half) {
        flag[j] = 0
      }else {
        flag[j] = 1;
        excess -= half
      }
      excess <<= 1;
      minimumCost[limit - 2 - j] = (minimumCost[limit - 1 - j] / 2 | 0) + symbols
    }
    minimumCost[0] = flag[0];
    value[0] = new Array(minimumCost[0]);
    type[0] = new Array(minimumCost[0]);
    for(j = 1;j < limit;++j) {
      if(minimumCost[j] > 2 * minimumCost[j - 1] + flag[j]) {
        minimumCost[j] = 2 * minimumCost[j - 1] + flag[j]
      }
      value[j] = new Array(minimumCost[j]);
      type[j] = new Array(minimumCost[j])
    }
    for(i = 0;i < symbols;++i) {
      codeLength[i] = limit
    }
    for(t = 0;t < minimumCost[limit - 1];++t) {
      value[limit - 1][t] = freqs[t];
      type[limit - 1][t] = t
    }
    for(i = 0;i < limit;++i) {
      currentPosition[i] = 0
    }
    if(flag[limit - 1] === 1) {
      --codeLength[0];
      ++currentPosition[limit - 1]
    }
    for(j = limit - 2;j >= 0;--j) {
      i = 0;
      weight = 0;
      next = currentPosition[j + 1];
      for(t = 0;t < minimumCost[j];t++) {
        weight = value[j + 1][next] + value[j + 1][next + 1];
        if(weight > freqs[i]) {
          value[j][t] = weight;
          type[j][t] = symbols;
          next += 2
        }else {
          value[j][t] = freqs[i];
          type[j][t] = i;
          ++i
        }
      }
      currentPosition[j] = 0;
      if(flag[j] === 1) {
        takePackage(j)
      }
    }
    return codeLength
  };
  Zlib.RawDeflate.prototype.getCodesFromLengths_ = function(lengths) {
    var codes = new (USE_TYPEDARRAY ? Uint16Array : Array)(lengths.length), count = [], startCode = [], code = 0, i, il, j, m;
    for(i = 0, il = lengths.length;i < il;i++) {
      count[lengths[i]] = (count[lengths[i]] | 0) + 1
    }
    for(i = 1, il = Zlib.RawDeflate.MaxCodeLength;i <= il;i++) {
      startCode[i] = code;
      code += count[i] | 0;
      code <<= 1
    }
    for(i = 0, il = lengths.length;i < il;i++) {
      code = startCode[lengths[i]];
      startCode[lengths[i]] += 1;
      codes[i] = 0;
      for(j = 0, m = lengths[i];j < m;j++) {
        codes[i] = codes[i] << 1 | code & 1;
        code >>>= 1
      }
    }
    return codes
  }
});
goog.provide("Zlib.Gzip");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.CRC32");
goog.require("Zlib.RawDeflate");
goog.scope(function() {
  Zlib.Gzip = function(input, opt_params) {
    this.input = input;
    this.ip = 0;
    this.output;
    this.op = 0;
    this.flags = {};
    this.filename;
    this.comment;
    this.deflateOptions;
    if(opt_params) {
      if(opt_params["flags"]) {
        this.flags = opt_params["flags"]
      }
      if(typeof opt_params["filename"] === "string") {
        this.filename = opt_params["filename"]
      }
      if(typeof opt_params["comment"] === "string") {
        this.comment = opt_params["comment"]
      }
      if(opt_params["deflateOptions"]) {
        this.deflateOptions = opt_params["deflateOptions"]
      }
    }
    if(!this.deflateOptions) {
      this.deflateOptions = {}
    }
  };
  Zlib.Gzip.DefaultBufferSize = 32768;
  Zlib.Gzip.prototype.compress = function() {
    var flg;
    var mtime;
    var crc16;
    var crc32;
    var rawdeflate;
    var c;
    var i;
    var il;
    var output = new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.Gzip.DefaultBufferSize);
    var op = 0;
    var input = this.input;
    var ip = this.ip;
    var filename = this.filename;
    var comment = this.comment;
    output[op++] = 31;
    output[op++] = 139;
    output[op++] = 8;
    flg = 0;
    if(this.flags["fname"]) {
      flg |= Zlib.Gzip.FlagsMask.FNAME
    }
    if(this.flags["fcomment"]) {
      flg |= Zlib.Gzip.FlagsMask.FCOMMENT
    }
    if(this.flags["fhcrc"]) {
      flg |= Zlib.Gzip.FlagsMask.FHCRC
    }
    output[op++] = flg;
    mtime = (Date.now ? Date.now() : +new Date) / 1E3 | 0;
    output[op++] = mtime & 255;
    output[op++] = mtime >>> 8 & 255;
    output[op++] = mtime >>> 16 & 255;
    output[op++] = mtime >>> 24 & 255;
    output[op++] = 0;
    output[op++] = Zlib.Gzip.OperatingSystem.UNKNOWN;
    if(this.flags["fname"] !== void 0) {
      for(i = 0, il = filename.length;i < il;++i) {
        c = filename.charCodeAt(i);
        if(c > 255) {
          output[op++] = c >>> 8 & 255
        }
        output[op++] = c & 255
      }
      output[op++] = 0
    }
    if(this.flags["comment"]) {
      for(i = 0, il = comment.length;i < il;++i) {
        c = comment.charCodeAt(i);
        if(c > 255) {
          output[op++] = c >>> 8 & 255
        }
        output[op++] = c & 255
      }
      output[op++] = 0
    }
    if(this.flags["fhcrc"]) {
      crc16 = Zlib.CRC32.calc(output, 0, op) & 65535;
      output[op++] = crc16 & 255;
      output[op++] = crc16 >>> 8 & 255
    }
    this.deflateOptions["outputBuffer"] = output;
    this.deflateOptions["outputIndex"] = op;
    rawdeflate = new Zlib.RawDeflate(input, this.deflateOptions);
    output = rawdeflate.compress();
    op = rawdeflate.op;
    if(USE_TYPEDARRAY) {
      if(op + 8 > output.buffer.byteLength) {
        this.output = new Uint8Array(op + 8);
        this.output.set(new Uint8Array(output.buffer));
        output = this.output
      }else {
        output = new Uint8Array(output.buffer)
      }
    }
    crc32 = Zlib.CRC32.calc(input);
    output[op++] = crc32 & 255;
    output[op++] = crc32 >>> 8 & 255;
    output[op++] = crc32 >>> 16 & 255;
    output[op++] = crc32 >>> 24 & 255;
    il = input.length;
    output[op++] = il & 255;
    output[op++] = il >>> 8 & 255;
    output[op++] = il >>> 16 & 255;
    output[op++] = il >>> 24 & 255;
    this.ip = ip;
    if(USE_TYPEDARRAY && op < output.length) {
      this.output = output = output.subarray(0, op)
    }
    return output
  };
  Zlib.Gzip.OperatingSystem = {FAT:0, AMIGA:1, VMS:2, UNIX:3, VM_CMS:4, ATARI_TOS:5, HPFS:6, MACINTOSH:7, Z_SYSTEM:8, CP_M:9, TOPS_20:10, NTFS:11, QDOS:12, ACORN_RISCOS:13, UNKNOWN:255};
  Zlib.Gzip.FlagsMask = {FTEXT:1, FHCRC:2, FEXTRA:4, FNAME:8, FCOMMENT:16}
});
goog.provide("Zlib.RawInflate");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.Huffman");
var ZLIB_RAW_INFLATE_BUFFER_SIZE = 32768;
goog.scope(function() {
  var buildHuffmanTable = Zlib.Huffman.buildHuffmanTable;
  Zlib.RawInflate = function(input, opt_params) {
    this.buffer;
    this.blocks = [];
    this.bufferSize = ZLIB_RAW_INFLATE_BUFFER_SIZE;
    this.totalpos = 0;
    this.ip = 0;
    this.bitsbuf = 0;
    this.bitsbuflen = 0;
    this.input = USE_TYPEDARRAY ? new Uint8Array(input) : input;
    this.output;
    this.op;
    this.bfinal = false;
    this.bufferType = Zlib.RawInflate.BufferType.ADAPTIVE;
    this.resize = false;
    this.prev;
    if(opt_params || !(opt_params = {})) {
      if(opt_params["index"]) {
        this.ip = opt_params["index"]
      }
      if(opt_params["bufferSize"]) {
        this.bufferSize = opt_params["bufferSize"]
      }
      if(opt_params["bufferType"]) {
        this.bufferType = opt_params["bufferType"]
      }
      if(opt_params["resize"]) {
        this.resize = opt_params["resize"]
      }
    }
    switch(this.bufferType) {
      case Zlib.RawInflate.BufferType.BLOCK:
        this.op = Zlib.RawInflate.MaxBackwardLength;
        this.output = new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.RawInflate.MaxBackwardLength + this.bufferSize + Zlib.RawInflate.MaxCopyLength);
        break;
      case Zlib.RawInflate.BufferType.ADAPTIVE:
        this.op = 0;
        this.output = new (USE_TYPEDARRAY ? Uint8Array : Array)(this.bufferSize);
        this.expandBuffer = this.expandBufferAdaptive;
        this.concatBuffer = this.concatBufferDynamic;
        this.decodeHuffman = this.decodeHuffmanAdaptive;
        break;
      default:
        throw new Error("invalid inflate mode");
    }
  };
  Zlib.RawInflate.BufferType = {BLOCK:0, ADAPTIVE:1};
  Zlib.RawInflate.prototype.decompress = function() {
    while(!this.bfinal) {
      this.parseBlock()
    }
    return this.concatBuffer()
  };
  Zlib.RawInflate.MaxBackwardLength = 32768;
  Zlib.RawInflate.MaxCopyLength = 258;
  Zlib.RawInflate.Order = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]);
  Zlib.RawInflate.LengthCodeTable = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258, 258, 258]);
  Zlib.RawInflate.LengthExtraTable = function(table) {
    return USE_TYPEDARRAY ? new Uint8Array(table) : table
  }([0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0, 0, 0]);
  Zlib.RawInflate.DistCodeTable = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]);
  Zlib.RawInflate.DistExtraTable = function(table) {
    return USE_TYPEDARRAY ? new Uint8Array(table) : table
  }([0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]);
  Zlib.RawInflate.FixedLiteralLengthTable = function(table) {
    return table
  }(function() {
    var lengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(288);
    var i, il;
    for(i = 0, il = lengths.length;i < il;++i) {
      lengths[i] = i <= 143 ? 8 : i <= 255 ? 9 : i <= 279 ? 7 : 8
    }
    return buildHuffmanTable(lengths)
  }());
  Zlib.RawInflate.FixedDistanceTable = function(table) {
    return table
  }(function() {
    var lengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(30);
    var i, il;
    for(i = 0, il = lengths.length;i < il;++i) {
      lengths[i] = 5
    }
    return buildHuffmanTable(lengths)
  }());
  Zlib.RawInflate.prototype.parseBlock = function() {
    var hdr = this.readBits(3);
    if(hdr & 1) {
      this.bfinal = true
    }
    hdr >>>= 1;
    switch(hdr) {
      case 0:
        this.parseUncompressedBlock();
        break;
      case 1:
        this.parseFixedHuffmanBlock();
        break;
      case 2:
        this.parseDynamicHuffmanBlock();
        break;
      default:
        throw new Error("unknown BTYPE: " + hdr);
    }
  };
  Zlib.RawInflate.prototype.readBits = function(length) {
    var bitsbuf = this.bitsbuf;
    var bitsbuflen = this.bitsbuflen;
    var input = this.input;
    var ip = this.ip;
    var inputLength = input.length;
    var octet;
    while(bitsbuflen < length) {
      if(ip >= inputLength) {
        throw new Error("input buffer is broken");
      }
      bitsbuf |= input[ip++] << bitsbuflen;
      bitsbuflen += 8
    }
    octet = bitsbuf & (1 << length) - 1;
    bitsbuf >>>= length;
    bitsbuflen -= length;
    this.bitsbuf = bitsbuf;
    this.bitsbuflen = bitsbuflen;
    this.ip = ip;
    return octet
  };
  Zlib.RawInflate.prototype.readCodeByTable = function(table) {
    var bitsbuf = this.bitsbuf;
    var bitsbuflen = this.bitsbuflen;
    var input = this.input;
    var ip = this.ip;
    var inputLength = input.length;
    var codeTable = table[0];
    var maxCodeLength = table[1];
    var codeWithLength;
    var codeLength;
    while(bitsbuflen < maxCodeLength) {
      if(ip >= inputLength) {
        break
      }
      bitsbuf |= input[ip++] << bitsbuflen;
      bitsbuflen += 8
    }
    codeWithLength = codeTable[bitsbuf & (1 << maxCodeLength) - 1];
    codeLength = codeWithLength >>> 16;
    this.bitsbuf = bitsbuf >> codeLength;
    this.bitsbuflen = bitsbuflen - codeLength;
    this.ip = ip;
    return codeWithLength & 65535
  };
  Zlib.RawInflate.prototype.parseUncompressedBlock = function() {
    var input = this.input;
    var ip = this.ip;
    var output = this.output;
    var op = this.op;
    var inputLength = input.length;
    var len;
    var nlen;
    var olength = output.length;
    var preCopy;
    this.bitsbuf = 0;
    this.bitsbuflen = 0;
    if(ip + 1 >= inputLength) {
      throw new Error("invalid uncompressed block header: LEN");
    }
    len = input[ip++] | input[ip++] << 8;
    if(ip + 1 >= inputLength) {
      throw new Error("invalid uncompressed block header: NLEN");
    }
    nlen = input[ip++] | input[ip++] << 8;
    if(len === ~nlen) {
      throw new Error("invalid uncompressed block header: length verify");
    }
    if(ip + len > input.length) {
      throw new Error("input buffer is broken");
    }
    switch(this.bufferType) {
      case Zlib.RawInflate.BufferType.BLOCK:
        while(op + len > output.length) {
          preCopy = olength - op;
          len -= preCopy;
          if(USE_TYPEDARRAY) {
            output.set(input.subarray(ip, ip + preCopy), op);
            op += preCopy;
            ip += preCopy
          }else {
            while(preCopy--) {
              output[op++] = input[ip++]
            }
          }
          this.op = op;
          output = this.expandBuffer();
          op = this.op
        }
        break;
      case Zlib.RawInflate.BufferType.ADAPTIVE:
        while(op + len > output.length) {
          output = this.expandBuffer({fixRatio:2})
        }
        break;
      default:
        throw new Error("invalid inflate mode");
    }
    if(USE_TYPEDARRAY) {
      output.set(input.subarray(ip, ip + len), op);
      op += len;
      ip += len
    }else {
      while(len--) {
        output[op++] = input[ip++]
      }
    }
    this.ip = ip;
    this.op = op;
    this.output = output
  };
  Zlib.RawInflate.prototype.parseFixedHuffmanBlock = function() {
    this.decodeHuffman(Zlib.RawInflate.FixedLiteralLengthTable, Zlib.RawInflate.FixedDistanceTable)
  };
  Zlib.RawInflate.prototype.parseDynamicHuffmanBlock = function() {
    var hlit = this.readBits(5) + 257;
    var hdist = this.readBits(5) + 1;
    var hclen = this.readBits(4) + 4;
    var codeLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.RawInflate.Order.length);
    var codeLengthsTable;
    var litlenLengths;
    var distLengths;
    var i;
    for(i = 0;i < hclen;++i) {
      codeLengths[Zlib.RawInflate.Order[i]] = this.readBits(3)
    }
    if(!USE_TYPEDARRAY) {
      for(i = hclen, hclen = codeLengths.length;i < hclen;++i) {
        codeLengths[Zlib.RawInflate.Order[i]] = 0
      }
    }
    codeLengthsTable = buildHuffmanTable(codeLengths);
    function decode(num, table, lengths) {
      var code;
      var prev = this.prev;
      var repeat;
      var i;
      for(i = 0;i < num;) {
        code = this.readCodeByTable(table);
        switch(code) {
          case 16:
            repeat = 3 + this.readBits(2);
            while(repeat--) {
              lengths[i++] = prev
            }
            break;
          case 17:
            repeat = 3 + this.readBits(3);
            while(repeat--) {
              lengths[i++] = 0
            }
            prev = 0;
            break;
          case 18:
            repeat = 11 + this.readBits(7);
            while(repeat--) {
              lengths[i++] = 0
            }
            prev = 0;
            break;
          default:
            lengths[i++] = code;
            prev = code;
            break
        }
      }
      this.prev = prev;
      return lengths
    }
    litlenLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(hlit);
    distLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(hdist);
    this.prev = 0;
    this.decodeHuffman(buildHuffmanTable(decode.call(this, hlit, codeLengthsTable, litlenLengths)), buildHuffmanTable(decode.call(this, hdist, codeLengthsTable, distLengths)))
  };
  Zlib.RawInflate.prototype.decodeHuffman = function(litlen, dist) {
    var output = this.output;
    var op = this.op;
    this.currentLitlenTable = litlen;
    var olength = output.length - Zlib.RawInflate.MaxCopyLength;
    var code;
    var ti;
    var codeDist;
    var codeLength;
    while((code = this.readCodeByTable(litlen)) !== 256) {
      if(code < 256) {
        if(op >= olength) {
          this.op = op;
          output = this.expandBuffer();
          op = this.op
        }
        output[op++] = code;
        continue
      }
      ti = code - 257;
      codeLength = Zlib.RawInflate.LengthCodeTable[ti];
      if(Zlib.RawInflate.LengthExtraTable[ti] > 0) {
        codeLength += this.readBits(Zlib.RawInflate.LengthExtraTable[ti])
      }
      code = this.readCodeByTable(dist);
      codeDist = Zlib.RawInflate.DistCodeTable[code];
      if(Zlib.RawInflate.DistExtraTable[code] > 0) {
        codeDist += this.readBits(Zlib.RawInflate.DistExtraTable[code])
      }
      if(op >= olength) {
        this.op = op;
        output = this.expandBuffer();
        op = this.op
      }
      while(codeLength--) {
        output[op] = output[op++ - codeDist]
      }
    }
    while(this.bitsbuflen >= 8) {
      this.bitsbuflen -= 8;
      this.ip--
    }
    this.op = op
  };
  Zlib.RawInflate.prototype.decodeHuffmanAdaptive = function(litlen, dist) {
    var output = this.output;
    var op = this.op;
    this.currentLitlenTable = litlen;
    var olength = output.length;
    var code;
    var ti;
    var codeDist;
    var codeLength;
    while((code = this.readCodeByTable(litlen)) !== 256) {
      if(code < 256) {
        if(op >= olength) {
          output = this.expandBuffer();
          olength = output.length
        }
        output[op++] = code;
        continue
      }
      ti = code - 257;
      codeLength = Zlib.RawInflate.LengthCodeTable[ti];
      if(Zlib.RawInflate.LengthExtraTable[ti] > 0) {
        codeLength += this.readBits(Zlib.RawInflate.LengthExtraTable[ti])
      }
      code = this.readCodeByTable(dist);
      codeDist = Zlib.RawInflate.DistCodeTable[code];
      if(Zlib.RawInflate.DistExtraTable[code] > 0) {
        codeDist += this.readBits(Zlib.RawInflate.DistExtraTable[code])
      }
      if(op + codeLength > olength) {
        output = this.expandBuffer();
        olength = output.length
      }
      while(codeLength--) {
        output[op] = output[op++ - codeDist]
      }
    }
    while(this.bitsbuflen >= 8) {
      this.bitsbuflen -= 8;
      this.ip--
    }
    this.op = op
  };
  Zlib.RawInflate.prototype.expandBuffer = function(opt_param) {
    var buffer = new (USE_TYPEDARRAY ? Uint8Array : Array)(this.op - Zlib.RawInflate.MaxBackwardLength);
    var backward = this.op - Zlib.RawInflate.MaxBackwardLength;
    var i;
    var il;
    var output = this.output;
    if(USE_TYPEDARRAY) {
      buffer.set(output.subarray(Zlib.RawInflate.MaxBackwardLength, buffer.length))
    }else {
      for(i = 0, il = buffer.length;i < il;++i) {
        buffer[i] = output[i + Zlib.RawInflate.MaxBackwardLength]
      }
    }
    this.blocks.push(buffer);
    this.totalpos += buffer.length;
    if(USE_TYPEDARRAY) {
      output.set(output.subarray(backward, backward + Zlib.RawInflate.MaxBackwardLength))
    }else {
      for(i = 0;i < Zlib.RawInflate.MaxBackwardLength;++i) {
        output[i] = output[backward + i]
      }
    }
    this.op = Zlib.RawInflate.MaxBackwardLength;
    return output
  };
  Zlib.RawInflate.prototype.expandBufferAdaptive = function(opt_param) {
    var buffer;
    var ratio = this.input.length / this.ip + 1 | 0;
    var maxHuffCode;
    var newSize;
    var maxInflateSize;
    var input = this.input;
    var output = this.output;
    if(opt_param) {
      if(typeof opt_param.fixRatio === "number") {
        ratio = opt_param.fixRatio
      }
      if(typeof opt_param.addRatio === "number") {
        ratio += opt_param.addRatio
      }
    }
    if(ratio < 2) {
      maxHuffCode = (input.length - this.ip) / this.currentLitlenTable[2];
      maxInflateSize = maxHuffCode / 2 * 258 | 0;
      newSize = maxInflateSize < output.length ? output.length + maxInflateSize : output.length << 1
    }else {
      newSize = output.length * ratio
    }
    if(USE_TYPEDARRAY) {
      buffer = new Uint8Array(newSize);
      buffer.set(output)
    }else {
      buffer = output
    }
    this.output = buffer;
    return this.output
  };
  Zlib.RawInflate.prototype.concatBuffer = function() {
    var pos = 0;
    var limit = this.totalpos + (this.op - Zlib.RawInflate.MaxBackwardLength);
    var output = this.output;
    var blocks = this.blocks;
    var block;
    var buffer = new (USE_TYPEDARRAY ? Uint8Array : Array)(limit);
    var i;
    var il;
    var j;
    var jl;
    if(blocks.length === 0) {
      return USE_TYPEDARRAY ? this.output.subarray(Zlib.RawInflate.MaxBackwardLength, this.op) : this.output.slice(Zlib.RawInflate.MaxBackwardLength, this.op)
    }
    for(i = 0, il = blocks.length;i < il;++i) {
      block = blocks[i];
      for(j = 0, jl = block.length;j < jl;++j) {
        buffer[pos++] = block[j]
      }
    }
    for(i = Zlib.RawInflate.MaxBackwardLength, il = this.op;i < il;++i) {
      buffer[pos++] = output[i]
    }
    this.blocks = [];
    this.buffer = buffer;
    return this.buffer
  };
  Zlib.RawInflate.prototype.concatBufferDynamic = function() {
    var buffer;
    var op = this.op;
    if(USE_TYPEDARRAY) {
      if(this.resize) {
        buffer = new Uint8Array(op);
        buffer.set(this.output.subarray(0, op))
      }else {
        buffer = this.output.subarray(0, op)
      }
    }else {
      if(this.output.length > op) {
        this.output.length = op
      }
      buffer = this.output
    }
    this.buffer = buffer;
    return this.buffer
  }
});
goog.provide("Zlib.Gunzip");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.CRC32");
goog.require("Zlib.Gzip");
goog.require("Zlib.RawInflate");
goog.require("Zlib.GunzipMember");
goog.scope(function() {
  Zlib.Gunzip = function(input, opt_params) {
    this.input = input;
    this.ip = 0;
    this.member = [];
    this.decompressed = false
  };
  Zlib.Gunzip.prototype.getMembers = function() {
    if(!this.decompressed) {
      this.decompress()
    }
    return this.member.slice()
  };
  Zlib.Gunzip.prototype.decompress = function() {
    var il = this.input.length;
    while(this.ip < il) {
      this.decodeMember()
    }
    this.decompressed = true;
    return this.concatMember()
  };
  Zlib.Gunzip.prototype.decodeMember = function() {
    var member = new Zlib.GunzipMember;
    var isize;
    var rawinflate;
    var inflated;
    var inflen;
    var c;
    var ci;
    var str;
    var mtime;
    var crc32;
    var input = this.input;
    var ip = this.ip;
    member.id1 = input[ip++];
    member.id2 = input[ip++];
    if(member.id1 !== 31 || member.id2 !== 139) {
      throw new Error("invalid file signature:" + member.id1 + "," + member.id2);
    }
    member.cm = input[ip++];
    switch(member.cm) {
      case 8:
        break;
      default:
        throw new Error("unknown compression method: " + member.cm);
    }
    member.flg = input[ip++];
    mtime = input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24;
    member.mtime = new Date(mtime * 1E3);
    member.xfl = input[ip++];
    member.os = input[ip++];
    if((member.flg & Zlib.Gzip.FlagsMask.FEXTRA) > 0) {
      member.xlen = input[ip++] | input[ip++] << 8;
      ip = this.decodeSubField(ip, member.xlen)
    }
    if((member.flg & Zlib.Gzip.FlagsMask.FNAME) > 0) {
      for(str = [], ci = 0;(c = input[ip++]) > 0;) {
        str[ci++] = String.fromCharCode(c)
      }
      member.name = str.join("")
    }
    if((member.flg & Zlib.Gzip.FlagsMask.FCOMMENT) > 0) {
      for(str = [], ci = 0;(c = input[ip++]) > 0;) {
        str[ci++] = String.fromCharCode(c)
      }
      member.comment = str.join("")
    }
    if((member.flg & Zlib.Gzip.FlagsMask.FHCRC) > 0) {
      member.crc16 = Zlib.CRC32.calc(input, 0, ip) & 65535;
      if(member.crc16 !== (input[ip++] | input[ip++] << 8)) {
        throw new Error("invalid header crc16");
      }
    }
    isize = input[input.length - 4] | input[input.length - 3] << 8 | input[input.length - 2] << 16 | input[input.length - 1] << 24;
    if(input.length - ip - 4 - 4 < isize * 512) {
      inflen = isize
    }
    rawinflate = new Zlib.RawInflate(input, {"index":ip, "bufferSize":inflen});
    member.data = inflated = rawinflate.decompress();
    ip = rawinflate.ip;
    member.crc32 = crc32 = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    if(Zlib.CRC32.calc(inflated) !== crc32) {
      throw new Error("invalid CRC-32 checksum: 0x" + Zlib.CRC32.calc(inflated).toString(16) + " / 0x" + crc32.toString(16));
    }
    member.isize = isize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    if((inflated.length & 4294967295) !== isize) {
      throw new Error("invalid input size: " + (inflated.length & 4294967295) + " / " + isize);
    }
    this.member.push(member);
    this.ip = ip
  };
  Zlib.Gunzip.prototype.decodeSubField = function(ip, length) {
    return ip + length
  };
  Zlib.Gunzip.prototype.concatMember = function() {
    var member = this.member;
    var i;
    var il;
    var p = 0;
    var size = 0;
    var buffer;
    for(i = 0, il = member.length;i < il;++i) {
      size += member[i].data.length
    }
    if(USE_TYPEDARRAY) {
      buffer = new Uint8Array(size);
      for(i = 0;i < il;++i) {
        buffer.set(member[i].data, p);
        p += member[i].data.length
      }
    }else {
      buffer = [];
      for(i = 0;i < il;++i) {
        buffer[i] = member[i].data
      }
      buffer = Array.prototype.concat.apply([], buffer)
    }
    return buffer
  }
});
goog.provide("Zlib.RawInflateStream");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.Huffman");
var ZLIB_STREAM_RAW_INFLATE_BUFFER_SIZE = 32768;
goog.scope(function() {
  var buildHuffmanTable = Zlib.Huffman.buildHuffmanTable;
  Zlib.RawInflateStream = function(input, ip, opt_buffersize) {
    this.buffer;
    this.blocks = [];
    this.bufferSize = opt_buffersize ? opt_buffersize : ZLIB_STREAM_RAW_INFLATE_BUFFER_SIZE;
    this.totalpos = 0;
    this.ip = ip === void 0 ? 0 : ip;
    this.bitsbuf = 0;
    this.bitsbuflen = 0;
    this.input = USE_TYPEDARRAY ? new Uint8Array(input) : input;
    this.output = new (USE_TYPEDARRAY ? Uint8Array : Array)(this.bufferSize);
    this.op = 0;
    this.bfinal = false;
    this.blockLength;
    this.resize = false;
    this.litlenTable;
    this.distTable;
    this.sp = 0;
    this.status = Zlib.RawInflateStream.Status.INITIALIZED;
    this.prev;
    this.ip_;
    this.bitsbuflen_;
    this.bitsbuf_
  };
  Zlib.RawInflateStream.BlockType = {UNCOMPRESSED:0, FIXED:1, DYNAMIC:2};
  Zlib.RawInflateStream.Status = {INITIALIZED:0, BLOCK_HEADER_START:1, BLOCK_HEADER_END:2, BLOCK_BODY_START:3, BLOCK_BODY_END:4, DECODE_BLOCK_START:5, DECODE_BLOCK_END:6};
  Zlib.RawInflateStream.prototype.decompress = function(newInput, ip) {
    var stop = false;
    if(newInput !== void 0) {
      this.input = newInput
    }
    if(ip !== void 0) {
      this.ip = ip
    }
    while(!stop) {
      switch(this.status) {
        case Zlib.RawInflateStream.Status.INITIALIZED:
        ;
        case Zlib.RawInflateStream.Status.BLOCK_HEADER_START:
          if(this.readBlockHeader() < 0) {
            stop = true
          }
          break;
        case Zlib.RawInflateStream.Status.BLOCK_HEADER_END:
        ;
        case Zlib.RawInflateStream.Status.BLOCK_BODY_START:
          switch(this.currentBlockType) {
            case Zlib.RawInflateStream.BlockType.UNCOMPRESSED:
              if(this.readUncompressedBlockHeader() < 0) {
                stop = true
              }
              break;
            case Zlib.RawInflateStream.BlockType.FIXED:
              if(this.parseFixedHuffmanBlock() < 0) {
                stop = true
              }
              break;
            case Zlib.RawInflateStream.BlockType.DYNAMIC:
              if(this.parseDynamicHuffmanBlock() < 0) {
                stop = true
              }
              break
          }
          break;
        case Zlib.RawInflateStream.Status.BLOCK_BODY_END:
        ;
        case Zlib.RawInflateStream.Status.DECODE_BLOCK_START:
          switch(this.currentBlockType) {
            case Zlib.RawInflateStream.BlockType.UNCOMPRESSED:
              if(this.parseUncompressedBlock() < 0) {
                stop = true
              }
              break;
            case Zlib.RawInflateStream.BlockType.FIXED:
            ;
            case Zlib.RawInflateStream.BlockType.DYNAMIC:
              if(this.decodeHuffman() < 0) {
                stop = true
              }
              break
          }
          break;
        case Zlib.RawInflateStream.Status.DECODE_BLOCK_END:
          if(this.bfinal) {
            stop = true
          }else {
            this.status = Zlib.RawInflateStream.Status.INITIALIZED
          }
          break
      }
    }
    return this.concatBuffer()
  };
  Zlib.RawInflateStream.MaxBackwardLength = 32768;
  Zlib.RawInflateStream.MaxCopyLength = 258;
  Zlib.RawInflateStream.Order = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]);
  Zlib.RawInflateStream.LengthCodeTable = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258, 258, 258]);
  Zlib.RawInflateStream.LengthExtraTable = function(table) {
    return USE_TYPEDARRAY ? new Uint8Array(table) : table
  }([0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0, 0, 0]);
  Zlib.RawInflateStream.DistCodeTable = function(table) {
    return USE_TYPEDARRAY ? new Uint16Array(table) : table
  }([1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]);
  Zlib.RawInflateStream.DistExtraTable = function(table) {
    return USE_TYPEDARRAY ? new Uint8Array(table) : table
  }([0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13]);
  Zlib.RawInflateStream.FixedLiteralLengthTable = function(table) {
    return table
  }(function() {
    var lengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(288);
    var i, il;
    for(i = 0, il = lengths.length;i < il;++i) {
      lengths[i] = i <= 143 ? 8 : i <= 255 ? 9 : i <= 279 ? 7 : 8
    }
    return buildHuffmanTable(lengths)
  }());
  Zlib.RawInflateStream.FixedDistanceTable = function(table) {
    return table
  }(function() {
    var lengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(30);
    var i, il;
    for(i = 0, il = lengths.length;i < il;++i) {
      lengths[i] = 5
    }
    return buildHuffmanTable(lengths)
  }());
  Zlib.RawInflateStream.prototype.readBlockHeader = function() {
    var hdr;
    this.status = Zlib.RawInflateStream.Status.BLOCK_HEADER_START;
    this.save_();
    if((hdr = this.readBits(3)) < 0) {
      this.restore_();
      return-1
    }
    if(hdr & 1) {
      this.bfinal = true
    }
    hdr >>>= 1;
    switch(hdr) {
      case 0:
        this.currentBlockType = Zlib.RawInflateStream.BlockType.UNCOMPRESSED;
        break;
      case 1:
        this.currentBlockType = Zlib.RawInflateStream.BlockType.FIXED;
        break;
      case 2:
        this.currentBlockType = Zlib.RawInflateStream.BlockType.DYNAMIC;
        break;
      default:
        throw new Error("unknown BTYPE: " + hdr);
    }
    this.status = Zlib.RawInflateStream.Status.BLOCK_HEADER_END
  };
  Zlib.RawInflateStream.prototype.readBits = function(length) {
    var bitsbuf = this.bitsbuf;
    var bitsbuflen = this.bitsbuflen;
    var input = this.input;
    var ip = this.ip;
    var octet;
    while(bitsbuflen < length) {
      if(input.length <= ip) {
        return-1
      }
      octet = input[ip++];
      bitsbuf |= octet << bitsbuflen;
      bitsbuflen += 8
    }
    octet = bitsbuf & (1 << length) - 1;
    bitsbuf >>>= length;
    bitsbuflen -= length;
    this.bitsbuf = bitsbuf;
    this.bitsbuflen = bitsbuflen;
    this.ip = ip;
    return octet
  };
  Zlib.RawInflateStream.prototype.readCodeByTable = function(table) {
    var bitsbuf = this.bitsbuf;
    var bitsbuflen = this.bitsbuflen;
    var input = this.input;
    var ip = this.ip;
    var codeTable = table[0];
    var maxCodeLength = table[1];
    var octet;
    var codeWithLength;
    var codeLength;
    while(bitsbuflen < maxCodeLength) {
      if(input.length <= ip) {
        return-1
      }
      octet = input[ip++];
      bitsbuf |= octet << bitsbuflen;
      bitsbuflen += 8
    }
    codeWithLength = codeTable[bitsbuf & (1 << maxCodeLength) - 1];
    codeLength = codeWithLength >>> 16;
    this.bitsbuf = bitsbuf >> codeLength;
    this.bitsbuflen = bitsbuflen - codeLength;
    this.ip = ip;
    return codeWithLength & 65535
  };
  Zlib.RawInflateStream.prototype.readUncompressedBlockHeader = function() {
    var len;
    var nlen;
    var input = this.input;
    var ip = this.ip;
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_START;
    if(ip + 4 >= input.length) {
      return-1
    }
    len = input[ip++] | input[ip++] << 8;
    nlen = input[ip++] | input[ip++] << 8;
    if(len === ~nlen) {
      throw new Error("invalid uncompressed block header: length verify");
    }
    this.bitsbuf = 0;
    this.bitsbuflen = 0;
    this.ip = ip;
    this.blockLength = len;
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_END
  };
  Zlib.RawInflateStream.prototype.parseUncompressedBlock = function() {
    var input = this.input;
    var ip = this.ip;
    var output = this.output;
    var op = this.op;
    var len = this.blockLength;
    this.status = Zlib.RawInflateStream.Status.DECODE_BLOCK_START;
    while(len--) {
      if(op === output.length) {
        output = this.expandBuffer({fixRatio:2})
      }
      if(ip >= input.length) {
        this.ip = ip;
        this.op = op;
        this.blockLength = len + 1;
        return-1
      }
      output[op++] = input[ip++]
    }
    if(len < 0) {
      this.status = Zlib.RawInflateStream.Status.DECODE_BLOCK_END
    }
    this.ip = ip;
    this.op = op;
    return 0
  };
  Zlib.RawInflateStream.prototype.parseFixedHuffmanBlock = function() {
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_START;
    this.litlenTable = Zlib.RawInflateStream.FixedLiteralLengthTable;
    this.distTable = Zlib.RawInflateStream.FixedDistanceTable;
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_END;
    return 0
  };
  Zlib.RawInflateStream.prototype.save_ = function() {
    this.ip_ = this.ip;
    this.bitsbuflen_ = this.bitsbuflen;
    this.bitsbuf_ = this.bitsbuf
  };
  Zlib.RawInflateStream.prototype.restore_ = function() {
    this.ip = this.ip_;
    this.bitsbuflen = this.bitsbuflen_;
    this.bitsbuf = this.bitsbuf_
  };
  Zlib.RawInflateStream.prototype.parseDynamicHuffmanBlock = function() {
    var hlit;
    var hdist;
    var hclen;
    var codeLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.RawInflateStream.Order.length);
    var codeLengthsTable;
    var litlenLengths;
    var distLengths;
    var i = 0;
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_START;
    this.save_();
    hlit = this.readBits(5) + 257;
    hdist = this.readBits(5) + 1;
    hclen = this.readBits(4) + 4;
    if(hlit < 0 || hdist < 0 || hclen < 0) {
      this.restore_();
      return-1
    }
    try {
      parseDynamicHuffmanBlockImpl.call(this)
    }catch(e) {
      this.restore_();
      return-1
    }
    function parseDynamicHuffmanBlockImpl() {
      var bits;
      for(i = 0;i < hclen;++i) {
        if((bits = this.readBits(3)) < 0) {
          throw new Error("not enough input");
        }
        codeLengths[Zlib.RawInflateStream.Order[i]] = bits
      }
      codeLengthsTable = buildHuffmanTable(codeLengths);
      function decode(num, table, lengths) {
        var code;
        var prev = this.prev;
        var repeat;
        var i;
        var bits;
        for(i = 0;i < num;) {
          code = this.readCodeByTable(table);
          if(code < 0) {
            throw new Error("not enough input");
          }
          switch(code) {
            case 16:
              if((bits = this.readBits(2)) < 0) {
                throw new Error("not enough input");
              }
              repeat = 3 + bits;
              while(repeat--) {
                lengths[i++] = prev
              }
              break;
            case 17:
              if((bits = this.readBits(3)) < 0) {
                throw new Error("not enough input");
              }
              repeat = 3 + bits;
              while(repeat--) {
                lengths[i++] = 0
              }
              prev = 0;
              break;
            case 18:
              if((bits = this.readBits(7)) < 0) {
                throw new Error("not enough input");
              }
              repeat = 11 + bits;
              while(repeat--) {
                lengths[i++] = 0
              }
              prev = 0;
              break;
            default:
              lengths[i++] = code;
              prev = code;
              break
          }
        }
        this.prev = prev;
        return lengths
      }
      litlenLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(hlit);
      distLengths = new (USE_TYPEDARRAY ? Uint8Array : Array)(hdist);
      this.prev = 0;
      this.litlenTable = buildHuffmanTable(decode.call(this, hlit, codeLengthsTable, litlenLengths));
      this.distTable = buildHuffmanTable(decode.call(this, hdist, codeLengthsTable, distLengths))
    }
    this.status = Zlib.RawInflateStream.Status.BLOCK_BODY_END;
    return 0
  };
  Zlib.RawInflateStream.prototype.decodeHuffman = function() {
    var output = this.output;
    var op = this.op;
    var code;
    var ti;
    var codeDist;
    var codeLength;
    var litlen = this.litlenTable;
    var dist = this.distTable;
    var olength = output.length;
    var bits;
    this.status = Zlib.RawInflateStream.Status.DECODE_BLOCK_START;
    while(true) {
      this.save_();
      code = this.readCodeByTable(litlen);
      if(code < 0) {
        this.op = op;
        this.restore_();
        return-1
      }
      if(code === 256) {
        break
      }
      if(code < 256) {
        if(op === olength) {
          output = this.expandBuffer();
          olength = output.length
        }
        output[op++] = code;
        continue
      }
      ti = code - 257;
      codeLength = Zlib.RawInflateStream.LengthCodeTable[ti];
      if(Zlib.RawInflateStream.LengthExtraTable[ti] > 0) {
        bits = this.readBits(Zlib.RawInflateStream.LengthExtraTable[ti]);
        if(bits < 0) {
          this.op = op;
          this.restore_();
          return-1
        }
        codeLength += bits
      }
      code = this.readCodeByTable(dist);
      if(code < 0) {
        this.op = op;
        this.restore_();
        return-1
      }
      codeDist = Zlib.RawInflateStream.DistCodeTable[code];
      if(Zlib.RawInflateStream.DistExtraTable[code] > 0) {
        bits = this.readBits(Zlib.RawInflateStream.DistExtraTable[code]);
        if(bits < 0) {
          this.op = op;
          this.restore_();
          return-1
        }
        codeDist += bits
      }
      if(op + codeLength >= olength) {
        output = this.expandBuffer();
        olength = output.length
      }
      while(codeLength--) {
        output[op] = output[op++ - codeDist]
      }
      if(this.ip === this.input.length) {
        this.op = op;
        return-1
      }
    }
    while(this.bitsbuflen >= 8) {
      this.bitsbuflen -= 8;
      this.ip--
    }
    this.op = op;
    this.status = Zlib.RawInflateStream.Status.DECODE_BLOCK_END
  };
  Zlib.RawInflateStream.prototype.expandBuffer = function(opt_param) {
    var buffer;
    var ratio = this.input.length / this.ip + 1 | 0;
    var maxHuffCode;
    var newSize;
    var maxInflateSize;
    var input = this.input;
    var output = this.output;
    if(opt_param) {
      if(typeof opt_param.fixRatio === "number") {
        ratio = opt_param.fixRatio
      }
      if(typeof opt_param.addRatio === "number") {
        ratio += opt_param.addRatio
      }
    }
    if(ratio < 2) {
      maxHuffCode = (input.length - this.ip) / this.litlenTable[2];
      maxInflateSize = maxHuffCode / 2 * 258 | 0;
      newSize = maxInflateSize < output.length ? output.length + maxInflateSize : output.length << 1
    }else {
      newSize = output.length * ratio
    }
    if(USE_TYPEDARRAY) {
      buffer = new Uint8Array(newSize);
      buffer.set(output)
    }else {
      buffer = output
    }
    this.output = buffer;
    return this.output
  };
  Zlib.RawInflateStream.prototype.concatBuffer = function() {
    var buffer;
    var resize = this.resize;
    var op = this.op;
    if(resize) {
      if(USE_TYPEDARRAY) {
        buffer = new Uint8Array(op);
        buffer.set(this.output.subarray(this.sp, op))
      }else {
        buffer = this.output.slice(this.sp, op)
      }
    }else {
      buffer = USE_TYPEDARRAY ? this.output.subarray(this.sp, op) : this.output.slice(this.sp, op)
    }
    this.buffer = buffer;
    this.sp = op;
    return this.buffer
  };
  Zlib.RawInflateStream.prototype.getBytes = function() {
    return USE_TYPEDARRAY ? this.output.subarray(0, this.op) : this.output.slice(0, this.op)
  }
});
goog.provide("Zlib.Util");
goog.scope(function() {
  Zlib.Util.stringToByteArray = function(str) {
    var tmp = str.split("");
    var i;
    var il;
    for(i = 0, il = tmp.length;i < il;i++) {
      tmp[i] = (tmp[i].charCodeAt(0) & 255) >>> 0
    }
    return tmp
  }
});
goog.provide("Zlib.Adler32");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.Util");
goog.scope(function() {
  Zlib.Adler32 = function(array) {
    if(typeof array === "string") {
      array = Zlib.Util.stringToByteArray(array)
    }
    return Zlib.Adler32.update(1, array)
  };
  Zlib.Adler32.update = function(adler, array) {
    var s1 = adler & 65535;
    var s2 = adler >>> 16 & 65535;
    var len = array.length;
    var tlen;
    var i = 0;
    while(len > 0) {
      tlen = len > Zlib.Adler32.OptimizationParameter ? Zlib.Adler32.OptimizationParameter : len;
      len -= tlen;
      do {
        s1 += array[i++];
        s2 += s1
      }while(--tlen);
      s1 %= 65521;
      s2 %= 65521
    }
    return(s2 << 16 | s1) >>> 0
  };
  Zlib.Adler32.OptimizationParameter = 1024
});
goog.provide("Zlib.Inflate");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.Adler32");
goog.require("Zlib.RawInflate");
goog.scope(function() {
  Zlib.Inflate = function(input, opt_params) {
    var bufferSize;
    var bufferType;
    var cmf;
    var flg;
    this.input = input;
    this.ip = 0;
    this.rawinflate;
    this.verify;
    if(opt_params || !(opt_params = {})) {
      if(opt_params["index"]) {
        this.ip = opt_params["index"]
      }
      if(opt_params["verify"]) {
        this.verify = opt_params["verify"]
      }
    }
    cmf = input[this.ip++];
    flg = input[this.ip++];
    switch(cmf & 15) {
      case Zlib.CompressionMethod.DEFLATE:
        this.method = Zlib.CompressionMethod.DEFLATE;
        break;
      default:
        throw new Error("unsupported compression method");
    }
    if(((cmf << 8) + flg) % 31 !== 0) {
      throw new Error("invalid fcheck flag:" + ((cmf << 8) + flg) % 31);
    }
    if(flg & 32) {
      throw new Error("fdict flag is not supported");
    }
    this.rawinflate = new Zlib.RawInflate(input, {"index":this.ip, "bufferSize":opt_params["bufferSize"], "bufferType":opt_params["bufferType"], "resize":opt_params["resize"]})
  };
  Zlib.Inflate.BufferType = Zlib.RawInflate.BufferType;
  Zlib.Inflate.prototype.decompress = function() {
    var input = this.input;
    var buffer;
    var adler32;
    buffer = this.rawinflate.decompress();
    this.ip = this.rawinflate.ip;
    if(this.verify) {
      adler32 = (input[this.ip++] << 24 | input[this.ip++] << 16 | input[this.ip++] << 8 | input[this.ip++]) >>> 0;
      if(adler32 !== Zlib.Adler32(buffer)) {
        throw new Error("invalid adler-32 checksum");
      }
    }
    return buffer
  }
});
goog.provide("Zlib.Zip");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.RawDeflate");
goog.require("Zlib.CRC32");
goog.scope(function() {
  Zlib.Zip = function(opt_params) {
    opt_params = opt_params || {};
    this.files = [];
    this.comment = opt_params["comment"];
    this.password
  };
  Zlib.Zip.CompressionMethod = {STORE:0, DEFLATE:8};
  Zlib.Zip.OperatingSystem = {MSDOS:0, UNIX:3, MACINTOSH:7};
  Zlib.Zip.Flags = {ENCRYPT:1, DESCRIPTOR:8, UTF8:2048};
  Zlib.Zip.FileHeaderSignature = [80, 75, 1, 2];
  Zlib.Zip.LocalFileHeaderSignature = [80, 75, 3, 4];
  Zlib.Zip.CentralDirectorySignature = [80, 75, 5, 6];
  Zlib.Zip.prototype.addFile = function(input, opt_params) {
    opt_params = opt_params || {};
    var filename = "" || opt_params["filename"];
    var compressed;
    var size = input.length;
    var crc32 = 0;
    if(USE_TYPEDARRAY && input instanceof Array) {
      input = new Uint8Array(input)
    }
    if(typeof opt_params["compressionMethod"] !== "number") {
      opt_params["compressionMethod"] = Zlib.Zip.CompressionMethod.DEFLATE
    }
    if(opt_params["compress"]) {
      switch(opt_params["compressionMethod"]) {
        case Zlib.Zip.CompressionMethod.STORE:
          break;
        case Zlib.Zip.CompressionMethod.DEFLATE:
          crc32 = Zlib.CRC32.calc(input);
          input = this.deflateWithOption(input, opt_params);
          compressed = true;
          break;
        default:
          throw new Error("unknown compression method:" + opt_params["compressionMethod"]);
      }
    }
    this.files.push({buffer:input, option:opt_params, compressed:compressed, encrypted:false, size:size, crc32:crc32})
  };
  Zlib.Zip.prototype.setPassword = function(password) {
    this.password = password
  };
  Zlib.Zip.prototype.compress = function() {
    var files = this.files;
    var file;
    var output;
    var op1;
    var op2;
    var op3;
    var localFileSize = 0;
    var centralDirectorySize = 0;
    var endOfCentralDirectorySize;
    var offset;
    var needVersion;
    var flags;
    var compressionMethod;
    var date;
    var crc32;
    var size;
    var plainSize;
    var filenameLength;
    var extraFieldLength;
    var commentLength;
    var filename;
    var extraField;
    var comment;
    var buffer;
    var tmp;
    var key;
    var i;
    var il;
    var j;
    var jl;
    for(i = 0, il = files.length;i < il;++i) {
      file = files[i];
      filenameLength = file.option["filename"] ? file.option["filename"].length : 0;
      extraFieldLength = file.option["extraField"] ? file.option["extraField"].length : 0;
      commentLength = file.option["comment"] ? file.option["comment"].length : 0;
      if(!file.compressed) {
        file.crc32 = Zlib.CRC32.calc(file.buffer);
        switch(file.option["compressionMethod"]) {
          case Zlib.Zip.CompressionMethod.STORE:
            break;
          case Zlib.Zip.CompressionMethod.DEFLATE:
            file.buffer = this.deflateWithOption(file.buffer, file.option);
            file.compressed = true;
            break;
          default:
            throw new Error("unknown compression method:" + file.option["compressionMethod"]);
        }
      }
      if(file.option["password"] !== void 0 || this.password !== void 0) {
        key = this.createEncryptionKey(file.option["password"] || this.password);
        buffer = file.buffer;
        if(USE_TYPEDARRAY) {
          tmp = new Uint8Array(buffer.length + 12);
          tmp.set(buffer, 12);
          buffer = tmp
        }else {
          buffer.unshift(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        }
        for(j = 0;j < 12;++j) {
          buffer[j] = this.encode(key, i === 11 ? file.crc32 & 255 : Math.random() * 256 | 0)
        }
        for(jl = buffer.length;j < jl;++j) {
          buffer[j] = this.encode(key, buffer[j])
        }
        file.buffer = buffer
      }
      localFileSize += 30 + filenameLength + file.buffer.length;
      centralDirectorySize += 46 + filenameLength + commentLength
    }
    endOfCentralDirectorySize = 46 + (this.comment ? this.comment.length : 0);
    output = new (USE_TYPEDARRAY ? Uint8Array : Array)(localFileSize + centralDirectorySize + endOfCentralDirectorySize);
    op1 = 0;
    op2 = localFileSize;
    op3 = op2 + centralDirectorySize;
    for(i = 0, il = files.length;i < il;++i) {
      file = files[i];
      filenameLength = file.option["filename"] ? file.option["filename"].length : 0;
      extraFieldLength = 0;
      commentLength = file.option["comment"] ? file.option["comment"].length : 0;
      offset = op1;
      output[op1++] = Zlib.Zip.LocalFileHeaderSignature[0];
      output[op1++] = Zlib.Zip.LocalFileHeaderSignature[1];
      output[op1++] = Zlib.Zip.LocalFileHeaderSignature[2];
      output[op1++] = Zlib.Zip.LocalFileHeaderSignature[3];
      output[op2++] = Zlib.Zip.FileHeaderSignature[0];
      output[op2++] = Zlib.Zip.FileHeaderSignature[1];
      output[op2++] = Zlib.Zip.FileHeaderSignature[2];
      output[op2++] = Zlib.Zip.FileHeaderSignature[3];
      needVersion = 20;
      output[op2++] = needVersion & 255;
      output[op2++] = (file.option["os"]) || Zlib.Zip.OperatingSystem.MSDOS;
      output[op1++] = output[op2++] = needVersion & 255;
      output[op1++] = output[op2++] = needVersion >> 8 & 255;
      flags = 0;
      if(file.option["password"] || this.password) {
        flags |= Zlib.Zip.Flags.ENCRYPT
      }
      output[op1++] = output[op2++] = flags & 255;
      output[op1++] = output[op2++] = flags >> 8 & 255;
      compressionMethod = (file.option["compressionMethod"]);
      output[op1++] = output[op2++] = compressionMethod & 255;
      output[op1++] = output[op2++] = compressionMethod >> 8 & 255;
      date = (file.option["date"]) || new Date;
      output[op1++] = output[op2++] = (date.getMinutes() & 7) << 5 | date.getSeconds() / 2 | 0;
      output[op1++] = output[op2++] = date.getHours() << 3 | date.getMinutes() >> 3;
      output[op1++] = output[op2++] = (date.getMonth() + 1 & 7) << 5 | date.getDate();
      output[op1++] = output[op2++] = (date.getFullYear() - 1980 & 127) << 1 | date.getMonth() + 1 >> 3;
      crc32 = file.crc32;
      output[op1++] = output[op2++] = crc32 & 255;
      output[op1++] = output[op2++] = crc32 >> 8 & 255;
      output[op1++] = output[op2++] = crc32 >> 16 & 255;
      output[op1++] = output[op2++] = crc32 >> 24 & 255;
      size = file.buffer.length;
      output[op1++] = output[op2++] = size & 255;
      output[op1++] = output[op2++] = size >> 8 & 255;
      output[op1++] = output[op2++] = size >> 16 & 255;
      output[op1++] = output[op2++] = size >> 24 & 255;
      plainSize = file.size;
      output[op1++] = output[op2++] = plainSize & 255;
      output[op1++] = output[op2++] = plainSize >> 8 & 255;
      output[op1++] = output[op2++] = plainSize >> 16 & 255;
      output[op1++] = output[op2++] = plainSize >> 24 & 255;
      output[op1++] = output[op2++] = filenameLength & 255;
      output[op1++] = output[op2++] = filenameLength >> 8 & 255;
      output[op1++] = output[op2++] = extraFieldLength & 255;
      output[op1++] = output[op2++] = extraFieldLength >> 8 & 255;
      output[op2++] = commentLength & 255;
      output[op2++] = commentLength >> 8 & 255;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = 0;
      output[op2++] = offset & 255;
      output[op2++] = offset >> 8 & 255;
      output[op2++] = offset >> 16 & 255;
      output[op2++] = offset >> 24 & 255;
      filename = file.option["filename"];
      if(filename) {
        if(USE_TYPEDARRAY) {
          output.set(filename, op1);
          output.set(filename, op2);
          op1 += filenameLength;
          op2 += filenameLength
        }else {
          for(j = 0;j < filenameLength;++j) {
            output[op1++] = output[op2++] = filename[j]
          }
        }
      }
      extraField = file.option["extraField"];
      if(extraField) {
        if(USE_TYPEDARRAY) {
          output.set(extraField, op1);
          output.set(extraField, op2);
          op1 += extraFieldLength;
          op2 += extraFieldLength
        }else {
          for(j = 0;j < commentLength;++j) {
            output[op1++] = output[op2++] = extraField[j]
          }
        }
      }
      comment = file.option["comment"];
      if(comment) {
        if(USE_TYPEDARRAY) {
          output.set(comment, op2);
          op2 += commentLength
        }else {
          for(j = 0;j < commentLength;++j) {
            output[op2++] = comment[j]
          }
        }
      }
      if(USE_TYPEDARRAY) {
        output.set(file.buffer, op1);
        op1 += file.buffer.length
      }else {
        for(j = 0, jl = file.buffer.length;j < jl;++j) {
          output[op1++] = file.buffer[j]
        }
      }
    }
    output[op3++] = Zlib.Zip.CentralDirectorySignature[0];
    output[op3++] = Zlib.Zip.CentralDirectorySignature[1];
    output[op3++] = Zlib.Zip.CentralDirectorySignature[2];
    output[op3++] = Zlib.Zip.CentralDirectorySignature[3];
    output[op3++] = 0;
    output[op3++] = 0;
    output[op3++] = 0;
    output[op3++] = 0;
    output[op3++] = il & 255;
    output[op3++] = il >> 8 & 255;
    output[op3++] = il & 255;
    output[op3++] = il >> 8 & 255;
    output[op3++] = centralDirectorySize & 255;
    output[op3++] = centralDirectorySize >> 8 & 255;
    output[op3++] = centralDirectorySize >> 16 & 255;
    output[op3++] = centralDirectorySize >> 24 & 255;
    output[op3++] = localFileSize & 255;
    output[op3++] = localFileSize >> 8 & 255;
    output[op3++] = localFileSize >> 16 & 255;
    output[op3++] = localFileSize >> 24 & 255;
    commentLength = this.comment ? this.comment.length : 0;
    output[op3++] = commentLength & 255;
    output[op3++] = commentLength >> 8 & 255;
    if(this.comment) {
      if(USE_TYPEDARRAY) {
        output.set(this.comment, op3);
        op3 += commentLength
      }else {
        for(j = 0, jl = commentLength;j < jl;++j) {
          output[op3++] = this.comment[j]
        }
      }
    }
    return output
  };
  Zlib.Zip.prototype.deflateWithOption = function(input, opt_params) {
    var deflator = new Zlib.RawDeflate(input, opt_params["deflateOption"]);
    return deflator.compress()
  };
  Zlib.Zip.prototype.getByte = function(key) {
    var tmp = key[2] & 65535 | 2;
    return tmp * (tmp ^ 1) >> 8 & 255
  };
  Zlib.Zip.prototype.encode = function(key, n) {
    var tmp = this.getByte((key));
    this.updateKeys((key), n);
    return tmp ^ n
  };
  Zlib.Zip.prototype.updateKeys = function(key, n) {
    key[0] = Zlib.CRC32.single(key[0], n);
    key[1] = (((key[1] + (key[0] & 255)) * 20173 >>> 0) * 6681 >>> 0) + 1 >>> 0;
    key[2] = Zlib.CRC32.single(key[2], key[1] >>> 24)
  };
  Zlib.Zip.prototype.createEncryptionKey = function(password) {
    var key = [305419896, 591751049, 878082192];
    var i;
    var il;
    if(USE_TYPEDARRAY) {
      key = new Uint32Array(key)
    }
    for(i = 0, il = password.length;i < il;++i) {
      this.updateKeys(key, password[i] & 255)
    }
    return key
  }
});
goog.provide("Zlib.Unzip");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib.RawInflate");
goog.require("Zlib.CRC32");
goog.require("Zlib.Zip");
goog.scope(function() {
  Zlib.Unzip = function(input, opt_params) {
    opt_params = opt_params || {};
    this.input = USE_TYPEDARRAY && input instanceof Array ? new Uint8Array(input) : input;
    this.ip = 0;
    this.eocdrOffset;
    this.numberOfThisDisk;
    this.startDisk;
    this.totalEntriesThisDisk;
    this.totalEntries;
    this.centralDirectorySize;
    this.centralDirectoryOffset;
    this.commentLength;
    this.comment;
    this.fileHeaderList;
    this.filenameToIndex;
    this.verify = opt_params["verify"] || false;
    this.password = opt_params["password"]
  };
  Zlib.Unzip.CompressionMethod = Zlib.Zip.CompressionMethod;
  Zlib.Unzip.FileHeaderSignature = Zlib.Zip.FileHeaderSignature;
  Zlib.Unzip.LocalFileHeaderSignature = Zlib.Zip.LocalFileHeaderSignature;
  Zlib.Unzip.CentralDirectorySignature = Zlib.Zip.CentralDirectorySignature;
  Zlib.Unzip.FileHeader = function(input, ip) {
    this.input = input;
    this.offset = ip;
    this.length;
    this.version;
    this.os;
    this.needVersion;
    this.flags;
    this.compression;
    this.time;
    this.date;
    this.crc32;
    this.compressedSize;
    this.plainSize;
    this.fileNameLength;
    this.extraFieldLength;
    this.fileCommentLength;
    this.diskNumberStart;
    this.internalFileAttributes;
    this.externalFileAttributes;
    this.relativeOffset;
    this.filename;
    this.extraField;
    this.comment
  };
  Zlib.Unzip.FileHeader.prototype.parse = function() {
    var input = this.input;
    var ip = this.offset;
    if(input[ip++] !== Zlib.Unzip.FileHeaderSignature[0] || input[ip++] !== Zlib.Unzip.FileHeaderSignature[1] || input[ip++] !== Zlib.Unzip.FileHeaderSignature[2] || input[ip++] !== Zlib.Unzip.FileHeaderSignature[3]) {
      throw new Error("invalid file header signature");
    }
    this.version = input[ip++];
    this.os = input[ip++];
    this.needVersion = input[ip++] | input[ip++] << 8;
    this.flags = input[ip++] | input[ip++] << 8;
    this.compression = input[ip++] | input[ip++] << 8;
    this.time = input[ip++] | input[ip++] << 8;
    this.date = input[ip++] | input[ip++] << 8;
    this.crc32 = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.compressedSize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.plainSize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.fileNameLength = input[ip++] | input[ip++] << 8;
    this.extraFieldLength = input[ip++] | input[ip++] << 8;
    this.fileCommentLength = input[ip++] | input[ip++] << 8;
    this.diskNumberStart = input[ip++] | input[ip++] << 8;
    this.internalFileAttributes = input[ip++] | input[ip++] << 8;
    this.externalFileAttributes = input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24;
    this.relativeOffset = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.filename = String.fromCharCode.apply(null, USE_TYPEDARRAY ? input.subarray(ip, ip += this.fileNameLength) : input.slice(ip, ip += this.fileNameLength));
    this.extraField = USE_TYPEDARRAY ? input.subarray(ip, ip += this.extraFieldLength) : input.slice(ip, ip += this.extraFieldLength);
    this.comment = USE_TYPEDARRAY ? input.subarray(ip, ip + this.fileCommentLength) : input.slice(ip, ip + this.fileCommentLength);
    this.length = ip - this.offset
  };
  Zlib.Unzip.LocalFileHeader = function(input, ip) {
    this.input = input;
    this.offset = ip;
    this.length;
    this.needVersion;
    this.flags;
    this.compression;
    this.time;
    this.date;
    this.crc32;
    this.compressedSize;
    this.plainSize;
    this.fileNameLength;
    this.extraFieldLength;
    this.filename;
    this.extraField
  };
  Zlib.Unzip.LocalFileHeader.Flags = Zlib.Zip.Flags;
  Zlib.Unzip.LocalFileHeader.prototype.parse = function() {
    var input = this.input;
    var ip = this.offset;
    if(input[ip++] !== Zlib.Unzip.LocalFileHeaderSignature[0] || input[ip++] !== Zlib.Unzip.LocalFileHeaderSignature[1] || input[ip++] !== Zlib.Unzip.LocalFileHeaderSignature[2] || input[ip++] !== Zlib.Unzip.LocalFileHeaderSignature[3]) {
      throw new Error("invalid local file header signature");
    }
    this.needVersion = input[ip++] | input[ip++] << 8;
    this.flags = input[ip++] | input[ip++] << 8;
    this.compression = input[ip++] | input[ip++] << 8;
    this.time = input[ip++] | input[ip++] << 8;
    this.date = input[ip++] | input[ip++] << 8;
    this.crc32 = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.compressedSize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.plainSize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.fileNameLength = input[ip++] | input[ip++] << 8;
    this.extraFieldLength = input[ip++] | input[ip++] << 8;
    this.filename = String.fromCharCode.apply(null, USE_TYPEDARRAY ? input.subarray(ip, ip += this.fileNameLength) : input.slice(ip, ip += this.fileNameLength));
    this.extraField = USE_TYPEDARRAY ? input.subarray(ip, ip += this.extraFieldLength) : input.slice(ip, ip += this.extraFieldLength);
    this.length = ip - this.offset
  };
  Zlib.Unzip.prototype.searchEndOfCentralDirectoryRecord = function() {
    var input = this.input;
    var ip;
    for(ip = input.length - 12;ip > 0;--ip) {
      if(input[ip] === Zlib.Unzip.CentralDirectorySignature[0] && input[ip + 1] === Zlib.Unzip.CentralDirectorySignature[1] && input[ip + 2] === Zlib.Unzip.CentralDirectorySignature[2] && input[ip + 3] === Zlib.Unzip.CentralDirectorySignature[3]) {
        this.eocdrOffset = ip;
        return
      }
    }
    throw new Error("End of Central Directory Record not found");
  };
  Zlib.Unzip.prototype.parseEndOfCentralDirectoryRecord = function() {
    var input = this.input;
    var ip;
    if(!this.eocdrOffset) {
      this.searchEndOfCentralDirectoryRecord()
    }
    ip = this.eocdrOffset;
    if(input[ip++] !== Zlib.Unzip.CentralDirectorySignature[0] || input[ip++] !== Zlib.Unzip.CentralDirectorySignature[1] || input[ip++] !== Zlib.Unzip.CentralDirectorySignature[2] || input[ip++] !== Zlib.Unzip.CentralDirectorySignature[3]) {
      throw new Error("invalid signature");
    }
    this.numberOfThisDisk = input[ip++] | input[ip++] << 8;
    this.startDisk = input[ip++] | input[ip++] << 8;
    this.totalEntriesThisDisk = input[ip++] | input[ip++] << 8;
    this.totalEntries = input[ip++] | input[ip++] << 8;
    this.centralDirectorySize = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.centralDirectoryOffset = (input[ip++] | input[ip++] << 8 | input[ip++] << 16 | input[ip++] << 24) >>> 0;
    this.commentLength = input[ip++] | input[ip++] << 8;
    this.comment = USE_TYPEDARRAY ? input.subarray(ip, ip + this.commentLength) : input.slice(ip, ip + this.commentLength)
  };
  Zlib.Unzip.prototype.parseFileHeader = function() {
    var filelist = [];
    var filetable = {};
    var ip;
    var fileHeader;
    var i;
    var il;
    if(this.fileHeaderList) {
      return
    }
    if(this.centralDirectoryOffset === void 0) {
      this.parseEndOfCentralDirectoryRecord()
    }
    ip = this.centralDirectoryOffset;
    for(i = 0, il = this.totalEntries;i < il;++i) {
      fileHeader = new Zlib.Unzip.FileHeader(this.input, ip);
      fileHeader.parse();
      ip += fileHeader.length;
      filelist[i] = fileHeader;
      filetable[fileHeader.filename] = i
    }
    if(this.centralDirectorySize < ip - this.centralDirectoryOffset) {
      throw new Error("invalid file header size");
    }
    this.fileHeaderList = filelist;
    this.filenameToIndex = filetable
  };
  Zlib.Unzip.prototype.getFileData = function(index, opt_params) {
    opt_params = opt_params || {};
    var input = this.input;
    var fileHeaderList = this.fileHeaderList;
    var localFileHeader;
    var offset;
    var length;
    var buffer;
    var crc32;
    var key;
    var i;
    var il;
    if(!fileHeaderList) {
      this.parseFileHeader()
    }
    if(fileHeaderList[index] === void 0) {
      throw new Error("wrong index");
    }
    offset = fileHeaderList[index].relativeOffset;
    localFileHeader = new Zlib.Unzip.LocalFileHeader(this.input, offset);
    localFileHeader.parse();
    offset += localFileHeader.length;
    length = localFileHeader.compressedSize;
    if((localFileHeader.flags & Zlib.Unzip.LocalFileHeader.Flags.ENCRYPT) !== 0) {
      if(!(opt_params["password"] || this.password)) {
        throw new Error("please set password");
      }
      key = this.createDecryptionKey(opt_params["password"] || this.password);
      for(i = offset, il = offset + 12;i < il;++i) {
        this.decode(key, input[i])
      }
      offset += 12;
      length -= 12;
      for(i = offset, il = offset + length;i < il;++i) {
        input[i] = this.decode(key, input[i])
      }
    }
    switch(localFileHeader.compression) {
      case Zlib.Unzip.CompressionMethod.STORE:
        buffer = USE_TYPEDARRAY ? this.input.subarray(offset, offset + length) : this.input.slice(offset, offset + length);
        break;
      case Zlib.Unzip.CompressionMethod.DEFLATE:
        buffer = (new Zlib.RawInflate(this.input, {"index":offset, "bufferSize":localFileHeader.plainSize})).decompress();
        break;
      default:
        throw new Error("unknown compression type");
    }
    if(this.verify) {
      crc32 = Zlib.CRC32.calc(buffer);
      if(localFileHeader.crc32 !== crc32) {
        throw new Error("wrong crc: file=0x" + localFileHeader.crc32.toString(16) + ", data=0x" + crc32.toString(16));
      }
    }
    return buffer
  };
  Zlib.Unzip.prototype.getFilenames = function() {
    var filenameList = [];
    var i;
    var il;
    var fileHeaderList;
    if(!this.fileHeaderList) {
      this.parseFileHeader()
    }
    fileHeaderList = this.fileHeaderList;
    for(i = 0, il = fileHeaderList.length;i < il;++i) {
      filenameList[i] = fileHeaderList[i].filename
    }
    return filenameList
  };
  Zlib.Unzip.prototype.decompress = function(filename, opt_params) {
    var index;
    if(!this.filenameToIndex) {
      this.parseFileHeader()
    }
    index = this.filenameToIndex[filename];
    if(index === void 0) {
      throw new Error(filename + " not found");
    }
    return this.getFileData(index, opt_params)
  };
  Zlib.Unzip.prototype.setPassword = function(password) {
    this.password = password
  };
  Zlib.Unzip.prototype.decode = function(key, n) {
    n ^= this.getByte((key));
    this.updateKeys((key), n);
    return n
  };
  Zlib.Unzip.prototype.updateKeys = Zlib.Zip.prototype.updateKeys;
  Zlib.Unzip.prototype.createDecryptionKey = Zlib.Zip.prototype.createEncryptionKey;
  Zlib.Unzip.prototype.getByte = Zlib.Zip.prototype.getByte
});
goog.provide("Zlib");
goog.scope(function() {
  Zlib.CompressionMethod = {DEFLATE:8, RESERVED:15}
});
goog.provide("Zlib.Deflate");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib");
goog.require("Zlib.Adler32");
goog.require("Zlib.RawDeflate");
goog.scope(function() {
  Zlib.Deflate = function(input, opt_params) {
    this.input = input;
    this.output = new (USE_TYPEDARRAY ? Uint8Array : Array)(Zlib.Deflate.DefaultBufferSize);
    this.compressionType = Zlib.Deflate.CompressionType.DYNAMIC;
    this.rawDeflate;
    var rawDeflateOption = {};
    var prop;
    if(opt_params || !(opt_params = {})) {
      if(typeof opt_params["compressionType"] === "number") {
        this.compressionType = opt_params["compressionType"]
      }
    }
    for(prop in opt_params) {
      rawDeflateOption[prop] = opt_params[prop]
    }
    rawDeflateOption["outputBuffer"] = this.output;
    this.rawDeflate = new Zlib.RawDeflate(this.input, rawDeflateOption)
  };
  Zlib.Deflate.DefaultBufferSize = 32768;
  Zlib.Deflate.CompressionType = Zlib.RawDeflate.CompressionType;
  Zlib.Deflate.compress = function(input, opt_params) {
    return(new Zlib.Deflate(input, opt_params)).compress()
  };
  Zlib.Deflate.prototype.compress = function() {
    var cm;
    var cinfo;
    var cmf;
    var flg;
    var fcheck;
    var fdict;
    var flevel;
    var clevel;
    var adler;
    var error = false;
    var output;
    var pos = 0;
    output = this.output;
    cm = Zlib.CompressionMethod.DEFLATE;
    switch(cm) {
      case Zlib.CompressionMethod.DEFLATE:
        cinfo = Math.LOG2E * Math.log(Zlib.RawDeflate.WindowSize) - 8;
        break;
      default:
        throw new Error("invalid compression method");
    }
    cmf = cinfo << 4 | cm;
    output[pos++] = cmf;
    fdict = 0;
    switch(cm) {
      case Zlib.CompressionMethod.DEFLATE:
        switch(this.compressionType) {
          case Zlib.Deflate.CompressionType.NONE:
            flevel = 0;
            break;
          case Zlib.Deflate.CompressionType.FIXED:
            flevel = 1;
            break;
          case Zlib.Deflate.CompressionType.DYNAMIC:
            flevel = 2;
            break;
          default:
            throw new Error("unsupported compression type");
        }
        break;
      default:
        throw new Error("invalid compression method");
    }
    flg = flevel << 6 | fdict << 5;
    fcheck = 31 - (cmf * 256 + flg) % 31;
    flg |= fcheck;
    output[pos++] = flg;
    adler = Zlib.Adler32(this.input);
    this.rawDeflate.op = pos;
    output = this.rawDeflate.compress();
    pos = output.length;
    if(USE_TYPEDARRAY) {
      output = new Uint8Array(output.buffer);
      if(output.length <= pos + 4) {
        this.output = new Uint8Array(output.length + 4);
        this.output.set(output);
        output = this.output
      }
      output = output.subarray(0, pos + 4)
    }
    output[pos++] = adler >> 24 & 255;
    output[pos++] = adler >> 16 & 255;
    output[pos++] = adler >> 8 & 255;
    output[pos++] = adler & 255;
    return output
  }
});
goog.provide("Zlib.exportObject");
goog.require("Zlib");
goog.scope(function() {
  Zlib.exportObject = function(enumString, exportKeyValue) {
    var keys;
    var key;
    var i;
    var il;
    if(Object.keys) {
      keys = Object.keys(exportKeyValue)
    }else {
      keys = [];
      i = 0;
      for(key in exportKeyValue) {
        keys[i++] = key
      }
    }
    for(i = 0, il = keys.length;i < il;++i) {
      key = keys[i];
      goog.exportSymbol(enumString + "." + key, exportKeyValue[key])
    }
  }
});
goog.provide("Zlib.InflateStream");
goog.require("USE_TYPEDARRAY");
goog.require("Zlib");
goog.require("Zlib.RawInflateStream");
goog.scope(function() {
  Zlib.InflateStream = function(input) {
    this.input = input === void 0 ? new (USE_TYPEDARRAY ? Uint8Array : Array) : input;
    this.ip = 0;
    this.rawinflate = new Zlib.RawInflateStream(this.input, this.ip);
    this.method;
    this.output = this.rawinflate.output
  };
  Zlib.InflateStream.prototype.decompress = function(input) {
    var buffer;
    var adler32;
    if(input !== void 0) {
      if(USE_TYPEDARRAY) {
        var tmp = new Uint8Array(this.input.length + input.length);
        tmp.set(this.input, 0);
        tmp.set(input, this.input.length);
        this.input = tmp
      }else {
        this.input = this.input.concat(input)
      }
    }
    if(this.method === void 0) {
      if(this.readHeader() < 0) {
        return new (USE_TYPEDARRAY ? Uint8Array : Array)
      }
    }
    buffer = this.rawinflate.decompress(this.input, this.ip);
    if(this.rawinflate.ip !== 0) {
      this.input = USE_TYPEDARRAY ? this.input.subarray(this.rawinflate.ip) : this.input.slice(this.rawinflate.ip);
      this.ip = 0
    }
    return buffer
  };
  Zlib.InflateStream.prototype.getBytes = function() {
    return this.rawinflate.getBytes()
  };
  Zlib.InflateStream.prototype.readHeader = function() {
    var ip = this.ip;
    var input = this.input;
    var cmf = input[ip++];
    var flg = input[ip++];
    if(cmf === void 0 || flg === void 0) {
      return-1
    }
    switch(cmf & 15) {
      case Zlib.CompressionMethod.DEFLATE:
        this.method = Zlib.CompressionMethod.DEFLATE;
        break;
      default:
        throw new Error("unsupported compression method");
    }
    if(((cmf << 8) + flg) % 31 !== 0) {
      throw new Error("invalid fcheck flag:" + ((cmf << 8) + flg) % 31);
    }
    if(flg & 32) {
      throw new Error("fdict flag is not supported");
    }
    this.ip = ip
  }
});
goog.require("Zlib.Adler32");
goog.exportSymbol("Zlib.Adler32", Zlib.Adler32);
goog.exportSymbol("Zlib.Adler32.update", Zlib.Adler32.update);
goog.require("Zlib.CRC32");
goog.exportSymbol("Zlib.CRC32", Zlib.CRC32);
goog.exportSymbol("Zlib.CRC32.calc", Zlib.CRC32.calc);
goog.exportSymbol("Zlib.CRC32.update", Zlib.CRC32.update);
goog.require("Zlib.Deflate");
goog.require("Zlib.exportObject");
goog.exportSymbol("Zlib.Deflate", Zlib.Deflate);
goog.exportSymbol("Zlib.Deflate.compress", Zlib.Deflate.compress);
goog.exportSymbol("Zlib.Deflate.prototype.compress", Zlib.Deflate.prototype.compress);
Zlib.exportObject("Zlib.Deflate.CompressionType", {"NONE":Zlib.Deflate.CompressionType.NONE, "FIXED":Zlib.Deflate.CompressionType.FIXED, "DYNAMIC":Zlib.Deflate.CompressionType.DYNAMIC});
goog.require("Zlib.Gunzip");
goog.exportSymbol("Zlib.Gunzip", Zlib.Gunzip);
goog.exportSymbol("Zlib.Gunzip.prototype.decompress", Zlib.Gunzip.prototype.decompress);
goog.exportSymbol("Zlib.Gunzip.prototype.getMembers", Zlib.Gunzip.prototype.getMembers);
goog.require("Zlib.GunzipMember");
goog.exportSymbol("Zlib.GunzipMember", Zlib.GunzipMember);
goog.exportSymbol("Zlib.GunzipMember.prototype.getName", Zlib.GunzipMember.prototype.getName);
goog.exportSymbol("Zlib.GunzipMember.prototype.getData", Zlib.GunzipMember.prototype.getData);
goog.exportSymbol("Zlib.GunzipMember.prototype.getMtime", Zlib.GunzipMember.prototype.getMtime);
goog.require("Zlib.Gzip");
goog.exportSymbol("Zlib.Gzip", Zlib.Gzip);
goog.exportSymbol("Zlib.Gzip.prototype.compress", Zlib.Gzip.prototype.compress);
goog.require("Zlib.Inflate");
goog.require("Zlib.exportObject");
goog.exportSymbol("Zlib.Inflate", Zlib.Inflate);
goog.exportSymbol("Zlib.Inflate.prototype.decompress", Zlib.Inflate.prototype.decompress);
Zlib.exportObject("Zlib.Inflate.BufferType", {"ADAPTIVE":Zlib.Inflate.BufferType.ADAPTIVE, "BLOCK":Zlib.Inflate.BufferType.BLOCK});
goog.require("Zlib.InflateStream");
goog.exportSymbol("Zlib.InflateStream", Zlib.InflateStream);
goog.exportSymbol("Zlib.InflateStream.prototype.decompress", Zlib.InflateStream.prototype.decompress);
goog.exportSymbol("Zlib.InflateStream.prototype.getBytes", Zlib.InflateStream.prototype.getBytes);
goog.require("Zlib.RawDeflate");
goog.require("Zlib.exportObject");
goog.exportSymbol("Zlib.RawDeflate", Zlib.RawDeflate);
goog.exportSymbol("Zlib.RawDeflate.prototype.compress", Zlib.RawDeflate.prototype.compress);
Zlib.exportObject("Zlib.RawDeflate.CompressionType", {"NONE":Zlib.RawDeflate.CompressionType.NONE, "FIXED":Zlib.RawDeflate.CompressionType.FIXED, "DYNAMIC":Zlib.RawDeflate.CompressionType.DYNAMIC});
goog.require("Zlib.RawInflate");
goog.require("Zlib.exportObject");
goog.exportSymbol("Zlib.RawInflate", Zlib.RawInflate);
goog.exportSymbol("Zlib.RawInflate.prototype.decompress", Zlib.RawInflate.prototype.decompress);
Zlib.exportObject("Zlib.RawInflate.BufferType", {"ADAPTIVE":Zlib.RawInflate.BufferType.ADAPTIVE, "BLOCK":Zlib.RawInflate.BufferType.BLOCK});
goog.require("Zlib.RawInflateStream");
goog.exportSymbol("Zlib.RawInflateStream", Zlib.RawInflateStream);
goog.exportSymbol("Zlib.RawInflateStream.prototype.decompress", Zlib.RawInflateStream.prototype.decompress);
goog.exportSymbol("Zlib.RawInflateStream.prototype.getBytes", Zlib.RawInflateStream.prototype.getBytes);
goog.require("Zlib.Unzip");
goog.exportSymbol("Zlib.Unzip", Zlib.Unzip);
goog.exportSymbol("Zlib.Unzip.prototype.decompress", Zlib.Unzip.prototype.decompress);
goog.exportSymbol("Zlib.Unzip.prototype.getFilenames", Zlib.Unzip.prototype.getFilenames);
goog.exportSymbol("Zlib.Unzip.prototype.setPassword", Zlib.Unzip.prototype.setPassword);
goog.require("Zlib.Zip");
goog.require("Zlib.exportObject");
goog.exportSymbol("Zlib.Zip", Zlib.Zip);
goog.exportSymbol("Zlib.Zip.prototype.addFile", Zlib.Zip.prototype.addFile);
goog.exportSymbol("Zlib.Zip.prototype.compress", Zlib.Zip.prototype.compress);
goog.exportSymbol("Zlib.Zip.prototype.setPassword", Zlib.Zip.prototype.setPassword);
Zlib.exportObject("Zlib.Zip.CompressionMethod", {"STORE":Zlib.Zip.CompressionMethod.STORE, "DEFLATE":Zlib.Zip.CompressionMethod.DEFLATE});
Zlib.exportObject("Zlib.Zip.OperatingSystem", {"MSDOS":Zlib.Zip.OperatingSystem.MSDOS, "UNIX":Zlib.Zip.OperatingSystem.UNIX, "MACINTOSH":Zlib.Zip.OperatingSystem.MACINTOSH});
}).call(this); //@ sourceMappingURL=zlib.pretty.js.map
