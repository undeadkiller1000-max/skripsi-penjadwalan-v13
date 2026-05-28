"""
scheduler/benchmark.py
======================
Metode pembanding: First Come First Served (FCFS).
Menjadwalkan pesanan persis sesuai urutan masuknya ke sistem
(field 'urutan_masuk' dari data_handler).

Ini merepresentasikan cara penjadwalan yang saat ini digunakan
oleh Cigem Creative — sehingga perbandingan skor SA/MILP vs FCFS
langsung menunjukkan nilai tambah dari sistem optimasi.
"""

from simulator import simulate_schedule, ringkasan_performa


def jalankan_fcfs(
    pesanan_routed: list[dict],
    resource_override: dict = None,
    setup_time: dict = None,
) -> tuple[list[dict], float, dict]:
    """
    Jalankan penjadwalan FCFS.

    Parameter
    ---------
    pesanan_routed   : list[dict] pesanan dengan routing sudah dibangun
    resource_override: override jumlah resource (opsional)
    setup_time       : setup time per stasiun (opsional)

    Return
    ------
    (hasil_list, total_weighted_tardiness, ringkasan)
    """
    # Urutkan berdasarkan urutan masuk (indeks 0 = paling duluan masuk)
    urutan_fcfs = sorted(pesanan_routed, key=lambda p: p["urutan_masuk"])

    hasil, total_wt = simulate_schedule(
        urutan_fcfs,
        resource_override=resource_override,
        setup_time=setup_time,
    )
    ringkasan = ringkasan_performa(hasil)
    return hasil, total_wt, ringkasan
