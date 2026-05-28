"""
scheduler/simulator.py
======================
Engine simulasi penjadwalan job shop.

Fungsi utama: simulate_schedule()
  - Menerima urutan job (list of pesanan dict yang sudah punya routing)
  - Menjadwalkan setiap job seawal mungkin (earliest start) sesuai:
      1. Ketersediaan resource di stasiun tersebut
      2. Selesainya operasi sebelumnya untuk job yang sama (precedence)
  - Menghitung start_time dan end_time setiap operasi
  - Menghitung tardiness dan weighted tardiness per job

Output dict per job:
{
    "id_pesanan"       : str,
    "schedule"         : { stasiun_id: {"start": float, "end": float} },
    "completion_time"  : float,   # end time stasiun terakhir
    "deadline_mnt"     : float,
    "tardiness"        : float,   # max(0, completion - deadline)
    "weighted_tardiness": float,  # bobot × tardiness
    "terlambat"        : bool,
}

Catatan penting tentang resource:
  - Setiap stasiun memiliki N resource (tim/mesin/operator)
  - N resource = bisa mengerjakan N job secara paralel di stasiun yang sama
  - Implementasi: track N "slot" per stasiun, pilih slot yang paling awal bebas
"""

from config import RESOURCE_CONFIG, MENIT_PER_HARI


# ---------------------------------------------------------------------------
# FUNGSI UTAMA
# ---------------------------------------------------------------------------

def simulate_schedule(
    urutan_job: list[dict],
    resource_override: dict = None,
    setup_time: dict = None,
) -> tuple[list[dict], float]:
    """
    Simulasi penjadwalan berdasarkan urutan job yang diberikan.

    Parameter
    ---------
    urutan_job       : list[dict] pesanan sudah punya routing & waktu_proses,
                       diurutkan sesuai yang ingin dijadwalkan (index 0 = prioritas pertama)
    resource_override: dict { stasiun_id: int } untuk override jumlah resource
                       (digunakan saat crashing). Jika None, pakai default.
    setup_time       : dict { stasiun_id: float } menit setup per job per stasiun.
                       Jika None, semua 0.

    Return
    ------
    (hasil_list, total_weighted_tardiness)
    - hasil_list : list[dict] hasil jadwal per job (urutan sama dengan urutan_job)
    - total_weighted_tardiness : float, objective value untuk optimizer
    """
    # -- Setup resource slots --
    # Setiap stasiun punya N slot, masing-masing slot menyimpan kapan dia bebas
    resource_count = _get_resource_count(resource_override)
    slot_bebas = {
        st: [0.0] * resource_count[st]
        for st in resource_count
    }

    # -- Setup time per stasiun (default 0) --
    st_time = setup_time or {st: 0.0 for st in range(1, 11)}

    # -- Tracking waktu selesai setiap job di setiap stasiun --
    # job_selesai[job_idx][stasiun] = menit selesai operasi tersebut
    hasil_list = []

    # Jadwalkan job satu per satu sesuai urutan
    for job in urutan_job:
        schedule_job = {}
        waktu_tersedia = 0.0   # kapan job ini siap (selesai stasiun sebelumnya)

        for stasiun in job["routing"]:
            waktu_proses_1_resource = job["waktu_proses"][stasiun]
            n_resource = resource_count[stasiun]

            # Waktu proses efektif dengan resource yang tersedia
            waktu_proses_efektif = waktu_proses_1_resource / n_resource

            # Tambahkan setup time
            setup = st_time.get(stasiun, 0.0)

            # Cari slot resource yang paling awal bisa mulai
            # (slot bebas >= waktu_tersedia agar precedence constraint terpenuhi)
            earliest_start = None
            best_slot_idx  = None

            for slot_idx, slot_free in enumerate(slot_bebas[stasiun]):
                # Job bisa mulai di slot ini saat kedua kondisi terpenuhi:
                # 1. slot sudah bebas, 2. job sudah siap dari stasiun sebelumnya
                kandidat_start = max(slot_free, waktu_tersedia) + setup
                if earliest_start is None or kandidat_start < earliest_start:
                    earliest_start = kandidat_start
                    best_slot_idx  = slot_idx

            end_time = earliest_start + waktu_proses_efektif

            # Update slot yang dipakai
            slot_bebas[stasiun][best_slot_idx] = end_time

            schedule_job[stasiun] = {
                "start":    round(earliest_start, 4),
                "end":      round(end_time, 4),
                "resource": best_slot_idx + 1,   # 1-indexed untuk display
            }

            # Precedence: job ini siap ke stasiun berikutnya setelah selesai di sini
            waktu_tersedia = end_time

        completion = waktu_tersedia
        deadline   = job["deadline_mnt"]
        tardiness  = max(0.0, completion - deadline)
        w_tardiness = job["bobot"] * tardiness

        hasil_list.append({
            "id_pesanan":          job["id_pesanan"],
            "jenis_produk":        job["jenis_produk"],
            "jumlah_unit":         job["jumlah_unit"],
            "prioritas":           job["prioritas"],
            "bobot":               job["bobot"],
            "routing":             job["routing"],
            "schedule":            schedule_job,
            "completion_time":     round(completion, 4),
            "deadline_mnt":        deadline,
            "deadline_tgl":        job["deadline_tgl"],
            "tardiness":           round(tardiness, 4),
            "weighted_tardiness":  round(w_tardiness, 4),
            "terlambat":           tardiness > 0,
        })

    total_wt = sum(r["weighted_tardiness"] for r in hasil_list)
    return hasil_list, round(total_wt, 4)


