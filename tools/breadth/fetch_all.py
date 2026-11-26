"""Fetch every Danish-language page in the Nalunaarutit sitemap into the greenland-law cache (5 in flight)."""
import hashlib, re, sys, time, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
CACHE = Path(r'C:\Users\alany\Documents\lexifina\scripts\greenland-law\.cache')
LOG = Path(r'C:\Users\alany\Documents\greenland-work\progress.log')
SM = Path(r'C:\Users\alany\Documents\greenland-work\dl\sm.xml')
UA = 'Mozilla/5.0 (compatible; lexifina-law-archive; +https://github.com/lexifina)'
lock = threading.Lock(); stats = {'ok': 0, 'cached': 0, 'err': 0, 'empty': 0}
stop = threading.Event()
def log(msg):
    with lock, LOG.open('a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%dT%H:%M:%S ') + msg + '\n')
def one(url):
    if stop.is_set(): return
    p = CACHE / hashlib.sha256(url.encode()).hexdigest()[:32]
    if p.exists():
        stats['cached'] += 1; return
    delay = 5
    for attempt in range(6):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=90)
            data = r.read()
            if b'challenge' in data[:3000].lower() and b'richtext' not in data:
                log(f'CHALLENGE? {url}'); stop.set(); return
            tmp = p.with_suffix('.tmp'); tmp.write_bytes(data); tmp.replace(p)
            time.sleep(0.3); stats["ok" if b'richtext' in data else 'empty'] += 1
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                p.write_bytes(b''); stats['empty'] += 1; return
            if e.code in (403,):
                log(f'403 {url}'); stop.set(); return
            log(f'HTTP {e.code} {url} retry in {delay}s')
        except Exception as e:
            log(f'ERR {e!r} {url} retry in {delay}s')
        time.sleep(delay); delay *= 2
    stats['err'] += 1; log(f'GAVE UP {url}')
def main():
    xml = SM.read_text(encoding='utf-8')
    urls = sorted({l for l in re.findall(r'<loc>([^<]+)</loc>', xml) if l.endswith('sc_lang=da')})
    # glfetch keys: path+?sc_lang=da with BASE prefix -> same full URL; normalise to lower-case-free original
    log(f'start {len(urls)} urls')
    t0 = time.time()
    def mon():
        while not done.is_set():
            done.wait(60); n = sum(stats.values())
            log(f'progress {n}/{len(urls)} {stats} {n/max(1,time.time()-t0)*60:.0f}/min')
    done = threading.Event(); threading.Thread(target=mon, daemon=True).start()
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, urls))
    done.set(); log(f'done {stats} stop={stop.is_set()}')
main()
