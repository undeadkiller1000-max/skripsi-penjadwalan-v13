"""
ui/dashboard.py
===============
Dashboard 8 tab hasil optimasi.

Perbaikan:
  #4 - Judul tab sesuai nama metode (pemenang vs kalah)
  #5 - Teks label di Gantt chart hitam (bukan putih)
  #6 - Warna tabel lebih kontras (merah gelap = terlambat, hijau gelap = tepat)
"""

import streamlit as st
import pandas as pd
from datetime import date

from config import STASIUN, RESOURCE_CONFIG
from calendar_utils import menit_ke_tanggal_waktu, format_durasi
from verifier import verifikasi_jadwal, buat_routing_chart
from simulator import ringkasan_performa
from gantt_chart import buat_gantt
from exporter import export_ke_excel

# Warna tabel yang kontras
WARNA_TERLAMBAT_BG  = "#8B0000"   # merah gelap
WARNA_TERLAMBAT_FG  = "#FFFFFF"   # putih
WARNA_TEPAT_BG      = "#1B5E20"   # hijau gelap
WARNA_TEPAT_FG      = "#FFFFFF"   # putih


# ---------------------------------------------------------------------------
# ENTRY POINT UTAMA
# ---------------------------------------------------------------------------
def render_dashboard(
    hasil_pemenang, hasil_sa, hasil_fcfs,
    hasil_kalah=None,
    pesanan_routed=None,
    tanggal_mulai=None,
    nama_pemenang="SA",
    nama_kalah=None,
    info_sa=None, info_milp=None,
    resource_aktual=None, setup_time=None,
):
    # Tentukan label tab #2 berdasarkan siapa yang kalah (poin #4)
    if nama_kalah:
        label_tab2 = f"📊 Gantt {nama_kalah}"
        hasil_tab2 = hasil_kalah
    else:
        label_tab2 = "📊 Gantt SA"
        hasil_tab2 = hasil_sa

    tabs = st.tabs([
        f"📊 Gantt {nama_pemenang} (Terbaik)",
        label_tab2,
        "📊 Gantt FCFS",
        "📋 Laporan Manajemen",
        "🏭 Lembar Kerja Stasiun",
        "✅ Verifikasi & Routing",
        "➕ Pesanan Baru",
        "⚡ Analisis Crashing",
    ])

    with tabs[0]:
        _tab_gantt(hasil_pemenang, tanggal_mulai, f"Jadwal Terbaik — {nama_pemenang}")

    with tabs[1]:
        judul2 = f"Jadwal {nama_kalah}" if nama_kalah else "Jadwal Simulated Annealing"
        _tab_gantt(hasil_tab2, tanggal_mulai, judul2)

    with tabs[2]:
        _tab_gantt(hasil_fcfs, tanggal_mulai, "Jadwal FCFS (Kondisi Saat Ini)")

    with tabs[3]:
        _tab_laporan_manajemen(
            hasil_pemenang, hasil_fcfs, tanggal_mulai,
            nama_pemenang, info_sa, info_milp
        )

    with tabs[4]:
        _tab_lembar_kerja_stasiun(hasil_pemenang, tanggal_mulai)

    with tabs[5]:
        _tab_verifikasi(hasil_pemenang, pesanan_routed, tanggal_mulai)

    with tabs[6]:
        render_tab_reoptimasi(
            hasil_pemenang, pesanan_routed, tanggal_mulai,
            resource_aktual or {}, setup_time or {}
        )

    with tabs[7]:
        render_tab_crashing(pesanan_routed, tanggal_mulai, setup_time or {})

    st.divider()
    _render_download(hasil_pemenang, hasil_fcfs, tanggal_mulai, nama_pemenang)


