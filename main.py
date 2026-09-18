import os
import sys
import tkinter as tk
import json
import csv
import shutil
from tkinter import filedialog, messagebox, ttk
import sqlite3
from datetime import date, datetime, timedelta
import calendar
import statistics
import math
from typing import Optional, Tuple, List, Any 
from scoresheet_importer import read_scoresheet
from arsenal import show_arsenal, _ensure_balls_table


# ---------- CONSTANTS ----------

CATEGORIES = ["All", "Practice", "League Match", "Family Night", "Friendship Game", "Tournament"]
GAME_CATEGORIES = CATEGORIES[1:]


# ---------- DATABASE ----------

if getattr(sys, "frozen", False):
    APP_FOLDER = os.path.dirname(sys.executable)
else:
    APP_FOLDER = os.path.dirname(os.path.abspath(__file__))

try:
    connection = sqlite3.connect(os.path.join(APP_FOLDER, "bowling.db"))
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            score INTEGER NOT NULL,
            category TEXT DEFAULT 'All'
        )
    """)

    cursor.execute("PRAGMA table_info(games)")
    existing_columns = {column[1] for column in cursor.fetchall()}
    if "frames" not in existing_columns:
        cursor.execute("ALTER TABLE games ADD COLUMN frames TEXT")
    if "center" not in existing_columns:
        cursor.execute("ALTER TABLE games ADD COLUMN center TEXT")
    if "ball" not in existing_columns:
        cursor.execute("ALTER TABLE games ADD COLUMN ball TEXT")
    if "spare_ball" not in existing_columns:
        cursor.execute("ALTER TABLE games ADD COLUMN spare_ball TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    connection.commit()
    _ensure_balls_table(cursor, connection)
except sqlite3.Error as error:
    messagebox.showerror("Database Error", f"Could not open the database:\n{error}")
    sys.exit(1)


# ---------- STATE ----------

scores = []
displayed_ids = []
sort_column = "date"   # one of: "date", "score", "category"
sort_ascending = True


# ---------- SETTINGS (defined early so the theme can be picked before widgets build) ----------

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (str(key),))
        row = cursor.fetchone()
        return str(row[0]) if row else default
    except sqlite3.Error:
        return default


def set_setting(key: str, value: Any) -> None:
    try:
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(key), str(value)),
        )
        connection.commit()
    except sqlite3.Error:
        pass


def set_setting(key, value):
    try:
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        connection.commit()
    except sqlite3.Error:
        pass


def get_overall_stats():
    """Count/average/high across ALL games, ignoring the active History
    filters -- goals and personal-best alerts are always measured against
    your whole history, not just whatever's currently filtered into view."""
    try:
        cursor.execute("SELECT COUNT(*), AVG(score), MAX(score) FROM games")
        count, avg, high = cursor.fetchone()
        return (count or 0), avg, high
    except sqlite3.Error:
        return 0, None, None


NIGHT_MODE = get_setting("night_mode", "0") == "1"


# ---------- DESIGN TOKENS ----------

if NIGHT_MODE:
    NAVY        = "#0B1523"
    NAVY_MID    = "#15243A"
    AMBER       = "#F59E0B"
    AMBER_DIM   = "#92600A"
    WHITE       = "#FFFFFF"
    OFFWHITE    = "#000000"
    CARD_BG     = "#131E2E"
    BORDER      = "#26364C"
    TEXT        = "#E5EDF7"
    TEXT_MUTED  = "#8CA0BA"
    RED         = "#F87171"
    GREEN       = "#4ADE80"
    ENTRY_BG    = "#1B2A3F"
    STRIPE_BG   = "#1A2739"
    INFO_BG     = "#132235"
    WARN_BG     = "#2A2411"
    WARN_TEXT   = "#F2C14E"
    BTN_BG      = "#22344A"
    BTN_ACTIVE  = "#2E4666"
else:
    NAVY        = "#0F1F36"
    NAVY_MID    = "#1A3352"
    AMBER       = "#F59E0B"
    AMBER_DIM   = "#92600A"
    WHITE       = "#FFFFFF"
    OFFWHITE    = "#F8FAFC"
    CARD_BG     = "#FFFFFF"
    BORDER      = "#E2EAF3"
    TEXT        = "#0F1F36"
    TEXT_MUTED  = "#64748B"
    RED         = "#DC2626"
    GREEN       = "#16A34A"
    ENTRY_BG    = "#F1F5FB"
    STRIPE_BG   = "#F8FAFC"
    INFO_BG     = "#EFF6FF"
    WARN_BG     = "#FFFBEB"
    WARN_TEXT   = "#92600A"
    BTN_BG      = "#E2EAF3"
    BTN_ACTIVE  = "#C7D5E8"

FONT_BODY   = "Helvetica"
FONT_MONO   = "Courier"

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24

DESIGN_TOKENS = {
    "NAVY": NAVY, "NAVY_MID": NAVY_MID, "AMBER": AMBER,
    "WHITE": WHITE, "OFFWHITE": OFFWHITE, "CARD_BG": CARD_BG,
    "BORDER": BORDER, "TEXT": TEXT, "TEXT_MUTED": TEXT_MUTED,
    "RED": RED, "GREEN": GREEN, "ENTRY_BG": ENTRY_BG,
    "FONT_BODY": FONT_BODY, "FONT_MONO": FONT_MONO,
}


# ---------- STATISTICS ----------

NO_BALL_LABEL = "— No Ball —"
NO_SPARE_LABEL = "— No Spare Ball —"


def combo_ball(value: Optional[str]) -> Optional[str]:
    """Turn a dropdown value into a stored ball name, or None."""
    if value is None:
        return None
    v: str = str(value).strip()
    if not v or v in (NO_BALL_LABEL, NO_SPARE_LABEL):
        return None
    return v


def pair_balls(strike_value: Optional[str], spare_value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (strike_ball, spare_ball). Same ball twice is stored as strike-only."""
    strike: Optional[str] = combo_ball(strike_value)
    spare: Optional[str] = combo_ball(spare_value)
    if strike and spare and strike.lower() == spare.lower():
        spare = None
    return strike, spare


def format_balls_display(strike: Optional[str], spare: Optional[str]) -> str:
    """Format the ball names for the UI list."""
    str_strike = strike or ""
    str_spare = spare or ""
    if str_strike and str_spare:
        return f"{str_strike} / {str_spare}"
    return str_strike or str_spare or ""

def format_balls_display(strike, spare):
    strike = strike or ""
    spare = spare or ""
    if strike and spare:
        return f"{strike} / {spare}"
    return strike or spare or ""

def get_arsenal_ball_names() -> List[str]:
    """Ball names from the Arsenal (balls table), alphabetical."""
    try:
        cursor.execute("SELECT name FROM balls ORDER BY name")
        return [str(row[0]) for row in cursor.fetchall()]
    except sqlite3.Error:
        return []


def update_stats():
    if len(scores) == 0:
        games_value.config(text="0")
        average_value.config(text="—")
        high_value.config(text="—")
        low_value.config(text="—")
    else:
        games = len(scores)
        average = sum(scores) / games
        high = max(scores)
        low = min(scores)

        games_value.config(text=str(games))
        average_value.config(text=f"{average:.1f}")
        high_value.config(text=str(high))
        low_value.config(text=str(low))

    update_goal_tile()


def update_goal_tile():
    """Refresh the clickable GOAL tile in the header with progress toward
    whatever target is currently set (measured against ALL games, not the
    filtered History view). Shows a "set a goal" prompt when nothing's set."""
    _, overall_avg, overall_high = get_overall_stats()

    target_avg_str = get_setting("target_average", "")
    target_score_str = get_setting("target_score", "")

    if target_avg_str and overall_avg is not None:
        try:
            target_avg = float(target_avg_str)
            met = overall_avg >= target_avg
            goal_label.config(text="AVG GOAL" + ("  ✓" if met else ""))
            goal_value.config(text=f"{overall_avg:.1f}/{target_avg:.1f}", fg=(GREEN if met else AMBER))
            return
        except ValueError:
            pass

    if target_score_str and overall_high is not None:
        try:
            target_score = int(target_score_str)
            met = overall_high >= target_score
            goal_label.config(text="SCORE GOAL" + ("  ✓" if met else ""))
            goal_value.config(text=f"{overall_high}/{target_score}", fg=(GREEN if met else AMBER))
            return
        except ValueError:
            pass

    goal_label.config(text="SET A GOAL →")
    goal_value.config(text="—", fg=AMBER)


def check_goal_alerts(prev_high, prev_avg, added_scores):
    """Call right after committing new game(s). Compares before/after
    all-time stats and pops up a congratulatory message for a new personal
    best, or for crossing a target average/score for the first time."""
    if not added_scores:
        return
    if get_setting("pb_alerts_enabled", "1") != "1":
        return

    _, new_avg, new_high = get_overall_stats()
    top_new_score = max(added_scores)

    if prev_high is None or top_new_score > prev_high:
        messagebox.showinfo(
            "🎉 New Personal Best!",
            f"New high game: {top_new_score}!" + (
                f"\nPrevious best was {prev_high}." if prev_high is not None
                else "\nThat's your first logged game!"
            ),
        )

    target_score_str = get_setting("target_score", "")
    if target_score_str:
        try:
            target_score = int(target_score_str)
            if top_new_score >= target_score and (prev_high is None or prev_high < target_score):
                messagebox.showinfo(
                    "🎯 Goal Reached!",
                    f"You hit your target score of {target_score} with a {top_new_score}!",
                )
        except ValueError:
            pass

    target_avg_str = get_setting("target_average", "")
    if target_avg_str and new_avg is not None:
        try:
            target_avg = float(target_avg_str)
            if new_avg >= target_avg and (prev_avg is None or prev_avg < target_avg):
                messagebox.showinfo(
                    "🎯 Goal Reached!",
                    f"Your average has reached your target of {target_avg:.1f}! Current average: {new_avg:.1f}.",
                )
        except ValueError:
            pass


def open_goals_dialog():
    dlg = tk.Toplevel(window)
    dlg.title("Goals")
    dlg.configure(bg=OFFWHITE)
    dlg.resizable(False, False)
    dlg.transient(window)
    dlg.grab_set()

    tk.Label(dlg, text="🎯  Goals", font=(FONT_BODY, 16, "bold"), bg=OFFWHITE, fg=NAVY).pack(
        pady=(20, 4), padx=30
    )
    tk.Label(
        dlg, text="Set a target and Bowling Tracker will track your progress\nand let you know when you hit it.",
        font=(FONT_BODY, 10), bg=OFFWHITE, fg=TEXT_MUTED, justify=tk.CENTER,
    ).pack(pady=(0, 16), padx=30)

    form = tk.Frame(dlg, bg=OFFWHITE)
    form.pack(padx=30)

    def entry_style(width):
        return dict(
            font=(FONT_BODY, 13), width=width, bg=ENTRY_BG, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=AMBER,
        )

    tk.Label(form, text="Target average (leave blank to disable)", font=(FONT_BODY, 10, "bold"),
             bg=OFFWHITE, fg=TEXT, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 3))
    target_avg_entry = tk.Entry(form, **entry_style(12))
    target_avg_entry.grid(row=1, column=0, sticky="w", ipady=6, ipadx=4, pady=(0, 14))
    target_avg_entry.insert(0, get_setting("target_average", ""))

    tk.Label(form, text="Target single-game score (leave blank to disable)", font=(FONT_BODY, 10, "bold"),
             bg=OFFWHITE, fg=TEXT, anchor="w").grid(row=2, column=0, sticky="w", pady=(0, 3))
    target_score_entry = tk.Entry(form, **entry_style(12))
    target_score_entry.grid(row=3, column=0, sticky="w", ipady=6, ipadx=4, pady=(0, 14))
    target_score_entry.insert(0, get_setting("target_score", ""))

    pb_alerts_var = tk.BooleanVar(value=get_setting("pb_alerts_enabled", "1") == "1")
    tk.Checkbutton(
        form, text="Celebrate new personal bests and goals reached", variable=pb_alerts_var,
        font=(FONT_BODY, 10), bg=OFFWHITE, fg=TEXT, activebackground=OFFWHITE,
        selectcolor=ENTRY_BG,
    ).grid(row=4, column=0, sticky="w", pady=(0, 6))

    def save_goals():
        avg_text = target_avg_entry.get().strip()
        score_text = target_score_entry.get().strip()

        if avg_text:
            try:
                avg_val = float(avg_text)
                if not (0 <= avg_val <= 300):
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Invalid Target Average", "Target average must be a number between 0 and 300.")
                return

        if score_text:
            try:
                score_val = int(score_text)
                if not (0 <= score_val <= 300):
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Invalid Target Score", "Target score must be a whole number between 0 and 300.")
                return

        set_setting("target_average", avg_text)
        set_setting("target_score", score_text)
        set_setting("pb_alerts_enabled", "1" if pb_alerts_var.get() else "0")

        dlg.destroy()
        update_goal_tile()

    make_button(dlg, "Save Goals", save_goals, primary=True).pack(pady=(4, 20))


# ---------- DATE HANDLING ----------

def parse_date_flexible(date_str):
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def to_iso_date(display_date_str):
    parsed = parse_date_flexible(display_date_str)
    return parsed.isoformat() if parsed else None


def to_display_date(iso_date_str):
    try:
        return datetime.strptime(iso_date_str.strip(), "%Y-%m-%d").strftime("%m/%d/%Y")
    except (ValueError, AttributeError):
        return iso_date_str


def migrate_dates_to_iso():
    cursor.execute("SELECT id, date FROM games")
    rows = cursor.fetchall()
    for row_id, row_date in rows:
        iso = to_iso_date(row_date)
        if iso and iso != row_date:
            cursor.execute("UPDATE games SET date = ? WHERE id = ?", (iso, row_id))


migrate_dates_to_iso()
connection.commit()


# ---------- LOAD / FILTER GAMES ----------

def get_date_range_from_quick_pick(pick):
    today = date.today()
    if pick == "All Time":
        return None, None
    elif pick == "Today":
        s = today.strftime("%m/%d/%Y")
        return s, s
    elif pick == "This Week":
        start = today - timedelta(days=today.weekday())
        return start.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")
    elif pick == "Last 30 Days":
        return (today - timedelta(days=30)).strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y")
    elif pick == "This Year":
        return f"01/01/{today.year}", today.strftime("%m/%d/%Y")
    elif pick == "Last Year":
        y = today.year - 1
        return f"01/01/{y}", f"12/31/{y}"
    else:
        for month_num, month_name in enumerate(
            ["January","February","March","April","May","June",
             "July","August","September","October","November","December"], start=1
        ):
            if pick == month_name:
                year = today.year
                last_day = calendar.monthrange(year, month_num)[1]
                return f"{month_num:02d}/01/{year}", f"{month_num:02d}/{last_day:02d}/{year}"
    return None, None


def apply_quick_pick(*args):
    pick = time_quick_var.get()
    if pick == "Custom":
        update_history_display()
        return
    d_from, d_to = get_date_range_from_quick_pick(pick)
    date_from_entry.delete(0, tk.END)
    date_to_entry.delete(0, tk.END)
    if d_from:
        date_from_entry.insert(0, d_from)
    if d_to:
        date_to_entry.insert(0, d_to)
    update_history_display()


def update_history_display():
    selected_category = category_filter_var.get()
    selected_center = center_filter_var.get()
    selected_ball = ball_filter_var.get()
    try:
        date_from_str = date_from_entry.get().strip()
        date_to_str   = date_to_entry.get().strip()
    except NameError:
        date_from_str = ""
        date_to_str   = ""

    date_from = parse_date_flexible(date_from_str) if date_from_str else None
    date_to   = parse_date_flexible(date_to_str)   if date_to_str   else None

    conditions = []
    params = []
    if selected_category != "All":
        conditions.append("category = ?")
        params.append(selected_category)
    if selected_center != "All":
        conditions.append("center = ?")
        params.append(selected_center)
    if selected_ball != "All":
        conditions.append("(ball = ? OR spare_ball = ?)")
        params.append(selected_ball)
        params.append(selected_ball)

    query = "SELECT id, date, score, category, ball, spare_ball FROM games"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    sql_column = {
        "date": "date",
        "score": "score",
        "category": "category",
        "ball": "COALESCE(ball, spare_ball)",
    }[sort_column]
    direction = "ASC" if sort_ascending else "DESC"
    query += f" ORDER BY {sql_column} {direction}"

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load games:\n{error}")
        return

    history.delete(0, tk.END)
    scores.clear()
    displayed_ids.clear()

    display_i = 0
    for (game_id, game_date, score, category, ball, spare_ball) in rows:
        if date_from or date_to:
            parsed = parse_date_flexible(game_date)
            if parsed is None:
                continue
            if date_from and parsed < date_from:
                continue
            if date_to and parsed > date_to:
                continue

        scores.append(score)
        displayed_ids.append(game_id)
        history.insert(
            tk.END,
            f"  {to_display_date(game_date):<14} {score:>3}   {category or '':<16} "
            f"{format_balls_display(ball, spare_ball)}",
        )
        history.itemconfig(display_i, **{"bg": STRIPE_BG if display_i % 2 == 0 else CARD_BG})
        display_i += 1

    update_stats()


