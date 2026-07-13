"""
Complaint normalizer — handles double-tagged tipe/alasan/impact via PDF mapping.
Logic:
1. ROLE → valid TIPES (from ROLE_TO_TIPES)
2. TIPE → valid ALASANS (from TIPE_TO_ALASANS)
3. ALASAN → valid IMPACTS (from ALASAN_TO_IMPACTS)
Pick first match per cascade. Fallback: first candidate.
"""
import json, re
from collections import defaultdict


def load_pdf_mapping(path='/sessions/tender-vigilant-planck/mnt/outputs/pdf_mapping.json'):
    with open(path) as f:
        pdf = json.load(f)
    RTT, TTA, ATI = defaultdict(set), defaultdict(set), defaultdict(set)
    for m in pdf:
        if m.get('r') and m.get('t'): RTT[m['r']].add(m['t'])
        if m.get('t') and m.get('a'): TTA[m['t']].add(m['a'])
        if m.get('a') and m.get('i'): ATI[m['a']].add(m['i'])
    return dict(RTT), dict(TTA), dict(ATI)


def _norm_strict(s):
    """Lower + remove punct + collapse spaces (proper order)."""
    if not s: return ''
    t = str(s).lower().strip()
    t = re.sub(r'[^\w\s]', '', t)  # remove punct first
    t = re.sub(r'\s+', ' ', t)  # then collapse
    return t


def smart_split(text, candidates):
    """Split a multi-tagged field into candidate parts based on known PDF values.
    text: e.g. "Fulfillment Accuracy Fulfillment Accuracy Layanan Informasi Customer"
    candidates: set of known valid values (e.g. all PDF tipes)
    Returns: list of detected values
    """
    if not text:
        return []
    text = text.strip()
    # Try to match longest valid candidate at each position
    # Pre-compute normalized candidates: norm_form -> canonical
    sorted_cands = sorted(candidates, key=len, reverse=True)
    cand_norm_map = {_norm_strict(c): c for c in sorted_cands}
    cand_norm_sorted = sorted(cand_norm_map.keys(), key=len, reverse=True)
    found = []
    remaining = text
    while remaining:
        matched = False
        # Try strict-norm prefix match (tolerant of punct/case/whitespace)
        remaining_norm = _norm_strict(remaining)
        for c_norm in cand_norm_sorted:
            if remaining_norm.startswith(c_norm):
                # Match found - need to determine how many chars of original to consume
                # Strategy: find candidate-canonical match in remaining via fuzzy walk
                canonical = cand_norm_map[c_norm]
                # Consume original chars up to the end of the normalized match
                # Count words in canonical → match same word count in remaining
                cand_words = c_norm.split()
                if cand_words:
                    # Walk through remaining and find boundary after matching N words
                    words_matched = 0
                    pos = 0
                    in_word = False
                    while pos < len(remaining) and words_matched < len(cand_words):
                        ch = remaining[pos]
                        if re.match(r'\w', ch):
                            in_word = True
                        else:
                            if in_word:
                                words_matched += 1
                                in_word = False
                        pos += 1
                    if in_word and pos == len(remaining):
                        words_matched += 1
                    found.append(canonical)
                    remaining = remaining[pos:].strip(' ,/-')
                    matched = True
                    break
        if not matched:
            # Fall back to splitting by 2+ spaces or punct
            parts = re.split(r'[,;/]|\s{2,}', remaining, maxsplit=1)
            if len(parts) > 1:
                first = parts[0].strip()
                if first:
                    found.append(first)
                remaining = parts[1].strip()
            else:
                if remaining.strip():
                    found.append(remaining.strip())
                break
        if not matched:
            # Try splitting by common separators
            parts = re.split(r'[,;/]|\s{2,}', remaining, maxsplit=1)
            if len(parts) > 1:
                first = parts[0].strip()
                if first:
                    found.append(first)
                remaining = parts[1].strip()
            else:
                # Unknown — keep as is
                if remaining.strip():
                    found.append(remaining.strip())
                break
    return found


