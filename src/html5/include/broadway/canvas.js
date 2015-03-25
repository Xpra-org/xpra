/*
 * This file wraps several WebGL constructs and provides a simple, single texture based WebGLCanvas as well as a
 * specialized YUVWebGLCanvas that can handle YUV->RGB conversion. 
 */

/**
 * Represents a WebGL shader script.
 */
var Script = (function script() {
  function constructor() {}
  
  constructor.createFromElementId = function(id) {
    var script = document.getElementById(id);
    
    // Didn't find an element with the specified ID, abort.
    assert(script , "Could not find shader with ID: " + id);
    
    // Walk through the source element's children, building the shader source string.
    var source = "";
    var currentChild = script .firstChild;
    while(currentChild) {
      if (currentChild.nodeType == 3) {
        source += currentChild.textContent;
      }
      currentChild = currentChild.nextSibling;
    }
    
    var res = new constructor();
    res.type = script.type;
    res.source = source;
    return res;
  };
  
  constructor.createFromSource = function(type, source) {
    var res = new constructor();
    res.type = type;
    res.source = source;
    return res;
  }
  return constructor;
})();

/**
 * Represents a WebGL shader object and provides a mechanism to load shaders from HTML
 * script tags.
 */
var Shader = (function shader() {
  function constructor(gl, script) {
    
    // Now figure out what type of shader script we have, based on its MIME type.
    if (script.type == "x-shader/x-fragment") {
      this.shader = gl.createShader(gl.FRAGMENT_SHADER);
    } else if (script.type == "x-shader/x-vertex") {
      this.shader = gl.createShader(gl.VERTEX_SHADER);
    } else {
      error("Unknown shader type: " + script.type);
      return;
    }
    
    // Send the source to the shader object.
    gl.shaderSource(this.shader, script.source);
    
    // Compile the shader program.
    gl.compileShader(this.shader);
    
    // See if it compiled successfully.
    if (!gl.getShaderParameter(this.shader, gl.COMPILE_STATUS)) {
      error("An error occurred compiling the shaders: " + gl.getShaderInfoLog(this.shader));
      return;
    }
  }
  return constructor;
})();

var Program = (function () {
  function constructor(gl) {
    this.gl = gl;
    this.program = this.gl.createProgram();
  }
  constructor.prototype = {
    attach: function (shader) {
      this.gl.attachShader(this.program, shader.shader);
    }, 
    link: function () {
      this.gl.linkProgram(this.program);
      // If creating the shader program failed, alert.
      assert(this.gl.getProgramParameter(this.program, this.gl.LINK_STATUS),
             "Unable to initialize the shader program.");
    },
    use: function () {
      this.gl.useProgram(this.program);
    },
    getAttributeLocation: function(name) {
      return this.gl.getAttribLocation(this.program, name);
    },
    setMatrixUniform: function(name, array) {
      var uniform = this.gl.getUniformLocation(this.program, name);
      this.gl.uniformMatrix4fv(uniform, false, array);
    }
  };
  return constructor;
})();

/**
 * Represents a WebGL texture object.
 */
var Texture = (function texture() {
  function constructor(gl, size, format) {
    this.gl = gl;
    this.size = size;
    this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    this.format = format ? format : gl.LUMINANCE; 
    gl.texImage2D(gl.TEXTURE_2D, 0, this.format, size.w, size.h, 0, this.format, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }
  var textureIDs = null;
  constructor.prototype = {
    fill: function(textureData, useTexSubImage2D) {
      var gl = this.gl;
      assert(textureData.length >= this.size.w * this.size.h, 
             "Texture size mismatch, data:" + textureData.length + ", texture: " + this.size.w * this.size.h);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      if (useTexSubImage2D) {
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, this.size.w , this.size.h, this.format, gl.UNSIGNED_BYTE, textureData);
      } else {
        // texImage2D seems to be faster, thus keeping it as the default
        gl.texImage2D(gl.TEXTURE_2D, 0, this.format, this.size.w, this.size.h, 0, this.format, gl.UNSIGNED_BYTE, textureData);
      }
    },
    bind: function(n, program, name) {
      var gl = this.gl;
      if (!textureIDs) {
        textureIDs = [gl.TEXTURE0, gl.TEXTURE1, gl.TEXTURE2];
      }
      gl.activeTexture(textureIDs[n]);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.uniform1i(gl.getUniformLocation(program.program, name), n);
    }
  };
  return constructor; 
})();

/**
 * Generic WebGL backed canvas that sets up: a quad to paint a texture on, appropriate vertex/fragment shaders,
 * scene parameters and other things. Specialized versions of this class can be created by overriding several 
 * initialization methods.
 * 
 * <code>
 * var canvas = new WebGLCanvas(document.getElementById('canvas'), new Size(512, 512);
 * canvas.texture.fill(data);
 * canvas.drawScene();
 * </code>
 */
