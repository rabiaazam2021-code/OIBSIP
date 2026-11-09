"""
Chat Client (Advanced Tier) - Desktop GUI (tkinter)

Author : Rabia Azam
Program: Oasis Infobyte Internship (OIBSIP) - Python Programming Track
Task   : Task 5 - Chat Application (Advanced)

This is the FRONTEND. Start server.py first, then run this file (you can run it many times,
once for each user).

Features:
    - login and registration screen
    - rooms list: create a room or double-click a room to join it
    - old messages of a room are shown when you join
    - messages look like  [14:35] Alice: Hello
    - emoji shortcodes: type :smile: and it shows as an emoji
    - notification when a message arrives and the window is not in focus
      (window title counter, a beep and a flashing taskbar icon on Windows)
    - messages when someone joins, leaves or disconnects
"""

import json
import queue
import re
import socket
import sys
import threading
import tkinter as tk

# ---------------------------------------------------------------- settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
CONNECT_TIMEOUT = 5
APP_TITLE = "Chat App"
MAX_MESSAGE_LENGTH = 500

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_]{3,20}")
ROOM_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,20}")

COLOR_BG = "#f2f6fa"
COLOR_ERROR = "#d9382f"
COLOR_OK = "#2e9b4f"
COLOR_MUTED = "#777777"
COLOR_ACCENT = "#2f6fdb"
USER_COLORS = ["#c0392b", "#8e44ad", "#16813a", "#d35400", "#1b7f9e", "#a0522d", "#6c5ce7", "#b7950b"]

# Emoji shortcodes. They are written with \U escapes so the file works on any computer.
EMOJI = {
    "smile": "\U0001F604", "grin": "\U0001F601", "laughing": "\U0001F606", "joy": "\U0001F602",
    "wink": "\U0001F609", "blush": "\U0001F60A", "heart_eyes": "\U0001F60D", "sunglasses": "\U0001F60E",
    "thinking": "\U0001F914", "neutral": "\U0001F610", "sad": "\U0001F622", "cry": "\U0001F62D",
    "angry": "\U0001F620", "scream": "\U0001F631", "sleepy": "\U0001F634", "party": "\U0001F973",
    "heart": "❤️", "broken_heart": "\U0001F494", "fire": "\U0001F525", "star": "⭐",
    "tada": "\U0001F389", "rocket": "\U0001F680", "100": "\U0001F4AF", "eyes": "\U0001F440",
    "thumbsup": "\U0001F44D", "thumbsdown": "\U0001F44E", "clap": "\U0001F44F", "wave": "\U0001F44B",
    "pray": "\U0001F64F", "ok_hand": "\U0001F44C", "muscle": "\U0001F4AA", "v": "✌️",
    "check": "✅", "x": "❌", "coffee": "☕", "sun": "☀️",
}
MENU_EMOJI = ["smile", "grin", "joy", "wink", "heart_eyes", "sunglasses", "thinking", "sad",
              "heart", "fire", "tada", "rocket", "thumbsup", "clap", "wave", "check"]
SHORTCODE_PATTERN = re.compile(r":([a-z0-9_]+):")


def render_emojis(text):
    """Replace shortcodes like :smile: with the emoji. Unknown shortcodes stay as they are."""
    return SHORTCODE_PATTERN.sub(lambda match: EMOJI.get(match.group(1), match.group(0)), text)


def tk_safe(text):
    """Some old Tk versions cannot show characters above U+FFFF. Replace them with '?' instead of crashing."""
    return "".join(ch if ord(ch) <= 0xFFFF else "?" for ch in text)


def user_color_index(name):
    """The same name always gets the same colour."""
    return sum(ord(ch) for ch in name) % len(USER_COLORS)


