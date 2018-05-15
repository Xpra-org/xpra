// universal module definition
(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        // AMD. Register as an anonymous module.
        define([], factory);
    } else if (typeof exports === 'object') {
        // Node. Does not work with strict CommonJS, but
        // only CommonJS-like environments that support module.exports,
        // like Node.
        module.exports = factory();
    } else {
        // Browser globals (root is window)
        root.Decoder = factory();
    }
}(this, function () {
  
  var global;
  
  function initglobal(){
    global = this;
    if (!global){
      if (typeof window != "undefined"){
        global = window;
      }else if (typeof self != "undefined"){
        global = self;
      };
    };
  };
  initglobal();
  
  
  function error(message) {
    console.error(message);
    console.trace();
  };

  
  function assert(condition, message) {
    if (!condition) {
      error(message);
    };
  };
  
  
  var getModule = function(par_broadwayOnHeadersDecoded, par_broadwayOnPictureDecoded){
    
    
    /*var ModuleX = {
      'print': function(text) { console.log('stdout: ' + text); },
      'printErr': function(text) { console.log('stderr: ' + text); }
    };*/
    
    
    /*
    
      The reason why this is all packed into one file is that this file can also function as worker.
      you can integrate the file into your build system and provide the original file to be loaded into a worker.
    
    */
    
    var Module = (function(){
    
var Module = typeof Module !== "undefined" ? Module : {};
var moduleOverrides = {};
var key;
for (key in Module) {
 if (Module.hasOwnProperty(key)) {
  moduleOverrides[key] = Module[key];
 }
}
Module["arguments"] = [];
Module["thisProgram"] = "./this.program";
Module["quit"] = (function(status, toThrow) {
 throw toThrow;
});
Module["preRun"] = [];
Module["postRun"] = [];
var ENVIRONMENT_IS_WEB = false;
var ENVIRONMENT_IS_WORKER = false;
var ENVIRONMENT_IS_NODE = false;
var ENVIRONMENT_IS_SHELL = false;
if (Module["ENVIRONMENT"]) {
 if (Module["ENVIRONMENT"] === "WEB") {
  ENVIRONMENT_IS_WEB = true;
 } else if (Module["ENVIRONMENT"] === "WORKER") {
  ENVIRONMENT_IS_WORKER = true;
 } else if (Module["ENVIRONMENT"] === "NODE") {
  ENVIRONMENT_IS_NODE = true;
 } else if (Module["ENVIRONMENT"] === "SHELL") {
  ENVIRONMENT_IS_SHELL = true;
 } else {
  throw new Error("Module['ENVIRONMENT'] value is not valid. must be one of: WEB|WORKER|NODE|SHELL.");
 }
} else {
 ENVIRONMENT_IS_WEB = typeof window === "object";
 ENVIRONMENT_IS_WORKER = typeof importScripts === "function";
 ENVIRONMENT_IS_NODE = typeof process === "object" && typeof null === "function" && !ENVIRONMENT_IS_WEB && !ENVIRONMENT_IS_WORKER;
 ENVIRONMENT_IS_SHELL = !ENVIRONMENT_IS_WEB && !ENVIRONMENT_IS_NODE && !ENVIRONMENT_IS_WORKER;
}
if (ENVIRONMENT_IS_NODE) {
 var nodeFS;
 var nodePath;
 Module["read"] = function shell_read(filename, binary) {
  var ret;
  ret = tryParseAsDataURI(filename);
  if (!ret) {
   if (!nodeFS) nodeFS = (null)("fs");
   if (!nodePath) nodePath = (null)("path");
   filename = nodePath["normalize"](filename);
   ret = nodeFS["readFileSync"](filename);
  }
  return binary ? ret : ret.toString();
 };
 Module["readBinary"] = function readBinary(filename) {
  var ret = Module["read"](filename, true);
  if (!ret.buffer) {
   ret = new Uint8Array(ret);
  }
  assert(ret.buffer);
  return ret;
 };
 if (process["argv"].length > 1) {
  Module["thisProgram"] = process["argv"][1].replace(/\\/g, "/");
 }
 Module["arguments"] = process["argv"].slice(2);
 if (typeof module !== "undefined") {
  module["exports"] = Module;
 }
 process["on"]("uncaughtException", (function(ex) {
  if (!(ex instanceof ExitStatus)) {
   throw ex;
  }
 }));
 process["on"]("unhandledRejection", (function(reason, p) {
  process["exit"](1);
 }));
 Module["inspect"] = (function() {
  return "[Emscripten Module object]";
 });
} else if (ENVIRONMENT_IS_SHELL) {
 if (typeof read != "undefined") {
  Module["read"] = function shell_read(f) {
   var data = tryParseAsDataURI(f);
   if (data) {
    return intArrayToString(data);
   }
   return read(f);
  };
 }
 Module["readBinary"] = function readBinary(f) {
  var data;
  data = tryParseAsDataURI(f);
  if (data) {
   return data;
  }
  if (typeof readbuffer === "function") {
   return new Uint8Array(readbuffer(f));
  }
  data = read(f, "binary");
  assert(typeof data === "object");
  return data;
 };
 if (typeof scriptArgs != "undefined") {
  Module["arguments"] = scriptArgs;
 } else if (typeof arguments != "undefined") {
  Module["arguments"] = arguments;
 }
 if (typeof quit === "function") {
  Module["quit"] = (function(status, toThrow) {
   quit(status);
  });
 }
} else if (ENVIRONMENT_IS_WEB || ENVIRONMENT_IS_WORKER) {
 Module["read"] = function shell_read(url) {
  try {
   var xhr = new XMLHttpRequest;
   xhr.open("GET", url, false);
   xhr.send(null);
   return xhr.responseText;
  } catch (err) {
   var data = tryParseAsDataURI(url);
   if (data) {
    return intArrayToString(data);
   }
   throw err;
  }
 };
 if (ENVIRONMENT_IS_WORKER) {
  Module["readBinary"] = function readBinary(url) {
   try {
    var xhr = new XMLHttpRequest;
    xhr.open("GET", url, false);
    xhr.responseType = "arraybuffer";
    xhr.send(null);
    return new Uint8Array(xhr.response);
   } catch (err) {
    var data = tryParseAsDataURI(url);
    if (data) {
     return data;
    }
    throw err;
   }
  };
 }
 Module["readAsync"] = function readAsync(url, onload, onerror) {
  var xhr = new XMLHttpRequest;
  xhr.open("GET", url, true);
  xhr.responseType = "arraybuffer";
  xhr.onload = function xhr_onload() {
   if (xhr.status == 200 || xhr.status == 0 && xhr.response) {
    onload(xhr.response);
    return;
   }
   var data = tryParseAsDataURI(url);
   if (data) {
    onload(data.buffer);
    return;
   }
   onerror();
  };
  xhr.onerror = onerror;
  xhr.send(null);
 };
 Module["setWindowTitle"] = (function(title) {
  document.title = title;
 });
}
Module["print"] = typeof console !== "undefined" ? console.log.bind(console) : typeof print !== "undefined" ? print : null;
Module["printErr"] = typeof printErr !== "undefined" ? printErr : typeof console !== "undefined" && console.warn.bind(console) || Module["print"];
Module.print = Module["print"];
Module.printErr = Module["printErr"];
for (key in moduleOverrides) {
 if (moduleOverrides.hasOwnProperty(key)) {
  Module[key] = moduleOverrides[key];
 }
}
moduleOverrides = undefined;
var STACK_ALIGN = 16;
function staticAlloc(size) {
 assert(!staticSealed);
 var ret = STATICTOP;
 STATICTOP = STATICTOP + size + 15 & -16;
 return ret;
}
function dynamicAlloc(size) {
 assert(DYNAMICTOP_PTR);
 var ret = HEAP32[DYNAMICTOP_PTR >> 2];
 var end = ret + size + 15 & -16;
 HEAP32[DYNAMICTOP_PTR >> 2] = end;
 if (end >= TOTAL_MEMORY) {
  var success = enlargeMemory();
  if (!success) {
   HEAP32[DYNAMICTOP_PTR >> 2] = ret;
   return 0;
  }
 }
 return ret;
}
function alignMemory(size, factor) {
 if (!factor) factor = STACK_ALIGN;
 var ret = size = Math.ceil(size / factor) * factor;
 return ret;
}
function getNativeTypeSize(type) {
 switch (type) {
 case "i1":
 case "i8":
  return 1;
 case "i16":
  return 2;
 case "i32":
  return 4;
 case "i64":
  return 8;
 case "float":
  return 4;
 case "double":
  return 8;
 default:
  {
   if (type[type.length - 1] === "*") {
    return 4;
   } else if (type[0] === "i") {
    var bits = parseInt(type.substr(1));
    assert(bits % 8 === 0);
    return bits / 8;
   } else {
    return 0;
   }
  }
 }
}
function warnOnce(text) {
 if (!warnOnce.shown) warnOnce.shown = {};
 if (!warnOnce.shown[text]) {
  warnOnce.shown[text] = 1;
  Module.printErr(text);
 }
}
var jsCallStartIndex = 1;
var functionPointers = new Array(0);
var funcWrappers = {};
function dynCall(sig, ptr, args) {
 if (args && args.length) {
  return Module["dynCall_" + sig].apply(null, [ ptr ].concat(args));
 } else {
  return Module["dynCall_" + sig].call(null, ptr);
 }
}
var GLOBAL_BASE = 8;
var ABORT = 0;
var EXITSTATUS = 0;
function assert(condition, text) {
 if (!condition) {
  abort("Assertion failed: " + text);
 }
}
function getCFunc(ident) {
 var func = Module["_" + ident];
 assert(func, "Cannot call unknown function " + ident + ", make sure it is exported");
 return func;
}
var JSfuncs = {
 "stackSave": (function() {
  stackSave();
 }),
 "stackRestore": (function() {
  stackRestore();
 }),
 "arrayToC": (function(arr) {
  var ret = stackAlloc(arr.length);
  writeArrayToMemory(arr, ret);
  return ret;
 }),
 "stringToC": (function(str) {
  var ret = 0;
  if (str !== null && str !== undefined && str !== 0) {
   var len = (str.length << 2) + 1;
   ret = stackAlloc(len);
   stringToUTF8(str, ret, len);
  }
  return ret;
 })
};
var toC = {
 "string": JSfuncs["stringToC"],
 "array": JSfuncs["arrayToC"]
};
function ccall(ident, returnType, argTypes, args, opts) {
 var func = getCFunc(ident);
 var cArgs = [];
 var stack = 0;
 if (args) {
  for (var i = 0; i < args.length; i++) {
   var converter = toC[argTypes[i]];
   if (converter) {
    if (stack === 0) stack = stackSave();
    cArgs[i] = converter(args[i]);
   } else {
    cArgs[i] = args[i];
   }
  }
 }
 var ret = func.apply(null, cArgs);
 if (returnType === "string") ret = Pointer_stringify(ret); else if (returnType === "boolean") ret = Boolean(ret);
 if (stack !== 0) {
  stackRestore(stack);
 }
 return ret;
}
function setValue(ptr, value, type, noSafe) {
 type = type || "i8";
 if (type.charAt(type.length - 1) === "*") type = "i32";
 switch (type) {
 case "i1":
  HEAP8[ptr >> 0] = value;
  break;
 case "i8":
  HEAP8[ptr >> 0] = value;
  break;
 case "i16":
  HEAP16[ptr >> 1] = value;
  break;
 case "i32":
  HEAP32[ptr >> 2] = value;
  break;
 case "i64":
  tempI64 = [ value >>> 0, (tempDouble = value, +Math_abs(tempDouble) >= +1 ? tempDouble > +0 ? (Math_min(+Math_floor(tempDouble / +4294967296), +4294967295) | 0) >>> 0 : ~~+Math_ceil((tempDouble - +(~~tempDouble >>> 0)) / +4294967296) >>> 0 : 0) ], HEAP32[ptr >> 2] = tempI64[0], HEAP32[ptr + 4 >> 2] = tempI64[1];
  break;
 case "float":
  HEAPF32[ptr >> 2] = value;
  break;
 case "double":
  HEAPF64[ptr >> 3] = value;
  break;
 default:
  abort("invalid type for setValue: " + type);
 }
}
var ALLOC_STATIC = 2;
var ALLOC_NONE = 4;
function Pointer_stringify(ptr, length) {
 if (length === 0 || !ptr) return "";
 var hasUtf = 0;
 var t;
 var i = 0;
 while (1) {
  t = HEAPU8[ptr + i >> 0];
  hasUtf |= t;
  if (t == 0 && !length) break;
  i++;
  if (length && i == length) break;
 }
 if (!length) length = i;
 var ret = "";
 if (hasUtf < 128) {
  var MAX_CHUNK = 1024;
  var curr;
  while (length > 0) {
   curr = String.fromCharCode.apply(String, HEAPU8.subarray(ptr, ptr + Math.min(length, MAX_CHUNK)));
   ret = ret ? ret + curr : curr;
   ptr += MAX_CHUNK;
   length -= MAX_CHUNK;
  }
  return ret;
 }
 return UTF8ToString(ptr);
}
var UTF8Decoder = typeof TextDecoder !== "undefined" ? new TextDecoder("utf8") : undefined;
function UTF8ArrayToString(u8Array, idx) {
 var endPtr = idx;
 while (u8Array[endPtr]) ++endPtr;
 if (endPtr - idx > 16 && u8Array.subarray && UTF8Decoder) {
  return UTF8Decoder.decode(u8Array.subarray(idx, endPtr));
 } else {
  var u0, u1, u2, u3, u4, u5;
  var str = "";
  while (1) {
   u0 = u8Array[idx++];
   if (!u0) return str;
   if (!(u0 & 128)) {
    str += String.fromCharCode(u0);
    continue;
   }
   u1 = u8Array[idx++] & 63;
   if ((u0 & 224) == 192) {
    str += String.fromCharCode((u0 & 31) << 6 | u1);
    continue;
   }
   u2 = u8Array[idx++] & 63;
   if ((u0 & 240) == 224) {
    u0 = (u0 & 15) << 12 | u1 << 6 | u2;
   } else {
    u3 = u8Array[idx++] & 63;
    if ((u0 & 248) == 240) {
     u0 = (u0 & 7) << 18 | u1 << 12 | u2 << 6 | u3;
    } else {
     u4 = u8Array[idx++] & 63;
     if ((u0 & 252) == 248) {
      u0 = (u0 & 3) << 24 | u1 << 18 | u2 << 12 | u3 << 6 | u4;
     } else {
      u5 = u8Array[idx++] & 63;
      u0 = (u0 & 1) << 30 | u1 << 24 | u2 << 18 | u3 << 12 | u4 << 6 | u5;
     }
    }
   }
   if (u0 < 65536) {
    str += String.fromCharCode(u0);
   } else {
    var ch = u0 - 65536;
    str += String.fromCharCode(55296 | ch >> 10, 56320 | ch & 1023);
   }
  }
 }
}
function UTF8ToString(ptr) {
 return UTF8ArrayToString(HEAPU8, ptr);
}
function stringToUTF8Array(str, outU8Array, outIdx, maxBytesToWrite) {
 if (!(maxBytesToWrite > 0)) return 0;
 var startIdx = outIdx;
 var endIdx = outIdx + maxBytesToWrite - 1;
 for (var i = 0; i < str.length; ++i) {
  var u = str.charCodeAt(i);
  if (u >= 55296 && u <= 57343) u = 65536 + ((u & 1023) << 10) | str.charCodeAt(++i) & 1023;
  if (u <= 127) {
   if (outIdx >= endIdx) break;
   outU8Array[outIdx++] = u;
  } else if (u <= 2047) {
   if (outIdx + 1 >= endIdx) break;
   outU8Array[outIdx++] = 192 | u >> 6;
   outU8Array[outIdx++] = 128 | u & 63;
  } else if (u <= 65535) {
   if (outIdx + 2 >= endIdx) break;
   outU8Array[outIdx++] = 224 | u >> 12;
   outU8Array[outIdx++] = 128 | u >> 6 & 63;
   outU8Array[outIdx++] = 128 | u & 63;
  } else if (u <= 2097151) {
   if (outIdx + 3 >= endIdx) break;
   outU8Array[outIdx++] = 240 | u >> 18;
   outU8Array[outIdx++] = 128 | u >> 12 & 63;
   outU8Array[outIdx++] = 128 | u >> 6 & 63;
   outU8Array[outIdx++] = 128 | u & 63;
  } else if (u <= 67108863) {
   if (outIdx + 4 >= endIdx) break;
   outU8Array[outIdx++] = 248 | u >> 24;
   outU8Array[outIdx++] = 128 | u >> 18 & 63;
   outU8Array[outIdx++] = 128 | u >> 12 & 63;
   outU8Array[outIdx++] = 128 | u >> 6 & 63;
   outU8Array[outIdx++] = 128 | u & 63;
  } else {
   if (outIdx + 5 >= endIdx) break;
   outU8Array[outIdx++] = 252 | u >> 30;
   outU8Array[outIdx++] = 128 | u >> 24 & 63;
   outU8Array[outIdx++] = 128 | u >> 18 & 63;
   outU8Array[outIdx++] = 128 | u >> 12 & 63;
   outU8Array[outIdx++] = 128 | u >> 6 & 63;
   outU8Array[outIdx++] = 128 | u & 63;
  }
 }
 outU8Array[outIdx] = 0;
 return outIdx - startIdx;
}
function stringToUTF8(str, outPtr, maxBytesToWrite) {
 return stringToUTF8Array(str, HEAPU8, outPtr, maxBytesToWrite);
}
function lengthBytesUTF8(str) {
 var len = 0;
 for (var i = 0; i < str.length; ++i) {
  var u = str.charCodeAt(i);
  if (u >= 55296 && u <= 57343) u = 65536 + ((u & 1023) << 10) | str.charCodeAt(++i) & 1023;
  if (u <= 127) {
   ++len;
  } else if (u <= 2047) {
   len += 2;
  } else if (u <= 65535) {
   len += 3;
  } else if (u <= 2097151) {
   len += 4;
  } else if (u <= 67108863) {
   len += 5;
  } else {
   len += 6;
  }
 }
 return len;
}
var UTF16Decoder = typeof TextDecoder !== "undefined" ? new TextDecoder("utf-16le") : undefined;
function demangle(func) {
 return func;
}
function demangleAll(text) {
 var regex = /__Z[\w\d_]+/g;
 return text.replace(regex, (function(x) {
  var y = demangle(x);
  return x === y ? x : x + " [" + y + "]";
 }));
}
function jsStackTrace() {
 var err = new Error;
 if (!err.stack) {
  try {
   throw new Error(0);
  } catch (e) {
   err = e;
  }
  if (!err.stack) {
   return "(no stack trace available)";
  }
 }
 return err.stack.toString();
}
var buffer, HEAP8, HEAPU8, HEAP16, HEAPU16, HEAP32, HEAPU32, HEAPF32, HEAPF64;
function updateGlobalBufferViews() {
 Module["HEAP8"] = HEAP8 = new Int8Array(buffer);
 Module["HEAP16"] = HEAP16 = new Int16Array(buffer);
 Module["HEAP32"] = HEAP32 = new Int32Array(buffer);
 Module["HEAPU8"] = HEAPU8 = new Uint8Array(buffer);
 Module["HEAPU16"] = HEAPU16 = new Uint16Array(buffer);
 Module["HEAPU32"] = HEAPU32 = new Uint32Array(buffer);
 Module["HEAPF32"] = HEAPF32 = new Float32Array(buffer);
 Module["HEAPF64"] = HEAPF64 = new Float64Array(buffer);
}
var STATIC_BASE, STATICTOP, staticSealed;
var STACK_BASE, STACKTOP, STACK_MAX;
var DYNAMIC_BASE, DYNAMICTOP_PTR;
STATIC_BASE = STATICTOP = STACK_BASE = STACKTOP = STACK_MAX = DYNAMIC_BASE = DYNAMICTOP_PTR = 0;
staticSealed = false;
function abortOnCannotGrowMemory() {
 abort("Cannot enlarge memory arrays. Either (1) compile with  -s TOTAL_MEMORY=X  with X higher than the current value " + TOTAL_MEMORY + ", (2) compile with  -s ALLOW_MEMORY_GROWTH=1  which allows increasing the size at runtime but prevents some optimizations, (3) set Module.TOTAL_MEMORY to a higher value before the program runs, or (4) if you want malloc to return NULL (0) instead of this abort, compile with  -s ABORTING_MALLOC=0 ");
}
function enlargeMemory() {
 abortOnCannotGrowMemory();
}
var TOTAL_STACK = Module["TOTAL_STACK"] || 5242880;
var TOTAL_MEMORY = Module["TOTAL_MEMORY"] || 67108864;
if (TOTAL_MEMORY < TOTAL_STACK) Module.printErr("TOTAL_MEMORY should be larger than TOTAL_STACK, was " + TOTAL_MEMORY + "! (TOTAL_STACK=" + TOTAL_STACK + ")");
if (Module["buffer"]) {
 buffer = Module["buffer"];
} else {
 {
  buffer = new ArrayBuffer(TOTAL_MEMORY);
 }
 Module["buffer"] = buffer;
}
updateGlobalBufferViews();
function getTotalMemory() {
 return TOTAL_MEMORY;
}
HEAP32[0] = 1668509029;
HEAP16[1] = 25459;
if (HEAPU8[2] !== 115 || HEAPU8[3] !== 99) throw "Runtime error: expected the system to be little-endian!";
function callRuntimeCallbacks(callbacks) {
 while (callbacks.length > 0) {
  var callback = callbacks.shift();
  if (typeof callback == "function") {
   callback();
   continue;
  }
  var func = callback.func;
  if (typeof func === "number") {
   if (callback.arg === undefined) {
    Module["dynCall_v"](func);
   } else {
    Module["dynCall_vi"](func, callback.arg);
   }
  } else {
   func(callback.arg === undefined ? null : callback.arg);
  }
 }
}
var __ATPRERUN__ = [];
var __ATINIT__ = [];
var __ATMAIN__ = [];
var __ATEXIT__ = [];
var __ATPOSTRUN__ = [];
var runtimeInitialized = false;
var runtimeExited = false;
function preRun() {
 if (Module["preRun"]) {
  if (typeof Module["preRun"] == "function") Module["preRun"] = [ Module["preRun"] ];
  while (Module["preRun"].length) {
   addOnPreRun(Module["preRun"].shift());
  }
 }
 callRuntimeCallbacks(__ATPRERUN__);
}
function ensureInitRuntime() {
 if (runtimeInitialized) return;
 runtimeInitialized = true;
 callRuntimeCallbacks(__ATINIT__);
}
function preMain() {
 callRuntimeCallbacks(__ATMAIN__);
}
function exitRuntime() {
 callRuntimeCallbacks(__ATEXIT__);
 runtimeExited = true;
}
function postRun() {
 if (Module["postRun"]) {
  if (typeof Module["postRun"] == "function") Module["postRun"] = [ Module["postRun"] ];
  while (Module["postRun"].length) {
   addOnPostRun(Module["postRun"].shift());
  }
 }
 callRuntimeCallbacks(__ATPOSTRUN__);
}
function addOnPreRun(cb) {
 __ATPRERUN__.unshift(cb);
}
function addOnPostRun(cb) {
 __ATPOSTRUN__.unshift(cb);
}
function writeArrayToMemory(array, buffer) {
 HEAP8.set(array, buffer);
}
function writeAsciiToMemory(str, buffer, dontAddNull) {
 for (var i = 0; i < str.length; ++i) {
  HEAP8[buffer++ >> 0] = str.charCodeAt(i);
 }
 if (!dontAddNull) HEAP8[buffer >> 0] = 0;
}
var Math_abs = Math.abs;
var Math_cos = Math.cos;
var Math_sin = Math.sin;
var Math_tan = Math.tan;
var Math_acos = Math.acos;
var Math_asin = Math.asin;
var Math_atan = Math.atan;
var Math_atan2 = Math.atan2;
var Math_exp = Math.exp;
var Math_log = Math.log;
var Math_sqrt = Math.sqrt;
var Math_ceil = Math.ceil;
var Math_floor = Math.floor;
var Math_pow = Math.pow;
var Math_imul = Math.imul;
var Math_fround = Math.fround;
var Math_round = Math.round;
var Math_min = Math.min;
var Math_max = Math.max;
var Math_clz32 = Math.clz32;
var Math_trunc = Math.trunc;
var runDependencies = 0;
var runDependencyWatcher = null;
var dependenciesFulfilled = null;
function addRunDependency(id) {
 runDependencies++;
 if (Module["monitorRunDependencies"]) {
  Module["monitorRunDependencies"](runDependencies);
 }
}
function removeRunDependency(id) {
 runDependencies--;
 if (Module["monitorRunDependencies"]) {
  Module["monitorRunDependencies"](runDependencies);
 }
 if (runDependencies == 0) {
  if (runDependencyWatcher !== null) {
   clearInterval(runDependencyWatcher);
   runDependencyWatcher = null;
  }
  if (dependenciesFulfilled) {
   var callback = dependenciesFulfilled;
   dependenciesFulfilled = null;
   callback();
  }
 }
}
Module["preloadedImages"] = {};
Module["preloadedAudios"] = {};
var memoryInitializer = null;
var dataURIPrefix = "data:application/octet-stream;base64,";
function isDataURI(filename) {
 return String.prototype.startsWith ? filename.startsWith(dataURIPrefix) : filename.indexOf(dataURIPrefix) === 0;
}
STATIC_BASE = GLOBAL_BASE;
STATICTOP = STATIC_BASE + 8864;
__ATINIT__.push();
memoryInitializer = "data:application/octet-stream;base64,CgAAAA0AAAAQAAAACwAAAA4AAAASAAAADQAAABAAAAAUAAAADgAAABIAAAAXAAAAEAAAABQAAAAZAAAAEgAAABcAAAAdAAAAAAAAAAEAAAACAAAAAwAAAAQAAAAFAAAABgAAAAcAAAAIAAAACQAAAAoAAAALAAAADAAAAA0AAAAOAAAADwAAABAAAAARAAAAEgAAABMAAAAUAAAAFQAAABYAAAAXAAAAGAAAABkAAAAaAAAAGwAAABwAAAAdAAAAHQAAAB4AAAAfAAAAIAAAACAAAAAhAAAAIgAAACIAAAAjAAAAIwAAACQAAAAkAAAAJQAAACUAAAAlAAAAJgAAACYAAAAmAAAAJwAAACcAAAAnAAAAJwAAAAEAAAABAAAAAgAAAAIAAAADAAAAAwAAAAMAAAADAAAAAAAAAAEAAAAEAAAABQAAAAIAAAADAAAABgAAAAcAAAAIAAAACQAAAAwAAAANAAAACgAAAAsAAAAOAAAADwAAAAAAAAAFAAAABAAAAAAAAAAAAAAABwAAAAQAAAACAAAABAAAAAEAAAAEAAAABAAAAAQAAAADAAAABAAAAAYAAAAAAAAADQAAAAQAAAAIAAAAAAAAAA8AAAAEAAAACgAAAAQAAAAJAAAABAAAAAwAAAAEAAAACwAAAAQAAAAOAAAAAAAAABEAAAAEAAAAEAAAAAAAAAATAAAABAAAABIAAAAAAAAAFQAAAAQAAAAUAAAAAAAAABcAAAAEAAAAFgAAAAEAAAAKAAAAAQAAAAsAAAAEAAAAAAAAAAQAAAABAAAAAQAAAA4AAAABAAAADwAAAAQAAAAEAAAABAAAAAUAAAAEAAAAAgAAAAQAAAADAAAABAAAAAgAAAAEAAAACQAAAAQAAAAGAAAABAAAAAcAAAAEAAAADAAAAAQAAAANAAAAAQAAABIAAAABAAAAEwAAAAQAAAAQAAAABAAAABEAAAABAAAAFgAAAAEAAAAXAAAABAAAABQAAAAEAAAAFQAAAAEAAAALAAAAAQAAAA4AAAAEAAAAAQAAAP8AAAAEAAAAAQAAAA8AAAACAAAACgAAAAQAAAAFAAAA/wAAAAAAAAAEAAAAAwAAAAQAAAAGAAAABAAAAAkAAAD/AAAADAAAAAQAAAAHAAAA/wAAAAIAAAAEAAAADQAAAP8AAAAIAAAAAQAAABMAAAACAAAAEgAAAAQAAAARAAAA/wAAABAAAAABAAAAFwAAAAIAAAAWAAAABAAAABUAAAD/AAAAFAAAAAMAAAAPAAAAAQAAAAoAAAAAAAAABQAAAAQAAAAAAAAAAQAAAAsAAAABAAAADgAAAAQAAAABAAAABAAAAAQAAAAAAAAABwAAAAQAAAACAAAAAAAAAA0AAAAEAAAACAAAAAQAAAADAAAABAAAAAYAAAAEAAAACQAAAAQAAAAMAAAAAwAAABMAAAABAAAAEgAAAAAAAAARAAAABAAAABAAAAADAAAAFwAAAAEAAAAWAAAAAAAAABUAAAAEAAAAFAAAAAAAAAAEAAAAAAAAAAQAAAAIAAAADAAAAAgAAAAMAAAAAAAAAAQAAAAAAAAABAAAAAgAAAAMAAAACAAAAAwAAAAAAAAAAAAAAAQAAAAEAAAAAAAAAAAAAAAEAAAABAAAAAgAAAAIAAAADAAAAAwAAAAIAAAACAAAAAwAAAAMAAAAAAAAAAUAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAAAAAAABQAAAAAAAAAHAAAA/wAAAAAAAAD/AAAAAAAAAAAAAAAFAAAABAAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAAAAAAUAAAAEAAAAAAAAAAAAAAAHAAAABAAAAAIAAAAEAAAAAQAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAABAAAABAAAAAMAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAEAAAAEAAAABAAAAP8AAAAAAAAA/wAAAAAAAAAEAAAAAQAAAAQAAAAEAAAABAAAAAMAAAAEAAAABgAAAAAAAAANAAAA/wAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAAAAAA0AAAAAAAAADwAAAP8AAAAAAAAA/wAAAAAAAAAAAAAADQAAAAQAAAAIAAAA/wAAAAAAAAD/AAAAAAAAAAAAAAANAAAABAAAAAgAAAAAAAAADwAAAAQAAAAKAAAABAAAAAkAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAAEAAAACQAAAAQAAAALAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAAJAAAABAAAAAwAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAkAAAAEAAAADAAAAAQAAAALAAAABAAAAA4AAAABAAAACgAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAEAAAAKAAAABAAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAQAAAAoAAAABAAAACwAAAP8AAAAAAAAA/wAAAAAAAAABAAAACgAAAAEAAAALAAAABAAAAAAAAAAEAAAAAQAAAAEAAAAOAAAA/wAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAQAAAA4AAAAEAAAABAAAAP8AAAAAAAAA/wAAAAAAAAABAAAADgAAAAEAAAAPAAAA/wAAAAAAAAD/AAAAAAAAAAEAAAAOAAAAAQAAAA8AAAAEAAAABAAAAAQAAAAFAAAABAAAAAIAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAAEAAAAAgAAAAQAAAAIAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAACAAAABAAAAAMAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAIAAAAEAAAAAwAAAAQAAAAIAAAABAAAAAkAAAAEAAAABgAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAAGAAAABAAAAAwAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAYAAAAEAAAABwAAAP8AAAAAAAAA/wAAAAAAAAAEAAAABgAAAAQAAAAHAAAABAAAAAwAAAAEAAAADQAAAAEAAAAOAAAA/wAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAQAAAA4AAAD/AAAABAAAAP8AAAAAAAAA/wAAAAAAAAABAAAACwAAAAEAAAAOAAAA/wAAAAAAAAD/AAAAAAAAAAEAAAALAAAAAQAAAA4AAAAEAAAAAQAAAP8AAAAEAAAAAgAAAAoAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAACAAAACgAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAEAAAAPAAAAAgAAAAoAAAD/AAAAAAAAAP8AAAAAAAAAAQAAAA8AAAACAAAACgAAAAQAAAAFAAAA/wAAAAAAAAAEAAAABgAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAAGAAAA/wAAAAwAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAMAAAAEAAAABgAAAP8AAAAAAAAA/wAAAAAAAAAEAAAAAwAAAAQAAAAGAAAABAAAAAkAAAD/AAAADAAAAP8AAAACAAAA/wAAAAAAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAIAAAD/AAAACAAAAP8AAAAAAAAA/wAAAAAAAAAEAAAABwAAAP8AAAACAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAAHAAAA/wAAAAIAAAAEAAAADQAAAP8AAAAIAAAAAwAAAA8AAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAADAAAADwAAAAAAAAAFAAAA/wAAAAAAAAD/AAAAAAAAAAMAAAAPAAAAAQAAAAoAAAD/AAAAAAAAAP8AAAAAAAAAAwAAAA8AAAABAAAACgAAAAAAAAAFAAAABAAAAAAAAAABAAAACwAAAP8AAAAAAAAA/wAAAAAAAAD/AAAAAAAAAAEAAAALAAAABAAAAAEAAAD/AAAAAAAAAP8AAAAAAAAAAQAAAAsAAAABAAAADgAAAP8AAAAAAAAA/wAAAAAAAAABAAAACwAAAAEAAAAOAAAABAAAAAEAAAAEAAAABAAAAAAAAAAHAAAA/wAAAAAAAAD/AAAAAAAAAP8AAAAAAAAAAAAAAAcAAAAAAAAADQAAAP8AAAAAAAAA/wAAAAAAAAAAAAAABwAAAAQAAAACAAAA/wAAAAAAAAD/AAAAAAAAAAAAAAAHAAAABAAAAAIAAAAAAAAADQAAAAQAAAAIAAAABAAAAAMAAAD/AAAAAAAAAP8AAAAAAAAA/wAAAAAAAAAEAAAAAwAAAAQAAAAJAAAA/wAAAAAAAAD/AAAAAAAAAAQAAAADAAAABAAAAAYAAAD/AAAAAAAAAP8AAAAAAAAABAAAAAMAAAAEAAAABgAAAAQAAAAJAAAABAAAAAwAAAAAAAAAAQAAAAIAAAADAAAABAAAAAUAAAAGAAAABwAAAAgAAAAJAAAACgAAAAsAAAAMAAAADQAAAA4AAAAPAAAABQAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAIAAACcHgAAAAQAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAACv////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGYgJhAGCGUYZRhDEEMQQxBDEEMQQxBDEEMQIggiCCIIIggiCCIIIggiCCIIIggiCCIIIggiCCIIIggAAAAAAAAAAGpASjAqKAogaThpOEkoSSgpICkgCRgJGGgwaDBoMGgwSCBIIEggSCAoGCgYKBgoGAgQCBAIEAgQZyhnKGcoZyhnKGcoZyhnKEcYRxhHGEcYRxhHGEcYRxhuYE5YLlAOUG5YTlAuSA5IDUANQE1ITUgtQC1ADTgNOG1QbVBNQE1ALTgtOA0wDTBrSGtIa0hrSGtIa0hrSGtISzhLOEs4SzhLOEs4SzhLOCswKzArMCswKzArMCswKzALKAsoCygLKAsoCygLKAsoAAAAAC9oL2gQgFCAMIAQeHCAUHgweBBwcHhQcDBwEGhvcG9wT2hPaC9gL2APYA9gb2hvaE9gT2AvWC9YD1gPWAAAAAAAAAAAZjhGICYgBhBmMEYYJhgGCGUoZSglECUQZCBkIGQgZCBkGGQYZBhkGEMQQxBDEEMQQxBDEEMQQxAAAAAAAAAAAGlISTgpOAkwCCgIKEgwSDAoMCgwCCAIIGdAZ0BnQGdARyhHKEcoRygnKCcoJygnKAcYBxgHGAcYAAAAAG14bXhugE6ALoAOgC54DnhOeC5wTXBNcA1wDXBtcG1wTWhNaC1oLWgNaA1obWhtaE1gTWAtYC1gDWANYAxYDFgMWAxYTFhMWExYTFgsWCxYLFgsWAxQDFAMUAxQbGBsYGxgbGBMUExQTFBMUCxQLFAsUCxQDEgMSAxIDEhrWGtYa1hrWGtYa1hrWGtYS0hLSEtIS0hLSEtIS0hLSCtIK0grSCtIK0grSCtIK0gLQAtAC0ALQAtAC0ALQAtAa1BrUGtQa1BrUGtQa1BrUEtAS0BLQEtAS0BLQEtAS0ArQCtAK0ArQCtAK0ArQCtACzgLOAs4CzgLOAs4CzgLOAAAAAAAAAAAAAAAAAAAAAAGGEY4JjgGEGZIRjAmMAYIJSglKEUoRSglICUgRSBFICUYJRhlQGVARRhFGCUQJRBkOGQ4ZDhkOGQwZDBkMGQwZChkKGQoZChkIGQgZCBkIGQYZBhkGGQYRBBEEEQQRBAkCCQIJAgkCAQABAAEAAQAAAAKgGqASoAqgAp4anhKeCp4CnBqcEpwKnAKaCloKWgJYAlgSWhJaClgKWAJWAlYaWhpaElgSWApWClYCVAJUGhgaGBoYGhgSFhIWEhYSFgoUChQKFAoUAhICEgISAhIaFhoWGhYaFhIUEhQSFBIUChIKEgoSChICEAIQAhACEAHOAc4BzgHOAc4BzgHOAc4BzAHMAcwBzAHMAcwBzAHMEdIR0hHSEdIR0hHSEdIR0gHKAcoBygHKAcoBygHKAcoZ1BnUGdQZ1BnUGdQZ1BnUEdAR0BHQEdAR0BHQEdAR0AnQCdAJ0AnQCdAJ0AnQCdAByAHIAcgByAHIAcgByAHIAYIJggAAAYABhAmEEYQAAAGGCYYRhhmGAYgJiBGIGYgBigmKEYoZigGMCYwRjBmMAY4JjhGOGY4BkAmQEZAZkAGSCZIRkhmSAZQJlBGUGZQBlgmWEZYZlgGYCZgRmBmYAZoJmhGaGZoBnAmcEZwZnAGeCZ4RnhmeAaAJoBGgGaAAABDEAIAAgAhCCEIIQghCGcgZyBIICggRxhHGCcYJxgGIAYgBiAGIAYYBhgGGAYYBhAGEAYQBhBmGGYYZhhmGCYQJhAmECYQBggGCAYIBggAAAAAAAABAQEBAQECAgICAgIDAwMDAwMEBAQEBAQFBQUFBQUGBgYGBgYHBwcHBwcICAgIAAECAwQFAAECAwQFAAECAwQFAAECAwQFAAECAwQFAAECAwQFAAECAwQFAAECAwQFAAECAwAQAQIECCADBQoMDy8HCw0OBgkfIyUqLCEiJCgnKy0uERIUGBMVGhwXGx0eFhkmKS8fDwAXGx0eBwsNDicrLS4QAwUKDBMVGhwjJSosAQIECBESFBgGCRYZICEiJCgmKQAAZVVERDQ0IyMjIxMTExMBAQEBAQEBAQEBAQEBAQEBAPnp2cjIuLinp6enl5eXl4aGhoaGhoaGdnZ2dnZ2dnbm1sa2paWVlYSEhIR0dHR0ZGRkZFRUVFRDQ0NDQ0NDQzMzMzMzMzMzIyMjIyMjIyMTExMTExMTEwMDAwMDAwMD1rbFxaWllZWEhISEVFRUVEREREQEBAQEc3Nzc3Nzc3NjY2NjY2NjYzMzMzMzMzMzIyMjIyMjIyMTExMTExMTE8W1pQWUlHR0NDQkJIODg4NjY2NjU1NTU0NDQ0MTExMTtZWkpISEJCQUFAQEc3Nzc2NjY2NTU1NTQ0NDQzMzMzOmBhUVhISEhJOTk5OTk5OTc3Nzc3Nzc3NjY2NjY2NjY1NTU1NTU1NTQ0NDQ0NDQ0MzMzMzMzMzMyMjIyMjIyMjlgYVFXR0dHSDg4ODg4ODg2NjY2NjY2NjQ0NDQ0NDQ0MzMzMzMzMzMyMjIyMjIyMjUlJSUlJSUlJSUlJSUlJSUoYGJSUUFBQUc3Nzc3Nzc3NjY2NjY2NjYzMzMzMzMzMzUlJSUlJSUlJSUlJSUlJSUkJCQkJCQkJCQkJCQkJCQkIWBnV1JCQkJFNTU1NTU1NTYmJiYmJiYmJiYmJiYmJiYkJCQkJCQkJCQkJCQkJCQkIyMjIyMjIyMjIyMjIyMjIyFQVkZCMjIyNSUlJSUlJSUkJCQkJCQkJCMjIyMjIyMjIEFCMjMzNTU0FBQUFBQUFBBBRDQyIiIiIxMTExMTExMQMTMjIhISEhAhIhIREBIhIBATIiEgJDMyIiEhICAlNDMyMSEgICEyNDM2NTAgIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4fICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj9AQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVpbXF1eX2BhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ent8fX5/gIGCg4SFhoeIiYqLjI2Oj5CRkpOUlZaXmJmam5ydnp+goaKjpKWmp6ipqqusra6vsLGys7S1tre4ubq7vL2+v8DBwsPExcbHyMnKy8zNzs/Q0dLT1NXW19jZ2tvc3d7f4OHi4+Tl5ufo6err7O3u7/Dx8vP09fb3+Pn6+/z9/v///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////wAAAAAAAAAAAAAAAAAAAAAEBAUGBwgJCgwNDxEUFhkcICQoLTI4P0dQWmVxf5Citsvi//8AAAAAAAAAAAAAAAAAAAAAAgICAwMDAwQEBAYGBwcICAkJCgoLCwwMDQ0ODg8PEBARERISAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAABAAABAAABAAEBAAEBAQEBAQEBAQEBAQEBAQECAQECAQECAQECAQIDAQIDAgIDAgIEAgMEAgMEAwMFAwQGAwQGBAUHBAUIBAYJBQcKBggLBggNBwoOCAsQCQwSCg0UCw8XDREZREVDT0RFUiBJTklUSUFMSVpBVElPTiBGQUlMRUQ=";
var tempDoublePtr = STATICTOP;
STATICTOP += 16;
var SYSCALLS = {
 varargs: 0,
 get: (function(varargs) {
  SYSCALLS.varargs += 4;
  var ret = HEAP32[SYSCALLS.varargs - 4 >> 2];
  return ret;
 }),
 getStr: (function() {
  var ret = Pointer_stringify(SYSCALLS.get());
  return ret;
 }),
 get64: (function() {
  var low = SYSCALLS.get(), high = SYSCALLS.get();
  if (low >= 0) assert(high === 0); else assert(high === -1);
  return low;
 }),
 getZero: (function() {
  assert(SYSCALLS.get() === 0);
 })
};
function ___syscall140(which, varargs) {
 SYSCALLS.varargs = varargs;
 try {
  var stream = SYSCALLS.getStreamFromFD(), offset_high = SYSCALLS.get(), offset_low = SYSCALLS.get(), result = SYSCALLS.get(), whence = SYSCALLS.get();
  var offset = offset_low;
  FS.llseek(stream, offset, whence);
  HEAP32[result >> 2] = stream.position;
  if (stream.getdents && offset === 0 && whence === 0) stream.getdents = null;
  return 0;
 } catch (e) {
  if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
  return -e.errno;
 }
}
function flush_NO_FILESYSTEM() {
 var fflush = Module["_fflush"];
 if (fflush) fflush(0);
 var printChar = ___syscall146.printChar;
 if (!printChar) return;
 var buffers = ___syscall146.buffers;
 if (buffers[1].length) printChar(1, 10);
 if (buffers[2].length) printChar(2, 10);
}
function ___syscall146(which, varargs) {
 SYSCALLS.varargs = varargs;
 try {
  var stream = SYSCALLS.get(), iov = SYSCALLS.get(), iovcnt = SYSCALLS.get();
  var ret = 0;
  if (!___syscall146.buffers) {
   ___syscall146.buffers = [ null, [], [] ];
   ___syscall146.printChar = (function(stream, curr) {
    var buffer = ___syscall146.buffers[stream];
    assert(buffer);
    if (curr === 0 || curr === 10) {
     (stream === 1 ? Module["print"] : Module["printErr"])(UTF8ArrayToString(buffer, 0));
     buffer.length = 0;
    } else {
     buffer.push(curr);
    }
   });
  }
  for (var i = 0; i < iovcnt; i++) {
   var ptr = HEAP32[iov + i * 8 >> 2];
   var len = HEAP32[iov + (i * 8 + 4) >> 2];
   for (var j = 0; j < len; j++) {
    ___syscall146.printChar(stream, HEAPU8[ptr + j]);
   }
   ret += len;
  }
  return ret;
 } catch (e) {
  if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
  return -e.errno;
 }
}
function ___syscall54(which, varargs) {
 SYSCALLS.varargs = varargs;
 try {
  return 0;
 } catch (e) {
  if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
  return -e.errno;
 }
}
function ___syscall6(which, varargs) {
 SYSCALLS.varargs = varargs;
 try {
  var stream = SYSCALLS.getStreamFromFD();
  FS.close(stream);
  return 0;
 } catch (e) {
  if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
  return -e.errno;
 }
}
function _broadwayOnHeadersDecoded() {
 par_broadwayOnHeadersDecoded();
}
Module["_broadwayOnHeadersDecoded"] = _broadwayOnHeadersDecoded;
function _broadwayOnPictureDecoded($buffer, width, height) {
 par_broadwayOnPictureDecoded($buffer, width, height);
}
Module["_broadwayOnPictureDecoded"] = _broadwayOnPictureDecoded;
function _emscripten_memcpy_big(dest, src, num) {
 HEAPU8.set(HEAPU8.subarray(src, src + num), dest);
 return dest;
}
function ___setErrNo(value) {
 if (Module["___errno_location"]) HEAP32[Module["___errno_location"]() >> 2] = value;
 return value;
}
DYNAMICTOP_PTR = staticAlloc(4);
STACK_BASE = STACKTOP = alignMemory(STATICTOP);
STACK_MAX = STACK_BASE + TOTAL_STACK;
DYNAMIC_BASE = alignMemory(STACK_MAX);
HEAP32[DYNAMICTOP_PTR >> 2] = DYNAMIC_BASE;
staticSealed = true;
var ASSERTIONS = false;
function intArrayToString(array) {
 var ret = [];
 for (var i = 0; i < array.length; i++) {
  var chr = array[i];
  if (chr > 255) {
   if (ASSERTIONS) {
    assert(false, "Character code " + chr + " (" + String.fromCharCode(chr) + ")  at offset " + i + " not in 0x00-0xFF.");
   }
   chr &= 255;
  }
  ret.push(String.fromCharCode(chr));
 }
 return ret.join("");
}
var decodeBase64 = typeof atob === "function" ? atob : (function(input) {
 var keyStr = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
 var output = "";
 var chr1, chr2, chr3;
 var enc1, enc2, enc3, enc4;
 var i = 0;
 input = input.replace(/[^A-Za-z0-9\+\/\=]/g, "");
 do {
  enc1 = keyStr.indexOf(input.charAt(i++));
  enc2 = keyStr.indexOf(input.charAt(i++));
  enc3 = keyStr.indexOf(input.charAt(i++));
  enc4 = keyStr.indexOf(input.charAt(i++));
  chr1 = enc1 << 2 | enc2 >> 4;
  chr2 = (enc2 & 15) << 4 | enc3 >> 2;
  chr3 = (enc3 & 3) << 6 | enc4;
  output = output + String.fromCharCode(chr1);
  if (enc3 !== 64) {
   output = output + String.fromCharCode(chr2);
  }
  if (enc4 !== 64) {
   output = output + String.fromCharCode(chr3);
  }
 } while (i < input.length);
 return output;
});
function intArrayFromBase64(s) {
 if (typeof ENVIRONMENT_IS_NODE === "boolean" && ENVIRONMENT_IS_NODE) {
  var buf;
  try {
   buf = Buffer.from(s, "base64");
  } catch (_) {
   buf = new Buffer(s, "base64");
  }
  return new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
 }
 try {
  var decoded = decodeBase64(s);
  var bytes = new Uint8Array(decoded.length);
  for (var i = 0; i < decoded.length; ++i) {
   bytes[i] = decoded.charCodeAt(i);
  }
  return bytes;
 } catch (_) {
  throw new Error("Converting base64 string to bytes failed.");
 }
}
function tryParseAsDataURI(filename) {
 if (!isDataURI(filename)) {
  return;
 }
 return intArrayFromBase64(filename.slice(dataURIPrefix.length));
}
function invoke_ii(index, a1) {
 try {
  return Module["dynCall_ii"](index, a1);
 } catch (e) {
  if (typeof e !== "number" && e !== "longjmp") throw e;
  Module["setThrew"](1, 0);
 }
}
function invoke_iiii(index, a1, a2, a3) {
 try {
  return Module["dynCall_iiii"](index, a1, a2, a3);
 } catch (e) {
  if (typeof e !== "number" && e !== "longjmp") throw e;
  Module["setThrew"](1, 0);
 }
}
function invoke_viiiii(index, a1, a2, a3, a4, a5) {
 try {
  Module["dynCall_viiiii"](index, a1, a2, a3, a4, a5);
 } catch (e) {
  if (typeof e !== "number" && e !== "longjmp") throw e;
  Module["setThrew"](1, 0);
 }
}
Module.asmGlobalArg = {
 "Math": Math,
 "Int8Array": Int8Array,
 "Int16Array": Int16Array,
 "Int32Array": Int32Array,
 "Uint8Array": Uint8Array,
 "Uint16Array": Uint16Array,
 "Uint32Array": Uint32Array,
 "Float32Array": Float32Array,
 "Float64Array": Float64Array,
 "NaN": NaN,
 "Infinity": Infinity
};
Module.asmLibraryArg = {
 "abort": abort,
 "assert": assert,
 "enlargeMemory": enlargeMemory,
 "getTotalMemory": getTotalMemory,
 "abortOnCannotGrowMemory": abortOnCannotGrowMemory,
 "invoke_ii": invoke_ii,
 "invoke_iiii": invoke_iiii,
 "invoke_viiiii": invoke_viiiii,
 "___setErrNo": ___setErrNo,
 "___syscall140": ___syscall140,
 "___syscall146": ___syscall146,
 "___syscall54": ___syscall54,
 "___syscall6": ___syscall6,
 "_broadwayOnHeadersDecoded": _broadwayOnHeadersDecoded,
 "_broadwayOnPictureDecoded": _broadwayOnPictureDecoded,
 "_emscripten_memcpy_big": _emscripten_memcpy_big,
 "flush_NO_FILESYSTEM": flush_NO_FILESYSTEM,
 "DYNAMICTOP_PTR": DYNAMICTOP_PTR,
 "tempDoublePtr": tempDoublePtr,
 "ABORT": ABORT,
 "STACKTOP": STACKTOP,
 "STACK_MAX": STACK_MAX
};
// EMSCRIPTEN_START_ASM

var asm = (/** @suppress {uselessCode} */ function(global,env,buffer) {

 "use asm";
 var a = new global.Int8Array(buffer);
 var b = new global.Int16Array(buffer);
 var c = new global.Int32Array(buffer);
 var d = new global.Uint8Array(buffer);
 var e = new global.Uint16Array(buffer);
 var f = new global.Uint32Array(buffer);
 var g = new global.Float32Array(buffer);
 var h = new global.Float64Array(buffer);
 var i = env.DYNAMICTOP_PTR | 0;
 var j = env.tempDoublePtr | 0;
 var k = env.ABORT | 0;
 var l = env.STACKTOP | 0;
 var m = env.STACK_MAX | 0;
 var n = 0;
 var o = 0;
 var p = 0;
 var q = 0;
 var r = global.NaN, s = global.Infinity;
 var t = 0, u = 0, v = 0, w = 0, x = 0.0;
 var y = 0;
 var z = global.Math.floor;
 var A = global.Math.abs;
 var B = global.Math.sqrt;
 var C = global.Math.pow;
 var D = global.Math.cos;
 var E = global.Math.sin;
 var F = global.Math.tan;
 var G = global.Math.acos;
 var H = global.Math.asin;
 var I = global.Math.atan;
 var J = global.Math.atan2;
 var K = global.Math.exp;
 var L = global.Math.log;
 var M = global.Math.ceil;
 var N = global.Math.imul;
 var O = global.Math.min;
 var P = global.Math.max;
 var Q = global.Math.clz32;
 var R = env.abort;
 var S = env.assert;
 var T = env.enlargeMemory;
 var U = env.getTotalMemory;
 var V = env.abortOnCannotGrowMemory;
 var W = env.invoke_ii;
 var X = env.invoke_iiii;
 var Y = env.invoke_viiiii;
 var Z = env.___setErrNo;
 var _ = env.___syscall140;
 var $ = env.___syscall146;
 var aa = env.___syscall54;
 var ba = env.___syscall6;
 var ca = env._broadwayOnHeadersDecoded;
 var da = env._broadwayOnPictureDecoded;
 var ea = env._emscripten_memcpy_big;
 var fa = env.flush_NO_FILESYSTEM;
 var ga = 0.0;
 
// EMSCRIPTEN_START_FUNCS
function Ta(e, f, g, h, i) {
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 var j = 0, k = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0, H = 0, I = 0, J = 0, K = 0, L = 0, M = 0, O = 0, P = 0, Q = 0, R = 0, S = 0, T = 0, U = 0, V = 0, W = 0, X = 0, Y = 0, Z = 0, _ = 0, $ = 0, aa = 0, ba = 0, ca = 0, da = 0, ea = 0, fa = 0, ga = 0, ha = 0, ia = 0, ja = 0, ka = 0, la = 0, ma = 0, na = 0, oa = 0, pa = 0, qa = 0, ra = 0, ua = 0, xa = 0, ya = 0, za = 0, Aa = 0, Ba = 0, Ca = 0, Da = 0, Ea = 0, Fa = 0, Ga = 0, Ia = 0, Ka = 0, Ra = 0, Ta = 0, Ua = 0, Va = 0, Wa = 0, Xa = 0, Ya = 0, Za = 0, ab = 0, bb = 0, cb = 0, db = 0, eb = 0, fb = 0, gb = 0, hb = 0, ib = 0, jb = 0, kb = 0, lb = 0, mb = 0, nb = 0, qb = 0, rb = 0, sb = 0, tb = 0, ub = 0, vb = 0, wb = 0, xb = 0, yb = 0, zb = 0, Ab = 0, Bb = 0, Cb = 0, Db = 0, Eb = 0, Fb = 0, Gb = 0, Hb = 0, Ib = 0, Jb = 0, Kb = 0, Lb = 0, Mb = 0, Nb = 0, Ob = 0, Pb = 0, Qb = 0;
 Qb = l;
 l = l + 816 | 0;
 if (!(c[e + 3344 >> 2] | 0)) Pb = 4; else if ((c[e + 3348 >> 2] | 0) == (f | 0)) {
  c[Qb >> 2] = c[e + 3356 >> 2];
  c[Qb + 4 >> 2] = c[e + 3356 + 4 >> 2];
  c[Qb + 8 >> 2] = c[e + 3356 + 8 >> 2];
  c[Qb + 12 >> 2] = c[e + 3356 + 12 >> 2];
  c[Qb + 4 >> 2] = c[Qb >> 2];
  c[Qb + 8 >> 2] = 0;
  c[Qb + 16 >> 2] = 0;
  c[i >> 2] = c[e + 3352 >> 2];
  bb = Qb + 12 | 0;
  Ob = Qb + 8 | 0;
  L = Qb + 4 | 0;
  K = Qb + 16 | 0;
  n = c[Qb + 12 >> 2] | 0;
  J = 0;
 } else Pb = 4;
 if ((Pb | 0) == 4) {
  do if (g >>> 0 > 3) if (!(a[f >> 0] | 0)) if (!(a[f + 1 >> 0] | 0)) {
   n = a[f + 2 >> 0] | 0;
   if ((n & 255) < 2) {
    o = 2;
    t = -3;
    s = f + 3 | 0;
    u = 3;
    while (1) {
     if (!(n << 24 >> 24)) o = o + 1 | 0; else if (o >>> 0 > 1 & n << 24 >> 24 == 1) {
      v = 0;
      w = 0;
      x = s;
      y = 0;
      z = u;
      break;
     } else o = 0;
     n = a[s >> 0] | 0;
     r = u + 1 | 0;
     if ((r | 0) == (g | 0)) {
      Pb = 10;
      break;
     } else {
      t = ~u;
      s = s + 1 | 0;
      u = r;
     }
    }
    if ((Pb | 0) == 10) {
     c[i >> 2] = g;
     e = 3;
     l = Qb;
     return e | 0;
    }
    while (1) {
     n = a[x >> 0] | 0;
     o = z + 1 | 0;
     r = y + ((n << 24 >> 24 != 0 ^ 1) & 1) | 0;
     w = n << 24 >> 24 == 3 & (r | 0) == 2 ? 1 : w;
     if (n << 24 >> 24 == 1 & r >>> 0 > 1) {
      Pb = 15;
      break;
     }
     y = n << 24 >> 24 ? 0 : r;
     A = n << 24 >> 24 != 0 & r >>> 0 > 2 ? 1 : v;
     if ((o | 0) == (g | 0)) {
      Pb = 17;
      break;
     } else {
      v = A;
      x = x + 1 | 0;
      z = o;
     }
    }
    if ((Pb | 0) == 15) {
     q = z + t - r | 0;
     c[Qb + 12 >> 2] = q;
     B = u;
     C = w;
     D = v;
     E = r - (r >>> 0 < 3 ? r : 3) | 0;
     G = Qb + 12 | 0;
     break;
    } else if ((Pb | 0) == 17) {
     q = t + g - y | 0;
     c[Qb + 12 >> 2] = q;
     B = u;
     C = w;
     D = A;
     E = y;
     G = Qb + 12 | 0;
     break;
    }
   } else Pb = 18;
  } else Pb = 18; else Pb = 18; else Pb = 18; while (0);
  if ((Pb | 0) == 18) {
   c[Qb + 12 >> 2] = g;
   B = 0;
   C = 1;
   D = 0;
   E = 0;
   G = Qb + 12 | 0;
   q = g;
  }
  n = f + B | 0;
  c[Qb >> 2] = n;
  c[Qb + 4 >> 2] = n;
  c[Qb + 8 >> 2] = 0;
  c[Qb + 16 >> 2] = 0;
  c[i >> 2] = B + q + E;
  if (D | 0) {
   e = 3;
   l = Qb;
   return e | 0;
  }
  do if (!C) {
   H = 0;
   I = q;
  } else {
   s = n;
   o = n;
   n = 0;
   a : while (1) {
    while (1) {
     Ob = q;
     q = q + -1 | 0;
     if (!Ob) {
      Pb = 29;
      break a;
     }
     r = a[o >> 0] | 0;
     if ((n | 0) != 2) {
      F = n;
      break;
     }
     if (r << 24 >> 24 != 3) {
      Pb = 27;
      break;
     }
     if (!q) {
      fa = 3;
      Pb = 1869;
      break a;
     }
     n = o + 1 | 0;
     if ((d[n >> 0] | 0) > 3) {
      fa = 3;
      Pb = 1869;
      break a;
     } else {
      o = n;
      n = 0;
     }
    }
    if ((Pb | 0) == 27) {
     Pb = 0;
     if ((r & 255) < 3) {
      fa = 3;
      Pb = 1869;
      break;
     } else F = 2;
    }
    a[s >> 0] = r;
    s = s + 1 | 0;
    o = o + 1 | 0;
    n = r << 24 >> 24 == 0 ? F + 1 | 0 : 0;
   }
   if ((Pb | 0) == 29) {
    I = s - o + (c[G >> 2] | 0) | 0;
    c[G >> 2] = I;
    H = c[Qb + 16 >> 2] | 0;
    break;
   } else if ((Pb | 0) == 1869) {
    l = Qb;
    return fa | 0;
   }
  } while (0);
  c[e + 3356 >> 2] = c[Qb >> 2];
  c[e + 3356 + 4 >> 2] = c[Qb + 4 >> 2];
  c[e + 3356 + 8 >> 2] = c[Qb + 8 >> 2];
  c[e + 3356 + 12 >> 2] = c[Qb + 12 >> 2];
  c[e + 3356 + 16 >> 2] = c[Qb + 16 >> 2];
  c[e + 3352 >> 2] = c[i >> 2];
  c[e + 3348 >> 2] = f;
  bb = Qb + 12 | 0;
  Ob = Qb + 8 | 0;
  L = Qb + 4 | 0;
  K = Qb + 16 | 0;
  n = I;
  J = H;
 }
 c[e + 3344 >> 2] = 0;
 t = n << 3;
 s = J + 1 | 0;
 c[K >> 2] = s;
 c[Ob >> 2] = s & 7;
 if (t >>> 0 < s >>> 0) {
  e = 3;
  l = Qb;
  return e | 0;
 }
 u = c[Qb >> 2] | 0;
 c[L >> 2] = u + (s >>> 3);
 if ((t - s | 0) > 31) {
  n = d[u + (s >>> 3) + 1 >> 0] << 16 | d[u + (s >>> 3) >> 0] << 24 | d[u + (s >>> 3) + 2 >> 0] << 8 | d[u + (s >>> 3) + 3 >> 0];
  if (s & 7) n = (d[u + (s >>> 3) + 4 >> 0] | 0) >>> (8 - (s & 7) | 0) | n << (s & 7);
 } else if ((t - s | 0) > 0) {
  n = d[u + (s >>> 3) >> 0] << (s & 7 | 24);
  if ((t - s + -8 + (s & 7) | 0) > 0) {
   o = t - s + -8 + (s & 7) | 0;
   q = s & 7 | 24;
   r = u + (s >>> 3) | 0;
   while (1) {
    r = r + 1 | 0;
    q = q + -8 | 0;
    n = d[r >> 0] << q | n;
    if ((o | 0) <= 8) break; else o = o + -8 | 0;
   }
  }
 } else n = 0;
 q = J + 3 | 0;
 c[K >> 2] = q;
 c[Ob >> 2] = q & 7;
 if (t >>> 0 < q >>> 0) {
  o = u + (s >>> 3) | 0;
  D = -1;
 } else {
  c[L >> 2] = u + (q >>> 3);
  o = u + (q >>> 3) | 0;
  D = n >>> 30;
 }
 if ((t - q | 0) > 31) {
  n = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
  if (q & 7) n = (d[o + 4 >> 0] | 0) >>> (8 - (q & 7) | 0) | n << (q & 7);
 } else if ((t - q | 0) > 0) {
  n = d[o >> 0] << (q & 7 | 24);
  if ((t - q + -8 + (q & 7) | 0) > 0) {
   r = t - q + -8 + (q & 7) | 0;
   q = q & 7 | 24;
   while (1) {
    o = o + 1 | 0;
    q = q + -8 | 0;
    n = d[o >> 0] << q | n;
    if ((r | 0) <= 8) break; else r = r + -8 | 0;
   }
  }
 } else n = 0;
 o = J + 8 | 0;
 c[K >> 2] = o;
 c[Ob >> 2] = o & 7;
 C = n >>> 27;
 if (o >>> 0 > t >>> 0) {
  e = 0;
  l = Qb;
  return e | 0;
 }
 c[L >> 2] = u + (o >>> 3);
 if ((C + -2 | 0) >>> 0 < 3) {
  e = 3;
  l = Qb;
  return e | 0;
 }
 switch (C & 31) {
 case 5:
 case 7:
 case 8:
  {
   if ((C | 0) == 6 | (D | 0) == 0) {
    e = 3;
    l = Qb;
    return e | 0;
   }
   break;
  }
 case 6:
 case 9:
 case 10:
 case 11:
 case 12:
  {
   if (D | 0) {
    e = 3;
    l = Qb;
    return e | 0;
   }
   break;
  }
 default:
  {}
 }
 if ((C + -1 | 0) >>> 0 > 11) {
  e = 0;
  l = Qb;
  return e | 0;
 }
 b : do switch (C & 31) {
 case 6:
 case 7:
 case 8:
 case 9:
 case 10:
 case 11:
 case 13:
 case 14:
 case 15:
 case 16:
 case 17:
 case 18:
  {
   S = 1;
   Pb = 201;
   break;
  }
 case 5:
 case 1:
  {
   if (!(c[e + 1332 >> 2] | 0)) B = 0; else {
    c[e + 1332 >> 2] = 0;
    B = 1;
   };
   c[Qb + 648 >> 2] = c[Qb >> 2];
   c[Qb + 648 + 4 >> 2] = c[Qb + 4 >> 2];
   c[Qb + 648 + 8 >> 2] = c[Qb + 8 >> 2];
   c[Qb + 648 + 12 >> 2] = c[Qb + 12 >> 2];
   c[Qb + 648 + 16 >> 2] = c[Qb + 16 >> 2];
   n = va(Qb + 648 | 0, Qb + 688 | 0) | 0;
   c : do if (!n) {
    n = va(Qb + 648 | 0, Qb + 688 | 0) | 0;
    if (!n) {
     n = va(Qb + 648 | 0, Qb + 688 | 0) | 0;
     if (!n) {
      n = c[Qb + 688 >> 2] | 0;
      if (n >>> 0 > 255) {
       R = 1;
       Pb = 60;
      } else {
       y = c[e + 148 + (n << 2) >> 2] | 0;
       if (y | 0) {
        n = c[y + 4 >> 2] | 0;
        x = c[e + 20 + (n << 2) >> 2] | 0;
        if (x | 0) {
         L = c[e + 8 >> 2] | 0;
         if ((L | 0) == 32 | (n | 0) == (L | 0) | (C | 0) == 5) {
          n = c[e + 1304 >> 2] | 0;
          if ((n | 0) == (D | 0)) n = B; else n = (n | 0) == 0 | (D | 0) == 0 ? 1 : B;
          if ((c[e + 1300 >> 2] | 0) == 5) if ((C | 0) == 5) j = n; else Pb = 69; else if ((C | 0) == 5) Pb = 69; else j = n;
          if ((Pb | 0) == 69) j = 1;
          n = c[x + 12 >> 2] | 0;
          c[Qb + 628 >> 2] = c[Qb >> 2];
          c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
          c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
          c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
          c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
          d : do if (!(va(Qb + 628 | 0, Qb + 688 | 0) | 0)) {
           if (va(Qb + 628 | 0, Qb + 688 | 0) | 0) {
            Pb = 82;
            break;
           }
           if (!(va(Qb + 628 | 0, Qb + 688 | 0) | 0)) t = 0; else {
            Pb = 82;
            break;
           }
           while (1) if (!(n >>> t)) break; else t = t + 1 | 0;
           u = t + -1 | 0;
           A = Qb + 628 + 4 | 0;
           r = c[A >> 2] | 0;
           z = Qb + 628 + 12 | 0;
           v = c[z >> 2] << 3;
           g = Qb + 628 + 16 | 0;
           w = c[g >> 2] | 0;
           do if ((v - w | 0) > 31) {
            o = c[Qb + 628 + 8 >> 2] | 0;
            n = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
            if (!o) {
             o = Qb + 628 + 8 | 0;
             break;
            }
            n = (d[r + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
            o = Qb + 628 + 8 | 0;
           } else {
            if ((v - w | 0) <= 0) {
             n = 0;
             o = Qb + 628 + 8 | 0;
             break;
            }
            o = c[Qb + 628 + 8 >> 2] | 0;
            n = d[r >> 0] << o + 24;
            if ((v - w + -8 + o | 0) > 0) {
             s = v - w + -8 + o | 0;
             q = o + 24 | 0;
             o = r;
            } else {
             o = Qb + 628 + 8 | 0;
             break;
            }
            while (1) {
             o = o + 1 | 0;
             q = q + -8 | 0;
             n = d[o >> 0] << q | n;
             if ((s | 0) <= 8) {
              o = Qb + 628 + 8 | 0;
              break;
             } else s = s + -8 | 0;
            }
           } while (0);
           c[g >> 2] = u + w;
           c[o >> 2] = u + w & 7;
           n = n >>> (33 - t | 0);
           if ((u + w | 0) >>> 0 > v >>> 0) {
            Pb = 82;
            break;
           }
           c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((u + w | 0) >>> 3);
           if ((n | 0) == -1) {
            Pb = 82;
            break;
           }
           if ((c[e + 1308 >> 2] | 0) != (n | 0)) {
            c[e + 1308 >> 2] = n;
            j = 1;
           }
           e : do if ((C | 0) == 5) {
            n = c[x + 12 >> 2] | 0;
            c[Qb + 628 >> 2] = c[Qb >> 2];
            c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
            c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
            c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
            c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
            do if (!(va(Qb + 628 | 0, Qb + 688 | 0) | 0)) {
             if (va(Qb + 628 | 0, Qb + 688 | 0) | 0) break;
             if (!(va(Qb + 628 | 0, Qb + 688 | 0) | 0)) w = 0; else break;
             while (1) if (!(n >>> w)) break; else w = w + 1 | 0;
             t = w + -1 | 0;
             r = c[A >> 2] | 0;
             u = c[z >> 2] << 3;
             v = c[g >> 2] | 0;
             do if ((u - v | 0) > 31) {
              o = c[Qb + 628 + 8 >> 2] | 0;
              n = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
              if (!o) {
               o = Qb + 628 + 8 | 0;
               break;
              }
              n = (d[r + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
              o = Qb + 628 + 8 | 0;
             } else {
              if ((u - v | 0) <= 0) {
               n = 0;
               o = Qb + 628 + 8 | 0;
               break;
              }
              o = c[Qb + 628 + 8 >> 2] | 0;
              n = d[r >> 0] << o + 24;
              if ((u - v + -8 + o | 0) > 0) {
               s = u - v + -8 + o | 0;
               q = o + 24 | 0;
               o = r;
              } else {
               o = Qb + 628 + 8 | 0;
               break;
              }
              while (1) {
               o = o + 1 | 0;
               q = q + -8 | 0;
               n = d[o >> 0] << q | n;
               if ((s | 0) <= 8) {
                o = Qb + 628 + 8 | 0;
                break;
               } else s = s + -8 | 0;
              }
             } while (0);
             c[g >> 2] = t + v;
             c[o >> 2] = t + v & 7;
             if ((t + v | 0) >>> 0 > u >>> 0) break;
             c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((t + v | 0) >>> 3);
             if ((n >>> (33 - w | 0) | 0) == -1) break;
             if (va(Qb + 628 | 0, Qb + 196 | 0) | 0) break d;
             if ((c[e + 1300 >> 2] | 0) == 5) {
              o = c[Qb + 196 >> 2] | 0;
              j = (c[e + 1312 >> 2] | 0) == (o | 0) ? j : 1;
              n = e + 1312 | 0;
             } else {
              n = e + 1312 | 0;
              o = c[Qb + 196 >> 2] | 0;
             }
             c[n >> 2] = o;
             break e;
            } while (0);
            break d;
           } while (0);
           f : do switch (c[x + 16 >> 2] | 0) {
           case 0:
            {
             c[Qb + 628 >> 2] = c[Qb >> 2];
             c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
             c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
             c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
             c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
             do if (!(va(Qb + 628 | 0, Qb + 688 | 0) | 0)) {
              if (va(Qb + 628 | 0, Qb + 688 | 0) | 0) break;
              if (va(Qb + 628 | 0, Qb + 688 | 0) | 0) break;
              n = c[x + 12 >> 2] | 0;
              w = 0;
              while (1) if (!(n >>> w)) break; else w = w + 1 | 0;
              t = w + -1 | 0;
              r = c[A >> 2] | 0;
              u = c[z >> 2] << 3;
              v = c[g >> 2] | 0;
              do if ((u - v | 0) > 31) {
               o = c[Qb + 628 + 8 >> 2] | 0;
               n = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
               if (!o) {
                o = Qb + 628 + 8 | 0;
                break;
               }
               n = (d[r + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
               o = Qb + 628 + 8 | 0;
              } else {
               if ((u - v | 0) <= 0) {
                n = 0;
                o = Qb + 628 + 8 | 0;
                break;
               }
               o = c[Qb + 628 + 8 >> 2] | 0;
               n = d[r >> 0] << o + 24;
               if ((u - v + -8 + o | 0) > 0) {
                s = u - v + -8 + o | 0;
                q = o + 24 | 0;
                o = r;
               } else {
                o = Qb + 628 + 8 | 0;
                break;
               }
               while (1) {
                o = o + 1 | 0;
                q = q + -8 | 0;
                n = d[o >> 0] << q | n;
                if ((s | 0) <= 8) {
                 o = Qb + 628 + 8 | 0;
                 break;
                } else s = s + -8 | 0;
               }
              } while (0);
              c[g >> 2] = t + v;
              c[o >> 2] = t + v & 7;
              if ((t + v | 0) >>> 0 > u >>> 0) break;
              c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((t + v | 0) >>> 3);
              if ((n >>> (33 - w | 0) | 0) == -1) break;
              if ((C | 0) == 5) if (va(Qb + 628 | 0, Qb + 688 | 0) | 0) break;
              n = c[x + 20 >> 2] | 0;
              t = 0;
              while (1) if (!(n >>> t)) break; else t = t + 1 | 0;
              u = t + -1 | 0;
              r = c[A >> 2] | 0;
              v = c[z >> 2] << 3;
              w = c[g >> 2] | 0;
              do if ((v - w | 0) > 31) {
               o = c[Qb + 628 + 8 >> 2] | 0;
               n = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
               if (!o) {
                o = Qb + 628 + 8 | 0;
                break;
               }
               n = (d[r + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
               o = Qb + 628 + 8 | 0;
              } else {
               if ((v - w | 0) <= 0) {
                n = 0;
                o = Qb + 628 + 8 | 0;
                break;
               }
               o = c[Qb + 628 + 8 >> 2] | 0;
               n = d[r >> 0] << o + 24;
               if ((v - w + -8 + o | 0) > 0) {
                s = v - w + -8 + o | 0;
                q = o + 24 | 0;
                o = r;
               } else {
                o = Qb + 628 + 8 | 0;
                break;
               }
               while (1) {
                o = o + 1 | 0;
                q = q + -8 | 0;
                n = d[o >> 0] << q | n;
                if ((s | 0) <= 8) {
                 o = Qb + 628 + 8 | 0;
                 break;
                } else s = s + -8 | 0;
               }
              } while (0);
              c[g >> 2] = u + w;
              c[o >> 2] = u + w & 7;
              n = n >>> (33 - t | 0);
              if ((u + w | 0) >>> 0 > v >>> 0) break;
              c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((u + w | 0) >>> 3);
              if ((n | 0) == -1) break;
              if ((c[e + 1316 >> 2] | 0) != (n | 0)) {
               c[e + 1316 >> 2] = n;
               j = 1;
              }
              if (!(c[y + 8 >> 2] | 0)) break f;
              c[Qb + 628 >> 2] = c[Qb >> 2];
              c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
              c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
              c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
              c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
              n = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
              do if (!n) {
               n = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
               if (n | 0) {
                k = n;
                break;
               }
               n = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
               if (n | 0) {
                k = n;
                break;
               }
               n = c[x + 12 >> 2] | 0;
               w = 0;
               while (1) if (!(n >>> w)) break; else w = w + 1 | 0;
               t = w + -1 | 0;
               r = c[A >> 2] | 0;
               u = c[z >> 2] << 3;
               v = c[g >> 2] | 0;
               do if ((u - v | 0) > 31) {
                o = c[Qb + 628 + 8 >> 2] | 0;
                n = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
                if (!o) {
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                n = (d[r + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
                o = Qb + 628 + 8 | 0;
               } else {
                if ((u - v | 0) <= 0) {
                 n = 0;
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                o = c[Qb + 628 + 8 >> 2] | 0;
                n = d[r >> 0] << o + 24;
                if ((u - v + -8 + o | 0) > 0) {
                 s = u - v + -8 + o | 0;
                 q = o + 24 | 0;
                 o = r;
                } else {
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                while (1) {
                 o = o + 1 | 0;
                 q = q + -8 | 0;
                 n = d[o >> 0] << q | n;
                 if ((s | 0) <= 8) {
                  o = Qb + 628 + 8 | 0;
                  break;
                 } else s = s + -8 | 0;
                }
               } while (0);
               c[g >> 2] = t + v;
               c[o >> 2] = t + v & 7;
               if ((t + v | 0) >>> 0 > u >>> 0) {
                k = 1;
                break;
               }
               c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((t + v | 0) >>> 3);
               if ((n >>> (33 - w | 0) | 0) == -1) {
                k = 1;
                break;
               }
               if ((C | 0) == 5) {
                n = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
                if (n | 0) {
                 k = n;
                 break;
                }
               }
               n = c[x + 20 >> 2] | 0;
               w = 0;
               while (1) if (!(n >>> w)) break; else w = w + 1 | 0;
               v = w + -1 | 0;
               s = c[A >> 2] | 0;
               t = c[z >> 2] << 3;
               u = c[g >> 2] | 0;
               do if ((t - u | 0) > 31) {
                o = c[Qb + 628 + 8 >> 2] | 0;
                n = d[s + 1 >> 0] << 16 | d[s >> 0] << 24 | d[s + 2 >> 0] << 8 | d[s + 3 >> 0];
                if (!o) {
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                n = (d[s + 4 >> 0] | 0) >>> (8 - o | 0) | n << o;
                o = Qb + 628 + 8 | 0;
               } else {
                if ((t - u | 0) <= 0) {
                 n = 0;
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                o = c[Qb + 628 + 8 >> 2] | 0;
                n = d[s >> 0] << o + 24;
                if ((t - u + -8 + o | 0) > 0) {
                 r = t - u + -8 + o | 0;
                 q = o + 24 | 0;
                 o = s;
                } else {
                 o = Qb + 628 + 8 | 0;
                 break;
                }
                while (1) {
                 o = o + 1 | 0;
                 q = q + -8 | 0;
                 n = d[o >> 0] << q | n;
                 if ((r | 0) <= 8) {
                  o = Qb + 628 + 8 | 0;
                  break;
                 } else r = r + -8 | 0;
                }
               } while (0);
               c[g >> 2] = v + u;
               c[o >> 2] = v + u & 7;
               if ((v + u | 0) >>> 0 > t >>> 0) {
                k = 1;
                break;
               }
               c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((v + u | 0) >>> 3);
               if ((n >>> (33 - w | 0) | 0) == -1) {
                k = 1;
                break;
               }
               c[Qb + 688 >> 2] = 0;
               n = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
               o = c[Qb + 688 >> 2] | 0;
               do if ((o | 0) == -1) if ((n | 0) == 0 ^ 1) k = -2147483648; else break d; else if (!n) {
                k = o & 1 | 0 ? (o + 1 | 0) >>> 1 : 0 - ((o + 1 | 0) >>> 1) | 0;
                break;
               } else break d; while (0);
               if ((c[e + 1320 >> 2] | 0) == (k | 0)) break f;
               c[e + 1320 >> 2] = k;
               j = 1;
               break f;
              } else k = n; while (0);
              Q = j;
              Pb = 203;
              break c;
             } while (0);
             break d;
            }
           case 1:
            {
             if (c[x + 24 >> 2] | 0) break f;
             w = c[y + 8 >> 2] | 0;
             c[Qb + 628 >> 2] = c[Qb >> 2];
             c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
             c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
             c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
             c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
             k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
             g : do if (!k) {
              k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
              if (k | 0) break;
              k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
              if (k | 0) break;
              k = c[x + 12 >> 2] | 0;
              v = 0;
              while (1) if (!(k >>> v)) break; else v = v + 1 | 0;
              u = v + -1 | 0;
              r = c[A >> 2] | 0;
              s = c[z >> 2] << 3;
              t = c[g >> 2] | 0;
              do if ((s - t | 0) > 31) {
               n = c[Qb + 628 + 8 >> 2] | 0;
               k = d[r + 1 >> 0] << 16 | d[r >> 0] << 24 | d[r + 2 >> 0] << 8 | d[r + 3 >> 0];
               if (!n) {
                n = Qb + 628 + 8 | 0;
                break;
               }
               k = (d[r + 4 >> 0] | 0) >>> (8 - n | 0) | k << n;
               n = Qb + 628 + 8 | 0;
              } else {
               if ((s - t | 0) <= 0) {
                k = 0;
                n = Qb + 628 + 8 | 0;
                break;
               }
               n = c[Qb + 628 + 8 >> 2] | 0;
               k = d[r >> 0] << n + 24;
               if ((s - t + -8 + n | 0) > 0) {
                q = s - t + -8 + n | 0;
                o = n + 24 | 0;
                n = r;
               } else {
                n = Qb + 628 + 8 | 0;
                break;
               }
               while (1) {
                n = n + 1 | 0;
                o = o + -8 | 0;
                k = d[n >> 0] << o | k;
                if ((q | 0) <= 8) {
                 n = Qb + 628 + 8 | 0;
                 break;
                } else q = q + -8 | 0;
               }
              } while (0);
              c[g >> 2] = u + t;
              c[n >> 2] = u + t & 7;
              if ((u + t | 0) >>> 0 > s >>> 0) {
               k = 1;
               break;
              }
              c[A >> 2] = (c[Qb + 628 >> 2] | 0) + ((u + t | 0) >>> 3);
              if ((k >>> (33 - v | 0) | 0) == -1) {
               k = 1;
               break;
              }
              if ((C | 0) == 5) {
               k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
               if (k | 0) break;
              }
              c[Qb + 688 >> 2] = 0;
              k = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
              n = c[Qb + 688 >> 2] | 0;
              if ((n | 0) == -1) if (!k) Pb = 186; else M = -2147483648; else if (!k) M = n & 1 | 0 ? (n + 1 | 0) >>> 1 : 0 - ((n + 1 | 0) >>> 1) | 0; else Pb = 186;
              if ((Pb | 0) == 186) {
               k = 1;
               break;
              }
              do if (!w) P = 0; else {
               c[Qb + 688 >> 2] = 0;
               k = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
               n = c[Qb + 688 >> 2] | 0;
               if ((n | 0) == -1) if (!k) Pb = 192; else {
                O = -2147483648;
                Pb = 191;
               } else if (!k) {
                O = n & 1 | 0 ? (n + 1 | 0) >>> 1 : 0 - ((n + 1 | 0) >>> 1) | 0;
                Pb = 191;
               } else Pb = 192;
               if ((Pb | 0) == 191) {
                P = O;
                break;
               } else if ((Pb | 0) == 192) {
                k = 1;
                break g;
               }
              } while (0);
              if ((c[e + 1324 >> 2] | 0) != (M | 0)) {
               c[e + 1324 >> 2] = M;
               j = 1;
              }
              if (!(c[y + 8 >> 2] | 0)) break f;
              if ((c[e + 1328 >> 2] | 0) == (P | 0)) break f;
              c[e + 1328 >> 2] = P;
              j = 1;
              break f;
             } while (0);
             Q = j;
             Pb = 203;
             break c;
            }
           default:
            {}
           } while (0);
           c[e + 1300 >> 2] = C;
           c[e + 1300 + 4 >> 2] = D;
           S = j;
           Pb = 201;
           break b;
          } else Pb = 82; while (0);
          break;
         }
        }
       }
       e = 4;
       l = Qb;
       return e | 0;
      }
     } else {
      R = n;
      Pb = 60;
     }
    } else {
     R = n;
     Pb = 60;
    }
   } else {
    R = n;
    Pb = 60;
   } while (0);
   if ((Pb | 0) == 60) {
    k = R;
    Q = B;
    Pb = 203;
   }
   h : do if ((Pb | 0) == 203) {
    if ((k | 0) < 65520) switch (k | 0) {
    case 0:
     {
      T = Q;
      break b;
     }
    default:
     break h;
    }
    switch (k | 0) {
    case 65520:
     {
      fa = 4;
      break;
     }
    default:
     break h;
    }
    l = Qb;
    return fa | 0;
   } while (0);
   e = 3;
   l = Qb;
   return e | 0;
  }
 default:
  {
   S = 0;
   Pb = 201;
  }
 } while (0);
 if ((Pb | 0) == 201) T = S;
 do if (!T) Pb = 217; else {
  if (c[e + 1184 >> 2] | 0) if (c[e + 16 >> 2] | 0) {
   if (c[e + 3380 >> 2] | 0) {
    e = 3;
    l = Qb;
    return e | 0;
   }
   if (!(c[e + 1188 >> 2] | 0)) {
    j = c[e + 1220 >> 2] | 0;
    k = j + ((c[e + 1248 >> 2] | 0) * 40 | 0) | 0;
    c[e + 1228 >> 2] = k;
    c[e + 1336 >> 2] = c[k >> 2];
    k = c[e + 1260 >> 2] | 0;
    if (k | 0) {
     c[c[e + 1224 >> 2] >> 2] = j;
     if ((k | 0) != 1) {
      j = 1;
      do {
       c[(c[e + 1224 >> 2] | 0) + (j << 2) >> 2] = (c[e + 1220 >> 2] | 0) + (j * 40 | 0);
       j = j + 1 | 0;
      } while ((j | 0) != (k | 0));
     }
    }
    Qa(e, e + 1336 | 0, 0);
    j = e + 1336 | 0;
   } else {
    Qa(e, e + 1336 | 0, c[e + 1372 >> 2] | 0);
    j = e + 1336 | 0;
   }
   c[i >> 2] = 0;
   c[e + 3344 >> 2] = 1;
   c[e + 1180 >> 2] = 0;
   cb = e + 1212 | 0;
   db = e + 16 | 0;
   fb = e + 1188 | 0;
   eb = j;
   break;
  }
  c[e + 1188 >> 2] = 0;
  c[e + 1180 >> 2] = 0;
  Pb = 217;
 } while (0);
 i : do if ((Pb | 0) == 217) switch (C & 31) {
 case 7:
  {
   j = Qb + 96 | 0;
   n = j + 92 | 0;
   do {
    c[j >> 2] = 0;
    j = j + 4 | 0;
   } while ((j | 0) < (n | 0));
   o = c[Qb + 4 >> 2] | 0;
   s = c[bb >> 2] << 3;
   t = c[Qb + 16 >> 2] | 0;
   if ((s - t | 0) > 31) {
    k = c[Ob >> 2] | 0;
    j = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
    if (k) j = (d[o + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
   } else if ((s - t | 0) > 0) {
    k = c[Ob >> 2] | 0;
    j = d[o >> 0] << k + 24;
    if ((s - t + -8 + k | 0) > 0) {
     q = s - t + -8 + k | 0;
     n = k + 24 | 0;
     k = o;
     while (1) {
      k = k + 1 | 0;
      n = n + -8 | 0;
      j = d[k >> 0] << n | j;
      if ((q | 0) <= 8) break; else q = q + -8 | 0;
     }
    }
   } else j = 0;
   c[Qb + 16 >> 2] = t + 8;
   c[Ob >> 2] = t + 8 & 7;
   j : do if (s >>> 0 >= (t + 8 | 0) >>> 0) {
    r = c[Qb >> 2] | 0;
    c[Qb + 4 >> 2] = r + ((t + 8 | 0) >>> 3);
    c[Qb + 96 >> 2] = j >>> 24;
    c[Qb + 16 >> 2] = t + 9;
    c[Ob >> 2] = t + 9 & 7;
    if (s >>> 0 >= (t + 9 | 0) >>> 0) c[Qb + 4 >> 2] = r + ((t + 9 | 0) >>> 3);
    c[Qb + 16 >> 2] = t + 10;
    c[Ob >> 2] = t + 10 & 7;
    if (s >>> 0 >= (t + 10 | 0) >>> 0) c[Qb + 4 >> 2] = r + ((t + 10 | 0) >>> 3);
    if ((s - (t + 10) + -1 | 0) >>> 0 < 31) {
     j = s - (t + 10) + -8 + (t + 10 & 7) | 0;
     if ((j | 0) > 0) while (1) if ((j | 0) > 8) j = j + -8 | 0; else break;
    }
    c[Qb + 16 >> 2] = t + 11;
    c[Ob >> 2] = t + 11 & 7;
    if (s >>> 0 >= (t + 11 | 0) >>> 0) {
     c[Qb + 4 >> 2] = r + ((t + 11 | 0) >>> 3);
     do if ((s - (t + 11) + -1 | 0) >>> 0 < 31) {
      j = s - (t + 11) + -8 + (t + 11 & 7) | 0;
      if ((j | 0) <= 0) break;
      while (1) if ((j | 0) > 8) j = j + -8 | 0; else break;
     } while (0);
     c[Qb + 16 >> 2] = t + 16;
     k = t + 16 & 7;
     c[Ob >> 2] = k;
     if (s >>> 0 >= (t + 16 | 0) >>> 0) {
      n = r + ((t + 16 | 0) >>> 3) | 0;
      c[Qb + 4 >> 2] = n;
      do if ((s - (t + 16) | 0) > 31) {
       j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
       if (!k) break;
       j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
      } else {
       if ((s - (t + 16) | 0) <= 0) {
        j = 0;
        break;
       }
       j = d[n >> 0] << (k | 24);
       if ((s - (t + 16) + -8 + k | 0) > 0) {
        q = s - (t + 16) + -8 + k | 0;
        o = k | 24;
        k = n;
       } else break;
       while (1) {
        k = k + 1 | 0;
        o = o + -8 | 0;
        j = d[k >> 0] << o | j;
        if ((q | 0) <= 8) break; else q = q + -8 | 0;
       }
      } while (0);
      c[Qb + 16 >> 2] = t + 24;
      c[Ob >> 2] = t + 24 & 7;
      if ((t + 24 | 0) >>> 0 > s >>> 0) break;
      c[Qb + 4 >> 2] = r + ((t + 24 | 0) >>> 3);
      c[Qb + 96 + 4 >> 2] = j >>> 24;
      Nb = (va(Qb, Qb + 96 + 8 | 0) | 0) != 0;
      if (Nb | (c[Qb + 96 + 8 >> 2] | 0) >>> 0 > 31) break;
      if (va(Qb, Qb + 648 | 0) | 0) break;
      j = c[Qb + 648 >> 2] | 0;
      if (j >>> 0 > 12) break;
      c[Qb + 96 + 12 >> 2] = 1 << j + 4;
      if (va(Qb, Qb + 648 | 0) | 0) break;
      j = c[Qb + 648 >> 2] | 0;
      if (j >>> 0 > 2) break;
      c[Qb + 96 + 16 >> 2] = j;
      k : do switch (j | 0) {
      case 0:
       {
        if (va(Qb, Qb + 648 | 0) | 0) break j;
        j = c[Qb + 648 >> 2] | 0;
        if (j >>> 0 > 12) break j;
        c[Qb + 96 + 20 >> 2] = 1 << j + 4;
        break;
       }
      case 1:
       {
        o = c[Qb + 4 >> 2] | 0;
        r = c[bb >> 2] << 3;
        s = c[Qb + 16 >> 2] | 0;
        do if ((r - s | 0) > 31) {
         k = c[Ob >> 2] | 0;
         j = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
         if (!k) break;
         j = (d[o + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
        } else {
         if ((r - s | 0) <= 0) {
          j = 0;
          break;
         }
         k = c[Ob >> 2] | 0;
         j = d[o >> 0] << k + 24;
         if ((r - s + -8 + k | 0) > 0) {
          q = r - s + -8 + k | 0;
          n = k + 24 | 0;
          k = o;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((q | 0) <= 8) break; else q = q + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = s + 1;
        c[Ob >> 2] = s + 1 & 7;
        if ((s + 1 | 0) >>> 0 > r >>> 0) break j;
        c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((s + 1 | 0) >>> 3);
        c[Qb + 96 + 24 >> 2] = j >>> 31;
        c[Qb + 688 >> 2] = 0;
        j = va(Qb, Qb + 688 | 0) | 0;
        k = c[Qb + 688 >> 2] | 0;
        if ((k | 0) == -1) if (!j) Pb = 263; else U = -2147483648; else if (!j) U = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else Pb = 263;
        if ((Pb | 0) == 263) break j;
        c[Qb + 96 + 28 >> 2] = U;
        c[Qb + 688 >> 2] = 0;
        j = va(Qb, Qb + 688 | 0) | 0;
        k = c[Qb + 688 >> 2] | 0;
        if ((k | 0) == -1) if (!j) Pb = 267; else V = -2147483648; else if (!j) V = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else Pb = 267;
        if ((Pb | 0) == 267) break j;
        c[Qb + 96 + 32 >> 2] = V;
        q = Qb + 96 + 36 | 0;
        if (va(Qb, q) | 0) break j;
        j = c[q >> 2] | 0;
        if (j >>> 0 > 255) break j;
        if (!j) {
         c[Qb + 96 + 40 >> 2] = 0;
         break k;
        }
        j = _a(j << 2) | 0;
        c[Qb + 96 + 40 >> 2] = j;
        if (!j) break j;
        if (!(c[q >> 2] | 0)) break k;
        c[Qb + 688 >> 2] = 0;
        k = va(Qb, Qb + 688 | 0) | 0;
        n = c[Qb + 688 >> 2] | 0;
        if ((n | 0) == -1) if (!k) Pb = 278; else W = -2147483648; else if (!k) W = n & 1 | 0 ? (n + 1 | 0) >>> 1 : 0 - ((n + 1 | 0) >>> 1) | 0; else Pb = 278;
        if ((Pb | 0) == 278) break j;
        c[j >> 2] = W;
        if ((c[q >> 2] | 0) >>> 0 <= 1) break k;
        o = 1;
        while (1) {
         n = (c[Qb + 96 + 40 >> 2] | 0) + (o << 2) | 0;
         c[Qb + 688 >> 2] = 0;
         j = va(Qb, Qb + 688 | 0) | 0;
         k = c[Qb + 688 >> 2] | 0;
         if ((k | 0) == -1) if (!j) break; else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else break;
         c[n >> 2] = j;
         o = o + 1 | 0;
         if (o >>> 0 >= (c[q >> 2] | 0) >>> 0) break k;
        }
        break j;
       }
      default:
       {}
      } while (0);
      w = Qb + 96 + 44 | 0;
      Pb = (va(Qb, w) | 0) != 0;
      if (Pb | (c[w >> 2] | 0) >>> 0 > 16) break;
      o = c[Qb + 4 >> 2] | 0;
      r = c[bb >> 2] << 3;
      s = c[Qb + 16 >> 2] | 0;
      do if ((r - s | 0) > 31) {
       k = c[Ob >> 2] | 0;
       j = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
       if (!k) break;
       j = (d[o + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
      } else {
       if ((r - s | 0) <= 0) {
        j = 0;
        break;
       }
       k = c[Ob >> 2] | 0;
       j = d[o >> 0] << k + 24;
       if ((r - s + -8 + k | 0) > 0) {
        q = r - s + -8 + k | 0;
        n = k + 24 | 0;
        k = o;
       } else break;
       while (1) {
        k = k + 1 | 0;
        n = n + -8 | 0;
        j = d[k >> 0] << n | j;
        if ((q | 0) <= 8) break; else q = q + -8 | 0;
       }
      } while (0);
      c[Qb + 16 >> 2] = s + 1;
      c[Ob >> 2] = s + 1 & 7;
      if ((s + 1 | 0) >>> 0 > r >>> 0) break;
      c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((s + 1 | 0) >>> 3);
      c[Qb + 96 + 48 >> 2] = j >>> 31;
      if (va(Qb, Qb + 648 | 0) | 0) break;
      c[Qb + 96 + 52 >> 2] = (c[Qb + 648 >> 2] | 0) + 1;
      if (va(Qb, Qb + 648 | 0) | 0) break;
      j = (c[Qb + 648 >> 2] | 0) + 1 | 0;
      c[Qb + 96 + 56 >> 2] = j;
      q = c[Qb + 4 >> 2] | 0;
      t = c[bb >> 2] << 3;
      u = c[Qb + 16 >> 2] | 0;
      do if ((t - u | 0) > 31) {
       n = c[Ob >> 2] | 0;
       k = d[q + 1 >> 0] << 16 | d[q >> 0] << 24 | d[q + 2 >> 0] << 8 | d[q + 3 >> 0];
       if (!n) break;
       k = (d[q + 4 >> 0] | 0) >>> (8 - n | 0) | k << n;
      } else {
       if ((t - u | 0) <= 0) {
        k = 0;
        break;
       }
       n = c[Ob >> 2] | 0;
       k = d[q >> 0] << n + 24;
       if ((t - u + -8 + n | 0) > 0) {
        r = t - u + -8 + n | 0;
        o = n + 24 | 0;
        n = q;
       } else break;
       while (1) {
        n = n + 1 | 0;
        o = o + -8 | 0;
        k = d[n >> 0] << o | k;
        if ((r | 0) <= 8) break; else r = r + -8 | 0;
       }
      } while (0);
      c[Qb + 16 >> 2] = u + 1;
      c[Ob >> 2] = u + 1 & 7;
      if (t >>> 0 < (u + 1 | 0) >>> 0) break;
      s = c[Qb >> 2] | 0;
      c[Qb + 4 >> 2] = s + ((u + 1 | 0) >>> 3);
      if ((k | 0) > -1) break;
      do if ((t - (u + 1) + -1 | 0) >>> 0 < 31) {
       k = t - (u + 1) + -8 + (u + 1 & 7) | 0;
       if ((k | 0) <= 0) break;
       while (1) if ((k | 0) > 8) k = k + -8 | 0; else break;
      } while (0);
      c[Qb + 16 >> 2] = u + 2;
      n = u + 2 & 7;
      c[Ob >> 2] = n;
      if (t >>> 0 < (u + 2 | 0) >>> 0) break;
      o = s + ((u + 2 | 0) >>> 3) | 0;
      c[Qb + 4 >> 2] = o;
      do if ((t - (u + 2) | 0) > 31) {
       k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
       if (!n) break;
       k = (d[o + 4 >> 0] | 0) >>> (8 - n | 0) | k << n;
      } else {
       if ((t - (u + 2) | 0) <= 0) {
        k = 0;
        break;
       }
       k = d[o >> 0] << (n | 24);
       if ((t - (u + 2) + -8 + n | 0) > 0) {
        r = t - (u + 2) + -8 + n | 0;
        q = n | 24;
        n = o;
       } else break;
       while (1) {
        n = n + 1 | 0;
        q = q + -8 | 0;
        k = d[n >> 0] << q | k;
        if ((r | 0) <= 8) break; else r = r + -8 | 0;
       }
      } while (0);
      c[Qb + 16 >> 2] = u + 3;
      c[Ob >> 2] = u + 3 & 7;
      if ((u + 3 | 0) >>> 0 > t >>> 0) break;
      c[Qb + 4 >> 2] = s + ((u + 3 | 0) >>> 3);
      c[Qb + 96 + 60 >> 2] = k >>> 31;
      if ((k | 0) < 0) {
       if (va(Qb, Qb + 96 + 64 | 0) | 0) break;
       if (va(Qb, Qb + 96 + 68 | 0) | 0) break;
       if (va(Qb, Qb + 96 + 72 | 0) | 0) break;
       if (va(Qb, Qb + 96 + 76 | 0) | 0) break;
       k = c[Qb + 96 + 52 >> 2] | 0;
       if ((c[Qb + 96 + 64 >> 2] | 0) > ((k << 3) + ~c[Qb + 96 + 68 >> 2] | 0)) break;
       j = c[Qb + 96 + 56 >> 2] | 0;
       if ((c[Qb + 96 + 72 >> 2] | 0) > ((j << 3) + ~c[Qb + 96 + 76 >> 2] | 0)) break;
      } else k = c[Qb + 96 + 52 >> 2] | 0;
      j = N(k, j) | 0;
      do switch (c[Qb + 96 + 4 >> 2] | 0) {
      case 10:
       {
        $ = 99;
        aa = 152064;
        Pb = 337;
        break;
       }
      case 11:
       {
        $ = 396;
        aa = 345600;
        Pb = 337;
        break;
       }
      case 12:
       {
        $ = 396;
        aa = 912384;
        Pb = 337;
        break;
       }
      case 13:
       {
        $ = 396;
        aa = 912384;
        Pb = 337;
        break;
       }
      case 20:
       {
        $ = 396;
        aa = 912384;
        Pb = 337;
        break;
       }
      case 21:
       {
        $ = 792;
        aa = 1824768;
        Pb = 337;
        break;
       }
      case 22:
       {
        $ = 1620;
        aa = 3110400;
        Pb = 337;
        break;
       }
      case 30:
       {
        $ = 1620;
        aa = 3110400;
        Pb = 337;
        break;
       }
      case 31:
       {
        $ = 3600;
        aa = 6912e3;
        Pb = 337;
        break;
       }
      case 32:
       {
        $ = 5120;
        aa = 7864320;
        Pb = 337;
        break;
       }
      case 40:
       {
        $ = 8192;
        aa = 12582912;
        Pb = 337;
        break;
       }
      case 41:
       {
        $ = 8192;
        aa = 12582912;
        Pb = 337;
        break;
       }
      case 42:
       {
        $ = 8704;
        aa = 13369344;
        Pb = 337;
        break;
       }
      case 50:
       {
        $ = 22080;
        aa = 42393600;
        Pb = 337;
        break;
       }
      case 51:
       {
        $ = 36864;
        aa = 70778880;
        Pb = 337;
        break;
       }
      default:
       Pb = 339;
      } while (0);
      do if ((Pb | 0) == 337) {
       if ($ >>> 0 < j >>> 0) {
        Pb = 339;
        break;
       }
       j = (aa >>> 0) / ((j * 384 | 0) >>> 0) | 0;
       j = j >>> 0 < 16 ? j : 16;
       c[Qb + 648 >> 2] = j;
       k = c[w >> 2] | 0;
       if (k >>> 0 > j >>> 0) {
        ba = k;
        Pb = 340;
       } else ca = j;
      } while (0);
      if ((Pb | 0) == 339) {
       c[Qb + 648 >> 2] = 2147483647;
       ba = c[w >> 2] | 0;
       Pb = 340;
      }
      if ((Pb | 0) == 340) {
       c[Qb + 648 >> 2] = ba;
       ca = ba;
      }
      c[Qb + 96 + 88 >> 2] = ca;
      o = c[Qb + 4 >> 2] | 0;
      r = c[bb >> 2] << 3;
      s = c[Qb + 16 >> 2] | 0;
      do if ((r - s | 0) > 31) {
       k = c[Ob >> 2] | 0;
       j = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
       if (!k) break;
       j = (d[o + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
      } else {
       if ((r - s | 0) <= 0) {
        j = 0;
        break;
       }
       k = c[Ob >> 2] | 0;
       j = d[o >> 0] << k + 24;
       if ((r - s + -8 + k | 0) > 0) {
        q = r - s + -8 + k | 0;
        n = k + 24 | 0;
        k = o;
       } else break;
       while (1) {
        k = k + 1 | 0;
        n = n + -8 | 0;
        j = d[k >> 0] << n | j;
        if ((q | 0) <= 8) break; else q = q + -8 | 0;
       }
      } while (0);
      c[Qb + 16 >> 2] = s + 1;
      c[Ob >> 2] = s + 1 & 7;
      if ((s + 1 | 0) >>> 0 > r >>> 0) break;
      c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((s + 1 | 0) >>> 3);
      c[Qb + 96 + 80 >> 2] = j >>> 31;
      do if ((j | 0) < 0) {
       v = _a(952) | 0;
       c[Qb + 96 + 84 >> 2] = v;
       if (!v) break j;
       pb(v | 0, 0, 952) | 0;
       o = c[Qb + 4 >> 2] | 0;
       u = c[bb >> 2] | 0;
       s = c[Qb + 16 >> 2] | 0;
       do if (((u << 3) - s | 0) > 31) {
        j = c[Ob >> 2] | 0;
        k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
        if (!j) break;
        k = (d[o + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
       } else {
        if (((u << 3) - s | 0) <= 0) {
         k = 0;
         break;
        }
        j = c[Ob >> 2] | 0;
        k = d[o >> 0] << j + 24;
        if (((u << 3) - s + -8 + j | 0) > 0) {
         q = (u << 3) - s + -8 + j | 0;
         n = j + 24 | 0;
         j = o;
        } else break;
        while (1) {
         j = j + 1 | 0;
         n = n + -8 | 0;
         k = d[j >> 0] << n | k;
         if ((q | 0) <= 8) break; else q = q + -8 | 0;
        }
       } while (0);
       c[Qb + 16 >> 2] = s + 1;
       o = s + 1 & 7;
       c[Ob >> 2] = o;
       if (u << 3 >>> 0 < (s + 1 | 0) >>> 0) break j;
       t = c[Qb >> 2] | 0;
       n = t + ((s + 1 | 0) >>> 3) | 0;
       c[Qb + 4 >> 2] = n;
       c[v >> 2] = k >>> 31;
       do if ((k | 0) < 0) {
        do if (((u << 3) - (s + 1) | 0) > 31) {
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!o) break;
         j = (d[n + 4 >> 0] | 0) >>> (8 - o | 0) | j << o;
        } else {
         if (((u << 3) - (s + 1) | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[n >> 0] << (o | 24);
         if (((u << 3) - (s + 1) + -8 + o | 0) > 0) {
          q = (u << 3) - (s + 1) + -8 + o | 0;
          o = o | 24;
          k = n;
         } else break;
         while (1) {
          k = k + 1 | 0;
          o = o + -8 | 0;
          j = d[k >> 0] << o | j;
          if ((q | 0) <= 8) break; else q = q + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = s + 9;
        o = s + 9 & 7;
        c[Ob >> 2] = o;
        if (u << 3 >>> 0 < (s + 9 | 0) >>> 0) break j;
        Nb = j >>> 24;
        k = t + ((s + 9 | 0) >>> 3) | 0;
        c[Qb + 4 >> 2] = k;
        c[v + 4 >> 2] = Nb;
        if ((Nb | 0) != 255) {
         r = s + 9 | 0;
         n = k;
         break;
        }
        do if (((u << 3) - (s + 9) | 0) > 31) {
         j = d[k + 1 >> 0] << 16 | d[k >> 0] << 24 | d[k + 2 >> 0] << 8 | d[k + 3 >> 0];
         if (!o) break;
         j = (d[k + 4 >> 0] | 0) >>> (8 - o | 0) | j << o;
        } else {
         if (((u << 3) - (s + 9) | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[k >> 0] << (o | 24);
         if (((u << 3) - (s + 9) + -8 + o | 0) > 0) {
          q = (u << 3) - (s + 9) + -8 + o | 0;
          n = o | 24;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((q | 0) <= 8) break; else q = q + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = s + 25;
        n = s + 25 & 7;
        c[Ob >> 2] = n;
        if (u << 3 >>> 0 < (s + 25 | 0) >>> 0) break j;
        k = t + ((s + 25 | 0) >>> 3) | 0;
        c[Qb + 4 >> 2] = k;
        c[v + 8 >> 2] = j >>> 16;
        do if (((u << 3) - (s + 25) | 0) > 31) {
         j = d[k + 1 >> 0] << 16 | d[k >> 0] << 24 | d[k + 2 >> 0] << 8 | d[k + 3 >> 0];
         if (!n) break;
         j = (d[k + 4 >> 0] | 0) >>> (8 - n | 0) | j << n;
        } else {
         if (((u << 3) - (s + 25) | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[k >> 0] << (n | 24);
         if (((u << 3) - (s + 25) + -8 + n | 0) > 0) {
          o = (u << 3) - (s + 25) + -8 + n | 0;
          n = n | 24;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((o | 0) <= 8) break; else o = o + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = s + 41;
        c[Ob >> 2] = s + 41 & 7;
        if ((s + 41 | 0) >>> 0 > u << 3 >>> 0) break j;
        c[Qb + 4 >> 2] = t + ((s + 41 | 0) >>> 3);
        c[v + 12 >> 2] = j >>> 16;
        r = s + 41 | 0;
        n = t + ((s + 41 | 0) >>> 3) | 0;
        o = s + 41 & 7;
       } else r = s + 1 | 0; while (0);
       k = (u << 3) - r | 0;
       do if ((k | 0) > 31) {
        j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
        if (!o) break;
        j = (d[n + 4 >> 0] | 0) >>> (8 - o | 0) | j << o;
       } else {
        if ((k | 0) <= 0) {
         j = 0;
         break;
        }
        q = o | 24;
        j = d[n >> 0] << q;
        k = k + -8 + o | 0;
        if ((k | 0) > 0) o = q; else break;
        while (1) {
         n = n + 1 | 0;
         o = o + -8 | 0;
         j = d[n >> 0] << o | j;
         if ((k | 0) <= 8) break; else k = k + -8 | 0;
        }
       } while (0);
       k = r + 1 | 0;
       c[Qb + 16 >> 2] = k;
       c[Ob >> 2] = k & 7;
       if (u << 3 >>> 0 < k >>> 0) break j;
       c[Qb + 4 >> 2] = t + (k >>> 3);
       c[v + 16 >> 2] = j >>> 31;
       if ((j | 0) < 0) {
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          n = (u << 3) - k + -8 + (k & 7) | 0;
          o = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          o = o + -8 | 0;
          j = d[k >> 0] << o | j;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        k = r + 2 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (k >>> 0 > u << 3 >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 20 >> 2] = j >>> 31;
        r = k;
        n = t + (k >>> 3) | 0;
        o = k & 7;
       } else {
        r = k;
        n = t + (k >>> 3) | 0;
        o = k & 7;
       }
       k = (u << 3) - r | 0;
       do if ((k | 0) > 31) {
        j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
        if (!o) break;
        j = (d[n + 4 >> 0] | 0) >>> (8 - o | 0) | j << o;
       } else {
        if ((k | 0) <= 0) {
         j = 0;
         break;
        }
        q = o | 24;
        j = d[n >> 0] << q;
        k = k + -8 + o | 0;
        if ((k | 0) > 0) o = q; else break;
        while (1) {
         n = n + 1 | 0;
         o = o + -8 | 0;
         j = d[n >> 0] << o | j;
         if ((k | 0) <= 8) break; else k = k + -8 | 0;
        }
       } while (0);
       k = r + 1 | 0;
       c[Qb + 16 >> 2] = k;
       c[Ob >> 2] = k & 7;
       if (u << 3 >>> 0 < k >>> 0) break j;
       c[Qb + 4 >> 2] = t + (k >>> 3);
       c[v + 24 >> 2] = j >>> 31;
       do if ((j | 0) < 0) {
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          n = (u << 3) - k + -8 + (k & 7) | 0;
          o = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          o = o + -8 | 0;
          j = d[k >> 0] << o | j;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        k = r + 4 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (u << 3 >>> 0 < k >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 28 >> 2] = j >>> 29;
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          n = (u << 3) - k + -8 + (k & 7) | 0;
          o = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          o = o + -8 | 0;
          j = d[k >> 0] << o | j;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        k = r + 5 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (u << 3 >>> 0 < k >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 32 >> 2] = j >>> 31;
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          n = (u << 3) - k + -8 + (k & 7) | 0;
          o = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          o = o + -8 | 0;
          j = d[k >> 0] << o | j;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        k = r + 6 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (u << 3 >>> 0 < k >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 36 >> 2] = j >>> 31;
        if ((j | 0) >= 0) {
         la = k & 7;
         ma = k;
         na = t + (k >>> 3) | 0;
         Pb = 450;
         break;
        }
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          m = (u << 3) - k + -8 + (k & 7) | 0;
          n = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((m | 0) <= 8) break; else m = m + -8 | 0;
         }
        } while (0);
        k = r + 14 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (u << 3 >>> 0 < k >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 40 >> 2] = j >>> 24;
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          m = (u << 3) - k + -8 + (k & 7) | 0;
          n = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((m | 0) <= 8) break; else m = m + -8 | 0;
         }
        } while (0);
        k = r + 22 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (u << 3 >>> 0 < k >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        c[v + 44 >> 2] = j >>> 24;
        do if (((u << 3) - k | 0) > 31) {
         j = d[t + (k >>> 3) + 1 >> 0] << 16 | d[t + (k >>> 3) >> 0] << 24 | d[t + (k >>> 3) + 2 >> 0] << 8 | d[t + (k >>> 3) + 3 >> 0];
         if (!(k & 7)) break;
         j = (d[t + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
        } else {
         if (((u << 3) - k | 0) <= 0) {
          j = 0;
          break;
         }
         j = d[t + (k >>> 3) >> 0] << (k & 7 | 24);
         if (((u << 3) - k + -8 + (k & 7) | 0) > 0) {
          m = (u << 3) - k + -8 + (k & 7) | 0;
          n = k & 7 | 24;
          k = t + (k >>> 3) | 0;
         } else break;
         while (1) {
          k = k + 1 | 0;
          n = n + -8 | 0;
          j = d[k >> 0] << n | j;
          if ((m | 0) <= 8) break; else m = m + -8 | 0;
         }
        } while (0);
        k = r + 30 | 0;
        c[Qb + 16 >> 2] = k;
        c[Ob >> 2] = k & 7;
        if (k >>> 0 > u << 3 >>> 0) break j;
        c[Qb + 4 >> 2] = t + (k >>> 3);
        ia = j >>> 24;
        ka = k;
        m = t + (k >>> 3) | 0;
        ja = k & 7;
       } else {
        c[v + 28 >> 2] = 5;
        la = k & 7;
        ma = k;
        na = t + (k >>> 3) | 0;
        Pb = 450;
       } while (0);
       if ((Pb | 0) == 450) {
        c[v + 40 >> 2] = 2;
        c[v + 44 >> 2] = 2;
        ia = 2;
        ka = ma;
        m = na;
        ja = la;
       }
       c[v + 48 >> 2] = ia;
       k = (u << 3) - ka | 0;
       do if ((k | 0) > 31) {
        j = d[m + 1 >> 0] << 16 | d[m >> 0] << 24 | d[m + 2 >> 0] << 8 | d[m + 3 >> 0];
        if (!ja) break;
        j = (d[m + 4 >> 0] | 0) >>> (8 - ja | 0) | j << ja;
       } else {
        if ((k | 0) <= 0) {
         j = 0;
         break;
        }
        n = ja + 24 | 0;
        j = d[m >> 0] << n;
        k = k + -8 + ja | 0;
        if ((k | 0) <= 0) break;
        while (1) {
         m = m + 1 | 0;
         n = n + -8 | 0;
         j = d[m >> 0] << n | j;
         if ((k | 0) <= 8) break; else k = k + -8 | 0;
        }
       } while (0);
       k = ka + 1 | 0;
       c[Qb + 16 >> 2] = k;
       c[Ob >> 2] = k & 7;
       if (k >>> 0 > u << 3 >>> 0) break j;
       c[Qb + 4 >> 2] = t + (k >>> 3);
       c[v + 52 >> 2] = j >>> 31;
       if ((j | 0) < 0) {
        if (va(Qb, v + 56 | 0) | 0) break j;
        if ((c[v + 56 >> 2] | 0) >>> 0 > 5) break j;
        if (va(Qb, v + 60 | 0) | 0) break j;
        if ((c[v + 60 >> 2] | 0) >>> 0 > 5) break j;
        j = c[bb >> 2] | 0;
        r = c[Qb + 16 >> 2] | 0;
        q = c[Qb + 4 >> 2] | 0;
       } else {
        j = u;
        r = k;
        q = t + (k >>> 3) | 0;
       }
       t = j << 3;
       m = t - r | 0;
       do if ((m | 0) > 31) {
        m = c[Ob >> 2] | 0;
        k = d[q + 1 >> 0] << 16 | d[q >> 0] << 24 | d[q + 2 >> 0] << 8 | d[q + 3 >> 0];
        if (!m) break;
        k = (d[q + 4 >> 0] | 0) >>> (8 - m | 0) | k << m;
       } else {
        if ((m | 0) <= 0) {
         k = 0;
         break;
        }
        n = c[Ob >> 2] | 0;
        k = d[q >> 0] << n + 24;
        if ((m + -8 + n | 0) > 0) {
         o = m + -8 + n | 0;
         n = n + 24 | 0;
         m = q;
        } else break;
        while (1) {
         m = m + 1 | 0;
         n = n + -8 | 0;
         k = d[m >> 0] << n | k;
         if ((o | 0) <= 8) break; else o = o + -8 | 0;
        }
       } while (0);
       m = r + 1 | 0;
       c[Qb + 16 >> 2] = m;
       c[Ob >> 2] = m & 7;
       if (t >>> 0 < m >>> 0) break j;
       s = c[Qb >> 2] | 0;
       c[Qb + 4 >> 2] = s + (m >>> 3);
       c[v + 64 >> 2] = k >>> 31;
       if ((k | 0) < 0) {
        do if ((t - m | 0) > 31) {
         k = d[s + (m >>> 3) + 1 >> 0] << 16 | d[s + (m >>> 3) >> 0] << 24 | d[s + (m >>> 3) + 2 >> 0] << 8 | d[s + (m >>> 3) + 3 >> 0];
         if (!(m & 7)) break;
         k = (d[s + (m >>> 3) + 4 >> 0] | 0) >>> (8 - (m & 7) | 0) | k << (m & 7);
        } else {
         if ((t - m | 0) <= 0) {
          k = 0;
          break;
         }
         k = d[s + (m >>> 3) >> 0] << (m & 7 | 24);
         if ((t - m + -8 + (m & 7) | 0) > 0) {
          n = t - m + -8 + (m & 7) | 0;
          o = m & 7 | 24;
          m = s + (m >>> 3) | 0;
         } else break;
         while (1) {
          m = m + 1 | 0;
          o = o + -8 | 0;
          k = d[m >> 0] << o | k;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        m = r + 33 | 0;
        c[Qb + 16 >> 2] = m;
        c[Ob >> 2] = m & 7;
        if (t >>> 0 < m >>> 0) break j;
        c[Qb + 4 >> 2] = s + (m >>> 3);
        if (!k) break j;
        c[v + 68 >> 2] = k;
        do if ((t - m | 0) > 31) {
         k = d[s + (m >>> 3) + 1 >> 0] << 16 | d[s + (m >>> 3) >> 0] << 24 | d[s + (m >>> 3) + 2 >> 0] << 8 | d[s + (m >>> 3) + 3 >> 0];
         if (!(m & 7)) break;
         k = (d[s + (m >>> 3) + 4 >> 0] | 0) >>> (8 - (m & 7) | 0) | k << (m & 7);
        } else {
         if ((t - m | 0) <= 0) {
          k = 0;
          break;
         }
         k = d[s + (m >>> 3) >> 0] << (m & 7 | 24);
         if ((t - m + -8 + (m & 7) | 0) > 0) {
          n = t - m + -8 + (m & 7) | 0;
          o = m & 7 | 24;
          m = s + (m >>> 3) | 0;
         } else break;
         while (1) {
          m = m + 1 | 0;
          o = o + -8 | 0;
          k = d[m >> 0] << o | k;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        m = r + 65 | 0;
        c[Qb + 16 >> 2] = m;
        c[Ob >> 2] = m & 7;
        if (t >>> 0 < m >>> 0) break j;
        c[Qb + 4 >> 2] = s + (m >>> 3);
        if (!k) break j;
        c[v + 72 >> 2] = k;
        do if ((t - m | 0) > 31) {
         k = d[s + (m >>> 3) + 1 >> 0] << 16 | d[s + (m >>> 3) >> 0] << 24 | d[s + (m >>> 3) + 2 >> 0] << 8 | d[s + (m >>> 3) + 3 >> 0];
         if (!(m & 7)) break;
         k = (d[s + (m >>> 3) + 4 >> 0] | 0) >>> (8 - (m & 7) | 0) | k << (m & 7);
        } else {
         if ((t - m | 0) <= 0) {
          k = 0;
          break;
         }
         k = d[s + (m >>> 3) >> 0] << (m & 7 | 24);
         if ((t - m + -8 + (m & 7) | 0) > 0) {
          n = t - m + -8 + (m & 7) | 0;
          o = m & 7 | 24;
          m = s + (m >>> 3) | 0;
         } else break;
         while (1) {
          m = m + 1 | 0;
          o = o + -8 | 0;
          k = d[m >> 0] << o | k;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        m = r + 66 | 0;
        c[Qb + 16 >> 2] = m;
        c[Ob >> 2] = m & 7;
        if (m >>> 0 > t >>> 0) break j;
        c[Qb + 4 >> 2] = s + (m >>> 3);
        c[v + 76 >> 2] = k >>> 31;
        r = m;
        n = s + (m >>> 3) | 0;
        o = m & 7;
       } else {
        r = m;
        n = s + (m >>> 3) | 0;
        o = m & 7;
       }
       m = t - r | 0;
       do if ((m | 0) > 31) {
        k = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
        if (!o) break;
        k = (d[n + 4 >> 0] | 0) >>> (8 - o | 0) | k << o;
       } else {
        if ((m | 0) <= 0) {
         k = 0;
         break;
        }
        q = o | 24;
        k = d[n >> 0] << q;
        m = m + -8 + o | 0;
        if ((m | 0) > 0) o = q; else break;
        while (1) {
         n = n + 1 | 0;
         o = o + -8 | 0;
         k = d[n >> 0] << o | k;
         if ((m | 0) <= 8) break; else m = m + -8 | 0;
        }
       } while (0);
       m = r + 1 | 0;
       c[Qb + 16 >> 2] = m;
       c[Ob >> 2] = m & 7;
       if (m >>> 0 > t >>> 0) break j;
       c[Qb + 4 >> 2] = s + (m >>> 3);
       c[v + 80 >> 2] = k >>> 31;
       if ((k | 0) < 0) {
        if (Sa(Qb, v + 84 | 0) | 0) break j;
        j = c[bb >> 2] | 0;
        r = c[Qb + 16 >> 2] | 0;
        o = c[Qb + 4 >> 2] | 0;
       } else {
        c[v + 84 >> 2] = 1;
        c[v + 96 >> 2] = 288000001;
        c[v + 224 >> 2] = 288000001;
        c[v + 480 >> 2] = 24;
        c[v + 484 >> 2] = 24;
        c[v + 488 >> 2] = 24;
        c[v + 492 >> 2] = 24;
        r = m;
        o = s + (m >>> 3) | 0;
       }
       q = j << 3;
       j = q - r | 0;
       do if ((j | 0) > 31) {
        j = c[Ob >> 2] | 0;
        k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
        if (!j) break;
        k = (d[o + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
       } else {
        if ((j | 0) <= 0) {
         k = 0;
         break;
        }
        m = c[Ob >> 2] | 0;
        k = d[o >> 0] << m + 24;
        if ((j + -8 + m | 0) > 0) {
         n = j + -8 + m | 0;
         m = m + 24 | 0;
         j = o;
        } else break;
        while (1) {
         j = j + 1 | 0;
         m = m + -8 | 0;
         k = d[j >> 0] << m | k;
         if ((n | 0) <= 8) break; else n = n + -8 | 0;
        }
       } while (0);
       j = r + 1 | 0;
       c[Qb + 16 >> 2] = j;
       c[Ob >> 2] = j & 7;
       if (j >>> 0 > q >>> 0) break j;
       c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + (j >>> 3);
       c[v + 496 >> 2] = k >>> 31;
       if ((k | 0) < 0) {
        if (Sa(Qb, v + 500 | 0) | 0) break j;
       } else {
        c[v + 500 >> 2] = 1;
        c[v + 512 >> 2] = 240000001;
        c[v + 640 >> 2] = 240000001;
        c[v + 896 >> 2] = 24;
        c[v + 900 >> 2] = 24;
        c[v + 904 >> 2] = 24;
        c[v + 908 >> 2] = 24;
       }
       do if (!(c[v + 80 >> 2] | 0)) {
        if (c[v + 496 >> 2] | 0) {
         Pb = 520;
         break;
        }
        p = c[bb >> 2] | 0;
        ra = c[Qb + 16 >> 2] | 0;
        oa = c[Qb + 4 >> 2] | 0;
       } else Pb = 520; while (0);
       if ((Pb | 0) == 520) {
        n = c[Qb + 4 >> 2] | 0;
        p = c[bb >> 2] | 0;
        q = c[Qb + 16 >> 2] | 0;
        do if (((p << 3) - q | 0) > 31) {
         k = c[Ob >> 2] | 0;
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!k) break;
         j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
        } else {
         if (((p << 3) - q | 0) <= 0) {
          j = 0;
          break;
         }
         k = c[Ob >> 2] | 0;
         j = d[n >> 0] << k + 24;
         if (((p << 3) - q + -8 + k | 0) > 0) {
          o = (p << 3) - q + -8 + k | 0;
          m = k + 24 | 0;
          k = n;
         } else break;
         while (1) {
          k = k + 1 | 0;
          m = m + -8 | 0;
          j = d[k >> 0] << m | j;
          if ((o | 0) <= 8) break; else o = o + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = q + 1;
        c[Ob >> 2] = q + 1 & 7;
        if ((q + 1 | 0) >>> 0 > p << 3 >>> 0) break j;
        oa = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3) | 0;
        c[Qb + 4 >> 2] = oa;
        c[v + 912 >> 2] = j >>> 31;
        ra = q + 1 | 0;
       }
       q = p << 3;
       k = q - ra | 0;
       do if ((k | 0) > 31) {
        k = c[Ob >> 2] | 0;
        j = d[oa + 1 >> 0] << 16 | d[oa >> 0] << 24 | d[oa + 2 >> 0] << 8 | d[oa + 3 >> 0];
        if (!k) break;
        j = (d[oa + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
       } else {
        if ((k | 0) <= 0) {
         j = 0;
         break;
        }
        m = c[Ob >> 2] | 0;
        j = d[oa >> 0] << m + 24;
        if ((k + -8 + m | 0) > 0) {
         n = k + -8 + m | 0;
         m = m + 24 | 0;
         k = oa;
        } else break;
        while (1) {
         k = k + 1 | 0;
         m = m + -8 | 0;
         j = d[k >> 0] << m | j;
         if ((n | 0) <= 8) break; else n = n + -8 | 0;
        }
       } while (0);
       k = ra + 1 | 0;
       c[Qb + 16 >> 2] = k;
       c[Ob >> 2] = k & 7;
       if (q >>> 0 < k >>> 0) break j;
       p = c[Qb >> 2] | 0;
       c[Qb + 4 >> 2] = p + (k >>> 3);
       c[v + 916 >> 2] = j >>> 31;
       do if ((q - k | 0) > 31) {
        j = d[p + (k >>> 3) + 1 >> 0] << 16 | d[p + (k >>> 3) >> 0] << 24 | d[p + (k >>> 3) + 2 >> 0] << 8 | d[p + (k >>> 3) + 3 >> 0];
        if (!(k & 7)) break;
        j = (d[p + (k >>> 3) + 4 >> 0] | 0) >>> (8 - (k & 7) | 0) | j << (k & 7);
       } else {
        if ((q - k | 0) <= 0) {
         j = 0;
         break;
        }
        j = d[p + (k >>> 3) >> 0] << (k & 7 | 24);
        if ((q - k + -8 + (k & 7) | 0) > 0) {
         m = q - k + -8 + (k & 7) | 0;
         n = k & 7 | 24;
         k = p + (k >>> 3) | 0;
        } else break;
        while (1) {
         k = k + 1 | 0;
         n = n + -8 | 0;
         j = d[k >> 0] << n | j;
         if ((m | 0) <= 8) break; else m = m + -8 | 0;
        }
       } while (0);
       m = ra + 2 | 0;
       c[Qb + 16 >> 2] = m;
       c[Ob >> 2] = m & 7;
       if (q >>> 0 < m >>> 0) break j;
       c[Qb + 4 >> 2] = p + (m >>> 3);
       c[v + 920 >> 2] = j >>> 31;
       if ((j | 0) < 0) {
        do if ((q - m | 0) > 31) {
         k = d[p + (m >>> 3) + 1 >> 0] << 16 | d[p + (m >>> 3) >> 0] << 24 | d[p + (m >>> 3) + 2 >> 0] << 8 | d[p + (m >>> 3) + 3 >> 0];
         if (!(m & 7)) break;
         k = (d[p + (m >>> 3) + 4 >> 0] | 0) >>> (8 - (m & 7) | 0) | k << (m & 7);
        } else {
         if ((q - m | 0) <= 0) {
          k = 0;
          break;
         }
         k = d[p + (m >>> 3) >> 0] << (m & 7 | 24);
         if ((q - m + -8 + (m & 7) | 0) > 0) {
          n = q - m + -8 + (m & 7) | 0;
          o = m & 7 | 24;
          j = p + (m >>> 3) | 0;
         } else break;
         while (1) {
          j = j + 1 | 0;
          o = o + -8 | 0;
          k = d[j >> 0] << o | k;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        j = ra + 3 | 0;
        c[Qb + 16 >> 2] = j;
        c[Ob >> 2] = j & 7;
        if (j >>> 0 > q >>> 0) break j;
        c[Qb + 4 >> 2] = p + (j >>> 3);
        c[v + 924 >> 2] = k >>> 31;
        if (va(Qb, v + 928 | 0) | 0) break j;
        if ((c[v + 928 >> 2] | 0) >>> 0 > 16) break j;
        if (va(Qb, v + 932 | 0) | 0) break j;
        if ((c[v + 932 >> 2] | 0) >>> 0 > 16) break j;
        if (va(Qb, v + 936 | 0) | 0) break j;
        if ((c[v + 936 >> 2] | 0) >>> 0 > 16) break j;
        if (va(Qb, v + 940 | 0) | 0) break j;
        if ((c[v + 940 >> 2] | 0) >>> 0 > 16) break j;
        if (va(Qb, v + 944 | 0) | 0) break j;
        if (va(Qb, v + 948 | 0) | 0) break j;
       } else {
        c[v + 924 >> 2] = 1;
        c[v + 928 >> 2] = 2;
        c[v + 932 >> 2] = 1;
        c[v + 936 >> 2] = 16;
        c[v + 940 >> 2] = 16;
        c[v + 944 >> 2] = 16;
        c[v + 948 >> 2] = 16;
       }
       j = c[Qb + 96 + 84 >> 2] | 0;
       if (!(c[j + 920 >> 2] | 0)) break;
       k = c[j + 948 >> 2] | 0;
       if ((k >>> 0 < (c[w >> 2] | 0) >>> 0 ? 1 : (c[j + 944 >> 2] | 0) >>> 0 > k >>> 0) | k >>> 0 > (c[Qb + 96 + 88 >> 2] | 0) >>> 0) break j;
       c[Qb + 96 + 88 >> 2] = (k | 0) == 0 ? 1 : k;
      } while (0);
      Pb = c[bb >> 2] << 3;
      j = (c[Qb + 16 >> 2] | 0) + (8 - (c[Ob >> 2] | 0)) | 0;
      c[Qb + 16 >> 2] = j;
      c[Ob >> 2] = j & 7;
      if (j >>> 0 <= Pb >>> 0) c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + (j >>> 3);
      p = c[Qb + 96 + 8 >> 2] | 0;
      q = c[e + 20 + (p << 2) >> 2] | 0;
      do if (!q) {
       Pb = _a(92) | 0;
       c[e + 20 + (p << 2) >> 2] = Pb;
       if (!Pb) fa = 0; else break;
       l = Qb;
       return fa | 0;
      } else {
       if ((p | 0) != (c[e + 8 >> 2] | 0)) {
        $a(c[q + 40 >> 2] | 0);
        c[(c[e + 20 + (p << 2) >> 2] | 0) + 40 >> 2] = 0;
        $a(c[(c[e + 20 + (p << 2) >> 2] | 0) + 84 >> 2] | 0);
        c[(c[e + 20 + (p << 2) >> 2] | 0) + 84 >> 2] = 0;
        break;
       }
       r = c[e + 16 >> 2] | 0;
       l : do if ((c[Qb + 96 >> 2] | 0) == (c[r >> 2] | 0)) {
        if ((c[Qb + 96 + 4 >> 2] | 0) != (c[r + 4 >> 2] | 0)) break;
        if ((c[Qb + 96 + 12 >> 2] | 0) != (c[r + 12 >> 2] | 0)) break;
        j = c[Qb + 96 + 16 >> 2] | 0;
        if ((j | 0) != (c[r + 16 >> 2] | 0)) break;
        if ((c[w >> 2] | 0) != (c[r + 44 >> 2] | 0)) break;
        if ((c[Qb + 96 + 48 >> 2] | 0) != (c[r + 48 >> 2] | 0)) break;
        if ((c[Qb + 96 + 52 >> 2] | 0) != (c[r + 52 >> 2] | 0)) break;
        if ((c[Qb + 96 + 56 >> 2] | 0) != (c[r + 56 >> 2] | 0)) break;
        o = c[Qb + 96 + 60 >> 2] | 0;
        if ((o | 0) != (c[r + 60 >> 2] | 0)) break;
        if ((c[Qb + 96 + 80 >> 2] | 0) != (c[r + 80 >> 2] | 0)) break;
        m : do switch (j | 0) {
        case 0:
         {
          if ((c[Qb + 96 + 20 >> 2] | 0) != (c[r + 20 >> 2] | 0)) break l;
          break;
         }
        case 1:
         {
          if ((c[Qb + 96 + 24 >> 2] | 0) != (c[r + 24 >> 2] | 0)) break l;
          if ((c[Qb + 96 + 28 >> 2] | 0) != (c[r + 28 >> 2] | 0)) break l;
          if ((c[Qb + 96 + 32 >> 2] | 0) != (c[r + 32 >> 2] | 0)) break l;
          k = c[Qb + 96 + 36 >> 2] | 0;
          if ((k | 0) != (c[r + 36 >> 2] | 0)) break l;
          if (!k) break m;
          m = c[Qb + 96 + 40 >> 2] | 0;
          n = c[r + 40 >> 2] | 0;
          j = 0;
          do {
           if ((c[m + (j << 2) >> 2] | 0) != (c[n + (j << 2) >> 2] | 0)) break l;
           j = j + 1 | 0;
          } while (j >>> 0 < k >>> 0);
          break;
         }
        default:
         {}
        } while (0);
        if (o | 0) {
         if ((c[Qb + 96 + 64 >> 2] | 0) != (c[r + 64 >> 2] | 0)) break;
         if ((c[Qb + 96 + 68 >> 2] | 0) != (c[r + 68 >> 2] | 0)) break;
         if ((c[Qb + 96 + 72 >> 2] | 0) != (c[r + 72 >> 2] | 0)) break;
         if ((c[Qb + 96 + 76 >> 2] | 0) != (c[r + 76 >> 2] | 0)) break;
        }
        $a(c[Qb + 96 + 40 >> 2] | 0);
        c[Qb + 96 + 40 >> 2] = 0;
        $a(c[Qb + 96 + 84 >> 2] | 0);
        c[Qb + 96 + 84 >> 2] = 0;
        e = 0;
        l = Qb;
        return e | 0;
       } while (0);
       $a(c[q + 40 >> 2] | 0);
       c[(c[e + 20 + (p << 2) >> 2] | 0) + 40 >> 2] = 0;
       $a(c[(c[e + 20 + (p << 2) >> 2] | 0) + 84 >> 2] | 0);
       c[(c[e + 20 + (p << 2) >> 2] | 0) + 84 >> 2] = 0;
       c[e + 8 >> 2] = 33;
       c[e + 4 >> 2] = 257;
       c[e + 16 >> 2] = 0;
       c[e + 12 >> 2] = 0;
      } while (0);
      j = c[e + 20 + (p << 2) >> 2] | 0;
      k = Qb + 96 | 0;
      n = j + 92 | 0;
      do {
       c[j >> 2] = c[k >> 2];
       j = j + 4 | 0;
       k = k + 4 | 0;
      } while ((j | 0) < (n | 0));
      e = 0;
      l = Qb;
      return e | 0;
     }
    }
   } while (0);
   $a(c[Qb + 96 + 40 >> 2] | 0);
   c[Qb + 96 + 40 >> 2] = 0;
   $a(c[Qb + 96 + 84 >> 2] | 0);
   c[Qb + 96 + 84 >> 2] = 0;
   e = 3;
   l = Qb;
   return e | 0;
  }
 case 8:
  {
   j = Qb + 24 | 0;
   n = j + 72 | 0;
   do {
    c[j >> 2] = 0;
    j = j + 4 | 0;
   } while ((j | 0) < (n | 0));
   n : do if (!(va(Qb, Qb + 24 | 0) | 0 ? 1 : (c[Qb + 24 >> 2] | 0) >>> 0 > 255)) {
    Pb = (va(Qb, Qb + 24 + 4 | 0) | 0) != 0;
    if (!(Pb | (c[Qb + 24 + 4 >> 2] | 0) >>> 0 > 31)) {
     n = c[Qb + 4 >> 2] | 0;
     q = c[bb >> 2] << 3;
     r = c[Qb + 16 >> 2] | 0;
     if ((q - r | 0) > 31) {
      j = c[Ob >> 2] | 0;
      k = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
      if (j) k = (d[n + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
     } else if ((q - r | 0) > 0) {
      j = c[Ob >> 2] | 0;
      k = d[n >> 0] << j + 24;
      if ((q - r + -8 + j | 0) > 0) {
       o = q - r + -8 + j | 0;
       m = j + 24 | 0;
       j = n;
       while (1) {
        j = j + 1 | 0;
        m = m + -8 | 0;
        k = d[j >> 0] << m | k;
        if ((o | 0) <= 8) break; else o = o + -8 | 0;
       }
      }
     } else k = 0;
     c[Qb + 16 >> 2] = r + 1;
     m = r + 1 & 7;
     c[Ob >> 2] = m;
     if (q >>> 0 >= (r + 1 | 0) >>> 0) {
      p = c[Qb >> 2] | 0;
      n = p + ((r + 1 | 0) >>> 3) | 0;
      c[Qb + 4 >> 2] = n;
      if ((k | 0) > -1) {
       do if ((q - (r + 1) | 0) > 31) {
        j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
        if (m) j = (d[n + 4 >> 0] | 0) >>> (8 - m | 0) | j << m;
       } else if ((q - (r + 1) | 0) > 0) {
        j = d[n >> 0] << (m | 24);
        if ((q - (r + 1) + -8 + m | 0) > 0) {
         o = q - (r + 1) + -8 + m | 0;
         m = m | 24;
         k = n;
        } else break;
        while (1) {
         k = k + 1 | 0;
         m = m + -8 | 0;
         j = d[k >> 0] << m | j;
         if ((o | 0) <= 8) break; else o = o + -8 | 0;
        }
       } else j = 0; while (0);
       c[Qb + 16 >> 2] = r + 2;
       c[Ob >> 2] = r + 2 & 7;
       if ((r + 2 | 0) >>> 0 <= q >>> 0) {
        c[Qb + 4 >> 2] = p + ((r + 2 | 0) >>> 3);
        c[Qb + 24 + 8 >> 2] = j >>> 31;
        if (!(va(Qb, Qb + 648 | 0) | 0)) {
         j = (c[Qb + 648 >> 2] | 0) + 1 | 0;
         u = Qb + 24 + 12 | 0;
         c[u >> 2] = j;
         if (j >>> 0 > 8) break;
         o : do if (j >>> 0 > 1) {
          if (va(Qb, Qb + 24 + 16 | 0) | 0) break n;
          j = c[Qb + 24 + 16 >> 2] | 0;
          if (j >>> 0 > 6) break n;
          switch (j | 0) {
          case 0:
           {
            Pb = _a(c[u >> 2] << 2) | 0;
            c[Qb + 24 + 20 >> 2] = Pb;
            if (!Pb) break n;
            if (!(c[u >> 2] | 0)) break o; else j = 0;
            do {
             if (va(Qb, Qb + 648 | 0) | 0) break n;
             c[(c[Qb + 24 + 20 >> 2] | 0) + (j << 2) >> 2] = (c[Qb + 648 >> 2] | 0) + 1;
             j = j + 1 | 0;
            } while (j >>> 0 < (c[u >> 2] | 0) >>> 0);
            break;
           }
          case 2:
           {
            c[Qb + 24 + 24 >> 2] = _a((c[u >> 2] << 2) + -4 | 0) | 0;
            Pb = _a((c[u >> 2] << 2) + -4 | 0) | 0;
            c[Qb + 24 + 28 >> 2] = Pb;
            if ((Pb | 0) == 0 ? 1 : (c[Qb + 24 + 24 >> 2] | 0) == 0) break n;
            if ((c[u >> 2] | 0) == 1) break o; else j = 0;
            do {
             if (va(Qb, Qb + 648 | 0) | 0) break n;
             c[(c[Qb + 24 + 24 >> 2] | 0) + (j << 2) >> 2] = c[Qb + 648 >> 2];
             if (va(Qb, Qb + 648 | 0) | 0) break n;
             c[(c[Qb + 24 + 28 >> 2] | 0) + (j << 2) >> 2] = c[Qb + 648 >> 2];
             j = j + 1 | 0;
            } while (j >>> 0 < ((c[u >> 2] | 0) + -1 | 0) >>> 0);
            break;
           }
          case 5:
          case 4:
          case 3:
           {
            n = c[Qb + 4 >> 2] | 0;
            p = c[bb >> 2] << 3;
            q = c[Qb + 16 >> 2] | 0;
            do if ((p - q | 0) > 31) {
             k = c[Ob >> 2] | 0;
             j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
             if (!k) break;
             j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
            } else {
             if ((p - q | 0) <= 0) {
              j = 0;
              break;
             }
             k = c[Ob >> 2] | 0;
             j = d[n >> 0] << k + 24;
             if ((p - q + -8 + k | 0) > 0) {
              o = p - q + -8 + k | 0;
              m = k + 24 | 0;
              k = n;
             } else break;
             while (1) {
              k = k + 1 | 0;
              m = m + -8 | 0;
              j = d[k >> 0] << m | j;
              if ((o | 0) <= 8) break; else o = o + -8 | 0;
             }
            } while (0);
            c[Qb + 16 >> 2] = q + 1;
            c[Ob >> 2] = q + 1 & 7;
            if ((q + 1 | 0) >>> 0 > p >>> 0) break n;
            c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
            c[Qb + 24 + 32 >> 2] = j >>> 31;
            if (va(Qb, Qb + 648 | 0) | 0) break n;
            c[Qb + 24 + 36 >> 2] = (c[Qb + 648 >> 2] | 0) + 1;
            break o;
           }
          case 6:
           {
            if (va(Qb, Qb + 648 | 0) | 0) break n;
            s = (c[Qb + 648 >> 2] | 0) + 1 | 0;
            c[Qb + 24 + 40 >> 2] = s;
            s = _a(s << 2) | 0;
            c[Qb + 24 + 44 >> 2] = s;
            if (!s) break n;
            t = c[288 + ((c[u >> 2] | 0) + -1 << 2) >> 2] | 0;
            if (!(c[Qb + 24 + 40 >> 2] | 0)) break o;
            j = 0;
            p = c[Qb + 4 >> 2] | 0;
            while (1) {
             q = c[bb >> 2] << 3;
             r = c[Qb + 16 >> 2] | 0;
             do if ((q - r | 0) > 31) {
              m = c[Ob >> 2] | 0;
              k = d[p + 1 >> 0] << 16 | d[p >> 0] << 24 | d[p + 2 >> 0] << 8 | d[p + 3 >> 0];
              if (!m) break;
              k = (d[p + 4 >> 0] | 0) >>> (8 - m | 0) | k << m;
             } else {
              if ((q - r | 0) <= 0) {
               k = 0;
               break;
              }
              m = c[Ob >> 2] | 0;
              k = d[p >> 0] << m + 24;
              if ((q - r + -8 + m | 0) > 0) {
               o = q - r + -8 + m | 0;
               n = m + 24 | 0;
               m = p;
              } else break;
              while (1) {
               m = m + 1 | 0;
               n = n + -8 | 0;
               k = d[m >> 0] << n | k;
               if ((o | 0) <= 8) break; else o = o + -8 | 0;
              }
             } while (0);
             c[Qb + 16 >> 2] = r + t;
             c[Ob >> 2] = r + t & 7;
             if ((r + t | 0) >>> 0 > q >>> 0) break;
             Pb = k >>> (32 - t | 0);
             p = (c[Qb >> 2] | 0) + ((r + t | 0) >>> 3) | 0;
             c[Qb + 4 >> 2] = p;
             c[s + (j << 2) >> 2] = Pb;
             j = j + 1 | 0;
             if (Pb >>> 0 >= (c[u >> 2] | 0) >>> 0) break n;
             if (j >>> 0 >= (c[Qb + 24 + 40 >> 2] | 0) >>> 0) break o;
            }
            c[s + (j << 2) >> 2] = -1;
            break n;
           }
          default:
           break o;
          }
         } while (0);
         if (va(Qb, Qb + 648 | 0) | 0) break;
         j = c[Qb + 648 >> 2] | 0;
         if (j >>> 0 > 31) break;
         c[Qb + 24 + 48 >> 2] = j + 1;
         Pb = (va(Qb, Qb + 648 | 0) | 0) != 0;
         if (Pb | (c[Qb + 648 >> 2] | 0) >>> 0 > 31) break;
         n = c[Qb + 4 >> 2] | 0;
         q = c[bb >> 2] << 3;
         r = c[Qb + 16 >> 2] | 0;
         do if ((q - r | 0) > 31) {
          j = c[Ob >> 2] | 0;
          k = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
          if (!j) break;
          k = (d[n + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
         } else {
          if ((q - r | 0) <= 0) {
           k = 0;
           break;
          }
          j = c[Ob >> 2] | 0;
          k = d[n >> 0] << j + 24;
          if ((q - r + -8 + j | 0) > 0) {
           o = q - r + -8 + j | 0;
           m = j + 24 | 0;
           j = n;
          } else break;
          while (1) {
           j = j + 1 | 0;
           m = m + -8 | 0;
           k = d[j >> 0] << m | k;
           if ((o | 0) <= 8) break; else o = o + -8 | 0;
          }
         } while (0);
         c[Qb + 16 >> 2] = r + 1;
         m = r + 1 & 7;
         c[Ob >> 2] = m;
         if (q >>> 0 < (r + 1 | 0) >>> 0) break;
         p = c[Qb >> 2] | 0;
         n = p + ((r + 1 | 0) >>> 3) | 0;
         c[Qb + 4 >> 2] = n;
         if ((k | 0) <= -1) break;
         do if ((q - (r + 1) | 0) > 31) {
          j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
          if (!m) break;
          j = (d[n + 4 >> 0] | 0) >>> (8 - m | 0) | j << m;
         } else {
          if ((q - (r + 1) | 0) <= 0) {
           j = 0;
           break;
          }
          j = d[n >> 0] << (m | 24);
          if ((q - (r + 1) + -8 + m | 0) > 0) {
           o = q - (r + 1) + -8 + m | 0;
           m = m | 24;
           k = n;
          } else break;
          while (1) {
           k = k + 1 | 0;
           m = m + -8 | 0;
           j = d[k >> 0] << m | j;
           if ((o | 0) <= 8) break; else o = o + -8 | 0;
          }
         } while (0);
         c[Qb + 16 >> 2] = r + 3;
         c[Ob >> 2] = r + 3 & 7;
         if ((r + 3 | 0) >>> 0 > q >>> 0) break;
         c[Qb + 4 >> 2] = p + ((r + 3 | 0) >>> 3);
         if (j >>> 0 > 3221225471) break;
         c[Qb + 688 >> 2] = 0;
         j = va(Qb, Qb + 688 | 0) | 0;
         k = c[Qb + 688 >> 2] | 0;
         do if ((k | 0) == -1) {
          if (!j) break;
          break n;
         } else {
          if (j | 0) break;
          j = (k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0) + 26 | 0;
          if (j >>> 0 > 51) break n;
          c[Qb + 24 + 52 >> 2] = j;
          c[Qb + 688 >> 2] = 0;
          j = va(Qb, Qb + 688 | 0) | 0;
          k = c[Qb + 688 >> 2] | 0;
          do if ((k | 0) == -1) {
           if (!j) break;
           break n;
          } else {
           if (j | 0) break;
           if (((k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0) + 26 | 0) >>> 0 > 51) break n;
           c[Qb + 688 >> 2] = 0;
           k = va(Qb, Qb + 688 | 0) | 0;
           j = c[Qb + 688 >> 2] | 0;
           do if ((j | 0) == -1) {
            if (!k) break;
            break n;
           } else {
            j = j & 1 | 0 ? (j + 1 | 0) >>> 1 : 0 - ((j + 1 | 0) >>> 1) | 0;
            if (k | 0) break;
            if ((j + 12 | 0) >>> 0 > 24) break n;
            c[Qb + 24 + 56 >> 2] = j;
            o = c[Qb + 4 >> 2] | 0;
            r = c[bb >> 2] << 3;
            q = c[Qb + 16 >> 2] | 0;
            do if ((r - q | 0) > 31) {
             j = c[Ob >> 2] | 0;
             k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
             if (!j) break;
             k = (d[o + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
            } else {
             if ((r - q | 0) <= 0) {
              k = 0;
              break;
             }
             j = c[Ob >> 2] | 0;
             k = d[o >> 0] << j + 24;
             if ((r - q + -8 + j | 0) > 0) {
              n = r - q + -8 + j | 0;
              m = j + 24 | 0;
              j = o;
             } else break;
             while (1) {
              j = j + 1 | 0;
              m = m + -8 | 0;
              k = d[j >> 0] << m | k;
              if ((n | 0) <= 8) break; else n = n + -8 | 0;
             }
            } while (0);
            c[Qb + 16 >> 2] = q + 1;
            m = q + 1 & 7;
            c[Ob >> 2] = m;
            if (r >>> 0 < (q + 1 | 0) >>> 0) break n;
            p = c[Qb >> 2] | 0;
            n = p + ((q + 1 | 0) >>> 3) | 0;
            c[Qb + 4 >> 2] = n;
            c[Qb + 24 + 60 >> 2] = k >>> 31;
            do if ((r - (q + 1) | 0) > 31) {
             j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
             if (!m) break;
             j = (d[n + 4 >> 0] | 0) >>> (8 - m | 0) | j << m;
            } else {
             if ((r - (q + 1) | 0) <= 0) {
              j = 0;
              break;
             }
             j = d[n >> 0] << (m | 24);
             if ((r - (q + 1) + -8 + m | 0) > 0) {
              o = r - (q + 1) + -8 + m | 0;
              m = m | 24;
              k = n;
             } else break;
             while (1) {
              k = k + 1 | 0;
              m = m + -8 | 0;
              j = d[k >> 0] << m | j;
              if ((o | 0) <= 8) break; else o = o + -8 | 0;
             }
            } while (0);
            c[Qb + 16 >> 2] = q + 2;
            m = q + 2 & 7;
            c[Ob >> 2] = m;
            if (r >>> 0 < (q + 2 | 0) >>> 0) break n;
            k = p + ((q + 2 | 0) >>> 3) | 0;
            c[Qb + 4 >> 2] = k;
            c[Qb + 24 + 64 >> 2] = j >>> 31;
            do if ((r - (q + 2) | 0) > 31) {
             j = d[k + 1 >> 0] << 16 | d[k >> 0] << 24 | d[k + 2 >> 0] << 8 | d[k + 3 >> 0];
             if (!m) break;
             j = (d[k + 4 >> 0] | 0) >>> (8 - m | 0) | j << m;
            } else {
             if ((r - (q + 2) | 0) <= 0) {
              j = 0;
              break;
             }
             j = d[k >> 0] << (m | 24);
             if ((r - (q + 2) + -8 + m | 0) > 0) {
              n = r - (q + 2) + -8 + m | 0;
              m = m | 24;
             } else break;
             while (1) {
              k = k + 1 | 0;
              m = m + -8 | 0;
              j = d[k >> 0] << m | j;
              if ((n | 0) <= 8) break; else n = n + -8 | 0;
             }
            } while (0);
            c[Qb + 16 >> 2] = q + 3;
            c[Ob >> 2] = q + 3 & 7;
            if (r >>> 0 < (q + 3 | 0) >>> 0) break n;
            c[Qb + 4 >> 2] = p + ((q + 3 | 0) >>> 3);
            c[Qb + 24 + 68 >> 2] = j >>> 31;
            j = q + 3 + (8 - (q + 3 & 7)) | 0;
            c[Qb + 16 >> 2] = j;
            c[Ob >> 2] = j & 7;
            if (j >>> 0 <= r >>> 0) c[Qb + 4 >> 2] = p + (j >>> 3);
            k = c[Qb + 24 >> 2] | 0;
            j = c[e + 148 + (k << 2) >> 2] | 0;
            do if (!j) {
             j = _a(72) | 0;
             c[e + 148 + (k << 2) >> 2] = j;
             if (!j) fa = 0; else break;
             l = Qb;
             return fa | 0;
            } else {
             if ((k | 0) == (c[e + 4 >> 2] | 0)) {
              if ((c[Qb + 24 + 4 >> 2] | 0) != (c[e + 8 >> 2] | 0)) {
               c[e + 4 >> 2] = 257;
               j = c[e + 148 + (k << 2) >> 2] | 0;
              }
              $a(c[j + 20 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 20 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 24 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 24 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 28 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 28 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 44 >> 2] | 0);
             } else {
              $a(c[j + 20 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 20 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 24 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 24 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 28 >> 2] | 0);
              c[(c[e + 148 + (k << 2) >> 2] | 0) + 28 >> 2] = 0;
              $a(c[(c[e + 148 + (k << 2) >> 2] | 0) + 44 >> 2] | 0);
             }
             c[(c[e + 148 + (k << 2) >> 2] | 0) + 44 >> 2] = 0;
             j = c[e + 148 + (k << 2) >> 2] | 0;
            } while (0);
            k = Qb + 24 | 0;
            n = j + 72 | 0;
            do {
             c[j >> 2] = c[k >> 2];
             j = j + 4 | 0;
             k = k + 4 | 0;
            } while ((j | 0) < (n | 0));
            e = 0;
            l = Qb;
            return e | 0;
           } while (0);
           break n;
          } while (0);
          break n;
         } while (0);
        }
       }
      }
     }
    }
   } while (0);
   $a(c[Qb + 24 + 20 >> 2] | 0);
   c[Qb + 24 + 20 >> 2] = 0;
   $a(c[Qb + 24 + 24 >> 2] | 0);
   c[Qb + 24 + 24 >> 2] = 0;
   $a(c[Qb + 24 + 28 >> 2] | 0);
   c[Qb + 24 + 28 >> 2] = 0;
   $a(c[Qb + 24 + 44 >> 2] | 0);
   c[Qb + 24 + 44 >> 2] = 0;
   e = 3;
   l = Qb;
   return e | 0;
  }
 case 1:
 case 5:
  {
   if (c[e + 1180 >> 2] | 0) {
    e = 0;
    l = Qb;
    return e | 0;
   }
   c[e + 1184 >> 2] = 1;
   p : do if (!(c[e + 1188 >> 2] | 0)) {
    c[e + 1204 >> 2] = 0;
    c[e + 1208 >> 2] = h;
    c[Qb + 648 >> 2] = c[Qb >> 2];
    c[Qb + 648 + 4 >> 2] = c[Qb + 4 >> 2];
    c[Qb + 648 + 8 >> 2] = c[Qb + 8 >> 2];
    c[Qb + 648 + 12 >> 2] = c[Qb + 12 >> 2];
    c[Qb + 648 + 16 >> 2] = c[Qb + 16 >> 2];
    if (!(va(Qb + 648 | 0, Qb + 688 | 0) | 0)) if (!(va(Qb + 648 | 0, Qb + 688 | 0) | 0)) {
     va(Qb + 648 | 0, Qb + 688 | 0) | 0;
     s = c[Qb + 688 >> 2] | 0;
    } else s = 0; else s = 0;
    v = c[e + 8 >> 2] | 0;
    t = e + 148 + (s << 2) | 0;
    k = c[t >> 2] | 0;
    q : do if (!k) j = 4; else {
     u = c[k + 4 >> 2] | 0;
     j = c[e + 20 + (u << 2) >> 2] | 0;
     if (!j) j = 4; else {
      p = c[j + 52 >> 2] | 0;
      q = N(c[j + 56 >> 2] | 0, p) | 0;
      r = c[k + 12 >> 2] | 0;
      r : do if (r >>> 0 > 1) {
       j = c[k + 16 >> 2] | 0;
       switch (j | 0) {
       case 0:
        {
         k = c[k + 20 >> 2] | 0;
         j = 0;
         do {
          if ((c[k + (j << 2) >> 2] | 0) >>> 0 > q >>> 0) {
           j = 4;
           break q;
          }
          j = j + 1 | 0;
         } while (j >>> 0 < r >>> 0);
         break;
        }
       case 2:
        {
         o = c[k + 24 >> 2] | 0;
         k = c[k + 28 >> 2] | 0;
         j = 0;
         do {
          m = c[o + (j << 2) >> 2] | 0;
          n = c[k + (j << 2) >> 2] | 0;
          if (!(m >>> 0 <= n >>> 0 & n >>> 0 < q >>> 0)) {
           j = 4;
           break q;
          }
          j = j + 1 | 0;
          if (((m >>> 0) % (p >>> 0) | 0) >>> 0 > ((n >>> 0) % (p >>> 0) | 0) >>> 0) {
           j = 4;
           break q;
          }
         } while (j >>> 0 < (r + -1 | 0) >>> 0);
         break;
        }
       default:
        {
         if ((j + -3 | 0) >>> 0 < 3) if ((c[k + 36 >> 2] | 0) >>> 0 > q >>> 0) {
          j = 4;
          break q;
         } else break r;
         if ((j | 0) != 6) break r;
         if ((c[k + 40 >> 2] | 0) >>> 0 < q >>> 0) {
          j = 4;
          break q;
         } else break r;
        }
       }
      } while (0);
      j = c[e + 4 >> 2] | 0;
      do if ((j | 0) == 256) {
       c[e + 4 >> 2] = s;
       j = c[t >> 2] | 0;
       c[e + 12 >> 2] = j;
       j = c[j + 4 >> 2] | 0;
       c[e + 8 >> 2] = j;
       fb = c[e + 20 + (j << 2) >> 2] | 0;
       c[e + 16 >> 2] = fb;
       eb = c[fb + 52 >> 2] | 0;
       fb = c[fb + 56 >> 2] | 0;
       c[e + 1176 >> 2] = N(fb, eb) | 0;
       c[e + 1340 >> 2] = eb;
       c[e + 1344 >> 2] = fb;
       c[e + 3380 >> 2] = 1;
      } else {
       if (!(c[e + 3380 >> 2] | 0)) {
        if ((j | 0) == (s | 0)) {
         j = v;
         break;
        }
        if ((u | 0) == (v | 0)) {
         c[e + 4 >> 2] = s;
         c[e + 12 >> 2] = c[t >> 2];
         j = v;
         break;
        }
        if ((C | 0) != 5) {
         j = 4;
         break q;
        }
        c[e + 4 >> 2] = s;
        j = c[t >> 2] | 0;
        c[e + 12 >> 2] = j;
        j = c[j + 4 >> 2] | 0;
        c[e + 8 >> 2] = j;
        fb = c[e + 20 + (j << 2) >> 2] | 0;
        c[e + 16 >> 2] = fb;
        eb = c[fb + 52 >> 2] | 0;
        fb = c[fb + 56 >> 2] | 0;
        c[e + 1176 >> 2] = N(fb, eb) | 0;
        c[e + 1340 >> 2] = eb;
        c[e + 1344 >> 2] = fb;
        c[e + 3380 >> 2] = 1;
        break;
       }
       c[e + 3380 >> 2] = 0;
       $a(c[e + 1212 >> 2] | 0);
       c[e + 1212 >> 2] = 0;
       $a(c[e + 1172 >> 2] | 0);
       c[e + 1172 >> 2] = 0;
       c[e + 1212 >> 2] = _a((c[e + 1176 >> 2] | 0) * 216 | 0) | 0;
       fb = _a(c[e + 1176 >> 2] << 2) | 0;
       c[e + 1172 >> 2] = fb;
       j = c[e + 1212 >> 2] | 0;
       if ((fb | 0) == 0 | (j | 0) == 0) {
        j = 5;
        break q;
       }
       pb(j | 0, 0, (c[e + 1176 >> 2] | 0) * 216 | 0) | 0;
       n = c[e + 1212 >> 2] | 0;
       r = c[e + 16 >> 2] | 0;
       p = c[r + 52 >> 2] | 0;
       o = c[e + 1176 >> 2] | 0;
       if (o | 0) {
        k = 0;
        m = 0;
        j = 0;
        while (1) {
         db = (j | 0) != 0;
         fb = n + (m * 216 | 0) | 0;
         c[n + (m * 216 | 0) + 200 >> 2] = db ? fb + -216 | 0 : 0;
         eb = (k | 0) != 0;
         c[n + (m * 216 | 0) + 204 >> 2] = eb ? fb + ((0 - p | 0) * 216 | 0) | 0 : 0;
         c[n + (m * 216 | 0) + 208 >> 2] = j >>> 0 < (p + -1 | 0) >>> 0 & eb ? fb + ((1 - p | 0) * 216 | 0) | 0 : 0;
         c[n + (m * 216 | 0) + 212 >> 2] = db & eb ? fb + (~p * 216 | 0) | 0 : 0;
         j = j + 1 | 0;
         m = m + 1 | 0;
         if ((m | 0) == (o | 0)) break; else {
          k = k + ((j | 0) == (p | 0) & 1) | 0;
          j = (j | 0) == (p | 0) ? 0 : j;
         }
        }
       }
       s : do if (!(c[e + 1216 >> 2] | 0)) {
        if ((c[r + 16 >> 2] | 0) == 2) {
         q = 1;
         break;
        }
        do if (c[r + 80 >> 2] | 0) {
         j = c[r + 84 >> 2] | 0;
         if (!(c[j + 920 >> 2] | 0)) break;
         if (!(c[j + 944 >> 2] | 0)) {
          q = 1;
          break s;
         }
        } while (0);
        q = 0;
       } else q = 1; while (0);
       p = N(c[r + 56 >> 2] | 0, p) | 0;
       n = c[r + 88 >> 2] | 0;
       o = c[r + 44 >> 2] | 0;
       m = c[r + 12 >> 2] | 0;
       j = c[e + 1220 >> 2] | 0;
       do if (j) {
        if ((c[e + 1248 >> 2] | 0) == -1) break; else k = 0;
        do {
         $a(c[j + (k * 40 | 0) + 4 >> 2] | 0);
         j = c[e + 1220 >> 2] | 0;
         c[j + (k * 40 | 0) + 4 >> 2] = 0;
         k = k + 1 | 0;
        } while (k >>> 0 < ((c[e + 1248 >> 2] | 0) + 1 | 0) >>> 0);
       } while (0);
       $a(j);
       c[e + 1220 >> 2] = 0;
       $a(c[e + 1224 >> 2] | 0);
       c[e + 1224 >> 2] = 0;
       $a(c[e + 1232 >> 2] | 0);
       c[e + 1232 >> 2] = 0;
       c[e + 1256 >> 2] = 65535;
       j = o >>> 0 > 1 ? o : 1;
       c[e + 1244 >> 2] = j;
       c[e + 1248 >> 2] = (q | 0) == 0 ? n : j;
       c[e + 1252 >> 2] = m;
       c[e + 1276 >> 2] = q;
       c[e + 1264 >> 2] = 0;
       c[e + 1260 >> 2] = 0;
       c[e + 1268 >> 2] = 0;
       j = _a(680) | 0;
       c[e + 1220 >> 2] = j;
       if (!j) {
        j = 5;
        break q;
       }
       pb(j | 0, 0, 680) | 0;
       if ((c[e + 1248 >> 2] | 0) != -1) {
        j = 0;
        do {
         k = _a(p * 384 | 47) | 0;
         m = c[e + 1220 >> 2] | 0;
         c[m + (j * 40 | 0) + 4 >> 2] = k;
         if (!k) {
          j = 5;
          break q;
         }
         c[m + (j * 40 | 0) >> 2] = k + (0 - k & 15);
         j = j + 1 | 0;
        } while (j >>> 0 < ((c[e + 1248 >> 2] | 0) + 1 | 0) >>> 0);
       }
       c[e + 1224 >> 2] = _a(68) | 0;
       fb = _a((c[e + 1248 >> 2] << 4) + 16 | 0) | 0;
       c[e + 1232 >> 2] = fb;
       j = c[e + 1224 >> 2] | 0;
       if ((fb | 0) == 0 | (j | 0) == 0) {
        j = 5;
        break q;
       }
       n = j + 68 | 0;
       do {
        a[j >> 0] = 0;
        j = j + 1 | 0;
       } while ((j | 0) < (n | 0));
       c[e + 1240 >> 2] = 0;
       c[e + 1236 >> 2] = 0;
       j = c[e + 8 >> 2] | 0;
      } while (0);
      if ((v | 0) == (j | 0)) break p;
      x = c[e + 16 >> 2] | 0;
      j = c[e >> 2] | 0;
      if (j >>> 0 < 32) w = c[e + 20 + (j << 2) >> 2] | 0; else w = 0;
      c[i >> 2] = 0;
      c[e + 3344 >> 2] = 1;
      t : do if ((C | 0) == 5) {
       t = c[e + 12 >> 2] | 0;
       c[Qb + 628 >> 2] = c[Qb >> 2];
       c[Qb + 628 + 4 >> 2] = c[Qb + 4 >> 2];
       c[Qb + 628 + 8 >> 2] = c[Qb + 8 >> 2];
       c[Qb + 628 + 12 >> 2] = c[Qb + 12 >> 2];
       c[Qb + 628 + 16 >> 2] = c[Qb + 16 >> 2];
       k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
       u : do if (!k) {
        k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
        if (k | 0) {
         j = 1;
         break;
        }
        k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
        if (k | 0) {
         j = 1;
         break;
        }
        j = c[x + 12 >> 2] | 0;
        s = 0;
        while (1) if (!(j >>> s)) break; else s = s + 1 | 0;
        p = s + -1 | 0;
        u = Qb + 628 + 4 | 0;
        n = c[u >> 2] | 0;
        q = c[Qb + 628 + 12 >> 2] << 3;
        v = Qb + 628 + 16 | 0;
        r = c[v >> 2] | 0;
        do if ((q - r | 0) > 31) {
         k = c[Qb + 628 + 8 >> 2] | 0;
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!k) {
          k = Qb + 628 + 8 | 0;
          break;
         }
         j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
         k = Qb + 628 + 8 | 0;
        } else {
         if ((q - r | 0) <= 0) {
          j = 0;
          k = Qb + 628 + 8 | 0;
          break;
         }
         k = c[Qb + 628 + 8 >> 2] | 0;
         j = d[n >> 0] << k + 24;
         if ((q - r + -8 + k | 0) > 0) {
          o = q - r + -8 + k | 0;
          m = k + 24 | 0;
          k = n;
         } else {
          k = Qb + 628 + 8 | 0;
          break;
         }
         while (1) {
          k = k + 1 | 0;
          m = m + -8 | 0;
          j = d[k >> 0] << m | j;
          if ((o | 0) <= 8) {
           k = Qb + 628 + 8 | 0;
           break;
          } else o = o + -8 | 0;
         }
        } while (0);
        c[v >> 2] = p + r;
        c[k >> 2] = p + r & 7;
        if ((p + r | 0) >>> 0 > q >>> 0) {
         k = 1;
         j = 1;
         break;
        }
        c[u >> 2] = (c[Qb + 628 >> 2] | 0) + ((p + r | 0) >>> 3);
        if ((j >>> (33 - s | 0) | 0) == -1) {
         k = 1;
         j = 1;
         break;
        }
        k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
        if (k | 0) {
         j = 1;
         break;
        }
        j = c[x + 16 >> 2] | 0;
        do if (!j) {
         j = c[x + 20 >> 2] | 0;
         s = 0;
         while (1) if (!(j >>> s)) break; else s = s + 1 | 0;
         p = s + -1 | 0;
         n = c[u >> 2] | 0;
         q = c[Qb + 628 + 12 >> 2] << 3;
         r = c[v >> 2] | 0;
         do if ((q - r | 0) > 31) {
          k = c[Qb + 628 + 8 >> 2] | 0;
          j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
          if (!k) {
           k = Qb + 628 + 8 | 0;
           break;
          }
          j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
          k = Qb + 628 + 8 | 0;
         } else {
          if ((q - r | 0) <= 0) {
           j = 0;
           k = Qb + 628 + 8 | 0;
           break;
          }
          k = c[Qb + 628 + 8 >> 2] | 0;
          j = d[n >> 0] << k + 24;
          if ((q - r + -8 + k | 0) > 0) {
           o = q - r + -8 + k | 0;
           m = k + 24 | 0;
           k = n;
          } else {
           k = Qb + 628 + 8 | 0;
           break;
          }
          while (1) {
           k = k + 1 | 0;
           m = m + -8 | 0;
           j = d[k >> 0] << m | j;
           if ((o | 0) <= 8) {
            k = Qb + 628 + 8 | 0;
            break;
           } else o = o + -8 | 0;
          }
         } while (0);
         c[v >> 2] = p + r;
         c[k >> 2] = p + r & 7;
         if ((p + r | 0) >>> 0 > q >>> 0) {
          k = 1;
          j = 1;
          break u;
         }
         c[u >> 2] = (c[Qb + 628 >> 2] | 0) + ((p + r | 0) >>> 3);
         if ((j >>> (33 - s | 0) | 0) == -1) {
          k = 1;
          j = 1;
          break u;
         }
         if (!(c[t + 8 >> 2] | 0)) break;
         c[Qb + 688 >> 2] = 0;
         j = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
         if ((c[Qb + 688 >> 2] | 0) == -1) if (!j) Pb = 808; else Pb = 807; else if (!j) Pb = 807; else Pb = 808;
         if ((Pb | 0) == 807) {
          _ = c[x + 16 >> 2] | 0;
          Pb = 809;
          break;
         } else if ((Pb | 0) == 808) {
          k = 1;
          j = 1;
          break u;
         }
        } else {
         _ = j;
         Pb = 809;
        } while (0);
        do if ((Pb | 0) == 809) {
         if ((_ | 0) != 1) break;
         if (c[x + 24 >> 2] | 0) break;
         c[Qb + 688 >> 2] = 0;
         j = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
         if ((c[Qb + 688 >> 2] | 0) == -1) {
          if (!j) Pb = 814;
         } else if (j | 0) Pb = 814;
         if ((Pb | 0) == 814) {
          k = 1;
          j = 1;
          break u;
         }
         if (!(c[t + 8 >> 2] | 0)) break;
         c[Qb + 688 >> 2] = 0;
         j = va(Qb + 628 | 0, Qb + 688 | 0) | 0;
         if ((c[Qb + 688 >> 2] | 0) == -1) if (!j) Pb = 820; else Pb = 819; else if (!j) Pb = 819; else Pb = 820;
         if ((Pb | 0) == 819) break; else if ((Pb | 0) == 820) {
          k = 1;
          j = 1;
          break u;
         }
        } while (0);
        if (c[t + 68 >> 2] | 0) {
         k = va(Qb + 628 | 0, Qb + 648 | 0) | 0;
         if (k | 0) {
          j = 1;
          break;
         }
        }
        n = c[u >> 2] | 0;
        p = c[Qb + 628 + 12 >> 2] << 3;
        q = c[v >> 2] | 0;
        do if ((p - q | 0) > 31) {
         k = c[Qb + 628 + 8 >> 2] | 0;
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!k) {
          k = Qb + 628 + 8 | 0;
          break;
         }
         j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
         k = Qb + 628 + 8 | 0;
        } else {
         if ((p - q | 0) <= 0) {
          j = 0;
          k = Qb + 628 + 8 | 0;
          break;
         }
         k = c[Qb + 628 + 8 >> 2] | 0;
         j = d[n >> 0] << k + 24;
         if ((p - q + -8 + k | 0) > 0) {
          o = p - q + -8 + k | 0;
          m = k + 24 | 0;
          k = n;
         } else {
          k = Qb + 628 + 8 | 0;
          break;
         }
         while (1) {
          k = k + 1 | 0;
          m = m + -8 | 0;
          j = d[k >> 0] << m | j;
          if ((o | 0) <= 8) {
           k = Qb + 628 + 8 | 0;
           break;
          } else o = o + -8 | 0;
         }
        } while (0);
        c[v >> 2] = q + 1;
        c[k >> 2] = q + 1 & 7;
        if ((q + 1 | 0) >>> 0 > p >>> 0) j = -1; else {
         c[u >> 2] = (c[Qb + 628 >> 2] | 0) + ((q + 1 | 0) >>> 3);
         j = j >>> 31;
        }
        k = (j | 0) == -1 & 1;
       } else j = 1; while (0);
       if (j | k | 0) {
        Pb = 837;
        break;
       }
       if ((w | 0) == 0 | (c[e + 1276 >> 2] | 0) != 0) {
        Pb = 837;
        break;
       }
       if ((c[w + 52 >> 2] | 0) != (c[x + 52 >> 2] | 0)) {
        Pb = 837;
        break;
       }
       if ((c[w + 56 >> 2] | 0) != (c[x + 56 >> 2] | 0)) {
        Pb = 837;
        break;
       }
       if ((c[w + 88 >> 2] | 0) != (c[x + 88 >> 2] | 0)) {
        Pb = 837;
        break;
       }
       n = c[e + 1220 >> 2] | 0;
       if (!n) break;
       c[e + 1280 >> 2] = 1;
       o = c[e + 1248 >> 2] | 0;
       while (1) {
        k = 2147483647;
        m = 0;
        j = 0;
        do {
         if (c[n + (m * 40 | 0) + 24 >> 2] | 0) {
          Ob = c[n + (m * 40 | 0) + 16 >> 2] | 0;
          Nb = (Ob | 0) < (k | 0);
          j = Nb ? n + (m * 40 | 0) | 0 : j;
          k = Nb ? Ob : k;
         }
         m = m + 1 | 0;
        } while (m >>> 0 <= o >>> 0);
        if (!j) break t;
        Nb = c[e + 1232 >> 2] | 0;
        Ob = c[e + 1236 >> 2] | 0;
        c[Nb + (Ob << 4) >> 2] = c[j >> 2];
        c[Nb + (Ob << 4) + 12 >> 2] = c[j + 36 >> 2];
        c[Nb + (Ob << 4) + 4 >> 2] = c[j + 28 >> 2];
        c[Nb + (Ob << 4) + 8 >> 2] = c[j + 32 >> 2];
        c[e + 1236 >> 2] = Ob + 1;
        c[j + 24 >> 2] = 0;
        if (c[j + 20 >> 2] | 0) continue;
        c[e + 1264 >> 2] = (c[e + 1264 >> 2] | 0) + -1;
       }
      } else Pb = 837; while (0);
      if ((Pb | 0) == 837) c[e + 1280 >> 2] = 0;
      c[e >> 2] = c[e + 8 >> 2];
      e = 2;
      l = Qb;
      return e | 0;
     }
    } while (0);
    c[e + 4 >> 2] = 256;
    c[e + 12 >> 2] = 0;
    c[e + 8 >> 2] = 32;
    c[e + 16 >> 2] = 0;
    c[e + 3380 >> 2] = 0;
    e = j;
    l = Qb;
    return e | 0;
   } while (0);
   if (c[e + 3380 >> 2] | 0) {
    e = 3;
    l = Qb;
    return e | 0;
   }
   t = c[e + 16 >> 2] | 0;
   u = c[e + 12 >> 2] | 0;
   pb(e + 2356 | 0, 0, 988) | 0;
   v = N(c[t + 56 >> 2] | 0, c[t + 52 >> 2] | 0) | 0;
   v : do if (!(va(Qb, Qb + 628 | 0) | 0)) {
    fb = c[Qb + 628 >> 2] | 0;
    c[e + 2356 >> 2] = fb;
    if (fb >>> 0 < v >>> 0) if (!(va(Qb, Qb + 628 | 0) | 0)) {
     fb = c[Qb + 628 >> 2] | 0;
     c[e + 2360 >> 2] = fb;
     switch (fb | 0) {
     case 7:
     case 2:
      break;
     case 5:
     case 0:
      {
       if ((C | 0) == 5) break v;
       if (!(c[t + 44 >> 2] | 0)) break v;
       break;
      }
     default:
      break v;
     }
     if (!(va(Qb, Qb + 628 | 0) | 0)) {
      fb = c[Qb + 628 >> 2] | 0;
      c[e + 2364 >> 2] = fb;
      if ((fb | 0) == (c[u >> 2] | 0)) {
       j = c[t + 12 >> 2] | 0;
       q = 0;
       while (1) if (!(j >>> q)) break; else q = q + 1 | 0;
       r = q + -1 | 0;
       n = c[Qb + 4 >> 2] | 0;
       p = c[bb >> 2] << 3;
       s = c[Qb + 16 >> 2] | 0;
       do if ((p - s | 0) > 31) {
        k = c[Ob >> 2] | 0;
        j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
        if (!k) break;
        j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
       } else {
        if ((p - s | 0) <= 0) {
         j = 0;
         break;
        }
        k = c[Ob >> 2] | 0;
        j = d[n >> 0] << k + 24;
        if ((p - s + -8 + k | 0) > 0) {
         o = p - s + -8 + k | 0;
         m = k + 24 | 0;
         k = n;
        } else break;
        while (1) {
         k = k + 1 | 0;
         m = m + -8 | 0;
         j = d[k >> 0] << m | j;
         if ((o | 0) <= 8) break; else o = o + -8 | 0;
        }
       } while (0);
       c[Qb + 16 >> 2] = s + r;
       c[Ob >> 2] = s + r & 7;
       if ((s + r | 0) >>> 0 > p >>> 0) break;
       j = j >>> (33 - q | 0);
       c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((s + r | 0) >>> 3);
       if ((j | 0) == -1) break;
       if ((j | 0) != 0 & (C | 0) == 5) break;
       c[e + 2368 >> 2] = j;
       if ((C | 0) == 5) {
        if (va(Qb, Qb + 628 | 0) | 0) break;
        fb = c[Qb + 628 >> 2] | 0;
        c[e + 2372 >> 2] = fb;
        if (fb >>> 0 > 65535) break;
       }
       j = c[t + 16 >> 2] | 0;
       if (!j) {
        j = c[t + 20 >> 2] | 0;
        q = 0;
        while (1) if (!(j >>> q)) break; else q = q + 1 | 0;
        r = q + -1 | 0;
        n = c[Qb + 4 >> 2] | 0;
        p = c[bb >> 2] << 3;
        s = c[Qb + 16 >> 2] | 0;
        do if ((p - s | 0) > 31) {
         k = c[Ob >> 2] | 0;
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!k) break;
         j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
        } else {
         if ((p - s | 0) <= 0) {
          j = 0;
          break;
         }
         k = c[Ob >> 2] | 0;
         j = d[n >> 0] << k + 24;
         if ((p - s + -8 + k | 0) > 0) {
          o = p - s + -8 + k | 0;
          m = k + 24 | 0;
          k = n;
         } else break;
         while (1) {
          k = k + 1 | 0;
          m = m + -8 | 0;
          j = d[k >> 0] << m | j;
          if ((o | 0) <= 8) break; else o = o + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = s + r;
        c[Ob >> 2] = s + r & 7;
        if ((s + r | 0) >>> 0 > p >>> 0) break;
        j = j >>> (33 - q | 0);
        c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((s + r | 0) >>> 3);
        if ((j | 0) == -1) break;
        c[e + 2376 >> 2] = j;
        do if (c[u + 8 >> 2] | 0) {
         c[Qb + 688 >> 2] = 0;
         j = va(Qb, Qb + 688 | 0) | 0;
         k = c[Qb + 688 >> 2] | 0;
         if ((k | 0) == -1) if (!j) Pb = 886; else {
          X = -2147483648;
          Pb = 887;
         } else if (!j) {
          X = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0;
          Pb = 887;
         } else Pb = 886;
         if ((Pb | 0) == 886) break v; else if ((Pb | 0) == 887) {
          c[e + 2380 >> 2] = X;
          break;
         }
        } while (0);
        if ((C | 0) == 5) {
         j = c[e + 2376 >> 2] | 0;
         if (j >>> 0 > (c[t + 20 >> 2] | 0) >>> 1 >>> 0) break;
         fb = c[e + 2380 >> 2] | 0;
         if ((j | 0) != (0 - ((fb | 0) < 0 ? fb : 0) | 0)) break;
        }
        j = c[t + 16 >> 2] | 0;
       }
       do if ((j | 0) == 1) {
        if (c[t + 24 >> 2] | 0) break;
        c[Qb + 688 >> 2] = 0;
        j = va(Qb, Qb + 688 | 0) | 0;
        k = c[Qb + 688 >> 2] | 0;
        if ((k | 0) == -1) if (!j) Pb = 897; else Y = -2147483648; else if (!j) Y = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else Pb = 897;
        if ((Pb | 0) == 897) break v;
        c[e + 2384 >> 2] = Y;
        do if (c[u + 8 >> 2] | 0) {
         c[Qb + 688 >> 2] = 0;
         j = va(Qb, Qb + 688 | 0) | 0;
         k = c[Qb + 688 >> 2] | 0;
         if ((k | 0) == -1) if (!j) Pb = 902; else {
          Z = -2147483648;
          Pb = 903;
         } else if (!j) {
          Z = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0;
          Pb = 903;
         } else Pb = 902;
         if ((Pb | 0) == 902) break v; else if ((Pb | 0) == 903) {
          c[e + 2388 >> 2] = Z;
          break;
         }
        } while (0);
        if ((C | 0) != 5) break;
        eb = c[e + 2384 >> 2] | 0;
        fb = (c[t + 32 >> 2] | 0) + eb + (c[e + 2388 >> 2] | 0) | 0;
        if (((eb | 0) < (fb | 0) ? eb : fb) | 0) break v;
       } while (0);
       if (c[u + 68 >> 2] | 0) {
        if (va(Qb, Qb + 628 | 0) | 0) break;
        fb = c[Qb + 628 >> 2] | 0;
        c[e + 2392 >> 2] = fb;
        if (fb >>> 0 > 127) break;
       }
       j = c[e + 2360 >> 2] | 0;
       switch (j | 0) {
       case 5:
       case 0:
        {
         o = c[Qb + 4 >> 2] | 0;
         q = c[bb >> 2] << 3;
         r = c[Qb + 16 >> 2] | 0;
         do if ((q - r | 0) > 31) {
          m = c[Ob >> 2] | 0;
          k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
          if (!m) break;
          k = (d[o + 4 >> 0] | 0) >>> (8 - m | 0) | k << m;
         } else {
          if ((q - r | 0) <= 0) {
           k = 0;
           break;
          }
          m = c[Ob >> 2] | 0;
          k = d[o >> 0] << m + 24;
          if ((q - r + -8 + m | 0) > 0) {
           p = q - r + -8 + m | 0;
           n = m + 24 | 0;
           m = o;
          } else break;
          while (1) {
           m = m + 1 | 0;
           n = n + -8 | 0;
           k = d[m >> 0] << n | k;
           if ((p | 0) <= 8) break; else p = p + -8 | 0;
          }
         } while (0);
         c[Qb + 16 >> 2] = r + 1;
         c[Ob >> 2] = r + 1 & 7;
         if ((r + 1 | 0) >>> 0 > q >>> 0) break v;
         fb = k >>> 31;
         c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((r + 1 | 0) >>> 3);
         c[e + 2396 >> 2] = fb;
         if (!fb) {
          k = c[u + 48 >> 2] | 0;
          if (k >>> 0 > 16) break v;
         } else {
          if (va(Qb, Qb + 628 | 0) | 0) break v;
          k = c[Qb + 628 >> 2] | 0;
          if (k >>> 0 > 15) break v;
          j = c[e + 2360 >> 2] | 0;
          k = k + 1 | 0;
         }
         c[e + 2400 >> 2] = k;
         break;
        }
       default:
        {}
       }
       w : do switch (j | 0) {
       case 5:
       case 0:
        {
         r = c[e + 2400 >> 2] | 0;
         s = c[t + 12 >> 2] | 0;
         n = c[Qb + 4 >> 2] | 0;
         p = c[bb >> 2] << 3;
         q = c[Qb + 16 >> 2] | 0;
         do if ((p - q | 0) > 31) {
          k = c[Ob >> 2] | 0;
          j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
          if (!k) break;
          j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
         } else {
          if ((p - q | 0) <= 0) {
           j = 0;
           break;
          }
          k = c[Ob >> 2] | 0;
          j = d[n >> 0] << k + 24;
          if ((p - q + -8 + k | 0) > 0) {
           o = p - q + -8 + k | 0;
           m = k + 24 | 0;
           k = n;
          } else break;
          while (1) {
           k = k + 1 | 0;
           m = m + -8 | 0;
           j = d[k >> 0] << m | j;
           if ((o | 0) <= 8) break; else o = o + -8 | 0;
          }
         } while (0);
         c[Qb + 16 >> 2] = q + 1;
         c[Ob >> 2] = q + 1 & 7;
         x : do if ((q + 1 | 0) >>> 0 <= p >>> 0) {
          fb = j >>> 31;
          c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
          c[e + 2424 >> 2] = fb;
          if (fb | 0) {
           j = 0;
           while (1) {
            if (va(Qb, Qb + 648 | 0) | 0) break x;
            k = c[Qb + 648 >> 2] | 0;
            if (k >>> 0 > 3) break x;
            c[e + 2428 + (j * 12 | 0) >> 2] = k;
            if (k >>> 0 < 2) {
             if (va(Qb, Qb + 688 | 0) | 0) break x;
             k = c[Qb + 688 >> 2] | 0;
             if (k >>> 0 >= s >>> 0) break x;
             c[e + 2428 + (j * 12 | 0) + 4 >> 2] = k + 1;
            } else {
             if ((k | 0) != 2) break;
             if (va(Qb, Qb + 688 | 0) | 0) break x;
             c[e + 2428 + (j * 12 | 0) + 8 >> 2] = c[Qb + 688 >> 2];
            }
            j = j + 1 | 0;
            if (j >>> 0 > r >>> 0) break x;
           }
           if (!j) break;
          }
          break w;
         } while (0);
         break v;
        }
       default:
        {}
       } while (0);
       do if (D | 0) {
        s = c[t + 44 >> 2] | 0;
        p = c[Qb + 4 >> 2] | 0;
        q = c[bb >> 2] << 3;
        r = c[Qb + 16 >> 2] | 0;
        do if ((q - r | 0) > 31) {
         k = c[Ob >> 2] | 0;
         j = d[p + 1 >> 0] << 16 | d[p >> 0] << 24 | d[p + 2 >> 0] << 8 | d[p + 3 >> 0];
         if (!k) break;
         j = (d[p + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
        } else {
         if ((q - r | 0) <= 0) {
          j = 0;
          break;
         }
         k = c[Ob >> 2] | 0;
         j = d[p >> 0] << k + 24;
         if ((q - r + -8 + k | 0) > 0) {
          n = q - r + -8 + k | 0;
          k = k + 24 | 0;
          m = p;
         } else break;
         while (1) {
          m = m + 1 | 0;
          k = k + -8 | 0;
          j = d[m >> 0] << k | j;
          if ((n | 0) <= 8) break; else n = n + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = r + 1;
        o = r + 1 & 7;
        c[Ob >> 2] = o;
        if (q >>> 0 < (r + 1 | 0) >>> 0) {
         m = -1;
         k = p;
        } else {
         k = (c[Qb >> 2] | 0) + ((r + 1 | 0) >>> 3) | 0;
         c[Qb + 4 >> 2] = k;
         m = j >>> 31;
        }
        j = (m | 0) == -1;
        y : do if ((C | 0) == 5) {
         if (j) {
          Pb = 984;
          break;
         }
         c[e + 2632 >> 2] = m;
         do if ((q - (r + 1) | 0) > 31) {
          j = d[k + 1 >> 0] << 16 | d[k >> 0] << 24 | d[k + 2 >> 0] << 8 | d[k + 3 >> 0];
          if (!o) break;
          j = (d[k + 4 >> 0] | 0) >>> (8 - o | 0) | j << o;
         } else {
          if ((q - (r + 1) | 0) <= 0) {
           j = 0;
           break;
          }
          j = d[k >> 0] << (o | 24);
          if ((q - (r + 1) + -8 + o | 0) > 0) {
           n = q - (r + 1) + -8 + o | 0;
           m = o | 24;
          } else break;
          while (1) {
           k = k + 1 | 0;
           m = m + -8 | 0;
           j = d[k >> 0] << m | j;
           if ((n | 0) <= 8) break; else n = n + -8 | 0;
          }
         } while (0);
         c[Qb + 16 >> 2] = r + 2;
         c[Ob >> 2] = r + 2 & 7;
         if ((r + 2 | 0) >>> 0 > q >>> 0) {
          Pb = 984;
          break;
         }
         Pb = j >>> 31;
         c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((r + 2 | 0) >>> 3);
         c[e + 2636 >> 2] = Pb;
         if ((s | 0) != 0 | (Pb | 0) == 0) Pb = 985; else Pb = 984;
        } else {
         if (j) {
          Pb = 984;
          break;
         }
         c[e + 2640 >> 2] = m;
         if (!m) {
          Pb = 985;
          break;
         }
         k = 0;
         m = 0;
         n = 0;
         o = 0;
         p = 0;
         while (1) {
          if (p >>> 0 > ((s << 1) + 2 | 0) >>> 0) {
           Pb = 984;
           break y;
          }
          if (va(Qb, Qb + 648 | 0) | 0) {
           Pb = 984;
           break y;
          }
          q = c[Qb + 648 >> 2] | 0;
          if (q >>> 0 > 6) {
           Pb = 984;
           break y;
          }
          c[e + 2644 + (p * 20 | 0) >> 2] = q;
          if ((q | 2 | 0) == 3) {
           if (va(Qb, Qb + 688 | 0) | 0) {
            Pb = 984;
            break y;
           }
           c[e + 2644 + (p * 20 | 0) + 4 >> 2] = (c[Qb + 688 >> 2] | 0) + 1;
          }
          switch (q | 0) {
          case 2:
           {
            if (va(Qb, Qb + 688 | 0) | 0) {
             Pb = 984;
             break y;
            }
            c[e + 2644 + (p * 20 | 0) + 8 >> 2] = c[Qb + 688 >> 2];
            da = o;
            break;
           }
          case 3:
          case 6:
           {
            if (va(Qb, Qb + 688 | 0) | 0) {
             Pb = 984;
             break y;
            }
            c[e + 2644 + (p * 20 | 0) + 12 >> 2] = c[Qb + 688 >> 2];
            if ((q | 0) == 4) Pb = 978; else da = o;
            break;
           }
          case 4:
           {
            Pb = 978;
            break;
           }
          default:
           da = o;
          }
          if ((Pb | 0) == 978) {
           Pb = 0;
           if (va(Qb, Qb + 688 | 0) | 0) {
            Pb = 984;
            break y;
           }
           j = c[Qb + 688 >> 2] | 0;
           if (j >>> 0 > s >>> 0) {
            Pb = 984;
            break y;
           }
           c[e + 2644 + (p * 20 | 0) + 16 >> 2] = (j | 0) == 0 ? 65535 : j + -1 | 0;
           da = o + 1 | 0;
          }
          n = n + ((q | 0) == 5 & 1) | 0;
          k = k + ((q + -1 | 0) >>> 0 < 3 & 1) | 0;
          m = m + ((q | 0) == 6 & 1) | 0;
          if (!q) break; else {
           o = da;
           p = p + 1 | 0;
          }
         }
         if ((n | da | m) >>> 0 > 1) {
          Pb = 984;
          break;
         }
         if ((n | 0) != 0 & (k | 0) != 0) Pb = 984; else Pb = 985;
        } while (0);
        if ((Pb | 0) == 984) break v; else if ((Pb | 0) == 985) break;
       } while (0);
       c[Qb + 688 >> 2] = 0;
       j = va(Qb, Qb + 688 | 0) | 0;
       k = c[Qb + 688 >> 2] | 0;
       if ((k | 0) == -1) if (!j) Pb = 989; else ea = -2147483648; else if (!j) ea = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else Pb = 989;
       if ((Pb | 0) == 989) break;
       c[e + 2404 >> 2] = ea;
       if (((c[u + 52 >> 2] | 0) + ea | 0) >>> 0 > 51) break;
       z : do if (c[u + 60 >> 2] | 0) {
        if (va(Qb, Qb + 628 | 0) | 0) break v;
        j = c[Qb + 628 >> 2] | 0;
        c[e + 2408 >> 2] = j;
        if (j >>> 0 > 2) break v;
        if ((j | 0) == 1) break;
        c[Qb + 688 >> 2] = 0;
        k = va(Qb, Qb + 688 | 0) | 0;
        j = c[Qb + 688 >> 2] | 0;
        do if ((j | 0) == -1) {
         if (!k) break;
         break v;
        } else {
         j = j & 1 | 0 ? (j + 1 | 0) >>> 1 : 0 - ((j + 1 | 0) >>> 1) | 0;
         if (k | 0) break;
         if ((j + 6 | 0) >>> 0 > 12) break v;
         c[e + 2412 >> 2] = j << 1;
         c[Qb + 688 >> 2] = 0;
         k = va(Qb, Qb + 688 | 0) | 0;
         j = c[Qb + 688 >> 2] | 0;
         do if ((j | 0) == -1) {
          if (!k) break;
          break v;
         } else {
          j = j & 1 | 0 ? (j + 1 | 0) >>> 1 : 0 - ((j + 1 | 0) >>> 1) | 0;
          if (k | 0) break;
          if ((j + 6 | 0) >>> 0 > 12) break v;
          c[e + 2416 >> 2] = j << 1;
          break z;
         } while (0);
         break v;
        } while (0);
        break v;
       } while (0);
       do if ((c[u + 12 >> 2] | 0) >>> 0 > 1) {
        if (((c[u + 16 >> 2] | 0) + -3 | 0) >>> 0 >= 3) break;
        s = c[u + 36 >> 2] | 0;
        k = (((v >>> 0) % (s >>> 0) | 0 | 0) == 0 ? 1 : 2) + ((v >>> 0) / (s >>> 0) | 0) | 0;
        j = 0;
        while (1) {
         m = j + 1 | 0;
         if (!(-1 << m & k)) break; else j = m;
        }
        q = ((1 << j) + -1 & k | 0) == 0 ? j : m;
        n = c[Qb + 4 >> 2] | 0;
        p = c[bb >> 2] << 3;
        r = c[Qb + 16 >> 2] | 0;
        do if ((p - r | 0) > 31) {
         k = c[Ob >> 2] | 0;
         j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
         if (!k) break;
         j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
        } else {
         if ((p - r | 0) <= 0) {
          j = 0;
          break;
         }
         k = c[Ob >> 2] | 0;
         j = d[n >> 0] << k + 24;
         if ((p - r + -8 + k | 0) > 0) {
          o = p - r + -8 + k | 0;
          m = k + 24 | 0;
          k = n;
         } else break;
         while (1) {
          k = k + 1 | 0;
          m = m + -8 | 0;
          j = d[k >> 0] << m | j;
          if ((o | 0) <= 8) break; else o = o + -8 | 0;
         }
        } while (0);
        c[Qb + 16 >> 2] = r + q;
        c[Ob >> 2] = r + q & 7;
        if ((r + q | 0) >>> 0 > p >>> 0) {
         c[Qb + 628 >> 2] = -1;
         break v;
        }
        j = j >>> (32 - q | 0);
        c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((r + q | 0) >>> 3);
        c[Qb + 628 >> 2] = j;
        if ((j | 0) == -1) break v;
        c[e + 2420 >> 2] = j;
        if (j >>> 0 > (((v + -1 + s | 0) >>> 0) / (s >>> 0) | 0) >>> 0) break v;
       } while (0);
       if (!(c[e + 1188 >> 2] | 0)) {
        do if ((C | 0) != 5) {
         t = c[e + 2368 >> 2] | 0;
         u = (D | 0) != 0;
         fb = c[(c[e + 16 >> 2] | 0) + 48 >> 2] | 0;
         c[e + 1236 >> 2] = 0;
         c[e + 1240 >> 2] = 0;
         if (!fb) break;
         v = c[e + 1268 >> 2] | 0;
         do if ((v | 0) == (t | 0)) Pb = 1065; else {
          j = c[e + 1252 >> 2] | 0;
          if ((((v + 1 | 0) >>> 0) % (j >>> 0) | 0 | 0) == (t | 0)) {
           Pb = 1065;
           break;
          }
          w = c[(c[e + 1220 >> 2] | 0) + ((c[e + 1248 >> 2] | 0) * 40 | 0) >> 2] | 0;
          s = ((v + 1 | 0) >>> 0) % (j >>> 0) | 0;
          A : while (1) {
           n = c[e + 1260 >> 2] | 0;
           if (!n) o = 0; else {
            m = c[e + 1220 >> 2] | 0;
            k = 0;
            do {
             if (((c[m + (k * 40 | 0) + 20 >> 2] | 0) + -1 | 0) >>> 0 < 2) {
              Pb = c[m + (k * 40 | 0) + 12 >> 2] | 0;
              c[m + (k * 40 | 0) + 8 >> 2] = Pb - (Pb >>> 0 > s >>> 0 ? j : 0);
             }
             k = k + 1 | 0;
            } while ((k | 0) != (n | 0));
            o = n;
           }
           do if (o >>> 0 < (c[e + 1244 >> 2] | 0) >>> 0) j = n; else {
            if (!o) {
             fa = 3;
             Pb = 1869;
             break A;
            }
            n = c[e + 1220 >> 2] | 0;
            j = 0;
            k = -1;
            m = 0;
            do {
             if (((c[n + (m * 40 | 0) + 20 >> 2] | 0) + -1 | 0) >>> 0 < 2) {
              fb = c[n + (m * 40 | 0) + 8 >> 2] | 0;
              Pb = (k | 0) == -1 | (fb | 0) < (j | 0);
              j = Pb ? fb : j;
              k = Pb ? m : k;
             }
             m = m + 1 | 0;
            } while ((m | 0) != (o | 0));
            if ((k | 0) <= -1) {
             fa = 3;
             Pb = 1869;
             break A;
            }
            c[n + (k * 40 | 0) + 20 >> 2] = 0;
            j = o + -1 | 0;
            c[e + 1260 >> 2] = j;
            if (c[n + (k * 40 | 0) + 24 >> 2] | 0) break;
            c[e + 1264 >> 2] = (c[e + 1264 >> 2] | 0) + -1;
           } while (0);
           k = c[e + 1264 >> 2] | 0;
           r = c[e + 1248 >> 2] | 0;
           if (k >>> 0 < r >>> 0) m = c[e + 1220 >> 2] | 0; else {
            if (c[e + 1276 >> 2] | 0) {
             Pb = 1055;
             break;
            }
            q = c[e + 1220 >> 2] | 0;
            do {
             n = 2147483647;
             o = 0;
             m = 0;
             while (1) {
              if (!(c[q + (o * 40 | 0) + 24 >> 2] | 0)) {
               p = m;
               m = n;
              } else {
               Pb = c[q + (o * 40 | 0) + 16 >> 2] | 0;
               fb = (Pb | 0) < (n | 0);
               p = fb ? q + (o * 40 | 0) | 0 : m;
               m = fb ? Pb : n;
              }
              o = o + 1 | 0;
              if (o >>> 0 > r >>> 0) break; else {
               n = m;
               m = p;
              }
             }
             do if (p) {
              Pb = c[e + 1232 >> 2] | 0;
              m = c[e + 1236 >> 2] | 0;
              c[Pb + (m << 4) >> 2] = c[p >> 2];
              c[Pb + (m << 4) + 12 >> 2] = c[p + 36 >> 2];
              c[Pb + (m << 4) + 4 >> 2] = c[p + 28 >> 2];
              c[Pb + (m << 4) + 8 >> 2] = c[p + 32 >> 2];
              c[e + 1236 >> 2] = m + 1;
              c[p + 24 >> 2] = 0;
              m = k + -1 | 0;
              if (c[p + 20 >> 2] | 0) break;
              c[e + 1264 >> 2] = m;
              k = m;
             } while (0);
            } while (k >>> 0 >= r >>> 0);
            m = q;
           }
           c[m + (r * 40 | 0) + 20 >> 2] = 1;
           c[m + (r * 40 | 0) + 12 >> 2] = s;
           c[m + (r * 40 | 0) + 8 >> 2] = s;
           c[m + (r * 40 | 0) + 16 >> 2] = 0;
           c[m + (r * 40 | 0) + 24 >> 2] = 0;
           c[e + 1264 >> 2] = k + 1;
           c[e + 1260 >> 2] = j + 1;
           Ja(m, r + 1 | 0);
           j = c[e + 1252 >> 2] | 0;
           s = ((s + 1 | 0) >>> 0) % (j >>> 0) | 0;
           if ((s | 0) == (t | 0)) {
            Pb = 1057;
            break;
           }
          }
          if ((Pb | 0) == 1055) while (1) {} else if ((Pb | 0) == 1057) {
           k = c[e + 1236 >> 2] | 0;
           B : do if (k | 0) {
            m = c[e + 1232 >> 2] | 0;
            n = c[e + 1220 >> 2] | 0;
            o = c[e + 1248 >> 2] | 0;
            p = c[n + (o * 40 | 0) >> 2] | 0;
            j = 0;
            while (1) {
             if ((c[m + (j << 4) >> 2] | 0) == (p | 0)) break;
             j = j + 1 | 0;
             if (j >>> 0 >= k >>> 0) break B;
            }
            if (!o) break; else j = 0;
            while (1) {
             k = n + (j * 40 | 0) | 0;
             j = j + 1 | 0;
             if ((c[k >> 2] | 0) == (w | 0)) break;
             if (j >>> 0 >= o >>> 0) break B;
            }
            c[k >> 2] = p;
            c[n + (o * 40 | 0) >> 2] = w;
           } while (0);
           if (u) {
            ga = t;
            break;
           }
           ha = c[e + 1268 >> 2] | 0;
           Pb = 1069;
           break;
          } else if ((Pb | 0) == 1869) {
           l = Qb;
           return fa | 0;
          }
         } while (0);
         do if ((Pb | 0) == 1065) {
          if (!u) {
           ha = v;
           Pb = 1069;
           break;
          }
          if ((v | 0) == (t | 0)) fa = 3; else {
           ga = t;
           break;
          }
          l = Qb;
          return fa | 0;
         } while (0);
         if ((Pb | 0) == 1069) {
          if ((ha | 0) == (t | 0)) break;
          ga = c[e + 1252 >> 2] | 0;
          ga = ((t + -1 + ga | 0) >>> 0) % (ga >>> 0) | 0;
         }
         c[e + 1268 >> 2] = ga;
        } while (0);
        fb = (c[e + 1220 >> 2] | 0) + ((c[e + 1248 >> 2] | 0) * 40 | 0) | 0;
        c[e + 1228 >> 2] = fb;
        c[e + 1336 >> 2] = c[fb >> 2];
       }
       ob(e + 1368 | 0, e + 2356 | 0, 988) | 0;
       c[e + 1188 >> 2] = 1;
       c[e + 1360 >> 2] = C;
       c[e + 1360 + 4 >> 2] = D;
       j = c[e + 1432 >> 2] | 0;
       z = c[e + 1172 >> 2] | 0;
       m = c[e + 12 >> 2] | 0;
       x = c[e + 16 >> 2] | 0;
       y = c[x + 52 >> 2] | 0;
       x = c[x + 56 >> 2] | 0;
       t = N(x, y) | 0;
       s = c[m + 12 >> 2] | 0;
       C : do if ((s | 0) == 1) pb(z | 0, 0, t << 2 | 0) | 0; else {
        k = c[m + 16 >> 2] | 0;
        do if ((k + -3 | 0) >>> 0 < 3) {
         j = N(c[m + 36 >> 2] | 0, j) | 0;
         j = j >>> 0 < t >>> 0 ? j : t;
         if ((k & -2 | 0) != 4) {
          p = 0;
          w = j;
          break;
         }
         p = (c[m + 32 >> 2] | 0) == 0 ? j : t - j | 0;
         w = j;
        } else {
         p = 0;
         w = 0;
        } while (0);
        switch (k | 0) {
        case 0:
         {
          q = c[m + 20 >> 2] | 0;
          if (!s) {
           if (!t) break C;
           while (1) {}
          } else j = 0;
          do {
           if (j >>> 0 < t >>> 0) p = 0; else break C;
           do {
            o = q + (p << 2) | 0;
            k = c[o >> 2] | 0;
            D : do if (!k) k = 0; else {
             n = 0;
             do {
              m = n + j | 0;
              if (m >>> 0 >= t >>> 0) break D;
              c[z + (m << 2) >> 2] = p;
              n = n + 1 | 0;
              k = c[o >> 2] | 0;
             } while (n >>> 0 < k >>> 0);
            } while (0);
            p = p + 1 | 0;
            j = k + j | 0;
            k = j >>> 0 < t >>> 0;
           } while (p >>> 0 < s >>> 0 & k);
          } while (k);
          break;
         }
        case 1:
         {
          if (!t) break C; else j = 0;
          do {
           c[z + (j << 2) >> 2] = ((((N((j >>> 0) / (y >>> 0) | 0, s) | 0) >>> 1) + ((j >>> 0) % (y >>> 0) | 0) | 0) >>> 0) % (s >>> 0) | 0;
           j = j + 1 | 0;
          } while ((j | 0) != (t | 0));
          break;
         }
        case 2:
         {
          r = c[m + 24 >> 2] | 0;
          q = c[m + 28 >> 2] | 0;
          if (t | 0) {
           j = 0;
           do {
            c[z + (j << 2) >> 2] = s + -1;
            j = j + 1 | 0;
           } while ((j | 0) != (t | 0));
           if (!(s + -1 | 0)) break C;
          }
          o = s + -2 | 0;
          while (1) {
           m = c[r + (o << 2) >> 2] | 0;
           p = c[q + (o << 2) >> 2] | 0;
           E : do if (((m >>> 0) / (y >>> 0) | 0) >>> 0 <= ((p >>> 0) / (y >>> 0) | 0) >>> 0) {
            if (((m >>> 0) % (y >>> 0) | 0) >>> 0 > ((p >>> 0) % (y >>> 0) | 0) >>> 0) {
             j = (m >>> 0) / (y >>> 0) | 0;
             while (1) {
              j = j + 1 | 0;
              if (j >>> 0 > ((p >>> 0) / (y >>> 0) | 0) >>> 0) break E;
             }
            } else j = (m >>> 0) / (y >>> 0) | 0;
            do {
             n = N(j, y) | 0;
             k = (m >>> 0) % (y >>> 0) | 0;
             do {
              c[z + (k + n << 2) >> 2] = o;
              k = k + 1 | 0;
             } while (k >>> 0 <= ((p >>> 0) % (y >>> 0) | 0) >>> 0);
             j = j + 1 | 0;
            } while (j >>> 0 <= ((p >>> 0) / (y >>> 0) | 0) >>> 0);
           } while (0);
           if (!o) break; else o = o + -1 | 0;
          }
          break;
         }
        case 3:
         {
          v = c[m + 32 >> 2] | 0;
          if (t | 0) {
           j = 0;
           do {
            c[z + (j << 2) >> 2] = 1;
            j = j + 1 | 0;
           } while ((j | 0) != (t | 0));
          }
          if (!w) break C;
          s = (y - v | 0) >>> 1;
          t = 0;
          r = (x - v | 0) >>> 1;
          m = (y - v | 0) >>> 1;
          n = (x - v | 0) >>> 1;
          o = (y - v | 0) >>> 1;
          p = v;
          q = v + -1 | 0;
          k = (x - v | 0) >>> 1;
          while (1) {
           j = z + ((N(k, y) | 0) + s << 2) | 0;
           u = (c[j >> 2] | 0) == 1;
           if (u) c[j >> 2] = 0;
           do if ((q | 0) == -1 & (s | 0) == (o | 0)) {
            o = o + -1 | 0;
            o = (o | 0) > 0 ? o : 0;
            j = o;
            p = (v << 1) + -1 | 0;
            q = 0;
           } else {
            if ((q | 0) == 1 & (s | 0) == (m | 0)) {
             m = m + 1 | 0;
             m = (m | 0) < (y + -1 | 0) ? m : y + -1 | 0;
             j = m;
             p = 1 - (v << 1) | 0;
             q = 0;
             break;
            }
            if ((p | 0) == -1 & (k | 0) == (n | 0)) {
             n = n + -1 | 0;
             n = (n | 0) > 0 ? n : 0;
             k = n;
             j = s;
             p = 0;
             q = 1 - (v << 1) | 0;
             break;
            }
            if ((p | 0) == 1 & (k | 0) == (r | 0)) {
             k = r + 1 | 0;
             k = (k | 0) < (x + -1 | 0) ? k : x + -1 | 0;
             r = k;
             j = s;
             p = 0;
             q = (v << 1) + -1 | 0;
             break;
            } else {
             k = k + p | 0;
             j = s + q | 0;
             break;
            }
           } while (0);
           t = t + (u & 1) | 0;
           if (t >>> 0 >= w >>> 0) break; else s = j;
          }
          break;
         }
        case 4:
         {
          k = c[m + 32 >> 2] | 0;
          if (!t) break C;
          j = 0;
          do {
           c[z + (j << 2) >> 2] = j >>> 0 < p >>> 0 ? k : 1 - k | 0;
           j = j + 1 | 0;
          } while ((j | 0) != (t | 0));
          break;
         }
        case 5:
         {
          o = c[m + 32 >> 2] | 0;
          if (!y) break C;
          if (!x) break C; else {
           j = 0;
           m = 0;
          }
          while (1) {
           k = 0;
           n = m;
           while (1) {
            c[z + ((N(k, y) | 0) + j << 2) >> 2] = n >>> 0 < p >>> 0 ? o : 1 - o | 0;
            k = k + 1 | 0;
            if ((k | 0) == (x | 0)) break; else n = n + 1 | 0;
           }
           j = j + 1 | 0;
           if ((j | 0) == (y | 0)) break; else m = m + x | 0;
          }
          break;
         }
        default:
         {
          if (!t) break C;
          k = c[m + 44 >> 2] | 0;
          j = 0;
          do {
           c[z + (j << 2) >> 2] = c[k + (j << 2) >> 2];
           j = j + 1 | 0;
          } while ((j | 0) != (t | 0));
         }
        }
       } while (0);
       o = c[e + 1260 >> 2] | 0;
       do if (!o) {
        m = c[e + 1380 >> 2] | 0;
        p = c[e + 1412 >> 2] | 0;
        A = e + 1412 | 0;
       } else {
        j = 0;
        do {
         c[(c[e + 1224 >> 2] | 0) + (j << 2) >> 2] = (c[e + 1220 >> 2] | 0) + (j * 40 | 0);
         j = j + 1 | 0;
        } while ((j | 0) != (o | 0));
        m = c[e + 1380 >> 2] | 0;
        p = c[e + 1412 >> 2] | 0;
        if (!o) {
         A = e + 1412 | 0;
         break;
        }
        n = c[e + 1220 >> 2] | 0;
        k = 0;
        do {
         if (((c[n + (k * 40 | 0) + 20 >> 2] | 0) + -1 | 0) >>> 0 < 2) {
          j = c[n + (k * 40 | 0) + 12 >> 2] | 0;
          if (j >>> 0 > m >>> 0) j = j - (c[e + 1252 >> 2] | 0) | 0;
          c[n + (k * 40 | 0) + 8 >> 2] = j;
         }
         k = k + 1 | 0;
        } while ((k | 0) != (o | 0));
        A = e + 1412 | 0;
       } while (0);
       F : do if (c[e + 1436 >> 2] | 0) {
        k = c[e + 1440 >> 2] | 0;
        if (k >>> 0 >= 3) break;
        s = 0;
        j = m;
        G : while (1) {
         H : do if ((k | 0) == 2) {
          n = c[e + 1440 + (s * 12 | 0) + 8 >> 2] | 0;
          o = c[e + 1244 >> 2] | 0;
          if (!o) {
           fa = 3;
           Pb = 1869;
           break G;
          }
          k = c[e + 1220 >> 2] | 0;
          q = 0;
          while (1) {
           if ((c[k + (q * 40 | 0) + 20 >> 2] | 0) == 3) if ((c[k + (q * 40 | 0) + 8 >> 2] | 0) == (n | 0)) {
            n = 3;
            break H;
           }
           q = q + 1 | 0;
           if (q >>> 0 >= o >>> 0) {
            fa = 3;
            Pb = 1869;
            break G;
           }
          }
         } else {
          n = c[e + 1440 + (s * 12 | 0) + 4 >> 2] | 0;
          do if (!k) {
           j = j - n | 0;
           if ((j | 0) >= 0) break;
           j = (c[e + 1252 >> 2] | 0) + j | 0;
          } else {
           fb = n + j | 0;
           j = c[e + 1252 >> 2] | 0;
           j = fb - ((fb | 0) < (j | 0) ? 0 : j) | 0;
          } while (0);
          if (j >>> 0 > m >>> 0) n = j - (c[e + 1252 >> 2] | 0) | 0; else n = j;
          o = c[e + 1244 >> 2] | 0;
          if (!o) {
           fa = 3;
           Pb = 1869;
           break G;
          }
          k = c[e + 1220 >> 2] | 0;
          q = 0;
          while (1) {
           r = c[k + (q * 40 | 0) + 20 >> 2] | 0;
           if ((r + -1 | 0) >>> 0 < 2) if ((c[k + (q * 40 | 0) + 8 >> 2] | 0) == (n | 0)) {
            n = r;
            break H;
           }
           q = q + 1 | 0;
           if (q >>> 0 >= o >>> 0) {
            fa = 3;
            Pb = 1869;
            break G;
           }
          }
         } while (0);
         if (!(n >>> 0 > 1 & (q | 0) > -1)) {
          fa = 3;
          Pb = 1869;
          break;
         }
         if (s >>> 0 < p >>> 0) {
          k = p;
          do {
           eb = c[e + 1224 >> 2] | 0;
           fb = k;
           k = k + -1 | 0;
           c[eb + (fb << 2) >> 2] = c[eb + (k << 2) >> 2];
          } while (k >>> 0 > s >>> 0);
          k = c[e + 1220 >> 2] | 0;
         }
         c[(c[e + 1224 >> 2] | 0) + (s << 2) >> 2] = k + (q * 40 | 0);
         s = s + 1 | 0;
         if (s >>> 0 <= p >>> 0) {
          k = s;
          r = s;
          do {
           n = c[e + 1224 >> 2] | 0;
           o = c[n + (r << 2) >> 2] | 0;
           if ((o | 0) != ((c[e + 1220 >> 2] | 0) + (q * 40 | 0) | 0)) {
            c[n + (k << 2) >> 2] = o;
            k = k + 1 | 0;
           }
           r = r + 1 | 0;
          } while (r >>> 0 <= p >>> 0);
         }
         k = c[e + 1440 + (s * 12 | 0) >> 2] | 0;
         if (k >>> 0 >= 3) break F;
        }
        if ((Pb | 0) == 1869) {
         l = Qb;
         return fa | 0;
        }
       } while (0);
       z = c[e + 3376 >> 2] | 0;
       x = c[e + 1368 >> 2] | 0;
       c[Qb + 192 >> 2] = 0;
       c[e + 1192 >> 2] = (c[e + 1192 >> 2] | 0) + 1;
       c[e + 1200 >> 2] = 0;
       c[Qb + 188 >> 2] = (c[e + 1416 >> 2] | 0) + (c[(c[e + 12 >> 2] | 0) + 52 >> 2] | 0);
       y = 0;
       k = 0;
       p = c[e + 1212 >> 2] | 0;
       n = 0;
       I : while (1) {
        if (!(c[e + 1404 >> 2] | 0)) if (c[p + (x * 216 | 0) + 196 >> 2] | 0) {
         Ba = 1;
         break;
        }
        m = c[(c[e + 12 >> 2] | 0) + 56 >> 2] | 0;
        db = c[e + 1420 >> 2] | 0;
        eb = c[e + 1424 >> 2] | 0;
        fb = c[e + 1428 >> 2] | 0;
        c[p + (x * 216 | 0) + 4 >> 2] = c[e + 1192 >> 2];
        c[p + (x * 216 | 0) + 8 >> 2] = db;
        c[p + (x * 216 | 0) + 12 >> 2] = eb;
        c[p + (x * 216 | 0) + 16 >> 2] = fb;
        c[p + (x * 216 | 0) + 24 >> 2] = m;
        m = c[e + 1372 >> 2] | 0;
        do if ((m | 0) == 2) Pb = 1178; else {
         if ((k | 0) != 0 | (m | 0) == 7) {
          Pb = 1178;
          break;
         }
         j = va(Qb, Qb + 192 | 0) | 0;
         if (j | 0) {
          Ba = j;
          break I;
         }
         j = c[Qb + 192 >> 2] | 0;
         if (j >>> 0 > ((c[e + 1176 >> 2] | 0) - x | 0) >>> 0) {
          Ba = 1;
          break I;
         }
         if (!j) {
          Va = c[e + 1212 >> 2] | 0;
          Wa = c[e + 1372 >> 2] | 0;
          Pb = 1180;
          break;
         } else {
          pb(z + 12 | 0, 0, 164) | 0;
          c[z >> 2] = 0;
          Ra = 1;
          Ua = j;
          Pb = 1179;
          break;
         }
        } while (0);
        if ((Pb | 0) == 1178) if (!n) {
         Va = p;
         Wa = m;
         Pb = 1180;
        } else {
         Ra = k;
         Ua = n;
         Pb = 1179;
        }
        if ((Pb | 0) == 1179) {
         Pb = 0;
         qa = Ua + -1 | 0;
         c[Qb + 192 >> 2] = qa;
         pa = Ra;
        } else if ((Pb | 0) == 1180) {
         Pb = 0;
         w = Va + (x * 216 | 0) | 0;
         t = c[A >> 2] | 0;
         pb(z | 0, 0, 2088) | 0;
         j = va(Qb, Qb + 628 | 0) | 0;
         k = c[Qb + 628 >> 2] | 0;
         switch (Wa | 0) {
         case 2:
         case 7:
          {
           if ((j | 0) != 0 | (k + 6 | 0) >>> 0 > 31) {
            ab = 1;
            Pb = 1450;
            break I;
           } else u = k + 6 | 0;
           break;
          }
         default:
          if ((j | 0) != 0 | (k + 1 | 0) >>> 0 > 31) {
           ab = 1;
           Pb = 1450;
           break I;
          } else u = k + 1 | 0;
         }
         c[z >> 2] = u;
         do if ((u | 0) == 31) {
          k = c[Ob >> 2] | 0;
          while (1) {
           m = c[Qb + 4 >> 2] | 0;
           if (!k) {
            q = z + 328 | 0;
            r = 0;
            break;
           }
           o = c[bb >> 2] << 3;
           p = c[Qb + 16 >> 2] | 0;
           do if ((o - p | 0) > 31) j = (d[m + 4 >> 0] | 0) >>> (8 - k | 0) | (d[m + 1 >> 0] << 16 | d[m >> 0] << 24 | d[m + 2 >> 0] << 8 | d[m + 3 >> 0]) << k; else {
            if ((o - p | 0) <= 0) {
             j = 0;
             break;
            }
            n = k + 24 | 0;
            j = d[m >> 0] << n;
            k = o - p + -8 + k | 0;
            if ((k | 0) <= 0) break;
            while (1) {
             m = m + 1 | 0;
             n = n + -8 | 0;
             j = d[m >> 0] << n | j;
             if ((k | 0) <= 8) break; else k = k + -8 | 0;
            }
           } while (0);
           c[Qb + 16 >> 2] = p + 1;
           k = p + 1 & 7;
           c[Ob >> 2] = k;
           if ((p + 1 | 0) >>> 0 > o >>> 0) {
            ab = 1;
            Pb = 1450;
            break I;
           }
           c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((p + 1 | 0) >>> 3);
           if ((j | 0) <= -1) {
            ab = 1;
            Pb = 1450;
            break I;
           }
          }
          while (1) {
           o = c[bb >> 2] << 3;
           p = c[Qb + 16 >> 2] | 0;
           do if ((o - p | 0) > 31) {
            k = c[Ob >> 2] | 0;
            j = d[m + 1 >> 0] << 16 | d[m >> 0] << 24 | d[m + 2 >> 0] << 8 | d[m + 3 >> 0];
            if (!k) break;
            j = (d[m + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
           } else {
            if ((o - p | 0) <= 0) {
             j = 0;
             break;
            }
            k = c[Ob >> 2] | 0;
            j = d[m >> 0] << k + 24;
            if ((o - p + -8 + k | 0) > 0) {
             n = o - p + -8 + k | 0;
             k = k + 24 | 0;
            } else break;
            while (1) {
             m = m + 1 | 0;
             k = k + -8 | 0;
             j = d[m >> 0] << k | j;
             if ((n | 0) <= 8) break; else n = n + -8 | 0;
            }
           } while (0);
           c[Qb + 16 >> 2] = p + 8;
           c[Ob >> 2] = p + 8 & 7;
           if ((p + 8 | 0) >>> 0 > o >>> 0) {
            Pb = 1432;
            break I;
           }
           j = j >>> 24;
           m = (c[Qb >> 2] | 0) + ((p + 8 | 0) >>> 3) | 0;
           c[Qb + 4 >> 2] = m;
           c[q >> 2] = j;
           r = r + 1 | 0;
           if (r >>> 0 >= 384) break; else q = q + 4 | 0;
          }
          c[Qb + 628 >> 2] = j;
         } else {
          j = u >>> 0 < 6;
          v = (u | 0) != 6;
          if (u >>> 0 < 4 | j ^ 1) {
           J : do switch ((j ? 2 : v & 1) & 3) {
           case 2:
            {
             K : do if (t >>> 0 > 1) {
              switch (u | 0) {
              case 0:
              case 1:
               {
                k = 0;
                break;
               }
              case 3:
              case 2:
               {
                k = 1;
                break;
               }
              default:
               k = 3;
              }
              if (t >>> 0 >= 3) {
               m = 0;
               while (1) {
                if (va(Qb, Qb + 648 | 0) | 0) {
                 Aa = 1;
                 break J;
                }
                j = c[Qb + 648 >> 2] | 0;
                if (j >>> 0 >= t >>> 0) {
                 Aa = 1;
                 break J;
                }
                c[z + 144 + (m << 2) >> 2] = j;
                if (!k) break K; else {
                 m = m + 1 | 0;
                 k = k + -1 | 0;
                }
               }
              }
              r = c[bb >> 2] | 0;
              q = 0;
              s = c[Qb + 16 >> 2] | 0;
              p = c[Qb + 4 >> 2] | 0;
              while (1) {
               m = (r << 3) - s | 0;
               do if ((m | 0) > 31) {
                m = c[Ob >> 2] | 0;
                j = d[p + 1 >> 0] << 16 | d[p >> 0] << 24 | d[p + 2 >> 0] << 8 | d[p + 3 >> 0];
                if (!m) break;
                j = (d[p + 4 >> 0] | 0) >>> (8 - m | 0) | j << m;
               } else {
                if ((m | 0) <= 0) {
                 j = 0;
                 break;
                }
                n = c[Ob >> 2] | 0;
                j = d[p >> 0] << n + 24;
                if ((m + -8 + n | 0) > 0) {
                 o = m + -8 + n | 0;
                 n = n + 24 | 0;
                 m = p;
                } else break;
                while (1) {
                 m = m + 1 | 0;
                 n = n + -8 | 0;
                 j = d[m >> 0] << n | j;
                 if ((o | 0) <= 8) break; else o = o + -8 | 0;
                }
               } while (0);
               s = s + 1 | 0;
               c[Qb + 16 >> 2] = s;
               c[Ob >> 2] = s & 7;
               if (s >>> 0 > r << 3 >>> 0) {
                Ta = -1;
                Pb = 1380;
                break;
               }
               p = (c[Qb >> 2] | 0) + (s >>> 3) | 0;
               c[Qb + 4 >> 2] = p;
               Xa = j >>> 31 ^ 1;
               if (Xa >>> 0 >= t >>> 0) {
                Ta = Xa;
                Pb = 1380;
                break;
               }
               c[z + 144 + (q << 2) >> 2] = Xa;
               if (!k) {
                Pb = 1340;
                break;
               } else {
                q = q + 1 | 0;
                k = k + -1 | 0;
               }
              }
              if ((Pb | 0) == 1340) {
               Pb = 0;
               c[Qb + 648 >> 2] = Xa;
               break;
              } else if ((Pb | 0) == 1380) {
               Pb = 0;
               c[Qb + 648 >> 2] = Ta;
               Aa = 1;
               break J;
              }
             } while (0);
             switch (u | 0) {
             case 0:
             case 1:
              {
               m = 0;
               n = 0;
               break;
              }
             case 3:
             case 2:
              {
               m = 0;
               n = 1;
               break;
              }
             default:
              {
               m = 0;
               n = 3;
              }
             }
             while (1) {
              c[Qb + 688 >> 2] = 0;
              j = va(Qb, Qb + 688 | 0) | 0;
              k = c[Qb + 688 >> 2] | 0;
              if ((k | 0) == -1) if (!j) {
               Pb = 1347;
               break;
              } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
               Pb = 1347;
               break;
              }
              b[z + 160 + (m << 2) >> 1] = j;
              c[Qb + 688 >> 2] = 0;
              j = va(Qb, Qb + 688 | 0) | 0;
              k = c[Qb + 688 >> 2] | 0;
              if ((k | 0) == -1) if (!j) {
               Pb = 1351;
               break;
              } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
               Pb = 1351;
               break;
              }
              b[z + 160 + (m << 2) + 2 >> 1] = j;
              if (!n) {
               Aa = 0;
               break J;
              } else {
               m = m + 1 | 0;
               n = n + -1 | 0;
              }
             }
             if ((Pb | 0) == 1347) {
              Pb = 0;
              Aa = 1;
              break J;
             } else if ((Pb | 0) == 1351) {
              Pb = 0;
              Aa = 1;
              break J;
             }
             break;
            }
           case 0:
            {
             o = c[Qb + 4 >> 2] | 0;
             k = (c[bb >> 2] << 3) - (c[Qb + 16 >> 2] | 0) | 0;
             do if ((k | 0) > 31) {
              j = c[Ob >> 2] | 0;
              k = d[o + 1 >> 0] << 16 | d[o >> 0] << 24 | d[o + 2 >> 0] << 8 | d[o + 3 >> 0];
              if (!j) {
               ya = k;
               Pb = 1321;
               break;
              }
              ya = (d[o + 4 >> 0] | 0) >>> (8 - j | 0) | k << j;
              Pb = 1321;
             } else {
              if ((k | 0) <= 0) {
               c[z + 12 >> 2] = 0;
               Ca = 0;
               Pb = 1353;
               break;
              }
              m = c[Ob >> 2] | 0;
              j = d[o >> 0] << m + 24;
              if ((k + -8 + m | 0) > 0) {
               n = k + -8 + m | 0;
               m = m + 24 | 0;
               k = o;
              } else {
               ya = j;
               Pb = 1321;
               break;
              }
              while (1) {
               k = k + 1 | 0;
               m = m + -8 | 0;
               j = d[k >> 0] << m | j;
               if ((n | 0) <= 8) {
                ya = j;
                Pb = 1321;
                break;
               } else n = n + -8 | 0;
              }
             } while (0);
             if ((Pb | 0) == 1321) {
              Pb = 0;
              fb = ya >>> 31;
              c[z + 12 >> 2] = fb;
              if (!fb) {
               Ca = ya;
               Pb = 1353;
              } else {
               Ka = 0;
               Ya = ya << 1;
              }
             }
             if ((Pb | 0) == 1353) {
              Pb = 0;
              c[z + 76 >> 2] = Ca >>> 28 & 7;
              Ka = 1;
              Ya = Ca << 4;
             }
             fb = Ya >>> 31;
             c[z + 16 >> 2] = fb;
             if (!fb) {
              c[z + 80 >> 2] = Ya >>> 28 & 7;
              j = Ka + 1 | 0;
              k = Ya << 4;
             } else {
              j = Ka;
              k = Ya << 1;
             }
             fb = k >>> 31;
             c[z + 20 >> 2] = fb;
             if (!fb) {
              c[z + 84 >> 2] = k >>> 28 & 7;
              j = j + 1 | 0;
              k = k << 4;
             } else k = k << 1;
             fb = k >>> 31;
             c[z + 24 >> 2] = fb;
             if (!fb) {
              c[z + 88 >> 2] = k >>> 28 & 7;
              j = j + 1 | 0;
              k = k << 4;
             } else k = k << 1;
             fb = k >>> 31;
             c[z + 28 >> 2] = fb;
             if (!fb) {
              c[z + 92 >> 2] = k >>> 28 & 7;
              j = j + 1 | 0;
              k = k << 4;
             } else k = k << 1;
             fb = k >>> 31;
             c[z + 32 >> 2] = fb;
             if (!fb) {
              c[z + 96 >> 2] = k >>> 28 & 7;
              j = j + 1 | 0;
              k = k << 4;
             } else k = k << 1;
             fb = k >>> 31;
             c[z + 36 >> 2] = fb;
             if (!fb) {
              c[z + 100 >> 2] = k >>> 28 & 7;
              j = j + 1 | 0;
              m = k << 4;
             } else m = k << 1;
             fb = m >>> 31;
             c[z + 40 >> 2] = fb;
             if (!fb) {
              c[z + 104 >> 2] = m >>> 28 & 7;
              k = j + 1 | 0;
              j = m << 4;
             } else {
              k = j;
              j = m << 1;
             }
             o = (k * 3 | 0) + 8 + (c[Qb + 16 >> 2] | 0) | 0;
             c[Qb + 16 >> 2] = o;
             c[Ob >> 2] = o & 7;
             q = c[bb >> 2] << 3;
             do if (q >>> 0 >= o >>> 0) {
              p = c[Qb >> 2] | 0;
              c[Qb + 4 >> 2] = p + (o >>> 3);
              do if ((q - o | 0) > 31) {
               j = d[p + (o >>> 3) + 1 >> 0] << 16 | d[p + (o >>> 3) >> 0] << 24 | d[p + (o >>> 3) + 2 >> 0] << 8 | d[p + (o >>> 3) + 3 >> 0];
               if (!(o & 7)) {
                za = j;
                Pb = 1362;
                break;
               }
               za = (d[p + (o >>> 3) + 4 >> 0] | 0) >>> (8 - (o & 7) | 0) | j << (o & 7);
               Pb = 1362;
              } else {
               if ((q - o | 0) <= 0) {
                c[z + 44 >> 2] = 0;
                Da = 0;
                Pb = 1433;
                break;
               }
               j = d[p + (o >>> 3) >> 0] << (o & 7 | 24);
               if ((q - o + -8 + (o & 7) | 0) > 0) {
                k = q - o + -8 + (o & 7) | 0;
                m = o & 7 | 24;
                n = p + (o >>> 3) | 0;
               } else {
                za = j;
                Pb = 1362;
                break;
               }
               while (1) {
                n = n + 1 | 0;
                m = m + -8 | 0;
                j = d[n >> 0] << m | j;
                if ((k | 0) <= 8) {
                 za = j;
                 Pb = 1362;
                 break;
                } else k = k + -8 | 0;
               }
              } while (0);
              if ((Pb | 0) == 1362) {
               Pb = 0;
               fb = za >>> 31;
               c[z + 44 >> 2] = fb;
               if (!fb) {
                Da = za;
                Pb = 1433;
               } else {
                Ia = 0;
                Za = za << 1;
               }
              }
              if ((Pb | 0) == 1433) {
               Pb = 0;
               c[z + 108 >> 2] = Da >>> 28 & 7;
               Ia = 1;
               Za = Da << 4;
              }
              fb = Za >>> 31;
              c[z + 48 >> 2] = fb;
              if (!fb) {
               c[z + 112 >> 2] = Za >>> 28 & 7;
               j = Ia + 1 | 0;
               k = Za << 4;
              } else {
               j = Ia;
               k = Za << 1;
              }
              fb = k >>> 31;
              c[z + 52 >> 2] = fb;
              if (!fb) {
               c[z + 116 >> 2] = k >>> 28 & 7;
               j = j + 1 | 0;
               k = k << 4;
              } else k = k << 1;
              fb = k >>> 31;
              c[z + 56 >> 2] = fb;
              if (!fb) {
               c[z + 120 >> 2] = k >>> 28 & 7;
               j = j + 1 | 0;
               k = k << 4;
              } else k = k << 1;
              fb = k >>> 31;
              c[z + 60 >> 2] = fb;
              if (!fb) {
               c[z + 124 >> 2] = k >>> 28 & 7;
               j = j + 1 | 0;
               k = k << 4;
              } else k = k << 1;
              fb = k >>> 31;
              c[z + 64 >> 2] = fb;
              if (!fb) {
               c[z + 128 >> 2] = k >>> 28 & 7;
               j = j + 1 | 0;
               k = k << 4;
              } else k = k << 1;
              fb = k >>> 31;
              c[z + 68 >> 2] = fb;
              if (!fb) {
               c[z + 132 >> 2] = k >>> 28 & 7;
               j = j + 1 | 0;
               m = k << 4;
              } else m = k << 1;
              fb = m >>> 31;
              c[z + 72 >> 2] = fb;
              if (!fb) {
               c[z + 136 >> 2] = m >>> 28 & 7;
               k = j + 1 | 0;
               j = m << 4;
              } else {
               k = j;
               j = m << 1;
              }
              k = (k * 3 | 0) + 8 + o | 0;
              c[Qb + 16 >> 2] = k;
              c[Ob >> 2] = k & 7;
              if (k >>> 0 > q >>> 0) break;
              c[Qb + 4 >> 2] = p + (k >>> 3);
              c[Qb + 648 >> 2] = j;
              Pb = 1363;
              break J;
             } while (0);
             c[Qb + 648 >> 2] = j;
             Aa = 1;
             break;
            }
           case 1:
            {
             Pb = 1363;
             break;
            }
           default:
            Aa = 0;
           } while (0);
           do if ((Pb | 0) == 1363) {
            Pb = 0;
            fb = (va(Qb, Qb + 648 | 0) | 0) != 0;
            j = c[Qb + 648 >> 2] | 0;
            if (fb | j >>> 0 > 3) {
             Aa = 1;
             break;
            }
            c[z + 140 >> 2] = j;
            Aa = 0;
           } while (0);
           j = Aa;
          } else {
           fb = (va(Qb, Qb + 648 | 0) | 0) != 0;
           j = c[Qb + 648 >> 2] | 0;
           L : do if (fb | j >>> 0 > 3) Ea = 1; else {
            c[z + 176 >> 2] = j;
            fb = (va(Qb, Qb + 648 | 0) | 0) != 0;
            j = c[Qb + 648 >> 2] | 0;
            if (fb | j >>> 0 > 3) {
             Ea = 1;
             break;
            }
            c[z + 180 >> 2] = j;
            fb = (va(Qb, Qb + 648 | 0) | 0) != 0;
            j = c[Qb + 648 >> 2] | 0;
            if (fb | j >>> 0 > 3) {
             Ea = 1;
             break;
            }
            c[z + 184 >> 2] = j;
            fb = (va(Qb, Qb + 648 | 0) | 0) != 0;
            j = c[Qb + 648 >> 2] | 0;
            if (fb | j >>> 0 > 3) {
             Ea = 1;
             break;
            }
            c[z + 188 >> 2] = j;
            if (t >>> 0 > 1 & (u | 0) != 5) {
             do if (t >>> 0 < 3) {
              n = c[Qb + 4 >> 2] | 0;
              p = c[bb >> 2] << 3;
              q = c[Qb + 16 >> 2] | 0;
              do if ((p - q | 0) > 31) {
               k = c[Ob >> 2] | 0;
               j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
               if (!k) break;
               j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
              } else {
               if ((p - q | 0) <= 0) {
                j = 0;
                break;
               }
               k = c[Ob >> 2] | 0;
               j = d[n >> 0] << k + 24;
               if ((p - q + -8 + k | 0) > 0) {
                o = p - q + -8 + k | 0;
                m = k + 24 | 0;
                k = n;
               } else break;
               while (1) {
                k = k + 1 | 0;
                m = m + -8 | 0;
                j = d[k >> 0] << m | j;
                if ((o | 0) <= 8) break; else o = o + -8 | 0;
               }
              } while (0);
              c[Qb + 16 >> 2] = q + 1;
              c[Ob >> 2] = q + 1 & 7;
              if ((q + 1 | 0) >>> 0 > p >>> 0) {
               c[Qb + 648 >> 2] = -1;
               Ea = 1;
               break L;
              } else {
               c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
               j = j >>> 31 ^ 1;
               c[Qb + 648 >> 2] = j;
               break;
              }
             } else {
              if (va(Qb, Qb + 648 | 0) | 0) {
               Ea = 1;
               break L;
              }
              j = c[Qb + 648 >> 2] | 0;
             } while (0);
             if (j >>> 0 >= t >>> 0) {
              Ea = 1;
              break;
             }
             c[z + 192 >> 2] = j;
             do if (t >>> 0 < 3) {
              n = c[Qb + 4 >> 2] | 0;
              p = c[bb >> 2] << 3;
              q = c[Qb + 16 >> 2] | 0;
              do if ((p - q | 0) > 31) {
               k = c[Ob >> 2] | 0;
               j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
               if (!k) break;
               j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
              } else {
               if ((p - q | 0) <= 0) {
                j = 0;
                break;
               }
               k = c[Ob >> 2] | 0;
               j = d[n >> 0] << k + 24;
               if ((p - q + -8 + k | 0) > 0) {
                o = p - q + -8 + k | 0;
                m = k + 24 | 0;
                k = n;
               } else break;
               while (1) {
                k = k + 1 | 0;
                m = m + -8 | 0;
                j = d[k >> 0] << m | j;
                if ((o | 0) <= 8) break; else o = o + -8 | 0;
               }
              } while (0);
              c[Qb + 16 >> 2] = q + 1;
              c[Ob >> 2] = q + 1 & 7;
              if ((q + 1 | 0) >>> 0 > p >>> 0) {
               c[Qb + 648 >> 2] = -1;
               Ea = 1;
               break L;
              } else {
               c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
               j = j >>> 31 ^ 1;
               c[Qb + 648 >> 2] = j;
               break;
              }
             } else {
              if (va(Qb, Qb + 648 | 0) | 0) {
               Ea = 1;
               break L;
              }
              j = c[Qb + 648 >> 2] | 0;
             } while (0);
             if (j >>> 0 >= t >>> 0) {
              Ea = 1;
              break;
             }
             c[z + 196 >> 2] = j;
             do if (t >>> 0 < 3) {
              n = c[Qb + 4 >> 2] | 0;
              p = c[bb >> 2] << 3;
              q = c[Qb + 16 >> 2] | 0;
              do if ((p - q | 0) > 31) {
               k = c[Ob >> 2] | 0;
               j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
               if (!k) break;
               j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
              } else {
               if ((p - q | 0) <= 0) {
                j = 0;
                break;
               }
               k = c[Ob >> 2] | 0;
               j = d[n >> 0] << k + 24;
               if ((p - q + -8 + k | 0) > 0) {
                o = p - q + -8 + k | 0;
                m = k + 24 | 0;
                k = n;
               } else break;
               while (1) {
                k = k + 1 | 0;
                m = m + -8 | 0;
                j = d[k >> 0] << m | j;
                if ((o | 0) <= 8) break; else o = o + -8 | 0;
               }
              } while (0);
              c[Qb + 16 >> 2] = q + 1;
              c[Ob >> 2] = q + 1 & 7;
              if ((q + 1 | 0) >>> 0 > p >>> 0) {
               c[Qb + 648 >> 2] = -1;
               Ea = 1;
               break L;
              } else {
               c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
               j = j >>> 31 ^ 1;
               c[Qb + 648 >> 2] = j;
               break;
              }
             } else {
              if (va(Qb, Qb + 648 | 0) | 0) {
               Ea = 1;
               break L;
              }
              j = c[Qb + 648 >> 2] | 0;
             } while (0);
             if (j >>> 0 >= t >>> 0) {
              Ea = 1;
              break;
             }
             c[z + 200 >> 2] = j;
             do if (t >>> 0 < 3) {
              n = c[Qb + 4 >> 2] | 0;
              p = c[bb >> 2] << 3;
              q = c[Qb + 16 >> 2] | 0;
              do if ((p - q | 0) > 31) {
               k = c[Ob >> 2] | 0;
               j = d[n + 1 >> 0] << 16 | d[n >> 0] << 24 | d[n + 2 >> 0] << 8 | d[n + 3 >> 0];
               if (!k) break;
               j = (d[n + 4 >> 0] | 0) >>> (8 - k | 0) | j << k;
              } else {
               if ((p - q | 0) <= 0) {
                j = 0;
                break;
               }
               k = c[Ob >> 2] | 0;
               j = d[n >> 0] << k + 24;
               if ((p - q + -8 + k | 0) > 0) {
                o = p - q + -8 + k | 0;
                m = k + 24 | 0;
                k = n;
               } else break;
               while (1) {
                k = k + 1 | 0;
                m = m + -8 | 0;
                j = d[k >> 0] << m | j;
                if ((o | 0) <= 8) break; else o = o + -8 | 0;
               }
              } while (0);
              c[Qb + 16 >> 2] = q + 1;
              c[Ob >> 2] = q + 1 & 7;
              if ((q + 1 | 0) >>> 0 > p >>> 0) {
               c[Qb + 648 >> 2] = -1;
               Ea = 1;
               break L;
              } else {
               c[Qb + 4 >> 2] = (c[Qb >> 2] | 0) + ((q + 1 | 0) >>> 3);
               j = j >>> 31 ^ 1;
               c[Qb + 648 >> 2] = j;
               break;
              }
             } else {
              if (va(Qb, Qb + 648 | 0) | 0) {
               Ea = 1;
               break L;
              }
              j = c[Qb + 648 >> 2] | 0;
             } while (0);
             if (j >>> 0 >= t >>> 0) {
              Ea = 1;
              break;
             }
             c[z + 204 >> 2] = j;
            }
            switch (c[z + 176 >> 2] | 0) {
            case 0:
             {
              j = 0;
              break;
             }
            case 2:
            case 1:
             {
              j = 1;
              break;
             }
            default:
             j = 3;
            }
            c[Qb + 648 >> 2] = j;
            m = 0;
            while (1) {
             c[Qb + 688 >> 2] = 0;
             j = va(Qb, Qb + 688 | 0) | 0;
             k = c[Qb + 688 >> 2] | 0;
             if ((k | 0) == -1) if (!j) {
              Pb = 1236;
              break;
             } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
              Pb = 1236;
              break;
             }
             b[z + 208 + (m << 2) >> 1] = j;
             c[Qb + 688 >> 2] = 0;
             j = va(Qb, Qb + 688 | 0) | 0;
             k = c[Qb + 688 >> 2] | 0;
             if ((k | 0) == -1) if (!j) {
              Pb = 1240;
              break;
             } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
              Pb = 1240;
              break;
             }
             b[z + 208 + (m << 2) + 2 >> 1] = j;
             Pb = c[Qb + 648 >> 2] | 0;
             c[Qb + 648 >> 2] = Pb + -1;
             if (!Pb) {
              Pb = 1242;
              break;
             } else m = m + 1 | 0;
            }
            if ((Pb | 0) == 1236) {
             Pb = 0;
             Ea = 1;
             break;
            } else if ((Pb | 0) == 1240) {
             Pb = 0;
             Ea = 1;
             break;
            } else if ((Pb | 0) == 1242) {
             switch (c[z + 180 >> 2] | 0) {
             case 0:
              {
               j = 0;
               break;
              }
             case 2:
             case 1:
              {
               j = 1;
               break;
              }
             default:
              j = 3;
             }
             c[Qb + 648 >> 2] = j;
             m = 0;
             while (1) {
              c[Qb + 688 >> 2] = 0;
              j = va(Qb, Qb + 688 | 0) | 0;
              k = c[Qb + 688 >> 2] | 0;
              if ((k | 0) == -1) if (!j) {
               Pb = 1249;
               break;
              } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
               Pb = 1249;
               break;
              }
              b[z + 224 + (m << 2) >> 1] = j;
              c[Qb + 688 >> 2] = 0;
              j = va(Qb, Qb + 688 | 0) | 0;
              k = c[Qb + 688 >> 2] | 0;
              if ((k | 0) == -1) if (!j) {
               Pb = 1253;
               break;
              } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
               Pb = 1253;
               break;
              }
              b[z + 224 + (m << 2) + 2 >> 1] = j;
              Pb = c[Qb + 648 >> 2] | 0;
              c[Qb + 648 >> 2] = Pb + -1;
              if (!Pb) {
               Pb = 1255;
               break;
              } else m = m + 1 | 0;
             }
             if ((Pb | 0) == 1249) {
              Pb = 0;
              Ea = 1;
              break;
             } else if ((Pb | 0) == 1253) {
              Pb = 0;
              Ea = 1;
              break;
             } else if ((Pb | 0) == 1255) {
              switch (c[z + 184 >> 2] | 0) {
              case 0:
               {
                j = 0;
                break;
               }
              case 2:
              case 1:
               {
                j = 1;
                break;
               }
              default:
               j = 3;
              }
              c[Qb + 648 >> 2] = j;
              m = 0;
              while (1) {
               c[Qb + 688 >> 2] = 0;
               j = va(Qb, Qb + 688 | 0) | 0;
               k = c[Qb + 688 >> 2] | 0;
               if ((k | 0) == -1) if (!j) {
                Pb = 1262;
                break;
               } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
                Pb = 1262;
                break;
               }
               b[z + 240 + (m << 2) >> 1] = j;
               c[Qb + 688 >> 2] = 0;
               j = va(Qb, Qb + 688 | 0) | 0;
               k = c[Qb + 688 >> 2] | 0;
               if ((k | 0) == -1) if (!j) {
                Pb = 1266;
                break;
               } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
                Pb = 1266;
                break;
               }
               b[z + 240 + (m << 2) + 2 >> 1] = j;
               Pb = c[Qb + 648 >> 2] | 0;
               c[Qb + 648 >> 2] = Pb + -1;
               if (!Pb) {
                Pb = 1268;
                break;
               } else m = m + 1 | 0;
              }
              if ((Pb | 0) == 1262) {
               Pb = 0;
               Ea = 1;
               break;
              } else if ((Pb | 0) == 1266) {
               Pb = 0;
               Ea = 1;
               break;
              } else if ((Pb | 0) == 1268) {
               Pb = 0;
               switch (c[z + 188 >> 2] | 0) {
               case 0:
                {
                 j = 0;
                 break;
                }
               case 2:
               case 1:
                {
                 j = 1;
                 break;
                }
               default:
                j = 3;
               }
               c[Qb + 648 >> 2] = j;
               m = 0;
               while (1) {
                c[Qb + 688 >> 2] = 0;
                j = va(Qb, Qb + 688 | 0) | 0;
                k = c[Qb + 688 >> 2] | 0;
                if ((k | 0) == -1) if (!j) {
                 Pb = 1275;
                 break;
                } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
                 Pb = 1275;
                 break;
                }
                b[z + 256 + (m << 2) >> 1] = j;
                c[Qb + 688 >> 2] = 0;
                j = va(Qb, Qb + 688 | 0) | 0;
                k = c[Qb + 688 >> 2] | 0;
                if ((k | 0) == -1) if (!j) {
                 Pb = 1279;
                 break;
                } else j = -2147483648; else if (!j) j = k & 1 | 0 ? (k + 1 | 0) >>> 1 : 0 - ((k + 1 | 0) >>> 1) | 0; else {
                 Pb = 1279;
                 break;
                }
                b[z + 256 + (m << 2) + 2 >> 1] = j;
                fb = c[Qb + 648 >> 2] | 0;
                c[Qb + 648 >> 2] = fb + -1;
                if (!fb) {
                 Ea = 0;
                 break L;
                } else m = m + 1 | 0;
               }
               if ((Pb | 0) == 1275) {
                Pb = 0;
                Ea = 1;
                break;
               } else if ((Pb | 0) == 1279) {
                Pb = 0;
                Ea = 1;
                break;
               }
              }
             }
            }
           } while (0);
           j = Ea;
          }
          if (j | 0) {
           ab = 1;
           Pb = 1450;
           break I;
          }
          if (u >>> 0 > 6) {
           fb = c[z >> 2] | 0;
           c[z + 4 >> 2] = ((fb + -7 | 0) >>> 0 > 11 ? ((fb + -7 | 0) >>> 2) + 268435453 | 0 : (fb + -7 | 0) >>> 2) << 4 | (fb >>> 0 > 18 ? 15 : 0);
          } else {
           if (va(Qb, Qb + 688 | 0) | 0) {
            Pb = 1386;
            break I;
           }
           j = c[Qb + 688 >> 2] | 0;
           if (j >>> 0 > 47) {
            Pb = 1386;
            break I;
           }
           fb = a[(v ? 4932 : 4980) + j >> 0] | 0;
           c[Qb + 628 >> 2] = fb & 255;
           c[z + 4 >> 2] = fb & 255;
           if (!(fb << 24 >> 24)) break;
          }
          c[Qb + 688 >> 2] = 0;
          k = va(Qb, Qb + 688 | 0) | 0;
          j = c[Qb + 688 >> 2] | 0;
          if ((j | 0) == -1) {
           Pb = 1391;
           break I;
          }
          j = j & 1 | 0 ? (j + 1 | 0) >>> 1 : 0 - ((j + 1 | 0) >>> 1) | 0;
          if (k | 0) {
           Pb = 1391;
           break I;
          }
          if ((j + 26 | 0) >>> 0 > 51) {
           ab = 1;
           Pb = 1450;
           break I;
          }
          c[z + 8 >> 2] = j;
          k = c[z + 4 >> 2] | 0;
          M : do if ((c[z >> 2] | 0) >>> 0 > 6) {
           j = c[Va + (x * 216 | 0) + 200 >> 2] | 0;
           do if (!j) {
            n = 0;
            j = 0;
           } else {
            if ((c[Va + (x * 216 | 0) + 4 >> 2] | 0) != (c[j + 4 >> 2] | 0)) {
             n = 0;
             j = 0;
             break;
            }
            n = 1;
            j = b[j + 38 >> 1] | 0;
           } while (0);
           m = c[Va + (x * 216 | 0) + 204 >> 2] | 0;
           do if (m) {
            if ((c[Va + (x * 216 | 0) + 4 >> 2] | 0) != (c[m + 4 >> 2] | 0)) break;
            fb = b[m + 48 >> 1] | 0;
            j = (n | 0) == 0 ? fb : j + 1 + fb >> 1;
           } while (0);
           j = wa(Qb, z + 1864 | 0, j, 16) | 0;
           if (j & 15 | 0) {
            ua = j;
            break;
           }
           b[z + 320 >> 1] = j >>> 4 & 255;
           j = 0;
           o = 3;
           while (1) {
            n = k >>> 1;
            if (k & 1 | 0) {
             k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
             c[z + 1992 + (j << 2) >> 2] = k >>> 15;
             if (k & 15 | 0) {
              ua = k;
              break M;
             }
             b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
             k = j | 1;
             m = wa(Qb, z + 328 + (k << 6) + 4 | 0, sa(w, k, z + 272 | 0) | 0, 15) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 15;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
             k = j | 2;
             m = wa(Qb, z + 328 + (k << 6) + 4 | 0, sa(w, k, z + 272 | 0) | 0, 15) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 15;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
             k = j | 3;
             m = wa(Qb, z + 328 + (k << 6) + 4 | 0, sa(w, k, z + 272 | 0) | 0, 15) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 15;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
            }
            j = j + 4 | 0;
            if (!o) {
             Fa = j;
             Ga = n;
             Pb = 1410;
             break;
            } else {
             k = n;
             o = o + -1 | 0;
            }
           }
          } else {
           j = 0;
           o = 3;
           while (1) {
            n = k >>> 1;
            if (k & 1 | 0) {
             k = wa(Qb, z + 328 + (j << 6) | 0, sa(w, j, z + 272 | 0) | 0, 16) | 0;
             c[z + 1992 + (j << 2) >> 2] = k >>> 16;
             if (k & 15 | 0) {
              ua = k;
              break M;
             }
             b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
             k = j | 1;
             m = wa(Qb, z + 328 + (k << 6) | 0, sa(w, k, z + 272 | 0) | 0, 16) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 16;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
             k = j | 2;
             m = wa(Qb, z + 328 + (k << 6) | 0, sa(w, k, z + 272 | 0) | 0, 16) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 16;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
             k = j | 3;
             m = wa(Qb, z + 328 + (k << 6) | 0, sa(w, k, z + 272 | 0) | 0, 16) | 0;
             c[z + 1992 + (k << 2) >> 2] = m >>> 16;
             if (m & 15 | 0) {
              ua = m;
              break M;
             }
             b[z + 272 + (k << 1) >> 1] = m >>> 4 & 255;
            }
            j = j + 4 | 0;
            if (!o) {
             Fa = j;
             Ga = n;
             Pb = 1410;
             break;
            } else {
             k = n;
             o = o + -1 | 0;
            }
           }
          } while (0);
          do if ((Pb | 0) == 1410) {
           Pb = 0;
           if (Ga & 3 | 0) {
            j = wa(Qb, z + 1928 | 0, -1, 4) | 0;
            if (j & 15 | 0) {
             ua = j;
             break;
            }
            b[z + 322 >> 1] = j >>> 4 & 255;
            j = wa(Qb, z + 1944 | 0, -1, 4) | 0;
            if (j & 15 | 0) {
             ua = j;
             break;
            }
            b[z + 324 >> 1] = j >>> 4 & 255;
           }
           if (!(Ga & 2)) {
            ua = 0;
            break;
           }
           j = wa(Qb, z + 328 + (Fa << 6) + 4 | 0, sa(w, Fa, z + 272 | 0) | 0, 15) | 0;
           if (j & 15 | 0) {
            ua = j;
            break;
           }
           b[z + 272 + (Fa << 1) >> 1] = j >>> 4 & 255;
           c[z + 1992 + (Fa << 2) >> 2] = j >>> 15;
           j = Fa + 1 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           j = Fa + 2 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           j = Fa + 3 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           j = Fa + 4 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           j = Fa + 5 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           j = Fa + 6 | 0;
           k = wa(Qb, z + 328 + (j << 6) + 4 | 0, sa(w, j, z + 272 | 0) | 0, 15) | 0;
           if (k & 15 | 0) {
            ua = k;
            break;
           }
           b[z + 272 + (j << 1) >> 1] = k >>> 4 & 255;
           c[z + 1992 + (j << 2) >> 2] = k >>> 15;
           k = Fa + 7 | 0;
           j = wa(Qb, z + 328 + (k << 6) + 4 | 0, sa(w, k, z + 272 | 0) | 0, 15) | 0;
           if (j & 15 | 0) {
            ua = j;
            break;
           }
           b[z + 272 + (k << 1) >> 1] = j >>> 4 & 255;
           c[z + 1992 + (k << 2) >> 2] = j >>> 15;
           ua = 0;
          } while (0);
          c[Qb + 16 >> 2] = ((c[Qb + 4 >> 2] | 0) - (c[Qb >> 2] | 0) << 3) + (c[Ob >> 2] | 0);
          if (ua | 0) {
           ab = ua;
           Pb = 1450;
           break I;
          }
         } while (0);
         pa = 0;
         qa = 0;
        }
        j = ta((c[e + 1212 >> 2] | 0) + (x * 216 | 0) | 0, z, e + 1336 | 0, e + 1220 | 0, Qb + 188 | 0, x, c[(c[e + 12 >> 2] | 0) + 64 >> 2] | 0, Qb + 196 + (0 - (Qb + 196) & 15) | 0) | 0;
        if (j | 0) {
         Ba = j;
         break;
        }
        p = c[e + 1212 >> 2] | 0;
        y = y + ((c[p + (x * 216 | 0) + 196 >> 2] | 0) == 1 & 1) | 0;
        o = (c[bb >> 2] << 3) - (c[Qb + 16 >> 2] | 0) | 0;
        do if (!o) j = 0; else {
         if (o >>> 0 > 8) {
          j = 1;
          break;
         }
         m = c[Qb + 4 >> 2] | 0;
         k = c[Ob >> 2] | 0;
         j = d[m >> 0] << k + 24;
         if ((o + -8 + k | 0) > 0) {
          n = o + -8 + k | 0;
          k = k + 24 | 0;
          while (1) {
           m = m + 1 | 0;
           k = k + -8 | 0;
           j = d[m >> 0] << k | j;
           if ((n | 0) <= 8) break; else n = n + -8 | 0;
          }
         }
         j = (j >>> (32 - o | 0) | 0) != (1 << o + -1 | 0) & 1;
        } while (0);
        k = (qa | j | 0) != 0;
        switch (c[e + 1372 >> 2] | 0) {
        case 7:
        case 2:
         {
          c[e + 1200 >> 2] = x;
          break;
         }
        default:
         {}
        }
        m = c[e + 1172 >> 2] | 0;
        xa = c[e + 1176 >> 2] | 0;
        n = c[m + (x << 2) >> 2] | 0;
        j = x;
        do {
         j = j + 1 | 0;
         if (j >>> 0 >= xa >>> 0) break;
        } while ((c[m + (j << 2) >> 2] | 0) != (n | 0));
        x = (j | 0) == (xa | 0) ? 0 : j;
        if (!((x | 0) != 0 | k ^ 1)) {
         Ba = 1;
         break;
        }
        if (!k) {
         Pb = 1465;
         break;
        } else {
         k = pa;
         n = qa;
        }
       }
       do if ((Pb | 0) == 1386) {
        ab = 1;
        Pb = 1450;
       } else if ((Pb | 0) == 1391) {
        ab = 1;
        Pb = 1450;
       } else if ((Pb | 0) == 1432) {
        c[Qb + 628 >> 2] = -1;
        ab = 1;
        Pb = 1450;
       } else if ((Pb | 0) == 1465) {
        j = (c[e + 1196 >> 2] | 0) + y | 0;
        if (j >>> 0 > xa >>> 0) {
         Ba = 1;
         break;
        }
        c[e + 1196 >> 2] = j;
        Ba = 0;
       } while (0);
       if ((Pb | 0) == 1450) Ba = ab;
       if (!Ba) {
        do if (!(c[e + 1404 >> 2] | 0)) {
         if ((c[e + 1196 >> 2] | 0) == (c[e + 1176 >> 2] | 0)) break; else fa = 0;
         l = Qb;
         return fa | 0;
        } else {
         m = c[e + 1176 >> 2] | 0;
         if (!m) break;
         n = c[e + 1212 >> 2] | 0;
         j = 0;
         k = 0;
         do {
          k = k + ((c[n + (j * 216 | 0) + 196 >> 2] | 0) != 0 & 1) | 0;
          j = j + 1 | 0;
         } while ((j | 0) != (m | 0));
         if ((k | 0) == (m | 0)) break; else fa = 0;
         l = Qb;
         return fa | 0;
        } while (0);
        c[e + 1180 >> 2] = 1;
        cb = e + 1212 | 0;
        db = e + 16 | 0;
        fb = e + 1188 | 0;
        eb = e + 1336 | 0;
        break i;
       }
       m = c[e + 1368 >> 2] | 0;
       p = c[e + 1192 >> 2] | 0;
       j = c[e + 1200 >> 2] | 0;
       N : do if (!j) j = m; else {
        k = 0;
        do {
         do {
          j = j + -1 | 0;
          if (j >>> 0 <= m >>> 0) break N;
         } while ((c[(c[e + 1212 >> 2] | 0) + (j * 216 | 0) + 4 >> 2] | 0) != (p | 0));
         k = k + 1 | 0;
         Pb = c[(c[e + 16 >> 2] | 0) + 52 >> 2] | 0;
        } while (k >>> 0 < (Pb >>> 0 > 10 ? Pb : 10) >>> 0);
       } while (0);
       o = c[e + 1212 >> 2] | 0;
       while (1) {
        if ((c[o + (j * 216 | 0) + 4 >> 2] | 0) != (p | 0)) {
         fa = 3;
         Pb = 1869;
         break;
        }
        k = o + (j * 216 | 0) + 196 | 0;
        m = c[k >> 2] | 0;
        if (!m) {
         fa = 3;
         Pb = 1869;
         break;
        }
        c[k >> 2] = m + -1;
        k = c[e + 1172 >> 2] | 0;
        m = c[e + 1176 >> 2] | 0;
        n = c[k + (j << 2) >> 2] | 0;
        do {
         j = j + 1 | 0;
         if (j >>> 0 >= m >>> 0) break;
        } while ((c[k + (j << 2) >> 2] | 0) != (n | 0));
        j = (j | 0) == (m | 0) ? 0 : j;
        if (!j) {
         fa = 3;
         Pb = 1869;
         break;
        }
       }
       if ((Pb | 0) == 1869) {
        l = Qb;
        return fa | 0;
       }
      }
     }
    }
   } while (0);
   e = 3;
   l = Qb;
   return e | 0;
  }
 default:
  {
   e = 0;
   l = Qb;
   return e | 0;
  }
 } while (0);
 fa = c[eb + 4 >> 2] | 0;
 ga = eb + 8 | 0;
 Ob = c[ga >> 2] | 0;
 ha = N(Ob, fa) | 0;
 if (Ob | 0) {
  ia = Qb + 688 + 24 | 0;
  ja = Qb + 688 + 16 | 0;
  ka = Qb + 688 + 8 | 0;
  la = Qb + 688 + 100 | 0;
  ma = Qb + 688 + 68 | 0;
  na = Qb + 688 + 36 | 0;
  oa = Qb + 688 + 4 | 0;
  pa = Qb + 688 + 120 | 0;
  qa = Qb + 688 + 112 | 0;
  ra = Qb + 688 + 104 | 0;
  ua = Qb + 688 + 96 | 0;
  xa = Qb + 688 + 88 | 0;
  ya = Qb + 688 + 80 | 0;
  za = Qb + 688 + 72 | 0;
  Aa = Qb + 688 + 64 | 0;
  Ba = Qb + 688 + 56 | 0;
  Ca = Qb + 688 + 48 | 0;
  Da = Qb + 688 + 40 | 0;
  Ea = Qb + 688 + 32 | 0;
  Fa = Qb + 688 + 116 | 0;
  Ga = Qb + 688 + 108 | 0;
  Ia = Qb + 688 + 92 | 0;
  Ka = Qb + 688 + 84 | 0;
  Ra = Qb + 688 + 76 | 0;
  Ta = Qb + 688 + 60 | 0;
  Ua = Qb + 688 + 52 | 0;
  Va = Qb + 688 + 44 | 0;
  Wa = Qb + 688 + 28 | 0;
  Xa = Qb + 688 + 20 | 0;
  Ya = Qb + 688 + 12 | 0;
  Za = N(fa, -48) | 0;
  ab = Qb + 648 + 24 | 0;
  bb = Qb + 648 + 12 | 0;
  da = 0;
  ca = 0;
  ea = c[cb >> 2] | 0;
  while (1) {
   k = c[ea + 8 >> 2] | 0;
   O : do if ((k | 0) != 1) {
    ba = ea + 200 | 0;
    q = c[ba >> 2] | 0;
    do if (!q) j = 1; else {
     if ((k | 0) == 2) if ((c[ea + 4 >> 2] | 0) != (c[q + 4 >> 2] | 0)) {
      j = 1;
      break;
     }
     j = 5;
    } while (0);
    aa = ea + 204 | 0;
    Z = c[aa >> 2] | 0;
    do if (Z) {
     if ((k | 0) == 2) if ((c[ea + 4 >> 2] | 0) != (c[Z + 4 >> 2] | 0)) break;
     j = j | 2;
    } while (0);
    $ = (j & 2 | 0) == 0;
    P : do if ($) {
     c[ia >> 2] = 0;
     c[ja >> 2] = 0;
     c[ka >> 2] = 0;
     c[Qb + 688 >> 2] = 0;
     p = 0;
    } else {
     do if ((c[ea >> 2] | 0) >>> 0 <= 5) {
      if ((c[Z >> 2] | 0) >>> 0 > 5) break;
      do if (!(b[ea + 28 >> 1] | 0)) {
       if (b[Z + 48 >> 1] | 0) {
        k = 2;
        break;
       }
       if ((c[ea + 116 >> 2] | 0) != (c[Z + 124 >> 2] | 0)) {
        k = 1;
        break;
       }
       Pb = (b[ea + 132 >> 1] | 0) - (b[Z + 172 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        k = 1;
        break;
       }
       k = (b[ea + 134 >> 1] | 0) - (b[Z + 174 >> 1] | 0) | 0;
       k = (((k | 0) < 0 ? 0 - k | 0 : k) | 0) > 3 & 1;
      } else k = 2; while (0);
      c[Qb + 688 >> 2] = k;
      do if (!(b[ea + 30 >> 1] | 0)) {
       if (b[Z + 50 >> 1] | 0) {
        m = 2;
        break;
       }
       if ((c[ea + 116 >> 2] | 0) != (c[Z + 124 >> 2] | 0)) {
        m = 1;
        break;
       }
       Pb = (b[ea + 136 >> 1] | 0) - (b[Z + 176 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        m = 1;
        break;
       }
       m = (b[ea + 138 >> 1] | 0) - (b[Z + 178 >> 1] | 0) | 0;
       m = (((m | 0) < 0 ? 0 - m | 0 : m) | 0) > 3 & 1;
      } else m = 2; while (0);
      c[ka >> 2] = m;
      do if (!(b[ea + 36 >> 1] | 0)) {
       if (b[Z + 56 >> 1] | 0) {
        n = 2;
        break;
       }
       if ((c[ea + 120 >> 2] | 0) != (c[Z + 128 >> 2] | 0)) {
        n = 1;
        break;
       }
       Pb = (b[ea + 148 >> 1] | 0) - (b[Z + 188 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        n = 1;
        break;
       }
       n = (b[ea + 150 >> 1] | 0) - (b[Z + 190 >> 1] | 0) | 0;
       n = (((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 & 1;
      } else n = 2; while (0);
      c[ja >> 2] = n;
      do if (!(b[ea + 38 >> 1] | 0)) {
       if (b[Z + 58 >> 1] | 0) {
        o = 2;
        break;
       }
       if ((c[ea + 120 >> 2] | 0) != (c[Z + 128 >> 2] | 0)) {
        o = 1;
        break;
       }
       Pb = (b[ea + 152 >> 1] | 0) - (b[Z + 192 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        o = 1;
        break;
       }
       o = (b[ea + 154 >> 1] | 0) - (b[Z + 194 >> 1] | 0) | 0;
       o = (((o | 0) < 0 ? 0 - o | 0 : o) | 0) > 3 & 1;
      } else o = 2; while (0);
      c[ia >> 2] = o;
      p = (m | k | n | o | 0) != 0 & 1;
      break P;
     } while (0);
     c[ia >> 2] = 4;
     c[ja >> 2] = 4;
     c[ka >> 2] = 4;
     c[Qb + 688 >> 2] = 4;
     p = 1;
    } while (0);
    _ = (j & 4 | 0) == 0;
    Q : do if (_) {
     c[la >> 2] = 0;
     c[ma >> 2] = 0;
     c[na >> 2] = 0;
     c[oa >> 2] = 0;
     ib = p;
     kb = c[ea >> 2] | 0;
     Pb = 1550;
    } else {
     o = c[ea >> 2] | 0;
     do if (o >>> 0 <= 5) {
      if ((c[q >> 2] | 0) >>> 0 > 5) break;
      do if (!(b[ea + 28 >> 1] | 0)) {
       if (b[q + 38 >> 1] | 0) {
        k = 2;
        break;
       }
       if ((c[ea + 116 >> 2] | 0) != (c[q + 120 >> 2] | 0)) {
        k = 1;
        break;
       }
       Pb = (b[ea + 132 >> 1] | 0) - (b[q + 152 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        k = 1;
        break;
       }
       k = (b[ea + 134 >> 1] | 0) - (b[q + 154 >> 1] | 0) | 0;
       k = (((k | 0) < 0 ? 0 - k | 0 : k) | 0) > 3 & 1;
      } else k = 2; while (0);
      c[oa >> 2] = k;
      do if (!(b[ea + 32 >> 1] | 0)) {
       if (b[q + 42 >> 1] | 0) {
        m = 2;
        break;
       }
       if ((c[ea + 116 >> 2] | 0) != (c[q + 120 >> 2] | 0)) {
        m = 1;
        break;
       }
       Pb = (b[ea + 140 >> 1] | 0) - (b[q + 160 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        m = 1;
        break;
       }
       m = (b[ea + 142 >> 1] | 0) - (b[q + 162 >> 1] | 0) | 0;
       m = (((m | 0) < 0 ? 0 - m | 0 : m) | 0) > 3 & 1;
      } else m = 2; while (0);
      c[na >> 2] = m;
      do if (!(b[ea + 44 >> 1] | 0)) {
       if (b[q + 54 >> 1] | 0) {
        n = 2;
        break;
       }
       if ((c[ea + 124 >> 2] | 0) != (c[q + 128 >> 2] | 0)) {
        n = 1;
        break;
       }
       Pb = (b[ea + 164 >> 1] | 0) - (b[q + 184 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        n = 1;
        break;
       }
       n = (b[ea + 166 >> 1] | 0) - (b[q + 186 >> 1] | 0) | 0;
       n = (((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 & 1;
      } else n = 2; while (0);
      c[ma >> 2] = n;
      do if (!(b[ea + 48 >> 1] | 0)) {
       if (b[q + 58 >> 1] | 0) {
        j = 2;
        break;
       }
       if ((c[ea + 124 >> 2] | 0) != (c[q + 128 >> 2] | 0)) {
        j = 1;
        break;
       }
       Pb = (b[ea + 172 >> 1] | 0) - (b[q + 192 >> 1] | 0) | 0;
       if ((((Pb | 0) < 0 ? 0 - Pb | 0 : Pb) | 0) > 3) {
        j = 1;
        break;
       }
       j = (b[ea + 174 >> 1] | 0) - (b[q + 194 >> 1] | 0) | 0;
       j = (((j | 0) < 0 ? 0 - j | 0 : j) | 0) > 3 & 1;
      } else j = 2; while (0);
      c[la >> 2] = j;
      gb = (k | p | m | n | j | 0) != 0 & 1;
      hb = o;
      Pb = 1552;
      break Q;
     } while (0);
     c[la >> 2] = 4;
     c[ma >> 2] = 4;
     c[na >> 2] = 4;
     c[oa >> 2] = 4;
     ib = 1;
     kb = o;
     Pb = 1550;
    } while (0);
    if ((Pb | 0) == 1550) {
     Pb = 0;
     if (kb >>> 0 > 5) {
      c[pa >> 2] = 3;
      c[qa >> 2] = 3;
      c[ra >> 2] = 3;
      c[ua >> 2] = 3;
      c[xa >> 2] = 3;
      c[ya >> 2] = 3;
      c[za >> 2] = 3;
      c[Aa >> 2] = 3;
      c[Ba >> 2] = 3;
      c[Ca >> 2] = 3;
      c[Da >> 2] = 3;
      c[Ea >> 2] = 3;
      c[Qb + 688 + 124 >> 2] = 3;
      c[Fa >> 2] = 3;
      c[Ga >> 2] = 3;
      c[Ia >> 2] = 3;
      c[Ka >> 2] = 3;
      c[Ra >> 2] = 3;
      c[Ta >> 2] = 3;
      c[Ua >> 2] = 3;
      c[Va >> 2] = 3;
      c[Wa >> 2] = 3;
      c[Xa >> 2] = 3;
      c[Ya >> 2] = 3;
     } else {
      gb = ib;
      hb = kb;
      Pb = 1552;
     }
    }
    do if ((Pb | 0) == 1552) {
     Pb = 0;
     R : do if (hb >>> 0 < 2) {
      j = ea + 28 | 0;
      k = b[ea + 32 >> 1] | 0;
      if (!(k << 16 >> 16)) if (!(b[j >> 1] | 0)) lb = 0; else Pb = 1555; else Pb = 1555;
      if ((Pb | 0) == 1555) {
       Pb = 0;
       lb = 2;
      }
      c[Ea >> 2] = lb;
      m = b[ea + 34 >> 1] | 0;
      if (!(m << 16 >> 16)) if (!(b[ea + 30 >> 1] | 0)) mb = 0; else Pb = 1558; else Pb = 1558;
      if ((Pb | 0) == 1558) {
       Pb = 0;
       mb = 2;
      }
      c[Da >> 2] = mb;
      n = b[ea + 40 >> 1] | 0;
      if (!(n << 16 >> 16)) if (!(b[ea + 36 >> 1] | 0)) nb = 0; else Pb = 1561; else Pb = 1561;
      if ((Pb | 0) == 1561) {
       Pb = 0;
       nb = 2;
      }
      c[Ca >> 2] = nb;
      p = b[ea + 42 >> 1] | 0;
      if (!(p << 16 >> 16)) if (!(b[ea + 38 >> 1] | 0)) qb = 0; else Pb = 1564; else Pb = 1564;
      if ((Pb | 0) == 1564) {
       Pb = 0;
       qb = 2;
      }
      c[Ba >> 2] = qb;
      q = b[ea + 44 >> 1] | 0;
      o = (q | k) << 16 >> 16 ? 2 : 0;
      c[Aa >> 2] = o;
      r = b[ea + 46 >> 1] | 0;
      E = (r | m) << 16 >> 16 ? 2 : 0;
      c[za >> 2] = E;
      s = b[ea + 52 >> 1] | 0;
      D = (s | n) << 16 >> 16 ? 2 : 0;
      c[ya >> 2] = D;
      t = b[ea + 54 >> 1] | 0;
      C = (t | p) << 16 >> 16 ? 2 : 0;
      c[xa >> 2] = C;
      u = b[ea + 48 >> 1] | 0;
      B = (u | q) << 16 >> 16 ? 2 : 0;
      c[ua >> 2] = B;
      v = b[ea + 50 >> 1] | 0;
      g = (v | r) << 16 >> 16 ? 2 : 0;
      c[ra >> 2] = g;
      w = b[ea + 56 >> 1] | 0;
      A = (w | s) << 16 >> 16 ? 2 : 0;
      c[qa >> 2] = A;
      x = b[ea + 58 >> 1] | 0;
      z = (x | t) << 16 >> 16 ? 2 : 0;
      c[pa >> 2] = z;
      y = b[ea + 30 >> 1] | 0;
      if (!(y << 16 >> 16)) if (!(b[j >> 1] | 0)) rb = 0; else Pb = 1567; else Pb = 1567;
      if ((Pb | 0) == 1567) {
       Pb = 0;
       rb = 2;
      }
      c[Ya >> 2] = rb;
      j = b[ea + 36 >> 1] | 0;
      c[Xa >> 2] = (j | y) << 16 >> 16 ? 2 : 0;
      c[Wa >> 2] = (b[ea + 38 >> 1] | j) << 16 >> 16 ? 2 : 0;
      c[Va >> 2] = (m | k) << 16 >> 16 ? 2 : 0;
      c[Ua >> 2] = (n | m) << 16 >> 16 ? 2 : 0;
      c[Ta >> 2] = (p | n) << 16 >> 16 ? 2 : 0;
      c[Ra >> 2] = (r | q) << 16 >> 16 ? 2 : 0;
      c[Ka >> 2] = (s | r) << 16 >> 16 ? 2 : 0;
      c[Ia >> 2] = (t | s) << 16 >> 16 ? 2 : 0;
      c[Ga >> 2] = (v | u) << 16 >> 16 ? 2 : 0;
      c[Fa >> 2] = w << 16 >> 16 == 0 ? (v << 16 >> 16 ? 2 : 0) : 2;
      s = x << 16 >> 16 == 0 ? (w << 16 >> 16 ? 2 : 0) : 2;
      t = 15;
      r = C;
      q = D;
      p = E;
      n = qb;
      m = nb;
      k = mb;
      j = lb;
     } else switch (hb | 0) {
     case 2:
      {
       r = ea + 28 | 0;
       s = b[ea + 32 >> 1] | 0;
       if (!(s << 16 >> 16)) if (!(b[r >> 1] | 0)) sb = 0; else Pb = 1572; else Pb = 1572;
       if ((Pb | 0) == 1572) {
        Pb = 0;
        sb = 2;
       }
       c[Ea >> 2] = sb;
       t = b[ea + 34 >> 1] | 0;
       if (!(t << 16 >> 16)) if (!(b[ea + 30 >> 1] | 0)) tb = 0; else Pb = 1575; else Pb = 1575;
       if ((Pb | 0) == 1575) {
        Pb = 0;
        tb = 2;
       }
       c[Da >> 2] = tb;
       u = b[ea + 40 >> 1] | 0;
       if (!(u << 16 >> 16)) if (!(b[ea + 36 >> 1] | 0)) ub = 0; else Pb = 1578; else Pb = 1578;
       if ((Pb | 0) == 1578) {
        Pb = 0;
        ub = 2;
       }
       c[Ca >> 2] = ub;
       v = b[ea + 42 >> 1] | 0;
       if (!(v << 16 >> 16)) if (!(b[ea + 38 >> 1] | 0)) vb = 0; else Pb = 1581; else Pb = 1581;
       if ((Pb | 0) == 1581) {
        Pb = 0;
        vb = 2;
       }
       c[Ba >> 2] = vb;
       w = b[ea + 48 >> 1] | 0;
       if (!(w << 16 >> 16)) if (!(b[ea + 44 >> 1] | 0)) wb = 0; else Pb = 1584; else Pb = 1584;
       if ((Pb | 0) == 1584) {
        Pb = 0;
        wb = 2;
       }
       c[ua >> 2] = wb;
       x = b[ea + 50 >> 1] | 0;
       if (!(x << 16 >> 16)) if (!(b[ea + 46 >> 1] | 0)) xb = 0; else Pb = 1587; else Pb = 1587;
       if ((Pb | 0) == 1587) {
        Pb = 0;
        xb = 2;
       }
       c[ra >> 2] = xb;
       y = b[ea + 56 >> 1] | 0;
       if (!(y << 16 >> 16)) if (!(b[ea + 52 >> 1] | 0)) yb = 0; else Pb = 1590; else Pb = 1590;
       if ((Pb | 0) == 1590) {
        Pb = 0;
        yb = 2;
       }
       c[qa >> 2] = yb;
       z = (b[ea + 58 >> 1] | 0) == 0;
       if (z) if (!(b[ea + 54 >> 1] | 0)) zb = 0; else Pb = 1593; else Pb = 1593;
       if ((Pb | 0) == 1593) {
        Pb = 0;
        zb = 2;
       }
       c[pa >> 2] = zb;
       A = b[ea + 44 >> 1] | 0;
       j = b[ea + 166 >> 1] | 0;
       k = b[ea + 142 >> 1] | 0;
       do if (!((A | s) << 16 >> 16)) {
        Ob = (b[ea + 164 >> 1] | 0) - (b[ea + 140 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         o = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         o = 1;
         break;
        }
        o = (c[ea + 124 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else o = 2; while (0);
       c[Aa >> 2] = o;
       q = b[ea + 46 >> 1] | 0;
       j = b[ea + 170 >> 1] | 0;
       k = b[ea + 146 >> 1] | 0;
       do if (!((q | t) << 16 >> 16)) {
        Ob = (b[ea + 168 >> 1] | 0) - (b[ea + 144 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         p = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         p = 1;
         break;
        }
        p = (c[ea + 124 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else p = 2; while (0);
       c[za >> 2] = p;
       n = b[ea + 52 >> 1] | 0;
       j = b[ea + 182 >> 1] | 0;
       k = b[ea + 158 >> 1] | 0;
       do if (!((n | u) << 16 >> 16)) {
        Ob = (b[ea + 180 >> 1] | 0) - (b[ea + 156 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         C = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         C = 1;
         break;
        }
        C = (c[ea + 128 >> 2] | 0) != (c[ea + 120 >> 2] | 0) & 1;
       } else C = 2; while (0);
       c[ya >> 2] = C;
       m = b[ea + 54 >> 1] | 0;
       j = b[ea + 186 >> 1] | 0;
       k = b[ea + 162 >> 1] | 0;
       do if (!((m | v) << 16 >> 16)) {
        Ob = (b[ea + 184 >> 1] | 0) - (b[ea + 160 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         k = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         k = 1;
         break;
        }
        k = (c[ea + 128 >> 2] | 0) != (c[ea + 120 >> 2] | 0) & 1;
       } else k = 2; while (0);
       c[xa >> 2] = k;
       j = b[ea + 30 >> 1] | 0;
       if (!(j << 16 >> 16)) if (!(b[r >> 1] | 0)) Ab = 0; else Pb = 1612; else Pb = 1612;
       if ((Pb | 0) == 1612) {
        Pb = 0;
        Ab = 2;
       }
       c[Ya >> 2] = Ab;
       g = b[ea + 36 >> 1] | 0;
       c[Xa >> 2] = (g | j) << 16 >> 16 ? 2 : 0;
       c[Wa >> 2] = (b[ea + 38 >> 1] | g) << 16 >> 16 ? 2 : 0;
       c[Va >> 2] = (t | s) << 16 >> 16 ? 2 : 0;
       c[Ua >> 2] = (u | t) << 16 >> 16 ? 2 : 0;
       c[Ta >> 2] = (v | u) << 16 >> 16 ? 2 : 0;
       c[Ra >> 2] = (q | A) << 16 >> 16 == 0 ? 0 : 2;
       c[Ka >> 2] = (n | q) << 16 >> 16 ? 2 : 0;
       c[Ia >> 2] = (m | n) << 16 >> 16 ? 2 : 0;
       c[Ga >> 2] = (x | w) << 16 >> 16 ? 2 : 0;
       c[Fa >> 2] = y << 16 >> 16 == 0 ? (x << 16 >> 16 ? 2 : 0) : 2;
       s = z ? (y << 16 >> 16 ? 2 : 0) : 2;
       t = 15;
       z = zb;
       A = yb;
       g = xb;
       B = wb;
       r = k;
       q = C;
       n = vb;
       m = ub;
       k = tb;
       j = sb;
       break R;
      }
     case 3:
      {
       j = ea + 28 | 0;
       k = b[ea + 32 >> 1] | 0;
       if (!(k << 16 >> 16)) if (!(b[j >> 1] | 0)) Bb = 0; else Pb = 1616; else Pb = 1616;
       if ((Pb | 0) == 1616) {
        Pb = 0;
        Bb = 2;
       }
       c[Ea >> 2] = Bb;
       u = b[ea + 34 >> 1] | 0;
       if (!(u << 16 >> 16)) if (!(b[ea + 30 >> 1] | 0)) Cb = 0; else Pb = 1619; else Pb = 1619;
       if ((Pb | 0) == 1619) {
        Pb = 0;
        Cb = 2;
       }
       c[Da >> 2] = Cb;
       v = b[ea + 40 >> 1] | 0;
       if (!(v << 16 >> 16)) if (!(b[ea + 36 >> 1] | 0)) Db = 0; else Pb = 1622; else Pb = 1622;
       if ((Pb | 0) == 1622) {
        Pb = 0;
        Db = 2;
       }
       c[Ca >> 2] = Db;
       m = b[ea + 42 >> 1] | 0;
       if (!(m << 16 >> 16)) if (!(b[ea + 38 >> 1] | 0)) Eb = 0; else Pb = 1625; else Pb = 1625;
       if ((Pb | 0) == 1625) {
        Pb = 0;
        Eb = 2;
       }
       c[Ba >> 2] = Eb;
       n = b[ea + 44 >> 1] | 0;
       o = (n | k) << 16 >> 16 ? 2 : 0;
       c[Aa >> 2] = o;
       w = b[ea + 46 >> 1] | 0;
       p = (w | u) << 16 >> 16 ? 2 : 0;
       c[za >> 2] = p;
       x = b[ea + 52 >> 1] | 0;
       E = (x | v) << 16 >> 16 ? 2 : 0;
       c[ya >> 2] = E;
       q = b[ea + 54 >> 1] | 0;
       D = (q | m) << 16 >> 16 ? 2 : 0;
       c[xa >> 2] = D;
       r = b[ea + 48 >> 1] | 0;
       B = (r | n) << 16 >> 16 ? 2 : 0;
       c[ua >> 2] = B;
       y = b[ea + 50 >> 1] | 0;
       g = (y | w) << 16 >> 16 ? 2 : 0;
       c[ra >> 2] = g;
       C = b[ea + 56 >> 1] | 0;
       A = (C | x) << 16 >> 16 ? 2 : 0;
       c[qa >> 2] = A;
       s = b[ea + 58 >> 1] | 0;
       z = (s | q) << 16 >> 16 ? 2 : 0;
       c[pa >> 2] = z;
       t = b[ea + 30 >> 1] | 0;
       if (!(t << 16 >> 16)) if (!(b[j >> 1] | 0)) Fb = 0; else Pb = 1628; else Pb = 1628;
       if ((Pb | 0) == 1628) {
        Pb = 0;
        Fb = 2;
       }
       c[Ya >> 2] = Fb;
       j = ea + 36 | 0;
       if (!(b[ea + 38 >> 1] | 0)) {
        j = b[j >> 1] | 0;
        if (!(j << 16 >> 16)) {
         Gb = 0;
         Hb = 0;
        } else {
         jb = j;
         Pb = 1632;
        }
       } else {
        jb = b[j >> 1] | 0;
        Pb = 1632;
       }
       if ((Pb | 0) == 1632) {
        Pb = 0;
        Gb = 2;
        Hb = jb;
       }
       c[Wa >> 2] = Gb;
       c[Va >> 2] = (u | k) << 16 >> 16 ? 2 : 0;
       c[Ta >> 2] = (m | v) << 16 >> 16 ? 2 : 0;
       c[Ra >> 2] = (w | n) << 16 >> 16 ? 2 : 0;
       c[Ia >> 2] = (q | x) << 16 >> 16 ? 2 : 0;
       c[Ga >> 2] = y << 16 >> 16 == 0 ? (r << 16 >> 16 ? 2 : 0) : 2;
       c[Qb + 688 + 124 >> 2] = s << 16 >> 16 == 0 ? (C << 16 >> 16 ? 2 : 0) : 2;
       j = b[ea + 150 >> 1] | 0;
       k = b[ea + 138 >> 1] | 0;
       do if (!((Hb | t) << 16 >> 16)) {
        Ob = (b[ea + 148 >> 1] | 0) - (b[ea + 136 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         j = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         j = 1;
         break;
        }
        j = (c[ea + 120 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else j = 2; while (0);
       c[Xa >> 2] = j;
       j = b[ea + 158 >> 1] | 0;
       k = b[ea + 146 >> 1] | 0;
       do if (!((v | u) << 16 >> 16)) {
        Ob = (b[ea + 156 >> 1] | 0) - (b[ea + 144 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         j = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         j = 1;
         break;
        }
        j = (c[ea + 120 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else j = 2; while (0);
       c[Ua >> 2] = j;
       j = b[ea + 182 >> 1] | 0;
       k = b[ea + 170 >> 1] | 0;
       do if (!((x | w) << 16 >> 16)) {
        Ob = (b[ea + 180 >> 1] | 0) - (b[ea + 168 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         j = 1;
         break;
        }
        if ((((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) | 0) > 3) {
         j = 1;
         break;
        }
        j = (c[ea + 128 >> 2] | 0) != (c[ea + 124 >> 2] | 0) & 1;
       } else j = 2; while (0);
       c[Ka >> 2] = j;
       if ((C | y) << 16 >> 16) {
        s = 2;
        t = 14;
        r = D;
        q = E;
        n = Eb;
        m = Db;
        k = Cb;
        j = Bb;
        break R;
       }
       Ob = (b[ea + 188 >> 1] | 0) - (b[ea + 176 >> 1] | 0) | 0;
       if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
        s = 1;
        t = 14;
        r = D;
        q = E;
        n = Eb;
        m = Db;
        k = Cb;
        j = Bb;
        break R;
       }
       Ob = (b[ea + 190 >> 1] | 0) - (b[ea + 178 >> 1] | 0) | 0;
       if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
        s = 1;
        t = 14;
        r = D;
        q = E;
        n = Eb;
        m = Db;
        k = Cb;
        j = Bb;
        break R;
       }
       s = (c[ea + 128 >> 2] | 0) != (c[ea + 124 >> 2] | 0) & 1;
       t = 14;
       r = D;
       q = E;
       n = Eb;
       m = Db;
       k = Cb;
       j = Bb;
       break R;
      }
     default:
      {
       C = b[ea + 32 >> 1] | 0;
       n = b[ea + 28 >> 1] | 0;
       D = b[ea + 142 >> 1] | 0;
       s = b[ea + 134 >> 1] | 0;
       if (!((n | C) << 16 >> 16)) {
        j = (b[ea + 140 >> 1] | 0) - (b[ea + 132 >> 1] | 0) | 0;
        j = ((((j | 0) < 0 ? 0 - j | 0 : j) | 0) > 3 ? 1 : (((D - s | 0) < 0 ? 0 - (D - s) | 0 : D - s | 0) | 0) > 3) & 1;
       } else j = 2;
       c[Ea >> 2] = j;
       E = b[ea + 34 >> 1] | 0;
       t = b[ea + 30 >> 1] | 0;
       F = b[ea + 146 >> 1] | 0;
       u = b[ea + 138 >> 1] | 0;
       if (!((t | E) << 16 >> 16)) {
        k = (b[ea + 144 >> 1] | 0) - (b[ea + 136 >> 1] | 0) | 0;
        k = ((((k | 0) < 0 ? 0 - k | 0 : k) | 0) > 3 ? 1 : (((F - u | 0) < 0 ? 0 - (F - u) | 0 : F - u | 0) | 0) > 3) & 1;
       } else k = 2;
       c[Da >> 2] = k;
       G = b[ea + 40 >> 1] | 0;
       v = b[ea + 36 >> 1] | 0;
       H = b[ea + 158 >> 1] | 0;
       w = b[ea + 150 >> 1] | 0;
       if (!((v | G) << 16 >> 16)) {
        m = (b[ea + 156 >> 1] | 0) - (b[ea + 148 >> 1] | 0) | 0;
        m = ((((m | 0) < 0 ? 0 - m | 0 : m) | 0) > 3 ? 1 : (((H - w | 0) < 0 ? 0 - (H - w) | 0 : H - w | 0) | 0) > 3) & 1;
       } else m = 2;
       c[Ca >> 2] = m;
       f = b[ea + 42 >> 1] | 0;
       x = b[ea + 38 >> 1] | 0;
       I = b[ea + 162 >> 1] | 0;
       y = b[ea + 154 >> 1] | 0;
       if (!((x | f) << 16 >> 16)) {
        Y = (b[ea + 160 >> 1] | 0) - (b[ea + 152 >> 1] | 0) | 0;
        Y = ((((Y | 0) < 0 ? 0 - Y | 0 : Y) | 0) > 3 ? 1 : (((I - y | 0) < 0 ? 0 - (I - y) | 0 : I - y | 0) | 0) > 3) & 1;
       } else Y = 2;
       c[Ba >> 2] = Y;
       J = b[ea + 44 >> 1] | 0;
       K = b[ea + 166 >> 1] | 0;
       do if (!((J | C) << 16 >> 16)) {
        Ob = (b[ea + 164 >> 1] | 0) - (b[ea + 140 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         o = 1;
         break;
        }
        if ((((K - D | 0) < 0 ? 0 - (K - D) | 0 : K - D | 0) | 0) > 3) {
         o = 1;
         break;
        }
        o = (c[ea + 124 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else o = 2; while (0);
       c[Aa >> 2] = o;
       L = b[ea + 46 >> 1] | 0;
       M = b[ea + 170 >> 1] | 0;
       do if (!((L | E) << 16 >> 16)) {
        Ob = (b[ea + 168 >> 1] | 0) - (b[ea + 144 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         p = 1;
         break;
        }
        if ((((M - F | 0) < 0 ? 0 - (M - F) | 0 : M - F | 0) | 0) > 3) {
         p = 1;
         break;
        }
        p = (c[ea + 124 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else p = 2; while (0);
       c[za >> 2] = p;
       O = b[ea + 52 >> 1] | 0;
       P = b[ea + 182 >> 1] | 0;
       do if (!((O | G) << 16 >> 16)) {
        Ob = (b[ea + 180 >> 1] | 0) - (b[ea + 156 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         q = 1;
         break;
        }
        if ((((P - H | 0) < 0 ? 0 - (P - H) | 0 : P - H | 0) | 0) > 3) {
         q = 1;
         break;
        }
        q = (c[ea + 128 >> 2] | 0) != (c[ea + 120 >> 2] | 0) & 1;
       } else q = 2; while (0);
       c[ya >> 2] = q;
       Q = b[ea + 54 >> 1] | 0;
       R = b[ea + 186 >> 1] | 0;
       do if (!((Q | f) << 16 >> 16)) {
        Ob = (b[ea + 184 >> 1] | 0) - (b[ea + 160 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         r = 1;
         break;
        }
        if ((((R - I | 0) < 0 ? 0 - (R - I) | 0 : R - I | 0) | 0) > 3) {
         r = 1;
         break;
        }
        r = (c[ea + 128 >> 2] | 0) != (c[ea + 120 >> 2] | 0) & 1;
       } else r = 2; while (0);
       c[xa >> 2] = r;
       S = b[ea + 48 >> 1] | 0;
       T = b[ea + 174 >> 1] | 0;
       if (!((S | J) << 16 >> 16)) {
        B = (b[ea + 172 >> 1] | 0) - (b[ea + 164 >> 1] | 0) | 0;
        B = ((((B | 0) < 0 ? 0 - B | 0 : B) | 0) > 3 ? 1 : (((T - K | 0) < 0 ? 0 - (T - K) | 0 : T - K | 0) | 0) > 3) & 1;
       } else B = 2;
       c[ua >> 2] = B;
       h = b[ea + 50 >> 1] | 0;
       U = b[ea + 178 >> 1] | 0;
       if (!((h | L) << 16 >> 16)) {
        g = (b[ea + 176 >> 1] | 0) - (b[ea + 168 >> 1] | 0) | 0;
        g = ((((g | 0) < 0 ? 0 - g | 0 : g) | 0) > 3 ? 1 : (((U - M | 0) < 0 ? 0 - (U - M) | 0 : U - M | 0) | 0) > 3) & 1;
       } else g = 2;
       c[ra >> 2] = g;
       i = b[ea + 56 >> 1] | 0;
       V = b[ea + 190 >> 1] | 0;
       if (!((i | O) << 16 >> 16)) {
        A = (b[ea + 188 >> 1] | 0) - (b[ea + 180 >> 1] | 0) | 0;
        A = ((((A | 0) < 0 ? 0 - A | 0 : A) | 0) > 3 ? 1 : (((V - P | 0) < 0 ? 0 - (V - P) | 0 : V - P | 0) | 0) > 3) & 1;
       } else A = 2;
       c[qa >> 2] = A;
       W = b[ea + 58 >> 1] | 0;
       X = b[ea + 194 >> 1] | 0;
       if (!((W | Q) << 16 >> 16)) {
        z = (b[ea + 192 >> 1] | 0) - (b[ea + 184 >> 1] | 0) | 0;
        z = ((((z | 0) < 0 ? 0 - z | 0 : z) | 0) > 3 ? 1 : (((X - R | 0) < 0 ? 0 - (X - R) | 0 : X - R | 0) | 0) > 3) & 1;
       } else z = 2;
       c[pa >> 2] = z;
       if (!((t | n) << 16 >> 16)) {
        n = (b[ea + 136 >> 1] | 0) - (b[ea + 132 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((u - s | 0) < 0 ? 0 - (u - s) | 0 : u - s | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Ya >> 2] = n;
       do if (!((v | t) << 16 >> 16)) {
        Ob = (b[ea + 148 >> 1] | 0) - (b[ea + 136 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         n = 1;
         break;
        }
        if ((((w - u | 0) < 0 ? 0 - (w - u) | 0 : w - u | 0) | 0) > 3) {
         n = 1;
         break;
        }
        n = (c[ea + 120 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else n = 2; while (0);
       c[Xa >> 2] = n;
       if (!((x | v) << 16 >> 16)) {
        n = (b[ea + 152 >> 1] | 0) - (b[ea + 148 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((y - w | 0) < 0 ? 0 - (y - w) | 0 : y - w | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Wa >> 2] = n;
       if (!((E | C) << 16 >> 16)) {
        n = (b[ea + 144 >> 1] | 0) - (b[ea + 140 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((F - D | 0) < 0 ? 0 - (F - D) | 0 : F - D | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Va >> 2] = n;
       do if (!((G | E) << 16 >> 16)) {
        Ob = (b[ea + 156 >> 1] | 0) - (b[ea + 144 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         n = 1;
         break;
        }
        if ((((H - F | 0) < 0 ? 0 - (H - F) | 0 : H - F | 0) | 0) > 3) {
         n = 1;
         break;
        }
        n = (c[ea + 120 >> 2] | 0) != (c[ea + 116 >> 2] | 0) & 1;
       } else n = 2; while (0);
       c[Ua >> 2] = n;
       if (!((f | G) << 16 >> 16)) {
        n = (b[ea + 160 >> 1] | 0) - (b[ea + 156 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((I - H | 0) < 0 ? 0 - (I - H) | 0 : I - H | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Ta >> 2] = n;
       if (!((L | J) << 16 >> 16)) {
        n = (b[ea + 168 >> 1] | 0) - (b[ea + 164 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((M - K | 0) < 0 ? 0 - (M - K) | 0 : M - K | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Ra >> 2] = n;
       do if (!((O | L) << 16 >> 16)) {
        Ob = (b[ea + 180 >> 1] | 0) - (b[ea + 168 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         n = 1;
         break;
        }
        if ((((P - M | 0) < 0 ? 0 - (P - M) | 0 : P - M | 0) | 0) > 3) {
         n = 1;
         break;
        }
        n = (c[ea + 128 >> 2] | 0) != (c[ea + 124 >> 2] | 0) & 1;
       } else n = 2; while (0);
       c[Ka >> 2] = n;
       if (!((Q | O) << 16 >> 16)) {
        n = (b[ea + 184 >> 1] | 0) - (b[ea + 180 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((R - P | 0) < 0 ? 0 - (R - P) | 0 : R - P | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Ia >> 2] = n;
       if (!((h | S) << 16 >> 16)) {
        n = (b[ea + 176 >> 1] | 0) - (b[ea + 172 >> 1] | 0) | 0;
        n = ((((n | 0) < 0 ? 0 - n | 0 : n) | 0) > 3 ? 1 : (((U - T | 0) < 0 ? 0 - (U - T) | 0 : U - T | 0) | 0) > 3) & 1;
       } else n = 2;
       c[Ga >> 2] = n;
       do if (!((i | h) << 16 >> 16)) {
        Ob = (b[ea + 188 >> 1] | 0) - (b[ea + 176 >> 1] | 0) | 0;
        if ((((Ob | 0) < 0 ? 0 - Ob | 0 : Ob) | 0) > 3) {
         n = 1;
         break;
        }
        if ((((V - U | 0) < 0 ? 0 - (V - U) | 0 : V - U | 0) | 0) > 3) {
         n = 1;
         break;
        }
        n = (c[ea + 128 >> 2] | 0) != (c[ea + 124 >> 2] | 0) & 1;
       } else n = 2; while (0);
       c[Fa >> 2] = n;
       if ((W | i) << 16 >> 16) {
        s = 2;
        t = 15;
        n = Y;
        break R;
       }
       s = (b[ea + 192 >> 1] | 0) - (b[ea + 188 >> 1] | 0) | 0;
       s = ((((s | 0) < 0 ? 0 - s | 0 : s) | 0) > 3 ? 1 : (((X - V | 0) < 0 ? 0 - (X - V) | 0 : X - V | 0) | 0) > 3) & 1;
       t = 15;
       n = Y;
       break R;
      }
     } while (0);
     c[Qb + 688 + (t << 3) + 4 >> 2] = s;
     if (gb | 0) break;
     if (!(A | z | g | B | r | q | p | o | n | m | k | j | c[Ya >> 2] | c[Xa >> 2] | c[Wa >> 2] | c[Va >> 2] | c[Ua >> 2] | c[Ta >> 2] | c[Ra >> 2] | c[Ka >> 2] | c[Ia >> 2] | c[Ga >> 2] | c[Fa >> 2] | c[Qb + 688 + 124 >> 2])) break O;
    } while (0);
    I = ea + 20 | 0;
    p = c[I >> 2] | 0;
    K = ea + 12 | 0;
    q = c[K >> 2] | 0;
    s = (q + p | 0) > 0 ? ((q + p | 0) < 51 ? q + p | 0 : 51) : 0;
    L = ea + 16 | 0;
    r = c[L >> 2] | 0;
    k = d[6930 + s >> 0] | 0;
    c[Qb + 648 + 28 >> 2] = k;
    m = d[6982 + ((r + p | 0) > 0 ? ((r + p | 0) < 51 ? r + p | 0 : 51) : 0) >> 0] | 0;
    c[Qb + 648 + 32 >> 2] = m;
    c[Qb + 648 + 24 >> 2] = 7034 + (s * 3 | 0);
    if (!$) {
     j = c[Z + 20 >> 2] | 0;
     if ((j | 0) == (p | 0)) {
      j = 7034 + (s * 3 | 0) | 0;
      n = k;
      o = m;
     } else {
      n = ((p + 1 + j | 0) >>> 1) + q | 0;
      n = (n | 0) > 0 ? ((n | 0) < 51 ? n : 51) : 0;
      o = ((p + 1 + j | 0) >>> 1) + r | 0;
      j = 7034 + (n * 3 | 0) | 0;
      n = d[6930 + n >> 0] | 0;
      o = d[6982 + ((o | 0) > 0 ? ((o | 0) < 51 ? o : 51) : 0) >> 0] | 0;
     }
     c[Qb + 648 + 4 >> 2] = n;
     c[Qb + 648 + 8 >> 2] = o;
     c[Qb + 648 >> 2] = j;
    }
    if (!_) {
     j = c[(c[ba >> 2] | 0) + 20 >> 2] | 0;
     if ((j | 0) == (p | 0)) j = 7034 + (s * 3 | 0) | 0; else {
      Ob = ((p + 1 + j | 0) >>> 1) + q | 0;
      Ob = (Ob | 0) > 0 ? ((Ob | 0) < 51 ? Ob : 51) : 0;
      m = ((p + 1 + j | 0) >>> 1) + r | 0;
      m = d[6982 + ((m | 0) > 0 ? ((m | 0) < 51 ? m : 51) : 0) >> 0] | 0;
      k = d[6930 + Ob >> 0] | 0;
      j = 7034 + (Ob * 3 | 0) | 0;
     }
     c[Qb + 648 + 16 >> 2] = k;
     c[Qb + 648 + 20 >> 2] = m;
     c[Qb + 648 + 12 >> 2] = j;
    }
    J = N(da, fa) | 0;
    F = (c[eb >> 2] | 0) + (J << 8) + (ca << 4) | 0;
    G = Qb + 688 | 0;
    H = 0;
    f = 3;
    while (1) {
     j = c[G + 4 >> 2] | 0;
     if (j | 0) La(F, j, bb, fa << 4);
     j = c[G + 12 >> 2] | 0;
     if (j | 0) La(F + 4 | 0, j, ab, fa << 4);
     D = G + 16 | 0;
     j = c[G + 20 >> 2] | 0;
     if (j | 0) La(F + 8 | 0, j, ab, fa << 4);
     E = G + 24 | 0;
     j = c[G + 28 >> 2] | 0;
     if (j | 0) La(F + 12 | 0, j, ab, fa << 4);
     B = c[G >> 2] | 0;
     C = G + 8 | 0;
     j = c[C >> 2] | 0;
     S : do if ((B | 0) == (j | 0)) {
      if ((B | 0) != (c[D >> 2] | 0)) {
       Pb = 1760;
       break;
      }
      if ((B | 0) != (c[E >> 2] | 0)) {
       Pb = 1760;
       break;
      }
      if (!B) break;
      if (B >>> 0 < 4) {
       r = d[(c[Qb + 648 + (H * 12 | 0) >> 2] | 0) + (B + -1) >> 0] | 0;
       s = Qb + 648 + (H * 12 | 0) + 4 | 0;
       t = Qb + 648 + (H * 12 | 0) + 8 | 0;
       p = 16;
       q = F;
       while (1) {
        k = q + (0 - (fa << 4) << 1) | 0;
        u = q + (0 - (fa << 4)) | 0;
        o = q + (fa << 4) | 0;
        v = a[o >> 0] | 0;
        w = d[u >> 0] | 0;
        x = d[q >> 0] | 0;
        do if (((w - x | 0) < 0 ? 0 - (w - x) | 0 : w - x | 0) >>> 0 < (c[s >> 2] | 0) >>> 0) {
         y = d[k >> 0] | 0;
         n = c[t >> 2] | 0;
         if (((y - w | 0) < 0 ? 0 - (y - w) | 0 : y - w | 0) >>> 0 >= n >>> 0) break;
         if ((((v & 255) - x | 0) < 0 ? 0 - ((v & 255) - x) | 0 : (v & 255) - x | 0) >>> 0 >= n >>> 0) break;
         m = d[q + Za >> 0] | 0;
         if (((m - w | 0) < 0 ? 0 - (m - w) | 0 : m - w | 0) >>> 0 < n >>> 0) {
          a[k >> 0] = ((((w + 1 + x | 0) >>> 1) - (y << 1) + m >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((w + 1 + x | 0) >>> 1) - (y << 1) + m >> 1 | 0) > (r | 0) ? r : ((w + 1 + x | 0) >>> 1) - (y << 1) + m >> 1) + y;
          k = r + 1 | 0;
          n = c[t >> 2] | 0;
         } else k = r;
         m = d[q + (fa << 5) >> 0] | 0;
         if (((m - x | 0) < 0 ? 0 - (m - x) | 0 : m - x | 0) >>> 0 < n >>> 0) {
          a[o >> 0] = ((((w + 1 + x | 0) >>> 1) - ((v & 255) << 1) + m >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((w + 1 + x | 0) >>> 1) - ((v & 255) << 1) + m >> 1 | 0) > (r | 0) ? r : ((w + 1 + x | 0) >>> 1) - ((v & 255) << 1) + m >> 1) + (v & 255);
          k = k + 1 | 0;
         }
         Z = 0 - k | 0;
         Z = (4 - (v & 255) + (x - w << 2) + y >> 3 | 0) < (Z | 0) ? Z : (4 - (v & 255) + (x - w << 2) + y >> 3 | 0) > (k | 0) ? k : 4 - (v & 255) + (x - w << 2) + y >> 3;
         Ob = a[6162 + (x - Z) >> 0] | 0;
         a[u >> 0] = a[6162 + (Z + w) >> 0] | 0;
         a[q >> 0] = Ob;
        } while (0);
        p = p + -1 | 0;
        if (!p) break S; else q = q + 1 | 0;
       }
      }
      A = Qb + 648 + (H * 12 | 0) + 4 | 0;
      g = Qb + 648 + (H * 12 | 0) + 8 | 0;
      y = 16;
      z = F;
      while (1) {
       r = z + (0 - (fa << 4) << 1) | 0;
       p = z + (0 - (fa << 4)) | 0;
       u = z + (fa << 4) | 0;
       w = a[u >> 0] | 0;
       v = d[p >> 0] | 0;
       m = d[z >> 0] | 0;
       n = (v - m | 0) < 0 ? 0 - (v - m) | 0 : v - m | 0;
       q = c[A >> 2] | 0;
       do if (n >>> 0 < q >>> 0) {
        o = d[r >> 0] | 0;
        s = c[g >> 2] | 0;
        if (((o - v | 0) < 0 ? 0 - (o - v) | 0 : o - v | 0) >>> 0 >= s >>> 0) break;
        if ((((w & 255) - m | 0) < 0 ? 0 - ((w & 255) - m) | 0 : (w & 255) - m | 0) >>> 0 >= s >>> 0) break;
        t = z + Za | 0;
        k = z + (fa << 5) | 0;
        x = a[k >> 0] | 0;
        do if (n >>> 0 < ((q >>> 2) + 2 | 0) >>> 0) {
         n = d[t >> 0] | 0;
         if (((n - v | 0) < 0 ? 0 - (n - v) | 0 : n - v | 0) >>> 0 < s >>> 0) {
          a[p >> 0] = ((w & 255) + 4 + (m + v + o << 1) + n | 0) >>> 3;
          a[r >> 0] = (m + v + o + 2 + n | 0) >>> 2;
          p = t;
          q = 3;
          r = d[z + (0 - (fa << 4) << 2) >> 0] | 0;
          s = m + v + o + 4 | 0;
          n = n * 3 | 0;
         } else {
          q = 2;
          r = o;
          s = v + 2 | 0;
          n = w & 255;
         }
         a[p >> 0] = (s + n + (r << 1) | 0) >>> q;
         if ((((x & 255) - m | 0) < 0 ? 0 - ((x & 255) - m) | 0 : (x & 255) - m | 0) >>> 0 >= (c[g >> 2] | 0) >>> 0) {
          p = 2;
          q = 2;
          n = w & 255;
          k = z;
          break;
         }
         a[z >> 0] = ((m + v + (w & 255) << 1) + 4 + o + (x & 255) | 0) >>> 3;
         a[u >> 0] = (m + v + (w & 255) + 2 + (x & 255) | 0) >>> 2;
         p = 3;
         q = 4;
         o = m + v + (w & 255) | 0;
         n = d[z + (fa * 48 | 0) >> 0] | 0;
         m = (x & 255) * 3 | 0;
        } else {
         a[p >> 0] = (v + 2 + (w & 255) + (o << 1) | 0) >>> 2;
         p = 2;
         q = 2;
         n = w & 255;
         k = z;
        } while (0);
        a[k >> 0] = ((n << 1) + m + o + q | 0) >>> p;
       } while (0);
       y = y + -1 | 0;
       if (!y) break; else z = z + 1 | 0;
      }
     } else Pb = 1760; while (0);
     do if ((Pb | 0) == 1760) {
      Pb = 0;
      if (B) {
       Ma(F, B, Qb + 648 + (H * 12 | 0) | 0, fa << 4);
       j = c[C >> 2] | 0;
      }
      if (j | 0) Ma(F + 4 | 0, j, Qb + 648 + (H * 12 | 0) | 0, fa << 4);
      j = c[D >> 2] | 0;
      if (j | 0) Ma(F + 8 | 0, j, Qb + 648 + (H * 12 | 0) | 0, fa << 4);
      j = c[E >> 2] | 0;
      if (!j) break;
      Ma(F + 12 | 0, j, Qb + 648 + (H * 12 | 0) | 0, fa << 4);
     } while (0);
     if (!f) break; else {
      F = F + (fa << 6) | 0;
      G = G + 32 | 0;
      H = 2;
      f = f + -1 | 0;
     }
    }
    t = c[ea + 24 >> 2] | 0;
    r = c[I >> 2] | 0;
    s = c[80 + (((r + t | 0) > 0 ? ((r + t | 0) < 51 ? r + t | 0 : 51) : 0) << 2) >> 2] | 0;
    q = c[K >> 2] | 0;
    u = (q + s | 0) > 0 ? ((q + s | 0) < 51 ? q + s | 0 : 51) : 0;
    p = c[L >> 2] | 0;
    k = d[6930 + u >> 0] | 0;
    c[Qb + 648 + 28 >> 2] = k;
    m = d[6982 + ((p + s | 0) > 0 ? ((p + s | 0) < 51 ? p + s | 0 : 51) : 0) >> 0] | 0;
    c[Qb + 648 + 32 >> 2] = m;
    c[Qb + 648 + 24 >> 2] = 7034 + (u * 3 | 0);
    if (!$) {
     j = c[(c[aa >> 2] | 0) + 20 >> 2] | 0;
     if ((j | 0) == (r | 0)) {
      j = 7034 + (u * 3 | 0) | 0;
      n = m;
      o = k;
     } else {
      n = (s + 1 + (c[80 + (((j + t | 0) > 0 ? ((j + t | 0) < 51 ? j + t | 0 : 51) : 0) << 2) >> 2] | 0) | 0) >>> 1;
      o = (n + q | 0) > 0 ? ((n + q | 0) < 51 ? n + q | 0 : 51) : 0;
      j = 7034 + (o * 3 | 0) | 0;
      n = d[6982 + ((n + p | 0) > 0 ? ((n + p | 0) < 51 ? n + p | 0 : 51) : 0) >> 0] | 0;
      o = d[6930 + o >> 0] | 0;
     }
     c[Qb + 648 + 4 >> 2] = o;
     c[Qb + 648 + 8 >> 2] = n;
     c[Qb + 648 >> 2] = j;
    }
    if (!_) {
     j = c[(c[ba >> 2] | 0) + 20 >> 2] | 0;
     if ((j | 0) == (r | 0)) j = 7034 + (u * 3 | 0) | 0; else {
      m = (s + 1 + (c[80 + (((j + t | 0) > 0 ? ((j + t | 0) < 51 ? j + t | 0 : 51) : 0) << 2) >> 2] | 0) | 0) >>> 1;
      j = (m + q | 0) > 0 ? ((m + q | 0) < 51 ? m + q | 0 : 51) : 0;
      m = d[6982 + ((m + p | 0) > 0 ? ((m + p | 0) < 51 ? m + p | 0 : 51) : 0) >> 0] | 0;
      k = d[6930 + j >> 0] | 0;
      j = 7034 + (j * 3 | 0) | 0;
     }
     c[Qb + 648 + 16 >> 2] = k;
     c[Qb + 648 + 20 >> 2] = m;
     c[Qb + 648 + 12 >> 2] = j;
    }
    m = (c[eb >> 2] | 0) + (ha << 8) + (J << 6) + (ca << 3) | 0;
    n = m + (ha << 6) | 0;
    j = c[oa >> 2] | 0;
    if (j | 0) {
     Na(m, j, bb, fa << 3);
     Na(n, c[oa >> 2] | 0, bb, fa << 3);
    }
    j = c[na >> 2] | 0;
    if (j | 0) {
     Na(m + (fa << 4) | 0, j, bb, fa << 3);
     Na(n + (fa << 4) | 0, c[na >> 2] | 0, bb, fa << 3);
    }
    j = c[Xa >> 2] | 0;
    if (j | 0) {
     Na(m + 4 | 0, j, ab, fa << 3);
     Na(n + 4 | 0, c[Xa >> 2] | 0, ab, fa << 3);
    }
    j = c[Ua >> 2] | 0;
    if (j | 0) {
     Na(m + (fa << 4) + 4 | 0, j, ab, fa << 3);
     Na(n + (fa << 4) + 4 | 0, c[Ua >> 2] | 0, ab, fa << 3);
    }
    k = c[Qb + 688 >> 2] | 0;
    j = c[ka >> 2] | 0;
    do if (((k | 0) == (j | 0) ? (k | 0) == (c[ja >> 2] | 0) : 0) & (k | 0) == (c[ia >> 2] | 0)) {
     if (!k) break;
     Oa(m, k, Qb + 648 | 0, fa << 3);
     Oa(n, c[Qb + 688 >> 2] | 0, Qb + 648 | 0, fa << 3);
    } else {
     if (k) {
      Pa(m, k, Qb + 648 | 0, fa << 3);
      Pa(n, c[Qb + 688 >> 2] | 0, Qb + 648 | 0, fa << 3);
      j = c[ka >> 2] | 0;
     }
     if (j | 0) {
      Pa(m + 2 | 0, j, Qb + 648 | 0, fa << 3);
      Pa(n + 2 | 0, c[ka >> 2] | 0, Qb + 648 | 0, fa << 3);
     }
     j = c[ja >> 2] | 0;
     if (j | 0) {
      Pa(m + 4 | 0, j, Qb + 648 | 0, fa << 3);
      Pa(n + 4 | 0, c[ja >> 2] | 0, Qb + 648 | 0, fa << 3);
     }
     j = c[ia >> 2] | 0;
     if (!j) break;
     Pa(m + 6 | 0, j, Qb + 648 | 0, fa << 3);
     Pa(n + 6 | 0, c[ia >> 2] | 0, Qb + 648 | 0, fa << 3);
    } while (0);
    o = m + (fa << 5) | 0;
    m = n + (fa << 5) | 0;
    j = c[ma >> 2] | 0;
    if (j | 0) {
     Na(o, j, bb, fa << 3);
     Na(m, c[ma >> 2] | 0, bb, fa << 3);
    }
    j = c[la >> 2] | 0;
    if (j | 0) {
     Na(o + (fa << 4) | 0, j, bb, fa << 3);
     Na(m + (fa << 4) | 0, c[la >> 2] | 0, bb, fa << 3);
    }
    j = c[Ka >> 2] | 0;
    if (j | 0) {
     Na(o + 4 | 0, j, ab, fa << 3);
     Na(m + 4 | 0, c[Ka >> 2] | 0, ab, fa << 3);
    }
    j = c[Fa >> 2] | 0;
    if (j | 0) {
     Na(o + (fa << 4) + 4 | 0, j, ab, fa << 3);
     Na(m + (fa << 4) + 4 | 0, c[Fa >> 2] | 0, ab, fa << 3);
    }
    k = c[Aa >> 2] | 0;
    j = c[za >> 2] | 0;
    if (((k | 0) == (j | 0) ? (k | 0) == (c[ya >> 2] | 0) : 0) & (k | 0) == (c[xa >> 2] | 0)) {
     if (!k) break;
     Oa(o, k, ab, fa << 3);
     Oa(m, c[Aa >> 2] | 0, ab, fa << 3);
     break;
    }
    if (k) {
     Pa(o, k, ab, fa << 3);
     Pa(m, c[Aa >> 2] | 0, ab, fa << 3);
     j = c[za >> 2] | 0;
    }
    if (j | 0) {
     Pa(o + 2 | 0, j, ab, fa << 3);
     Pa(m + 2 | 0, c[za >> 2] | 0, ab, fa << 3);
    }
    j = c[ya >> 2] | 0;
    if (j | 0) {
     Pa(o + 4 | 0, j, ab, fa << 3);
     Pa(m + 4 | 0, c[ya >> 2] | 0, ab, fa << 3);
    }
    j = c[xa >> 2] | 0;
    if (!j) break;
    Pa(o + 6 | 0, j, ab, fa << 3);
    Pa(m + 6 | 0, c[xa >> 2] | 0, ab, fa << 3);
   } while (0);
   j = ca + 1 | 0;
   da = da + ((j | 0) == (fa | 0) & 1) | 0;
   if (da >>> 0 >= (c[ga >> 2] | 0) >>> 0) break; else {
    ca = (j | 0) == (fa | 0) ? 0 : j;
    ea = ea + 216 | 0;
   }
  }
 }
 c[e + 1196 >> 2] = 0;
 c[e + 1192 >> 2] = 0;
 m = c[e + 1176 >> 2] | 0;
 if (m | 0) {
  k = c[cb >> 2] | 0;
  j = 0;
  do {
   c[k + (j * 216 | 0) + 4 >> 2] = 0;
   c[k + (j * 216 | 0) + 196 >> 2] = 0;
   j = j + 1 | 0;
  } while ((j | 0) != (m | 0));
 }
 u = c[db >> 2] | 0;
 T : do if (!(c[e + 1652 >> 2] | 0)) v = 0; else {
  j = 0;
  U : while (1) {
   switch (c[e + 1656 + (j * 20 | 0) >> 2] | 0) {
   case 5:
    {
     v = 1;
     break T;
    }
   case 0:
    break U;
   default:
    {}
   }
   j = j + 1 | 0;
  }
  v = 0;
 } while (0);
 V : do switch (c[u + 16 >> 2] | 0) {
 case 0:
  {
   j = c[e + 1360 >> 2] | 0;
   if ((j | 0) == 5) {
    c[e + 1288 >> 2] = 0;
    c[e + 1284 >> 2] = 0;
    Kb = e + 1284 | 0;
    Lb = c[e + 1388 >> 2] | 0;
    Mb = 0;
    Pb = 1829;
   } else {
    k = c[e + 1284 >> 2] | 0;
    m = c[e + 1388 >> 2] | 0;
    if (k >>> 0 > m >>> 0) {
     n = c[u + 20 >> 2] | 0;
     if ((k - m | 0) >>> 0 < n >>> 1 >>> 0) {
      Kb = e + 1284 | 0;
      Lb = m;
      Mb = k;
      Pb = 1829;
     } else {
      Ib = (c[e + 1288 >> 2] | 0) + n | 0;
      Jb = e + 1284 | 0;
      Nb = m;
     }
    } else {
     Kb = e + 1284 | 0;
     Lb = m;
     Mb = k;
     Pb = 1829;
    }
   }
   do if ((Pb | 0) == 1829) {
    if (Lb >>> 0 > Mb >>> 0) {
     k = c[u + 20 >> 2] | 0;
     if ((Lb - Mb | 0) >>> 0 > k >>> 1 >>> 0) {
      Ib = (c[e + 1288 >> 2] | 0) - k | 0;
      Jb = Kb;
      Nb = Lb;
      break;
     }
    }
    Ib = c[e + 1288 >> 2] | 0;
    Jb = Kb;
    Nb = Lb;
   } while (0);
   if (!(c[e + 1364 >> 2] | 0)) {
    k = c[e + 1392 >> 2] | 0;
    k = Ib + Nb + ((k | 0) < 0 ? k : 0) | 0;
    break V;
   }
   c[e + 1288 >> 2] = Ib;
   k = c[e + 1392 >> 2] | 0;
   if (!v) {
    c[Jb >> 2] = Nb;
    k = Ib + Nb + ((k | 0) < 0 ? k : 0) | 0;
    break V;
   } else {
    c[e + 1288 >> 2] = 0;
    c[Jb >> 2] = (k | 0) < 0 ? 0 - k | 0 : 0;
    k = 0;
    break V;
   }
  }
 case 1:
  {
   j = c[e + 1360 >> 2] | 0;
   if ((j | 0) == 5) k = 0; else {
    k = c[e + 1296 >> 2] | 0;
    if ((c[e + 1292 >> 2] | 0) >>> 0 > (c[e + 1380 >> 2] | 0) >>> 0) k = (c[u + 12 >> 2] | 0) + k | 0;
   }
   r = c[u + 36 >> 2] | 0;
   if (!r) m = 0; else m = (c[e + 1380 >> 2] | 0) + k | 0;
   t = (c[e + 1364 >> 2] | 0) == 0;
   p = m + (((m | 0) != 0 & t) << 31 >> 31) | 0;
   if (p | 0) {
    s = ((p + -1 | 0) >>> 0) % (r >>> 0) | 0;
    q = ((p + -1 | 0) >>> 0) / (r >>> 0) | 0;
   } else {
    s = 0;
    q = 0;
   }
   if (!r) m = 0; else {
    o = c[u + 40 >> 2] | 0;
    m = 0;
    n = 0;
    do {
     m = (c[o + (n << 2) >> 2] | 0) + m | 0;
     n = n + 1 | 0;
    } while ((n | 0) != (r | 0));
   }
   if (p | 0) {
    m = N(m, q) | 0;
    o = c[u + 40 >> 2] | 0;
    n = 0;
    do {
     m = (c[o + (n << 2) >> 2] | 0) + m | 0;
     n = n + 1 | 0;
    } while (n >>> 0 <= s >>> 0);
   } else m = 0;
   if (t) n = (c[u + 28 >> 2] | 0) + m | 0; else n = m;
   m = (c[e + 1400 >> 2] | 0) + (c[u + 32 >> 2] | 0) | 0;
   if (!v) {
    Pb = ((m | 0) < 0 ? m : 0) + n + (c[e + 1396 >> 2] | 0) | 0;
    c[e + 1296 >> 2] = k;
    c[e + 1292 >> 2] = c[e + 1380 >> 2];
    k = Pb;
    break V;
   } else {
    c[e + 1296 >> 2] = 0;
    c[e + 1292 >> 2] = 0;
    k = 0;
    break V;
   }
  }
 default:
  {
   j = c[e + 1360 >> 2] | 0;
   if ((j | 0) == 5) {
    n = 0;
    k = 0;
    m = e + 1296 | 0;
   } else {
    m = c[e + 1380 >> 2] | 0;
    k = c[e + 1296 >> 2] | 0;
    if ((c[e + 1292 >> 2] | 0) >>> 0 > m >>> 0) k = (c[u + 12 >> 2] | 0) + k | 0;
    n = k;
    k = (k + m << 1) + (((c[e + 1364 >> 2] | 0) == 0) << 31 >> 31) | 0;
    m = e + 1296 | 0;
   }
   if (!v) {
    c[m >> 2] = n;
    c[e + 1292 >> 2] = c[e + 1380 >> 2];
    break V;
   } else {
    c[m >> 2] = 0;
    c[e + 1292 >> 2] = 0;
    k = 0;
    break V;
   }
  }
 } while (0);
 do if (c[fb >> 2] | 0) if (!(c[e + 1364 >> 2] | 0)) {
  Ha(e + 1220 | 0, 0, c[eb >> 2] | 0, c[e + 1380 >> 2] | 0, k, (j | 0) == 5 & 1, c[e + 1208 >> 2] | 0, c[e + 1204 >> 2] | 0);
  break;
 } else {
  Ha(e + 1220 | 0, e + 1644 | 0, c[eb >> 2] | 0, c[e + 1380 >> 2] | 0, k, (j | 0) == 5 & 1, c[e + 1208 >> 2] | 0, c[e + 1204 >> 2] | 0);
  break;
 } while (0);
 c[e + 1184 >> 2] = 0;
 c[fb >> 2] = 0;
 e = 1;
 l = Qb;
 return e | 0;
}

function ta(f, g, h, i, j, k, m, n) {
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 m = m | 0;
 n = n | 0;
 var o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0, H = 0, I = 0, J = 0, K = 0, L = 0;
 L = l;
 l = l + 96 | 0;
 G = c[g >> 2] | 0;
 c[f >> 2] = G;
 o = (c[f + 196 >> 2] | 0) + 1 | 0;
 c[f + 196 >> 2] = o;
 I = c[h + 4 >> 2] | 0;
 J = N(c[h + 8 >> 2] | 0, I) | 0;
 H = c[h >> 2] | 0;
 c[h + 12 >> 2] = H + (((k >>> 0) % (I >>> 0) | 0) << 4) + (k - ((k >>> 0) % (I >>> 0) | 0) << 8);
 I = H + (J << 8) + (k - ((k >>> 0) % (I >>> 0) | 0) << 6) + (((k >>> 0) % (I >>> 0) | 0) << 3) | 0;
 c[h + 16 >> 2] = I;
 c[h + 20 >> 2] = I + (J << 6);
 if ((G | 0) == 31) {
  c[f + 20 >> 2] = 0;
  if (o >>> 0 > 1) {
   b[f + 28 >> 1] = 16;
   b[f + 30 >> 1] = 16;
   b[f + 32 >> 1] = 16;
   b[f + 34 >> 1] = 16;
   b[f + 36 >> 1] = 16;
   b[f + 38 >> 1] = 16;
   b[f + 40 >> 1] = 16;
   b[f + 42 >> 1] = 16;
   b[f + 44 >> 1] = 16;
   b[f + 46 >> 1] = 16;
   b[f + 48 >> 1] = 16;
   b[f + 50 >> 1] = 16;
   b[f + 52 >> 1] = 16;
   b[f + 54 >> 1] = 16;
   b[f + 56 >> 1] = 16;
   b[f + 58 >> 1] = 16;
   b[f + 60 >> 1] = 16;
   b[f + 62 >> 1] = 16;
   b[f + 64 >> 1] = 16;
   b[f + 66 >> 1] = 16;
   b[f + 68 >> 1] = 16;
   b[f + 70 >> 1] = 16;
   b[f + 72 >> 1] = 16;
   b[f + 74 >> 1] = 16;
   n = 0;
   l = L;
   return n | 0;
  }
  j = n;
  q = g + 328 | 0;
  o = f + 28 | 0;
  p = 23;
  while (1) {
   b[o >> 1] = 16;
   a[j >> 0] = c[q >> 2];
   a[j + 1 >> 0] = c[q + 4 >> 2];
   a[j + 2 >> 0] = c[q + 8 >> 2];
   a[j + 3 >> 0] = c[q + 12 >> 2];
   a[j + 4 >> 0] = c[q + 16 >> 2];
   a[j + 5 >> 0] = c[q + 20 >> 2];
   a[j + 6 >> 0] = c[q + 24 >> 2];
   a[j + 7 >> 0] = c[q + 28 >> 2];
   a[j + 8 >> 0] = c[q + 32 >> 2];
   a[j + 9 >> 0] = c[q + 36 >> 2];
   a[j + 10 >> 0] = c[q + 40 >> 2];
   a[j + 11 >> 0] = c[q + 44 >> 2];
   a[j + 12 >> 0] = c[q + 48 >> 2];
   a[j + 13 >> 0] = c[q + 52 >> 2];
   a[j + 14 >> 0] = c[q + 56 >> 2];
   a[j + 15 >> 0] = c[q + 60 >> 2];
   if (!p) break; else {
    j = j + 16 | 0;
    q = q + 64 | 0;
    o = o + 2 | 0;
    p = p + -1 | 0;
   }
  }
  Ka(h, n);
  n = 0;
  l = L;
  return n | 0;
 }
 do if (!G) {
  o = f + 28 | 0;
  q = o + 54 | 0;
  do {
   a[o >> 0] = 0;
   o = o + 1 | 0;
  } while ((o | 0) < (q | 0));
  c[f + 20 >> 2] = c[j >> 2];
  q = 0;
 } else {
  o = f + 28 | 0;
  p = g + 272 | 0;
  q = o + 54 | 0;
  do {
   a[o >> 0] = a[p >> 0] | 0;
   o = o + 1 | 0;
   p = p + 1 | 0;
  } while ((o | 0) < (q | 0));
  p = c[g + 8 >> 2] | 0;
  o = c[j >> 2] | 0;
  do if (p) {
   c[j >> 2] = o + p;
   if ((o + p | 0) < 0) {
    c[j >> 2] = o + p + 52;
    o = o + p + 52 | 0;
    break;
   }
   if ((o + p | 0) > 51) {
    c[j >> 2] = o + p + -52;
    o = o + p + -52 | 0;
   } else o = o + p | 0;
  } while (0);
  c[f + 20 >> 2] = o;
  a : do if (G >>> 0 > 6) {
   if (!(b[f + 76 >> 1] | 0)) {
    p = f + 28 | 0;
    o = g + 328 | 0;
    q = g + 1992 | 0;
    j = 320;
    r = 15;
   } else {
    F = a[4880 + o >> 0] | 0;
    p = a[4828 + o >> 0] | 0;
    y = c[g + 1872 >> 2] | 0;
    u = c[g + 1884 >> 2] | 0;
    w = c[g + 1880 >> 2] | 0;
    A = c[g + 1896 >> 2] | 0;
    J = c[g + 1876 >> 2] | 0;
    s = c[g + 1888 >> 2] | 0;
    z = c[g + 1892 >> 2] | 0;
    x = c[g + 1912 >> 2] | 0;
    I = c[g + 1900 >> 2] | 0;
    E = c[g + 1904 >> 2] | 0;
    B = c[g + 1908 >> 2] | 0;
    H = c[g + 1916 >> 2] | 0;
    v = c[g + 1864 >> 2] | 0;
    t = c[g + 1868 >> 2] | 0;
    q = t + s + (v + u) | 0;
    c[g + 1864 >> 2] = q;
    j = t - s + (v - u) | 0;
    c[g + 1868 >> 2] = j;
    r = v - u - (t - s) | 0;
    c[g + 1872 >> 2] = r;
    s = v + u - (t + s) | 0;
    c[g + 1876 >> 2] = s;
    t = x + w + (z + y) | 0;
    c[g + 1880 >> 2] = t;
    u = w - x + (y - z) | 0;
    c[g + 1884 >> 2] = u;
    v = y - z - (w - x) | 0;
    c[g + 1888 >> 2] = v;
    w = z + y - (x + w) | 0;
    c[g + 1892 >> 2] = w;
    x = H + A + (B + J) | 0;
    c[g + 1896 >> 2] = x;
    y = A - H + (J - B) | 0;
    c[g + 1900 >> 2] = y;
    z = J - B - (A - H) | 0;
    c[g + 1904 >> 2] = z;
    A = B + J - (H + A) | 0;
    c[g + 1908 >> 2] = A;
    H = c[g + 1920 >> 2] | 0;
    J = c[g + 1924 >> 2] | 0;
    B = J + E + (H + I) | 0;
    c[g + 1912 >> 2] = B;
    C = E - J + (I - H) | 0;
    c[g + 1916 >> 2] = C;
    D = I - H - (E - J) | 0;
    c[g + 1920 >> 2] = D;
    E = H + I - (J + E) | 0;
    c[g + 1924 >> 2] = E;
    F = c[8 + ((F & 255) * 12 | 0) >> 2] | 0;
    if (o >>> 0 > 11) {
     o = F << (p & 255) + -2;
     c[g + 1864 >> 2] = N(o, B + t + (q + x) | 0) | 0;
     c[g + 1880 >> 2] = N(o, t - B + (q - x) | 0) | 0;
     c[g + 1896 >> 2] = N(o, q - x - (t - B) | 0) | 0;
     c[g + 1912 >> 2] = N(o, q + x - (B + t) | 0) | 0;
     c[g + 1868 >> 2] = N(o, C + u + (j + y) | 0) | 0;
     c[g + 1884 >> 2] = N(o, u - C + (j - y) | 0) | 0;
     c[g + 1900 >> 2] = N(o, j - y - (u - C) | 0) | 0;
     c[g + 1916 >> 2] = N(o, j + y - (C + u) | 0) | 0;
     c[g + 1872 >> 2] = N(o, D + v + (r + z) | 0) | 0;
     c[g + 1888 >> 2] = N(o, v - D + (r - z) | 0) | 0;
     c[g + 1904 >> 2] = N(o, r - z - (v - D) | 0) | 0;
     c[g + 1920 >> 2] = N(o, r + z - (D + v) | 0) | 0;
     c[g + 1876 >> 2] = N(o, E + w + (s + A) | 0) | 0;
     c[g + 1892 >> 2] = N(o, w - E + (s - A) | 0) | 0;
     c[g + 1908 >> 2] = N(o, s - A - (w - E) | 0) | 0;
     o = N(o, s + A - (E + w) | 0) | 0;
    } else {
     J = (o + -6 | 0) >>> 0 < 6 ? 1 : 2;
     o = 2 - (p & 255) | 0;
     c[g + 1864 >> 2] = (N(F, B + t + (q + x) | 0) | 0) + J >> o;
     c[g + 1880 >> 2] = (N(F, t - B + (q - x) | 0) | 0) + J >> o;
     c[g + 1896 >> 2] = (N(F, q - x - (t - B) | 0) | 0) + J >> o;
     c[g + 1912 >> 2] = (N(F, q + x - (B + t) | 0) | 0) + J >> o;
     c[g + 1868 >> 2] = (N(F, C + u + (j + y) | 0) | 0) + J >> o;
     c[g + 1884 >> 2] = (N(F, u - C + (j - y) | 0) | 0) + J >> o;
     c[g + 1900 >> 2] = (N(F, j - y - (u - C) | 0) | 0) + J >> o;
     c[g + 1916 >> 2] = (N(F, j + y - (C + u) | 0) | 0) + J >> o;
     c[g + 1872 >> 2] = (N(F, D + v + (r + z) | 0) | 0) + J >> o;
     c[g + 1888 >> 2] = (N(F, v - D + (r - z) | 0) | 0) + J >> o;
     c[g + 1904 >> 2] = (N(F, r - z - (v - D) | 0) | 0) + J >> o;
     c[g + 1920 >> 2] = (N(F, r + z - (D + v) | 0) | 0) + J >> o;
     c[g + 1876 >> 2] = (N(F, E + w + (s + A) | 0) | 0) + J >> o;
     c[g + 1892 >> 2] = (N(F, w - E + (s - A) | 0) | 0) + J >> o;
     c[g + 1908 >> 2] = (N(F, s - A - (w - E) | 0) | 0) + J >> o;
     o = (N(F, s + A - (E + w) | 0) | 0) + J >> o;
    }
    c[g + 1924 >> 2] = o;
    p = f + 28 | 0;
    o = g + 328 | 0;
    q = g + 1992 | 0;
    j = 320;
    r = 15;
   }
   while (1) {
    J = c[g + 1864 + (c[j >> 2] << 2) >> 2] | 0;
    j = j + 4 | 0;
    c[o >> 2] = J;
    if (!J) if (!(b[p >> 1] | 0)) c[o >> 2] = 16777215; else K = 22; else K = 22;
    if ((K | 0) == 22) {
     K = 0;
     if (ra(o, c[f + 20 >> 2] | 0, 1, c[q >> 2] | 0) | 0) {
      o = 1;
      break;
     }
    }
    o = o + 64 | 0;
    p = p + 2 | 0;
    q = q + 4 | 0;
    if (!r) {
     t = p;
     r = q;
     break a;
    } else r = r + -1 | 0;
   }
   l = L;
   return o | 0;
  } else {
   if (!(b[f + 28 >> 1] | 0)) c[g + 328 >> 2] = 16777215; else if (ra(g + 328 | 0, o, 0, c[g + 1992 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 30 >> 1] | 0)) c[g + 392 >> 2] = 16777215; else if (ra(g + 392 | 0, c[f + 20 >> 2] | 0, 0, c[g + 1996 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 32 >> 1] | 0)) c[g + 456 >> 2] = 16777215; else if (ra(g + 456 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2e3 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 34 >> 1] | 0)) c[g + 520 >> 2] = 16777215; else if (ra(g + 520 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2004 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 36 >> 1] | 0)) c[g + 584 >> 2] = 16777215; else if (ra(g + 584 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2008 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 38 >> 1] | 0)) c[g + 648 >> 2] = 16777215; else if (ra(g + 648 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2012 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 40 >> 1] | 0)) c[g + 712 >> 2] = 16777215; else if (ra(g + 712 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2016 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 42 >> 1] | 0)) c[g + 776 >> 2] = 16777215; else if (ra(g + 776 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2020 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 44 >> 1] | 0)) c[g + 840 >> 2] = 16777215; else if (ra(g + 840 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2024 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 46 >> 1] | 0)) c[g + 904 >> 2] = 16777215; else if (ra(g + 904 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2028 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 48 >> 1] | 0)) c[g + 968 >> 2] = 16777215; else if (ra(g + 968 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2032 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   if (!(b[f + 50 >> 1] | 0)) c[g + 1032 >> 2] = 16777215; else if (ra(g + 1032 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2036 >> 2] | 0) | 0) {
    n = 1;
    l = L;
    return n | 0;
   }
   do if (!(b[f + 52 >> 1] | 0)) c[g + 1096 >> 2] = 16777215; else {
    if (!(ra(g + 1096 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2040 >> 2] | 0) | 0)) break; else o = 1;
    l = L;
    return o | 0;
   } while (0);
   do if (!(b[f + 54 >> 1] | 0)) c[g + 1160 >> 2] = 16777215; else {
    if (!(ra(g + 1160 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2044 >> 2] | 0) | 0)) break; else o = 1;
    l = L;
    return o | 0;
   } while (0);
   do if (!(b[f + 56 >> 1] | 0)) c[g + 1224 >> 2] = 16777215; else {
    if (!(ra(g + 1224 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2048 >> 2] | 0) | 0)) break; else o = 1;
    l = L;
    return o | 0;
   } while (0);
   do if (!(b[f + 58 >> 1] | 0)) c[g + 1288 >> 2] = 16777215; else {
    if (!(ra(g + 1288 | 0, c[f + 20 >> 2] | 0, 0, c[g + 2052 >> 2] | 0) | 0)) break; else o = 1;
    l = L;
    return o | 0;
   } while (0);
   t = f + 60 | 0;
   o = g + 1352 | 0;
   r = g + 2056 | 0;
  } while (0);
  q = (c[f + 24 >> 2] | 0) + (c[f + 20 >> 2] | 0) | 0;
  q = (q | 0) > 0 ? ((q | 0) < 51 ? q : 51) : 0;
  s = c[80 + (q << 2) >> 2] | 0;
  if (!(b[f + 78 >> 1] | 0)) if (!(b[f + 80 >> 1] | 0)) {
   q = g + 1932 | 0;
   p = c[g + 1928 >> 2] | 0;
  } else K = 31; else K = 31;
  if ((K | 0) == 31) {
   p = c[8 + ((d[4880 + s >> 0] | 0) * 12 | 0) >> 2] | 0;
   if ((q + -6 | 0) >>> 0 < 46) {
    q = 0;
    p = p << (d[4828 + s >> 0] | 0) + -1;
   } else q = 1;
   I = c[g + 1928 >> 2] | 0;
   H = c[g + 1936 >> 2] | 0;
   F = c[g + 1932 >> 2] | 0;
   E = c[g + 1940 >> 2] | 0;
   J = (N(E + F + (H + I) | 0, p) | 0) >> q;
   c[g + 1928 >> 2] = J;
   c[g + 1932 >> 2] = (N(H + I - (E + F) | 0, p) | 0) >> q;
   c[g + 1936 >> 2] = (N(F - E + (I - H) | 0, p) | 0) >> q;
   c[g + 1940 >> 2] = (N(I - H - (F - E) | 0, p) | 0) >> q;
   E = c[g + 1944 >> 2] | 0;
   F = c[g + 1952 >> 2] | 0;
   H = c[g + 1948 >> 2] | 0;
   I = c[g + 1956 >> 2] | 0;
   c[g + 1944 >> 2] = (N(I + H + (F + E) | 0, p) | 0) >> q;
   c[g + 1948 >> 2] = (N(F + E - (I + H) | 0, p) | 0) >> q;
   c[g + 1952 >> 2] = (N(H - I + (E - F) | 0, p) | 0) >> q;
   c[g + 1956 >> 2] = (N(E - F - (H - I) | 0, p) | 0) >> q;
   q = g + 1932 | 0;
   p = J;
  }
  c[o >> 2] = p;
  if (!p) if (!(b[t >> 1] | 0)) c[o >> 2] = 16777215; else K = 36; else K = 36;
  if ((K | 0) == 36) if (ra(o, s, 1, c[r >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  j = r + 4 | 0;
  J = c[q >> 2] | 0;
  p = o + 64 | 0;
  c[p >> 2] = J;
  if (!J) if (!(b[t + 2 >> 1] | 0)) c[p >> 2] = 16777215; else K = 40; else K = 40;
  if ((K | 0) == 40) if (ra(p, s, 1, c[j >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 8 | 0;
  J = c[g + 1936 >> 2] | 0;
  q = o + 128 | 0;
  c[q >> 2] = J;
  if (!J) if (!(b[t + 4 >> 1] | 0)) c[q >> 2] = 16777215; else K = 44; else K = 44;
  if ((K | 0) == 44) if (ra(q, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 12 | 0;
  J = c[g + 1940 >> 2] | 0;
  q = o + 192 | 0;
  c[q >> 2] = J;
  if (!J) if (!(b[t + 6 >> 1] | 0)) c[q >> 2] = 16777215; else K = 48; else K = 48;
  if ((K | 0) == 48) if (ra(q, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 16 | 0;
  J = c[g + 1944 >> 2] | 0;
  q = o + 256 | 0;
  c[q >> 2] = J;
  if (!J) if (!(b[t + 8 >> 1] | 0)) c[q >> 2] = 16777215; else K = 52; else K = 52;
  if ((K | 0) == 52) if (ra(q, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 20 | 0;
  J = c[g + 1948 >> 2] | 0;
  q = o + 320 | 0;
  c[q >> 2] = J;
  if (!J) if (!(b[t + 10 >> 1] | 0)) c[q >> 2] = 16777215; else K = 56; else K = 56;
  if ((K | 0) == 56) if (ra(q, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 24 | 0;
  J = c[g + 1952 >> 2] | 0;
  q = o + 384 | 0;
  c[q >> 2] = J;
  if (!J) if (!(b[t + 12 >> 1] | 0)) c[q >> 2] = 16777215; else K = 60; else K = 60;
  if ((K | 0) == 60) if (ra(q, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  p = r + 28 | 0;
  J = c[g + 1956 >> 2] | 0;
  o = o + 448 | 0;
  c[o >> 2] = J;
  if (!J) if (!(b[t + 14 >> 1] | 0)) c[o >> 2] = 16777215; else K = 64; else K = 64;
  if ((K | 0) == 64) if (ra(o, s, 1, c[p >> 2] | 0) | 0) {
   n = 1;
   l = L;
   return n | 0;
  }
  if (G >>> 0 < 6) {
   q = c[f >> 2] | 0;
   break;
  }
  do if (k | 0) {
   r = c[h + 4 >> 2] | 0;
   s = N(c[h + 8 >> 2] | 0, r) | 0;
   t = k - (N((k >>> 0) / (r >>> 0) | 0, r) | 0) | 0;
   q = c[h >> 2] | 0;
   o = q + (N(r << 8, (k >>> 0) / (r >>> 0) | 0) | 0) + (t << 4) | 0;
   if (r >>> 0 <= k >>> 0) {
    a[L + 56 >> 0] = a[o + (0 - (r << 4 | 1)) >> 0] | 0;
    J = o + (0 - (r << 4 | 1)) + 1 + 1 | 0;
    a[L + 56 + 1 >> 0] = a[o + (0 - (r << 4 | 1)) + 1 >> 0] | 0;
    a[L + 56 + 2 >> 0] = a[J >> 0] | 0;
    a[L + 56 + 3 >> 0] = a[J + 1 >> 0] | 0;
    a[L + 56 + 4 >> 0] = a[J + 1 + 1 >> 0] | 0;
    a[L + 56 + 5 >> 0] = a[J + 1 + 1 + 1 >> 0] | 0;
    j = J + 1 + 1 + 1 + 1 + 1 | 0;
    a[L + 56 + 6 >> 0] = a[J + 1 + 1 + 1 + 1 >> 0] | 0;
    a[L + 56 + 7 >> 0] = a[j >> 0] | 0;
    a[L + 56 + 8 >> 0] = a[j + 1 >> 0] | 0;
    a[L + 56 + 9 >> 0] = a[j + 1 + 1 >> 0] | 0;
    a[L + 56 + 10 >> 0] = a[j + 1 + 1 + 1 >> 0] | 0;
    J = j + 1 + 1 + 1 + 1 + 1 | 0;
    a[L + 56 + 11 >> 0] = a[j + 1 + 1 + 1 + 1 >> 0] | 0;
    a[L + 56 + 12 >> 0] = a[J >> 0] | 0;
    a[L + 56 + 13 >> 0] = a[J + 1 >> 0] | 0;
    a[L + 56 + 14 >> 0] = a[J + 1 + 1 >> 0] | 0;
    a[L + 56 + 15 >> 0] = a[J + 1 + 1 + 1 >> 0] | 0;
    j = J + 1 + 1 + 1 + 1 + 1 | 0;
    a[L + 56 + 16 >> 0] = a[J + 1 + 1 + 1 + 1 >> 0] | 0;
    a[L + 56 + 17 >> 0] = a[j >> 0] | 0;
    a[L + 56 + 18 >> 0] = a[j + 1 >> 0] | 0;
    a[L + 56 + 19 >> 0] = a[j + 1 + 1 >> 0] | 0;
    a[L + 56 + 20 >> 0] = a[j + 1 + 1 + 1 >> 0] | 0;
    j = L + 56 + 21 | 0;
   } else j = L + 56 | 0;
   if (t | 0) {
    a[L + 24 >> 0] = a[o + -1 >> 0] | 0;
    a[L + 24 + 1 >> 0] = a[o + -1 + (r << 4) >> 0] | 0;
    p = o + -1 + (r << 4) + (r << 4) | 0;
    a[L + 24 + 2 >> 0] = a[p >> 0] | 0;
    a[L + 24 + 3 >> 0] = a[p + (r << 4) >> 0] | 0;
    a[L + 24 + 4 >> 0] = a[p + (r << 4) + (r << 4) >> 0] | 0;
    p = p + (r << 4) + (r << 4) + (r << 4) | 0;
    a[L + 24 + 5 >> 0] = a[p >> 0] | 0;
    a[L + 24 + 6 >> 0] = a[p + (r << 4) >> 0] | 0;
    a[L + 24 + 7 >> 0] = a[p + (r << 4) + (r << 4) >> 0] | 0;
    p = p + (r << 4) + (r << 4) + (r << 4) | 0;
    a[L + 24 + 8 >> 0] = a[p >> 0] | 0;
    a[L + 24 + 9 >> 0] = a[p + (r << 4) >> 0] | 0;
    a[L + 24 + 10 >> 0] = a[p + (r << 4) + (r << 4) >> 0] | 0;
    p = p + (r << 4) + (r << 4) + (r << 4) | 0;
    a[L + 24 + 11 >> 0] = a[p >> 0] | 0;
    a[L + 24 + 12 >> 0] = a[p + (r << 4) >> 0] | 0;
    a[L + 24 + 13 >> 0] = a[p + (r << 4) + (r << 4) >> 0] | 0;
    p = p + (r << 4) + (r << 4) + (r << 4) | 0;
    a[L + 24 + 14 >> 0] = a[p >> 0] | 0;
    a[L + 24 + 15 >> 0] = a[p + (r << 4) >> 0] | 0;
    p = L + 24 + 16 | 0;
   } else p = L + 24 | 0;
   o = q + (s << 8) + (N(((k >>> 0) / (r >>> 0) | 0) << 3, r << 3 & 2147483640) | 0) + (t << 3) | 0;
   if (r >>> 0 <= k >>> 0) {
    k = o + (0 - (r << 3 & 2147483640 | 1)) + 1 | 0;
    a[j >> 0] = a[o + (0 - (r << 3 & 2147483640 | 1)) >> 0] | 0;
    a[j + 1 >> 0] = a[k >> 0] | 0;
    a[j + 2 >> 0] = a[k + 1 >> 0] | 0;
    a[j + 3 >> 0] = a[k + 1 + 1 >> 0] | 0;
    a[j + 4 >> 0] = a[k + 1 + 1 + 1 >> 0] | 0;
    J = k + 1 + 1 + 1 + 1 + 1 | 0;
    a[j + 5 >> 0] = a[k + 1 + 1 + 1 + 1 >> 0] | 0;
    a[j + 6 >> 0] = a[J >> 0] | 0;
    a[j + 7 >> 0] = a[J + 1 >> 0] | 0;
    a[j + 8 >> 0] = a[J + 1 + 1 >> 0] | 0;
    k = J + 1 + 1 + 1 + ((s << 6) + -9) + 1 | 0;
    a[j + 9 >> 0] = a[J + 1 + 1 + 1 + ((s << 6) + -9) >> 0] | 0;
    a[j + 10 >> 0] = a[k >> 0] | 0;
    a[j + 11 >> 0] = a[k + 1 >> 0] | 0;
    a[j + 12 >> 0] = a[k + 1 + 1 >> 0] | 0;
    a[j + 13 >> 0] = a[k + 1 + 1 + 1 >> 0] | 0;
    J = k + 1 + 1 + 1 + 1 + 1 | 0;
    a[j + 14 >> 0] = a[k + 1 + 1 + 1 + 1 >> 0] | 0;
    a[j + 15 >> 0] = a[J >> 0] | 0;
    a[j + 16 >> 0] = a[J + 1 >> 0] | 0;
    a[j + 17 >> 0] = a[J + 1 + 1 >> 0] | 0;
   }
   if (!t) break;
   a[p >> 0] = a[o + -1 >> 0] | 0;
   a[p + 1 >> 0] = a[o + -1 + (r << 3 & 2147483640) >> 0] | 0;
   J = o + -1 + (r << 3 & 2147483640) + (r << 3 & 2147483640) | 0;
   a[p + 2 >> 0] = a[J >> 0] | 0;
   a[p + 3 >> 0] = a[J + (r << 3 & 2147483640) >> 0] | 0;
   a[p + 4 >> 0] = a[J + (r << 3 & 2147483640) + (r << 3 & 2147483640) >> 0] | 0;
   J = J + (r << 3 & 2147483640) + (r << 3 & 2147483640) + (r << 3 & 2147483640) | 0;
   a[p + 5 >> 0] = a[J >> 0] | 0;
   a[p + 6 >> 0] = a[J + (r << 3 & 2147483640) >> 0] | 0;
   a[p + 7 >> 0] = a[J + (r << 3 & 2147483640) + (r << 3 & 2147483640) >> 0] | 0;
   J = J + (r << 3 & 2147483640) + (r << 3 & 2147483640) + (r << 3 & 2147483640) + (s - r << 6) | 0;
   a[p + 8 >> 0] = a[J >> 0] | 0;
   a[p + 9 >> 0] = a[J + (r << 3 & 2147483640) >> 0] | 0;
   a[p + 10 >> 0] = a[J + (r << 3 & 2147483640) + (r << 3 & 2147483640) >> 0] | 0;
   J = J + (r << 3 & 2147483640) + (r << 3 & 2147483640) + (r << 3 & 2147483640) | 0;
   a[p + 11 >> 0] = a[J >> 0] | 0;
   a[p + 12 >> 0] = a[J + (r << 3 & 2147483640) >> 0] | 0;
   a[p + 13 >> 0] = a[J + (r << 3 & 2147483640) + (r << 3 & 2147483640) >> 0] | 0;
   J = J + (r << 3 & 2147483640) + (r << 3 & 2147483640) + (r << 3 & 2147483640) | 0;
   a[p + 14 >> 0] = a[J >> 0] | 0;
   a[p + 15 >> 0] = a[J + (r << 3 & 2147483640) >> 0] | 0;
  } while (0);
  s = c[f >> 2] | 0;
  b : do if (s >>> 0 > 6) {
   o = c[f + 200 >> 2] | 0;
   do if (!o) {
    p = 0;
    r = (m | 0) != 0;
   } else {
    p = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
    if (!((m | 0) != 0 & p)) {
     r = (m | 0) != 0;
     break;
    }
    p = (c[o >> 2] | 0) >>> 0 > 5;
    r = 1;
   } while (0);
   o = c[f + 204 >> 2] | 0;
   do if (!o) q = 0; else {
    q = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
    if (!(r & q)) break;
    q = (c[o >> 2] | 0) >>> 0 > 5;
   } while (0);
   j = c[f + 212 >> 2] | 0;
   do if (!j) o = 0; else {
    o = (c[f + 4 >> 2] | 0) == (c[j + 4 >> 2] | 0);
    if (!(r & o)) break;
    o = (c[j >> 2] | 0) >>> 0 > 5;
   } while (0);
   switch (s + 1 & 3) {
   case 0:
    {
     if (!q) break b;
     o = n;
     p = 0;
     while (1) {
      a[o >> 0] = a[L + 56 + 1 >> 0] | 0;
      a[o + 1 >> 0] = a[L + 56 + 2 >> 0] | 0;
      a[o + 2 >> 0] = a[L + 56 + 3 >> 0] | 0;
      a[o + 3 >> 0] = a[L + 56 + 4 >> 0] | 0;
      a[o + 4 >> 0] = a[L + 56 + 5 >> 0] | 0;
      a[o + 5 >> 0] = a[L + 56 + 6 >> 0] | 0;
      a[o + 6 >> 0] = a[L + 56 + 7 >> 0] | 0;
      a[o + 7 >> 0] = a[L + 56 + 8 >> 0] | 0;
      a[o + 8 >> 0] = a[L + 56 + 9 >> 0] | 0;
      a[o + 9 >> 0] = a[L + 56 + 10 >> 0] | 0;
      a[o + 10 >> 0] = a[L + 56 + 11 >> 0] | 0;
      a[o + 11 >> 0] = a[L + 56 + 12 >> 0] | 0;
      a[o + 12 >> 0] = a[L + 56 + 13 >> 0] | 0;
      a[o + 13 >> 0] = a[L + 56 + 14 >> 0] | 0;
      a[o + 14 >> 0] = a[L + 56 + 15 >> 0] | 0;
      a[o + 15 >> 0] = a[L + 56 + 16 >> 0] | 0;
      p = p + 1 | 0;
      if ((p | 0) == 16) break; else o = o + 16 | 0;
     }
     break;
    }
   case 1:
    {
     if (p) {
      o = n;
      p = 0;
     } else break b;
     while (1) {
      K = L + 24 + p | 0;
      a[o >> 0] = a[K >> 0] | 0;
      a[o + 1 >> 0] = a[K >> 0] | 0;
      a[o + 2 >> 0] = a[K >> 0] | 0;
      a[o + 3 >> 0] = a[K >> 0] | 0;
      a[o + 4 >> 0] = a[K >> 0] | 0;
      a[o + 5 >> 0] = a[K >> 0] | 0;
      a[o + 6 >> 0] = a[K >> 0] | 0;
      a[o + 7 >> 0] = a[K >> 0] | 0;
      a[o + 8 >> 0] = a[K >> 0] | 0;
      a[o + 9 >> 0] = a[K >> 0] | 0;
      a[o + 10 >> 0] = a[K >> 0] | 0;
      a[o + 11 >> 0] = a[K >> 0] | 0;
      a[o + 12 >> 0] = a[K >> 0] | 0;
      a[o + 13 >> 0] = a[K >> 0] | 0;
      a[o + 14 >> 0] = a[K >> 0] | 0;
      a[o + 15 >> 0] = a[K >> 0] | 0;
      p = p + 1 | 0;
      if ((p | 0) == 16) break; else o = o + 16 | 0;
     }
     break;
    }
   case 2:
    {
     do if (p & q) o = ((d[L + 56 + 1 >> 0] | 0) + 16 + (d[L + 24 >> 0] | 0) + (d[L + 56 + 2 >> 0] | 0) + (d[L + 24 + 1 >> 0] | 0) + (d[L + 56 + 3 >> 0] | 0) + (d[L + 24 + 2 >> 0] | 0) + (d[L + 56 + 4 >> 0] | 0) + (d[L + 24 + 3 >> 0] | 0) + (d[L + 56 + 5 >> 0] | 0) + (d[L + 24 + 4 >> 0] | 0) + (d[L + 56 + 6 >> 0] | 0) + (d[L + 24 + 5 >> 0] | 0) + (d[L + 56 + 7 >> 0] | 0) + (d[L + 24 + 6 >> 0] | 0) + (d[L + 56 + 8 >> 0] | 0) + (d[L + 24 + 7 >> 0] | 0) + (d[L + 56 + 9 >> 0] | 0) + (d[L + 24 + 8 >> 0] | 0) + (d[L + 56 + 10 >> 0] | 0) + (d[L + 24 + 9 >> 0] | 0) + (d[L + 56 + 11 >> 0] | 0) + (d[L + 24 + 10 >> 0] | 0) + (d[L + 56 + 12 >> 0] | 0) + (d[L + 24 + 11 >> 0] | 0) + (d[L + 56 + 13 >> 0] | 0) + (d[L + 24 + 12 >> 0] | 0) + (d[L + 56 + 14 >> 0] | 0) + (d[L + 24 + 13 >> 0] | 0) + (d[L + 56 + 15 >> 0] | 0) + (d[L + 24 + 14 >> 0] | 0) + (d[L + 56 + 16 >> 0] | 0) + (d[L + 24 + 15 >> 0] | 0) | 0) >>> 5; else {
      if (p) {
       o = ((d[L + 24 >> 0] | 0) + 8 + (d[L + 24 + 1 >> 0] | 0) + (d[L + 24 + 2 >> 0] | 0) + (d[L + 24 + 3 >> 0] | 0) + (d[L + 24 + 4 >> 0] | 0) + (d[L + 24 + 5 >> 0] | 0) + (d[L + 24 + 6 >> 0] | 0) + (d[L + 24 + 7 >> 0] | 0) + (d[L + 24 + 8 >> 0] | 0) + (d[L + 24 + 9 >> 0] | 0) + (d[L + 24 + 10 >> 0] | 0) + (d[L + 24 + 11 >> 0] | 0) + (d[L + 24 + 12 >> 0] | 0) + (d[L + 24 + 13 >> 0] | 0) + (d[L + 24 + 14 >> 0] | 0) + (d[L + 24 + 15 >> 0] | 0) | 0) >>> 4;
       break;
      }
      if (!q) {
       o = 128;
       break;
      }
      o = ((d[L + 56 + 1 >> 0] | 0) + 8 + (d[L + 56 + 2 >> 0] | 0) + (d[L + 56 + 3 >> 0] | 0) + (d[L + 56 + 4 >> 0] | 0) + (d[L + 56 + 5 >> 0] | 0) + (d[L + 56 + 6 >> 0] | 0) + (d[L + 56 + 7 >> 0] | 0) + (d[L + 56 + 8 >> 0] | 0) + (d[L + 56 + 9 >> 0] | 0) + (d[L + 56 + 10 >> 0] | 0) + (d[L + 56 + 11 >> 0] | 0) + (d[L + 56 + 12 >> 0] | 0) + (d[L + 56 + 13 >> 0] | 0) + (d[L + 56 + 14 >> 0] | 0) + (d[L + 56 + 15 >> 0] | 0) + (d[L + 56 + 16 >> 0] | 0) | 0) >>> 4;
     } while (0);
     pb(n | 0, o & 255 | 0, 256) | 0;
     break;
    }
   default:
    {
     if (!(p & q & o)) break b;
     p = d[L + 56 + 16 >> 0] | 0;
     q = d[L + 24 + 15 >> 0] | 0;
     r = d[L + 56 >> 0] | 0;
     j = (((d[L + 56 + 9 >> 0] | 0) - (d[L + 56 + 7 >> 0] | 0) + ((d[L + 56 + 10 >> 0] | 0) - (d[L + 56 + 6 >> 0] | 0) << 1) + (((d[L + 56 + 11 >> 0] | 0) - (d[L + 56 + 5 >> 0] | 0) | 0) * 3 | 0) + ((d[L + 56 + 12 >> 0] | 0) - (d[L + 56 + 4 >> 0] | 0) << 2) + (((d[L + 56 + 13 >> 0] | 0) - (d[L + 56 + 3 >> 0] | 0) | 0) * 5 | 0) + (((d[L + 56 + 14 >> 0] | 0) - (d[L + 56 + 2 >> 0] | 0) | 0) * 6 | 0) + (((d[L + 56 + 15 >> 0] | 0) - (d[L + 56 + 1 >> 0] | 0) | 0) * 7 | 0) + (p - r << 3) | 0) * 5 | 0) + 32 >> 6;
     r = (((d[L + 24 + 8 >> 0] | 0) - (d[L + 24 + 6 >> 0] | 0) + (q - r << 3) + ((d[L + 24 + 9 >> 0] | 0) - (d[L + 24 + 5 >> 0] | 0) << 1) + (((d[L + 24 + 10 >> 0] | 0) - (d[L + 24 + 4 >> 0] | 0) | 0) * 3 | 0) + ((d[L + 24 + 11 >> 0] | 0) - (d[L + 24 + 3 >> 0] | 0) << 2) + (((d[L + 24 + 12 >> 0] | 0) - (d[L + 24 + 2 >> 0] | 0) | 0) * 5 | 0) + (((d[L + 24 + 13 >> 0] | 0) - (d[L + 24 + 1 >> 0] | 0) | 0) * 6 | 0) + (((d[L + 24 + 14 >> 0] | 0) - (d[L + 24 >> 0] | 0) | 0) * 7 | 0) | 0) * 5 | 0) + 32 >> 6;
     s = N(j, -7) | 0;
     t = N(j, -6) | 0;
     u = N(j, -5) | 0;
     v = N(j, -4) | 0;
     w = N(j, -3) | 0;
     x = N(j, -2) | 0;
     o = 0;
     do {
      J = (q + p << 4) + 16 + (N(o + -7 | 0, r) | 0) | 0;
      K = o << 4;
      a[n + K >> 0] = (J + s >> 5 | 0) > 0 ? ((J + s >> 5 | 0) < 255 ? J + s >> 5 : 255) & 255 : 0;
      a[n + (K | 1) >> 0] = (J + t >> 5 | 0) > 0 ? ((J + t >> 5 | 0) < 255 ? J + t >> 5 : 255) & 255 : 0;
      a[n + (K | 2) >> 0] = (J + u >> 5 | 0) > 0 ? ((J + u >> 5 | 0) < 255 ? J + u >> 5 : 255) & 255 : 0;
      a[n + (K | 3) >> 0] = (J + v >> 5 | 0) > 0 ? ((J + v >> 5 | 0) < 255 ? J + v >> 5 : 255) & 255 : 0;
      a[n + (K | 4) >> 0] = (J + w >> 5 | 0) > 0 ? ((J + w >> 5 | 0) < 255 ? J + w >> 5 : 255) & 255 : 0;
      a[n + (K | 5) >> 0] = (J + x >> 5 | 0) > 0 ? ((J + x >> 5 | 0) < 255 ? J + x >> 5 : 255) & 255 : 0;
      a[n + (K | 6) >> 0] = (J - j >> 5 | 0) > 0 ? ((J - j >> 5 | 0) < 255 ? J - j >> 5 : 255) & 255 : 0;
      a[n + (K | 7) >> 0] = (J >> 5 | 0) > 0 ? ((J >> 5 | 0) < 255 ? J >> 5 : 255) & 255 : 0;
      a[n + (K | 8) >> 0] = (J + j >> 5 | 0) > 0 ? ((J + j >> 5 | 0) < 255 ? J + j >> 5 : 255) & 255 : 0;
      a[n + (K | 9) >> 0] = (J + (j << 1) >> 5 | 0) > 0 ? ((J + (j << 1) >> 5 | 0) < 255 ? J + (j << 1) >> 5 : 255) & 255 : 0;
      a[n + (K | 10) >> 0] = (J + (j * 3 | 0) >> 5 | 0) > 0 ? ((J + (j * 3 | 0) >> 5 | 0) < 255 ? J + (j * 3 | 0) >> 5 : 255) & 255 : 0;
      a[n + (K | 11) >> 0] = (J + (j << 2) >> 5 | 0) > 0 ? ((J + (j << 2) >> 5 | 0) < 255 ? J + (j << 2) >> 5 : 255) & 255 : 0;
      a[n + (K | 12) >> 0] = (J + (j * 5 | 0) >> 5 | 0) > 0 ? ((J + (j * 5 | 0) >> 5 | 0) < 255 ? J + (j * 5 | 0) >> 5 : 255) & 255 : 0;
      a[n + (K | 13) >> 0] = (J + (j * 6 | 0) >> 5 | 0) > 0 ? ((J + (j * 6 | 0) >> 5 | 0) < 255 ? J + (j * 6 | 0) >> 5 : 255) & 255 : 0;
      a[n + (K | 14) >> 0] = (J + (j * 7 | 0) >> 5 | 0) > 0 ? ((J + (j * 7 | 0) >> 5 | 0) < 255 ? J + (j * 7 | 0) >> 5 : 255) & 255 : 0;
      a[n + (K | 15) >> 0] = (J + (j << 3) >> 5 | 0) > 0 ? ((J + (j << 3) >> 5 | 0) < 255 ? J + (j << 3) >> 5 : 255) & 255 : 0;
      o = o + 1 | 0;
     } while ((o | 0) != 16);
    }
   }
   xa(n, g + 328 | 0, 0);
   xa(n, g + 392 | 0, 1);
   xa(n, g + 456 | 0, 2);
   xa(n, g + 520 | 0, 3);
   xa(n, g + 584 | 0, 4);
   xa(n, g + 648 | 0, 5);
   xa(n, g + 712 | 0, 6);
   xa(n, g + 776 | 0, 7);
   xa(n, g + 840 | 0, 8);
   xa(n, g + 904 | 0, 9);
   xa(n, g + 968 | 0, 10);
   xa(n, g + 1032 | 0, 11);
   xa(n, g + 1096 | 0, 12);
   xa(n, g + 1160 | 0, 13);
   xa(n, g + 1224 | 0, 14);
   xa(n, g + 1288 | 0, 15);
   o = f + 200 | 0;
   K = 226;
  } else {
   J = 0;
   c : while (1) {
    k = 384 + (J << 3) | 0;
    s = c[k + 4 >> 2] | 0;
    switch (c[k >> 2] | 0) {
    case 0:
     {
      o = f + 200 | 0;
      K = 156;
      break;
     }
    case 1:
     {
      o = f + 204 | 0;
      K = 156;
      break;
     }
    case 2:
     {
      o = f + 208 | 0;
      K = 156;
      break;
     }
    case 3:
     {
      o = f + 212 | 0;
      K = 156;
      break;
     }
    case 4:
     {
      o = f;
      K = 157;
      break;
     }
    default:
     {
      r = 0;
      p = 0;
     }
    }
    if ((K | 0) == 156) {
     K = 0;
     o = c[o >> 2] | 0;
     if (!o) {
      r = 0;
      p = 0;
     } else K = 157;
    }
    do if ((K | 0) == 157) {
     K = 0;
     p = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
     if (!((m | 0) != 0 & p)) {
      r = o;
      break;
     }
     r = o;
     p = (c[o >> 2] | 0) >>> 0 > 5;
    } while (0);
    k = 576 + (J << 3) | 0;
    j = c[k + 4 >> 2] | 0;
    switch (c[k >> 2] | 0) {
    case 0:
     {
      o = f + 200 | 0;
      K = 163;
      break;
     }
    case 1:
     {
      o = f + 204 | 0;
      K = 163;
      break;
     }
    case 2:
     {
      o = f + 208 | 0;
      K = 163;
      break;
     }
    case 3:
     {
      o = f + 212 | 0;
      K = 163;
      break;
     }
    case 4:
     {
      o = f;
      K = 164;
      break;
     }
    default:
     {
      o = 2;
      y = 0;
      x = 0;
     }
    }
    if ((K | 0) == 163) {
     K = 0;
     o = c[o >> 2] | 0;
     if (!o) {
      o = 2;
      y = 0;
      x = 0;
     } else K = 164;
    }
    do if ((K | 0) == 164) {
     K = 0;
     q = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
     if ((m | 0) != 0 & q) q = (c[o >> 2] | 0) >>> 0 > 5;
     if (!(p & q)) {
      o = 2;
      y = 0;
      x = q;
      break;
     }
     if ((c[r >> 2] | 0) == 6) q = d[(s & 255) + (r + 82) >> 0] | 0; else q = 2;
     if ((c[o >> 2] | 0) == 6) o = d[(j & 255) + (o + 82) >> 0] | 0; else o = 2;
     o = q >>> 0 < o >>> 0 ? q : o;
     y = 1;
     x = 1;
    } while (0);
    if (!(c[g + 12 + (J << 2) >> 2] | 0)) {
     k = c[g + 76 + (J << 2) >> 2] | 0;
     o = k + (k >>> 0 >= o >>> 0 & 1) | 0;
    }
    a[f + 82 + J >> 0] = o;
    switch (c[768 + (J << 3) >> 2] | 0) {
    case 0:
     {
      q = f + 200 | 0;
      K = 178;
      break;
     }
    case 1:
     {
      q = f + 204 | 0;
      K = 178;
      break;
     }
    case 2:
     {
      q = f + 208 | 0;
      K = 178;
      break;
     }
    case 3:
     {
      q = f + 212 | 0;
      K = 178;
      break;
     }
    case 4:
     {
      q = f;
      K = 179;
      break;
     }
    default:
     j = 0;
    }
    if ((K | 0) == 178) {
     K = 0;
     q = c[q >> 2] | 0;
     if (!q) j = 0; else K = 179;
    }
    do if ((K | 0) == 179) {
     K = 0;
     j = (c[f + 4 >> 2] | 0) == (c[q + 4 >> 2] | 0);
     if (!((m | 0) != 0 & j)) break;
     j = (c[q >> 2] | 0) >>> 0 > 5;
    } while (0);
    switch (c[960 + (J << 3) >> 2] | 0) {
    case 0:
     {
      q = f + 200 | 0;
      K = 185;
      break;
     }
    case 1:
     {
      q = f + 204 | 0;
      K = 185;
      break;
     }
    case 2:
     {
      q = f + 208 | 0;
      K = 185;
      break;
     }
    case 3:
     {
      q = f + 212 | 0;
      K = 185;
      break;
     }
    case 4:
     {
      q = f;
      K = 186;
      break;
     }
    default:
     r = 0;
    }
    if ((K | 0) == 185) {
     K = 0;
     q = c[q >> 2] | 0;
     if (!q) r = 0; else K = 186;
    }
    do if ((K | 0) == 186) {
     K = 0;
     r = (c[f + 4 >> 2] | 0) == (c[q + 4 >> 2] | 0);
     if (!((m | 0) != 0 & r)) break;
     r = (c[q >> 2] | 0) >>> 0 > 5;
    } while (0);
    i = c[1152 + (J << 2) >> 2] | 0;
    k = c[1216 + (J << 2) >> 2] | 0;
    w = (1285 >>> J & 1 | 0) != 0;
    if (w) {
     u = L + 24 | 0;
     t = L + 24 + (k + 2) | 0;
     v = k + 3 | 0;
     q = L + 24 + (k + 1) | 0;
     s = L + 24 + k | 0;
    } else {
     u = n;
     t = n + ((k << 4) + i + 31) | 0;
     v = (k << 4) + i + 47 | 0;
     q = n + ((k << 4) + i + 15) | 0;
     s = n + ((k << 4) + i + -1) | 0;
    }
    E = a[q >> 0] | 0;
    D = a[s >> 0] | 0;
    C = a[t >> 0] | 0;
    B = a[u + v >> 0] | 0;
    if (!(51 >>> J & 1)) {
     u = (k + -1 << 4) + i | 0;
     G = a[n + u >> 0] | 0;
     H = a[n + (u + 1) >> 0] | 0;
     I = a[n + (u + 2) >> 0] | 0;
     F = a[n + (u + 3) >> 0] | 0;
     v = a[n + (u + 4) >> 0] | 0;
     q = a[n + (u + 5) >> 0] | 0;
     A = a[n + (u + 6) >> 0] | 0;
     a[L >> 0] = a[n + (u + 7) >> 0] | 0;
     u = a[(w ? L + 24 + (k + -1) | 0 : n + (u + -1) | 0) >> 0] | 0;
     s = u;
     t = L + 95 | 0;
     w = A;
    } else {
     u = a[L + 56 + i >> 0] | 0;
     a[L + 95 >> 0] = u;
     s = a[L + 56 + (i + 8) >> 0] | 0;
     t = L;
     F = a[L + 56 + (i + 4) >> 0] | 0;
     v = a[L + 56 + (i + 5) >> 0] | 0;
     q = a[L + 56 + (i + 6) >> 0] | 0;
     w = a[L + 56 + (i + 7) >> 0] | 0;
     G = a[L + 56 + (i + 1) >> 0] | 0;
     H = a[L + 56 + (i + 2) >> 0] | 0;
     I = a[L + 56 + (i + 3) >> 0] | 0;
    }
    a[t >> 0] = s;
    switch (o | 0) {
    case 0:
     {
      if (!x) {
       K = 224;
       break c;
      }
      p = G;
      j = H;
      r = I;
      s = F;
      t = G;
      u = H;
      v = I;
      w = F;
      x = G;
      y = H;
      z = I;
      A = F;
      o = (I & 255) << 16 | (F & 255) << 24 | G & 255 | (H & 255) << 8;
      break;
     }
    case 1:
     {
      if (!p) {
       K = 224;
       break c;
      }
      s = N(D & 255, 16843009) | 0;
      w = N(E & 255, 16843009) | 0;
      A = N(C & 255, 16843009) | 0;
      p = s & 255;
      j = s >>> 8 & 255;
      r = s >>> 16 & 255;
      s = s >>> 24 & 255;
      t = w & 255;
      u = w >>> 8 & 255;
      v = w >>> 16 & 255;
      w = w >>> 24 & 255;
      x = A & 255;
      y = A >>> 8 & 255;
      z = A >>> 16 & 255;
      A = A >>> 24 & 255;
      o = N(B & 255, 16843009) | 0;
      break;
     }
    case 2:
     {
      do if (y) o = ((E & 255) + 4 + (D & 255) + (C & 255) + (B & 255) + (F & 255) + (I & 255) + (H & 255) + (G & 255) | 0) >>> 3; else {
       if (p) {
        o = ((E & 255) + 2 + (D & 255) + (C & 255) + (B & 255) | 0) >>> 2;
        break;
       }
       if (!x) {
        o = 128;
        break;
       }
       o = ((F & 255) + 2 + (I & 255) + (H & 255) + (G & 255) | 0) >>> 2;
      } while (0);
      o = N(o & 255, 16843009) | 0;
      p = o & 255;
      j = o >>> 8 & 255;
      r = o >>> 16 & 255;
      s = o >>> 24 & 255;
      t = o & 255;
      u = o >>> 8 & 255;
      v = o >>> 16 & 255;
      w = o >>> 24 & 255;
      x = o & 255;
      y = o >>> 8 & 255;
      z = o >>> 16 & 255;
      A = o >>> 24 & 255;
      break;
     }
    case 3:
     {
      if (!x) {
       K = 224;
       break c;
      }
      if (j) {
       j = v;
       o = w;
       p = a[L >> 0] | 0;
      } else {
       a[L >> 0] = F;
       j = F;
       q = F;
       o = F;
       p = F;
      }
      t = H & 255;
      x = I & 255;
      E = F & 255;
      F = j & 255;
      I = q & 255;
      y = (E + 2 + I + (F << 1) | 0) >>> 2 & 255;
      o = o & 255;
      z = (F + 2 + (I << 1) + o | 0) >>> 2 & 255;
      H = p & 255;
      p = (x + 2 + (G & 255) + (t << 1) | 0) >>> 2 & 255;
      j = (E + 2 + t + (x << 1) | 0) >>> 2 & 255;
      r = (x + 2 + (E << 1) + F | 0) >>> 2 & 255;
      s = y;
      t = (E + 2 + t + (x << 1) | 0) >>> 2 & 255;
      u = (x + 2 + (E << 1) + F | 0) >>> 2 & 255;
      v = y;
      w = z;
      x = (x + 2 + (E << 1) + F | 0) >>> 2 & 255;
      A = (H + 2 + I + (o << 1) | 0) >>> 2 & 255;
      o = ((H * 3 | 0) + 2 + o | 0) >>> 2 << 24 | (E + 2 + I + (F << 1) | 0) >>> 2 & 255 | (F + 2 + (I << 1) + o | 0) >>> 2 << 8 & 65280 | (H + 2 + I + (o << 1) | 0) >>> 2 << 16 & 16711680;
      break;
     }
    case 4:
     {
      if (!(y & r)) {
       K = 224;
       break c;
      }
      q = G & 255;
      G = u & 255;
      z = (q + 2 + (D & 255) + (G << 1) | 0) >>> 2 & 255;
      A = H & 255;
      w = I & 255;
      o = (((D & 255) << 1) + ((E & 255) + 2) + (d[L + 95 >> 0] | 0) | 0) >>> 2;
      p = z;
      j = (A + 2 + G + (q << 1) | 0) >>> 2 & 255;
      r = ((A << 1) + w + (q + 2) | 0) >>> 2 & 255;
      s = ((F & 255) + 2 + A + (w << 1) | 0) >>> 2 & 255;
      t = o & 255;
      u = z;
      v = (A + 2 + G + (q << 1) | 0) >>> 2 & 255;
      w = ((A << 1) + w + (q + 2) | 0) >>> 2 & 255;
      x = ((D & 255) + 2 + ((E & 255) << 1) + (C & 255) | 0) >>> 2 & 255;
      y = o & 255;
      A = (A + 2 + G + (q << 1) | 0) >>> 2 & 255;
      o = (((C & 255) << 1) + ((E & 255) + 2) + (B & 255) | 0) >>> 2 & 255 | ((D & 255) + 2 + ((E & 255) << 1) + (C & 255) | 0) >>> 2 << 8 & 65280 | (q + 2 + (D & 255) + (G << 1) | 0) >>> 2 << 24 | o << 16 & 16711680;
      break;
     }
    case 5:
     {
      if (!(y & r)) {
       K = 224;
       break c;
      }
      B = u & 255;
      o = G & 255;
      H = H & 255;
      I = I & 255;
      w = F & 255;
      p = (o + 1 + B | 0) >>> 1 & 255;
      j = (H + 1 + o | 0) >>> 1 & 255;
      r = (I + 1 + H | 0) >>> 1 & 255;
      s = (w + 1 + I | 0) >>> 1 & 255;
      t = (o + 2 + (D & 255) + (B << 1) | 0) >>> 2 & 255;
      u = (H + 2 + B + (o << 1) | 0) >>> 2 & 255;
      v = ((H << 1) + I + (o + 2) | 0) >>> 2 & 255;
      w = (w + 2 + H + (I << 1) | 0) >>> 2 & 255;
      x = ((E & 255) + 2 + ((D & 255) << 1) + (d[L + 95 >> 0] | 0) | 0) >>> 2 & 255;
      y = (o + 1 + B | 0) >>> 1 & 255;
      z = (H + 1 + o | 0) >>> 1 & 255;
      A = (I + 1 + H | 0) >>> 1 & 255;
      o = ((H << 1) + I + (o + 2) | 0) >>> 2 << 24 | (((E & 255) << 1) + 2 + (D & 255) + (C & 255) | 0) >>> 2 & 255 | (o + 2 + (D & 255) + (B << 1) | 0) >>> 2 << 8 & 65280 | (H + 2 + B + (o << 1) | 0) >>> 2 << 16 & 16711680;
      break;
     }
    case 6:
     {
      if (!(y & r)) {
       K = 224;
       break c;
      }
      A = d[L + 95 >> 0] | 0;
      x = G & 255;
      w = u & 255;
      s = H & 255;
      p = ((D & 255) + 1 + A | 0) >>> 1 & 255;
      j = ((D & 255) + 2 + x + (w << 1) | 0) >>> 2 & 255;
      r = (s + 2 + (x << 1) + w | 0) >>> 2 & 255;
      s = ((I & 255) + 2 + (s << 1) + x | 0) >>> 2 & 255;
      t = ((E & 255) + 1 + (D & 255) | 0) >>> 1 & 255;
      u = (((D & 255) << 1) + ((E & 255) + 2) + A | 0) >>> 2 & 255;
      v = ((D & 255) + 1 + A | 0) >>> 1 & 255;
      w = ((D & 255) + 2 + x + (w << 1) | 0) >>> 2 & 255;
      x = ((E & 255) + 1 + (C & 255) | 0) >>> 1 & 255;
      y = ((D & 255) + 2 + ((E & 255) << 1) + (C & 255) | 0) >>> 2 & 255;
      z = ((E & 255) + 1 + (D & 255) | 0) >>> 1 & 255;
      A = (((D & 255) << 1) + ((E & 255) + 2) + A | 0) >>> 2 & 255;
      o = ((D & 255) + 2 + ((E & 255) << 1) + (C & 255) | 0) >>> 2 << 24 | ((E & 255) + 1 + (C & 255) | 0) >>> 1 << 16 & 16711680 | ((C & 255) + 1 + (B & 255) | 0) >>> 1 & 255 | ((C & 255) << 1) + ((E & 255) + 2) + (B & 255) << 6 & 65280;
      break;
     }
    case 7:
     {
      if (!x) {
       K = 224;
       break c;
      }
      if (j) {
       p = v;
       o = q;
       q = w;
      } else {
       a[L >> 0] = F;
       p = F;
       o = F;
       q = F;
      }
      t = G & 255;
      E = H & 255;
      G = I & 255;
      H = F & 255;
      I = p & 255;
      o = o & 255;
      p = (E + 1 + t | 0) >>> 1 & 255;
      j = (G + 1 + E | 0) >>> 1 & 255;
      r = (H + 1 + G | 0) >>> 1 & 255;
      s = (H + 1 + I | 0) >>> 1 & 255;
      t = (G + 2 + t + (E << 1) | 0) >>> 2 & 255;
      u = (H + 2 + E + (G << 1) | 0) >>> 2 & 255;
      v = (G + 2 + (H << 1) + I | 0) >>> 2 & 255;
      w = (H + 2 + o + (I << 1) | 0) >>> 2 & 255;
      x = (G + 1 + E | 0) >>> 1 & 255;
      y = (H + 1 + G | 0) >>> 1 & 255;
      z = (H + 1 + I | 0) >>> 1 & 255;
      A = (o + 1 + I | 0) >>> 1 & 255;
      o = (G + 2 + (H << 1) + I | 0) >>> 2 << 8 & 65280 | (H + 2 + E + (G << 1) | 0) >>> 2 & 255 | (I + 2 + (o << 1) + (q & 255) | 0) >>> 2 << 24 | (H + 2 + o + (I << 1) | 0) >>> 2 << 16 & 16711680;
      break;
     }
    default:
     {
      if (!p) {
       K = 224;
       break c;
      }
      p = ((E & 255) + 1 + (D & 255) | 0) >>> 1 & 255;
      j = ((D & 255) + 2 + ((E & 255) << 1) + (C & 255) | 0) >>> 2 & 255;
      r = ((E & 255) + 1 + (C & 255) | 0) >>> 1 & 255;
      s = ((E & 255) + 2 + ((C & 255) << 1) + (B & 255) | 0) >>> 2 & 255;
      t = ((E & 255) + 1 + (C & 255) | 0) >>> 1 & 255;
      u = ((E & 255) + 2 + ((C & 255) << 1) + (B & 255) | 0) >>> 2 & 255;
      v = ((C & 255) + 1 + (B & 255) | 0) >>> 1 & 255;
      w = ((C & 255) + 2 + ((B & 255) * 3 | 0) | 0) >>> 2 & 255;
      x = ((C & 255) + 1 + (B & 255) | 0) >>> 1 & 255;
      y = ((C & 255) + 2 + ((B & 255) * 3 | 0) | 0) >>> 2 & 255;
      z = B;
      A = B;
      o = (B & 255) << 8 | B & 255 | (B & 255) << 16 | (B & 255) << 24;
     }
    }
    c[n + ((k << 4) + i) >> 2] = (r & 255) << 16 | (s & 255) << 24 | (j & 255) << 8 | p & 255;
    c[n + ((k << 4) + i) + 16 >> 2] = (v & 255) << 16 | (w & 255) << 24 | (u & 255) << 8 | t & 255;
    c[n + ((k << 4) + i) + 32 >> 2] = (z & 255) << 16 | (A & 255) << 24 | (y & 255) << 8 | x & 255;
    c[n + ((k << 4) + i) + 48 >> 2] = o;
    xa(n, g + 328 + (J << 6) | 0, J);
    J = J + 1 | 0;
    if (J >>> 0 >= 16) {
     K = 225;
     break;
    }
   }
   if ((K | 0) == 224) break; else if ((K | 0) == 225) {
    o = f + 200 | 0;
    K = 226;
    break;
   }
  } while (0);
  d : do if ((K | 0) == 226) {
   D = c[g + 140 >> 2] | 0;
   o = c[o >> 2] | 0;
   do if (!o) {
    p = 0;
    r = (m | 0) != 0;
   } else {
    p = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
    if (!((m | 0) != 0 & p)) {
     r = (m | 0) != 0;
     break;
    }
    p = (c[o >> 2] | 0) >>> 0 > 5;
    r = 1;
   } while (0);
   o = c[f + 204 >> 2] | 0;
   do if (!o) q = 0; else {
    q = (c[f + 4 >> 2] | 0) == (c[o + 4 >> 2] | 0);
    if (!(r & q)) break;
    q = (c[o >> 2] | 0) >>> 0 > 5;
   } while (0);
   j = c[f + 212 >> 2] | 0;
   do if (!j) o = 0; else {
    o = (c[f + 4 >> 2] | 0) == (c[j + 4 >> 2] | 0);
    if (!(r & o)) break;
    o = (c[j >> 2] | 0) >>> 0 > 5;
   } while (0);
   C = p & q;
   B = C & o;
   w = 16;
   x = 0;
   y = n + 256 | 0;
   z = L + 24 + 16 | 0;
   A = L + 56 + 21 | 0;
   v = g + 1352 | 0;
   while (1) {
    switch (D | 0) {
    case 0:
     {
      r = A + 1 | 0;
      do if (C) {
       o = ((d[A + 5 >> 0] | 0) + 2 + (d[A + 6 >> 0] | 0) + (d[A + 7 >> 0] | 0) + (d[A + 8 >> 0] | 0) | 0) >>> 2;
       j = ((d[r >> 0] | 0) + 4 + (d[A + 2 >> 0] | 0) + (d[A + 3 >> 0] | 0) + (d[A + 4 >> 0] | 0) + (d[z >> 0] | 0) + (d[z + 1 >> 0] | 0) + (d[z + 2 >> 0] | 0) + (d[z + 3 >> 0] | 0) | 0) >>> 3;
      } else {
       if (q) {
        o = ((d[A + 5 >> 0] | 0) + 2 + (d[A + 6 >> 0] | 0) + (d[A + 7 >> 0] | 0) + (d[A + 8 >> 0] | 0) | 0) >>> 2;
        j = ((d[r >> 0] | 0) + 2 + (d[A + 2 >> 0] | 0) + (d[A + 3 >> 0] | 0) + (d[A + 4 >> 0] | 0) | 0) >>> 2;
        break;
       }
       if (!p) {
        o = 128;
        j = 128;
        break;
       }
       j = ((d[z >> 0] | 0) + 2 + (d[z + 1 >> 0] | 0) + (d[z + 2 >> 0] | 0) + (d[z + 3 >> 0] | 0) | 0) >>> 2;
       o = j;
      } while (0);
      K = j & 255;
      g = o & 255;
      pb(y | 0, K | 0, 4) | 0;
      pb(y + 4 | 0, g | 0, 4) | 0;
      pb(y + 8 | 0, K | 0, 4) | 0;
      pb(y + 12 | 0, g | 0, 4) | 0;
      pb(y + 16 | 0, K | 0, 4) | 0;
      pb(y + 20 | 0, g | 0, 4) | 0;
      u = y + 32 | 0;
      pb(y + 24 | 0, K | 0, 4) | 0;
      pb(y + 28 | 0, g | 0, 4) | 0;
      do if (p) {
       o = d[z + 4 >> 0] | 0;
       j = d[z + 5 >> 0] | 0;
       r = d[z + 6 >> 0] | 0;
       s = d[z + 7 >> 0] | 0;
       if (!q) {
        t = (o + 2 + j + r + s | 0) >>> 2;
        o = (o + 2 + j + r + s | 0) >>> 2;
        break;
       }
       t = (o + 4 + j + r + s + (d[A + 5 >> 0] | 0) + (d[A + 6 >> 0] | 0) + (d[A + 7 >> 0] | 0) + (d[A + 8 >> 0] | 0) | 0) >>> 3;
       o = (o + 2 + j + r + s | 0) >>> 2;
      } else {
       if (!q) {
        t = 128;
        o = 128;
        break;
       }
       t = ((d[A + 5 >> 0] | 0) + 2 + (d[A + 6 >> 0] | 0) + (d[A + 7 >> 0] | 0) + (d[A + 8 >> 0] | 0) | 0) >>> 2;
       o = ((d[r >> 0] | 0) + 2 + (d[A + 2 >> 0] | 0) + (d[A + 3 >> 0] | 0) + (d[A + 4 >> 0] | 0) | 0) >>> 2;
      } while (0);
      K = o & 255;
      g = t & 255;
      pb(u | 0, K | 0, 4) | 0;
      pb(y + 36 | 0, g | 0, 4) | 0;
      pb(y + 40 | 0, K | 0, 4) | 0;
      pb(y + 44 | 0, g | 0, 4) | 0;
      pb(y + 48 | 0, K | 0, 4) | 0;
      pb(y + 52 | 0, g | 0, 4) | 0;
      pb(y + 56 | 0, K | 0, 4) | 0;
      pb(y + 60 | 0, g | 0, 4) | 0;
      break;
     }
    case 1:
     {
      if (!p) break d;
      pb(y | 0, a[z >> 0] | 0, 8) | 0;
      pb(y + 8 | 0, a[z + 1 >> 0] | 0, 8) | 0;
      pb(y + 16 | 0, a[z + 2 >> 0] | 0, 8) | 0;
      pb(y + 24 | 0, a[z + 3 >> 0] | 0, 8) | 0;
      pb(y + 32 | 0, a[z + 4 >> 0] | 0, 8) | 0;
      pb(y + 40 | 0, a[z + 5 >> 0] | 0, 8) | 0;
      pb(y + 48 | 0, a[z + 6 >> 0] | 0, 8) | 0;
      pb(y + 56 | 0, a[z + 7 >> 0] | 0, 8) | 0;
      break;
     }
    case 2:
     {
      if (!q) break d;
      g = a[A + 1 >> 0] | 0;
      a[y >> 0] = g;
      a[y + 8 >> 0] = g;
      a[y + 16 >> 0] = g;
      a[y + 24 >> 0] = g;
      a[y + 32 >> 0] = g;
      a[y + 40 >> 0] = g;
      a[y + 48 >> 0] = g;
      a[y + 56 >> 0] = g;
      g = a[A + 2 >> 0] | 0;
      a[y + 1 >> 0] = g;
      a[y + 9 >> 0] = g;
      a[y + 17 >> 0] = g;
      a[y + 25 >> 0] = g;
      a[y + 33 >> 0] = g;
      a[y + 41 >> 0] = g;
      a[y + 49 >> 0] = g;
      a[y + 57 >> 0] = g;
      g = a[A + 3 >> 0] | 0;
      a[y + 2 >> 0] = g;
      a[y + 10 >> 0] = g;
      a[y + 18 >> 0] = g;
      a[y + 26 >> 0] = g;
      a[y + 34 >> 0] = g;
      a[y + 42 >> 0] = g;
      a[y + 50 >> 0] = g;
      a[y + 58 >> 0] = g;
      g = a[A + 4 >> 0] | 0;
      a[y + 3 >> 0] = g;
      a[y + 11 >> 0] = g;
      a[y + 19 >> 0] = g;
      a[y + 27 >> 0] = g;
      a[y + 35 >> 0] = g;
      a[y + 43 >> 0] = g;
      a[y + 51 >> 0] = g;
      a[y + 59 >> 0] = g;
      g = a[A + 5 >> 0] | 0;
      a[y + 4 >> 0] = g;
      a[y + 12 >> 0] = g;
      a[y + 20 >> 0] = g;
      a[y + 28 >> 0] = g;
      a[y + 36 >> 0] = g;
      a[y + 44 >> 0] = g;
      a[y + 52 >> 0] = g;
      a[y + 60 >> 0] = g;
      g = a[A + 6 >> 0] | 0;
      a[y + 5 >> 0] = g;
      a[y + 13 >> 0] = g;
      a[y + 21 >> 0] = g;
      a[y + 29 >> 0] = g;
      a[y + 37 >> 0] = g;
      a[y + 45 >> 0] = g;
      a[y + 53 >> 0] = g;
      a[y + 61 >> 0] = g;
      g = a[A + 7 >> 0] | 0;
      a[y + 6 >> 0] = g;
      a[y + 14 >> 0] = g;
      a[y + 22 >> 0] = g;
      a[y + 30 >> 0] = g;
      a[y + 38 >> 0] = g;
      a[y + 46 >> 0] = g;
      a[y + 54 >> 0] = g;
      a[y + 62 >> 0] = g;
      g = a[A + 8 >> 0] | 0;
      a[y + 7 >> 0] = g;
      a[y + 15 >> 0] = g;
      a[y + 23 >> 0] = g;
      a[y + 31 >> 0] = g;
      a[y + 39 >> 0] = g;
      a[y + 47 >> 0] = g;
      a[y + 55 >> 0] = g;
      a[y + 63 >> 0] = g;
      break;
     }
    default:
     {
      if (!B) break d;
      m = d[A + 8 >> 0] | 0;
      J = d[z + 7 >> 0] | 0;
      K = d[A >> 0] | 0;
      g = (((d[A + 5 >> 0] | 0) - (d[A + 3 >> 0] | 0) + ((d[A + 6 >> 0] | 0) - (d[A + 2 >> 0] | 0) << 1) + (((d[A + 7 >> 0] | 0) - (d[A + 1 >> 0] | 0) | 0) * 3 | 0) + (m - K << 2) | 0) * 17 | 0) + 16 >> 5;
      K = (((d[z + 4 >> 0] | 0) - (d[z + 2 >> 0] | 0) + (J - K << 2) + ((d[z + 5 >> 0] | 0) - (d[z + 1 >> 0] | 0) << 1) + (((d[z + 6 >> 0] | 0) - (d[z >> 0] | 0) | 0) * 3 | 0) | 0) * 17 | 0) + 16 >> 5;
      m = (J + m << 4) + 16 + (N(K, -3) | 0) | 0;
      J = N(g, -3) | 0;
      a[y >> 0] = a[6162 + (m + J >> 5) >> 0] | 0;
      a[y + 1 >> 0] = a[6162 + (m + J + g >> 5) >> 0] | 0;
      a[y + 2 >> 0] = a[6162 + (m + J + g + g >> 5) >> 0] | 0;
      a[y + 3 >> 0] = a[6162 + (m + J + g + g + g >> 5) >> 0] | 0;
      k = m + J + g + g + g + g | 0;
      a[y + 4 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 5 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 6 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 7 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 8 >> 0] = a[6162 + (m + K + J >> 5) >> 0] | 0;
      a[y + 9 >> 0] = a[6162 + (m + K + J + g >> 5) >> 0] | 0;
      a[y + 10 >> 0] = a[6162 + (m + K + J + g + g >> 5) >> 0] | 0;
      k = m + K + J + g + g + g | 0;
      a[y + 11 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 12 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 13 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 14 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 15 >> 0] = a[6162 + (k + g + g + g + g >> 5) >> 0] | 0;
      a[y + 16 >> 0] = a[6162 + (m + K + K + J >> 5) >> 0] | 0;
      a[y + 17 >> 0] = a[6162 + (m + K + K + J + g >> 5) >> 0] | 0;
      k = m + K + K + J + g + g | 0;
      a[y + 18 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 19 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 20 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 21 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 22 >> 0] = a[6162 + (k + g + g + g + g >> 5) >> 0] | 0;
      a[y + 23 >> 0] = a[6162 + (k + g + g + g + g + g >> 5) >> 0] | 0;
      a[y + 24 >> 0] = a[6162 + (m + K + K + K + J >> 5) >> 0] | 0;
      k = m + K + K + K + J + g | 0;
      a[y + 25 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 26 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 27 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 28 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 29 >> 0] = a[6162 + (k + g + g + g + g >> 5) >> 0] | 0;
      k = k + g + g + g + g + g | 0;
      a[y + 30 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 31 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      k = m + K + K + K + K + J | 0;
      a[y + 32 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 33 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 34 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 35 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 36 >> 0] = a[6162 + (k + g + g + g + g >> 5) >> 0] | 0;
      k = k + g + g + g + g + g | 0;
      a[y + 37 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 38 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 39 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      m = m + K + K + K + K + K | 0;
      a[y + 40 >> 0] = a[6162 + (m + J >> 5) >> 0] | 0;
      a[y + 41 >> 0] = a[6162 + (m + J + g >> 5) >> 0] | 0;
      a[y + 42 >> 0] = a[6162 + (m + J + g + g >> 5) >> 0] | 0;
      a[y + 43 >> 0] = a[6162 + (m + J + g + g + g >> 5) >> 0] | 0;
      k = m + J + g + g + g + g | 0;
      a[y + 44 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 45 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 46 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 47 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 48 >> 0] = a[6162 + (m + K + J >> 5) >> 0] | 0;
      a[y + 49 >> 0] = a[6162 + (m + K + J + g >> 5) >> 0] | 0;
      a[y + 50 >> 0] = a[6162 + (m + K + J + g + g >> 5) >> 0] | 0;
      k = m + K + J + g + g + g | 0;
      a[y + 51 >> 0] = a[6162 + (k >> 5) >> 0] | 0;
      a[y + 52 >> 0] = a[6162 + (k + g >> 5) >> 0] | 0;
      a[y + 53 >> 0] = a[6162 + (k + g + g >> 5) >> 0] | 0;
      a[y + 54 >> 0] = a[6162 + (k + g + g + g >> 5) >> 0] | 0;
      a[y + 55 >> 0] = a[6162 + (k + g + g + g + g >> 5) >> 0] | 0;
      a[y + 56 >> 0] = a[6162 + (K + J + (m + K) >> 5) >> 0] | 0;
      a[y + 57 >> 0] = a[6162 + (K + J + (m + K) + g >> 5) >> 0] | 0;
      K = K + J + (m + K) + g + g | 0;
      a[y + 58 >> 0] = a[6162 + (K >> 5) >> 0] | 0;
      a[y + 59 >> 0] = a[6162 + (K + g >> 5) >> 0] | 0;
      a[y + 60 >> 0] = a[6162 + (K + g + g >> 5) >> 0] | 0;
      a[y + 61 >> 0] = a[6162 + (K + g + g + g >> 5) >> 0] | 0;
      a[y + 62 >> 0] = a[6162 + (K + g + g + g + g >> 5) >> 0] | 0;
      a[y + 63 >> 0] = a[6162 + (K + g + g + g + g + g >> 5) >> 0] | 0;
     }
    }
    xa(y, v, w);
    g = w | 1;
    xa(y, v + 64 | 0, g);
    xa(y, v + 128 | 0, g + 1 | 0);
    xa(y, v + 192 | 0, w | 3);
    x = x + 1 | 0;
    if (x >>> 0 >= 2) break; else {
     w = w + 4 | 0;
     y = y + 64 | 0;
     z = z + 8 | 0;
     A = A + 9 | 0;
     v = v + 256 | 0;
    }
   }
   if ((c[f + 196 >> 2] | 0) >>> 0 <= 1) Ka(h, n);
   n = 0;
   l = L;
   return n | 0;
  } while (0);
  n = 1;
  l = L;
  return n | 0;
 } while (0);
 m = c[h + 4 >> 2] | 0;
 H = ((k >>> 0) / (m >>> 0) | 0) << 4;
 I = k - (N((k >>> 0) / (m >>> 0) | 0, m) | 0) << 4;
 c[L + 4 >> 2] = m;
 c[L + 8 >> 2] = c[h + 8 >> 2];
 e : do switch (q | 0) {
 case 1:
 case 0:
  {
   z = c[g + 144 >> 2] | 0;
   p = c[f + 200 >> 2] | 0;
   if (!p) {
    r = 0;
    o = 0;
    x = 0;
    t = -1;
   } else if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[p >> 2] | 0) >>> 0 < 6) {
    x = e[p + 152 >> 1] | e[p + 152 + 2 >> 1] << 16;
    r = 1;
    o = x & 65535;
    x = x >>> 16 & 65535;
    t = c[p + 104 >> 2] | 0;
   } else {
    r = 1;
    o = 0;
    x = 0;
    t = -1;
   } else {
    r = 0;
    o = 0;
    x = 0;
    t = -1;
   }
   p = c[f + 204 >> 2] | 0;
   if (!p) {
    j = 0;
    s = -1;
    w = 0;
    u = 0;
   } else if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[p >> 2] | 0) >>> 0 < 6) {
    u = e[p + 172 >> 1] | e[p + 172 + 2 >> 1] << 16;
    j = 1;
    s = c[p + 108 >> 2] | 0;
    w = u & 65535;
    u = u >>> 16 & 65535;
   } else {
    j = 1;
    s = -1;
    w = 0;
    u = 0;
   } else {
    j = 0;
    s = -1;
    w = 0;
    u = 0;
   }
   if (!q) if ((r | 0) == 0 | (j | 0) == 0) {
    q = 0;
    p = 0;
   } else if (!((x & 65535) << 16 | o & 65535 | t)) {
    q = 0;
    p = 0;
   } else if (!((u & 65535) << 16 | w & 65535 | s)) {
    q = 0;
    p = 0;
   } else K = 274; else K = 274;
   if ((K | 0) == 274) {
    v = b[g + 160 >> 1] | 0;
    y = b[g + 162 >> 1] | 0;
    p = c[f + 208 >> 2] | 0;
    if (!p) K = 278; else if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[p >> 2] | 0) >>> 0 < 6) {
     r = c[p + 108 >> 2] | 0;
     j = e[p + 172 >> 1] | e[p + 172 + 2 >> 1] << 16;
     K = 283;
    } else {
     r = -1;
     j = 0;
     K = 283;
    } else K = 278;
    do if ((K | 0) == 278) {
     p = c[f + 212 >> 2] | 0;
     if (p | 0) if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) {
      if ((c[p >> 2] | 0) >>> 0 >= 6) {
       r = -1;
       j = 0;
       K = 283;
       break;
      }
      r = c[p + 112 >> 2] | 0;
      j = e[p + 192 >> 1] | e[p + 192 + 2 >> 1] << 16;
      K = 283;
      break;
     }
     if ((r | 0) == 0 | (j | 0) != 0) {
      r = -1;
      j = 0;
      K = 283;
     } else q = x & 65535;
    } while (0);
    do if ((K | 0) == 283) {
     q = (t | 0) == (z | 0);
     p = (s | 0) == (z | 0);
     if (((p & 1) + (q & 1) + ((r | 0) == (z | 0) & 1) | 0) != 1) {
      G = o << 16 >> 16;
      E = w << 16 >> 16;
      m = j << 16 >> 16;
      q = w << 16 >> 16 > o << 16 >> 16;
      J = q ? w : o;
      o = q ? G : (E | 0) < (G | 0) ? E : G;
      G = x << 16 >> 16;
      E = u << 16 >> 16;
      q = j >> 16;
      D = u << 16 >> 16 > x << 16 >> 16;
      F = D ? u : x;
      G = D ? G : (E | 0) < (G | 0) ? E : G;
      q = F << 16 >> 16 < (j >>> 16 & 65535) << 16 >> 16 ? F & 65535 : (G | 0) > (q | 0) ? G : q;
      o = (J << 16 >> 16 < (j & 65535) << 16 >> 16 ? J & 65535 : (o | 0) > (m | 0) ? o : m) & 65535;
      break;
     }
     if (q) {
      q = x & 65535;
      break;
     }
     if (p) {
      q = u & 65535;
      o = w;
      break;
     } else {
      q = j >>> 16;
      o = j & 65535;
      break;
     }
    } while (0);
    p = (o & 65535) + (v & 65535) | 0;
    o = (q & 65535) + (y & 65535) | 0;
    if (((p << 16 >> 16) + 8192 | 0) >>> 0 > 16383) {
     K = 486;
     break e;
    }
    if (((o << 16 >> 16) + 2048 | 0) >>> 0 > 4095) {
     K = 486;
     break e;
    } else {
     q = p & 65535;
     p = o & 65535;
    }
   }
   if (z >>> 0 > 16) K = 486; else {
    o = c[(c[i + 4 >> 2] | 0) + (z << 2) >> 2] | 0;
    if (!o) K = 486; else if ((c[o + 20 >> 2] | 0) >>> 0 > 1) {
     o = c[o >> 2] | 0;
     if (!o) K = 486; else {
      b[f + 192 >> 1] = q;
      b[f + 194 >> 1] = p;
      m = c[f + 192 >> 2] | 0;
      c[f + 188 >> 2] = m;
      c[f + 184 >> 2] = m;
      c[f + 180 >> 2] = m;
      c[f + 176 >> 2] = m;
      c[f + 172 >> 2] = m;
      c[f + 168 >> 2] = m;
      c[f + 164 >> 2] = m;
      c[f + 160 >> 2] = m;
      c[f + 156 >> 2] = m;
      c[f + 152 >> 2] = m;
      c[f + 148 >> 2] = m;
      c[f + 144 >> 2] = m;
      c[f + 140 >> 2] = m;
      c[f + 136 >> 2] = m;
      c[f + 132 >> 2] = m;
      c[f + 100 >> 2] = z;
      c[f + 104 >> 2] = z;
      c[f + 108 >> 2] = z;
      c[f + 112 >> 2] = z;
      c[f + 116 >> 2] = o;
      c[f + 120 >> 2] = o;
      c[f + 124 >> 2] = o;
      c[f + 128 >> 2] = o;
      c[L >> 2] = o;
      Ga(n, f + 132 | 0, L, I, H, 0, 0, 16, 16);
     }
    } else K = 486;
   }
   break;
  }
 case 2:
  {
   v = b[g + 160 >> 1] | 0;
   w = b[g + 162 >> 1] | 0;
   x = c[g + 144 >> 2] | 0;
   o = c[f + 204 >> 2] | 0;
   if (!o) {
    j = 0;
    o = -1;
    t = 0;
    u = 0;
   } else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
    u = e[o + 172 >> 1] | e[o + 172 + 2 >> 1] << 16;
    j = 1;
    o = c[o + 108 >> 2] | 0;
    t = u & 65535;
    u = u >>> 16 & 65535;
   } else {
    j = 1;
    o = -1;
    t = 0;
    u = 0;
   } else {
    j = 0;
    o = -1;
    t = 0;
    u = 0;
   }
   f : do if ((o | 0) == (x | 0)) {
    p = t;
    o = u & 65535;
   } else {
    o = c[f + 200 >> 2] | 0;
    if (!o) {
     q = 0;
     p = 0;
     s = 0;
     r = -1;
    } else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
     s = e[o + 152 >> 1] | e[o + 152 + 2 >> 1] << 16;
     q = 1;
     p = s & 65535;
     s = s >>> 16 & 65535;
     r = c[o + 104 >> 2] | 0;
    } else {
     q = 1;
     p = 0;
     s = 0;
     r = -1;
    } else {
     q = 0;
     p = 0;
     s = 0;
     r = -1;
    }
    o = c[f + 208 >> 2] | 0;
    if (!o) K = 312; else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
     j = c[o + 108 >> 2] | 0;
     q = e[o + 172 >> 1] | e[o + 172 + 2 >> 1] << 16;
    } else {
     j = -1;
     q = 0;
    } else K = 312;
    do if ((K | 0) == 312) {
     o = c[f + 212 >> 2] | 0;
     if (o | 0) if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) {
      if ((c[o >> 2] | 0) >>> 0 >= 6) {
       j = -1;
       q = 0;
       break;
      }
      j = c[o + 112 >> 2] | 0;
      q = e[o + 192 >> 1] | e[o + 192 + 2 >> 1] << 16;
      break;
     }
     if ((j | 0) != 0 | (q | 0) == 0) {
      j = -1;
      q = 0;
     } else {
      o = s & 65535;
      break f;
     }
    } while (0);
    o = (r | 0) == (x | 0);
    if ((((j | 0) == (x | 0) & 1) + (o & 1) | 0) != 1) {
     m = p << 16 >> 16;
     E = t << 16 >> 16;
     G = q << 16 >> 16;
     o = t << 16 >> 16 > p << 16 >> 16;
     F = o ? t : p;
     p = o ? m : (E | 0) < (m | 0) ? E : m;
     m = s << 16 >> 16;
     E = u << 16 >> 16;
     o = q >> 16;
     D = u << 16 >> 16 > s << 16 >> 16;
     J = D ? u : s;
     m = D ? m : (E | 0) < (m | 0) ? E : m;
     p = (F << 16 >> 16 < (q & 65535) << 16 >> 16 ? F & 65535 : (p | 0) > (G | 0) ? p : G) & 65535;
     o = J << 16 >> 16 < (q >>> 16 & 65535) << 16 >> 16 ? J & 65535 : (m | 0) > (o | 0) ? m : o;
     break;
    }
    if (o) {
     o = s & 65535;
     break;
    } else {
     p = q & 65535;
     o = q >>> 16;
     break;
    }
   } while (0);
   q = (p & 65535) + (v & 65535) | 0;
   p = (o & 65535) + (w & 65535) | 0;
   if (((q << 16 >> 16) + 8192 | 0) >>> 0 > 16383) K = 486; else if (x >>> 0 > 16 | ((p << 16 >> 16) + 2048 | 0) >>> 0 > 4095) K = 486; else {
    o = c[(c[i + 4 >> 2] | 0) + (x << 2) >> 2] | 0;
    if (!o) K = 486; else if ((c[o + 20 >> 2] | 0) >>> 0 > 1) {
     w = c[o >> 2] | 0;
     if (!w) K = 486; else {
      b[f + 160 >> 1] = q;
      b[f + 162 >> 1] = p;
      s = c[f + 160 >> 2] | 0;
      c[f + 156 >> 2] = s;
      c[f + 152 >> 2] = s;
      c[f + 148 >> 2] = s;
      c[f + 144 >> 2] = s;
      c[f + 140 >> 2] = s;
      c[f + 136 >> 2] = s;
      c[f + 132 >> 2] = s;
      c[f + 100 >> 2] = x;
      c[f + 104 >> 2] = x;
      c[f + 116 >> 2] = w;
      c[f + 120 >> 2] = w;
      t = b[g + 164 >> 1] | 0;
      u = b[g + 166 >> 1] | 0;
      v = c[g + 148 >> 2] | 0;
      p = c[f + 200 >> 2] | 0;
      if (!p) {
       j = 0;
       r = 0;
       o = -1;
      } else if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[p >> 2] | 0) >>> 0 < 6) {
       r = e[p + 184 >> 1] | e[p + 184 + 2 >> 1] << 16;
       j = r & 65535;
       r = r >>> 16 & 65535;
       o = c[p + 112 >> 2] | 0;
      } else {
       j = 0;
       r = 0;
       o = -1;
      } else {
       j = 0;
       r = 0;
       o = -1;
      }
      do if ((o | 0) == (v | 0)) {
       o = r & 65535;
       p = o << 16 | j & 65535;
      } else {
       if (!p) {
        o = -1;
        q = 0;
       } else if ((c[p + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[p >> 2] | 0) >>> 0 < 6) {
        o = c[p + 104 >> 2] | 0;
        q = e[p + 160 >> 1] | e[p + 160 + 2 >> 1] << 16;
       } else {
        o = -1;
        q = 0;
       } else {
        o = -1;
        q = 0;
       }
       if ((((o | 0) == (v | 0) & 1) + ((x | 0) == (v | 0) & 1) | 0) == 1) {
        p = (x | 0) == (v | 0) ? s : q;
        o = (x | 0) == (v | 0) ? s >>> 16 : q >>> 16;
        break;
       } else {
        G = j << 16 >> 16;
        p = q << 16 >> 16;
        m = j << 16 >> 16 < (s & 65535) << 16 >> 16;
        F = m ? s & 65535 : j;
        G = m ? G : (s << 16 >> 16 | 0) < (G | 0) ? s << 16 >> 16 : G;
        m = r << 16 >> 16;
        o = q >> 16;
        E = r << 16 >> 16 < (s >>> 16 & 65535) << 16 >> 16;
        J = E ? s >>> 16 & 65535 : r;
        m = E ? m : (s >> 16 | 0) < (m | 0) ? s >> 16 : m;
        p = F << 16 >> 16 < (q & 65535) << 16 >> 16 ? F & 65535 : (G | 0) > (p | 0) ? G : p;
        o = J << 16 >> 16 < (q >>> 16 & 65535) << 16 >> 16 ? J & 65535 : (m | 0) > (o | 0) ? m : o;
        break;
       }
      } while (0);
      q = (p & 65535) + (t & 65535) | 0;
      p = (o & 65535) + (u & 65535) | 0;
      if (((q << 16 >> 16) + 8192 | 0) >>> 0 > 16383) K = 486; else if (v >>> 0 > 16 | ((p << 16 >> 16) + 2048 | 0) >>> 0 > 4095) K = 486; else {
       o = c[(c[i + 4 >> 2] | 0) + (v << 2) >> 2] | 0;
       if (!o) K = 486; else if ((c[o + 20 >> 2] | 0) >>> 0 > 1) {
        o = c[o >> 2] | 0;
        if (!o) K = 486; else {
         b[f + 192 >> 1] = q;
         b[f + 194 >> 1] = p;
         m = c[f + 192 >> 2] | 0;
         c[f + 188 >> 2] = m;
         c[f + 184 >> 2] = m;
         c[f + 180 >> 2] = m;
         c[f + 176 >> 2] = m;
         c[f + 172 >> 2] = m;
         c[f + 168 >> 2] = m;
         c[f + 164 >> 2] = m;
         c[f + 108 >> 2] = v;
         c[f + 112 >> 2] = v;
         c[f + 124 >> 2] = o;
         c[f + 128 >> 2] = o;
         c[L >> 2] = w;
         Ga(n, f + 132 | 0, L, I, H, 0, 0, 16, 8);
         c[L >> 2] = c[f + 124 >> 2];
         Ga(n, f + 164 | 0, L, I, H, 0, 8, 16, 8);
        }
       } else K = 486;
      }
     }
    } else K = 486;
   }
   break;
  }
 case 3:
  {
   v = b[g + 160 >> 1] | 0;
   w = b[g + 162 >> 1] | 0;
   x = c[g + 144 >> 2] | 0;
   o = c[f + 200 >> 2] | 0;
   if (!o) {
    q = 0;
    p = 0;
    u = 0;
    o = -1;
   } else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
    u = e[o + 152 >> 1] | e[o + 152 + 2 >> 1] << 16;
    q = 1;
    p = u & 65535;
    u = u >>> 16 & 65535;
    o = c[o + 104 >> 2] | 0;
   } else {
    q = 1;
    p = 0;
    u = 0;
    o = -1;
   } else {
    q = 0;
    p = 0;
    u = 0;
    o = -1;
   }
   g : do if ((o | 0) == (x | 0)) o = u & 65535; else {
    o = c[f + 204 >> 2] | 0;
    if (!o) K = 357; else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
     t = e[o + 172 >> 1] | e[o + 172 + 2 >> 1] << 16;
     q = c[o + 108 >> 2] | 0;
     r = t & 65535;
     t = t >>> 16 & 65535;
     s = c[o + 112 >> 2] | 0;
     j = e[o + 188 >> 1] | e[o + 188 + 2 >> 1] << 16;
    } else {
     q = -1;
     r = 0;
     t = 0;
     s = -1;
     j = 0;
    } else K = 357;
    do if ((K | 0) == 357) {
     o = c[f + 212 >> 2] | 0;
     if (o | 0) if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) {
      if ((c[o >> 2] | 0) >>> 0 >= 6) {
       q = -1;
       r = 0;
       t = 0;
       s = -1;
       j = 0;
       break;
      }
      q = -1;
      r = 0;
      t = 0;
      s = c[o + 112 >> 2] | 0;
      j = e[o + 192 >> 1] | e[o + 192 + 2 >> 1] << 16;
      break;
     }
     if (!q) {
      q = -1;
      r = 0;
      t = 0;
      s = -1;
      j = 0;
     } else {
      o = u & 65535;
      break g;
     }
    } while (0);
    o = (q | 0) == (x | 0);
    if (((o & 1) + ((s | 0) == (x | 0) & 1) | 0) != 1) {
     m = p << 16 >> 16;
     E = r << 16 >> 16;
     G = j << 16 >> 16;
     o = r << 16 >> 16 > p << 16 >> 16;
     F = o ? r : p;
     p = o ? m : (E | 0) < (m | 0) ? E : m;
     m = u << 16 >> 16;
     E = t << 16 >> 16;
     o = j >> 16;
     D = t << 16 >> 16 > u << 16 >> 16;
     J = D ? t : u;
     m = D ? m : (E | 0) < (m | 0) ? E : m;
     p = (F << 16 >> 16 < (j & 65535) << 16 >> 16 ? F & 65535 : (p | 0) > (G | 0) ? p : G) & 65535;
     o = J << 16 >> 16 < (j >>> 16 & 65535) << 16 >> 16 ? J & 65535 : (m | 0) > (o | 0) ? m : o;
     break;
    }
    if (o) {
     p = r;
     o = t & 65535;
     break;
    } else {
     p = j & 65535;
     o = j >>> 16;
     break;
    }
   } while (0);
   q = (p & 65535) + (v & 65535) | 0;
   p = (o & 65535) + (w & 65535) | 0;
   if (((q << 16 >> 16) + 8192 | 0) >>> 0 > 16383) K = 486; else if (x >>> 0 > 16 | ((p << 16 >> 16) + 2048 | 0) >>> 0 > 4095) K = 486; else {
    o = c[(c[i + 4 >> 2] | 0) + (x << 2) >> 2] | 0;
    if (!o) K = 486; else if ((c[o + 20 >> 2] | 0) >>> 0 > 1) {
     v = c[o >> 2] | 0;
     if (!v) K = 486; else {
      b[f + 176 >> 1] = q;
      b[f + 178 >> 1] = p;
      r = c[f + 176 >> 2] | 0;
      c[f + 172 >> 2] = r;
      c[f + 168 >> 2] = r;
      c[f + 164 >> 2] = r;
      c[f + 144 >> 2] = r;
      c[f + 140 >> 2] = r;
      c[f + 136 >> 2] = r;
      c[f + 132 >> 2] = r;
      c[f + 100 >> 2] = x;
      c[f + 108 >> 2] = x;
      c[f + 116 >> 2] = v;
      c[f + 124 >> 2] = v;
      s = b[g + 164 >> 1] | 0;
      t = b[g + 166 >> 1] | 0;
      u = c[g + 148 >> 2] | 0;
      o = c[f + 208 >> 2] | 0;
      if (!o) K = 377; else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
       q = 1;
       p = c[o + 108 >> 2] | 0;
       j = e[o + 172 >> 1] | e[o + 172 + 2 >> 1] << 16;
      } else {
       q = 1;
       p = -1;
       j = 0;
      } else K = 377;
      if ((K | 0) == 377) {
       o = c[f + 204 >> 2] | 0;
       if (!o) {
        q = 0;
        p = -1;
        j = 0;
       } else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
        q = 1;
        p = c[o + 108 >> 2] | 0;
        j = e[o + 176 >> 1] | e[o + 176 + 2 >> 1] << 16;
       } else {
        q = 1;
        p = -1;
        j = 0;
       } else {
        q = 0;
        p = -1;
        j = 0;
       }
      }
      do if ((p | 0) == (u | 0)) {
       p = j;
       o = j >>> 16;
      } else {
       o = c[f + 204 >> 2] | 0;
       if (!o) K = 387; else if ((c[o + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[o >> 2] | 0) >>> 0 < 6) {
        q = e[o + 188 >> 1] | e[o + 188 + 2 >> 1] << 16;
        o = c[o + 112 >> 2] | 0;
        p = q & 65535;
        q = q >>> 16 & 65535;
       } else {
        o = -1;
        p = 0;
        q = 0;
       } else K = 387;
       if ((K | 0) == 387) if (!q) {
        p = r;
        o = r >>> 16;
        break;
       } else {
        o = -1;
        p = 0;
        q = 0;
       }
       o = (o | 0) == (u | 0);
       if (((o & 1) + ((x | 0) == (u | 0) & 1) | 0) != 1) {
        m = p << 16 >> 16;
        G = j << 16 >> 16;
        o = p << 16 >> 16 > (r & 65535) << 16 >> 16;
        F = o ? p : r & 65535;
        p = o ? r << 16 >> 16 : (r << 16 >> 16 | 0) > (m | 0) ? m : r << 16 >> 16;
        m = q << 16 >> 16;
        o = j >> 16;
        E = q << 16 >> 16 > (r >>> 16 & 65535) << 16 >> 16;
        J = E ? q : r >>> 16 & 65535;
        m = E ? r >> 16 : (r >> 16 | 0) > (m | 0) ? m : r >> 16;
        p = F << 16 >> 16 < (j & 65535) << 16 >> 16 ? F & 65535 : (p | 0) > (G | 0) ? p : G;
        o = J << 16 >> 16 < (j >>> 16 & 65535) << 16 >> 16 ? J & 65535 : (m | 0) > (o | 0) ? m : o;
        break;
       }
       if ((x | 0) == (u | 0)) {
        p = r;
        o = r >>> 16;
       } else if (o) {
        o = q & 65535;
        p = o << 16 | p & 65535;
        break;
       } else {
        p = j;
        o = j >>> 16;
        break;
       }
      } while (0);
      q = (p & 65535) + (s & 65535) | 0;
      p = (o & 65535) + (t & 65535) | 0;
      if (((q << 16 >> 16) + 8192 | 0) >>> 0 > 16383) K = 486; else if (u >>> 0 > 16 | ((p << 16 >> 16) + 2048 | 0) >>> 0 > 4095) K = 486; else {
       o = c[(c[i + 4 >> 2] | 0) + (u << 2) >> 2] | 0;
       if (!o) K = 486; else if ((c[o + 20 >> 2] | 0) >>> 0 > 1) {
        o = c[o >> 2] | 0;
        if (!o) K = 486; else {
         b[f + 192 >> 1] = q;
         b[f + 194 >> 1] = p;
         m = c[f + 192 >> 2] | 0;
         c[f + 188 >> 2] = m;
         c[f + 184 >> 2] = m;
         c[f + 180 >> 2] = m;
         c[f + 160 >> 2] = m;
         c[f + 156 >> 2] = m;
         c[f + 152 >> 2] = m;
         c[f + 148 >> 2] = m;
         c[f + 104 >> 2] = u;
         c[f + 112 >> 2] = u;
         c[f + 120 >> 2] = o;
         c[f + 128 >> 2] = o;
         c[L >> 2] = v;
         Ga(n, f + 132 | 0, L, I, H, 0, 0, 8, 16);
         c[L >> 2] = c[f + 120 >> 2];
         Ga(n, f + 148 | 0, L, I, H, 8, 0, 8, 16);
        }
       } else K = 486;
      }
     }
    } else K = 486;
   }
   break;
  }
 default:
  {
   o = 0;
   do {
    F = g + 176 + (o << 2) | 0;
    switch (c[F >> 2] | 0) {
    case 0:
     {
      E = 1;
      break;
     }
    case 2:
    case 1:
     {
      E = 2;
      break;
     }
    default:
     E = 4;
    }
    G = g + 192 + (o << 2) | 0;
    c[f + 100 + (o << 2) >> 2] = c[G >> 2];
    q = c[G >> 2] | 0;
    if (q >>> 0 > 16) {
     K = 407;
     break;
    }
    p = c[(c[i + 4 >> 2] | 0) + (q << 2) >> 2] | 0;
    if (!p) {
     K = 407;
     break;
    }
    if ((c[p + 20 >> 2] | 0) >>> 0 <= 1) {
     K = 407;
     break;
    }
    m = c[p >> 2] | 0;
    c[f + 116 + (o << 2) >> 2] = m;
    if (!m) {
     K = 486;
     break e;
    }
    D = o << 2;
    p = 0;
    while (1) {
     A = b[g + 208 + (o << 4) + (p << 2) >> 1] | 0;
     B = b[g + 208 + (o << 4) + (p << 2) + 2 >> 1] | 0;
     C = c[F >> 2] | 0;
     switch (c[1280 + (o << 7) + (C << 5) + (p << 3) >> 2] | 0) {
     case 0:
      {
       j = f + 200 | 0;
       K = 414;
       break;
      }
     case 1:
      {
       j = f + 204 | 0;
       K = 414;
       break;
      }
     case 2:
      {
       j = f + 208 | 0;
       K = 414;
       break;
      }
     case 3:
      {
       j = f + 212 | 0;
       K = 414;
       break;
      }
     case 4:
      {
       j = f;
       K = 415;
       break;
      }
     default:
      {
       t = 0;
       x = -1;
       z = 0;
       y = 0;
      }
     }
     if ((K | 0) == 414) {
      j = c[j >> 2] | 0;
      K = 415;
     }
     if ((K | 0) == 415) {
      K = 0;
      r = d[1280 + (o << 7) + (C << 5) + (p << 3) + 4 >> 0] | 0;
      if (!j) {
       t = 0;
       x = -1;
       z = 0;
       y = 0;
      } else if ((c[j + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[j >> 2] | 0) >>> 0 < 6) {
       y = j + 132 + (r << 2) | 0;
       y = e[y >> 1] | e[y + 2 >> 1] << 16;
       t = 1;
       x = c[j + 100 + (r >>> 2 << 2) >> 2] | 0;
       z = y & 65535;
       y = y >>> 16 & 65535;
      } else {
       t = 1;
       x = -1;
       z = 0;
       y = 0;
      } else {
       t = 0;
       x = -1;
       z = 0;
       y = 0;
      }
     }
     switch (c[1792 + (o << 7) + (C << 5) + (p << 3) >> 2] | 0) {
     case 0:
      {
       j = f + 200 | 0;
       K = 423;
       break;
      }
     case 1:
      {
       j = f + 204 | 0;
       K = 423;
       break;
      }
     case 2:
      {
       j = f + 208 | 0;
       K = 423;
       break;
      }
     case 3:
      {
       j = f + 212 | 0;
       K = 423;
       break;
      }
     case 4:
      {
       r = f;
       K = 424;
       break;
      }
     default:
      {
       s = 0;
       u = -1;
       w = 0;
       v = 0;
      }
     }
     if ((K | 0) == 423) {
      r = c[j >> 2] | 0;
      K = 424;
     }
     if ((K | 0) == 424) {
      j = d[1792 + (o << 7) + (C << 5) + (p << 3) + 4 >> 0] | 0;
      if (!r) {
       s = 0;
       u = -1;
       w = 0;
       v = 0;
      } else if ((c[r + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[r >> 2] | 0) >>> 0 < 6) {
       v = r + 132 + (j << 2) | 0;
       v = e[v >> 1] | e[v + 2 >> 1] << 16;
       s = 1;
       u = c[r + 100 + (j >>> 2 << 2) >> 2] | 0;
       w = v & 65535;
       v = v >>> 16 & 65535;
      } else {
       s = 1;
       u = -1;
       w = 0;
       v = 0;
      } else {
       s = 0;
       u = -1;
       w = 0;
       v = 0;
      }
     }
     switch (c[2304 + (o << 7) + (C << 5) + (p << 3) >> 2] | 0) {
     case 0:
      {
       j = f + 200 | 0;
       K = 432;
       break;
      }
     case 1:
      {
       j = f + 204 | 0;
       K = 432;
       break;
      }
     case 2:
      {
       j = f + 208 | 0;
       K = 432;
       break;
      }
     case 3:
      {
       j = f + 212 | 0;
       K = 432;
       break;
      }
     case 4:
      {
       r = f;
       K = 433;
       break;
      }
     default:
      K = 437;
     }
     if ((K | 0) == 432) {
      r = c[j >> 2] | 0;
      K = 433;
     }
     if ((K | 0) == 433) {
      j = d[2304 + (o << 7) + (C << 5) + (p << 3) + 4 >> 0] | 0;
      if (!r) K = 437; else if ((c[r + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) if ((c[r >> 2] | 0) >>> 0 < 6) {
       t = r + 132 + (j << 2) | 0;
       s = c[r + 100 + (j >>> 2 << 2) >> 2] | 0;
       t = e[t >> 1] | e[t + 2 >> 1] << 16;
       K = 447;
      } else {
       s = -1;
       t = 0;
       K = 447;
      } else K = 437;
     }
     do if ((K | 0) == 437) {
      K = 0;
      switch (c[2816 + (o << 7) + (C << 5) + (p << 3) >> 2] | 0) {
      case 0:
       {
        j = f + 200 | 0;
        K = 441;
        break;
       }
      case 1:
       {
        j = f + 204 | 0;
        K = 441;
        break;
       }
      case 2:
       {
        j = f + 208 | 0;
        K = 441;
        break;
       }
      case 3:
       {
        j = f + 212 | 0;
        K = 441;
        break;
       }
      case 4:
       {
        j = f;
        K = 442;
        break;
       }
      default:
       {}
      }
      if ((K | 0) == 441) {
       j = c[j >> 2] | 0;
       K = 442;
      }
      if ((K | 0) == 442) {
       K = 0;
       r = d[2816 + (o << 7) + (C << 5) + (p << 3) + 4 >> 0] | 0;
       if (j | 0) if ((c[j + 4 >> 2] | 0) == (c[f + 4 >> 2] | 0)) {
        if ((c[j >> 2] | 0) >>> 0 >= 6) {
         s = -1;
         t = 0;
         K = 447;
         break;
        }
        t = j + 132 + (r << 2) | 0;
        s = c[j + 100 + (r >>> 2 << 2) >> 2] | 0;
        t = e[t >> 1] | e[t + 2 >> 1] << 16;
        K = 447;
        break;
       }
      }
      if ((t | 0) == 0 | (s | 0) != 0) {
       s = -1;
       t = 0;
       K = 447;
      } else {
       j = y & 65535;
       q = z;
      }
     } while (0);
     do if ((K | 0) == 447) {
      K = 0;
      r = (x | 0) == (q | 0);
      j = (u | 0) == (q | 0);
      if (((j & 1) + (r & 1) + ((s | 0) == (q | 0) & 1) | 0) != 1) {
       m = z << 16 >> 16;
       x = w << 16 >> 16;
       q = t << 16 >> 16;
       j = w << 16 >> 16 > z << 16 >> 16;
       J = j ? w : z;
       m = j ? m : (x | 0) < (m | 0) ? x : m;
       z = y << 16 >> 16;
       x = v << 16 >> 16;
       j = t >> 16;
       w = v << 16 >> 16 > y << 16 >> 16;
       y = w ? v : y;
       z = w ? z : (x | 0) < (z | 0) ? x : z;
       j = y << 16 >> 16 < (t >>> 16 & 65535) << 16 >> 16 ? y & 65535 : (z | 0) > (j | 0) ? z : j;
       q = (J << 16 >> 16 < (t & 65535) << 16 >> 16 ? J & 65535 : (m | 0) > (q | 0) ? m : q) & 65535;
       break;
      }
      if (r) {
       j = y & 65535;
       q = z;
       break;
      }
      if (j) {
       j = v & 65535;
       q = w;
       break;
      } else {
       j = t >>> 16;
       q = t & 65535;
       break;
      }
     } while (0);
     r = (q & 65535) + (A & 65535) | 0;
     j = (j & 65535) + (B & 65535) | 0;
     if (((r << 16 >> 16) + 8192 | 0) >>> 0 > 16383) {
      K = 486;
      break e;
     }
     if (((j << 16 >> 16) + 2048 | 0) >>> 0 > 4095) {
      K = 486;
      break e;
     }
     switch (C | 0) {
     case 0:
      {
       b[f + 132 + (D << 2) >> 1] = r;
       b[f + 132 + (D << 2) + 2 >> 1] = j;
       b[f + 132 + ((D | 1) << 2) >> 1] = r;
       b[f + 132 + ((D | 1) << 2) + 2 >> 1] = j;
       b[f + 132 + ((D | 2) << 2) >> 1] = r;
       b[f + 132 + ((D | 2) << 2) + 2 >> 1] = j;
       q = D | 3;
       K = 462;
       break;
      }
     case 1:
      {
       q = (p << 1) + D | 0;
       b[f + 132 + (q << 2) >> 1] = r;
       b[f + 132 + (q << 2) + 2 >> 1] = j;
       q = q | 1;
       K = 462;
       break;
      }
     case 2:
      {
       q = p + D | 0;
       b[f + 132 + (q << 2) >> 1] = r;
       b[f + 132 + (q << 2) + 2 >> 1] = j;
       q = q + 2 | 0;
       K = 462;
       break;
      }
     case 3:
      {
       q = p + D | 0;
       K = 462;
       break;
      }
     default:
      {}
     }
     if ((K | 0) == 462) {
      K = 0;
      b[f + 132 + (q << 2) >> 1] = r;
      b[f + 132 + (q << 2) + 2 >> 1] = j;
     }
     p = p + 1 | 0;
     if (p >>> 0 >= E >>> 0) break;
     q = c[G >> 2] | 0;
    }
    o = o + 1 | 0;
   } while (o >>> 0 < 4);
   if ((K | 0) == 407) {
    c[f + 116 + (o << 2) >> 2] = 0;
    K = 486;
    break e;
   }
   o = 0;
   while (1) {
    c[L >> 2] = c[f + 116 + (o << 2) >> 2];
    p = o << 3 & 8;
    q = o >>> 0 < 2 ? 0 : 8;
    switch (c[g + 176 + (o << 2) >> 2] | 0) {
    case 0:
     {
      Ga(n, f + 132 + (o << 2 << 2) | 0, L, I, H, p, q, 8, 8);
      break;
     }
    case 1:
     {
      m = f + 132 + (o << 2 << 2) | 0;
      Ga(n, m, L, I, H, p, q, 8, 4);
      Ga(n, m + 8 | 0, L, I, H, p, q | 4, 8, 4);
      break;
     }
    case 2:
     {
      m = f + 132 + (o << 2 << 2) | 0;
      Ga(n, m, L, I, H, p, q, 4, 8);
      Ga(n, m + 4 | 0, L, I, H, p | 4, q, 4, 8);
      break;
     }
    default:
     {
      m = f + 132 + (o << 2 << 2) | 0;
      Ga(n, m, L, I, H, p, q, 4, 4);
      Ga(n, m + 4 | 0, L, I, H, p | 4, q, 4, 4);
      Ga(n, m + 8 | 0, L, I, H, p, q | 4, 4, 4);
      Ga(n, m + 12 | 0, L, I, H, p | 4, q | 4, 4, 4);
     }
    }
    o = o + 1 | 0;
    if ((o | 0) == 4) break e;
   }
  }
 } while (0);
 if ((K | 0) == 486) {
  n = 1;
  l = L;
  return n | 0;
 }
 do if ((c[f + 196 >> 2] | 0) >>> 0 <= 1) {
  if (!(c[f >> 2] | 0)) {
   Ka(h, n);
   break;
  }
  t = c[h + 4 >> 2] | 0;
  u = N(c[h + 8 >> 2] | 0, t) | 0;
  p = c[h >> 2] | 0;
  o = 0;
  do {
   q = c[1152 + (o << 2) >> 2] | 0;
   j = c[1216 + (o << 2) >> 2] | 0;
   r = p + (k - ((k >>> 0) % (t >>> 0) | 0) << 8) + (((k >>> 0) % (t >>> 0) | 0) << 4) + (N(j, t << 4) | 0) + q | 0;
   s = c[g + 328 + (o << 6) >> 2] | 0;
   if ((s | 0) == 16777215) {
    h = c[n + (j << 4) + q + 16 >> 2] | 0;
    K = n + (j << 4) + q + 16 + 16 | 0;
    c[r >> 2] = c[n + (j << 4) + q >> 2];
    c[r + ((t << 2 & 1073741820) << 2) >> 2] = h;
    h = r + ((t << 2 & 1073741820) << 2) + ((t << 2 & 1073741820) << 2) | 0;
    f = c[K + 16 >> 2] | 0;
    c[h >> 2] = c[K >> 2];
    c[h + ((t << 2 & 1073741820) << 2) >> 2] = f;
   } else {
    h = d[n + (j << 4) + q + 1 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 4 >> 2] | 0;
    a[r >> 0] = a[6162 + (s + (d[n + (j << 4) + q >> 0] | 0)) >> 0] | 0;
    f = d[n + (j << 4) + q + 2 >> 0] | 0;
    i = c[g + 328 + (o << 6) + 8 >> 2] | 0;
    a[r + 1 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = d[n + (j << 4) + q + 3 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 12 >> 2] | 0;
    a[r + 2 >> 0] = a[6162 + (i + f) >> 0] | 0;
    f = n + (j << 4) + q + 16 | 0;
    a[r + 3 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = d[f + 1 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 20 >> 2] | 0;
    a[r + (t << 4) >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 16 >> 2] | 0) + (d[f >> 0] | 0)) >> 0] | 0;
    i = d[f + 2 >> 0] | 0;
    m = c[g + 328 + (o << 6) + 24 >> 2] | 0;
    a[r + (t << 4) + 1 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = d[f + 3 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 28 >> 2] | 0;
    a[r + (t << 4) + 2 >> 0] = a[6162 + (m + i) >> 0] | 0;
    a[r + (t << 4) + 3 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = r + (t << 4) + (t << 4) | 0;
    K = d[f + 16 + 1 >> 0] | 0;
    i = c[g + 328 + (o << 6) + 36 >> 2] | 0;
    a[h >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 32 >> 2] | 0) + (d[f + 16 >> 0] | 0)) >> 0] | 0;
    m = d[f + 16 + 2 >> 0] | 0;
    J = c[g + 328 + (o << 6) + 40 >> 2] | 0;
    a[h + 1 >> 0] = a[6162 + (i + K) >> 0] | 0;
    K = d[f + 16 + 3 >> 0] | 0;
    i = c[g + 328 + (o << 6) + 44 >> 2] | 0;
    a[h + 2 >> 0] = a[6162 + (J + m) >> 0] | 0;
    a[h + 3 >> 0] = a[6162 + (i + K) >> 0] | 0;
    K = d[f + 16 + 16 + 1 >> 0] | 0;
    i = c[g + 328 + (o << 6) + 52 >> 2] | 0;
    a[h + (t << 4) >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 48 >> 2] | 0) + (d[f + 16 + 16 >> 0] | 0)) >> 0] | 0;
    m = d[f + 16 + 16 + 2 >> 0] | 0;
    J = c[g + 328 + (o << 6) + 56 >> 2] | 0;
    a[h + (t << 4) + 1 >> 0] = a[6162 + (i + K) >> 0] | 0;
    f = d[f + 16 + 16 + 3 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 60 >> 2] | 0;
    a[h + (t << 4) + 2 >> 0] = a[6162 + (J + m) >> 0] | 0;
    a[h + (t << 4) + 3 >> 0] = a[6162 + (K + f) >> 0] | 0;
   }
   o = o + 1 | 0;
  } while ((o | 0) != 16);
  p = p + (u << 8) + (k - ((k >>> 0) % (t >>> 0) | 0) << 6) + (((k >>> 0) % (t >>> 0) | 0) << 3) | 0;
  o = 16;
  do {
   r = o & 3;
   j = c[1152 + (r << 2) >> 2] | 0;
   r = c[1216 + (r << 2) >> 2] | 0;
   h = o >>> 0 > 19;
   q = n + (h ? 320 : 256) + ((r << 3) + j) | 0;
   j = (h ? p + (u << 6) | 0 : p) + ((N(r, t << 3 & 2147483640) | 0) + j) | 0;
   r = c[g + 328 + (o << 6) >> 2] | 0;
   if ((r | 0) == 16777215) {
    h = c[q + 8 >> 2] | 0;
    c[j >> 2] = c[q >> 2];
    c[j + ((t << 3 & 2147483640) >>> 2 << 2) >> 2] = h;
    h = j + ((t << 3 & 2147483640) >>> 2 << 2) + ((t << 3 & 2147483640) >>> 2 << 2) | 0;
    f = c[q + 8 + 8 + 8 >> 2] | 0;
    c[h >> 2] = c[q + 8 + 8 >> 2];
    c[h + ((t << 3 & 2147483640) >>> 2 << 2) >> 2] = f;
   } else {
    h = d[q + 1 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 4 >> 2] | 0;
    a[j >> 0] = a[6162 + (r + (d[q >> 0] | 0)) >> 0] | 0;
    k = d[q + 2 >> 0] | 0;
    f = c[g + 328 + (o << 6) + 8 >> 2] | 0;
    a[j + 1 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = d[q + 3 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 12 >> 2] | 0;
    a[j + 2 >> 0] = a[6162 + (f + k) >> 0] | 0;
    a[j + 3 >> 0] = a[6162 + (K + h) >> 0] | 0;
    h = j + (t << 3 & 2147483640) | 0;
    K = d[q + 8 + 1 >> 0] | 0;
    k = c[g + 328 + (o << 6) + 20 >> 2] | 0;
    a[h >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 16 >> 2] | 0) + (d[q + 8 >> 0] | 0)) >> 0] | 0;
    f = d[q + 8 + 2 >> 0] | 0;
    m = c[g + 328 + (o << 6) + 24 >> 2] | 0;
    a[h + 1 >> 0] = a[6162 + (k + K) >> 0] | 0;
    K = d[q + 8 + 3 >> 0] | 0;
    k = c[g + 328 + (o << 6) + 28 >> 2] | 0;
    a[h + 2 >> 0] = a[6162 + (m + f) >> 0] | 0;
    f = q + 8 + 8 | 0;
    a[h + 3 >> 0] = a[6162 + (k + K) >> 0] | 0;
    h = h + (t << 3 & 2147483640) | 0;
    K = d[f + 1 >> 0] | 0;
    k = c[g + 328 + (o << 6) + 36 >> 2] | 0;
    a[h >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 32 >> 2] | 0) + (d[f >> 0] | 0)) >> 0] | 0;
    m = d[f + 2 >> 0] | 0;
    J = c[g + 328 + (o << 6) + 40 >> 2] | 0;
    a[h + 1 >> 0] = a[6162 + (k + K) >> 0] | 0;
    K = d[f + 3 >> 0] | 0;
    k = c[g + 328 + (o << 6) + 44 >> 2] | 0;
    a[h + 2 >> 0] = a[6162 + (J + m) >> 0] | 0;
    a[h + 3 >> 0] = a[6162 + (k + K) >> 0] | 0;
    K = d[f + 8 + 1 >> 0] | 0;
    k = c[g + 328 + (o << 6) + 52 >> 2] | 0;
    a[h + (t << 3 & 2147483640) >> 0] = a[6162 + ((c[g + 328 + (o << 6) + 48 >> 2] | 0) + (d[f + 8 >> 0] | 0)) >> 0] | 0;
    m = d[f + 8 + 2 >> 0] | 0;
    J = c[g + 328 + (o << 6) + 56 >> 2] | 0;
    a[h + (t << 3 & 2147483640) + 1 >> 0] = a[6162 + (k + K) >> 0] | 0;
    f = d[f + 8 + 3 >> 0] | 0;
    K = c[g + 328 + (o << 6) + 60 >> 2] | 0;
    a[h + (t << 3 & 2147483640) + 2 >> 0] = a[6162 + (J + m) >> 0] | 0;
    a[h + (t << 3 & 2147483640) + 3 >> 0] = a[6162 + (K + f) >> 0] | 0;
   }
   o = o + 1 | 0;
  } while ((o | 0) != 24);
 } while (0);
 n = 0;
 l = L;
 return n | 0;
}

function _a(a) {
 a = a | 0;
 var b = 0, d = 0, e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0, m = 0, n = 0, o = 0, p = 0;
 p = l;
 l = l + 16 | 0;
 do if (a >>> 0 < 245) {
  n = a >>> 0 < 11 ? 16 : a + 11 & -8;
  k = c[1833] | 0;
  if (k >>> (n >>> 3) & 3 | 0) {
   a = 7372 + ((k >>> (n >>> 3) & 1 ^ 1) + (n >>> 3) << 1 << 2) | 0;
   b = c[a + 8 >> 2] | 0;
   d = c[b + 8 >> 2] | 0;
   if ((d | 0) == (a | 0)) c[1833] = k & ~(1 << (k >>> (n >>> 3) & 1 ^ 1) + (n >>> 3)); else {
    c[d + 12 >> 2] = a;
    c[a + 8 >> 2] = d;
   }
   o = (k >>> (n >>> 3) & 1 ^ 1) + (n >>> 3) << 3;
   c[b + 4 >> 2] = o | 3;
   c[b + o + 4 >> 2] = c[b + o + 4 >> 2] | 1;
   o = b + 8 | 0;
   l = p;
   return o | 0;
  }
  m = c[1835] | 0;
  if (n >>> 0 > m >>> 0) {
   if (k >>> (n >>> 3) | 0) {
    a = k >>> (n >>> 3) << (n >>> 3) & (2 << (n >>> 3) | 0 - (2 << (n >>> 3)));
    f = ((a & 0 - a) + -1 | 0) >>> (((a & 0 - a) + -1 | 0) >>> 12 & 16);
    e = f >>> (f >>> 5 & 8) >>> (f >>> (f >>> 5 & 8) >>> 2 & 4);
    e = (f >>> 5 & 8 | ((a & 0 - a) + -1 | 0) >>> 12 & 16 | f >>> (f >>> 5 & 8) >>> 2 & 4 | e >>> 1 & 2 | e >>> (e >>> 1 & 2) >>> 1 & 1) + (e >>> (e >>> 1 & 2) >>> (e >>> (e >>> 1 & 2) >>> 1 & 1)) | 0;
    f = c[7372 + (e << 1 << 2) + 8 >> 2] | 0;
    a = c[f + 8 >> 2] | 0;
    if ((a | 0) == (7372 + (e << 1 << 2) | 0)) {
     c[1833] = k & ~(1 << e);
     a = k & ~(1 << e);
    } else {
     c[a + 12 >> 2] = 7372 + (e << 1 << 2);
     c[7372 + (e << 1 << 2) + 8 >> 2] = a;
     a = k;
    }
    c[f + 4 >> 2] = n | 3;
    c[f + n + 4 >> 2] = (e << 3) - n | 1;
    c[f + (e << 3) >> 2] = (e << 3) - n;
    if (m | 0) {
     d = c[1838] | 0;
     if (!(a & 1 << (m >>> 3))) {
      c[1833] = a | 1 << (m >>> 3);
      a = 7372 + (m >>> 3 << 1 << 2) | 0;
      b = 7372 + (m >>> 3 << 1 << 2) + 8 | 0;
     } else {
      a = c[7372 + (m >>> 3 << 1 << 2) + 8 >> 2] | 0;
      b = 7372 + (m >>> 3 << 1 << 2) + 8 | 0;
     }
     c[b >> 2] = d;
     c[a + 12 >> 2] = d;
     c[d + 8 >> 2] = a;
     c[d + 12 >> 2] = 7372 + (m >>> 3 << 1 << 2);
    }
    c[1835] = (e << 3) - n;
    c[1838] = f + n;
    o = f + 8 | 0;
    l = p;
    return o | 0;
   }
   j = c[1834] | 0;
   if (j) {
    b = ((j & 0 - j) + -1 | 0) >>> (((j & 0 - j) + -1 | 0) >>> 12 & 16);
    a = b >>> (b >>> 5 & 8) >>> (b >>> (b >>> 5 & 8) >>> 2 & 4);
    a = c[7636 + ((b >>> 5 & 8 | ((j & 0 - j) + -1 | 0) >>> 12 & 16 | b >>> (b >>> 5 & 8) >>> 2 & 4 | a >>> 1 & 2 | a >>> (a >>> 1 & 2) >>> 1 & 1) + (a >>> (a >>> 1 & 2) >>> (a >>> (a >>> 1 & 2) >>> 1 & 1)) << 2) >> 2] | 0;
    b = (c[a + 4 >> 2] & -8) - n | 0;
    d = c[a + 16 + (((c[a + 16 >> 2] | 0) == 0 & 1) << 2) >> 2] | 0;
    if (!d) {
     i = a;
     g = b;
    } else {
     do {
      h = (c[d + 4 >> 2] & -8) - n | 0;
      i = h >>> 0 < b >>> 0;
      b = i ? h : b;
      a = i ? d : a;
      d = c[d + 16 + (((c[d + 16 >> 2] | 0) == 0 & 1) << 2) >> 2] | 0;
     } while ((d | 0) != 0);
     i = a;
     g = b;
    }
    h = i + n | 0;
    if (h >>> 0 > i >>> 0) {
     f = c[i + 24 >> 2] | 0;
     a = c[i + 12 >> 2] | 0;
     do if ((a | 0) == (i | 0)) {
      b = i + 20 | 0;
      a = c[b >> 2] | 0;
      if (!a) {
       b = i + 16 | 0;
       a = c[b >> 2] | 0;
       if (!a) {
        b = 0;
        break;
       }
      }
      while (1) {
       d = a + 20 | 0;
       e = c[d >> 2] | 0;
       if (e | 0) {
        a = e;
        b = d;
        continue;
       }
       d = a + 16 | 0;
       e = c[d >> 2] | 0;
       if (!e) break; else {
        a = e;
        b = d;
       }
      }
      c[b >> 2] = 0;
      b = a;
     } else {
      b = c[i + 8 >> 2] | 0;
      c[b + 12 >> 2] = a;
      c[a + 8 >> 2] = b;
      b = a;
     } while (0);
     do if (f | 0) {
      a = c[i + 28 >> 2] | 0;
      if ((i | 0) == (c[7636 + (a << 2) >> 2] | 0)) {
       c[7636 + (a << 2) >> 2] = b;
       if (!b) {
        c[1834] = j & ~(1 << a);
        break;
       }
      } else {
       c[f + 16 + (((c[f + 16 >> 2] | 0) != (i | 0) & 1) << 2) >> 2] = b;
       if (!b) break;
      }
      c[b + 24 >> 2] = f;
      a = c[i + 16 >> 2] | 0;
      if (a | 0) {
       c[b + 16 >> 2] = a;
       c[a + 24 >> 2] = b;
      }
      a = c[i + 20 >> 2] | 0;
      if (a | 0) {
       c[b + 20 >> 2] = a;
       c[a + 24 >> 2] = b;
      }
     } while (0);
     if (g >>> 0 < 16) {
      o = g + n | 0;
      c[i + 4 >> 2] = o | 3;
      o = i + o + 4 | 0;
      c[o >> 2] = c[o >> 2] | 1;
     } else {
      c[i + 4 >> 2] = n | 3;
      c[h + 4 >> 2] = g | 1;
      c[h + g >> 2] = g;
      if (m | 0) {
       d = c[1838] | 0;
       if (!(1 << (m >>> 3) & k)) {
        c[1833] = 1 << (m >>> 3) | k;
        a = 7372 + (m >>> 3 << 1 << 2) | 0;
        b = 7372 + (m >>> 3 << 1 << 2) + 8 | 0;
       } else {
        a = c[7372 + (m >>> 3 << 1 << 2) + 8 >> 2] | 0;
        b = 7372 + (m >>> 3 << 1 << 2) + 8 | 0;
       }
       c[b >> 2] = d;
       c[a + 12 >> 2] = d;
       c[d + 8 >> 2] = a;
       c[d + 12 >> 2] = 7372 + (m >>> 3 << 1 << 2);
      }
      c[1835] = g;
      c[1838] = h;
     }
     o = i + 8 | 0;
     l = p;
     return o | 0;
    }
   }
  }
 } else if (a >>> 0 > 4294967231) n = -1; else {
  n = a + 11 & -8;
  j = c[1834] | 0;
  if (j) {
   if (!((a + 11 | 0) >>> 8)) h = 0; else if (n >>> 0 > 16777215) h = 31; else {
    h = (a + 11 | 0) >>> 8 << ((((a + 11 | 0) >>> 8) + 1048320 | 0) >>> 16 & 8);
    h = 14 - ((h + 520192 | 0) >>> 16 & 4 | (((a + 11 | 0) >>> 8) + 1048320 | 0) >>> 16 & 8 | ((h << ((h + 520192 | 0) >>> 16 & 4)) + 245760 | 0) >>> 16 & 2) + (h << ((h + 520192 | 0) >>> 16 & 4) << (((h << ((h + 520192 | 0) >>> 16 & 4)) + 245760 | 0) >>> 16 & 2) >>> 15) | 0;
    h = n >>> (h + 7 | 0) & 1 | h << 1;
   }
   a = c[7636 + (h << 2) >> 2] | 0;
   a : do if (!a) {
    b = 0;
    a = 0;
    d = 0 - n | 0;
    o = 57;
   } else {
    f = 0;
    d = 0 - n | 0;
    g = n << ((h | 0) == 31 ? 0 : 25 - (h >>> 1) | 0);
    b = 0;
    while (1) {
     e = (c[a + 4 >> 2] & -8) - n | 0;
     if (e >>> 0 < d >>> 0) if (!e) {
      d = 0;
      b = a;
      o = 61;
      break a;
     } else {
      f = a;
      d = e;
     }
     e = c[a + 20 >> 2] | 0;
     a = c[a + 16 + (g >>> 31 << 2) >> 2] | 0;
     b = (e | 0) == 0 | (e | 0) == (a | 0) ? b : e;
     e = (a | 0) == 0;
     if (e) {
      a = f;
      o = 57;
      break;
     } else g = g << ((e ^ 1) & 1);
    }
   } while (0);
   if ((o | 0) == 57) {
    if ((b | 0) == 0 & (a | 0) == 0) {
     a = 2 << h;
     if (!((a | 0 - a) & j)) break;
     k = ((a | 0 - a) & j & 0 - ((a | 0 - a) & j)) + -1 | 0;
     m = k >>> (k >>> 12 & 16) >>> (k >>> (k >>> 12 & 16) >>> 5 & 8);
     b = m >>> (m >>> 2 & 4) >>> (m >>> (m >>> 2 & 4) >>> 1 & 2);
     a = 0;
     b = c[7636 + ((k >>> (k >>> 12 & 16) >>> 5 & 8 | k >>> 12 & 16 | m >>> 2 & 4 | m >>> (m >>> 2 & 4) >>> 1 & 2 | b >>> 1 & 1) + (b >>> (b >>> 1 & 1)) << 2) >> 2] | 0;
    }
    if (!b) i = a; else o = 61;
   }
   if ((o | 0) == 61) while (1) {
    o = 0;
    k = (c[b + 4 >> 2] & -8) - n | 0;
    m = k >>> 0 < d >>> 0;
    d = m ? k : d;
    a = m ? b : a;
    b = c[b + 16 + (((c[b + 16 >> 2] | 0) == 0 & 1) << 2) >> 2] | 0;
    if (!b) {
     i = a;
     break;
    } else o = 61;
   }
   if (i) if (d >>> 0 < ((c[1835] | 0) - n | 0) >>> 0) {
    h = i + n | 0;
    if (h >>> 0 <= i >>> 0) {
     o = 0;
     l = p;
     return o | 0;
    }
    g = c[i + 24 >> 2] | 0;
    a = c[i + 12 >> 2] | 0;
    do if ((a | 0) == (i | 0)) {
     b = i + 20 | 0;
     a = c[b >> 2] | 0;
     if (!a) {
      b = i + 16 | 0;
      a = c[b >> 2] | 0;
      if (!a) {
       a = 0;
       break;
      }
     }
     while (1) {
      e = a + 20 | 0;
      f = c[e >> 2] | 0;
      if (f | 0) {
       a = f;
       b = e;
       continue;
      }
      e = a + 16 | 0;
      f = c[e >> 2] | 0;
      if (!f) break; else {
       a = f;
       b = e;
      }
     }
     c[b >> 2] = 0;
    } else {
     o = c[i + 8 >> 2] | 0;
     c[o + 12 >> 2] = a;
     c[a + 8 >> 2] = o;
    } while (0);
    do if (!g) f = j; else {
     b = c[i + 28 >> 2] | 0;
     if ((i | 0) == (c[7636 + (b << 2) >> 2] | 0)) {
      c[7636 + (b << 2) >> 2] = a;
      if (!a) {
       c[1834] = j & ~(1 << b);
       f = j & ~(1 << b);
       break;
      }
     } else {
      c[g + 16 + (((c[g + 16 >> 2] | 0) != (i | 0) & 1) << 2) >> 2] = a;
      if (!a) {
       f = j;
       break;
      }
     }
     c[a + 24 >> 2] = g;
     b = c[i + 16 >> 2] | 0;
     if (b | 0) {
      c[a + 16 >> 2] = b;
      c[b + 24 >> 2] = a;
     }
     b = c[i + 20 >> 2] | 0;
     if (!b) f = j; else {
      c[a + 20 >> 2] = b;
      c[b + 24 >> 2] = a;
      f = j;
     }
    } while (0);
    do if (d >>> 0 < 16) {
     o = d + n | 0;
     c[i + 4 >> 2] = o | 3;
     o = i + o + 4 | 0;
     c[o >> 2] = c[o >> 2] | 1;
    } else {
     c[i + 4 >> 2] = n | 3;
     c[h + 4 >> 2] = d | 1;
     c[h + d >> 2] = d;
     e = d >>> 3;
     if (d >>> 0 < 256) {
      a = c[1833] | 0;
      if (!(a & 1 << e)) {
       c[1833] = a | 1 << e;
       a = 7372 + (e << 1 << 2) | 0;
       b = 7372 + (e << 1 << 2) + 8 | 0;
      } else {
       a = c[7372 + (e << 1 << 2) + 8 >> 2] | 0;
       b = 7372 + (e << 1 << 2) + 8 | 0;
      }
      c[b >> 2] = h;
      c[a + 12 >> 2] = h;
      c[h + 8 >> 2] = a;
      c[h + 12 >> 2] = 7372 + (e << 1 << 2);
      break;
     }
     a = d >>> 8;
     if (!a) a = 0; else if (d >>> 0 > 16777215) a = 31; else {
      o = a << ((a + 1048320 | 0) >>> 16 & 8) << (((a << ((a + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4);
      a = 14 - (((a << ((a + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4 | (a + 1048320 | 0) >>> 16 & 8 | (o + 245760 | 0) >>> 16 & 2) + (o << ((o + 245760 | 0) >>> 16 & 2) >>> 15) | 0;
      a = d >>> (a + 7 | 0) & 1 | a << 1;
     }
     e = 7636 + (a << 2) | 0;
     c[h + 28 >> 2] = a;
     c[h + 16 + 4 >> 2] = 0;
     c[h + 16 >> 2] = 0;
     b = 1 << a;
     if (!(b & f)) {
      c[1834] = b | f;
      c[e >> 2] = h;
      c[h + 24 >> 2] = e;
      c[h + 12 >> 2] = h;
      c[h + 8 >> 2] = h;
      break;
     }
     b = d << ((a | 0) == 31 ? 0 : 25 - (a >>> 1) | 0);
     e = c[e >> 2] | 0;
     while (1) {
      if ((c[e + 4 >> 2] & -8 | 0) == (d | 0)) {
       o = 97;
       break;
      }
      f = e + 16 + (b >>> 31 << 2) | 0;
      a = c[f >> 2] | 0;
      if (!a) {
       o = 96;
       break;
      } else {
       b = b << 1;
       e = a;
      }
     }
     if ((o | 0) == 96) {
      c[f >> 2] = h;
      c[h + 24 >> 2] = e;
      c[h + 12 >> 2] = h;
      c[h + 8 >> 2] = h;
      break;
     } else if ((o | 0) == 97) {
      n = e + 8 | 0;
      o = c[n >> 2] | 0;
      c[o + 12 >> 2] = h;
      c[n >> 2] = h;
      c[h + 8 >> 2] = o;
      c[h + 12 >> 2] = e;
      c[h + 24 >> 2] = 0;
      break;
     }
    } while (0);
    o = i + 8 | 0;
    l = p;
    return o | 0;
   }
  }
 } while (0);
 d = c[1835] | 0;
 if (d >>> 0 >= n >>> 0) {
  a = d - n | 0;
  b = c[1838] | 0;
  if (a >>> 0 > 15) {
   o = b + n | 0;
   c[1838] = o;
   c[1835] = a;
   c[o + 4 >> 2] = a | 1;
   c[b + d >> 2] = a;
   c[b + 4 >> 2] = n | 3;
  } else {
   c[1835] = 0;
   c[1838] = 0;
   c[b + 4 >> 2] = d | 3;
   c[b + d + 4 >> 2] = c[b + d + 4 >> 2] | 1;
  }
  o = b + 8 | 0;
  l = p;
  return o | 0;
 }
 g = c[1836] | 0;
 if (g >>> 0 > n >>> 0) {
  k = g - n | 0;
  c[1836] = k;
  o = c[1839] | 0;
  m = o + n | 0;
  c[1839] = m;
  c[m + 4 >> 2] = k | 1;
  c[o + 4 >> 2] = n | 3;
  o = o + 8 | 0;
  l = p;
  return o | 0;
 }
 if (!(c[1951] | 0)) {
  c[1953] = 4096;
  c[1952] = 4096;
  c[1954] = -1;
  c[1955] = -1;
  c[1956] = 0;
  c[1944] = 0;
  c[1951] = p & -16 ^ 1431655768;
  a = 4096;
 } else a = c[1953] | 0;
 h = n + 48 | 0;
 i = n + 47 | 0;
 k = a + i | 0;
 j = 0 - a | 0;
 if ((k & j) >>> 0 <= n >>> 0) {
  o = 0;
  l = p;
  return o | 0;
 }
 a = c[1943] | 0;
 if (a | 0) {
  m = c[1941] | 0;
  if ((m + (k & j) | 0) >>> 0 <= m >>> 0 ? 1 : (m + (k & j) | 0) >>> 0 > a >>> 0) {
   o = 0;
   l = p;
   return o | 0;
  }
 }
 b : do if (!(c[1944] & 4)) {
  d = c[1839] | 0;
  c : do if (!d) o = 118; else {
   a = 7780;
   while (1) {
    b = c[a >> 2] | 0;
    if (b >>> 0 <= d >>> 0) {
     f = a + 4 | 0;
     if ((b + (c[f >> 2] | 0) | 0) >>> 0 > d >>> 0) break;
    }
    a = c[a + 8 >> 2] | 0;
    if (!a) {
     o = 118;
     break c;
    }
   }
   if ((k - g & j) >>> 0 < 2147483647) {
    e = qb(k - g & j | 0) | 0;
    if ((e | 0) == ((c[a >> 2] | 0) + (c[f >> 2] | 0) | 0)) if ((e | 0) == (-1 | 0)) a = k - g & j; else {
     g = k - g & j;
     break b;
    } else {
     b = k - g & j;
     o = 126;
    }
   } else a = 0;
  } while (0);
  do if ((o | 0) == 118) {
   f = qb(0) | 0;
   if ((f | 0) == (-1 | 0)) a = 0; else {
    b = c[1952] | 0;
    b = ((b + -1 & f | 0) == 0 ? 0 : (b + -1 + f & 0 - b) - f | 0) + (k & j) | 0;
    a = c[1941] | 0;
    if (b >>> 0 > n >>> 0 & b >>> 0 < 2147483647) {
     d = c[1943] | 0;
     if (d | 0) if ((b + a | 0) >>> 0 <= a >>> 0 | (b + a | 0) >>> 0 > d >>> 0) {
      a = 0;
      break;
     }
     e = qb(b | 0) | 0;
     if ((e | 0) == (f | 0)) {
      g = b;
      e = f;
      break b;
     } else o = 126;
    } else a = 0;
   }
  } while (0);
  do if ((o | 0) == 126) {
   d = 0 - b | 0;
   if (!(h >>> 0 > b >>> 0 & (b >>> 0 < 2147483647 & (e | 0) != (-1 | 0)))) if ((e | 0) == (-1 | 0)) {
    a = 0;
    break;
   } else {
    g = b;
    break b;
   }
   a = c[1953] | 0;
   a = i - b + a & 0 - a;
   if (a >>> 0 >= 2147483647) {
    g = b;
    break b;
   }
   if ((qb(a | 0) | 0) == (-1 | 0)) {
    qb(d | 0) | 0;
    a = 0;
    break;
   } else {
    g = a + b | 0;
    break b;
   }
  } while (0);
  c[1944] = c[1944] | 4;
  o = 133;
 } else {
  a = 0;
  o = 133;
 } while (0);
 if ((o | 0) == 133) {
  if ((k & j) >>> 0 >= 2147483647) {
   o = 0;
   l = p;
   return o | 0;
  }
  e = qb(k & j | 0) | 0;
  b = qb(0) | 0;
  d = (b - e | 0) >>> 0 > (n + 40 | 0) >>> 0;
  if ((e | 0) == (-1 | 0) | d ^ 1 | e >>> 0 < b >>> 0 & ((e | 0) != (-1 | 0) & (b | 0) != (-1 | 0)) ^ 1) {
   o = 0;
   l = p;
   return o | 0;
  } else g = d ? b - e | 0 : a;
 }
 a = (c[1941] | 0) + g | 0;
 c[1941] = a;
 if (a >>> 0 > (c[1942] | 0) >>> 0) c[1942] = a;
 h = c[1839] | 0;
 do if (!h) {
  o = c[1837] | 0;
  if ((o | 0) == 0 | e >>> 0 < o >>> 0) c[1837] = e;
  c[1945] = e;
  c[1946] = g;
  c[1948] = 0;
  c[1842] = c[1951];
  c[1841] = -1;
  c[1846] = 7372;
  c[1845] = 7372;
  c[1848] = 7380;
  c[1847] = 7380;
  c[1850] = 7388;
  c[1849] = 7388;
  c[1852] = 7396;
  c[1851] = 7396;
  c[1854] = 7404;
  c[1853] = 7404;
  c[1856] = 7412;
  c[1855] = 7412;
  c[1858] = 7420;
  c[1857] = 7420;
  c[1860] = 7428;
  c[1859] = 7428;
  c[1862] = 7436;
  c[1861] = 7436;
  c[1864] = 7444;
  c[1863] = 7444;
  c[1866] = 7452;
  c[1865] = 7452;
  c[1868] = 7460;
  c[1867] = 7460;
  c[1870] = 7468;
  c[1869] = 7468;
  c[1872] = 7476;
  c[1871] = 7476;
  c[1874] = 7484;
  c[1873] = 7484;
  c[1876] = 7492;
  c[1875] = 7492;
  c[1878] = 7500;
  c[1877] = 7500;
  c[1880] = 7508;
  c[1879] = 7508;
  c[1882] = 7516;
  c[1881] = 7516;
  c[1884] = 7524;
  c[1883] = 7524;
  c[1886] = 7532;
  c[1885] = 7532;
  c[1888] = 7540;
  c[1887] = 7540;
  c[1890] = 7548;
  c[1889] = 7548;
  c[1892] = 7556;
  c[1891] = 7556;
  c[1894] = 7564;
  c[1893] = 7564;
  c[1896] = 7572;
  c[1895] = 7572;
  c[1898] = 7580;
  c[1897] = 7580;
  c[1900] = 7588;
  c[1899] = 7588;
  c[1902] = 7596;
  c[1901] = 7596;
  c[1904] = 7604;
  c[1903] = 7604;
  c[1906] = 7612;
  c[1905] = 7612;
  c[1908] = 7620;
  c[1907] = 7620;
  o = g + -40 | 0;
  k = e + 8 | 0;
  k = (k & 7 | 0) == 0 ? 0 : 0 - k & 7;
  m = e + k | 0;
  c[1839] = m;
  c[1836] = o - k;
  c[m + 4 >> 2] = o - k | 1;
  c[e + o + 4 >> 2] = 40;
  c[1840] = c[1955];
 } else {
  a = 7780;
  do {
   b = c[a >> 2] | 0;
   d = a + 4 | 0;
   f = c[d >> 2] | 0;
   if ((e | 0) == (b + f | 0)) {
    o = 143;
    break;
   }
   a = c[a + 8 >> 2] | 0;
  } while ((a | 0) != 0);
  if ((o | 0) == 143) if (!(c[a + 12 >> 2] & 8)) if (e >>> 0 > h >>> 0 & b >>> 0 <= h >>> 0) {
   c[d >> 2] = f + g;
   o = (c[1836] | 0) + g | 0;
   m = (h + 8 & 7 | 0) == 0 ? 0 : 0 - (h + 8) & 7;
   c[1839] = h + m;
   c[1836] = o - m;
   c[h + m + 4 >> 2] = o - m | 1;
   c[h + o + 4 >> 2] = 40;
   c[1840] = c[1955];
   break;
  }
  if (e >>> 0 < (c[1837] | 0) >>> 0) c[1837] = e;
  b = e + g | 0;
  a = 7780;
  while (1) {
   if ((c[a >> 2] | 0) == (b | 0)) {
    o = 151;
    break;
   }
   a = c[a + 8 >> 2] | 0;
   if (!a) {
    b = 7780;
    break;
   }
  }
  if ((o | 0) == 151) if (!(c[a + 12 >> 2] & 8)) {
   c[a >> 2] = e;
   k = a + 4 | 0;
   c[k >> 2] = (c[k >> 2] | 0) + g;
   k = e + 8 | 0;
   k = e + ((k & 7 | 0) == 0 ? 0 : 0 - k & 7) | 0;
   a = b + ((b + 8 & 7 | 0) == 0 ? 0 : 0 - (b + 8) & 7) | 0;
   j = k + n | 0;
   i = a - k - n | 0;
   c[k + 4 >> 2] = n | 3;
   do if ((h | 0) == (a | 0)) {
    o = (c[1836] | 0) + i | 0;
    c[1836] = o;
    c[1839] = j;
    c[j + 4 >> 2] = o | 1;
   } else {
    if ((c[1838] | 0) == (a | 0)) {
     o = (c[1835] | 0) + i | 0;
     c[1835] = o;
     c[1838] = j;
     c[j + 4 >> 2] = o | 1;
     c[j + o >> 2] = o;
     break;
    }
    h = c[a + 4 >> 2] | 0;
    if ((h & 3 | 0) == 1) {
     d : do if (h >>> 0 < 256) {
      b = c[a + 8 >> 2] | 0;
      d = c[a + 12 >> 2] | 0;
      if ((d | 0) == (b | 0)) {
       c[1833] = c[1833] & ~(1 << (h >>> 3));
       break;
      } else {
       c[b + 12 >> 2] = d;
       c[d + 8 >> 2] = b;
       break;
      }
     } else {
      g = c[a + 24 >> 2] | 0;
      b = c[a + 12 >> 2] | 0;
      do if ((b | 0) == (a | 0)) {
       b = c[a + 16 + 4 >> 2] | 0;
       if (!b) {
        b = c[a + 16 >> 2] | 0;
        if (!b) {
         b = 0;
         break;
        } else f = a + 16 | 0;
       } else f = a + 16 + 4 | 0;
       while (1) {
        d = b + 20 | 0;
        e = c[d >> 2] | 0;
        if (e | 0) {
         b = e;
         f = d;
         continue;
        }
        d = b + 16 | 0;
        e = c[d >> 2] | 0;
        if (!e) break; else {
         b = e;
         f = d;
        }
       }
       c[f >> 2] = 0;
      } else {
       o = c[a + 8 >> 2] | 0;
       c[o + 12 >> 2] = b;
       c[b + 8 >> 2] = o;
      } while (0);
      if (!g) break;
      d = c[a + 28 >> 2] | 0;
      do if ((c[7636 + (d << 2) >> 2] | 0) == (a | 0)) {
       c[7636 + (d << 2) >> 2] = b;
       if (b | 0) break;
       c[1834] = c[1834] & ~(1 << d);
       break d;
      } else {
       c[g + 16 + (((c[g + 16 >> 2] | 0) != (a | 0) & 1) << 2) >> 2] = b;
       if (!b) break d;
      } while (0);
      c[b + 24 >> 2] = g;
      d = c[a + 16 >> 2] | 0;
      if (d | 0) {
       c[b + 16 >> 2] = d;
       c[d + 24 >> 2] = b;
      }
      d = c[a + 16 + 4 >> 2] | 0;
      if (!d) break;
      c[b + 20 >> 2] = d;
      c[d + 24 >> 2] = b;
     } while (0);
     a = a + (h & -8) | 0;
     f = (h & -8) + i | 0;
    } else f = i;
    d = a + 4 | 0;
    c[d >> 2] = c[d >> 2] & -2;
    c[j + 4 >> 2] = f | 1;
    c[j + f >> 2] = f;
    d = f >>> 3;
    if (f >>> 0 < 256) {
     a = c[1833] | 0;
     if (!(a & 1 << d)) {
      c[1833] = a | 1 << d;
      a = 7372 + (d << 1 << 2) | 0;
      b = 7372 + (d << 1 << 2) + 8 | 0;
     } else {
      a = c[7372 + (d << 1 << 2) + 8 >> 2] | 0;
      b = 7372 + (d << 1 << 2) + 8 | 0;
     }
     c[b >> 2] = j;
     c[a + 12 >> 2] = j;
     c[j + 8 >> 2] = a;
     c[j + 12 >> 2] = 7372 + (d << 1 << 2);
     break;
    }
    a = f >>> 8;
    do if (!a) a = 0; else {
     if (f >>> 0 > 16777215) {
      a = 31;
      break;
     }
     o = a << ((a + 1048320 | 0) >>> 16 & 8) << (((a << ((a + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4);
     a = 14 - (((a << ((a + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4 | (a + 1048320 | 0) >>> 16 & 8 | (o + 245760 | 0) >>> 16 & 2) + (o << ((o + 245760 | 0) >>> 16 & 2) >>> 15) | 0;
     a = f >>> (a + 7 | 0) & 1 | a << 1;
    } while (0);
    e = 7636 + (a << 2) | 0;
    c[j + 28 >> 2] = a;
    c[j + 16 + 4 >> 2] = 0;
    c[j + 16 >> 2] = 0;
    b = c[1834] | 0;
    d = 1 << a;
    if (!(b & d)) {
     c[1834] = b | d;
     c[e >> 2] = j;
     c[j + 24 >> 2] = e;
     c[j + 12 >> 2] = j;
     c[j + 8 >> 2] = j;
     break;
    }
    b = f << ((a | 0) == 31 ? 0 : 25 - (a >>> 1) | 0);
    d = c[e >> 2] | 0;
    while (1) {
     if ((c[d + 4 >> 2] & -8 | 0) == (f | 0)) {
      o = 192;
      break;
     }
     e = d + 16 + (b >>> 31 << 2) | 0;
     a = c[e >> 2] | 0;
     if (!a) {
      o = 191;
      break;
     } else {
      b = b << 1;
      d = a;
     }
    }
    if ((o | 0) == 191) {
     c[e >> 2] = j;
     c[j + 24 >> 2] = d;
     c[j + 12 >> 2] = j;
     c[j + 8 >> 2] = j;
     break;
    } else if ((o | 0) == 192) {
     n = d + 8 | 0;
     o = c[n >> 2] | 0;
     c[o + 12 >> 2] = j;
     c[n >> 2] = j;
     c[j + 8 >> 2] = o;
     c[j + 12 >> 2] = d;
     c[j + 24 >> 2] = 0;
     break;
    }
   } while (0);
   o = k + 8 | 0;
   l = p;
   return o | 0;
  } else b = 7780;
  while (1) {
   a = c[b >> 2] | 0;
   if (a >>> 0 <= h >>> 0) {
    d = a + (c[b + 4 >> 2] | 0) | 0;
    if (d >>> 0 > h >>> 0) break;
   }
   b = c[b + 8 >> 2] | 0;
  }
  f = d + -47 + ((d + -47 + 8 & 7 | 0) == 0 ? 0 : 0 - (d + -47 + 8) & 7) | 0;
  f = f >>> 0 < (h + 16 | 0) >>> 0 ? h : f;
  a = g + -40 | 0;
  m = e + 8 | 0;
  m = (m & 7 | 0) == 0 ? 0 : 0 - m & 7;
  o = e + m | 0;
  c[1839] = o;
  c[1836] = a - m;
  c[o + 4 >> 2] = a - m | 1;
  c[e + a + 4 >> 2] = 40;
  c[1840] = c[1955];
  c[f + 4 >> 2] = 27;
  c[f + 8 >> 2] = c[1945];
  c[f + 8 + 4 >> 2] = c[1946];
  c[f + 8 + 8 >> 2] = c[1947];
  c[f + 8 + 12 >> 2] = c[1948];
  c[1945] = e;
  c[1946] = g;
  c[1948] = 0;
  c[1947] = f + 8;
  a = f + 24 | 0;
  do {
   o = a;
   a = a + 4 | 0;
   c[a >> 2] = 7;
  } while ((o + 8 | 0) >>> 0 < d >>> 0);
  if ((f | 0) != (h | 0)) {
   c[f + 4 >> 2] = c[f + 4 >> 2] & -2;
   c[h + 4 >> 2] = f - h | 1;
   c[f >> 2] = f - h;
   if ((f - h | 0) >>> 0 < 256) {
    d = 7372 + ((f - h | 0) >>> 3 << 1 << 2) | 0;
    a = c[1833] | 0;
    if (!(a & 1 << ((f - h | 0) >>> 3))) {
     c[1833] = a | 1 << ((f - h | 0) >>> 3);
     a = d;
     b = d + 8 | 0;
    } else {
     a = c[d + 8 >> 2] | 0;
     b = d + 8 | 0;
    }
    c[b >> 2] = h;
    c[a + 12 >> 2] = h;
    c[h + 8 >> 2] = a;
    c[h + 12 >> 2] = d;
    break;
   }
   if (!((f - h | 0) >>> 8)) a = 0; else if ((f - h | 0) >>> 0 > 16777215) a = 31; else {
    a = (f - h | 0) >>> 8 << ((((f - h | 0) >>> 8) + 1048320 | 0) >>> 16 & 8);
    a = 14 - ((a + 520192 | 0) >>> 16 & 4 | (((f - h | 0) >>> 8) + 1048320 | 0) >>> 16 & 8 | ((a << ((a + 520192 | 0) >>> 16 & 4)) + 245760 | 0) >>> 16 & 2) + (a << ((a + 520192 | 0) >>> 16 & 4) << (((a << ((a + 520192 | 0) >>> 16 & 4)) + 245760 | 0) >>> 16 & 2) >>> 15) | 0;
    a = (f - h | 0) >>> (a + 7 | 0) & 1 | a << 1;
   }
   e = 7636 + (a << 2) | 0;
   c[h + 28 >> 2] = a;
   c[h + 20 >> 2] = 0;
   c[h + 16 >> 2] = 0;
   b = c[1834] | 0;
   d = 1 << a;
   if (!(b & d)) {
    c[1834] = b | d;
    c[e >> 2] = h;
    c[h + 24 >> 2] = e;
    c[h + 12 >> 2] = h;
    c[h + 8 >> 2] = h;
    break;
   }
   b = f - h << ((a | 0) == 31 ? 0 : 25 - (a >>> 1) | 0);
   d = c[e >> 2] | 0;
   while (1) {
    if ((c[d + 4 >> 2] & -8 | 0) == (f - h | 0)) {
     o = 213;
     break;
    }
    e = d + 16 + (b >>> 31 << 2) | 0;
    a = c[e >> 2] | 0;
    if (!a) {
     o = 212;
     break;
    } else {
     b = b << 1;
     d = a;
    }
   }
   if ((o | 0) == 212) {
    c[e >> 2] = h;
    c[h + 24 >> 2] = d;
    c[h + 12 >> 2] = h;
    c[h + 8 >> 2] = h;
    break;
   } else if ((o | 0) == 213) {
    m = d + 8 | 0;
    o = c[m >> 2] | 0;
    c[o + 12 >> 2] = h;
    c[m >> 2] = h;
    c[h + 8 >> 2] = o;
    c[h + 12 >> 2] = d;
    c[h + 24 >> 2] = 0;
    break;
   }
  }
 } while (0);
 a = c[1836] | 0;
 if (a >>> 0 <= n >>> 0) {
  o = 0;
  l = p;
  return o | 0;
 }
 k = a - n | 0;
 c[1836] = k;
 o = c[1839] | 0;
 m = o + n | 0;
 c[1839] = m;
 c[m + 4 >> 2] = k | 1;
 c[o + 4 >> 2] = n | 3;
 o = o + 8 | 0;
 l = p;
 return o | 0;
}

function Ga(e, f, g, h, i, j, k, m, n) {
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 m = m | 0;
 n = n | 0;
 var o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0, H = 0;
 D = l;
 l = l + 1792 | 0;
 A = b[f >> 1] | 0;
 B = b[f + 2 >> 1] | 0;
 z = c[g + 4 >> 2] << 4;
 q = c[g + 8 >> 2] << 4;
 p = (A >> 2) + (j + h) | 0;
 s = (B >> 2) + (k + i) | 0;
 do switch (c[3328 + ((A & 3) << 4) + ((B & 3) << 2) >> 2] | 0) {
 case 0:
  {
   ya(c[g >> 2] | 0, e + (k << 4) + j | 0, p, s, z, q, m, n, 16);
   o = g;
   break;
  }
 case 1:
  {
   Ba(c[g >> 2] | 0, e + (k << 4) + j | 0, p, s + -2 | 0, z, q, m, n, 0);
   o = g;
   break;
  }
 case 2:
  {
   o = c[g >> 2] | 0;
   if ((p | 0) < 0) C = 7; else if ((s | 0) < 2 | (p + m | 0) >>> 0 > z >>> 0) C = 7; else if ((s + 3 + n | 0) >>> 0 > q >>> 0) C = 7; else {
    q = o;
    o = s + -2 | 0;
   }
   if ((C | 0) == 7) {
    ya(o, D, p, s + -2 | 0, z, q, m, n + 5 | 0, m);
    q = D;
    p = 0;
    o = 0;
    z = m;
   }
   o = q + ((N(o, z) | 0) + p) + z | 0;
   if (n >>> 2 | 0) {
    w = z << 2;
    x = 0 - z | 0;
    y = z << 1;
    if (m | 0) {
     v = o + (z * 5 | 0) | 0;
     p = e + (k << 4) + j | 0;
     q = n >>> 2;
     while (1) {
      r = m;
      s = o;
      t = p;
      u = v;
      while (1) {
       B = d[u + (x << 1) >> 0] | 0;
       G = d[u + x >> 0] | 0;
       A = d[u + z >> 0] | 0;
       H = d[u >> 0] | 0;
       E = d[s + y >> 0] | 0;
       a[t + 48 >> 0] = a[6162 + ((d[u + y >> 0] | 0) + 16 - (A + B) - (A + B << 2) + E + ((H + G | 0) * 20 | 0) >> 5) >> 0] | 0;
       F = d[s + z >> 0] | 0;
       a[t + 32 >> 0] = a[6162 + (A + 16 + ((G + B | 0) * 20 | 0) - (E + H) - (E + H << 2) + F >> 5) >> 0] | 0;
       A = d[s >> 0] | 0;
       a[t + 16 >> 0] = a[6162 + (H + 16 + ((E + B | 0) * 20 | 0) - (F + G) - (F + G << 2) + A >> 5) >> 0] | 0;
       a[t >> 0] = a[6162 + (G + 16 + ((F + E | 0) * 20 | 0) - (A + B) - (A + B << 2) + (d[s + x >> 0] | 0) >> 5) >> 0] | 0;
       r = r + -1 | 0;
       if (!r) break; else {
        s = s + 1 | 0;
        t = t + 1 | 0;
        u = u + 1 | 0;
       }
      }
      q = q + -1 | 0;
      if (!q) break; else {
       v = v + w | 0;
       o = o + w | 0;
       p = p + 64 | 0;
      }
     }
    }
   }
   o = g;
   break;
  }
 case 3:
  {
   Ba(c[g >> 2] | 0, e + (k << 4) + j | 0, p, s + -2 | 0, z, q, m, n, 1);
   o = g;
   break;
  }
 case 4:
  {
   Ca(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s, z, q, m, n, 0);
   o = g;
   break;
  }
 case 5:
  {
   Da(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 0);
   o = g;
   break;
  }
 case 6:
  {
   Fa(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 0);
   o = g;
   break;
  }
 case 7:
  {
   Da(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 2);
   o = g;
   break;
  }
 case 8:
  {
   o = c[g >> 2] | 0;
   if ((p | 0) < 2) C = 22; else if ((s + n | 0) >>> 0 > q >>> 0 | ((s | 0) < 0 | (p + 3 + m | 0) >>> 0 > z >>> 0)) C = 22; else {
    r = p + -2 | 0;
    q = s;
    p = z;
   }
   if ((C | 0) == 22) {
    ya(o, D, p + -2 | 0, s, z, q, m + 5 | 0, n, m + 5 | 0);
    o = D;
    r = 0;
    q = 0;
    p = m + 5 | 0;
   }
   if (n | 0) {
    z = p - m | 0;
    if (m >>> 2 | 0) {
     x = e + (k << 4) + j | 0;
     y = n;
     u = o + ((N(q, p) | 0) + r) + 5 | 0;
     while (1) {
      o = d[u + -5 >> 0] | 0;
      p = d[u + -4 >> 0] | 0;
      q = d[u + -3 >> 0] | 0;
      r = d[u + -2 >> 0] | 0;
      s = d[u + -1 >> 0] | 0;
      t = m >>> 2;
      v = u;
      w = x;
      while (1) {
       H = s + p | 0;
       G = p;
       p = d[v >> 0] | 0;
       a[w >> 0] = a[6162 + (o + 16 - H + ((r + q | 0) * 20 | 0) - (H << 2) + p >> 5) >> 0] | 0;
       H = q + p | 0;
       o = q;
       q = d[v + 1 >> 0] | 0;
       a[w + 1 >> 0] = a[6162 + (G + 16 + ((s + r | 0) * 20 | 0) - H - (H << 2) + q >> 5) >> 0] | 0;
       H = r + q | 0;
       G = r;
       r = d[v + 2 >> 0] | 0;
       a[w + 2 >> 0] = a[6162 + (o + 16 + ((s + p | 0) * 20 | 0) - H - (H << 2) + r >> 5) >> 0] | 0;
       H = s + r | 0;
       o = d[v + 3 >> 0] | 0;
       a[w + 3 >> 0] = a[6162 + (G + 16 + ((q + p | 0) * 20 | 0) - H - (H << 2) + o >> 5) >> 0] | 0;
       t = t + -1 | 0;
       if (!t) break; else {
        H = s;
        s = o;
        v = v + 4 | 0;
        w = w + 4 | 0;
        o = H;
       }
      }
      y = y + -1 | 0;
      if (!y) break; else {
       x = x + (m & -4) + (16 - m) | 0;
       u = u + (m & -4) + z | 0;
      }
     }
    }
   }
   o = g;
   break;
  }
 case 9:
  {
   Ea(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 0);
   o = g;
   break;
  }
 case 10:
  {
   o = c[g >> 2] | 0;
   if ((p | 0) < 2) C = 35; else if ((s | 0) < 2 | (p + 3 + m | 0) >>> 0 > z >>> 0) C = 35; else if ((s + 3 + n | 0) >>> 0 > q >>> 0) C = 35; else {
    r = p + -2 | 0;
    q = s + -2 | 0;
    p = z;
    s = n + 5 | 0;
   }
   if ((C | 0) == 35) {
    ya(o, D, p + -2 | 0, s + -2 | 0, z, q, m + 5 | 0, n + 5 | 0, m + 5 | 0);
    o = D;
    r = 0;
    q = 0;
    p = m + 5 | 0;
    s = n + 5 | 0;
   }
   if (s | 0) {
    z = p - m | 0;
    if (m >>> 2 | 0) {
     x = o + ((N(q, p) | 0) + r) + 5 | 0;
     y = D + 448 | 0;
     while (1) {
      o = d[x + -5 >> 0] | 0;
      p = d[x + -4 >> 0] | 0;
      q = d[x + -3 >> 0] | 0;
      r = d[x + -2 >> 0] | 0;
      t = d[x + -1 >> 0] | 0;
      u = m >>> 2;
      v = y;
      w = x;
      while (1) {
       H = t + p | 0;
       G = p;
       p = d[w >> 0] | 0;
       c[v >> 2] = o - H + ((r + q | 0) * 20 | 0) - (H << 2) + p;
       H = q + p | 0;
       o = q;
       q = d[w + 1 >> 0] | 0;
       c[v + 4 >> 2] = ((t + r | 0) * 20 | 0) + G - H - (H << 2) + q;
       H = r + q | 0;
       G = r;
       r = d[w + 2 >> 0] | 0;
       c[v + 8 >> 2] = ((t + p | 0) * 20 | 0) + o - H - (H << 2) + r;
       H = t + r | 0;
       o = d[w + 3 >> 0] | 0;
       c[v + 12 >> 2] = ((q + p | 0) * 20 | 0) + G - H - (H << 2) + o;
       u = u + -1 | 0;
       if (!u) break; else {
        H = t;
        t = o;
        v = v + 16 | 0;
        w = w + 4 | 0;
        o = H;
       }
      }
      s = s + -1 | 0;
      if (!s) break; else {
       x = x + (m & -4) + z | 0;
       y = y + ((m & -4) << 2) | 0;
      }
     }
    }
   }
   if (n >>> 2 | 0) if (m | 0) {
    o = D + 448 + (m << 2) + (m * 5 << 2) | 0;
    p = D + 448 + (m << 2) | 0;
    q = e + (k << 4) + j | 0;
    t = n >>> 2;
    while (1) {
     r = o;
     s = p;
     u = m;
     v = q;
     while (1) {
      H = c[r + (0 - m << 1 << 2) >> 2] | 0;
      B = c[r + (0 - m << 2) >> 2] | 0;
      G = c[r + (m << 2) >> 2] | 0;
      A = c[r >> 2] | 0;
      F = c[s + (m << 1 << 2) >> 2] | 0;
      a[v + 48 >> 0] = a[6162 + ((c[r + (m << 1 << 2) >> 2] | 0) + 512 - (G + H) - (G + H << 2) + F + ((A + B | 0) * 20 | 0) >> 10) >> 0] | 0;
      E = c[s + (m << 2) >> 2] | 0;
      a[v + 32 >> 0] = a[6162 + (G + 512 + ((B + H | 0) * 20 | 0) - (F + A) - (F + A << 2) + E >> 10) >> 0] | 0;
      G = c[s >> 2] | 0;
      a[v + 16 >> 0] = a[6162 + (A + 512 + ((F + H | 0) * 20 | 0) - (E + B) - (E + B << 2) + G >> 10) >> 0] | 0;
      a[v >> 0] = a[6162 + (B + 512 + ((E + F | 0) * 20 | 0) - (G + H) - (G + H << 2) + (c[s + (0 - m << 2) >> 2] | 0) >> 10) >> 0] | 0;
      u = u + -1 | 0;
      if (!u) break; else {
       r = r + 4 | 0;
       s = s + 4 | 0;
       v = v + 1 | 0;
      }
     }
     t = t + -1 | 0;
     if (!t) break; else {
      o = o + (m << 2) + (m * 3 << 2) | 0;
      p = p + (m << 2) + (m * 3 << 2) | 0;
      q = q + 64 | 0;
     }
    }
   }
   o = g;
   break;
  }
 case 11:
  {
   Ea(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 1);
   o = g;
   break;
  }
 case 12:
  {
   Ca(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s, z, q, m, n, 1);
   o = g;
   break;
  }
 case 13:
  {
   Da(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 1);
   o = g;
   break;
  }
 case 14:
  {
   Fa(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 1);
   o = g;
   break;
  }
 default:
  {
   Da(c[g >> 2] | 0, e + (k << 4) + j | 0, p + -2 | 0, s + -2 | 0, z, q, m, n, 3);
   o = g;
  }
 } while (0);
 r = c[g + 4 >> 2] | 0;
 s = c[g + 8 >> 2] | 0;
 B = b[f >> 1] | 0;
 p = (B >> 3) + ((j + h | 0) >>> 1) | 0;
 A = b[f + 2 >> 1] | 0;
 q = (A >> 3) + ((k + i | 0) >>> 1) | 0;
 o = (c[o >> 2] | 0) + (N(r << 8, s) | 0) | 0;
 if ((B & 7 | 0) != 0 & (A & 7 | 0) != 0) {
  if ((p | 0) < 0) C = 58; else if ((q | 0) < 0 ? 1 : (p + 1 + (m >>> 1) | 0) >>> 0 > r << 3 >>> 0) C = 58; else if ((q + 1 + (n >>> 1) | 0) >>> 0 > s << 3 >>> 0) C = 58; else {
   i = r << 3;
   z = s << 3;
  }
  if ((C | 0) == 58) {
   ya(o, D + 448 | 0, p, q, r << 3, s << 3, (m >>> 1) + 1 | 0, (n >>> 1) + 1 | 0, (m >>> 1) + 1 | 0);
   ya(o + (N(s << 3, r << 3) | 0) | 0, D + 448 + (N((n >>> 1) + 1 | 0, (m >>> 1) + 1 | 0) | 0) | 0, p, q, r << 3, s << 3, (m >>> 1) + 1 | 0, (n >>> 1) + 1 | 0, (m >>> 1) + 1 | 0);
   o = D + 448 | 0;
   p = 0;
   q = 0;
   i = (m >>> 1) + 1 | 0;
   z = (n >>> 1) + 1 | 0;
  }
  g = 8 - (B & 7) | 0;
  h = 8 - (A & 7) | 0;
  f = i << 1;
  if (!((m >>> 2 | 0) == 0 | (n >>> 2 | 0) == 0)) {
   r = o + (N(q, i) | 0) + p | 0;
   v = n >>> 2;
   w = e + 256 + (k >>> 1 << 3) + (j >>> 1) | 0;
   while (1) {
    u = d[r + i >> 0] | 0;
    s = (N(A & 7, d[r + f >> 0] | 0) | 0) + (N(h, u) | 0) | 0;
    t = m >>> 2;
    u = (N(A & 7, u) | 0) + (N(h, d[r >> 0] | 0) | 0) | 0;
    x = r;
    y = w;
    while (1) {
     F = x + 1 | 0;
     G = d[F + i >> 0] | 0;
     H = (N(A & 7, G) | 0) + (N(h, d[F >> 0] | 0) | 0) | 0;
     G = (N(A & 7, d[F + f >> 0] | 0) | 0) + (N(h, G) | 0) | 0;
     F = ((N(u, g) | 0) + 32 + (N(H, B & 7) | 0) | 0) >>> 6;
     a[y + 8 >> 0] = ((N(s, g) | 0) + 32 + (N(G, B & 7) | 0) | 0) >>> 6;
     a[y >> 0] = F;
     x = x + 2 | 0;
     F = d[x + i >> 0] | 0;
     u = (N(A & 7, F) | 0) + (N(h, d[x >> 0] | 0) | 0) | 0;
     s = (N(A & 7, d[x + f >> 0] | 0) | 0) + (N(h, F) | 0) | 0;
     H = ((N(H, g) | 0) + 32 + (N(u, B & 7) | 0) | 0) >>> 6;
     a[y + 9 >> 0] = ((N(G, g) | 0) + 32 + (N(s, B & 7) | 0) | 0) >>> 6;
     a[y + 1 >> 0] = H;
     t = t + -1 | 0;
     if (!t) break; else y = y + 2 | 0;
    }
    v = v + -1 | 0;
    if (!v) break; else {
     r = r + (m >>> 1 & 2147483646) + (f - (m >>> 1)) | 0;
     w = w + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
    }
   }
   v = o + (N(q + z | 0, i) | 0) + p | 0;
   u = n >>> 2;
   r = e + 256 + (k >>> 1 << 3) + (j >>> 1) + 64 | 0;
   while (1) {
    q = d[v + i >> 0] | 0;
    o = (N(A & 7, d[v + f >> 0] | 0) | 0) + (N(h, q) | 0) | 0;
    p = m >>> 2;
    q = (N(A & 7, q) | 0) + (N(h, d[v >> 0] | 0) | 0) | 0;
    s = v;
    t = r;
    while (1) {
     F = s + 1 | 0;
     G = d[F + i >> 0] | 0;
     H = (N(A & 7, G) | 0) + (N(h, d[F >> 0] | 0) | 0) | 0;
     G = (N(A & 7, d[F + f >> 0] | 0) | 0) + (N(h, G) | 0) | 0;
     F = ((N(q, g) | 0) + 32 + (N(H, B & 7) | 0) | 0) >>> 6;
     a[t + 8 >> 0] = ((N(o, g) | 0) + 32 + (N(G, B & 7) | 0) | 0) >>> 6;
     a[t >> 0] = F;
     s = s + 2 | 0;
     F = d[s + i >> 0] | 0;
     q = (N(A & 7, F) | 0) + (N(h, d[s >> 0] | 0) | 0) | 0;
     o = (N(A & 7, d[s + f >> 0] | 0) | 0) + (N(h, F) | 0) | 0;
     H = ((N(H, g) | 0) + 32 + (N(q, B & 7) | 0) | 0) >>> 6;
     a[t + 9 >> 0] = ((N(G, g) | 0) + 32 + (N(o, B & 7) | 0) | 0) >>> 6;
     a[t + 1 >> 0] = H;
     p = p + -1 | 0;
     if (!p) break; else t = t + 2 | 0;
    }
    u = u + -1 | 0;
    if (!u) break; else {
     v = v + (m >>> 1 & 2147483646) + (f - (m >>> 1)) | 0;
     r = r + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
    }
   }
  }
  l = D;
  return;
 }
 if (B & 7 | 0) {
  if ((p | 0) < 0) C = 72; else if (((n >>> 1) + q | 0) >>> 0 > s << 3 >>> 0 | ((q | 0) < 0 ? 1 : (p + 1 + (m >>> 1) | 0) >>> 0 > r << 3 >>> 0)) C = 72; else {
   x = p;
   w = q;
   g = r << 3;
   v = s << 3;
  }
  if ((C | 0) == 72) {
   ya(o, D + 448 | 0, p, q, r << 3, s << 3, (m >>> 1) + 1 | 0, n >>> 1, (m >>> 1) + 1 | 0);
   ya(o + (N(s << 3, r << 3) | 0) | 0, D + 448 + (N((m >>> 1) + 1 | 0, n >>> 1) | 0) | 0, p, q, r << 3, s << 3, (m >>> 1) + 1 | 0, n >>> 1, (m >>> 1) + 1 | 0);
   o = D + 448 | 0;
   x = 0;
   w = 0;
   g = (m >>> 1) + 1 | 0;
   v = n >>> 1;
  }
  y = 8 - (B & 7) | 0;
  z = (g << 1) - (m >>> 1) | 0;
  if (!((m >>> 2 | 0) == 0 | (n >>> 2 | 0) == 0)) {
   p = e + 256 + (k >>> 1 << 3) + (j >>> 1) | 0;
   q = o + (N(w, g) | 0) + x | 0;
   s = n >>> 2;
   while (1) {
    r = m >>> 2;
    t = q;
    u = p;
    while (1) {
     H = t + 1 | 0;
     G = d[t >> 0] | 0;
     F = d[H + g >> 0] | 0;
     H = d[H >> 0] | 0;
     a[u + 8 >> 0] = (((N(B & 7, F) | 0) + (N(y, d[t + g >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
     t = t + 2 | 0;
     a[u >> 0] = (((N(B & 7, H) | 0) + (N(y, G) | 0) << 3) + 32 | 0) >>> 6;
     G = d[t >> 0] | 0;
     a[u + 9 >> 0] = (((N(B & 7, d[t + g >> 0] | 0) | 0) + (N(y, F) | 0) << 3) + 32 | 0) >>> 6;
     a[u + 1 >> 0] = (((N(B & 7, G) | 0) + (N(y, H) | 0) << 3) + 32 | 0) >>> 6;
     r = r + -1 | 0;
     if (!r) break; else u = u + 2 | 0;
    }
    s = s + -1 | 0;
    if (!s) break; else {
     p = p + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
     q = q + (m >>> 1 & 2147483646) + z | 0;
    }
   }
   t = e + 256 + (k >>> 1 << 3) + (j >>> 1) + 64 | 0;
   s = o + (N(w + v | 0, g) | 0) + x | 0;
   p = n >>> 2;
   while (1) {
    o = m >>> 2;
    q = s;
    r = t;
    while (1) {
     H = q + 1 | 0;
     G = d[q >> 0] | 0;
     F = d[H + g >> 0] | 0;
     H = d[H >> 0] | 0;
     a[r + 8 >> 0] = (((N(B & 7, F) | 0) + (N(y, d[q + g >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
     q = q + 2 | 0;
     a[r >> 0] = (((N(B & 7, H) | 0) + (N(y, G) | 0) << 3) + 32 | 0) >>> 6;
     G = d[q >> 0] | 0;
     a[r + 9 >> 0] = (((N(B & 7, d[q + g >> 0] | 0) | 0) + (N(y, F) | 0) << 3) + 32 | 0) >>> 6;
     a[r + 1 >> 0] = (((N(B & 7, G) | 0) + (N(y, H) | 0) << 3) + 32 | 0) >>> 6;
     o = o + -1 | 0;
     if (!o) break; else r = r + 2 | 0;
    }
    p = p + -1 | 0;
    if (!p) break; else {
     t = t + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
     s = s + (m >>> 1 & 2147483646) + z | 0;
    }
   }
  }
  l = D;
  return;
 }
 if (!(A & 7)) {
  ya(o, e + 256 + (k >>> 1 << 3) + (j >>> 1) | 0, p, q, r << 3, s << 3, m >>> 1, n >>> 1, 8);
  ya(o + (N(s << 3, r << 3) | 0) | 0, e + 256 + (k >>> 1 << 3) + (j >>> 1) + 64 | 0, p, q, r << 3, s << 3, m >>> 1, n >>> 1, 8);
  l = D;
  return;
 }
 if ((p | 0) < 0) C = 87; else if ((q | 0) < 0 ? 1 : ((m >>> 1) + p | 0) >>> 0 > r << 3 >>> 0) C = 87; else if ((q + 1 + (n >>> 1) | 0) >>> 0 > s << 3 >>> 0) C = 87; else {
  x = p;
  w = q;
  g = r << 3;
  v = s << 3;
 }
 if ((C | 0) == 87) {
  ya(o, D + 448 | 0, p, q, r << 3, s << 3, m >>> 1, (n >>> 1) + 1 | 0, m >>> 1);
  ya(o + (N(s << 3, r << 3) | 0) | 0, D + 448 + (N((n >>> 1) + 1 | 0, m >>> 1) | 0) | 0, p, q, r << 3, s << 3, m >>> 1, (n >>> 1) + 1 | 0, m >>> 1);
  o = D + 448 | 0;
  x = 0;
  w = 0;
  g = m >>> 1;
  v = (n >>> 1) + 1 | 0;
 }
 y = 8 - (A & 7) | 0;
 z = g << 1;
 if (!((m >>> 2 | 0) == 0 | (n >>> 2 | 0) == 0)) {
  p = e + 256 + (k >>> 1 << 3) + (j >>> 1) | 0;
  q = o + (N(w, g) | 0) + x | 0;
  r = n >>> 2;
  while (1) {
   s = m >>> 2;
   t = q;
   u = p;
   while (1) {
    H = d[t + g >> 0] | 0;
    F = t + 1 | 0;
    G = d[t >> 0] | 0;
    a[u + 8 >> 0] = (((N(y, H) | 0) + (N(A & 7, d[t + z >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
    a[u >> 0] = (((N(y, G) | 0) + (N(A & 7, H) | 0) << 3) + 32 | 0) >>> 6;
    H = d[F + g >> 0] | 0;
    G = d[F >> 0] | 0;
    a[u + 9 >> 0] = (((N(y, H) | 0) + (N(A & 7, d[F + z >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
    a[u + 1 >> 0] = (((N(y, G) | 0) + (N(A & 7, H) | 0) << 3) + 32 | 0) >>> 6;
    s = s + -1 | 0;
    if (!s) break; else {
     t = t + 2 | 0;
     u = u + 2 | 0;
    }
   }
   r = r + -1 | 0;
   if (!r) break; else {
    p = p + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
    q = q + (m >>> 1 & 2147483646) + (z - (m >>> 1)) | 0;
   }
  }
  t = e + 256 + (k >>> 1 << 3) + (j >>> 1) + 64 | 0;
  s = o + (N(w + v | 0, g) | 0) + x | 0;
  o = n >>> 2;
  while (1) {
   p = m >>> 2;
   q = s;
   r = t;
   while (1) {
    H = d[q + g >> 0] | 0;
    F = q + 1 | 0;
    G = d[q >> 0] | 0;
    a[r + 8 >> 0] = (((N(y, H) | 0) + (N(A & 7, d[q + z >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
    a[r >> 0] = (((N(y, G) | 0) + (N(A & 7, H) | 0) << 3) + 32 | 0) >>> 6;
    H = d[F + g >> 0] | 0;
    G = d[F >> 0] | 0;
    a[r + 9 >> 0] = (((N(y, H) | 0) + (N(A & 7, d[F + z >> 0] | 0) | 0) << 3) + 32 | 0) >>> 6;
    a[r + 1 >> 0] = (((N(y, G) | 0) + (N(A & 7, H) | 0) << 3) + 32 | 0) >>> 6;
    p = p + -1 | 0;
    if (!p) break; else {
     q = q + 2 | 0;
     r = r + 2 | 0;
    }
   }
   o = o + -1 | 0;
   if (!o) break; else {
    t = t + (m >>> 1 & 2147483646) + (16 - (m >>> 1)) | 0;
    s = s + (m >>> 1 & 2147483646) + (z - (m >>> 1)) | 0;
   }
  }
 }
 l = D;
 return;
}

function wa(a, b, f, g) {
 a = a | 0;
 b = b | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0, H = 0, I = 0, J = 0, K = 0, L = 0, M = 0, N = 0, O = 0, P = 0, Q = 0, R = 0, S = 0, T = 0;
 T = l;
 l = l + 128 | 0;
 r = c[a + 4 >> 2] | 0;
 Q = c[a + 12 >> 2] << 3;
 o = c[a + 16 >> 2] | 0;
 if ((Q - o | 0) > 31) {
  n = c[a + 8 >> 2] | 0;
  p = (d[r + 1 >> 0] | 0) << 16 | (d[r >> 0] | 0) << 24 | (d[r + 2 >> 0] | 0) << 8 | (d[r + 3 >> 0] | 0);
  if (n) p = (d[r + 4 >> 0] | 0) >>> (8 - n | 0) | p << n;
 } else if ((Q - o | 0) > 0) {
  n = c[a + 8 >> 2] | 0;
  p = (d[r >> 0] | 0) << n + 24;
  if ((Q - o + -8 + n | 0) > 0) {
   t = Q - o + -8 + n | 0;
   q = n + 24 | 0;
   n = r;
   while (1) {
    n = n + 1 | 0;
    q = q + -8 | 0;
    p = (d[n >> 0] | 0) << q | p;
    if ((t | 0) <= 8) break; else t = t + -8 | 0;
   }
  }
 } else p = 0;
 n = p >>> 16;
 do if (f >>> 0 < 2) if ((p | 0) < 0) v = 1; else {
  if (p >>> 0 > 201326591) {
   u = e[3516 + (p >>> 26 << 1) >> 1] | 0;
   K = 31;
   break;
  }
  if (p >>> 0 > 16777215) {
   u = e[3580 + (p >>> 22 << 1) >> 1] | 0;
   K = 31;
   break;
  }
  if (p >>> 0 > 2097151) {
   u = e[3676 + ((p >>> 18) + -8 << 1) >> 1] | 0;
   K = 31;
   break;
  } else {
   u = e[3788 + (n << 1) >> 1] | 0;
   K = 31;
   break;
  }
 } else if (f >>> 0 < 4) {
  if ((p | 0) < 0) {
   v = n & 16384 | 0 ? 2 : 2082;
   break;
  }
  if (p >>> 0 > 268435455) {
   u = e[3852 + (p >>> 26 << 1) >> 1] | 0;
   K = 31;
   break;
  }
  if (p >>> 0 > 33554431) {
   u = e[3916 + (p >>> 23 << 1) >> 1] | 0;
   K = 31;
   break;
  } else {
   u = e[3980 + (p >>> 18 << 1) >> 1] | 0;
   K = 31;
   break;
  }
 } else {
  if (f >>> 0 < 8) {
   n = p >>> 26;
   if ((n + -8 | 0) >>> 0 < 56) {
    u = e[4236 + (n << 1) >> 1] | 0;
    K = 31;
    break;
   }
   u = e[4364 + (p >>> 22 << 1) >> 1] | 0;
   K = 31;
   break;
  }
  if (f >>> 0 < 17) {
   u = e[4620 + (p >>> 26 << 1) >> 1] | 0;
   K = 31;
   break;
  }
  n = p >>> 29;
  if (n | 0) {
   u = e[4748 + (n << 1) >> 1] | 0;
   K = 31;
   break;
  }
  u = e[4764 + (p >>> 24 << 1) >> 1] | 0;
  K = 31;
  break;
 } while (0);
 if ((K | 0) == 31) if (!u) {
  a = 1;
  l = T;
  return a | 0;
 } else v = u;
 u = v & 31;
 p = p << u;
 L = v >>> 11;
 if ((L & 31) >>> 0 > g >>> 0) {
  a = 1;
  l = T;
  return a | 0;
 }
 w = v >>> 5 & 63;
 do if (!(L & 31)) {
  R = 0;
  O = 32 - u | 0;
 } else {
  if (!w) {
   q = 0;
   n = 32 - u | 0;
  } else {
   do if ((32 - u | 0) >>> 0 < w >>> 0) {
    c[a + 16 >> 2] = o + u;
    q = o + u & 7;
    c[a + 8 >> 2] = q;
    if (Q >>> 0 < (o + u | 0) >>> 0) {
     a = 1;
     l = T;
     return a | 0;
    }
    p = (c[a >> 2] | 0) + ((o + u | 0) >>> 3) | 0;
    c[a + 4 >> 2] = p;
    if ((Q - (o + u) | 0) > 31) {
     n = (d[p + 1 >> 0] | 0) << 16 | (d[p >> 0] | 0) << 24 | (d[p + 2 >> 0] | 0) << 8 | (d[p + 3 >> 0] | 0);
     if (!q) {
      t = 32;
      r = n;
      o = o + u | 0;
      break;
     }
     t = 32;
     r = (d[p + 4 >> 0] | 0) >>> (8 - q | 0) | n << q;
     o = o + u | 0;
     break;
    }
    if ((Q - (o + u) | 0) > 0) {
     n = (d[p >> 0] | 0) << (q | 24);
     if ((Q - (o + u) + -8 + q | 0) > 0) {
      r = Q - (o + u) + -8 + q | 0;
      q = q | 24;
      while (1) {
       p = p + 1 | 0;
       q = q + -8 | 0;
       n = (d[p >> 0] | 0) << q | n;
       if ((r | 0) <= 8) {
        t = 32;
        r = n;
        o = o + u | 0;
        break;
       } else r = r + -8 | 0;
      }
     } else {
      t = 32;
      r = n;
      o = o + u | 0;
     }
    } else {
     t = 32;
     r = 0;
     o = o + u | 0;
    }
   } else {
    t = 32 - u | 0;
    r = p;
   } while (0);
   q = r >>> (32 - w | 0);
   n = 0;
   p = 1 << w + -1;
   do {
    c[T + 64 + (n << 2) >> 2] = p & q | 0 ? -1 : 1;
    p = p >>> 1;
    n = n + 1 | 0;
   } while ((p | 0) != 0);
   q = n;
   n = t - w | 0;
   p = r << w;
  }
  a : do if (q >>> 0 < (L & 31) >>> 0) {
   f = (L & 31) >>> 0 > 10 & w >>> 0 < 3 & 1;
   v = q;
   b : while (1) {
    do if (n >>> 0 < 16) {
     o = o + (32 - n) | 0;
     c[a + 16 >> 2] = o;
     c[a + 8 >> 2] = o & 7;
     if (Q >>> 0 < o >>> 0) {
      N = 1;
      K = 154;
      break b;
     }
     p = (c[a >> 2] | 0) + (o >>> 3) | 0;
     c[a + 4 >> 2] = p;
     if ((Q - o | 0) > 31) {
      n = (d[p + 1 >> 0] | 0) << 16 | (d[p >> 0] | 0) << 24 | (d[p + 2 >> 0] | 0) << 8 | (d[p + 3 >> 0] | 0);
      if (!(o & 7)) {
       u = 32;
       t = n;
       break;
      }
      u = 32;
      t = (d[p + 4 >> 0] | 0) >>> (8 - (o & 7) | 0) | n << (o & 7);
      break;
     }
     if ((Q - o | 0) <= 0) {
      N = 1;
      K = 154;
      break b;
     }
     n = (d[p >> 0] | 0) << (o & 7 | 24);
     if ((Q - o + -8 + (o & 7) | 0) > 0) {
      q = Q - o + -8 + (o & 7) | 0;
      r = o & 7 | 24;
      while (1) {
       p = p + 1 | 0;
       r = r + -8 | 0;
       n = (d[p >> 0] | 0) << r | n;
       if ((q | 0) <= 8) {
        u = 32;
        t = n;
        break;
       } else q = q + -8 | 0;
      }
     } else {
      u = 32;
      t = n;
     }
    } else {
     u = n;
     t = p;
    } while (0);
    do if ((t | 0) < 0) {
     I = 0;
     K = 75;
    } else if (t >>> 0 > 1073741823) {
     I = 1;
     K = 75;
    } else if (t >>> 0 > 536870911) {
     I = 2;
     K = 75;
    } else if (t >>> 0 > 268435455) {
     I = 3;
     K = 75;
    } else if (t >>> 0 > 134217727) {
     I = 4;
     K = 75;
    } else if (t >>> 0 > 67108863) {
     I = 5;
     K = 75;
    } else if (t >>> 0 > 33554431) {
     I = 6;
     K = 75;
    } else if (t >>> 0 > 16777215) {
     I = 7;
     K = 75;
    } else if (t >>> 0 > 8388607) {
     I = 8;
     K = 75;
    } else {
     if (t >>> 0 > 4194303) {
      I = 9;
      K = 75;
      break;
     }
     if (t >>> 0 > 2097151) {
      I = 10;
      K = 75;
      break;
     }
     if (t >>> 0 > 1048575) {
      I = 11;
      K = 75;
      break;
     }
     if (t >>> 0 > 524287) {
      I = 12;
      K = 75;
      break;
     }
     if (t >>> 0 > 262143) {
      I = 13;
      K = 75;
      break;
     }
     if (t >>> 0 > 131071) {
      q = 14;
      n = f | 0 ? f : 4;
      r = f;
      p = u + -15 | 0;
      s = t << 15;
     } else {
      if ((t & -65536 | 0) != 65536) {
       N = 1;
       K = 154;
       break b;
      }
      q = 15;
      n = 12;
      r = f | 0 ? f : 1;
      p = u + -16 | 0;
      s = t << 16;
     }
     G = n;
     H = r;
     F = p;
     E = q << r;
     D = (r | 0) == 0;
     K = 76;
    } while (0);
    if ((K | 0) == 75) {
     K = 0;
     n = I + 1 | 0;
     q = t << n;
     n = u - n | 0;
     p = I << f;
     if (!f) {
      B = p;
      C = 0;
      A = n;
      y = q;
      z = 1;
      x = o;
     } else {
      G = f;
      H = f;
      F = n;
      E = p;
      D = 0;
      s = q;
      K = 76;
     }
    }
    if ((K | 0) == 76) {
     K = 0;
     do if (F >>> 0 < G >>> 0) {
      r = o + (32 - F) | 0;
      c[a + 16 >> 2] = r;
      c[a + 8 >> 2] = r & 7;
      if (Q >>> 0 < r >>> 0) {
       N = 1;
       K = 154;
       break b;
      }
      o = (c[a >> 2] | 0) + (r >>> 3) | 0;
      c[a + 4 >> 2] = o;
      if ((Q - r | 0) > 31) {
       n = (d[o + 1 >> 0] | 0) << 16 | (d[o >> 0] | 0) << 24 | (d[o + 2 >> 0] | 0) << 8 | (d[o + 3 >> 0] | 0);
       if (!(r & 7)) {
        p = 32;
        o = r;
        break;
       }
       p = 32;
       n = (d[o + 4 >> 0] | 0) >>> (8 - (r & 7) | 0) | n << (r & 7);
       o = r;
       break;
      }
      if ((Q - r | 0) > 0) {
       n = (d[o >> 0] | 0) << (r & 7 | 24);
       if ((Q - r + -8 + (r & 7) | 0) > 0) {
        p = Q - r + -8 + (r & 7) | 0;
        q = r & 7 | 24;
        while (1) {
         o = o + 1 | 0;
         q = q + -8 | 0;
         n = (d[o >> 0] | 0) << q | n;
         if ((p | 0) <= 8) {
          p = 32;
          o = r;
          break;
         } else p = p + -8 | 0;
        }
       } else {
        p = 32;
        o = r;
       }
      } else {
       p = 32;
       n = 0;
       o = r;
      }
     } else {
      p = F;
      n = s;
     } while (0);
     B = (n >>> (32 - G | 0)) + E | 0;
     C = H;
     A = p - G | 0;
     y = n << G;
     z = D;
     x = o;
    }
    n = w >>> 0 < 3 & (v | 0) == (w | 0) ? B + 2 | 0 : B;
    o = z ? 1 : C;
    c[T + 64 + (v << 2) >> 2] = (n & 1 | 0) == 0 ? (n + 2 | 0) >>> 1 : 0 - ((n + 2 | 0) >>> 1) | 0;
    v = v + 1 | 0;
    if (v >>> 0 >= (L & 31) >>> 0) {
     k = A;
     m = y;
     j = x;
     break a;
    } else {
     f = o + ((o >>> 0 < 6 ? ((n + 2 | 0) >>> 1 | 0) > (3 << o + -1 | 0) : 0) & 1) | 0;
     p = y;
     n = A;
     o = x;
    }
   }
   if ((K | 0) == 154) {
    l = T;
    return N | 0;
   }
  } else {
   k = n;
   m = p;
   j = o;
  } while (0);
  if ((L & 31) >>> 0 < g >>> 0) {
   do if (k >>> 0 < 9) {
    j = j + (32 - k) | 0;
    c[a + 16 >> 2] = j;
    c[a + 8 >> 2] = j & 7;
    if (Q >>> 0 < j >>> 0) {
     a = 1;
     l = T;
     return a | 0;
    }
    n = (c[a >> 2] | 0) + (j >>> 3) | 0;
    c[a + 4 >> 2] = n;
    if ((Q - j | 0) > 31) {
     m = (d[n + 1 >> 0] | 0) << 16 | (d[n >> 0] | 0) << 24 | (d[n + 2 >> 0] | 0) << 8 | (d[n + 3 >> 0] | 0);
     if (!(j & 7)) {
      k = 32;
      break;
     }
     k = 32;
     m = (d[n + 4 >> 0] | 0) >>> (8 - (j & 7) | 0) | m << (j & 7);
     break;
    }
    if ((Q - j | 0) > 0) {
     m = (d[n >> 0] | 0) << (j & 7 | 24);
     if ((Q - j + -8 + (j & 7) | 0) > 0) {
      o = Q - j + -8 + (j & 7) | 0;
      p = j & 7 | 24;
      k = n;
      while (1) {
       k = k + 1 | 0;
       p = p + -8 | 0;
       m = (d[k >> 0] | 0) << p | m;
       if ((o | 0) <= 8) {
        k = 32;
        break;
       } else o = o + -8 | 0;
      }
     } else k = 32;
    } else {
     k = 32;
     m = 0;
    }
   } while (0);
   n = m >>> 23;
   c : do if ((g | 0) == 4) if ((m | 0) < 0) h = 1; else if ((L & 31 | 0) == 3) h = 17; else h = m >>> 0 > 1073741823 ? 18 : (L & 31 | 0) == 2 ? 34 : m >>> 0 > 536870911 ? 35 : 51; else {
    do switch (L & 31) {
    case 1:
     {
      if (m >>> 0 > 268435455) h = d[5028 + (m >>> 27) >> 0] | 0; else {
       J = 5060 + n | 0;
       K = 115;
      }
      break;
     }
    case 2:
     {
      J = 5092 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 3:
     {
      J = 5156 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 4:
     {
      J = 5220 + (m >>> 27) | 0;
      K = 115;
      break;
     }
    case 5:
     {
      J = 5252 + (m >>> 27) | 0;
      K = 115;
      break;
     }
    case 6:
     {
      J = 5284 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 7:
     {
      J = 5348 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 8:
     {
      J = 5412 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 9:
     {
      J = 5476 + (m >>> 26) | 0;
      K = 115;
      break;
     }
    case 10:
     {
      J = 5540 + (m >>> 27) | 0;
      K = 115;
      break;
     }
    case 11:
     {
      J = 5572 + (m >>> 28) | 0;
      K = 115;
      break;
     }
    case 12:
     {
      J = 5588 + (m >>> 28) | 0;
      K = 115;
      break;
     }
    case 13:
     {
      J = 5604 + (m >>> 29) | 0;
      K = 115;
      break;
     }
    case 14:
     {
      J = 5612 + (m >>> 30) | 0;
      K = 115;
      break;
     }
    default:
     {
      h = m >> 31 & 16 | 1;
      break c;
     }
    } while (0);
    if ((K | 0) == 115) h = d[J >> 0] | 0;
    if (!h) {
     a = 1;
     l = T;
     return a | 0;
    }
   } while (0);
   g = h & 15;
   n = h >>> 4 & 15;
   k = k - g | 0;
   h = m << g;
  } else {
   n = 0;
   h = m;
  }
  if (!((L & 31) + -1 | 0)) {
   c[b + (n << 2) >> 2] = c[T + 64 >> 2];
   R = 1 << n;
   O = k;
   break;
  }
  p = n;
  q = 0;
  d : while (1) {
   if (!p) {
    c[T + (q << 2) >> 2] = 1;
    S = k;
    i = 0;
   } else {
    do if (k >>> 0 < 11) {
     j = j + (32 - k) | 0;
     c[a + 16 >> 2] = j;
     c[a + 8 >> 2] = j & 7;
     if (Q >>> 0 < j >>> 0) {
      N = 1;
      K = 154;
      break d;
     }
     m = (c[a >> 2] | 0) + (j >>> 3) | 0;
     c[a + 4 >> 2] = m;
     if ((Q - j | 0) > 31) {
      h = (d[m + 1 >> 0] | 0) << 16 | (d[m >> 0] | 0) << 24 | (d[m + 2 >> 0] | 0) << 8 | (d[m + 3 >> 0] | 0);
      if (!(j & 7)) {
       k = 32;
       m = h;
       break;
      }
      k = 32;
      m = (d[m + 4 >> 0] | 0) >>> (8 - (j & 7) | 0) | h << (j & 7);
      break;
     }
     if ((Q - j | 0) > 0) {
      h = (d[m >> 0] | 0) << (j & 7 | 24);
      if ((Q - j + -8 + (j & 7) | 0) > 0) {
       n = Q - j + -8 + (j & 7) | 0;
       o = j & 7 | 24;
       k = m;
       while (1) {
        k = k + 1 | 0;
        o = o + -8 | 0;
        h = (d[k >> 0] | 0) << o | h;
        if ((n | 0) <= 8) {
         k = 32;
         m = h;
         break;
        } else n = n + -8 | 0;
       }
      } else {
       k = 32;
       m = h;
      }
     } else {
      k = 32;
      m = 0;
     }
    } else m = h; while (0);
    switch (p | 0) {
    case 1:
     {
      P = 5616 + (m >>> 31) | 0;
      K = 145;
      break;
     }
    case 2:
     {
      P = 5618 + (m >>> 30) | 0;
      K = 145;
      break;
     }
    case 3:
     {
      P = 5622 + (m >>> 30) | 0;
      K = 145;
      break;
     }
    case 4:
     {
      P = 5626 + (m >>> 29) | 0;
      K = 145;
      break;
     }
    case 5:
     {
      P = 5634 + (m >>> 29) | 0;
      K = 145;
      break;
     }
    case 6:
     {
      P = 5642 + (m >>> 29) | 0;
      K = 145;
      break;
     }
    default:
     {
      if (m >>> 0 > 536870911) h = m >>> 29 << 4 ^ 115; else if (m >>> 0 > 268435455) h = 116; else if (m >>> 0 > 134217727) h = 133; else if (m >>> 0 > 67108863) h = 150; else if (m >>> 0 > 33554431) h = 167; else h = m >>> 0 > 16777215 ? 184 : m >>> 0 > 8388607 ? 201 : m >>> 0 > 4194303 ? 218 : m >>> 0 < 2097152 ? 0 : 235;
      if ((h >>> 4 & 15) >>> 0 > p >>> 0) {
       N = 1;
       K = 154;
       break d;
      } else M = h;
     }
    }
    if ((K | 0) == 145) {
     K = 0;
     M = d[P >> 0] | 0;
    }
    if (!M) {
     N = 1;
     K = 154;
     break;
    }
    h = M & 15;
    i = M >>> 4 & 15;
    c[T + (q << 2) >> 2] = i + 1;
    S = k - h | 0;
    h = m << h;
    i = p - i | 0;
   }
   q = q + 1 | 0;
   if (q >>> 0 >= ((L & 31) + -1 | 0) >>> 0) {
    K = 150;
    break;
   } else {
    p = i;
    k = S;
   }
  }
  if ((K | 0) == 150) {
   c[b + (i << 2) >> 2] = c[T + 64 + ((L & 31) + -1 << 2) >> 2];
   h = 1 << i;
   j = (L & 31) + -2 | 0;
   while (1) {
    i = (c[T + (j << 2) >> 2] | 0) + i | 0;
    h = 1 << i | h;
    c[b + (i << 2) >> 2] = c[T + 64 + (j << 2) >> 2];
    if (!j) {
     R = h;
     O = S;
     break;
    } else j = j + -1 | 0;
   }
  } else if ((K | 0) == 154) {
   l = T;
   return N | 0;
  }
 } while (0);
 h = (c[a + 16 >> 2] | 0) + (32 - O) | 0;
 c[a + 16 >> 2] = h;
 c[a + 8 >> 2] = h & 7;
 if (h >>> 0 > c[a + 12 >> 2] << 3 >>> 0) {
  a = 1;
  l = T;
  return a | 0;
 }
 c[a + 4 >> 2] = (c[a >> 2] | 0) + (h >>> 3);
 a = R << 16 | (L & 31) << 4;
 l = T;
 return a | 0;
}

function Ra(b, e, f, g, h, i) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 var j = 0, k = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0, H = 0, I = 0, J = 0, K = 0, L = 0, M = 0, O = 0, P = 0, Q = 0, R = 0, S = 0, T = 0;
 T = l;
 l = l + 480 | 0;
 R = c[e + 4 >> 2] | 0;
 j = c[e + 8 >> 2] | 0;
 Q = (N(R, f) | 0) + g | 0;
 S = N(j, R) | 0;
 m = c[e >> 2] | 0;
 c[e + 12 >> 2] = m + (((Q >>> 0) % (R >>> 0) | 0) << 4) + (Q - ((Q >>> 0) % (R >>> 0) | 0) << 8);
 Q = m + (S << 8) + (Q - ((Q >>> 0) % (R >>> 0) | 0) << 6) + (((Q >>> 0) % (R >>> 0) | 0) << 3) | 0;
 c[e + 16 >> 2] = Q;
 c[e + 20 >> 2] = Q + (S << 6);
 m = m + (N(f << 8, R) | 0) + (g << 4) | 0;
 c[b + 20 >> 2] = 40;
 c[b + 8 >> 2] = 0;
 c[b >> 2] = 6;
 c[b + 12 >> 2] = 0;
 c[b + 16 >> 2] = 0;
 c[b + 24 >> 2] = 0;
 a : do switch (h | 0) {
 case 2:
 case 7:
  {
   pb(T + 96 | 0, 0, 384) | 0;
   break;
  }
 default:
  {
   c[T + 24 >> 2] = 0;
   c[T + 4 >> 2] = R;
   c[T + 8 >> 2] = j;
   c[T >> 2] = i;
   if (!i) {
    pb(T + 96 | 0, 0, 384) | 0;
    break a;
   }
   Ga(T + 96 | 0, T + 24 | 0, T, g << 4, f << 4, 0, 0, 16, 16);
   Ka(e, T + 96 | 0);
   l = T;
   return;
  }
 } while (0);
 i = T + 32 | 0;
 k = i + 64 | 0;
 do {
  c[i >> 2] = 0;
  i = i + 4 | 0;
 } while ((i | 0) < (k | 0));
 if (!f) {
  w = 0;
  z = 0;
  D = 0;
  G = 0;
  J = 0;
  i = 0;
  h = 0;
 } else if (!(c[b + ((0 - R | 0) * 216 | 0) + 196 >> 2] | 0)) {
  w = 0;
  z = 0;
  D = 0;
  G = 0;
  J = 0;
  i = 0;
  h = 0;
 } else {
  O = m + (0 - (R << 4)) + 1 + 1 | 0;
  P = (d[m + (0 - (R << 4)) + 1 >> 0] | 0) + (d[m + (0 - (R << 4)) >> 0] | 0) + (d[O >> 0] | 0) + (d[O + 1 >> 0] | 0) | 0;
  Q = O + 1 + 1 + 1 + 1 + 1 | 0;
  O = (d[O + 1 + 1 + 1 >> 0] | 0) + (d[O + 1 + 1 >> 0] | 0) + (d[O + 1 + 1 + 1 + 1 >> 0] | 0) + (d[Q >> 0] | 0) | 0;
  h = Q + 1 + 1 + 1 + 1 + 1 | 0;
  Q = (d[Q + 1 + 1 >> 0] | 0) + (d[Q + 1 >> 0] | 0) + (d[Q + 1 + 1 + 1 >> 0] | 0) + (d[Q + 1 + 1 + 1 + 1 >> 0] | 0) | 0;
  h = (d[h + 1 >> 0] | 0) + (d[h >> 0] | 0) + (d[h + 1 + 1 >> 0] | 0) + (d[h + 1 + 1 + 1 >> 0] | 0) | 0;
  c[T + 32 >> 2] = Q + (O + P) + h;
  c[T + 32 + 4 >> 2] = O + P - Q - h;
  w = 1;
  z = P;
  D = O;
  G = Q;
  J = h;
  i = Q + (O + P) + h | 0;
  h = O + P - Q - h | 0;
 }
 if ((j + -1 | 0) == (f | 0)) {
  x = 0;
  t = w;
  y = 0;
  A = 0;
  B = 0;
  E = 0;
 } else if (!(c[b + (R * 216 | 0) + 196 >> 2] | 0)) {
  x = 0;
  t = w;
  y = 0;
  A = 0;
  B = 0;
  E = 0;
 } else {
  A = m + (R << 8) + 1 + 1 + 1 | 0;
  y = (d[m + (R << 8) + 1 >> 0] | 0) + (d[m + (R << 8) >> 0] | 0) + (d[m + (R << 8) + 1 + 1 >> 0] | 0) + (d[A >> 0] | 0) | 0;
  x = A + 1 + 1 + 1 + 1 + 1 | 0;
  A = (d[A + 1 + 1 >> 0] | 0) + (d[A + 1 >> 0] | 0) + (d[A + 1 + 1 + 1 >> 0] | 0) + (d[A + 1 + 1 + 1 + 1 >> 0] | 0) | 0;
  B = (d[x + 1 >> 0] | 0) + (d[x >> 0] | 0) + (d[x + 1 + 1 >> 0] | 0) + (d[x + 1 + 1 + 1 >> 0] | 0) | 0;
  E = x + 1 + 1 + 1 + 1 + 1 | 0;
  E = (d[E >> 0] | 0) + (d[x + 1 + 1 + 1 + 1 >> 0] | 0) + (d[E + 1 >> 0] | 0) + (d[E + 1 + 1 >> 0] | 0) | 0;
  i = B + (A + y) + i + E | 0;
  c[T + 32 >> 2] = i;
  h = A + y - B - E + h | 0;
  c[T + 32 + 4 >> 2] = h;
  x = 1;
  t = w + 1 | 0;
 }
 if (!g) {
  s = 0;
  j = t;
  v = 0;
  u = 0;
  C = 0;
  F = 0;
  r = 0;
 } else if (!(c[b + -20 >> 2] | 0)) {
  s = 0;
  j = t;
  v = 0;
  u = 0;
  C = 0;
  F = 0;
  r = 0;
 } else {
  P = (d[m + -1 + (R << 4) >> 0] | 0) + (d[m + -1 >> 0] | 0) + (d[m + -1 + (R << 5) >> 0] | 0) + (d[m + -1 + (R * 48 | 0) >> 0] | 0) | 0;
  r = m + -1 + (R << 6) | 0;
  O = (d[r + (R << 4) >> 0] | 0) + (d[r >> 0] | 0) + (d[r + (R << 5) >> 0] | 0) + (d[r + (R * 48 | 0) >> 0] | 0) | 0;
  Q = (d[r + (R << 6) + (R << 4) >> 0] | 0) + (d[r + (R << 6) >> 0] | 0) + (d[r + (R << 6) + (R << 5) >> 0] | 0) + (d[r + (R << 6) + (R * 48 | 0) >> 0] | 0) | 0;
  r = r + (R << 6) + (R << 6) | 0;
  r = (d[r + (R << 4) >> 0] | 0) + (d[r >> 0] | 0) + (d[r + (R << 5) >> 0] | 0) + (d[r + (R * 48 | 0) >> 0] | 0) | 0;
  i = Q + (O + P) + i + r | 0;
  c[T + 32 >> 2] = i;
  c[T + 32 + 16 >> 2] = O + P - Q - r;
  s = 1;
  j = t + 1 | 0;
  v = P;
  u = O;
  C = Q;
  F = r;
  r = O + P - Q - r | 0;
 }
 do if ((R + -1 | 0) == (g | 0)) K = 17; else if (!(c[b + 412 >> 2] | 0)) K = 17; else {
  n = (d[m + 16 + (R << 4) >> 0] | 0) + (d[m + 16 >> 0] | 0) + (d[m + 16 + (R << 5) >> 0] | 0) + (d[m + 16 + (R * 48 | 0) >> 0] | 0) | 0;
  m = m + 16 + (R << 6) | 0;
  k = (d[m + (R << 4) >> 0] | 0) + (d[m >> 0] | 0) + (d[m + (R << 5) >> 0] | 0) + (d[m + (R * 48 | 0) >> 0] | 0) | 0;
  b = (d[m + (R << 6) + (R << 4) >> 0] | 0) + (d[m + (R << 6) >> 0] | 0) + (d[m + (R << 6) + (R << 5) >> 0] | 0) + (d[m + (R << 6) + (R * 48 | 0) >> 0] | 0) | 0;
  m = m + (R << 6) + (R << 6) | 0;
  m = (d[m + (R << 4) >> 0] | 0) + (d[m >> 0] | 0) + (d[m + (R << 5) >> 0] | 0) + (d[m + (R * 48 | 0) >> 0] | 0) | 0;
  o = j + 1 | 0;
  p = s + 1 | 0;
  i = b + (k + n) + i + m | 0;
  c[T + 32 >> 2] = i;
  r = k + n - b - m + r | 0;
  c[T + 32 + 16 >> 2] = r;
  j = (t | 0) == 0;
  s = (s | 0) != 0;
  if (j & s) {
   h = C + F + u + v - n - k - b - m >> 5;
   c[T + 32 + 4 >> 2] = h;
  } else if (!j) {
   q = 1;
   m = p;
   n = o;
   b = r;
   j = T + 32 + 4 | 0;
   k = s;
   K = 22;
   break;
  }
  q = 1;
  n = o;
  j = r;
  o = T + 32 + 16 | 0;
  k = s;
  m = (w | 0) != 0;
  b = (x | 0) != 0;
  K = 28;
 } while (0);
 if ((K | 0) == 17) {
  k = (s | 0) != 0;
  if (!t) {
   q = 0;
   p = s;
   n = j;
   o = r;
   K = 24;
  } else {
   q = 0;
   m = s;
   n = j;
   b = r;
   j = T + 32 + 4 | 0;
   K = 22;
  }
 }
 if ((K | 0) == 22) {
  h = h >> t + 3;
  c[j >> 2] = h;
  p = m;
  o = b;
  K = 24;
 }
 do if ((K | 0) == 24) {
  j = (p | 0) == 0;
  m = (w | 0) != 0;
  b = (x | 0) != 0;
  if (b & (m & j)) {
   j = G + J + D + z - E - B - A - y >> 5;
   c[T + 32 + 16 >> 2] = j;
   Q = q;
   P = k;
   m = 1;
   O = 1;
   break;
  }
  if (j) {
   Q = q;
   j = o;
   P = k;
   O = b;
  } else {
   j = o;
   o = T + 32 + 16 | 0;
   K = 28;
  }
 } while (0);
 if ((K | 0) == 28) {
  j = j >> p + 3;
  c[o >> 2] = j;
  Q = q;
  P = k;
  O = b;
 }
 switch (n | 0) {
 case 1:
  {
   i = i >> 4;
   break;
  }
 case 2:
  {
   i = i >> 5;
   break;
  }
 case 3:
  {
   i = i * 21 >> 10;
   break;
  }
 default:
  i = i >> 6;
 }
 c[T + 32 >> 2] = i;
 L = T + 32 + 4 | 0;
 M = T + 32 + 16 | 0;
 if (!(j | h)) {
  c[T + 32 + 60 >> 2] = i;
  c[T + 32 + 56 >> 2] = i;
  c[T + 32 + 52 >> 2] = i;
  c[T + 32 + 48 >> 2] = i;
  c[T + 32 + 44 >> 2] = i;
  c[T + 32 + 40 >> 2] = i;
  c[T + 32 + 36 >> 2] = i;
  c[T + 32 + 32 >> 2] = i;
  c[T + 32 + 28 >> 2] = i;
  c[T + 32 + 24 >> 2] = i;
  c[T + 32 + 20 >> 2] = i;
  c[M >> 2] = i;
  c[T + 32 + 12 >> 2] = i;
  c[T + 32 + 8 >> 2] = i;
  c[L >> 2] = i;
  i = T + 32 | 0;
  j = T + 96 | 0;
  h = 0;
 } else {
  H = h + i | 0;
  K = h >> 1;
  I = K + i | 0;
  K = i - K | 0;
  i = i - h | 0;
  c[T + 32 >> 2] = j + H;
  h = j >> 1;
  c[M >> 2] = h + H;
  c[T + 32 + 32 >> 2] = H - h;
  c[T + 32 + 48 >> 2] = H - j;
  c[L >> 2] = I + j;
  c[T + 32 + 20 >> 2] = h + I;
  c[T + 32 + 36 >> 2] = I - h;
  c[T + 32 + 52 >> 2] = I - j;
  c[T + 32 + 8 >> 2] = K + j;
  c[T + 32 + 24 >> 2] = h + K;
  c[T + 32 + 40 >> 2] = K - h;
  c[T + 32 + 56 >> 2] = K - j;
  c[T + 32 + 12 >> 2] = j + i;
  c[T + 32 + 28 >> 2] = h + i;
  c[T + 32 + 44 >> 2] = i - h;
  c[T + 32 + 60 >> 2] = i - j;
  i = T + 32 | 0;
  j = T + 96 | 0;
  h = 0;
 }
 while (1) {
  K = c[i + ((h >>> 2 & 3) << 2) >> 2] | 0;
  a[j >> 0] = (K | 0) > 0 ? ((K | 0) < 255 ? K : 255) & 255 : 0;
  h = h + 1 | 0;
  if ((h | 0) == 256) break; else {
   i = (h & 63 | 0) == 0 ? i + 16 | 0 : i;
   j = j + 1 | 0;
  }
 }
 H = (c[e >> 2] | 0) + (S << 8) + (N(f << 6, R) | 0) + (g << 3) | 0;
 I = 0;
 t = y;
 q = z;
 r = A;
 b = D;
 o = B;
 s = C;
 j = G;
 n = E;
 p = F;
 h = J;
 while (1) {
  i = T + 32 | 0;
  k = i + 64 | 0;
  do {
   c[i >> 2] = 0;
   i = i + 4 | 0;
  } while ((i | 0) < (k | 0));
  if (m) {
   K = H + (0 - (R << 3)) | 0;
   J = (d[K + 1 >> 0] | 0) + (d[K >> 0] | 0) | 0;
   G = (d[K + 1 + 1 + 1 >> 0] | 0) + (d[K + 1 + 1 >> 0] | 0) | 0;
   j = K + 1 + 1 + 1 + 1 + 1 | 0;
   K = (d[j >> 0] | 0) + (d[K + 1 + 1 + 1 + 1 >> 0] | 0) | 0;
   j = (d[j + 1 + 1 >> 0] | 0) + (d[j + 1 >> 0] | 0) | 0;
   c[T + 32 >> 2] = K + (G + J) + j;
   c[L >> 2] = G + J - K - j;
   i = 1;
   f = J;
   g = G;
   B = K;
   C = j;
   h = K + (G + J) + j | 0;
   j = G + J - K - j | 0;
  } else {
   i = 0;
   f = q;
   g = b;
   B = j;
   C = h;
   h = 0;
   j = 0;
  }
  if (O) {
   z = H + (R << 6) | 0;
   t = (d[z + 1 >> 0] | 0) + (d[z >> 0] | 0) | 0;
   x = (d[z + 1 + 1 + 1 >> 0] | 0) + (d[z + 1 + 1 >> 0] | 0) | 0;
   A = z + 1 + 1 + 1 + 1 + 1 | 0;
   z = (d[A >> 0] | 0) + (d[z + 1 + 1 + 1 + 1 >> 0] | 0) | 0;
   A = (d[A + 1 + 1 >> 0] | 0) + (d[A + 1 >> 0] | 0) | 0;
   h = z + (x + t) + h + A | 0;
   c[T + 32 >> 2] = h;
   j = x + t - z - A + j | 0;
   c[L >> 2] = j;
   w = i + 1 | 0;
  } else {
   w = i;
   x = r;
   z = o;
   A = n;
  }
  if (P) {
   i = H + -1 | 0;
   J = (d[i + (R << 3) >> 0] | 0) + (d[i >> 0] | 0) | 0;
   G = (d[i + (R << 4) + (R << 3) >> 0] | 0) + (d[i + (R << 4) >> 0] | 0) | 0;
   i = i + (R << 4) + (R << 4) | 0;
   K = (d[i + (R << 3) >> 0] | 0) + (d[i >> 0] | 0) | 0;
   i = (d[i + (R << 4) + (R << 3) >> 0] | 0) + (d[i + (R << 4) >> 0] | 0) | 0;
   h = K + (G + J) + h + i | 0;
   c[T + 32 >> 2] = h;
   c[M >> 2] = G + J - K - i;
   b = 1;
   k = w + 1 | 0;
   v = J;
   u = G;
   s = K;
   y = i;
   i = G + J - K - i | 0;
  } else {
   b = 0;
   k = w;
   y = p;
   i = 0;
  }
  do if (Q) {
   r = H + 8 | 0;
   o = (d[r + (R << 3) >> 0] | 0) + (d[r >> 0] | 0) | 0;
   p = (d[r + (R << 4) + (R << 3) >> 0] | 0) + (d[r + (R << 4) >> 0] | 0) | 0;
   r = r + (R << 4) + (R << 4) | 0;
   q = (d[r + (R << 3) >> 0] | 0) + (d[r >> 0] | 0) | 0;
   r = (d[r + (R << 4) + (R << 3) >> 0] | 0) + (d[r + (R << 4) >> 0] | 0) | 0;
   k = k + 1 | 0;
   n = b + 1 | 0;
   h = q + (p + o) + h + r | 0;
   c[T + 32 >> 2] = h;
   i = p + o - q - r + i | 0;
   c[M >> 2] = i;
   b = (w | 0) == 0;
   if (P & b) {
    j = s + y + u + v - o - p - q - r >> 4;
    c[L >> 2] = j;
    b = n;
    K = 54;
    break;
   } else if (b) {
    b = n;
    K = 54;
    break;
   } else {
    b = n;
    K = 50;
    break;
   }
  } else if (!w) {
   n = h;
   K = 51;
  } else K = 50; while (0);
  if ((K | 0) == 50) {
   j = j >> w + 2;
   c[L >> 2] = j;
   n = h;
   K = 51;
  }
  do if ((K | 0) == 51) {
   K = 0;
   h = (b | 0) == 0;
   if (O & (m & h)) {
    i = B + C + g + f - A - z - x - t | 0;
    b = 4;
    h = n;
    K = 55;
    break;
   } else if (h) {
    h = n;
    break;
   } else {
    h = n;
    K = 54;
    break;
   }
  } while (0);
  if ((K | 0) == 54) {
   b = b + 2 | 0;
   K = 55;
  }
  if ((K | 0) == 55) {
   i = i >> b;
   c[M >> 2] = i;
  }
  switch (k | 0) {
  case 1:
   {
    h = h >> 3;
    break;
   }
  case 2:
   {
    h = h >> 4;
    break;
   }
  case 3:
   {
    h = h * 21 >> 9;
    break;
   }
  default:
   h = h >> 5;
  }
  c[T + 32 >> 2] = h;
  if (!(i | j)) {
   c[T + 32 + 60 >> 2] = h;
   c[T + 32 + 56 >> 2] = h;
   c[T + 32 + 52 >> 2] = h;
   c[T + 32 + 48 >> 2] = h;
   c[T + 32 + 44 >> 2] = h;
   c[T + 32 + 40 >> 2] = h;
   c[T + 32 + 36 >> 2] = h;
   c[T + 32 + 32 >> 2] = h;
   c[T + 32 + 28 >> 2] = h;
   c[T + 32 + 24 >> 2] = h;
   c[T + 32 + 20 >> 2] = h;
   c[M >> 2] = h;
   c[T + 32 + 12 >> 2] = h;
   c[T + 32 + 8 >> 2] = h;
   c[L >> 2] = h;
  } else {
   E = j + h | 0;
   G = j >> 1;
   F = G + h | 0;
   G = h - G | 0;
   K = h - j | 0;
   c[T + 32 >> 2] = i + E;
   J = i >> 1;
   c[M >> 2] = J + E;
   c[T + 32 + 32 >> 2] = E - J;
   c[T + 32 + 48 >> 2] = E - i;
   c[L >> 2] = F + i;
   c[T + 32 + 20 >> 2] = J + F;
   c[T + 32 + 36 >> 2] = F - J;
   c[T + 32 + 52 >> 2] = F - i;
   c[T + 32 + 8 >> 2] = G + i;
   c[T + 32 + 24 >> 2] = J + G;
   c[T + 32 + 40 >> 2] = G - J;
   c[T + 32 + 56 >> 2] = G - i;
   c[T + 32 + 12 >> 2] = i + K;
   c[T + 32 + 28 >> 2] = J + K;
   c[T + 32 + 44 >> 2] = K - J;
   c[T + 32 + 60 >> 2] = K - i;
  }
  i = T + 32 | 0;
  j = T + 96 + 256 + (I << 6) | 0;
  h = 0;
  while (1) {
   K = c[i + ((h >>> 1 & 3) << 2) >> 2] | 0;
   a[j >> 0] = (K | 0) > 0 ? ((K | 0) < 255 ? K : 255) & 255 : 0;
   h = h + 1 | 0;
   if ((h | 0) == 64) break; else {
    i = (h & 15 | 0) == 0 ? i + 16 | 0 : i;
    j = j + 1 | 0;
   }
  }
  I = I + 1 | 0;
  if ((I | 0) == 2) break; else {
   H = H + (S << 6) | 0;
   q = f;
   r = x;
   b = g;
   o = z;
   j = B;
   n = A;
   p = y;
   h = C;
  }
 }
 Ka(e, T + 96 | 0);
 l = T;
 return;
}

function Va(a) {
 a = a | 0;
 var b = 0, d = 0, e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0;
 s = l;
 l = l + 16 | 0;
 c[1809] = a;
 b = c[1810] | 0;
 c[1805] = b;
 c[1806] = a;
 a : while (1) {
  e = c[1815] | 0;
  c[1807] = e;
  q = c[1813] | 0;
  b : do if ((b | 0) == 0 | (a | 0) == 0 | (q | 0) == 0) r = 32; else {
   d = c[q >> 2] | 0;
   if (!d) r = 32; else {
    c[1816] = 0;
    c[s >> 2] = 0;
    c[q + 3392 >> 2] = c[1808];
    c : do if ((d | 0) == 2) {
     a = 0;
     r = 6;
    } else {
     f = a;
     a = 1;
     d = e;
     d : while (1) {
      n = Ta(q + 8 | 0, b, f, d, s) | 0;
      p = c[s >> 2] | 0;
      b = b + p | 0;
      o = f - p | 0;
      f = (o | 0) > 0 ? o : 0;
      c[1816] = b;
      switch (n | 0) {
      case 5:
       {
        r = 32;
        break b;
       }
      case 2:
       {
        r = 8;
        break c;
       }
      case 1:
       {
        r = 11;
        break d;
       }
      case 4:
       {
        n = 0;
        e : while (1) {
         e = c[q + 8 + 148 + (n << 2) >> 2] | 0;
         f : do if (e | 0) {
          d = c[q + 8 + 20 + (c[e + 4 >> 2] << 2) >> 2] | 0;
          if (d | 0) {
           j = c[d + 52 >> 2] | 0;
           k = N(c[d + 56 >> 2] | 0, j) | 0;
           m = c[e + 12 >> 2] | 0;
           if (m >>> 0 <= 1) {
            d = 1;
            break e;
           }
           d = c[e + 16 >> 2] | 0;
           switch (d | 0) {
           case 0:
            {
             e = c[e + 20 >> 2] | 0;
             d = 0;
             while (1) {
              if ((c[e + (d << 2) >> 2] | 0) >>> 0 > k >>> 0) break f;
              d = d + 1 | 0;
              if (d >>> 0 >= m >>> 0) {
               d = 1;
               break e;
              }
             }
            }
           case 2:
            {
             i = c[e + 24 >> 2] | 0;
             e = c[e + 28 >> 2] | 0;
             d = 0;
             while (1) {
              g = c[i + (d << 2) >> 2] | 0;
              h = c[e + (d << 2) >> 2] | 0;
              if (!(g >>> 0 <= h >>> 0 & h >>> 0 < k >>> 0)) break f;
              d = d + 1 | 0;
              if (((g >>> 0) % (j >>> 0) | 0) >>> 0 > ((h >>> 0) % (j >>> 0) | 0) >>> 0) break f;
              if (d >>> 0 >= (m + -1 | 0) >>> 0) {
               d = 1;
               break e;
              }
             }
            }
           default:
            {
             if ((d + -3 | 0) >>> 0 < 3) if ((c[e + 36 >> 2] | 0) >>> 0 > k >>> 0) break f; else {
              d = 1;
              break e;
             }
             if ((d | 0) != 6) {
              d = 1;
              break e;
             }
             if ((c[e + 40 >> 2] | 0) >>> 0 < k >>> 0) break f; else {
              d = 1;
              break e;
             }
            }
           }
          }
         } while (0);
         n = n + 1 | 0;
         if (n >>> 0 >= 256) {
          d = 0;
          break;
         }
        }
        a = (f | d | 0) == 0 ? -2 : a;
        break;
       }
      default:
       {}
      }
      if ((o | 0) < 1) break;
      if ((c[q >> 2] | 0) == 2) {
       a = p;
       r = 6;
       break c;
      }
      d = c[1807] | 0;
     }
     if ((r | 0) == 11) {
      r = 0;
      c[q + 4 >> 2] = (c[q + 4 >> 2] | 0) + 1;
      a = (o | 0) < 1 ? 2 : 3;
     }
     switch (a | 0) {
     case -2:
     case 1:
      break a;
     case 4:
      {
       r = 35;
       break;
      }
     case 3:
      {
       r = 72;
       break;
      }
     case 2:
      break;
     default:
      {
       r = 84;
       break b;
      }
     }
    } while (0);
    if ((r | 0) == 6) {
     c[q >> 2] = 1;
     b = b + a | 0;
     c[1816] = b;
     r = 8;
    }
    do if ((r | 0) == 8) {
     if (c[q + 1288 >> 2] | 0) if ((c[q + 1244 >> 2] | 0) != (c[q + 1248 >> 2] | 0)) {
      c[q + 1288 >> 2] = 0;
      c[q >> 2] = 2;
      r = 72;
      break;
     }
     r = 35;
    } while (0);
    if ((r | 0) == 35) {
     r = 0;
     a = c[1813] | 0;
     if (!a) {
      r = 84;
      break;
     }
     g = c[a + 24 >> 2] | 0;
     if (!g) {
      r = 84;
      break;
     }
     if (!(c[a + 20 >> 2] | 0)) {
      r = 84;
      break;
     }
     d = c[g + 52 >> 2] << 4;
     c[1818] = d;
     e = c[g + 56 >> 2] << 4;
     c[1819] = e;
     if (!(c[g + 80 >> 2] | 0)) {
      c[1820] = 0;
      b = 2;
     } else {
      b = c[g + 84 >> 2] | 0;
      if (!b) b = 0; else if (!(c[b + 24 >> 2] | 0)) b = 0; else b = (c[b + 32 >> 2] | 0) == 0 ? 0 : 1;
      c[1820] = b;
      b = c[g + 84 >> 2] | 0;
      if (!b) b = 2; else if (!(c[b + 24 >> 2] | 0)) b = 2; else if (!(c[b + 36 >> 2] | 0)) b = 2; else b = c[b + 48 >> 2] | 0;
     }
     c[1821] = b;
     if (!(c[g + 60 >> 2] | 0)) {
      c[1824] = 0;
      c[1825] = 0;
      c[1826] = 0;
      c[1827] = 0;
      b = c[a + 24 >> 2] | 0;
      c[1828] = 0;
      if (!b) {
       c[1822] = 1;
       c[1823] = 1;
       b = 0;
      } else {
       f = b;
       e = (b | 0) == 0;
       r = 50;
      }
     } else {
      c[1824] = 1;
      f = c[g + 64 >> 2] | 0;
      c[1825] = f << 1;
      c[1826] = d - ((c[g + 68 >> 2] | 0) + f << 1);
      f = c[g + 72 >> 2] | 0;
      c[1827] = f << 1;
      c[1828] = e - ((c[g + 76 >> 2] | 0) + f << 1);
      f = g;
      e = (g | 0) == 0;
      r = 50;
     }
     if ((r | 0) == 50) {
      r = 0;
      g : do if (!(c[f + 80 >> 2] | 0)) {
       a = 1;
       b = 1;
      } else {
       b = c[f + 84 >> 2] | 0;
       if (!b) {
        a = 1;
        b = 1;
       } else if (!(c[b >> 2] | 0)) {
        a = 1;
        b = 1;
       } else {
        d = c[b + 4 >> 2] | 0;
        do switch (d | 0) {
        case 1:
        case 0:
         {
          a = d;
          b = d;
          break g;
         }
        case 2:
         {
          a = 11;
          b = 12;
          break g;
         }
        case 3:
         {
          a = 11;
          b = 10;
          break g;
         }
        case 4:
         {
          a = 11;
          b = 16;
          break g;
         }
        case 5:
         {
          a = 33;
          b = 40;
          break g;
         }
        case 6:
         {
          a = 11;
          b = 24;
          break g;
         }
        case 7:
         {
          a = 11;
          b = 20;
          break g;
         }
        case 8:
         {
          a = 11;
          b = 32;
          break g;
         }
        case 9:
         {
          a = 33;
          b = 80;
          break g;
         }
        case 10:
         {
          a = 11;
          b = 18;
          break g;
         }
        case 11:
         {
          a = 11;
          b = 15;
          break g;
         }
        case 12:
         {
          a = 33;
          b = 64;
          break g;
         }
        case 13:
         {
          a = 99;
          b = 160;
          break g;
         }
        case 255:
         {
          q = c[b + 8 >> 2] | 0;
          b = c[b + 12 >> 2] | 0;
          a = (q | 0) == 0 | (b | 0) == 0 ? 0 : b;
          b = (q | 0) == 0 | (b | 0) == 0 ? 0 : q;
          break g;
         }
        default:
         {
          a = 0;
          b = 0;
          break g;
         }
        } while (0);
       }
      } while (0);
      c[1822] = b;
      c[1823] = a;
      if (e) b = 0; else b = c[f >> 2] | 0;
     }
     c[1817] = b;
     ca();
     q = c[1816] | 0;
     a = (c[1805] | 0) - q + (c[1806] | 0) | 0;
     c[1806] = a;
     c[1805] = q;
     break;
    } else if ((r | 0) == 72) {
     c[1806] = (c[1805] | 0) - b + (c[1806] | 0);
     c[1805] = b;
    }
    c[1806] = 0;
    c[1815] = (c[1815] | 0) + 1;
    b = c[1813] | 0;
    if (!b) r = 84; else {
     a = c[b + 1248 >> 2] | 0;
     if (a >>> 0 < (c[b + 1244 >> 2] | 0) >>> 0) {
      d = c[b + 1240 >> 2] | 0;
      c[b + 1248 >> 2] = a + 1;
      if (!(d + (a << 4) | 0)) r = 84; else {
       b = c[d + (a << 4) >> 2] | 0;
       if (!b) r = 84; else {
        f = d + (a << 4) + 8 | 0;
        g = d + (a << 4) + 12 | 0;
        e = b;
        b = d + (a << 4) + 4 | 0;
        while (1) {
         r = c[f >> 2] | 0;
         q = c[g >> 2] | 0;
         b = c[b >> 2] | 0;
         c[1829] = e;
         c[1830] = b;
         c[1831] = q;
         c[1832] = r;
         c[1814] = (c[1814] | 0) + 1;
         da(e | 0, c[1818] | 0, c[1819] | 0);
         b = c[1813] | 0;
         if (!b) {
          r = 84;
          break b;
         }
         a = c[b + 1248 >> 2] | 0;
         if (a >>> 0 >= (c[b + 1244 >> 2] | 0) >>> 0) {
          r = 84;
          break b;
         }
         d = c[b + 1240 >> 2] | 0;
         c[b + 1248 >> 2] = a + 1;
         if (!(d + (a << 4) | 0)) {
          r = 84;
          break b;
         }
         b = c[d + (a << 4) >> 2] | 0;
         if (!b) {
          r = 84;
          break b;
         }
         f = d + (a << 4) + 8 | 0;
         g = d + (a << 4) + 12 | 0;
         e = b;
         b = d + (a << 4) + 4 | 0;
        }
       }
      }
     } else r = 84;
    }
   }
  } while (0);
  if ((r | 0) == 32) r = 84;
  if ((r | 0) == 84) {
   r = 0;
   a = c[1806] | 0;
  }
  if (!a) {
   r = 86;
   break;
  }
  b = c[1805] | 0;
 }
 if ((r | 0) == 86) {
  l = s;
  return;
 }
 c[1806] = 0;
 l = s;
 return;
}

function Ha(a, b, d, e, f, g, h, i) {
 a = a | 0;
 b = b | 0;
 d = d | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 var j = 0, k = 0, l = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0;
 j = c[a + 8 >> 2] | 0;
 if ((c[j >> 2] | 0) != (d | 0)) return;
 c[a + 52 >> 2] = 0;
 t = (c[a + 56 >> 2] | 0) == 0;
 do if (!b) {
  c[j + 20 >> 2] = 0;
  c[j + 12 >> 2] = e;
  c[j + 8 >> 2] = e;
  c[j + 16 >> 2] = f;
  c[j + 24 >> 2] = t & 1;
  if (t) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + 1;
 } else {
  if (g | 0) {
   c[a + 20 >> 2] = 0;
   c[a + 16 >> 2] = 0;
   Ia(a);
   if (!(c[b >> 2] | 0)) {
    if (c[a + 56 >> 2] | 0) s = 8;
   } else s = 8;
   if ((s | 0) == 8) {
    c[a + 16 >> 2] = 0;
    c[a + 20 >> 2] = 0;
   }
   s = (c[b + 4 >> 2] | 0) == 0;
   f = c[a + 8 >> 2] | 0;
   c[f + 20 >> 2] = s ? 2 : 3;
   c[a + 36 >> 2] = s ? 65535 : 0;
   c[f + 12 >> 2] = 0;
   c[f + 8 >> 2] = 0;
   c[f + 16 >> 2] = 0;
   c[f + 24 >> 2] = t & 1;
   c[a + 44 >> 2] = 1;
   c[a + 40 >> 2] = 1;
   break;
  }
  if (!(c[b + 8 >> 2] | 0)) {
   j = c[a + 40 >> 2] | 0;
   d = c[a + 24 >> 2] | 0;
   if (j >>> 0 < d >>> 0) k = a + 40 | 0; else if (!j) {
    k = a + 40 | 0;
    j = 0;
   } else {
    n = c[a >> 2] | 0;
    k = 0;
    l = -1;
    m = 0;
    do {
     if (((c[n + (m * 40 | 0) + 20 >> 2] | 0) + -1 | 0) >>> 0 < 2) {
      b = c[n + (m * 40 | 0) + 8 >> 2] | 0;
      s = (l | 0) == -1 | (b | 0) < (k | 0);
      k = s ? b : k;
      l = s ? m : l;
     }
     m = m + 1 | 0;
    } while ((m | 0) != (j | 0));
    if ((l | 0) > -1) {
     c[n + (l * 40 | 0) + 20 >> 2] = 0;
     c[a + 40 >> 2] = j + -1;
     if (!(c[n + (l * 40 | 0) + 24 >> 2] | 0)) {
      c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
      k = a + 40 | 0;
      j = j + -1 | 0;
     } else {
      k = a + 40 | 0;
      j = j + -1 | 0;
     }
    } else k = a + 40 | 0;
   }
  } else {
   d = 0;
   r = 0;
   j = e;
   a : while (1) {
    switch (c[b + 12 + (r * 20 | 0) >> 2] | 0) {
    case 6:
     {
      m = c[b + 12 + (r * 20 | 0) + 12 >> 2] | 0;
      q = c[a + 36 >> 2] | 0;
      if ((q | 0) == 65535 | q >>> 0 < m >>> 0) break a;
      n = c[a + 24 >> 2] | 0;
      b : do if (n | 0) {
       l = c[a >> 2] | 0;
       e = 0;
       while (1) {
        k = l + (e * 40 | 0) + 20 | 0;
        if ((c[k >> 2] | 0) == 3) if ((c[l + (e * 40 | 0) + 8 >> 2] | 0) == (m | 0)) break;
        e = e + 1 | 0;
        if (e >>> 0 >= n >>> 0) break b;
       }
       c[k >> 2] = 0;
       c[a + 40 >> 2] = (c[a + 40 >> 2] | 0) + -1;
       if (!(c[l + (e * 40 | 0) + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
      } while (0);
      e = c[a + 40 >> 2] | 0;
      if (e >>> 0 >= n >>> 0) break a;
      d = c[a + 8 >> 2] | 0;
      c[d + 12 >> 2] = j;
      c[d + 8 >> 2] = m;
      c[d + 16 >> 2] = f;
      c[d + 20 >> 2] = 3;
      c[d + 24 >> 2] = (c[a + 56 >> 2] | 0) == 0 & 1;
      c[a + 40 >> 2] = e + 1;
      c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + 1;
      d = 1;
      break;
     }
    case 1:
     {
      l = j - (c[b + 12 + (r * 20 | 0) + 4 >> 2] | 0) | 0;
      m = c[a + 24 >> 2] | 0;
      if (!m) break a;
      n = c[a >> 2] | 0;
      e = 0;
      while (1) {
       k = n + (e * 40 | 0) + 20 | 0;
       if (((c[k >> 2] | 0) + -1 | 0) >>> 0 < 2) if ((c[n + (e * 40 | 0) + 8 >> 2] | 0) == (l | 0)) break;
       e = e + 1 | 0;
       if (e >>> 0 >= m >>> 0) break a;
      }
      if ((e | 0) < 0) break a;
      c[k >> 2] = 0;
      c[a + 40 >> 2] = (c[a + 40 >> 2] | 0) + -1;
      if (!(c[n + (e * 40 | 0) + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
      break;
     }
    case 2:
     {
      l = c[b + 12 + (r * 20 | 0) + 8 >> 2] | 0;
      m = c[a + 24 >> 2] | 0;
      if (!m) break a;
      n = c[a >> 2] | 0;
      e = 0;
      while (1) {
       k = n + (e * 40 | 0) + 20 | 0;
       if ((c[k >> 2] | 0) == 3) if ((c[n + (e * 40 | 0) + 8 >> 2] | 0) == (l | 0)) break;
       e = e + 1 | 0;
       if (e >>> 0 >= m >>> 0) break a;
      }
      if ((e | 0) < 0) break a;
      c[k >> 2] = 0;
      c[a + 40 >> 2] = (c[a + 40 >> 2] | 0) + -1;
      if (!(c[n + (e * 40 | 0) + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
      break;
     }
    case 3:
     {
      l = c[b + 12 + (r * 20 | 0) + 4 >> 2] | 0;
      q = c[b + 12 + (r * 20 | 0) + 12 >> 2] | 0;
      p = c[a + 36 >> 2] | 0;
      if ((p | 0) == 65535 | p >>> 0 < q >>> 0) break a;
      o = c[a + 24 >> 2] | 0;
      if (!o) break a;
      p = c[a >> 2] | 0;
      e = 0;
      do {
       k = p + (e * 40 | 0) + 20 | 0;
       if ((c[k >> 2] | 0) == 3) if ((c[p + (e * 40 | 0) + 8 >> 2] | 0) == (q | 0)) {
        s = 34;
        break;
       }
       e = e + 1 | 0;
      } while (e >>> 0 < o >>> 0);
      if ((s | 0) == 34) {
       s = 0;
       c[k >> 2] = 0;
       c[a + 40 >> 2] = (c[a + 40 >> 2] | 0) + -1;
       if (!(c[p + (e * 40 | 0) + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
      }
      n = j - l | 0;
      e = 0;
      while (1) {
       k = p + (e * 40 | 0) + 20 | 0;
       l = c[k >> 2] | 0;
       if ((l + -1 | 0) >>> 0 < 2) {
        m = p + (e * 40 | 0) + 8 | 0;
        if ((c[m >> 2] | 0) == (n | 0)) break;
       }
       e = e + 1 | 0;
       if (e >>> 0 >= o >>> 0) break a;
      }
      if (!((e | 0) > -1 & l >>> 0 > 1)) break a;
      c[k >> 2] = 3;
      c[m >> 2] = q;
      break;
     }
    case 4:
     {
      m = c[b + 12 + (r * 20 | 0) + 16 >> 2] | 0;
      c[a + 36 >> 2] = m;
      n = c[a + 24 >> 2] | 0;
      if (n) {
       o = c[a >> 2] | 0;
       l = 0;
       e = m;
       do {
        k = o + (l * 40 | 0) + 20 | 0;
        do if ((c[k >> 2] | 0) == 3) {
         if ((c[o + (l * 40 | 0) + 8 >> 2] | 0) >>> 0 <= m >>> 0) if ((e | 0) == 65535) e = 65535; else break;
         c[k >> 2] = 0;
         c[a + 40 >> 2] = (c[a + 40 >> 2] | 0) + -1;
         if (!(c[o + (l * 40 | 0) + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
        } while (0);
        l = l + 1 | 0;
       } while ((l | 0) != (n | 0));
      }
      break;
     }
    case 5:
     {
      Ia(a);
      c[a + 52 >> 2] = 1;
      j = 0;
      break;
     }
    default:
     break a;
    }
    r = r + 1 | 0;
   }
   if (d | 0) break;
   e = j;
   k = a + 40 | 0;
   j = c[a + 40 >> 2] | 0;
   d = c[a + 24 >> 2] | 0;
  }
  if (j >>> 0 < d >>> 0) {
   s = c[a + 8 >> 2] | 0;
   c[s + 12 >> 2] = e;
   c[s + 8 >> 2] = e;
   c[s + 16 >> 2] = f;
   c[s + 20 >> 2] = 2;
   c[s + 24 >> 2] = t & 1;
   c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + 1;
   c[k >> 2] = j + 1;
  }
 } while (0);
 d = c[a + 8 >> 2] | 0;
 c[d + 36 >> 2] = g;
 c[d + 28 >> 2] = h;
 c[d + 32 >> 2] = i;
 if (!(c[a + 56 >> 2] | 0)) {
  j = c[a + 44 >> 2] | 0;
  d = c[a + 28 >> 2] | 0;
  if (j >>> 0 > d >>> 0) {
   n = c[a >> 2] | 0;
   do {
    k = 2147483647;
    l = 0;
    e = 0;
    while (1) {
     if (!(c[n + (l * 40 | 0) + 24 >> 2] | 0)) {
      m = e;
      e = k;
     } else {
      i = c[n + (l * 40 | 0) + 16 >> 2] | 0;
      h = (i | 0) < (k | 0);
      m = h ? n + (l * 40 | 0) | 0 : e;
      e = h ? i : k;
     }
     l = l + 1 | 0;
     if (l >>> 0 > d >>> 0) break; else {
      k = e;
      e = m;
     }
    }
    if (m) {
     i = c[a + 12 >> 2] | 0;
     e = c[a + 16 >> 2] | 0;
     c[i + (e << 4) >> 2] = c[m >> 2];
     c[i + (e << 4) + 12 >> 2] = c[m + 36 >> 2];
     c[i + (e << 4) + 4 >> 2] = c[m + 28 >> 2];
     c[i + (e << 4) + 8 >> 2] = c[m + 32 >> 2];
     c[a + 16 >> 2] = e + 1;
     c[m + 24 >> 2] = 0;
     e = j + -1 | 0;
     if (!(c[m + 20 >> 2] | 0)) {
      c[a + 44 >> 2] = e;
      j = e;
     }
    }
   } while (j >>> 0 > d >>> 0);
  }
 } else {
  t = c[a + 12 >> 2] | 0;
  f = c[a + 16 >> 2] | 0;
  c[t + (f << 4) >> 2] = c[d >> 2];
  c[t + (f << 4) + 12 >> 2] = g;
  c[t + (f << 4) + 4 >> 2] = h;
  c[t + (f << 4) + 8 >> 2] = i;
  c[a + 16 >> 2] = f + 1;
  d = c[a + 28 >> 2] | 0;
 }
 Ja(c[a >> 2] | 0, d + 1 | 0);
 return;
}

function $a(a) {
 a = a | 0;
 var b = 0, d = 0, e = 0, f = 0, g = 0, h = 0, i = 0, j = 0;
 if (!a) return;
 b = c[1837] | 0;
 d = c[a + -4 >> 2] | 0;
 j = a + -8 + (d & -8) | 0;
 do if (!(d & 1)) {
  e = c[a + -8 >> 2] | 0;
  if (!(d & 3)) return;
  h = a + -8 + (0 - e) | 0;
  g = e + (d & -8) | 0;
  if (h >>> 0 < b >>> 0) return;
  if ((c[1838] | 0) == (h | 0)) {
   b = c[j + 4 >> 2] | 0;
   if ((b & 3 | 0) != 3) {
    i = h;
    b = g;
    break;
   }
   c[1835] = g;
   c[j + 4 >> 2] = b & -2;
   c[h + 4 >> 2] = g | 1;
   c[h + g >> 2] = g;
   return;
  }
  if (e >>> 0 < 256) {
   b = c[h + 8 >> 2] | 0;
   a = c[h + 12 >> 2] | 0;
   if ((a | 0) == (b | 0)) {
    c[1833] = c[1833] & ~(1 << (e >>> 3));
    i = h;
    b = g;
    break;
   } else {
    c[b + 12 >> 2] = a;
    c[a + 8 >> 2] = b;
    i = h;
    b = g;
    break;
   }
  }
  f = c[h + 24 >> 2] | 0;
  b = c[h + 12 >> 2] | 0;
  do if ((b | 0) == (h | 0)) {
   b = c[h + 16 + 4 >> 2] | 0;
   if (!b) {
    b = c[h + 16 >> 2] | 0;
    if (!b) {
     b = 0;
     break;
    } else e = h + 16 | 0;
   } else e = h + 16 + 4 | 0;
   while (1) {
    a = b + 20 | 0;
    d = c[a >> 2] | 0;
    if (d | 0) {
     b = d;
     e = a;
     continue;
    }
    a = b + 16 | 0;
    d = c[a >> 2] | 0;
    if (!d) break; else {
     b = d;
     e = a;
    }
   }
   c[e >> 2] = 0;
  } else {
   i = c[h + 8 >> 2] | 0;
   c[i + 12 >> 2] = b;
   c[b + 8 >> 2] = i;
  } while (0);
  if (!f) {
   i = h;
   b = g;
  } else {
   a = c[h + 28 >> 2] | 0;
   if ((c[7636 + (a << 2) >> 2] | 0) == (h | 0)) {
    c[7636 + (a << 2) >> 2] = b;
    if (!b) {
     c[1834] = c[1834] & ~(1 << a);
     i = h;
     b = g;
     break;
    }
   } else {
    c[f + 16 + (((c[f + 16 >> 2] | 0) != (h | 0) & 1) << 2) >> 2] = b;
    if (!b) {
     i = h;
     b = g;
     break;
    }
   }
   c[b + 24 >> 2] = f;
   a = c[h + 16 >> 2] | 0;
   if (a | 0) {
    c[b + 16 >> 2] = a;
    c[a + 24 >> 2] = b;
   }
   a = c[h + 16 + 4 >> 2] | 0;
   if (!a) {
    i = h;
    b = g;
   } else {
    c[b + 20 >> 2] = a;
    c[a + 24 >> 2] = b;
    i = h;
    b = g;
   }
  }
 } else {
  i = a + -8 | 0;
  b = d & -8;
  h = a + -8 | 0;
 } while (0);
 if (h >>> 0 >= j >>> 0) return;
 d = c[j + 4 >> 2] | 0;
 if (!(d & 1)) return;
 if (!(d & 2)) {
  if ((c[1839] | 0) == (j | 0)) {
   j = (c[1836] | 0) + b | 0;
   c[1836] = j;
   c[1839] = i;
   c[i + 4 >> 2] = j | 1;
   if ((i | 0) != (c[1838] | 0)) return;
   c[1838] = 0;
   c[1835] = 0;
   return;
  }
  if ((c[1838] | 0) == (j | 0)) {
   j = (c[1835] | 0) + b | 0;
   c[1835] = j;
   c[1838] = h;
   c[i + 4 >> 2] = j | 1;
   c[h + j >> 2] = j;
   return;
  }
  f = (d & -8) + b | 0;
  do if (d >>> 0 < 256) {
   a = c[j + 8 >> 2] | 0;
   b = c[j + 12 >> 2] | 0;
   if ((b | 0) == (a | 0)) {
    c[1833] = c[1833] & ~(1 << (d >>> 3));
    break;
   } else {
    c[a + 12 >> 2] = b;
    c[b + 8 >> 2] = a;
    break;
   }
  } else {
   g = c[j + 24 >> 2] | 0;
   b = c[j + 12 >> 2] | 0;
   do if ((b | 0) == (j | 0)) {
    b = c[j + 16 + 4 >> 2] | 0;
    if (!b) {
     b = c[j + 16 >> 2] | 0;
     if (!b) {
      a = 0;
      break;
     } else e = j + 16 | 0;
    } else e = j + 16 + 4 | 0;
    while (1) {
     a = b + 20 | 0;
     d = c[a >> 2] | 0;
     if (d | 0) {
      b = d;
      e = a;
      continue;
     }
     a = b + 16 | 0;
     d = c[a >> 2] | 0;
     if (!d) break; else {
      b = d;
      e = a;
     }
    }
    c[e >> 2] = 0;
    a = b;
   } else {
    a = c[j + 8 >> 2] | 0;
    c[a + 12 >> 2] = b;
    c[b + 8 >> 2] = a;
    a = b;
   } while (0);
   if (g | 0) {
    b = c[j + 28 >> 2] | 0;
    if ((c[7636 + (b << 2) >> 2] | 0) == (j | 0)) {
     c[7636 + (b << 2) >> 2] = a;
     if (!a) {
      c[1834] = c[1834] & ~(1 << b);
      break;
     }
    } else {
     c[g + 16 + (((c[g + 16 >> 2] | 0) != (j | 0) & 1) << 2) >> 2] = a;
     if (!a) break;
    }
    c[a + 24 >> 2] = g;
    b = c[j + 16 >> 2] | 0;
    if (b | 0) {
     c[a + 16 >> 2] = b;
     c[b + 24 >> 2] = a;
    }
    b = c[j + 16 + 4 >> 2] | 0;
    if (b | 0) {
     c[a + 20 >> 2] = b;
     c[b + 24 >> 2] = a;
    }
   }
  } while (0);
  c[i + 4 >> 2] = f | 1;
  c[h + f >> 2] = f;
  if ((i | 0) == (c[1838] | 0)) {
   c[1835] = f;
   return;
  }
 } else {
  c[j + 4 >> 2] = d & -2;
  c[i + 4 >> 2] = b | 1;
  c[h + b >> 2] = b;
  f = b;
 }
 d = f >>> 3;
 if (f >>> 0 < 256) {
  b = c[1833] | 0;
  if (!(b & 1 << d)) {
   c[1833] = b | 1 << d;
   b = 7372 + (d << 1 << 2) | 0;
   a = 7372 + (d << 1 << 2) + 8 | 0;
  } else {
   b = c[7372 + (d << 1 << 2) + 8 >> 2] | 0;
   a = 7372 + (d << 1 << 2) + 8 | 0;
  }
  c[a >> 2] = i;
  c[b + 12 >> 2] = i;
  c[i + 8 >> 2] = b;
  c[i + 12 >> 2] = 7372 + (d << 1 << 2);
  return;
 }
 b = f >>> 8;
 if (!b) b = 0; else if (f >>> 0 > 16777215) b = 31; else {
  j = b << ((b + 1048320 | 0) >>> 16 & 8) << (((b << ((b + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4);
  b = 14 - (((b << ((b + 1048320 | 0) >>> 16 & 8)) + 520192 | 0) >>> 16 & 4 | (b + 1048320 | 0) >>> 16 & 8 | (j + 245760 | 0) >>> 16 & 2) + (j << ((j + 245760 | 0) >>> 16 & 2) >>> 15) | 0;
  b = f >>> (b + 7 | 0) & 1 | b << 1;
 }
 e = 7636 + (b << 2) | 0;
 c[i + 28 >> 2] = b;
 c[i + 20 >> 2] = 0;
 c[i + 16 >> 2] = 0;
 a = c[1834] | 0;
 d = 1 << b;
 do if (!(a & d)) {
  c[1834] = a | d;
  c[e >> 2] = i;
  c[i + 24 >> 2] = e;
  c[i + 12 >> 2] = i;
  c[i + 8 >> 2] = i;
 } else {
  a = f << ((b | 0) == 31 ? 0 : 25 - (b >>> 1) | 0);
  d = c[e >> 2] | 0;
  while (1) {
   if ((c[d + 4 >> 2] & -8 | 0) == (f | 0)) {
    b = 73;
    break;
   }
   e = d + 16 + (a >>> 31 << 2) | 0;
   b = c[e >> 2] | 0;
   if (!b) {
    b = 72;
    break;
   } else {
    a = a << 1;
    d = b;
   }
  }
  if ((b | 0) == 72) {
   c[e >> 2] = i;
   c[i + 24 >> 2] = d;
   c[i + 12 >> 2] = i;
   c[i + 8 >> 2] = i;
   break;
  } else if ((b | 0) == 73) {
   h = d + 8 | 0;
   j = c[h >> 2] | 0;
   c[j + 12 >> 2] = i;
   c[h >> 2] = i;
   c[i + 8 >> 2] = j;
   c[i + 12 >> 2] = d;
   c[i + 24 >> 2] = 0;
   break;
  }
 } while (0);
 j = (c[1841] | 0) + -1 | 0;
 c[1841] = j;
 if (!j) b = 7788; else return;
 while (1) {
  b = c[b >> 2] | 0;
  if (!b) break; else b = b + 8 | 0;
 }
 c[1841] = -1;
 return;
}
function Ka(a, b) {
 a = a | 0;
 b = b | 0;
 var d = 0, e = 0, f = 0, g = 0;
 d = c[a + 4 >> 2] | 0;
 f = c[a + 12 >> 2] | 0;
 e = c[a + 16 >> 2] | 0;
 a = c[a + 20 >> 2] | 0;
 g = c[b + 4 >> 2] | 0;
 c[f >> 2] = c[b >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 12 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 8 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 20 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 16 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 28 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 24 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 36 >> 2] | 0;
 c[f >> 2] = c[b + 32 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 44 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 40 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 52 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 48 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 60 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 56 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 68 >> 2] | 0;
 c[f >> 2] = c[b + 64 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 76 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 72 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 84 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 80 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 92 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 88 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 100 >> 2] | 0;
 c[f >> 2] = c[b + 96 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 108 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 104 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 116 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 112 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 124 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 120 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 132 >> 2] | 0;
 c[f >> 2] = c[b + 128 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 140 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 136 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 148 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 144 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 156 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 152 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 164 >> 2] | 0;
 c[f >> 2] = c[b + 160 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 172 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 168 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 180 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 176 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 188 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 184 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 196 >> 2] | 0;
 c[f >> 2] = c[b + 192 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 204 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 200 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 212 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 208 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 220 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 216 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = f + (d << 2 << 2) + (d << 2 << 2) | 0;
 g = c[b + 228 >> 2] | 0;
 c[f >> 2] = c[b + 224 >> 2];
 c[f + 4 >> 2] = g;
 g = c[b + 236 >> 2] | 0;
 c[f + 8 >> 2] = c[b + 232 >> 2];
 c[f + 12 >> 2] = g;
 g = c[b + 244 >> 2] | 0;
 c[f + (d << 2 << 2) >> 2] = c[b + 240 >> 2];
 c[f + (d << 2 << 2) + 4 >> 2] = g;
 g = c[b + 252 >> 2] | 0;
 c[f + (d << 2 << 2) + 8 >> 2] = c[b + 248 >> 2];
 c[f + (d << 2 << 2) + 12 >> 2] = g;
 f = c[b + 260 >> 2] | 0;
 c[e >> 2] = c[b + 256 >> 2];
 c[e + 4 >> 2] = f;
 f = c[b + 268 >> 2] | 0;
 c[e + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 264 >> 2];
 c[e + ((d << 1 & 2147483646) << 2) + 4 >> 2] = f;
 e = e + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 f = c[b + 276 >> 2] | 0;
 c[e >> 2] = c[b + 272 >> 2];
 c[e + 4 >> 2] = f;
 f = c[b + 284 >> 2] | 0;
 c[e + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 280 >> 2];
 c[e + ((d << 1 & 2147483646) << 2) + 4 >> 2] = f;
 e = e + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 f = c[b + 292 >> 2] | 0;
 c[e >> 2] = c[b + 288 >> 2];
 c[e + 4 >> 2] = f;
 f = c[b + 300 >> 2] | 0;
 c[e + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 296 >> 2];
 c[e + ((d << 1 & 2147483646) << 2) + 4 >> 2] = f;
 e = e + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 f = c[b + 308 >> 2] | 0;
 c[e >> 2] = c[b + 304 >> 2];
 c[e + 4 >> 2] = f;
 f = c[b + 316 >> 2] | 0;
 c[e + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 312 >> 2];
 c[e + ((d << 1 & 2147483646) << 2) + 4 >> 2] = f;
 e = c[b + 324 >> 2] | 0;
 c[a >> 2] = c[b + 320 >> 2];
 c[a + 4 >> 2] = e;
 e = c[b + 332 >> 2] | 0;
 c[a + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 328 >> 2];
 c[a + ((d << 1 & 2147483646) << 2) + 4 >> 2] = e;
 a = a + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 e = c[b + 340 >> 2] | 0;
 c[a >> 2] = c[b + 336 >> 2];
 c[a + 4 >> 2] = e;
 e = c[b + 348 >> 2] | 0;
 c[a + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 344 >> 2];
 c[a + ((d << 1 & 2147483646) << 2) + 4 >> 2] = e;
 a = a + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 e = c[b + 356 >> 2] | 0;
 c[a >> 2] = c[b + 352 >> 2];
 c[a + 4 >> 2] = e;
 e = c[b + 364 >> 2] | 0;
 c[a + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 360 >> 2];
 c[a + ((d << 1 & 2147483646) << 2) + 4 >> 2] = e;
 a = a + ((d << 1 & 2147483646) << 2) + ((d << 1 & 2147483646) << 2) | 0;
 e = c[b + 372 >> 2] | 0;
 c[a >> 2] = c[b + 368 >> 2];
 c[a + 4 >> 2] = e;
 e = c[b + 380 >> 2] | 0;
 c[a + ((d << 1 & 2147483646) << 2) >> 2] = c[b + 376 >> 2];
 c[a + ((d << 1 & 2147483646) << 2) + 4 >> 2] = e;
 return;
}

function ra(a, b, e, f) {
 a = a | 0;
 b = b | 0;
 e = e | 0;
 f = f | 0;
 var g = 0, h = 0, i = 0, j = 0, k = 0, l = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0, B = 0, C = 0, D = 0, E = 0, F = 0, G = 0;
 h = d[4828 + b >> 0] | 0;
 s = d[4880 + b >> 0] | 0;
 b = c[8 + (s * 12 | 0) >> 2] << h;
 g = c[8 + (s * 12 | 0) + 4 >> 2] << h;
 h = c[8 + (s * 12 | 0) + 8 >> 2] << h;
 if (!e) c[a >> 2] = N(c[a >> 2] | 0, b) | 0;
 do if (!(f & 65436)) {
  if (f & 98 | 0) {
   s = N(c[a + 4 >> 2] | 0, g) | 0;
   m = N(c[a + 20 >> 2] | 0, b) | 0;
   o = N(c[a + 24 >> 2] | 0, g) | 0;
   n = c[a >> 2] | 0;
   p = m + 32 + n + ((o >> 1) + s) >> 6;
   c[a >> 2] = p;
   q = n - m + 32 + ((s >> 1) - o) >> 6;
   c[a + 4 >> 2] = q;
   r = n - m + 32 - ((s >> 1) - o) >> 6;
   c[a + 8 >> 2] = r;
   s = m + 32 + n - ((o >> 1) + s) >> 6;
   c[a + 12 >> 2] = s;
   c[a + 48 >> 2] = p;
   c[a + 32 >> 2] = p;
   c[a + 16 >> 2] = p;
   c[a + 52 >> 2] = q;
   c[a + 36 >> 2] = q;
   c[a + 20 >> 2] = q;
   c[a + 56 >> 2] = r;
   c[a + 40 >> 2] = r;
   c[a + 24 >> 2] = r;
   c[a + 60 >> 2] = s;
   c[a + 44 >> 2] = s;
   c[a + 28 >> 2] = s;
   if ((p + 512 | q + 512 | r + 512 | s + 512) >>> 0 > 1023) b = 1; else break;
   return b | 0;
  }
  b = (c[a >> 2] | 0) + 32 >> 6;
  if ((b + 512 | 0) >>> 0 > 1023) {
   a = 1;
   return a | 0;
  } else {
   c[a + 60 >> 2] = b;
   c[a + 56 >> 2] = b;
   c[a + 52 >> 2] = b;
   c[a + 48 >> 2] = b;
   c[a + 44 >> 2] = b;
   c[a + 40 >> 2] = b;
   c[a + 36 >> 2] = b;
   c[a + 32 >> 2] = b;
   c[a + 28 >> 2] = b;
   c[a + 24 >> 2] = b;
   c[a + 20 >> 2] = b;
   c[a + 16 >> 2] = b;
   c[a + 12 >> 2] = b;
   c[a + 8 >> 2] = b;
   c[a + 4 >> 2] = b;
   c[a >> 2] = b;
   break;
  }
 } else {
  w = N(c[a + 4 >> 2] | 0, g) | 0;
  F = N(c[a + 56 >> 2] | 0, g) | 0;
  G = N(c[a + 60 >> 2] | 0, h) | 0;
  A = N(c[a + 8 >> 2] | 0, g) | 0;
  y = N(c[a + 20 >> 2] | 0, b) | 0;
  C = N(c[a + 16 >> 2] | 0, h) | 0;
  u = N(c[a + 32 >> 2] | 0, g) | 0;
  e = N(c[a + 12 >> 2] | 0, b) | 0;
  x = N(c[a + 24 >> 2] | 0, g) | 0;
  B = N(c[a + 28 >> 2] | 0, g) | 0;
  D = N(c[a + 48 >> 2] | 0, h) | 0;
  E = N(c[a + 36 >> 2] | 0, g) | 0;
  h = N(c[a + 40 >> 2] | 0, h) | 0;
  t = N(c[a + 44 >> 2] | 0, b) | 0;
  v = N(c[a + 52 >> 2] | 0, g) | 0;
  z = c[a >> 2] | 0;
  i = z - y + ((w >> 1) - x) | 0;
  c[a + 4 >> 2] = i;
  m = z - y - ((w >> 1) - x) | 0;
  c[a + 8 >> 2] = m;
  q = z + y - ((x >> 1) + w) | 0;
  c[a + 12 >> 2] = q;
  j = (C >> 1) - D + (A - B) | 0;
  c[a + 20 >> 2] = j;
  n = A - B - ((C >> 1) - D) | 0;
  c[a + 24 >> 2] = n;
  r = B + A - ((D >> 1) + C) | 0;
  c[a + 28 >> 2] = r;
  k = (u >> 1) - v + (e - t) | 0;
  c[a + 36 >> 2] = k;
  o = e - t - ((u >> 1) - v) | 0;
  c[a + 40 >> 2] = o;
  s = t + e - ((v >> 1) + u) | 0;
  c[a + 44 >> 2] = s;
  f = (h >> 1) - G + (E - F) | 0;
  c[a + 52 >> 2] = f;
  l = E - F - ((h >> 1) - G) | 0;
  c[a + 56 >> 2] = l;
  p = F + E - ((G >> 1) + h) | 0;
  c[a + 60 >> 2] = p;
  b = ((D >> 1) + C + (B + A) >> 1) - ((G >> 1) + h + (F + E)) | 0;
  g = ((G >> 1) + h + (F + E) >> 1) + ((D >> 1) + C + (B + A)) | 0;
  h = z + y + ((x >> 1) + w) + 32 + ((v >> 1) + u + (t + e)) | 0;
  c[a >> 2] = g + h >> 6;
  e = z + y + ((x >> 1) + w) - ((v >> 1) + u + (t + e)) + 32 | 0;
  c[a + 16 >> 2] = b + e >> 6;
  c[a + 32 >> 2] = e - b >> 6;
  c[a + 48 >> 2] = h - g >> 6;
  if (((g + h >> 6) + 512 | (b + e >> 6) + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  if (((h - g >> 6) + 512 | (e - b >> 6) + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  F = (f >> 1) + j + (i + 32 + k) >> 6;
  c[a + 4 >> 2] = F;
  G = (j >> 1) - f + (i - k + 32) >> 6;
  c[a + 20 >> 2] = G;
  g = i - k + 32 - ((j >> 1) - f) >> 6;
  c[a + 36 >> 2] = g;
  b = i + 32 + k - ((f >> 1) + j) >> 6;
  c[a + 52 >> 2] = b;
  if ((F + 512 | G + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  if ((b + 512 | g + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  F = (l >> 1) + n + (m + 32 + o) >> 6;
  c[a + 8 >> 2] = F;
  G = (n >> 1) - l + (m - o + 32) >> 6;
  c[a + 24 >> 2] = G;
  g = m - o + 32 - ((n >> 1) - l) >> 6;
  c[a + 40 >> 2] = g;
  b = m + 32 + o - ((l >> 1) + n) >> 6;
  c[a + 56 >> 2] = b;
  if ((F + 512 | G + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  if ((b + 512 | g + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  F = (p >> 1) + r + (q + 32 + s) >> 6;
  c[a + 12 >> 2] = F;
  G = (r >> 1) - p + (q - s + 32) >> 6;
  c[a + 28 >> 2] = G;
  g = q - s + 32 - ((r >> 1) - p) >> 6;
  c[a + 44 >> 2] = g;
  b = q + 32 + s - ((p >> 1) + r) >> 6;
  c[a + 60 >> 2] = b;
  if ((F + 512 | G + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
  if ((b + 512 | g + 512) >>> 0 > 1023) {
   G = 1;
   return G | 0;
  }
 } while (0);
 G = 0;
 return G | 0;
}

function va(a, b) {
 a = a | 0;
 b = b | 0;
 var e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0;
 h = c[a + 4 >> 2] | 0;
 k = c[a + 12 >> 2] << 3;
 j = c[a + 16 >> 2] | 0;
 if ((k - j | 0) > 31) {
  f = c[a + 8 >> 2] | 0;
  e = (d[h + 1 >> 0] | 0) << 16 | (d[h >> 0] | 0) << 24 | (d[h + 2 >> 0] | 0) << 8 | (d[h + 3 >> 0] | 0);
  if (!f) h = 7; else {
   e = (d[h + 4 >> 0] | 0) >>> (8 - f | 0) | e << f;
   h = 7;
  }
 } else if ((k - j | 0) > 0) {
  f = c[a + 8 >> 2] | 0;
  e = (d[h >> 0] | 0) << f + 24;
  if ((k - j + -8 + f | 0) > 0) {
   i = k - j + -8 + f | 0;
   g = f + 24 | 0;
   f = h;
   while (1) {
    f = f + 1 | 0;
    g = g + -8 | 0;
    e = (d[f >> 0] | 0) << g | e;
    if ((i | 0) <= 8) {
     h = 7;
     break;
    } else i = i + -8 | 0;
   }
  } else h = 7;
 } else {
  e = 0;
  h = 21;
 }
 do if ((h | 0) == 7) {
  if ((e | 0) < 0) {
   c[a + 16 >> 2] = j + 1;
   c[a + 8 >> 2] = j + 1 & 7;
   if ((j + 1 | 0) >>> 0 <= k >>> 0) c[a + 4 >> 2] = (c[a >> 2] | 0) + ((j + 1 | 0) >>> 3);
   c[b >> 2] = 0;
   b = 0;
   return b | 0;
  }
  if (e >>> 0 > 1073741823) {
   c[a + 16 >> 2] = j + 3;
   c[a + 8 >> 2] = j + 3 & 7;
   if ((j + 3 | 0) >>> 0 > k >>> 0) {
    b = 1;
    return b | 0;
   }
   c[a + 4 >> 2] = (c[a >> 2] | 0) + ((j + 3 | 0) >>> 3);
   c[b >> 2] = (e >>> 29 & 1) + 1;
   b = 0;
   return b | 0;
  }
  if (e >>> 0 > 536870911) {
   c[a + 16 >> 2] = j + 5;
   c[a + 8 >> 2] = j + 5 & 7;
   if ((j + 5 | 0) >>> 0 > k >>> 0) {
    b = 1;
    return b | 0;
   }
   c[a + 4 >> 2] = (c[a >> 2] | 0) + ((j + 5 | 0) >>> 3);
   c[b >> 2] = (e >>> 27 & 3) + 3;
   b = 0;
   return b | 0;
  }
  if (e >>> 0 <= 268435455) if (!(e & 134217728)) {
   h = 21;
   break;
  } else {
   f = 0;
   g = 4;
   break;
  }
  c[a + 16 >> 2] = j + 7;
  c[a + 8 >> 2] = j + 7 & 7;
  if ((j + 7 | 0) >>> 0 > k >>> 0) {
   b = 1;
   return b | 0;
  }
  c[a + 4 >> 2] = (c[a >> 2] | 0) + ((j + 7 | 0) >>> 3);
  c[b >> 2] = (e >>> 25 & 7) + 7;
  b = 0;
  return b | 0;
 } while (0);
 if ((h | 0) == 21) {
  f = 134217728;
  g = 0;
  while (1) {
   h = g + 1 | 0;
   f = f >>> 1;
   if (!((f | 0) != 0 & (f & e | 0) == 0)) break; else g = h;
  }
  e = g + 5 | 0;
  if ((e | 0) == 32) {
   c[b >> 2] = 0;
   e = (c[a + 16 >> 2] | 0) + 32 | 0;
   c[a + 16 >> 2] = e;
   c[a + 8 >> 2] = e & 7;
   if (e >>> 0 <= c[a + 12 >> 2] << 3 >>> 0) c[a + 4 >> 2] = (c[a >> 2] | 0) + (e >>> 3);
   if ((ua(a, 1) | 0) != 1) {
    b = 1;
    return b | 0;
   }
   h = c[a + 4 >> 2] | 0;
   j = c[a + 12 >> 2] << 3;
   k = c[a + 16 >> 2] | 0;
   if ((j - k | 0) > 31) {
    f = c[a + 8 >> 2] | 0;
    e = (d[h + 1 >> 0] | 0) << 16 | (d[h >> 0] | 0) << 24 | (d[h + 2 >> 0] | 0) << 8 | (d[h + 3 >> 0] | 0);
    if (f) e = (d[h + 4 >> 0] | 0) >>> (8 - f | 0) | e << f;
   } else if ((j - k | 0) > 0) {
    f = c[a + 8 >> 2] | 0;
    e = (d[h >> 0] | 0) << f + 24;
    if ((j - k + -8 + f | 0) > 0) {
     i = j - k + -8 + f | 0;
     g = f + 24 | 0;
     f = h;
     while (1) {
      f = f + 1 | 0;
      g = g + -8 | 0;
      e = (d[f >> 0] | 0) << g | e;
      if ((i | 0) <= 8) break; else i = i + -8 | 0;
     }
    }
   } else e = 0;
   c[a + 16 >> 2] = k + 32;
   c[a + 8 >> 2] = k + 32 & 7;
   if ((k + 32 | 0) >>> 0 > j >>> 0) {
    b = 1;
    return b | 0;
   }
   c[a + 4 >> 2] = (c[a >> 2] | 0) + ((k + 32 | 0) >>> 3);
   switch (e | 0) {
   case 0:
    {
     c[b >> 2] = -1;
     b = 0;
     return b | 0;
    }
   case 1:
    {
     c[b >> 2] = -1;
     b = 1;
     return b | 0;
    }
   default:
    {
     b = 1;
     return b | 0;
    }
   }
  } else {
   f = h;
   g = e;
  }
 }
 e = f + 5 + j | 0;
 c[a + 16 >> 2] = e;
 c[a + 8 >> 2] = e & 7;
 if (e >>> 0 <= k >>> 0) c[a + 4 >> 2] = (c[a >> 2] | 0) + (e >>> 3);
 e = ua(a, g) | 0;
 if ((e | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b >> 2] = (1 << g) + -1 + e;
 b = 0;
 return b | 0;
}

function La(b, e, f, g) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, l = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0;
 if (e >>> 0 < 4) {
  r = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
  q = 4;
  while (1) {
   e = b + -2 | 0;
   l = b + -1 | 0;
   j = b + 1 | 0;
   m = a[j >> 0] | 0;
   n = d[l >> 0] | 0;
   o = d[b >> 0] | 0;
   if (((n - o | 0) < 0 ? 0 - (n - o) | 0 : n - o | 0) >>> 0 < (c[f + 4 >> 2] | 0) >>> 0) {
    p = d[e >> 0] | 0;
    h = c[f + 8 >> 2] | 0;
    if (((p - n | 0) < 0 ? 0 - (p - n) | 0 : p - n | 0) >>> 0 < h >>> 0) if ((((m & 255) - o | 0) < 0 ? 0 - ((m & 255) - o) | 0 : (m & 255) - o | 0) >>> 0 < h >>> 0) {
     k = a[b + 2 >> 0] | 0;
     i = d[b + -3 >> 0] | 0;
     if (((i - n | 0) < 0 ? 0 - (i - n) | 0 : i - n | 0) >>> 0 < h >>> 0) {
      a[e >> 0] = ((((n + 1 + o | 0) >>> 1) - (p << 1) + i >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((n + 1 + o | 0) >>> 1) - (p << 1) + i >> 1 | 0) > (r | 0) ? r : ((n + 1 + o | 0) >>> 1) - (p << 1) + i >> 1) + p;
      e = r + 1 | 0;
      h = c[f + 8 >> 2] | 0;
     } else e = r;
     if ((((k & 255) - o | 0) < 0 ? 0 - ((k & 255) - o) | 0 : (k & 255) - o | 0) >>> 0 < h >>> 0) {
      a[j >> 0] = ((((n + 1 + o | 0) >>> 1) - ((m & 255) << 1) + (k & 255) >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((n + 1 + o | 0) >>> 1) - ((m & 255) << 1) + (k & 255) >> 1 | 0) > (r | 0) ? r : ((n + 1 + o | 0) >>> 1) - ((m & 255) << 1) + (k & 255) >> 1) + (m & 255);
      e = e + 1 | 0;
     }
     s = 0 - e | 0;
     s = (4 - (m & 255) + (o - n << 2) + p >> 3 | 0) < (s | 0) ? s : (4 - (m & 255) + (o - n << 2) + p >> 3 | 0) > (e | 0) ? e : 4 - (m & 255) + (o - n << 2) + p >> 3;
     t = a[6162 + (o - s) >> 0] | 0;
     a[l >> 0] = a[6162 + (s + n) >> 0] | 0;
     a[b >> 0] = t;
    }
   }
   q = q + -1 | 0;
   if (!q) break; else b = b + g | 0;
  }
  return;
 }
 t = 4;
 while (1) {
  m = b + -2 | 0;
  k = b + -1 | 0;
  p = b + 1 | 0;
  r = a[p >> 0] | 0;
  q = d[k >> 0] | 0;
  h = d[b >> 0] | 0;
  i = (q - h | 0) < 0 ? 0 - (q - h) | 0 : q - h | 0;
  l = c[f + 4 >> 2] | 0;
  if (i >>> 0 < l >>> 0) {
   j = d[m >> 0] | 0;
   n = c[f + 8 >> 2] | 0;
   if (((j - q | 0) < 0 ? 0 - (j - q) | 0 : j - q | 0) >>> 0 < n >>> 0) if ((((r & 255) - h | 0) < 0 ? 0 - ((r & 255) - h) | 0 : (r & 255) - h | 0) >>> 0 < n >>> 0) {
    o = b + -3 | 0;
    e = b + 2 | 0;
    s = a[e >> 0] | 0;
    if (i >>> 0 < ((l >>> 2) + 2 | 0) >>> 0) {
     i = d[o >> 0] | 0;
     if (((i - q | 0) < 0 ? 0 - (i - q) | 0 : i - q | 0) >>> 0 < n >>> 0) {
      a[k >> 0] = ((r & 255) + 4 + (h + q + j << 1) + i | 0) >>> 3;
      a[m >> 0] = (h + q + j + 2 + i | 0) >>> 2;
      k = o;
      l = 3;
      m = d[b + -4 >> 0] | 0;
      n = h + q + j + 4 | 0;
      i = i * 3 | 0;
     } else {
      l = 2;
      m = j;
      n = q + 2 | 0;
      i = r & 255;
     }
     a[k >> 0] = (n + i + (m << 1) | 0) >>> l;
     if ((((s & 255) - h | 0) < 0 ? 0 - ((s & 255) - h) | 0 : (s & 255) - h | 0) >>> 0 < (c[f + 8 >> 2] | 0) >>> 0) {
      a[b >> 0] = ((h + q + (r & 255) << 1) + 4 + j + (s & 255) | 0) >>> 3;
      a[p >> 0] = (h + q + (r & 255) + 2 + (s & 255) | 0) >>> 2;
      k = 3;
      l = 4;
      j = h + q + (r & 255) | 0;
      i = d[b + 3 >> 0] | 0;
      h = (s & 255) * 3 | 0;
     } else {
      k = 2;
      l = 2;
      i = r & 255;
      e = b;
     }
    } else {
     a[k >> 0] = (q + 2 + (r & 255) + (j << 1) | 0) >>> 2;
     k = 2;
     l = 2;
     i = r & 255;
     e = b;
    }
    a[e >> 0] = ((i << 1) + h + j + l | 0) >>> k;
   }
  }
  t = t + -1 | 0;
  if (!t) break; else b = b + g | 0;
 }
 return;
}

function Ja(a, b) {
 a = a | 0;
 b = b | 0;
 var d = 0, e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0;
 s = l;
 l = l + 16 | 0;
 i = 7;
 do {
  if (i >>> 0 < b >>> 0) {
   q = 0 - i | 0;
   h = i;
   do {
    d = a + (h * 40 | 0) | 0;
    r = c[d >> 2] | 0;
    n = c[d + 4 >> 2] | 0;
    j = c[a + (h * 40 | 0) + 8 >> 2] | 0;
    p = a + (h * 40 | 0) + 12 | 0;
    o = c[p >> 2] | 0;
    p = c[p + 4 >> 2] | 0;
    k = c[a + (h * 40 | 0) + 20 >> 2] | 0;
    m = c[a + (h * 40 | 0) + 24 >> 2] | 0;
    g = a + (h * 40 | 0) + 28 | 0;
    c[s >> 2] = c[g >> 2];
    c[s + 4 >> 2] = c[g + 4 >> 2];
    c[s + 8 >> 2] = c[g + 8 >> 2];
    a : do if (h >>> 0 < i >>> 0) f = h; else {
     b : do if (!k) if (!m) d = h; else {
      d = h;
      while (1) {
       e = a + (d * 40 | 0) | 0;
       if (c[e + (q * 40 | 0) + 20 >> 2] | 0) break b;
       if (c[e + (q * 40 | 0) + 24 >> 2] | 0) break b;
       d = d - i | 0;
       f = a + (d * 40 | 0) | 0;
       g = e + 40 | 0;
       do {
        c[e >> 2] = c[f >> 2];
        e = e + 4 | 0;
        f = f + 4 | 0;
       } while ((e | 0) < (g | 0));
       if (d >>> 0 < i >>> 0) {
        f = d;
        d = a + (d * 40 | 0) | 0;
        break a;
       }
      }
     } else {
      if ((k + -1 | 0) >>> 0 < 2) {
       d = h;
       while (1) {
        e = a + (d * 40 | 0) | 0;
        f = c[e + (q * 40 | 0) + 20 >> 2] | 0;
        do if (f | 0) {
         if ((f + -1 | k + -1) >>> 0 >= 2) if ((f + -1 | 0) >>> 0 < 2) break b; else break;
         f = c[e + (q * 40 | 0) + 8 >> 2] | 0;
         if ((f | 0) > (j | 0)) break b;
         if ((f | 0) >= (j | 0)) {
          f = d;
          d = e;
          break a;
         }
        } while (0);
        d = d - i | 0;
        f = a + (d * 40 | 0) | 0;
        g = e + 40 | 0;
        do {
         c[e >> 2] = c[f >> 2];
         e = e + 4 | 0;
         f = f + 4 | 0;
        } while ((e | 0) < (g | 0));
        if (d >>> 0 < i >>> 0) {
         f = d;
         d = a + (d * 40 | 0) | 0;
         break a;
        }
       }
      } else d = h;
      while (1) {
       e = a + (d * 40 | 0) | 0;
       f = c[e + (q * 40 | 0) + 20 >> 2] | 0;
       do if (f | 0) if ((f + -1 | k + -1) >>> 0 < 2) {
        f = c[e + (q * 40 | 0) + 8 >> 2] | 0;
        if ((f | 0) > (j | 0)) break b;
        if ((f | 0) < (j | 0)) break; else {
         f = d;
         d = e;
         break a;
        }
       } else {
        if ((f + -1 | 0) >>> 0 < 2) break b;
        if ((c[e + (q * 40 | 0) + 8 >> 2] | 0) > (j | 0)) break; else break b;
       } while (0);
       d = d - i | 0;
       f = a + (d * 40 | 0) | 0;
       g = e + 40 | 0;
       do {
        c[e >> 2] = c[f >> 2];
        e = e + 4 | 0;
        f = f + 4 | 0;
       } while ((e | 0) < (g | 0));
       if (d >>> 0 < i >>> 0) {
        f = d;
        d = a + (d * 40 | 0) | 0;
        break a;
       }
      }
     } while (0);
     f = d;
     d = a + (d * 40 | 0) | 0;
    } while (0);
    g = d;
    c[g >> 2] = r;
    c[g + 4 >> 2] = n;
    c[a + (f * 40 | 0) + 8 >> 2] = j;
    r = a + (f * 40 | 0) + 12 | 0;
    c[r >> 2] = o;
    c[r + 4 >> 2] = p;
    c[a + (f * 40 | 0) + 20 >> 2] = k;
    c[a + (f * 40 | 0) + 24 >> 2] = m;
    r = a + (f * 40 | 0) + 28 | 0;
    c[r >> 2] = c[s >> 2];
    c[r + 4 >> 2] = c[s + 4 >> 2];
    c[r + 8 >> 2] = c[s + 8 >> 2];
    h = h + 1 | 0;
   } while ((h | 0) != (b | 0));
  }
  i = i >>> 1;
 } while ((i | 0) != 0);
 l = s;
 return;
}

function Ea(b, e, f, g, h, i, j, k, m) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 m = m | 0;
 var n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0;
 u = l;
 l = l + 1792 | 0;
 if ((f | 0) < 0) n = 5; else if ((g | 0) < 0 | (f + 5 + j | 0) >>> 0 > h >>> 0) n = 5; else if ((g + 5 + k | 0) >>> 0 > i >>> 0) n = 5; else {
  i = h;
  h = k + 5 | 0;
 }
 if ((n | 0) == 5) {
  ya(b, u + 1344 | 0, f, g, h, i, j + 5 | 0, k + 5 | 0, j + 5 | 0);
  b = u + 1344 | 0;
  f = 0;
  g = 0;
  i = j + 5 | 0;
  h = k + 5 | 0;
 }
 if (h | 0) {
  t = i - j | 0;
  if (j >>> 2 | 0) {
   r = b + ((N(g, i) | 0) + f) + 5 | 0;
   s = u;
   while (1) {
    b = d[r + -5 >> 0] | 0;
    i = d[r + -4 >> 0] | 0;
    f = d[r + -3 >> 0] | 0;
    g = d[r + -2 >> 0] | 0;
    n = d[r + -1 >> 0] | 0;
    o = j >>> 2;
    p = s;
    q = r;
    while (1) {
     v = n + i | 0;
     w = i;
     i = d[q >> 0] | 0;
     c[p >> 2] = b - v + ((g + f | 0) * 20 | 0) - (v << 2) + i;
     v = f + i | 0;
     b = f;
     f = d[q + 1 >> 0] | 0;
     c[p + 4 >> 2] = ((n + g | 0) * 20 | 0) + w - v - (v << 2) + f;
     v = g + f | 0;
     w = g;
     g = d[q + 2 >> 0] | 0;
     c[p + 8 >> 2] = ((n + i | 0) * 20 | 0) + b - v - (v << 2) + g;
     v = n + g | 0;
     b = d[q + 3 >> 0] | 0;
     c[p + 12 >> 2] = ((f + i | 0) * 20 | 0) + w - v - (v << 2) + b;
     o = o + -1 | 0;
     if (!o) break; else {
      w = n;
      n = b;
      p = p + 16 | 0;
      q = q + 4 | 0;
      b = w;
     }
    }
    h = h + -1 | 0;
    if (!h) break; else {
     r = r + (j & -4) + t | 0;
     s = s + ((j & -4) << 2) | 0;
    }
   }
  }
 }
 if (!(k >>> 2)) {
  l = u;
  return;
 }
 b = u + (j << 2) + ((N(m + 2 | 0, j) | 0) << 2) | 0;
 i = u + (j << 2) + (j * 5 << 2) | 0;
 f = u + (j << 2) | 0;
 q = k >>> 2;
 while (1) {
  if (j) {
   g = b;
   h = i;
   n = f;
   o = j;
   p = e;
   while (1) {
    w = c[h + (0 - j << 1 << 2) >> 2] | 0;
    t = c[h + (0 - j << 2) >> 2] | 0;
    v = c[h + (j << 2) >> 2] | 0;
    s = c[h >> 2] | 0;
    k = c[n + (j << 1 << 2) >> 2] | 0;
    a[p + 48 >> 0] = ((d[6162 + ((c[h + (j << 1 << 2) >> 2] | 0) + 512 - (v + w) - (v + w << 2) + k + ((s + t | 0) * 20 | 0) >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[g + (j << 1 << 2) >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    m = c[n + (j << 2) >> 2] | 0;
    a[p + 32 >> 0] = ((d[6162 + (v + 512 + ((t + w | 0) * 20 | 0) - (k + s) - (k + s << 2) + m >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[g + (j << 2) >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    v = c[n >> 2] | 0;
    a[p + 16 >> 0] = ((d[6162 + (s + 512 + ((k + w | 0) * 20 | 0) - (m + t) - (m + t << 2) + v >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[g >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    a[p >> 0] = ((d[6162 + (t + 512 + ((m + k | 0) * 20 | 0) - (v + w) - (v + w << 2) + (c[n + (0 - j << 2) >> 2] | 0) >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[g + (0 - j << 2) >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    o = o + -1 | 0;
    if (!o) break; else {
     g = g + 4 | 0;
     h = h + 4 | 0;
     n = n + 4 | 0;
     p = p + 1 | 0;
    }
   }
   b = b + (j << 2) | 0;
   i = i + (j << 2) | 0;
   f = f + (j << 2) | 0;
   e = e + j | 0;
  }
  q = q + -1 | 0;
  if (!q) break; else {
   b = b + (j * 3 << 2) | 0;
   i = i + (j * 3 << 2) | 0;
   f = f + (j * 3 << 2) | 0;
   e = e + (64 - j) | 0;
  }
 }
 l = u;
 return;
}

function Da(b, c, e, f, g, h, i, j, k) {
 b = b | 0;
 c = c | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 var m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0;
 u = l;
 l = l + 448 | 0;
 if ((e | 0) < 0) m = 4; else if ((f | 0) < 0 | (e + 5 + i | 0) >>> 0 > g >>> 0) m = 4; else if ((f + 5 + j | 0) >>> 0 > h >>> 0) m = 4; else {
  h = e;
  t = g;
 }
 if ((m | 0) == 4) {
  ya(b, u, e, f, g, h, i + 5 | 0, j + 5 | 0, i + 5 | 0);
  b = u;
  h = 0;
  f = 0;
  t = i + 5 | 0;
 }
 f = b + ((N(f, t) | 0) + h) | 0;
 b = f + t + 2 + (k & 1) | 0;
 if (!j) {
  l = u;
  return;
 }
 s = t - i | 0;
 if (!(i >>> 2)) h = N(j + -1 | 0, 16 - i | 0) | 0; else {
  r = j;
  n = f + (N(t, k >>> 1 & 1 | 2) | 0) + 5 | 0;
  o = c;
  while (1) {
   f = d[n + -5 >> 0] | 0;
   h = d[n + -4 >> 0] | 0;
   e = d[n + -3 >> 0] | 0;
   g = d[n + -2 >> 0] | 0;
   m = d[n + -1 >> 0] | 0;
   k = i >>> 2;
   p = n;
   q = o;
   while (1) {
    v = m + h | 0;
    w = h;
    h = d[p >> 0] | 0;
    a[q >> 0] = a[6162 + (f + 16 - v + ((g + e | 0) * 20 | 0) - (v << 2) + h >> 5) >> 0] | 0;
    v = e + h | 0;
    f = e;
    e = d[p + 1 >> 0] | 0;
    a[q + 1 >> 0] = a[6162 + (w + 16 + ((m + g | 0) * 20 | 0) - v - (v << 2) + e >> 5) >> 0] | 0;
    v = g + e | 0;
    w = g;
    g = d[p + 2 >> 0] | 0;
    a[q + 2 >> 0] = a[6162 + (f + 16 + ((m + h | 0) * 20 | 0) - v - (v << 2) + g >> 5) >> 0] | 0;
    v = m + g | 0;
    f = d[p + 3 >> 0] | 0;
    a[q + 3 >> 0] = a[6162 + (w + 16 + ((e + h | 0) * 20 | 0) - v - (v << 2) + f >> 5) >> 0] | 0;
    k = k + -1 | 0;
    if (!k) break; else {
     w = m;
     m = f;
     p = p + 4 | 0;
     q = q + 4 | 0;
     f = w;
    }
   }
   r = r + -1 | 0;
   if (!r) break; else {
    n = n + (i & -4) + s | 0;
    o = o + (i & -4) + (16 - i) | 0;
   }
  }
  h = (N(16 - i + (i & -4) | 0, j + -1 | 0) | 0) + (i & -4) | 0;
 }
 if (!(j >>> 2)) {
  l = u;
  return;
 }
 o = (t << 2) - i | 0;
 p = 0 - t | 0;
 q = t << 1;
 f = b + (t * 5 | 0) | 0;
 n = j >>> 2;
 h = c + (16 - i + h) + (0 - (j << 4)) | 0;
 while (1) {
  if (i) {
   e = i;
   g = f;
   m = b;
   k = h;
   while (1) {
    w = d[g + (p << 1) >> 0] | 0;
    s = d[g + p >> 0] | 0;
    r = d[g + t >> 0] | 0;
    x = d[g >> 0] | 0;
    j = d[m + q >> 0] | 0;
    c = k + 48 | 0;
    a[c >> 0] = ((d[6162 + ((d[g + q >> 0] | 0) + 16 - (r + w) - (r + w << 2) + j + ((x + s | 0) * 20 | 0) >> 5) >> 0] | 0) + 1 + (d[c >> 0] | 0) | 0) >>> 1;
    c = d[m + t >> 0] | 0;
    v = k + 32 | 0;
    a[v >> 0] = ((d[6162 + (r + 16 + ((s + w | 0) * 20 | 0) - (j + x) - (j + x << 2) + c >> 5) >> 0] | 0) + 1 + (d[v >> 0] | 0) | 0) >>> 1;
    v = d[m >> 0] | 0;
    r = k + 16 | 0;
    a[r >> 0] = ((d[6162 + (x + 16 + ((j + w | 0) * 20 | 0) - (c + s) - (c + s << 2) + v >> 5) >> 0] | 0) + 1 + (d[r >> 0] | 0) | 0) >>> 1;
    a[k >> 0] = ((d[6162 + (s + 16 + ((c + j | 0) * 20 | 0) - (v + w) - (v + w << 2) + (d[m + p >> 0] | 0) >> 5) >> 0] | 0) + 1 + (d[k >> 0] | 0) | 0) >>> 1;
    e = e + -1 | 0;
    if (!e) break; else {
     g = g + 1 | 0;
     m = m + 1 | 0;
     k = k + 1 | 0;
    }
   }
   f = f + i | 0;
   b = b + i | 0;
   h = h + i | 0;
  }
  n = n + -1 | 0;
  if (!n) break; else {
   f = f + o | 0;
   b = b + o | 0;
   h = h + (64 - i) | 0;
  }
 }
 l = u;
 return;
}

function Fa(b, e, f, g, h, i, j, k, m) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 m = m | 0;
 var n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0, z = 0, A = 0;
 u = l;
 l = l + 1792 | 0;
 if ((f | 0) < 0) n = 4; else if ((g | 0) < 0 | (f + 5 + j | 0) >>> 0 > h >>> 0) n = 4; else if ((g + 5 + k | 0) >>> 0 > i >>> 0) n = 4; else i = f;
 if ((n | 0) == 4) {
  ya(b, u + 1344 | 0, f, g, h, i, j + 5 | 0, k + 5 | 0, j + 5 | 0);
  b = u + 1344 | 0;
  i = 0;
  g = 0;
  h = j + 5 | 0;
 }
 g = b + ((N(g, h) | 0) + i) + h | 0;
 if (k >>> 2 | 0) {
  r = h << 2;
  s = 0 - h | 0;
  t = h << 1;
  if (j + 5 | 0) {
   q = g + (h * 5 | 0) | 0;
   b = u + (j + 5 << 2) | 0;
   i = k >>> 2;
   while (1) {
    f = j + 5 | 0;
    n = q;
    o = g;
    p = b;
    while (1) {
     v = d[n + (s << 1) >> 0] | 0;
     x = d[n + s >> 0] | 0;
     w = d[n + h >> 0] | 0;
     A = d[n >> 0] | 0;
     y = d[o + t >> 0] | 0;
     c[p + (j + 5 << 1 << 2) >> 2] = (d[n + t >> 0] | 0) - (w + v) - (w + v << 2) + y + ((A + x | 0) * 20 | 0);
     z = d[o + h >> 0] | 0;
     c[p + (j + 5 << 2) >> 2] = ((x + v | 0) * 20 | 0) + w - (y + A) - (y + A << 2) + z;
     w = d[o >> 0] | 0;
     c[p >> 2] = ((y + v | 0) * 20 | 0) + A - (z + x) - (z + x << 2) + w;
     c[p + (-5 - j << 2) >> 2] = ((z + y | 0) * 20 | 0) + x - (w + v) - (w + v << 2) + (d[o + s >> 0] | 0);
     f = f + -1 | 0;
     if (!f) break; else {
      n = n + 1 | 0;
      o = o + 1 | 0;
      p = p + 4 | 0;
     }
    }
    i = i + -1 | 0;
    if (!i) break; else {
     q = q + r | 0;
     g = g + r | 0;
     b = b + (j + 5 << 2) + ((j + 5 | 0) * 3 << 2) | 0;
    }
   }
  }
 }
 if (!k) {
  l = u;
  return;
 }
 g = u + 8 + (m << 2) | 0;
 b = u + 20 | 0;
 t = k;
 while (1) {
  if (j >>> 2) {
   i = c[b + -20 >> 2] | 0;
   f = c[b + -16 >> 2] | 0;
   h = c[b + -12 >> 2] | 0;
   n = c[b + -8 >> 2] | 0;
   o = c[b + -4 >> 2] | 0;
   p = g;
   q = b;
   r = j >>> 2;
   s = e;
   while (1) {
    A = o + f | 0;
    z = f;
    f = c[q >> 2] | 0;
    a[s >> 0] = ((d[6162 + (i + 512 - A + ((n + h | 0) * 20 | 0) - (A << 2) + f >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[p >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    A = f + h | 0;
    i = h;
    h = c[q + 4 >> 2] | 0;
    a[s + 1 >> 0] = ((d[6162 + (z + 512 + ((o + n | 0) * 20 | 0) - A - (A << 2) + h >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[p + 4 >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    A = h + n | 0;
    z = n;
    n = c[q + 8 >> 2] | 0;
    a[s + 2 >> 0] = ((d[6162 + (i + 512 + ((f + o | 0) * 20 | 0) - A - (A << 2) + n >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[p + 8 >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    A = n + o | 0;
    i = c[q + 12 >> 2] | 0;
    a[s + 3 >> 0] = ((d[6162 + (z + 512 + ((h + f | 0) * 20 | 0) - A - (A << 2) + i >> 10) >> 0] | 0) + 1 + (d[6162 + ((c[p + 12 >> 2] | 0) + 16 >> 5) >> 0] | 0) | 0) >>> 1;
    r = r + -1 | 0;
    if (!r) break; else {
     A = o;
     o = i;
     p = p + 16 | 0;
     q = q + 16 | 0;
     s = s + 4 | 0;
     i = A;
    }
   }
   e = e + (j & -4) | 0;
   g = g + ((j & -4) << 2) | 0;
   b = b + ((j & -4) << 2) | 0;
  }
  t = t + -1 | 0;
  if (!t) break; else {
   e = e + (16 - j) | 0;
   g = g + 20 | 0;
   b = b + 20 | 0;
  }
 }
 l = u;
 return;
}

function Ia(a) {
 a = a | 0;
 var b = 0, d = 0, e = 0, f = 0, g = 0, h = 0, i = 0;
 f = c[a >> 2] | 0;
 if (c[f + 20 >> 2] | 0) {
  c[f + 20 >> 2] = 0;
  if (!(c[f + 24 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 60 >> 2] | 0) {
  c[f + 60 >> 2] = 0;
  if (!(c[f + 64 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 100 >> 2] | 0) {
  c[f + 100 >> 2] = 0;
  if (!(c[f + 104 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 140 >> 2] | 0) {
  c[f + 140 >> 2] = 0;
  if (!(c[f + 144 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 180 >> 2] | 0) {
  c[f + 180 >> 2] = 0;
  if (!(c[f + 184 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 220 >> 2] | 0) {
  c[f + 220 >> 2] = 0;
  if (!(c[f + 224 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 260 >> 2] | 0) {
  c[f + 260 >> 2] = 0;
  if (!(c[f + 264 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 300 >> 2] | 0) {
  c[f + 300 >> 2] = 0;
  if (!(c[f + 304 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 340 >> 2] | 0) {
  c[f + 340 >> 2] = 0;
  if (!(c[f + 344 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 380 >> 2] | 0) {
  c[f + 380 >> 2] = 0;
  if (!(c[f + 384 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 420 >> 2] | 0) {
  c[f + 420 >> 2] = 0;
  if (!(c[f + 424 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 460 >> 2] | 0) {
  c[f + 460 >> 2] = 0;
  if (!(c[f + 464 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 500 >> 2] | 0) {
  c[f + 500 >> 2] = 0;
  if (!(c[f + 504 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 540 >> 2] | 0) {
  c[f + 540 >> 2] = 0;
  if (!(c[f + 544 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 580 >> 2] | 0) {
  c[f + 580 >> 2] = 0;
  if (!(c[f + 584 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[f + 620 >> 2] | 0) {
  c[f + 620 >> 2] = 0;
  if (!(c[f + 624 >> 2] | 0)) c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 if (c[a + 56 >> 2] | 0) {
  g = a + 40 | 0;
  c[g >> 2] = 0;
  g = a + 36 | 0;
  c[g >> 2] = 65535;
  g = a + 48 | 0;
  c[g >> 2] = 0;
  return;
 }
 g = c[a + 28 >> 2] | 0;
 while (1) {
  d = 2147483647;
  e = 0;
  b = 0;
  do {
   if (c[f + (e * 40 | 0) + 24 >> 2] | 0) {
    h = c[f + (e * 40 | 0) + 16 >> 2] | 0;
    i = (h | 0) < (d | 0);
    b = i ? f + (e * 40 | 0) | 0 : b;
    d = i ? h : d;
   }
   e = e + 1 | 0;
  } while (e >>> 0 <= g >>> 0);
  if (!b) break;
  h = c[a + 12 >> 2] | 0;
  i = c[a + 16 >> 2] | 0;
  c[h + (i << 4) >> 2] = c[b >> 2];
  c[h + (i << 4) + 12 >> 2] = c[b + 36 >> 2];
  c[h + (i << 4) + 4 >> 2] = c[b + 28 >> 2];
  c[h + (i << 4) + 8 >> 2] = c[b + 32 >> 2];
  c[a + 16 >> 2] = i + 1;
  c[b + 24 >> 2] = 0;
  if (c[b + 20 >> 2] | 0) continue;
  c[a + 44 >> 2] = (c[a + 44 >> 2] | 0) + -1;
 }
 i = a + 40 | 0;
 c[i >> 2] = 0;
 i = a + 36 | 0;
 c[i >> 2] = 65535;
 i = a + 48 | 0;
 c[i >> 2] = 0;
 return;
}

function Qa(a, b, d) {
 a = a | 0;
 b = b | 0;
 d = d | 0;
 var e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0, l = 0, m = 0;
 l = c[b + 4 >> 2] | 0;
 m = c[b + 8 >> 2] | 0;
 switch (d | 0) {
 case 0:
 case 5:
  {
   e = 3;
   break;
  }
 default:
  if (!(c[a + 3384 >> 2] | 0)) k = 0; else e = 3;
 }
 if ((e | 0) == 3) {
  g = c[a + 1224 >> 2] | 0;
  f = 0;
  do {
   e = c[g + (f << 2) >> 2] | 0;
   if (!e) e = 0; else if ((c[e + 20 >> 2] | 0) >>> 0 > 1) e = c[e >> 2] | 0; else e = 0;
   f = f + 1 | 0;
  } while (f >>> 0 < 16 & (e | 0) == 0);
  k = e;
 }
 i = c[a + 1176 >> 2] | 0;
 a : do if (!i) {
  g = 0;
  e = 0;
  f = 0;
 } else {
  h = c[a + 1212 >> 2] | 0;
  g = 0;
  e = 0;
  f = 0;
  do {
   if (c[h + (f * 216 | 0) + 196 >> 2] | 0) break a;
   f = f + 1 | 0;
   g = g + 1 | 0;
   e = e + ((g | 0) == (l | 0) & 1) | 0;
   g = (g | 0) == (l | 0) ? 0 : g;
  } while (f >>> 0 < i >>> 0);
 } while (0);
 if ((f | 0) == (i | 0)) {
  switch (d | 0) {
  case 2:
  case 7:
   {
    if ((k | 0) == 0 | (c[a + 3384 >> 2] | 0) == 0) e = 16; else e = 17;
    break;
   }
  default:
   if (!k) e = 16; else e = 17;
  }
  if ((e | 0) == 16) pb(c[b >> 2] | 0, -128, N(l * 384 | 0, m) | 0) | 0; else if ((e | 0) == 17) ob(c[b >> 2] | 0, k | 0, N(l * 384 | 0, m) | 0) | 0;
  g = c[a + 1176 >> 2] | 0;
  c[a + 1204 >> 2] = g;
  if (!g) return;
  f = c[a + 1212 >> 2] | 0;
  e = 0;
  do {
   c[f + (e * 216 | 0) + 8 >> 2] = 1;
   e = e + 1 | 0;
  } while ((e | 0) != (g | 0));
  return;
 }
 h = (c[a + 1212 >> 2] | 0) + ((N(e, l) | 0) * 216 | 0) | 0;
 if (g | 0) {
  f = g;
  do {
   f = f + -1 | 0;
   j = h + (f * 216 | 0) | 0;
   Ra(j, b, e, f, d, k);
   c[j + 196 >> 2] = 1;
   c[a + 1204 >> 2] = (c[a + 1204 >> 2] | 0) + 1;
  } while ((f | 0) != 0);
 }
 f = g + 1 | 0;
 if (f >>> 0 < l >>> 0) do {
  g = h + (f * 216 | 0) | 0;
  if (!(c[g + 196 >> 2] | 0)) {
   Ra(g, b, e, f, d, k);
   c[g + 196 >> 2] = 1;
   c[a + 1204 >> 2] = (c[a + 1204 >> 2] | 0) + 1;
  }
  f = f + 1 | 0;
 } while ((f | 0) != (l | 0));
 if (!e) e = 0; else if (l) {
  i = e + -1 | 0;
  j = N(i, l) | 0;
  g = 0;
  do {
   f = (c[a + 1212 >> 2] | 0) + (j * 216 | 0) + (g * 216 | 0) | 0;
   h = i;
   while (1) {
    Ra(f, b, h, g, d, k);
    c[f + 196 >> 2] = 1;
    c[a + 1204 >> 2] = (c[a + 1204 >> 2] | 0) + 1;
    if (!h) break; else {
     f = f + ((0 - l | 0) * 216 | 0) | 0;
     h = h + -1 | 0;
    }
   }
   g = g + 1 | 0;
  } while ((g | 0) != (l | 0));
 }
 e = e + 1 | 0;
 if (e >>> 0 >= m >>> 0) return;
 if (!l) return;
 do {
  g = (c[a + 1212 >> 2] | 0) + ((N(e, l) | 0) * 216 | 0) | 0;
  f = 0;
  do {
   h = g + (f * 216 | 0) | 0;
   if (!(c[h + 196 >> 2] | 0)) {
    Ra(h, b, e, f, d, k);
    c[h + 196 >> 2] = 1;
    c[a + 1204 >> 2] = (c[a + 1204 >> 2] | 0) + 1;
   }
   f = f + 1 | 0;
  } while ((f | 0) != (l | 0));
  e = e + 1 | 0;
 } while ((e | 0) != (m | 0));
 return;
}

function Ca(b, c, e, f, g, h, i, j, k) {
 b = b | 0;
 c = c | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 var m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0;
 r = l;
 l = l + 448 | 0;
 if ((e | 0) < 0) m = 3; else if ((j + f | 0) >>> 0 > h >>> 0 | ((f | 0) < 0 | (e + 5 + i | 0) >>> 0 > g >>> 0)) m = 3; else h = g;
 if ((m | 0) == 3) {
  ya(b, r, e, f, g, h, i + 5 | 0, j, i + 5 | 0);
  b = r;
  e = 0;
  f = 0;
  h = i + 5 | 0;
 }
 if (!j) {
  l = r;
  return;
 }
 q = h - i | 0;
 b = b + ((N(f, h) | 0) + e) + 5 | 0;
 while (1) {
  h = d[b + -5 >> 0] | 0;
  e = d[b + -4 >> 0] | 0;
  g = d[b + -3 >> 0] | 0;
  n = d[b + -2 >> 0] | 0;
  f = d[b + -1 >> 0] | 0;
  do if (i >>> 2) {
   p = b + (i & -4) | 0;
   if (!k) {
    o = g;
    g = i >>> 2;
    m = c;
    while (1) {
     s = f + e | 0;
     t = e;
     e = d[b >> 0] | 0;
     a[m >> 0] = (o + 1 + (d[6162 + (h + 16 - s + ((n + o | 0) * 20 | 0) - (s << 2) + e >> 5) >> 0] | 0) | 0) >>> 1;
     s = o + e | 0;
     h = o;
     o = d[b + 1 >> 0] | 0;
     a[m + 1 >> 0] = (n + 1 + (d[6162 + (t + 16 + ((f + n | 0) * 20 | 0) - s - (s << 2) + o >> 5) >> 0] | 0) | 0) >>> 1;
     s = n + o | 0;
     t = n;
     n = d[b + 2 >> 0] | 0;
     a[m + 2 >> 0] = (f + 1 + (d[6162 + (h + 16 + ((f + e | 0) * 20 | 0) - s - (s << 2) + n >> 5) >> 0] | 0) | 0) >>> 1;
     s = f + n | 0;
     h = d[b + 3 >> 0] | 0;
     a[m + 3 >> 0] = (e + 1 + (d[6162 + (t + 16 + ((o + e | 0) * 20 | 0) - s - (s << 2) + h >> 5) >> 0] | 0) | 0) >>> 1;
     g = g + -1 | 0;
     if (!g) break; else {
      t = f;
      f = h;
      m = m + 4 | 0;
      b = b + 4 | 0;
      h = t;
     }
    }
    c = c + (i & -4) | 0;
    b = p;
    break;
   } else {
    o = g;
    g = i >>> 2;
    m = c;
    while (1) {
     t = f + e | 0;
     s = e;
     e = d[b >> 0] | 0;
     a[m >> 0] = (n + 1 + (d[6162 + (h + 16 - t + ((n + o | 0) * 20 | 0) - (t << 2) + e >> 5) >> 0] | 0) | 0) >>> 1;
     t = o + e | 0;
     h = o;
     o = d[b + 1 >> 0] | 0;
     a[m + 1 >> 0] = (f + 1 + (d[6162 + (s + 16 + ((f + n | 0) * 20 | 0) - t - (t << 2) + o >> 5) >> 0] | 0) | 0) >>> 1;
     t = n + o | 0;
     s = n;
     n = d[b + 2 >> 0] | 0;
     a[m + 2 >> 0] = (e + 1 + (d[6162 + (h + 16 + ((f + e | 0) * 20 | 0) - t - (t << 2) + n >> 5) >> 0] | 0) | 0) >>> 1;
     t = f + n | 0;
     h = d[b + 3 >> 0] | 0;
     a[m + 3 >> 0] = (o + 1 + (d[6162 + (s + 16 + ((o + e | 0) * 20 | 0) - t - (t << 2) + h >> 5) >> 0] | 0) | 0) >>> 1;
     g = g + -1 | 0;
     if (!g) break; else {
      t = f;
      f = h;
      m = m + 4 | 0;
      b = b + 4 | 0;
      h = t;
     }
    }
    c = c + (i & -4) | 0;
    b = p;
    break;
   }
  } while (0);
  j = j + -1 | 0;
  if (!j) break; else {
   c = c + (16 - i) | 0;
   b = b + q | 0;
  }
 }
 l = r;
 return;
}

function Ba(b, c, e, f, g, h, i, j, k) {
 b = b | 0;
 c = c | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 j = j | 0;
 k = k | 0;
 var m = 0, n = 0, o = 0, p = 0, q = 0, r = 0, s = 0, t = 0, u = 0, v = 0, w = 0, x = 0, y = 0;
 s = l;
 l = l + 448 | 0;
 if ((e | 0) < 0) m = 4; else if ((f | 0) < 0 | (i + e | 0) >>> 0 > g >>> 0) m = 4; else if ((f + 5 + j | 0) >>> 0 > h >>> 0) m = 4; else h = e;
 if ((m | 0) == 4) {
  ya(b, s, e, f, g, h, i, j + 5 | 0, i);
  b = s;
  h = 0;
  f = 0;
  g = i;
 }
 f = b + ((N(f, g) | 0) + h) + g | 0;
 if (!(j >>> 2)) {
  l = s;
  return;
 }
 p = (g << 2) - i | 0;
 q = 0 - g | 0;
 r = g << 1;
 b = f + (N(g, k + 2 | 0) | 0) | 0;
 h = f + (g * 5 | 0) | 0;
 e = c;
 o = j >>> 2;
 while (1) {
  if (i) {
   m = i;
   k = h;
   c = f;
   j = e;
   n = b;
   while (1) {
    t = d[k + (q << 1) >> 0] | 0;
    x = d[k + q >> 0] | 0;
    u = d[k + g >> 0] | 0;
    y = d[k >> 0] | 0;
    v = d[c + r >> 0] | 0;
    a[j + 48 >> 0] = ((d[6162 + ((d[k + r >> 0] | 0) + 16 - (u + t) - (u + t << 2) + v + ((y + x | 0) * 20 | 0) >> 5) >> 0] | 0) + 1 + (d[n + r >> 0] | 0) | 0) >>> 1;
    w = d[c + g >> 0] | 0;
    a[j + 32 >> 0] = ((d[6162 + (u + 16 + ((x + t | 0) * 20 | 0) - (v + y) - (v + y << 2) + w >> 5) >> 0] | 0) + 1 + (d[n + g >> 0] | 0) | 0) >>> 1;
    u = d[c >> 0] | 0;
    a[j + 16 >> 0] = ((d[6162 + (y + 16 + ((v + t | 0) * 20 | 0) - (w + x) - (w + x << 2) + u >> 5) >> 0] | 0) + 1 + (d[n >> 0] | 0) | 0) >>> 1;
    a[j >> 0] = ((d[6162 + (x + 16 + ((w + v | 0) * 20 | 0) - (u + t) - (u + t << 2) + (d[c + q >> 0] | 0) >> 5) >> 0] | 0) + 1 + (d[n + q >> 0] | 0) | 0) >>> 1;
    m = m + -1 | 0;
    if (!m) break; else {
     k = k + 1 | 0;
     c = c + 1 | 0;
     j = j + 1 | 0;
     n = n + 1 | 0;
    }
   }
   b = b + i | 0;
   h = h + i | 0;
   f = f + i | 0;
   e = e + i | 0;
  }
  o = o + -1 | 0;
  if (!o) break; else {
   b = b + p | 0;
   h = h + p | 0;
   f = f + p | 0;
   e = e + (64 - i) | 0;
  }
 }
 l = s;
 return;
}

function Na(b, e, f, g) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, l = 0, m = 0;
 l = a[b + 1 >> 0] | 0;
 m = d[b + -1 >> 0] | 0;
 i = d[b >> 0] | 0;
 h = c[f + 4 >> 2] | 0;
 if (((m - i | 0) < 0 ? 0 - (m - i) | 0 : m - i | 0) >>> 0 < h >>> 0) {
  j = d[b + -2 >> 0] | 0;
  k = c[f + 8 >> 2] | 0;
  if (((j - m | 0) < 0 ? 0 - (j - m) | 0 : j - m | 0) >>> 0 < k >>> 0) if ((((l & 255) - i | 0) < 0 ? 0 - ((l & 255) - i) | 0 : (l & 255) - i | 0) >>> 0 < k >>> 0) {
   if (e >>> 0 < 4) {
    h = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
    l = (4 - (l & 255) + (i - m << 2) + j >> 3 | 0) < (~h | 0) ? ~h : (4 - (l & 255) + (i - m << 2) + j >> 3 | 0) > (h + 1 | 0) ? h + 1 | 0 : 4 - (l & 255) + (i - m << 2) + j >> 3;
    h = a[6162 + (i - l) >> 0] | 0;
    a[b + -1 >> 0] = a[6162 + (l + m) >> 0] | 0;
   } else {
    a[b + -1 >> 0] = (m + 2 + (l & 255) + (j << 1) | 0) >>> 2;
    h = (i + 2 + ((l & 255) << 1) + j | 0) >>> 2 & 255;
   }
   a[b >> 0] = h;
   h = c[f + 4 >> 2] | 0;
  }
 }
 k = d[b + g + -1 >> 0] | 0;
 l = d[b + g >> 0] | 0;
 if (((k - l | 0) < 0 ? 0 - (k - l) | 0 : k - l | 0) >>> 0 >= h >>> 0) return;
 h = d[b + g + -2 >> 0] | 0;
 i = c[f + 8 >> 2] | 0;
 if (((h - k | 0) < 0 ? 0 - (h - k) | 0 : h - k | 0) >>> 0 >= i >>> 0) return;
 j = d[b + g + 1 >> 0] | 0;
 if (((j - l | 0) < 0 ? 0 - (j - l) | 0 : j - l | 0) >>> 0 >= i >>> 0) return;
 if (e >>> 0 < 4) {
  f = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
  f = (4 - j + (l - k << 2) + h >> 3 | 0) < (~f | 0) ? ~f : (4 - j + (l - k << 2) + h >> 3 | 0) > (f + 1 | 0) ? f + 1 | 0 : 4 - j + (l - k << 2) + h >> 3;
  h = a[6162 + (l - f) >> 0] | 0;
  a[b + g + -1 >> 0] = a[6162 + (f + k) >> 0] | 0;
 } else {
  a[b + g + -1 >> 0] = (k + 2 + j + (h << 1) | 0) >>> 2;
  h = (l + 2 + (j << 1) + h | 0) >>> 2 & 255;
 }
 a[b + g >> 0] = h;
 return;
}

function Ma(b, e, f, g) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, l = 0, m = 0, n = 0, o = 0, p = 0, q = 0, r = 0;
 r = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
 q = N(g, -3) | 0;
 p = 4;
 while (1) {
  e = b + (0 - g << 1) | 0;
  k = b + (0 - g) | 0;
  j = b + g | 0;
  l = a[j >> 0] | 0;
  m = d[k >> 0] | 0;
  n = d[b >> 0] | 0;
  if (((m - n | 0) < 0 ? 0 - (m - n) | 0 : m - n | 0) >>> 0 < (c[f + 4 >> 2] | 0) >>> 0) {
   o = d[e >> 0] | 0;
   i = c[f + 8 >> 2] | 0;
   if (((o - m | 0) < 0 ? 0 - (o - m) | 0 : o - m | 0) >>> 0 < i >>> 0) if ((((l & 255) - n | 0) < 0 ? 0 - ((l & 255) - n) | 0 : (l & 255) - n | 0) >>> 0 < i >>> 0) {
    h = d[b + q >> 0] | 0;
    if (((h - m | 0) < 0 ? 0 - (h - m) | 0 : h - m | 0) >>> 0 < i >>> 0) {
     a[e >> 0] = ((((m + 1 + n | 0) >>> 1) - (o << 1) + h >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((m + 1 + n | 0) >>> 1) - (o << 1) + h >> 1 | 0) > (r | 0) ? r : ((m + 1 + n | 0) >>> 1) - (o << 1) + h >> 1) + o;
     e = r + 1 | 0;
     i = c[f + 8 >> 2] | 0;
    } else e = r;
    h = d[b + (g << 1) >> 0] | 0;
    if (((h - n | 0) < 0 ? 0 - (h - n) | 0 : h - n | 0) >>> 0 < i >>> 0) {
     a[j >> 0] = ((((m + 1 + n | 0) >>> 1) - ((l & 255) << 1) + h >> 1 | 0) < (0 - r | 0) ? 0 - r | 0 : (((m + 1 + n | 0) >>> 1) - ((l & 255) << 1) + h >> 1 | 0) > (r | 0) ? r : ((m + 1 + n | 0) >>> 1) - ((l & 255) << 1) + h >> 1) + (l & 255);
     e = e + 1 | 0;
    }
    j = 0 - e | 0;
    l = (4 - (l & 255) + (n - m << 2) + o >> 3 | 0) < (j | 0) ? j : (4 - (l & 255) + (n - m << 2) + o >> 3 | 0) > (e | 0) ? e : 4 - (l & 255) + (n - m << 2) + o >> 3;
    o = a[6162 + (n - l) >> 0] | 0;
    a[k >> 0] = a[6162 + (l + m) >> 0] | 0;
    a[b >> 0] = o;
   }
  }
  p = p + -1 | 0;
  if (!p) break; else b = b + 1 | 0;
 }
 return;
}

function Wa() {
 var a = 0, b = 0, d = 0, e = 0;
 e = _a(3396) | 0;
 if (e | 0) {
  pb(e + 8 | 0, 0, 3388) | 0;
  c[e + 16 >> 2] = 32;
  c[e + 12 >> 2] = 256;
  c[e + 1340 >> 2] = 1;
  d = _a(2112) | 0;
  c[e + 3384 >> 2] = d;
  if (d | 0) {
   c[e >> 2] = 1;
   c[e + 4 >> 2] = 0;
   c[1813] = e;
   c[1814] = 1;
   c[1815] = 1;
   e = 0;
   return e | 0;
  }
  a = 0;
  do {
   d = e + 8 + 20 + (a << 2) | 0;
   b = c[d >> 2] | 0;
   if (b | 0) {
    $a(c[b + 40 >> 2] | 0);
    c[(c[d >> 2] | 0) + 40 >> 2] = 0;
    $a(c[(c[d >> 2] | 0) + 84 >> 2] | 0);
    c[(c[d >> 2] | 0) + 84 >> 2] = 0;
    $a(c[d >> 2] | 0);
    c[d >> 2] = 0;
   }
   a = a + 1 | 0;
  } while ((a | 0) != 32);
  a = 0;
  do {
   b = e + 8 + 148 + (a << 2) | 0;
   d = c[b >> 2] | 0;
   if (d | 0) {
    $a(c[d + 20 >> 2] | 0);
    c[(c[b >> 2] | 0) + 20 >> 2] = 0;
    $a(c[(c[b >> 2] | 0) + 24 >> 2] | 0);
    c[(c[b >> 2] | 0) + 24 >> 2] = 0;
    $a(c[(c[b >> 2] | 0) + 28 >> 2] | 0);
    c[(c[b >> 2] | 0) + 28 >> 2] = 0;
    $a(c[(c[b >> 2] | 0) + 44 >> 2] | 0);
    c[(c[b >> 2] | 0) + 44 >> 2] = 0;
    $a(c[b >> 2] | 0);
    c[b >> 2] = 0;
   }
   a = a + 1 | 0;
  } while ((a | 0) != 256);
  $a(c[e + 3384 >> 2] | 0);
  c[e + 3384 >> 2] = 0;
  $a(c[e + 1220 >> 2] | 0);
  c[e + 1220 >> 2] = 0;
  $a(c[e + 1180 >> 2] | 0);
  c[e + 1180 >> 2] = 0;
  a = c[e + 1228 >> 2] | 0;
  if (a) if ((c[e + 1256 >> 2] | 0) != -1) {
   b = 0;
   do {
    $a(c[a + (b * 40 | 0) + 4 >> 2] | 0);
    a = c[e + 1228 >> 2] | 0;
    c[a + (b * 40 | 0) + 4 >> 2] = 0;
    b = b + 1 | 0;
   } while (b >>> 0 < ((c[e + 1256 >> 2] | 0) + 1 | 0) >>> 0);
  }
  $a(a);
  c[e + 1228 >> 2] = 0;
  $a(c[e + 1232 >> 2] | 0);
  c[e + 1232 >> 2] = 0;
  $a(c[e + 1240 >> 2] | 0);
  $a(e);
 }
 mb();
 e = -1;
 return e | 0;
}

function xa(b, e, f) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 var g = 0, h = 0, i = 0, j = 0;
 g = c[e >> 2] | 0;
 if ((g | 0) == 16777215) return;
 h = f >>> 0 < 16 ? 16 : 8;
 j = f >>> 0 < 16 ? f : f & 3;
 b = b + (N(c[1216 + (j << 2) >> 2] | 0, h) | 0) + (c[1152 + (j << 2) >> 2] | 0) | 0;
 j = c[e + 4 >> 2] | 0;
 f = d[b + 1 >> 0] | 0;
 a[b >> 0] = a[6162 + (g + (d[b >> 0] | 0)) >> 0] | 0;
 i = c[e + 8 >> 2] | 0;
 g = d[b + 2 >> 0] | 0;
 a[b + 1 >> 0] = a[6162 + (j + f) >> 0] | 0;
 f = a[6162 + ((c[e + 12 >> 2] | 0) + (d[b + 3 >> 0] | 0)) >> 0] | 0;
 a[b + 2 >> 0] = a[6162 + (i + g) >> 0] | 0;
 a[b + 3 >> 0] = f;
 f = c[e + 20 >> 2] | 0;
 g = d[b + h + 1 >> 0] | 0;
 a[b + h >> 0] = a[6162 + ((c[e + 16 >> 2] | 0) + (d[b + h >> 0] | 0)) >> 0] | 0;
 i = c[e + 24 >> 2] | 0;
 j = d[b + h + 2 >> 0] | 0;
 a[b + h + 1 >> 0] = a[6162 + (f + g) >> 0] | 0;
 g = a[6162 + ((c[e + 28 >> 2] | 0) + (d[b + h + 3 >> 0] | 0)) >> 0] | 0;
 a[b + h + 2 >> 0] = a[6162 + (i + j) >> 0] | 0;
 a[b + h + 3 >> 0] = g;
 g = b + h + h | 0;
 b = c[e + 36 >> 2] | 0;
 j = d[g + 1 >> 0] | 0;
 a[g >> 0] = a[6162 + ((c[e + 32 >> 2] | 0) + (d[g >> 0] | 0)) >> 0] | 0;
 i = c[e + 40 >> 2] | 0;
 f = d[g + 2 >> 0] | 0;
 a[g + 1 >> 0] = a[6162 + (b + j) >> 0] | 0;
 j = a[6162 + ((c[e + 44 >> 2] | 0) + (d[g + 3 >> 0] | 0)) >> 0] | 0;
 a[g + 2 >> 0] = a[6162 + (i + f) >> 0] | 0;
 a[g + 3 >> 0] = j;
 j = c[e + 52 >> 2] | 0;
 f = d[g + h + 1 >> 0] | 0;
 a[g + h >> 0] = a[6162 + ((c[e + 48 >> 2] | 0) + (d[g + h >> 0] | 0)) >> 0] | 0;
 i = c[e + 56 >> 2] | 0;
 b = d[g + h + 2 >> 0] | 0;
 a[g + h + 1 >> 0] = a[6162 + (j + f) >> 0] | 0;
 f = a[6162 + ((c[e + 60 >> 2] | 0) + (d[g + h + 3 >> 0] | 0)) >> 0] | 0;
 a[g + h + 2 >> 0] = a[6162 + (i + b) >> 0] | 0;
 a[g + h + 3 >> 0] = f;
 return;
}

function Oa(b, e, f, g) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, l = 0, m = 0, n = 0;
 if (e >>> 0 < 4) {
  n = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
  m = 8;
  while (1) {
   e = b + (0 - g) | 0;
   h = a[b + g >> 0] | 0;
   i = d[e >> 0] | 0;
   j = d[b >> 0] | 0;
   if (((i - j | 0) < 0 ? 0 - (i - j) | 0 : i - j | 0) >>> 0 < (c[f + 4 >> 2] | 0) >>> 0) {
    k = d[b + (0 - g << 1) >> 0] | 0;
    l = c[f + 8 >> 2] | 0;
    if (((k - i | 0) < 0 ? 0 - (k - i) | 0 : k - i | 0) >>> 0 < l >>> 0) if ((((h & 255) - j | 0) < 0 ? 0 - ((h & 255) - j) | 0 : (h & 255) - j | 0) >>> 0 < l >>> 0) {
     k = (4 - (h & 255) + (j - i << 2) + k >> 3 | 0) < (~n | 0) ? ~n : (4 - (h & 255) + (j - i << 2) + k >> 3 | 0) > (n + 1 | 0) ? n + 1 | 0 : 4 - (h & 255) + (j - i << 2) + k >> 3;
     l = a[6162 + (j - k) >> 0] | 0;
     a[e >> 0] = a[6162 + (k + i) >> 0] | 0;
     a[b >> 0] = l;
    }
   }
   m = m + -1 | 0;
   if (!m) break; else b = b + 1 | 0;
  }
  return;
 } else {
  e = 8;
  while (1) {
   h = b + (0 - g) | 0;
   i = a[b + g >> 0] | 0;
   j = d[h >> 0] | 0;
   k = d[b >> 0] | 0;
   if (((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) >>> 0 < (c[f + 4 >> 2] | 0) >>> 0) {
    l = d[b + (0 - g << 1) >> 0] | 0;
    m = c[f + 8 >> 2] | 0;
    if (((l - j | 0) < 0 ? 0 - (l - j) | 0 : l - j | 0) >>> 0 < m >>> 0) if ((((i & 255) - k | 0) < 0 ? 0 - ((i & 255) - k) | 0 : (i & 255) - k | 0) >>> 0 < m >>> 0) {
     a[h >> 0] = (j + 2 + (i & 255) + (l << 1) | 0) >>> 2;
     a[b >> 0] = (k + 2 + ((i & 255) << 1) + l | 0) >>> 2;
    }
   }
   e = e + -1 | 0;
   if (!e) break; else b = b + 1 | 0;
  }
  return;
 }
}

function Sa(a, b) {
 a = a | 0;
 b = b | 0;
 var d = 0, e = 0, f = 0;
 d = va(a, b) | 0;
 if (d | 0) {
  b = d;
  return b | 0;
 }
 f = (c[b >> 2] | 0) + 1 | 0;
 c[b >> 2] = f;
 if (f >>> 0 > 32) {
  b = 1;
  return b | 0;
 }
 d = ua(a, 4) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 4 >> 2] = d;
 d = ua(a, 4) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 8 >> 2] = d;
 a : do if (c[b >> 2] | 0) {
  f = 0;
  while (1) {
   e = b + 12 + (f << 2) | 0;
   d = va(a, e) | 0;
   if (d | 0) {
    e = 17;
    break;
   }
   d = c[e >> 2] | 0;
   if ((d | 0) == -1) {
    d = 1;
    e = 17;
    break;
   }
   c[e >> 2] = d + 1;
   c[e >> 2] = d + 1 << (c[b + 4 >> 2] | 0) + 6;
   e = b + 140 + (f << 2) | 0;
   d = va(a, e) | 0;
   if (d | 0) {
    e = 17;
    break;
   }
   d = c[e >> 2] | 0;
   if ((d | 0) == -1) {
    d = 1;
    e = 17;
    break;
   }
   c[e >> 2] = d + 1;
   c[e >> 2] = d + 1 << (c[b + 8 >> 2] | 0) + 4;
   d = ua(a, 1) | 0;
   if ((d | 0) == -1) {
    d = 1;
    e = 17;
    break;
   }
   c[b + 268 + (f << 2) >> 2] = (d | 0) == 1 & 1;
   f = f + 1 | 0;
   if (f >>> 0 >= (c[b >> 2] | 0) >>> 0) break a;
  }
  if ((e | 0) == 17) return d | 0;
 } while (0);
 d = ua(a, 5) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 396 >> 2] = d + 1;
 d = ua(a, 5) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 400 >> 2] = d + 1;
 d = ua(a, 5) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 404 >> 2] = d + 1;
 d = ua(a, 5) | 0;
 if ((d | 0) == -1) {
  b = 1;
  return b | 0;
 }
 c[b + 408 >> 2] = d;
 b = 0;
 return b | 0;
}

function Pa(b, e, f, g) {
 b = b | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 var h = 0, i = 0, j = 0, k = 0, l = 0, m = 0;
 m = d[(c[f >> 2] | 0) + (e + -1) >> 0] | 0;
 h = a[b + g >> 0] | 0;
 i = d[b + (0 - g) >> 0] | 0;
 j = d[b >> 0] | 0;
 e = c[f + 4 >> 2] | 0;
 if (((i - j | 0) < 0 ? 0 - (i - j) | 0 : i - j | 0) >>> 0 < e >>> 0) {
  k = d[b + (0 - g << 1) >> 0] | 0;
  l = c[f + 8 >> 2] | 0;
  if (((k - i | 0) < 0 ? 0 - (k - i) | 0 : k - i | 0) >>> 0 < l >>> 0) if ((((h & 255) - j | 0) < 0 ? 0 - ((h & 255) - j) | 0 : (h & 255) - j | 0) >>> 0 < l >>> 0) {
   l = (4 - (h & 255) + (j - i << 2) + k >> 3 | 0) < (~m | 0) ? ~m : (4 - (h & 255) + (j - i << 2) + k >> 3 | 0) > (m + 1 | 0) ? m + 1 | 0 : 4 - (h & 255) + (j - i << 2) + k >> 3;
   e = a[6162 + (j - l) >> 0] | 0;
   a[b + (0 - g) >> 0] = a[6162 + (l + i) >> 0] | 0;
   a[b >> 0] = e;
   e = c[f + 4 >> 2] | 0;
  }
 }
 j = d[b + 1 + (0 - g) >> 0] | 0;
 k = d[b + 1 >> 0] | 0;
 if (((j - k | 0) < 0 ? 0 - (j - k) | 0 : j - k | 0) >>> 0 >= e >>> 0) return;
 i = d[b + 1 + (0 - g << 1) >> 0] | 0;
 e = c[f + 8 >> 2] | 0;
 if (((i - j | 0) < 0 ? 0 - (i - j) | 0 : i - j | 0) >>> 0 >= e >>> 0) return;
 h = d[b + 1 + g >> 0] | 0;
 if (((h - k | 0) < 0 ? 0 - (h - k) | 0 : h - k | 0) >>> 0 >= e >>> 0) return;
 f = (4 - h + (k - j << 2) + i >> 3 | 0) < (~m | 0) ? ~m : (4 - h + (k - j << 2) + i >> 3 | 0) > (m + 1 | 0) ? m + 1 | 0 : 4 - h + (k - j << 2) + i >> 3;
 m = a[6162 + (k - f) >> 0] | 0;
 a[b + 1 + (0 - g) >> 0] = a[6162 + (f + j) >> 0] | 0;
 a[b + 1 >> 0] = m;
 return;
}

function nb() {}
function ob(b, d, e) {
 b = b | 0;
 d = d | 0;
 e = e | 0;
 var f = 0, g = 0, h = 0;
 if ((e | 0) >= 8192) return ea(b | 0, d | 0, e | 0) | 0;
 h = b | 0;
 g = b + e | 0;
 if ((b & 3) == (d & 3)) {
  while (b & 3) {
   if (!e) return h | 0;
   a[b >> 0] = a[d >> 0] | 0;
   b = b + 1 | 0;
   d = d + 1 | 0;
   e = e - 1 | 0;
  }
  e = g & -4 | 0;
  f = e - 64 | 0;
  while ((b | 0) <= (f | 0)) {
   c[b >> 2] = c[d >> 2];
   c[b + 4 >> 2] = c[d + 4 >> 2];
   c[b + 8 >> 2] = c[d + 8 >> 2];
   c[b + 12 >> 2] = c[d + 12 >> 2];
   c[b + 16 >> 2] = c[d + 16 >> 2];
   c[b + 20 >> 2] = c[d + 20 >> 2];
   c[b + 24 >> 2] = c[d + 24 >> 2];
   c[b + 28 >> 2] = c[d + 28 >> 2];
   c[b + 32 >> 2] = c[d + 32 >> 2];
   c[b + 36 >> 2] = c[d + 36 >> 2];
   c[b + 40 >> 2] = c[d + 40 >> 2];
   c[b + 44 >> 2] = c[d + 44 >> 2];
   c[b + 48 >> 2] = c[d + 48 >> 2];
   c[b + 52 >> 2] = c[d + 52 >> 2];
   c[b + 56 >> 2] = c[d + 56 >> 2];
   c[b + 60 >> 2] = c[d + 60 >> 2];
   b = b + 64 | 0;
   d = d + 64 | 0;
  }
  while ((b | 0) < (e | 0)) {
   c[b >> 2] = c[d >> 2];
   b = b + 4 | 0;
   d = d + 4 | 0;
  }
 } else {
  e = g - 4 | 0;
  while ((b | 0) < (e | 0)) {
   a[b >> 0] = a[d >> 0] | 0;
   a[b + 1 >> 0] = a[d + 1 >> 0] | 0;
   a[b + 2 >> 0] = a[d + 2 >> 0] | 0;
   a[b + 3 >> 0] = a[d + 3 >> 0] | 0;
   b = b + 4 | 0;
   d = d + 4 | 0;
  }
 }
 while ((b | 0) < (g | 0)) {
  a[b >> 0] = a[d >> 0] | 0;
  b = b + 1 | 0;
  d = d + 1 | 0;
 }
 return h | 0;
}

function sa(d, e, f) {
 d = d | 0;
 e = e | 0;
 f = f | 0;
 var g = 0, h = 0, i = 0;
 h = a[384 + (e << 3) + 4 >> 0] | 0;
 i = a[576 + (e << 3) + 4 >> 0] | 0;
 if (11205370 >>> e & 1 | 0) {
  g = b[f + ((h & 255) << 1) >> 1] | 0;
  if (13434828 >>> e & 1 | 0) {
   d = g + 1 + (b[f + ((i & 255) << 1) >> 1] | 0) >> 1;
   return d | 0;
  }
  e = c[d + 204 >> 2] | 0;
  if (!e) {
   d = g;
   return d | 0;
  }
  if ((c[d + 4 >> 2] | 0) != (c[e + 4 >> 2] | 0)) {
   d = g;
   return d | 0;
  }
  d = g + 1 + (b[e + 28 + ((i & 255) << 1) >> 1] | 0) >> 1;
  return d | 0;
 }
 if (13434828 >>> e & 1 | 0) {
  e = b[f + ((i & 255) << 1) >> 1] | 0;
  g = c[d + 200 >> 2] | 0;
  if (!g) {
   d = e;
   return d | 0;
  }
  if ((c[d + 4 >> 2] | 0) != (c[g + 4 >> 2] | 0)) {
   d = e;
   return d | 0;
  }
  d = e + 1 + (b[g + 28 + ((h & 255) << 1) >> 1] | 0) >> 1;
  return d | 0;
 }
 e = c[d + 200 >> 2] | 0;
 if (!e) {
  f = 0;
  e = 0;
 } else if ((c[d + 4 >> 2] | 0) == (c[e + 4 >> 2] | 0)) {
  f = 1;
  e = b[e + 28 + ((h & 255) << 1) >> 1] | 0;
 } else {
  f = 0;
  e = 0;
 }
 g = c[d + 204 >> 2] | 0;
 if (!g) {
  d = e;
  return d | 0;
 }
 if ((c[d + 4 >> 2] | 0) == (c[g + 4 >> 2] | 0)) {
  d = b[g + 28 + ((i & 255) << 1) >> 1] | 0;
  return ((f | 0) == 0 ? d : e + 1 + d >> 1) | 0;
 } else {
  d = e;
  return d | 0;
 }
 return 0;
}

function ya(a, b, c, d, e, f, g, h, i) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 d = d | 0;
 e = e | 0;
 f = f | 0;
 g = g | 0;
 h = h | 0;
 i = i | 0;
 var j = 0, k = 0, l = 0, m = 0, n = 0, o = 0, p = 0;
 p = (c | 0) < 0 | (g + c | 0) > (e | 0) ? 2 : 1;
 m = (h + d | 0) < 0 ? 0 - h | 0 : d;
 n = (g + c | 0) < 0 ? 0 - g | 0 : c;
 m = (m | 0) > (f | 0) ? f : m;
 n = (n | 0) > (e | 0) ? e : n;
 c = (n | 0) > 0 ? a + n | 0 : a;
 o = c + (N(m, e) | 0) | 0;
 c = (m | 0) > 0 ? o : c;
 o = (n | 0) < 0 ? 0 - n | 0 : 0;
 n = (n + g | 0) > (e | 0) ? n + g - e | 0 : 0;
 k = (m | 0) < 0 ? 0 - m | 0 : 0;
 l = (m + h | 0) > (f | 0) ? m + h - f | 0 : 0;
 if (k) {
  d = 0 - m | 0;
  a = b;
  while (1) {
   ja[p & 3](c, a, o, g - o - n | 0, n);
   d = d + -1 | 0;
   if (!d) break; else a = a + i | 0;
  }
  b = b + (N(k, i) | 0) | 0;
 }
 if (h - k - l | 0) {
  d = h - k - l | 0;
  a = b;
  j = c;
  while (1) {
   ja[p & 3](j, a, o, g - o - n | 0, n);
   d = d + -1 | 0;
   if (!d) break; else {
    a = a + i | 0;
    j = j + e | 0;
   }
  }
  b = b + (N(h - k - l | 0, i) | 0) | 0;
  c = c + (N(h - k - l | 0, e) | 0) | 0;
 }
 d = c + (0 - e) | 0;
 if (!l) return; else c = m + h - f | 0;
 while (1) {
  ja[p & 3](d, b, o, g - o - n | 0, n);
  c = c + -1 | 0;
  if (!c) break; else b = b + i | 0;
 }
 return;
}

function eb(a, b, d) {
 a = a | 0;
 b = b | 0;
 d = d | 0;
 var e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0;
 i = l;
 l = l + 48 | 0;
 e = c[a + 28 >> 2] | 0;
 c[i + 32 >> 2] = e;
 e = (c[a + 20 >> 2] | 0) - e | 0;
 c[i + 32 + 4 >> 2] = e;
 c[i + 32 + 8 >> 2] = b;
 c[i + 32 + 12 >> 2] = d;
 c[i >> 2] = c[a + 60 >> 2];
 c[i + 4 >> 2] = i + 32;
 c[i + 8 >> 2] = 2;
 f = cb($(146, i | 0) | 0) | 0;
 a : do if ((e + d | 0) == (f | 0)) h = 3; else {
  b = 2;
  g = e + d | 0;
  e = i + 32 | 0;
  while (1) {
   if ((f | 0) < 0) break;
   g = g - f | 0;
   j = c[e + 4 >> 2] | 0;
   k = f >>> 0 > j >>> 0;
   e = k ? e + 8 | 0 : e;
   b = b + (k << 31 >> 31) | 0;
   j = f - (k ? j : 0) | 0;
   c[e >> 2] = (c[e >> 2] | 0) + j;
   c[e + 4 >> 2] = (c[e + 4 >> 2] | 0) - j;
   c[i + 16 >> 2] = c[a + 60 >> 2];
   c[i + 16 + 4 >> 2] = e;
   c[i + 16 + 8 >> 2] = b;
   f = cb($(146, i + 16 | 0) | 0) | 0;
   if ((g | 0) == (f | 0)) {
    h = 3;
    break a;
   }
  }
  c[a + 16 >> 2] = 0;
  c[a + 28 >> 2] = 0;
  c[a + 20 >> 2] = 0;
  c[a >> 2] = c[a >> 2] | 32;
  if ((b | 0) == 2) d = 0; else d = d - (c[e + 4 >> 2] | 0) | 0;
 } while (0);
 if ((h | 0) == 3) {
  k = c[a + 44 >> 2] | 0;
  c[a + 16 >> 2] = k + (c[a + 48 >> 2] | 0);
  c[a + 28 >> 2] = k;
  c[a + 20 >> 2] = k;
 }
 l = i;
 return d | 0;
}

function ua(a, b) {
 a = a | 0;
 b = b | 0;
 var e = 0, f = 0, g = 0, h = 0, i = 0, j = 0, k = 0;
 h = c[a + 4 >> 2] | 0;
 j = c[a + 12 >> 2] << 3;
 k = c[a + 16 >> 2] | 0;
 if ((j - k | 0) > 31) {
  f = c[a + 8 >> 2] | 0;
  e = (d[h + 1 >> 0] | 0) << 16 | (d[h >> 0] | 0) << 24 | (d[h + 2 >> 0] | 0) << 8 | (d[h + 3 >> 0] | 0);
  if (!f) f = a + 8 | 0; else {
   e = (d[h + 4 >> 0] | 0) >>> (8 - f | 0) | e << f;
   f = a + 8 | 0;
  }
 } else if ((j - k | 0) > 0) {
  f = c[a + 8 >> 2] | 0;
  e = (d[h >> 0] | 0) << f + 24;
  if ((j - k + -8 + f | 0) > 0) {
   i = j - k + -8 + f | 0;
   g = f + 24 | 0;
   f = h;
   while (1) {
    f = f + 1 | 0;
    g = g + -8 | 0;
    e = (d[f >> 0] | 0) << g | e;
    if ((i | 0) <= 8) {
     f = a + 8 | 0;
     break;
    } else i = i + -8 | 0;
   }
  } else f = a + 8 | 0;
 } else {
  e = 0;
  f = a + 8 | 0;
 }
 c[a + 16 >> 2] = k + b;
 c[f >> 2] = k + b & 7;
 if ((k + b | 0) >>> 0 > j >>> 0) {
  k = -1;
  return k | 0;
 }
 c[a + 4 >> 2] = (c[a >> 2] | 0) + ((k + b | 0) >>> 3);
 k = e >>> (32 - b | 0);
 return k | 0;
}

function pb(b, d, e) {
 b = b | 0;
 d = d | 0;
 e = e | 0;
 var f = 0, g = 0;
 f = b + e | 0;
 d = d & 255;
 if ((e | 0) >= 67) {
  while (b & 3) {
   a[b >> 0] = d;
   b = b + 1 | 0;
  }
  g = d | d << 8 | d << 16 | d << 24;
  while ((b | 0) <= ((f & -4) - 64 | 0)) {
   c[b >> 2] = g;
   c[b + 4 >> 2] = g;
   c[b + 8 >> 2] = g;
   c[b + 12 >> 2] = g;
   c[b + 16 >> 2] = g;
   c[b + 20 >> 2] = g;
   c[b + 24 >> 2] = g;
   c[b + 28 >> 2] = g;
   c[b + 32 >> 2] = g;
   c[b + 36 >> 2] = g;
   c[b + 40 >> 2] = g;
   c[b + 44 >> 2] = g;
   c[b + 48 >> 2] = g;
   c[b + 52 >> 2] = g;
   c[b + 56 >> 2] = g;
   c[b + 60 >> 2] = g;
   b = b + 64 | 0;
  }
  while ((b | 0) < (f & -4 | 0)) {
   c[b >> 2] = g;
   b = b + 4 | 0;
  }
 }
 while ((b | 0) < (f | 0)) {
  a[b >> 0] = d;
  b = b + 1 | 0;
 }
 return f - e | 0;
}

function lb() {
 var b = 0, e = 0, f = 0;
 f = l;
 l = l + 16 | 0;
 a[f >> 0] = 10;
 b = c[852] | 0;
 if (!b) if (!(ib() | 0)) {
  b = c[852] | 0;
  e = 4;
 } else b = -1; else e = 4;
 do if ((e | 0) == 4) {
  e = c[853] | 0;
  if (!(e >>> 0 >= b >>> 0 | (a[3467] | 0) == 10)) {
   c[853] = e + 1;
   a[e >> 0] = 10;
   b = 10;
   break;
  }
  if ((ia[c[3428 >> 2] & 3](3392, f, 1) | 0) == 1) b = d[f >> 0] | 0; else b = -1;
 } while (0);
 l = f;
 return b | 0;
}

function za(b, c, d, e, f) {
 b = b | 0;
 c = c | 0;
 d = d | 0;
 e = e | 0;
 f = f | 0;
 var g = 0, h = 0;
 if (d) {
  pb(c | 0, a[b >> 0] | 0, d | 0) | 0;
  c = c + d | 0;
 }
 if (e) {
  d = e;
  g = b;
  h = c;
  while (1) {
   a[h >> 0] = a[g >> 0] | 0;
   d = d + -1 | 0;
   if (!d) break; else {
    g = g + 1 | 0;
    h = h + 1 | 0;
   }
  }
  b = b + e | 0;
  c = c + e | 0;
 }
 if (!f) return;
 pb(c | 0, a[b + -1 >> 0] | 0, f | 0) | 0;
 return;
}

function hb(a) {
 a = a | 0;
 var b = 0, d = 0;
 b = c[852] | 0;
 if (!b) if (!(ib() | 0)) {
  b = c[852] | 0;
  d = 5;
 } else a = 0; else d = 5;
 do if ((d | 0) == 5) {
  d = c[853] | 0;
  if ((b - d | 0) >>> 0 < a >>> 0) {
   a = ia[c[3428 >> 2] & 3](3392, 7190, a) | 0;
   break;
  } else {
   ob(d | 0, 7190, a | 0) | 0;
   c[853] = (c[853] | 0) + a;
   break;
  }
 } while (0);
 return a | 0;
}

function bb(a, b, d) {
 a = a | 0;
 b = b | 0;
 d = d | 0;
 var e = 0;
 e = l;
 l = l + 32 | 0;
 c[e >> 2] = c[a + 60 >> 2];
 c[e + 4 >> 2] = 0;
 c[e + 8 >> 2] = b;
 c[e + 12 >> 2] = e + 20;
 c[e + 16 >> 2] = d;
 if ((cb(_(140, e | 0) | 0) | 0) < 0) {
  c[e + 20 >> 2] = -1;
  a = -1;
 } else a = c[e + 20 >> 2] | 0;
 l = e;
 return a | 0;
}

function fb(b, d, e) {
 b = b | 0;
 d = d | 0;
 e = e | 0;
 var f = 0;
 f = l;
 l = l + 32 | 0;
 c[b + 36 >> 2] = 3;
 if (!(c[b >> 2] & 64)) {
  c[f >> 2] = c[b + 60 >> 2];
  c[f + 4 >> 2] = 21523;
  c[f + 8 >> 2] = f + 16;
  if (aa(54, f | 0) | 0) a[b + 75 >> 0] = -1;
 }
 e = eb(b, d, e) | 0;
 l = f;
 return e | 0;
}

function qb(a) {
 a = a | 0;
 var b = 0;
 b = c[i >> 2] | 0;
 if ((a | 0) > 0 & (b + a | 0) < (b | 0) | (b + a | 0) < 0) {
  V() | 0;
  Z(12);
  return -1;
 }
 c[i >> 2] = b + a;
 if ((b + a | 0) > (U() | 0)) if (!(T() | 0)) {
  c[i >> 2] = b;
  Z(12);
  return -1;
 }
 return b | 0;
}

function ib() {
 var b = 0;
 b = a[3466] | 0;
 a[3466] = b + 255 | b;
 b = c[848] | 0;
 if (!(b & 8)) {
  c[850] = 0;
  c[849] = 0;
  b = c[859] | 0;
  c[855] = b;
  c[853] = b;
  c[852] = b + (c[860] | 0);
  b = 0;
 } else {
  c[848] = b | 32;
  b = -1;
 }
 return b | 0;
}

function mb() {
 var b = 0;
 do if ((jb() | 0) >= 0) {
  if ((a[3467] | 0) != 10) {
   b = c[853] | 0;
   if (b >>> 0 < (c[852] | 0) >>> 0) {
    c[853] = b + 1;
    a[b >> 0] = 10;
    break;
   }
  }
  lb() | 0;
 } while (0);
 return;
}

function ab(a) {
 a = a | 0;
 var b = 0;
 b = l;
 l = l + 16 | 0;
 c[b >> 2] = db(c[a + 60 >> 2] | 0) | 0;
 a = cb(ba(6, b | 0) | 0) | 0;
 l = b;
 return a | 0;
}

function tb(a, b, c, d, e, f) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 d = d | 0;
 e = e | 0;
 f = f | 0;
 ja[a & 3](b | 0, c | 0, d | 0, e | 0, f | 0);
}
function Ua(a) {
 a = a | 0;
 var b = 0;
 b = _a(a) | 0;
 c[1811] = b;
 c[1810] = b;
 c[1809] = a;
 c[1812] = b + a;
 return b | 0;
}

function Aa(a, b, c, d, e) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 d = d | 0;
 e = e | 0;
 ob(b | 0, a | 0, d | 0) | 0;
 return;
}

function sb(a, b, c, d) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 d = d | 0;
 return ia[a & 3](b | 0, c | 0, d | 0) | 0;
}
function ka(a) {
 a = a | 0;
 var b = 0;
 b = l;
 l = l + a | 0;
 l = l + 15 & -16;
 return b | 0;
}

function wb(a, b, c, d, e) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 d = d | 0;
 e = e | 0;
 R(2);
}

function jb() {
 var a = 0;
 a = gb() | 0;
 return ((kb(a) | 0) != (a | 0)) << 31 >> 31 | 0;
}

function vb(a, b, c) {
 a = a | 0;
 b = b | 0;
 c = c | 0;
 R(1);
 return 0;
}

function oa(a, b) {
 a = a | 0;
 b = b | 0;
 if (!n) {
  n = a;
  o = b;
 }
}

function rb(a, b) {
 a = a | 0;
 b = b | 0;
 return ha[a & 1](b | 0) | 0;
}

function cb(a) {
 a = a | 0;
 return (a >>> 0 > 4294963200 ? -1 : a) | 0;
}

function na(a, b) {
 a = a | 0;
 b = b | 0;
 l = a;
 m = b;
}

function kb(a) {
 a = a | 0;
 return hb(a) | 0;
}

function ub(a) {
 a = a | 0;
 R(0);
 return 0;
}

function db(a) {
 a = a | 0;
 return a | 0;
}

function pa(a) {
 a = a | 0;
 y = a;
}

function ma(a) {
 a = a | 0;
 l = a;
}

function qa() {
 return y | 0;
}

function la() {
 return l | 0;
}

function gb() {
 return 29;
}

function Za() {
 return 3;
}

function Ya() {
 return 2;
}

function Xa() {
 return;
}

// EMSCRIPTEN_END_FUNCS

 var ha = [ ub, ab ];
 var ia = [ vb, fb, bb, eb ];
 var ja = [ wb, Aa, za, wb ];
 return {
  _broadwayCreateStream: Ua,
  _broadwayExit: Xa,
  _broadwayGetMajorVersion: Ya,
  _broadwayGetMinorVersion: Za,
  _broadwayInit: Wa,
  _broadwayPlayStream: Va,
  _free: $a,
  _malloc: _a,
  _memcpy: ob,
  _memset: pb,
  _sbrk: qb,
  dynCall_ii: rb,
  dynCall_iiii: sb,
  dynCall_viiiii: tb,
  establishStackSpace: na,
  getTempRet0: qa,
  runPostSets: nb,
  setTempRet0: pa,
  setThrew: oa,
  stackAlloc: ka,
  stackRestore: ma,
  stackSave: la
 };
})


// EMSCRIPTEN_END_ASM
(Module.asmGlobalArg, Module.asmLibraryArg, buffer);
var _broadwayCreateStream = Module["_broadwayCreateStream"] = asm["_broadwayCreateStream"];
var _broadwayExit = Module["_broadwayExit"] = asm["_broadwayExit"];
var _broadwayGetMajorVersion = Module["_broadwayGetMajorVersion"] = asm["_broadwayGetMajorVersion"];
var _broadwayGetMinorVersion = Module["_broadwayGetMinorVersion"] = asm["_broadwayGetMinorVersion"];
var _broadwayInit = Module["_broadwayInit"] = asm["_broadwayInit"];
var _broadwayPlayStream = Module["_broadwayPlayStream"] = asm["_broadwayPlayStream"];
var _free = Module["_free"] = asm["_free"];
var _malloc = Module["_malloc"] = asm["_malloc"];
var _memcpy = Module["_memcpy"] = asm["_memcpy"];
var _memset = Module["_memset"] = asm["_memset"];
var _sbrk = Module["_sbrk"] = asm["_sbrk"];
var establishStackSpace = Module["establishStackSpace"] = asm["establishStackSpace"];
var getTempRet0 = Module["getTempRet0"] = asm["getTempRet0"];
var runPostSets = Module["runPostSets"] = asm["runPostSets"];
var setTempRet0 = Module["setTempRet0"] = asm["setTempRet0"];
var setThrew = Module["setThrew"] = asm["setThrew"];
var stackAlloc = Module["stackAlloc"] = asm["stackAlloc"];
var stackRestore = Module["stackRestore"] = asm["stackRestore"];
var stackSave = Module["stackSave"] = asm["stackSave"];
var dynCall_ii = Module["dynCall_ii"] = asm["dynCall_ii"];
var dynCall_iiii = Module["dynCall_iiii"] = asm["dynCall_iiii"];
var dynCall_viiiii = Module["dynCall_viiiii"] = asm["dynCall_viiiii"];
Module["asm"] = asm;
if (memoryInitializer) {
 if (!isDataURI(memoryInitializer)) {
  if (typeof Module["locateFile"] === "function") {
   memoryInitializer = Module["locateFile"](memoryInitializer);
  } else if (Module["memoryInitializerPrefixURL"]) {
   memoryInitializer = Module["memoryInitializerPrefixURL"] + memoryInitializer;
  }
 }
 if (ENVIRONMENT_IS_NODE || ENVIRONMENT_IS_SHELL) {
  var data = Module["readBinary"](memoryInitializer);
  HEAPU8.set(data, GLOBAL_BASE);
 } else {
  addRunDependency("memory initializer");
  var applyMemoryInitializer = (function(data) {
   if (data.byteLength) data = new Uint8Array(data);
   HEAPU8.set(data, GLOBAL_BASE);
   if (Module["memoryInitializerRequest"]) delete Module["memoryInitializerRequest"].response;
   removeRunDependency("memory initializer");
  });
  function doBrowserLoad() {
   Module["readAsync"](memoryInitializer, applyMemoryInitializer, (function() {
    throw "could not load memory initializer " + memoryInitializer;
   }));
  }
  var memoryInitializerBytes = tryParseAsDataURI(memoryInitializer);
  if (memoryInitializerBytes) {
   applyMemoryInitializer(memoryInitializerBytes.buffer);
  } else if (Module["memoryInitializerRequest"]) {
   function useRequest() {
    var request = Module["memoryInitializerRequest"];
    var response = request.response;
    if (request.status !== 200 && request.status !== 0) {
     var data = tryParseAsDataURI(Module["memoryInitializerRequestURL"]);
     if (data) {
      response = data.buffer;
     } else {
      console.warn("a problem seems to have happened with Module.memoryInitializerRequest, status: " + request.status + ", retrying " + memoryInitializer);
      doBrowserLoad();
      return;
     }
    }
    applyMemoryInitializer(response);
   }
   if (Module["memoryInitializerRequest"].response) {
    setTimeout(useRequest, 0);
   } else {
    Module["memoryInitializerRequest"].addEventListener("load", useRequest);
   }
  } else {
   doBrowserLoad();
  }
 }
}
function ExitStatus(status) {
 this.name = "ExitStatus";
 this.message = "Program terminated with exit(" + status + ")";
 this.status = status;
}
ExitStatus.prototype = new Error;
ExitStatus.prototype.constructor = ExitStatus;
var initialStackTop;
dependenciesFulfilled = function runCaller() {
 if (!Module["calledRun"]) run();
 if (!Module["calledRun"]) dependenciesFulfilled = runCaller;
};
function run(args) {
 args = args || Module["arguments"];
 if (runDependencies > 0) {
  return;
 }
 preRun();
 if (runDependencies > 0) return;
 if (Module["calledRun"]) return;
 function doRun() {
  if (Module["calledRun"]) return;
  Module["calledRun"] = true;
  if (ABORT) return;
  ensureInitRuntime();
  preMain();
  if (Module["onRuntimeInitialized"]) Module["onRuntimeInitialized"]();
  postRun();
 }
 if (Module["setStatus"]) {
  Module["setStatus"]("Running...");
  setTimeout((function() {
   setTimeout((function() {
    Module["setStatus"]("");
   }), 1);
   doRun();
  }), 1);
 } else {
  doRun();
 }
}
Module["run"] = run;
function exit(status, implicit) {
 if (implicit && Module["noExitRuntime"] && status === 0) {
  return;
 }
 if (Module["noExitRuntime"]) {} else {
  ABORT = true;
  EXITSTATUS = status;
  STACKTOP = initialStackTop;
  exitRuntime();
  if (Module["onExit"]) Module["onExit"](status);
 }
 if (ENVIRONMENT_IS_NODE) {
  process["exit"](status);
 }
 Module["quit"](status, new ExitStatus(status));
}
Module["exit"] = exit;
function abort(what) {
 if (Module["onAbort"]) {
  Module["onAbort"](what);
 }
 if (what !== undefined) {
  Module.print(what);
  Module.printErr(what);
  what = JSON.stringify(what);
 } else {
  what = "";
 }
 ABORT = true;
 EXITSTATUS = 1;
 throw "abort(" + what + "). Build with -s ASSERTIONS=1 for more info.";
}
Module["abort"] = abort;
if (Module["preInit"]) {
 if (typeof Module["preInit"] == "function") Module["preInit"] = [ Module["preInit"] ];
 while (Module["preInit"].length > 0) {
  Module["preInit"].pop()();
 }
}
Module["noExitRuntime"] = true;
run();




       return Module;
    })();
    
    var resultModule = global.Module || Module;

    resultModule._broadwayOnHeadersDecoded = par_broadwayOnHeadersDecoded;
    resultModule._broadwayOnPictureDecoded = par_broadwayOnPictureDecoded;
    
    return resultModule;
  };

  return (function(){
    "use strict";
  
  
  var nowValue = function(){
    return (new Date()).getTime();
  };
  
  if (typeof performance != "undefined"){
    if (performance.now){
      nowValue = function(){
        return performance.now();
      };
    };
  };
  
  
  var Decoder = function(parOptions){
    this.options = parOptions || {};
    
    this.now = nowValue;
    
    var asmInstance;
    
    var fakeWindow = {
    };
    
    var onPicFun = function ($buffer, width, height) {
      var buffer = this.pictureBuffers[$buffer];
      if (!buffer) {
        buffer = this.pictureBuffers[$buffer] = toU8Array($buffer, (width * height * 3) / 2);
      };
      
      var infos;
      var doInfo = false;
      if (this.infoAr.length){
        doInfo = true;
        infos = this.infoAr;
      };
      this.infoAr = [];
      
      if (this.options.rgb){
        if (!asmInstance){
          asmInstance = getAsm(width, height);
        };
        asmInstance.inp.set(buffer);
        asmInstance.doit();

        var copyU8 = new Uint8Array(asmInstance.outSize);
        copyU8.set( asmInstance.out );
        
        if (doInfo){
          infos[0].finishDecoding = nowValue();
        };
        
        this.onPictureDecoded(copyU8, width, height, infos);
        return;
        
      };
      
      if (doInfo){
        infos[0].finishDecoding = nowValue();
      };
      this.onPictureDecoded(buffer, width, height, infos);
    }.bind(this);
    
    var ignore = false;
    
    if (this.options.sliceMode){
      onPicFun = function ($buffer, width, height, $sliceInfo) {
        if (ignore){
          return;
        };
        var buffer = this.pictureBuffers[$buffer];
        if (!buffer) {
          buffer = this.pictureBuffers[$buffer] = toU8Array($buffer, (width * height * 3) / 2);
        };
        var sliceInfo = this.pictureBuffers[$sliceInfo];
        if (!sliceInfo) {
          sliceInfo = this.pictureBuffers[$sliceInfo] = toU32Array($sliceInfo, 18);
        };

        var infos;
        var doInfo = false;
        if (this.infoAr.length){
          doInfo = true;
          infos = this.infoAr;
        };
        this.infoAr = [];

        /*if (this.options.rgb){
        
        no rgb in slice mode

        };*/

        infos[0].finishDecoding = nowValue();
        var sliceInfoAr = [];
        for (var i = 0; i < 20; ++i){
          sliceInfoAr.push(sliceInfo[i]);
        };
        infos[0].sliceInfoAr = sliceInfoAr;

        this.onPictureDecoded(buffer, width, height, infos);
      }.bind(this);
    };
    
    var Module = getModule.apply(fakeWindow, [function () {
    }, onPicFun]);
    

    var HEAP8 = Module.HEAP8;
    var HEAPU8 = Module.HEAPU8;
    var HEAP16 = Module.HEAP16;
    var HEAP32 = Module.HEAP32;

    
    var MAX_STREAM_BUFFER_LENGTH = 1024 * 1024;
  
    // from old constructor
    Module._broadwayInit();
    
    /**
   * Creates a typed array from a HEAP8 pointer. 
   */
    function toU8Array(ptr, length) {
      return HEAPU8.subarray(ptr, ptr + length);
    };
    function toU32Array(ptr, length) {
      //var tmp = HEAPU8.subarray(ptr, ptr + (length * 4));
      return new Uint32Array(HEAPU8.buffer, ptr, length);
    };
    this.streamBuffer = toU8Array(Module._broadwayCreateStream(MAX_STREAM_BUFFER_LENGTH), MAX_STREAM_BUFFER_LENGTH);
    this.pictureBuffers = {};
    // collect extra infos that are provided with the nal units
    this.infoAr = [];
    
    this.onPictureDecoded = function (buffer, width, height, infos) {
      
    };
    
    /**
     * Decodes a stream buffer. This may be one single (unframed) NAL unit without the
     * start code, or a sequence of NAL units with framing start code prefixes. This
     * function overwrites stream buffer allocated by the codec with the supplied buffer.
     */
    
    var sliceNum = 0;
    if (this.options.sliceMode){
      sliceNum = this.options.sliceNum;
      
      this.decode = function decode(typedAr, parInfo, copyDoneFun) {
        this.infoAr.push(parInfo);
        parInfo.startDecoding = nowValue();
        var nals = parInfo.nals;
        var i;
        if (!nals){
          nals = [];
          parInfo.nals = nals;
          var l = typedAr.length;
          var foundSomething = false;
          var lastFound = 0;
          var lastStart = 0;
          for (i = 0; i < l; ++i){
            if (typedAr[i] === 1){
              if (
                typedAr[i - 1] === 0 &&
                typedAr[i - 2] === 0
              ){
                var startPos = i - 2;
                if (typedAr[i - 3] === 0){
                  startPos = i - 3;
                };
                // its a nal;
                if (foundSomething){
                  nals.push({
                    offset: lastFound,
                    end: startPos,
                    type: typedAr[lastStart] & 31
                  });
                };
                lastFound = startPos;
                lastStart = startPos + 3;
                if (typedAr[i - 3] === 0){
                  lastStart = startPos + 4;
                };
                foundSomething = true;
              };
            };
          };
          if (foundSomething){
            nals.push({
              offset: lastFound,
              end: i,
              type: typedAr[lastStart] & 31
            });
          };
        };
        
        var currentSlice = 0;
        var playAr;
        var offset = 0;
        for (i = 0; i < nals.length; ++i){
          if (nals[i].type === 1 || nals[i].type === 5){
            if (currentSlice === sliceNum){
              playAr = typedAr.subarray(nals[i].offset, nals[i].end);
              this.streamBuffer[offset] = 0;
              offset += 1;
              this.streamBuffer.set(playAr, offset);
              offset += playAr.length;
            };
            currentSlice += 1;
          }else{
            playAr = typedAr.subarray(nals[i].offset, nals[i].end);
            this.streamBuffer[offset] = 0;
            offset += 1;
            this.streamBuffer.set(playAr, offset);
            offset += playAr.length;
            Module._broadwayPlayStream(offset);
            offset = 0;
          };
        };
        copyDoneFun();
        Module._broadwayPlayStream(offset);
      };
      
    }else{
      this.decode = function decode(typedAr, parInfo) {
        // console.info("Decoding: " + buffer.length);
        // collect infos
        if (parInfo){
          this.infoAr.push(parInfo);
          parInfo.startDecoding = nowValue();
        };

        this.streamBuffer.set(typedAr);
        Module._broadwayPlayStream(typedAr.length);
      };
    };

  };

  
  Decoder.prototype = {
    
  };
  
  
  
  
  /*
  
    asm.js implementation of a yuv to rgb convertor
    provided by @soliton4
    
    based on 
    http://www.wordsaretoys.com/2013/10/18/making-yuv-conversion-a-little-faster/
  
  */
  
  
  // factory to create asm.js yuv -> rgb convertor for a given resolution
  var asmInstances = {};
  var getAsm = function(parWidth, parHeight){
    var idStr = "" + parWidth + "x" + parHeight;
    if (asmInstances[idStr]){
      return asmInstances[idStr];
    };

    var lumaSize = parWidth * parHeight;
    var chromaSize = (lumaSize|0) >> 2;

    var inpSize = lumaSize + chromaSize + chromaSize;
    var outSize = parWidth * parHeight * 4;
    var cacheSize = Math.pow(2, 24) * 4;
    var size = inpSize + outSize + cacheSize;

    var chunkSize = Math.pow(2, 24);
    var heapSize = chunkSize;
    while (heapSize < size){
      heapSize += chunkSize;
    };
    var heap = new ArrayBuffer(heapSize);

    var res = asmFactory(global, {}, heap);
    res.init(parWidth, parHeight);
    asmInstances[idStr] = res;

    res.heap = heap;
    res.out = new Uint8Array(heap, 0, outSize);
    res.inp = new Uint8Array(heap, outSize, inpSize);
    res.outSize = outSize;

    return res;
  }


  function asmFactory(stdlib, foreign, heap) {
    "use asm";

    var imul = stdlib.Math.imul;
    var min = stdlib.Math.min;
    var max = stdlib.Math.max;
    var pow = stdlib.Math.pow;
    var out = new stdlib.Uint8Array(heap);
    var out32 = new stdlib.Uint32Array(heap);
    var inp = new stdlib.Uint8Array(heap);
    var mem = new stdlib.Uint8Array(heap);
    var mem32 = new stdlib.Uint32Array(heap);

    // for double algo
    /*var vt = 1.370705;
    var gt = 0.698001;
    var gt2 = 0.337633;
    var bt = 1.732446;*/

    var width = 0;
    var height = 0;
    var lumaSize = 0;
    var chromaSize = 0;
    var inpSize = 0;
    var outSize = 0;

    var inpStart = 0;
    var outStart = 0;

    var widthFour = 0;

    var cacheStart = 0;


    function init(parWidth, parHeight){
      parWidth = parWidth|0;
      parHeight = parHeight|0;

      var i = 0;
      var s = 0;

      width = parWidth;
      widthFour = imul(parWidth, 4)|0;
      height = parHeight;
      lumaSize = imul(width|0, height|0)|0;
      chromaSize = (lumaSize|0) >> 2;
      outSize = imul(imul(width, height)|0, 4)|0;
      inpSize = ((lumaSize + chromaSize)|0 + chromaSize)|0;

      outStart = 0;
      inpStart = (outStart + outSize)|0;
      cacheStart = (inpStart + inpSize)|0;

      // initializing memory (to be on the safe side)
      s = ~~(+pow(+2, +24));
      s = imul(s, 4)|0;

      for (i = 0|0; ((i|0) < (s|0))|0; i = (i + 4)|0){
        mem32[((cacheStart + i)|0) >> 2] = 0;
      }
    }

    function doit(){
      var ystart = 0;
      var ustart = 0;
      var vstart = 0;

      var y = 0;
      var yn = 0;
      var u = 0;
      var v = 0;

      var o = 0;

      var line = 0;
      var col = 0;

      var usave = 0;
      var vsave = 0;

      var ostart = 0;
      var cacheAdr = 0;

      ostart = outStart|0;

      ystart = inpStart|0;
      ustart = (ystart + lumaSize|0)|0;
      vstart = (ustart + chromaSize)|0;

      for (line = 0; (line|0) < (height|0); line = (line + 2)|0){
        usave = ustart;
        vsave = vstart;
        for (col = 0; (col|0) < (width|0); col = (col + 2)|0){
          y = inp[ystart >> 0]|0;
          yn = inp[((ystart + width)|0) >> 0]|0;

          u = inp[ustart >> 0]|0;
          v = inp[vstart >> 0]|0;

          cacheAdr = (((((y << 16)|0) + ((u << 8)|0))|0) + v)|0;
          o = mem32[((cacheStart + cacheAdr)|0) >> 2]|0;
          if (o){}else{
            o = yuv2rgbcalc(y,u,v)|0;
            mem32[((cacheStart + cacheAdr)|0) >> 2] = o|0;
          };
          mem32[ostart >> 2] = o;

          cacheAdr = (((((yn << 16)|0) + ((u << 8)|0))|0) + v)|0;
          o = mem32[((cacheStart + cacheAdr)|0) >> 2]|0;
          if (o){}else{
            o = yuv2rgbcalc(yn,u,v)|0;
            mem32[((cacheStart + cacheAdr)|0) >> 2] = o|0;
          };
          mem32[((ostart + widthFour)|0) >> 2] = o;

          //yuv2rgb5(y, u, v, ostart);
          //yuv2rgb5(yn, u, v, (ostart + widthFour)|0);
          ostart = (ostart + 4)|0;

          // next step only for y. u and v stay the same
          ystart = (ystart + 1)|0;
          y = inp[ystart >> 0]|0;
          yn = inp[((ystart + width)|0) >> 0]|0;

          //yuv2rgb5(y, u, v, ostart);
          cacheAdr = (((((y << 16)|0) + ((u << 8)|0))|0) + v)|0;
          o = mem32[((cacheStart + cacheAdr)|0) >> 2]|0;
          if (o){}else{
            o = yuv2rgbcalc(y,u,v)|0;
            mem32[((cacheStart + cacheAdr)|0) >> 2] = o|0;
          };
          mem32[ostart >> 2] = o;

          //yuv2rgb5(yn, u, v, (ostart + widthFour)|0);
          cacheAdr = (((((yn << 16)|0) + ((u << 8)|0))|0) + v)|0;
          o = mem32[((cacheStart + cacheAdr)|0) >> 2]|0;
          if (o){}else{
            o = yuv2rgbcalc(yn,u,v)|0;
            mem32[((cacheStart + cacheAdr)|0) >> 2] = o|0;
          };
          mem32[((ostart + widthFour)|0) >> 2] = o;
          ostart = (ostart + 4)|0;

          //all positions inc 1

          ystart = (ystart + 1)|0;
          ustart = (ustart + 1)|0;
          vstart = (vstart + 1)|0;
        };
        ostart = (ostart + widthFour)|0;
        ystart = (ystart + width)|0;

      }

    }

    function yuv2rgbcalc(y, u, v){
      y = y|0;
      u = u|0;
      v = v|0;

      var r = 0;
      var g = 0;
      var b = 0;

      var o = 0;

      var a0 = 0;
      var a1 = 0;
      var a2 = 0;
      var a3 = 0;
      var a4 = 0;

      a0 = imul(1192, (y - 16)|0)|0;
      a1 = imul(1634, (v - 128)|0)|0;
      a2 = imul(832, (v - 128)|0)|0;
      a3 = imul(400, (u - 128)|0)|0;
      a4 = imul(2066, (u - 128)|0)|0;

      r = (((a0 + a1)|0) >> 10)|0;
      g = (((((a0 - a2)|0) - a3)|0) >> 10)|0;
      b = (((a0 + a4)|0) >> 10)|0;

      if ((((r & 255)|0) != (r|0))|0){
        r = min(255, max(0, r|0)|0)|0;
      };
      if ((((g & 255)|0) != (g|0))|0){
        g = min(255, max(0, g|0)|0)|0;
      };
      if ((((b & 255)|0) != (b|0))|0){
        b = min(255, max(0, b|0)|0)|0;
      };

      o = 255;
      o = (o << 8)|0;
      o = (o + b)|0;
      o = (o << 8)|0;
      o = (o + g)|0;
      o = (o << 8)|0;
      o = (o + r)|0;

      return o|0;

    }



    return {
      init: init,
      doit: doit
    }
  }

  
  /*
    potential worker initialization
  
  */
  
  
  if (typeof self != "undefined"){
    var isWorker = false;
    var decoder;
    var reuseMemory = false;
    var sliceMode = false;
    var sliceNum = 0;
    var sliceCnt = 0;
    var lastSliceNum = 0;
    var sliceInfoAr;
    var lastBuf;
    var awaiting = 0;
    var pile = [];
    var startDecoding;
    var finishDecoding;
    var timeDecoding;
    
    var memAr = [];
    var getMem = function(length){
      if (memAr.length){
        var u = memAr.shift();
        while (u && u.byteLength !== length){
          u = memAr.shift();
        };
        if (u){
          return u;
        };
      };
      return new ArrayBuffer(length);
    }; 
    
    var copySlice = function(source, target, infoAr, width, height){
      
      var length = width * height;
      var length4 = length / 4
      var plane2 = length;
      var plane3 = length + length4;
      
      var copy16 = function(parBegin, parEnd){
        var i = 0;
        for (i = 0; i < 16; ++i){
          var begin = parBegin + (width * i);
          var end = parEnd + (width * i)
          target.set(source.subarray(begin, end), begin);
        };
      };
      var copy8 = function(parBegin, parEnd){
        var i = 0;
        for (i = 0; i < 8; ++i){
          var begin = parBegin + ((width / 2) * i);
          var end = parEnd + ((width / 2) * i)
          target.set(source.subarray(begin, end), begin);
        };
      };
      var copyChunk = function(begin, end){
        target.set(source.subarray(begin, end), begin);
      };
      
      var begin = infoAr[0];
      var end = infoAr[1];
      if (end > 0){
        copy16(begin, end);
        copy8(infoAr[2], infoAr[3]);
        copy8(infoAr[4], infoAr[5]);
      };
      begin = infoAr[6];
      end = infoAr[7];
      if (end > 0){
        copy16(begin, end);
        copy8(infoAr[8], infoAr[9]);
        copy8(infoAr[10], infoAr[11]);
      };
      
      begin = infoAr[12];
      end = infoAr[15];
      if (end > 0){
        copyChunk(begin, end);
        copyChunk(infoAr[13], infoAr[16]);
        copyChunk(infoAr[14], infoAr[17]);
      };
      
    };
    
    var sliceMsgFun = function(){};
    
    var setSliceCnt = function(parSliceCnt){
      sliceCnt = parSliceCnt;
      lastSliceNum = sliceCnt - 1;
    };
    
    
    self.addEventListener('message', function(e) {
      
      if (isWorker){
        if (reuseMemory){
          if (e.data.reuse){
            memAr.push(e.data.reuse);
          };
        };
        if (e.data.buf){
          if (sliceMode && awaiting !== 0){
            pile.push(e.data);
          }else{
            decoder.decode(
              new Uint8Array(e.data.buf, e.data.offset || 0, e.data.length), 
              e.data.info, 
              function(){
                if (sliceMode && sliceNum !== lastSliceNum){
                  postMessage(e.data, [e.data.buf]);
                };
              }
            );
          };
          return;
        };
        
        if (e.data.slice){
          // update ref pic
          var copyStart = nowValue();
          copySlice(new Uint8Array(e.data.slice), lastBuf, e.data.infos[0].sliceInfoAr, e.data.width, e.data.height);
          // is it the one? then we need to update it
          if (e.data.theOne){
            copySlice(lastBuf, new Uint8Array(e.data.slice), sliceInfoAr, e.data.width, e.data.height);
            if (timeDecoding > e.data.infos[0].timeDecoding){
              e.data.infos[0].timeDecoding = timeDecoding;
            };
            e.data.infos[0].timeCopy += (nowValue() - copyStart);
          };
          // move on
          postMessage(e.data, [e.data.slice]);
          
          // next frame in the pipe?
          awaiting -= 1;
          if (awaiting === 0 && pile.length){
            var data = pile.shift();
            decoder.decode(
              new Uint8Array(data.buf, data.offset || 0, data.length), 
              data.info, 
              function(){
                if (sliceMode && sliceNum !== lastSliceNum){
                  postMessage(data, [data.buf]);
                };
              }
            );
          };
          return;
        };
        
        if (e.data.setSliceCnt){
          setSliceCnt(e.data.sliceCnt);
          return;
        };
        
      }else{
        if (e.data && e.data.type === "Broadway.js - Worker init"){
          isWorker = true;
          decoder = new Decoder(e.data.options);
          
          if (e.data.options.sliceMode){
            reuseMemory = true;
            sliceMode = true;
            sliceNum = e.data.options.sliceNum;
            setSliceCnt(e.data.options.sliceCnt);

            decoder.onPictureDecoded = function (buffer, width, height, infos) {
              
              // buffer needs to be copied because we give up ownership
              var copyU8 = new Uint8Array(getMem(buffer.length));
              copySlice(buffer, copyU8, infos[0].sliceInfoAr, width, height);
              
              startDecoding = infos[0].startDecoding;
              finishDecoding = infos[0].finishDecoding;
              timeDecoding = finishDecoding - startDecoding;
              infos[0].timeDecoding = timeDecoding;
              infos[0].timeCopy = 0;
              
              postMessage({
                slice: copyU8.buffer,
                sliceNum: sliceNum,
                width: width, 
                height: height, 
                infos: infos
              }, [copyU8.buffer]); // 2nd parameter is used to indicate transfer of ownership
              
              awaiting = sliceCnt - 1;
              
              lastBuf = buffer;
              sliceInfoAr = infos[0].sliceInfoAr;

            };
            
          }else if (e.data.options.reuseMemory){
            reuseMemory = true;
            decoder.onPictureDecoded = function (buffer, width, height, infos) {
              
              // buffer needs to be copied because we give up ownership
              var copyU8 = new Uint8Array(getMem(buffer.length));
              copyU8.set( buffer, 0, buffer.length );

              postMessage({
                buf: copyU8.buffer, 
                length: buffer.length,
                width: width, 
                height: height, 
                infos: infos
              }, [copyU8.buffer]); // 2nd parameter is used to indicate transfer of ownership

            };
            
          }else{
            decoder.onPictureDecoded = function (buffer, width, height, infos) {
              if (buffer) {
                buffer = new Uint8Array(buffer);
              };

              // buffer needs to be copied because we give up ownership
              var copyU8 = new Uint8Array(buffer.length);
              copyU8.set( buffer, 0, buffer.length );

              postMessage({
                buf: copyU8.buffer, 
                length: buffer.length,
                width: width, 
                height: height, 
                infos: infos
              }, [copyU8.buffer]); // 2nd parameter is used to indicate transfer of ownership

            };
          };
          postMessage({ consoleLog: "broadway worker initialized" });
        };
      };


    }, false);
  };
  
  Decoder.nowValue = nowValue;
  
  return Decoder;
  
  })();
  
  
}));

