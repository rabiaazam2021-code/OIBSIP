"""
Random Password Generator (Advanced Tier) - Desktop GUI

Author : Rabia Azam
Program: Oasis Infobyte Internship (OIBSIP) - Python Programming Track
Task   : Task 3 - Random Password Generator (Advanced)

Features:
    - tkinter window with a length slider and character-type checkboxes
    - cryptographically secure generation using the `secrets` module
    - password strength indicator (Weak / Medium / Strong)
    - at least one character from every selected type is guaranteed
    - automatic copy to clipboard (pyperclip) plus a Copy button
    - option to exclude ambiguous characters (0, O, 1, l, I)
    - history of the last 5 passwords (kept in memory only, never saved to a file)
"""

import secrets          # secure random numbers (used instead of `random`)
import string           # ready-made sets of letters, digits and symbols
import tkinter as tk    # the GUI library that comes with Python
from collections import deque   # a list that keeps only the newest N items

# pyperclip is an extra package (pip install pyperclip).
# If it is missing, the program still works and uses tkinter's own clipboard.
try:
    import pyperclip
except ImportError:
    pyperclip = None

# ---------------------------------------------------------------- settings
MIN_LENGTH = 8
MAX_LENGTH = 64
DEFAULT_LENGTH = 16
MIN_TYPES = 2
HISTORY_SIZE = 5
AMBIGUOUS = "0O1lI"     # characters that are easy to confuse when reading

# Colours used by the strength bar and the messages
COLOR_WEAK = "#d9534f"
COLOR_MEDIUM = "#f0ad4e"
COLOR_STRONG = "#3c9a4a"
COLOR_BAR_BACKGROUND = "#dddddd"
BAR_WIDTH = 330         # width of the strength bar in pixels


# --------------------------------------------------------- password logic
def build_pools(use_upper, use_lower, use_digits, use_symbols, exclude_ambiguous):
    """Return a list of strings. Each string holds the characters of one selected type."""
    pools = []
    if use_upper:
        pools.append(string.ascii_uppercase)
    if use_lower:
        pools.append(string.ascii_lowercase)
    if use_digits:
        pools.append(string.digits)
    if use_symbols:
        pools.append(string.punctuation)

    if exclude_ambiguous:
        # Rebuild every pool without the confusing characters
        pools = ["".join(c for c in pool if c not in AMBIGUOUS) for pool in pools]
    return pools


def secure_shuffle(items):
    """Shuffle a list in place using secrets (Fisher-Yates algorithm)."""
    for i in range(len(items) - 1, 0, -1):
        j = secrets.randbelow(i + 1)            # secure random index from 0 to i
        items[i], items[j] = items[j], items[i]  # swap the two items


def generate_password(length, pools):
    """Create a password that contains at least one character from every pool."""
    # Step 1: one secure random character from each selected type
    password = [secrets.choice(pool) for pool in pools]

    # Step 2: fill the remaining places from all selected characters
    all_characters = "".join(pools)
    for _ in range(length - len(password)):
        password.append(secrets.choice(all_characters))

    # Step 3: shuffle so the guaranteed characters are not always first
    secure_shuffle(password)
    return "".join(password)


def password_strength(password):
    """Return 'Weak', 'Medium' or 'Strong' based on length and character variety."""
    # How many different character types does the password contain?
    kinds = sum([
        any(c in string.ascii_uppercase for c in password),
        any(c in string.ascii_lowercase for c in password),
        any(c in string.digits for c in password),
        any(c in string.punctuation for c in password),
    ])

    # Length points: longer passwords are harder to guess
    if len(password) >= 20:
        length_points = 3
    elif len(password) >= 14:
        length_points = 2
    elif len(password) >= 10:
        length_points = 1
    else:
        length_points = 0

    # Variety points: 2 types = 0 points, 3 types = 1 point, 4 types = 2 points
    score = length_points + max(kinds - 2, 0)

    if score >= 4:
        return "Strong"
    if score >= 2:
        return "Medium"
    return "Weak"


