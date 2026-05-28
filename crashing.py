"""
features/crashing.py
====================
Analisis crashing: mencari resource tambahan minimum yang dibutuhkan
agar seluruh (atau sebagian) pesanan selesai tepat waktu.

Tiga skenario:
  1. Target tanggal : semua selesai sebelum tanggal tertentu
  2. Target persen  : percepat makespan sebesar X%
  3. Realita Cigem  : hanya tambah tim jahit kaos/polo (St.2), maks 3 tim

Strategi greedy (skenario 1 & 2):
  Pada setiap langkah, tambahkan 1 unit resource pada stasiun yang
  memberikan pengurangan weighted tardiness terbesar.
  Ulangi hingga target tercapai atau semua stasiun sudah di kapasitas maks.

Stasiun yang bisa di-crash (skenario 1 & 2):
  Dipilih sendiri oleh pengguna via checkbox di UI.
"""

import copy
from datetime import date
from sa_optimizer import jalankan_sa
from simulator import ringkasan_performa, get_resource_count
from calendar_utils import deadline_ke_menit
from config import RESOURCE_CONFIG, STASIUN


# ---------------------------------------------------------------------------
# SKENARIO 1: TARGET TANGGAL
# ---------------------------------------------------------------------------

def crashing_target_tanggal(
    pesanan_routed: list[dict],
    tanggal_target: date,
    tanggal_mulai: date,
    stasiun_bisa_crash: list[int],
    setup_time: dict = None,
) -> dict:
    """
    Tambah resource secara greedy sampai semua pesanan selesai
    sebelum atau pada tanggal_target.

    Return: dict hasil crashing (lihat _format_hasil)
    """
    # Konversi tanggal target ke menit efektif
    target_mnt = deadline_ke_menit(tanggal_mulai, tanggal_target)

    def sudah_tercapai(resource_current):
        hasil, _, __ = jalankan_sa(pesanan_routed,
                               resource_override=resource_current,
                               setup_time=setup_time)
        return (
            all(h["completion_time"] <= target_mnt for h in hasil),
            hasil,
        )

    return _greedy_crash(
        pesanan_routed, stasiun_bisa_crash, sudah_tercapai,
        setup_time, label=f"Selesai sebelum {tanggal_target.strftime('%d/%m/%Y')}"
    )


# ---------------------------------------------------------------------------
# SKENARIO 2: TARGET PERSEN PERCEPATAN
# ---------------------------------------------------------------------------

def crashing_target_persen(
    pesanan_routed: list[dict],
    persen_percepatan: float,
    stasiun_bisa_crash: list[int],
    setup_time: dict = None,
) -> dict:
    """
    Tambah resource secara greedy sampai total weighted tardiness
    berkurang sebesar persen_percepatan dari kondisi awal.

    persen_percepatan : 0–100 (misal 30 = turun 30%)
    """
    # Hitung baseline dulu
    hasil_awal, wt_awal, _ = jalankan_sa(pesanan_routed, setup_time=setup_time)
    target_wt = wt_awal * (1 - persen_percepatan / 100)

    def sudah_tercapai(resource_current):
        hasil, wt, _ = jalankan_sa(pesanan_routed,
                                resource_override=resource_current,
                                setup_time=setup_time)
        return wt <= target_wt, hasil

    return _greedy_crash(
        pesanan_routed, stasiun_bisa_crash, sudah_tercapai,
        setup_time,
        label=f"WTardiness turun {persen_percepatan:.0f}%",
        wt_awal=wt_awal,
    )


# ---------------------------------------------------------------------------
# SKENARIO 3: REALITA CIGEM (HANYA TAMBAH TIM JAHIT KAOS/POLO)
# ---------------------------------------------------------------------------

def crashing_realita_cigem(
    pesanan_routed: list[dict],
    setup_time: dict = None,
) -> dict:
    """
    Uji setiap level penambahan tim di St.2 (Jahit Kaos/Polo): 1, 2, 3 tim.
    Temukan jumlah tim minimum yang menghilangkan seluruh keterlambatan.

    Return: dict hasil per level + rekomendasi minimum.
    """
    hasil_per_level = []
    rekomendasi_tim = None

    for n_tim in range(1, RESOURCE_CONFIG[2]["max"] + 1):
        resource_override = {2: n_tim}
        hasil, wt, _ = jalankan_sa(
            pesanan_routed,
            resource_override=resource_override,
            setup_time=setup_time,
        )
        perf = ringkasan_performa(hasil)
        level_info = {
            "n_tim":               n_tim,
            "resource_override":   resource_override,
            "hasil":               hasil,
            "total_wt":            wt,
            "n_terlambat":         perf["n_terlambat"],
            "n_tepat_waktu":       perf["n_tepat_waktu"],
            "pct_tepat_waktu":     perf["pct_tepat_waktu"],
        }
        hasil_per_level.append(level_info)

        # Tandai level minimum yang menghilangkan semua keterlambatan
        if rekomendasi_tim is None and perf["n_terlambat"] == 0:
            rekomendasi_tim = n_tim

    # Baseline (kondisi default)
    hasil_default, wt_default, _ = jalankan_sa(pesanan_routed, setup_time=setup_time)
    perf_default = ringkasan_performa(hasil_default)

    return {
        "skenario":         "Realita Cigem — Tambah Tim Jahit Kaos/Polo",
        "baseline":         {
            "n_tim":        RESOURCE_CONFIG[2]["default"],
            "total_wt":     wt_default,
            "n_terlambat":  perf_default["n_terlambat"],
        },
        "hasil_per_level":  hasil_per_level,
        "rekomendasi_tim":  rekomendasi_tim,
        "zero_tardiness_possible": rekomendasi_tim is not None,
    }


