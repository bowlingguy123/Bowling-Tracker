import os
import sys
import tkinter as tk
import json
from tkinter import filedialog, messagebox, ttk
import sqlite3
from datetime import date, datetime, timedelta
import calendar
from scoresheet_importer import read_scoresheet


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

    connection.commit()
except sqlite3.Error as error:
    messagebox.showerror("Database Error", f"Could not open the database:\n{error}")
    sys.exit(1)


# ---------- STATE ----------

scores = []
displayed_ids = []


# ---------- DESIGN TOKENS ----------

# Scoreboard-inspired palette: deep navy base, amber accent (lane wood + pin gloss)
NAVY        = "#0F1F36"   # scoreboard background
NAVY_MID    = "#1A3352"   # slightly lighter navy for card accents
AMBER       = "#F59E0B"   # gold accent — like pin gloss / trophy
AMBER_DIM   = "#92600A"   # muted amber for secondary text on dark bg
WHITE       = "#FFFFFF"
OFFWHITE    = "#F8FAFC"   # page background
CARD_BG     = "#FFFFFF"
BORDER      = "#E2EAF3"
TEXT        = "#0F1F36"
TEXT_MUTED  = "#64748B"
RED         = "#DC2626"
GREEN       = "#16A34A"
ENTRY_BG    = "#F1F5FB"

FONT_BODY   = "Helvetica"
FONT_MONO   = "Courier"


# ---------- STATISTICS ----------

def update_stats():
    if len(scores) == 0:
        games_value.config(text="0")
        average_value.config(text="—")
        high_value.config(text="—")
        low_value.config(text="—")
        return

    games = len(scores)
    average = sum(scores) / games
    high = max(scores)
    low = min(scores)

    games_value.config(text=str(games))
    average_value.config(text=f"{average:.1f}")
    high_value.config(text=str(high))
    low_value.config(text=str(low))


# ---------- LOAD / FILTER GAMES ----------

