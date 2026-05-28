"""
config.py
=========
Semua konstanta, parameter kapasitas, dan konfigurasi sistem DSS Cigem Creative.
Tidak ada logika bisnis di sini — hanya data statis yang dibaca oleh modul lain.
"""

# ---------------------------------------------------------------------------
# PARAMETER WAKTU KERJA
# ---------------------------------------------------------------------------

MENIT_PER_HARI = 450          # 08.30–11.30 (180 mnt) + 13.00–17.30 (270 mnt)
JAM_MULAI_PAGI  = (8,  30)    # tuple (jam, menit)
JAM_SELESAI_PAGI = (11, 30)
JAM_MULAI_SIANG  = (13,  0)
JAM_SELESAI_SIANG = (17, 30)
HARI_LIBUR = [6]              # 6 = Minggu (weekday() Python: 0=Senin … 6=Minggu)

# ---------------------------------------------------------------------------
# DEFINISI STASIUN
# Kunci: nomor stasiun (int)
# ---------------------------------------------------------------------------

STASIUN = {
    1:  "Potong",
    2:  "Jahit Kaos/Polo",
    3:  "Jahit Kemeja/Jaket",
    4:  "Sablon",
    5:  "DTF",
    6:  "Bordir",
    7:  "Pasang Kancing",
    8:  "Buang Benang",
    9:  "Lipat",
    10: "Packing",
}

# ---------------------------------------------------------------------------
# RESOURCE DEFAULT & MAKSIMUM PER STASIUN
# Format: { stasiun_id: {"default": int, "max": int} }
# ---------------------------------------------------------------------------

RESOURCE_CONFIG = {
    1:  {"default": 1, "max": 2},
    2:  {"default": 1, "max": 3},
    3:  {"default": 3, "max": 6},
    4:  {"default": 2, "max": 5},
    5:  {"default": 1, "max": 5},
    6:  {"default": 1, "max": 1},   # bordir: maks tetap 1
    7:  {"default": 1, "max": 2},
    8:  {"default": 2, "max": 5},
    9:  {"default": 1, "max": 5},
    10: {"default": 1, "max": 5},
}

# ---------------------------------------------------------------------------
# KAPASITAS PRODUKSI (unit/hari/resource)
# Dikembalikan sebagai menit_per_unit = MENIT_PER_HARI / kapasitas
#
# Kunci level pertama : stasiun_id
# Kunci level kedua   : kode kondisi produk (lihat keterangan di bawah)
#
# Kode kondisi:
#   "kaos"         = kaos (tanpa furing, tanpa kancing relevan)
#   "polo"         = polo (tanpa furing)
#   "kemeja"       = kemeja tanpa furing
#   "kemeja_furing"= kemeja dengan furing
#   "jaket"        = jaket tanpa furing
#   "jaket_furing" = jaket dengan furing
#   "semua"        = berlaku sama untuk semua jenis produk
#   "tanpa_furing" = produk apapun tanpa furing
#   "dengan_furing"= produk apapun dengan furing
#   "polo_kancing" = polo dengan kancing
#   "non_polo_kancing" = kemeja/jaket dengan kancing
# ---------------------------------------------------------------------------

