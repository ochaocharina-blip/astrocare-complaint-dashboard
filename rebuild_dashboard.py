"""
STANDARD REBUILD SCRIPT — pakai ini setiap kali update data.
Auto-handles:
1. Update generated_at + build version to current WIB
2. Merge case-variants (UPPER/Proper/lower)
3. Re-embed DATA + RAW_DEFAULT + SKU_AGG into HTML
4. Verify math tally
"""
import json, re, os, sys, subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

WIB = ZoneInfo('Asia/Jakarta')
BASE = '/sessions/tender-vigilant-planck/mnt/outputs'

def normalize_case_key(s):
    if not s: return ''
    return re.sub(r'\s+', ' ', str(s).lower().strip())

def merge_case_variants(dim_list, canonical_set):
    groups = {}
    for i, val in enumerate(dim_list):
        if not val:
            groups.setdefault(None, []).append((i, val))
            continue
        groups.setdefault(normalize_case_key(val), []).append((i, val))
    idx_remap = {}
    new_dim_list = []
    for key, items in groups.items():
        winner = None
        for _, val in items:
            if val in canonical_set:
                winner = val
                break
        if not winner:
            sorted_items = sorted(items, key=lambda x: (
                -int(x[1] in canonical_set if canonical_set else False),
                -int(x[1] and x[1][0].isupper()),
                -len(x[1] or ''),
            ))
            winner = sorted_items[0][1]
        new_idx = len(new_dim_list)
        new_dim_list.append(winner)
        for old_idx, _ in items:
            idx_remap[old_idx] = new_idx
    return new_dim_list, idx_remap

def main():
    os.chdir(BASE)
    now = datetime.now(WIB)
    
    # Load PDF mapping
    with open('pdf_mapping.json') as f:
        pdf = json.load(f)
    canonical = {
        'impacts': {m['i'] for m in pdf if m.get('i')},
        'alasans': {m['a'] for m in pdf if m.get('a')},
        'tipes': {m['t'] for m in pdf if m.get('t')},
        'roles': {m['r'] for m in pdf if m.get('r')},
    }
    
    # Load data
    with open('dashboard_data_v10.json') as f:
        agg = json.load(f)
    
    RIDX = {'d':0,'m':1,'w':2,'day':3,'r':4,'t':5,'al':6,'im':7,'ac':8,'h':9,'l0':10,'l1':11,'l2':12,'c':13}
    
    # Merge case-variants
    new_dims = {}
    remap = {}
    for dim_name, ridx_key in [('impacts','im'),('alasans','al'),('tipes','t'),('roles','r')]:
        new_dims[dim_name], remap[ridx_key] = merge_case_variants(agg['dims'][dim_name], canonical[dim_name])
        if len(agg['dims'][dim_name]) != len(new_dims[dim_name]):
            print(f"  {dim_name}: {len(agg['dims'][dim_name])} → {len(new_dims[dim_name])}")
    
    # Re-aggregate rows
    new_agg = defaultdict(int)
    for row in agg['rows']:
        new_row = row[:]
        for ridx_key, m in remap.items():
            new_row[RIDX[ridx_key]] = m.get(row[RIDX[ridx_key]], row[RIDX[ridx_key]])
        new_agg[tuple(new_row[:13])] += new_row[RIDX['c']]
    
    new_rows = [list(k) + [c] for k, c in new_agg.items()]
    
    old_total = sum(r[RIDX['c']] for r in agg['rows'])
    new_total = sum(r[RIDX['c']] for r in new_rows)
    assert old_total == new_total, f'Total mismatch: {old_total} != {new_total}'
    
    for k, v in new_dims.items():
        agg['dims'][k] = v
    agg['rows'] = new_rows
    agg['generated_at'] = now.isoformat()
    
    with open('dashboard_data_v10.json', 'w') as f:
        json.dump(agg, f, separators=(',',':'), ensure_ascii=False)
    print(f"✅ dashboard_data_v10.json saved, total={new_total:,}")
    
    # Rebuild HTML
    html = open('Dashboard CX Astro.html').read()
    
    def replace_const(html, var_name, data):
        start_marker = f'const {var_name} = '
        start = html.find(start_marker)
        if start < 0: return html, False
        obj_start = start + len(start_marker)
        open_ch = html[obj_start]
        close_ch = '}' if open_ch == '{' else ']'
        depth = 0
        i = obj_start
        while i < len(html):
            c = html[i]
            if c == open_ch: depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    obj_end = i + 1
                    break
            i += 1
        return html[:obj_start] + json.dumps(data, separators=(',',':')) + html[obj_end:], True
    
    # === Compressed data injection (gzip + base64, async decompress on load) ===
    import gzip as _gzip, base64 as _b64
    def _gz(obj):
        s = json.dumps(obj, separators=(',',':'), ensure_ascii=False).encode('utf-8')
        return _b64.b64encode(_gzip.compress(s, compresslevel=9)).decode('ascii')
    def _replace_compressed(html, var, obj):
        marker = f'const {var} = "'
        start = html.find(marker)
        if start < 0: return html
        obj_start = start + len(marker)
        end_q = html.find('"', obj_start)
        if end_q < 0: return html
        return html[:obj_start] + _gz(obj) + html[end_q:]

    html = _replace_compressed(html, '_CDATA', agg)
    for var, fn in [('_CRAW', 'raw_default.json'), ('_CSKU', 'sku_agg.json'), ('_CPDF', 'pdf_mapping.json')]:
        if os.path.exists(fn):
            with open(fn) as f:
                d = json.load(f)
            html = _replace_compressed(html, var, d)
    
    new_label = now.strftime('%d %b %Y, %H:%M WIB (v%Y%m%d.%H%M)')
    html = re.sub(r'Build:\s*([^<]+)<', f'Build: {new_label}<', html, count=1)
    
    with open('Dashboard CX Astro.html', 'w') as f:
        f.write(html)
    
    print(f"✅ Build: {new_label}")
    
    # Verify JS
    r = subprocess.run(['node', '-e', '''
const fs=require('fs');
const html=fs.readFileSync('Dashboard CX Astro.html','utf-8');
const scripts=[...html.matchAll(/<script[^>]*>([\\s\\S]*?)<\\/script>/g)];
let allOK=true;
for(const [i,s] of scripts.entries()){try{new Function(s[1]);}catch(e){console.log('❌ Script',i,':',e.message.slice(0,150));allOK=false;}}
if(allOK)console.log('✅ JS OK ('+scripts.length+' scripts)');
'''], capture_output=True, text=True)
    print(r.stdout)

