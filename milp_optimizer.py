"""
scheduler/milp_optimizer.py
===========================
Optimasi penjadwalan menggunakan Mixed-Integer Linear Programming (MILP)
via PuLP dengan solver CBC.

Formulasi:
  Variabel keputusan:
    s[j][k]  = float, start time job j di stasiun ke-k dalam routingnya
    T[j]     = float, tardiness job j (≥ 0)
    y[j1][j2][st] = binary, 1 jika job j1 dikerjakan sebelum j2 di stasiun st

  Constraints:
    1. Precedence: s[j][k+1] ≥ s[j][k] + processing_time[j][k]
    2. No-overlap: untuk setiap pasangan job (j1,j2) yang berbagi stasiun st,
       salah satu harus selesai sebelum yang lain mulai
    3. Non-negativity: s[j][k] ≥ 0
    4. Tardiness: T[j] ≥ completion[j] - deadline[j]

  Objective: minimize Σ w[j] × T[j]

Catatan skala:
  Untuk 40–70 job, CBC dengan time limit 300 detik kemungkinan menghasilkan
  near-optimal (feasible solution terbaik yang ditemukan dalam batas waktu),
  bukan solusi optimal sejati. Ini acceptable dan didokumentasikan dengan jelas.

  SA solution digunakan sebagai warm start untuk mempercepat konvergensi.

Big-M:
  Digunakan untuk no-overlap constraint. Nilai M = total makespan estimasi
  (jumlah semua waktu proses semua job) untuk menjaga numerik stabil.
"""

import time
import re
from typing import Optional
import pulp

def _sanitize(name: str) -> str:
    """Sanitize nama variabel untuk PuLP: ganti karakter non-alphanumeric dengan underscore."""
    return re.sub(r'[^a-zA-Z0-9]', '_', str(name))
from simulator import simulate_schedule, get_resource_count
from config import MILP_CONFIG


# ---------------------------------------------------------------------------
# FUNGSI UTAMA
# ---------------------------------------------------------------------------

