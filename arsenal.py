"""
arsenal.py — Ball Arsenal window for Bowling Tracker.

Opened via show_arsenal(window, connection, cursor, design_tokens).
Tracks every ball the user owns, stores metadata, and computes live
stats from the games table wherever ball names match.
"""

import csv
import json
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_balls_table(cursor, connection):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS balls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            brand           TEXT,
            weight          REAL,
            cover_stock     TEXT,
            surface         TEXT,
            date_purchased  TEXT,
            notes           TEXT
        )
    """)
    connection.commit()


# ── USBC approved ball list (reference data, searchable) ───────────────────────

def _app_folder():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_approved_balls_table(cursor, connection):
    """Create the approved_balls reference table and populate it from the
    bundled USBC CSV export the first time it's empty. Safe to call every
    time the Arsenal window opens — it's a no-op once populated.

    Returns a status string: "ok", "missing_csv", or an error message —
    so the caller can surface it instead of failing silently."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_balls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            brand           TEXT NOT NULL,
            ball_name       TEXT NOT NULL,
            date_approved   TEXT,
            UNIQUE(brand, ball_name)
        )
    """)
    connection.commit()

    cursor.execute("SELECT COUNT(*) FROM approved_balls")
    if cursor.fetchone()[0] > 0:
        return "ok"

    csv_path = os.path.join(_app_folder(), "usbc_approved_balls.csv")
    if not os.path.isfile(csv_path):
        return f"missing_csv:{csv_path}"

    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = [
                (row["brand"].strip(), row["ball_name"].strip(), row.get("date_approved", "").strip())
                for row in reader
                if row.get("brand") and row.get("ball_name")
            ]
        if not rows:
            return f"empty_csv:{csv_path}"
        cursor.executemany(
            "INSERT OR IGNORE INTO approved_balls (brand, ball_name, date_approved) VALUES (?, ?, ?)",
            rows
        )
        connection.commit()
        cursor.execute("SELECT COUNT(*) FROM approved_balls")
        if cursor.fetchone()[0] == 0:
            return f"import_failed:{csv_path}"
        return "ok"
    except Exception as e:
        connection.rollback()
        return f"error:{e}"


def _search_approved_balls(cursor, query, limit=200):
    """Search brand + ball name for a substring match (case-insensitive)."""
    query = (query or "").strip()
    if not query:
        cursor.execute(
            "SELECT brand, ball_name, date_approved FROM approved_balls "
            "ORDER BY brand, ball_name LIMIT ?", (limit,)
        )
        return cursor.fetchall()

    like = f"%{query}%"
    cursor.execute(
        "SELECT brand, ball_name, date_approved FROM approved_balls "
        "WHERE brand LIKE ? OR ball_name LIKE ? "
        "ORDER BY brand, ball_name LIMIT ?",
        (like, like, limit)
    )
    return cursor.fetchall()


def _parse_frames(frame_data):
    if not frame_data:
        return None
    try:
        return json.loads(frame_data)
    except (TypeError, json.JSONDecodeError):
        return None


def _count_strikes_and_misses(frames):
    """Return (strike_frames, first_throw_misses, total_frames_counted)
    from a list of frame dicts."""
    strikes = 0
    misses = 0
    total = 0
    for i, frame in enumerate(frames[:10]):
        throws = frame.get("throws", [])
        if not throws:
            continue
        total += 1
        first = throws[0].strip().upper()
        if first == "X":
            strikes += 1
        elif first in ("-", "0"):
            misses += 1
    return strikes, misses, total


# ── Ball stats (computed live from games table) ───────────────────────────────

def _compute_ball_stats(ball_name, cursor):
    """Return a dict of stats for ball_name, or None if no games recorded.
    Never raises — any bad/unexpected row data is skipped rather than
    crashing the whole detail panel."""
    try:
        # Case/whitespace-tolerant match: games logged before the Ball
        # dropdown existed may have slightly different capitalization or
        # stray spaces compared to the Arsenal entry's exact name.
        cursor.execute(
            "SELECT score, frames FROM games "
            "WHERE ball IS NOT NULL AND TRIM(LOWER(ball)) = TRIM(LOWER(?))",
            (ball_name,)
        )
        rows = cursor.fetchall()
    except Exception:
        return None

    if not rows:
        return None

    # Filter out any row whose score isn't a usable number instead of
    # letting one bad/legacy row crash the whole stats panel.
    scores = []
    frame_rows = []
    for score, frame_data in rows:
        try:
            scores.append(int(score))
            frame_rows.append(frame_data)
        except (TypeError, ValueError):
            continue

    if not scores:
        return None

    games = len(scores)
    avg = sum(scores) / games
    high = max(scores)
    # Total pins: sum of all scores (each score already represents pins knocked
    # down across 10 frames in standard scoring, which is the conventional
    # "total pins" metric used by bowling centers and apps).
    total_pins = sum(scores)

    # Frame-level stats
    total_strike_frames = 0
    total_miss_frames = 0
    total_frames = 0
    games_with_frames = 0

    for frame_data in frame_rows:
        frames = _parse_frames(frame_data)
        if frames is None:
            continue
        games_with_frames += 1
        try:
            s, m, t = _count_strikes_and_misses(frames)
        except (AttributeError, TypeError):
            # Malformed frame JSON (e.g. from an older import format) —
            # skip its frame-level contribution rather than crashing.
            continue
        total_strike_frames += s
        total_miss_frames += m
        total_frames += t

    result = {
        "games": games,
        "avg": avg,
        "high": high,
        "total_pins": total_pins,
        "games_with_frames": games_with_frames,
        "total_frames": total_frames,
        "strike_frames": total_strike_frames,
        "miss_frames": total_miss_frames,
    }
    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def show_arsenal(parent_window, connection, cursor, tokens):
    """Open the Arsenal window. tokens is a dict of design constants."""

    _ensure_balls_table(cursor, connection)
    approved_balls_status = _ensure_approved_balls_table(cursor, connection)

    # Unpack tokens
    NAVY      = tokens["NAVY"]
    NAVY_MID  = tokens["NAVY_MID"]
    AMBER     = tokens["AMBER"]
    WHITE     = tokens["WHITE"]
    OFFWHITE  = tokens["OFFWHITE"]
    CARD_BG   = tokens["CARD_BG"]
    BORDER    = tokens["BORDER"]
    TEXT      = tokens["TEXT"]
    TEXT_MUTED = tokens["TEXT_MUTED"]
    RED       = tokens["RED"]
    GREEN     = tokens["GREEN"]
    ENTRY_BG  = tokens["ENTRY_BG"]
    FONT_BODY = tokens["FONT_BODY"]
    FONT_MONO = tokens["FONT_MONO"]

    # ── Window ────────────────────────────────────────────────────────────────
    win = tk.Toplevel(parent_window)
    win.title("Ball Arsenal")
    win.configure(bg=OFFWHITE)
    win.resizable(True, True)
    win.transient(parent_window)
    win.geometry("980x680")
    win.minsize(800, 520)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(win, bg=NAVY, height=64)
    hdr.pack(fill=tk.X)
    hdr.pack_propagate(False)

    tk.Label(hdr, text="🎳", font=("Arial", 22),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=(20, 8), pady=12)
    title_stack = tk.Frame(hdr, bg=NAVY)
    title_stack.pack(side=tk.LEFT)
    tk.Label(title_stack, text="BALL ARSENAL",
             font=(FONT_BODY, 13, "bold"), bg=NAVY, fg=AMBER).pack(anchor="w")
    tk.Label(title_stack, text="YOUR EQUIPMENT LOCKER",
             font=(FONT_BODY, 8), bg=NAVY, fg="#5B7FA6").pack(anchor="w")

    # ── Body: left roster + right detail ─────────────────────────────────────
    body = tk.Frame(win, bg=OFFWHITE)
    body.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(0, weight=1)

    # ── LEFT: ball roster ─────────────────────────────────────────────────────
    left = tk.Frame(body, bg=CARD_BG,
                    highlightthickness=1, highlightbackground=BORDER,
                    width=220)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
    left.pack_propagate(False)

    tk.Label(left, text="MY BALLS", font=(FONT_BODY, 9, "bold"),
             bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w", padx=12, pady=(10, 4))

    roster_frame = tk.Frame(left, bg=CARD_BG)
    roster_frame.pack(fill=tk.BOTH, expand=True, padx=4)

    roster_scroll = tk.Scrollbar(roster_frame, orient=tk.VERTICAL)
    roster_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    roster = tk.Listbox(
        roster_frame,
        font=(FONT_BODY, 12),
        yscrollcommand=roster_scroll.set,
        selectbackground=NAVY,
        selectforeground=AMBER,
        activestyle="none",
        bg=CARD_BG, fg=TEXT,
        relief="flat", borderwidth=0,
        highlightthickness=0,
    )
    roster.pack(fill=tk.BOTH, expand=True)
    roster_scroll.config(command=roster.yview)

    # Small buttons below roster
    roster_btn_row = tk.Frame(left, bg=CARD_BG)
    roster_btn_row.pack(fill=tk.X, padx=8, pady=8)

    # ── RIGHT: detail panel ───────────────────────────────────────────────────
    right = tk.Frame(body, bg=OFFWHITE)
    right.grid(row=0, column=1, sticky="nsew")

    # Placeholder shown when nothing is selected
    placeholder = tk.Frame(right, bg=CARD_BG,
                           highlightthickness=1, highlightbackground=BORDER)
    placeholder.pack(fill=tk.BOTH, expand=True)
    tk.Label(placeholder, text="⬅  Select a ball to see its stats",
             font=(FONT_BODY, 13), bg=CARD_BG, fg=TEXT_MUTED).pack(expand=True)

    detail_frame = None   # will be built on selection

    # Internal state
    ball_ids = []         # parallel to roster listbox rows

    # ── Roster loader ─────────────────────────────────────────────────────────
    def load_roster(select_id=None):
        nonlocal ball_ids
        roster.delete(0, tk.END)
        ball_ids.clear()
        try:
            cursor.execute("SELECT id, name, weight FROM balls ORDER BY name")
            rows = cursor.fetchall()
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=win)
            return
        for ball_id, name, weight in rows:
            label = name
            if weight:
                label += f"  ({weight}lb)"
            roster.insert(tk.END, f"  {label}")
            ball_ids.append(ball_id)

        if select_id is not None:
            for i, bid in enumerate(ball_ids):
                if bid == select_id:
                    roster.selection_set(i)
                    roster.see(i)
                    show_detail(bid)
                    return
        if ball_ids:
            roster.selection_set(0)
            show_detail(ball_ids[0])
        else:
            show_placeholder()

    def show_placeholder():
        nonlocal detail_frame
        if detail_frame:
            detail_frame.destroy()
            detail_frame = None
        placeholder.pack(fill=tk.BOTH, expand=True)

    # ── Detail panel builder ──────────────────────────────────────────────────
    def show_detail(ball_id):
        nonlocal detail_frame
        placeholder.pack_forget()
        if detail_frame:
            detail_frame.destroy()

        try:
            cursor.execute(
                "SELECT name, brand, weight, cover_stock, surface, date_purchased, notes "
                "FROM balls WHERE id = ?", (ball_id,)
            )
            row = cursor.fetchone()
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=win)
            return

        if not row:
            show_placeholder()
            return

        name, brand, weight, cover_stock, surface, date_purchased, notes = row

        detail_frame = tk.Frame(right, bg=OFFWHITE)
        detail_frame.pack(fill=tk.BOTH, expand=True)

        # ── Ball name header ──
        name_hdr = tk.Frame(detail_frame, bg=NAVY, pady=12)
        name_hdr.pack(fill=tk.X)
        tk.Label(name_hdr, text=name,
                 font=(FONT_BODY, 18, "bold"), bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=18)
        if brand:
            tk.Label(name_hdr, text=brand,
                     font=(FONT_BODY, 12), bg=NAVY, fg=AMBER).pack(side=tk.LEFT)

        # ── Scrollable detail body ──
        canvas_outer = tk.Canvas(detail_frame, bg=OFFWHITE, highlightthickness=0)
        detail_scroll = tk.Scrollbar(detail_frame, orient=tk.VERTICAL,
                                     command=canvas_outer.yview)
        canvas_outer.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_outer.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas_outer, bg=OFFWHITE)
        canvas_win = canvas_outer.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(event):
            canvas_outer.configure(scrollregion=canvas_outer.bbox("all"))

        def on_canvas_configure(event):
            canvas_outer.itemconfig(canvas_win, width=event.width)

        inner.bind("<Configure>", on_inner_configure)
        canvas_outer.bind("<Configure>", on_canvas_configure)

        pad = dict(padx=18, pady=0)

        # ── Equipment info card ──
        def section_label(text):
            tk.Label(inner, text=text, font=(FONT_BODY, 9, "bold"),
                     bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", padx=18, pady=(18, 6))

        def info_row(label, value):
            if not value:
                return
            row_f = tk.Frame(info_card, bg=CARD_BG)
            row_f.pack(fill=tk.X, padx=14, pady=3)
            tk.Label(row_f, text=label, font=(FONT_BODY, 10, "bold"),
                     bg=CARD_BG, fg=TEXT_MUTED, width=16, anchor="w").pack(side=tk.LEFT)
            tk.Label(row_f, text=str(value), font=(FONT_BODY, 11),
                     bg=CARD_BG, fg=TEXT, anchor="w").pack(side=tk.LEFT)

        section_label("EQUIPMENT INFO")
        info_card = tk.Frame(inner, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        info_card.pack(fill=tk.X, **pad)
        tk.Frame(info_card, bg=CARD_BG, height=8).pack()   # top padding

        weight_str = f"{weight} lb" if weight else None
        info_row("Weight", weight_str)
        info_row("Cover stock", cover_stock)
        info_row("Surface", surface)
        info_row("Purchased", date_purchased)
        if notes:
            notes_row = tk.Frame(info_card, bg=CARD_BG)
            notes_row.pack(fill=tk.X, padx=14, pady=(3, 10))
            tk.Label(notes_row, text="Notes", font=(FONT_BODY, 10, "bold"),
                     bg=CARD_BG, fg=TEXT_MUTED, width=16, anchor="nw").pack(side=tk.LEFT)
            tk.Label(notes_row, text=notes, font=(FONT_BODY, 11),
                     bg=CARD_BG, fg=TEXT, anchor="nw",
                     wraplength=380, justify=tk.LEFT).pack(side=tk.LEFT)
        tk.Frame(info_card, bg=CARD_BG, height=8).pack()   # bottom padding

        # ── Performance stats (live from games table) ──
        section_label("PERFORMANCE STATS")

        try:
            stats = _compute_ball_stats(name, cursor)
        except Exception as e:
            stats = "error"

        if stats == "error":
            err_card = tk.Frame(inner, bg=CARD_BG,
                                highlightthickness=1, highlightbackground=BORDER)
            err_card.pack(fill=tk.X, **pad)
            tk.Label(err_card,
                     text="Couldn't load stats for this ball. Try again, "
                          "and let me know if this keeps happening.",
                     font=(FONT_BODY, 10), bg=CARD_BG, fg=RED,
                     justify=tk.LEFT, wraplength=440).pack(padx=14, pady=14, anchor="w")
        elif stats is None:
            no_stats = tk.Frame(inner, bg=CARD_BG,
                                highlightthickness=1, highlightbackground=BORDER)
            no_stats.pack(fill=tk.X, **pad)
            tk.Label(no_stats,
                     text="No games recorded with this ball yet.\n"
                          "Add games and set the Ball field to see stats here.",
                     font=(FONT_BODY, 10), bg=CARD_BG, fg=TEXT_MUTED,
                     justify=tk.LEFT).pack(padx=14, pady=14, anchor="w")
        else:
            # ── Top stat tiles ──
            tiles_frame = tk.Frame(inner, bg=OFFWHITE)
            tiles_frame.pack(fill=tk.X, **pad)

            def stat_tile(parent, label, value, sub=None, highlight=False):
                card = tk.Frame(parent,
                                bg=NAVY if highlight else CARD_BG,
                                highlightthickness=1, highlightbackground=BORDER,
                                padx=18, pady=14)
                card.pack(side=tk.LEFT, padx=(0, 10))
                tk.Label(card, text=str(value),
                         font=(FONT_BODY, 28, "bold"),
                         bg=NAVY if highlight else CARD_BG,
                         fg=AMBER if highlight else TEXT).pack()
                tk.Label(card, text=label,
                         font=(FONT_BODY, 9, "bold"),
                         bg=NAVY if highlight else CARD_BG,
                         fg="#5B7FA6" if highlight else TEXT_MUTED).pack()
                if sub:
                    tk.Label(card, text=sub,
                             font=(FONT_BODY, 8),
                             bg=NAVY if highlight else CARD_BG,
                             fg="#5B7FA6" if highlight else TEXT_MUTED).pack()

            stat_tile(tiles_frame, "TOTAL PINS", f"{stats['total_pins']:,}", highlight=True)
            stat_tile(tiles_frame, "GAMES", stats["games"])
            stat_tile(tiles_frame, "AVG SCORE", f"{stats['avg']:.1f}")
            stat_tile(tiles_frame, "HIGH GAME", stats["high"])

            # ── Frame-level stats (only if frame data exists) ──
            if stats["games_with_frames"] > 0 and stats["total_frames"] > 0:
                section_label(
                    f"FRAME STATS  "
                    f"({stats['games_with_frames']} of {stats['games']} games have frame data)"
                )

                pct_row = tk.Frame(inner, bg=OFFWHITE)
                pct_row.pack(fill=tk.X, **pad)

                def pct_tile(parent, label, numerator, denominator, color, note=None):
                    pct = (numerator / denominator * 100) if denominator else 0
                    card = tk.Frame(parent, bg=CARD_BG,
                                   highlightthickness=1, highlightbackground=BORDER,
                                   padx=20, pady=14)
                    card.pack(side=tk.LEFT, padx=(0, 10))
                    tk.Label(card, text=f"{pct:.1f}%",
                             font=(FONT_BODY, 26, "bold"),
                             bg=CARD_BG, fg=color).pack()
                    tk.Label(card, text=label,
                             font=(FONT_BODY, 9, "bold"),
                             bg=CARD_BG, fg=TEXT_MUTED).pack()
                    tk.Label(card, text=f"{numerator} / {denominator} frames",
                             font=(FONT_BODY, 8),
                             bg=CARD_BG, fg=TEXT_MUTED).pack()
                    if note:
                        tk.Label(card, text=note,
                                 font=(FONT_BODY, 7),
                                 bg=CARD_BG, fg=TEXT_MUTED).pack()

                tf = stats["total_frames"]
                pct_tile(pct_row, "STRIKE RATE",
                         stats["strike_frames"], tf, AMBER)

                spare_opps = tf - stats["strike_frames"]
                pct_tile(pct_row, "FIRST-THROW MISS RATE",
                         stats["miss_frames"], tf, RED,
                         note="(gutter ball or no pins on 1st ball)")

            # ── Score mini-chart (sparkline) ──
            try:
                cursor.execute(
                    "SELECT date, score FROM games "
                    "WHERE ball IS NOT NULL AND TRIM(LOWER(ball)) = TRIM(LOWER(?)) "
                    "ORDER BY date",
                    (name,)
                )
                raw_score_rows = cursor.fetchall()
                score_rows = []
                for d, s in raw_score_rows:
                    try:
                        score_rows.append((d, int(s)))
                    except (TypeError, ValueError):
                        continue
            except Exception:
                score_rows = []

            if len(score_rows) >= 2:
                section_label("SCORE TREND WITH THIS BALL")

                CHART_W, CHART_H = 580, 140
                PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 14, 28

                chart_card = tk.Frame(inner, bg=CARD_BG,
                                      highlightthickness=1, highlightbackground=BORDER)
                chart_card.pack(fill=tk.X, padx=18, pady=(0, 4))

                chart_canvas = tk.Canvas(chart_card, width=CHART_W, height=CHART_H,
                                         bg=CARD_BG, highlightthickness=0)
                chart_canvas.pack()

                plot = [r[1] for r in score_rows]
                dates = [r[0] for r in score_rows]
                n = len(plot)
                lo, hi = min(plot), max(plot)
                rng = hi - lo if hi != lo else 1
                ball_avg = sum(plot) / n

                def sx(i):
                    return PAD_L + (i / max(n - 1, 1)) * (CHART_W - PAD_L - PAD_R)

                def sy(s):
                    return PAD_T + (1 - (s - lo) / rng) * (CHART_H - PAD_T - PAD_B)

                for val in [lo, (lo + hi) // 2, hi]:
                    y = sy(val)
                    chart_canvas.create_line(PAD_L, y, CHART_W - PAD_R, y,
                                             fill=BORDER, dash=(4, 4))
                    chart_canvas.create_text(PAD_L - 6, y, text=str(val),
                                             font=(FONT_BODY, 7), fill=TEXT_MUTED, anchor="e")

                avg_y = sy(ball_avg)
                chart_canvas.create_line(PAD_L, avg_y, CHART_W - PAD_R, avg_y,
                                         fill=AMBER, dash=(6, 3), width=1)

                pts = [(sx(i), sy(s)) for i, s in enumerate(plot)]
                flat = [c for pt in pts for c in pt]
                chart_canvas.create_line(*flat, fill=NAVY, width=2, smooth=True)

                tooltip = tk.Label(chart_card, font=(FONT_BODY, 9, "bold"),
                                   bg=NAVY, fg=WHITE, padx=6, pady=3)

                for i, (score_val, date_str) in enumerate(zip(plot, dates)):
                    x, y = sx(i), sy(score_val)
                    color = GREEN if score_val >= ball_avg else RED
                    dot = chart_canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                                                   fill=color, outline=CARD_BG, width=1)
                    def _enter(e, _x=x, _y=y, _s=score_val, _d=date_str):
                        tooltip.config(text=f"{_s}  {_d}")
                        tooltip.place(x=min(_x + 8, CHART_W - 80), y=max(_y - 22, 4))
                    def _leave(e):
                        tooltip.place_forget()
                    chart_canvas.tag_bind(dot, "<Enter>", _enter)
                    chart_canvas.tag_bind(dot, "<Leave>", _leave)

                # X labels: first + last
                for i in [0, n - 1]:
                    chart_canvas.create_text(sx(i), CHART_H - PAD_B + 10,
                                             text=dates[i],
                                             font=(FONT_BODY, 7), fill=TEXT_MUTED)

        # ── Edit / Delete buttons at the bottom of detail ──
        action_strip = tk.Frame(inner, bg=OFFWHITE)
        action_strip.pack(anchor="w", padx=18, pady=(20, 16))

        def _btn(parent, text, cmd, primary=False, danger=False):
            if primary:
                bg, fg, abg = AMBER, NAVY, "#D97706"
            elif danger:
                bg, fg, abg = "#DC2626", WHITE, "#B91C1C"
            else:
                bg, fg, abg = "#E2EAF3", TEXT, "#C7D5E8"
            b = tk.Button(parent, text=text, command=cmd,
                          font=(FONT_BODY, 11, "bold"),
                          bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                          relief="flat", cursor="hand2", padx=16, pady=7, borderwidth=0)
            return b

        _btn(action_strip, "✏  Edit Ball", lambda: open_edit_dialog(ball_id)).pack(side=tk.LEFT, padx=(0, 8))
        _btn(action_strip, "🗑  Delete Ball", lambda: delete_ball(ball_id), danger=True).pack(side=tk.LEFT)

    # ── Roster click handler ──────────────────────────────────────────────────
    def on_roster_select(event):
        sel = roster.curselection()
        if not sel:
            return
        show_detail(ball_ids[sel[0]])

    roster.bind("<<ListboxSelect>>", on_roster_select)

    # ── Add ball dialog ───────────────────────────────────────────────────────
    def open_add_dialog():
        _open_ball_form(win, None)

    def open_edit_dialog(ball_id):
        _open_ball_form(win, ball_id)

    def _open_ball_form(parent, ball_id, prefill=None):
        """Shared add/edit form. ball_id=None means add.
        prefill (add-mode only) pre-populates fields, e.g. from a USBC pick."""
        is_edit = ball_id is not None
        existing = dict(prefill) if prefill else {}
        if is_edit:
            try:
                cursor.execute(
                    "SELECT name, brand, weight, cover_stock, surface, date_purchased, notes "
                    "FROM balls WHERE id = ?", (ball_id,)
                )
                row = cursor.fetchone()
                if row:
                    keys = ["name", "brand", "weight", "cover_stock",
                            "surface", "date_purchased", "notes"]
                    existing = dict(zip(keys, row))
            except Exception as e:
                messagebox.showerror("Database Error", str(e), parent=parent)
                return

        dlg = tk.Toplevel(parent)
        dlg.title("Edit Ball" if is_edit else "Add Ball")
        dlg.resizable(False, False)
        dlg.transient(parent)
        dlg.grab_set()
        dlg.configure(bg=OFFWHITE)

        hdr_dlg = tk.Frame(dlg, bg=NAVY, height=48)
        hdr_dlg.pack(fill=tk.X)
        tk.Label(hdr_dlg,
                 text="Edit Ball" if is_edit else "Add Ball to Arsenal",
                 font=(FONT_BODY, 14, "bold"), bg=NAVY, fg=WHITE).pack(
                     side=tk.LEFT, padx=20, pady=12)

        body_dlg = tk.Frame(dlg, bg=OFFWHITE, padx=28, pady=18)
        body_dlg.pack(fill=tk.BOTH)

        entries = {}

        FIELDS = [
            ("name",          "Ball Name *",    14, False),
            ("brand",         "Brand",          16, False),
            ("weight",        "Weight (lb)",     6, False),
            ("cover_stock",   "Cover Stock",    16, False),
            ("surface",       "Surface Finish", 18, False),
            ("date_purchased","Date Purchased", 14, False),
        ]

        for key, label, width, _ in FIELDS:
            tk.Label(body_dlg, text=label, font=(FONT_BODY, 10, "bold"),
                     bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(10, 2))
            e = tk.Entry(body_dlg, font=(FONT_BODY, 13), width=width,
                         bg=ENTRY_BG, relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=AMBER)
            e.pack(anchor="w", ipady=5, ipadx=4)
            val = existing.get(key)
            if val is not None:
                e.insert(0, str(val))
            entries[key] = e

        tk.Label(body_dlg, text="Notes", font=(FONT_BODY, 10, "bold"),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(10, 2))
        notes_text = tk.Text(body_dlg, font=(FONT_BODY, 12), width=34, height=4,
                             bg=ENTRY_BG, relief="flat",
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=AMBER)
        notes_text.pack(anchor="w", ipadx=4)
        if existing.get("notes"):
            notes_text.insert("1.0", existing["notes"])

        def save():
            name_val = entries["name"].get().strip()
            if not name_val:
                messagebox.showwarning("Missing Name",
                                       "Please enter a name for the ball.", parent=dlg)
                return
            weight_raw = entries["weight"].get().strip()
            weight_val = None
            if weight_raw:
                try:
                    weight_val = float(weight_raw)
                    if weight_val <= 0 or weight_val > 16:
                        raise ValueError
                except ValueError:
                    messagebox.showwarning("Invalid Weight",
                                           "Weight must be a number between 1 and 16.",
                                           parent=dlg)
                    return

            notes_val = notes_text.get("1.0", tk.END).strip() or None

            try:
                if is_edit:
                    cursor.execute(
                        """UPDATE balls SET name=?, brand=?, weight=?, cover_stock=?,
                           surface=?, date_purchased=?, notes=? WHERE id=?""",
                        (name_val,
                         entries["brand"].get().strip() or None,
                         weight_val,
                         entries["cover_stock"].get().strip() or None,
                         entries["surface"].get().strip() or None,
                         entries["date_purchased"].get().strip() or None,
                         notes_val,
                         ball_id)
                    )
                else:
                    cursor.execute(
                        """INSERT INTO balls (name, brand, weight, cover_stock,
                           surface, date_purchased, notes) VALUES (?,?,?,?,?,?,?)""",
                        (name_val,
                         entries["brand"].get().strip() or None,
                         weight_val,
                         entries["cover_stock"].get().strip() or None,
                         entries["surface"].get().strip() or None,
                         entries["date_purchased"].get().strip() or None,
                         notes_val)
                    )
                connection.commit()
            except Exception as e:
                messagebox.showerror("Database Error", str(e), parent=dlg)
                return

            saved_id = ball_id if is_edit else cursor.lastrowid
            dlg.destroy()
            load_roster(select_id=saved_id)

        btn_row_dlg = tk.Frame(body_dlg, bg=OFFWHITE)
        btn_row_dlg.pack(pady=(18, 4))

        def _dlg_btn(parent, text, cmd, primary=False):
            if primary:
                bg, fg, abg = AMBER, NAVY, "#D97706"
            else:
                bg, fg, abg = "#E2EAF3", TEXT, "#C7D5E8"
            b = tk.Button(parent, text=text, command=cmd,
                          font=(FONT_BODY, 11, "bold"),
                          bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                          relief="flat", cursor="hand2", padx=16, pady=7, borderwidth=0)
            return b

        _dlg_btn(btn_row_dlg, "Save", save, primary=True).pack(side=tk.LEFT, padx=(0, 8))
        _dlg_btn(btn_row_dlg, "Cancel", dlg.destroy).pack(side=tk.LEFT)

        dlg.update_idletasks()
        dlg.geometry(f"{dlg.winfo_reqwidth()}x{dlg.winfo_reqheight()}")

    # ── Delete ball ───────────────────────────────────────────────────────────
    def delete_ball(ball_id):
        try:
            cursor.execute("SELECT name FROM balls WHERE id = ?", (ball_id,))
            row = cursor.fetchone()
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=win)
            return
        if not row:
            load_roster()
            return
        name = row[0]
        if not messagebox.askyesno(
            "Delete Ball",
            f"Remove \"{name}\" from your arsenal?\n\n"
            "This does not delete any games — the ball name in those games will be kept.\n\n"
            "This can't be undone.",
            parent=win
        ):
            return
        try:
            cursor.execute("DELETE FROM balls WHERE id = ?", (ball_id,))
            connection.commit()
        except Exception as e:
            messagebox.showerror("Database Error", str(e), parent=win)
            return
        load_roster()

    # ── USBC approved-ball picker ────────────────────────────────────────────
    def open_usbc_picker():
        pick = tk.Toplevel(win)
        pick.title("USBC Approved Ball List")
        pick.configure(bg=OFFWHITE)
        pick.resizable(True, True)
        pick.transient(win)
        pick.grab_set()
        pick.geometry("560x520")
        pick.minsize(440, 360)

        hdr_pick = tk.Frame(pick, bg=NAVY, height=48)
        hdr_pick.pack(fill=tk.X)
        tk.Label(hdr_pick, text="Search USBC Approved Balls",
                 font=(FONT_BODY, 13, "bold"), bg=NAVY, fg=WHITE).pack(
                     side=tk.LEFT, padx=18, pady=12)

        body_pick = tk.Frame(pick, bg=OFFWHITE, padx=16, pady=12)
        body_pick.pack(fill=tk.BOTH, expand=True)

        search_row = tk.Frame(body_pick, bg=OFFWHITE)
        search_row.pack(fill=tk.X)
        tk.Label(search_row, text="Search", font=(FONT_BODY, 10, "bold"),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w")
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_row, textvariable=search_var,
                                font=(FONT_BODY, 13), bg=ENTRY_BG, relief="flat",
                                highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=AMBER)
        search_entry.pack(fill=tk.X, ipady=6, ipadx=4, pady=(2, 8))
        search_entry.focus_set()

        count_label = tk.Label(body_pick, text="", font=(FONT_BODY, 9),
                               bg=OFFWHITE, fg=TEXT_MUTED)
        count_label.pack(anchor="w", pady=(0, 4))

        if approved_balls_status != "ok":
            kind = approved_balls_status.split(":", 1)[0]
            detail = approved_balls_status.split(":", 1)[1] if ":" in approved_balls_status else ""
            if kind == "missing_csv":
                msg = f"Couldn't find usbc_approved_balls.csv.\nExpected it at:\n{detail}\n\nPut the CSV in that folder and reopen the Arsenal window."
            elif kind == "empty_csv":
                msg = f"usbc_approved_balls.csv was found but has no rows:\n{detail}"
            elif kind == "import_failed":
                msg = f"Found the CSV but nothing imported from it:\n{detail}"
            else:
                msg = f"Couldn't load the USBC ball list:\n{approved_balls_status}"
            tk.Label(body_pick, text=msg, font=(FONT_BODY, 10),
                     bg=OFFWHITE, fg=RED, justify="left", wraplength=500).pack(
                         anchor="w", pady=(0, 10))

        list_wrap = tk.Frame(body_pick, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        list_wrap.pack(fill=tk.BOTH, expand=True)

        pick_scroll = tk.Scrollbar(list_wrap, orient=tk.VERTICAL)
        pick_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        pick_list = tk.Listbox(
            list_wrap, font=(FONT_MONO, 11),
            yscrollcommand=pick_scroll.set,
            selectbackground=NAVY, selectforeground=AMBER,
            activestyle="none", bg=CARD_BG, fg=TEXT,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        pick_list.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        pick_scroll.config(command=pick_list.yview)

        results = []  # parallel list of (brand, ball_name, date_approved)

        def refresh_results(*args):
            nonlocal results
            try:
                results = _search_approved_balls(cursor, search_var.get())
            except Exception as e:
                messagebox.showerror("Database Error", str(e), parent=pick)
                return
            pick_list.delete(0, tk.END)
            for brand, ball_name, date_approved in results:
                pick_list.insert(tk.END, f"  {brand} — {ball_name}")
            if not results:
                count_label.config(text="No matches")
            elif len(results) >= 200:
                count_label.config(text="Showing first 200 matches — keep typing to narrow it down")
            else:
                count_label.config(text=f"{len(results)} match{'es' if len(results) != 1 else ''}")

        search_var.trace("w", refresh_results)

        def add_selected():
            sel = pick_list.curselection()
            if not sel:
                messagebox.showinfo("Pick a Ball", "Select a ball from the list first.", parent=pick)
                return
            brand, ball_name, date_approved = results[sel[0]]
            pick.destroy()
            _open_ball_form(win, None, prefill={"name": ball_name, "brand": brand})

        def on_double_click(event):
            add_selected()

        pick_list.bind("<Double-Button-1>", on_double_click)

        btn_row_pick = tk.Frame(body_pick, bg=OFFWHITE)
        btn_row_pick.pack(fill=tk.X, pady=(10, 0))

        def _pick_btn(parent, text, cmd, primary=False):
            if primary:
                bg, fg, abg = AMBER, NAVY, "#D97706"
            else:
                bg, fg, abg = "#E2EAF3", TEXT, "#C7D5E8"
            b = tk.Button(parent, text=text, command=cmd,
                          font=(FONT_BODY, 11, "bold"),
                          bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                          relief="flat", cursor="hand2", padx=16, pady=7, borderwidth=0)
            return b

        _pick_btn(btn_row_pick, "Add to Arsenal", add_selected, primary=True).pack(
            side=tk.LEFT, padx=(0, 8))
        _pick_btn(btn_row_pick, "Cancel", pick.destroy).pack(side=tk.LEFT)

        refresh_results()

    # ── Roster buttons ────────────────────────────────────────────────────────
    def _small_btn(parent, text, cmd, primary=False):
        if primary:
            bg, fg, abg = AMBER, NAVY, "#D97706"
        else:
            bg, fg, abg = "#E2EAF3", TEXT, "#C7D5E8"
        b = tk.Button(parent, text=text, command=cmd,
                      font=(FONT_BODY, 10, "bold"),
                      bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
                      relief="flat", cursor="hand2", padx=10, pady=5, borderwidth=0)
        return b

    _small_btn(roster_btn_row, "+ Add Ball", open_add_dialog, primary=True).pack(
        side=tk.LEFT, padx=(0, 6))
    _small_btn(roster_btn_row, "🔍 USBC List", open_usbc_picker).pack(
        side=tk.LEFT)

    # ── Initial load ──────────────────────────────────────────────────────────
    load_roster()