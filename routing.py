"""
routing.py
==========
Membangun jalur produksi (routing) unik untuk setiap pesanan
berdasarkan jenis produk dan atributnya.

Output: setiap pesanan mendapat field tambahan:
  "routing"  : list[int]  → urutan stasiun yang harus dilalui
  "kode_kapasitas": dict  → { stasiun_id: kode_kondisi_untuk_lookup_kapasitas }

Logika tiga lapis:
  Lapis 1 – Jalur jahit (stasiun 2 XOR 3)
  Lapis 2 – Dekorasi opsional (stasiun 4, 5, 6 dalam urutan fixed jika diperlukan)
  Lapis 3 – Kancing opsional (stasiun 7, jika diperlukan)
  Selalu diakhiri: stasiun 8, 9, 10
"""

from config import (
    JENIS_PRODUK_VALID,
    PRODUK_TANPA_FURING,
    PRODUK_TANPA_KANCING,
    URUTAN_DEKORASI,
    KAPASITAS,
    MENIT_PER_HARI,
)


# ---------------------------------------------------------------------------
# FUNGSI UTAMA
# ---------------------------------------------------------------------------

def bangun_routing(pesanan: dict) -> dict:
    """
    Tambahkan field 'routing' dan 'kode_kapasitas' ke dict pesanan.

    Parameter
    ---------
    pesanan : dict standar dari data_handler.validasi_dan_bersihkan()

    Return
    ------
    Dict pesanan yang sudah dilengkapi dengan:
      - routing        : list[int] urutan stasiun
      - kode_kapasitas : dict { stasiun_id: str } untuk lookup KAPASITAS
      - waktu_proses   : dict { stasiun_id: float } menit per unit × jumlah unit
                         (total waktu proses di stasiun tersebut)
    """
    jenis   = pesanan["jenis_produk"]
    unit    = pesanan["jumlah_unit"]
    furing  = pesanan["furing"]
    sablon  = pesanan["sablon"]
    dtf     = pesanan["dtf"]
    bordir  = pesanan["bordir"]
    kancing = pesanan["kancing"]

    routing         = []
    kode_kapasitas  = {}

    # ------------------------------------------------------------------ #
    # STASIUN 1: Potong (selalu)
    # ------------------------------------------------------------------ #
    routing.append(1)
    kode_kapasitas[1] = _kode_potong(jenis, furing)

    # ------------------------------------------------------------------ #
    # LAPIS 1: Jalur jahit — mutually exclusive
    # ------------------------------------------------------------------ #
    if jenis in ("kaos", "polo"):
        routing.append(2)
        kode_kapasitas[2] = jenis                      # "kaos" atau "polo"
    else:  # kemeja / jaket
        routing.append(3)
        kode_kapasitas[3] = _kode_jahit_kemeja_jaket(jenis, furing)

    # ------------------------------------------------------------------ #
    # LAPIS 2: Dekorasi opsional (urutan fixed: Sablon→DTF→Bordir)
    # ------------------------------------------------------------------ #
    flags_dekorasi = {4: sablon, 5: dtf, 6: bordir}
    for st in URUTAN_DEKORASI:                         # [4, 5, 6]
        if flags_dekorasi[st]:
            routing.append(st)
            kode_kapasitas[st] = "semua"

    # ------------------------------------------------------------------ #
    # LAPIS 3: Pasang kancing opsional
    # ------------------------------------------------------------------ #
    if kancing and jenis not in PRODUK_TANPA_KANCING:
        routing.append(7)
        kode_kapasitas[7] = "polo_kancing" if jenis == "polo" else "non_polo_kancing"

    # ------------------------------------------------------------------ #
    # STASIUN FINISHING: selalu aktif (8, 9, 10)
    # ------------------------------------------------------------------ #
    for st in (8, 9, 10):
        routing.append(st)
    kode_kapasitas[8]  = "dengan_furing" if furing else "tanpa_furing"
    kode_kapasitas[9]  = "semua"
    kode_kapasitas[10] = "semua"

    # ------------------------------------------------------------------ #
    # HITUNG WAKTU PROSES per stasiun (menit total untuk seluruh unit)
    # ------------------------------------------------------------------ #
    waktu_proses = _hitung_waktu_proses(routing, kode_kapasitas, unit)

    hasil = pesanan.copy()
    hasil["routing"]        = routing
    hasil["kode_kapasitas"] = kode_kapasitas
    hasil["waktu_proses"]   = waktu_proses
    return hasil


