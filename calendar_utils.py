"""
calendar_utils.py
=================
Utilitas konversi antara tanggal kalender dan menit kerja efektif.

Aturan:
- 1 hari kerja = 450 menit efektif (08.30–11.30 + 13.00–17.30)
- Hari Minggu adalah hari libur (tidak dihitung)
- Menit efektif dihitung dari awal sesi pagi hari pertama produksi (t=0)

Representasi waktu internal:
  t = 0       → 08.30 hari pertama produksi
  t = 180     → 11.30 hari pertama (akhir sesi pagi)
  t = 180+    → langsung loncat ke 13.00 (sesi siang mulai)
  t = 450     → 17.30 hari pertama (akhir hari kerja)
  t = 451     → 08.30 hari kedua (hari kerja berikutnya)
  dst.
"""

from datetime import date, timedelta
from config import MENIT_PER_HARI, HARI_LIBUR


# ---------------------------------------------------------------------------
# UTILITAS DASAR
# ---------------------------------------------------------------------------

def adalah_hari_kerja(d: date) -> bool:
    """Return True jika tanggal d adalah hari kerja (bukan Minggu)."""
    return d.weekday() not in HARI_LIBUR


def hitung_hari_kerja_antara(tanggal_mulai: date, tanggal_akhir: date) -> int:
    """
    Hitung jumlah hari kerja dari tanggal_mulai s.d. tanggal_akhir (inklusif).
    tanggal_akhir >= tanggal_mulai.
    """
    if tanggal_akhir < tanggal_mulai:
        return 0
    jumlah = 0
    current = tanggal_mulai
    while current <= tanggal_akhir:
        if adalah_hari_kerja(current):
            jumlah += 1
        current += timedelta(days=1)
    return jumlah


def tanggal_kerja_ke_n(tanggal_mulai: date, n: int) -> date:
    """
    Kembalikan tanggal hari kerja ke-n setelah tanggal_mulai.
    n=0 → tanggal_mulai sendiri (jika hari kerja).
    n=1 → hari kerja pertama setelah tanggal_mulai.
    Jika tanggal_mulai bukan hari kerja, otomatis geser ke hari kerja berikutnya.
    """
    current = tanggal_mulai
    if not adalah_hari_kerja(current):
        current = hari_kerja_berikutnya(current)
    while n > 0:
        current += timedelta(days=1)
        if adalah_hari_kerja(current):
            n -= 1
    return current


def hari_kerja_berikutnya(d: date) -> date:
    """Kembalikan hari kerja pertama setelah tanggal d (tidak inklusif)."""
    next_day = d + timedelta(days=1)
    while not adalah_hari_kerja(next_day):
        next_day += timedelta(days=1)
    return next_day


# ---------------------------------------------------------------------------
# KONVERSI TANGGAL ↔ MENIT EFEKTIF
# ---------------------------------------------------------------------------

def deadline_ke_menit(tanggal_mulai_produksi: date, tanggal_deadline: date) -> int:
    """
    Konversi deadline (tanggal kalender) ke menit efektif.

    Deadline diartikan sebagai akhir hari kerja pada tanggal_deadline,
    yaitu pukul 17.30 → akhir menit ke-450 hari tersebut.

    Jika tanggal_deadline jatuh pada Minggu, deadline dianggap akhir
    hari kerja terakhir sebelumnya (Sabtu).

    Parameter
    ---------
    tanggal_mulai_produksi : date
        Hari pertama produksi berjalan (t=0 di menit efektif).
    tanggal_deadline : date
        Batas waktu penyelesaian pesanan.

    Return
    ------
    int : menit efektif deadline (≥ 0). 0 jika deadline sebelum mulai.
    """
    # Geser deadline ke hari kerja jika jatuh di hari libur
    dl = tanggal_deadline
    while not adalah_hari_kerja(dl):
        dl -= timedelta(days=1)

    if dl < tanggal_mulai_produksi:
        return 0

    # Pastikan tanggal_mulai_produksi adalah hari kerja
    mulai = tanggal_mulai_produksi
    while not adalah_hari_kerja(mulai):
        mulai += timedelta(days=1)

    # Hitung jumlah hari kerja penuh antara mulai dan dl (inklusif mulai, eksklusif dl)
    hari_kerja = hitung_hari_kerja_antara(mulai, dl)

    # Hari ke-1 = indeks 1, jadi menit deadline = hari_kerja × MENIT_PER_HARI
    # (karena akhir hari ke-1 = menit 450, akhir hari ke-2 = 900, dst.)
    return hari_kerja * MENIT_PER_HARI


