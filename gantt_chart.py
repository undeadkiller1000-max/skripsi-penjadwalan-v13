"""
ui/gantt_chart.py
=================
Gantt chart interaktif menggunakan Plotly.

Dua mode tampilan:
  Mode 1 - Per job   : setiap job punya warna berbeda, mudah dilacak
  Mode 2 - Status    : hijau = tepat waktu, merah = terlambat

Fix: x-width menggunakan milidetik (int) bukan timedelta
     agar kompatibel dengan semua versi Plotly JSON encoder.
"""

import plotly.graph_objects as go
from plotly.colors import qualitative
from datetime import datetime, date, timedelta
from calendar_utils import menit_ke_tanggal_waktu
from config import STASIUN

WARNA_TEPAT     = "#2ecc71"
WARNA_TERLAMBAT = "#e74c3c"


def _menit_ke_datetime(tanggal_mulai: date, menit: float) -> datetime:
    tgl, wkt = menit_ke_tanggal_waktu(tanggal_mulai, menit)
    jam, mnt = map(int, wkt.split(":"))
    return datetime(tgl.year, tgl.month, tgl.day, jam, mnt)


def _dt_to_ms(dt: datetime) -> int:
    """Konversi datetime ke milidetik epoch — JSON serializable."""
    epoch = datetime(1970, 1, 1)
    return int((dt - epoch).total_seconds() * 1000)


def buat_gantt(
    hasil_list: list[dict],
    tanggal_mulai: date,
    mode: str = "job",
    judul: str = "Jadwal Produksi",
) -> go.Figure:
    if not hasil_list:
        fig = go.Figure()
        fig.update_layout(title="Tidak ada data jadwal", height=300)
        return fig

    palette = qualitative.Plotly + qualitative.D3 + qualitative.G10
    job_warna = {
        h["id_pesanan"]: palette[i % len(palette)]
        for i, h in enumerate(hasil_list)
    }

    stasiun_urut = sorted(STASIUN.keys())
    y_label = {st: f"St.{st} - {STASIUN[st]}" for st in stasiun_urut}

    bars        = []
    shapes      = []
    legend_shown = set()

    for hasil in hasil_list:
        jid   = hasil["id_pesanan"]
        warna = job_warna[jid] if mode == "job" else (
            WARNA_TEPAT if not hasil["terlambat"] else WARNA_TERLAMBAT
        )

        for st, ops in hasil["schedule"].items():
            x0 = _menit_ke_datetime(tanggal_mulai, ops["start"])
            x1 = _menit_ke_datetime(tanggal_mulai, ops["end"])
            y  = y_label[st]

            # Durasi dalam milidetik (int) — JSON serializable
            durasi_ms  = _dt_to_ms(x1) - _dt_to_ms(x0)
            base_ms    = _dt_to_ms(x0)
            durasi_mnt = round(ops["end"] - ops["start"], 1)

            tooltip = (
                f"<b>{jid}</b><br>"
                f"Produk: {hasil['jenis_produk'].capitalize()} ({hasil['jumlah_unit']} unit)<br>"
                f"Stasiun: {STASIUN[st]}<br>"
                f"Mulai: {x0.strftime('%d/%m %H:%M')}<br>"
                f"Selesai: {x1.strftime('%d/%m %H:%M')}<br>"
                f"Durasi: {durasi_mnt:.1f} mnt<br>"
                f"Resource: #{ops['resource']}<br>"
                f"Prioritas: {hasil['prioritas']}<br>"
                f"Status: {'Terlambat' if hasil['terlambat'] else 'Tepat waktu'}"
            )

            show_legend = jid not in legend_shown
            if show_legend:
                legend_shown.add(jid)

            bars.append(go.Bar(
                x=[durasi_ms],
                base=[base_ms],
                y=[y],
                orientation="h",
                marker=dict(
                    color=warna, opacity=0.92,
                    line=dict(color="white", width=0.5),
                ),
                hovertemplate=tooltip + "<extra></extra>",
                name=jid,
                legendgroup=jid,
                showlegend=show_legend,
                text=jid if durasi_mnt > 30 else "",
                textposition="inside",
                textfont=dict(size=10, color="#1a1a1a", family="Arial Black"),
                insidetextanchor="middle",
            ))

        # Deadline marker
        dl_dt = _menit_ke_datetime(tanggal_mulai, hasil["deadline_mnt"])
        dl_ms = _dt_to_ms(dl_dt)
        shapes.append(dict(
            type="line",
            x0=dl_ms, x1=dl_ms,
            y0=-0.5, y1=len(stasiun_urut) - 0.5,
            line=dict(
                color=WARNA_TERLAMBAT if hasil["terlambat"] else "#95a5a6",
                width=1, dash="dot",
            ),
            opacity=0.6,
        ))

    fig = go.Figure(data=bars)

    # Tentukan range x-axis dari data aktual
    semua_start = [_dt_to_ms(_menit_ke_datetime(tanggal_mulai, ops["start"]))
                   for h in hasil_list for ops in h["schedule"].values()]
    semua_end   = [_dt_to_ms(_menit_ke_datetime(tanggal_mulai, ops["end"]))
                   for h in hasil_list for ops in h["schedule"].values()]
    x_min = min(semua_start) - 3_600_000        # -1 jam padding
    x_max = max(semua_end)   + 3_600_000 * 2    # +2 jam padding

    # Buat tick label manual (setiap hari kerja)
    tick_vals, tick_texts = _buat_ticks(tanggal_mulai, hasil_list)

    fig.update_layout(
        title=dict(text=judul, font=dict(size=14)),
        barmode="overlay",
        height=max(450, len(stasiun_urut) * 58 + 120),
        xaxis=dict(
            title="Waktu",
            range=[x_min, x_max],
            tickvals=tick_vals,
            ticktext=tick_texts,
            tickangle=-35,
            showgrid=True,
            gridcolor="#313244",
            tickfont=dict(size=10, color="#cdd6f4"),
            titlefont=dict(color="#cdd6f4"),
        ),
        yaxis=dict(
            title="Stasiun Kerja",
            categoryorder="array",
            categoryarray=list(reversed([y_label[st] for st in stasiun_urut])),
            showgrid=True,
            gridcolor="#313244",
            tickfont=dict(color="#cdd6f4"),
            titlefont=dict(color="#cdd6f4"),
        ),
        shapes=shapes,
        legend=dict(
            title="Pesanan", orientation="v",
            x=1.01, y=1, xanchor="left",
            font=dict(size=9, color="#cdd6f4"),
            bgcolor="#313244",
            bordercolor="#45475a",
            borderwidth=1,
            tracegroupgap=2,
        ),
        margin=dict(l=185, r=170, t=60, b=90),
        plot_bgcolor="#1e1e2e",
        paper_bgcolor="#1e1e2e",
        font=dict(color="#cdd6f4"),
        hoverlabel=dict(bgcolor="#313244", font_size=12, font_color="#cdd6f4"),
    )

    _tambah_blok_minggu(fig, tanggal_mulai, hasil_list)
    return fig


