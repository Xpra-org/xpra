#include "vpx/vpx_encoder.h"
#include "vpx/vpx_decoder.h"
#include <libswscale/swscale.h>

typedef struct vpx_context {
	vpx_codec_ctx_t codec;
	struct SwsContext *rgb2yuv;
	struct SwsContext *yuv2rgb;
} vpx_context;


/** Create an encoding context for images of a given size.  */
vpx_context *init_encoder(int width, int height);

/** Create a decoding context for images of a given size. */
vpx_context *init_decoder(int width, int height);

/** Cleanup encoding context. Must be freed after calling this function. */
void clean_encoder(vpx_context *ctx);

/** Cleanup decoding context. Must be freed after calling this function. */
void clean_decoder(vpx_context *ctx);

/** Compress an image using the given context. 
 @param in: Input buffer, format is packed RGB24.
 @param stride: Input stride (size is taken from context).
 @param out: Will be set to point to the output data. This output buffer MUST NOT BE FREED and will be erased on the 
 next call to compress_image.
 @param outsz: Output size
*/
int compress_image(vpx_context *ctx, uint8_t *in, int w, int h, int stride, uint8_t **out, int *outsz);

/** Decompress an image using the given context. 
 @param in: Input buffer, format is H264.
 @param size: Input size.
 @param out: Will be set to point to the output data in RGB24 format.
 @param outstride: Output stride.
*/
int decompress_image(vpx_context *ctx, uint8_t *in, int size, uint8_t **out, int *outsize, int *outstride);
