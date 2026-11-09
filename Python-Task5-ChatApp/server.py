"""
Chat Server (Advanced Tier) - Backend

Author : Rabia Azam
Program: Oasis Infobyte Internship (OIBSIP) - Python Programming Track
Task   : Task 5 - Chat Application (Advanced)

This is the BACKEND. Start it first, then open one or more client windows (client.py).

What the server does:
    - listens for many clients at the same time (one thread per client)
    - user registration and login (passwords are hashed, never stored as plain text)
    - multiple chat rooms that users can create and join
    - saves every message in SQLite, and sends the last messages to a user who joins a room
    - tells the room when someone joins, leaves or disconnects
    - basic protection: message size limit and a simple flood limit

Messages between client and server are JSON, one per line, over plain TCP.
NOTE: this connection is NOT encrypted (see README, "Security and Privacy").
"""

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing
from datetime import datetime

# ---------------------------------------------------------------- settings
DEFAULT_HOST = "127.0.0.1"      # localhost: only this computer can connect
DEFAULT_PORT = 5555
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_data.db")

DEFAULT_ROOM = "General"
HISTORY_LIMIT = 50              # how many old messages a user sees when joining a room
MAX_MESSAGE_LENGTH = 500
MAX_LINE_BYTES = 8192           # a client that sends a longer line without a newline is disconnected
FLOOD_MAX_MESSAGES = 10         # more than 10 messages ...
FLOOD_WINDOW_SECONDS = 5        # ... in 5 seconds is too fast

PBKDF2_ROUNDS = 200_000
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_]{3,20}")
ROOM_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,20}")
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 64