var WebGLCanvas = (function () {
  
  var vertexShaderScript = Script.createFromSource("x-shader/x-vertex", text([
    "attribute vec3 aVertexPosition;",
    "attribute vec2 aTextureCoord;",
    "uniform mat4 uMVMatrix;",
    "uniform mat4 uPMatrix;",
    "varying highp vec2 vTextureCoord;",
    "void main(void) {",
    "  gl_Position = uPMatrix * uMVMatrix * vec4(aVertexPosition, 1.0);",
    "  vTextureCoord = aTextureCoord;",
    "}"
    ]));
  
  var fragmentShaderScript = Script.createFromSource("x-shader/x-fragment", text([
    "precision highp float;",
    "varying highp vec2 vTextureCoord;",
    "uniform sampler2D texture;",
    "void main(void) {",
    "  gl_FragColor = texture2D(texture, vTextureCoord);",
    "}"
    ]));
  
  function constructor(canvas, size, useFrameBuffer) {
    this.canvas = canvas;
    this.size = size;
    this.canvas.width = size.w;
    this.canvas.height = size.h;
    
    this.onInitWebGL();
    this.onInitShaders();
    initBuffers.call(this);
    if (useFrameBuffer) {
      initFramebuffer.call(this);
    }
    this.onInitTextures();
    initScene.call(this);
  }

  /**
   * Initialize a frame buffer so that we can render off-screen.
   */
  function initFramebuffer() {
    var gl = this.gl;
    
    // Create framebuffer object and texture.
    this.framebuffer = gl.createFramebuffer(); 
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    this.framebufferTexture = new Texture(this.gl, this.size, gl.RGBA);

    // Create and allocate renderbuffer for depth data.
    var renderbuffer = gl.createRenderbuffer();
    gl.bindRenderbuffer(gl.RENDERBUFFER, renderbuffer);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, this.size.w, this.size.h);

    // Attach texture and renderbuffer to the framebuffer.
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.framebufferTexture.texture, 0);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, renderbuffer);
  }
  
  /**
   * Initialize vertex and texture coordinate buffers for a plane.
   */
  function initBuffers() {
    var tmp;
    var gl = this.gl;
    
    // Create vertex position buffer.
    this.quadVPBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadVPBuffer);
    tmp = [
       1.0,  1.0, 0.0,
      -1.0,  1.0, 0.0, 
       1.0, -1.0, 0.0, 
      -1.0, -1.0, 0.0];
    
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(tmp), gl.STATIC_DRAW);
    this.quadVPBuffer.itemSize = 3;
    this.quadVPBuffer.numItems = 4;
    
    /*
     +--------------------+ 
     | -1,1 (1)           | 1,1 (0)
     |                    |
     |                    |
     |                    |
     |                    |
     |                    |
     | -1,-1 (3)          | 1,-1 (2)
     +--------------------+
     */
    
    var scaleX = 1.0;
    var scaleY = 1.0;
    
    // Create vertex texture coordinate buffer.
    this.quadVTCBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadVTCBuffer);
    tmp = [
      scaleX, 0.0,
      0.0, 0.0,
      scaleX, scaleY,
      0.0, scaleY,
    ];
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(tmp), gl.STATIC_DRAW);
  }
  
  function mvIdentity() {
    this.mvMatrix = Matrix.I(4);
  }

  function mvMultiply(m) {
    this.mvMatrix = this.mvMatrix.x(m);
  }

  function mvTranslate(m) {
    mvMultiply.call(this, Matrix.Translation($V([m[0], m[1], m[2]])).ensure4x4());
  }
  
  function setMatrixUniforms() {
    this.program.setMatrixUniform("uPMatrix", new Float32Array(this.perspectiveMatrix.flatten()));
    this.program.setMatrixUniform("uMVMatrix", new Float32Array(this.mvMatrix.flatten()));
  }

  function initScene() {
    var gl = this.gl;
    
    // Establish the perspective with which we want to view the
    // scene. Our field of view is 45 degrees, with a width/height
    // ratio of 640:480, and we only want to see objects between 0.1 units
    // and 100 units away from the camera.
    
    this.perspectiveMatrix = makePerspective(45, 1, 0.1, 100.0);
    
    // Set the drawing position to the "identity" point, which is
    // the center of the scene.
    mvIdentity.call(this);
    
    // Now move the drawing position a bit to where we want to start
    // drawing the square.
    mvTranslate.call(this, [0.0, 0.0, -2.4]);

    // Draw the cube by binding the array buffer to the cube's vertices
    // array, setting attributes, and pushing it to GL.
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadVPBuffer);
    gl.vertexAttribPointer(this.vertexPositionAttribute, 3, gl.FLOAT, false, 0, 0);
    
    // Set the texture coordinates attribute for the vertices.
    
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quadVTCBuffer);
    gl.vertexAttribPointer(this.textureCoordAttribute, 2, gl.FLOAT, false, 0, 0);  
    
    this.onInitSceneTextures();
    
    setMatrixUniforms.call(this);
    
    if (this.framebuffer) {
      console.log("Bound Frame Buffer");
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
    }
  }
  
  constructor.prototype = {
    toString: function() {
      return "WebGLCanvas Size: " + this.size;
    },
    checkLastError: function (operation) {
      var err = this.gl.getError();
      if (err != this.gl.NO_ERROR) {
        var name = this.glNames[err];
        name = (name !== undefined) ? name + "(" + err + ")":
            ("Unknown WebGL ENUM (0x" + value.toString(16) + ")");
        if (operation) {
          console.log("WebGL Error: %s, %s", operation, name);
        } else {
          console.log("WebGL Error: %s", name);
        }
        console.trace();
      }
    },
    onInitWebGL: function () {
      try {
        this.gl = this.canvas.getContext("experimental-webgl");
      } catch(e) {}
      
      if (!this.gl) {
        error("Unable to initialize WebGL. Your browser may not support it.");
      }
      if (this.glNames) {
        return;
      }
      this.glNames = {};
      for (var propertyName in this.gl) {
        if (typeof this.gl[propertyName] == 'number') {
          this.glNames[this.gl[propertyName]] = propertyName;
        }
      }
    },
    onInitShaders: function() {
      this.program = new Program(this.gl);
      this.program.attach(new Shader(this.gl, vertexShaderScript));
      this.program.attach(new Shader(this.gl, fragmentShaderScript));
      this.program.link();
      this.program.use();
      this.vertexPositionAttribute = this.program.getAttributeLocation("aVertexPosition");
      this.gl.enableVertexAttribArray(this.vertexPositionAttribute);
      this.textureCoordAttribute = this.program.getAttributeLocation("aTextureCoord");;
      this.gl.enableVertexAttribArray(this.textureCoordAttribute);
    },
    onInitTextures: function () {
      var gl = this.gl;
      this.texture = new Texture(gl, this.size, gl.RGBA);
    },
    onInitSceneTextures: function () {
      this.texture.bind(0, this.program, "texture");
    },
    drawScene: function() {
      this.gl.drawArrays(this.gl.TRIANGLE_STRIP, 0, 4);
    },
    readPixels: function(buffer) {
      var gl = this.gl;
      gl.readPixels(0, 0, this.size.w, this.size.h, gl.RGBA, gl.UNSIGNED_BYTE, buffer);
    }
  };
  return constructor;
})();

