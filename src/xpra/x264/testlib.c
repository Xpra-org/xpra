#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "x264lib.h"

#define X 800
#define Y 600
#define totalSZ X*Y*3
int main(int argc, char **argv)
{
	struct x264lib_ctx *ctx = init_encoder(X, Y);

	uint8_t *b = malloc(totalSZ);
	int i;

	FILE *in = fopen("x264test.rgb", "r");
	fread(b, totalSZ, 1, in);
	fclose(in);

	/*for (i = 0; i < totalSZ;) {
		b[i++] = i;
		b[i++] = 255-i;
		b[i++] = 0;
	}*/

	uint8_t *out;
	int sz;
	printf("Compressing image, size %d...", totalSZ);
	compress_image(ctx, b, X*3, &out, &sz);
	printf("after compressing %d bytes, ratio %f\n", sz, (float)sz/totalSZ);

	clean_encoder(ctx);
	free(ctx);

	uint8_t *out2;
	int sz2;
	ctx = init_decoder(X, Y);
	int stride;
	decompress_image(ctx, out, sz, &out2, &sz2, &stride);
	printf("After decompressing, stride %d...", sz2);
	if (sz2 != totalSZ) {
		printf("size doesn't match original!\n");
		return 1;
	} else 
		printf("OK\n");

	FILE *fout = fopen("decompressed.rgb", "w");
	fwrite(out2, sz2, 1, fout);
	fclose(fout);
	return 0;
}
