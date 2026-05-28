"""
data_handler.py
===============
Membaca, memvalidasi, dan menormalisasi data pesanan dari file CSV/Excel.

Output utama: list of dict, satu dict per pesanan yang valid.
Setiap dict memiliki struktur standar yang digunakan oleh semua modul lain.

Struktur dict pesanan (setelah normalisasi):
{
    "id_pesanan"   : str,
    "jenis_produk" : str,          # "kaos" / "polo" / "kemeja" / "jaket"
    "jumlah_unit"  : int,
    "deadline_tgl" : date,         # tanggal kalender asli
    "deadline_mnt" : int,          # menit efektif (diisi setelah set tanggal mulai)
    "prioritas"    : str,          # "Normal" / "Tinggi" / "Kritis"
    "bobot"        : int,          # 1 / 2 / 3
    "furing"       : bool,
    "sablon"       : bool,
    "dtf"          : bool,
    "bordir"       : bool,
    "kancing"      : bool,
    "urutan_masuk" : int,          # urutan baris di file asli (untuk FCFS)
}
"""

import pandas as pd
from datetime import date, datetime
from typing import Optional
from config import (
    KOLOM_WAJIB,
    JENIS_PRODUK_VALID,
    PRODUK_TANPA_FURING,
    PRODUK_TANPA_KANCING,
    BOBOT_PRIORITAS,
)


# ---------------------------------------------------------------------------
# KONSTANTA VALIDASI
# ---------------------------------------------------------------------------

PRIORITAS_VALID = set(BOBOT_PRIORITAS.keys())
FLAG_COLUMNS    = ["furing", "sablon", "dtf", "bordir", "kancing"]


# ---------------------------------------------------------------------------
# FUNGSI UTAMA
# ---------------------------------------------------------------------------

def baca_file(uploaded_file) -> tuple[Optional[pd.DataFrame], str]:
    """
    Baca file CSV atau Excel yang di-upload via Streamlit.

    Return
    ------
    (df, pesan_error)
    - Jika berhasil: (DataFrame, "")
    - Jika gagal    : (None, pesan_error)
    """
    nama = uploaded_file.name.lower()
    try:
        if nama.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif nama.endswith((".xlsx", ".xls")):
            df = pd.read_excel(uploaded_file)
        else:
            return None, (
                f"Format file '{uploaded_file.name}' tidak didukung. "
                "Gunakan .csv, .xlsx, atau .xls."
            )
        return df, ""
    except Exception as e:
        return None, f"Gagal membaca file: {str(e)}"


