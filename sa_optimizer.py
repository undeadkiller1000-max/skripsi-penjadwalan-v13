"""
scheduler/sa_optimizer.py
=========================
Optimasi penjadwalan menggunakan Simulated Annealing (SA).

Alur:
1. Mulai dari urutan awal berdasarkan EDD (Earliest Due Date)
2. Lakukan 8.000 iterasi pertukaran posisi job (swap / insert)
3. Terima solusi yang lebih baik selalu; solusi lebih buruk diterima
   dengan probabilitas exp(-delta/T) yang menurun seiring suhu turun
4. Kembalikan urutan terbaik yang pernah ditemukan beserta jadwal detailnya

Dua jenis pertukaran (neighborhood move):
  - SWAP  : tukar posisi dua job secara acak
  - INSERT: ambil satu job, sisipkan ke posisi lain
Kedua jenis bergantian untuk diversifikasi eksplorasi.
"""

import random
import math
import time
from simulator import simulate_schedule, evaluate_sequence, get_resource_count
from config import SA_CONFIG


# ---------------------------------------------------------------------------
# FUNGSI UTAMA
# ---------------------------------------------------------------------------

def jalankan_sa(
    pesanan_routed: list[dict],
    resource_override: dict = None,
    setup_time: dict = None,
    callback_progress=None,
) -> tuple[list[dict], float, dict]:
    """
    Jalankan Simulated Annealing.

    Parameter
    ---------
    pesanan_routed   : list[dict] pesanan dengan routing
    resource_override: override resource (untuk crashing)
    setup_time       : setup time per stasiun
    callback_progress: fungsi opsional callback(iterasi, suhu, best_wt)
                       untuk update progress bar di Streamlit

    Return
    ------
    (hasil_list, total_weighted_tardiness, info)
    - hasil_list : detail jadwal dari urutan terbaik SA
    - total_wt   : total weighted tardiness terbaik
    - info       : dict metadata (waktu komputasi, iterasi, dll)
    """
    if len(pesanan_routed) == 0:
        return [], 0.0, {}

    resource_count = get_resource_count(resource_override)
    st_time = setup_time or {st: 0.0 for st in range(1, 11)}

    # -- Parameter SA --
    n_iterasi        = SA_CONFIG["n_iterasi"]
    suhu             = SA_CONFIG["suhu_awal"]
    laju_pendinginan = SA_CONFIG["laju_pendinginan"]
    rng              = random.Random(SA_CONFIG["seed"])

    # -- Urutan awal: EDD (Earliest Due Date) --
    urutan_sekarang = sorted(pesanan_routed, key=lambda p: p["deadline_mnt"])
    wt_sekarang     = evaluate_sequence(urutan_sekarang, resource_count, st_time)

    urutan_terbaik  = urutan_sekarang[:]
    wt_terbaik      = wt_sekarang

    waktu_mulai = time.time()
    n_diterima  = 0
    n_memburuk_diterima = 0

    for iterasi in range(n_iterasi):
        # -- Generate tetangga --
        urutan_baru = _generate_neighbor(urutan_sekarang, rng, iterasi)
        wt_baru     = evaluate_sequence(urutan_baru, resource_count, st_time)

        # -- Keputusan penerimaan --
        delta = wt_baru - wt_sekarang

        if delta <= 0:
            # Solusi lebih baik atau sama: selalu terima
            urutan_sekarang = urutan_baru
            wt_sekarang     = wt_baru
            n_diterima += 1

            if wt_baru < wt_terbaik:
                urutan_terbaik = urutan_baru[:]
                wt_terbaik     = wt_baru
        else:
            # Solusi lebih buruk: terima dengan probabilitas Boltzmann
            prob = math.exp(-delta / suhu) if suhu > 1e-10 else 0.0
            if rng.random() < prob:
                urutan_sekarang = urutan_baru
                wt_sekarang     = wt_baru
                n_diterima += 1
                n_memburuk_diterima += 1

        # -- Pendinginan suhu --
        suhu *= laju_pendinginan

        # -- Callback progress (setiap 500 iterasi) --
        if callback_progress and iterasi % 500 == 0:
            callback_progress(iterasi, suhu, wt_terbaik)

        # -- Early stopping: jika weighted tardiness sudah 0, tidak perlu lanjut --
        if wt_terbaik == 0.0:
            break

    waktu_selesai = time.time()

    # -- Simulasi penuh dari urutan terbaik untuk mendapat detail jadwal --
    hasil_list, total_wt_final = simulate_schedule(
        urutan_terbaik,
        resource_override=resource_override,
        setup_time=setup_time,
    )

    info = {
        "metode":               "Simulated Annealing",
        "n_iterasi_dijalankan": iterasi + 1,
        "n_iterasi_max":        n_iterasi,
        "wt_terbaik":           wt_terbaik,
        "wt_awal_edd":          evaluate_sequence(
                                    sorted(pesanan_routed, key=lambda p: p["deadline_mnt"]),
                                    resource_count, st_time
                                ),
        "n_diterima":           n_diterima,
        "n_memburuk_diterima":  n_memburuk_diterima,
        "waktu_komputasi_detik": round(waktu_selesai - waktu_mulai, 2),
        "suhu_akhir":           round(suhu, 6),
        "urutan_terbaik":       [p["id_pesanan"] for p in urutan_terbaik],
    }

    return hasil_list, total_wt_final, info


# ---------------------------------------------------------------------------
# NEIGHBORHOOD MOVE
# ---------------------------------------------------------------------------

def _generate_neighbor(urutan: list, rng: random.Random, iterasi: int) -> list:
    """
    Generate urutan tetangga dengan salah satu dari dua jenis move:
    - SWAP  : tukar dua posisi acak (lebih baik di awal saat eksplorasi luas)
    - INSERT: ambil satu job, sisipkan ke posisi lain (intensifikasi)

    Bergantian setiap 100 iterasi untuk keseimbangan eksplorasi/intensifikasi.
    """
    n = len(urutan)
    if n <= 1:
        return urutan[:]

    baru = urutan[:]

    if (iterasi // 100) % 2 == 0:
        # SWAP
        i, j = rng.sample(range(n), 2)
        baru[i], baru[j] = baru[j], baru[i]
    else:
        # INSERT: ambil job di posisi i, sisipkan di posisi j
        i = rng.randrange(n)
        j = rng.randrange(n)
        if i != j:
            job = baru.pop(i)
            baru.insert(j, job)

    return baru
