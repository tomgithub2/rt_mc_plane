"""检查截图 PNG 的实际像素内容：判断"空白"是真空白还是我看错了。

用法： python inspect_shots.py <png> [png...]
输出：唯一色数、非背景像素占比、以及按行分带的非背景占比（定位内容在哪一段）。
"""
import sys
from PIL import Image


def analyze(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    px = im.load()
    # 取四角与中心推断背景色
    bg = px[2, 2]
    diff = 0
    rows = []
    band = max(1, h // 20)
    for y in range(h):
        cnt = 0
        for x in range(0, w, 3):
            p = px[x, y]
            if abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2]) > 18:
                cnt += 1
        diff += cnt
        if y % band == 0:
            rows.append((y, cnt))
    total_sampled = (w // 3) * h
    print('%-26s %dx%d  bg=%s  非背景像素=%.3f%%' %
          (path.split('\\')[-1], w, h, bg, diff / max(1, total_sampled) * 100))
    bands = ' '.join('%d:%d' % (y, c) for y, c in rows)
    print('   行带非背景计数: ' + bands)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            analyze(p)
        except Exception as e:
            print('%s -> 读取失败 %s' % (p, e))