var YUVWebGLCanvas = (function () {
  var vertexShaderScript = Script.createFromSource("x-shader/x-vertex", text([
    "attribute vec3 aVertexPosition;",
    "attribute vec2 aTextureCoord;",
    "uniform mat4 uMVMatrix;",
    "uniform mat4 uPMatrix;",
    "varying highp vec2 vTextureCoord;",
    "void main(void) {",
    "  gl_Position = uPMatrix * uMVMatrix * vec4(aVertexPosition, 1.0);",
    "  vTextureCoord = aTextureCoord;",
    "}"
  ]));
  
  var fragmentShaderScriptOld = Script.createFromSource("x-shader/x-fragment", text([
    "precision highp float;",
    "varying highp vec2 vTextureCoord;",
    "uniform sampler2D YTexture;",
    "uniform sampler2D UTexture;",
    "uniform sampler2D VTexture;",
    
    "void main(void) {",
    "  vec3 YUV = vec3",
    "  (",
    "    texture2D(YTexture, vTextureCoord).x * 1.1643828125,   // premultiply Y",
    "    texture2D(UTexture, vTextureCoord).x,",
    "    texture2D(VTexture, vTextureCoord).x",
    "  );",
    "  gl_FragColor = vec4",
    "  (",
    "    YUV.x + 1.59602734375 * YUV.z - 0.87078515625,",
    "    YUV.x - 0.39176171875 * YUV.y - 0.81296875 * YUV.z + 0.52959375,",
    "    YUV.x + 2.017234375   * YUV.y - 1.081390625,",
    "    1",
    "  );",
    "}"
  ]));
  
  var fragmentShaderScriptSimple = Script.createFromSource("x-shader/x-fragment", text([
   "precision highp float;",
   "varying highp vec2 vTextureCoord;",
   "uniform sampler2D YTexture;",
   "uniform sampler2D UTexture;",
   "uniform sampler2D VTexture;",
   
   "void main(void) {",
   "  gl_FragColor = texture2D(YTexture, vTextureCoord);",
   "}"
   ]));

  var fragmentShaderScript = Script.createFromSource("x-shader/x-fragment", text([
    "precision highp float;",
    "varying highp vec2 vTextureCoord;",
    "uniform sampler2D YTexture;",
    "uniform sampler2D UTexture;",
    "uniform sampler2D VTexture;",
    "const mat4 YUV2RGB = mat4",
    "(",
    " 1.1643828125, 0, 1.59602734375, -.87078515625,",
    " 1.1643828125, -.39176171875, -.81296875, .52959375,",
    " 1.1643828125, 2.017234375, 0, -1.081390625,",
    " 0, 0, 0, 1",
    ");",
  
    "void main(void) {",
    " gl_FragColor = vec4( texture2D(YTexture,  vTextureCoord).x, texture2D(UTexture, vTextureCoord).x, texture2D(VTexture, vTextureCoord).x, 1) * YUV2RGB;",
    "}"
  ]));
  
  
  function constructor(canvas, size) {
    WebGLCanvas.call(this, canvas, size);
  } 
  
  constructor.prototype = inherit(WebGLCanvas, {
    onInitShaders: function() {
      this.program = new Program(this.gl);
      this.program.attach(new Shader(this.gl, vertexShaderScript));
      this.program.attach(new Shader(this.gl, fragmentShaderScript));
      this.program.link();
      this.program.use();
      this.vertexPositionAttribute = this.program.getAttributeLocation("aVertexPosition");
      this.gl.enableVertexAttribArray(this.vertexPositionAttribute);
      this.textureCoordAttribute = this.program.getAttributeLocation("aTextureCoord");;
      this.gl.enableVertexAttribArray(this.textureCoordAttribute);
    },
    onInitTextures: function () {
      console.log("creatingTextures: size: " + this.size);
      this.YTexture = new Texture(this.gl, this.size);
      this.UTexture = new Texture(this.gl, this.size.getHalfSize());
      this.VTexture = new Texture(this.gl, this.size.getHalfSize());
    },
    onInitSceneTextures: function () {
      this.YTexture.bind(0, this.program, "YTexture");
      this.UTexture.bind(1, this.program, "UTexture");
      this.VTexture.bind(2, this.program, "VTexture");
    },
    fillYUVTextures: function(y, u, v) {
      this.YTexture.fill(y);
      this.UTexture.fill(u);
      this.VTexture.fill(v);
    },
    toString: function() {
      return "YUVCanvas Size: " + this.size;
    }
  });
  
  return constructor;
})(); 


