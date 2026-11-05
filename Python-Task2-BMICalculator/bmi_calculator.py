"""
BMI Calculator (Advanced Tier) - Desktop GUI

Author : Rabia Azam
Program: Oasis Infobyte Internship (OIBSIP) - Python Programming Track
Task   : Task 2 - BMI Calculator (Advanced)

Features:
    - tkinter window with labelled input fields and a Calculate button
    - height can be entered in feet and inches, or in meters
    - BMI = weight (kg) / height (m) squared, shown with 2 decimal places
    - colour-coded result: Underweight / Normal / Overweight / Obese
    - input validation with helpful error messages (shown inside the window)
    - multi-user support: records are saved under a user name
    - history stored in an SQLite database (bmi_data.db)
    - line chart of a user's BMI trend over time (matplotlib)
    - error handling for database read/write failures
"""

import math
import os
import sqlite3
import tkinter as tk
from contextlib import closing      # makes sure a database connection is always closed
from datetime import datetime
from tkinter import ttk

# matplotlib is an extra package (pip install matplotlib).
# If it is missing, the calculator still works, only the graph is unavailable.
try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# ---------------------------------------------------------------- settings
# The database file is created next to this script
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bmi_data.db")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_NAME_LENGTH = 30

INCH_IN_METERS = 0.0254     # 1 inch = 0.0254 meters
MIN_HEIGHT_INCHES = 20      # about 1 ft 8 in (0.5 m)
MAX_HEIGHT_INCHES = 98      # about 8 ft 2 in (2.5 m)

# Colour for each BMI category
CATEGORY_COLORS = {
    "Underweight": "#2f80ed",   # blue
    "Normal": "#2e9b4f",        # green
    "Overweight": "#e08a00",    # orange
    "Obese": "#d9382f",         # red
}
COLOR_ERROR = "#d9382f"
COLOR_OK = "#2e9b4f"
COLOR_EMPTY = "#e6e6e6"


# ------------------------------------------------------------ BMI logic
def parse_number(text, label, example):
    """Convert text to a positive number or raise ValueError with a helpful message."""
    text = text.strip()
    if not text:
        raise ValueError(f"Please enter your {label}.")

    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label.capitalize()} must be a number, for example {example}.") from None

    # float() also accepts the words "nan" and "inf", which are not real measurements
    if not math.isfinite(value):
        raise ValueError(f"{label.capitalize()} must be a real number.")
    if value <= 0:
        raise ValueError(f"{label.capitalize()} must be greater than zero.")
    return value


def validate_weight(text):
    """Return the weight in kg, or raise ValueError."""
    weight = parse_number(text, "weight", "65 or 65.5")
    if not 10 <= weight <= 500:
        raise ValueError("Weight looks wrong. Please enter it in kilograms (10 to 500).")
    return weight


def validate_height(text):
    """Return the height in meters (typed in meters), or raise ValueError."""
    height = parse_number(text, "height", "1.70")
    if height > 2.5:
        if height <= 250:
            raise ValueError("Height must be in meters, for example 1.70 (not centimetres).")
        raise ValueError("Height looks wrong. Please enter it in meters (0.5 to 2.5).")
    if height < 0.5:
        raise ValueError("Height looks wrong. Please enter it in meters (0.5 to 2.5).")
    return height


def parse_inches(text):
    """Return the inches part of a height. An empty box means 0 inches."""
    text = text.strip()
    if not text:
        return 0.0

    try:
        value = float(text)
    except ValueError:
        raise ValueError("Inches must be a number, for example 6.") from None

    if not math.isfinite(value) or value < 0:
        raise ValueError("Inches must be zero or more.")
    if value >= 12:
        raise ValueError("Inches must be less than 12. Add the extra to the feet box.")
    return value


def validate_height_feet(feet_text, inches_text):
    """Return the height in meters (typed in feet and inches), or raise ValueError."""
    feet = parse_number(feet_text, "height in feet", "5")
    if feet != int(feet):
        raise ValueError("Feet must be a whole number, for example 5. Use the inches box for the rest, like 6.")

    inches = parse_inches(inches_text)
    total_inches = feet * 12 + inches
    if not MIN_HEIGHT_INCHES <= total_inches <= MAX_HEIGHT_INCHES:
        raise ValueError("Height looks wrong. Please enter a height between 1 ft 8 in and 8 ft 2 in.")
    return total_inches * INCH_IN_METERS


def format_height(height_m):
    """Show a height in meters as feet and inches, for example 1.68 -> '5 ft 6 in'."""
    total_inches = round(height_m / INCH_IN_METERS)
    feet, inches = divmod(total_inches, 12)     # divmod gives the whole feet and the leftover inches
    return f"{feet} ft {inches} in"


