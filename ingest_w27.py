"""Ingest W27 all roles from BC Raw CSV."""
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

def get_or_add(dim, val):
    if not val or not str(val).strip(): val = '(kosong)'
    val = str(val).strip()
    if val in dim: return dim.index(val)
    dim.append(val); return len(dim)-1

raw_dicts = raw['dicts']
def raw_dict_idx(name, val):
    if not val or not str(val).strip(): val='(kosong)'
    val = str(val).strip()
    d = raw_dicts[name]
    if val in d: return d.index(val)
    d.append(val); return len(d)-1

sku_list = sku['skus']
sku_map = {s:i for i,s in enumerate(sku_list)}
def sku_idx_get(name):
    name = name or '(kosong)'
    if name in sku_map: return sku_map[name]
    sku_list.append(name); sku_map[name]=len(sku_list)-1
    return sku_map[name]

RTT, TTA, ATI = load_pdf_mapping()

new_agg = defaultdict(int); new_raw = []; new_sku = defaultdict(int)
n_read = 0
roles_seen = defaultdict(int)

with open(f'{UPLOADS}/BC - Complaint Recap v2_Raw Data_Table (3).csv', encoding='utf-8-sig') as f:
    r = csv.reader(f, delimiter=';')
    header = next(r)
    h2i = {h:i for i,h in enumerate(header)}
    
    for row in r:
        if len(row) < len(header): continue
        role = (row[h2i['role']] or '').strip()
        if not role: continue
        
        date_raw = row[h2i['date_key']]
        try: dt = datetime.strptime(date_raw, '%d/%m/%Y')
        except: continue
        iso = dt.strftime('%Y-%m-%d')
        month = dt.strftime('%Y-%m')
        day_name = DAY_MAP.get(dt.strftime('%A'))
        week_iso = dt.strftime('%G-W%V')
        
        ticket = row[h2i['ticket_no']]
        invoice = row[h2i['no_invoice']]
        hub = row[h2i.get('hub_name', -1)] if 'hub_name' in h2i else ''
        tipe_raw = row[h2i['tipe_complaint']]
        alasan_raw = row[h2i['alasan_complaint']]
        impact_raw = row[h2i['impact_to_customer']]
        action = row[h2i.get('action', -1)] if 'action' in h2i else ''
        no_sku = str(row[h2i.get('no_sku', -1)] or '').strip() if 'no_sku' in h2i else ''
        nama_sku = row[h2i.get('nama_sku', -1)] if 'nama_sku' in h2i else ''
        
        n_read += 1; roles_seen[role] += 1
        
        # Normalize (cascade picker handles double tags)
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
        ac_idx = get_or_add(agg['dims']['actions'], action)
        h_idx = get_or_add(agg['dims']['hubs'], hub)
        l0_idx = get_or_add(agg['dims']['l0_cats'], l0)
        l1_idx = get_or_add(agg['dims']['l1_cats'], l1)
        l2_idx = get_or_add(agg['dims']['l2_cats'], l2)
        
        key = (d_idx, m_idx, w_idx, day_idx, r_idx, t_idx, al_idx, im_idx, ac_idx, h_idx, l0_idx, l1_idx, l2_idx)
        new_agg[key] += 1
        
        new_raw.append([iso, raw_dict_idx('role', role), raw_dict_idx('tipe', tipe),
                        raw_dict_idx('alasan', alasan), raw_dict_idx('hub', hub),
                        no_sku, raw_dict_idx('nama_sku', nama_sku), ticket, invoice])
        new_sku[(m_idx, w_idx, r_idx, h_idx, t_idx, nama_sku or '(kosong)')] += 1

print(f"Rows read: {n_read:,}")
print(f"Roles: {dict(roles_seen)}")
print(f"Unique agg keys: {len(new_agg):,}")

for k, c in new_agg.items():
    agg['rows'].append(list(k) + [c])
raw['rows'].extend(new_raw)
for k, c in new_sku.items():
    m_idx, w_idx, r_idx, h_idx, t_idx, sku_name = k
    s_idx = sku_idx_get(sku_name)
    sku['rows'].append([m_idx, w_idx, r_idx, h_idx, t_idx, s_idx, c])

total = sum(r[RIDX['c']] for r in agg['rows'])
print(f"Total cases all-time: {total:,}")

with open(f'{BASE}/dashboard_data_v10.json','w') as f:
    json.dump(agg, f, separators=(',',':'), ensure_ascii=False)
with open(f'{BASE}/raw_default.json','w') as f:
    json.dump(raw, f, separators=(',',':'), ensure_ascii=False)
with open(f'{BASE}/sku_agg.json','w') as f:
    json.dump(sku, f, separators=(',',':'), ensure_ascii=False)
print("✅ Saved 3 files")
