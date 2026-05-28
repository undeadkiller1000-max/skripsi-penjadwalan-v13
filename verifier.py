"""
scheduler/verifier.py
=====================
Verifikasi jadwal final sebelum ditampilkan ke pengguna.

Tiga pemeriksaan:
  1. No-overlap  : tidak ada dua job menggunakan resource yang sama bersamaan
  2. Precedence  : setiap operasi dimulai setelah operasi sebelumnya selesai
  3. No-Sunday   : tidak ada aktivitas di hari Minggu

Output: dict ringkasan verifikasi dengan detail error jika ada.
"""

from collections import defaultdict
from datetime import date
from config import STASIUN, MENIT_PER_HARI
from calendar_utils import menit_ke_tanggal_waktu


TOLERANSI = 0.01   # menit, untuk menghindari floating point false positive


def verifikasi_jadwal(
    hasil_list: list[dict],
    tanggal_mulai: date,
) -> dict:
    """
    Jalankan ketiga pemeriksaan dan kembalikan laporan lengkap.

    Return
    ------
    {
        "lulus":           bool,   # True jika semua pemeriksaan lulus
        "no_overlap":      { "lulus": bool, "pelanggaran": list[dict] },
        "precedence":      { "lulus": bool, "pelanggaran": list[dict] },
        "no_sunday":       { "lulus": bool, "pelanggaran": list[dict] },
        "ringkasan":       str,    # pesan singkat untuk ditampilkan di UI
    }
    """
    hasil_overlap    = _cek_no_overlap(hasil_list)
    hasil_precedence = _cek_precedence(hasil_list)
    hasil_sunday     = _cek_no_sunday(hasil_list, tanggal_mulai)

    semua_lulus = (
        hasil_overlap["lulus"]
        and hasil_precedence["lulus"]
        and hasil_sunday["lulus"]
    )

    if semua_lulus:
        ringkasan = "✓ Jadwal valid — semua pemeriksaan lulus."
    else:
        masalah = []
        if not hasil_overlap["lulus"]:
            masalah.append(f"{len(hasil_overlap['pelanggaran'])} konflik resource")
        if not hasil_precedence["lulus"]:
            masalah.append(f"{len(hasil_precedence['pelanggaran'])} pelanggaran urutan")
        if not hasil_sunday["lulus"]:
            masalah.append(f"{len(hasil_sunday['pelanggaran'])} operasi di hari Minggu")
        ringkasan = "⚠ Jadwal memiliki masalah: " + ", ".join(masalah)

    return {
        "lulus":       semua_lulus,
        "no_overlap":  hasil_overlap,
        "precedence":  hasil_precedence,
        "no_sunday":   hasil_sunday,
        "ringkasan":   ringkasan,
    }


# ---------------------------------------------------------------------------
# CEK 1: NO OVERLAP
# ---------------------------------------------------------------------------

def _cek_no_overlap(hasil_list: list[dict]) -> dict:
    """
    Pastikan tidak ada dua job menggunakan resource (stasiun, slot) yang sama
    pada waktu yang bersamaan.
    """
    # Kumpulkan semua operasi per (stasiun, resource_slot)
    ops_per_resource = defaultdict(list)
    for hasil in hasil_list:
        for st, ops in hasil["schedule"].items():
            key = (st, ops["resource"])
            ops_per_resource[key].append({
                "id_pesanan": hasil["id_pesanan"],
                "start":      ops["start"],
                "end":        ops["end"],
            })

    pelanggaran = []
    for (st, res), ops_list in ops_per_resource.items():
        ops_list_sorted = sorted(ops_list, key=lambda x: x["start"])
        for i in range(len(ops_list_sorted) - 1):
            a = ops_list_sorted[i]
            b = ops_list_sorted[i + 1]
            if a["end"] > b["start"] + TOLERANSI:
                pelanggaran.append({
                    "stasiun":    f"St.{st} – {STASIUN[st]}",
                    "resource":   res,
                    "job_a":      a["id_pesanan"],
                    "job_b":      b["id_pesanan"],
                    "end_a":      round(a["end"], 2),
                    "start_b":    round(b["start"], 2),
                    "overlap_mnt": round(a["end"] - b["start"], 2),
                })

    return {
        "lulus":       len(pelanggaran) == 0,
        "pelanggaran": pelanggaran,
    }