def log(text):
    """Print a line with the time, so the server window shows what is happening."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}", flush=True)


# --------------------------------------------------------------- database
class ChatDatabase:
    """All SQLite work lives here. Queries use ? placeholders, so user input cannot damage the database."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()    # one database job at a time keeps SQLite happy with many threads
        self.create_tables()

    def connect(self):
        return sqlite3.connect(self.path)

    def create_tables(self):
        with self.lock, closing(self.connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                                salt TEXT NOT NULL,
                                password_hash TEXT NOT NULL,
                                created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS rooms (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                name TEXT NOT NULL UNIQUE COLLATE NOCASE)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS messages (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                room TEXT NOT NULL COLLATE NOCASE,
                                username TEXT NOT NULL,
                                text TEXT NOT NULL,
                                sent_at TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_room ON messages (room, id)")
            conn.execute("INSERT OR IGNORE INTO rooms (name) VALUES (?)", (DEFAULT_ROOM,))

    @staticmethod
    def hash_password(password, salt):
        """Return the PBKDF2 hash (hex text) of a password and a salt (bytes)."""
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS).hex()

    def add_user(self, username, password):
        """Create a user. Raise ValueError if the name is taken. Return the saved username."""
        salt = secrets.token_bytes(16)      # a different random salt for every user
        password_hash = self.hash_password(password, salt)
        try:
            with self.lock, closing(self.connect()) as conn, conn:
                conn.execute("INSERT INTO users (username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                             (username, salt.hex(), password_hash, datetime.now().isoformat(timespec="seconds")))
        except sqlite3.IntegrityError:
            raise ValueError("That username is already taken.") from None
        return username

    def check_login(self, username, password):
        """Return the saved username if the password is right, otherwise None."""
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT username, salt, password_hash FROM users WHERE username = ?",
                               (username,)).fetchone()
        if row is None:
            # Do the same amount of work for unknown users, so response time does not reveal if a name exists
            self.hash_password(password, b"0" * 16)
            return None
        saved_name, salt_hex, saved_hash = row
        new_hash = self.hash_password(password, bytes.fromhex(salt_hex))
        return saved_name if hmac.compare_digest(new_hash, saved_hash) else None

    def get_room(self, name):
        """Return the room's saved spelling, or None if there is no such room."""
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT name FROM rooms WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def add_room(self, name):
        """Create a room. Raise ValueError if it already exists."""
        try:
            with self.lock, closing(self.connect()) as conn, conn:
                conn.execute("INSERT INTO rooms (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            raise ValueError("That room already exists. Double-click it in the list to join.") from None
        return name

    def list_rooms(self):
        with self.lock, closing(self.connect()) as conn:
            return [row[0] for row in conn.execute("SELECT name FROM rooms ORDER BY name COLLATE NOCASE")]

    def add_message(self, room, username, text, sent_at):
        with self.lock, closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO messages (room, username, text, sent_at) VALUES (?, ?, ?, ?)",
                         (room, username, text, sent_at.isoformat(timespec="seconds")))

    def get_history(self, room, limit=HISTORY_LIMIT):
        """Return the newest `limit` messages of a room, oldest first, as (username, text, sent_at)."""
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute("SELECT username, text, sent_at FROM messages WHERE room = ? "
                                "ORDER BY id DESC LIMIT ?", (room, limit)).fetchall()
        return list(reversed(rows))


def format_time(sent_at):
    """Return '14:35' for today's messages and '05 Nov 14:35' for older ones."""
    moment = sent_at if isinstance(sent_at, datetime) else datetime.fromisoformat(sent_at)
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M")
    return moment.strftime("%d %b %H:%M")


# ----------------------------------------------------------------- clients
class ClientConnection:
    """One connected client."""

    def __init__(self, sock, address):
        self.sock = sock
        self.address = address
        self.username = None            # set after a successful login
        self.room = None                # the room the user is in now
        self.send_lock = threading.Lock()
        self.recent_messages = deque()  # times of the latest messages, for the flood limit

    def send(self, payload):
        """Send one JSON message. Return False if the client is gone."""
        data = (json.dumps(payload) + "\n").encode("utf-8")
        try:
            with self.send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            return False

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def is_flooding(self):
        """True if the user sent too many messages in a short time."""
        now = time.monotonic()
        while self.recent_messages and now - self.recent_messages[0] > FLOOD_WINDOW_SECONDS:
            self.recent_messages.popleft()
        if len(self.recent_messages) >= FLOOD_MAX_MESSAGES:
            return True
        self.recent_messages.append(now)
        return False


# ------------------------------------------------------------------ server
class ChatServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, db_path=DB_FILE):
        self.host = host
        self.port = port
        self.db = ChatDatabase(db_path)
        self.clients = set()
        self.lock = threading.RLock()   # protects self.clients and each client's username/room
        self.listener = None
        self.running = False

    # --- starting and stopping
    def start(self):
        """Open the port and accept clients in a background thread."""
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((self.host, self.port))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]      # useful when the port was 0 (any free port)
        self.running = True
        threading.Thread(target=self.accept_loop, daemon=True).start()
        log(f"Chat server running on {self.host}:{self.port}")

    def serve_forever(self):
        self.start()
        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            log("Stopping the server...")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.close()

    def accept_loop(self):
        while self.running:
            try:
                sock, address = self.listener.accept()
            except OSError:
                break                   # the listener was closed
            client = ClientConnection(sock, address)
            with self.lock:
                self.clients.add(client)
            threading.Thread(target=self.handle_client, args=(client,), daemon=True).start()

    # --- one client
    def handle_client(self, client):
        """Read the client's messages (one JSON per line) until it disconnects."""
        buffer = b""
        try:
            while True:
                chunk = client.sock.recv(4096)
                if not chunk:
                    break               # the client closed the connection
                buffer += chunk
                if b"\n" not in buffer and len(buffer) > MAX_LINE_BYTES:
                    break               # too much data without a line end: not a real client
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self.handle_line(client, line)
        except OSError:
            pass
        finally:
            self.disconnect(client)

    def handle_line(self, client, line):
        """Understand one message and call the right handler."""
        try:
            payload = json.loads(line.decode("utf-8"))
            kind = payload["type"]
        except (ValueError, KeyError, TypeError):       # includes bad UTF-8 and non-object JSON
            client.send({"type": "error", "message": "Invalid message."})
            return

        handlers = {"register": self.on_register, "login": self.on_login,
                    "join_room": self.on_join_room, "create_room": self.on_create_room,
                    "list_rooms": self.on_list_rooms, "message": self.on_message}
        handler = handlers.get(kind)
        if handler is None:
            client.send({"type": "error", "message": "Unknown request."})
        elif kind not in ("register", "login") and not client.username:
            client.send({"type": "error", "message": "Please log in first."})
        else:
            handler(client, payload)

    # --- handlers
    def check_credentials_format(self, client, payload):
        """Return (username, password) if both look valid, else send an error and return None."""
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            client.send({"type": "error", "message": "Enter a username and a password."})
            return None
        username = username.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            client.send({"type": "error",
                         "message": "Username must be 3-20 characters: letters, numbers or underscore."})
            return None
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            client.send({"type": "error",
                         "message": f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."})
            return None
        return username, password

    def on_register(self, client, payload):
        if client.username:
            client.send({"type": "error", "message": "You are already logged in."})
            return
        credentials = self.check_credentials_format(client, payload)
        if credentials is None:
            return
        try:
            username = self.db.add_user(*credentials)
        except ValueError as error:
            client.send({"type": "error", "message": str(error)})
            return
        log(f"New user registered: {username}")
        self.finish_login(client, username)

    def on_login(self, client, payload):
        if client.username:
            client.send({"type": "error", "message": "You are already logged in."})
            return
        credentials = self.check_credentials_format(client, payload)
        if credentials is None:
            return
        username = self.db.check_login(*credentials)
        if username is None:
            time.sleep(0.5)             # slows down password guessing a little
            client.send({"type": "error", "message": "Wrong username or password."})
            return
        self.finish_login(client, username)

    def finish_login(self, client, username):
        """Mark the client as logged in and put it in the default room."""
        with self.lock:
            if any(other.username and other.username.lower() == username.lower() for other in self.clients):
                client.send({"type": "error", "message": "That user is already logged in somewhere else."})
                return
            client.username = username
        client.send({"type": "auth_ok", "username": username})
        log(f"{username} logged in")
        self.join_room(client, DEFAULT_ROOM)

    def on_list_rooms(self, client, payload):
        client.send(self.rooms_payload())

    def on_create_room(self, client, payload):
        name = payload.get("room")
        if not isinstance(name, str) or not ROOM_PATTERN.fullmatch(name.strip()):
            client.send({"type": "error",
                         "message": "Room name must be 1-20 characters: letters, numbers, - or _."})
            return
        try:
            name = self.db.add_room(name.strip())
        except ValueError as error:
            client.send({"type": "error", "message": str(error)})
            return
        log(f"{client.username} created room {name}")
        self.join_room(client, name)    # the creator goes into the new room (this also updates everyone's room list)

    def on_join_room(self, client, payload):
        name = payload.get("room")
        self.join_room(client, name if isinstance(name, str) else "")

    def on_message(self, client, payload):
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        text = " ".join(text.split())   # one line, no extra spaces or line breaks
        if len(text) > MAX_MESSAGE_LENGTH:
            client.send({"type": "error", "message": f"Message is too long (maximum {MAX_MESSAGE_LENGTH} characters)."})
            return
        if client.is_flooding():
            client.send({"type": "error", "message": "You are sending messages too fast. Please slow down."})
            return
        with self.lock:
            room, username = client.room, client.username
        if not room:
            client.send({"type": "error", "message": "Join a room first."})
            return
        sent_at = datetime.now()
        self.db.add_message(room, username, text, sent_at)
        self.broadcast(room, {"type": "message", "room": room, "user": username,
                              "time": format_time(sent_at), "text": text})

    # --- rooms and broadcasting
    def members(self, room):
        """Return the clients that are in a room now."""
        with self.lock:
            return [c for c in self.clients if c.room and room and c.room.lower() == room.lower()]

    def broadcast(self, room, payload, exclude=None):
        for member in self.members(room):
            if member is not exclude:
                member.send(payload)

    def system_message(self, room, text, exclude=None):
        self.broadcast(room, {"type": "system", "room": room, "text": text,
                              "time": format_time(datetime.now())}, exclude=exclude)

    def rooms_payload(self):
        names = self.db.list_rooms()
        with self.lock:
            counts = {}
            for client in self.clients:
                if client.room:
                    counts[client.room.lower()] = counts.get(client.room.lower(), 0) + 1
        return {"type": "rooms", "rooms": [{"name": n, "online": counts.get(n.lower(), 0)} for n in names]}

    def send_rooms_to_all(self):
        payload = self.rooms_payload()
        with self.lock:
            logged_in = [c for c in self.clients if c.username]
        for client in logged_in:
            client.send(payload)

    def send_users(self, room):
        """Tell everyone in a room who is online there."""
        users = sorted((c.username for c in self.members(room)), key=str.lower)
        self.broadcast(room, {"type": "users", "room": room, "users": users})

    def join_room(self, client, name):
        room = self.db.get_room(name.strip())
        if room is None:
            client.send({"type": "error", "message": "That room does not exist."})
            return
        with self.lock:
            old_room = client.room
            if old_room and old_room.lower() == room.lower():
                return                  # already there
            client.room = room
        username = client.username

        if old_room:
            self.system_message(old_room, f"{username} left the room.")
            self.send_users(old_room)

        history = [{"user": user, "text": text, "time": format_time(sent_at)}
                   for user, text, sent_at in self.db.get_history(room)]
        client.send({"type": "joined", "room": room, "history": history})
        self.system_message(room, f"{username} joined the room.", exclude=client)
        self.send_users(room)
        self.send_rooms_to_all()

    def disconnect(self, client):
        """Clean up after a client leaves (closed window, lost connection, logout)."""
        with self.lock:
            if client not in self.clients:
                return
            self.clients.discard(client)
            username, room = client.username, client.room
            client.username = None
            client.room = None
        client.close()
        if username:
            log(f"{username} disconnected")
        if username and room:
            self.system_message(room, f"{username} disconnected.")
            self.send_users(room)
            self.send_rooms_to_all()


def main():
    parser = argparse.ArgumentParser(description="Chat server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="address to listen on (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to listen on (default 5555)")
    args = parser.parse_args()

    if args.host != DEFAULT_HOST:
        log("WARNING: other computers can connect, and the connection is NOT encrypted. "
            "Do not use real passwords.")
    try:
        ChatServer(args.host, args.port).serve_forever()
    except OSError as error:
        print(f"Could not start the server on {args.host}:{args.port}: {error}")
        print("Is another copy of the server already running? Try a different port: python server.py --port 5556")


if __name__ == "__main__":
    main()