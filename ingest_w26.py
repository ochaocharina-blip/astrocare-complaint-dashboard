"""
Ingest W26 HW complaints + REPLACE all orders with new dataset (Jan-Jun fresh).
"""
import sys, json, csv
sys.path.insert(0, '/sessions/tender-vigilant-planck/mnt/outputs')
from normalize_complaint import load_pdf_mapping, normalize_complaint
from rebuild_dashboard import lookup_sku
from collections import defaultdict
from datetime import datetime

BASE = '/sessions/tender-vigilant-planck/mnt/outputs'
UPLOADS = '/sessions/tender-vigilant-planck/mnt/uploads'

DAY_MAP = {'Monday':'Senin','Tuesday':'Selasa','Wednesday':'Rabu','Thursday':'Kamis','Friday':'Jumat','Saturday':'Sabtu','Sunday':'Minggu'}
RIDX = {'d':0,'m':1,'w':2,'day':3,'r':4,'t':5,'al':6,'im':7,'ac':8,'h':9,'l0':10,'l1':11,'l2':12,'c':13}

with open(f'{BASE}/dashboard_data_v10.json') as f: agg = json.load(f)
with open(f'{BASE}/raw_default.json') as f: raw = json.load(f)
with open(f'{BASE}/sku_agg.json') as f: sku = json.load(f)

# Helpers
def get_or_add(dim, val):
    if not val or not str(val).strip(): val = '(kosong)'
    val = str(val).strip()
    if val in dim: return dim.index(val)
    dim.append(val); return len(dim) - 1

raw_dicts = raw['dicts']
def raw_dict_idx(name, val):
    if not val or not str(val).strip(): val = '(kosong)'
    val = str(val).strip()
    d = raw_dicts[name]
    if val in d: return d.index(val)
    d.append(val); return len(d) - 1

sku_list = sku['skus']
sku_map = {s:i for i,s in enumerate(sku_list)}
def sku_idx_get(name):
    name = name or '(kosong)'
    if name in sku_map: return sku_map[name]
    sku_list.append(name); sku_map[name] = len(sku_list) - 1
    return sku_map[name]

# ============================================================
# PART 1: Ingest W26 HW complaints
# ============================================================
print("="*60)
print("Ingesting W26 HW complaints...")
print("="*60)
RTT, TTA, ATI = load_pdf_mapping()

new_agg = defaultdict(int); new_raw = []; new_sku = defaultdict(int)
n_read = 0

with open(f'{UPLOADS}/hub Week 26 - Sheet1.csv', encoding='utf-8-sig') as f:
    r = csv.reader(f)
    header = next(r)
    h2i = {h:i for i,h in enumerate(header)}
    
    for row in r:
        if len(row) < len(header): continue
        date_raw = row[h2i['date_key']]
        try:
            dt = datetime.strptime(date_raw, '%d %b %Y')
        except: continue
        iso = dt.strftime('%Y-%m-%d')
        month = dt.strftime('%Y-%m')
        day_name = DAY_MAP.get(dt.strftime('%A'))
        week_iso = dt.strftime('%G-W%V')
        
        ticket = row[h2i['ticket_no']]
        invoice = row[h2i['no_invoice']]
        hub = row[h2i['hub_name']]
        role = row[h2i['role']]
        tipe_raw = row[h2i['tipe_complaint']]
        alasan_raw = row[h2i['alasan_complaint']]
        impact_raw = row[h2i['impact_to_customer']]
        no_sku = str(row[h2i['no_sku']] or '').strip()
        nama_sku = row[h2i['nama_sku']]
        
        n_read += 1
        tipe, alasan, impact = normalize_complaint(role, tipe_raw, alasan_raw, impact_raw, RTT, TTA, ATI)
        l0, l1, l2 = lookup_sku(no_sku, nama_sku)
        if not l0: l0 = '(Tidak ada kategori)'
        if not l1: l1 = '(Tidak ada kategori)'
        if not l2: l2 = '(Tidak ada kategori)'
        
        d_idx = get_or_add(agg['dims']['dates'], iso)
        m_idx = get_or_add(agg['dims']['months'], month)
        w_idx = get_or_add(agg['dims']['weeks'], week_iso)
        day_idx = get_or_add(agg['dims']['days'], day_name)
        r_idx = get_or_add(agg['dims']['roles'], role)
        t_idx = get_or_add(agg['dims']['tipes'], tipe)
        al_idx = get_or_add(agg['dims']['alasans'], alasan)
        im_idx = get_or_add(agg['dims']['impacts'], impact)
        ac_idx = get_or_add(agg['dims']['actions'], '')
        h_idx = get_or_add(agg['dims']['hubs'], hub)
        l0_idx = get_or_add(agg['dims']['l0_cats'], l0)
        l1_idx = get_or_add(agg['dims']['l1_cats'], l1)
        l2_idx = get_or_add(agg['dims']['l2_cats'], l2)
        
        key = (d_idx, m_idx, w_idx, day_idx, r_idx, t_idx, al_idx, im_idx, ac_idx, h_idx, l0_idx, l1_idx, l2_idx)
        new_agg[key] += 1
        
        new_raw.append([
            iso,
            raw_dict_idx('role', role),
            raw_dict_idx('tipe', tipe),
            raw_dict_idx('alasan', alasan),
            raw_dict_idx('hub', hub),
            no_sku,
            raw_dict_idx('nama_sku', nama_sku),
            ticket, invoice
        ])
        new_sku[(m_idx, w_idx, r_idx, h_idx, t_idx, nama_sku or '(kosong)')] += 1