def normalize_complaint(role, tipe_raw, alasan_raw, impact_raw, RTT, TTA, ATI):
    """
    Returns: (tipe, alasan, impact) — cleaned, role-consistent.
    """
    # Get valid sets for this role
    valid_tipes = RTT.get(role, set())
    all_tipes = set()
    for s in RTT.values(): all_tipes.update(s)
    all_alasans = set()
    for s in TTA.values(): all_alasans.update(s)
    all_impacts = set()
    for s in ATI.values(): all_impacts.update(s)

    # === Step 1: Pick tipe ===
    tipe = (tipe_raw or '').strip()
    if not tipe:
        chosen_tipe = '(kosong)'
    else:
        cands_tipe = smart_split(tipe, all_tipes)
        # Filter by role validity
        if valid_tipes:
            role_valid = [t for t in cands_tipe if t in valid_tipes]
            chosen_tipe = role_valid[0] if role_valid else (cands_tipe[0] if cands_tipe else tipe)
        else:
            chosen_tipe = cands_tipe[0] if cands_tipe else tipe

    # === Step 2: Pick alasan based on chosen tipe ===
    alasan = (alasan_raw or '').strip()
    if not alasan:
        chosen_alasan = '(kosong)'
    else:
        cands_alasan = smart_split(alasan, all_alasans)
        valid_alasans_for_tipe = TTA.get(chosen_tipe, set())
        if valid_alasans_for_tipe:
            tipe_valid = [a for a in cands_alasan if a in valid_alasans_for_tipe]
            chosen_alasan = tipe_valid[0] if tipe_valid else (cands_alasan[0] if cands_alasan else alasan)
        else:
            chosen_alasan = cands_alasan[0] if cands_alasan else alasan

    # === Step 3: Pick impact based on chosen alasan ===
    impact = (impact_raw or '').strip()
    if not impact:
        chosen_impact = '(kosong)'
    else:
        # Impact often separated by comma
        parts = re.split(r',\s*', impact)
        parts = [p.strip() for p in parts if p.strip()]
        # Try matching by alasan validity
        valid_impacts_for_alasan = ATI.get(chosen_alasan, set())
        if valid_impacts_for_alasan and parts:
            alasan_valid = [p for p in parts if p in valid_impacts_for_alasan]
            chosen_impact = alasan_valid[0] if alasan_valid else parts[0]
        else:
            chosen_impact = parts[0] if parts else impact

    return chosen_tipe, chosen_alasan, chosen_impact


if __name__ == '__main__':
    # Test with example from user
    RTT, TTA, ATI = load_pdf_mapping()
    
    # Example 1: ticket 425747 (Customers)
    t, a, i = normalize_complaint(
        'Customers',
        'Fulfillment Accuracy Fulfillment Accuracy Layanan Informasi Customer',
        'Kurang Barang Informasi Lanjutan Keluhan Sebelumnya Kurang Barang',
        'Customer Menanyakan Kelanjutan Case Sebelumnya, Customer Infokan Ada Produk Yang Tidak Dikirimkan, Customer Infokan Ada Produk Yang Tidak Dikirimkan Kurang 1 Koli',
        RTT, TTA, ATI
    )
    print('Test 1 (Customers):')
    print(f'  Tipe   : {t}')
    print(f'  Alasan : {a}')
    print(f'  Impact : {i}')
    print()
    
    # Example 2: ticket 425745 (HW)
    t, a, i = normalize_complaint(
        'Hub Warehouse',
        'Fulfillment Accuracy Layanan Informasi Customer',
        'Kurang Barang',
        'Customer Infokan Ada Produk Yang Tidak Dikirimkan',
        RTT, TTA, ATI
    )
    print('Test 2 (HW):')
    print(f'  Tipe   : {t}')
    print(f'  Alasan : {a}')
    print(f'  Impact : {i}')
    print()
    
    # Example 3: ticket 425631 (Customers, reversed order)
    t, a, i = normalize_complaint(
        'Customers',
        'Layanan Informasi Customer Fulfillment Accuracy',
        'Customer Tidak Melanjutkan Percakapan Kendala Pada Pengiriman Kurang Barang',
        'Customer Yang Merasa Blm Terima Satu/Beberapa Produk Namun Setelah Cek Cctv Sudah Dikirimkan / Ternyata Nyelip Di Packaging, Customer Tidak Melanjutkan Percakapan',
        RTT, TTA, ATI
    )
    print('Test 3 (Customers, tipe reversed):')
    print(f'  Tipe   : {t}')
    print(f'  Alasan : {a}')
    print(f'  Impact : {i}')