var FilterWebGLCanvas = (function () {
  var vertexShaderScript = Script.createFromSource("x-shader/x-vertex", text([
    "attribute vec3 aVertexPosition;",
    "attribute vec2 aTextureCoord;",
    "uniform mat4 uMVMatrix;",
    "uniform mat4 uPMatrix;",
    "varying highp vec2 vTextureCoord;",
    "void main(void) {",
    "  gl_Position = uPMatrix * uMVMatrix * vec4(aVertexPosition, 1.0);",
    "  vTextureCoord = aTextureCoord;",
    "}"
  ]));

  var fragmentShaderScript = Script.createFromSource("x-shader/x-fragment", text([
    "precision highp float;",
    "varying highp vec2 vTextureCoord;",
    "uniform sampler2D FTexture;",
    
    "void main(void) {",
    " gl_FragColor = texture2D(FTexture,  vTextureCoord);",
    "}"
  ]));
  
  
  function constructor(canvas, size, useFrameBuffer) {
    WebGLCanvas.call(this, canvas, size, useFrameBuffer);
  } 
  
  constructor.prototype = inherit(WebGLCanvas, {
    onInitShaders: function() {
      this.program = new Program(this.gl);
      this.program.attach(new Shader(this.gl, vertexShaderScript));
      this.program.attach(new Shader(this.gl, fragmentShaderScript));
      this.program.link();
      this.program.use();
      this.vertexPositionAttribute = this.program.getAttributeLocation("aVertexPosition");
      this.gl.enableVertexAttribArray(this.vertexPositionAttribute);
      this.textureCoordAttribute = this.program.getAttributeLocation("aTextureCoord");
      this.gl.enableVertexAttribArray(this.textureCoordAttribute);
    },
    onInitTextures: function () {
      console.log("creatingTextures: size: " + this.size);
      this.FTexture = new Texture(this.gl, this.size, this.gl.RGBA);
    },
    onInitSceneTextures: function () {
      this.FTexture.bind(0, this.program, "FTexture");
    },
    process: function(buffer, output) {
      this.FTexture.fill(buffer);
      this.drawScene();
      this.readPixels(output);
    },
    toString: function() {
      return "FilterWebGLCanvas Size: " + this.size;
    }
  });
  
  return constructor;
})(); 