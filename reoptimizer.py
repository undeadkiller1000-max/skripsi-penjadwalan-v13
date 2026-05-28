"""
features/reoptimizer.py
=======================
Re-optimasi jadwal ketika pesanan baru masuk di tengah produksi berjalan.

Konsep:
  - Pesanan terkunci (sudah mulai/selesai): posisinya tidak boleh diubah
  - Pesanan bebas + baru: dijadwalkan ulang dengan SA
  - Resource yang dipakai pesanan terkunci tidak bisa disentuh pesanan lain
"""

import random
import math
import time
from datetime import date
from calendar_utils import menit_ke_tanggal_waktu, tanggal_kerja_ke_n
from simulator import get_resource_count
from config import SA_CONFIG


def jalankan_reoptimasi(
    pesanan_terkunci: list,
    pesanan_bebas: list,
    pesanan_baru: list,
    tanggal_mulai: date,
    resource_override: dict = None,
    setup_time: dict = None,
) -> dict:
    """
    Re-optimasi dengan mempertahankan posisi pesanan terkunci.

    Return dict:
      jadwal_lengkap, jadwal_baru, total_wt,
      dampak, rekomendasi_deadline, waktu_komputasi
    """
    resource_count = get_resource_count(resource_override)
    st_time = setup_time or {st: 0.0 for st in range(1, 11)}
    t0 = time.time()

    slot_terpakai = _bangun_slot_terpakai(pesanan_terkunci, resource_count)
    semua_bebas   = pesanan_bebas + pesanan_baru

    if not semua_bebas:
        return _hasil_kosong(pesanan_terkunci)

    urutan_terbaik, _ = _sa_dengan_constraint(
        semua_bebas, slot_terpakai, resource_count, st_time
    )
    jadwal_bebas = _simulate_dengan_constraint(
        urutan_terbaik, slot_terpakai, resource_count, st_time
    )

    jadwal_lengkap = list(pesanan_terkunci) + jadwal_bebas
    total_wt       = sum(h["weighted_tardiness"] for h in jadwal_lengkap)

    id_baru    = {p["id_pesanan"] for p in pesanan_baru}
    jadwal_baru = [h for h in jadwal_bebas if h["id_pesanan"] in id_baru]

    return {
        "jadwal_lengkap":        jadwal_lengkap,
        "jadwal_baru":           jadwal_baru,
        "total_wt":              round(total_wt, 2),
        "dampak":                _hitung_dampak(pesanan_bebas, jadwal_bebas),
        "rekomendasi_deadline":  _hitung_rekomendasi_deadline(jadwal_baru, tanggal_mulai),
        "waktu_komputasi":       round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# SIMULASI DENGAN SLOT TERKUNCI
# ---------------------------------------------------------------------------

def _simulate_dengan_constraint(urutan_job, slot_terpakai, resource_count, st_time):
    slot_bebas = {}
    for st in resource_count:
        slot_bebas[st] = []
        for r_idx in range(resource_count[st]):
            key = (st, r_idx)
            if key in slot_terpakai and slot_terpakai[key]:
                slot_bebas[st].append(max(e for _, e in slot_terpakai[key]))
            else:
                slot_bebas[st].append(0.0)

    hasil_list = []
    for job in urutan_job:
        schedule_job   = {}
        waktu_tersedia = 0.0

        for stasiun in job["routing"]:
            wp    = job["waktu_proses"][stasiun] / resource_count[stasiun]
            setup = st_time.get(stasiun, 0.0)
            earliest_start = None
            best_slot_idx  = None

            for slot_idx, slot_free in enumerate(slot_bebas[stasiun]):
                start = max(slot_free, waktu_tersedia) + setup
                end   = start + wp
                r_key = (stasiun, slot_idx)
                # Geser jika konflik dengan interval terkunci
                if r_key in slot_terpakai:
                    changed = True
                    while changed:
                        changed = False
                        for (ls, le) in slot_terpakai[r_key]:
                            if start < le and end > ls:
                                start   = le + setup
                                end     = start + wp
                                changed = True
                start = max(start, waktu_tersedia)
                if earliest_start is None or start < earliest_start:
                    earliest_start = start
                    best_slot_idx  = slot_idx

            end_time = earliest_start + wp
            slot_bebas[stasiun][best_slot_idx] = end_time
            schedule_job[stasiun] = {
                "start":    round(earliest_start, 4),
                "end":      round(end_time, 4),
                "resource": best_slot_idx + 1,
            }
            waktu_tersedia = end_time

        completion = waktu_tersedia
        tardiness  = max(0.0, completion - job["deadline_mnt"])
        hasil_list.append({
            "id_pesanan":         job["id_pesanan"],
            "jenis_produk":       job["jenis_produk"],
            "jumlah_unit":        job["jumlah_unit"],
            "prioritas":          job["prioritas"],
            "bobot":              job["bobot"],
            "routing":            job["routing"],
            "schedule":           schedule_job,
            "completion_time":    round(completion, 4),
            "deadline_mnt":       job["deadline_mnt"],
            "deadline_tgl":       job["deadline_tgl"],
            "tardiness":          round(tardiness, 4),
            "weighted_tardiness": round(job["bobot"] * tardiness, 4),
            "terlambat":          tardiness > 0,
        })
    return hasil_list


# ---------------------------------------------------------------------------
# SA DENGAN CONSTRAINT
# ---------------------------------------------------------------------------

def _sa_dengan_constraint(semua_bebas, slot_terpakai, resource_count, st_time):
    n_iterasi        = SA_CONFIG["n_iterasi"]
    suhu             = SA_CONFIG["suhu_awal"]
    laju_pendinginan = SA_CONFIG["laju_pendinginan"]
    rng              = random.Random(SA_CONFIG["seed"])

    def evaluate(urutan):
        return sum(
            h["weighted_tardiness"]
            for h in _simulate_dengan_constraint(urutan, slot_terpakai, resource_count, st_time)
        )

    urutan = sorted(semua_bebas, key=lambda p: p["deadline_mnt"])
    wt     = evaluate(urutan)
    urutan_terbaik, wt_terbaik = urutan[:], wt
    n = len(urutan)

    for iterasi in range(n_iterasi):
        if n <= 1:
            break
        baru = urutan[:]
        if (iterasi // 100) % 2 == 0:
            i, j = rng.sample(range(n), 2)
            baru[i], baru[j] = baru[j], baru[i]
        else:
            i, j = rng.randrange(n), rng.randrange(n)
            if i != j:
                baru.insert(j, baru.pop(i))

        wt_baru = evaluate(baru)
        delta   = wt_baru - wt
        if delta <= 0:
            urutan, wt = baru, wt_baru
            if wt_baru < wt_terbaik:
                urutan_terbaik, wt_terbaik = baru[:], wt_baru
        elif rng.random() < (math.exp(-delta / suhu) if suhu > 1e-10 else 0.0):
            urutan, wt = baru, wt_baru
        suhu *= laju_pendinginan
        if wt_terbaik == 0.0:
            break

    return urutan_terbaik, wt_terbaik


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _bangun_slot_terpakai(pesanan_terkunci, resource_count):
    slot_terpakai = {}
    for h in pesanan_terkunci:
        if "schedule" not in h:
            continue
        for st, ops in h["schedule"].items():
            key = (st, ops["resource"] - 1)
            slot_terpakai.setdefault(key, []).append((ops["start"], ops["end"]))
    for key in slot_terpakai:
        slot_terpakai[key].sort()
    return slot_terpakai


def _hitung_rekomendasi_deadline(jadwal_baru, tanggal_mulai):
    rekomendasi = {}
    for h in jadwal_baru:
        tgl_selesai, wkt = menit_ke_tanggal_waktu(tanggal_mulai, h["completion_time"])
        tgl_rekomendasi  = tanggal_kerja_ke_n(tgl_selesai, 1)
        rekomendasi[h["id_pesanan"]] = {
            "estimasi_selesai":     tgl_selesai,
            "waktu_selesai":        wkt,
            "deadline_rekomendasi": tgl_rekomendasi,
            "completion_mnt":       round(h["completion_time"], 1),
        }
    return rekomendasi


def _hitung_dampak(pesanan_bebas_lama, jadwal_bebas_baru):
    id_lama = {p["id_pesanan"] for p in pesanan_bebas_lama}
    dampak  = [
        {"id_pesanan": h["id_pesanan"],
         "tardiness":  h["tardiness"],
         "terlambat":  h["terlambat"]}
        for h in jadwal_bebas_baru if h["id_pesanan"] in id_lama
    ]
    return {
        "detail":          dampak,
        "n_terdampak":     sum(1 for d in dampak if d["terlambat"]),
        "total_wt_dampak": sum(d["tardiness"] for d in dampak),
    }


def _hasil_kosong(pesanan_terkunci):
    return {
        "jadwal_lengkap":       pesanan_terkunci,
        "jadwal_baru":          [],
        "total_wt":             sum(h.get("weighted_tardiness", 0) for h in pesanan_terkunci),
        "dampak":               {"detail": [], "n_terdampak": 0, "total_wt_dampak": 0},
        "rekomendasi_deadline": {},
        "waktu_komputasi":      0.0,
    }
