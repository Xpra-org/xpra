// based on aurora-websocket.js https://github.com/fsbdev/aurora-websocket
// MIT licensed

(function() {
  var __hasProp = {}.hasOwnProperty,
    __extends = function(child, parent) { for (var key in parent) { if (__hasProp.call(parent, key)) child[key] = parent[key]; } function ctor() { this.constructor = child; } ctor.prototype = parent.prototype; child.prototype = new ctor(); child.__super__ = parent.prototype; return child; };

  AV.XpraSource = (function(_super) {
    __extends(XpraSource, _super);

    function XpraSource() {
      // constructor
    }

    XpraSource.prototype.start = function() {
      return true;
    };

    XpraSource.prototype.pause = function() {
      return true;
    };

    XpraSource.prototype.reset = function() {
      return true;
    };

    XpraSource.prototype._on_data = function(data) {
      var buf = new AV.Buffer(data);
      return this.emit('data', buf);
    };

    return XpraSource;

  })(AV.EventEmitter);

  AV.Asset.fromXpraSource = function() {
    var source;
    source = new AV.XpraSource();
    return new AV.Asset(source);
  };

  AV.Player.fromXpraSource = function() {
    var asset;
    asset = AV.Asset.fromXpraSource();
    return new AV.Player(asset);
  };

}).call(this);