def validasi_dan_bersihkan(
    df: pd.DataFrame,
    tanggal_mulai_produksi: date,
    drop_error: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Validasi setiap baris DataFrame dan konversi ke list of dict pesanan.

    Parameter
    ---------
    df                     : DataFrame hasil baca_file()
    tanggal_mulai_produksi : tanggal hari pertama produksi
    drop_error             : jika True, baris bermasalah di-drop dan proses lanjut;
                             jika False, seluruh proses berhenti saat ada error pertama.

    Return
    ------
    (pesanan_valid, error_list)
    - pesanan_valid : list[dict] pesanan yang lolos validasi
    - error_list    : list[dict] dengan kunci "baris", "id_pesanan", "error"
    """
    # -- 1. Normalisasi nama kolom (strip whitespace, lowercase) --
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # -- 1b. Mapping alias kolom (toleransi nama berbeda dari template) --
    ALIAS_KOLOM = {
        "qty":              "jumlah_unit",
        "jumlah":           "jumlah_unit",
        "quantity":         "jumlah_unit",
        "order_qty":        "jumlah_unit",
        "id_order":         "id_pesanan",
        "order_id":         "id_pesanan",
        "no_pesanan":       "id_pesanan",
        "produk":           "jenis_produk",
        "jenis":            "jenis_produk",
        "type":             "jenis_produk",
        "due_date":         "deadline",
        "tanggal_deadline": "deadline",
        "tgl_deadline":     "deadline",
        "pasang_kancing":   "kancing",
        "with_kancing":     "kancing",
        "priority":         "prioritas",
        "prio":             "prioritas",
    }
    df = df.rename(columns={k: v for k, v in ALIAS_KOLOM.items() if k in df.columns})

    # -- 2. Cek kolom wajib --
    kolom_ada = set(df.columns)
    kolom_kurang = [k for k in KOLOM_WAJIB if k not in kolom_ada]
    if kolom_kurang:
        raise ValueError(
            f"Kolom berikut tidak ditemukan di file: {', '.join(kolom_kurang)}. "
            f"Kolom yang tersedia di file kamu: {', '.join(sorted(kolom_ada))}. "
            f"Pastikan header kolom sesuai template (download via tombol Template CSV)."
        )

    pesanan_valid = []
    error_list    = []

    for idx, row in df.iterrows():
        nomor_baris = idx + 2   # +2 karena baris 1 = header di Excel/CSV
        errors_baris = []

        # -- Ambil nilai dengan safe getter --
        id_p      = str(row.get("id_pesanan", "")).strip()
        jenis_raw = str(row.get("jenis_produk", "")).strip().lower()
        unit_raw  = row.get("jumlah_unit")
        dl_raw    = row.get("deadline")
        prio_raw  = str(row.get("prioritas", "")).strip()

        label = id_p if id_p else f"baris-{nomor_baris}"

        # -- Validasi id_pesanan --
        if not id_p:
            errors_baris.append("id_pesanan kosong")

        # -- Validasi jenis_produk --
        if jenis_raw not in JENIS_PRODUK_VALID:
            errors_baris.append(
                f"jenis_produk '{jenis_raw}' tidak dikenal "
                f"(valid: {', '.join(sorted(JENIS_PRODUK_VALID))})"
            )

        # -- Validasi jumlah_unit --
        try:
            unit = int(unit_raw)
            if unit <= 0:
                errors_baris.append(f"jumlah_unit harus > 0, ditemukan: {unit}")
        except (TypeError, ValueError):
            unit = 0
            errors_baris.append(f"jumlah_unit bukan angka: '{unit_raw}'")

        # -- Validasi deadline --
        deadline_tgl = _parse_tanggal(dl_raw)
        if deadline_tgl is None:
            errors_baris.append(
                f"deadline '{dl_raw}' tidak dapat dibaca sebagai tanggal "
                "(format yang diterima: YYYY-MM-DD atau DD/MM/YYYY)"
            )
        # Catatan: deadline boleh lebih awal dari tanggal_mulai_produksi
        # karena sistem mendukung simulasi data historis.
        # Jika deadline sudah lewat, tardiness akan dihitung otomatis.

        # -- Validasi prioritas --
        # Normalisasi kapitalisasi
        prio_norm = prio_raw.capitalize()
        if prio_norm not in PRIORITAS_VALID:
            errors_baris.append(
                f"prioritas '{prio_raw}' tidak dikenal "
                f"(valid: {', '.join(PRIORITAS_VALID)})"
            )
            prio_norm = "Normal"   # fallback untuk lanjut validasi

        # -- Validasi flag biner --
        flags = {}
        for flag in FLAG_COLUMNS:
            val = row.get(flag, 0)
            parsed = _parse_flag(val)
            if parsed is None:
                errors_baris.append(
                    f"Kolom '{flag}' berisi nilai tidak valid '{val}' "
                    "(harus 0 atau 1)"
                )
                flags[flag] = False
            else:
                flags[flag] = parsed

        # -- Validasi konsistensi produk × atribut --
        # Catatan: ini HANYA warning, bukan error keras.
        # Pesanan tetap diproses; atribut tidak valid diabaikan otomatis.
        if jenis_raw in JENIS_PRODUK_VALID:
            konsistensi_warnings = _cek_konsistensi(jenis_raw, flags)
            if konsistensi_warnings:
                # Catat sebagai warning tapi JANGAN masukkan ke errors_baris
                error_list.append({
                    "baris":      nomor_baris,
                    "id_pesanan": label,
                    "error":      "⚠ Warning: " + "; ".join(konsistensi_warnings),
                })
                # Lanjut proses pesanan ini (tidak di-skip)

        # -- Kumpulkan error atau simpan pesanan valid --
        if errors_baris:
            error_list.append({
                "baris":      nomor_baris,
                "id_pesanan": label,
                "error":      "; ".join(errors_baris),
            })
            if not drop_error:
                # Hentikan seluruh proses, kembalikan apa yang sudah dikumpulkan
                return pesanan_valid, error_list
        else:
            from calendar_utils import deadline_ke_menit
            pesanan_valid.append({
                "id_pesanan":   id_p,
                "jenis_produk": jenis_raw,
                "jumlah_unit":  unit,
                "deadline_tgl": deadline_tgl,
                "deadline_mnt": deadline_ke_menit(tanggal_mulai_produksi, deadline_tgl),
                "prioritas":    prio_norm,
                "bobot":        BOBOT_PRIORITAS[prio_norm],
                "furing":       flags["furing"] if jenis_raw not in PRODUK_TANPA_FURING else False,
                "sablon":       flags["sablon"],
                "dtf":          flags["dtf"],
                "bordir":       flags["bordir"],
                "kancing":      flags["kancing"] if jenis_raw not in PRODUK_TANPA_KANCING else False,
                "urutan_masuk": len(pesanan_valid),   # 0-indexed, urutan di file
            })

    return pesanan_valid, error_list


# ---------------------------------------------------------------------------
# FUNGSI HELPER INTERNAL
# ---------------------------------------------------------------------------

def _parse_tanggal(nilai) -> Optional[date]:
    """
    Coba parse berbagai format tanggal.
    Return date jika berhasil, None jika gagal.
    """
    if isinstance(nilai, (date, datetime)):
        return nilai.date() if isinstance(nilai, datetime) else nilai

    if isinstance(nilai, str):
        nilai = nilai.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(nilai, fmt).date()
            except ValueError:
                continue

    # Pandas bisa memberikan Timestamp
    try:
        return pd.Timestamp(nilai).date()
    except Exception:
        return None


def _parse_flag(nilai) -> Optional[bool]:
    """
    Parse nilai flag (0/1, True/False, "ya"/"tidak", dll).
    Return True/False, atau None jika tidak bisa diparse.
    """
    if isinstance(nilai, bool):
        return nilai
    if isinstance(nilai, (int, float)):
        if nilai in (0, 1):
            return bool(nilai)
        return None
    if isinstance(nilai, str):
        v = nilai.strip().lower()
        if v in ("1", "ya", "yes", "true", "y"):
            return True
        if v in ("0", "tidak", "no", "false", "n"):
            return False
    return None


def _cek_konsistensi(jenis: str, flags: dict) -> list[str]:
    """
    Cek konsistensi atribut terhadap jenis produk.
    Return list string error (kosong jika tidak ada masalah).

    Catatan: furing dan kancing untuk produk yang tidak boleh memilikinya
    tidak dijadikan error keras — sistem akan otomatis mengabaikannya,
    tapi pengguna tetap diberi tahu via warning ringan.
    """
    warnings = []
    if jenis in PRODUK_TANPA_FURING and flags.get("furing"):
        warnings.append(
            f"{jenis} tidak bisa menggunakan furing — "
            "atribut furing akan diabaikan secara otomatis"
        )
    if jenis in PRODUK_TANPA_KANCING and flags.get("kancing"):
        warnings.append(
            f"{jenis} tidak bisa menggunakan kancing — "
            "atribut kancing akan diabaikan secara otomatis"
        )
    return warnings   # dikembalikan sebagai warning, bukan error keras


# ---------------------------------------------------------------------------
# UTILITAS DISPLAY
# ---------------------------------------------------------------------------

def ringkasan_pesanan(pesanan_list: list[dict]) -> pd.DataFrame:
    """
    Buat DataFrame ringkasan untuk ditampilkan di UI Streamlit.
    Kolom dipilih dan diformat agar mudah dibaca.
    """
    rows = []
    for p in pesanan_list:
        dekorasi = []
        if p["sablon"]:  dekorasi.append("Sablon")
        if p["dtf"]:     dekorasi.append("DTF")
        if p["bordir"]:  dekorasi.append("Bordir")

        rows.append({
            "ID Pesanan":   p["id_pesanan"],
            "Produk":       p["jenis_produk"].capitalize(),
            "Unit":         p["jumlah_unit"],
            "Deadline":     p["deadline_tgl"].strftime("%d/%m/%Y"),
            "Prioritas":    p["prioritas"],
            "Furing":       "✓" if p["furing"]  else "–",
            "Kancing":      "✓" if p["kancing"] else "–",
            "Dekorasi":     ", ".join(dekorasi) if dekorasi else "–",
        })
    return pd.DataFrame(rows)


def generate_template() -> pd.DataFrame:
    """
    Generate template DataFrame kosong yang bisa diunduh pengguna.
    """
    contoh = [
        {
            "id_pesanan":   "ORD-001",
            "jenis_produk": "kaos",
            "jumlah_unit":  100,
            "deadline":     "2024-06-15",
            "prioritas":    "Normal",
            "furing":       0,
            "sablon":       1,
            "dtf":          0,
            "bordir":       0,
            "kancing":      0,
        },
        {
            "id_pesanan":   "ORD-002",
            "jenis_produk": "kemeja",
            "jumlah_unit":  50,
            "deadline":     "2024-06-20",
            "prioritas":    "Tinggi",
            "furing":       1,
            "sablon":       0,
            "dtf":          1,
            "bordir":       1,
            "kancing":      1,
        },
        {
            "id_pesanan":   "ORD-003",
            "jenis_produk": "jaket",
            "jumlah_unit":  30,
            "deadline":     "2024-06-25",
            "prioritas":    "Kritis",
            "furing":       1,
            "sablon":       1,
            "dtf":          0,
            "bordir":       1,
            "kancing":      1,
        },
    ]
    return pd.DataFrame(contoh)
