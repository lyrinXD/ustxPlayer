/* ustx_yuv.c — RGBA8888 → 全范围(JPEG) BT.601 YUV420P 转换内核
 *
 * 公式与 libjpeg/Pillow 同源（JFIF 定点）；色度取 2x2 RGB 均值后转换。
 * 输出布局：Y(w*h) + U(w/2*h/2) + V(w/2*h/2)，三段紧凑连续。
 *
 * 无状态、无分配、无 CRT 调用。
 */

#include <stdint.h>

#if defined(_WIN32)
#  define UPX_API __declspec(dllexport)
#else
#  define UPX_API
#endif

#define UPX_MAX_PIXELS (1LL << 30)     /* 防 w*h 回绕上限（8K≈33M px，远够用） */
#define FIX(x)         ((int32_t)((x) * 65536.0 + 0.5))
#define ONE_HALF       (1L << 15)

static uint8_t clamp_u8(int32_t v)
{
    return (uint8_t)(v < 0 ? 0 : (v > 255 ? 255 : v));
}

/* rgba: 源图，每像素 4 字节 R,G,B,A；行距 src_stride 字节；alpha 忽略
 * dst : 调用方分配的 width*height*3/2 字节缓冲区
 * 返回 0 成功；-1 参数非法（空指针/非正尺寸/奇数尺寸/超上限）
 */
UPX_API int upx_rgba_to_yuv420p(const uint8_t *rgba, int64_t src_stride,
                                uint8_t *dst, int32_t width, int32_t height)
{
    if (!rgba || !dst || width <= 0 || height <= 0) {
        return -1;
    }
    if (width & 1 || height & 1) {
        return -1;                      /* yuv420p 要求偶数尺寸 */
    }
    if ((int64_t)width * height > UPX_MAX_PIXELS) {
        return -1;
    }

    const int32_t cw = width >> 1;
    const int32_t ch = height >> 1;
    uint8_t *yp = dst;
    uint8_t *up = dst + (size_t)width * (size_t)height;
    uint8_t *vp = up + (size_t)cw * (size_t)ch;

    /* 亮度：逐像素 */
    for (int32_t y = 0; y < height; y++) {
        const uint8_t *row = rgba + (size_t)y * (size_t)src_stride;
        uint8_t *yrow = yp + (size_t)y * (size_t)width;
        for (int32_t x = 0; x < width; x++) {
            int32_t r = row[x * 4];
            int32_t g = row[x * 4 + 1];
            int32_t b = row[x * 4 + 2];
            yrow[x] = clamp_u8((FIX(0.299) * r + FIX(0.587) * g
                                + FIX(0.114) * b + ONE_HALF) >> 16);
        }
    }

    /* 色度：2x2 块 RGB 均值后转换 */
    for (int32_t cy = 0; cy < ch; cy++) {
        const uint8_t *r0 = rgba + (size_t)(cy * 2) * (size_t)src_stride;
        const uint8_t *r1 = r0 + (size_t)src_stride;
        uint8_t *urow = up + (size_t)cy * (size_t)cw;
        uint8_t *vrow = vp + (size_t)cy * (size_t)cw;
        for (int32_t cx = 0; cx < cw; cx++) {
            size_t o = (size_t)cx * 8;
            int32_t r = (r0[o] + r0[o + 4] + r1[o] + r1[o + 4] + 2) >> 2;
            int32_t g = (r0[o + 1] + r0[o + 5] + r1[o + 1] + r1[o + 5] + 2) >> 2;
            int32_t b = (r0[o + 2] + r0[o + 6] + r1[o + 2] + r1[o + 6] + 2) >> 2;
            urow[cx] = clamp_u8(128 + ((-FIX(0.168736) * r - FIX(0.331264) * g
                                        + FIX(0.5) * b + ONE_HALF) >> 16));
            vrow[cx] = clamp_u8(128 + ((FIX(0.5) * r - FIX(0.418688) * g
                                        - FIX(0.081312) * b + ONE_HALF) >> 16));
        }
    }
    return 0;
}