def refresh_ball_filter_options():
    try:
        cursor.execute(
            """
            SELECT name FROM (
                SELECT DISTINCT ball AS name FROM games
                WHERE ball IS NOT NULL AND ball != ''
                UNION
                SELECT DISTINCT spare_ball AS name FROM games
                WHERE spare_ball IS NOT NULL AND spare_ball != ''
            ) ORDER BY name
            """
        )
        balls = [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load balls:\n{error}")
        balls = []

    ball_filter_menu["values"] = ["All"] + balls
    if ball_filter_var.get() not in ball_filter_menu["values"]:
        ball_filter_var.set("All")


def refresh_center_filter_options():
    try:
        cursor.execute(
            "SELECT DISTINCT center FROM games WHERE center IS NOT NULL AND center != '' ORDER BY center"
        )
        centers = [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load bowling centers:\n{error}")
        centers = []

    center_filter_menu["values"] = ["All"] + centers
    if center_filter_var.get() not in center_filter_menu["values"]:
        center_filter_var.set("All")


# ---------- ADD GAME ----------

def add_game():
    game_date_display = date_entry.get()
    score_text = score_entry.get()

    if game_date_display == "":
        messagebox.showwarning("Missing Date", "Please enter a date.")
        return

    game_date = to_iso_date(game_date_display)
    if game_date is None:
        messagebox.showwarning("Invalid Date", "Please enter a valid date (MM/DD/YYYY).")
        return

    if score_text == "":
        messagebox.showwarning("Missing Score", "Please enter a score.")
        return

    try:
        score = int(score_text)
    except ValueError:
        messagebox.showwarning("Invalid Score", "Score must be a number.")
        return

    if score < 0 or score > 300:
        messagebox.showwarning("Invalid Score", "Bowling scores must be between 0 and 300.")
        return

    category = new_game_category_var.get()
    ball, spare_ball = pair_balls(ball_var.get(), spare_ball_var.get())

    prev_count, prev_avg, prev_high = get_overall_stats()

    try:
        cursor.execute(
            "INSERT INTO games (date, score, category, ball, spare_ball) VALUES (?, ?, ?, ?, ?)",
            (game_date, score, category, ball, spare_ball)
        )
        connection.commit()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not save the game:\n{error}")
        return

    score_entry.delete(0, tk.END)
    refresh_ball_filter_options()
    update_history_display()
    check_goal_alerts(prev_high, prev_avg, [score])


# ---------- DELETE GAME ----------

def delete_game():
    selected = history.curselection()
    if not selected:
        messagebox.showwarning("No Game Selected", "Please select a game to delete.")
        return

    if len(selected) > 1:
        game_ids = [displayed_ids[i] for i in selected]
        confirm = messagebox.askyesno(
            "Delete Games",
            f"Delete these {len(game_ids)} games?\n\nThis can't be undone.",
        )
        if not confirm:
            return
        try:
            cursor.executemany(
                "DELETE FROM games WHERE id = ?", [(gid,) for gid in game_ids]
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not delete the games:\n{error}")
            return
        update_history_display()
        return

    index = selected[0]
    game_id = displayed_ids[index]

    try:
        cursor.execute("SELECT date, score, category FROM games WHERE id = ?", (game_id,))
        row = cursor.fetchone()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the game:\n{error}")
        return

    if row is None:
        messagebox.showwarning("Game Not Found", "That game no longer exists.")
        update_history_display()
        return

    game_date, score, category = row
    confirm = messagebox.askyesno(
        "Delete Game",
        f"Delete this game?\n\n"
        f"Date:      {to_display_date(game_date)}\n"
        f"Score:     {score}\n"
        f"Category:  {category or 'Uncategorized'}\n\n"
        f"This can't be undone.",
    )
    if not confirm:
        return

    try:
        cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
        connection.commit()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not delete the game:\n{error}")
        return

    update_history_display()


# ---------- EDIT GAME ----------

def edit_game():
    selected = history.curselection()
    if not selected:
        messagebox.showwarning("No Game Selected", "Please select a game to edit.")
        return

    if len(selected) > 1:
        game_ids = [displayed_ids[i] for i in selected]
        batch_edit_games(game_ids)
        return

    index = selected[0]
    game_id = displayed_ids[index]

    try:
        cursor.execute(
            "SELECT date, score, category, frames, ball, spare_ball FROM games WHERE id = ?",
            (game_id,)
        )
        current_date, current_score, current_category, current_frames, current_ball, current_spare = cursor.fetchone()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the game:\n{error}")
        return

    edit_window = tk.Toplevel(window)
    edit_window.title("Edit Game")
    edit_window.resizable(False, False)
    edit_window.transient(window)
    edit_window.grab_set()
    edit_window.configure(bg=OFFWHITE)

    hdr = tk.Frame(edit_window, bg=NAVY, height=48)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="Edit Game", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=12)

    body = tk.Frame(edit_window, bg=OFFWHITE, padx=28, pady=20)
    body.pack(fill=tk.BOTH)

    def field_label(parent, text):
        tk.Label(parent, text=text, font=(FONT_BODY, 11, "bold"),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(14, 2))

    field_label(body, "DATE")
    date_entry_edit = tk.Entry(body, font=(FONT_BODY, 14), width=16,
                                bg=ENTRY_BG, relief="flat",
                                highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=AMBER)
    date_entry_edit.pack(anchor="w", ipady=6, ipadx=4)
    date_entry_edit.insert(0, to_display_date(current_date))

    field_label(body, "SCORE")
    score_entry_edit = tk.Entry(body, font=(FONT_BODY, 14), width=10,
                                 bg=ENTRY_BG, relief="flat",
                                 highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=AMBER)
    score_entry_edit.pack(anchor="w", ipady=6, ipadx=4)
    score_entry_edit.insert(0, str(current_score))

    if current_frames:
        score_entry_edit.config(state="readonly", readonlybackground=ENTRY_BG)

    field_label(body, "CATEGORY")
    selected_category_var = tk.StringVar(value=current_category)
    make_dropdown(body, selected_category_var, CATEGORIES).pack(anchor="w")

    field_label(body, "STRIKE BALL")
    arsenal_ball_names = get_arsenal_ball_names()
    ball_choices_edit = [NO_BALL_LABEL] + arsenal_ball_names
    if current_ball and current_ball not in arsenal_ball_names:
        # Ball was set before it existed in (or after it was removed from)
        # the Arsenal — keep it selectable so editing doesn't wipe it out.
        ball_choices_edit.append(current_ball)
    ball_var_edit = tk.StringVar(value=current_ball if current_ball else NO_BALL_LABEL)
    ball_combo_edit = ttk.Combobox(body, textvariable=ball_var_edit, state="readonly",
                                    font=(FONT_BODY, 12), width=22, values=ball_choices_edit)
    ball_combo_edit.pack(anchor="w", ipady=4)

    field_label(body, "SPARE BALL")
    spare_choices_edit = [NO_SPARE_LABEL] + arsenal_ball_names
    if current_spare and current_spare not in arsenal_ball_names:
        spare_choices_edit.append(current_spare)
    spare_var_edit = tk.StringVar(value=current_spare if current_spare else NO_SPARE_LABEL)
    spare_combo_edit = ttk.Combobox(body, textvariable=spare_var_edit, state="readonly",
                                     font=(FONT_BODY, 12), width=22, values=spare_choices_edit)
    spare_combo_edit.pack(anchor="w", ipady=4)
    tk.Label(body, text="Leave spare blank if you used one ball the whole game.",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(4, 0))

    if current_frames:
        note = tk.Frame(body, bg=INFO_BG, relief="flat")
        note.pack(fill=tk.X, pady=(14, 0))
        tk.Label(note, text="This game has frame-by-frame data. The score above is calculated "
                             "from it — use \"Edit Frame-by-Frame\" below to correct a throw.",
                 font=(FONT_BODY, 9), bg=INFO_BG, fg=TEXT_MUTED,
                 wraplength=260, justify=tk.LEFT).pack(padx=10, pady=8)

        def open_frame_editor():
            show_frame_editor(game_id, on_saved=lambda new_score: (
                score_entry_edit.config(state="normal"),
                score_entry_edit.delete(0, tk.END),
                score_entry_edit.insert(0, str(new_score)),
                score_entry_edit.config(state="readonly"),
            ))

        make_button(body, "📋  Edit Frame-by-Frame", open_frame_editor).pack(anchor="w", pady=(10, 0))

    def save_edit():
        new_date_display = date_entry_edit.get()
        if new_date_display == "":
            messagebox.showwarning("Missing Date", "Please enter a date.")
            return
        new_date = to_iso_date(new_date_display)
        if new_date is None:
            messagebox.showwarning("Invalid Date", "Please enter a valid date (MM/DD/YYYY).")
            return

        if current_frames:
            try:
                cursor.execute("SELECT score FROM games WHERE id = ?", (game_id,))
                new_score = cursor.fetchone()[0]
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", f"Could not read the current score:\n{error}")
                return
        else:
            new_score_text = score_entry_edit.get()
            try:
                new_score = int(new_score_text)
            except ValueError:
                messagebox.showwarning("Invalid Score", "Score must be a number.")
                return
            if new_score < 0 or new_score > 300:
                messagebox.showwarning("Invalid Score", "Bowling scores must be between 0 and 300.")
                return

        try:
            new_ball, new_spare = pair_balls(ball_var_edit.get(), spare_var_edit.get())
            cursor.execute(
                "UPDATE games SET date = ?, score = ?, category = ?, ball = ?, spare_ball = ? WHERE id = ?",
                (new_date, new_score, selected_category_var.get(), new_ball, new_spare, game_id)
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not save changes:\n{error}")
            return
        edit_window.destroy()
        refresh_ball_filter_options()
        update_history_display()

    btn_row = tk.Frame(body, bg=OFFWHITE)
    btn_row.pack(pady=(20, 4))
    make_button(btn_row, "Save Changes", save_edit, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(btn_row, "Cancel", edit_window.destroy).pack(side=tk.LEFT)

    edit_window.update_idletasks()
    w = edit_window.winfo_reqwidth()
    h = edit_window.winfo_reqheight()
    edit_window.geometry(f"{w}x{h}")


# ---------- BATCH EDIT GAMES ----------

def batch_edit_games(game_ids):
    """Edit Category and/or balls across several games at once.
    Only fields whose checkbox is checked get applied to every selected game."""

    try:
        cursor.execute(
            f"SELECT date, score, category, ball, spare_ball FROM games WHERE id IN "
            f"({','.join('?' for _ in game_ids)}) ORDER BY date",
            game_ids
        )
        rows = cursor.fetchall()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the games:\n{error}")
        return

    batch_window = tk.Toplevel(window)
    batch_window.title("Batch Edit Games")
    batch_window.resizable(False, False)
    batch_window.transient(window)
    batch_window.grab_set()
    batch_window.configure(bg=OFFWHITE)

    hdr = tk.Frame(batch_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text=f"Batch Edit  ·  {len(game_ids)} Games", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=12)

    body = tk.Frame(batch_window, bg=OFFWHITE, padx=28, pady=18)
    body.pack(fill=tk.BOTH)

    tk.Label(body, text="Selected games", font=(FONT_BODY, 10, "bold"),
             bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w")

    preview_frame = tk.Frame(body, bg=BORDER)
    preview_frame.pack(fill=tk.X, pady=(4, 4))
    preview = tk.Listbox(preview_frame, font=(FONT_MONO, 11), height=min(len(rows), 6),
                         bg=CARD_BG, fg=TEXT, relief="flat", borderwidth=0,
                         highlightthickness=0, activestyle="none")
    preview.pack(padx=1, pady=1, fill=tk.X)
    for game_date, score, category, ball, spare_ball in rows:
        preview.insert(tk.END, f"  {to_display_date(game_date):<12} {score:>3}   "
                                f"{category or '':<16} {format_balls_display(ball, spare_ball)}")
    preview.config(state="disabled")

    tk.Label(body, text="Only the fields you check below will be changed. "
                        "Everything else on these games stays as-is.",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED,
             wraplength=340, justify=tk.LEFT).pack(anchor="w", pady=(10, 14))

    # ── Category field ──
    cat_row = tk.Frame(body, bg=OFFWHITE)
    cat_row.pack(fill=tk.X, pady=(0, 10))
    apply_category = tk.BooleanVar(value=False)
    batch_category_var = tk.StringVar(value=GAME_CATEGORIES[0])
    cat_dropdown = make_dropdown(cat_row, batch_category_var, GAME_CATEGORIES)

    def toggle_category():
        cat_dropdown.config(state="normal" if apply_category.get() else "disabled")

    tk.Checkbutton(cat_row, text="Set Category to:", variable=apply_category,
                   command=toggle_category, font=(FONT_BODY, 11, "bold"),
                   bg=OFFWHITE, fg=TEXT, activebackground=OFFWHITE,
                   selectcolor=ENTRY_BG).pack(side=tk.LEFT, padx=(0, 10))
    cat_dropdown.pack(side=tk.LEFT)
    cat_dropdown.config(state="disabled")

    # ── Strike ball field ──
    ball_row = tk.Frame(body, bg=OFFWHITE)
    ball_row.pack(fill=tk.X, pady=(0, 10))
    apply_ball = tk.BooleanVar(value=False)
    batch_ball_var = tk.StringVar(value=NO_BALL_LABEL)
    ball_dropdown = ttk.Combobox(ball_row, textvariable=batch_ball_var, state="disabled",
                                  font=(FONT_BODY, 11), width=16,
                                  values=[NO_BALL_LABEL] + get_arsenal_ball_names())

    def toggle_ball():
        ball_dropdown.config(state="readonly" if apply_ball.get() else "disabled")

    tk.Checkbutton(ball_row, text="Set Strike Ball to:", variable=apply_ball,
                   command=toggle_ball, font=(FONT_BODY, 11, "bold"),
                   bg=OFFWHITE, fg=TEXT, activebackground=OFFWHITE,
                   selectcolor=ENTRY_BG).pack(side=tk.LEFT, padx=(0, 10))
    ball_dropdown.pack(side=tk.LEFT)

    # ── Spare ball field ──
    spare_row = tk.Frame(body, bg=OFFWHITE)
    spare_row.pack(fill=tk.X)
    apply_spare = tk.BooleanVar(value=False)
    batch_spare_var = tk.StringVar(value=NO_SPARE_LABEL)
    spare_dropdown = ttk.Combobox(spare_row, textvariable=batch_spare_var, state="disabled",
                                   font=(FONT_BODY, 11), width=16,
                                   values=[NO_SPARE_LABEL] + get_arsenal_ball_names())

    def toggle_spare():
        spare_dropdown.config(state="readonly" if apply_spare.get() else "disabled")

    tk.Checkbutton(spare_row, text="Set Spare Ball to:", variable=apply_spare,
                   command=toggle_spare, font=(FONT_BODY, 11, "bold"),
                   bg=OFFWHITE, fg=TEXT, activebackground=OFFWHITE,
                   selectcolor=ENTRY_BG).pack(side=tk.LEFT, padx=(0, 10))
    spare_dropdown.pack(side=tk.LEFT)

    def apply_batch():
        if not apply_category.get() and not apply_ball.get() and not apply_spare.get():
            messagebox.showwarning("Nothing to Change",
                                   "Check at least one field to change.", parent=batch_window)
            return

        updates = []
        if apply_category.get():
            updates.append(("category", batch_category_var.get()))
        if apply_ball.get():
            updates.append(("ball", combo_ball(batch_ball_var.get())))
        if apply_spare.get():
            updates.append(("spare_ball", combo_ball(batch_spare_var.get())))

        field_display_names = {"category": "Category", "ball": "Strike Ball", "spare_ball": "Spare Ball"}
        summary = "\n".join(
            f"  • {field_display_names.get(field, field.capitalize())} → {value or 'None'}"
            for field, value in updates
        )
        if not messagebox.askyesno(
            "Apply Batch Edit",
            f"Apply this to {len(game_ids)} games?\n\n{summary}",
            parent=batch_window
        ):
            return

        set_clause = ", ".join(f"{field} = ?" for field, _ in updates)
        params = [value for _, value in updates]
        try:
            cursor.executemany(
                f"UPDATE games SET {set_clause} WHERE id = ?",
                [(*params, gid) for gid in game_ids]
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not save changes:\n{error}", parent=batch_window)
            return

        batch_window.destroy()
        refresh_ball_filter_options()
        update_history_display()

    btn_row = tk.Frame(body, bg=OFFWHITE)
    btn_row.pack(pady=(20, 4))
    make_button(btn_row, f"Apply to {len(game_ids)} Games", apply_batch, primary=True).pack(
        side=tk.LEFT, padx=(0, 8))
    make_button(btn_row, "Cancel", batch_window.destroy).pack(side=tk.LEFT)

    batch_window.update_idletasks()
    w = batch_window.winfo_reqwidth()
    h = batch_window.winfo_reqheight()
    batch_window.geometry(f"{w}x{h}")


# ---------- FRAME DETAILS ----------

def calculate_score_from_frames(frames):
    flat_pins = []
    frame_start_index = []
    for frame in frames:
        frame_start_index.append(len(flat_pins))
        pins_in_frame = []
        for mark in frame.get("throws", []):
            if mark == "X":
                pins_in_frame.append(10)
            elif mark == "-":
                pins_in_frame.append(0)
            elif mark == "/":
                prev = pins_in_frame[-1] if pins_in_frame else 0
                pins_in_frame.append(10 - prev)
            else:
                pins_in_frame.append(int(mark))
        flat_pins.extend(pins_in_frame)

    total = 0
    for i in range(min(10, len(frames))):
        start = frame_start_index[i]
        throws = frames[i].get("throws", [])
        if not throws:
            continue
        if i < 9:
            first = flat_pins[start]
            if first == 10:
                total += 10 + sum(flat_pins[start + 1:start + 3])
            elif len(throws) >= 2:
                frame_sum = flat_pins[start] + flat_pins[start + 1]
                if frame_sum == 10:
                    bonus = flat_pins[start + 2] if len(flat_pins) > start + 2 else 0
                    total += 10 + bonus
                else:
                    total += frame_sum
            else:
                total += flat_pins[start]
        else:
            total += sum(flat_pins[start:start + 3])
    return total


def is_valid_throw_mark(mark):
    mark = mark.strip()
    if mark in ("X", "/", "-"):
        return True
    return mark.isdigit() and len(mark) == 1


def frame_pin_left_values(frame_number, throws):
    remaining = 10
    values = []
    for throw_number, mark in enumerate(throws, start=1):
        before_throw = remaining
        if mark == "X":
            remaining = 0
        elif mark == "/":
            remaining = 0
        elif mark == "-":
            pass
        else:
            try:
                remaining = max(0, before_throw - int(mark))
            except ValueError:
                values.append("?")
                continue
        values.append(str(remaining))
        if frame_number == 10 and remaining == 0 and throw_number < len(throws):
            remaining = 10
    return values


def show_frame_details():
    selected = history.curselection()
    if not selected:
        messagebox.showwarning("No Game Selected", "Please select an imported game first.")
        return
    if len(selected) > 1:
        messagebox.showinfo("Select One Game",
                            "Frame details can only be shown for one game at a time. "
                            "Please select a single game.")
        return

    index = selected[0]
    game_id = displayed_ids[index]

    try:
        cursor.execute("SELECT date, score, frames FROM games WHERE id = ?", (game_id,))
        game_date, score, frame_data = cursor.fetchone()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the game:\n{error}")
        return

    if not frame_data:
        messagebox.showinfo("No Frame Details",
                            "This game was entered manually, so it does not have frame-by-frame information.")
        return

    try:
        frames = json.loads(frame_data)
    except (TypeError, json.JSONDecodeError):
        messagebox.showerror("Could Not Read Frames", "The saved frame details for this game are invalid.")
        return

    details_window = tk.Toplevel(window)
    details_window.title("Frame Details")
    details_window.configure(bg=OFFWHITE)
    details_window.resizable(False, False)
    details_window.transient(window)

    hdr = tk.Frame(details_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text=f"Frame Details", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(hdr, text=f"{to_display_date(game_date)}  ·  {score} pts",
             font=(FONT_BODY, 12), bg=NAVY, fg=AMBER).pack(side=tk.LEFT, pady=14)

    tk.Label(details_window,
             text="Throw marks shown above  ·  Pins remaining shown below",
             font=(FONT_BODY, 10), bg=OFFWHITE, fg=TEXT_MUTED).pack(pady=(14, 8))

    scorecard = tk.Frame(details_window, bg=OFFWHITE)
    scorecard.pack(fill=tk.X, padx=18, pady=(0, 20))

    for frame_number, frame in enumerate(frames, start=1):
        is_last = frame_number == 10
        frame_box = tk.Frame(scorecard, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER,
                             width=90 if not is_last else 108)
        frame_box.grid(row=0, column=frame_number - 1, padx=2, sticky="nsew")
        frame_box.grid_propagate(False)
        scorecard.grid_columnconfigure(frame_number - 1, weight=1)

        num_bar = tk.Frame(frame_box, bg=NAVY_MID)
        num_bar.pack(fill=tk.X)
        tk.Label(num_bar, text=f"{frame_number}", font=(FONT_BODY, 9, "bold"),
                 bg=NAVY_MID, fg=AMBER).pack(pady=4)

        throws = frame.get("throws", [])
        marks = "  ".join(throws) if throws else "—"
        pins_left = "  ".join(frame_pin_left_values(frame_number, throws)) if throws else "—"

        tk.Label(frame_box, text=marks, font=(FONT_MONO, 15, "bold"),
                 bg=CARD_BG, fg=TEXT, wraplength=86).pack(pady=(10, 4))

        divider = tk.Frame(frame_box, bg=BORDER, height=1)
        divider.pack(fill=tk.X, padx=6)

        tk.Label(frame_box, text="LEFT", font=(FONT_BODY, 7, "bold"),
                 bg=CARD_BG, fg=TEXT_MUTED).pack(pady=(6, 0))
        tk.Label(frame_box, text=pins_left, font=(FONT_MONO, 12),
                 bg=CARD_BG, fg=TEXT, wraplength=86).pack(pady=(2, 10))

    details_window.update_idletasks()
    w = details_window.winfo_reqwidth()
    h = details_window.winfo_reqheight()
    details_window.geometry(f"{max(w, 960)}x{h}")


def show_frame_editor(game_id, on_saved=None):
    try:
        cursor.execute("SELECT date, score, frames FROM games WHERE id = ?", (game_id,))
        game_date, score, frame_data = cursor.fetchone()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the game:\n{error}")
        return

    try:
        frames = json.loads(frame_data)
    except (TypeError, json.JSONDecodeError):
        messagebox.showerror("Could Not Read Frames", "The saved frame details for this game are invalid.")
        return

    editor = tk.Toplevel(window)
    editor.title("Edit Frame-by-Frame")
    editor.configure(bg=OFFWHITE)
    editor.resizable(False, False)
    editor.transient(window)
    editor.grab_set()

    hdr = tk.Frame(editor, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="Edit Frame-by-Frame", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(hdr, text=f"{to_display_date(game_date)}",
             font=(FONT_BODY, 12), bg=NAVY, fg=AMBER).pack(side=tk.LEFT, pady=14)

    tk.Label(editor,
             text="Edit a throw mark (X, /, -, or a digit 0-9), then recalculate.\n"
                  "Throws can't be added or removed here — only corrected.",
             font=(FONT_BODY, 10), bg=OFFWHITE, fg=TEXT_MUTED,
             justify=tk.LEFT).pack(pady=(14, 8), padx=18, anchor="w")

    scorecard = tk.Frame(editor, bg=OFFWHITE)
    scorecard.pack(fill=tk.X, padx=18, pady=(0, 8))

    throw_entries = []

    for frame_number, frame in enumerate(frames, start=1):
        is_last = frame_number == 10
        frame_box = tk.Frame(scorecard, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER,
                             width=90 if not is_last else 130)
        frame_box.grid(row=0, column=frame_number - 1, padx=2, sticky="nsew")
        frame_box.grid_propagate(False)
        scorecard.grid_columnconfigure(frame_number - 1, weight=1)

        num_bar = tk.Frame(frame_box, bg=NAVY_MID)
        num_bar.pack(fill=tk.X)
        tk.Label(num_bar, text=f"{frame_number}", font=(FONT_BODY, 9, "bold"),
                 bg=NAVY_MID, fg=AMBER).pack(pady=4)

        throws_row = tk.Frame(frame_box, bg=CARD_BG)
        throws_row.pack(pady=10)

        throws = frame.get("throws", [])
        for throw_index, mark in enumerate(throws):
            e = tk.Entry(throws_row, font=(FONT_MONO, 14, "bold"), width=2,
                         justify="center", bg=ENTRY_BG, relief="flat",
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=AMBER)
            e.pack(side=tk.LEFT, padx=2)
            e.insert(0, mark)
            throw_entries.append((frame_number - 1, throw_index, e))

    def recalculate_and_save():
        updated_frames = [dict(f) for f in frames]
        for frame_index, throw_index, entry in throw_entries:
            mark = entry.get().strip().upper()
            if not is_valid_throw_mark(mark):
                messagebox.showwarning(
                    "Invalid Throw",
                    f"Frame {frame_index + 1}: '{mark}' isn't valid. "
                    "Use X, /, -, or a single digit 0-9.",
                    parent=editor,
                )
                return
            updated_frames[frame_index]["throws"][throw_index] = mark

        try:
            new_score = calculate_score_from_frames(updated_frames)
        except (ValueError, IndexError):
            messagebox.showerror(
                "Could Not Calculate Score",
                "Those throw marks don't add up to a valid frame (e.g. a '/' with no prior throw, "
                "or pins exceeding 10 in a frame). Please check them and try again.",
                parent=editor,
            )
            return

        if new_score < 0 or new_score > 300:
            messagebox.showwarning("Invalid Score", "That would produce a score outside 0–300. "
                                                     "Please check the marks.", parent=editor)
            return

        try:
            cursor.execute(
                "UPDATE games SET score = ?, frames = ? WHERE id = ?",
                (new_score, json.dumps(updated_frames), game_id)
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not save changes:\n{error}", parent=editor)
            return

        editor.destroy()
        if on_saved:
            on_saved(new_score)
        update_history_display()
        messagebox.showinfo("Saved", f"Frame details updated. New score: {new_score}")

    btn_row = tk.Frame(editor, bg=OFFWHITE)
    btn_row.pack(pady=(8, 18))
    make_button(btn_row, "Recalculate & Save", recalculate_and_save, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(btn_row, "Cancel", editor.destroy).pack(side=tk.LEFT)

    editor.update_idletasks()
    w = editor.winfo_reqwidth()
    h = editor.winfo_reqheight()
    editor.geometry(f"{max(w, 960)}x{h}")


# ---------- IMPORT SCORESHEET ----------

def find_duplicate_flags(player_records):
    try:
        cursor.execute("SELECT date, score, center FROM games")
        existing = set()
        for row_date, row_score, row_center in cursor.fetchall():
            existing.add((row_date, row_score, row_center or None))
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not check for duplicates:\n{error}")
        return [False] * len(player_records)

    flags = []
    for record in player_records:
        iso_date = to_iso_date(record["date"]) or record["date"]
        key = (iso_date, record["score"], record.get("center") or None)
        flags.append(key in existing)
    return flags


def show_import_review(player, player_records, file_name):
    review_window = tk.Toplevel(window)
    review_window.title("Review Imported Games")
    review_window.resizable(False, False)
    review_window.transient(window)
    review_window.grab_set()
    review_window.configure(bg=OFFWHITE)

    centers_in_file = {record.get("center") for record in player_records if record.get("center")}
    center_line = ", ".join(sorted(centers_in_file)) if centers_in_file else "Unknown"

    hdr = tk.Frame(review_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="Import Scoresheet", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)

    body = tk.Frame(review_window, bg=OFFWHITE, padx=24, pady=16)
    body.pack(fill=tk.BOTH)

    info_frame = tk.Frame(body, bg=INFO_BG, highlightthickness=1, highlightbackground=BORDER)
    info_frame.pack(fill=tk.X, pady=(0, 12))
    tk.Label(info_frame, text=f"Player:  {player}", font=(FONT_BODY, 12, "bold"),
             bg=INFO_BG, fg=TEXT, anchor="w").pack(fill=tk.X, padx=14, pady=(10, 2))
    tk.Label(info_frame, text=f"Center:  {center_line}", font=(FONT_BODY, 11),
             bg=INFO_BG, fg=TEXT_MUTED, anchor="w").pack(fill=tk.X, padx=14)
    tk.Label(info_frame, text=f"File:      {file_name}", font=(FONT_BODY, 10),
             bg=INFO_BG, fg=TEXT_MUTED, anchor="w").pack(fill=tk.X, padx=14, pady=(0, 10))

    duplicate_flags = find_duplicate_flags(player_records)
    duplicate_count = sum(duplicate_flags)

    list_frame = tk.Frame(body, bg=BORDER, highlightthickness=0)
    list_frame.pack(fill=tk.X)

    preview = tk.Listbox(list_frame, font=(FONT_MONO, 12), width=54, height=10,
                         bg=CARD_BG, fg=TEXT, selectbackground=NAVY, selectforeground=AMBER,
                         relief="flat", borderwidth=0, highlightthickness=0)
    preview.pack(padx=1, pady=1)
    for game_number, (record, is_dup) in enumerate(zip(player_records, duplicate_flags), start=1):
        marker = "  ⚠ already in tracker" if is_dup else ""
        preview.insert(tk.END, f"  Game {game_number:<3}  {record['date']:<14}  {record['score']:<5}{marker}")
        if is_dup:
            preview.itemconfig(game_number - 1, fg="#B45309")

    if duplicate_count:
        dup_note = tk.Frame(body, bg=WARN_BG, relief="flat")
        dup_note.pack(fill=tk.X, pady=(10, 0))
        tk.Label(
            dup_note,
            text=f"⚠  {duplicate_count} of {len(player_records)} game(s) in this file look like "
                 "they're already in the tracker (same date, score, and center). "
                 "You can skip those or import everything anyway.",
            font=(FONT_BODY, 9), bg=WARN_BG, fg=WARN_TEXT,
            wraplength=440, justify=tk.LEFT,
        ).pack(padx=10, pady=8)

    cat_row = tk.Frame(body, bg=OFFWHITE)
    cat_row.pack(pady=(14, 0))
    tk.Label(cat_row, text="Category:", font=(FONT_BODY, 12, "bold"),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(0, 10))
    import_category_var = tk.StringVar(value=GAME_CATEGORIES[0])
    make_dropdown(cat_row, import_category_var, GAME_CATEGORIES).pack(side=tk.LEFT)

    tk.Label(body, text="Applied to every game in this file.",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED).pack(pady=(4, 0))

    ball_row = tk.Frame(body, bg=OFFWHITE)
    ball_row.pack(pady=(10, 0))
    tk.Label(ball_row, text="Strike ball:", font=(FONT_BODY, 12, "bold"),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(0, 10))
    import_ball_var = tk.StringVar(value=NO_BALL_LABEL)
    import_ball_combo = ttk.Combobox(ball_row, textvariable=import_ball_var, state="readonly",
                                      font=(FONT_BODY, 11), width=18,
                                      values=[NO_BALL_LABEL] + get_arsenal_ball_names())
    import_ball_combo.pack(side=tk.LEFT)

    spare_row = tk.Frame(body, bg=OFFWHITE)
    spare_row.pack(pady=(10, 0))
    tk.Label(spare_row, text="Spare ball:", font=(FONT_BODY, 12, "bold"),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(0, 10))
    import_spare_var = tk.StringVar(value=NO_SPARE_LABEL)
    import_spare_combo = ttk.Combobox(spare_row, textvariable=import_spare_var, state="readonly",
                                       font=(FONT_BODY, 11), width=18,
                                       values=[NO_SPARE_LABEL] + get_arsenal_ball_names())
    import_spare_combo.pack(side=tk.LEFT)

    tk.Label(body, text="Both are applied to every game in this file.",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED).pack(pady=(4, 0))

    def do_import(records_to_import):
        if not records_to_import:
            messagebox.showinfo("Nothing to Import", "No games left to import.", parent=review_window)
            return
        chosen_category = import_category_var.get()
        chosen_ball, chosen_spare = pair_balls(import_ball_var.get(), import_spare_var.get())
        prev_count, prev_avg, prev_high = get_overall_stats()
        try:
            cursor.executemany(
                "INSERT INTO games (date, score, category, center, frames, ball, spare_ball) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (to_iso_date(record["date"]) or record["date"], record["score"], chosen_category,
                     record.get("center") or None, json.dumps(record["frames"]),
                     chosen_ball, chosen_spare)
                    for record in records_to_import
                ],
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not import games:\n{error}", parent=review_window)
            return
        review_window.destroy()
        refresh_center_filter_options()
        refresh_ball_filter_options()
        update_history_display()
        messagebox.showinfo("Import Complete", f"Imported {len(records_to_import)} game(s) for {player}.")
        check_goal_alerts(prev_high, prev_avg, [r["score"] for r in records_to_import])

    def confirm_import_all():
        if not messagebox.askyesno("Import Games",
                                   f"Import {len(player_records)} game(s) for {player}?",
                                   parent=review_window):
            return
        do_import(player_records)

    def confirm_import_skip_duplicates():
        records_to_import = [r for r, is_dup in zip(player_records, duplicate_flags) if not is_dup]
        if not messagebox.askyesno(
            "Import Games",
            f"Import {len(records_to_import)} game(s) for {player}, "
            f"skipping {duplicate_count} likely duplicate(s)?",
            parent=review_window,
        ):
            return
        do_import(records_to_import)

    actions = tk.Frame(body, bg=OFFWHITE)
    actions.pack(pady=18)
    if duplicate_count:
        make_button(actions, f"Skip Duplicates & Import {len(player_records) - duplicate_count}",
                    confirm_import_skip_duplicates, primary=True).pack(side=tk.LEFT, padx=(0, 8))
        make_button(actions, f"Import All {len(player_records)} Anyway",
                    confirm_import_all).pack(side=tk.LEFT, padx=(0, 8))
    else:
        make_button(actions, f"Import {len(player_records)} Game(s)",
                    confirm_import_all, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(actions, "Cancel", review_window.destroy).pack(side=tk.LEFT)

    review_window.update_idletasks()
    w = review_window.winfo_reqwidth()
    h = review_window.winfo_reqheight()
    review_window.geometry(f"{w}x{h}")


def choose_player(records, file_name):
    players = list(dict.fromkeys(record["player"] for record in records))
    if len(players) == 1:
        show_import_review(players[0], records, file_name)
        return

    selection_window = tk.Toplevel(window)
    selection_window.title("Choose a Player")
    selection_window.resizable(False, False)
    selection_window.transient(window)
    selection_window.grab_set()
    selection_window.configure(bg=OFFWHITE)

    hdr = tk.Frame(selection_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="Choose a Player", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)

    body = tk.Frame(selection_window, bg=OFFWHITE, padx=24, pady=16)
    body.pack()

    tk.Label(body, text="Choose the player whose games you want to save.",
             font=(FONT_BODY, 11), bg=OFFWHITE, fg=TEXT_MUTED).pack(pady=(0, 12))

    player_list = tk.Listbox(body, font=(FONT_BODY, 13), width=28,
                              height=min(len(players), 7), exportselection=False,
                              bg=CARD_BG, fg=TEXT, selectbackground=NAVY,
                              selectforeground=AMBER, relief="flat",
                              highlightthickness=1, highlightbackground=BORDER)
    player_list.pack()
    for player in players:
        player_list.insert(tk.END, player)
    player_list.selection_set(0)

    def continue_to_review():
        chosen = player_list.curselection()
        if not chosen:
            messagebox.showwarning("Choose a Player", "Please choose a player first.", parent=selection_window)
            return
        player = players[chosen[0]]
        selected_records = [record for record in records if record["player"] == player]
        selection_window.destroy()
        show_import_review(player, selected_records, file_name)

    actions = tk.Frame(body, bg=OFFWHITE)
    actions.pack(pady=18)
    make_button(actions, "Continue", continue_to_review, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(actions, "Cancel", selection_window.destroy).pack(side=tk.LEFT)


def import_scoresheet():
    file_path = filedialog.askopenfilename(
        title="Choose a Brunswick/Sync Passport Scoresheet",
        filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")],
    )
    if not file_path:
        return
    try:
        records = read_scoresheet(file_path)
    except ValueError as error:
        messagebox.showerror("Could Not Read Scoresheet", str(error))
        return
    if not records:
        messagebox.showerror(
            "No Games Found",
            "No completed player scores were found in that file. "
            "Please choose a Brunswick/Sync Passport HTML scoresheet.",
        )
        return
    choose_player(records, os.path.basename(file_path))


# ---------- INSIGHTS WINDOW ----------

def categorize_frame(throws):
    if not throws:
        return None
    first = str(throws[0]).strip().upper()
    if first == "X":
        return "strike"
    if len(throws) >= 2 and str(throws[1]).strip().upper() == "/":
        return "spare"
    return "open"


def first_ball_pins(mark):
    """Pins knocked down on a first throw mark."""
    if mark is None:
        return None
    m = str(mark).strip().upper()
    if m == "X":
        return 10
    if m in ("-", ""):
        return 0
    try:
        v = int(m)
        if 0 <= v <= 9:
            return v
    except (TypeError, ValueError):
        pass
    return None


def analyze_frames_advanced(frames):
    """Derive advanced frame-level stats from a list of frame dicts.

    Returns a dict, or None if frames is empty/unusable.
    Single-pin vs multi-pin is inferred from first-ball pinfall
    (pins left = 10 - first ball). No separate leave list is required.
    """
    if not frames:
        return None

    strikes = 0
    spares = 0
    opens = 0
    frames_counted = 0
    first_ball_sum = 0
    first_ball_n = 0
    single_pin_opps = 0
    single_pin_made = 0
    multi_pin_opps = 0
    multi_pin_made = 0
    doubles = 0          # consecutive strike pairs (overlapping)
    turkeys = 0          # 3+ consecutive
    four_baggers = 0     # 4+ consecutive
    longest_string = 0
    run = 0
    is_clean = True

    for frame in frames[:10]:
        throws = frame.get("throws", [])
        if not throws:
            continue
        frames_counted += 1
        outcome = categorize_frame(throws)
        first = first_ball_pins(throws[0])
        if first is not None:
            first_ball_sum += first
            first_ball_n += 1

        if outcome == "strike":
            strikes += 1
            run += 1
            longest_string = max(longest_string, run)
            if run >= 2:
                doubles += 1
            if run >= 3:
                turkeys += 1
            if run >= 4:
                four_baggers += 1
        else:
            run = 0
            if outcome == "spare":
                spares += 1
            else:
                opens += 1
                is_clean = False

            # Spare opportunity breakdown by leave size
            if first is not None and first < 10:
                left = 10 - first
                converted = outcome == "spare"
                if left == 1:
                    single_pin_opps += 1
                    if converted:
                        single_pin_made += 1
                elif left >= 2:
                    multi_pin_opps += 1
                    if converted:
                        multi_pin_made += 1

    if frames_counted == 0:
        return None

    return {
        "frames": frames_counted,
        "strikes": strikes,
        "spares": spares,
        "opens": opens,
        "first_ball_sum": first_ball_sum,
        "first_ball_n": first_ball_n,
        "single_pin_opps": single_pin_opps,
        "single_pin_made": single_pin_made,
        "multi_pin_opps": multi_pin_opps,
        "multi_pin_made": multi_pin_made,
        "doubles": doubles,
        "turkeys": turkeys,
        "four_baggers": four_baggers,
        "longest_string": longest_string,
        "is_clean": is_clean and frames_counted >= 10,
    }


def show_insights(parent):
    """Build (or rebuild) the Insights tab's content into `parent`. Called
    fresh every time the Insights tab is selected, so it always reflects
    the current data -- same as the old popup window did on every open."""
    try:
        cursor.execute(
            "SELECT date, score, category, frames, ball, spare_ball, center FROM games ORDER BY date"
        )
        all_rows = cursor.fetchall()
    except sqlite3.Error as error:
        # Older DBs without center column fall back
        try:
            cursor.execute(
                "SELECT date, score, category, frames, ball, spare_ball FROM games ORDER BY date"
            )
            all_rows = [(*row, None) for row in cursor.fetchall()]
        except sqlite3.Error as error2:
            messagebox.showerror("Database Error", f"Could not load games:\n{error2}")
            return

    if not all_rows:
        for widget in parent.winfo_children():
            widget.destroy()
        empty_wrap = tk.Frame(parent, bg=OFFWHITE)
        empty_wrap.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            empty_wrap, text="📊", font=("Arial", 40), bg=OFFWHITE, fg=TEXT_MUTED
        ).pack(pady=(140, 10))
        tk.Label(
            empty_wrap, text="Add some games first to see insights.",
            font=(FONT_BODY, 13), bg=OFFWHITE, fg=TEXT_MUTED,
        ).pack()
        return

    parsed_games = []
    for game_date, score, category, frame_data, ball, spare_ball, center in all_rows:
        d = parse_date_flexible(game_date)
        parsed_games.append({
            "date": d,
            "date_str": to_display_date(game_date),
            "score": int(score) if score is not None else 0,
            "category": category or "Uncategorized",
            "frame_data": frame_data,
            "ball": ball,
            "spare_ball": spare_ball,
            "center": center or None,
            "adv": None,
        })

    all_scores = [g["score"] for g in parsed_games]
    n_games = len(all_scores)
    overall_avg = sum(all_scores) / n_games
    overall_median = statistics.median(all_scores)
    overall_high = max(all_scores)
    overall_low = min(all_scores)
    overall_range = overall_high - overall_low
    overall_stdev = statistics.pstdev(all_scores) if n_games > 1 else 0.0
    overall_cv = (overall_stdev / overall_avg) if overall_avg else 0.0

    # ── Per-game advanced frame analysis ──
    strike_count = spare_count = open_count = 0
    games_with_frames = clean_games = 0
    first_ball_sum = first_ball_n = 0
    single_pin_opps = single_pin_made = 0
    multi_pin_opps = multi_pin_made = 0
    doubles = turkeys = four_baggers = 0
    longest_string_overall = 0
    # Frame-number breakdown (1-10)
    frame_pos = {i: {"strikes": 0, "spares": 0, "opens": 0, "n": 0, "first_sum": 0} for i in range(1, 11)}
    # Per-game frame efficiency series (for consistency of process)
    game_strike_rates = []
    game_spare_rates = []
    game_open_rates = []
    game_first_ball_avgs = []
    game_mark_rates = []
    open_pin_totals = []  # pins scored in open frames (first+second when open)
    gutter_first = 0
    total_first_throws = 0
    tenth_strikes = tenth_spares = tenth_opens = tenth_n = 0

    for g in parsed_games:
        if not g["frame_data"]:
            continue
        try:
            frames = json.loads(g["frame_data"])
        except (TypeError, json.JSONDecodeError):
            continue
        adv = analyze_frames_advanced(frames)
        if adv is None:
            continue
        g["adv"] = adv
        games_with_frames += 1
        strike_count += adv["strikes"]
        spare_count += adv["spares"]
        open_count += adv["opens"]
        if adv["is_clean"]:
            clean_games += 1
        first_ball_sum += adv["first_ball_sum"]
        first_ball_n += adv["first_ball_n"]
        single_pin_opps += adv["single_pin_opps"]
        single_pin_made += adv["single_pin_made"]
        multi_pin_opps += adv["multi_pin_opps"]
        multi_pin_made += adv["multi_pin_made"]
        doubles += adv["doubles"]
        turkeys += adv["turkeys"]
        four_baggers += adv["four_baggers"]
        longest_string_overall = max(longest_string_overall, adv["longest_string"])

        tf = adv["frames"] or 1
        game_strike_rates.append(adv["strikes"] / tf)
        game_open_rates.append(adv["opens"] / tf)
        game_mark_rates.append((adv["strikes"] + adv["spares"]) / tf)
        spare_chances = adv["spares"] + adv["opens"]
        if spare_chances:
            game_spare_rates.append(adv["spares"] / spare_chances)
        if adv["first_ball_n"]:
            game_first_ball_avgs.append(adv["first_ball_sum"] / adv["first_ball_n"])

        # Position-level + open pins + gutters
        for idx, frame in enumerate(frames[:10]):
            throws = frame.get("throws", [])
            if not throws:
                continue
            pos = idx + 1
            outcome = categorize_frame(throws)
            frame_pos[pos]["n"] += 1
            fb = first_ball_pins(throws[0])
            if fb is not None:
                frame_pos[pos]["first_sum"] += fb
                total_first_throws += 1
                if fb == 0:
                    gutter_first += 1
            if outcome == "strike":
                frame_pos[pos]["strikes"] += 1
            elif outcome == "spare":
                frame_pos[pos]["spares"] += 1
            else:
                frame_pos[pos]["opens"] += 1
                # pins in open frame
                pins = 0
                for t in throws[:2]:
                    m = str(t).strip().upper()
                    if m == "X":
                        pins += 10
                    elif m in ("-", ""):
                        pass
                    elif m == "/":
                        pins = 10
                    else:
                        try:
                            pins += int(m)
                        except ValueError:
                            pass
                open_pin_totals.append(min(pins, 9))

            if pos == 10:
                tenth_n += 1
                if outcome == "strike":
                    tenth_strikes += 1
                elif outcome == "spare":
                    tenth_spares += 1
                else:
                    tenth_opens += 1

    total_frames_counted = strike_count + spare_count + open_count
    spare_opportunities = spare_count + open_count
    first_ball_avg = (first_ball_sum / first_ball_n) if first_ball_n else None

    # ── Ball-pair matrix ──
    pair_stats = {}
    for g in parsed_games:
        strike_b = g["ball"]
        spare_b = g.get("spare_ball")
        if not strike_b:
            continue
        if spare_b and spare_b.lower() != strike_b.lower():
            key = (strike_b, spare_b)
        else:
            key = (strike_b, None)
        if key not in pair_stats:
            pair_stats[key] = {"scores": [], "best": 0, "n": 0}
        pair_stats[key]["scores"].append(g["score"])
        pair_stats[key]["best"] = max(pair_stats[key]["best"], g["score"])
        pair_stats[key]["n"] += 1

    # Streaks
    current_streak = longest_streak = run = 0
    for g in parsed_games:
        if g["score"] >= overall_avg:
            run += 1
            longest_streak = max(longest_streak, run)
        else:
            run = 0
    for g in reversed(parsed_games):
        if g["score"] >= overall_avg:
            current_streak += 1
        else:
            break

    # Below-average streak
    current_cold = longest_cold = cold_run = 0
    for g in parsed_games:
        if g["score"] < overall_avg:
            cold_run += 1
            longest_cold = max(longest_cold, cold_run)
        else:
            cold_run = 0
    for g in reversed(parsed_games):
        if g["score"] < overall_avg:
            current_cold += 1
        else:
            break

    cat_stats = {}
    for g in parsed_games:
        cat = g["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"scores": [], "best": 0}
        cat_stats[cat]["scores"].append(g["score"])
        cat_stats[cat]["best"] = max(cat_stats[cat]["best"], g["score"])

    ball_stats = {}
    for g in parsed_games:
        names = []
        if g["ball"]:
            names.append(g["ball"])
        spare = g.get("spare_ball")
        if spare and spare.lower() != (g["ball"] or "").lower():
            names.append(spare)
        for ball in names:
            if ball not in ball_stats:
                ball_stats[ball] = {"scores": [], "best": 0}
            ball_stats[ball]["scores"].append(g["score"])
            ball_stats[ball]["best"] = max(ball_stats[ball]["best"], g["score"])

    center_stats = {}
    for g in parsed_games:
        c = g.get("center") or "Unknown"
        if c not in center_stats:
            center_stats[c] = {"scores": []}
        center_stats[c]["scores"].append(g["score"])

    # Day of week / month
    dow_stats = {i: [] for i in range(7)}
    month_stats = {i: [] for i in range(1, 13)}
    for g in parsed_games:
        if g["date"]:
            dow_stats[g["date"].weekday()].append(g["score"])
            month_stats[g["date"].month].append(g["score"])

    # Same-day series (multi-game sessions)
    by_date = {}
    for g in parsed_games:
        if not g["date"]:
            continue
        by_date.setdefault(g["date"], []).append(g["score"])
    series_sessions = {k: v for k, v in by_date.items() if len(v) >= 2}
    series_game1 = [v[0] for v in series_sessions.values()]
    series_last = [v[-1] for v in series_sessions.values()]
    series_mid = []
    for v in series_sessions.values():
        if len(v) >= 3:
            series_mid.extend(v[1:-1])

    # Milestone counts
    n_200 = sum(1 for s in all_scores if s >= 200)
    n_220 = sum(1 for s in all_scores if s >= 220)
    n_250 = sum(1 for s in all_scores if s >= 250)
    n_279 = sum(1 for s in all_scores if s >= 279)
    n_300 = sum(1 for s in all_scores if s == 300)
    n_under_100 = sum(1 for s in all_scores if s < 100)
    n_100_149 = sum(1 for s in all_scores if 100 <= s < 150)
    n_150_179 = sum(1 for s in all_scores if 150 <= s < 180)
    n_180_199 = sum(1 for s in all_scores if 180 <= s < 200)

    within_10 = sum(1 for s in all_scores if abs(s - overall_avg) <= 10)
    within_15 = sum(1 for s in all_scores if abs(s - overall_avg) <= 15)
    within_20 = sum(1 for s in all_scores if abs(s - overall_avg) <= 20)
    above_avg = sum(1 for s in all_scores if s >= overall_avg)
    below_avg = n_games - above_avg

    # Quartiles / IQR
    sorted_scores = sorted(all_scores)
    def _pctile(p):
        if not sorted_scores:
            return 0
        k = (len(sorted_scores) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_scores[int(k)]
        return sorted_scores[f] * (c - k) + sorted_scores[c] * (k - f)
    q1 = _pctile(0.25)
    q3 = _pctile(0.75)
    iqr = q3 - q1

    # Rolling averages
    def rolling_avg(window):
        if n_games < 1:
            return None
        w = min(window, n_games)
        return sum(all_scores[-w:]) / w

    # Career halves
    mid = n_games // 2
    first_half = all_scores[:mid] if mid else []
    second_half = all_scores[mid:] if mid else all_scores
    first_half_avg = sum(first_half) / len(first_half) if first_half else None
    second_half_avg = sum(second_half) / len(second_half) if second_half else None

    # Process consistency spreads
    def _stdev(xs):
        return statistics.pstdev(xs) if len(xs) > 1 else 0.0

    strike_rate_stdev = _stdev(game_strike_rates)
    spare_rate_stdev = _stdev(game_spare_rates)
    open_rate_stdev = _stdev(game_open_rates)
    fb_avg_stdev = _stdev(game_first_ball_avgs)

    # ── Content (built directly into the tab frame, not a separate window) ──
    ins = parent
    for widget in ins.winfo_children():
        widget.destroy()

    hdr = tk.Frame(ins, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="📊  Insights", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(hdr, text=f"{n_games} games  ·  avg {overall_avg:.1f}  ·  σ {overall_stdev:.1f}",
             font=(FONT_BODY, 11), bg=NAVY, fg=AMBER).pack(side=tk.LEFT, pady=14)

    notebook = ttk.Notebook(ins)
    notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    style = ttk.Style(ins)
    try:
        style.configure("TNotebook", background=OFFWHITE)
        style.configure("TNotebook.Tab", font=(FONT_BODY, 11, "bold"), padding=[14, 6])
    except Exception:
        pass

    overview_tab = tk.Frame(notebook, bg=OFFWHITE)
    advanced_tab = tk.Frame(notebook, bg=OFFWHITE)
    notebook.add(overview_tab, text="  Overview  ")
    notebook.add(advanced_tab, text="  Advanced  ")

    def make_scrollable(parent):
        canvas_outer = tk.Canvas(parent, bg=OFFWHITE, highlightthickness=0)
        body_scroll = tk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas_outer.yview)
        canvas_outer.configure(yscrollcommand=body_scroll.set)
        body_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_outer.pack(fill=tk.BOTH, expand=True)
        body = tk.Frame(canvas_outer, bg=OFFWHITE, padx=20, pady=16)
        canvas_win = canvas_outer.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(event):
            canvas_outer.configure(scrollregion=canvas_outer.bbox("all"))

        def _on_canvas_configure(event):
            canvas_outer.itemconfig(canvas_win, width=event.width)

        body.bind("<Configure>", _on_body_configure)
        canvas_outer.bind("<Configure>", _on_canvas_configure)
        return canvas_outer, body

    ov_canvas, ov_body = make_scrollable(overview_tab)
    adv_canvas, adv_body = make_scrollable(advanced_tab)

    def _on_mousewheel(event):
        # scroll the active sub-tab's canvas
        try:
            tab = notebook.index(notebook.select())
        except Exception:
            tab = 0
        target = ov_canvas if tab == 0 else adv_canvas
        if hasattr(event, "delta") and event.delta:
            target.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif getattr(event, "num", None) in (4, 5):
            target.yview_scroll(-1 if event.num == 4 else 1, "units")

    # This tab is now permanent (not a window that gets destroyed), so the
    # scroll wheel is only captured while the pointer is actually over this
    # tab's content -- bound on hover, released when the pointer leaves --
    # instead of being grabbed globally for the app's whole lifetime.
    def _bind_scroll(event=None):
        ins.bind_all("<MouseWheel>", _on_mousewheel)
        ins.bind_all("<Button-4>", _on_mousewheel)
        ins.bind_all("<Button-5>", _on_mousewheel)

    def _unbind_scroll(event=None):
        ins.unbind_all("<MouseWheel>")
        ins.unbind_all("<Button-4>")
        ins.unbind_all("<Button-5>")

    ins.bind("<Enter>", _bind_scroll)
    ins.bind("<Leave>", _unbind_scroll)

    def section_label(parent, text):
        tk.Label(parent, text=text, font=(FONT_BODY, 9, "bold"),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(14, 6))

    def pct_card(parent, label, count, total, color, note=None):
        pct = (count / total * 100) if total else 0
        card = tk.Frame(parent, bg=CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER,
                        padx=14, pady=10)
        card.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 4))
        tk.Label(card, text=f"{pct:.1f}%",
                 font=(FONT_BODY, 22, "bold"), bg=CARD_BG, fg=color).pack()
        tk.Label(card, text=label, font=(FONT_BODY, 8, "bold"),
                 bg=CARD_BG, fg=TEXT_MUTED).pack()
        if total:
            tk.Label(card, text=f"{count} / {total}",
                     font=(FONT_BODY, 7), bg=CARD_BG, fg=TEXT_MUTED).pack()
        if note:
            tk.Label(card, text=note, font=(FONT_BODY, 7),
                     bg=CARD_BG, fg=TEXT_MUTED).pack()

    def stat_card(parent, label, value, sub=None, highlight=False):
        card = tk.Frame(parent, bg=NAVY if highlight else CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER,
                        padx=14, pady=10)
        card.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 4))
        tk.Label(card, text=str(value),
                 font=(FONT_BODY, 22, "bold"),
                 bg=NAVY if highlight else CARD_BG,
                 fg=AMBER if highlight else TEXT).pack()
        tk.Label(card, text=label, font=(FONT_BODY, 8, "bold"),
                 bg=NAVY if highlight else CARD_BG,
                 fg="#5B7FA6" if highlight else TEXT_MUTED).pack()
        if sub:
            tk.Label(card, text=sub, font=(FONT_BODY, 7),
                     bg=NAVY if highlight else CARD_BG,
                     fg="#5B7FA6" if highlight else TEXT_MUTED).pack()

    def kv_row(parent, label, value):
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill=tk.X, padx=12, pady=2)
        tk.Label(row, text=label, font=(FONT_BODY, 10),
                 bg=CARD_BG, fg=TEXT_MUTED, width=28, anchor="w").pack(side=tk.LEFT)
        tk.Label(row, text=str(value), font=(FONT_BODY, 10, "bold"),
                 bg=CARD_BG, fg=TEXT, anchor="w").pack(side=tk.LEFT)

    # ══════════════════════════════════════════════════════════════════════════
    # OVERVIEW TAB (existing content, tightened)
    # ══════════════════════════════════════════════════════════════════════════
    body = ov_body

    section_label(body, "STREAK  (games at or above your average)")
    streak_row = tk.Frame(body, bg=OFFWHITE)
    streak_row.pack(fill=tk.X)

    def streak_card(parent, label, value, highlight=False):
        card = tk.Frame(parent, bg=NAVY if highlight else CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER,
                        padx=24, pady=14)
        card.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(card, text=str(value),
                 font=(FONT_BODY, 32, "bold"),
                 bg=NAVY if highlight else CARD_BG,
                 fg=AMBER if highlight else TEXT).pack()
        tk.Label(card, text=label,
                 font=(FONT_BODY, 9, "bold"),
                 bg=NAVY if highlight else CARD_BG,
                 fg="#5B7FA6" if highlight else TEXT_MUTED).pack()

    streak_card(streak_row, "CURRENT STREAK", current_streak, highlight=True)
    streak_card(streak_row, "LONGEST STREAK", longest_streak)
    tk.Label(streak_row,
             text=f"Your average is {overall_avg:.1f}.\nGames at or above that count toward a streak.",
             font=(FONT_BODY, 10), bg=OFFWHITE, fg=TEXT_MUTED,
             justify=tk.LEFT).pack(side=tk.LEFT, padx=(8, 0))

    if games_with_frames > 0 and total_frames_counted > 0:
        section_label(body, "FRAME EFFICIENCY  "
                             f"(from {games_with_frames} of {n_games} games with frame data)")
        pct_row = tk.Frame(body, bg=OFFWHITE)
        pct_row.pack(fill=tk.X)
        pct_card(pct_row, "STRIKE RATE", strike_count, total_frames_counted, AMBER)
        pct_card(pct_row, "SPARE CONVERSION", spare_count, spare_opportunities, GREEN,
                 note="spares made / chances")
        pct_card(pct_row, "OPEN FRAME %", open_count, total_frames_counted, RED)
        pct_card(pct_row, "MARK %", strike_count + spare_count, total_frames_counted, NAVY,
                 note="strikes + spares")

        section_label(body, "CLEAN GAMES & FIRST BALL")
        clean_row = tk.Frame(body, bg=OFFWHITE)
        clean_row.pack(fill=tk.X)
        pct_card(clean_row, "CLEAN GAME %", clean_games, games_with_frames, GREEN,
                 note="no open frames")
        if first_ball_avg is not None:
            stat_card(clean_row, "FIRST-BALL AVG", f"{first_ball_avg:.2f}",
                      sub=f"{first_ball_n} first shots", highlight=True)
        stat_card(clean_row, "CLEAN GAMES", clean_games,
                  sub=f"of {games_with_frames} with frames")

        if single_pin_opps > 0 or multi_pin_opps > 0:
            section_label(body, "SPARE CONVERSION BY LEAVE  "
                                 "(inferred from first-ball pinfall)")
            leave_row = tk.Frame(body, bg=OFFWHITE)
            leave_row.pack(fill=tk.X)
            if single_pin_opps > 0:
                pct_card(leave_row, "SINGLE-PIN SPARES",
                         single_pin_made, single_pin_opps, GREEN, note="1 pin standing")
            if multi_pin_opps > 0:
                pct_card(leave_row, "MULTI-PIN SPARES",
                         multi_pin_made, multi_pin_opps, AMBER, note="2+ pins standing")
            total_leave_opps = single_pin_opps + multi_pin_opps
            total_leave_made = single_pin_made + multi_pin_made
            if total_leave_opps > 0:
                pct_card(leave_row, "ALL SPARES", total_leave_made, total_leave_opps, NAVY)

        section_label(body, "STRIKE STRINGS")
        string_row = tk.Frame(body, bg=OFFWHITE)
        string_row.pack(fill=tk.X)
        stat_card(string_row, "DOUBLES", doubles, sub="2 strikes in a row")
        stat_card(string_row, "TURKEYS", turkeys, sub="3+ in a row")
        stat_card(string_row, "4-BAGGERS+", four_baggers, sub="4+ in a row")
        stat_card(string_row, "LONGEST STRING", longest_string_overall,
                  sub="consecutive strikes", highlight=True)

    if pair_stats:
        section_label(body, "STRIKE BALL × SPARE BALL  (pairings)")
        pair_frame = tk.Frame(body, bg=OFFWHITE)
        pair_frame.pack(fill=tk.X)
        ranked_pairs = sorted(
            pair_stats.items(),
            key=lambda kv: (kv[1]["n"], sum(kv[1]["scores"]) / kv[1]["n"]),
            reverse=True,
        )
        for i, ((strike_b, spare_b), data) in enumerate(ranked_pairs[:12]):
            pair_avg = sum(data["scores"]) / data["n"]
            label = f"{strike_b}" if spare_b is None else f"{strike_b}  +  {spare_b}"
            role = "one ball" if spare_b is None else "strike + spare"
            card = tk.Frame(pair_frame, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER,
                            padx=14, pady=10)
            card.grid(row=i // 2, column=i % 2, padx=(0, 10), pady=(0, 8), sticky="nsew")
            pair_frame.grid_columnconfigure(i % 2, weight=1)
            tk.Label(card, text=label, font=(FONT_BODY, 10, "bold"),
                     bg=CARD_BG, fg=TEXT, wraplength=320, justify=tk.LEFT).pack(anchor="w")
            tk.Label(card, text=str(data["best"]),
                     font=(FONT_BODY, 22, "bold"), bg=CARD_BG, fg=AMBER).pack(anchor="w")
            tk.Label(card,
                     text=f"avg {pair_avg:.1f}  ·  {data['n']} game{'s' if data['n'] != 1 else ''}  ·  {role}",
                     font=(FONT_BODY, 8), bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")

    section_label(body, "PERSONAL BESTS BY CATEGORY")
    bests_frame = tk.Frame(body, bg=OFFWHITE)
    bests_frame.pack(fill=tk.X)
    for i, (cat, data) in enumerate(sorted(cat_stats.items())):
        cat_avg = sum(data["scores"]) / len(data["scores"])
        card = tk.Frame(bests_frame, bg=CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER,
                        padx=16, pady=12)
        card.grid(row=i // 3, column=i % 3, padx=(0, 10), pady=(0, 10), sticky="nsew")
        bests_frame.grid_columnconfigure(i % 3, weight=1)
        tk.Label(card, text=cat, font=(FONT_BODY, 10, "bold"),
                 bg=CARD_BG, fg=TEXT).pack(anchor="w")
        tk.Label(card, text=str(data["best"]),
                 font=(FONT_BODY, 26, "bold"), bg=CARD_BG, fg=AMBER).pack(anchor="w")
        tk.Label(card, text=f"avg {cat_avg:.1f}  ·  {len(data['scores'])} games",
                 font=(FONT_BODY, 9), bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")

    if ball_stats:
        section_label(body, "PERSONAL BESTS BY BALL")
        ball_frame = tk.Frame(body, bg=OFFWHITE)
        ball_frame.pack(fill=tk.X)
        for i, (ball, data) in enumerate(sorted(ball_stats.items())):
            ball_avg = sum(data["scores"]) / len(data["scores"])
            card = tk.Frame(ball_frame, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER,
                            padx=16, pady=12)
            card.grid(row=i // 3, column=i % 3, padx=(0, 10), pady=(0, 10), sticky="nsew")
            ball_frame.grid_columnconfigure(i % 3, weight=1)
            tk.Label(card, text=ball, font=(FONT_BODY, 10, "bold"),
                     bg=CARD_BG, fg=TEXT).pack(anchor="w")
            tk.Label(card, text=str(data["best"]),
                     font=(FONT_BODY, 26, "bold"), bg=CARD_BG, fg=AMBER).pack(anchor="w")
            tk.Label(card, text=f"avg {ball_avg:.1f}  ·  {len(data['scores'])} games",
                     font=(FONT_BODY, 9), bg=CARD_BG, fg=TEXT_MUTED).pack(anchor="w")

    section_label(body, "SCORE TREND  (all games, chronological)")
    CHART_W, CHART_H = 740, 180
    PAD_L, PAD_R, PAD_T, PAD_B = 48, 16, 16, 32
    chart_frame = tk.Frame(body, bg=CARD_BG,
                           highlightthickness=1, highlightbackground=BORDER)
    chart_frame.pack(fill=tk.X, pady=(0, 8))
    canvas = tk.Canvas(chart_frame, width=CHART_W, height=CHART_H,
                       bg=CARD_BG, highlightthickness=0)
    canvas.pack()
    plot_scores = all_scores
    n = len(plot_scores)
    lo, hi = min(plot_scores), max(plot_scores)
    score_range = hi - lo if hi != lo else 1

    def sx(i):
        return PAD_L + (i / max(n - 1, 1)) * (CHART_W - PAD_L - PAD_R)

    def sy(s):
        return PAD_T + (1 - (s - lo) / score_range) * (CHART_H - PAD_T - PAD_B)

    for val in [lo, (lo + hi) // 2, hi]:
        y = sy(val)
        canvas.create_line(PAD_L, y, CHART_W - PAD_R, y, fill=BORDER, dash=(4, 4))
        canvas.create_text(PAD_L - 6, y, text=str(val),
                           font=(FONT_BODY, 8), fill=TEXT_MUTED, anchor="e")
    avg_y = sy(overall_avg)
    canvas.create_line(PAD_L, avg_y, CHART_W - PAD_R, avg_y, fill=AMBER, dash=(6, 3), width=1)
    if n > 1:
        points = [(sx(i), sy(s)) for i, s in enumerate(plot_scores)]
        flat = [coord for pt in points for coord in pt]
        canvas.create_line(*flat, fill=NAVY, width=2, smooth=True)
    tooltip_label = tk.Label(chart_frame, font=(FONT_BODY, 9, "bold"),
                              bg=NAVY, fg=WHITE, padx=6, pady=3, relief="flat")

    def make_hover(i, x, y, score, gdate):
        def enter(e):
            tooltip_label.config(text=f"{score}  {gdate}")
            tooltip_label.place(x=min(x + 8, CHART_W - 80), y=max(y - 22, 4))
        def leave(e):
            tooltip_label.place_forget()
        return enter, leave

    for i, (score_val, game) in enumerate(zip(plot_scores, parsed_games)):
        x, y = sx(i), sy(score_val)
        color = GREEN if score_val >= overall_avg else RED
        dot = canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                                  fill=color, outline=CARD_BG, width=1)
        enter_cb, leave_cb = make_hover(i, x, y, score_val, game["date_str"])
        canvas.tag_bind(dot, "<Enter>", enter_cb)
        canvas.tag_bind(dot, "<Leave>", leave_cb)

    label_indices = sorted(set([0, n - 1] + [n // 4, n // 2, 3 * n // 4]))
    for i in label_indices:
        if 0 <= i < n:
            canvas.create_text(sx(i), CHART_H - PAD_B + 10,
                               text=parsed_games[i]["date_str"],
                               font=(FONT_BODY, 7), fill=TEXT_MUTED)

    legend = tk.Frame(body, bg=OFFWHITE)
    legend.pack(anchor="w", pady=(2, 16))
    for color, label in [(GREEN, "At/above avg"), (RED, "Below avg"), (AMBER, "Your average")]:
        tk.Frame(legend, bg=color, width=10, height=10).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(legend, text=label, font=(FONT_BODY, 9),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 16))

    # ══════════════════════════════════════════════════════════════════════════
    # ADVANCED TAB — wildly detailed
    # ══════════════════════════════════════════════════════════════════════════
    body = adv_body

    section_label(body, "CONSISTENCY  (score distribution)")
    cons_row = tk.Frame(body, bg=OFFWHITE)
    cons_row.pack(fill=tk.X)
    stat_card(cons_row, "STD DEV (σ)", f"{overall_stdev:.1f}",
              sub="lower = steadier", highlight=True)
    stat_card(cons_row, "CV", f"{overall_cv:.1%}",
              sub="σ / average")
    stat_card(cons_row, "MEDIAN", f"{overall_median:.0f}")
    stat_card(cons_row, "IQR", f"{iqr:.0f}",
              sub=f"Q1 {q1:.0f} – Q3 {q3:.0f}")
    stat_card(cons_row, "RANGE", f"{overall_range}",
              sub=f"{overall_low} – {overall_high}")

    cons_row2 = tk.Frame(body, bg=OFFWHITE)
    cons_row2.pack(fill=tk.X, pady=(4, 0))
    pct_card(cons_row2, "WITHIN ±10", within_10, n_games, GREEN, note="of average")
    pct_card(cons_row2, "WITHIN ±15", within_15, n_games, AMBER, note="of average")
    pct_card(cons_row2, "WITHIN ±20", within_20, n_games, NAVY, note="of average")
    pct_card(cons_row2, "ABOVE AVG", above_avg, n_games, GREEN)
    pct_card(cons_row2, "BELOW AVG", below_avg, n_games, RED)

    section_label(body, "HOT & COLD STREAKS")
    hc_row = tk.Frame(body, bg=OFFWHITE)
    hc_row.pack(fill=tk.X)
    stat_card(hc_row, "HOT NOW", current_streak, sub="≥ avg in a row", highlight=True)
    stat_card(hc_row, "LONGEST HOT", longest_streak, sub="≥ avg")
    stat_card(hc_row, "COLD NOW", current_cold, sub="< avg in a row")
    stat_card(hc_row, "LONGEST COLD", longest_cold, sub="< avg")

    section_label(body, "ROLLING FORM")
    roll_row = tk.Frame(body, bg=OFFWHITE)
    roll_row.pack(fill=tk.X)
    for label, w in [("LAST 5", 5), ("LAST 10", 10), ("LAST 20", 20), ("LAST 30", 30)]:
        if n_games >= 1:
            ra = rolling_avg(w)
            sub = f"{min(w, n_games)} games"
            delta = ra - overall_avg
            sign = f"{delta:+.1f} vs career" if n_games >= w else "partial"
            stat_card(roll_row, label, f"{ra:.1f}", sub=f"{sub} · {sign}",
                      highlight=(w == 10))

    if first_half_avg is not None and second_half_avg is not None and mid > 0:
        section_label(body, "CAREER HALVES  (improvement check)")
        half_row = tk.Frame(body, bg=OFFWHITE)
        half_row.pack(fill=tk.X)
        stat_card(half_row, "FIRST HALF AVG", f"{first_half_avg:.1f}",
                  sub=f"{len(first_half)} games")
        stat_card(half_row, "SECOND HALF AVG", f"{second_half_avg:.1f}",
                  sub=f"{len(second_half)} games", highlight=True)
        delta_h = second_half_avg - first_half_avg
        stat_card(half_row, "CHANGE", f"{delta_h:+.1f}",
                  sub="second − first")

    section_label(body, "SCORE BUCKETS")
    bucket_card = tk.Frame(body, bg=CARD_BG,
                           highlightthickness=1, highlightbackground=BORDER)
    bucket_card.pack(fill=tk.X, pady=(0, 4))
    tk.Frame(bucket_card, bg=CARD_BG, height=6).pack()
    for lab, cnt in [
        ("Under 100", n_under_100),
        ("100–149", n_100_149),
        ("150–179", n_150_179),
        ("180–199", n_180_199),
        ("200–219", n_200 - n_220),
        ("220–249", n_220 - n_250),
        ("250–278", n_250 - n_279),
        ("279–299", n_279 - n_300),
        ("300", n_300),
    ]:
        kv_row(bucket_card, lab, f"{cnt}  ({cnt / n_games * 100:.1f}%)")
    tk.Frame(bucket_card, bg=CARD_BG, height=6).pack()

    section_label(body, "MILESTONES")
    ms_row = tk.Frame(body, bg=OFFWHITE)
    ms_row.pack(fill=tk.X)
    for lab, cnt in [("200+", n_200), ("220+", n_220), ("250+", n_250),
                     ("279+", n_279), ("300", n_300)]:
        stat_card(ms_row, lab, cnt, sub=f"{cnt / n_games * 100:.1f}% of games")

    # Process consistency (frame data)
    if games_with_frames >= 2:
        section_label(body, "PROCESS CONSISTENCY  (game-to-game spread of rates)")
        proc_row = tk.Frame(body, bg=OFFWHITE)
        proc_row.pack(fill=tk.X)
        if game_strike_rates:
            stat_card(proc_row, "STRIKE% σ", f"{strike_rate_stdev * 100:.1f}",
                      sub=f"mean {statistics.fmean(game_strike_rates)*100:.1f}%")
        if game_spare_rates:
            stat_card(proc_row, "SPARE% σ", f"{spare_rate_stdev * 100:.1f}",
                      sub=f"mean {statistics.fmean(game_spare_rates)*100:.1f}%")
        if game_open_rates:
            stat_card(proc_row, "OPEN% σ", f"{open_rate_stdev * 100:.1f}",
                      sub=f"mean {statistics.fmean(game_open_rates)*100:.1f}%")
        if game_first_ball_avgs:
            stat_card(proc_row, "1ST-BALL σ", f"{fb_avg_stdev:.2f}",
                      sub=f"mean {statistics.fmean(game_first_ball_avgs):.2f}",
                      highlight=True)
        if game_mark_rates:
            stat_card(proc_row, "MARK% σ", f"{_stdev(game_mark_rates)*100:.1f}",
                      sub=f"mean {statistics.fmean(game_mark_rates)*100:.1f}%")

    if total_frames_counted > 0:
        section_label(body, "FIRST-BALL DETAIL")
        fb_row = tk.Frame(body, bg=OFFWHITE)
        fb_row.pack(fill=tk.X)
        if first_ball_avg is not None:
            stat_card(fb_row, "FIRST-BALL AVG", f"{first_ball_avg:.2f}",
                      sub=f"{first_ball_n} shots", highlight=True)
        if total_first_throws:
            pct_card(fb_row, "GUTTER / ZERO 1ST", gutter_first, total_first_throws, RED,
                     note="first ball 0 pins")
        if open_pin_totals:
            avg_open = sum(open_pin_totals) / len(open_pin_totals)
            stat_card(fb_row, "AVG OPEN FRAME", f"{avg_open:.1f}",
                      sub="pins when open")

        section_label(body, "FRAME POSITION  (strike % by frame number)")
        pos_frame = tk.Frame(body, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        pos_frame.pack(fill=tk.X, pady=(0, 4))
        tk.Frame(pos_frame, bg=CARD_BG, height=6).pack()
        for pos in range(1, 11):
            d = frame_pos[pos]
            if d["n"] == 0:
                continue
            sp = d["strikes"] / d["n"] * 100
            spp = d["spares"] / d["n"] * 100
            op = d["opens"] / d["n"] * 100
            fb = (d["first_sum"] / d["n"]) if d["n"] else 0
            kv_row(pos_frame, f"Frame {pos}",
                   f"X {sp:.0f}%  ·  / {spp:.0f}%  ·  open {op:.0f}%  ·  1st-ball {fb:.1f}  (n={d['n']})")
        tk.Frame(pos_frame, bg=CARD_BG, height=6).pack()

        # Opening vs middle vs closing
        def _band(positions):
            s = o = n = 0
            for p in positions:
                d = frame_pos[p]
                s += d["strikes"]
                o += d["opens"]
                n += d["n"]
            return s, o, n
        open_s, open_o, open_n = _band([1, 2, 3])
        mid_s, mid_o, mid_n = _band([4, 5, 6, 7])
        close_s, close_o, close_n = _band([8, 9, 10])
        section_label(body, "GAME PHASES")
        phase_row = tk.Frame(body, bg=OFFWHITE)
        phase_row.pack(fill=tk.X)
        if open_n:
            pct_card(phase_row, "FRAMES 1–3 STRIKE", open_s, open_n, AMBER)
            pct_card(phase_row, "FRAMES 1–3 OPEN", open_o, open_n, RED)
        if mid_n:
            pct_card(phase_row, "FRAMES 4–7 STRIKE", mid_s, mid_n, AMBER)
        if close_n:
            pct_card(phase_row, "FRAMES 8–10 STRIKE", close_s, close_n, AMBER)
            pct_card(phase_row, "FRAMES 8–10 OPEN", close_o, close_n, RED)

        if tenth_n:
            section_label(body, "10TH FRAME")
            t_row = tk.Frame(body, bg=OFFWHITE)
            t_row.pack(fill=tk.X)
            pct_card(t_row, "10TH STRIKE", tenth_strikes, tenth_n, AMBER)
            pct_card(t_row, "10TH SPARE", tenth_spares, tenth_n, GREEN)
            pct_card(t_row, "10TH OPEN", tenth_opens, tenth_n, RED)

    # Day of week
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if any(dow_stats[i] for i in range(7)):
        section_label(body, "BY DAY OF WEEK")
        dow_card = tk.Frame(body, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER)
        dow_card.pack(fill=tk.X, pady=(0, 4))
        tk.Frame(dow_card, bg=CARD_BG, height=6).pack()
        for i, name in enumerate(dow_names):
            xs = dow_stats[i]
            if not xs:
                continue
            avg = sum(xs) / len(xs)
            sd = _stdev(xs)
            kv_row(dow_card, name,
                   f"avg {avg:.1f}  ·  σ {sd:.1f}  ·  high {max(xs)}  ·  {len(xs)} games")
        tk.Frame(dow_card, bg=CARD_BG, height=6).pack()

    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if any(month_stats[i] for i in range(1, 13)):
        section_label(body, "BY MONTH")
        mon_card = tk.Frame(body, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER)
        mon_card.pack(fill=tk.X, pady=(0, 4))
        tk.Frame(mon_card, bg=CARD_BG, height=6).pack()
        for i in range(1, 13):
            xs = month_stats[i]
            if not xs:
                continue
            avg = sum(xs) / len(xs)
            kv_row(mon_card, month_names[i],
                   f"avg {avg:.1f}  ·  high {max(xs)}  ·  {len(xs)} games")
        tk.Frame(mon_card, bg=CARD_BG, height=6).pack()

    # Series / same-day sessions
    if series_sessions:
        section_label(body, f"MULTI-GAME SESSIONS  ({len(series_sessions)} days with 2+ games)")
        ser_row = tk.Frame(body, bg=OFFWHITE)
        ser_row.pack(fill=tk.X)
        if series_game1:
            stat_card(ser_row, "1ST GAME AVG", f"{sum(series_game1)/len(series_game1):.1f}",
                      sub=f"{len(series_game1)} sessions")
        if series_last:
            stat_card(ser_row, "LAST GAME AVG", f"{sum(series_last)/len(series_last):.1f}",
                      sub="same day", highlight=True)
        if series_game1 and series_last:
            fade = sum(series_last) / len(series_last) - sum(series_game1) / len(series_game1)
            stat_card(ser_row, "SESSION FADE", f"{fade:+.1f}",
                      sub="last − first")
        # Best/worst series totals
        series_totals = [sum(v) for v in series_sessions.values()]
        series_avgs = [sum(v) / len(v) for v in series_sessions.values()]
        if series_avgs:
            stat_card(ser_row, "BEST SESSION AVG", f"{max(series_avgs):.1f}")
            stat_card(ser_row, "WORST SESSION AVG", f"{min(series_avgs):.1f}")

    # Category deep dive
    section_label(body, "CATEGORY DEEP DIVE")
    cat_card = tk.Frame(body, bg=CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER)
    cat_card.pack(fill=tk.X, pady=(0, 4))
    tk.Frame(cat_card, bg=CARD_BG, height=6).pack()
    for cat, data in sorted(cat_stats.items(), key=lambda kv: -len(kv[1]["scores"])):
        xs = data["scores"]
        avg = sum(xs) / len(xs)
        sd = _stdev(xs)
        kv_row(cat_card, cat,
               f"avg {avg:.1f}  ·  σ {sd:.1f}  ·  high {data['best']}  ·  low {min(xs)}  ·  {len(xs)} games")
    tk.Frame(cat_card, bg=CARD_BG, height=6).pack()

    # Center deep dive
    real_centers = {k: v for k, v in center_stats.items() if k != "Unknown"}
    if real_centers:
        section_label(body, "BY BOWLING CENTER")
        cen_card = tk.Frame(body, bg=CARD_BG,
                            highlightthickness=1, highlightbackground=BORDER)
        cen_card.pack(fill=tk.X, pady=(0, 4))
        tk.Frame(cen_card, bg=CARD_BG, height=6).pack()
        for c, data in sorted(real_centers.items(), key=lambda kv: -len(kv[1]["scores"])):
            xs = data["scores"]
            avg = sum(xs) / len(xs)
            sd = _stdev(xs)
            kv_row(cen_card, c,
                   f"avg {avg:.1f}  ·  σ {sd:.1f}  ·  high {max(xs)}  ·  {len(xs)} games")
        tk.Frame(cen_card, bg=CARD_BG, height=6).pack()

    # Ball pair deep dive with stdev
    if pair_stats:
        section_label(body, "BALL PAIRINGS  (with consistency)")
        pair_card = tk.Frame(body, bg=CARD_BG,
                             highlightthickness=1, highlightbackground=BORDER)
        pair_card.pack(fill=tk.X, pady=(0, 4))
        tk.Frame(pair_card, bg=CARD_BG, height=6).pack()
        ranked = sorted(
            pair_stats.items(),
            key=lambda kv: (kv[1]["n"], sum(kv[1]["scores"]) / kv[1]["n"]),
            reverse=True,
        )
        for (strike_b, spare_b), data in ranked[:20]:
            xs = data["scores"]
            avg = sum(xs) / len(xs)
            sd = _stdev(xs)
            label = strike_b if spare_b is None else f"{strike_b} + {spare_b}"
            role = "one ball" if spare_b is None else "dual"
            kv_row(pair_card, label[:40],
                   f"avg {avg:.1f}  ·  σ {sd:.1f}  ·  high {data['best']}  ·  {data['n']} ({role})")
        tk.Frame(pair_card, bg=CARD_BG, height=6).pack()

    # Summary footer
    section_label(body, "NOTES")
    note = tk.Label(
        body,
        text=(
            "All frame stats require imported or frame-edited games. "
            "Single/multi-pin leaves are inferred from first-ball pinfall (not exact pin IDs). "
            "σ is population standard deviation. CV = σ / average. "
            "Session fade uses games logged on the same calendar date."
        ),
        font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED,
        wraplength=820, justify=tk.LEFT,
    )
    note.pack(anchor="w", pady=(0, 20))

    ov_body.update_idletasks()
    adv_body.update_idletasks()
    ov_canvas.configure(scrollregion=ov_canvas.bbox("all"))
    adv_canvas.configure(scrollregion=adv_canvas.bbox("all"))



# ---------- EXPORT / BACKUP ----------

BACKUP_FOLDER = os.path.join(APP_FOLDER, "backups")


def _get_backup_retention():
    """Return the user-configured number of auto-backups to keep (default 5)."""
    try:
        return max(1, int(get_setting("backup_retention", "5")))
    except (ValueError, TypeError):
        return 5


def _prune_old_backups(folder, keep):
    """Delete the oldest auto-backups, keeping only the most recent `keep` files."""
    try:
        files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.startswith("auto_backup_") and f.endswith(".db")
        ]
        files.sort(key=os.path.getmtime)
        for old_file in files[:-keep]:
            try:
                os.remove(old_file)
            except OSError:
                pass
    except OSError:
        pass


def run_auto_backup():
    """Silently copy bowling.db into the backups/ folder on launch.
    Only runs if auto_backup_enabled == '1'. Prunes old backups after."""
    if get_setting("auto_backup_enabled", "0") != "1":
        return
    try:
        os.makedirs(BACKUP_FOLDER, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_FOLDER, f"auto_backup_{timestamp}.db")
        connection.commit()
        shutil.copy2(os.path.join(APP_FOLDER, "bowling.db"), dest)
        _prune_old_backups(BACKUP_FOLDER, _get_backup_retention())
    except OSError:
        pass  # Silently fail — auto-backup should never block the app from opening


def export_to_csv(path=None, silent=False):
    """Export game history to CSV.

    path   — if provided, skip the file dialog and write directly there.
    silent — if True, skip success/failure dialogs (used for auto-export).
    """
    if path is None:
        path = filedialog.asksaveasfilename(
            title="Export Game History",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="bowling_history.csv",
        )
    if not path:
        return False

    try:
        cursor.execute("SELECT date, score, category, center, ball, spare_ball FROM games ORDER BY date")
        rows = cursor.fetchall()
    except sqlite3.Error as error:
        if not silent:
            messagebox.showerror("Database Error", f"Could not load games:\n{error}")
        return False

    if not rows:
        if not silent:
            messagebox.showinfo("Nothing to Export", "There are no games in the tracker yet.")
        return False

    try:
        with open(path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["Date", "Score", "Category", "Center", "Strike Ball", "Spare Ball"])
            for game_date, score, category, center, ball, spare_ball in rows:
                writer.writerow([
                    to_display_date(game_date), score, category or "", center or "",
                    ball or "", spare_ball or "",
                ])
    except OSError as error:
        if not silent:
            messagebox.showerror("Export Failed", f"Could not write the CSV file:\n{error}")
        return False

    if not silent:
        messagebox.showinfo("Export Complete", f"Exported {len(rows)} game(s) to:\n{path}")
    return True


def _get_auto_export_path():
    """Return the configured auto-export CSV path, or None if not set."""
    p = get_setting("auto_export_path", "")
    return p.strip() if p and p.strip() else None


def run_auto_export():
    """Write the CSV to the configured path silently (called on close)."""
    if get_setting("auto_export_enabled", "0") != "1":
        return
    path = _get_auto_export_path()
    if not path:
        return
    export_to_csv(path=path, silent=True)


def backup_database():
    default_name = f"bowling_backup_{date.today().isoformat()}.db"
    file_path = filedialog.asksaveasfilename(
        title="Backup Database",
        defaultextension=".db",
        filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")],
        initialfile=default_name,
    )
    if not file_path:
        return

    try:
        connection.commit()
        shutil.copy2(os.path.join(APP_FOLDER, "bowling.db"), file_path)
    except OSError as error:
        messagebox.showerror("Backup Failed", f"Could not copy the database file:\n{error}")
        return

    messagebox.showinfo("Backup Complete", f"Database backed up to:\n{file_path}")


def open_backup_settings():
    """Settings dialog for auto-backup and auto-export."""
    dlg = tk.Toplevel(window)
    dlg.title("Backup & Data Settings")
    dlg.configure(bg=OFFWHITE)
    dlg.resizable(False, False)
    dlg.transient(window)
    dlg.grab_set()

    hdr = tk.Frame(dlg, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="💾  Backup & Data", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)

    body = tk.Frame(dlg, bg=OFFWHITE, padx=28, pady=20)
    body.pack(fill=tk.BOTH)

    def section_label(text):
        tk.Label(body, text=text, font=(FONT_BODY, 11, "bold"),
                 bg=OFFWHITE, fg=TEXT).pack(anchor="w", pady=(18, 4))

    def muted_label(text):
        tk.Label(body, text=text, font=(FONT_BODY, 9),
                 bg=OFFWHITE, fg=TEXT_MUTED, justify=tk.LEFT).pack(anchor="w", pady=(0, 6))

    def entry_style(width=32):
        return dict(font=(FONT_BODY, 11), width=width, bg=ENTRY_BG, relief="flat",
                    highlightthickness=1, highlightbackground=BORDER, highlightcolor=AMBER)

    # ── Auto-backup ──────────────────────────────────────────────────────────
    section_label("Auto-backup on launch")
    muted_label(
        f"Silently copies the database to a backups/ folder inside the app folder\n"
        f"every time Bowling Tracker opens. Old backups are pruned automatically."
    )

    auto_backup_var = tk.BooleanVar(value=get_setting("auto_backup_enabled", "0") == "1")
    tk.Checkbutton(
        body, text="Enable auto-backup on launch",
        variable=auto_backup_var,
        font=(FONT_BODY, 11), bg=OFFWHITE, fg=TEXT,
        activebackground=OFFWHITE, selectcolor=ENTRY_BG,
    ).pack(anchor="w")

    retention_row = tk.Frame(body, bg=OFFWHITE)
    retention_row.pack(anchor="w", pady=(8, 0))
    tk.Label(retention_row, text="Keep the last", font=(FONT_BODY, 11),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(0, 8))
    retention_entry = tk.Entry(retention_row, **entry_style(4))
    retention_entry.pack(side=tk.LEFT, ipady=4, ipadx=3)
    retention_entry.insert(0, get_setting("backup_retention", "5"))
    tk.Label(retention_row, text="backups", font=(FONT_BODY, 11),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(8, 0))

    # Show the backup folder path for reference
    tk.Label(body, text=f"Backup folder:  {BACKUP_FOLDER}",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(6, 0))

    def open_backup_folder():
        try:
            os.makedirs(BACKUP_FOLDER, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(BACKUP_FOLDER)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", BACKUP_FOLDER])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", BACKUP_FOLDER])
        except Exception as e:
            messagebox.showwarning("Could Not Open Folder", str(e), parent=dlg)

    make_secondary_button(body, "📂  Open backup folder", open_backup_folder).pack(
        anchor="w", pady=(6, 0)
    )

    tk.Frame(body, bg=BORDER, height=1).pack(fill=tk.X, pady=(20, 0))

    # ── Auto-export CSV ──────────────────────────────────────────────────────
    section_label("Auto-export CSV on close")
    muted_label(
        "Writes a CSV of your game history to a fixed file path every time\n"
        "the app closes. Useful for keeping a spreadsheet automatically in sync."
    )

    auto_export_var = tk.BooleanVar(value=get_setting("auto_export_enabled", "0") == "1")
    tk.Checkbutton(
        body, text="Enable auto-export on close",
        variable=auto_export_var,
        font=(FONT_BODY, 11), bg=OFFWHITE, fg=TEXT,
        activebackground=OFFWHITE, selectcolor=ENTRY_BG,
    ).pack(anchor="w")

    path_row = tk.Frame(body, bg=OFFWHITE)
    path_row.pack(fill=tk.X, pady=(8, 0))
    tk.Label(path_row, text="Save CSV to:", font=(FONT_BODY, 11),
             bg=OFFWHITE, fg=TEXT).pack(anchor="w")

    path_entry_row = tk.Frame(body, bg=OFFWHITE)
    path_entry_row.pack(fill=tk.X, pady=(4, 0))
    export_path_var = tk.StringVar(value=get_setting("auto_export_path", ""))
    export_path_entry = tk.Entry(path_entry_row, textvariable=export_path_var, **entry_style(34))
    export_path_entry.pack(side=tk.LEFT, ipady=4, ipadx=3, padx=(0, 8))

    def browse_export_path():
        chosen = filedialog.asksaveasfilename(
            parent=dlg,
            title="Choose auto-export CSV path",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="bowling_history.csv",
        )
        if chosen:
            export_path_var.set(chosen)

    make_secondary_button(path_entry_row, "Browse…", browse_export_path).pack(side=tk.LEFT)

    tk.Frame(body, bg=BORDER, height=1).pack(fill=tk.X, pady=(20, 0))

    # ── Save ─────────────────────────────────────────────────────────────────
    def save_backup_settings():
        # Validate retention count
        retention_text = retention_entry.get().strip()
        try:
            retention = int(retention_text)
            if retention < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid Value",
                                   "Backup retention must be a whole number of 1 or more.",
                                   parent=dlg)
            return

        # Validate export path if auto-export is enabled
        export_path = export_path_var.get().strip()
        if auto_export_var.get() and not export_path:
            messagebox.showwarning("Missing Path",
                                   "Please enter or browse to a CSV file path for auto-export.",
                                   parent=dlg)
            return

        set_setting("auto_backup_enabled", "1" if auto_backup_var.get() else "0")
        set_setting("backup_retention", str(retention))
        set_setting("auto_export_enabled", "1" if auto_export_var.get() else "0")
        set_setting("auto_export_path", export_path)

        dlg.destroy()
        messagebox.showinfo("Settings Saved",
                            "Backup & Data settings saved.\n\n"
                            + ("Auto-backup will run next time the app opens.\n" if auto_backup_var.get() else "")
                            + ("Auto-export will run the next time the app closes." if auto_export_var.get() else ""))

    btn_row = tk.Frame(body, bg=OFFWHITE)
    btn_row.pack(pady=(20, 4))
    make_button(btn_row, "Save", save_backup_settings, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(btn_row, "Cancel", dlg.destroy).pack(side=tk.LEFT)

    dlg.update_idletasks()
    dlg.geometry(f"{dlg.winfo_reqwidth()}x{dlg.winfo_reqheight()}")


def clear_all_data():
    """Wipe games and arsenal so the user can start fresh (e.g. after exploring example data)."""
    try:
        cursor.execute("SELECT COUNT(*) FROM games")
        n_games = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM balls")
        n_balls = cursor.fetchone()[0]
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not read the database:\n{error}")
        return

    if n_games == 0 and n_balls == 0:
        messagebox.showinfo("Nothing to Clear", "There are no games or arsenal balls to clear.")
        return

    warn = messagebox.askyesno(
        "Clear All Data?",
        "This permanently deletes:\n\n"
        f"  • {n_games} game(s)\n"
        f"  • {n_balls} arsenal ball(s)\n\n"
        "If you are looking at EXAMPLE data that shipped with the app, "
        "this is how you wipe it before logging your own scores.\n\n"
        "Export CSV or Backup DB first if you might want this data later.\n\n"
        "This cannot be undone. Continue?",
        icon="warning",
    )
    if not warn:
        return

    confirm = messagebox.askyesno(
        "Confirm Clear All Data",
        "Final confirmation:\n\n"
        "Delete ALL games and arsenal balls now?\n\n"
        "Type-style check: only click Yes if you are sure.",
        icon="warning",
    )
    if not confirm:
        return

    try:
        cursor.execute("DELETE FROM games")
        cursor.execute("DELETE FROM balls")
        # Keep approved_balls (USBC reference) and app_settings (tutorial flag, etc.)
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        messagebox.showerror("Database Error", f"Could not clear data:\n{error}")
        return

    refresh_center_filter_options()
    refresh_ball_filter_options()
    refresh_ball_choices()
    update_history_display()
    messagebox.showinfo(
        "Data Cleared",
        "All games and arsenal balls have been removed.\n\n"
        "You have a clean slate — add a game or import a scoresheet to begin.",
    )
# ---------- SHUTDOWN ----------

def on_close():
    try:
        connection.close()
    except sqlite3.Error:
        pass
    window.destroy()


def restart_app():
    """Close the DB connection and relaunch the app in-place (used after
    toggling Night Mode, since the color theme is picked at startup)."""
    try:
        connection.close()
    except sqlite3.Error:
        pass
    python = sys.executable
    os.execl(python, python, os.path.abspath(__file__), *sys.argv[1:])



# ---------- TUTORIAL ----------

TUTORIAL_STEPS = [
    {
        "title": "Welcome to Bowling Tracker",
        "body": (
            "This quick tour shows the main parts of the app.\n\n"
            "IMPORTANT: Any games and balls you see right now are EXAMPLE DATA — "
            "a simulated ~190-average bowler so you can explore the app.\n\n"
            "It is not your real history. At the end of this tour you will see how "
            "to clear all example data with one click.\n\n"
            "You can skip anytime and reopen the tutorial later from Help (top right)."
        ),
        "hint": "Example data is only for learning the app. Clear it before logging real games.",
    },
    {
        "title": "Add a Game",
        "body": (
            "Use the ADD GAME card at the top:\n\n"
            "  • Date — defaults to today (MM/DD/YYYY)\n"
            "  • Score — 0 to 300\n"
            "  • Category — practice, league, tournament, etc.\n"
            "  • Strike ball — the ball you throw for strikes\n"
            "  • Spare ball — optional follow-up when you leave pins\n\n"
            "Click Add Game to save. Your totals in the header update immediately."
        ),
        "hint": "Leave spare ball blank if you used one ball the whole game.",
    },
    {
        "title": "Import a Scoresheet",
        "body": (
            "Click Import Scoresheet to load a Brunswick / Sync Passport HTML file "
            "from your bowling center.\n\n"
            "You'll pick the player name, set a category, and optionally assign "
            "strike and spare balls for every game in the file.\n\n"
            "Imported games include frame-by-frame data, which unlocks richer stats."
        ),
        "hint": "Duplicate games (same date, score, and center) can be skipped on import.",
    },
    {
        "title": "Game History & Filters",
        "body": (
            "The GAME HISTORY list is your full log.\n\n"
            "Filter by category, center, ball, or time frame. Click column headers "
            "to sort by date, score, category, or ball.\n\n"
            "Select one game to edit or view frames — or select several for batch edit."
        ),
        "hint": "Ball filter matches either strike or spare ball.",
    },
    {
        "title": "Edit, Frames & Delete",
        "body": (
            "Bottom-left action buttons:\n\n"
            "  • Edit — change date, score, category, or balls\n"
            "  • Frame Details — see each frame's marks\n"
            "  • Edit Frame-by-Frame — fix a throw; score recalculates\n"
            "  • Delete — remove one or more selected games\n\n"
            "Games with frame data keep score locked until you edit frames."
        ),
        "hint": "Hold Ctrl/Cmd to multi-select games for batch edit or delete.",
    },
    {
        "title": "Ball Arsenal",
        "body": (
            "Open Arsenal (top-right header) to manage the balls you own.\n\n"
            "Add balls manually or pick from the USBC approved list. Each ball shows "
            "live stats from games where it was the strike ball, spare ball, or both — "
            "including strike rate, spare conversion, and first-ball average."
        ),
        "hint": "Keep usbc_approved_balls.csv next to the app so the USBC picker can load.",
    },
    {
        "title": "Insights & Analytics",
        "body": (
            "Open Insights for a full breakdown of your bowling.\n\n"
            "  • Overview — streaks, frame efficiency, clean games, strike strings, "
            "ball pairings, personal bests, and a score trend chart\n"
            "  • Advanced — consistency (σ, CV), rolling form, score buckets, "
            "frame-by-frame position stats, day/month splits, centers, and more\n\n"
            "Frame-heavy stats need imported or frame-edited games."
        ),
        "hint": "The header average and high/low always reflect the current history filter.",
    },
    {
        "title": "Export, Backup & Clear",
        "body": (
            "Protect — or reset — your data from the bottom DATA row:\n\n"
            "  • Export CSV — spreadsheet of dates, scores, categories, centers, balls\n"
            "  • Backup DB — copy of bowling.db you can restore later\n"
            "  • Clear All Data — permanently deletes all games and arsenal balls\n\n"
            "Use Clear All Data after exploring EXAMPLE data, or anytime you want a clean slate.\n"
            "You will be asked to confirm twice."
        ),
        "hint": "Always backup before clearing if the data might matter later.",
    },
    {
        "title": "You're Ready — Clear Example Data",
        "body": (
            "That's the tour.\n\n"
            ">>> THIS HISTORY IS EXAMPLE DATA <<<\n"
            "The games, scores, centers, and arsenal balls included with the app "
            "are simulated so you can click around safely. They are NOT your scores.\n\n"
            "When you are done exploring, clear them:\n\n"
            "  1. Look at the bottom DATA row\n"
            "  2. Click  Clear All Data  (next to Backup DB)\n"
            "  3. Confirm twice — everything is wiped\n\n"
            "Help, Arsenal, and Insights stay in the top-right header.\n\n"
            "Then add your own games or import a scoresheet.\n\n"
            "You can replay this tutorial anytime from Help."
        ),
        "hint": "Clear All Data removes all games and arsenal balls. Export or backup first if you want to keep anything.",
    },
]

# (get_setting / set_setting are defined near the top of the file, before
# the design tokens, so the saved theme can be picked before any widget builds.)


def show_tutorial(force=False):
    """Interactive first-run tour. force=True replays even if already completed."""
    if not force and get_setting("tutorial_completed") == "1":
        return

    dlg = tk.Toplevel(window)
    dlg.title("Tutorial")
    dlg.configure(bg=OFFWHITE)
    dlg.resizable(False, False)
    dlg.transient(window)
    dlg.grab_set()

    step_index = [0]

    hdr = tk.Frame(dlg, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="🎳  Getting Started", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    step_lbl = tk.Label(hdr, text="", font=(FONT_BODY, 11), bg=NAVY, fg=AMBER)
    step_lbl.pack(side=tk.RIGHT, padx=20, pady=14)

    body = tk.Frame(dlg, bg=OFFWHITE, padx=28, pady=20)
    body.pack(fill=tk.BOTH)

    title_lbl = tk.Label(body, text="", font=(FONT_BODY, 16, "bold"),
                         bg=OFFWHITE, fg=TEXT, anchor="w", justify=tk.LEFT)
    title_lbl.pack(anchor="w", pady=(0, 10))

    body_lbl = tk.Label(body, text="", font=(FONT_BODY, 11),
                        bg=OFFWHITE, fg=TEXT, anchor="w", justify=tk.LEFT,
                        wraplength=460)
    body_lbl.pack(anchor="w")

    hint_frame = tk.Frame(body, bg=INFO_BG, highlightthickness=1,
                          highlightbackground="#BFDBFE")
    hint_frame.pack(fill=tk.X, pady=(16, 0))
    hint_lbl = tk.Label(hint_frame, text="", font=(FONT_BODY, 10),
                        bg=INFO_BG, fg=TEXT_MUTED, anchor="w", justify=tk.LEFT,
                        wraplength=440)
    hint_lbl.pack(padx=12, pady=10, anchor="w")

    # Progress dots
    dots = tk.Frame(body, bg=OFFWHITE)
    dots.pack(anchor="w", pady=(18, 0))
    dot_labels = []
    for i in range(len(TUTORIAL_STEPS)):
        d = tk.Label(dots, text="●", font=(FONT_BODY, 10), bg=OFFWHITE, fg=BORDER)
        d.pack(side=tk.LEFT, padx=2)
        dot_labels.append(d)

    btn_row = tk.Frame(body, bg=OFFWHITE)
    btn_row.pack(fill=tk.X, pady=(22, 4))

    def finish(completed=True):
        if completed:
            set_setting("tutorial_completed", "1")
        dlg.grab_release()
        dlg.destroy()

    def render():
        i = step_index[0]
        step = TUTORIAL_STEPS[i]
        step_lbl.config(text=f"{i + 1} / {len(TUTORIAL_STEPS)}")
        title_lbl.config(text=step["title"])
        body_lbl.config(text=step["body"])
        hint_lbl.config(text=step.get("hint") or "")
        if step.get("hint"):
            hint_frame.pack(fill=tk.X, pady=(16, 0))
        else:
            hint_frame.pack_forget()
        for di, d in enumerate(dot_labels):
            d.config(fg=AMBER if di == i else (NAVY if di < i else BORDER))
        back_btn.config(state="normal" if i > 0 else "disabled")
        if i >= len(TUTORIAL_STEPS) - 1:
            next_btn.config(text="Done")
        else:
            next_btn.config(text="Next")

    def go_next():
        if step_index[0] >= len(TUTORIAL_STEPS) - 1:
            finish(True)
            return
        step_index[0] += 1
        render()

    def go_back():
        if step_index[0] > 0:
            step_index[0] -= 1
            render()

    skip_btn = make_secondary_button(btn_row, "Skip tutorial", lambda: finish(True))
    skip_btn.pack(side=tk.LEFT)

    next_btn = make_button(btn_row, "Next", go_next, primary=True)
    next_btn.pack(side=tk.RIGHT)
    back_btn = make_button(btn_row, "Back", go_back)
    back_btn.pack(side=tk.RIGHT, padx=(0, 8))

    dlg.protocol("WM_DELETE_WINDOW", lambda: finish(True))
    render()

    dlg.update_idletasks()
    w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
    # Center on parent
    try:
        px = window.winfo_rootx() + (window.winfo_width() - w) // 2
        py = window.winfo_rooty() + (window.winfo_height() - h) // 2
        dlg.geometry(f"+{max(px, 40)}+{max(py, 40)}")
    except Exception:
        pass
    dlg.focus_set()


def maybe_show_tutorial():
    """Show tutorial once after the main window is visible."""
    if get_setting("tutorial_completed") == "1":
        return
    show_tutorial(force=False)


# ══════════════════════════════════════
# HELPER: STYLED WIDGETS
# ══════════════════════════════════════
#
# NOTE: native tk.Button / tk.OptionMenu widgets ignore custom bg/fg colors
# on some platforms (notably macOS Aqua), which is why buttons and dropdowns
# were showing up white regardless of theme. These helpers use Label-based
# "flat" widgets instead, which reliably respect the color settings below.

def _make_flat_button(parent, text, command, bg, fg, active_bg, font,
                       padx=18, pady=7, border_color=None):
    btn = tk.Label(
        parent, text=text, font=font, bg=bg, fg=fg,
        padx=padx, pady=pady, cursor="hand2", borderwidth=0,
    )
    if border_color:
        btn.config(highlightthickness=1, highlightbackground=border_color)

    # Keep a handle to the REAL Label.configure before we shadow it below,
    # or _config would end up calling itself forever.
    _real_configure = btn.configure

    _state = {"enabled": True}

    def _enter(event):
        if _state["enabled"]:
            _real_configure(bg=active_bg)

    def _leave(event):
        if _state["enabled"]:
            _real_configure(bg=bg)

    def _click(event):
        if _state["enabled"] and command:
            command()

    btn.bind("<Enter>", _enter)
    btn.bind("<Leave>", _leave)
    btn.bind("<Button-1>", _click)

    def _config(**kwargs):
        if "state" in kwargs:
            state = kwargs.pop("state")
            _state["enabled"] = state != "disabled"
            _real_configure(bg=bg, fg=fg if _state["enabled"] else TEXT_MUTED,
                            cursor="hand2" if _state["enabled"] else "arrow")
        if kwargs:
            _real_configure(**kwargs)

    btn.config = _config
    btn.configure = _config
    return btn


def make_button(parent, text, command, primary=False, danger=False):
    if primary:
        bg, fg, abg = AMBER, NAVY, "#D97706"
    elif danger:
        bg, fg, abg = RED, WHITE, "#B91C1C"
    else:
        bg, fg, abg = BTN_BG, TEXT, BTN_ACTIVE

    return _make_flat_button(
        parent, text, command, bg, fg, abg,
        font=(FONT_BODY, 11, "bold"), padx=18, pady=7,
    )


def make_secondary_button(parent, text, command):
    return _make_flat_button(
        parent, text, command, OFFWHITE, TEXT_MUTED, BORDER,
        font=(FONT_BODY, 10), padx=14, pady=6, border_color=BORDER,
    )


class FlatOptionMenu(tk.Frame):
    """A dropdown that behaves like tk.OptionMenu but is built from Labels
    and a popup Menu, so it stays fully themed (native OptionMenu ignores
    custom colors on some platforms)."""

    def __init__(self, parent, variable, options, command=None, width=None):
        super().__init__(parent, bg=ENTRY_BG, highlightthickness=1,
                          highlightbackground=BORDER)
        self.variable = variable
        self.options = list(options)
        self.command = command
        self._enabled = True
        self._font = (FONT_BODY, 11)

        self.text_label = tk.Label(
            self, textvariable=variable, font=self._font,
            bg=ENTRY_BG, fg=TEXT, anchor="w", padx=10, pady=5, cursor="hand2",
        )
        if width:
            self.text_label.config(width=width)
        self.text_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.arrow_label = tk.Label(
            self, text="▾", font=self._font, bg=ENTRY_BG, fg=TEXT,
            padx=8, pady=5, cursor="hand2",
        )
        self.arrow_label.pack(side=tk.LEFT)

        self.menu = tk.Menu(
            self, tearoff=0, font=self._font,
            bg=CARD_BG, fg=TEXT,
            activebackground=NAVY, activeforeground=WHITE,
        )
        self._build_menu()

        for widget in (self, self.text_label, self.arrow_label):
            widget.bind("<Button-1>", self._popup)

    def _build_menu(self):
        self.menu.delete(0, "end")
        for opt in self.options:
            self.menu.add_command(label=opt, command=lambda o=opt: self._select(o))

    def _select(self, value):
        self.variable.set(value)
        if self.command:
            self.command(value)

    def _popup(self, event=None):
        if not self._enabled:
            return
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def config(self, **kwargs):
        if "state" in kwargs:
            state = kwargs.pop("state")
            self._enabled = state != "disabled"
            fg = TEXT if self._enabled else TEXT_MUTED
            cursor = "hand2" if self._enabled else "arrow"
            self.text_label.config(fg=fg, cursor=cursor)
            self.arrow_label.config(fg=fg, cursor=cursor)
        if "width" in kwargs:
            self.text_label.config(width=kwargs.pop("width"))
        if kwargs:
            super().config(**kwargs)

    configure = config


def make_dropdown(parent, variable, options, command=None, width=None):
    """Themed replacement for style_dropdown(tk.OptionMenu(...))."""
    return FlatOptionMenu(parent, variable, options, command=command, width=width)


# ══════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════

window = tk.Tk()
window.title("Bowling Tracker")
window.geometry("1100x760")
window.minsize(960, 640)
window.resizable(True, True)
window.protocol("WM_DELETE_WINDOW", on_close)
window.configure(bg=OFFWHITE)

# ttk widgets (Combobox, Notebook) ignore plain tk bg options, so they need
# their own style config or they stay white even in Night Mode.
_ttk_style = ttk.Style(window)
try:
    _ttk_style.theme_use("clam")
except Exception:
    pass
try:
    _ttk_style.configure(
        "TCombobox",
        fieldbackground=ENTRY_BG,
        background=ENTRY_BG,
        foreground=TEXT,
        arrowcolor=TEXT,
        selectbackground=ENTRY_BG,
        selectforeground=TEXT,
    )
    _ttk_style.map(
        "TCombobox",
        fieldbackground=[("readonly", ENTRY_BG), ("disabled", ENTRY_BG)],
        foreground=[("readonly", TEXT), ("disabled", TEXT_MUTED)],
        background=[("readonly", ENTRY_BG), ("disabled", ENTRY_BG)],
    )
    window.option_add("*TCombobox*Listbox.background", CARD_BG)
    window.option_add("*TCombobox*Listbox.foreground", TEXT)
    window.option_add("*TCombobox*Listbox.selectBackground", NAVY)
    window.option_add("*TCombobox*Listbox.selectForeground", WHITE)
except Exception:
    pass


# ── SCOREBOARD HEADER ─────────────────────────────────────────────────────────

scoreboard = tk.Frame(window, bg=NAVY, height=110)
scoreboard.pack(fill=tk.X)
scoreboard.pack_propagate(False)

brand_frame = tk.Frame(scoreboard, bg=NAVY)
brand_frame.pack(side=tk.LEFT, padx=(24, 0))
tk.Label(brand_frame, text="🎳", font=("Arial", 26),
         bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=(0, 10))
title_stack = tk.Frame(brand_frame, bg=NAVY)
title_stack.pack(side=tk.LEFT)
tk.Label(title_stack, text="BOWLING", font=(FONT_BODY, 13, "bold"),
         bg=NAVY, fg=AMBER, anchor="w").pack(anchor="w")
tk.Label(title_stack, text="TRACKER", font=(FONT_BODY, 9),
         bg=NAVY, fg="#5B7FA6", anchor="w").pack(anchor="w")

tk.Frame(scoreboard, bg=NAVY_MID, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=20, pady=14)

stats_area = tk.Frame(scoreboard, bg=NAVY)
stats_area.pack(side=tk.LEFT, fill=tk.X, expand=True)

STAT_DEFS = [
    ("GAMES PLAYED", "games_value"),
    ("AVG SCORE",    "average_value"),
    ("HIGH GAME",    "high_value"),
    ("LOW GAME",     "low_value"),
]

stat_widgets = {}
for label_text, var_name in STAT_DEFS:
    col = tk.Frame(stats_area, bg=NAVY)
    col.pack(side=tk.LEFT, padx=28, pady=14)
    lbl = tk.Label(col, text=label_text, font=(FONT_BODY, 8, "bold"),
                   bg=NAVY, fg="#5B7FA6")
    lbl.pack(anchor="w")
    val = tk.Label(col, text="—", font=(FONT_BODY, 28, "bold"),
                   bg=NAVY, fg=AMBER)
    val.pack(anchor="w")
    stat_widgets[var_name] = val

games_value   = stat_widgets["games_value"]
average_value = stat_widgets["average_value"]
high_value    = stat_widgets["high_value"]
low_value     = stat_widgets["low_value"]

# GOAL tile — separate from the loop above since it's clickable and its
# label text changes (AVG GOAL / SCORE GOAL / "set a goal" prompt)
# depending on what's configured, rather than being a fixed stat.
#
# NOTE: this tile is intentionally NOT affected by the History filters
# (category/center/ball/date). It always reflects progress against your
# whole all-time history, via get_overall_stats() / update_goal_tile().
# The other four tiles (games/average/high/low, from update_stats()) DO
# respect the active filters. This split is by design -- don't "fix" the
# goal tile to match the filtered view.
tk.Frame(stats_area, bg=NAVY_MID, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=20)

goal_col = tk.Frame(stats_area, bg=NAVY, cursor="hand2")
goal_col.pack(side=tk.LEFT, padx=28, pady=14)
goal_label = tk.Label(goal_col, text="SET A GOAL →", font=(FONT_BODY, 8, "bold"),
                       bg=NAVY, fg="#5B7FA6", cursor="hand2")
goal_label.pack(anchor="w")
goal_value = tk.Label(goal_col, text="—", font=(FONT_BODY, 22, "bold"),
                       bg=NAVY, fg=AMBER, cursor="hand2")
goal_value.pack(anchor="w")
for _goal_widget in (goal_col, goal_label, goal_value):
    _goal_widget.bind("<Button-1>", lambda event: open_goals_dialog())

# ── MAIN TABS (History / Insights) ─────────────────────────────────────────
# Insights used to open in its own popup window; it now lives in a tab next
# to History instead, rebuilt fresh with current data every time it's
# selected -- same "always current" behavior the popup had, minus the extra
# window.

main_notebook = ttk.Notebook(window)
main_notebook.pack(fill=tk.BOTH, expand=True)

try:
    _ttk_style.configure("TNotebook", background=OFFWHITE, borderwidth=0)
    _ttk_style.configure("TNotebook.Tab", font=(FONT_BODY, 11, "bold"), padding=[16, 8])
except Exception:
    pass

history_tab = tk.Frame(main_notebook, bg=OFFWHITE)
insights_tab = tk.Frame(main_notebook, bg=OFFWHITE)
main_notebook.add(history_tab, text="  🎳  History  ")
main_notebook.add(insights_tab, text="  📊  Insights  ")


def _on_main_tab_changed(event=None):
    if main_notebook.select() == str(insights_tab):
        show_insights(insights_tab)


main_notebook.bind("<<NotebookTabChanged>>", _on_main_tab_changed)


# Header tools — always visible, never crowded out by the bottom bar
header_tools = tk.Frame(scoreboard, bg=NAVY)
header_tools.pack(side=tk.RIGHT, padx=(0, 16), pady=14)

def _header_btn(parent, text, command, primary=False):
    if primary:
        bg, fg, abg = AMBER, NAVY, "#D97706"
    else:
        bg, fg, abg = NAVY_MID, WHITE, "#243F5C"
    return _make_flat_button(
        parent, text, command, bg, fg, abg,
        font=(FONT_BODY, 10, "bold"), padx=12, pady=6,
    )

def toggle_night_mode():
    set_setting("night_mode", "0" if NIGHT_MODE else "1")
    if messagebox.askyesno(
        "Restart Required",
        ("Night Mode will be turned off." if NIGHT_MODE else "Night Mode will be turned on.")
        + "\n\nBowling Tracker needs to restart to apply the new theme. Restart now?",
    ):
        restart_app()


options_menu = tk.Menu(
    window, tearoff=0,
    font=(FONT_BODY, 10),
    bg=CARD_BG, fg=TEXT,
    activebackground=NAVY, activeforeground=WHITE,
    relief="flat", borderwidth=0,
)
options_menu.add_checkbutton(
    label="🌙  Night Mode",
    onvalue=1, offvalue=0,
    variable=tk.BooleanVar(value=NIGHT_MODE),
    command=toggle_night_mode,
)
options_menu.add_separator()
options_menu.add_command(label="🎯  Set Goals...", command=open_goals_dialog)

def open_options_menu():
    # Popup just below the Settings button, right-aligned with it.
    options_menu.tk_popup(
        settings_btn.winfo_rootx() + settings_btn.winfo_width() - options_menu.winfo_reqwidth(),
        settings_btn.winfo_rooty() + settings_btn.winfo_height() + 4,
    )

settings_btn = _header_btn(header_tools, "⚙️  Settings", open_options_menu)
settings_btn.pack(side=tk.RIGHT, padx=(0, 8))

_header_btn(header_tools, "❓  Help", lambda: show_tutorial(force=True)).pack(side=tk.RIGHT)
_header_btn(header_tools, "🎳  Arsenal",
            lambda: show_arsenal(window, connection, cursor, DESIGN_TOKENS)
            ).pack(side=tk.RIGHT, padx=(0, 8))


# ── ENTRY CARD ────────────────────────────────────────────────────────────────

entry_card = tk.Frame(history_tab, bg=CARD_BG,
                      highlightthickness=1, highlightbackground=BORDER)
entry_card.pack(fill=tk.X, padx=SPACE_LG - 4, pady=(SPACE_MD, 0))

entry_inner = tk.Frame(entry_card, bg=CARD_BG, pady=SPACE_MD - 2, padx=SPACE_MD + 2)
entry_inner.pack(fill=tk.X)

tk.Label(entry_inner, text="ADD GAME", font=(FONT_BODY, 9, "bold"),
         bg=CARD_BG, fg=TEXT_MUTED).grid(row=0, column=0, columnspan=12, sticky="w", pady=(0, SPACE_SM))

tk.Label(entry_inner, text="Date", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=0, sticky="w")
date_entry = tk.Entry(entry_inner, font=(FONT_BODY, 13), width=13,
                      bg=ENTRY_BG, relief="flat",
                      highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=AMBER)
date_entry.grid(row=1, column=1, padx=(SPACE_XS + 2, SPACE_MD + 4), ipady=6, ipadx=4)
date_entry.insert(0, date.today().strftime("%m/%d/%Y"))

tk.Label(entry_inner, text="Score", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=2, sticky="w")
score_entry = tk.Entry(entry_inner, font=(FONT_BODY, 13), width=7,
                       bg=ENTRY_BG, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=AMBER)
score_entry.grid(row=1, column=3, padx=(SPACE_XS + 2, SPACE_MD + 4), ipady=6, ipadx=4)

tk.Label(entry_inner, text="Category", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=4, sticky="w")
new_game_category_var = tk.StringVar(value=GAME_CATEGORIES[0])
cat_menu = make_dropdown(entry_inner, new_game_category_var, GAME_CATEGORIES)
cat_menu.grid(row=1, column=5, padx=(SPACE_XS + 2, SPACE_MD + 4))

tk.Frame(entry_inner, bg=BORDER, width=1).grid(row=1, column=6, sticky="ns", padx=(0, SPACE_MD))

add_button = make_button(entry_inner, "Add Game", add_game, primary=True)
add_button.grid(row=1, column=7, padx=(0, SPACE_SM))

import_button = make_button(entry_inner, "Import Scoresheet", import_scoresheet)
import_button.grid(row=1, column=8)

tk.Label(entry_inner, text="Strike ball", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=2, column=0, sticky="w", pady=(SPACE_SM + 2, 0))
ball_var = tk.StringVar(value=NO_BALL_LABEL)
ball_combo = ttk.Combobox(entry_inner, textvariable=ball_var, state="readonly",
                           font=(FONT_BODY, 11), width=16)
ball_combo.grid(row=2, column=1, columnspan=2, sticky="w",
                padx=(SPACE_XS + 2, SPACE_MD + 4), pady=(SPACE_SM + 2, 0), ipady=4)

tk.Label(entry_inner, text="Spare ball", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=2, column=3, sticky="w", pady=(SPACE_SM + 2, 0))
spare_ball_var = tk.StringVar(value=NO_SPARE_LABEL)
spare_ball_combo = ttk.Combobox(entry_inner, textvariable=spare_ball_var, state="readonly",
                                 font=(FONT_BODY, 11), width=16)
spare_ball_combo.grid(row=2, column=4, columnspan=2, sticky="w",
                      padx=(SPACE_XS + 2, SPACE_MD + 4), pady=(SPACE_SM + 2, 0), ipady=4)

tk.Label(entry_inner, text="Spare ball is the follow-up when you leave pins. Leave it blank for one-ball games.",
         font=(FONT_BODY, 8), bg=CARD_BG, fg=TEXT_MUTED).grid(
             row=3, column=0, columnspan=8, sticky="w", pady=(4, 0))


def refresh_ball_choices(*args):
    """Repopulate every ball dropdown from the current Arsenal roster.
    Called at boot and whenever the main window regains focus, so balls
    added in the Arsenal window show up without restarting the app."""
    names = get_arsenal_ball_names()
    strike_values = [NO_BALL_LABEL] + names
    spare_values = [NO_SPARE_LABEL] + names
    ball_combo["values"] = strike_values
    spare_ball_combo["values"] = spare_values
    if ball_var.get() not in strike_values:
        ball_var.set(NO_BALL_LABEL)
    if spare_ball_var.get() not in spare_values:
        spare_ball_var.set(NO_SPARE_LABEL)


# ── HISTORY SECTION ───────────────────────────────────────────────────────────

history_card = tk.Frame(history_tab, bg=CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER)
history_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 0))

hist_hdr = tk.Frame(history_card, bg=CARD_BG, pady=SPACE_SM + 2, padx=SPACE_MD + 2)
hist_hdr.pack(fill=tk.X)

tk.Label(hist_hdr, text="GAME HISTORY", font=(FONT_BODY, 9, "bold"),
         bg=CARD_BG, fg=TEXT_MUTED).pack(side=tk.LEFT)

filter_row = tk.Frame(history_card, bg="#F8FAFC",
                       highlightthickness=1, highlightbackground=BORDER,
                       pady=SPACE_SM + 1, padx=SPACE_MD + 2)
filter_row.pack(fill=tk.X)

def toolbar_divider(parent):
    tk.Frame(parent, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=SPACE_MD, pady=2)

tk.Label(filter_row, text="Category:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))
category_filter_var = tk.StringVar(value="All")
cat_filter_menu = make_dropdown(filter_row, category_filter_var, CATEGORIES)
cat_filter_menu.pack(side=tk.LEFT)
category_filter_var.trace("w", lambda *args: update_history_display())

toolbar_divider(filter_row)

tk.Label(filter_row, text="Center:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))
center_filter_var = tk.StringVar(value="All")
center_filter_menu = ttk.Combobox(filter_row, textvariable=center_filter_var,
                                   state="readonly", font=(FONT_BODY, 11), width=16)
center_filter_menu["values"] = ["All"]
center_filter_menu.pack(side=tk.LEFT)
center_filter_menu.bind("<<ComboboxSelected>>", lambda event: update_history_display())

toolbar_divider(filter_row)

tk.Label(filter_row, text="Ball:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))
ball_filter_var = tk.StringVar(value="All")
ball_filter_menu = ttk.Combobox(filter_row, textvariable=ball_filter_var,
                                 state="readonly", font=(FONT_BODY, 11), width=14)
ball_filter_menu["values"] = ["All"]
ball_filter_menu.pack(side=tk.LEFT)
ball_filter_menu.bind("<<ComboboxSelected>>", lambda event: update_history_display())

toolbar_divider(filter_row)

tk.Label(filter_row, text="Time frame:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))

QUICK_PICKS = [
    "All Time", "Today", "This Week", "Last 30 Days",
    "This Year", "Last Year",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

time_quick_var = tk.StringVar(value="All Time")
quick_menu = make_dropdown(filter_row, time_quick_var, QUICK_PICKS, width=9)
quick_menu.pack(side=tk.LEFT)
time_quick_var.trace("w", apply_quick_pick)

toolbar_divider(filter_row)

tk.Label(filter_row, text="From:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))
date_from_entry = tk.Entry(filter_row, font=(FONT_BODY, 11), width=11,
                            bg=ENTRY_BG, relief="flat",
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=AMBER)
date_from_entry.pack(side=tk.LEFT, ipady=4, ipadx=3, padx=(0, SPACE_MD - 2))

tk.Label(filter_row, text="To:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, SPACE_XS + 2))
date_to_entry = tk.Entry(filter_row, font=(FONT_BODY, 11), width=11,
                          bg=ENTRY_BG, relief="flat",
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=AMBER)
date_to_entry.pack(side=tk.LEFT, ipady=4, ipadx=3, padx=(0, SPACE_SM))

def on_date_entry_change(event):
    time_quick_var.set("Custom")
    update_history_display()

date_from_entry.bind("<Return>", on_date_entry_change)
date_from_entry.bind("<FocusOut>", on_date_entry_change)
date_to_entry.bind("<Return>", on_date_entry_change)
date_to_entry.bind("<FocusOut>", on_date_entry_change)

def clear_time_filter():
    time_quick_var.set("All Time")

clear_btn = make_secondary_button(filter_row, "Clear", clear_time_filter)
clear_btn.pack(side=tk.LEFT)

col_hdr = tk.Frame(history_card, bg=INFO_BG, pady=5)
col_hdr.pack(fill=tk.X)

def sort_arrow(column):
    if sort_column != column:
        return ""
    return " ▲" if sort_ascending else " ▼"

def set_sort(column):
    global sort_column, sort_ascending
    if sort_column == column:
        sort_ascending = not sort_ascending
    else:
        sort_column = column
        sort_ascending = True
    refresh_column_headers()
    update_history_display()

column_header_labels = {}

def make_column_header(parent, text, column, width):
    lbl = tk.Label(parent, text=text + sort_arrow(column), font=(FONT_MONO, 12, "bold"),
                    bg=INFO_BG, fg=TEXT_MUTED, width=width, anchor="w", cursor="hand2")
    lbl.pack(side=tk.LEFT)
    lbl.bind("<Button-1>", lambda event: set_sort(column))
    column_header_labels[column] = (lbl, text)
    return lbl

def refresh_column_headers():
    for column, (lbl, base_text) in column_header_labels.items():
        lbl.config(
            text=base_text + sort_arrow(column),
            fg=TEXT if sort_column == column else TEXT_MUTED,
        )

make_column_header(col_hdr, "  DATE", "date", 16)
make_column_header(col_hdr, "SCORE", "score", 6)
make_column_header(col_hdr, "CATEGORY", "category", 17)
make_column_header(col_hdr, "STRIKE / SPARE", "ball", 28)

list_frame = tk.Frame(history_card, bg=CARD_BG)
list_frame.pack(fill=tk.BOTH, expand=True)

scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

history = tk.Listbox(
    list_frame,
    font=(FONT_MONO, 12),
    yscrollcommand=scrollbar.set,
    selectbackground=NAVY,
    selectforeground=AMBER,
    activestyle="none",
    bg=CARD_BG, fg=TEXT,
    relief="flat", borderwidth=0,
    highlightthickness=0,
    selectmode=tk.EXTENDED,
)
history.pack(fill=tk.BOTH, expand=True)
scrollbar.config(command=history.yview)


# ── ACTION BUTTONS (two rows so nothing gets crowded off-screen) ───────────────

footer = tk.Frame(history_tab, bg=OFFWHITE)
footer.pack(fill=tk.X, padx=SPACE_LG - 4, pady=(SPACE_SM + 2, SPACE_MD))

# Row 1 — actions on the selected game(s)
game_row = tk.Frame(footer, bg=OFFWHITE)
game_row.pack(fill=tk.X, pady=(0, 6))

tk.Label(game_row, text="SELECTED GAME", font=(FONT_BODY, 8, "bold"),
         bg=OFFWHITE, fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 12))

make_button(game_row, "✏  Edit", edit_game).pack(side=tk.LEFT, padx=(0, SPACE_SM))
make_button(game_row, "📋  Frame Details", show_frame_details).pack(side=tk.LEFT, padx=(0, SPACE_SM))
make_button(game_row, "🗑  Delete", delete_game, danger=True).pack(side=tk.LEFT)

# Row 2 — file / database tools
data_row = tk.Frame(footer, bg=OFFWHITE)
data_row.pack(fill=tk.X)

tk.Label(data_row, text="DATA", font=(FONT_BODY, 8, "bold"),
         bg=OFFWHITE, fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 12))

make_secondary_button(data_row, "⬇  Export CSV", export_to_csv).pack(side=tk.LEFT, padx=(0, SPACE_SM))
make_secondary_button(data_row, "💾  Backup DB", backup_database).pack(side=tk.LEFT, padx=(0, SPACE_SM))
make_button(data_row, "Clear All Data", clear_all_data, danger=True).pack(side=tk.LEFT)
# ── BOOT ──────────────────────────────────────────────────────────────────────

refresh_center_filter_options()
refresh_ball_filter_options()
refresh_ball_choices()
def on_window_focus_in(event):
    # <FocusIn> bubbles up from every child widget (Entry, Combobox, etc.),
    # so without this guard we'd re-query the Arsenal table on every click
    # into a form field. Only refresh when the toplevel itself regains focus
    # (e.g. switching back from the Arsenal window).
    if event.widget is window:
        refresh_ball_choices()

window.bind("<FocusIn>", on_window_focus_in)
update_history_display()
# First-run tutorial after the window is drawn (skip if already completed)
window.after(400, maybe_show_tutorial)
window.mainloop()
