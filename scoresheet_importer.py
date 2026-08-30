import re
from html.parser import HTMLParser


class BrunswickScoresheetParser(HTMLParser):
    """Read completed games, including frame throws, from Sync Passport HTML."""

    date_pattern = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")

    def __init__(self):
        super().__init__()
        self.current_date = ""
        self.current_center = ""
        self.capture = None
        self.capture_parts = []
        self.current_row = None
        self.player_row_depth = 0
        self.current_frame = None
        self.records = []

    @staticmethod
    def class_names(attributes):
        return set(dict(attributes).get("class", "").split())

    def start_capture(self, kind):
        self.capture = kind
        self.capture_parts = []

    def handle_starttag(self, tag, attributes):
        classes = self.class_names(attributes)

        if tag == "h2" and "scoredate" in classes:
            self.start_capture("date")
            return

        if tag == "h3" and "scorecenter" in classes:
            self.start_capture("center")
            return

        if tag == "tr":
            if "notranslate" in classes:
                self.current_row = {"player": "", "score": None, "frames": []}
                self.player_row_depth = 1
                self.current_frame = None
            elif self.current_row:
                self.player_row_depth += 1
            return

        if not self.current_row or tag != "td":
            return

        if "cls_player" in classes:
            self.start_capture("player")
        elif "cls_frame" in classes or "cls_frame10" in classes:
            self.current_frame = {"throws": []}
            self.current_row["frames"].append(self.current_frame)
        elif self.current_frame:
            for ball_class in ("cls_ball1", "cls_ball2", "cls_ball3"):
                if ball_class in classes:
                    self.start_capture("throw")
                    break
        if "cls_scoretotal" in classes:
            self.start_capture("score")

    def handle_data(self, data):
        if self.capture:
            self.capture_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.capture:
            value = " ".join("".join(self.capture_parts).split())
            capture = self.capture
            self.capture = None
            self.capture_parts = []

            if capture == "player" and self.current_row:
                self.current_row["player"] = value
            elif capture == "throw" and self.current_frame:
                if value:
                    self.current_frame["throws"].append(value)
            elif capture == "score" and self.current_row:
                try:
                    self.current_row["score"] = int(value)
                except ValueError:
                    pass

        elif tag == "h2" and self.capture == "date":
            value = " ".join("".join(self.capture_parts).split())
            self.capture = None
            self.capture_parts = []
            matched_date = self.date_pattern.search(value)
            if matched_date:
                self.current_date = matched_date.group(0)

        elif tag == "h3" and self.capture == "center":
            value = " ".join("".join(self.capture_parts).split())
            self.capture = None
            self.capture_parts = []
            if value:
                self.current_center = value

        if tag == "tr" and self.current_row:
            self.player_row_depth -= 1
            if self.player_row_depth == 0:
                row = self.current_row
                if row["player"] and row["score"] is not None and self.current_date:
                    # Passport adds a layout-only cell after the tenth frame.
                    # Keep the first ten frame cells even when a score display
                    # leaves a frame's throw marks blank.
                    frames = row["frames"][:10]
                    self.records.append({
                        "player": row["player"],
                        "date": self.current_date,
                        "center": self.current_center,
                        "score": row["score"],
                        "frames": frames,
                    })
                self.current_row = None
                self.current_frame = None


def read_scoresheet(file_path):
    """Return completed player games from a Brunswick/Sync Passport HTML file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as scoresheet:
            contents = scoresheet.read()
    except OSError as error:
        raise ValueError(f"The file could not be opened.\n\n{error}") from error

    parser = BrunswickScoresheetParser()
    parser.feed(contents)
    parser.close()
    return [record for record in parser.records if 0 <= record["score"] <= 300]