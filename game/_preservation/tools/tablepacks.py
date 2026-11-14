"""Read storage/cache/tablepacks.info: repeated field 7 (tag 58) = TablePack{1:pack 2:version 3:entries 4:reset}."""
import sys, os
def varint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1; r |= (c & 0x7f) << s; s += 7
        if c < 0x80: return r, i
def fields(b):
    i = 0; out = []
    while i < len(b):
        tag, i = varint(b, i); f, wt = tag >> 3, tag & 7
        if wt == 0: v, i = varint(b, i)
        elif wt == 2: n, i = varint(b, i); v = b[i:i+n]; i += n
        elif wt == 5: v = b[i:i+4]; i += 4
        elif wt == 1: v = b[i:i+8]; i += 8
        else: raise ValueError(wt)
        out.append((f, v))
    return out
def packs(path):
    res = []
    for f, v in fields(open(path, 'rb').read()):
        assert f == 7
        p = {'entries': []}
        for g, w in fields(v):
            if g == 1: p['pack'] = w.decode()
            elif g == 2: p['version'] = w
            elif g == 3: p['entries'].append({h: (x.decode('utf-8','replace') if isinstance(x, bytes) else x) for h, x in fields(w)})
            elif g == 4: p['reset'] = w
        res.append(p)
    return res
if __name__ == '__main__':
    for p in packs(sys.argv[1]):
        print(p['pack'], 'v', p.get('version'), 'reset', p.get('reset'), 'entries', len(p['entries']), p['entries'][:2])
