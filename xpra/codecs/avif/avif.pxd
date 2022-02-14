# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport uint8_t, uint32_t, uint64_t, uintptr_t   #pylint: disable=syntax-error

DEF AVIF_PLANE_COUNT_YUV = 3


cdef extern from "avif/avif.h":
    int AVIF_VERSION_MAJOR
    int AVIF_VERSION_MINOR
    int AVIF_VERSION_PATCH

    ctypedef int avifBool

    ctypedef enum avifPlanesFlags:
        AVIF_PLANES_YUV
        AVIF_PLANES_A
        AVIF_PLANES_ALL

    ctypedef enum avifChannelIndex:
        AVIF_CHAN_R
        AVIF_CHAN_G
        AVIF_CHAN_B

        AVIF_CHAN_Y
        AVIF_CHAN_U
        AVIF_CHAN_V

    ctypedef struct avifROData:
        const uint8_t * data
        size_t size

    ctypedef struct avifRWData:
        uint8_t * data
        size_t size

    ctypedef enum avifPixelFormat:
        AVIF_PIXEL_FORMAT_NONE
        AVIF_PIXEL_FORMAT_YUV444
        AVIF_PIXEL_FORMAT_YUV422
        AVIF_PIXEL_FORMAT_YUV420
        AVIF_PIXEL_FORMAT_YUV400

    ctypedef struct avifPixelFormatInfo:
        avifBool monochrome
        int chromaShiftX
        int chromaShiftY

    ctypedef enum avifChromaSamplePosition:
        AVIF_CHROMA_SAMPLE_POSITION_UNKNOWN
        AVIF_CHROMA_SAMPLE_POSITION_VERTICAL
        AVIF_CHROMA_SAMPLE_POSITION_COLOCATED

    ctypedef enum avifRange:
        AVIF_RANGE_LIMITED = 0,
        AVIF_RANGE_FULL = 1

    ctypedef enum avifColorPrimaries:
        AVIF_COLOR_PRIMARIES_UNKNOWN
        AVIF_COLOR_PRIMARIES_BT709
        AVIF_COLOR_PRIMARIES_IEC61966_2_4
        AVIF_COLOR_PRIMARIES_UNSPECIFIED
        AVIF_COLOR_PRIMARIES_BT470M
        AVIF_COLOR_PRIMARIES_BT470BG
        AVIF_COLOR_PRIMARIES_BT601
        AVIF_COLOR_PRIMARIES_SMPTE240
        AVIF_COLOR_PRIMARIES_GENERIC_FILM
        AVIF_COLOR_PRIMARIES_BT2020
        AVIF_COLOR_PRIMARIES_XYZ
        AVIF_COLOR_PRIMARIES_SMPTE431
        AVIF_COLOR_PRIMARIES_SMPTE432
        AVIF_COLOR_PRIMARIES_EBU3213

    ctypedef enum avifTransferCharacteristics:
        AVIF_TRANSFER_CHARACTERISTICS_UNKNOWN
        AVIF_TRANSFER_CHARACTERISTICS_BT709
        AVIF_TRANSFER_CHARACTERISTICS_UNSPECIFIED
        AVIF_TRANSFER_CHARACTERISTICS_BT470M
        AVIF_TRANSFER_CHARACTERISTICS_BT470BG
        AVIF_TRANSFER_CHARACTERISTICS_BT601
        AVIF_TRANSFER_CHARACTERISTICS_SMPTE240
        AVIF_TRANSFER_CHARACTERISTICS_LINEAR
        AVIF_TRANSFER_CHARACTERISTICS_LOG100
        AVIF_TRANSFER_CHARACTERISTICS_LOG100_SQRT10
        AVIF_TRANSFER_CHARACTERISTICS_IEC61966
        AVIF_TRANSFER_CHARACTERISTICS_BT1361
        AVIF_TRANSFER_CHARACTERISTICS_SRGB
        AVIF_TRANSFER_CHARACTERISTICS_BT2020_10BIT
        AVIF_TRANSFER_CHARACTERISTICS_BT2020_12BIT
        AVIF_TRANSFER_CHARACTERISTICS_SMPTE2084
        AVIF_TRANSFER_CHARACTERISTICS_SMPTE428
        AVIF_TRANSFER_CHARACTERISTICS_HLG

    ctypedef enum avifMatrixCoefficients:
        AVIF_MATRIX_COEFFICIENTS_IDENTITY
        AVIF_MATRIX_COEFFICIENTS_BT709
        AVIF_MATRIX_COEFFICIENTS_UNSPECIFIED
        AVIF_MATRIX_COEFFICIENTS_FCC
        AVIF_MATRIX_COEFFICIENTS_BT470BG
        AVIF_MATRIX_COEFFICIENTS_BT601
        AVIF_MATRIX_COEFFICIENTS_SMPTE240
        AVIF_MATRIX_COEFFICIENTS_YCGCO
        AVIF_MATRIX_COEFFICIENTS_BT2020_NCL
        AVIF_MATRIX_COEFFICIENTS_BT2020_CL
        AVIF_MATRIX_COEFFICIENTS_SMPTE2085
        AVIF_MATRIX_COEFFICIENTS_CHROMA_DERIVED_NCL
        AVIF_MATRIX_COEFFICIENTS_CHROMA_DERIVED_CL
        AVIF_MATRIX_COEFFICIENTS_ICTCP

    ctypedef enum avifTransformationFlags:
        AVIF_TRANSFORM_NONE
        AVIF_TRANSFORM_PASP
        AVIF_TRANSFORM_CLAP
        AVIF_TRANSFORM_IROT
        AVIF_TRANSFORM_IMIR

    ctypedef struct avifPixelAspectRatioBox:
        uint32_t hSpacing
        uint32_t vSpacing

    ctypedef struct avifCleanApertureBox:
        uint32_t widthN
        uint32_t widthD
        #a fractional number which defines the exact clean aperture height, in counted pixels, of the video image
        uint32_t heightN
        uint32_t heightD
        #a fractional number which defines the horizontal offset of clean aperture centre minus (width-1)/2. Typically 0.
        uint32_t horizOffN
        uint32_t horizOffD
        #a fractional number which defines the vertical offset of clean aperture centre minus (height-1)/2. Typically 0.
        uint32_t vertOffN
        uint32_t vertOffD

    ctypedef struct avifImageRotation:
        uint8_t angle

    ctypedef struct avifImageMirror:
        # 0: Mirror about a vertical axis ("left-to-right")
        # 1: Mirror about a horizontal axis ("top-to-bottom")
        uint8_t axis

    ctypedef struct avifImage:
        uint32_t width
        uint32_t height
        uint32_t depth      #all planes must share this depth; if depth>8, all planes are uint16_t internally

        avifPixelFormat yuvFormat
        avifRange yuvRange
        avifChromaSamplePosition yuvChromaSamplePosition
        uint8_t * yuvPlanes[AVIF_PLANE_COUNT_YUV]
        uint32_t yuvRowBytes[AVIF_PLANE_COUNT_YUV]
        avifBool imageOwnsYUVPlanes

        avifRange alphaRange
        uint8_t * alphaPlane
        uint32_t alphaRowBytes
        avifBool imageOwnsAlphaPlane
        avifBool alphaPremultiplied

        #ICC Profile
        avifRWData icc

        #CICP information:
        #These are stored in the AV1 payload and used to signal YUV conversion. Additionally, if an
        #ICC profile is not specified, these will be stored in the AVIF container's `colr` box with
        #a type of `nclx`. If your system supports ICC profiles, be sure to check for the existence
        #of one (avifImage.icc) before relying on the values listed here!
        avifColorPrimaries colorPrimaries
        avifTransferCharacteristics transferCharacteristics
        avifMatrixCoefficients matrixCoefficients

        #Transformations - These metadata values are encoded/decoded when transformFlags are set
        #appropriately, but do not impact/adjust the actual pixel buffers used (images won't be
        #pre-cropped or mirrored upon decode). Basic explanations from the standards are offered in
        #comments above, but for detailed explanations, please refer to the HEIF standard (ISO/IEC
        #23008-12:2017) and the BMFF standard (ISO/IEC 14496-12:2015).
        #To encode any of these boxes, set the values in the associated box, then enable the flag in
        #transformFlags. On decode, only honor the values in boxes with the associated transform flag set.
        uint32_t transformFlags
        avifPixelAspectRatioBox pasp
        avifCleanApertureBox clap
        avifImageRotation irot
        avifImageMirror imir
        #Metadata - set with avifImageSetMetadata*() before write, check .size>0 for existence after read
        avifRWData exif
        avifRWData xmp

    ctypedef enum avifRGBFormat:
        AVIF_RGB_FORMAT_RGB
        AVIF_RGB_FORMAT_RGBA    #This is the default format set in avifRGBImageSetDefaults().
        AVIF_RGB_FORMAT_ARGB
        AVIF_RGB_FORMAT_BGR
        AVIF_RGB_FORMAT_BGRA
        AVIF_RGB_FORMAT_ABGR

    void avifGetPixelFormatInfo(avifPixelFormat format, avifPixelFormatInfo * info)
    const char * avifPixelFormatToString(avifPixelFormat format)

    void * avifAlloc(size_t size)
    void avifFree(void * p)

    void avifRWDataRealloc(avifRWData * raw, size_t newSize)
    void avifRWDataSet(avifRWData * raw, const uint8_t * data, size_t len)
    void avifRWDataFree(avifRWData * raw)

    const char * avifResultToString(avifResult result)


    avifImage * avifImageCreate(int width, int height, int depth, avifPixelFormat yuvFormat)
    avifImage * avifImageCreateEmpty()  # helper for making an image to decode into
    void avifImageCopy(avifImage * dstImage, const avifImage * srcImage, uint32_t planes)   #deep copy
    void avifImageDestroy(avifImage * image)

    void avifImageSetProfileICC(avifImage * image, const uint8_t * icc, size_t iccSize)

    #Warning: If the Exif payload is set and invalid, avifEncoderWrite() may return AVIF_RESULT_INVALID_EXIF_PAYLOAD
    void avifImageSetMetadataExif(avifImage * image, const uint8_t * exif, size_t exifSize)
    void avifImageSetMetadataXMP(avifImage * image, const uint8_t * xmp, size_t xmpSize)

    void avifImageAllocatePlanes(avifImage * image, uint32_t planes)    #Ignores any pre-existing planes
    void avifImageFreePlanes(avifImage * image, uint32_t planes)        #Ignores already-freed planes
    void avifImageStealPlanes(avifImage * dstImage, avifImage * srcImage, uint32_t planes)

    uint32_t avifRGBFormatChannelCount(avifRGBFormat format)
    avifBool avifRGBFormatHasAlpha(avifRGBFormat format)

    ctypedef enum avifChromaUpsampling:
        AVIF_CHROMA_UPSAMPLING_AUTOMATIC
        AVIF_CHROMA_UPSAMPLING_FASTEST
        AVIF_CHROMA_UPSAMPLING_BEST_QUALITY
        AVIF_CHROMA_UPSAMPLING_NEAREST
        AVIF_CHROMA_UPSAMPLING_BILINEAR

    ctypedef struct avifRGBImage:
        uint32_t width          #must match associated avifImage
        uint32_t height         #must match associated avifImage
        uint32_t depth          #legal depths [8, 10, 12, 16]. if depth>8, pixels must be uint16_t internally
        avifRGBFormat format    #all channels are always full range
        avifChromaUpsampling chromaUpsampling   # Defaults to AVIF_CHROMA_UPSAMPLING_AUTOMATIC: How to upsample non-4:4:4 UV (ignored for 444) when converting to RGB.
                                                # Unused when converting to YUV. avifRGBImageSetDefaults() prefers quality over speed.
        avifBool ignoreAlpha    #Used for XRGB formats, treats formats containing alpha (such as ARGB) as if they were
                                #RGB, treating the alpha bits as if they were all 1.
        avifBool alphaPremultiplied #indicates if RGB value is pre-multiplied by alpha. Default: false
        uint8_t * pixels
        uint32_t rowBytes

    void avifRGBImageSetDefaults(avifRGBImage * rgb, const avifImage * image)
    uint32_t avifRGBImagePixelSize(const avifRGBImage * rgb)

    # Convenience functions. If you supply your own pixels/rowBytes, you do not need to use these.
    void avifRGBImageAllocatePixels(avifRGBImage * rgb)
    void avifRGBImageFreePixels(avifRGBImage * rgb)

    #The main conversion functions
    avifResult avifImageRGBToYUV(avifImage * image, const avifRGBImage * rgb)
    avifResult avifImageYUVToRGB(const avifImage * image, avifRGBImage * rgb)

    #Premultiply handling functions.
    #(Un)premultiply is automatically done by the main conversion functions above,
    #so usually you don't need to call these. They are there for convenience.
    avifResult avifRGBImagePremultiplyAlpha(avifRGBImage * rgb)
    avifResult avifRGBImageUnpremultiplyAlpha(avifRGBImage * rgb)

    int avifFullToLimitedY(int depth, int v)
    int avifFullToLimitedUV(int depth, int v)
    int avifLimitedToFullY(int depth, int v)
    int avifLimitedToFullUV(int depth, int v)

    ctypedef enum avifCodecChoice:
        AVIF_CODEC_CHOICE_AUTO
        AVIF_CODEC_CHOICE_AOM
        AVIF_CODEC_CHOICE_DAV1D
        AVIF_CODEC_CHOICE_LIBGAV1
        AVIF_CODEC_CHOICE_RAV1E
        AVIF_CODEC_CHOICE_SVT

    ctypedef enum avifCodecFlags:
        AVIF_CODEC_FLAG_CAN_DECODE
        AVIF_CODEC_FLAG_CAN_ENCODE

    ctypedef struct avifEncoderData:
        pass
    ctypedef struct avifCodecSpecificOptions:
        pass

    ctypedef struct avifEncoder:
        avifCodecChoice codecChoice
        int maxThreads
        int minQuantizer
        int maxQuantizer
        int minQuantizerAlpha
        int maxQuantizerAlpha
        int tileRowsLog2
        int tileColsLog2
        int speed
        int keyframeInterval    #How many frames between automatic forced keyframes; 0 to disable (default).
        uint64_t timescale      #timescale of the media (Hz)

        #stats from the most recent write
        #avifIOStats ioStats

        #Internals used by the encoder
        avifEncoderData * data
        avifCodecSpecificOptions * csOptions

    avifEncoder * avifEncoderCreate()
    avifResult avifEncoderWrite(avifEncoder * encoder, const avifImage * image, avifRWData * output)
    void avifEncoderDestroy(avifEncoder * encoder)

    ctypedef enum avifAddImageFlags:
        AVIF_ADD_IMAGE_FLAG_NONE
        AVIF_ADD_IMAGE_FLAG_FORCE_KEYFRAME
        AVIF_ADD_IMAGE_FLAG_SINGLE

    avifResult avifEncoderAddImage(avifEncoder * encoder, const avifImage * image, uint64_t durationInTimescales, uint32_t addImageFlags)
    avifResult avifEncoderAddImageGrid(avifEncoder * encoder,
                                            uint32_t gridCols,
                                            uint32_t gridRows,
                                            const avifImage * const * cellImages,
                                            uint32_t addImageFlags)
    avifResult avifEncoderFinish(avifEncoder * encoder, avifRWData * output)

    ctypedef struct avifDecoderData:
        pass
    enum avifDecoderSource:
        AVIF_DECODER_SOURCE_AUTO
        AVIF_DECODER_SOURCE_PRIMARY_ITEM
        AVIF_DECODER_SOURCE_TRACKS
    ctypedef struct avifImageTiming:
        uint64_t timescale              # timescale of the media (Hz)
        double pts                      # presentation timestamp in seconds (ptsInTimescales / timescale)
        uint64_t ptsInTimescales        # presentation timestamp in "timescales"
        double duration                 # in seconds (durationInTimescales / timescale)
        uint64_t durationInTimescales   # duration in "timescales"
    ctypedef struct avifIOStats:
        size_t colorOBUSize
        size_t alphaOBUSize
    ctypedef struct avifIO:
        pass
    ctypedef struct avifDecoder:
        # Defaults to AVIF_CODEC_CHOICE_AUTO: Preference determined by order in availableCodecs table (avif.c)
        avifCodecChoice codecChoice
        int maxThreads      # Defaults to 1
        # avifs can have multiple sets of images in them. This specifies which to decode.
        # Set this via avifDecoderSetSource().
        avifDecoderSource requestedSource

        # All decoded image data; owned by the decoder. All information in this image is incrementally
        # added and updated as avifDecoder*() functions are called. After a successful call to
        # avifDecoderParse(), all values in decoder->image (other than the planes/rowBytes themselves)
        # will be pre-populated with all information found in the outer AVIF container, prior to any
        # AV1 decoding. If the contents of the inner AV1 payload disagree with the outer container,
        # these values may change after calls to avifDecoderRead*(),avifDecoderNextImage(), or
        # avifDecoderNthImage().
        #
        # The YUV and A contents of this image are likely owned by the decoder, so be sure to copy any
        # data inside of this image before advancing to the next image or reusing the decoder. It is
        # legal to call avifImageYUVToRGB() on this in between calls to avifDecoderNextImage(), but use
        # avifImageCopy() if you want to make a complete, permanent copy of this image's YUV content or
        # metadata.
        avifImage * image
        # Counts and timing for the current image in an image sequence. Uninteresting for single image files.
        int imageIndex      # 0-based
        int imageCount      # Always 1 for non-sequences
        avifImageTiming imageTiming
        uint64_t timescale  # timescale of the media (Hz)
        double duration     # in seconds (durationInTimescales / timescale)
        uint64_t durationInTimescales   # duration in "timescales"
        # This is true when avifDecoderParse() detects an alpha plane. Use this to find out if alpha is
        # present after a successful call to avifDecoderParse(), but prior to any call to
        # avifDecoderNextImage() or avifDecoderNthImage(), as decoder->image->alphaPlane won't exist yet.
        avifBool alphaPresent
        # Enable any of these to avoid reading and surfacing specific data to the decoded avifImage.
        # These can be useful if your avifIO implementation heavily uses AVIF_RESULT_WAITING_ON_IO for
        # streaming data, as some of these payloads are (unfortunately) packed at the end of the file,
        # which will cause avifDecoderParse() to return AVIF_RESULT_WAITING_ON_IO until it finds them.
        # If you don't actually leverage this data, it is best to ignore it here.
        avifBool ignoreExif
        avifBool ignoreXMP
        # stats from the most recent read, possibly 0s if reading an image sequence
        avifIOStats ioStats
        # Use one of the avifDecoderSetIO*() functions to set this
        avifIO * io
        # Internals used by the decoder
        avifDecoderData * data

    avifDecoder * avifDecoderCreate()
    avifResult avifDecoderSetIOMemory(avifDecoder * decoder, const uint8_t * data, size_t size)
    avifResult avifDecoderParse(avifDecoder * decoder)
    avifResult avifDecoderNextImage(avifDecoder * decoder)
    void avifDecoderDestroy(avifDecoder * decoder)

    ctypedef enum avifResult:
        AVIF_RESULT_OK
        AVIF_RESULT_UNKNOWN_ERROR
        AVIF_RESULT_INVALID_FTYP
        AVIF_RESULT_NO_CONTENT
        AVIF_RESULT_NO_YUV_FORMAT_SELECTED
        AVIF_RESULT_REFORMAT_FAILED
        AVIF_RESULT_UNSUPPORTED_DEPTH
        AVIF_RESULT_ENCODE_COLOR_FAILED
        AVIF_RESULT_ENCODE_ALPHA_FAILED
        AVIF_RESULT_BMFF_PARSE_FAILED
        AVIF_RESULT_NO_AV1_ITEMS_FOUND
        AVIF_RESULT_DECODE_COLOR_FAILED
        AVIF_RESULT_DECODE_ALPHA_FAILED
        AVIF_RESULT_COLOR_ALPHA_SIZE_MISMATCH
        AVIF_RESULT_ISPE_SIZE_MISMATCH
        AVIF_RESULT_NO_CODEC_AVAILABLE
        AVIF_RESULT_NO_IMAGES_REMAINING
        AVIF_RESULT_INVALID_EXIF_PAYLOAD
        AVIF_RESULT_INVALID_IMAGE_GRID
        AVIF_RESULT_INVALID_CODEC_SPECIFIC_OPTION
        AVIF_RESULT_TRUNCATED_DATA
        AVIF_RESULT_IO_NOT_SET
        AVIF_RESULT_IO_ERROR
        AVIF_RESULT_WAITING_ON_IO
        AVIF_RESULT_INVALID_ARGUMENT
        AVIF_RESULT_NOT_IMPLEMENTED