# ---------------------------------------------------------------------------
# TAB GANTT (poin #5: teks hitam)
# ---------------------------------------------------------------------------
def _tab_gantt(hasil_list, tanggal_mulai, judul):
    if not hasil_list:
        st.warning("Tidak ada data jadwal.")
        return

    performa = ringkasan_performa(hasil_list)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total W.Tardiness", f"{performa['total_weighted_tardiness']:,.1f}")
    col2.metric("Tepat Waktu",
                f"{performa['n_tepat_waktu']}/{performa['n_job']}",
                f"{performa['pct_tepat_waktu']}%")
    col3.metric("Maks Tardiness", format_durasi(performa["maks_tardiness"]))
    col4.metric("Rata-rata Tardiness", format_durasi(performa["rata_tardiness"]))

    st.divider()
    mode = st.radio(
        "Mode warna:", ["Per pesanan", "Status ketepatan waktu"],
        horizontal=True, key=f"mode_{judul}",
    )
    mode_key = "job" if mode == "Per pesanan" else "status"

    fig = buat_gantt(hasil_list, tanggal_mulai, mode=mode_key, judul=judul)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Lihat data tabel"):
        rows = []
        for h in hasil_list:
            tgl_s, wkt_s = menit_ke_tanggal_waktu(tanggal_mulai, h["completion_time"])
            rows.append({
                "ID": h["id_pesanan"],
                "Produk": h["jenis_produk"].capitalize(),
                "Unit": h["jumlah_unit"],
                "Prioritas": h["prioritas"],
                "Selesai": f"{tgl_s.strftime('%d/%m/%Y')} {wkt_s}",
                "Deadline": h["deadline_tgl"].strftime("%d/%m/%Y"),
                "Tardiness": format_durasi(h["tardiness"]),
                "Status": "⚠ Terlambat" if h["terlambat"] else "✓ Tepat",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# TAB LAPORAN MANAJEMEN (poin #6: warna kontras)
# ---------------------------------------------------------------------------
def _tab_laporan_manajemen(hasil_pemenang, hasil_fcfs, tanggal_mulai,
                            nama_pemenang, info_sa, info_milp):
    st.subheader("Perbandingan Performa Metode")
    perf_p = ringkasan_performa(hasil_pemenang)
    perf_f = ringkasan_performa(hasil_fcfs)

    data_perb = {
        "Metode": [nama_pemenang, "FCFS"],
        "Total W.Tardiness": [perf_p["total_weighted_tardiness"], perf_f["total_weighted_tardiness"]],
        "Tepat Waktu": [f"{perf_p['n_tepat_waktu']}/{perf_p['n_job']}",
                        f"{perf_f['n_tepat_waktu']}/{perf_f['n_job']}"],
        "% Tepat Waktu": [f"{perf_p['pct_tepat_waktu']}%", f"{perf_f['pct_tepat_waktu']}%"],
        "Maks Tardiness": [format_durasi(perf_p["maks_tardiness"]),
                           format_durasi(perf_f["maks_tardiness"])],
    }
    st.dataframe(pd.DataFrame(data_perb), use_container_width=True, hide_index=True)

    if perf_f["total_weighted_tardiness"] > 0:
        impr = ((perf_f["total_weighted_tardiness"] - perf_p["total_weighted_tardiness"])
                / perf_f["total_weighted_tardiness"] * 100)
        st.metric(f"Improvement {nama_pemenang} vs FCFS", f"{impr:.1f}%",
                  f"Pengurangan W.Tardiness sebesar {impr:.1f}%")
    else:
        st.info("FCFS sudah zero tardiness.")

    # Info komputasi
    with st.expander("Info Komputasi", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Simulated Annealing**")
            if info_sa:
                st.write(f"- Iterasi: {info_sa.get('n_iterasi_dijalankan','-'):,}")
                st.write(f"- Waktu: {info_sa.get('waktu_komputasi_detik','-')} detik")
                st.write(f"- W.Tardiness SA: {info_sa.get('wt_terbaik','-'):.1f}")
        with col2:
            st.markdown("**MILP (CBC)**")
            if info_milp:
                st.write(f"- Status: {info_milp.get('status','-')}")
                st.write(f"- Waktu: {info_milp.get('waktu_komputasi_detik','-')} detik")
                wt_m = info_milp.get("objective_value")
                st.write(f"- W.Tardiness MILP: {wt_m:.1f}" if wt_m else "- MILP: tidak ada solusi / dilewati")

    st.divider()

    # Tabel detail — poin #6: warna kontras
    st.subheader(f"Detail Jadwal — {nama_pemenang}")
    rows = []
    for h in hasil_pemenang:
        tgl_s, wkt_s = menit_ke_tanggal_waktu(tanggal_mulai, h["completion_time"])
        rows.append({
            "ID Pesanan":       h["id_pesanan"],
            "Produk":           h["jenis_produk"].capitalize(),
            "Unit":             h["jumlah_unit"],
            "Prioritas":        h["prioritas"],
            "Deadline":         h["deadline_tgl"].strftime("%d/%m/%Y"),
            "Estimasi Selesai": f"{tgl_s.strftime('%d/%m/%Y')} {wkt_s}",
            "Tardiness":        format_durasi(h["tardiness"]),
            "W.Tardiness":      f"{h['weighted_tardiness']:.1f}",
            "Status":           "⚠ Terlambat" if h["terlambat"] else "✓ Tepat Waktu",
        })

    df_detail = pd.DataFrame(rows)

    def _style_row(row):
        if row["Status"].startswith("⚠"):
            return [f"background-color:{WARNA_TERLAMBAT_BG};color:{WARNA_TERLAMBAT_FG}"] * len(row)
        return [f"background-color:{WARNA_TEPAT_BG};color:{WARNA_TEPAT_FG}"] * len(row)

    st.dataframe(
        df_detail.style.apply(_style_row, axis=1),
        use_container_width=True, hide_index=True,
    )


# ---------------------------------------------------------------------------
# TAB LEMBAR KERJA STASIUN (poin #6: warna kontras)
# ---------------------------------------------------------------------------
def _tab_lembar_kerja_stasiun(hasil_list, tanggal_mulai):
    st.subheader("Lembar Kerja Operasional per Stasiun")
    st.caption("Pilih stasiun untuk melihat jadwal operator/tim.")

    stasiun_aktif = sorted({st for h in hasil_list for st in h["schedule"]})
    if not stasiun_aktif:
        st.warning("Tidak ada data.")
        return

    pilihan = st.selectbox(
        "Pilih stasiun:",
        options=stasiun_aktif,
        format_func=lambda s: f"St.{s} – {STASIUN[s]}",
        key="st_lembar",
    )

    ops_list = []
    for h in hasil_list:
        if pilihan in h["schedule"]:
            ops = h["schedule"][pilihan]
            tgl_m, wkt_m = menit_ke_tanggal_waktu(tanggal_mulai, ops["start"])
            tgl_s, wkt_s = menit_ke_tanggal_waktu(tanggal_mulai, ops["end"])
            ops_list.append({
                "Resource #":  ops["resource"],
                "ID Pesanan":  h["id_pesanan"],
                "Produk":      h["jenis_produk"].capitalize(),
                "Unit":        h["jumlah_unit"],
                "Prioritas":   h["prioritas"],
                "Tgl Mulai":   tgl_m.strftime("%d/%m/%Y"),
                "Jam Mulai":   wkt_m,
                "Tgl Selesai": tgl_s.strftime("%d/%m/%Y"),
                "Jam Selesai": wkt_s,
                "Durasi":      format_durasi(ops["end"] - ops["start"]),
                "Status":      "⚠ Terlambat" if h["terlambat"] else "✓ Tepat",
                "_start":      ops["start"],
                "_telat":      h["terlambat"],
            })

    ops_list.sort(key=lambda x: (x["Resource #"], x["_start"]))
    df_ops = pd.DataFrame(ops_list).drop(columns=["_start", "_telat"])

    def _style_ops(row):
        if row["Status"].startswith("⚠"):
            return [f"background-color:{WARNA_TERLAMBAT_BG};color:{WARNA_TERLAMBAT_FG}"] * len(row)
        return [f"background-color:{WARNA_TEPAT_BG};color:{WARNA_TEPAT_FG}"] * len(row)

    st.dataframe(
        df_ops.style.apply(_style_ops, axis=1),
        use_container_width=True, hide_index=True,
    )
    st.caption(f"Total {len(ops_list)} operasi di stasiun ini.")


# ---------------------------------------------------------------------------
# TAB VERIFIKASI
# ---------------------------------------------------------------------------
def _tab_verifikasi(hasil_pemenang, pesanan_routed, tanggal_mulai):
    st.subheader("Verifikasi Jadwal")
    laporan = verifikasi_jadwal(hasil_pemenang, tanggal_mulai)

    if laporan["lulus"]:
        st.success(laporan["ringkasan"])
    else:
        st.error(laporan["ringkasan"])

    col1, col2, col3 = st.columns(3)
    _render_cek_item(col1, "No-Overlap Resource", laporan["no_overlap"])
    _render_cek_item(col2, "Urutan Operasi (Precedence)", laporan["precedence"])
    _render_cek_item(col3, "Tidak Ada Operasi di Minggu", laporan["no_sunday"])

    for nama, key in [("No-Overlap","no_overlap"),("Precedence","precedence"),("No-Sunday","no_sunday")]:
        pelanggaran = laporan[key]["pelanggaran"]
        if pelanggaran:
            with st.expander(f"Detail pelanggaran {nama} ({len(pelanggaran)})"):
                st.dataframe(pd.DataFrame(pelanggaran), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Operation Process Chart (Routing per Pesanan)")
    st.dataframe(pd.DataFrame(buat_routing_chart(pesanan_routed)),
                 use_container_width=True, hide_index=True)


def _render_cek_item(col, label, hasil_cek):
    with col:
        if hasil_cek["lulus"]:
            st.success(f"✓ {label}")
        else:
            st.error(f"✗ {label} — {len(hasil_cek['pelanggaran'])} pelanggaran")


# ---------------------------------------------------------------------------
# TAB RE-OPTIMASI
# ---------------------------------------------------------------------------
def render_tab_reoptimasi(hasil_jadwal_aktif, pesanan_routed,
                           tanggal_mulai, resource_override, setup_time):
    from reoptimizer import jalankan_reoptimasi
    from data_handler import validasi_dan_bersihkan, baca_file
    from routing import bangun_routing_semua

    st.subheader("Penjadwalan Pesanan Baru di Tengah Produksi")
    st.info("Tandai pesanan yang sudah mulai dikerjakan sebagai 'terkunci', "
            "lalu input pesanan baru.", icon="ℹ️")

    if not hasil_jadwal_aktif:
        st.warning("Jalankan optimasi utama terlebih dahulu.")
        return

    st.markdown("**Langkah 1: Tandai pesanan yang sudah mulai dikerjakan**")
    id_terkunci = []
    cols = st.columns(3)
    for i, h in enumerate(hasil_jadwal_aktif):
        with cols[i % 3]:
            tgl_s, wkt_s = menit_ke_tanggal_waktu(tanggal_mulai, h["completion_time"])
            if st.checkbox(
                f"{h['id_pesanan']} ({h['jenis_produk']} {h['jumlah_unit']}u)",
                key=f"kunci_{h['id_pesanan']}",
                help=f"Est. selesai: {tgl_s.strftime('%d/%m')} {wkt_s}",
            ):
                id_terkunci.append(h["id_pesanan"])
    st.caption(f"{len(id_terkunci)} pesanan dikunci.")

    st.divider()
    st.markdown("**Langkah 2: Input pesanan baru**")
    uploaded = st.file_uploader("Upload file pesanan baru (CSV/Excel)",
                                type=["csv","xlsx","xls"], key="reopt_upload")
    if uploaded is None:
        st.caption("Upload file pesanan baru untuk melanjutkan.")
        return

    df_baru_raw, err = baca_file(uploaded)
    if df_baru_raw is None:
        st.error(f"Gagal baca file: {err}")
        return

    if st.button("Jalankan Re-optimasi", type="primary", key="btn_reopt"):
        pesanan_baru_raw, _ = validasi_dan_bersihkan(df_baru_raw, tanggal_mulai, drop_error=True)
        if not pesanan_baru_raw:
            st.error("Tidak ada pesanan baru yang valid.")
            return

        pesanan_baru_routed = bangun_routing_semua(pesanan_baru_raw)
        pesanan_terkunci    = [h for h in hasil_jadwal_aktif if h["id_pesanan"] in set(id_terkunci)]
        pesanan_bebas       = [p for p in pesanan_routed if p["id_pesanan"] not in set(id_terkunci)]

        with st.spinner("Menjalankan re-optimasi..."):
            hasil = jalankan_reoptimasi(
                pesanan_terkunci, pesanan_bebas, pesanan_baru_routed,
                tanggal_mulai, resource_override, setup_time
            )

        st.success(f"Selesai dalam {hasil['waktu_komputasi']}s")
        for jid, rek in hasil["rekomendasi_deadline"].items():
            col1, col2 = st.columns(2)
            col1.metric("Estimasi Selesai",
                        f"{rek['estimasi_selesai'].strftime('%d/%m/%Y')} {rek['waktu_selesai']}")
            col2.metric("Deadline Rekomendasi",
                        rek["deadline_rekomendasi"].strftime("%d/%m/%Y"))

        dampak = hasil["dampak"]
        if dampak["n_terdampak"] > 0:
            st.warning(f"⚠ {dampak['n_terdampak']} pesanan lama menjadi terlambat.")
        else:
            st.success("✓ Tidak ada pesanan lama yang terdampak.")

        if hasil["jadwal_lengkap"]:
            fig = buat_gantt(hasil["jadwal_lengkap"], tanggal_mulai,
                             mode="status", judul="Jadwal Setelah Re-optimasi")
            st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# TAB CRASHING
# ---------------------------------------------------------------------------
def render_tab_crashing(pesanan_routed, tanggal_mulai, setup_time):
    from crashing import crashing_target_tanggal, crashing_target_persen, crashing_realita_cigem

    st.subheader("Analisis Crashing — Penambahan Resource")
    st.info("Hitung resource tambahan minimum agar target ketepatan waktu tercapai.", icon="⚡")

    skenario = st.radio(
        "Pilih skenario:",
        ["Skenario 1: Target Tanggal Selesai",
         "Skenario 2: Target Persen Percepatan",
         "Skenario 3: Realita Cigem (Tambah Tim Jahit Kaos/Polo)"],
        key="skenario_crash",
    )

    if skenario.startswith("Skenario 1"):
        from datetime import timedelta
        col1, col2 = st.columns(2)
        with col1:
            tgl_target = st.date_input("Target semua selesai sebelum:",
                                       value=tanggal_mulai + timedelta(days=30),
                                       key="crash_tgl")
        with col2:
            st_crash = st.multiselect("Stasiun yang boleh ditambah:",
                                      options=list(range(1,11)), default=[2,3,8],
                                      format_func=lambda x: f"St.{x} – {STASIUN[x]}",
                                      key="crash_st1")
        st.warning("⏳ Analisis ini menjalankan SA berulang dan bisa memakan waktu beberapa menit.", icon="⚠️")
        if st.button("Jalankan Analisis", type="primary", key="btn_c1"):
            with st.spinner("Menganalisis..."):
                hasil = crashing_target_tanggal(pesanan_routed, tgl_target, tanggal_mulai, st_crash, setup_time)
            _render_hasil_crashing(hasil, tanggal_mulai)

    elif skenario.startswith("Skenario 2"):
        col1, col2 = st.columns(2)
        with col1:
            persen = st.slider("Target percepatan (%):", 10, 100, 50, 10, key="crash_pct")
        with col2:
            st_crash = st.multiselect("Stasiun yang boleh ditambah:",
                                      options=list(range(1,11)), default=[2,3,8],
                                      format_func=lambda x: f"St.{x} – {STASIUN[x]}",
                                      key="crash_st2")
        st.warning("⏳ Analisis ini menjalankan SA berulang dan bisa memakan waktu beberapa menit.", icon="⚠️")
        if st.button("Jalankan Analisis", type="primary", key="btn_c2"):
            with st.spinner("Menganalisis..."):
                hasil = crashing_target_persen(pesanan_routed, persen, st_crash, setup_time)
            _render_hasil_crashing(hasil, tanggal_mulai)

    else:
        st.caption("Menguji penambahan tim di St.2 (Jahit Kaos/Polo): 1–3 tim.")
        if st.button("Jalankan Analisis", type="primary", key="btn_c3"):
            with st.spinner("Menganalisis 3 level..."):
                hasil = crashing_realita_cigem(pesanan_routed, setup_time)
            _render_hasil_crashing_cigem(hasil, tanggal_mulai)


def _render_hasil_crashing(hasil, tanggal_mulai):
    st.divider()
    if hasil["tercapai"]:
        st.success(f"✓ Target tercapai!")
    else:
        st.warning("⚠ Target tidak tercapai meski semua stasiun sudah di kapasitas maks.")

    col1, col2, col3 = st.columns(3)
    col1.metric("W.Tardiness Awal", f"{hasil['wt_awal']:,.1f}")
    col2.metric("W.Tardiness Final", f"{hasil['wt_final']:,.1f}",
                delta=f"-{hasil['improvement_pct']}%")
    col3.metric("Tepat Waktu", f"{hasil['pct_tepat_waktu']}%")

    if hasil["langkah"]:
        st.markdown("**Langkah penambahan resource:**")
        st.dataframe(pd.DataFrame(hasil["langkah"]), use_container_width=True, hide_index=True)

    if hasil["resource_tambahan"]:
        st.markdown("**Resource yang perlu ditambah:**")
        for st_id, tambah in hasil["resource_tambahan"].items():
            default = RESOURCE_CONFIG[st_id]["default"]
            st.write(f"- St.{st_id} {STASIUN[st_id]}: +{tambah} (dari {default} → {default+tambah})")

    if hasil["hasil_final"]:
        fig = buat_gantt(hasil["hasil_final"], tanggal_mulai,
                         mode="status", judul="Jadwal Setelah Crashing")
        st.plotly_chart(fig, use_container_width=True)


def _render_hasil_crashing_cigem(hasil, tanggal_mulai):
    st.divider()
    rek = hasil["rekomendasi_tim"]
    if rek:
        st.success(f"✓ Zero tardiness tercapai dengan {rek} tim di St.2")
    else:
        st.warning("⚠ Penambahan tim di St.2 saja tidak cukup.")

    rows = []
    for lv in hasil["hasil_per_level"]:
        rows.append({
            "Jumlah Tim St.2": lv["n_tim"],
            "W.Tardiness":     round(lv["total_wt"], 1),
            "Tepat Waktu":     f"{lv['n_tepat_waktu']}/{lv['n_tepat_waktu']+lv['n_terlambat']}",
            "% Tepat Waktu":   f"{lv['pct_tepat_waktu']}%",
            "Rekomendasi":     "← Minimum" if lv["n_tim"] == rek else "",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    level_tampil = rek if rek else hasil["hasil_per_level"][-1]["n_tim"]
    jadwal_tampil = next(lv["hasil"] for lv in hasil["hasil_per_level"] if lv["n_tim"] == level_tampil)
    fig = buat_gantt(jadwal_tampil, tanggal_mulai, mode="status",
                     judul=f"Jadwal dengan {level_tampil} Tim Jahit Kaos/Polo")
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# DOWNLOAD
# ---------------------------------------------------------------------------
def _render_download(hasil_pemenang, hasil_fcfs, tanggal_mulai, nama_metode):
    st.subheader("Unduh Hasil")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"File Excel: Laporan Manajemen, Jadwal per Stasiun, Detail {nama_metode}, Detail FCFS.")
    with col2:
        try:
            excel_bytes = export_ke_excel(hasil_pemenang, hasil_fcfs, tanggal_mulai, nama_metode)
            st.download_button(
                "⬇ Unduh Excel", data=excel_bytes,
                file_name=f"jadwal_cigem_{tanggal_mulai.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            st.error(f"Gagal buat Excel: {e}")
