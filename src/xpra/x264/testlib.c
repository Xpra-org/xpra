#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "x264lib.h"

int encode(const char *in_file, int w, int h, const char *out_file)
{
	uint8_t *out;
	int i;
	int sz;
	FILE *dump;
	struct x264lib_ctx *ctx = init_encoder(w, h);

	uint8_t *b = malloc(w*h*3);


	FILE *in = fopen(in_file, "r");
	fread(b, w*h*3, 1, in);
	fclose(in);

	printf("Compressing image, size %d...", w*h*3);
	if (compress_image(ctx, b, w*3, &out, &sz)) {
		fprintf(stderr, "Error when compressing.\n");
		return 1;
	}

	printf("after compressing %d bytes, ratio %f\n", sz, (float)sz/w*h*3);

	dump = fopen(out_file, "w");
	fwrite(out, sz, 1, dump);
	fclose(dump);

	clean_encoder(ctx);
	free(ctx);

	return 0;
}

int decode(const char *in_file, int w, int h, const char *out_file)
{
	uint8_t *out2;
	int sz2;
	int stride;
	struct x264lib_ctx *ctx = init_decoder(w, h);
	FILE *fout;

	uint8_t *b = malloc(w*h*3);


	FILE *in = fopen(in_file, "r");
	int sz = fread(b, 1, w*h*3, in);
	printf("Read %d bytes\n", sz);
	fclose(in);

	decompress_image(ctx, b, sz, &out2, &sz2, &stride);
	printf("After decompressing, size %d, stride %d...\n", sz2, stride);

	fout = fopen(out_file, "w");
	fwrite(out2, sz2, 1, fout);
	fclose(fout);
	return 0;
}

int main(int argc, char **argv)
{
	const char *input_file;
	int width, height;
	const char *output_file;
	if (argc != 6) {
		fprintf(stderr, "Usage: %s <encode|decode> <input_filename> <width> <height> <output_filename>\n", argv[0]);
		return 1;
	}

	input_file = argv[2];
	width = atoi(argv[3]);
	height = atoi(argv[4]);
	output_file = argv[5];

	if (!strcmp(argv[1], "encode"))
		return encode(input_file, width, height, output_file);
	else return decode(input_file, width, height, output_file);

	return 0;
}