AVIF_RESULT = {
    AVIF_RESULT_OK                              : "OK",
    AVIF_RESULT_UNKNOWN_ERROR                   : "UNKNOWN ERROR",
    AVIF_RESULT_INVALID_FTYP                    : "INVALID_FTYP",
    AVIF_RESULT_NO_CONTENT                      : "NO_CONTENT",
    AVIF_RESULT_NO_YUV_FORMAT_SELECTED          : "NO_YUV_FORMAT_SELECTED",
    AVIF_RESULT_REFORMAT_FAILED                 : "REFORMAT_FAILED",
    AVIF_RESULT_UNSUPPORTED_DEPTH               : "UNSUPPORTED_DEPTH",
    AVIF_RESULT_ENCODE_COLOR_FAILED             : "ENCODE_COLOR_FAILED",
    AVIF_RESULT_ENCODE_ALPHA_FAILED             : "ENCODE_ALPHA_FAILED",
    AVIF_RESULT_BMFF_PARSE_FAILED               : "BMFF_PARSE_FAILED",
    AVIF_RESULT_NO_AV1_ITEMS_FOUND              : "NO_AV1_ITEMS_FOUND",
    AVIF_RESULT_DECODE_COLOR_FAILED             : "DECODE_COLOR_FAILED",
    AVIF_RESULT_DECODE_ALPHA_FAILED             : "DECODE_ALPHA_FAILED",
    AVIF_RESULT_COLOR_ALPHA_SIZE_MISMATCH       : "COLOR_ALPHA_SIZE_MISMATCH",
    AVIF_RESULT_ISPE_SIZE_MISMATCH              : "ISPE_SIZE_MISMATCH",
    AVIF_RESULT_NO_CODEC_AVAILABLE              : "NO_CODEC_AVAILABLE",
    AVIF_RESULT_NO_IMAGES_REMAINING             : "NO_IMAGES_REMAINING",
    AVIF_RESULT_INVALID_EXIF_PAYLOAD            : "INVALID_EXIF_PAYLOAD",
    AVIF_RESULT_INVALID_IMAGE_GRID              : "INVALID_IMAGE_GRID",
    AVIF_RESULT_INVALID_CODEC_SPECIFIC_OPTION   : "INVALID_CODEC_SPECIFIC_OPTION",
    AVIF_RESULT_TRUNCATED_DATA                  : "TRUNCATED_DATA",
    AVIF_RESULT_IO_NOT_SET                      : "IO_NOT_SET",
    AVIF_RESULT_IO_ERROR                        : "IO_ERROR",
    AVIF_RESULT_WAITING_ON_IO                   : "WAITING_ON_IO",
    AVIF_RESULT_INVALID_ARGUMENT                : "INVALID_ARGUMENT",
    AVIF_RESULT_NOT_IMPLEMENTED                 : "NOT_IMPLEMENTED",
    }
