"""
Ingest W25 complaint + order CSVs.
- Append rows to dashboard_data_v10.json (aggregate)
- Append rows to raw_default.json (ticket-level)
- Append rows to sku_agg.json (sku-level)
- Update orders_by_date / orders_monthly / orders_by_hub / orders_dow / total_orders
"""
import sys, csv, json, re, os
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, '/sessions/tender-vigilant-planck/mnt/outputs')
from normalize_complaint import load_pdf_mapping, normalize_complaint
from rebuild_dashboard import lookup_sku

BASE = '/sessions/tender-vigilant-planck/mnt/outputs'
UPLOADS = '/sessions/tender-vigilant-planck/mnt/uploads'

# === Load aggregate ===
with open(f'{BASE}/dashboard_data_v10.json') as f:
    agg = json.load(f)

RIDX = {'d':0,'m':1,'w':2,'day':3,'r':4,'t':5,'al':6,'im':7,'ac':8,'h':9,'l0':10,'l1':11,'l2':12,'c':13}

# Helpers to get/add to dim
def get_or_add(dim, val):
    """Get index of val in dim list, append if missing. Empty → '(kosong)' at index 0."""
    if not val or not val.strip():
        val = '(kosong)'
    if val in dim:
        return dim.index(val)
    dim.append(val)
    return len(dim) - 1

# === Parse W25 complaints ===
RTT, TTA, ATI = load_pdf_mapping()

# Day name mapping (Indonesian)
DAY_MAP = {
    'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
    'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu',
    'Sunday': 'Minggu',
}

def parse_date(s):
    """DD/MM/YYYY -> (iso, month, day_id, week_id)"""
    try:
        dt = datetime.strptime(s, '%d/%m/%Y')
    except Exception:
        return None, None, None, None
    iso = dt.strftime('%Y-%m-%d')
    month = dt.strftime('%Y-%m')
    day_name = DAY_MAP.get(dt.strftime('%A'), dt.strftime('%A'))
    week_iso = dt.strftime('%G-W%V')
    return iso, month, day_name, week_iso

# === Read complaints CSV ===
print("Reading Com w25.csv ...")
new_agg_rows = defaultdict(int)
raw_new_rows = []

# Track new SKU aggregates: (month_idx, week_idx, role_idx, hub_idx, tipe_idx, sku_text) -> count
sku_new = defaultdict(int)

# Load existing raw_default dicts to extend
with open(f'{BASE}/raw_default.json') as f:
    raw = json.load(f)

raw_dicts = raw['dicts']  # has role, tipe, alasan, hub, nama_sku

def raw_dict_idx(name, val):
    if not val:
        val = '(kosong)'
    d = raw_dicts[name]
    if val in d:
        return d.index(val)
    d.append(val)
    return len(d) - 1

with open(f'{UPLOADS}/Com w25.csv', encoding='utf-8-sig') as f:
    r = csv.reader(f, delimiter=';')
    header = next(r)
    h2i = {c: i for i, c in enumerate(header)}
    
    n_total = 0
    n_skipped = 0
    for row in r:
        if len(row) < len(header):
            continue
        n_total += 1
        
        date_raw = row[h2i['date_key']]
        iso, month, day_name, week_iso = parse_date(date_raw)
        if not iso:
            n_skipped += 1
            continue
        
        role = (row[h2i['role']] or '').strip()
        tipe_raw = (row[h2i['tipe_complaint']] or '').strip()
        alasan_raw = (row[h2i['alasan_complaint']] or '').strip()
        impact_raw = (row[h2i['impact_to_customer']] or '').strip()
        action = (row[h2i['action']] or '').strip()
        hub_name = (row[h2i['hub_name']] or '').strip()
        no_sku = (row[h2i['no_sku']] or '').strip()
        nama_sku = (row[h2i['nama_sku']] or '').strip()
        ticket_no = (row[h2i['ticket_no']] or '').strip()
        no_invoice = (row[h2i['no_invoice']] or '').strip()
        
        # Normalize via cascade
        tipe, alasan, impact = normalize_complaint(role, tipe_raw, alasan_raw, impact_raw, RTT, TTA, ATI)
        
        # L0/L1/L2 lookup
        l0, l1, l2 = lookup_sku(no_sku, nama_sku)
        if not l0: l0 = '(Tidak ada kategori)'
        if not l1: l1 = '(Tidak ada kategori)'
        if not l2: l2 = '(Tidak ada kategori)'
        
        # Map to agg dim indices
        d_idx = get_or_add(agg['dims']['dates'], iso)
        m_idx = get_or_add(agg['dims']['months'], month)
        w_idx = get_or_add(agg['dims']['weeks'], week_iso)
        day_idx = get_or_add(agg['dims']['days'], day_name)
        r_idx = get_or_add(agg['dims']['roles'], role)
        t_idx = get_or_add(agg['dims']['tipes'], tipe)
        al_idx = get_or_add(agg['dims']['alasans'], alasan)
        im_idx = get_or_add(agg['dims']['impacts'], impact)
        ac_idx = get_or_add(agg['dims']['actions'], action)
        h_idx = get_or_add(agg['dims']['hubs'], hub_name)
        l0_idx = get_or_add(agg['dims']['l0_cats'], l0)
        l1_idx = get_or_add(agg['dims']['l1_cats'], l1)
        l2_idx = get_or_add(agg['dims']['l2_cats'], l2)
        
        key = (d_idx, m_idx, w_idx, day_idx, r_idx, t_idx, al_idx, im_idx, ac_idx, h_idx, l0_idx, l1_idx, l2_idx)
        new_agg_rows[key] += 1
        
        # raw_default row: [date, role_idx, tipe_idx, alasan_idx, hub_idx, no_sku, nama_sku_idx, ticket_no, no_invoice]
        raw_row = [
            iso,
            raw_dict_idx('role', role),
            raw_dict_idx('tipe', tipe),
            raw_dict_idx('alasan', alasan),
            raw_dict_idx('hub', hub_name),
            no_sku,
            raw_dict_idx('nama_sku', nama_sku),
            ticket_no,
            no_invoice,
        ]
        raw_new_rows.append(raw_row)
        
        # sku_agg key
        sku_key = (m_idx, w_idx, r_idx, h_idx, t_idx, nama_sku or '(kosong)')
        sku_new[sku_key] += 1