# ---------------------------------------------------------------------------
# CEK 2: PRECEDENCE
# ---------------------------------------------------------------------------

def _cek_precedence(hasil_list: list[dict]) -> dict:
    """
    Pastikan setiap operasi dimulai setelah operasi sebelumnya (dalam routing
    yang sama) benar-benar selesai.
    """
    pelanggaran = []
    for hasil in hasil_list:
        routing = hasil["routing"]
        for k in range(len(routing) - 1):
            st_a = routing[k]
            st_b = routing[k + 1]
            end_a   = hasil["schedule"][st_a]["end"]
            start_b = hasil["schedule"][st_b]["start"]
            if start_b < end_a - TOLERANSI:
                pelanggaran.append({
                    "id_pesanan": hasil["id_pesanan"],
                    "st_a":       f"St.{st_a} – {STASIUN[st_a]}",
                    "st_b":       f"St.{st_b} – {STASIUN[st_b]}",
                    "end_a":      round(end_a, 2),
                    "start_b":    round(start_b, 2),
                    "selisih":    round(end_a - start_b, 2),
                })

    return {
        "lulus":       len(pelanggaran) == 0,
        "pelanggaran": pelanggaran,
    }


# ---------------------------------------------------------------------------
# CEK 3: NO SUNDAY
# ---------------------------------------------------------------------------

def _cek_no_sunday(hasil_list: list[dict], tanggal_mulai: date) -> dict:
    """
    Pastikan tidak ada operasi yang terjadwal pada hari Minggu.
    Cek dilakukan pada start time setiap operasi.
    """
    from calendar_utils import adalah_hari_kerja

    pelanggaran = []
    for hasil in hasil_list:
        for st, ops in hasil["schedule"].items():
            for titik_waktu, label in [(ops["start"], "mulai"), (ops["end"], "selesai")]:
                tgl, wkt = menit_ke_tanggal_waktu(tanggal_mulai, titik_waktu)
                if not adalah_hari_kerja(tgl):
                    pelanggaran.append({
                        "id_pesanan": hasil["id_pesanan"],
                        "stasiun":    f"St.{st} – {STASIUN[st]}",
                        "titik":      label,
                        "tanggal":    tgl.strftime("%d/%m/%Y"),
                        "waktu":      wkt,
                        "menit":      round(titik_waktu, 2),
                    })

    return {
        "lulus":       len(pelanggaran) == 0,
        "pelanggaran": pelanggaran,
    }


# ---------------------------------------------------------------------------
# UTILITAS: ROUTING CHART PER PESANAN (untuk tab verifikasi UI)
# ---------------------------------------------------------------------------

def buat_routing_chart(pesanan_routed: list[dict]) -> list[dict]:
    """
    Buat data untuk visualisasi OPC (Operation Process Chart) per pesanan.
    Return list of dict yang bisa langsung di-render sebagai tabel di Streamlit.
    """
    rows = []
    for p in pesanan_routed:
        routing_str = " → ".join(f"St.{st}" for st in p["routing"])
        rows.append({
            "ID Pesanan":    p["id_pesanan"],
            "Produk":        p["jenis_produk"].capitalize(),
            "Unit":          p["jumlah_unit"],
            "Furing":        "Ya" if p["furing"] else "–",
            "Kancing":       "Ya" if p["kancing"] else "–",
            "Dekorasi":      _dekorasi_str(p),
            "Routing":       routing_str,
            "Jml. Stasiun":  len(p["routing"]),
        })
    return rows


def _dekorasi_str(p: dict) -> str:
    parts = []
    if p["sablon"]:  parts.append("Sablon")
    if p["dtf"]:     parts.append("DTF")
    if p["bordir"]:  parts.append("Bordir")
    return ", ".join(parts) if parts else "–"
