"""
app.py - DSS Penjadwalan Produksi Cigem Creative
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import STASIUN, RESOURCE_CONFIG, SA_CONFIG, MILP_CONFIG, SETUP_TIME_DEFAULT, BOBOT_PRIORITAS
from data_handler import baca_file, validasi_dan_bersihkan, generate_template
from routing import bangun_routing_semua
from simulator import ringkasan_performa
from sa_optimizer import jalankan_sa
from milp_optimizer import jalankan_milp
from benchmark import jalankan_fcfs
from dashboard import render_dashboard

st.set_page_config(
    page_title="DSS Penjadwalan Produksi — Cigem Creative",
    page_icon="🏭", layout="wide", initial_sidebar_state="expanded",
)

NAMA_BULAN = {
    1:"Januari", 2:"Februari", 3:"Maret", 4:"April",
    5:"Mei", 6:"Juni", 7:"Juli", 8:"Agustus",
    9:"September", 10:"Oktober", 11:"November", 12:"Desember",
}

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
def render_sidebar():
    st.sidebar.title("⚙️ Konfigurasi")
    st.sidebar.subheader("📅 Tanggal Produksi")
    tanggal_mulai = st.sidebar.date_input(
        "Tanggal mulai produksi", value=date.today(),
        help="Hari pertama produksi batch ini (t=0).",
    )
    while tanggal_mulai.weekday() == 6:
        tanggal_mulai += timedelta(days=1)
        st.sidebar.warning("Digeser ke Senin (Minggu libur).")

    # Resource — dalam sidebar expander, pakai st.sidebar.number_input
    with st.sidebar.expander("🔧 Jumlah Resource per Stasiun", expanded=False):
        st.caption("Ubah jika ada kondisi khusus. Default = kondisi BAU.")
        resource_override = {}
        for st_id, nama in STASIUN.items():
            default = RESOURCE_CONFIG[st_id]["default"]
            maks    = RESOURCE_CONFIG[st_id]["max"]
            val = st.number_input(
                f"St.{st_id} – {nama}", min_value=1, max_value=maks,
                value=default, step=1, key=f"res_{st_id}",
                help=f"Default: {default}, Maks: {maks}",
            )
            if val != default:
                resource_override[st_id] = val

    # Setup time — dalam sidebar expander
    with st.sidebar.expander("⏱ Setup Time (menit/job/stasiun)", expanded=False):
        st.caption("Default 0 — kapasitas sudah memperhitungkan setup.")
        setup_time = {}
        for st_id, nama in STASIUN.items():
            val = st.number_input(
                f"St.{st_id} – {nama}", min_value=0.0, max_value=60.0,
                value=float(SETUP_TIME_DEFAULT[st_id]), step=1.0,
                key=f"setup_{st_id}",
            )
            setup_time[st_id] = val

    return tanggal_mulai, resource_override, setup_time


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    st.title("🏭 DSS Penjadwalan Produksi Job Shop")
    st.caption("Cigem Creative — Sistem Pendukung Keputusan Optimasi Jadwal Produksi")

    tanggal_mulai, resource_override, setup_time = render_sidebar()

    for key in ["hasil_optimasi"]:
        if key not in st.session_state:
            st.session_state[key] = None

    # ================================================================== #
    # STEP 1: UPLOAD
    # ================================================================== #
    st.header("1. Upload Data Pesanan")
    col_up, col_tpl = st.columns([3, 1])
    with col_up:
        uploaded_file = st.file_uploader(
            "Upload CSV atau Excel (.csv / .xlsx / .xls)",
            type=["csv", "xlsx", "xls"],
        )
    with col_tpl:
        st.markdown("**Download template:**")
        tpl_csv = generate_template().to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Template CSV", data=tpl_csv,
                           file_name="template_pesanan.csv", mime="text/csv")

    if uploaded_file is None:
        st.info("Upload file data pesanan untuk memulai.", icon="📂")
        _tampilkan_panduan()
        return

    # ================================================================== #
    # STEP 2: BACA & VALIDASI
    # ================================================================== #
    df_raw, err_baca = baca_file(uploaded_file)
    if df_raw is None:
        st.error(f"❌ Gagal membaca file: {err_baca}")
        return

    st.success(f"✓ File dibaca: {len(df_raw)} baris.")
    pesanan_semua, error_list = validasi_dan_bersihkan(df_raw, tanggal_mulai, drop_error=True)

    hard_errors = [e for e in error_list if not e["error"].startswith("⚠")]
    warnings    = [e for e in error_list if e["error"].startswith("⚠")]
    if hard_errors:
        with st.expander(f"❌ {len(hard_errors)} baris error", expanded=True):
            st.dataframe(pd.DataFrame(hard_errors), use_container_width=True, hide_index=True)
    if warnings:
        with st.expander(f"⚠ {len(warnings)} warning (atribut tidak valid diabaikan otomatis)", expanded=False):
            st.dataframe(pd.DataFrame(warnings), use_container_width=True, hide_index=True)
    if not pesanan_semua:
        st.error("Tidak ada pesanan valid.")
        return

    st.success(f"✓ {len(pesanan_semua)} pesanan valid dari file.")

    # ================================================================== #
    # STEP 3: FILTER & SELEKSI ORDER
    # ================================================================== #
    st.header("2. Pilih & Konfigurasi Order")

    # Beri setiap pesanan row_idx unik (posisi di list)
    pesanan_df = pd.DataFrame([{
        "row_idx":      i,                  # KEY UNIK — pakai ini untuk widget key
        "id_pesanan":   p["id_pesanan"],
        "jenis_produk": p["jenis_produk"].capitalize(),
        "jumlah_unit":  p["jumlah_unit"],
        "deadline":     p["deadline_tgl"],
        "bulan":        p["deadline_tgl"].month,
        "tahun":        p["deadline_tgl"].year,
        "prioritas":    p["prioritas"],
        "furing":       "Ya" if p["furing"] else "–",
        "kancing":      "Ya" if p["kancing"] else "–",
        "sablon":       "Ya" if p["sablon"] else "–",
        "dtf":          "Ya" if p["dtf"] else "–",
        "bordir":       "Ya" if p["bordir"] else "–",
    } for i, p in enumerate(pesanan_semua)])

    # --- Filter ---
    with st.expander("🔍 Filter Order", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            bulan_tersedia = sorted(pesanan_df["bulan"].unique())
            bulan_labels   = [
                f"{NAMA_BULAN[b]} {pesanan_df[pesanan_df['bulan']==b]['tahun'].iloc[0]}"
                for b in bulan_tersedia
            ]
            bulan_map = dict(zip(bulan_labels, bulan_tersedia))
            pilih_bulan_labels = st.multiselect(
                "Filter bulan deadline:", options=bulan_labels,
                default=bulan_labels[:1] if bulan_labels else [],
                key="filter_bulan",
            )
            pilih_bulan = [bulan_map[l] for l in pilih_bulan_labels]
        with col2:
            pilih_jenis = st.multiselect(
                "Filter jenis produk:",
                options=["Kaos","Polo","Kemeja","Jaket"],
                default=["Kaos","Polo","Kemeja","Jaket"],
                key="filter_jenis",
            )
        with col3:
            pilih_prio_filter = st.multiselect(
                "Filter prioritas:",
                options=["Normal","Tinggi","Kritis"],
                default=["Normal","Tinggi","Kritis"],
                key="filter_prio",
            )

    df_filtered = pesanan_df.copy()
    if pilih_bulan:
        df_filtered = df_filtered[df_filtered["bulan"].isin(pilih_bulan)]
    if pilih_jenis:
        df_filtered = df_filtered[df_filtered["jenis_produk"].isin(pilih_jenis)]
    if pilih_prio_filter:
        df_filtered = df_filtered[df_filtered["prioritas"].isin(pilih_prio_filter)]

    st.caption(f"Menampilkan **{len(df_filtered)}** order dari total {len(pesanan_semua)} order.")
    if df_filtered.empty:
        st.warning("Tidak ada order yang sesuai filter.")
        return

    # Statistik ringkasan
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("Total Order (filter)", len(df_filtered))
    col_s2.metric("Total Unit", f"{df_filtered['jumlah_unit'].sum():,}")
    col_s3.metric("Jenis Produk", df_filtered["jenis_produk"].nunique())
    col_s4.metric("Rentang Deadline",
                  f"{df_filtered['deadline'].min().strftime('%d/%m')} – "
                  f"{df_filtered['deadline'].max().strftime('%d/%m/%Y')}")

    st.divider()

    # ------------------------------------------------------------------ #
    # SELEKSI ORDER
    # Key unik = row_idx (integer posisi di list pesanan_semua)
    # Tidak terpengaruh duplikat id_pesanan maupun karakter spesial
    # ------------------------------------------------------------------ #
    st.markdown("**Pilih order yang akan dijadwalkan:**")

    # Daftar row_idx yang terfilter
    rows_filtered = df_filtered["row_idx"].tolist()

    # Inisialisasi selection — reset saat filter berubah
    filter_sig = (tuple(sorted(pilih_bulan)), tuple(sorted(pilih_jenis)), tuple(sorted(pilih_prio_filter)))
    if st.session_state.get("_filter_sig") != filter_sig:
        st.session_state["_filter_sig"]    = filter_sig
        st.session_state["selected_rows"]  = set(rows_filtered)   # default: semua terpilih
        st.session_state["prioritas_edit"] = {}

    # Tombol select/deselect all
    col_btn1, col_btn2, _ = st.columns([1, 1, 4])
    with col_btn1:
        if st.button("✅ Pilih Semua", use_container_width=True, key="btn_all"):
            st.session_state["selected_rows"] = set(rows_filtered)
            # Hapus key checkbox lama agar Streamlit baca ulang dari value=
            for k in list(st.session_state.keys()):
                if k.startswith("chk_"):
                    del st.session_state[k]
            st.rerun()
    with col_btn2:
        if st.button("❌ Hapus Semua", use_container_width=True, key="btn_none"):
            st.session_state["selected_rows"] = set()
            for k in list(st.session_state.keys()):
                if k.startswith("chk_"):
                    del st.session_state[k]
            st.rerun()

    # Tampilan tabel pakai st.data_editor — support scroll, checkbox native
    df_editor = df_filtered[["row_idx","id_pesanan","jenis_produk","jumlah_unit",
                              "deadline","prioritas","furing","kancing","sablon","dtf","bordir"]].copy()
    df_editor.insert(0, "Pilih", df_editor["row_idx"].apply(
        lambda r: r in st.session_state["selected_rows"]
    ))
    df_editor["deadline"] = df_editor["deadline"].apply(lambda d: d.strftime("%d/%m/%Y"))

    edited = st.data_editor(
        df_editor,
        column_config={
            "Pilih":       st.column_config.CheckboxColumn("✓", width="small"),
            "row_idx":     None,  # sembunyikan
            "id_pesanan":  st.column_config.TextColumn("ID Pesanan", width="large"),
            "jenis_produk":st.column_config.TextColumn("Produk", width="small"),
            "jumlah_unit": st.column_config.NumberColumn("Unit", width="small"),
            "deadline":    st.column_config.TextColumn("Deadline", width="small"),
            "prioritas":   st.column_config.SelectboxColumn(
                "Prioritas", options=["Normal","Tinggi","Kritis"], width="medium"
            ),
            "furing":      st.column_config.TextColumn("Furing", width="small"),
            "kancing":     st.column_config.TextColumn("Kancing", width="small"),
            "sablon":      st.column_config.TextColumn("Sablon", width="small"),
            "dtf":         st.column_config.TextColumn("DTF", width="small"),
            "bordir":      st.column_config.TextColumn("Bordir", width="small"),
        },
        hide_index=True,
        use_container_width=True,
        height=400,
        disabled=["id_pesanan","jenis_produk","jumlah_unit","deadline",
                  "furing","kancing","sablon","dtf","bordir"],
    )

    # Sync hasil edit kembali ke session_state
    st.session_state["selected_rows"] = set(
        int(row["row_idx"]) for _, row in edited.iterrows() if row["Pilih"]
    )
    for _, row in edited.iterrows():
        ridx = int(row["row_idx"])
        st.session_state["prioritas_edit"][ridx] = row["prioritas"]

    # Bangun pesanan_terpilih
    pesanan_terpilih = []
    for _, row in edited.iterrows():
        if row["Pilih"]:
            ridx  = int(row["row_idx"])
            p_ori = pesanan_semua[ridx]
            prio  = row["prioritas"]
            p = dict(p_ori)
            p["prioritas"] = prio
            p["bobot"]     = BOBOT_PRIORITAS.get(prio, 1)
            pesanan_terpilih.append(p)
    n_terpilih = len(pesanan_terpilih)
    total_unit = sum(p["jumlah_unit"] for p in pesanan_terpilih)

    if n_terpilih == 0:
        st.warning("Belum ada order yang dipilih.")
        return

    st.success(f"✓ **{n_terpilih} order dipilih** ({total_unit:,} unit total) siap dijadwalkan.")

    # ================================================================== #
    # STEP 4: OPTIMASI
    # ================================================================== #
    st.header("3. Jalankan Optimasi")
    st.caption(f"Mengoptimasi {n_terpilih} order | Mulai: **{tanggal_mulai.strftime('%d %B %Y')}**")

    col_opt1, col_opt2 = st.columns([3, 1])
    with col_opt2:
        skip_milp = st.checkbox(
            "⚡ Skip MILP", value=False,
            help="Lewati MILP, gunakan SA saja. Lebih cepat.",
        )
    with col_opt1:
        mulai_optimasi = st.button("🚀 Mulai Optimasi", type="primary", use_container_width=True)

    if mulai_optimasi:
        pesanan_routed = bangun_routing_semua(pesanan_terpilih)
        _jalankan_optimasi_dan_render(
            pesanan_routed, tanggal_mulai, resource_override, setup_time, skip_milp
        )
    elif st.session_state["hasil_optimasi"] is not None:
        st.info("Menampilkan hasil optimasi sebelumnya. Klik 'Mulai Optimasi' untuk memperbarui.", icon="ℹ️")
        _render_hasil(st.session_state["hasil_optimasi"])


# ---------------------------------------------------------------------------
# OPTIMASI & RENDER
# ---------------------------------------------------------------------------
def _jalankan_optimasi_dan_render(pesanan_routed, tanggal_mulai,
                                   resource_override, setup_time, skip_milp):
    progress_bar = st.progress(0, text="Memulai optimasi...")
    status_text  = st.empty()

    status_text.text("Menjalankan benchmark FCFS...")
    hasil_fcfs, fcfs_wt, _ = jalankan_fcfs(
        pesanan_routed, resource_override=resource_override or None, setup_time=setup_time,
    )
    progress_bar.progress(15, text="FCFS selesai...")

    status_text.text("Menjalankan Simulated Annealing...")
    def sa_callback(iterasi, suhu, best_wt):
        pct = 15 + int((iterasi / SA_CONFIG["n_iterasi"]) * (55 if skip_milp else 50))
        progress_bar.progress(min(pct, 70 if skip_milp else 65),
                              text=f"SA iter {iterasi:,} — WTard: {best_wt:.1f}")
    hasil_sa, sa_wt, info_sa = jalankan_sa(
        pesanan_routed, resource_override=resource_override or None,
        setup_time=setup_time, callback_progress=sa_callback,
    )

    info_milp  = {"status": "Dilewati", "objective_value": None, "waktu_komputasi_detik": 0}
    hasil_milp = None
    milp_wt    = None

    if not skip_milp:
        progress_bar.progress(65, text="SA selesai, menjalankan MILP...")
        status_text.text(f"Menjalankan MILP (batas {MILP_CONFIG['time_limit_detik']} detik)...")
        hasil_milp, milp_wt, info_milp = jalankan_milp(
            pesanan_routed, sa_urutan=info_sa.get("urutan_terbaik", []),
            resource_override=resource_override or None, setup_time=setup_time,
        )

    progress_bar.progress(95, text="Menentukan pemenang...")

    kandidat = {"SA": (hasil_sa, sa_wt)}
    if hasil_milp is not None and milp_wt is not None:
        kandidat["MILP"] = (hasil_milp, milp_wt)
    nama_pemenang = min(kandidat, key=lambda k: kandidat[k][1])
    nama_kalah    = [k for k in kandidat if k != nama_pemenang][0] if len(kandidat) > 1 else None
    hasil_pemenang, _ = kandidat[nama_pemenang]
    hasil_kalah = kandidat[nama_kalah][0] if nama_kalah else None

    progress_bar.progress(100, text="✓ Selesai!")
    status_text.empty()

    st.session_state["hasil_optimasi"] = {
        "hasil_pemenang": hasil_pemenang, "hasil_sa": hasil_sa,
        "hasil_fcfs": hasil_fcfs, "hasil_kalah": hasil_kalah,
        "pesanan_routed": pesanan_routed, "tanggal_mulai": tanggal_mulai,
        "nama_pemenang": nama_pemenang, "nama_kalah": nama_kalah,
        "info_sa": info_sa, "info_milp": info_milp,
        "resource_aktual": resource_override, "setup_time": setup_time,
    }
    _render_hasil(st.session_state["hasil_optimasi"])


def _render_hasil(data: dict):
    hp = data["hasil_pemenang"]
    hf = data["hasil_fcfs"]
    hk = data.get("hasil_kalah")
    np_ = data["nama_pemenang"]
    nk  = data.get("nama_kalah")
    tm  = data["tanggal_mulai"]

    perf_p = ringkasan_performa(hp)
    perf_f = ringkasan_performa(hf)
    perf_k = ringkasan_performa(hk) if hk else None

    st.divider()
    st.markdown("#### Perbandingan Hasil Penjadwalan")

    metode_list = [(np_, perf_p, "🥇")]
    if perf_k and nk:
        metode_list.append((nk, perf_k, "🥈"))
    metode_list.append(("FCFS", perf_f, "📋"))

    cols = st.columns(len(metode_list))
    for col, (nama, perf, icon) in zip(cols, metode_list):
        with col:
            impr_delta = None
            if nama == np_ and perf_f["total_weighted_tardiness"] > 0:
                impr = ((perf_f["total_weighted_tardiness"] - perf["total_weighted_tardiness"])
                        / perf_f["total_weighted_tardiness"] * 100)
                impr_delta = f"+{impr:.1f}% vs FCFS"
            st.markdown(f"**{icon} {nama}**")
            st.metric("Tepat Waktu",
                      f"{perf['n_tepat_waktu']}/{perf['n_job']}",
                      f"{perf['pct_tepat_waktu']}%")
            st.metric("W.Tardiness", f"{perf['total_weighted_tardiness']:,.1f}", impr_delta)

    st.divider()
    st.header("4. Hasil Optimasi")
    render_dashboard(
        hasil_pemenang=hp, hasil_sa=data["hasil_sa"], hasil_fcfs=hf,
        hasil_kalah=hk, pesanan_routed=data["pesanan_routed"],
        tanggal_mulai=tm, nama_pemenang=np_, nama_kalah=nk,
        info_sa=data["info_sa"], info_milp=data["info_milp"],
        resource_aktual=data["resource_aktual"], setup_time=data["setup_time"],
    )


# ---------------------------------------------------------------------------
# PANDUAN
# ---------------------------------------------------------------------------
def _tampilkan_panduan():
    with st.expander("📖 Panduan Penggunaan", expanded=True):
        st.markdown("""
        **Langkah penggunaan:**
        1. **Konfigurasi** di sidebar: tanggal mulai produksi (resource & setup bisa dibiarkan default)
        2. **Upload file** data pesanan (CSV/Excel)
        3. **Filter** per bulan, jenis produk, dan prioritas
        4. **Pilih order** — klik "Pilih Semua" atau centang manual, edit prioritas di kolom Prioritas
        5. Centang **Skip MILP** jika ingin hasil lebih cepat
        6. Klik **Mulai Optimasi**

        **Kolom file yang didukung:**
        | Nama standar | Alias yang diterima |
        |---|---|
        | `id_pesanan` | `id pesanan`, `order_id` |
        | `jenis_produk` | `jenis produk`, `produk` |
        | `jumlah_unit` | `qty`, `quantity` |
        | `deadline` | `due_date`, `tgl_deadline` |
        | `kancing` | `pasang kancing`, `pasang_kancing` |
        """)


if __name__ == "__main__":
    main()