def calculate_bmi(weight_kg, height_m):
    """BMI = weight / (height * height), rounded to 2 decimal places."""
    return round(weight_kg / (height_m ** 2), 2)


def classify_bmi(bmi):
    """Return the standard BMI category for a BMI value."""
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


# ------------------------------------------------------------- database
class BMIDatabase:
    """Saves and loads BMI records using SQLite."""

    def __init__(self, path=DB_FILE):
        self.path = path
        self.create_table()

    def create_table(self):
        """Create the records table if it does not exist yet."""
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:    # saves (commits) the changes
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS records (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_name   TEXT NOT NULL COLLATE NOCASE,
                        weight_kg   REAL NOT NULL,
                        height_m    REAL NOT NULL,
                        bmi         REAL NOT NULL,
                        category    TEXT NOT NULL,
                        recorded_at TEXT NOT NULL
                    )
                    """
                )

    def add_record(self, user_name, weight_kg, height_m, bmi, category):
        """Save one BMI record for a user."""
        recorded_at = datetime.now().strftime(TIME_FORMAT)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                # The ? marks keep user input safe from SQL injection
                connection.execute(
                    "INSERT INTO records (user_name, weight_kg, height_m, bmi, category, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_name, weight_kg, height_m, bmi, category, recorded_at),
                )

    def get_users(self):
        """Return the names of all users who have saved records."""
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT DISTINCT user_name FROM records ORDER BY user_name"
            ).fetchall()
        return [row[0] for row in rows]

    def get_records(self, user_name):
        """Return all records of one user, oldest first."""
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT recorded_at, weight_kg, height_m, bmi, category "
                "FROM records WHERE user_name = ? ORDER BY recorded_at, id",
                (user_name,),
            ).fetchall()


# ------------------------------------------------------------------- GUI
class BMIApp:
    """The main window of the program."""

    def __init__(self, root, db_path=DB_FILE):
        self.root = root
        self.root.title("BMI Calculator")
        self.root.resizable(False, False)
        self.root.configure(padx=20, pady=12)

        self.name_var = tk.StringVar()
        self.weight_var = tk.StringVar()
        self.unit_var = tk.StringVar(value="feet")      # "feet" or "meters"
        self.feet_var = tk.StringVar()
        self.inches_var = tk.StringVar()
        self.meters_var = tk.StringVar()
        self.history_title_var = tk.StringVar(value="History")

        # Open the database. If that fails, the calculator still works without saving.
        self.db = None
        self.startup_error = None
        try:
            self.db = BMIDatabase(db_path)
        except sqlite3.Error as error:
            self.startup_error = f"Database problem: {error}. Records cannot be saved."

        self.build_widgets()
        self.place_window_on_screen()

        if self.startup_error:
            self.show_message(self.startup_error, error=True)
        else:
            self.refresh_users()

    def build_widgets(self):
        """Create and place every widget. Two columns keep the window short."""
        tk.Label(self.root, text="BMI Calculator",
                 font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        left = tk.Frame(self.root)
        left.grid(row=1, column=0, sticky="n", padx=(0, 24))
        right = tk.Frame(self.root)
        right.grid(row=1, column=1, sticky="n")

        # ---------------- LEFT COLUMN: input and result ----------------
        tk.Label(left, text="User name:", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", pady=4)
        self.name_box = ttk.Combobox(left, textvariable=self.name_var, width=22)
        self.name_box.grid(row=0, column=1, sticky="w", pady=4)
        self.name_box.bind("<<ComboboxSelected>>", lambda event: self.load_history())

        tk.Label(left, text="Weight (kg):", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(left, textvariable=self.weight_var, width=25).grid(row=1, column=1, sticky="w", pady=4)

        # Height unit choice: feet and inches, or meters
        tk.Label(left, text="Height unit:", font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=4)
        unit_row = tk.Frame(left)
        unit_row.grid(row=2, column=1, sticky="w", pady=4)
        tk.Radiobutton(unit_row, text="Feet and inches", variable=self.unit_var, value="feet",
                       command=self.on_unit_change).pack(side="left")
        tk.Radiobutton(unit_row, text="Meters", variable=self.unit_var, value="meters",
                       command=self.on_unit_change).pack(side="left")

        tk.Label(left, text="Height:", font=("Segoe UI", 10)).grid(row=3, column=0, sticky="w", pady=4)
        height_box = tk.Frame(left)
        height_box.grid(row=3, column=1, sticky="w", pady=4)

        # Two input layouts share the same place. Only one is visible at a time.
        self.feet_frame = tk.Frame(height_box)
        tk.Entry(self.feet_frame, textvariable=self.feet_var, width=8).pack(side="left")
        tk.Label(self.feet_frame, text=" ft   ").pack(side="left")
        tk.Entry(self.feet_frame, textvariable=self.inches_var, width=8).pack(side="left")
        tk.Label(self.feet_frame, text=" in").pack(side="left")

        self.meters_frame = tk.Frame(height_box)
        tk.Entry(self.meters_frame, textvariable=self.meters_var, width=25).pack(side="left")
        tk.Label(self.meters_frame, text=" m").pack(side="left")

        self.example_label = tk.Label(left, text="", font=("Segoe UI", 9), fg="#666666")
        self.example_label.grid(row=4, column=0, columnspan=2, sticky="w")

        tk.Button(left, text="Calculate BMI", font=("Segoe UI", 11, "bold"),
                  bg="#2f6fdb", fg="white", activebackground="#2559b3", activeforeground="white",
                  command=self.on_calculate, padx=10, pady=4).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(12, 10))

        # Result box: its colour changes with the BMI category
        self.result_frame = tk.Frame(left, bg=COLOR_EMPTY, padx=10, pady=10)
        self.result_frame.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.bmi_label = tk.Label(self.result_frame, text="BMI: -", bg=COLOR_EMPTY,
                                  font=("Segoe UI", 20, "bold"))
        self.bmi_label.pack()
        self.category_label = tk.Label(self.result_frame, text="Category: -", bg=COLOR_EMPTY,
                                       font=("Segoe UI", 13))
        self.category_label.pack()

        # Message area (errors and confirmations appear here, not in the terminal)
        self.message_label = tk.Label(left, text=" ", font=("Segoe UI", 10), wraplength=340, justify="left")
        self.message_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

        # ---------------- RIGHT COLUMN: history ----------------
        tk.Label(right, textvariable=self.history_title_var,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")

        table_frame = tk.Frame(right)
        table_frame.pack(pady=(4, 6))
        columns = ("date", "weight", "height", "bmi", "category")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=11)
        for column, title, width in (("date", "Date", 130), ("weight", "kg", 55), ("height", "Height", 80),
                                     ("bmi", "BMI", 55), ("category", "Category", 90)):
            self.table.heading(column, text=title)
            self.table.column(column, width=width, anchor="center")
        for category, color in CATEGORY_COLORS.items():
            self.table.tag_configure(category, foreground=color)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left")
        scrollbar.pack(side="left", fill="y")

        button_row = tk.Frame(right)
        button_row.pack(fill="x")
        tk.Button(button_row, text="Show BMI Trend Graph", command=self.on_show_graph,
                  padx=8).pack(side="left")
        tk.Button(button_row, text="Refresh History", command=self.on_refresh,
                  padx=8).pack(side="left", padx=(8, 0))

        # Pressing Enter does the same as clicking Calculate
        self.root.bind("<Return>", lambda event: self.on_calculate())

        # Show the correct height boxes for the starting unit
        self.on_unit_change()

    def place_window_on_screen(self):
        """Centre the window horizontally and put it near the top so nothing is cut off."""
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        self.root.geometry(f"+{x}+10")

    # ------------------------------------------------------------ actions
    def on_unit_change(self):
        """Show the feet and inches boxes, or the meters box, depending on the chosen unit."""
        if self.unit_var.get() == "feet":
            self.meters_frame.grid_remove()
            self.feet_frame.grid(row=0, column=0)
            self.example_label.config(text="Example: weight 65 kg, height 5 ft 6 in")
        else:
            self.feet_frame.grid_remove()
            self.meters_frame.grid(row=0, column=0)
            self.example_label.config(text="Example: weight 65 kg, height 1.70 m")

    def get_height_in_meters(self):
        """Read the height boxes and return the height in meters (or raise ValueError)."""
        if self.unit_var.get() == "feet":
            return validate_height_feet(self.feet_var.get(), self.inches_var.get())
        return validate_height(self.meters_var.get())

    def on_calculate(self):
        """Validate the input, calculate the BMI, show it and save it."""
        name = self.name_var.get().strip()

        try:
            if not name:
                raise ValueError("Please enter a user name so the record can be saved.")
            if len(name) > MAX_NAME_LENGTH:
                raise ValueError(f"User name can have at most {MAX_NAME_LENGTH} characters.")
            weight = validate_weight(self.weight_var.get())
            height = self.get_height_in_meters()
        except ValueError as error:
            self.clear_result()
            self.show_message(str(error), error=True)
            return

        bmi = calculate_bmi(weight, height)
        category = classify_bmi(bmi)
        self.show_result(bmi, category)

        if self.db is None:
            self.show_message("Result shown, but it was not saved because the database is not available.",
                              error=True)
            return

        try:
            self.db.add_record(name, weight, round(height, 4), bmi, category)
        except sqlite3.Error as error:
            self.show_message(f"BMI calculated, but saving failed: {error}", error=True)
            return

        self.show_message(f"Saved for {name}.")
        self.refresh_users()
        self.load_history()

    def on_refresh(self):
        """Reload the user list and the history table."""
        self.refresh_users()
        self.load_history()

    def on_show_graph(self):
        """Open a window with the BMI trend of the selected user."""
        if not MATPLOTLIB_AVAILABLE:
            self.show_message("The graph needs matplotlib. Run: pip install matplotlib", error=True)
            return

        name = self.name_var.get().strip()
        if not name:
            self.show_message("Enter or choose a user name first.", error=True)
            return

        records = self.read_records(name)
        if records is None:
            return      # a database error message is already shown
        if not records:
            self.show_message(f"No records found for {name}.", error=True)
            return

        self.open_graph_window(name, records)

    # ------------------------------------------------------------ helpers
    def read_records(self, name):
        """Return the user's records, or None if the database could not be read."""
        if self.db is None:
            self.show_message("The database is not available.", error=True)
            return None
        try:
            return self.db.get_records(name)
        except sqlite3.Error as error:
            self.show_message(f"Could not read records: {error}", error=True)
            return None

    def refresh_users(self):
        """Fill the user name drop-down list from the database."""
        if self.db is None:
            return
        try:
            self.name_box["values"] = self.db.get_users()
        except sqlite3.Error as error:
            self.show_message(f"Could not read users: {error}", error=True)

    def load_history(self):
        """Show the selected user's records in the table."""
        for row in self.table.get_children():
            self.table.delete(row)

        name = self.name_var.get().strip()
        if not name:
            self.history_title_var.set("History")
            return

        records = self.read_records(name)
        if records is None:
            return

        self.history_title_var.set(f"History for {name} ({len(records)} records)")
        for recorded_at, weight, height, bmi, category in records:
            self.table.insert("", "end", tags=(category,),
                              values=(recorded_at[:16], weight, format_height(height),
                                      f"{bmi:.2f}", category))
        # Show the newest record at the bottom of the table
        children = self.table.get_children()
        if children:
            self.table.see(children[-1])

    def show_result(self, bmi, category):
        """Show the BMI and category in the coloured result box."""
        color = CATEGORY_COLORS[category]
        self.result_frame.config(bg=color)
        self.bmi_label.config(text=f"BMI: {bmi:.2f}", bg=color, fg="white")
        self.category_label.config(text=f"Category: {category}", bg=color, fg="white")

    def clear_result(self):
        """Reset the result box to its empty state."""
        self.result_frame.config(bg=COLOR_EMPTY)
        self.bmi_label.config(text="BMI: -", bg=COLOR_EMPTY, fg="black")
        self.category_label.config(text="Category: -", bg=COLOR_EMPTY, fg="black")

    def show_message(self, text, error=False):
        """Show a message inside the window (red for errors, green otherwise)."""
        self.message_label.config(text=text, fg=COLOR_ERROR if error else COLOR_OK)

    def open_graph_window(self, name, records):
        """Draw a line chart of BMI over time in a new window."""
        window = tk.Toplevel(self.root)
        window.title(f"BMI Trend - {name}")

        # X axis = record number (1, 2, 3 ...), so the chart looks good even when
        # records were saved only minutes apart. The date and time are the tick labels.
        numbers = list(range(1, len(records) + 1))
        labels = [datetime.strptime(record[0], TIME_FORMAT).strftime("%d %b\n%H:%M") for record in records]
        values = [record[3] for record in records]

        low = min(15, min(values) - 1)
        high = max(35, max(values) + 1)

        figure = Figure(figsize=(7, 4.4), dpi=100)
        axes = figure.add_subplot(111)

        # Coloured bands show which category each BMI range belongs to
        axes.axhspan(low, 18.5, color=CATEGORY_COLORS["Underweight"], alpha=0.12, label="Underweight")
        axes.axhspan(18.5, 25, color=CATEGORY_COLORS["Normal"], alpha=0.12, label="Normal")
        axes.axhspan(25, 30, color=CATEGORY_COLORS["Overweight"], alpha=0.12, label="Overweight")
        axes.axhspan(30, high, color=CATEGORY_COLORS["Obese"], alpha=0.12, label="Obese")

        axes.plot(numbers, values, marker="o", color="#333333", linewidth=2)
        axes.set_ylim(low, high)
        axes.set_xlim(0.5, len(records) + 0.5)
        axes.set_title(f"BMI trend over time for {name}")
        axes.set_xlabel("Record date and time")
        axes.set_ylabel("BMI")

        # With many records, show only some date labels so they do not overlap
        step = max(1, math.ceil(len(records) / 8))
        axes.set_xticks(numbers[::step])
        axes.set_xticklabels(labels[::step], fontsize=8)
        axes.legend(loc="upper left", fontsize=8)
        figure.tight_layout()

        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        window.canvas = canvas      # keep a reference so the chart is not deleted


def main():
    root = tk.Tk()
    BMIApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()