print(f"Read: {n_read:,} HW W26 rows")
print(f"Unique agg keys: {len(new_agg):,}")

for k, c in new_agg.items():
    agg['rows'].append(list(k) + [c])
raw['rows'].extend(new_raw)
for k, c in new_sku.items():
    m_idx, w_idx, r_idx, h_idx, t_idx, sku_name = k
    s_idx = sku_idx_get(sku_name)
    sku['rows'].append([m_idx, w_idx, r_idx, h_idx, t_idx, s_idx, c])

total_after = sum(r[RIDX['c']] for r in agg['rows'])
print(f"Total cases after HW W26: {total_after:,}")

# ============================================================
# PART 2: REPLACE all orders with new dataset
# ============================================================
print()
print("="*60)
print("Replacing ALL orders with new dataset...")
print("="*60)

# Reset
agg['orders_by_date'] = {}
agg['orders_by_hub'] = {}
agg['orders_dow'] = {}
agg['orders_monthly'] = {}
agg['total_orders'] = 0

with open(f'{UPLOADS}/Order week 26.csv', encoding='utf-8-sig') as f:
    r = csv.reader(f)
    header = next(r)
    h2i_o = {h:i for i,h in enumerate(header)}
    
    n_orders = 0
    for row in r:
        if len(row) < 7: continue
        date_raw = row[h2i_o['Date']]
        hub = row[h2i_o['Location Name']]
        n_str = row[h2i_o['Number of Orders']].replace(',','').strip()
        try:
            n = int(n_str)
        except: continue
        try:
            dt = datetime.strptime(date_raw, '%d %b %Y')
        except: continue
        iso = dt.strftime('%Y-%m-%d')
        month = dt.strftime('%Y-%m')
        dow = DAY_MAP.get(dt.strftime('%A'))
        
        agg['orders_by_date'][iso] = agg['orders_by_date'].get(iso, 0) + n
        agg['orders_by_hub'][hub] = agg['orders_by_hub'].get(hub, 0) + n
        agg['orders_dow'][dow] = agg['orders_dow'].get(dow, 0) + n
        agg['orders_monthly'][month] = agg['orders_monthly'].get(month, 0) + n
        agg['total_orders'] += n
        n_orders += 1

print(f"Order rows: {n_orders:,}")
print(f"Total orders: {agg['total_orders']:,}")
print(f"Months: {agg['orders_monthly']}")
print(f"Hubs: {len(agg['orders_by_hub'])}")

# Save W26 hub orders for next ref
w26_hub_orders = defaultdict(int)
for row in csv.reader(open(f'{UPLOADS}/Order week 26.csv', encoding='utf-8-sig')):
    if len(row) < 7: continue
    if row[2] == 'Date': continue
    try:
        dt = datetime.strptime(row[2], '%d %b %Y')
    except: continue
    iso = dt.strftime('%Y-%m-%d')
    if not ('2026-06-22' <= iso <= '2026-06-28'): continue
    try: n = int(row[6].replace(',', ''))
    except: continue
    w26_hub_orders[row[4]] += n

with open(f'{BASE}/w26_hub_orders.json', 'w') as f:
    json.dump(dict(w26_hub_orders), f, indent=1)
print(f"\nW26 total orders: {sum(w26_hub_orders.values()):,}")

# Save all
with open(f'{BASE}/dashboard_data_v10.json','w') as f:
    json.dump(agg, f, separators=(',',':'), ensure_ascii=False)
with open(f'{BASE}/raw_default.json','w') as f:
    json.dump(raw, f, separators=(',',':'), ensure_ascii=False)
with open(f'{BASE}/sku_agg.json','w') as f:
    json.dump(sku, f, separators=(',',':'), ensure_ascii=False)

print("\n✅ All files saved")