# ------------------------------------------------------------------- GUI
class PasswordGeneratorApp:
    """The main window of the program."""

    def __init__(self, root):
        self.root = root
        self.root.title("Random Password Generator")
        self.root.resizable(False, False)
        self.root.configure(padx=20, pady=12)

        # History of passwords from this session only (newest first)
        self.history = deque(maxlen=HISTORY_SIZE)

        # Tk variables: widgets and the program share their values
        self.length_var = tk.IntVar(value=DEFAULT_LENGTH)
        self.upper_var = tk.BooleanVar(value=True)
        self.lower_var = tk.BooleanVar(value=True)
        self.digits_var = tk.BooleanVar(value=True)
        self.symbols_var = tk.BooleanVar(value=True)
        self.exclude_var = tk.BooleanVar(value=False)
        self.password_var = tk.StringVar()

        self.build_widgets()
        self.place_window_on_screen()

    def build_widgets(self):
        """Create and place every widget. Two columns keep the window short enough for any screen."""
        tk.Label(self.root, text="Random Password Generator",
                 font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        # Left column = settings, right column = result and history
        left = tk.Frame(self.root)
        left.grid(row=1, column=0, sticky="n", padx=(0, 24))
        right = tk.Frame(self.root)
        right.grid(row=1, column=1, sticky="n")

        # ---------------- LEFT COLUMN: settings ----------------
        # --- Length slider
        tk.Label(left, text="Password length:", font=("Segoe UI", 10)).pack(anchor="w")
        tk.Scale(left, from_=MIN_LENGTH, to=MAX_LENGTH, orient=tk.HORIZONTAL,
                 variable=self.length_var, length=300).pack(anchor="w")

        # --- Character type checkboxes
        tk.Label(left, text="Include:", font=("Segoe UI", 10)).pack(anchor="w", pady=(8, 0))
        tk.Checkbutton(left, text="Uppercase letters (A-Z)", variable=self.upper_var).pack(anchor="w")
        tk.Checkbutton(left, text="Lowercase letters (a-z)", variable=self.lower_var).pack(anchor="w")
        tk.Checkbutton(left, text="Numbers (0-9)", variable=self.digits_var).pack(anchor="w")
        tk.Checkbutton(left, text="Symbols (!@#$%...)", variable=self.symbols_var).pack(anchor="w")
        tk.Checkbutton(left, text="Exclude ambiguous characters (0 O 1 l I)",
                       variable=self.exclude_var).pack(anchor="w", pady=(6, 0))

        # --- Generate button
        tk.Button(left, text="Generate Password", font=("Segoe UI", 11, "bold"),
                  bg="#2f6fdb", fg="white", activebackground="#2559b3", activeforeground="white",
                  command=self.on_generate, padx=10, pady=4).pack(fill="x", pady=(14, 0))

        # ---------------- RIGHT COLUMN: result ----------------
        # --- Password display (read-only so it can be selected but not edited)
        tk.Label(right, text="Your password:", font=("Segoe UI", 10)).pack(anchor="w")
        tk.Entry(right, textvariable=self.password_var, state="readonly",
                 font=("Consolas", 14), justify="center", width=28).pack(fill="x", ipady=4)

        # --- Strength bar and label
        self.strength_canvas = tk.Canvas(right, width=BAR_WIDTH, height=12,
                                         bg=COLOR_BAR_BACKGROUND, highlightthickness=0)
        self.strength_canvas.pack(pady=(8, 2))
        self.strength_label = tk.Label(right, text="Strength: -", font=("Segoe UI", 10, "bold"))
        self.strength_label.pack()

        # --- Copy button
        tk.Button(right, text="Copy to Clipboard", command=self.on_copy,
                  padx=8).pack(pady=(8, 4))

        # --- Message area (errors and confirmations appear here, not in the terminal)
        self.message_label = tk.Label(right, text=" ", font=("Segoe UI", 10), wraplength=330)
        self.message_label.pack(pady=(0, 6))

        # --- History list
        tk.Label(right, text=f"Last {HISTORY_SIZE} passwords (this session only):",
                 font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(right, text="Double-click one to copy it.",
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.history_list = tk.Listbox(right, height=HISTORY_SIZE, font=("Consolas", 11), width=34)
        self.history_list.pack(fill="x", pady=(2, 0))
        self.history_list.bind("<Double-Button-1>", self.on_history_double_click)

    def place_window_on_screen(self):
        """Centre the window horizontally and put it near the top so nothing is cut off."""
        self.root.update_idletasks()    # let tkinter calculate the real window size first
        width = self.root.winfo_reqwidth()
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        self.root.geometry(f"+{x}+10")

    # ------------------------------------------------------------ actions
    def on_generate(self):
        """Called when the user clicks 'Generate Password'."""
        pools = build_pools(self.upper_var.get(), self.lower_var.get(),
                            self.digits_var.get(), self.symbols_var.get(),
                            self.exclude_var.get())

        # Validation: at least 2 character types must be selected
        if len(pools) < MIN_TYPES:
            self.password_var.set("")       # clear the old password so the error is clear
            self.reset_strength()           # clear the old strength bar too
            self.show_message(f"Please select at least {MIN_TYPES} character types.", error=True)
            return

        password = generate_password(self.length_var.get(), pools)
        self.password_var.set(password)
        self.update_strength(password)
        self.add_to_history(password)

        # The password is copied automatically as soon as it is generated
        if self.copy_text(password):
            self.show_message("Password generated and copied to clipboard.")
        else:
            self.show_message("Password generated, but copying failed. Use the Copy button.", error=True)

    def on_copy(self):
        """Called when the user clicks 'Copy to Clipboard'."""
        password = self.password_var.get()
        if not password:
            self.show_message("Generate a password first.", error=True)
            return
        if self.copy_text(password):
            self.show_message("Copied to clipboard.")
        else:
            self.show_message("Could not access the clipboard.", error=True)

    def on_history_double_click(self, event):
        """Copy the history item the user double-clicked."""
        selection = self.history_list.curselection()
        if selection and self.copy_text(self.history_list.get(selection[0])):
            self.show_message("Copied from history.")

    # ------------------------------------------------------------ helpers
    def copy_text(self, text):
        """Copy text to the clipboard. Return True if it worked."""
        # First choice: pyperclip
        if pyperclip is not None:
            try:
                pyperclip.copy(text)
                return True
            except Exception:
                pass    # pyperclip failed, so try the fallback below

        # Fallback: tkinter's built-in clipboard
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()      # makes the clipboard text stay available
            return True
        except Exception:
            return False

    def add_to_history(self, password):
        """Store the password in memory and refresh the history list."""
        self.history.appendleft(password)
        self.history_list.delete(0, tk.END)
        for item in self.history:
            self.history_list.insert(tk.END, item)

    def update_strength(self, password):
        """Draw the strength bar and set the label text."""
        level = password_strength(password)
        colors = {"Weak": COLOR_WEAK, "Medium": COLOR_MEDIUM, "Strong": COLOR_STRONG}
        fill = {"Weak": 1 / 3, "Medium": 2 / 3, "Strong": 1.0}

        self.strength_canvas.delete("all")
        self.strength_canvas.create_rectangle(
            0, 0, int(BAR_WIDTH * fill[level]), 12, fill=colors[level], outline=colors[level])
        self.strength_label.config(text=f"Strength: {level}", fg=colors[level])

    def reset_strength(self):
        """Empty the strength bar and label (used when there is no password to rate)."""
        self.strength_canvas.delete("all")
        self.strength_label.config(text="Strength: -", fg="black")

    def show_message(self, text, error=False):
        """Show a message inside the window (red for errors, green otherwise)."""
        self.message_label.config(text=text, fg=COLOR_WEAK if error else COLOR_STRONG)


def main():
    root = tk.Tk()
    PasswordGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()