def menit_ke_tanggal_waktu(
    tanggal_mulai_produksi: date,
    menit_efektif: float
) -> tuple[date, str]:
    """
    Konversi menit efektif kembali ke tanggal dan jam-menit aktual.

    Return
    ------
    (tanggal, waktu_str) misal: (date(2024,6,3), "14:25")
    """
    if menit_efektif <= 0:
        # Tepat di awal hari pertama
        mulai = tanggal_mulai_produksi
        while not adalah_hari_kerja(mulai):
            mulai += timedelta(days=1)
        return mulai, "08:30"

    # Berapa hari kerja penuh sudah lewat?
    hari_penuh = int(menit_efektif // MENIT_PER_HARI)
    sisa_menit = menit_efektif % MENIT_PER_HARI

    # Cari tanggal hari kerja ke (hari_penuh + 1)
    # Jika sisa_menit == 0, berarti tepat di akhir hari ke-hari_penuh
    if sisa_menit == 0 and hari_penuh > 0:
        hari_penuh -= 1
        sisa_menit = MENIT_PER_HARI

    tanggal = tanggal_mulai_produksi
    while not adalah_hari_kerja(tanggal):
        tanggal += timedelta(days=1)

    counter = 0
    while counter < hari_penuh:
        tanggal += timedelta(days=1)
        if adalah_hari_kerja(tanggal):
            counter += 1

    # Konversi sisa_menit ke jam:menit aktual
    # Sesi pagi: 0–180 menit → 08.30–11.30
    # Sesi siang: 181–450 menit → 13.00–17.30
    if sisa_menit <= 180:
        total_menit_dari_tengah_malam = 8 * 60 + 30 + sisa_menit
    else:
        total_menit_dari_tengah_malam = 13 * 60 + (sisa_menit - 180)

    jam  = int(total_menit_dari_tengah_malam // 60)
    mnt  = int(total_menit_dari_tengah_malam % 60)
    return tanggal, f"{jam:02d}:{mnt:02d}"


def waktu_aktual_ke_menit(
    tanggal_mulai_produksi: date,
    tanggal_target: date,
    jam: int,
    menit: int
) -> float:
    """
    Konversi tanggal + jam:menit aktual ke menit efektif.
    Berguna saat pengguna menginput checkpoint progress pesanan berjalan.

    jam dan menit harus berada dalam jendela kerja (08:30–11:30 atau 13:00–17:30).
    Jika di luar jendela, dibulatkan ke ujung terdekat.
    """
    mulai = tanggal_mulai_produksi
    while not adalah_hari_kerja(mulai):
        mulai += timedelta(days=1)

    target = tanggal_target
    while not adalah_hari_kerja(target):
        target += timedelta(days=1)

    hari_kerja_sebelum = hitung_hari_kerja_antara(mulai, target) - 1
    base_menit = hari_kerja_sebelum * MENIT_PER_HARI

    total_menit_hari = jam * 60 + menit

    # Sesi pagi: 08:30 = 510 mnt, 11:30 = 690 mnt
    # Sesi siang: 13:00 = 780 mnt, 17:30 = 1050 mnt
    if total_menit_hari <= 510:
        menit_dalam_hari = 0
    elif total_menit_hari <= 690:
        menit_dalam_hari = total_menit_hari - 510          # 0–180
    elif total_menit_hari <= 780:
        menit_dalam_hari = 180                              # tepat akhir pagi
    elif total_menit_hari <= 1050:
        menit_dalam_hari = 180 + (total_menit_hari - 780)  # 180–450
    else:
        menit_dalam_hari = 450

    return base_menit + menit_dalam_hari


def is_menit_hari_minggu(
    tanggal_mulai_produksi: date,
    menit_efektif: float
) -> bool:
    """
    Cek apakah menit efektif tertentu jatuh pada hari Minggu.
    Digunakan oleh verifier untuk memastikan tidak ada jadwal di hari libur.
    """
    tanggal, _ = menit_ke_tanggal_waktu(tanggal_mulai_produksi, menit_efektif)
    return not adalah_hari_kerja(tanggal)


# ---------------------------------------------------------------------------
# UTILITAS TAMBAHAN UNTUK DISPLAY
# ---------------------------------------------------------------------------

def format_durasi(menit: float) -> str:
    """Format menit ke string 'X hari Y jam Z menit' untuk display."""
    menit = int(round(menit))
    hari = menit // MENIT_PER_HARI
    sisa = menit % MENIT_PER_HARI
    jam  = sisa // 60
    mnt  = sisa % 60

    parts = []
    if hari > 0:
        parts.append(f"{hari} hari")
    if jam > 0:
        parts.append(f"{jam} jam")
    if mnt > 0 or not parts:
        parts.append(f"{mnt} mnt")
    return " ".join(parts)


def daftar_hari_kerja(tanggal_mulai: date, n_hari: int) -> list[date]:
    """
    Kembalikan list n_hari hari kerja mulai dari tanggal_mulai.
    Digunakan untuk generate header tabel jadwal per stasiun.
    """
    hasil = []
    current = tanggal_mulai
    while not adalah_hari_kerja(current):
        current += timedelta(days=1)

    while len(hasil) < n_hari:
        if adalah_hari_kerja(current):
            hasil.append(current)
        current += timedelta(days=1)
    return hasil