print(f"Read {n_total} rows from W25, skipped {n_skipped}")
print(f"Unique agg keys: {len(new_agg_rows)}")
print(f"raw_new_rows: {len(raw_new_rows)}")
print(f"sku unique keys: {len(sku_new)}")

# === Append to agg.rows ===
for key, c in new_agg_rows.items():
    agg['rows'].append(list(key) + [c])

new_total = sum(r[RIDX['c']] for r in agg['rows'])
print(f"\nTotal cases after W25: {new_total:,}")

agg['totals'] = agg.get('totals', {})
agg['totals']['cases'] = new_total

# Save aggregate
with open(f'{BASE}/dashboard_data_v10.json', 'w') as f:
    json.dump(agg, f, separators=(',',':'), ensure_ascii=False)
print(f"✅ dashboard_data_v10.json saved")

# === Save raw_default ===
raw['rows'].extend(raw_new_rows)
print(f"\nraw_default rows: {len(raw['rows']):,}")
with open(f'{BASE}/raw_default.json', 'w') as f:
    json.dump(raw, f, separators=(',',':'), ensure_ascii=False)
print(f"✅ raw_default.json saved")

# === Save sku_agg ===
with open(f'{BASE}/sku_agg.json') as f:
    sku = json.load(f)

# Get sku_idx mapping
sku_list = sku['skus']
sku_map = {s: i for i, s in enumerate(sku_list)}

def sku_idx_get(name):
    if name in sku_map:
        return sku_map[name]
    sku_list.append(name)
    sku_map[name] = len(sku_list) - 1
    return sku_map[name]

# sku_agg rows: [m_idx, w_idx, role_idx, hub_idx, tipe_idx, sku_idx, count]
for key, c in sku_new.items():
    m_idx, w_idx, r_idx, h_idx, t_idx, sku_name = key
    s_idx = sku_idx_get(sku_name)
    sku['rows'].append([m_idx, w_idx, r_idx, h_idx, t_idx, s_idx, c])

print(f"\nsku_agg rows: {len(sku['rows']):,}, unique SKUs: {len(sku['skus']):,}")
with open(f'{BASE}/sku_agg.json', 'w') as f:
    json.dump(sku, f, separators=(',',':'), ensure_ascii=False)
print(f"✅ sku_agg.json saved")

# === Process orders ===
print("\n" + "="*60)
print("Processing orders W25 ...")

# Reload agg (with all new dims) — actually we already have it but dim was modified
# Just reuse same agg

# Day mapping for orders (same as complaints)
def parse_order_date(s):
    """e.g. '15 Jun 2026' -> (iso, month, day_name)"""
    try:
        dt = datetime.strptime(s, '%d %b %Y')
    except Exception:
        return None, None, None
    iso = dt.strftime('%Y-%m-%d')
    month = dt.strftime('%Y-%m')
    day_name = DAY_MAP.get(dt.strftime('%A'), dt.strftime('%A'))
    return iso, month, day_name

total_added = 0
order_dates_w25 = defaultdict(int)
order_hubs_w25 = defaultdict(int)
order_dow_w25 = defaultdict(int)
order_months_w25 = defaultdict(int)

with open(f'{UPLOADS}/week 25 order.csv', encoding='utf-8-sig') as f:
    r = csv.reader(f)
    header = next(r)
    for row in r:
        if len(row) < 5:
            continue
        date_raw = row[0]
        hub = row[2]
        try:
            n_orders = int(row[4])
        except Exception:
            continue
        iso, month, day_name = parse_order_date(date_raw)
        if not iso:
            continue
        order_dates_w25[iso] += n_orders
        order_hubs_w25[hub] += n_orders
        order_dow_w25[day_name] += n_orders
        order_months_w25[month] += n_orders
        total_added += n_orders

# Merge into agg
# orders_by_date: ADD (not replace) per date
for d, n in order_dates_w25.items():
    agg['orders_by_date'][d] = agg['orders_by_date'].get(d, 0) + n
# orders_by_hub: ADD
for h, n in order_hubs_w25.items():
    agg['orders_by_hub'][h] = agg['orders_by_hub'].get(h, 0) + n
# orders_dow: ADD
for d, n in order_dow_w25.items():
    agg['orders_dow'][d] = agg['orders_dow'].get(d, 0) + n
# orders_monthly: ADD
for m, n in order_months_w25.items():
    agg['orders_monthly'][m] = agg['orders_monthly'].get(m, 0) + n

agg['total_orders'] = agg.get('total_orders', 0) + total_added

print(f"Added {total_added:,} orders across {len(order_dates_w25)} days, {len(order_hubs_w25)} hubs")
print(f"New total_orders: {agg['total_orders']:,}")
print(f"Updated orders_monthly['2026-06']: {agg['orders_monthly']['2026-06']:,}")

# Re-save agg
with open(f'{BASE}/dashboard_data_v10.json', 'w') as f:
    json.dump(agg, f, separators=(',',':'), ensure_ascii=False)
print(f"\n✅ Ingest complete")
