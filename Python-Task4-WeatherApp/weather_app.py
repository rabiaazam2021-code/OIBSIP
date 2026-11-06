"""
Weather App (Advanced Tier) - Desktop GUI

Author : Rabia Azam
Program: Oasis Infobyte Internship (OIBSIP) - Python Programming Track
Task   : Task 4 - Basic Weather App (Advanced)

Features:
    - city name or ZIP code search (OpenWeatherMap API, free tier)
    - current temperature (C and F), humidity, description, wind speed
    - weather icons from OpenWeatherMap
    - forecast for the next hours (3-hour steps) and the next 5 days
    - Celsius / Fahrenheit switch
    - "Use My Location" button (finds your city from your IP address with ipinfo.io)
    - all error messages are shown inside the window
    - the internet work runs in a background thread, so the window never freezes

Setup: see README.md (you need a free OpenWeatherMap API key in config.json).
"""

import json
import os
import queue
import re
import threading
import tkinter as tk
from datetime import datetime, timezone
from io import BytesIO

# requests and Pillow are extra packages: pip install requests pillow
try:
    import requests
    from PIL import Image, ImageTk
except ImportError:
    print("Missing packages. Please run:  pip install requests pillow")
    raise SystemExit(1)

# ---------------------------------------------------------------- settings
API_BASE = "https://api.openweathermap.org/data/2.5"
ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"
LOCATION_URL = "https://ipinfo.io/json"
TIMEOUT_SECONDS = 10

# The config file is read from the same folder as this script
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
PLACEHOLDER_KEY = "YOUR_API_KEY_HERE"

HOURLY_SLOTS = 4        # the free forecast has 3-hour steps, so 4 steps cover 12 hours
DAILY_DAYS = 5

COLOR_ERROR = "#d9382f"
COLOR_OK = "#2e9b4f"
COLOR_BG = "#f2f6fa"
COLOR_CARD = "#ffffff"
COLOR_MUTED = "#666666"


class WeatherError(Exception):
    """An error with a message that is safe and clear to show to the user."""


# --------------------------------------------------------- helper logic
def load_api_key():
    """Return the API key from the OPENWEATHER_API_KEY variable or from config.json, else None."""
    key = os.environ.get("OPENWEATHER_API_KEY", "").strip()
    if not key and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as file:
                key = str(json.load(file).get("api_key", "")).strip()
        except (OSError, ValueError):
            key = ""
    if not key or key == PLACEHOLDER_KEY:
        return None
    return key


def build_query(text):
    """Turn what the user typed into API parameters. Raise ValueError if the input is empty."""
    text = text.strip()
    if not text:
        raise ValueError("Please enter a city name or a ZIP code.")
    if len(text) > 60:
        raise ValueError("That is too long. Please enter a city name or a ZIP code.")

    # A ZIP code: digits, optionally followed by a country code, like 90210 or 54000,PK
    zip_match = re.fullmatch(r"(\d{3,10})\s*(?:,\s*([A-Za-z]{2}))?", text)
    if zip_match:
        country = (zip_match.group(2) or "US").upper()
        return {"zip": f"{zip_match.group(1)},{country}"}
    return {"q": text}


def c_to_f(celsius):
    """Convert Celsius to Fahrenheit."""
    return celsius * 9 / 5 + 32


def format_temp(celsius, unit):
    """Return a temperature like '21°C' or '70°F'."""
    value = celsius if unit == "C" else c_to_f(celsius)
    return f"{round(value)}°{unit}"


def format_wind(speed_ms, unit):
    """Return the wind speed in m/s for Celsius mode and in mph for Fahrenheit mode."""
    if unit == "C":
        return f"{speed_ms:.1f} m/s"
    return f"{speed_ms * 2.23694:.1f} mph"


def clock_text(local_time):
    """Return a time like '3 PM' from a datetime."""
    hour = local_time.hour % 12 or 12
    return f"{hour} {'AM' if local_time.hour < 12 else 'PM'}"