def parse_date_flexible(date_str):
    """Try common date formats and return a date object, or None on failure."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def get_date_range_from_quick_pick(pick):
    """Return (date_from, date_to) strings for a quick-pick label, or (None, None)."""
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
        # Month names: "January", "February", …
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
    """When the quick-pick dropdown changes, populate the From/To fields and refresh."""
    pick = time_quick_var.get()
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

    query = "SELECT id, date, score, category FROM games"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id"

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
    for (game_id, game_date, score, category) in rows:
        # Apply date range filter in Python (dates stored in mixed formats)
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
        history.insert(tk.END, f"  {game_date:<22} {score:>3}   {category}")
        history.itemconfig(display_i, **{"bg": "#F8FAFC" if display_i % 2 == 0 else CARD_BG})
        display_i += 1

    update_stats()


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
    game_date = date_entry.get()
    score_text = score_entry.get()

    if game_date == "":
        messagebox.showwarning("Missing Date", "Please enter a date.")
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

    try:
        cursor.execute(
            "INSERT INTO games (date, score, category) VALUES (?, ?, ?)",
            (game_date, score, category)
        )
        connection.commit()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not save the game:\n{error}")
        return

    score_entry.delete(0, tk.END)
    update_history_display()


# ---------- DELETE GAME ----------

def delete_game():
    selected = history.curselection()
    if not selected:
        messagebox.showwarning("No Game Selected", "Please select a game to delete.")
        return

    index = selected[0]
    game_id = displayed_ids[index]
    confirm = messagebox.askyesno("Delete Game", "Are you sure you want to delete this game?")
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

    index = selected[0]
    game_id = displayed_ids[index]

    try:
        cursor.execute(
            "SELECT date, score, category, frames FROM games WHERE id = ?",
            (game_id,)
        )
        current_date, current_score, current_category, current_frames = cursor.fetchone()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load the game:\n{error}")
        return

    edit_window = tk.Toplevel(window)
    edit_window.title("Edit Game")
    edit_window.resizable(False, False)
    edit_window.transient(window)
    edit_window.grab_set()
    edit_window.configure(bg=OFFWHITE)

    # Header bar
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
    date_entry_edit.insert(0, current_date)

    field_label(body, "SCORE")
    score_entry_edit = tk.Entry(body, font=(FONT_BODY, 14), width=10,
                                 bg=ENTRY_BG, relief="flat",
                                 highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=AMBER)
    score_entry_edit.pack(anchor="w", ipady=6, ipadx=4)
    score_entry_edit.insert(0, str(current_score))

    field_label(body, "CATEGORY")
    selected_category_var = tk.StringVar(value=current_category)
    style_dropdown(tk.OptionMenu(body, selected_category_var, *CATEGORIES)).pack(anchor="w")

    if current_frames:
        warn = tk.Frame(body, bg="#FFFBEB", relief="flat")
        warn.pack(fill=tk.X, pady=(14, 0))
        tk.Label(warn, text="⚠  Changing the score won't update this game's saved frame details.",
                 font=(FONT_BODY, 9), bg="#FFFBEB", fg="#92600A",
                 wraplength=260, justify=tk.LEFT).pack(padx=10, pady=8)

    def save_edit():
        new_date = date_entry_edit.get()
        new_score_text = score_entry_edit.get()
        if new_date == "":
            messagebox.showwarning("Missing Date", "Please enter a date.")
            return
        try:
            new_score = int(new_score_text)
        except ValueError:
            messagebox.showwarning("Invalid Score", "Score must be a number.")
            return
        if new_score < 0 or new_score > 300:
            messagebox.showwarning("Invalid Score", "Bowling scores must be between 0 and 300.")
            return
        try:
            cursor.execute(
                "UPDATE games SET date = ?, score = ?, category = ? WHERE id = ?",
                (new_date, new_score, selected_category_var.get(), game_id)
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not save changes:\n{error}")
            return
        edit_window.destroy()
        update_history_display()

    btn_row = tk.Frame(body, bg=OFFWHITE)
    btn_row.pack(pady=(20, 4))
    make_button(btn_row, "Save Changes", save_edit, primary=True).pack(side=tk.LEFT, padx=(0, 8))
    make_button(btn_row, "Cancel", edit_window.destroy).pack(side=tk.LEFT)

    edit_window.update_idletasks()
    w = edit_window.winfo_reqwidth()
    h = edit_window.winfo_reqheight()
    edit_window.geometry(f"{w}x{h}")


# ---------- FRAME DETAILS ----------

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

    # Header
    hdr = tk.Frame(details_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text=f"Frame Details", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(hdr, text=f"{game_date}  ·  {score} pts",
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

        # Frame number header
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


# ---------- IMPORT SCORESHEET ----------

def show_import_review(player, player_records, file_name):
    review_window = tk.Toplevel(window)
    review_window.title("Review Imported Games")
    review_window.resizable(False, False)
    review_window.transient(window)
    review_window.grab_set()
    review_window.configure(bg=OFFWHITE)

    centers_in_file = {record.get("center") for record in player_records if record.get("center")}
    center_line = ", ".join(sorted(centers_in_file)) if centers_in_file else "Unknown"

    # Header
    hdr = tk.Frame(review_window, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="Import Scoresheet", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)

    body = tk.Frame(review_window, bg=OFFWHITE, padx=24, pady=16)
    body.pack(fill=tk.BOTH)

    # Meta info
    info_frame = tk.Frame(body, bg="#EFF6FF", highlightthickness=1, highlightbackground=BORDER)
    info_frame.pack(fill=tk.X, pady=(0, 12))
    tk.Label(info_frame, text=f"Player:  {player}", font=(FONT_BODY, 12, "bold"),
             bg="#EFF6FF", fg=TEXT, anchor="w").pack(fill=tk.X, padx=14, pady=(10, 2))
    tk.Label(info_frame, text=f"Center:  {center_line}", font=(FONT_BODY, 11),
             bg="#EFF6FF", fg=TEXT_MUTED, anchor="w").pack(fill=tk.X, padx=14)
    tk.Label(info_frame, text=f"File:      {file_name}", font=(FONT_BODY, 10),
             bg="#EFF6FF", fg=TEXT_MUTED, anchor="w").pack(fill=tk.X, padx=14, pady=(0, 10))

    # Game list
    list_frame = tk.Frame(body, bg=BORDER, highlightthickness=0)
    list_frame.pack(fill=tk.X)

    preview = tk.Listbox(list_frame, font=(FONT_MONO, 12), width=48, height=10,
                         bg=CARD_BG, fg=TEXT, selectbackground=NAVY, selectforeground=AMBER,
                         relief="flat", borderwidth=0, highlightthickness=0)
    preview.pack(padx=1, pady=1)
    for game_number, record in enumerate(player_records, start=1):
        preview.insert(tk.END, f"  Game {game_number:<3}  {record['date']:<14}  {record['score']}")

    # Category
    cat_row = tk.Frame(body, bg=OFFWHITE)
    cat_row.pack(pady=(14, 0))
    tk.Label(cat_row, text="Category:", font=(FONT_BODY, 12, "bold"),
             bg=OFFWHITE, fg=TEXT).pack(side=tk.LEFT, padx=(0, 10))
    import_category_var = tk.StringVar(value=GAME_CATEGORIES[0])
    style_dropdown(tk.OptionMenu(cat_row, import_category_var, *GAME_CATEGORIES)).pack(side=tk.LEFT)

    tk.Label(body, text="Applied to every game in this file.",
             font=(FONT_BODY, 9), bg=OFFWHITE, fg=TEXT_MUTED).pack(pady=(4, 0))

    def confirm_import():
        if not messagebox.askyesno("Import Games",
                                   f"Import {len(player_records)} game(s) for {player}?",
                                   parent=review_window):
            return
        chosen_category = import_category_var.get()
        try:
            cursor.executemany(
                "INSERT INTO games (date, score, category, center, frames) VALUES (?, ?, ?, ?, ?)",
                [
                    (record["date"], record["score"], chosen_category,
                     record.get("center") or None, json.dumps(record["frames"]))
                    for record in player_records
                ],
            )
            connection.commit()
        except sqlite3.Error as error:
            messagebox.showerror("Database Error", f"Could not import games:\n{error}", parent=review_window)
            return
        review_window.destroy()
        refresh_center_filter_options()
        update_history_display()
        messagebox.showinfo("Import Complete", f"Imported {len(player_records)} game(s) for {player}.")

    actions = tk.Frame(body, bg=OFFWHITE)
    actions.pack(pady=18)
    make_button(actions, f"Import {len(player_records)} Game(s)", confirm_import, primary=True).pack(side=tk.LEFT, padx=(0, 8))
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

def show_insights():
    try:
        cursor.execute("SELECT date, score, category FROM games ORDER BY id")
        all_rows = cursor.fetchall()
    except sqlite3.Error as error:
        messagebox.showerror("Database Error", f"Could not load games:\n{error}")
        return

    if not all_rows:
        messagebox.showinfo("No Data", "Add some games first to see insights.")
        return

    # ── Parse all rows ──────────────────────────────────────────────────────
    parsed_games = []
    for game_date, score, category in all_rows:
        d = parse_date_flexible(game_date)
        parsed_games.append({
            "date": d,
            "date_str": game_date,
            "score": score,
            "category": category or "Uncategorized",
        })
    parsed_games.sort(key=lambda g: g["date"] or date.min)

    all_scores = [g["score"] for g in parsed_games]
    overall_avg = sum(all_scores) / len(all_scores)

    # ── Streak tracking ─────────────────────────────────────────────────────
    # Current above-average streak and longest ever
    current_streak = 0
    longest_streak = 0
    run = 0
    for g in parsed_games:
        if g["score"] >= overall_avg:
            run += 1
            longest_streak = max(longest_streak, run)
        else:
            run = 0
    # current streak = tail of the list
    for g in reversed(parsed_games):
        if g["score"] >= overall_avg:
            current_streak += 1
        else:
            break

    # ── Personal bests per category ─────────────────────────────────────────
    cat_stats = {}
    for g in parsed_games:
        cat = g["category"]
        if cat not in cat_stats:
            cat_stats[cat] = {"scores": [], "best": 0}
        cat_stats[cat]["scores"].append(g["score"])
        cat_stats[cat]["best"] = max(cat_stats[cat]["best"], g["score"])

    # ── Build window ────────────────────────────────────────────────────────
    ins = tk.Toplevel(window)
    ins.title("Insights")
    ins.configure(bg=OFFWHITE)
    ins.resizable(False, False)
    ins.transient(window)

    # Header
    hdr = tk.Frame(ins, bg=NAVY)
    hdr.pack(fill=tk.X)
    tk.Label(hdr, text="📊  Insights", font=(FONT_BODY, 15, "bold"),
             bg=NAVY, fg=WHITE).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(hdr, text=f"{len(parsed_games)} games  ·  avg {overall_avg:.1f}",
             font=(FONT_BODY, 11), bg=NAVY, fg=AMBER).pack(side=tk.LEFT, pady=14)

    body = tk.Frame(ins, bg=OFFWHITE, padx=20, pady=16)
    body.pack(fill=tk.BOTH)

    # ── SECTION: Streak ──────────────────────────────────────────────────────
    def section_label(parent, text):
        tk.Label(parent, text=text, font=(FONT_BODY, 9, "bold"),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(anchor="w", pady=(14, 6))

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

    # ── SECTION: Personal bests per category ─────────────────────────────────
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

    # ── SECTION: Score trend chart ────────────────────────────────────────────
    section_label(body, "SCORE TREND  (all games, chronological)")

    CHART_W, CHART_H = 700, 180
    PAD_L, PAD_R, PAD_T, PAD_B = 48, 16, 16, 32

    chart_frame = tk.Frame(body, bg=CARD_BG,
                           highlightthickness=1, highlightbackground=BORDER)
    chart_frame.pack(fill=tk.X, pady=(0, 8))

    canvas = tk.Canvas(chart_frame, width=CHART_W, height=CHART_H,
                       bg=CARD_BG, highlightthickness=0)
    canvas.pack()

    plot_scores = [g["score"] for g in parsed_games]
    n = len(plot_scores)
    lo = min(plot_scores)
    hi = max(plot_scores)
    score_range = hi - lo if hi != lo else 1

    def sx(i):
        return PAD_L + (i / max(n - 1, 1)) * (CHART_W - PAD_L - PAD_R)

    def sy(s):
        return PAD_T + (1 - (s - lo) / score_range) * (CHART_H - PAD_T - PAD_B)

    # Gridlines + Y labels
    for val in [lo, (lo + hi) // 2, hi]:
        y = sy(val)
        canvas.create_line(PAD_L, y, CHART_W - PAD_R, y,
                           fill=BORDER, dash=(4, 4))
        canvas.create_text(PAD_L - 6, y, text=str(val),
                           font=(FONT_BODY, 8), fill=TEXT_MUTED, anchor="e")

    # Average line
    avg_y = sy(overall_avg)
    canvas.create_line(PAD_L, avg_y, CHART_W - PAD_R, avg_y,
                       fill=AMBER, dash=(6, 3), width=1)
    canvas.create_text(CHART_W - PAD_R + 2, avg_y,
                       text=f"avg", font=(FONT_BODY, 7), fill=AMBER, anchor="w")

    # Score line
    if n > 1:
        points = [(sx(i), sy(s)) for i, s in enumerate(plot_scores)]
        flat = [coord for pt in points for coord in pt]
        canvas.create_line(*flat, fill=NAVY, width=2, smooth=True)

    # Dots + hover tooltip
    dot_ids = []
    tooltip_label = tk.Label(chart_frame, font=(FONT_BODY, 9, "bold"),
                              bg=NAVY, fg=WHITE, padx=6, pady=3, relief="flat")

    def make_hover(i, x, y, score, gdate):
        def enter(e):
            tooltip_label.config(text=f"{score}  {gdate}")
            tx = min(x + 8, CHART_W - 80)
            ty = max(y - 22, 4)
            tooltip_label.place(x=tx, y=ty)
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
        dot_ids.append(dot)

    # X-axis labels: first, last, and a few in between
    label_indices = sorted(set([0, n - 1] + [n // 4, n // 2, 3 * n // 4]))
    for i in label_indices:
        if 0 <= i < n:
            canvas.create_text(sx(i), CHART_H - PAD_B + 10,
                               text=parsed_games[i]["date_str"],
                               font=(FONT_BODY, 7), fill=TEXT_MUTED, angle=0)

    # Legend
    legend = tk.Frame(body, bg=OFFWHITE)
    legend.pack(anchor="w", pady=(2, 10))
    for color, label in [(GREEN, "At/above avg"), (RED, "Below avg"), (AMBER, "Your average")]:
        dot_lbl = tk.Frame(legend, bg=color, width=10, height=10)
        dot_lbl.pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(legend, text=label, font=(FONT_BODY, 9),
                 bg=OFFWHITE, fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 16))

    ins.update_idletasks()
    w = ins.winfo_reqwidth()
    h = ins.winfo_reqheight()
    ins.geometry(f"{max(w, 760)}x{min(h, 860)}")


# ---------- SHUTDOWN ----------

def on_close():
    try:
        connection.close()
    except sqlite3.Error:
        pass
    window.destroy()


# ══════════════════════════════════════
# HELPER: STYLED WIDGETS
# ══════════════════════════════════════

def make_button(parent, text, command, primary=False, danger=False):
    if primary:
        bg, fg, abg = AMBER, NAVY, "#D97706"
    elif danger:
        bg, fg, abg = RED, WHITE, "#B91C1C"
    else:
        bg, fg, abg = "#E2EAF3", TEXT, "#C7D5E8"

    btn = tk.Button(
        parent, text=text, command=command,
        font=(FONT_BODY, 11, "bold"),
        bg=bg, fg=fg, activebackground=abg, activeforeground=fg,
        relief="flat", cursor="hand2",
        padx=18, pady=7, borderwidth=0
    )
    return btn


def style_dropdown(menu):
    menu.config(
        font=(FONT_BODY, 11),
        bg=ENTRY_BG, fg=TEXT,
        activebackground=NAVY, activeforeground=WHITE,
        relief="flat", borderwidth=0,
        highlightthickness=1, highlightbackground=BORDER,
        padx=10, pady=5, cursor="hand2"
    )
    menu["menu"].config(
        font=(FONT_BODY, 11),
        bg=CARD_BG, fg=TEXT,
        activebackground=NAVY, activeforeground=WHITE
    )
    return menu


# ══════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════

window = tk.Tk()
window.title("Bowling Tracker")
window.geometry("980x680")
window.resizable(False, False)
window.protocol("WM_DELETE_WINDOW", on_close)
window.configure(bg=OFFWHITE)


# ── SCOREBOARD HEADER ─────────────────────────────────────────────────────────
# Dark navy bar with amber numbers — the signature visual element of this design.
# Looks like an actual bowling alley overhead scoreboard.

scoreboard = tk.Frame(window, bg=NAVY, height=110)
scoreboard.pack(fill=tk.X)
scoreboard.pack_propagate(False)

# App name / branding on the far left
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

# Divider line
tk.Frame(scoreboard, bg=NAVY_MID, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=20, pady=14)

# Stats — right side of header
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


# ── ENTRY CARD ────────────────────────────────────────────────────────────────

entry_card = tk.Frame(window, bg=CARD_BG,
                      highlightthickness=1, highlightbackground=BORDER)
entry_card.pack(fill=tk.X, padx=20, pady=(16, 0))

entry_inner = tk.Frame(entry_card, bg=CARD_BG, pady=14, padx=18)
entry_inner.pack(fill=tk.X)

# Section label
tk.Label(entry_inner, text="ADD GAME", font=(FONT_BODY, 9, "bold"),
         bg=CARD_BG, fg=TEXT_MUTED).grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 8))

# Date
tk.Label(entry_inner, text="Date", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=0, sticky="w")
date_entry = tk.Entry(entry_inner, font=(FONT_BODY, 13), width=13,
                      bg=ENTRY_BG, relief="flat",
                      highlightthickness=1, highlightbackground=BORDER,
                      highlightcolor=AMBER)
date_entry.grid(row=1, column=1, padx=(6, 20), ipady=6, ipadx=4)
date_entry.insert(0, date.today().strftime("%m/%d/%Y"))

# Score
tk.Label(entry_inner, text="Score", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=2, sticky="w")
score_entry = tk.Entry(entry_inner, font=(FONT_BODY, 13), width=7,
                       bg=ENTRY_BG, relief="flat",
                       highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=AMBER)
score_entry.grid(row=1, column=3, padx=(6, 20), ipady=6, ipadx=4)

# Category
tk.Label(entry_inner, text="Category", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).grid(row=1, column=4, sticky="w")
new_game_category_var = tk.StringVar(value=GAME_CATEGORIES[0])
cat_menu = style_dropdown(tk.OptionMenu(entry_inner, new_game_category_var, *GAME_CATEGORIES))
cat_menu.grid(row=1, column=5, padx=(6, 20))

# Buttons
add_button = make_button(entry_inner, "Add Game", add_game, primary=True)
add_button.grid(row=1, column=6, padx=(0, 8))

import_button = make_button(entry_inner, "Import Scoresheet", import_scoresheet)
import_button.grid(row=1, column=7)


# ── HISTORY SECTION ───────────────────────────────────────────────────────────

history_card = tk.Frame(window, bg=CARD_BG,
                        highlightthickness=1, highlightbackground=BORDER)
history_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 0))

# ── History header: ROW 1 — title + Category + Center filters ────────────────
hist_hdr = tk.Frame(history_card, bg=CARD_BG, pady=8, padx=18)
hist_hdr.pack(fill=tk.X)

tk.Label(hist_hdr, text="GAME HISTORY", font=(FONT_BODY, 9, "bold"),
         bg=CARD_BG, fg=TEXT_MUTED).pack(side=tk.LEFT)

filter_row1 = tk.Frame(hist_hdr, bg=CARD_BG)
filter_row1.pack(side=tk.RIGHT)

tk.Label(filter_row1, text="Category:", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).pack(side=tk.LEFT, padx=(0, 6))
category_filter_var = tk.StringVar(value="All")
cat_filter_menu = style_dropdown(tk.OptionMenu(filter_row1, category_filter_var, *CATEGORIES))
cat_filter_menu.pack(side=tk.LEFT, padx=(0, 16))
category_filter_var.trace("w", lambda *args: update_history_display())

tk.Label(filter_row1, text="Center:", font=(FONT_BODY, 10, "bold"),
         bg=CARD_BG, fg=TEXT).pack(side=tk.LEFT, padx=(0, 6))
center_filter_var = tk.StringVar(value="All")
center_filter_menu = ttk.Combobox(filter_row1, textvariable=center_filter_var,
                                   state="readonly", font=(FONT_BODY, 11), width=18)
center_filter_menu["values"] = ["All"]
center_filter_menu.pack(side=tk.LEFT)
center_filter_menu.bind("<<ComboboxSelected>>", lambda event: update_history_display())

# ── History header: ROW 2 — time frame filters ────────────────────────────────
QUICK_PICKS = [
    "All Time", "Today", "This Week", "Last 30 Days",
    "This Year", "Last Year",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

filter_row2 = tk.Frame(history_card, bg="#F8FAFC",
                        highlightthickness=1, highlightbackground=BORDER,
                        pady=7, padx=18)
filter_row2.pack(fill=tk.X)

tk.Label(filter_row2, text="TIME FRAME", font=(FONT_BODY, 8, "bold"),
         bg="#F8FAFC", fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(0, 10))

time_quick_var = tk.StringVar(value="All Time")
quick_menu = style_dropdown(tk.OptionMenu(filter_row2, time_quick_var, *QUICK_PICKS))
quick_menu.config(width=12)
quick_menu.pack(side=tk.LEFT, padx=(0, 20))
time_quick_var.trace("w", apply_quick_pick)

# Divider
tk.Frame(filter_row2, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16), pady=2)

tk.Label(filter_row2, text="From:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, 6))
date_from_entry = tk.Entry(filter_row2, font=(FONT_BODY, 11), width=12,
                            bg=ENTRY_BG, relief="flat",
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=AMBER)
date_from_entry.pack(side=tk.LEFT, ipady=4, ipadx=3, padx=(0, 14))

tk.Label(filter_row2, text="To:", font=(FONT_BODY, 10, "bold"),
         bg="#F8FAFC", fg=TEXT).pack(side=tk.LEFT, padx=(0, 6))
date_to_entry = tk.Entry(filter_row2, font=(FONT_BODY, 11), width=12,
                          bg=ENTRY_BG, relief="flat",
                          highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=AMBER)
date_to_entry.pack(side=tk.LEFT, ipady=4, ipadx=3, padx=(0, 14))

def on_date_entry_change(event):
    # Clear the quick pick label when the user types custom dates
    time_quick_var.set("Custom")
    update_history_display()

date_from_entry.bind("<Return>", on_date_entry_change)
date_from_entry.bind("<FocusOut>", on_date_entry_change)
date_to_entry.bind("<Return>", on_date_entry_change)
date_to_entry.bind("<FocusOut>", on_date_entry_change)

def clear_time_filter():
    time_quick_var.set("All Time")  # triggers apply_quick_pick which clears entries + refreshes

clear_btn = make_button(filter_row2, "Clear", clear_time_filter)
clear_btn.pack(side=tk.LEFT)

# Column header strip
col_hdr = tk.Frame(history_card, bg="#EFF4FB", pady=5)
col_hdr.pack(fill=tk.X)
tk.Label(col_hdr, text="  DATE", font=(FONT_BODY, 9, "bold"),
         bg="#EFF4FB", fg=TEXT_MUTED, width=26, anchor="w").pack(side=tk.LEFT)
tk.Label(col_hdr, text="SCORE", font=(FONT_BODY, 9, "bold"),
         bg="#EFF4FB", fg=TEXT_MUTED, width=6, anchor="w").pack(side=tk.LEFT)
tk.Label(col_hdr, text="CATEGORY", font=(FONT_BODY, 9, "bold"),
         bg="#EFF4FB", fg=TEXT_MUTED, width=18, anchor="w").pack(side=tk.LEFT)

# Listbox + scrollbar
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
)
history.pack(fill=tk.BOTH, expand=True)
scrollbar.config(command=history.yview)


# ── ACTION BUTTONS ────────────────────────────────────────────────────────────

action_bar = tk.Frame(window, bg=OFFWHITE)
action_bar.pack(fill=tk.X, padx=20, pady=(10, 16))

make_button(action_bar, "✏  Edit Game", edit_game).pack(side=tk.LEFT, padx=(0, 8))
make_button(action_bar, "📋  Frame Details", show_frame_details).pack(side=tk.LEFT, padx=(0, 8))
make_button(action_bar, "🗑  Delete Game", delete_game, danger=True).pack(side=tk.LEFT, padx=(0, 8))
make_button(action_bar, "📊  Insights", show_insights, primary=True).pack(side=tk.RIGHT)


# ── BOOT ──────────────────────────────────────────────────────────────────────

refresh_center_filter_options()
update_history_display()
window.mainloop()