KAPASITAS = {
    # --- Stasiun 1: Potong ---
    1: {
        "kaos":          1000,    # 0.45 mnt/unit
        "polo":          1000,    # 0.45 mnt/unit
        "kemeja":         250,    # 1.80 mnt/unit
        "kemeja_furing":  125,    # 3.60 mnt/unit
        "jaket":          250,    # 1.80 mnt/unit
        "jaket_furing":   125,    # 3.60 mnt/unit
    },

    # --- Stasiun 2: Jahit Kaos/Polo (per tim) ---
    2: {
        "kaos": 112.5,            # 4.00 mnt/unit
        "polo":  55.0,            # 8.18 mnt/unit
    },

    # --- Stasiun 3: Jahit Kemeja/Jaket (per tim) ---
    3: {
        "kemeja":          13.5,  # 33.33 mnt/unit
        "kemeja_furing":    9.0,  # 50.00 mnt/unit
        "jaket":           11.0,  # 40.91 mnt/unit
        "jaket_furing":     7.33, # 61.39 mnt/unit
    },

    # --- Stasiun 4: Sablon ---
    4: {
        "semua": 700,             # 0.64 mnt/unit
    },

    # --- Stasiun 5: DTF ---
    5: {
        "semua": 750,             # 0.60 mnt/unit
    },

    # --- Stasiun 6: Bordir ---
    6: {
        "semua": 442.5,           # 1.02 mnt/unit
    },

    # --- Stasiun 7: Pasang Kancing ---
    7: {
        "polo_kancing":     400,  # 1.13 mnt/unit
        "non_polo_kancing": 125,  # 3.60 mnt/unit
    },

    # --- Stasiun 8: Buang Benang (per operator) ---
    8: {
        "tanpa_furing": 500,      # 0.90 mnt/unit  (2 op default → 1000/hari efektif)
        "dengan_furing": 166.67,  # 2.70 mnt/unit  (2 op default → 333.34/hari efektif)
    },

    # --- Stasiun 9: Lipat ---
    9: {
        "semua": 500,             # 0.90 mnt/unit
    },

    # --- Stasiun 10: Packing ---
    10: {
        "semua": 500,             # 0.90 mnt/unit
    },
}

# ---------------------------------------------------------------------------
# JENIS PRODUK YANG VALID
# ---------------------------------------------------------------------------

JENIS_PRODUK_VALID = {"kaos", "polo", "kemeja", "jaket"}

# Produk yang TIDAK BOLEH memiliki furing
PRODUK_TANPA_FURING = {"kaos", "polo"}

# Produk yang TIDAK BOLEH memiliki kancing (sistem abaikan flag kancing)
PRODUK_TANPA_KANCING = {"kaos"}

# ---------------------------------------------------------------------------
# PARAMETER SIMULATED ANNEALING
# ---------------------------------------------------------------------------

SA_CONFIG = {
    "n_iterasi":       8_000,
    "suhu_awal":       500.0,
    "laju_pendinginan": 0.997,
    "seed":            42,        # reproducibility
}

# ---------------------------------------------------------------------------
# PARAMETER MILP
# ---------------------------------------------------------------------------

MILP_CONFIG = {
    "time_limit_detik": 300,
    "solver":           "CBC",
    "gap_relatif":      0.05,     # terima solusi dalam 5% dari optimal
}

# ---------------------------------------------------------------------------
# BOBOT PRIORITAS (untuk weighted tardiness)
# ---------------------------------------------------------------------------

BOBOT_PRIORITAS = {
    "Normal":  1,
    "Tinggi":  2,
    "Kritis":  3,
}

# ---------------------------------------------------------------------------
# URUTAN DEKORASI (fixed, tidak bisa dikonfigurasi pengguna)
# Jika sebuah job memerlukan lebih dari satu dekorasi,
# urutan ini menentukan stasiun mana yang dikunjungi lebih dulu.
# ---------------------------------------------------------------------------

URUTAN_DEKORASI = [4, 5, 6]   # Sablon → DTF → Bordir

# ---------------------------------------------------------------------------
# KOLOM YANG WAJIB ADA DI FILE INPUT
# ---------------------------------------------------------------------------

KOLOM_WAJIB = [
    "id_pesanan",
    "jenis_produk",
    "jumlah_unit",
    "deadline",       # format: YYYY-MM-DD
    "prioritas",      # Normal / Tinggi / Kritis
    "furing",         # 0 atau 1
    "sablon",         # 0 atau 1
    "dtf",            # 0 atau 1
    "bordir",         # 0 atau 1
    "kancing",        # 0 atau 1
]

# ---------------------------------------------------------------------------
# SETUP TIME DEFAULT (menit, per stasiun, per job yang dikerjakan hari itu)
# Pengguna dapat mengubah nilai ini via sidebar Streamlit.
# Default 0 karena kapasitas sudah memperhitungkan setup.
# ---------------------------------------------------------------------------

SETUP_TIME_DEFAULT = {
    1: 0, 2: 0, 3: 0, 4: 0, 5: 0,
    6: 0, 7: 0, 8: 0, 9: 0, 10: 0,
}