def parse_current(data):
    """Pick the values we need out of the 'current weather' answer."""
    try:
        return {
            "city": data["name"],
            "country": data["sys"].get("country", ""),
            "temp_c": float(data["main"]["temp"]),
            "feels_c": float(data["main"]["feels_like"]),
            "humidity": int(data["main"]["humidity"]),
            "description": data["weather"][0]["description"].capitalize(),
            "icon": data["weather"][0]["icon"],
            "wind_ms": float(data["wind"]["speed"]),
            "lat": data["coord"]["lat"],
            "lon": data["coord"]["lon"],
            "timestamp": data["dt"],
        }
    except (KeyError, IndexError, TypeError, ValueError):
        raise WeatherError("The weather service sent data in an unexpected format.") from None


def parse_forecast(data, now_timestamp):
    """Return (hourly, daily) forecast lists from the 5-day / 3-hour forecast answer."""
    try:
        offset = data["city"].get("timezone", 0)    # the city's time difference from UTC, in seconds
        slots = []
        for item in data["list"]:
            local_time = datetime.fromtimestamp(item["dt"] + offset, tz=timezone.utc)
            slots.append({
                "timestamp": item["dt"],
                "local": local_time,
                "temp_c": float(item["main"]["temp"]),
                "icon": item["weather"][0]["icon"],
                "description": item["weather"][0]["description"].capitalize(),
            })
    except (KeyError, IndexError, TypeError, ValueError):
        raise WeatherError("The forecast data was in an unexpected format.") from None

    # Next hours: the first few steps that are still in the future
    hourly = [
        {"label": clock_text(slot["local"]), "temp_c": slot["temp_c"], "icon": slot["icon"]}
        for slot in slots if slot["timestamp"] > now_timestamp
    ][:HOURLY_SLOTS]

    # Next days: group the steps by the city's local date, skipping today
    today = datetime.fromtimestamp(now_timestamp + offset, tz=timezone.utc).date()
    days = {}
    for slot in slots:
        if slot["local"].date() > today:
            days.setdefault(slot["local"].date(), []).append(slot)

    daily = []
    for day in sorted(days)[:DAILY_DAYS]:
        day_slots = days[day]
        midday = min(day_slots, key=lambda slot: abs(slot["local"].hour - 12))  # the step closest to noon
        daily.append({
            "label": midday["local"].strftime("%a %d %b"),
            "high_c": max(slot["temp_c"] for slot in day_slots),
            "low_c": min(slot["temp_c"] for slot in day_slots),
            "icon": midday["icon"][:2] + "d",       # always show the daytime version of the icon
            "description": midday["description"],
        })
    return hourly, daily


