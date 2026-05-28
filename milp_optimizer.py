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
    # s[job_id][stasiun] = start time
    s = {}
    for p in pesanan_routed:
        jid = p["id_pesanan"]
        s[jid] = {}
        for st in p["routing"]:
            s[jid][st] = pulp.LpVariable(
                f"s_{_sanitize(jid)}_{st}", lowBound=0, cat="Continuous"
            )

    # -- Variabel: tardiness --
    T = {
        p["id_pesanan"]: pulp.LpVariable(f"T_{_sanitize(p['id_pesanan'])}", lowBound=0, cat="Continuous")
        for p in pesanan_routed
    }

    # -- Variabel: urutan antar job di stasiun yang sama (binary) --
    # y[j1_id][j2_id][st] = 1 berarti j1 selesai sebelum j2 mulai di stasiun st
    y = {}
    stasiun_shared = _cari_stasiun_shared(pesanan_routed)

    for (j1_id, j2_id, st) in stasiun_shared:
        key = (j1_id, j2_id, st)
        y[key] = pulp.LpVariable(f"y_{_sanitize(j1_id)}_{_sanitize(j2_id)}_{st}", cat="Binary")

    # -- Objective --
    model += pulp.lpSum(
        p["bobot"] * T[p["id_pesanan"]] for p in pesanan_routed
    ), "Total_Weighted_Tardiness"

    # -- Constraints --
    for p in pesanan_routed:
        jid     = p["id_pesanan"]
        routing = p["routing"]

        # 1. Precedence: operasi harus berurutan sesuai routing
        for k in range(len(routing) - 1):
            st_curr = routing[k]
            st_next = routing[k + 1]
            wp_curr = p["waktu_proses"][st_curr] / resource_count[st_curr]
            setup_curr = st_time.get(st_curr, 0.0)

            model += (
                s[jid][st_next] >= s[jid][st_curr] + wp_curr + setup_curr,
                f"prec_{jid}_{st_curr}_{st_next}"
            )

        # 2. Tardiness
        st_terakhir = routing[-1]
        wp_terakhir = p["waktu_proses"][st_terakhir] / resource_count[st_terakhir]
        setup_terakhir = st_time.get(st_terakhir, 0.0)
        completion = s[jid][st_terakhir] + wp_terakhir + setup_terakhir

        model += (
            T[jid] >= completion - p["deadline_mnt"],
            f"tard_{jid}"
        )

    # 3. No-overlap: setiap pasangan job yang berbagi stasiun
    for (j1_id, j2_id, st) in stasiun_shared:
        p1 = job_map[j1_id]
        p2 = job_map[j2_id]
        wp1 = p1["waktu_proses"][st] / resource_count[st]
        wp2 = p2["waktu_proses"][st] / resource_count[st]
        setup_st = st_time.get(st, 0.0)
        key = (j1_id, j2_id, st)

        # j1 selesai sebelum j2 mulai, ATAU j2 selesai sebelum j1 mulai
        model += (
            s[j1_id][st] + wp1 + setup_st <= s[j2_id][st] + big_m * (1 - y[key]),
            f"nooverlap_{j1_id}_{j2_id}_{st}_a"
        )
        model += (
            s[j2_id][st] + wp2 + setup_st <= s[j1_id][st] + big_m * y[key],
            f"nooverlap_{j1_id}_{j2_id}_{st}_b"
        )

    # -- Warm start dari SA (hint urutan ke solver) --
    if sa_urutan:
        _set_warm_start(y, sa_urutan, stasiun_shared, job_map)

    # -- Solve --
    solver = pulp.PULP_CBC_CMD(
        timeLimit=MILP_CONFIG["time_limit_detik"],
        gapRel=MILP_CONFIG["gap_relatif"],
        msg=0,   # silent
    )

    status = model.solve(solver)
    waktu_selesai = time.time()

    status_str = pulp.LpStatus[model.status]
    obj_value  = pulp.value(model.objective)

    info = {
        "metode":                "MILP (CBC)",
        "status":                status_str,
        "objective_value":       round(obj_value, 2) if obj_value is not None else None,
        "waktu_komputasi_detik": round(waktu_selesai - waktu_mulai, 2),
        "n_variabel":            len(model.variables()),
        "n_constraint":          len(model.constraints),
        "gap_relatif_target":    MILP_CONFIG["gap_relatif"],
        "time_limit":            MILP_CONFIG["time_limit_detik"],
    }

    # -- Ekstrak solusi jika feasible --
    if status in (1, -1) and obj_value is not None:
        # status 1 = Optimal, -1 = Not solved but feasible (time limit hit)
        urutan_milp = _ekstrak_urutan(s, pesanan_routed, resource_count, st_time)
        if urutan_milp is not None:
            hasil_list, total_wt = simulate_schedule(
                urutan_milp,
                resource_override=resource_override,
                setup_time=setup_time,
            )
            info["urutan_terbaik"] = [p["id_pesanan"] for p in urutan_milp]
            info["solusi_optimal"] = (status == 1)
            return hasil_list, total_wt, info

    # Tidak ada solusi feasible
    info["error"] = f"MILP tidak menemukan solusi feasible. Status: {status_str}"
    return None, None, info