def bangun_routing_semua(pesanan_list: list[dict]) -> list[dict]:
    """Terapkan bangun_routing() ke seluruh list pesanan."""
    return [bangun_routing(p) for p in pesanan_list]


# ---------------------------------------------------------------------------
# HELPER: KODE KAPASITAS
# ---------------------------------------------------------------------------

def _kode_potong(jenis: str, furing: bool) -> str:
    """Tentukan kode kondisi untuk lookup kapasitas stasiun potong."""
    if jenis in ("kaos", "polo"):
        return jenis                          # "kaos" atau "polo"
    if furing:
        return f"{jenis}_furing"             # "kemeja_furing" / "jaket_furing"
    return jenis                              # "kemeja" / "jaket"


def _kode_jahit_kemeja_jaket(jenis: str, furing: bool) -> str:
    """Tentukan kode kondisi untuk lookup kapasitas stasiun jahit kemeja/jaket."""
    if furing:
        return f"{jenis}_furing"
    return jenis


# ---------------------------------------------------------------------------
# HELPER: HITUNG WAKTU PROSES
# ---------------------------------------------------------------------------

def _hitung_waktu_proses(
    routing: list[int],
    kode_kapasitas: dict,
    jumlah_unit: int,
) -> dict:
    """
    Hitung total menit proses untuk job ini di setiap stasiun.

    Rumus: waktu_proses[st] = (jumlah_unit / kapasitas_per_resource) × MENIT_PER_HARI
    Atau equivalently: jumlah_unit × menit_per_unit

    Catatan: nilai ini adalah waktu proses SATU resource (tim/mesin/operator).
    Pembagian dengan jumlah resource dilakukan di simulator.py saat scheduling,
    karena jumlah resource bisa bervariasi (default vs crashing).
    """
    waktu = {}
    for st in routing:
        kode = kode_kapasitas[st]
        kapasitas_per_resource = KAPASITAS[st][kode]   # unit per hari per resource
        menit_per_unit = MENIT_PER_HARI / kapasitas_per_resource
        waktu[st] = round(jumlah_unit * menit_per_unit, 4)
    return waktu


# ---------------------------------------------------------------------------
# UTILITAS INFORMASI ROUTING
# ---------------------------------------------------------------------------

def deskripsi_routing(pesanan: dict) -> str:
    """
    Buat string deskripsi routing untuk display (misal di tab verifikasi).
    Contoh output: "Potong → Jahit Kaos/Polo → Sablon → Buang Benang → Lipat → Packing"
    """
    from config import STASIUN
    return " → ".join(STASIUN[st] for st in pesanan["routing"])


def ringkasan_waktu_proses(pesanan: dict) -> list[dict]:
    """
    Buat list of dict untuk tabel display waktu proses per stasiun.
    """
    from config import STASIUN, RESOURCE_CONFIG
    rows = []
    for st in pesanan["routing"]:
        wp = pesanan["waktu_proses"][st]
        resource_default = RESOURCE_CONFIG[st]["default"]
        wp_efektif = wp / resource_default      # dengan resource default
        rows.append({
            "Stasiun":          f"St.{st} – {STASIUN[st]}",
            "Kode kondisi":     pesanan["kode_kapasitas"][st],
            "Waktu (1 resource)": f"{wp:.1f} mnt",
            "Resource default": resource_default,
            "Waktu efektif":    f"{wp_efektif:.1f} mnt",
        })
    return rows


def kelompokkan_per_routing_type(pesanan_list: list[dict]) -> dict:
    """
    Kelompokkan pesanan berdasarkan pattern routing (tuple).
    Berguna untuk analisis dan debug.
    Return: { tuple_routing : [pesanan, ...] }
    """
    hasil = {}
    for p in pesanan_list:
        key = tuple(p["routing"])
        hasil.setdefault(key, []).append(p)
    return hasil