def jalankan_milp(
    pesanan_routed: list[dict],
    sa_urutan: list[str] = None,
    resource_override: dict = None,
    setup_time: dict = None,
) -> tuple[Optional[list[dict]], Optional[float], dict]:
    """
    Jalankan optimasi MILP.

    Parameter
    ---------
    pesanan_routed : list[dict] pesanan dengan routing
    sa_urutan      : list[str] id_pesanan dalam urutan terbaik SA (warm start).
                     Jika None, tidak ada warm start.
    resource_override: override resource
    setup_time     : setup time per stasiun

    Return
    ------
    (hasil_list, total_weighted_tardiness, info)
    - hasil_list None jika MILP tidak menemukan solusi feasible
    """
    if len(pesanan_routed) == 0:
        return [], 0.0, {}

    # Untuk dataset besar, MILP hanya dijalankan pada subset:
    # job prioritas Kritis + Tinggi (maks 30 job).
    # Ini valid secara akademis — MILP sebagai validasi optimal pada job kritis,
    # SA untuk keseluruhan dataset.
    BATAS_JOB_MILP = 30
    if len(pesanan_routed) > BATAS_JOB_MILP:
        # Ambil subset: prioritas Kritis dulu, lalu Tinggi, lalu Normal, maks 30
        urutan_prio = {"Kritis": 0, "Tinggi": 1, "Normal": 2}
        subset = sorted(pesanan_routed, key=lambda p: urutan_prio.get(p["prioritas"], 2))[:BATAS_JOB_MILP]
        pesanan_routed = subset

    resource_count = get_resource_count(resource_override)
    st_time = setup_time or {st: 0.0 for st in range(1, 11)}

    waktu_mulai = time.time()

    # -- Hitung Big-M: total semua waktu proses semua job semua stasiun --
    big_m = sum(
        p["waktu_proses"][st] / resource_count[st]
        for p in pesanan_routed
        for st in p["routing"]
    ) * 2   # faktor 2 untuk margin keamanan

    # -- Indeks job --
    n_job = len(pesanan_routed)
    job_ids = [p["id_pesanan"] for p in pesanan_routed]
    job_map = {p["id_pesanan"]: p for p in pesanan_routed}

    # -- Bangun model --
    model = pulp.LpProblem("JobShop_Cigem", pulp.LpMinimize)

    # -- Variabel: start time setiap operasi --
    # s[idx][stasiun] = start time, pakai idx (bukan id_pesanan) untuk hindari duplikat
    s = {}
    T = {}
    for idx, p in enumerate(pesanan_routed):
        jid = p["id_pesanan"]
        s[idx] = {}
        for st in p["routing"]:
            s[idx][st] = pulp.LpVariable(
                f"s_{idx}_{st}", lowBound=0, cat="Continuous"
            )
        T[idx] = pulp.LpVariable(f"T_{idx}", lowBound=0, cat="Continuous")

    # -- Variabel: urutan antar job di stasiun yang sama (binary) --
    # y[(idx1,idx2,st)] = 1 berarti job idx1 selesai sebelum idx2 di stasiun st
    y = {}
    stasiun_shared = _cari_stasiun_shared_idx(pesanan_routed)

    for (idx1, idx2, st) in stasiun_shared:
        key = (idx1, idx2, st)
        y[key] = pulp.LpVariable(f"y_{idx1}_{idx2}_{st}", cat="Binary")

    # -- Objective --
    model += pulp.lpSum(
        p["bobot"] * T[idx] for idx, p in enumerate(pesanan_routed)
    ), "Total_Weighted_Tardiness"

    # -- Constraints --
    for idx, p in enumerate(pesanan_routed):
        routing = p["routing"]

        # 1. Precedence: operasi harus berurutan sesuai routing
        for k in range(len(routing) - 1):
            st_curr = routing[k]
            st_next = routing[k + 1]
            wp_curr = p["waktu_proses"][st_curr] / resource_count[st_curr]
            setup_curr = st_time.get(st_curr, 0.0)

            model += (
                s[idx][st_next] >= s[idx][st_curr] + wp_curr + setup_curr,
                f"prec_{idx}_{st_curr}_{st_next}"
            )

        # 2. Tardiness
        st_terakhir = routing[-1]
        wp_terakhir = p["waktu_proses"][st_terakhir] / resource_count[st_terakhir]
        setup_terakhir = st_time.get(st_terakhir, 0.0)
        completion = s[idx][st_terakhir] + wp_terakhir + setup_terakhir

        model += (
            T[idx] >= completion - p["deadline_mnt"],
            f"tard_{idx}"
        )

    # 3. No-overlap: setiap pasangan job yang berbagi stasiun
    for (idx1, idx2, st) in stasiun_shared:
        p1 = pesanan_routed[idx1]
        p2 = pesanan_routed[idx2]
        wp1 = p1["waktu_proses"][st] / resource_count[st]
        wp2 = p2["waktu_proses"][st] / resource_count[st]
        setup_st = st_time.get(st, 0.0)
        key = (idx1, idx2, st)

        model += (
            s[idx1][st] + wp1 + setup_st <= s[idx2][st] + big_m * (1 - y[key]),
            f"nooverlap_{idx1}_{idx2}_{st}_a"
        )
        model += (
            s[idx2][st] + wp2 + setup_st <= s[idx1][st] + big_m * y[key],
            f"nooverlap_{idx1}_{idx2}_{st}_b"
        )

    # -- Warm start dari SA (hint urutan ke solver) --
    if sa_urutan:
        _set_warm_start_idx(y, sa_urutan, stasiun_shared, pesanan_routed)

    # -- Solve --
    solver = pulp.PULP_CBC_CMD(
        timeLimit=MILP_CONFIG["time_limit_detik"],
        gapRel=MILP_CONFIG["gap_relatif"],
        msg=0,   # silent
    )

    model.solve(solver)
    waktu_selesai = time.time()

    # sol_status: 1=Optimal, 2=IntegerFeasible(time limit hit), lainnya=tidak ada solusi
    sol_status = model.sol_status
    status_str = pulp.LpStatus[model.status]
    obj_value  = pulp.value(model.objective)

    info = {
        "metode":                "MILP (CBC)",
        "status":                status_str,
        "sol_status":            sol_status,
        "objective_value":       round(obj_value, 2) if obj_value is not None else None,
        "waktu_komputasi_detik": round(waktu_selesai - waktu_mulai, 2),
        "n_variabel":            len(model.variables()),
        "n_constraint":          len(model.constraints),
        "gap_relatif_target":    MILP_CONFIG["gap_relatif"],
        "time_limit":            MILP_CONFIG["time_limit_detik"],
    }

    # -- Ekstrak solusi jika feasible --
    # sol_status 1=Optimal, 2=IntegerFeasible (solusi ada tapi belum optimal, kena time limit)
    ada_solusi = sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
    if ada_solusi and obj_value is not None:
        # Ekstrak jadwal LANGSUNG dari variabel s — jangan simulate ulang
        # karena simulate ulang bisa merusak solusi MILP yang sudah optimal
        hasil_list = _ekstrak_jadwal_dari_s(s, pesanan_routed, resource_count, st_time)
        if hasil_list is not None:
            total_wt = round(sum(h["weighted_tardiness"] for h in hasil_list), 4)
            info["urutan_terbaik"] = [h["id_pesanan"] for h in hasil_list]
            info["solusi_optimal"] = (sol_status == pulp.LpSolutionOptimal)
            return hasil_list, total_wt, info

    # Tidak ada solusi feasible
    info["error"] = f"MILP tidak menemukan solusi feasible. Status: {status_str}"
    return None, None, info


