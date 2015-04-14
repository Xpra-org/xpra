'use strict';

function error(message) {
  console.error(message);
  console.trace();
}

function assert(condition, message) {
  if (!condition) {
    error(message);
  }
}

function isPowerOfTwo(x) {
  return (x & (x - 1)) == 0;
}

/**
 * Joins a list of lines using a newline separator, not the fastest
 * thing in the world but good enough for initialization code. 
 */
function text(lines) {
  return lines.join("\n");
}

/**
 * Rounds up to the next highest power of two.
 */
function nextHighestPowerOfTwo(x) {
  --x;
  for (var i = 1; i < 32; i <<= 1) {
      x = x | x >> i;
  }
  return x + 1;
}

/**
 * Represents a 2-dimensional size value. 
 */
var Size = (function size() {
  function constructor(w, h) {
    this.w = w;
    this.h = h;
  }
  constructor.prototype = {
    toString: function () {
      return "(" + this.w + ", " + this.h + ")";
    },
    getHalfSize: function() {
      return new Size(this.w >>> 1, this.h >>> 1);
    },
    length: function() {
      return this.w * this.h;
    }
  }
  return constructor;
})();

/**
 * Creates a new prototype object derived from another objects prototype along with a list of additional properties.
 *
 * @param base object whose prototype to use as the created prototype object's prototype
 * @param properties additional properties to add to the created prototype object
 */
function inherit(base, properties) {
  var prot = Object.create(base.prototype);
  for (var p in properties) {
    prot[p] = properties[p];
  }
  return prot;
}