# ---------------------------------------------------------------------------
# HELPER: TICK LABELS
# ---------------------------------------------------------------------------

def _buat_ticks(tanggal_mulai: date, hasil_list: list[dict]):
    """Buat tick setiap hari kerja jam 08:30 dan 13:00."""
    if not hasil_list:
        return [], []

    semua_end_mnt = [ops["end"] for h in hasil_list for ops in h["schedule"].values()]
    tgl_akhir, _  = menit_ke_tanggal_waktu(tanggal_mulai, max(semua_end_mnt))
    tgl_akhir    += timedelta(days=2)

    tick_vals  = []
    tick_texts = []
    current = tanggal_mulai

    while current <= tgl_akhir:
        if current.weekday() != 6:  # bukan Minggu
            # Tick pagi: 08:30
            dt_pagi = datetime(current.year, current.month, current.day, 8, 30)
            tick_vals.append(_dt_to_ms(dt_pagi))
            tick_texts.append(current.strftime("%d/%m"))
        current += timedelta(days=1)

    return tick_vals, tick_texts


# ---------------------------------------------------------------------------
# HELPER: BLOK MINGGU
# ---------------------------------------------------------------------------

def _tambah_blok_minggu(fig, tanggal_mulai, hasil_list):
    if not hasil_list:
        return
    semua_end = [ops["end"] for h in hasil_list for ops in h["schedule"].values()]
    if not semua_end:
        return
    tgl_akhir, _ = menit_ke_tanggal_waktu(tanggal_mulai, max(semua_end))
    tgl_akhir   += timedelta(days=2)

    current = tanggal_mulai
    while current <= tgl_akhir:
        if current.weekday() == 6:
            x0_ms = _dt_to_ms(datetime(current.year, current.month, current.day, 0, 0))
            x1_ms = _dt_to_ms(datetime(current.year, current.month, current.day, 23, 59))
            fig.add_vrect(
                x0=x0_ms, x1=x1_ms,
                fillcolor="gray", opacity=0.08,
                layer="below", line_width=0,
                annotation_text="Minggu",
                annotation_position="top left",
                annotation_font_size=9,
                annotation_font_color="gray",
            )
        current += timedelta(days=1)
