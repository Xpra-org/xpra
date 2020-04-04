/*
 * Copyright (c) 2016 Antoine Martin <antoine@xpra.org>
 * Licensed under MPL 2.0
 *
 */
'use strict';

const MediaSourceConstants = {

		CODEC_DESCRIPTION : {
				"mp4a"			: 'mpeg4: aac',
				"aac+mpeg4"		: 'mpeg4: aac',
				"mp3"			: 'mp3',
				"mp3+id3v2"		: 'mp3',
				"mp3+mpeg4"		: 'mpeg4: mp3',
				"wav"			: 'wav',
				"wave"			: 'wave',
				"flac"			: 'flac',
				"opus"			: 'opus',
				"vorbis"		: 'vorbis',
				"opus+mka"		: 'webm: opus',
				"opus+ogg"		: 'ogg: opus',
				"vorbis+mka"	: 'webm: vorbis',
				"vorbis+ogg"	: 'ogg: vorbis',
				"speex+ogg"		: 'ogg: speex',
				"flac+ogg"		: 'ogg: flac',
		},

		CODEC_STRING : {
			"aac+mpeg4"		: 'audio/mp4; codecs="mp4a.40.2"',
			//"aac+mpeg4"		: 'audio/mp4; codecs="aac51"',
			//"aac+mpeg4"		: 'audio/aac',
			"mp3"			: "audio/mpeg",
			"mp3+mpeg4"		: 'audio/mp4; codecs="mp3"',
			//"mp3"			: "audio/mp3",
			"ogg"			: "audio/ogg",
			//"wave"		: 'audio/wave',
			//"wav"			: 'audio/wav; codec="1"',
			"wav"			: 'audio/wav',
			"flac"			: 'audio/flac',
			"opus+mka"		: 'audio/webm; codecs="opus"',
			"vorbis+mka"	: 'audio/webm; codecs="vorbis"',
			"vorbis+ogg"	: 'audio/ogg; codecs="vorbis"',
			"speex+ogg"		: 'audio/ogg; codecs="speex"',
			"flac+ogg"		: 'audio/ogg; codecs="flac"',
			"opus+ogg"		: 'audio/ogg; codecs="opus"',
		},

		PREFERRED_CODEC_ORDER : [
			"opus+mka", "vorbis+mka",
			"opus+ogg", "vorbis+ogg",
			"opus", "vorbis",
			"speex+ogg", "flac+ogg",
			"aac+mpeg4", "mp3+mpeg4",
			"mp3", "mp3+id3v2", "flac", "wav", "wave",
		],

		H264_PROFILE_CODE : {
				//"baseline"	: "42E0",
				"baseline"	: "42C0",
				"main"		: "4D40",
				"high"		: "6400",
				"extended"	: "58A0",
		},

		H264_LEVEL_CODE : {
				"3.0"		: "1E",
				"3.1"		: "1F",
				"4.1"		: "29",
				"5.1"		: "33",
		},

		READY_STATE : {
			0	: "NOTHING",
			1	: "METADATA",
			2	: "CURRENT DATA",
			3	: "FUTURE DATA",
			4	: "ENOUGH DATA",
		},

		NETWORK_STATE : {
			0	: "EMPTY",
			1	: "IDLE",
			2	: "LOADING",
			3	: "NO_SOURCE",
		},

		ERROR_CODE : {
			1	: "ABORTED: fetching process aborted by user",
			2	: "NETWORK: error occurred when downloading",
			3 	: "DECODE: error occurred when decoding",
			4 	: "SRC_NOT_SUPPORTED",
		},

		AURORA_CODECS : {
			"wav"	: "lpcm",
			"mp3+id3v2"	: "mp3",
			"flac"	: "flac",
			"aac+mpeg4"	: "mp4a",
		}
};