# ------------------------------------------------------------ API client
class WeatherClient:
    """Talks to the OpenWeatherMap API."""

    def __init__(self, api_key, session=None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def get_json(self, path, params):
        """Call the API and return the JSON answer. Raise WeatherError with a clear message on problems."""
        params = dict(params, appid=self.api_key, units="metric")
        try:
            response = self.session.get(f"{API_BASE}/{path}", params=params, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.Timeout:
            raise WeatherError("The request timed out. Check your internet and try again.") from None
        except requests.exceptions.ConnectionError:
            raise WeatherError("No internet connection. Please connect and try again.") from None
        except requests.exceptions.RequestException:
            raise WeatherError("A network problem happened. Please try again.") from None

        if response.status_code == 401:
            raise WeatherError("Invalid API key. A new key can take a few hours to start working.")
        if response.status_code == 404:
            raise WeatherError("City not found. Check the spelling, or try 'City,CountryCode' like Lahore,PK.")
        if response.status_code == 429:
            raise WeatherError("Too many requests. Please wait a minute and try again.")
        if response.status_code != 200:
            raise WeatherError(f"The weather service had a problem (code {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise WeatherError("The weather service sent an unreadable answer.") from None

    def fetch_icon(self, code):
        """Download one icon image. Return the bytes, or None if it fails (the app works without icons)."""
        try:
            response = self.session.get(ICON_URL.format(code=code), timeout=TIMEOUT_SECONDS)
            if response.status_code == 200:
                return response.content
        except requests.exceptions.RequestException:
            pass
        return None

    def fetch_all(self, query):
        """Get the current weather, the forecast and the icons for a city or ZIP code."""
        current = parse_current(self.get_json("weather", query))
        forecast_data = self.get_json("forecast", {"lat": current["lat"], "lon": current["lon"]})
        hourly, daily = parse_forecast(forecast_data, current["timestamp"])

        codes = {current["icon"]} | {item["icon"] for item in hourly} | {item["icon"] for item in daily}
        icons = {}
        for code in codes:
            image_bytes = self.fetch_icon(code)
            if image_bytes:
                icons[code] = image_bytes
        return {"current": current, "hourly": hourly, "daily": daily, "icons": icons}

    def find_my_city(self):
        """Guess the user's city from their IP address (ipinfo.io). Return text like 'Lahore,PK'."""
        try:
            response = self.session.get(LOCATION_URL, timeout=TIMEOUT_SECONDS)
            info = response.json()
            return f"{info['city']},{info['country']}"
        except requests.exceptions.Timeout:
            raise WeatherError("Finding your location timed out. Type your city instead.") from None
        except (requests.exceptions.RequestException, ValueError, KeyError):
            raise WeatherError("Could not find your location. Type your city instead.") from None


# ------------------------------------------------------------------- GUI
class WeatherApp:
    """The main window of the program."""

    def __init__(self, root, client=None):
        self.root = root
        self.root.title("Weather App")
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_BG, padx=16, pady=12)

        self.city_var = tk.StringVar()
        self.unit_var = tk.StringVar(value="C")
        self.data = None                    # the last weather result, kept so the unit switch can redraw it
        self.photos = {}                    # keeps icon images alive (tkinter needs this)
        self.results = queue.Queue()        # the background thread puts its answer here
        self.busy = False

        # Use the given client (used for testing), or build one from the API key
        self.client = client
        self.api_key_problem = False
        if self.client is None:
            api_key = load_api_key()
            if api_key:
                self.client = WeatherClient(api_key)
            else:
                self.api_key_problem = True

        self.build_widgets()
        self.place_window_on_screen()

        if self.api_key_problem:
            self.show_message("API key not found. Create config.json with your key (see README).", error=True)

    # -------------------------------------------------------------- layout
    def build_widgets(self):
        """Create and place every widget."""
        tk.Label(self.root, text="Weather App", bg=COLOR_BG,
                 font=("Segoe UI", 16, "bold")).grid(row=0, column=0, pady=(0, 8))

        # --- Search bar
        bar = tk.Frame(self.root, bg=COLOR_BG)
        bar.grid(row=1, column=0, sticky="ew")
        tk.Label(bar, text="City or ZIP code:", bg=COLOR_BG, font=("Segoe UI", 10)).pack(side="left")
        entry = tk.Entry(bar, textvariable=self.city_var, width=24, font=("Segoe UI", 11))
        entry.pack(side="left", padx=(6, 6))
        entry.focus_set()
        self.search_button = tk.Button(bar, text="Get Weather", font=("Segoe UI", 10, "bold"),
                                       bg="#2f6fdb", fg="white", activebackground="#2559b3",
                                       activeforeground="white", command=self.on_search, padx=8)
        self.search_button.pack(side="left")
        self.location_button = tk.Button(bar, text="Use My Location", command=self.on_use_location, padx=6)
        self.location_button.pack(side="left", padx=(6, 0))

        # Unit switch on the right side of the bar
        unit_box = tk.Frame(bar, bg=COLOR_BG)
        unit_box.pack(side="right")
        tk.Radiobutton(unit_box, text="°C", variable=self.unit_var, value="C", bg=COLOR_BG,
                       command=self.render).pack(side="left")
        tk.Radiobutton(unit_box, text="°F", variable=self.unit_var, value="F", bg=COLOR_BG,
                       command=self.render).pack(side="left")

        tk.Label(self.root, text="Tip: for a ZIP code outside the USA add the country, like 54000,PK",
                 bg=COLOR_BG, fg=COLOR_MUTED, font=("Segoe UI", 8)).grid(row=2, column=0, sticky="w")

        # --- Message area (errors and information appear here, not in the terminal)
        self.message_label = tk.Label(self.root, text=" ", bg=COLOR_BG, font=("Segoe UI", 10), wraplength=720)
        self.message_label.grid(row=3, column=0, sticky="w", pady=(4, 6))

        # --- Current weather (left) and next hours (right)
        middle = tk.Frame(self.root, bg=COLOR_BG)
        middle.grid(row=4, column=0, sticky="ew")

        current = tk.Frame(middle, bg=COLOR_CARD, padx=14, pady=10, highlightbackground="#d5dde6",
                           highlightthickness=1)
        current.pack(side="left", fill="y")
        self.city_label = tk.Label(current, text="-", bg=COLOR_CARD, font=("Segoe UI", 13, "bold"))
        self.city_label.pack(anchor="w")
        top_row = tk.Frame(current, bg=COLOR_CARD)
        top_row.pack(anchor="w")
        self.current_icon = tk.Label(top_row, bg=COLOR_CARD)
        self.current_icon.pack(side="left")
        self.temp_label = tk.Label(top_row, text="--", bg=COLOR_CARD, font=("Segoe UI", 30, "bold"))
        self.temp_label.pack(side="left", padx=(4, 0))
        self.both_label = tk.Label(current, text=" ", bg=COLOR_CARD, fg=COLOR_MUTED, font=("Segoe UI", 9))
        self.both_label.pack(anchor="w")
        self.description_label = tk.Label(current, text="-", bg=COLOR_CARD, font=("Segoe UI", 11))
        self.description_label.pack(anchor="w", pady=(2, 4))
        self.feels_label = tk.Label(current, text="Feels like: -", bg=COLOR_CARD, font=("Segoe UI", 10))
        self.feels_label.pack(anchor="w")
        self.humidity_label = tk.Label(current, text="Humidity: -", bg=COLOR_CARD, font=("Segoe UI", 10))
        self.humidity_label.pack(anchor="w")
        self.wind_label = tk.Label(current, text="Wind: -", bg=COLOR_CARD, font=("Segoe UI", 10))
        self.wind_label.pack(anchor="w")

        hourly_box = tk.Frame(middle, bg=COLOR_BG)
        hourly_box.pack(side="left", fill="y", padx=(12, 0))
        tk.Label(hourly_box, text="Next hours (every 3 hours)", bg=COLOR_BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        hourly_row = tk.Frame(hourly_box, bg=COLOR_BG)
        hourly_row.pack(anchor="w", pady=(4, 0))
        self.hourly_cards = [self.make_card(hourly_row, with_description=False) for _ in range(HOURLY_SLOTS)]

        # --- Next 5 days
        tk.Label(self.root, text="Next 5 days", bg=COLOR_BG,
                 font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="w", pady=(10, 0))
        daily_row = tk.Frame(self.root, bg=COLOR_BG)
        daily_row.grid(row=6, column=0, sticky="w", pady=(4, 0))
        self.daily_cards = [self.make_card(daily_row, with_description=True) for _ in range(DAILY_DAYS)]

        # Pressing Enter does the same as clicking Get Weather
        self.root.bind("<Return>", lambda event: self.on_search())

        self.render()

    def make_card(self, parent, with_description):
        """Create one small forecast card and return its labels in a dictionary."""
        frame = tk.Frame(parent, bg=COLOR_CARD, padx=8, pady=6, highlightbackground="#d5dde6",
                         highlightthickness=1)
        frame.pack(side="left", padx=(0, 8))
        card = {
            "title": tk.Label(frame, text="-", bg=COLOR_CARD, font=("Segoe UI", 9, "bold"), width=11),
            "icon": tk.Label(frame, bg=COLOR_CARD),
            "temp": tk.Label(frame, text="-", bg=COLOR_CARD, font=("Segoe UI", 10)),
        }
        card["title"].pack()
        card["icon"].pack()
        card["temp"].pack()
        if with_description:
            card["text"] = tk.Label(frame, text=" ", bg=COLOR_CARD, fg=COLOR_MUTED,
                                    font=("Segoe UI", 8), wraplength=95, height=2)
            card["text"].pack()
        return card

    def place_window_on_screen(self):
        """Centre the window horizontally and put it near the top so nothing is cut off."""
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        self.root.geometry(f"+{x}+10")

    # ------------------------------------------------------------- actions
    def on_search(self):
        """Check the input, then fetch the weather in a background thread."""
        if self.busy:
            return
        if self.client is None:
            self.show_message("API key not found. Create config.json with your key (see README).", error=True)
            return
        try:
            query = build_query(self.city_var.get())
        except ValueError as error:
            self.show_message(str(error), error=True)
            return
        self.start_background(lambda: ("weather", self.client.fetch_all(query)))

    def on_use_location(self):
        """Find the user's city from the IP address, then fetch its weather."""
        if self.busy:
            return
        if self.client is None:
            self.show_message("API key not found. Create config.json with your key (see README).", error=True)
            return

        def job():
            city = self.client.find_my_city()
            return ("weather", self.client.fetch_all(build_query(city)), city)
        self.start_background(job)

    def start_background(self, job):
        """Run a job in another thread so the window stays responsive."""
        self.busy = True
        self.search_button.config(state="disabled")
        self.location_button.config(state="disabled")
        self.show_message("Loading...", error=False, color=COLOR_MUTED)

        def worker():
            try:
                self.results.put(("ok", job()))
            except WeatherError as error:
                self.results.put(("error", str(error)))
            except Exception:
                self.results.put(("error", "Something went wrong. Please try again."))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.check_results)

    def check_results(self):
        """Look for the background thread's answer. Check again soon if it is not ready."""
        try:
            kind, payload = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self.check_results)
            return

        self.busy = False
        self.search_button.config(state="normal")
        self.location_button.config(state="normal")

        if kind == "error":
            self.data = None
            self.render()               # clear the old weather so it does not look current
            self.show_message(payload, error=True)
            return

        self.data = payload[1]
        if len(payload) > 2:            # the "Use My Location" button also fills the search box
            self.city_var.set(payload[2])
        self.render()
        self.show_message("Weather updated.")

    # ------------------------------------------------------------- drawing
    def get_photo(self, code, size):
        """Return a tkinter image for an icon code, or None if the icon was not downloaded."""
        key = (code, size)
        if key not in self.photos:
            image_bytes = (self.data or {}).get("icons", {}).get(code)
            if not image_bytes:
                return None
            image = Image.open(BytesIO(image_bytes)).convert("RGBA").resize((size, size))
            self.photos[key] = ImageTk.PhotoImage(image)
        return self.photos[key]

    def set_icon(self, label, code, size):
        """Show an icon on a label (or nothing if there is no icon)."""
        photo = self.get_photo(code, size) if code else None
        label.config(image=photo if photo else "")
        label.image = photo             # keep a reference

    def render(self):
        """Draw the current data in the selected unit. With no data, show empty cards."""
        unit = self.unit_var.get()
        data = self.data

        if not data:
            self.city_label.config(text="-")
            self.temp_label.config(text="--")
            self.both_label.config(text=" ")
            self.description_label.config(text="-")
            self.feels_label.config(text="Feels like: -")
            self.humidity_label.config(text="Humidity: -")
            self.wind_label.config(text="Wind: -")
            self.set_icon(self.current_icon, None, 90)
            for card in self.hourly_cards + self.daily_cards:
                card["title"].config(text="-")
                card["temp"].config(text="-")
                self.set_icon(card["icon"], None, 44)
                if "text" in card:
                    card["text"].config(text=" ")
            return

        now = data["current"]
        place = f"{now['city']}, {now['country']}" if now["country"] else now["city"]
        self.city_label.config(text=place)
        self.temp_label.config(text=format_temp(now["temp_c"], unit))
        self.both_label.config(text=f"{format_temp(now['temp_c'], 'C')}  /  {format_temp(now['temp_c'], 'F')}")
        self.description_label.config(text=now["description"])
        self.feels_label.config(text=f"Feels like: {format_temp(now['feels_c'], unit)}")
        self.humidity_label.config(text=f"Humidity: {now['humidity']}%")
        self.wind_label.config(text=f"Wind: {format_wind(now['wind_ms'], unit)}")
        self.set_icon(self.current_icon, now["icon"], 90)

        for card, item in zip(self.hourly_cards, data["hourly"]):
            card["title"].config(text=item["label"])
            card["temp"].config(text=format_temp(item["temp_c"], unit))
            self.set_icon(card["icon"], item["icon"], 44)

        for card, item in zip(self.daily_cards, data["daily"]):
            card["title"].config(text=item["label"])
            card["temp"].config(text=f"{format_temp(item['high_c'], unit)} / {format_temp(item['low_c'], unit)}")
            card["text"].config(text=item["description"])
            self.set_icon(card["icon"], item["icon"], 44)

    def show_message(self, text, error=False, color=None):
        """Show a message inside the window (red for errors, green otherwise)."""
        self.message_label.config(text=text, fg=color or (COLOR_ERROR if error else COLOR_OK))


def main():
    root = tk.Tk()
    WeatherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()