# ---------------------------------------------------------------------------
# EVALUASI CEPAT (tanpa menyimpan detail schedule)
# Digunakan oleh SA saat evaluasi 8.000 iterasi agar cepat
# ---------------------------------------------------------------------------

def evaluate_sequence(
    urutan_job: list[dict],
    resource_count: dict,
    setup_time: dict,
) -> float:
    """
    Hitung total weighted tardiness untuk sebuah urutan job.
    Lebih cepat dari simulate_schedule() karena tidak menyimpan detail.

    Return
    ------
    float : total weighted tardiness
    """
    slot_bebas = {st: [0.0] * resource_count[st] for st in resource_count}

    total_wt = 0.0
    for job in urutan_job:
        waktu_tersedia = 0.0
        for stasiun in job["routing"]:
            wp_efektif = job["waktu_proses"][stasiun] / resource_count[stasiun]
            setup      = setup_time.get(stasiun, 0.0)

            # Cari slot terbaik
            earliest_start = None
            best_slot_idx  = None
            for i, slot_free in enumerate(slot_bebas[stasiun]):
                kandidat = max(slot_free, waktu_tersedia) + setup
                if earliest_start is None or kandidat < earliest_start:
                    earliest_start = kandidat
                    best_slot_idx  = i

            end_time = earliest_start + wp_efektif
            slot_bebas[stasiun][best_slot_idx] = end_time
            waktu_tersedia = end_time

        tardiness = max(0.0, waktu_tersedia - job["deadline_mnt"])
        total_wt += job["bobot"] * tardiness

    return total_wt


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def _get_resource_count(resource_override: dict = None) -> dict:
    """
    Gabungkan default resource config dengan override (jika ada).
    Return dict { stasiun_id: int }.
    """
    counts = {st: RESOURCE_CONFIG[st]["default"] for st in RESOURCE_CONFIG}
    if resource_override:
        for st, val in resource_override.items():
            max_val = RESOURCE_CONFIG[st]["max"]
            counts[st] = min(int(val), max_val)   # tidak boleh melebihi max
    return counts


def get_resource_count(resource_override: dict = None) -> dict:
    """Public wrapper untuk _get_resource_count, dipakai modul lain."""
    return _get_resource_count(resource_override)


# ---------------------------------------------------------------------------
# UTILITAS ANALISIS HASIL
# ---------------------------------------------------------------------------

def ringkasan_performa(hasil_list: list[dict]) -> dict:
    """
    Hitung metrik performa dari hasil simulasi.

    Return dict dengan:
      - total_weighted_tardiness
      - total_tardiness (unweighted)
      - n_terlambat
      - n_tepat_waktu
      - pct_tepat_waktu
      - maks_tardiness
      - rata_tardiness
    """
    n = len(hasil_list)
    if n == 0:
        return {}

    total_wt   = sum(r["weighted_tardiness"] for r in hasil_list)
    total_t    = sum(r["tardiness"] for r in hasil_list)
    n_terlambat = sum(1 for r in hasil_list if r["terlambat"])

    return {
        "total_weighted_tardiness": round(total_wt, 2),
        "total_tardiness":          round(total_t, 2),
        "n_job":                    n,
        "n_terlambat":              n_terlambat,
        "n_tepat_waktu":            n - n_terlambat,
        "pct_tepat_waktu":          round((n - n_terlambat) / n * 100, 1),
        "maks_tardiness":           round(max(r["tardiness"] for r in hasil_list), 2),
        "rata_tardiness":           round(total_t / n, 2),
    }


def jadwal_per_stasiun(
    hasil_list: list[dict],
    tanggal_mulai,
) -> dict:
    """
    Susun ulang jadwal dari perspektif stasiun (bukan job).
    Digunakan untuk tab 'lembar kerja per stasiun' di UI.

    Return
    ------
    dict { stasiun_id: [ {job_info + start + end + hari}, ... ] }
    Diurutkan berdasarkan start time.
    """
    from calendar_utils import menit_ke_tanggal_waktu
    from config import STASIUN

    per_stasiun = {st: [] for st in STASIUN}

    for hasil in hasil_list:
        for st, ops in hasil["schedule"].items():
            tgl_mulai, wkt_mulai = menit_ke_tanggal_waktu(tanggal_mulai, ops["start"])
            tgl_selesai, wkt_selesai = menit_ke_tanggal_waktu(tanggal_mulai, ops["end"])
            per_stasiun[st].append({
                "id_pesanan":   hasil["id_pesanan"],
                "jenis_produk": hasil["jenis_produk"],
                "jumlah_unit":  hasil["jumlah_unit"],
                "prioritas":    hasil["prioritas"],
                "start_mnt":    ops["start"],
                "end_mnt":      ops["end"],
                "resource":     ops["resource"],
                "tgl_mulai":    tgl_mulai,
                "wkt_mulai":    wkt_mulai,
                "tgl_selesai":  tgl_selesai,
                "wkt_selesai":  wkt_selesai,
                "durasi_mnt":   round(ops["end"] - ops["start"], 1),
                "terlambat":    hasil["terlambat"],
            })

    # Urutkan per stasiun berdasarkan start time
    for st in per_stasiun:
        per_stasiun[st].sort(key=lambda x: x["start_mnt"])

    return per_stasiun