const MediaSourceUtil = {

		getMediaSourceClass : function() {
			return window.MediaSource || window.WebKitMediaSource;
		},

		getMediaSource : function() {
			const ms = MediaSourceUtil.getMediaSourceClass();
			if(!ms) {
				throw new Error("no MediaSource support!");
			}
			return new ms();
		},

		getAuroraAudioCodecs : function() {
			//IE is totally useless:
			if(Utilities.isIE()) {
				return {};
			}
			const codecs_supported = {};
			if(AV && AV.Decoder && AV.Decoder.find) {
				for (const codec_option in MediaSourceConstants.AURORA_CODECS) {
					const codec_string = MediaSourceConstants.AURORA_CODECS[codec_option];
					const decoder = AV.Decoder.find(codec_string);
					if(decoder) {
						Utilities.log("audio codec aurora OK  '"+codec_option+"' / '"+codec_string+"'");
						codecs_supported[codec_option] = codec_string;
					}
					else {
						Utilities.log("audio codec aurora NOK '"+codec_option+"' / '"+codec_string+"'");
					}
				}
			}
			return codecs_supported;
		},

		getMediaSourceAudioCodecs : function(ignore_blacklist) {
			const media_source_class = MediaSourceUtil.getMediaSourceClass();
			if(!media_source_class) {
				Utilities.log("audio forwarding: no media source API support");
				return [];
			}
			//IE is totally useless:
			if(Utilities.isIE()) {
				return [];
			}
			const codecs_supported = [];
			for (const codec_option in MediaSourceConstants.CODEC_STRING) {
				const codec_string = MediaSourceConstants.CODEC_STRING[codec_option];
				try {
					if(!media_source_class.isTypeSupported(codec_string)) {
						Utilities.log("audio codec MediaSource NOK: '"+codec_option+"' / '"+codec_string+"'");
						//add whitelisting here?
						continue;
					}
					let blacklist = [];
					if (Utilities.isFirefox() || Utilities.isSafari()) {
						blacklist += ["opus+mka", "vorbis+mka"];
						if (Utilities.isSafari()) {
							//this crashes Safari!
							blacklist += ["wav", ];
						}
					}
					else if (Utilities.isChrome()) {
						blacklist = ["aac+mpeg4"];
						if (Utilities.isMacOS()) {
							blacklist += ["opus+mka"];
						}
					}
					if(blacklist.includes(codec_option)) {
						Utilities.log("audio codec MediaSource '"+codec_option+"' / '"+codec_string+"' is blacklisted for "+navigator.userAgent);
						if(ignore_blacklist) {
							Utilities.log("blacklist overruled!");
						}
						else {
							continue;
						}
					}
					codecs_supported[codec_option] = codec_string;
					Utilities.log("audio codec MediaSource OK  '"+codec_option+"' / '"+codec_string+"'");
				}
				catch (e) {
					Utilities.error("audio error probing codec '"+codec_string+"' / '"+codec_string+"': "+e);
				}
			}
			Utilities.log("getMediaSourceAudioCodecs(", ignore_blacklist, ")=", codecs_supported);
			return codecs_supported;
		},

		getSupportedAudioCodecs : function() {
			const codecs_supported = MediaSourceUtil.getMediaSourceAudioCodecs();
			const aurora_codecs = MediaSourceUtil.getAuroraAudioCodecs();
			for (const codec_option in aurora_codecs) {
				if(codec_option in codecs_supported) {
					//we already have native MediaSource support!
					continue;
				}
				codecs_supported[codec_option] = aurora_codecs[codec_option];
			}
			return codecs_supported;
		},

		getDefaultAudioCodec : function(codecs) {
			if(!codecs) {
				return null;
			}
			const codec_options = Object.keys(codecs);
			for (let i = 0; i < MediaSourceConstants.PREFERRED_CODEC_ORDER.length; i++) {
				const codec_option = MediaSourceConstants.PREFERRED_CODEC_ORDER[i];
				if(codec_options.includes(codec_option)) {
					return codec_option;
				}
			}
			return Object.keys(codecs)[0];
		},

		addMediaSourceEventDebugListeners : function(media_source, source_type) {
			function debug_source_event(event) {
				let msg = ""+source_type+" source "+event;
				try {
					msg += ": "+media_source.readyState;
				}
				catch (e) {
					//don't care
				}
				console.debug(msg);
			}
			media_source.addEventListener('sourceopen', 	function(e) { debug_source_event('open');  });
			media_source.addEventListener('sourceended', 	function(e) { debug_source_event('ended'); });
			media_source.addEventListener('sourceclose', 	function(e) { debug_source_event('close'); });
			media_source.addEventListener('error', 			function(e) { debug_source_event('error'); });
		},

		addMediaElementEventDebugListeners : function(media_element, element_type) {
			function debug_me_event(event) {
				console.debug(""+element_type+" "+event);
			}
			media_element.addEventListener('waiting', 			function() { debug_me_event("waiting"); });
			media_element.addEventListener('stalled', 			function() { debug_me_event("stalled"); });
			media_element.addEventListener('playing', 			function() { debug_me_event("playing"); });
			media_element.addEventListener('loadstart', 		function() { debug_me_event("loadstart"); });
			media_element.addEventListener('loadedmetadata', 	function() { debug_me_event("loadedmetadata"); });
			media_element.addEventListener('loadeddata', 		function() { debug_me_event("loadeddata"); });
			media_element.addEventListener('error', 			function() { debug_me_event("error"); });
			media_element.addEventListener('canplay', 			function() { debug_me_event("canplay"); });
			media_element.addEventListener('play', 			function() { debug_me_event("play"); });
		},

		addSourceBufferEventDebugListeners : function(asb, element_type) {
			function debug_buffer_event(event) {
				const msg = ""+element_type+" buffer "+event;
				console.debug(msg);
			}
			asb.addEventListener('updatestart', function(e) { debug_buffer_event('updatestart'); });
			asb.addEventListener('updateend', 	function(e) { debug_buffer_event('updateend'); });
			asb.addEventListener('error', 		function(e) { debug_buffer_event('error'); });
			asb.addEventListener('abort', 		function(e) { debug_buffer_event('abort'); });
		},

		get_supported_codecs : function(mediasource, aurora, http, ignore_audio_blacklist) {
			const codecs_supported = {};
			if (mediasource) {
				const mediasource_codecs = MediaSourceUtil.getMediaSourceAudioCodecs(ignore_audio_blacklist);
				for (const codec_option in mediasource_codecs) {
					codecs_supported["mediasource:"+codec_option] = MediaSourceConstants.CODEC_DESCRIPTION[codec_option];
				}
			}
			if (aurora) {
				const aurora_codecs = MediaSourceUtil.getAuroraAudioCodecs();
				for (const codec_option in aurora_codecs) {
					if(codec_option in codecs_supported) {
						//we already have native MediaSource support!
						continue;
					}
					codecs_supported["aurora:"+codec_option] = "legacy: "+MediaSourceConstants.CODEC_DESCRIPTION[codec_option];
				}
			}
			if (http) {
				const stream_codecs = ["mp3"];
				for (const i in stream_codecs) {
					const codec_option = stream_codecs[i];
					console.log("stream codecs=", stream_codecs, "codec=", codec_option);
					codecs_supported["http-stream:"+codec_option] = "http stream: "+MediaSourceConstants.CODEC_DESCRIPTION[codec_option];
				}
			}
			return codecs_supported;
		},

		get_best_codec : function(codecs_supported) {
			let best_codec = null;
			let best_distance = MediaSourceConstants.PREFERRED_CODEC_ORDER.length;
			for (const codec_option in codecs_supported) {
				const cs = codec_option.split(":")[1];
				const distance = MediaSourceConstants.PREFERRED_CODEC_ORDER.indexOf(cs);
				if (distance>=0 && distance<best_distance) {
					best_codec = codec_option;
					best_distance = distance;
				}
			}
			return best_codec;
		},
};