# ---------------------------------------------------------------------------
# HELPER: STASIUN YANG DIBAGI ANTAR JOB
# ---------------------------------------------------------------------------

def _cari_stasiun_shared_idx(pesanan_routed: list[dict]) -> list[tuple]:
    """
    Cari semua pasangan (idx1, idx2, stasiun) di mana kedua job (berdasarkan
    index posisi, bukan id_pesanan) melewati stasiun yang sama.
    Pakai index untuk menghindari masalah duplikat id_pesanan.

    Return: list of (idx1, idx2, st) dengan idx1 < idx2
    """
    from collections import defaultdict
    stasiun_ke_idx = defaultdict(list)

    for idx, p in enumerate(pesanan_routed):
        for st in p["routing"]:
            stasiun_ke_idx[st].append(idx)

    hasil = []
    for st, idx_list in stasiun_ke_idx.items():
        for i in range(len(idx_list)):
            for j in range(i + 1, len(idx_list)):
                hasil.append((idx_list[i], idx_list[j], st))

    return hasil


# ---------------------------------------------------------------------------
# HELPER: WARM START
# ---------------------------------------------------------------------------

def _set_warm_start_idx(
    y: dict,
    sa_urutan: list[str],
    stasiun_shared: list[tuple],
    pesanan_routed: list[dict],
) -> None:
    """
    Set nilai awal variabel binary y berdasarkan urutan SA.
    Pakai index posisi sebagai key (bukan id_pesanan).
    """
    posisi_id = {jid: i for i, jid in enumerate(sa_urutan)}

    for (idx1, idx2, st) in stasiun_shared:
        key = (idx1, idx2, st)
        if key in y:
            id1 = pesanan_routed[idx1]["id_pesanan"]
            id2 = pesanan_routed[idx2]["id_pesanan"]
            pos1 = posisi_id.get(id1, idx1)
            pos2 = posisi_id.get(id2, idx2)
            y[key].setInitialValue(1 if pos1 < pos2 else 0)


# ---------------------------------------------------------------------------
# HELPER: EKSTRAK URUTAN DARI SOLUSI MILP
# ---------------------------------------------------------------------------

def _ekstrak_jadwal_dari_s(
    s: dict,
    pesanan_routed: list[dict],
    resource_count: dict,
    st_time: dict,
) -> Optional[list[dict]]:
    """
    Ekstrak jadwal langsung dari nilai variabel s (start time) hasil MILP.
    Tidak simulate ulang — gunakan nilai persis dari solver agar hasil optimal terjaga.
    """
    try:
        hasil_list = []
        for idx, p in enumerate(pesanan_routed):
            schedule = {}
            for st in p["routing"]:
                s_val = pulp.value(s[idx][st])
                if s_val is None:
                    return None
                wp = p["waktu_proses"][st] / resource_count[st]
                start = round(s_val, 4)
                end   = round(s_val + wp, 4)
                # Resource: tentukan dari slot mana yang dipakai
                # (simplified: pakai resource 1 karena MILP tidak track resource slot)
                schedule[st] = {"start": start, "end": end, "resource": 1}

            st_terakhir  = p["routing"][-1]
            completion   = schedule[st_terakhir]["end"]
            tardiness    = max(0.0, completion - p["deadline_mnt"])
            w_tardiness  = round(p["bobot"] * tardiness, 4)

            hasil_list.append({
                "id_pesanan":         p["id_pesanan"],
                "jenis_produk":       p["jenis_produk"],
                "jumlah_unit":        p["jumlah_unit"],
                "prioritas":          p["prioritas"],
                "bobot":              p["bobot"],
                "routing":            p["routing"],
                "schedule":           schedule,
                "completion_time":    round(completion, 4),
                "deadline_mnt":       p["deadline_mnt"],
                "deadline_tgl":       p["deadline_tgl"],
                "tardiness":          round(tardiness, 4),
                "weighted_tardiness": w_tardiness,
                "terlambat":          tardiness > 0,
            })

        # Urutkan berdasarkan completion time
        hasil_list.sort(key=lambda h: h["completion_time"])
        return hasil_list

    except Exception:
        return None