# ---------------------------------------------------------------------------
# HELPER: STASIUN YANG DIBAGI ANTAR JOB
# ---------------------------------------------------------------------------

def _cari_stasiun_shared(pesanan_routed: list[dict]) -> list[tuple]:
    """
    Cari semua pasangan (job1, job2, stasiun) di mana kedua job
    melewati stasiun yang sama. Digunakan untuk no-overlap constraint.

    Return: list of (j1_id, j2_id, st) dengan j1_id < j2_id (lexicographic)
    """
    from collections import defaultdict
    stasiun_ke_jobs = defaultdict(list)

    for p in pesanan_routed:
        for st in p["routing"]:
            stasiun_ke_jobs[st].append(p["id_pesanan"])

    hasil = []
    for st, jobs in stasiun_ke_jobs.items():
        for i in range(len(jobs)):
            for j in range(i + 1, len(jobs)):
                j1, j2 = sorted([jobs[i], jobs[j]])
                hasil.append((j1, j2, st))

    return hasil


# ---------------------------------------------------------------------------
# HELPER: WARM START
# ---------------------------------------------------------------------------

def _set_warm_start(
    y: dict,
    sa_urutan: list[str],
    stasiun_shared: list[tuple],
    job_map: dict,
) -> None:
    """
    Set nilai awal variabel binary y berdasarkan urutan SA.
    y[j1][j2][st] = 1 jika j1 datang sebelum j2 dalam urutan SA.
    """
    posisi = {jid: i for i, jid in enumerate(sa_urutan)}

    for (j1_id, j2_id, st) in stasiun_shared:
        key = (j1_id, j2_id, st)
        if key in y:
            pos1 = posisi.get(j1_id, 0)
            pos2 = posisi.get(j2_id, 0)
            # j1 sebelum j2 → y=1
            y[key].setInitialValue(1 if pos1 < pos2 else 0)


# ---------------------------------------------------------------------------
# HELPER: EKSTRAK URUTAN DARI SOLUSI MILP
# ---------------------------------------------------------------------------

def _ekstrak_urutan(
    s: dict,
    pesanan_routed: list[dict],
    resource_count: dict,
    st_time: dict,
) -> Optional[list[dict]]:
    """
    Dari nilai variabel s (start time), tentukan urutan job berdasarkan
    completion time masing-masing job, lalu kembalikan list pesanan
    dalam urutan tersebut untuk di-simulate ulang.

    Pendekatan ini lebih robust daripada mencoba merekonstruksi jadwal
    langsung dari variabel MILP (yang bisa ada numerical issue).
    """
    try:
        completion_times = []
        for p in pesanan_routed:
            jid = p["id_pesanan"]
            st_terakhir = p["routing"][-1]
            wp_terakhir = p["waktu_proses"][st_terakhir] / resource_count[st_terakhir]
            setup_terakhir = st_time.get(st_terakhir, 0.0)

            s_val = pulp.value(s[jid][st_terakhir])
            if s_val is None:
                return None
            ct = s_val + wp_terakhir + setup_terakhir
            completion_times.append((ct, p["id_pesanan"], p))

        completion_times.sort(key=lambda x: x[0])
        return [item[2] for item in completion_times]

    except Exception:
        return None