# ---------------------------------------------------------------------------
# GREEDY CRASH (dipakai skenario 1 & 2)
# ---------------------------------------------------------------------------

def _greedy_crash(
    pesanan_routed: list[dict],
    stasiun_bisa_crash: list[int],
    fn_tercapai,
    setup_time: dict,
    label: str = "",
    wt_awal: float = None,
) -> dict:
    """
    Greedy: tambah 1 resource di stasiun yang memberikan dampak terbesar,
    sampai target tercapai atau semua stasiun sudah maks.

    fn_tercapai(resource_current) -> (bool, hasil_list)
    """
    resource_current = {st: RESOURCE_CONFIG[st]["default"] for st in RESOURCE_CONFIG}
    langkah_list     = []

    # Cek apakah kondisi awal sudah memenuhi target
    tercapai, hasil_awal = fn_tercapai(resource_current)
    wt_awal_actual = sum(h["weighted_tardiness"] for h in hasil_awal)

    if tercapai:
        return _format_hasil(
            langkah_list, resource_current, hasil_awal,
            wt_awal_actual, wt_awal_actual, label, tercapai=True
        )

    max_langkah = sum(
        RESOURCE_CONFIG[st]["max"] - RESOURCE_CONFIG[st]["default"]
        for st in stasiun_bisa_crash
    )

    for langkah in range(max(max_langkah, 1)):
        # Cari stasiun yang jika ditambah 1 resource memberikan WTard terkecil
        kandidat = []
        for st in stasiun_bisa_crash:
            if resource_current[st] >= RESOURCE_CONFIG[st]["max"]:
                continue   # sudah maks
            # Coba tambah 1 di stasiun ini
            rc_coba = dict(resource_current)
            rc_coba[st] += 1
            _, hasil_coba = fn_tercapai(rc_coba)
            wt_coba = sum(h["weighted_tardiness"] for h in hasil_coba)
            kandidat.append((wt_coba, st, rc_coba, hasil_coba))

        if not kandidat:
            break   # semua stasiun sudah maks

        # Pilih yang memberikan WTard terkecil
        kandidat.sort(key=lambda x: x[0])
        wt_terbaik, st_terpilih, resource_current, hasil_sekarang = kandidat[0]

        langkah_list.append({
            "langkah":          langkah + 1,
            "stasiun_ditambah": f"St.{st_terpilih} – {STASIUN[st_terpilih]}",
            "resource_baru":    resource_current[st_terpilih],
            "wt_setelah":       round(wt_terbaik, 2),
            "n_terlambat":      sum(1 for h in hasil_sekarang if h["terlambat"]),
        })

        tercapai, _ = fn_tercapai(resource_current)
        if tercapai:
            break

    _, hasil_final = fn_tercapai(resource_current)
    wt_final = sum(h["weighted_tardiness"] for h in hasil_final)

    return _format_hasil(
        langkah_list, resource_current, hasil_final,
        wt_awal_actual, wt_final, label, tercapai
    )


# ---------------------------------------------------------------------------
# FORMAT HASIL
# ---------------------------------------------------------------------------

def _format_hasil(
    langkah_list, resource_final, hasil_final,
    wt_awal, wt_final, label, tercapai
) -> dict:
    perf = ringkasan_performa(hasil_final)

    # Hitung resource yang ditambahkan vs default
    resource_tambahan = {
        st: resource_final[st] - RESOURCE_CONFIG[st]["default"]
        for st in resource_final
        if resource_final[st] != RESOURCE_CONFIG[st]["default"]
    }

    improvement = (
        round((wt_awal - wt_final) / wt_awal * 100, 1)
        if wt_awal > 0 else 0.0
    )

    return {
        "label":              label,
        "tercapai":           tercapai,
        "langkah":            langkah_list,
        "resource_final":     resource_final,
        "resource_tambahan":  resource_tambahan,
        "hasil_final":        hasil_final,
        "wt_awal":            round(wt_awal, 2),
        "wt_final":           round(wt_final, 2),
        "improvement_pct":    improvement,
        "n_terlambat_final":  perf["n_terlambat"],
        "pct_tepat_waktu":    perf["pct_tepat_waktu"],
    }