if __name__ == '__main__':
    main()


# ============================================================
# SKU MASTER LOOKUP (for L0/L1/L2 auto-assignment)
# Usage in ingest scripts:
#   from rebuild_dashboard import lookup_sku
#   l0, l1, l2 = lookup_sku(no_sku, nama_sku)
# ============================================================
_MASTER_CACHE = None
def _load_master():
    global _MASTER_CACHE
    if _MASTER_CACHE is not None: return _MASTER_CACHE
    try:
        with open(f'{BASE}/master_inventory.json') as f:
            _MASTER_CACHE = json.load(f)
    except FileNotFoundError:
        _MASTER_CACHE = {'by_name': {}, 'by_code': {}, 'by_name_aggressive': {}}
    return _MASTER_CACHE

def _aggressive_norm(s):
    if not s: return ''
    t = str(s).lower().strip()
    t = re.sub(r'\[.*?\]', '', t)
    t = re.sub(r'\(.*?\)', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def lookup_sku(no_sku, nama_sku):
    """Return (l0, l1, l2) for given SKU. Falls back: code → exact name → fuzzy name."""
    m = _load_master()
    if no_sku:
        code = str(no_sku).strip()
        if code in m['by_code']:
            e = m['by_code'][code]
            return e['l0'], e['l1'], e['l2']
    if nama_sku:
        if nama_sku in m['by_name']:
            e = m['by_name'][nama_sku]
            return e['l0'], e['l1'], e['l2']
        nk = _aggressive_norm(nama_sku)
        if nk in m['by_name_aggressive']:
            e = m['by_name_aggressive'][nk]
            return e['l0'], e['l1'], e['l2']
    return '', '', ''