# -------------------------------------------------------------- networking
class Connection:
    """One TCP connection to the server. A background thread reads the incoming messages."""

    def __init__(self, incoming):
        self.incoming = incoming        # queue shared with the GUI
        self.sock = None
        self.closed = False

    def start(self, host, port, first_payload):
        """Connect in a background thread (so the window does not freeze), then send the first message."""
        threading.Thread(target=self.run, args=(host, port, first_payload), daemon=True).start()

    def run(self, host, port, first_payload):
        try:
            self.sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
            self.sock.settimeout(None)
        except OSError:
            self.incoming.put((self, "connect_failed", f"Cannot connect to {host}:{port}. Is server.py running?"))
            return
        if self.closed:                 # the user pressed Logout while we were connecting
            self.close()
            return
        self.send(first_payload)

        buffer = b""
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        self.incoming.put((self, "message", json.loads(line.decode("utf-8"))))
                    except ValueError:
                        pass            # ignore a broken line
        except OSError:
            pass
        self.incoming.put((self, "closed", None))

    def send(self, payload):
        """Send one JSON message. Return False if it did not work."""
        if self.sock is None or self.closed:
            return False
        try:
            self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    def close(self):
        self.closed = True
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass


def flash_taskbar(root):
    """Make the taskbar icon flash (Windows only). Fails quietly on other systems."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.user32.FlashWindow(hwnd, True)
    except Exception:
        pass


# --------------------------------------------------------------------- GUI
class ChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_BG, padx=16, pady=12)

        self.incoming = queue.Queue()   # messages from the network thread
        self.conn = None
        self.username = None
        self.current_room = None
        self.unread = 0

        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.new_room_var = tk.StringVar()
        self.message_var = tk.StringVar()

        self.build_login_frame()
        self.build_chat_frame()
        self.show_login()

        self.root.bind("<FocusIn>", self.on_focus_in)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.process_incoming)

    # ------------------------------------------------------------ layout
    def build_login_frame(self):
        frame = tk.Frame(self.root, bg=COLOR_BG)
        self.login_frame = frame
        tk.Label(frame, text="Chat App", bg=COLOR_BG, font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(10, 2))
        tk.Label(frame, text="Log in or create an account", bg=COLOR_BG, fg=COLOR_MUTED,
                 font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2, pady=(0, 12))

        fields = [("Server address:", self.host_var, ""), ("Port:", self.port_var, ""),
                  ("Username:", self.user_var, ""), ("Password:", self.pass_var, "*")]
        self.login_entries = []
        for row, (label, variable, hide) in enumerate(fields, start=2):
            tk.Label(frame, text=label, bg=COLOR_BG, font=("Segoe UI", 10)).grid(
                row=row, column=0, sticky="e", padx=(0, 8), pady=3)
            entry = tk.Entry(frame, textvariable=variable, show=hide, width=26, font=("Segoe UI", 11))
            entry.grid(row=row, column=1, pady=3)
            self.login_entries.append(entry)

        buttons = tk.Frame(frame, bg=COLOR_BG)
        buttons.grid(row=6, column=0, columnspan=2, pady=(12, 4))
        self.login_button = tk.Button(buttons, text="Login", width=12, bg=COLOR_ACCENT, fg="white",
                                      activebackground="#2559b3", activeforeground="white",
                                      font=("Segoe UI", 10, "bold"), command=lambda: self.on_auth("login"))
        self.login_button.pack(side="left", padx=4)
        self.register_button = tk.Button(buttons, text="Register", width=12, font=("Segoe UI", 10),
                                         command=lambda: self.on_auth("register"))
        self.register_button.pack(side="left", padx=4)

        self.login_status = tk.Label(frame, text=" ", bg=COLOR_BG, font=("Segoe UI", 10), wraplength=340)
        self.login_status.grid(row=7, column=0, columnspan=2, pady=(6, 10))
        tk.Label(frame, text="Messages are not encrypted. Do not use a password you use elsewhere.",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=("Segoe UI", 8), wraplength=340).grid(
            row=8, column=0, columnspan=2)

    def build_chat_frame(self):
        frame = tk.Frame(self.root, bg=COLOR_BG)
        self.chat_frame = frame

        # ---- left side: rooms and users
        left = tk.Frame(frame, bg=COLOR_BG)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        self.me_label = tk.Label(left, text="", bg=COLOR_BG, font=("Segoe UI", 10, "bold"))
        self.me_label.pack(anchor="w")
        tk.Label(left, text="Rooms (double-click to join)", bg=COLOR_BG, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(8, 0))
        self.room_list = tk.Listbox(left, height=7, width=24, exportselection=False, font=("Segoe UI", 10))
        self.room_list.pack(anchor="w")
        self.room_list.bind("<Double-Button-1>", self.on_room_double_click)
        self.room_names = []

        tk.Label(left, text="New room name:", bg=COLOR_BG, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
        room_row = tk.Frame(left, bg=COLOR_BG)
        room_row.pack(anchor="w")
        room_entry = tk.Entry(room_row, textvariable=self.new_room_var, width=15, font=("Segoe UI", 10))
        room_entry.pack(side="left")
        room_entry.bind("<Return>", lambda event: self.on_create_room())
        tk.Button(room_row, text="Create", command=self.on_create_room).pack(side="left", padx=(4, 0))

        tk.Label(left, text="Online in this room", bg=COLOR_BG, font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
        self.user_list = tk.Listbox(left, height=6, width=24, font=("Segoe UI", 10), activestyle="none")
        self.user_list.pack(anchor="w")
        tk.Button(left, text="Logout", command=self.on_logout).pack(anchor="w", pady=(10, 0))

        # ---- right side: messages
        right = tk.Frame(frame, bg=COLOR_BG)
        right.grid(row=0, column=1, sticky="n")
        self.room_label = tk.Label(right, text="", bg=COLOR_BG, font=("Segoe UI", 13, "bold"))
        self.room_label.pack(anchor="w")

        text_frame = tk.Frame(right)
        text_frame.pack()
        self.chat_text = tk.Text(text_frame, width=58, height=20, wrap="word", state="disabled",
                                 font=("Segoe UI", 10), padx=8, pady=6, bg="white", relief="flat",
                                 highlightthickness=1, highlightbackground="#d5dde6")
        scrollbar = tk.Scrollbar(text_frame, command=self.chat_text.yview)
        self.chat_text.config(yscrollcommand=scrollbar.set)
        self.chat_text.pack(side="left")
        scrollbar.pack(side="left", fill="y")
        self.chat_text.tag_config("time", foreground=COLOR_MUTED)
        self.chat_text.tag_config("system", foreground=COLOR_MUTED, font=("Segoe UI", 9, "italic"))
        self.chat_text.tag_config("history_note", foreground=COLOR_MUTED, font=("Segoe UI", 8, "italic"),
                                  justify="center")
        self.chat_text.tag_config("own", foreground=COLOR_ACCENT, font=("Segoe UI", 10, "bold"))
        for index, color in enumerate(USER_COLORS):
            self.chat_text.tag_config(f"user{index}", foreground=color, font=("Segoe UI", 10, "bold"))

        self.chat_status = tk.Label(right, text=" ", bg=COLOR_BG, font=("Segoe UI", 9), anchor="w")
        self.chat_status.pack(fill="x", pady=(4, 0))

        send_row = tk.Frame(right, bg=COLOR_BG)
        send_row.pack(fill="x", pady=(2, 0))
        self.message_entry = tk.Entry(send_row, textvariable=self.message_var, font=("Segoe UI", 11), width=40)
        self.message_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.message_entry.bind("<Return>", lambda event: self.on_send())

        emoji_button = tk.Menubutton(send_row, text="Emoji", relief="raised", padx=6)
        emoji_menu = tk.Menu(emoji_button, tearoff=0)
        for position, name in enumerate(MENU_EMOJI):
            emoji_menu.add_command(label=f":{name}:", columnbreak=1 if position and position % 8 == 0 else 0,
                                   command=lambda code=name: self.insert_shortcode(code))
        emoji_button.config(menu=emoji_menu)
        emoji_button.pack(side="left", padx=(6, 0))
        tk.Button(send_row, text="Send", bg=COLOR_ACCENT, fg="white", activebackground="#2559b3",
                  activeforeground="white", font=("Segoe UI", 10, "bold"), padx=10,
                  command=self.on_send).pack(side="left", padx=(6, 0))
        tk.Label(right, text="Tip: type :smile: :heart: :thumbsup: :fire: ... to get emoji",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=("Segoe UI", 8)).pack(anchor="w")

    def show_login(self, message=" ", error=False):
        self.chat_frame.pack_forget()
        self.login_frame.pack()
        self.pass_var.set("")
        self.set_buttons_enabled(True)
        self.show_login_message(message, error)
        self.login_entries[2].focus_set()
        self.root.title(APP_TITLE)
        self.place_window_on_screen()

    def show_chat(self):
        self.login_frame.pack_forget()
        self.chat_frame.pack()
        self.me_label.config(text=f"Logged in as {self.username}")
        self.message_entry.focus_set()
        self.place_window_on_screen()

    def place_window_on_screen(self):
        """Centre the window horizontally and keep it near the top so nothing is cut off."""
        self.root.update_idletasks()
        x = max((self.root.winfo_screenwidth() - self.root.winfo_reqwidth()) // 2, 0)
        self.root.geometry(f"+{x}+10")

    def show_login_message(self, text, error=False):
        self.login_status.config(text=text, fg=COLOR_ERROR if error else COLOR_OK)

    def show_chat_message(self, text, error=False):
        self.chat_status.config(text=text, fg=COLOR_ERROR if error else COLOR_OK)

    def set_buttons_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.login_button.config(state=state)
        self.register_button.config(state=state)

    # ------------------------------------------------------------ actions
    def on_auth(self, kind):
        """Check the form, then connect and send a login or register request."""
        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.show_login_message("Port must be a number between 1 and 65535.", error=True)
            return
        username = self.user_var.get().strip()
        password = self.pass_var.get()
        if not USERNAME_PATTERN.fullmatch(username):
            self.show_login_message("Username must be 3-20 characters: letters, numbers or underscore.", error=True)
            return
        if len(password) < 6:
            self.show_login_message("Password must be at least 6 characters.", error=True)
            return

        if self.conn:
            self.conn.close()
        self.conn = Connection(self.incoming)
        self.set_buttons_enabled(False)
        self.show_login_message("Connecting...", error=False)
        self.conn.start(host, port, {"type": kind, "username": username, "password": password})

    def on_send(self):
        text = self.message_var.get().strip()
        if not text:
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            self.show_chat_message(f"Message is too long (maximum {MAX_MESSAGE_LENGTH} characters).", error=True)
            return
        if self.conn and self.conn.send({"type": "message", "text": text}):
            self.message_var.set("")
            self.show_chat_message(" ")
        else:
            self.handle_disconnect()

    def on_create_room(self):
        name = self.new_room_var.get().strip()
        if not ROOM_PATTERN.fullmatch(name):
            self.show_chat_message("Room name: 1-20 characters, letters, numbers, - or _.", error=True)
            return
        if self.conn and self.conn.send({"type": "create_room", "room": name}):
            self.new_room_var.set("")
        else:
            self.handle_disconnect()

    def on_room_double_click(self, event):
        selection = self.room_list.curselection()
        if not selection:
            return
        name = self.room_names[selection[0]]
        if name != self.current_room and not (self.conn and self.conn.send({"type": "join_room", "room": name})):
            if name != self.current_room:
                self.handle_disconnect()

    def on_logout(self):
        if self.conn:
            self.conn.close()
            self.conn = None
        self.username = None
        self.current_room = None
        self.show_login("You are logged out.")

    def on_close(self):
        if self.conn:
            self.conn.close()
        self.root.destroy()

    def insert_shortcode(self, name):
        self.message_entry.insert(tk.INSERT, f":{name}: ")
        self.message_entry.focus_set()

    def handle_disconnect(self):
        """The connection is gone: go back to the login screen with a message."""
        if self.conn:
            self.conn.close()
            self.conn = None
        self.username = None
        self.current_room = None
        self.show_login("Disconnected from the server. Please log in again.", error=True)

    # ------------------------------------------------- incoming messages
    def process_incoming(self):
        """Handle everything the network thread has collected. Runs every 100 ms."""
        try:
            while True:
                conn, kind, data = self.incoming.get_nowait()
                if conn is not self.conn:
                    continue            # an old connection (after logout), ignore
                if kind == "connect_failed":
                    self.conn = None
                    self.set_buttons_enabled(True)
                    self.show_login_message(data, error=True)
                elif kind == "closed":
                    self.handle_disconnect()
                else:
                    self.handle_server_message(data)
        except queue.Empty:
            pass
        self.root.after(100, self.process_incoming)

    def handle_server_message(self, data):
        kind = data.get("type")
        if kind == "auth_ok":
            self.username = data["username"]
            self.show_chat()
        elif kind == "error":
            if self.username:
                self.show_chat_message(data.get("message", "Error"), error=True)
            else:
                self.set_buttons_enabled(True)
                self.show_login_message(data.get("message", "Error"), error=True)
        elif kind == "rooms":
            self.update_rooms(data.get("rooms", []))
        elif kind == "joined":
            self.on_joined(data)
        elif kind == "users":
            if data.get("room") == self.current_room:
                self.update_users(data.get("users", []))
        elif kind == "message":
            if data.get("room") == self.current_room:
                self.add_chat_line(data["time"], data["user"], data["text"])
                if data["user"] != self.username:
                    self.notify_new_message()
        elif kind == "system":
            if data.get("room") == self.current_room:
                self.add_system_line(f"[{data['time']}] {data['text']}")

    def on_joined(self, data):
        """We entered a room: clear the screen and show its old messages."""
        self.current_room = data["room"]
        self.room_label.config(text=f"# {self.current_room}")
        self.chat_text.config(state="normal")
        self.chat_text.delete("1.0", tk.END)
        self.chat_text.config(state="disabled")
        history = data.get("history", [])
        if history:
            self.append_text("--- earlier messages ---\n", "history_note")
            for item in history:
                self.add_chat_line(item["time"], item["user"], item["text"])
            self.append_text("--- end of earlier messages ---\n", "history_note")
        self.add_system_line(f"You joined #{self.current_room}.")
        self.highlight_current_room()
        self.show_chat_message(" ")

    def update_rooms(self, rooms):
        self.room_names = [room["name"] for room in rooms]
        self.room_list.delete(0, tk.END)
        for room in rooms:
            self.room_list.insert(tk.END, f"# {room['name']}  ({room['online']} online)")
        self.highlight_current_room()

    def highlight_current_room(self):
        self.room_list.selection_clear(0, tk.END)
        if self.current_room in self.room_names:
            self.room_list.selection_set(self.room_names.index(self.current_room))

    def update_users(self, users):
        self.user_list.delete(0, tk.END)
        for name in users:
            self.user_list.insert(tk.END, name + ("  (you)" if name == self.username else ""))

    # --------------------------------------------------- showing messages
    def append_text(self, text, *tags):
        """Add text at the end of the chat area (it is read-only, so unlock it for a moment)."""
        self.chat_text.config(state="normal")
        try:
            self.chat_text.insert(tk.END, text, tags)
        except tk.TclError:
            self.chat_text.insert(tk.END, tk_safe(text), tags)
        self.chat_text.config(state="disabled")
        self.chat_text.see(tk.END)

    def add_chat_line(self, time_text, user, text):
        """Show a message like  [14:35] Alice: Hello"""
        user_tag = "own" if user == self.username else f"user{user_color_index(user)}"
        self.append_text(f"[{time_text}] ", "time")
        self.append_text(f"{user}: ", user_tag)
        self.append_text(render_emojis(text) + "\n")

    def add_system_line(self, text):
        self.append_text(text + "\n", "system")

    # ------------------------------------------------------ notifications
    def window_has_focus(self):
        return self.root.focus_displayof() is not None

    def notify_new_message(self):
        """If the window is not in focus: change the title, beep and flash the taskbar."""
        if self.window_has_focus():
            return
        self.unread += 1
        self.root.title(f"({self.unread}) New message - {APP_TITLE}")
        try:
            self.root.bell()
        except tk.TclError:
            pass
        flash_taskbar(self.root)

    def on_focus_in(self, event=None):
        if self.unread:
            self.unread = 0
            self.root.title(APP_TITLE)


def main():
    root = tk.Tk()
    ChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()