
import os
import csv
import math
import json
import shutil
import hashlib
import threading
import queue
import subprocess
import sys
import ctypes
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import numpy as np
import cv2
import imagehash
from PIL import Image, ImageOps, ImageTk, ImageDraw, ImageGrab, ExifTags
import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")
# Les maquettes sont dessinées sur une base fixe de 1664 × 928. Neutraliser
# le zoom automatique de Windows garde les mêmes proportions sur un écran à
# 125 % ou 150 % et évite le mélange de tailles entre Canvas Tk et widgets CTk.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
ctk.deactivate_automatic_dpi_awareness()
ctk.set_window_scaling(1.0)
ctk.set_widget_scaling(1.0)

C = {
    "bg": "#F4F7FB",
    "panel": "#FFFFFF",
    "panel2": "#F7F9FC",
    "line": "#D7E0EA",
    "text": "#172033",
    "muted": "#66758A",
    "blue": "#3B82F6",
    "blue2": "#2563EB",
    "green": "#16A34A",
    "green_hover": "#15803D",
    "red": "#E11D48",
    "red_hover": "#BE123C",
    "amber": "#D97706",
    "amber_hover": "#B45309",
    "soft": "#E9EEF6",
    "soft_hover": "#DCE5F1",
}

SETTINGS_DEFAULT = {
    "sensitivity": "Équilibré",
    "exact_threshold": 80,
    "auto_save": True,
    "resume_session": False,
    "ask_save_at_end": True,
    "open_results_after_export": True,
    "default_output_dir": "",
    "show_metadata": True,
    "show_folder_progress": True,
    "show_composition_grid": False,
    "max_photo_width": True,
    "ui_scale": "Automatique",
    "preview_quality": "Haute",
    "preload_pairs": True,
    "gpu": True,
    "formats": {
        "JPG": True, "PNG": True, "HEIC": True,
        "TIFF": True, "WEBP": True
    }
}


def get_desktop_folder():
    candidates = []
    one_drive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    user_profile = os.environ.get("USERPROFILE")
    if one_drive:
        candidates.extend([Path(one_drive) / "Desktop", Path(one_drive) / "Bureau"])
    if user_profile:
        candidates.extend([Path(user_profile) / "Desktop", Path(user_profile) / "Bureau"])
    candidates.extend([Path.home() / "Desktop", Path.home() / "Bureau"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    fallback = Path.home() / "Desktop"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

def deep_merge(base, update):
    result = json.loads(json.dumps(base))
    for key, value in (update or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            data = stream.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()

def exif_datetime(image):
    try:
        exif = image.getexif()
        tags = {v: k for k, v in ExifTags.TAGS.items()}
        for name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            key = tags.get(name)
            if key and key in exif:
                try:
                    return datetime.strptime(str(exif[key]), "%Y:%m:%d %H:%M:%S")
                except Exception:
                    pass
    except Exception:
        pass
    return None

def image_metrics(path):
    with Image.open(path) as image:
        dt = exif_datetime(image)
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        preview = image.copy()
        preview.thumbnail((1600, 1600))
        arr = np.asarray(preview)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        contrast = float(gray.std())
        black = float((gray < 8).mean())
        white = float((gray > 247).mean())

        exposure = max(0.0, 1.0 - abs(brightness - 128) / 128)
        dynamic = min(1.0, contrast / 64)
        clipping = max(0.0, 1.0 - min(1.0, (black + white) * 3))

        exif = image.getexif()
        iso = exif.get(34855, "—") if exif else "—"
        fnumber = exif.get(33437, "—") if exif else "—"
        exposure_time = exif.get(33434, "—") if exif else "—"

        return {
            "path": str(path),
            "width": width,
            "height": height,
            "pixels": width * height,
            "sharpness": sharpness,
            "brightness": brightness,
            "contrast": contrast,
            "exposure_score": exposure,
            "dynamic_score": dynamic,
            "clipping_score": clipping,
            "phash": str(imagehash.phash(image, hash_size=8)),
            "dhash": str(imagehash.dhash(image, hash_size=8)),
            "whash": str(imagehash.whash(image, hash_size=8)),
            "datetime": dt.isoformat() if dt else None,
            "iso": str(iso),
            "fnumber": str(fnumber),
            "exposure_time": str(exposure_time),
        }

def quality_score(m):
    resolution = min(1.0, math.log10(max(m["pixels"], 1)) / 8.0)
    sharpness = min(1.0, math.log1p(max(m["sharpness"], 0.0)) / 8.0)
    return (
        0.43 * sharpness
        + 0.20 * m["exposure_score"]
        + 0.14 * m["dynamic_score"]
        + 0.13 * m["clipping_score"]
        + 0.10 * resolution
    )

def hamming_hex(a, b):
    return (int(a, 16) ^ int(b, 16)).bit_count()


def _record_aspect_ratio(record):
    width = max(1, int(record.get("width", 0) or 0))
    height = max(1, int(record.get("height", 0) or 0))
    return width / height


def _same_capture_time(a, b, time_window):
    if not a.get("datetime") or not b.get("datetime"):
        return True
    try:
        da = datetime.fromisoformat(a["datetime"])
        db = datetime.fromisoformat(b["datetime"])
        return abs((da - db).total_seconds()) <= time_window
    except Exception:
        return True


def natural_path_key(path):
    """Trie les chemins comme l'Explorateur : photo2 avant photo10."""
    import re
    text = str(path).replace("\\", "/").casefold()
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text))


def fit_image_size(source_size, available_size):
    """Retourne une taille contenue dans la zone, sans recadrage ni déformation."""
    source_w, source_h = source_size
    available_w, available_h = available_size
    if source_w <= 0 or source_h <= 0:
        raise ValueError("Dimensions d'image invalides.")
    available_w = max(1, int(available_w))
    available_h = max(1, int(available_h))
    scale = min(available_w / source_w, available_h / source_h)
    return (
        max(1, min(available_w, int(round(source_w * scale)))),
        max(1, min(available_h, int(round(source_h * scale)))),
    )


def records_are_similar(a, b, threshold, time_window):
    """Détecte les doublons et prises quasi identiques sans dépendre du dossier.

    Une ressemblance visuelle très forte reste valable même si les dates EXIF ont
    changé lors d'une copie ou d'un export. Pour les ressemblances moins nettes,
    la proximité temporelle et la géométrie renforcent la décision.
    """
    if not a or not b:
        return False

    try:
        phash_distance = hamming_hex(a["phash"], b["phash"])
        dhash_distance = hamming_hex(a["dhash"], b["dhash"])
        whash_distance = hamming_hex(a.get("whash", a["phash"]), b.get("whash", b["phash"]))
    except Exception:
        return False

    pixels_a = max(1, int(a.get("pixels", 0) or 0))
    pixels_b = max(1, int(b.get("pixels", 0) or 0))
    resolution_ratio = min(pixels_a, pixels_b) / max(pixels_a, pixels_b)

    aspect_a = _record_aspect_ratio(a)
    aspect_b = _record_aspect_ratio(b)
    aspect_ratio = min(aspect_a, aspect_b) / max(aspect_a, aspect_b)
    close_time = _same_capture_time(a, b, time_window)

    # Copies exactes ou réencodées : les dates et la résolution peuvent différer.
    very_strong = (
        phash_distance <= 3
        and dhash_distance <= 5
        and whash_distance <= 5
        and aspect_ratio >= 0.82
    )

    # Même prise ou rafale proche. Les trois signatures doivent être cohérentes.
    normal_match = (
        phash_distance <= threshold
        and dhash_distance <= threshold + 3
        and whash_distance <= threshold + 3
        and aspect_ratio >= 0.78
        and resolution_ratio >= 0.28
        and (close_time or (phash_distance <= max(4, threshold - 2) and whash_distance <= threshold + 1))
    )
    return very_strong or normal_match


def find_similar_pairs(records, threshold, time_window, progress=None, cancel_check=None):
    """Retourne toutes les paires similaires sans saut silencieux.

    Jusqu'à 6 000 photos, toutes les paires sont réellement vérifiées. Au-delà,
    un index multi-blocs complet pour la distance de Hamming réduit le travail
    tout en garantissant qu'une paire située sous le seuil pHash est candidate.
    """
    count = len(records)
    matches = set()
    if count < 2:
        return matches

    if count <= 6000:
        for i in range(count - 1):
            if cancel_check is not None:
                cancel_check()
            left = records[i]
            for j in range(i + 1, count):
                if cancel_check is not None and (j % 120 == 0):
                    cancel_check()
                if records_are_similar(left, records[j], threshold, time_window):
                    matches.add((i, j))
            if progress is not None:
                progress.update_progress(value=i + 1)
        return matches

    block_count = min(16, max(5, threshold + 1))
    base, remainder = divmod(64, block_count)
    blocks = []
    shift = 0
    for block_index in range(block_count):
        width = base + (1 if block_index < remainder else 0)
        mask = (1 << width) - 1
        blocks.append((shift, mask))
        shift += width

    buckets = defaultdict(list)
    for index, record in enumerate(records):
        value = int(record["phash"], 16)
        for block_index, (block_shift, mask) in enumerate(blocks):
            buckets[(block_index, (value >> block_shift) & mask)].append(index)

    bucket_values = list(buckets.values())
    for bucket_number, ids in enumerate(bucket_values, 1):
        if cancel_check is not None:
            cancel_check()
        for left_pos in range(len(ids) - 1):
            i = ids[left_pos]
            for right_pos in range(left_pos + 1, len(ids)):
                j = ids[right_pos]
                pair = (i, j) if i < j else (j, i)
                if pair in matches:
                    continue
                if records_are_similar(records[pair[0]], records[pair[1]], threshold, time_window):
                    matches.add(pair)
        if progress is not None:
            progress.update_progress(value=bucket_number)
    return matches

def copy_unique(source, destination):
    source = Path(source)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if not target.exists():
        shutil.copy2(source, target)
        return target
    index = 2
    while True:
        target = destination / f"{source.stem}_{index}{source.suffix}"
        if not target.exists():
            shutil.copy2(source, target)
            return target
        index += 1

def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)

def is_relative_to(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (ValueError, OSError):
        return False

def copy_result_file(source, destination_root, source_root):
    source = Path(source)
    destination_root = Path(destination_root)
    source_root = Path(source_root)
    try:
        relative = source.resolve().relative_to(source_root.resolve())
    except (ValueError, OSError):
        relative = Path(source.name)

    target = destination_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target

def open_folder(path):
    path = str(Path(path))
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass

class ProgressDialog(ctk.CTkToplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.parent = parent
        self._parent_map_binding = None
        self._parent_unmap_binding = None
        self._cancelled = threading.Event()
        self.title(title)
        self.geometry("600x258")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.configure(fg_color=C["bg"])
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=23, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 8)
        )
        self.text = ctk.StringVar(value="Préparation…")
        ctk.CTkLabel(self, textvariable=self.text, text_color=C["muted"]).grid(
            row=1, column=0, sticky="w", padx=28
        )
        self.bar = ctk.CTkProgressBar(self, height=14, progress_color=C["blue"])
        self.bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(22, 8))
        self.bar.set(0)
        self.percent = ctk.StringVar(value="0 %")
        ctk.CTkLabel(self, textvariable=self.percent, text_color=C["muted"]).grid(
            row=3, column=0, sticky="e", padx=28)
        self.cancel_hint = ctk.StringVar(value="Tu peux fermer cette fenêtre pour annuler l'analyse.")
        ctk.CTkLabel(self, textvariable=self.cancel_hint, text_color="#6D7E98", font=ctk.CTkFont(size=12)).grid(
            row=4, column=0, sticky="w", padx=28, pady=(14, 0)
        )
        ctk.CTkButton(
            self, text="Annuler", width=130, height=38,
            fg_color="#FFFFFF", hover_color="#F4F7FC", text_color=C["text"],
            border_width=1, border_color=C["line"], corner_radius=12,
            command=self.cancel
        ).grid(row=5, column=0, sticky="e", padx=28, pady=(12, 20))
        self.maximum = 1

        # Sous Windows, un grab modal maintenu pendant la réduction peut empêcher
        # la fenêtre principale de revenir depuis la barre des tâches. On libère
        # donc le grab à la réduction, puis on restaure la boîte et le grab au retour.
        self._parent_map_binding = parent.bind(
            "<Map>", self._on_parent_restored, add="+"
        )
        self._parent_unmap_binding = parent.bind(
            "<Unmap>", self._on_parent_minimized, add="+"
        )
        self.after(80, self._bring_to_front)

    def _on_parent_minimized(self, event=None):
        if event is not None and event.widget is not self.parent:
            return
        try:
            self.grab_release()
        except Exception:
            pass

    def _on_parent_restored(self, event=None):
        if event is not None and event.widget is not self.parent:
            return
        try:
            if self.parent.state() != "iconic":
                self.after(60, self._bring_to_front)
        except Exception:
            pass

    def _bring_to_front(self):
        try:
            if not self.winfo_exists() or self.parent.state() == "iconic":
                return
            if self.state() == "iconic":
                self.deiconify()
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass

    def cancel(self):
        self._cancelled.set()
        self.text.set("Annulation en cours…")
        self.cancel_hint.set("L'analyse s'arrête dès que l'étape en cours est finie.")

    def cancelled(self):
        return self._cancelled.is_set()

    def raise_if_cancelled(self):
        if self.cancelled():
            raise AnalysisCancelled("Analyse annulée.")

    def update_progress(self, text=None, value=None, maximum=None):
        # Cette méthode est appelée depuis le thread d'analyse/copie. Aucun appel
        # Tk ne doit être fait depuis ce thread : on passe par la file de l'UI.
        self.parent.call_on_ui(
            self._apply_progress, text=text, value=value, maximum=maximum
        )

    def _apply_progress(self, text=None, value=None, maximum=None):
        try:
            if not self.winfo_exists():
                return
            if text is not None:
                self.text.set(text)
            if maximum is not None:
                self.maximum = max(1, maximum)
            if value is not None:
                ratio = min(1, max(0, value / self.maximum))
                self.bar.set(ratio)
                self.percent.set(f"{round(ratio * 100)} %")
        except Exception:
            pass

    def destroy(self):
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            if self._parent_map_binding:
                self.parent.unbind("<Map>", self._parent_map_binding)
            if self._parent_unmap_binding:
                self.parent.unbind("<Unmap>", self._parent_unmap_binding)
        except Exception:
            pass
        super().destroy()

class FullImage(ctk.CTkToplevel):
    """Affiche l'image complète au-dessus de l'interface en cours."""
    def __init__(self, parent, path):
        super().__init__(parent)
        self.parent = parent
        self.title(Path(path).name)
        self.geometry("1320x900")
        self.minsize(760, 520)
        self.configure(fg_color=C["bg"])
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.photo = None
        self.source_image = None
        self._resize_job = None
        self._is_fullscreen = False
        self.transient(parent)

        self.image_label = ctk.CTkLabel(self, text="", fg_color=C["soft"])
        self.image_label.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=1, column=0, pady=(0, 18))
        self.fullscreen_button = ctk.CTkButton(
            controls, text="Quitter le plein écran", command=self._toggle_fullscreen,
            width=190,
        )
        self.fullscreen_button.pack(side="left", padx=(0, 12))
        ctk.CTkButton(controls, text="Fermer", command=self.destroy, width=140).pack(side="left")

        try:
            with Image.open(path) as image:
                self.source_image = ImageOps.exif_transpose(image).convert("RGB").copy()
            self.bind("<Configure>", self._schedule_refit, add="+")
            self.bind("<Escape>", lambda _e: self._leave_fullscreen(), add="+")
            self.bind("<F11>", lambda _e: self._toggle_fullscreen(), add="+")
            self.image_label.bind("<Double-Button-1>", lambda _e: self._toggle_fullscreen(), add="+")
            self.after(20, lambda: self._set_fullscreen(True))
            self.after(60, self._refit_image)
            self.after(70, self._bring_to_front)
        except Exception as exc:
            self.image_label.configure(text=str(exc))

    def _bring_to_front(self):
        try:
            if not self.winfo_exists():
                return
            self.lift()
            self.attributes("-topmost", True)
            self.focus_force()
            self.grab_set()
            self.after(220, lambda: self.attributes("-topmost", False) if self.winfo_exists() else None)
        except Exception:
            pass

    def _set_fullscreen(self, enabled):
        """Bascule dans le vrai plein écran Windows, sans bordure système."""
        try:
            self._is_fullscreen = bool(enabled)
            self.attributes("-fullscreen", self._is_fullscreen)
            self.fullscreen_button.configure(
                text="Quitter le plein écran" if self._is_fullscreen else "Afficher en plein écran"
            )
            self.after(80, self._refit_image)
            self.focus_force()
        except Exception:
            pass

    def _toggle_fullscreen(self):
        self._set_fullscreen(not self._is_fullscreen)

    def _leave_fullscreen(self):
        if self._is_fullscreen:
            self._set_fullscreen(False)
        else:
            self.destroy()

    def _schedule_refit(self, _event=None):
        if self.source_image is None:
            return
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(120, self._refit_image)

    def _refit_image(self):
        self._resize_job = None
        if self.source_image is None or not self.winfo_exists():
            return
        available_w = max(1, self.image_label.winfo_width() - 8)
        available_h = max(1, self.image_label.winfo_height() - 8)
        image = self.source_image.copy()
        image = image.resize(
            fit_image_size(image.size, (available_w, available_h)),
            Image.Resampling.LANCZOS,
        )
        self.photo = ImageTk.PhotoImage(image)
        self.image_label.configure(image=self.photo, text="")

    def destroy(self):
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

class TriPhotosApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Tri de photos — Deux par deux")
        self.geometry("1664x928")
        self.minsize(1000, 620)
        self.configure(fg_color=C["bg"])
        self.overrideredirect(True)
        self._window_is_maximized = False
        self._window_restore_geometry = "1664x928"
        self._window_drag_origin = None
        self._window_redraw_suspended = False
        self._window_transition_job = None
        self._window_transition_cache = None
        self._window_transition_cache_job = self.after(120, self._prepare_window_transition_cache)
        self._initial_geometry_job = self.after(20, self._apply_model_window_geometry)
        self.after(60, self._apply_rounded_window_corners)

        self.desktop_dir = get_desktop_folder()
        self.config_dir = self.desktop_dir / "TriPhotos - Travail en cours"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.config_dir / "settings.json"
        self.last_session_path = self.config_dir / "last_session.json"

        old_dir = Path.home() / ".triphotos_v3"
        if old_dir.exists():
            for filename in ("working_session.json", "last_session.json", "settings.json"):
                source = old_dir / filename
                target = self.config_dir / filename
                if source.exists() and not target.exists():
                    try:
                        shutil.copy2(source, target)
                    except Exception:
                        pass

        try:
            saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        self.settings = deep_merge(SETTINGS_DEFAULT, saved)
        self.ui_scale = 1.0
        self._responsive_resize_job = None

        self.session = None
        self.session_path = None
        self.source_dir = None
        self.history = []
        self.decision_in_progress = False
        self.left_photo = None
        self.right_photo = None
        self._photo_resize_job = None
        self.current_page = "home"
        self.closing = False
        self.export_in_progress = False
        self.close_after_export = False
        self.window_is_minimized = False
        self.ui_queue = queue.Queue()

        try:
            icon_path = Path(__file__).with_name("triphotos_icon.png")
            icon = Image.open(icon_path)
            self.window_icon = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self.window_icon)
            header_icon_path = Path(__file__).with_name("triphotos_header_icon.png")
            header_icon = Image.open(header_icon_path) if header_icon_path.exists() else icon
            self.icon_image = ctk.CTkImage(light_image=header_icon, dark_image=header_icon, size=(94, 94))

            bg = Image.open(Path(__file__).with_name("header_bg.png")).convert("RGBA")
            self.header_bg_pil = bg
            self.header_bg_image = None

            def ui_icon(filename, size=(24, 24)):
                asset = Image.open(Path(__file__).with_name(filename)).convert("RGBA")
                return ctk.CTkImage(light_image=asset, dark_image=asset, size=size)

            self.nav_home_icon = ui_icon("home.png")
            self.nav_save_icon = ui_icon("save.png")
            self.nav_settings_icon = ui_icon("settings.png")
            self.folder_icon = ui_icon("folder.png", (22, 22))
            shield_asset = Image.open(Path(__file__).with_name("shield.png")).convert("RGBA")
            shield_tint = Image.new("RGBA", shield_asset.size, "#2A9B4A")
            shield_tint.putalpha(shield_asset.getchannel("A"))
            self.shield_icon = ctk.CTkImage(light_image=shield_tint, dark_image=shield_tint, size=(28, 28))
            self.info_icon = ui_icon("info.png", (25, 25))
            from PIL import ImageDraw
            clock_asset = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            clock_draw = ImageDraw.Draw(clock_asset)
            clock_draw.ellipse((7, 7, 57, 57), outline="#1768F2", width=4)
            clock_draw.line((32, 17, 32, 33, 43, 41), fill="#1768F2", width=4, joint="curve")
            self.history_icon = ctk.CTkImage(light_image=clock_asset, dark_image=clock_asset, size=(30, 30))
            self.action_icon_left = ui_icon("left.png", (48, 48))
            self.action_icon_right = ui_icon("right.png", (48, 48))
            self.action_icon_both = ui_icon("both.png", (48, 48))
            self.action_icon_trash = ui_icon("trash.png", (48, 48))
            undo_asset = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            undo_draw = ImageDraw.Draw(undo_asset)
            undo_draw.arc((18, 18, 80, 80), start=205, end=535, fill="#13213D", width=7)
            undo_draw.polygon(((13, 43), (17, 18), (39, 31)), fill="#13213D")
            self.action_icon_undo = ctk.CTkImage(light_image=undo_asset, dark_image=undo_asset, size=(48, 48))
            decor = Image.open(Path(__file__).with_name("info_decor.png")).convert("RGBA")
            self.info_decor_image = ctk.CTkImage(light_image=decor, dark_image=decor, size=(138, 99))
            home_decor = Image.open(Path(__file__).with_name("home_decor.png")).convert("RGBA")
            self.home_decor_pil = home_decor
            self.home_decor_image = ctk.CTkImage(light_image=home_decor, dark_image=home_decor, size=(1900, 760))
        except Exception:
            self.icon_image = None
            self.header_bg_image = None
            self.header_bg_pil = None
            self.nav_home_icon = self.nav_save_icon = self.nav_settings_icon = None
            self.folder_icon = self.shield_icon = self.info_icon = self.history_icon = None
            self.action_icon_left = self.action_icon_right = self.action_icon_both = None
            self.action_icon_trash = self.action_icon_undo = None
            self.info_decor_image = None
            self.home_decor_image = None
            self.home_decor_pil = None

        self.header_variant = "home"
        self.grid_rowconfigure(0, minsize=178)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.build_header()
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew")
        self.body.grid_propagate(False)
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        self.build_footer()
        self.build_resize_grip()

        self.bind_all("<Left>", self._shortcut_left)
        self.bind_all("<Right>", self._shortcut_right)
        self.bind_all("<Up>", self._shortcut_both)
        self.bind_all("<Delete>", self._shortcut_delete)
        self.bind_all("<Control-z>", self._shortcut_undo)
        self.bind("<Map>", self._on_window_map, add="+")
        self.bind("<Map>", self._restore_borderless_window, add="+")
        self.bind("<Unmap>", self._on_window_unmap, add="+")
        self.bind("<Configure>", self._schedule_responsive_layout, add="+")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.show_home()
        self.after(40, self._drain_ui_queue)

    def _apply_model_window_geometry(self):
        """Conserve l'allure du modèle sans zoom ni étirement.

        La fenêtre garde le ratio de la maquette 1664×928 et se centre
        dans l'écran. Sur un écran plus petit, elle se réduit proprement
        au lieu d'être zoomée.
        """
        self._initial_geometry_job = None
        if self._window_is_maximized or self._window_redraw_suspended:
            return
        try:
            base_w, base_h = 1664, 928
            screen_w = max(1, self.winfo_screenwidth())
            screen_h = max(1, self.winfo_screenheight())
            max_w = max(1000, screen_w - 48)
            max_h = max(620, screen_h - 48)
            scale = min(max_w / base_w, max_h / base_h, 1.0)
            width = max(1000, int(round(base_w * scale)))
            height = max(620, int(round(base_h * scale)))
            width = min(width, screen_w)
            height = min(height, screen_h - 1 if screen_h > 1 else screen_h)
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self._window_restore_geometry = self.geometry()
            self.update_idletasks()
        except Exception:
            pass

    def _set_header_variant(self, variant):
        """Adapte le bandeau aux deux maquettes sans recréer la fenêtre."""
        self.header_variant = variant
        base_height = 178 if variant == "home" else 146
        height = max(1, int(round(base_height * self.ui_scale)))
        self.grid_rowconfigure(0, minsize=height)
        self.header_canvas.configure(height=height)
        self._render_header_canvas()

    def _compute_responsive_scale(self, width=None, height=None):
        """Calcule une échelle qui conserve intégralement le modèle 1664 × 928."""
        width = max(1, int(width or self.winfo_width()))
        height = max(1, int(height or self.winfo_height()))
        fit_scale = min(width / 1664, height / 928)
        choice = self.settings.get("ui_scale", "Automatique")
        caps = {
            "75 %": 0.75,
            "90 %": 0.90,
            "100 %": 1.00,
            "110 %": 1.10,
            "125 %": 1.25,
            "150 %": 1.50,
        }
        scale = fit_scale if choice == "Automatique" else min(fit_scale, caps.get(choice, 1.0))
        return max(0.58, min(2.40, scale))

    def _schedule_responsive_layout(self, event=None, force=False):
        if event is not None and event.widget is not self:
            return
        if self._window_redraw_suspended and not force:
            return
        # Pendant le glissement de la poignée, la géométrie suit directement la
        # souris mais l'échelle CTk reste stable. Elle n'est recalculée qu'au
        # relâchement, ce qui évite les images intermédiaires superposées.
        if self._window_resize_origin is not None and not force:
            return
        if self._responsive_resize_job is not None:
            try:
                self.after_cancel(self._responsive_resize_job)
            except Exception:
                pass
        delay = 20 if force else 120
        self._responsive_resize_job = self.after(delay, lambda: self._apply_responsive_layout(force=force))

    def _apply_responsive_layout(self, force=False, target_size=None):
        self._responsive_resize_job = None
        if self.state() == "iconic":
            return
        if target_size is None:
            new_scale = self._compute_responsive_scale()
        else:
            new_scale = self._compute_responsive_scale(*target_size)
        scale_changed = abs(new_scale - self.ui_scale) >= 0.008
        if not scale_changed:
            self._set_header_variant(getattr(self, "header_variant", "home"))
            if self.current_page == "home":
                self._schedule_home_background()
            elif self.current_page == "review":
                self._schedule_review_geometry()
                self._schedule_photo_refit()
            return
        self.ui_scale = new_scale
        ctk.set_widget_scaling(new_scale)
        self._set_header_variant(getattr(self, "header_variant", "home"))
        if hasattr(self, "status_canvas") and self.status_canvas.winfo_exists():
            status_height = max(1, int(round(60 * new_scale)))
            self.status_canvas.configure(height=status_height)
            self.status_canvas.place_configure(height=status_height)
            self._draw_header_status()
        if self.current_page == "review":
            self._schedule_photo_refit()

    def _apply_rounded_window_corners(self):
        """Demande les coins Windows 11 arrondis visibles dans les modèles."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)
            preference = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(preference), ctypes.sizeof(preference)
            )
        except Exception:
            pass

    def _start_window_drag(self, event):
        current = self.header_canvas.find_withtag("current")
        tags = self.header_canvas.gettags(current[0]) if current else ()
        if any(tag.startswith(("nav_", "window_", "header_action_")) for tag in tags):
            return
        if self._window_is_maximized:
            return
        self._window_drag_origin = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def _drag_window(self, event):
        if not self._window_drag_origin:
            return
        start_x, start_y, win_x, win_y = self._window_drag_origin
        self.geometry(f"+{win_x + event.x_root - start_x}+{win_y + event.y_root - start_y}")

    def _stop_window_drag(self, _event=None):
        self._window_drag_origin = None

    def build_resize_grip(self):
        """Poignée permanente pour redimensionner la fenêtre sans cadre natif."""
        self._window_resize_origin = None
        self.resize_grip = tk.Canvas(
            self, width=24, height=24, bd=0, highlightthickness=0,
            bg="#F5F8FD", cursor="size_nw_se",
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se")
        for offset in (5, 10, 15):
            self.resize_grip.create_line(
                23 - offset, 23, 23, 23 - offset,
                fill="#8FA0B8", width=1,
            )
        self.resize_grip.bind("<ButtonPress-1>", self._start_window_resize)
        self.resize_grip.bind("<B1-Motion>", self._resize_window)
        self.resize_grip.bind("<ButtonRelease-1>", self._stop_window_resize)

    def _start_window_resize(self, event):
        if self._window_is_maximized:
            self._window_is_maximized = False
        self._window_resize_origin = (
            event.x_root, event.y_root,
            self.winfo_width(), self.winfo_height(),
            self.winfo_x(), self.winfo_y(),
        )

    def _resize_window(self, event):
        if not self._window_resize_origin:
            return
        start_x, start_y, start_w, start_h, win_x, win_y = self._window_resize_origin
        width = max(1000, min(self.winfo_screenwidth(), start_w + event.x_root - start_x))
        height = max(620, min(self.winfo_screenheight(), start_h + event.y_root - start_y))
        self.geometry(f"{int(width)}x{int(height)}+{win_x}+{win_y}")

    def _stop_window_resize(self, _event=None):
        self._window_resize_origin = None
        self._window_restore_geometry = self.geometry()
        self._begin_window_transition()
        self._schedule_responsive_layout(force=True)
        self._window_transition_job = self.after(240, self._finish_window_transition)

    def _raise_resize_grip(self):
        try:
            self.resize_grip.tk.call("raise", self.resize_grip._w)
        except Exception:
            pass

    def _minimize_window(self):
        # Windows ne réduit pas toujours une fenêtre override-redirect. Le bref
        # retour au cadre natif permet une restauration normale depuis la barre.
        self.overrideredirect(False)
        self.iconify()

    def _restore_borderless_window(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            if self.state() == "normal" and not self.overrideredirect():
                self.after(10, lambda: self.overrideredirect(True))
        except Exception:
            pass

    def _set_window_redraw(self, enabled):
        """Fige/reprend le dessin Windows pendant un changement d'échelle."""
        if sys.platform != "win32":
            return
        try:
            hwnd = ctypes.windll.user32.GetAncestor(self.winfo_id(), 2)
            ctypes.windll.user32.SendMessageW(hwnd, 0x000B, 1 if enabled else 0, 0)  # WM_SETREDRAW
            if enabled:
                flags = 0x0001 | 0x0080 | 0x0100 | 0x0400  # invalidate, children, update, frame
                ctypes.windll.user32.RedrawWindow(hwnd, None, None, flags)
                ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass

    def _prepare_window_transition_cache(self):
        """Prépare hors clic la copie normale et sa version plein écran."""
        self._window_transition_cache_job = None
        try:
            if (
                self._window_is_maximized
                or self._window_redraw_suspended
                or self.state() == "iconic"
                or not self.winfo_ismapped()
            ):
                if not self._window_is_maximized:
                    self._window_transition_cache_job = self.after(
                        120, self._prepare_window_transition_cache
                    )
                return
            self.update_idletasks()
            width = max(1, self.winfo_width())
            height = max(1, self.winfo_height())
            root_x = self.winfo_rootx()
            root_y = self.winfo_rooty()
            snapshot = ImageGrab.grab(
                bbox=(root_x, root_y, root_x + width, root_y + height),
                include_layered_windows=True,
            ).convert("RGB")

            target_w = max(1, self.winfo_screenwidth())
            target_h = max(1, self.winfo_screenheight())
            fitted = ImageOps.contain(
                snapshot, (target_w, target_h), Image.Resampling.BILINEAR,
            )
            preview = Image.new("RGB", (target_w, target_h), "#F4F7FB")
            preview.paste(
                fitted,
                ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2),
            )
            self._window_transition_cache = {
                "page": self.current_page,
                "size": (width, height),
                "screen_size": (target_w, target_h),
                "snapshot": snapshot,
                "normal_photo": ImageTk.PhotoImage(snapshot),
                "maximized_photo": ImageTk.PhotoImage(preview),
            }
            self._ensure_window_transition_overlay()
        except Exception as error:
            self._window_transition_cache = None
            self._window_transition_cache_error = repr(error)
            if not self._window_is_maximized:
                self._window_transition_cache_job = self.after(
                    180, self._prepare_window_transition_cache
                )

    def _ensure_window_transition_overlay(self):
        """Crée une seule fois le calque, avant que l'utilisateur clique."""
        overlay = getattr(self, "_window_transition_overlay", None)
        if overlay is None or not overlay.winfo_exists():
            overlay = tk.Canvas(
                self, bg="#EEF4FD", bd=0, highlightthickness=0,
                relief="flat",
            )
            overlay.bind("<Configure>", self._render_window_transition_overlay)
            self._window_transition_overlay = overlay
        return overlay

    def _begin_window_transition(self):
        job = getattr(self, "_window_transition_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._window_transition_job = None
        if not self._window_redraw_suspended:
            responsive_job = getattr(self, "_responsive_resize_job", None)
            if responsive_job is not None:
                try:
                    self.after_cancel(responsive_job)
                except Exception:
                    pass
                self._responsive_resize_job = None

            # Conserver visuellement la fenêtre elle-même pendant que CTk
            # recalcule toutes les tailles. La copie est redimensionnée en
            # conservant strictement son ratio : aucun écran blanc, aucune
            # ancienne fenêtre flottant au milieu du nouvel écran.
            width = max(1, self.winfo_width())
            height = max(1, self.winfo_height())
            cache = getattr(self, "_window_transition_cache", None)
            cache_is_current = bool(
                cache
                and cache.get("page") == self.current_page
                and abs(cache.get("size", (0, 0))[0] - width) <= 2
                and abs(cache.get("size", (0, 0))[1] - height) <= 2
            )
            if cache_is_current:
                self._window_transition_snapshot = cache["snapshot"]
                self._window_transition_prepared_cache = cache
                self._window_transition_photo = cache["normal_photo"]
                self._window_transition_snapshot_is_screen = False
            else:
                self._window_transition_prepared_cache = None
                try:
                    self.update_idletasks()
                    width = max(1, self.winfo_width())
                    height = max(1, self.winfo_height())
                    root_x = self.winfo_rootx()
                    root_y = self.winfo_rooty()
                    self._window_transition_snapshot = ImageGrab.grab(
                        bbox=(root_x, root_y, root_x + width, root_y + height),
                        include_layered_windows=True,
                    ).convert("RGB")
                    self._window_transition_snapshot_is_screen = False
                except Exception:
                    self._window_transition_snapshot = None
                    self._window_transition_snapshot_is_screen = False

            overlay = self._ensure_window_transition_overlay()

            overlay.configure(width=width, height=height)
            self._render_window_transition_overlay(width=width, height=height)
            overlay.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            overlay.tk.call("raise", overlay._w)
            self._window_redraw_suspended = True

    def _render_window_transition_overlay(self, event=None, width=None, height=None):
        """Conserve le ratio de la dernière vue pendant le bref recalcul."""
        overlay = getattr(self, "_window_transition_overlay", None)
        if overlay is None or not overlay.winfo_exists():
            return
        snapshot = getattr(self, "_window_transition_snapshot", None)
        if snapshot is None:
            return
        target_w = max(1, int(width or getattr(event, "width", 0) or overlay.winfo_width()))
        target_h = max(1, int(height or getattr(event, "height", 0) or overlay.winfo_height()))
        try:
            prepared = getattr(self, "_window_transition_prepared_cache", None)
            if prepared:
                if (
                    abs(target_w - prepared["screen_size"][0]) <= 3
                    and abs(target_h - prepared["screen_size"][1]) <= 3
                ):
                    self._window_transition_photo = prepared["maximized_photo"]
                    overlay.delete("transition_snapshot")
                    overlay.create_image(
                        0, 0, anchor="nw", image=self._window_transition_photo,
                        tags="transition_snapshot",
                    )
                    return
                if (
                    abs(target_w - prepared["size"][0]) <= 3
                    and abs(target_h - prepared["size"][1]) <= 3
                ):
                    self._window_transition_photo = prepared["normal_photo"]
                    overlay.delete("transition_snapshot")
                    overlay.create_image(
                        0, 0, anchor="nw", image=self._window_transition_photo,
                        tags="transition_snapshot",
                    )
                    return
            if getattr(self, "_window_transition_snapshot_is_screen", False):
                overlay.delete("transition_snapshot")
                overlay.create_image(
                    -self.winfo_rootx(), -self.winfo_rooty(), anchor="nw",
                    image=self._window_transition_photo,
                    tags="transition_snapshot",
                )
                return
            # BILINEAR est largement suffisant pour cette copie visible moins
            # d'un dixième de seconde et accélère nettement l'agrandissement.
            fitted = ImageOps.contain(
                snapshot, (target_w, target_h), Image.Resampling.BILINEAR,
            )
            preview = Image.new("RGB", (target_w, target_h), "#F4F7FB")
            preview.paste(
                fitted,
                ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2),
            )
            self._window_transition_photo = ImageTk.PhotoImage(preview)
            overlay.delete("transition_snapshot")
            overlay.create_image(
                0, 0, anchor="nw", image=self._window_transition_photo,
                tags="transition_snapshot",
            )
        except Exception:
            pass

    def _finish_window_transition(self):
        """Publie en une fois la mise en page complètement recalculée."""
        self._window_transition_job = None
        try:
            self.update_idletasks()
            if self.current_page == "home":
                self._render_home_background()
            elif self.current_page == "review":
                self._rebuild_review_actions()
                self._configure_review_geometry()
                self.update_idletasks()
                self._refit_current_photos()
            self._render_header_canvas()
            self.update_idletasks()
        finally:
            overlay = getattr(self, "_window_transition_overlay", None)
            if overlay is not None and overlay.winfo_exists():
                overlay.place_forget()
            self._window_transition_snapshot = None
            self._window_transition_photo = None
            self._window_transition_prepared_cache = None
            self._window_transition_snapshot_is_screen = False
            self._window_redraw_suspended = False
            self._raise_resize_grip()
            if self.current_page == "review":
                self.after(10, self._raise_review_actions)
                self.after(120, self._raise_review_actions)
            elif not self._window_is_maximized:
                cache_job = getattr(self, "_window_transition_cache_job", None)
                if cache_job is not None:
                    try:
                        self.after_cancel(cache_job)
                    except Exception:
                        pass
                self._window_transition_cache_job = self.after(
                    120, self._prepare_window_transition_cache
                )

    def _apply_window_transition_layout(self):
        """Attend la nouvelle géométrie Windows avant de changer l'échelle."""
        self._window_transition_job = None
        self.update_idletasks()
        self._apply_responsive_layout(force=True)
        # Deux cycles d'affichage suffisent à CTk pour achever ses Canvas. La
        # copie proportionnelle ne reste donc visible qu'un instant.
        self._window_transition_job = self.after(35, self._finish_window_transition)

    def _raise_review_actions(self):
        """Replace la rangée native au-dessus du fond de la grande carte."""
        if self.current_page != "review" or not hasattr(self, "actions_zone"):
            return
        widgets = [self.actions_zone, getattr(self, "actions_canvas", None)]
        for widget in widgets:
            if widget is None:
                continue
            try:
                widget.tk.call("raise", widget._w)
            except Exception:
                pass

    def _toggle_maximize_window(self):
        initial_job = getattr(self, "_initial_geometry_job", None)
        if initial_job is not None:
            try:
                self.after_cancel(initial_job)
            except Exception:
                pass
            self._initial_geometry_job = None
            # Si le clic arrive dès l'apparition de la fenêtre, établir tout
            # de suite sa géométrie normale de référence avant de la maximiser.
            self._apply_model_window_geometry()
        self._begin_window_transition()
        if self._window_is_maximized:
            target_geometry = self._window_restore_geometry
            self._window_is_maximized = False
            self.resize_grip.place(relx=1.0, rely=1.0, anchor="se")
        else:
            self._window_restore_geometry = self.geometry()
            target_geometry = f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0"
            self._window_is_maximized = True
            self.resize_grip.place_forget()
        size_text = target_geometry.split("+", 1)[0]
        try:
            target_w, target_h = (int(value) for value in size_text.split("x", 1))
        except (TypeError, ValueError):
            target_w, target_h = self.winfo_width(), self.winfo_height()
        self._window_transition_target_size = (target_w, target_h)

        # Le bref état natif est nécessaire sous Windows : une géométrie plein
        # écran envoyée directement à une fenêtre sans bordure peut être
        # ignorée. Toute la partie graphique étant déjà en cache, il ne reste
        # ici que le basculement système, d'environ quelques dizaines de ms.
        if sys.platform == "win32":
            self.overrideredirect(False)
            if self._window_is_maximized:
                self.attributes("-fullscreen", True)
            else:
                self.attributes("-fullscreen", False)
                self.geometry(target_geometry)
            self.after(20, lambda: self.overrideredirect(True))
        else:
            self.geometry(target_geometry)

        self._window_transition_geometry_attempt = 0
        self._window_transition_job = self.after_idle(self._wait_for_window_transition_geometry)

    def _wait_for_window_transition_geometry(self):
        """Attend que Windows confirme la taille demandée avant tout recalcul."""
        self._window_transition_job = None
        self.update_idletasks()
        target_w, target_h = getattr(
            self, "_window_transition_target_size",
            (self.winfo_width(), self.winfo_height()),
        )
        current_w, current_h = self.winfo_width(), self.winfo_height()
        attempt = int(getattr(self, "_window_transition_geometry_attempt", 0))
        if (abs(current_w - target_w) > 2 or abs(current_h - target_h) > 2) and attempt < 24:
            self._window_transition_geometry_attempt = attempt + 1
            self._window_transition_job = self.after(12, self._wait_for_window_transition_geometry)
            return
        self._apply_window_transition_layout()

    def _on_window_unmap(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            self.window_is_minimized = self.state() == "iconic"
        except Exception:
            pass

    def _on_window_map(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            self.window_is_minimized = self.state() == "iconic"
        except Exception:
            pass

    def _focus_if_visible(self):
        try:
            if self.winfo_exists() and self.state() != "iconic":
                self.focus_force()
        except Exception:
            pass

    def call_on_ui(self, callback, *args, **kwargs):
        """Programme une action Tk depuis n'importe quel thread."""
        self.ui_queue.put((callback, args, kwargs))

    def _drain_ui_queue(self):
        try:
            while True:
                callback, args, kwargs = self.ui_queue.get_nowait()
                try:
                    callback(*args, **kwargs)
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            if self.winfo_exists():
                self.after(40, self._drain_ui_queue)
        except Exception:
            pass

    def _shortcut_allowed(self):
        return self.current_page == "review" and self.session is not None

    def _shortcut_left(self, event=None):
        if self._shortcut_allowed():
            group = self.current_group()
            self.keep_unique() if group and group.get("type") == "unique" else self.keep_left()
            return "break"

    def _shortcut_right(self, event=None):
        if self._shortcut_allowed():
            group = self.current_group()
            self.reject_unique() if group and group.get("type") == "unique" else self.keep_right()
            return "break"

    def _shortcut_both(self, event=None):
        if self._shortcut_allowed():
            group = self.current_group()
            self.defer_unique() if group and group.get("type") == "unique" else self.keep_both()
            return "break"

    def _shortcut_down(self, event=None):
        if self._shortcut_allowed():
            group = self.current_group()
            self.reject_unique() if group and group.get("type") == "unique" else self.resolve_pair("reject")
            return "break"

    def _shortcut_delete(self, event=None):
        if self._shortcut_allowed():
            group = self.current_group()
            if group and group.get("type") == "unique":
                self.reject_unique()
            else:
                self.resolve_pair("reject")
            return "break"

    def _shortcut_undo(self, event=None):
        if self._shortcut_allowed():
            self.undo()
            return "break"

    def build_header(self):
        """Bandeau 100 % Canvas : aucun CTkFrame transparent au-dessus du fond.

        Cela évite les plaques grises de CustomTkinter et conserve le motif
        pastel sans zoom ni déformation.
        """
        self.grid_rowconfigure(0, minsize=178)
        self.header_canvas = tk.Canvas(
            self, height=178, highlightthickness=0, bd=0,
            bg="#EEF4FB"
        )
        self.header_canvas.grid(row=0, column=0, sticky="ew")
        self.header_canvas.bind("<Configure>", self._render_header_canvas, add="+")
        self.header_canvas.bind("<ButtonPress-1>", self._start_window_drag, add="+")
        self.header_canvas.bind("<B1-Motion>", self._drag_window, add="+")
        self.header_canvas.bind("<ButtonRelease-1>", self._stop_window_drag, add="+")

        # Images Canvas chargées depuis les assets PNG transparents.
        self._header_logo_pil = Image.open(Path(__file__).with_name("triphotos_header_icon.png")).convert("RGBA")
        self._header_home_pil = Image.open(Path(__file__).with_name("home.png")).convert("RGBA")
        self._header_save_pil = Image.open(Path(__file__).with_name("save.png")).convert("RGBA")
        self._header_settings_pil = Image.open(Path(__file__).with_name("settings.png")).convert("RGBA")
        self._header_refs = []
        self.nav_buttons = {"home": "home", "settings": "settings"}
        self._header_active_nav = "home"
        self._header_status_folder = None
        self._header_progress_ratio = 0.0
        self._header_progress_values = {
            "photos": "", "percent": "", "comparisons": "",
            "kept": "Gardées : 0", "rejected": "Mises de côté : 0"
        }

        ctk.CTkFrame(self, height=1, fg_color="#D7E2EF", corner_radius=0).grid(row=1, column=0, sticky="ew")
        self.after(20, self._render_header_canvas)

    @staticmethod
    def _canvas_round_rect(canvas, x1, y1, x2, y2, radius=18, **kwargs):
        radius = max(1, min(radius, (x2-x1)/2, (y2-y1)/2))
        points = [
            x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
            x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
            x1, y2, x1, y2-radius, x1, y1+radius, x1, y1
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _header_photo(self, pil_image, size):
        image = pil_image.resize(size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self._header_refs.append(photo)
        return photo

    def _render_header_canvas(self, _event=None):
        canvas = getattr(self, "header_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        w = max(2, canvas.winfo_width())
        variant = getattr(self, "header_variant", "home")
        scale = max(0.01, float(getattr(self, "ui_scale", 1.0)))
        base_h = 178 if variant == "home" else 146
        h = max(1, int(round(base_h * scale)))
        design_width = 1664 * scale
        origin_x = max(0.0, (w - design_width) / 2)

        def sx(value):
            return origin_x + value * scale

        def sy(value):
            return value * scale

        def font_size(value):
            return -max(1, int(round(value * scale)))

        def line_width(value=1):
            return max(1, int(round(value * scale)))

        def round_rect(x1, y1, x2, y2, radius, **kwargs):
            return self._canvas_round_rect(
                canvas, sx(x1), sy(y1), sx(x2), sy(y2),
                max(1, radius * scale), **kwargs,
            )

        canvas.delete("all")
        self._header_refs = []

        # Le fond remplit la fenêtre ; les éléments restent centrés dans une
        # surface au ratio exact du modèle.
        base = getattr(self, "header_bg_pil", None)
        if base is not None:
            fitted = ImageOps.fit(base, (w, h), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            bg_photo = ImageTk.PhotoImage(fitted)
            self._header_refs.append(bg_photo)
            canvas.create_image(0, 0, image=bg_photo, anchor="nw")
        else:
            canvas.create_rectangle(0, 0, w, h, fill="#EEF4FB", outline="")

        # --- Marque et navigation : deux géométries distinctes dans les modèles. ---
        if variant == "home":
            # Même bord gauche que le contenu principal (x=183) : le logo est
            # maintenant exactement aligné avec « Trier vos photos ».
            shell_x1, shell_y1, shell_x2, shell_y2 = 183, 36, 303, 154
            logo_size = (108, 108)
            logo_center = (243, 95)
            brand_x, brand_y, brand_size = 328, 82, 45
            subtitle_x, subtitle_y, subtitle_size = 329, 123, 18
            # Le bord droit du menu reprend celui de la tuile « Dossier à
            # analyser » (x=1481), pour une grille parfaitement cohérente.
            nav_x1, nav_y1, nav_x2, nav_y2 = 779, 80, 1481, 144
            nav_font = 16
        else:
            # Bord gauche commun au grand panneau de comparaison (x=24).
            shell_x1, shell_y1, shell_x2, shell_y2 = 24, 26, 119, 123
            logo_size = (84, 84)
            logo_center = (71, 74)
            brand_x, brand_y, brand_size = 135, 60, 32
            subtitle_x, subtitle_y, subtitle_size = 135, 94, 14
            # Identité, navigation et statistiques se répartissent le bandeau
            # avec des respirations régulières.
            nav_x1, nav_y1, nav_x2, nav_y2 = 410, 50, 990, 108
            nav_font = 14

        # Ombres discrètes visibles sur les deux maquettes.
        round_rect(shell_x1 + 2, shell_y1 + 5, shell_x2 + 2, shell_y2 + 5, 20, fill="#DCE3EE", outline="")
        round_rect(shell_x1, shell_y1, shell_x2, shell_y2, 20, fill="#FFFFFF", outline="#E2E8F2", width=line_width())
        scaled_logo_size = tuple(max(1, int(round(v * scale))) for v in logo_size)
        logo = self._header_photo(self._header_logo_pil, scaled_logo_size)
        canvas.create_image(sx(logo_center[0]), sy(logo_center[1]), image=logo, anchor="center")
        canvas.create_text(
            sx(brand_x), sy(brand_y - (7 if variant == "home" else 0)),
            text="Tri de photos", anchor="w", fill="#0D1936",
            font=("Segoe UI", font_size(brand_size - (2 if variant == "home" else 0)), "bold"),
        )
        canvas.create_text(
            sx(subtitle_x), sy(subtitle_y - (5 if variant == "home" else 0)),
            text="Deux par deux", anchor="w", fill="#5F7292",
            font=("Segoe UI", font_size(subtitle_size)),
        )

        round_rect(nav_x1 + 2, nav_y1 + 5, nav_x2 + 2, nav_y2 + 5, 18, fill="#D9E0EB", outline="")
        round_rect(nav_x1, nav_y1, nav_x2, nav_y2, 18, fill="#FFFFFF", outline="#DEE6F0", width=line_width())

        nav_width = nav_x2 - nav_x1
        if variant == "home":
            sep1, sep2 = nav_x1 + 205, nav_x1 + 505
            inner_y1, inner_y2 = nav_y1 + 8, nav_y2 - 8
            home_box = (nav_x1 + 9, inner_y1, sep1 - 8, inner_y2)
            save_box = (sep1 + 8, inner_y1, sep2 - 8, inner_y2)
            settings_box = (sep2 + 8, inner_y1, nav_x2 - 9, inner_y2)
        else:
            # Accueil / Sauvegarder / Réglages : largeurs adaptées au texte,
            # dans le panneau plus court de la page de comparaison.
            sep1, sep2 = nav_x1 + 145, nav_x1 + 400
            inner_y1, inner_y2 = nav_y1 + 7, nav_y2 - 7
            home_box = (nav_x1 + 8, inner_y1, sep1 - 8, inner_y2)
            save_box = (sep1 + 8, inner_y1, sep2 - 8, inner_y2)
            settings_box = (sep2 + 8, inner_y1, nav_x2 - 8, inner_y2)
        canvas.create_line(sx(sep1), sy(nav_y1 + 16), sx(sep1), sy(nav_y2 - 16), fill="#D7E0EA", width=line_width())
        canvas.create_line(sx(sep2), sy(nav_y1 + 16), sx(sep2), sy(nav_y2 - 16), fill="#D7E0EA", width=line_width())

        active = getattr(self, "_header_active_nav", "home")
        if active == "home":
            round_rect(*home_box, 14, fill="#EEF4FF", outline="")
        elif active == "settings":
            round_rect(*settings_box, 14, fill="#EEF4FF", outline="")

        icon_size = (25, 25) if variant == "home" else (22, 22)
        scaled_icon_size = tuple(max(1, int(round(v * scale))) for v in icon_size)
        home_icon = self._header_photo(self._header_home_pil, scaled_icon_size)
        save_icon = self._header_photo(self._header_save_pil, scaled_icon_size)
        settings_icon = self._header_photo(self._header_settings_pil, scaled_icon_size)
        nav_center_y = (nav_y1 + nav_y2) / 2

        def draw_centered_nav_group(box, icon, label, color, font):
            """Centre réellement le couple icône + texte dans son segment."""
            text_id = canvas.create_text(
                0, sy(nav_center_y), text=label, anchor="w",
                fill=color, font=font,
            )
            bbox = canvas.bbox(text_id)
            text_width = max(1, bbox[2] - bbox[0]) if bbox else 1
            icon_width = scaled_icon_size[0]
            gap = max(5, int(round(10 * scale)))
            group_width = icon_width + gap + text_width
            segment_center = sx((box[0] + box[2]) / 2)
            start_x = segment_center - group_width / 2
            canvas.create_image(start_x + icon_width / 2, sy(nav_center_y), image=icon, anchor="center")
            canvas.coords(text_id, start_x + icon_width + gap, sy(nav_center_y))

        draw_centered_nav_group(
            home_box, home_icon, "Accueil",
            "#2563EB" if active == "home" else "#172033",
            ("Segoe UI", font_size(nav_font), "bold"),
        )
        draw_centered_nav_group(
            save_box, save_icon, "Sauvegarder et fermer", "#172033",
            ("Segoe UI", font_size(nav_font - 1)),
        )
        draw_centered_nav_group(
            settings_box, settings_icon, "Réglages",
            "#2563EB" if active == "settings" else "#172033",
            ("Segoe UI", font_size(nav_font - 1)),
        )

        # Zones cliquables invisibles (tags)
        canvas.create_rectangle(sx(home_box[0]), sy(home_box[1]), sx(home_box[2]), sy(home_box[3]), fill="", outline="", tags=("nav_home",))
        canvas.create_rectangle(sx(save_box[0]), sy(save_box[1]), sx(save_box[2]), sy(save_box[3]), fill="", outline="", tags=("nav_save",))
        canvas.create_rectangle(sx(settings_box[0]), sy(settings_box[1]), sx(settings_box[2]), sy(settings_box[3]), fill="", outline="", tags=("nav_settings",))
        canvas.tag_bind("nav_home", "<Button-1>", lambda _e: self.navigate("home"))
        canvas.tag_bind("nav_save", "<Button-1>", lambda _e: self.on_close())
        canvas.tag_bind("nav_settings", "<Button-1>", lambda _e: self.navigate("settings"))

        # Sur la page de tri, toute la progression tient directement dans le
        # bandeau. Cela remplace la bande blanche de 60 px qui séparait le
        # bandeau des photos.
        if variant == "review" and getattr(self, "_header_status_folder", None):
            vals = getattr(self, "_header_progress_values", {})
            stat_font = ("Segoe UI", font_size(14))
            stat_bold = ("Segoe UI", font_size(14), "bold")
            photos_text = vals.get("photos", "")
            comparisons_text = vals.get("comparisons", "")
            kept_text = vals.get("kept", "")
            rejected_text = vals.get("rejected", "").replace("Mises de côté :", "Écartées :")
            # Deux lignes aérées dans la même tuile : les informations ne se
            # chevauchent plus, même avec une police plus grande.
            round_rect(1007, 54, 1642, 112, 16, fill="#D9E0EB", outline="")
            round_rect(1005, 50, 1640, 108, 16, fill="#FFFFFF", outline="#DEE6F0", width=line_width())
            top_y, bottom_y = 68, 92
            canvas.create_text(sx(1019), sy(top_y), text=photos_text, anchor="w", fill="#52617C", font=stat_font)
            # Le début de la barre partage l'axe de « Gardées » ; son extrémité
            # et le pourcentage rejoignent l'axe droit du zéro d'« Écartées ».
            progress_x1, progress_x2 = 1230, 1550
            round_rect(progress_x1, top_y - 4, progress_x2, top_y + 4, 4, fill="#B9C4D6", outline="")
            ratio = max(0.0, min(1.0, float(getattr(self, "_header_progress_ratio", 0.0))))
            if ratio > 0:
                round_rect(progress_x1, top_y - 4, progress_x1 + (progress_x2 - progress_x1) * ratio, top_y + 4, 4, fill="#2E6EF7", outline="")
            canvas.create_text(sx(1620), sy(top_y), text=vals.get("percent", ""), anchor="e", fill="#2563EB", font=stat_bold)
            canvas.create_text(sx(1019), sy(bottom_y), text=comparisons_text, anchor="w", fill="#52617C", font=stat_font)
            kept_id = canvas.create_text(sx(1230), sy(bottom_y), text=kept_text, anchor="w", fill="#52617C", font=stat_font)
            rejected_id = canvas.create_text(sx(1620), sy(bottom_y), text=rejected_text, anchor="e", fill="#52617C", font=stat_font)
            # Le séparateur se place d'après la largeur réellement rendue des
            # deux libellés. Il reste donc exactement à mi-distance entre le
            # zéro de « Gardées » et le début d'« Écartées », à toute échelle.
            kept_bbox = canvas.bbox(kept_id)
            rejected_bbox = canvas.bbox(rejected_id)
            if kept_bbox and rejected_bbox:
                separator_x = (kept_bbox[2] + rejected_bbox[0]) / 2
            else:
                separator_x = sx(1460)
            canvas.create_line(separator_x, sy(82), separator_x, sy(102), fill="#CDD7E4", width=line_width())

        # Contrôles de fenêtre intégrés au fond, comme sur les maquettes.
        if variant == "home":
            control_centers = (w - 136 * scale, w - 83 * scale, w - 29 * scale)
        else:
            control_centers = (w - 122 * scale, w - 72 * scale, w - 23 * scale)
        controls = (
            ("window_minimize", control_centers[0], self._minimize_window),
            ("window_maximize", control_centers[1], self._toggle_maximize_window),
            ("window_close", control_centers[2], self.on_close),
        )
        for tag, center_x, command in controls:
            canvas.create_rectangle(center_x - 20 * scale, sy(5), center_x + 20 * scale, sy(51), fill="", outline="", tags=(tag,))
            if tag == "window_minimize":
                canvas.create_line(center_x - 6 * scale, sy(29), center_x + 6 * scale, sy(29), fill="#20252D", width=line_width(), tags=(tag,))
            elif tag == "window_maximize":
                if self._window_is_maximized:
                    # Symbole Windows « Restaurer » : deux fenêtres
                    # superposées remplacent le carré de maximisation.
                    canvas.create_rectangle(
                        center_x - 3 * scale, sy(21), center_x + 6 * scale, sy(30),
                        outline="#20252D", width=line_width(), tags=(tag,),
                    )
                    canvas.create_rectangle(
                        center_x - 6 * scale, sy(24), center_x + 3 * scale, sy(33),
                        fill="#F7F9FE", outline="#20252D", width=line_width(), tags=(tag,),
                    )
                else:
                    canvas.create_rectangle(center_x - 5 * scale, sy(23), center_x + 5 * scale, sy(33), outline="#20252D", width=line_width(), tags=(tag,))
            else:
                canvas.create_line(center_x - 5 * scale, sy(23), center_x + 5 * scale, sy(33), fill="#20252D", width=line_width(), tags=(tag,))
                canvas.create_line(center_x + 5 * scale, sy(23), center_x - 5 * scale, sy(33), fill="#20252D", width=line_width(), tags=(tag,))
            canvas.tag_bind(tag, "<Button-1>", lambda _e, cmd=command: cmd())

    def _draw_header_status(self):
        canvas = getattr(self, "status_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        folder = getattr(self, "_header_status_folder", None)
        if not folder:
            return
        w = max(2, canvas.winfo_width())
        scale = max(0.01, float(getattr(self, "ui_scale", 1.0)))
        height = max(1, int(round(60 * scale)))
        origin_x = max(0.0, (w - 1664 * scale) / 2)

        def sx(value):
            return origin_x + value * scale

        def sy(value):
            return value * scale

        def font_size(value):
            return -max(1, int(round(value * scale)))

        def line_width(value=1):
            return max(1, int(round(value * scale)))

        vals = getattr(self, "_header_progress_values", {})
        canvas.create_rectangle(0, 0, w, height, fill="#FBFCFF", outline="")
        canvas.create_line(0, height - 1, w, height - 1, fill="#E2E8F2", width=line_width())
        y = sy(31)
        canvas.create_text(sx(108), y, text=vals.get("photos", ""), anchor="w", fill="#53617C", font=("Segoe UI", font_size(14)), tags="header_status")
        bar_x1 = sx(279)
        bar_x2 = sx(659)
        canvas.create_line(bar_x1, y, bar_x2, y, fill="#AEB8C8", width=line_width(11), capstyle="round", tags="header_status")
        ratio=max(0.0,min(1.0,getattr(self,"_header_progress_ratio",0.0)))
        blue_end = bar_x1 + max(scale, (bar_x2 - bar_x1) * ratio)
        canvas.create_line(bar_x1, y, blue_end, y, fill="#2563EB", width=line_width(11), capstyle="round", tags="header_status")
        canvas.create_text(sx(677), y, text=vals.get("percent", ""), anchor="w", fill="#2563EB", font=("Segoe UI", font_size(14), "bold"), tags="header_status")
        canvas.create_text(sx(846), y, text=vals.get("comparisons", ""), anchor="w", fill="#53617C", font=("Segoe UI", font_size(14)), tags="header_status")
        canvas.create_text(sx(1300), y, text=vals.get("kept", ""), anchor="w", fill="#53617C", font=("Segoe UI", font_size(14)), tags="header_status")
        canvas.create_line(sx(1421), sy(21), sx(1421), sy(41), fill="#D7E0EA", width=line_width(), tags="header_status")
        canvas.create_text(sx(1461), y, text=vals.get("rejected", ""), anchor="w", fill="#53617C", font=("Segoe UI", font_size(14)), tags="header_status")

    def build_footer(self):
        # Pas de bandeau permanent : l'espace est réservé aux photos.
        self.footer_stats = ctk.StringVar(value="")

    def render_header_status(self, folder_text=None):
        self._header_status_folder = folder_text
        self._draw_header_status()
        self._render_header_canvas()

    def set_active_nav(self, key):
        self._header_active_nav = key
        self.current_page = key
        self._render_header_canvas()

    def clear_body(self):
        actions_zone = getattr(self, "actions_zone", None)
        if actions_zone is not None and actions_zone.winfo_exists() and actions_zone.master is self:
            actions_zone.destroy()
        for child in self.body.winfo_children():
            child.destroy()
        if hasattr(self, "resize_grip"):
            self.after(0, self._raise_resize_grip)

    def navigate(self, key):
        if key == "home":
            self.show_home()
        elif key == "settings":
            self.show_settings()

    def _schedule_home_background(self, _event=None):
        job = getattr(self, "_home_background_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._home_background_job = self.after(90, self._render_home_background)

    def _render_home_background(self):
        self._home_background_job = None
        canvas = getattr(self, "_home_background_label", None)
        if canvas is None or not canvas.winfo_exists():
            return
        width = max(2, canvas.winfo_width())
        height = max(2, canvas.winfo_height())

        # Dégradé opaque sur toute la largeur réelle de la fenêtre : aucune
        # marge latérale ne peut réapparaître sur un écran ultralarge.
        top = np.array([249.0, 250.0, 255.0])
        bottom = np.array([246.0, 246.0, 254.0])
        vertical = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
        rgb = top[None, None, :] * (1.0 - vertical) + bottom[None, None, :] * vertical
        rgb = np.broadcast_to(rgb, (height, width, 3)).copy()
        x_axis = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
        y_axis = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
        pink_glow = np.exp(-(((x_axis - 0.62) / 0.25) ** 2 + ((y_axis - 0.05) / 0.34) ** 2))
        rgb += pink_glow[:, :, None] * np.array([4.0, -2.0, -2.0])[None, None, :]
        # Les deux coins inférieurs du modèle sont bleutés, tandis que son
        # centre reste presque blanc. Ces halos évitent la teinte grise qui
        # apparaissait auparavant dans toute la moitié basse.
        left_blue = np.exp(-(((x_axis + 0.03) / 0.27) ** 2 + ((y_axis - 1.05) / 0.30) ** 2))
        right_blue = np.exp(-(((x_axis - 1.03) / 0.29) ** 2 + ((y_axis - 1.05) / 0.30) ** 2))
        rgb += left_blue[:, :, None] * np.array([-30.0, -18.0, 0.0])[None, None, :]
        rgb += right_blue[:, :, None] * np.array([-35.0, -22.0, 0.0])[None, None, :]
        background = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

        decor = getattr(self, "home_decor_pil", None)
        if decor is not None:
            stretched = decor.resize((width, height), Image.Resampling.LANCZOS)
            alpha = np.asarray(stretched.getchannel("A"), dtype=np.float32)
            decor_rgb = np.asarray(stretched.convert("RGB"), dtype=np.float32)
            luminance = (
                decor_rgb[:, :, 0] * 0.2126
                + decor_rgb[:, :, 1] * 0.7152
                + decor_rgb[:, :, 2] * 0.0722
            )
            y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
            # Les zones pastel et les courbes claires reprennent leur intensité
            # du modèle, tandis que les pixels très sombres des ombres restent
            # discrets. On retrouve ainsi les formes sans voile gris général.
            bright_detail = np.clip((luminance - 75.0) / 155.0, 0.0, 1.0)
            vertical_presence = 0.08 + 1.25 * (y ** 9)
            strength = vertical_presence + 0.72 * bright_detail
            stretched.putalpha(Image.fromarray(np.clip(alpha * strength, 0, 255).astype(np.uint8), "L"))
            background.alpha_composite(stretched)

        mask = Image.new("L", (width, height), 0)
        radius = max(1, int(round(25 * self.ui_scale)))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
        background.putalpha(mask)
        photo = ImageTk.PhotoImage(background)
        canvas.delete("home_background")
        canvas.create_image(0, 0, image=photo, anchor="nw", tags="home_background")
        scale = max(0.01, float(self.ui_scale))
        content_x = width / 2 - 649 * scale
        canvas.create_text(
            content_x, 36 * scale, text="Trier vos photos, simplement",
            anchor="nw", fill="#13213D",
            font=("Segoe UI", -max(1, int(round(30 * scale))), "bold"),
            tags="home_background",
        )
        canvas.create_text(
            content_x, 77 * scale,
            text="Choisissez un dossier. L'application repère les photos réellement proches et ne vous présente que les comparaisons utiles.",
            anchor="nw", fill="#66789A",
            font=("Segoe UI", -max(1, int(round(16 * scale)))),
            tags="home_background",
        )
        self._home_background_photo = photo

    def show_home(self):
        self._set_header_variant("home")
        self.set_active_nav("home")
        self.render_header_status(None)
        self.clear_body()

        source_value = str(self.source_dir) if self.source_dir else ""
        page = ctk.CTkFrame(self.body, fg_color="#F4F7FD")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_propagate(False)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        main = ctk.CTkFrame(page, fg_color="#F4F7FD", corner_radius=26, border_width=1, border_color="#D9E3EF")
        main.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)
        background_layer = tk.Canvas(main, bg="#F4F7FD", bd=0, highlightthickness=0)
        background_layer.place(x=1, y=1, relwidth=1.0, relheight=1.0, width=-2, height=-2)
        self._home_background_label = background_layer
        main.bind("<Configure>", self._schedule_home_background, add="+")
        self.after(20, self._render_home_background)

        safe = ctk.CTkFrame(main, width=1298, height=52, fg_color="#EAF7EF", corner_radius=14, border_width=1, border_color="#D8EFE1")
        safe.place(relx=0.5, y=131, anchor="n")
        safe.pack_propagate(False)
        if self.shield_icon:
            ctk.CTkLabel(safe, text="", image=self.shield_icon).pack(side="left", padx=(18, 18), pady=12)
        ctk.CTkLabel(safe, text="Les originaux restent intacts.", text_color="#188548", font=ctk.CTkFont(size=16)).pack(side="left", pady=12)

        source_area = ctk.CTkFrame(main, width=1298, height=126, fg_color="#F7F9FE", corner_radius=16, border_width=1, border_color="#DCE5F1")
        source_area.place(relx=0.5, y=204, anchor="n")
        source_area.grid_propagate(False)
        source_area.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(source_area, text="Dossier à analyser", font=ctk.CTkFont(size=16, weight="bold"), text_color="#1C2942").grid(row=0, column=0, columnspan=2, sticky="w", padx=24, pady=(18, 12))
        entry_wrap = ctk.CTkFrame(source_area, fg_color="#FFFFFF", corner_radius=12, border_width=1, border_color="#D9E3EF", height=50)
        entry_wrap.grid(row=1, column=0, sticky="ew", padx=(18, 14), pady=(0, 19))
        entry_wrap.grid_propagate(False)
        entry_wrap.grid_columnconfigure(1, weight=1)
        if self.folder_icon:
            ctk.CTkLabel(entry_wrap, text="", image=self.folder_icon).grid(row=0, column=0, padx=(16, 10), pady=10)
        self.source_var = ctk.StringVar(value=source_value)
        self.source_entry = ctk.CTkEntry(
            entry_wrap, height=40,
            placeholder_text="Sélectionnez un dossier à analyser...",
            fg_color="transparent", border_width=0,
            text_color="#1E2B44", placeholder_text_color="#95A4BE",
            font=ctk.CTkFont(size=15),
        )
        self.source_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=4)
        if source_value:
            self.source_entry.insert(0, source_value)
        ctk.CTkButton(source_area, text="Parcourir", image=self.folder_icon, compound="left", width=194, height=50, fg_color="#FFFFFF", hover_color="#F6F9FF", text_color=C["blue2"], border_width=1, border_color="#D9E3EF", corner_radius=12, font=ctk.CTkFont(size=16, weight="bold"), command=self.pick_source).grid(row=1, column=1, padx=(0, 18), pady=(0, 17))

        # Les trois éléments inférieurs partagent désormais la même largeur :
        # la carte d'information ne paraît plus étirée par rapport au bouton.
        info = ctk.CTkFrame(main, width=1120, height=110, fg_color="#EEF4FF", corner_radius=16, border_width=1, border_color="#DDE8FA")
        info.place(relx=0.5, y=342, anchor="n")
        info.grid_propagate(False)
        info.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            info, text="i", width=40, height=40, corner_radius=20,
            fg_color="#2F7CF6", text_color="#FFFFFF",
            font=ctk.CTkFont(size=25, weight="bold"),
        ).grid(row=0, column=0, padx=(26, 20), pady=18, sticky="n")
        info_text = ctk.CTkFrame(info, fg_color="transparent")
        info_text.grid(row=0, column=1, sticky="ew", pady=15)
        ctk.CTkLabel(info_text, text="Enregistrement du résultat", font=ctk.CTkFont(size=16, weight="bold"), text_color=C["blue2"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info_text, text="Le dossier final ne vous sera demandé qu'une fois le tri terminé.\nL'avancement est sauvegardé automatiquement entre-temps.", text_color="#5F7190", font=ctk.CTkFont(size=13), justify="left", anchor="w").pack(fill="x", pady=(6, 0))
        if getattr(self, "info_decor_image", None):
            ctk.CTkLabel(info, text="", image=self.info_decor_image, fg_color="transparent").grid(row=0, column=2, padx=(10, 26), pady=6)

        ctk.CTkButton(
            main, text="✦  Analyser le dossier", width=1120, height=66,
            fg_color="#1768F2", hover_color="#0F5DDF",
            border_width=1, border_color="#0E5ADB", corner_radius=17,
            font=ctk.CTkFont(size=22, weight="bold"), command=self.begin_analysis,
        ).place(relx=0.5, y=475, anchor="n")

        # La carte de reprise reste à l'intérieur de la zone centrale claire du
        # décor. Ses quatre coins ont ainsi le même rendu, sans bande fantôme
        # sur les halos bleutés des côtés.
        resume_outer = ctk.CTkFrame(main, width=1120, height=145, fg_color="#F7F9FE", corner_radius=18, border_width=1, border_color="#DCE5F1")
        resume_outer.place(relx=0.5, y=566, anchor="n")
        resume_outer.grid_propagate(False)
        ctk.CTkLabel(
            resume_outer, text="Reprendre un travail", image=self.history_icon,
            compound="left", font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#1C2942",
        ).place(relx=0.5, y=18, anchor="n")
        ctk.CTkLabel(
            resume_outer, text="Rouvrez une session déjà commencée.",
            text_color=C["muted"], font=ctk.CTkFont(size=14),
        ).place(relx=0.5, y=49, anchor="n")
        resume_state = "normal" if (self.last_session_path.exists() or (self.config_dir / "working_session.json").exists()) else "disabled"
        ctk.CTkButton(resume_outer, text="Dernière session", image=self.history_icon, compound="left", width=500, height=48, fg_color="#FFFFFF", hover_color="#F6F9FF", text_color=C["blue2"], border_width=1, border_color="#D9E3EF", corner_radius=12, font=ctk.CTkFont(size=16), state=resume_state, command=self.resume_last_session).place(x=30, y=82)
        ctk.CTkButton(resume_outer, text="Ouvrir un tri en cours...", image=self.folder_icon, compound="left", width=500, height=48, fg_color="#FFFFFF", hover_color="#F6F9FF", text_color=C["blue2"], border_width=1, border_color="#D9E3EF", corner_radius=12, font=ctk.CTkFont(size=16), command=self.open_existing_session).place(x=590, y=82)

        self.footer_stats.set("")

    def card(self, parent):
        return ctk.CTkFrame(parent, fg_color=C["panel"], border_width=1, border_color=C["line"], corner_radius=18)

    def pick_source(self):
        path = filedialog.askdirectory(title="Choisir le dossier contenant les photos")
        if path:
            self.source_var.set(path)
            if hasattr(self, "source_entry"):
                self.source_entry.delete(0, "end")
                self.source_entry.insert(0, path)

    def current_output_directory(self):
        if self.session and self.session.get("output_dir"):
            return self.session["output_dir"]
        return self.settings.get("default_output_dir", "")

    def pick_output(self):
        current = self.current_output_directory()
        options = {"title": "Choisir le dossier qui recevra le tri complet"}
        if current and Path(current).exists():
            options["initialdir"] = current
        path = filedialog.askdirectory(**options)
        if path:
            self.output_var.set(path)
            self.settings["default_output_dir"] = path
            self.save_settings()

    def begin_analysis(self):
        source_text = self.source_entry.get().strip() if hasattr(self, "source_entry") else self.source_var.get().strip()
        source = Path(source_text)
        if not source.exists():
            messagebox.showerror("Dossier introuvable", "Choisis un dossier valide.")
            return

        self.settings["resume_session"] = False
        self.save_settings()
        self.session = None
        self.history.clear()
        self.decision_in_progress = False
        self.source_dir = source
        self.session_path = self.config_dir / "working_session.json"
        progress = ProgressDialog(self, "Analyse de la photothèque")
        threading.Thread(
            target=self.analysis_worker,
            args=(source, None, progress),
            daemon=True
        ).start()

    def analysis_worker(self, source, output, progress):
        try:
            def ensure_not_cancelled():
                progress.raise_if_cancelled()

            allowed = set()
            fmts = self.settings["formats"]
            if fmts.get("JPG"): allowed |= {".jpg", ".jpeg"}
            if fmts.get("PNG"): allowed.add(".png")
            if fmts.get("HEIC"): allowed |= {".heic", ".heif"}
            if fmts.get("TIFF"): allowed |= {".tif", ".tiff"}
            if fmts.get("WEBP"): allowed.add(".webp")

            ensure_not_cancelled()
            output_is_inside_source = False if output is None else is_relative_to(output, source)
            photos = sorted(
                (
                    p for p in source.rglob("*")
                    if p.is_file()
                    and p.suffix.lower() in allowed
                    and not (output_is_inside_source and is_relative_to(p, output))
                ),
                key=lambda p: natural_path_key(p.relative_to(source))
            )
            if not photos:
                raise RuntimeError("Aucune photo compatible trouvée.")

            progress.update_progress("Recherche des doublons exacts…", 0, len(photos))
            exact = defaultdict(list)
            hash_failed = []
            for i, path in enumerate(photos, 1):
                ensure_not_cancelled()
                try:
                    exact[(path.stat().st_size, sha256_file(path))].append(path)
                except Exception:
                    # Une erreur de lecture ne doit jamais faire disparaître une photo.
                    hash_failed.append(path)
                progress.update_progress(value=i)

            exact_groups = [list(group) for group in exact.values() if len(group) > 1]
            representatives = [group[0] for group in exact.values()]
            representatives.extend(hash_failed)
            representatives.sort(key=lambda p: natural_path_key(p.relative_to(source)))

            progress.update_progress("Analyse visuelle et technique de toutes les photos…", 0, len(representatives))
            representative_records = []
            skipped = []
            for i, path in enumerate(representatives, 1):
                ensure_not_cancelled()
                try:
                    rec = image_metrics(path)
                    rec["score"] = quality_score(rec)
                    representative_records.append(rec)
                except Exception as exc:
                    skipped.append({"path": str(path), "error": str(exc)})
                progress.update_progress(value=i)

            # Les doublons binaires réutilisent les métriques du représentant afin
            # que chaque fichier reste présent dans la comparaison sans décodage inutile.
            records_by_path = {record["path"]: record for record in representative_records}
            records = list(representative_records)
            for exact_group in exact_groups:
                representative = str(exact_group[0])
                base_record = records_by_path.get(representative)
                if base_record:
                    for path in exact_group[1:]:
                        clone = dict(base_record)
                        clone["path"] = str(path)
                        records.append(clone)
                        records_by_path[str(path)] = clone

            source_order = {str(path): index for index, path in enumerate(photos)}
            records.sort(key=lambda record: source_order.get(record["path"], len(source_order)))
            records_by_path = {record["path"]: record for record in records}

            mode = self.settings["sensitivity"]
            threshold = {"Prudent": 4, "Équilibré": 8, "Agressif": 12}[mode]
            time_window = {"Prudent": 20, "Équilibré": 120, "Agressif": 600}[mode]

            if len(records) <= 6000:
                progress.update_progress(
                    "Comparaison exhaustive de chaque photo…",
                    0,
                    max(1, len(records) - 1)
                )
                similar_index_pairs = find_similar_pairs(
                    records, threshold, time_window, progress=progress, cancel_check=ensure_not_cancelled
                )
            else:
                progress.update_progress(
                    "Comparaison complète par index multi-signatures…",
                    0,
                    1
                )
                similar_index_pairs = find_similar_pairs(
                    records, threshold, time_window, progress=None, cancel_check=ensure_not_cancelled
                )
                progress.update_progress(value=1)

            # Une paire reste indépendante : « garder les deux » ne les exempte
            # pas d'une comparaison ultérieure avec d'autres doublons possibles.
            ensure_not_cancelled()
            pair_types = {}
            for exact_group in exact_groups:
                paths = [str(path) for path in exact_group]
                for left_pos in range(len(paths) - 1):
                    for right_pos in range(left_pos + 1, len(paths)):
                        a, b = paths[left_pos], paths[right_pos]
                        key = (a, b) if source_order.get(a, 0) <= source_order.get(b, 0) else (b, a)
                        pair_types[key] = "exact"

            for left_index, right_index in similar_index_pairs:
                a = records[left_index]["path"]
                b = records[right_index]["path"]
                key = (a, b) if source_order.get(a, 0) <= source_order.get(b, 0) else (b, a)
                pair_types.setdefault(key, "similar")

            ordered_pairs = sorted(
                pair_types.items(),
                key=lambda item: (
                    source_order.get(item[0][0], len(source_order)),
                    source_order.get(item[0][1], len(source_order)),
                    0 if item[1] == "exact" else 1,
                )
            )

            groups = []
            paired_paths = set()
            for (left_path, right_path), pair_type in ordered_pairs:
                paired_paths.update((left_path, right_path))
                left_record = records_by_path.get(left_path, {"path": left_path, "score": 1.0 if pair_type == "exact" else 0.0})
                right_record = records_by_path.get(right_path, {"path": right_path, "score": 1.0 if pair_type == "exact" else 0.0})
                groups.append({
                    "type": pair_type,
                    "items": [left_path, right_path],
                    "records": {left_path: left_record, right_path: right_record},
                    "status": "pending",
                    "kept": [],
                    "rejected": [],
                    "aside": [],
                    "candidate": left_path,
                    "remaining": [right_path],
                })

            # Les photos sans correspondance pertinente sont conservées automatiquement.
            # Elles ne sont jamais associées artificiellement à une photo voisine : l'écran
            # « deux par deux » ne montre donc que de vraies comparaisons.
            readable_paths = [r["path"] for r in records]
            unique_paths = [path for path in readable_paths if path not in paired_paths]

            self.session = {
                "version": "14.21",
                "source_dir": str(source),
                "output_dir": "",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "total_files": len(photos),
                "all_files": [str(path) for path in photos],
                "analyzed_files": len(records),
                "skipped": skipped,
                "unique_keep": sorted(unique_paths, key=natural_path_key),
                "global_rejected": [],
                "groups": groups,
                "group_index": 0,
                "similarity_threshold": threshold,
                "time_window": time_window,
                "automatic_keep_both": 0,
                "comparisons_done": 0,
                "total_candidate_pairs": len(ordered_pairs),
                "total_unique_reviews": 0,
                "reviewed_files": [],
                "decisions": {"kept": 0, "rejected": 0},
                "review_complete": False,
                "complete": False
            }
            self.save_session(force=True)
            self.call_on_ui(progress.destroy)
            self.call_on_ui(self.show_review)
        except AnalysisCancelled:
            self.call_on_ui(progress.destroy)
        except Exception as exc:
            message = str(exc)
            self.call_on_ui(progress.destroy)
            self.call_on_ui(
                lambda msg=message: messagebox.showerror("Analyse impossible", msg)
            )

    def normalize_session(self, session):
        if not isinstance(session.get("groups"), list):
            raise ValueError("Le fichier ne contient pas une session de tri valide.")

        global_rejected = set(session.get("global_rejected", []))
        unique_keep = set(session.get("unique_keep", []))
        cleaned_groups = []
        for group in session.get("groups", []):
            legacy_aside = group.pop("aside", [])
            rejected = group.setdefault("rejected", [])
            for item in legacy_aside:
                if item not in rejected:
                    rejected.append(item)
            if group.get("type") == "unique":
                target = group.get("unique_target") or group.get("candidate")
                if target and target not in global_rejected:
                    unique_keep.add(target)
                continue
            cleaned_groups.append(group)

        session["groups"] = cleaned_groups
        session["unique_keep"] = sorted(unique_keep, key=natural_path_key)
        session.setdefault("complete", False)
        session.setdefault("review_complete", bool(session.get("complete")))
        session.setdefault("comparisons_done", 0)
        session.setdefault("group_index", 0)
        session.setdefault("reviewed_files", [])
        session["total_unique_reviews"] = 0
        session.setdefault("similarity_threshold", 8)
        session.setdefault("time_window", 120)
        session.setdefault("automatic_keep_both", 0)

        if not isinstance(session.get("all_files"), list):
            all_files = set(session.get("unique_keep", []))
            all_files.update(item.get("path") for item in session.get("skipped", []) if item.get("path"))
            for group in session.get("groups", []):
                all_files.update(group.get("items", []))
            session["all_files"] = sorted(all_files, key=natural_path_key)

        if not isinstance(session.get("global_rejected"), list):
            rejected = set()
            kept = set(session.get("unique_keep", []))
            for group in session.get("groups", []):
                rejected.update(group.get("rejected", []))
                kept.update(group.get("kept", []))
            rejected -= kept
            session["global_rejected"] = sorted(rejected, key=natural_path_key)

        # Recalage sur la première comparaison encore en attente.
        idx = 0
        while idx < len(cleaned_groups) and cleaned_groups[idx].get("status") != "pending":
            idx += 1
        session["group_index"] = idx
        session["total_candidate_pairs"] = len(cleaned_groups)
        return session

    def activate_session(self, session, source, loaded_from=None):
        session = self.normalize_session(session)
        output_text = session.get("output_dir", "")

        if not output_text and loaded_from:
            loaded_from = Path(loaded_from)
            if loaded_from.parent.resolve() != self.config_dir.resolve():
                output_text = str(loaded_from.parent)
                session["output_dir"] = output_text

        self.session = session
        self.source_dir = Path(source)
        if output_text:
            output = Path(output_text)
            output.mkdir(parents=True, exist_ok=True)
            self.session_path = output / "working_session.json"
            self.settings["default_output_dir"] = str(output)
            self.save_settings()
        else:
            self.session_path = self.config_dir / "working_session.json"

        self.save_session(force=True)
        self.show_review()

    def open_existing_session(self):
        choice = messagebox.askyesnocancel(
            "Ouvrir un tri en cours",
            "Oui : choisir un dossier de travail.\n"
            "Non : choisir directement un fichier de session.\n"
            "Annuler : revenir à l’accueil."
        )
        if choice is None:
            return

        if choice:
            folder = filedialog.askdirectory(title="Choisir le dossier du tri en cours")
            if not folder:
                return
            folder_path = Path(folder)
            candidates = [
                folder_path / "working_session.json",
                folder_path / "last_session.json",
                folder_path / "session_complete.json",
                folder_path / "session_tri_photos.json",
            ]
            # Also accept result folders that contain one nested session file.
            candidates.extend(folder_path.glob("**/working_session.json"))
            candidates.extend(folder_path.glob("**/session_complete.json"))
            candidates = [p for p in candidates if p.exists()]
            if not candidates:
                messagebox.showerror(
                    "Aucune session trouvée",
                    "Ce dossier ne contient aucun fichier de session reconnu."
                )
                return
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            self.load_session_file(candidates[0])
        else:
            file_path = filedialog.askopenfilename(
                title="Choisir un fichier de session",
                filetypes=[
                    ("Sessions TriPhotos", "*.json"),
                    ("Tous les fichiers", "*.*"),
                ]
            )
            if file_path:
                self.load_session_file(Path(file_path))

    def load_session_file(self, path):
        try:
            session = json.loads(Path(path).read_text(encoding="utf-8"))
            session = self.normalize_session(session)

            source = Path(session.get("source_dir", ""))
            if not source.exists():
                replacement = filedialog.askdirectory(
                    title="Le dossier source a été déplacé. Indique son nouvel emplacement."
                )
                if not replacement:
                    return
                source = Path(replacement)
                session["source_dir"] = str(source)

            self.activate_session(session, source, loaded_from=path)
        except Exception as exc:
            messagebox.showerror(
                "Session impossible à ouvrir",
                f"Le tri n’a pas pu être chargé.\n\n{exc}"
            )

    def resume_last_session(self):
        candidates = [
            self.config_dir / "working_session.json",
            self.last_session_path,
        ]
        candidates = [p for p in candidates if p.exists()]
        if not candidates:
            messagebox.showinfo("Aucune session", "Aucune session précédente n’a été trouvée.")
            return

        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        errors = []
        for path in candidates:
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
                session = self.normalize_session(session)
                source = Path(session.get("source_dir", ""))
                if not source.exists():
                    errors.append(f"{path.name} : dossier source introuvable")
                    continue
                self.activate_session(session, source, loaded_from=path)
                return
            except Exception as exc:
                errors.append(f"{path.name} : {exc}")

        messagebox.showerror(
            "Session impossible à ouvrir",
            "Aucune session exploitable n’a été trouvée.\n\n" + "\n".join(errors[:4])
        )

    def try_auto_resume(self):
        if not self.settings.get("resume_session", True):
            return
        if self.session is not None or self.current_page != "home":
            return

        candidates = [
            self.config_dir / "working_session.json",
            self.last_session_path,
        ]
        candidates = [p for p in candidates if p.exists()]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for path in candidates:
            try:
                session = self.normalize_session(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if session.get("complete"):
                    continue
                source = Path(session.get("source_dir", ""))
                if not source.exists():
                    continue
                self.activate_session(session, source, loaded_from=path)
                return
            except Exception:
                continue

    def show_review(self):
        self._set_header_variant("review")
        self.set_active_nav("home")
        self.current_page = "review"
        self.clear_body()
        self.history.clear()

        page = ctk.CTkFrame(self.body, fg_color="#F5F8FD")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_propagate(False)

        folder = Path(self.session["source_dir"]).name
        self.render_header_status(folder)

        # Le panneau se dimensionne ensuite selon le format réel des photos.
        board = ctk.CTkFrame(page, width=1616, height=758, fg_color="#FFFFFF", corner_radius=20, border_width=1, border_color="#D9E3EF")
        # Toute largeur supplémentaire de la fenêtre est utilisée : cela permet
        # d'agrandir une photo sans toucher à son rapport largeur/hauteur.
        board.place(relx=0.5, y=10, anchor="n")
        self.review_board = board
        self.review_page = page
        board.grid_propagate(False)
        board.grid_rowconfigure(0, weight=1)
        board.grid_rowconfigure(1, weight=0, minsize=90)
        board.grid_columnconfigure(0, weight=1, uniform="photo_columns")
        board.grid_columnconfigure(1, weight=0)
        board.grid_columnconfigure(2, weight=1, uniform="photo_columns")

        self.left_card = self.photo_card(board, 0)
        center_col = ctk.CTkFrame(board, width=74, fg_color="transparent")
        center_col.grid(row=0, column=1, sticky="ns", pady=24)
        center_col.grid_propagate(False)
        ctk.CTkFrame(center_col, width=1, fg_color="#DDE5EF", corner_radius=0).place(relx=0.5, rely=0.0, relheight=1.0, anchor="n")
        vs_shell = ctk.CTkFrame(center_col, fg_color="#FFFFFF", corner_radius=28, width=56, height=56, border_width=1, border_color="#DDE5EF")
        vs_shell.place(relx=0.5, rely=0.545, anchor="center")
        vs_shell.grid_propagate(False)
        ctk.CTkLabel(vs_shell, text="VS", text_color="#27364F", font=ctk.CTkFont(size=15, weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        self.right_card = self.photo_card(board, 2)

        self._build_review_actions(board)

        for card in (self.left_card, self.right_card):
            card["image_frame"].bind("<Configure>", self._schedule_photo_refit, add="+")
        page.bind("<Configure>", self._schedule_review_geometry, add="+")

        self.after(100, self._focus_if_visible)
        self.after(180, self.show_current_pair)
        self.after(520, self._refit_current_photos)

    def _build_review_actions(self, parent):
        """Construit une rangée native, stable à toutes les échelles Windows."""
        zone_height = max(1, int(round(90 * self.ui_scale)))
        self.actions_zone = tk.Frame(self, height=zone_height, bg="#FFFFFF", bd=0, highlightthickness=0)
        self.actions_zone.place(x=-10000, y=-10000, width=1, height=zone_height)
        self.actions_zone.pack_propagate(False)
        self.actions_canvas = tk.Canvas(self.actions_zone, bg="#FFFFFF", bd=0, highlightthickness=0)
        self.actions_canvas.pack(fill="both", expand=True)
        self.action_buttons = [
            {"kind": "canvas", "text": "Garder la gauche", "shortcut": "←", "color": C["red"], "hover": C["red_hover"], "command": self.keep_left, "text_color": "white", "hovered": False},
            {"kind": "canvas", "text": "Garder la droite", "shortcut": "→", "color": C["green"], "hover": C["green_hover"], "command": self.keep_right, "text_color": "white", "hovered": False},
            {"kind": "canvas", "text": "Garder les deux", "shortcut": "↑", "color": C["blue2"], "hover": "#1D4ED8", "command": self.keep_both, "text_color": "white", "hovered": False},
            {"kind": "canvas", "text": "Supprimer les deux", "shortcut": "Suppr", "color": "#7C3AED", "hover": "#6D28D9", "command": lambda: self.resolve_pair("reject"), "text_color": "white", "hovered": False},
            {"kind": "canvas", "text": "Annuler le choix", "shortcut": "Ctrl+Z", "color": C["soft"], "hover": C["soft_hover"], "command": self.undo, "text_color": C["text"], "hovered": False},
        ]
        self.actions_canvas.bind("<Configure>", lambda _e: self._draw_review_actions_canvas(), add="+")
        self.after_idle(self._draw_review_actions_canvas)

    def _draw_review_actions_canvas(self):
        canvas = getattr(self, "actions_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        scale = max(0.01, float(self.ui_scale))
        width = max(2, canvas.winfo_width())
        height = max(2, canvas.winfo_height())
        tile_widths = (210, 210, 205, 235, 240)
        key_widths = (42, 42, 42, 62, 68)
        padding = 8 * scale
        total_width = (sum(tile_widths) + 16 * len(tile_widths)) * scale
        x = (width - total_width) / 2
        tile_height = 70 * scale
        y1 = (height - tile_height) / 2
        y2 = y1 + tile_height

        for index, ref in enumerate(self.action_buttons):
            x += padding
            x1 = x
            x2 = x1 + tile_widths[index] * scale
            tag = f"action_{index}"
            color = ref["hover"] if ref.get("hovered") else ref["color"]
            self._canvas_round_rect(
                canvas, x1, y1, x2, y2, radius=17 * scale,
                fill=color, outline=color, width=max(1, int(round(scale))), tags=(tag,),
            )
            key_width = key_widths[index] * scale
            key_x1 = x1 + 18 * scale
            key_y1 = y1 + 18 * scale
            self._canvas_round_rect(
                canvas, key_x1, key_y1, key_x1 + key_width, key_y1 + 34 * scale,
                radius=7 * scale, fill="#FFFFFF", outline="", tags=(tag,),
            )
            canvas.create_text(
                key_x1 + key_width / 2, key_y1 + 17 * scale,
                text=ref["shortcut"], fill="#1C2942", anchor="center",
                font=("Segoe UI", -max(1, int(round(13 * scale))), "bold"), tags=(tag,),
            )
            text_center = key_x1 + key_width + (x2 - key_x1 - key_width) / 2
            canvas.create_text(
                text_center, y1 + tile_height / 2, text=ref["text"],
                fill=ref["text_color"], anchor="center",
                font=("Segoe UI", -max(1, int(round(14 * scale))), "bold"), tags=(tag,),
            )
            canvas.tag_bind(tag, "<Button-1>", lambda _e, i=index: self.action_buttons[i]["command"]())
            canvas.tag_bind(tag, "<Enter>", lambda _e, i=index: self._set_canvas_action_hover(i, True))
            canvas.tag_bind(tag, "<Leave>", lambda _e, i=index: self._set_canvas_action_hover(i, False))
            x = x2 + padding

    def _set_canvas_action_hover(self, index, hovered):
        if 0 <= index < len(getattr(self, "action_buttons", [])):
            self.action_buttons[index]["hovered"] = bool(hovered)
            self.actions_canvas.configure(cursor="hand2" if hovered else "")
            self._draw_review_actions_canvas()

    def _rebuild_review_actions(self):
        """Contourne un défaut de repeinture CTk après un zoom supérieur à 100 %."""
        if self.current_page != "review" or not hasattr(self, "review_page"):
            return
        old_zone = getattr(self, "actions_zone", None)
        if old_zone is not None and old_zone.winfo_exists():
            old_zone.destroy()
        self._build_review_actions(self.review_board)

    def _schedule_review_geometry(self, _event=None, left=None, right=None, records=None):
        """Adapte le panneau au format réel des deux images affichées."""
        if left and right and records is not None:
            self._review_geometry_inputs = (left, right, records)
        job = getattr(self, "_review_geometry_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._review_geometry_job = self.after(90, self._configure_review_geometry)

    def _configure_review_geometry(self):
        self._review_geometry_job = None
        if self.current_page != "review" or not hasattr(self, "review_board"):
            return
        inputs = getattr(self, "_review_geometry_inputs", None)
        if not inputs:
            return
        left, right, records = inputs
        scale = max(0.01, float(self.ui_scale))
        self.update_idletasks()
        page_width = max(1.0, self.review_page.winfo_width() / scale)
        board_width = max(1180.0, page_width - 48.0)
        self.review_board.configure(width=int(round(board_width)))
        self.update_idletasks()
        # Largeur de chaque cadre dans les unités de la maquette. Les 74 px du
        # séparateur et les marges latérales sont retirés avant le calcul.
        frame_width = max(1.0, (board_width - 74.0 - 48.0) / 2.0)

        ratios = []
        for path in (left, right):
            record = records.get(path, {})
            width = float(record.get("width", 0) or 0)
            height = float(record.get("height", 0) or 0)
            if width > 0 and height > 0:
                ratios.append(width / height)
                continue
            try:
                with Image.open(path) as image:
                    width, height = image.size
                if width > 0 and height > 0:
                    ratios.append(width / height)
            except Exception:
                pass
        if not ratios:
            ratios = [16 / 9]

        # 95 px correspondent au titre, aux métadonnées et aux marges de carte.
        # La limite dépend maintenant de la hauteur réellement disponible : sur
        # un grand écran, le cadre conserve exactement le rapport de la photo au
        # lieu de laisser une bande sombre résiduelle sous l'aperçu.
        image_height = max(frame_width / max(0.1, ratio) for ratio in ratios)
        page_height = max(1.0, self.review_page.winfo_height() / scale)
        max_photo_area_height = max(500.0, page_height - 112.0)
        photo_area_height = max(500, min(int(round(max_photo_area_height)), int(round(image_height + 95))))
        board_height = photo_area_height + 90
        self.review_board.configure(height=board_height)
        self.update_idletasks()
        actions_x = self.review_board.winfo_x()
        actions_y = self.body.winfo_y() + self.review_board.winfo_y() + int(round(photo_area_height * scale))
        actions_width = self.review_board.winfo_width()
        actions_height = max(1, int(round(90 * scale)))
        self.actions_zone.place(
            x=actions_x, y=actions_y,
            width=actions_width, height=actions_height,
        )
        try:
            self.actions_zone.tkraise()
        except Exception:
            pass
        self.after(70, self._refit_current_photos)

    def photo_card(self, parent, column):
        card = ctk.CTkFrame(parent, fg_color="transparent")
        horizontal_padding = (24, 0) if column == 0 else (0, 24)
        card.grid(row=0, column=column, sticky="nsew", padx=horizontal_padding, pady=(19, 23))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        head.grid_columnconfigure(0, weight=1)

        name = ctk.StringVar()
        meta = ctk.StringVar()
        score = ctk.StringVar(value="— / 100")
        recommendation = ctk.StringVar(value="")

        identity = ctk.CTkFrame(head, fg_color="transparent")
        identity.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(identity, textvariable=name, font=ctk.CTkFont(size=17, weight="bold"), text_color="#172033", anchor="w").pack(side="left")
        ctk.CTkLabel(identity, textvariable=meta, text_color=C["muted"], font=ctk.CTkFont(size=10), anchor="w").pack(side="left", padx=(10, 0))

        badges = ctk.CTkFrame(head, fg_color="transparent")
        badges.grid(row=0, column=1, padx=(12, 8))
        rec_label = ctk.CTkLabel(badges, textvariable=recommendation, fg_color="transparent", corner_radius=10, padx=12, pady=5, font=ctk.CTkFont(size=11, weight="bold"))
        rec_label.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(badges, textvariable=score, fg_color=C["soft"], corner_radius=10, padx=10, pady=5, font=ctk.CTkFont(size=11, weight="bold"), text_color=C["amber"]).pack(side="left")
        open_btn = ctk.CTkButton(head, text="⤢", width=42, height=42, fg_color=C["soft"], hover_color=C["soft_hover"], text_color=C["text"], corner_radius=12)
        open_btn.grid(row=0, column=2)

        image_frame = ctk.CTkFrame(card, fg_color="#FFFFFF", corner_radius=8)
        image_frame.grid(row=1, column=0, sticky="nsew")
        image_frame.grid_rowconfigure(0, weight=1)
        image_frame.grid_columnconfigure(0, weight=1)
        image_label = tk.Label(
            image_frame, text="", bg="#FFFFFF", fg="#172033",
            bd=0, highlightthickness=0, font=("Segoe UI", 13),
        )
        image_label.grid(row=0, column=0, sticky="nsew")

        hint = ctk.StringVar()
        return {"card": card, "name": name, "meta": meta, "score": score, "recommendation": recommendation, "recommendation_label": rec_label, "hint": hint, "open": open_btn, "image": image_label, "image_frame": image_frame}

    def _schedule_photo_refit(self, _event=None):
        """Réajuste les deux aperçus après un redimensionnement de la fenêtre."""
        if self.current_page != "review" or not self.session:
            return
        if self._photo_resize_job is not None:
            try:
                self.after_cancel(self._photo_resize_job)
            except Exception:
                pass
        self._photo_resize_job = self.after(160, self._refit_current_photos)

    def _refit_current_photos(self):
        self._photo_resize_job = None
        if self.current_page != "review" or not self.session:
            return
        groups = self.session.get("groups", [])
        idx = int(self.session.get("group_index", 0) or 0)
        if idx < 0 or idx >= len(groups):
            return
        group = groups[idx]
        if group.get("status") != "pending":
            return
        left = group.get("display_left")
        right = group.get("display_right")
        if not left or not right:
            return
        records = group.get("records", {})
        self.fill_photo(self.left_card, left, records.get(left, {}), "left", recommended=False)
        self.fill_photo(self.right_card, right, records.get(right, {}), "right", recommended=True)

    def action_btn(self, parent, column, text, shortcut, color, hover, command, text_color=None, icon=None):
        widths = (210, 210, 205, 235, 240)
        key_widths = (42, 42, 42, 62, 68)
        text_widths = (122, 122, 112, 137, 120)
        button = ctk.CTkFrame(
            parent, fg_color=color, corner_radius=17,
            border_width=1, border_color=color,
            width=widths[column], height=70,
        )
        button.grid(row=0, column=column, padx=8, sticky="n")
        button.grid_propagate(False)
        button.pack_propagate(False)

        label_color = text_color if text_color is not None else "white"
        key_width = key_widths[column]
        text_width = text_widths[column]
        group_width = key_width + 10 + text_width
        start_x = (widths[column] - group_width) / 2
        key_wrap = ctk.CTkFrame(
            button, width=key_width, height=34,
            fg_color="#FFFFFF", corner_radius=7, border_width=0,
        )
        key_wrap.place(x=start_x, y=18)
        key_wrap.pack_propagate(False)
        key_label = ctk.CTkLabel(
            key_wrap, text=shortcut, text_color="#1C2942",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        key_label.place(relx=0.5, rely=0.5, anchor="center")
        text_label = ctk.CTkLabel(
            button, text=text, width=text_width, height=34,
            text_color=label_color,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="center", justify="center",
        )
        text_label.place(x=start_x + key_width + 10, y=18)

        def bind_click(widget):
            widget.bind("<Button-1>", lambda _e: command(), add="+")
            widget.bind("<Enter>", lambda _e: button.configure(fg_color=hover, border_color=hover), add="+")
            widget.bind("<Leave>", lambda _e: button.configure(fg_color=color, border_color=color), add="+")
        for widget in (button, text_label, key_wrap, key_label):
            bind_click(widget)

        return {
            "frame": button, "text_label": text_label,
            "key_wrap": key_wrap, "key_label": key_label,
            "text_color": label_color, "color": color,
            "hover": hover, "command": command,
        }

    def set_action_button(self, button_ref, text, shortcut, color, hover, command, text_color=None):
        label_color = text_color if text_color is not None else "white"
        if button_ref.get("kind") == "canvas":
            button_ref.update({
                "text": text, "shortcut": shortcut,
                "color": color, "hover": hover,
                "command": command, "text_color": label_color,
            })
            self._draw_review_actions_canvas()
            return
        button_ref["text_label"].configure(text=text, text_color=label_color)
        button_ref["key_label"].configure(text=shortcut)
        button_ref["frame"].configure(fg_color=color, border_color=color)
        button_ref["text_color"] = label_color
        button_ref["color"] = color
        button_ref["hover"] = hover
        button_ref["command"] = command
        for widget in (
            button_ref["frame"], button_ref["text_label"],
            button_ref["key_wrap"], button_ref["key_label"],
        ):
            widget.bind("<Button-1>", lambda _e, cmd=command: cmd())
            widget.bind("<Enter>", lambda _e, ref=button_ref: ref["frame"].configure(fg_color=ref["hover"], border_color=ref["hover"]))
            widget.bind("<Leave>", lambda _e, ref=button_ref: ref["frame"].configure(fg_color=ref["color"], border_color=ref["color"]))

    def current_group(self):
        idx = self.session.get("group_index", 0)
        groups = self.session["groups"]
        while idx < len(groups) and groups[idx]["status"] != "pending":
            idx += 1
        self.session["group_index"] = idx
        return groups[idx] if idx < len(groups) else None

    def show_current_pair(self):
        session_changed = False

        while True:
            group = self.current_group()
            if not group:
                if session_changed:
                    self.save_session()
                self.decision_in_progress = False
                self.finish_review()
                return

            if group.get("type") == "unique":
                target = group.get("unique_target") or group.get("candidate")
                if target and target not in set(self.session.get("global_rejected", [])):
                    unique_keep = set(self.session.get("unique_keep", []))
                    unique_keep.add(target)
                    self.session["unique_keep"] = sorted(unique_keep, key=natural_path_key)
                group["status"] = "done"
                self.session["group_index"] += 1
                session_changed = True
                continue

            if getattr(self, "action_buttons", None):
                self.set_action_button(self.action_buttons[0], "Garder la gauche", "←", C["red"], C["red_hover"], self.keep_left)
                self.set_action_button(self.action_buttons[1], "Garder la droite", "→", C["green"], C["green_hover"], self.keep_right)
                self.set_action_button(self.action_buttons[2], "Garder les deux", "↑", C["blue2"], "#1D4ED8", self.keep_both)
                self.set_action_button(self.action_buttons[3], "Supprimer les deux", "Suppr", "#7C3AED", "#6D28D9", lambda: self.resolve_pair("reject"))
                self.set_action_button(self.action_buttons[4], "Annuler le choix", "Ctrl+Z", C["soft"], C["soft_hover"], self.undo, C["text"])

            globally_rejected = set(self.session.get("global_rejected", []))
            items = group.get("items", [])
            if any(path in globally_rejected for path in items):
                # Une photo déjà écartée n'a pas besoin d'être comparée de nouveau.
                group["status"] = "done"
                self.session["group_index"] += 1
                session_changed = True
                continue

            if not group.get("remaining"):
                candidate = group.get("candidate")
                if candidate and candidate not in group["kept"]:
                    group["kept"].append(candidate)
                group["status"] = "done"
                self.session["group_index"] += 1
                session_changed = True
                continue

            candidate = group["candidate"]
            challenger = group["remaining"][0]
            records = group["records"]

            c_score = float(records.get(candidate, {}).get("score", 0) or 0)
            h_score = float(records.get(challenger, {}).get("score", 0) or 0)

            if c_score >= h_score:
                left, right = challenger, candidate
            else:
                left, right = candidate, challenger

            group["display_left"] = left
            group["display_right"] = right
            if session_changed:
                self.save_session()
            self.fill_photo(self.left_card, left, records.get(left, {}), "left", recommended=False)
            self.fill_photo(self.right_card, right, records.get(right, {}), "right", recommended=True)
            self._schedule_review_geometry(left=left, right=right, records=records)
            self.update_progress_display()
            return

    def apply_composition_grid(self, image):
        if not self.settings.get("show_composition_grid", True):
            return image
        overlay = image.convert("RGBA")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(overlay, "RGBA")
        width, height = overlay.size
        line_color = (255, 255, 255, 70)
        shadow_color = (0, 0, 0, 55)
        for x in (width / 3, 2 * width / 3):
            x = int(round(x))
            draw.line((x + 1, 0, x + 1, height), fill=shadow_color, width=1)
            draw.line((x, 0, x, height), fill=line_color, width=1)
        for y in (height / 3, 2 * height / 3):
            y = int(round(y))
            draw.line((0, y + 1, width, y + 1), fill=shadow_color, width=1)
            draw.line((0, y, width, y), fill=line_color, width=1)
        return overlay.convert("RGB")

    def fill_photo(self, card, path, record, side, recommended=False):
        try:
            # Le cadre réel est la seule référence fiable. Les anciennes valeurs
            # minimales pouvaient créer une image plus grande que le cadre et donc
            # masquer ses bords. Ici l'image est toujours contenue intégralement.
            self.update_idletasks()
            frame = card["image_frame"]
            frame_w = frame.winfo_width()
            frame_h = frame.winfo_height()
            if frame_w > 2 and frame_h > 2:
                available_w = max(1, frame_w)
                available_h = max(1, frame_h)
            else:
                # Repli conservateur pendant les toutes premières millisecondes.
                available_w = max(1, (self.winfo_width() - 136) // 2)
                available_h = max(1, self.winfo_height() - 517)

            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                width, height = image.size
                # Toujours afficher l'image entière dans son format d'origine.
                # L'ancien remplissage recadrait fortement les paysages quand le
                # cadre devenait très haut. Les marges éventuelles sont donc
                # préférées à la perte d'une partie de la photo.
                render_size = fit_image_size(image.size, (available_w, available_h))
                image = image.resize(render_size, Image.Resampling.LANCZOS)
                image = self.apply_composition_grid(image)
                # Ne pas utiliser CTkImage ici : sa mise à l'échelle DPI peut
                # dépasser le cadre alors que l'image a déjà été ajustée.
                photo = ImageTk.PhotoImage(image)
            card["image"].configure(image=photo, text="")
            if side == "left":
                self.left_photo = photo
            else:
                self.right_photo = photo

            p = Path(path)
            dt = record.get("datetime")
            if dt:
                date_text = datetime.fromisoformat(dt).strftime("%d/%m/%Y %H:%M")
            else:
                date_text = datetime.fromtimestamp(p.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            megapixels = width * height / 1_000_000
            if self.settings["show_metadata"]:
                extra = f"{date_text}  ·  {width}×{height}  ·  {megapixels:.1f} MP".replace(".", ",")
                if record.get("iso") not in (None, "—"):
                    extra += f"  ·  ISO {record['iso']}"
            else:
                extra = f"{width} × {height}"
            technical_score = float(record.get("score", 0) or 0)
            score_100 = max(0, min(100, round(technical_score * 100)))
            card["name"].set(p.name)
            card["meta"].set(extra)
            card["score"].set(f"{score_100} / 100")
            card["recommendation"].set("★ Recommandée" if recommended else "")
            card["recommendation_label"].configure(
                fg_color=C["green"] if recommended else "transparent",
                text_color="#FFFFFF" if recommended else C["muted"]
            )
            card["hint"].set("")
            # Les deux panneaux restent visuellement intégrés dans un même ensemble.
            card["open"].configure(command=lambda target=path: FullImage(self, target))
        except Exception as exc:
            card["image"].configure(image=None, text=f"Impossible d’afficher\n{exc}")
            card["name"].set(Path(path).name)
            card["meta"].set("")
            card["score"].set("— / 100")
            card["recommendation"].set("")
            card["hint"].set("")

    def compute_selection_counts(self):
        rejected = set(self.session.get("global_rejected", []))
        kept = set(self.session.get("unique_keep", []))
        for group in self.session.get("groups", []):
            kept.update(group.get("kept", []))
        kept -= rejected
        return len(kept), len(rejected)

    def update_progress_display(self):
        total_files = int(self.session.get("total_files", 0) or 0)
        groups = self.session.get("groups", [])
        total_comparisons = sum(1 for g in groups if g.get("type") != "unique")
        comparisons_done = int(self.session.get("comparisons_done", 0) or 0)
        reviewed = set(self.session.get("reviewed_files", []))
        automatic = set(self.session.get("unique_keep", []))
        skipped = {item.get("path") for item in self.session.get("skipped", []) if item.get("path")}
        processed = reviewed | automatic | skipped
        if self.session.get("review_complete"):
            processed_count = total_files
        else:
            processed_count = min(total_files, len(processed)) if total_files else len(processed)
        ratio = 1.0 if total_files == 0 else min(1.0, processed_count / total_files)

        kept_count, rejected_count = self.compute_selection_counts()
        self._header_progress_ratio = ratio
        self._header_progress_values = {
            "photos": f"Photos traitées : {processed_count:,} / {total_files:,}".replace(",", " "),
            "percent": f"{ratio * 100:.1f} %".replace(".", ","),
            "comparisons": f"Comparaisons : {comparisons_done:,} / {total_comparisons:,}".replace(",", " "),
            "kept": f"Gardées : {kept_count:,}".replace(",", " "),
            "rejected": f"Mises de côté : {rejected_count:,}".replace(",", " "),
        }
        if self.current_page == "review":
            self._render_header_canvas()
        self.footer_stats.set("")

    def snapshot(self):
        self.history.append(json.dumps(self.session, ensure_ascii=False))
        if len(self.history) > 100:
            self.history.pop(0)

    def resolve_pair(self, action):
        if self.decision_in_progress:
            return
        group = self.current_group()
        if not group:
            return
        self.decision_in_progress = True
        self.snapshot()
        left = group["display_left"]
        right = group["display_right"]
        group.setdefault("aside", [])
        group["remaining"] = [p for p in group["remaining"] if p not in {left, right}]
        old = group["candidate"]

        global_rejected = set(self.session.get("global_rejected", []))
        if action == "left":
            global_rejected.add(right)
            global_rejected.discard(left)
        elif action == "right":
            global_rejected.add(left)
            global_rejected.discard(right)
        elif action == "both":
            # Garder les deux vaut uniquement pour cette comparaison : chaque
            # photo pourra encore être confrontée à un autre doublon potentiel.
            global_rejected.discard(left)
            global_rejected.discard(right)
        elif action == "reject":
            global_rejected.add(left)
            global_rejected.add(right)
        self.session["global_rejected"] = sorted(global_rejected, key=natural_path_key)

        if action == "left":
            group["candidate"] = left
            if right not in group["rejected"]:
                group["rejected"].append(right)
        elif action == "right":
            group["candidate"] = right
            if left not in group["rejected"]:
                group["rejected"].append(left)
        elif action == "both":
            if left not in group["kept"]:
                group["kept"].append(left)
            group["candidate"] = right
        elif action == "reject":
            if left not in group["rejected"]:
                group["rejected"].append(left)
            if right not in group["rejected"]:
                group["rejected"].append(right)
            group["candidate"] = group["remaining"][0] if group["remaining"] else None
            if group["remaining"]:
                group["remaining"] = group["remaining"][1:]

        if (
            old
            and old != group.get("candidate")
            and old not in group["kept"]
            and old not in group["rejected"]
        ):
            group["rejected"].append(old)

        reviewed = set(self.session.get("reviewed_files", []))
        reviewed.update((left, right))
        self.session["reviewed_files"] = sorted(reviewed, key=natural_path_key)
        self.session["comparisons_done"] += 1

        if not group["remaining"]:
            if (
                group.get("candidate")
                and group["candidate"] not in group["rejected"]
                and group["candidate"] not in group["kept"]
            ):
                group["kept"].append(group["candidate"])
            group["status"] = "done"
            self.session["group_index"] += 1

        self.save_session()
        self.show_current_pair()
        self.after(120, lambda: setattr(self, "decision_in_progress", False))

    def resolve_unique(self, action):
        if self.decision_in_progress:
            return
        group = self.current_group()
        if not group or group.get("type") != "unique":
            return
        self.decision_in_progress = True
        self.snapshot()
        target = group.get("unique_target") or group.get("candidate")
        rejected = set(self.session.get("global_rejected", []))
        reviewed = set(self.session.get("reviewed_files", []))
        if action == "keep":
            rejected.discard(target)
            reviewed.add(target)
            group["status"] = "done"
        elif action == "reject":
            rejected.add(target)
            reviewed.add(target)
            group["status"] = "done"
        elif action == "defer":
            # Replace la photo à la fin des décisions restantes sans la compter.
            groups = self.session.get("groups", [])
            idx = self.session.get("group_index", 0)
            groups.append(groups.pop(idx))
        self.session["global_rejected"] = sorted(rejected, key=natural_path_key)
        self.session["reviewed_files"] = sorted(reviewed, key=natural_path_key)
        if action != "defer":
            self.session["group_index"] += 1
        self.save_session()
        self.show_current_pair()
        self.after(120, lambda: setattr(self, "decision_in_progress", False))

    def keep_unique(self): self.resolve_unique("keep")
    def reject_unique(self): self.resolve_unique("reject")
    def defer_unique(self): self.resolve_unique("defer")

    def keep_left(self): self.resolve_pair("left")
    def keep_right(self): self.resolve_pair("right")
    def keep_both(self): self.resolve_pair("both")

    def undo(self):
        if not self.history:
            messagebox.showinfo("Annulation", "Aucun choix récent à annuler.")
            return
        self.session = json.loads(self.history.pop())
        self.save_session()
        self.show_current_pair()

    def save_session(self, force=False):
        if not self.session:
            return
        if not force and not self.settings.get("auto_save", True):
            return

        self.session["updated_at"] = datetime.now().isoformat()
        output_text = self.session.get("output_dir", "")
        if output_text:
            output = Path(output_text)
            output.mkdir(parents=True, exist_ok=True)
            primary = output / "working_session.json"
        else:
            primary = self.config_dir / "working_session.json"

        self.session_path = primary
        payload = json.dumps(self.session, ensure_ascii=False, indent=2)

        targets = [
            primary,
            self.config_dir / "working_session.json",
            self.last_session_path,
        ]
        written = set()
        for target in targets:
            try:
                key = str(Path(target).resolve())
                if key in written:
                    continue
                atomic_write_text(target, payload)
                written.add(key)
            except Exception:
                if Path(target) == primary:
                    raise

        if output_text:
            note = (
                "TRIPHOTOS — REPRENDRE CE TRI\n\n"
                "Le travail est sauvegardé automatiquement dans working_session.json.\n"
                "Pour reprendre : lance TriPhotos, puis utilise ‘Dernière session’ ou "
                "‘Ouvrir un tri en cours’ et choisis ce dossier.\n\n"
                "Les photos originales ne sont jamais modifiées.\n"
            )
            try:
                atomic_write_text(Path(output_text) / "REPRENDRE_LE_TRI.txt", note)
            except Exception:
                pass

    def on_close(self):
        if self.closing:
            return
        if self.export_in_progress:
            self.close_after_export = True
            messagebox.showinfo(
                "Enregistrement en cours",
                "Le dossier final est en cours d’enregistrement. La fenêtre se fermera une fois cette opération terminée."
            )
            return
        self.closing = True
        try:
            self.save_session(force=True)
        finally:
            self.destroy()

    def finish_review(self):
        if self.session.get("complete") or self.export_in_progress:
            return

        self.session["review_complete"] = True
        self.session["complete"] = False
        self.update_progress_display()
        self.save_session(force=True)

        options = {"title": "Choisir où enregistrer le tri terminé"}
        previous = self.session.get("output_dir", "") or self.settings.get("default_output_dir", "")
        if previous and Path(previous).exists():
            options["initialdir"] = previous
        output_text = filedialog.askdirectory(**options)
        if not output_text:
            messagebox.showinfo(
                "Travail conservé",
                "Le tri est terminé et sauvegardé. Tu pourras choisir le dossier final en reprenant cette session."
            )
            return

        try:
            destination = self.validate_output_directory(output_text)
        except Exception as exc:
            messagebox.showerror("Dossier impossible", str(exc))
            return

        self.session["output_dir"] = str(destination)
        self.settings["default_output_dir"] = str(destination)
        self.save_settings()
        self.save_session(force=True)
        self.export_results(destination)

    def export_results(self, destination):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        self.session["output_dir"] = str(destination)
        self.session["review_complete"] = True
        self.session["complete"] = False
        self.session_path = destination / "working_session.json"
        self.settings["default_output_dir"] = str(destination)
        self.save_settings()
        self.save_session(force=True)
        self.export_in_progress = True
        progress = ProgressDialog(self, "Enregistrement du travail")
        threading.Thread(
            target=self.export_worker,
            args=(destination, progress),
            daemon=False
        ).start()

    def export_worker(self, destination, progress):
        out = Path(destination)
        try:
            out.mkdir(parents=True, exist_ok=True)
            keep_dir = out / "A_GARDER"
            reject_dir = out / "B_ECARTEES"

            # Toutes les photos analysées sont conservées par défaut. Seules les
            # décisions explicites d'écarter une photo la placent dans B_ECARTEES.
            all_files = set(self.session.get("all_files", []))
            if not all_files:
                all_files.update(self.session.get("unique_keep", []))
                for group in self.session.get("groups", []):
                    all_files.update(group.get("items", []))
                all_files.update(
                    item.get("path") for item in self.session.get("skipped", [])
                    if item.get("path")
                )

            rejected = set(self.session.get("global_rejected", [])) & all_files
            keep = all_files - rejected

            manifest_path = out / "tri_photos_manifest.json"
            try:
                previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                previous_manifest = {}

            for relative_name in previous_manifest.get("managed_files", []):
                try:
                    target = out / relative_name
                    if is_relative_to(target, out) and target.is_file():
                        target.unlink()
                except Exception:
                    pass

            for managed_dir in (keep_dir, reject_dir):
                if managed_dir.exists():
                    for folder in sorted(
                        (p for p in managed_dir.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts),
                        reverse=True
                    ):
                        try:
                            folder.rmdir()
                        except OSError:
                            pass

            total = len(keep) + len(rejected)
            progress.update_progress(
                "Copie des photos retenues et écartées…",
                0,
                max(1, total)
            )

            source_root = Path(self.session["source_dir"])
            managed_files = []
            missing = []
            i = 0

            for path_text, target_root in [
                *[(p, keep_dir) for p in sorted(keep)],
                *[(p, reject_dir) for p in sorted(rejected)],
            ]:
                source = Path(path_text)
                if source.exists():
                    target = copy_result_file(source, target_root, source_root)
                    managed_files.append(target.relative_to(out).as_posix())
                else:
                    missing.append(str(source))
                i += 1
                progress.update_progress(value=i)

            self.session["review_complete"] = True
            self.session["complete"] = True
            self.session.pop("export_error", None)
            self.session["exported_at"] = datetime.now().isoformat()
            self.session["output_dir"] = str(out)
            self.save_session(force=True)
            payload = json.dumps(self.session, ensure_ascii=False, indent=2)
            atomic_write_text(out / "session_complete.json", payload)

            csv_temp = out / "decisions.csv.tmp"
            with open(csv_temp, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(["décision", "fichier_original"])
                for p in sorted(keep):
                    writer.writerow(["GARDER", p])
                for p in sorted(rejected):
                    writer.writerow(["ECARTER_ORIGINAL_CONSERVE", p])
                for p in missing:
                    writer.writerow(["FICHIER_INTROUVABLE", p])
            os.replace(csv_temp, out / "decisions.csv")

            report = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Rapport TriPhotos</title>
            <style>body{{font-family:Segoe UI,sans-serif;max-width:900px;margin:40px auto;background:#f4f6f8;color:#18202b}}
            .card{{background:white;padding:24px;border-radius:16px;margin:14px 0;box-shadow:0 5px 20px #0001}}
            b{{font-size:28px}}</style></head><body>
            <h1>Rapport TriPhotos</h1>
            <div class="card"><b>{len(keep)}</b><br>photos à garder</div>
            <div class="card"><b>{len(rejected)}</b><br>photos écartées, originaux conservés</div>
            <div class="card"><b>{self.session['total_files']}</b><br>fichiers dans le dossier source</div>
            <div class="card"><b>{len(set(self.session.get("reviewed_files", [])))}</b><br>photos réellement présentées à l’écran</div>
            <div class="card"><b>{len(missing)}</b><br>fichiers introuvables pendant la copie</div>
            <p>Dossier source : {self.session['source_dir']}</p>
            <p>Dossier enregistré : {out}</p>
            <p>Date : {datetime.now().strftime('%d/%m/%Y %H:%M')}</p></body></html>"""
            atomic_write_text(out / "rapport.html", report)

            manifest = {
                "version": "14.21",
                "created_at": datetime.now().isoformat(),
                "managed_files": managed_files,
                "keep_count": len(keep),
                "rejected_count": len(rejected),
                "missing": missing,
            }
            atomic_write_text(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            atomic_write_text(
                out / "TRI_TERMINE.txt",
                "Tri terminé. Les résultats complets sont dans A_GARDER et B_ECARTEES.\n"
                "Les originaux sont restés intacts.\n"
            )

            self.call_on_ui(progress.destroy)
            self.call_on_ui(lambda target=out: messagebox.showinfo(
                "Enregistrement terminé",
                f"Le travail complet a été enregistré directement dans :\n\n{target}\n\n"
                "Les originaux sont intacts."
            ))
            if self.settings.get("open_results_after_export", True):
                self.call_on_ui(lambda target=out: open_folder(target))
        except Exception as exc:
            message = str(exc)
            self.session["complete"] = False
            self.session["export_error"] = message
            try:
                self.save_session(force=True)
            except Exception:
                pass
            self.call_on_ui(progress.destroy)
            self.call_on_ui(lambda msg=message: messagebox.showerror(
                "Enregistrement impossible",
                "Le tri reste sauvegardé et pourra être repris.\n\n" + msg
            ))
        finally:
            self.export_in_progress = False
            if self.close_after_export:
                self.call_on_ui(self.on_close)

    def validate_output_directory(self, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        if self.source_dir and output.resolve() == self.source_dir.resolve():
            raise ValueError(
                "Le dossier de sauvegarde doit être différent du dossier contenant les photos."
            )
        probe = output / f".triphotos_write_test_{os.getpid()}.tmp"
        try:
            probe.write_text("test", encoding="utf-8")
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
        return output

    def change_output_directory(self):
        if self.export_in_progress:
            messagebox.showinfo(
                "Enregistrement en cours",
                "Le dossier de sauvegarde ne peut pas être changé pendant la copie finale."
            )
            return

        current = self.current_output_directory()
        options = {"title": "Changer le dossier de sauvegarde du travail"}
        if current and Path(current).exists():
            options["initialdir"] = current
        selected = filedialog.askdirectory(**options)
        if not selected:
            return

        try:
            new_output = self.validate_output_directory(selected)
        except Exception as exc:
            messagebox.showerror(
                "Dossier de sauvegarde impossible",
                f"Ce dossier ne peut pas être utilisé.\n\n{exc}"
            )
            return

        old_text = self.current_output_directory()
        old_output = Path(old_text) if old_text else None
        try:
            same_location = bool(
                old_output and old_output.resolve() == new_output.resolve()
            )
        except OSError:
            same_location = False

        if same_location:
            self.settings["default_output_dir"] = str(new_output)
            self.save_settings()
            messagebox.showinfo(
                "Dossier inchangé",
                "Ce dossier est déjà utilisé pour la sauvegarde du travail."
            )
            return

        if self.session:
            previous_output = self.session.get("output_dir", "")
            previous_session_path = self.session_path
            self.session["output_dir"] = str(new_output)
            self.session_path = new_output / "working_session.json"
            try:
                self.save_session(force=True)
            except Exception as exc:
                self.session["output_dir"] = previous_output
                self.session_path = previous_session_path
                messagebox.showerror(
                    "Transfert impossible",
                    f"L’avancement n’a pas été déplacé.\n\n{exc}"
                )
                return

            if old_output and old_output != self.config_dir:
                for filename in ("working_session.json", "REPRENDRE_LE_TRI.txt"):
                    try:
                        (old_output / filename).unlink()
                    except OSError:
                        pass

        self.settings["default_output_dir"] = str(new_output)
        self.save_settings()
        for variable_name in ("output_settings_var", "output_var"):
            variable = getattr(self, variable_name, None)
            if variable is not None:
                try:
                    variable.set(str(new_output))
                except Exception:
                    pass

        if self.session and self.session.get("complete"):
            self.export_results(new_output)
        elif self.session:
            messagebox.showinfo(
                "Dossier modifié",
                "L’avancement a été transféré dans le nouveau dossier. La suite du travail et le résultat final y seront sauvegardés."
            )
        else:
            messagebox.showinfo(
                "Dossier modifié",
                "Ce dossier sera proposé automatiquement pour le prochain tri."
            )

    def show_settings(self):
        self.set_active_nav("settings")
        self.render_header_status(None)
        self.clear_body()

        canvas = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        canvas.grid(row=0, column=0, sticky="nsew", padx=18, pady=(12, 8))
        canvas.grid_columnconfigure((0, 1, 2), weight=1, uniform="settings_columns")
        canvas.grid_rowconfigure((0, 1), weight=1, uniform="settings_rows")
        self.settings_widgets = {}

        card = self.settings_card(canvas, 0, 0, "Sauvegarde")
        self.add_switch(card, "Sauvegarde automatique de l'avancement", "auto_save")
        self.add_switch(card, "Ouvrir le dossier après l'enregistrement final", "open_results_after_export")
        save_description = ctk.CTkLabel(
            card,
            text="Le dossier final est demandé uniquement lorsque toutes les comparaisons sont terminées.",
            text_color=C["muted"], font=ctk.CTkFont(size=13),
            wraplength=470, justify="left", anchor="w"
        )
        save_description.pack(fill="x", padx=18, pady=(8, 20))
        self._fit_settings_text_to_card(card, save_description)

        card = self.settings_card(canvas, 0, 1, "Analyse et détection")
        ctk.CTkLabel(card, text="Sensibilité de regroupement").pack(anchor="w", padx=18, pady=(5, 8))
        mode = ctk.CTkSegmentedButton(
            card, values=["Prudent", "Équilibré", "Agressif"],
            command=lambda v: self.set_setting("sensitivity", v)
        )
        mode.set(self.settings["sensitivity"])
        mode.pack(fill="x", padx=18)
        ctk.CTkLabel(card, text="Formats analysés", text_color=C["muted"]).pack(anchor="w", padx=18, pady=(8, 4))
        fmt = ctk.CTkFrame(card, fg_color="transparent")
        fmt.pack(fill="x", padx=14, pady=(0, 16))
        for name in ["JPG", "PNG", "HEIC", "TIFF", "WEBP"]:
            var = ctk.BooleanVar(value=self.settings["formats"].get(name, True))
            ctk.CTkCheckBox(
                fmt, text=name, variable=var,
                width=72, checkbox_width=22, checkbox_height=22,
                font=ctk.CTkFont(size=12),
                command=lambda n=name, v=var: self.set_format(n, v.get())
            ).pack(side="left", fill="x", expand=True, padx=2)

        card = self.settings_card(canvas, 0, 2, "Raccourcis")
        shortcuts = [
            ("←", "Garder la gauche", C["red"], "white"),
            ("→", "Garder la droite", C["green"], "white"),
            ("↑", "Garder les deux", C["blue2"], "white"),
            ("Suppr", "Supprimer les deux", "#7C3AED", "white"),
            ("Ctrl+Z", "Annuler le dernier choix", C["soft"], C["text"]),
        ]
        for index, (key, desc, color, text_color) in enumerate(shortcuts):
            row = ctk.CTkFrame(
                card, width=284, height=40,
                fg_color=color, corner_radius=12,
            )
            row.pack(
                padx=28,
                pady=(4, 14 if index == len(shortcuts) - 1 else 4),
            )
            row.pack_propagate(False)
            ctk.CTkLabel(
                row, text=key, width=62, height=26,
                fg_color="white", corner_radius=6,
                font=ctk.CTkFont(weight="bold"), text_color=C["text"],
            ).pack(side="left", padx=(8, 9), pady=7)
            ctk.CTkLabel(
                row, text=desc, anchor="center", justify="center",
                font=ctk.CTkFont(size=13, weight="bold"), text_color=text_color,
            ).pack(side="left", fill="x", expand=True, padx=(0, 9), pady=7)

        card = self.settings_card(canvas, 1, 0, "Affichage")
        ctk.CTkLabel(card, text="Taille de l'interface").pack(anchor="w", padx=18, pady=(8, 6))
        ui_scale_values = ["Automatique", "75 %", "90 %", "100 %", "110 %", "125 %", "150 %"]
        ui_scale_menu = ctk.CTkOptionMenu(
            card, values=ui_scale_values,
            command=self.set_ui_scale,
        )
        current_ui_scale = self.settings.get("ui_scale", "Automatique")
        ui_scale_menu.set(current_ui_scale if current_ui_scale in ui_scale_values else "Automatique")
        ui_scale_menu.pack(fill="x", padx=18, pady=(0, 6))
        automatic_description = ctk.CTkLabel(
            card,
            text="Automatique conserve le ratio du modèle et remplit la fenêtre. Les pourcentages fixent une taille maximale, réduite si nécessaire.",
            text_color=C["muted"], font=ctk.CTkFont(size=13),
            wraplength=470, justify="left", anchor="w",
        )
        automatic_description.pack(fill="x", padx=18, pady=(0, 10))
        self._fit_settings_text_to_card(card, automatic_description)
        self.add_switch(card, "Afficher les métadonnées", "show_metadata")
        self.add_switch(card, "Afficher l'avancement du dossier", "show_folder_progress")
        self.add_switch(card, "Afficher la grille de composition 3 × 3", "show_composition_grid")
        self.add_switch(card, "Photos en largeur maximale", "max_photo_width")

        card = self.settings_card(canvas, 1, 1, "Performance")
        ctk.CTkLabel(card, text="Qualité d'aperçu").pack(anchor="w", padx=18, pady=(8, 6))
        quality = ctk.CTkOptionMenu(
            card, values=["Standard", "Haute", "Maximale"],
            command=lambda v: self.set_setting("preview_quality", v)
        )
        quality.set(self.settings["preview_quality"])
        quality.pack(fill="x", padx=18, pady=(0, 12))
        self.add_switch(card, "Précharger la paire suivante", "preload_pairs")
        self.add_switch(card, "Utiliser l'accélération graphique si disponible", "gpu")

        card = self.settings_card(canvas, 1, 2, "Comportement")
        facts = [
            "Les photos sans doublon ou série proche sont conservées automatiquement.",
            "Deux photos sans rapport ne sont jamais présentées ensemble.",
            "La touche Suppr écarte les deux photos de la comparaison en cours.",
            "Les fichiers originaux ne sont jamais supprimés ni déplacés.",
        ]
        for index, fact in enumerate(facts):
            fact_label = ctk.CTkLabel(
                card, text=f"•  {fact}", text_color=C["muted"],
                font=ctk.CTkFont(size=14),
                anchor="w", wraplength=470, justify="left"
            )
            fact_label.pack(fill="x", padx=18, pady=(4 if index == 0 else 0, 0))
            self._fit_settings_text_to_card(card, fact_label)

    def _fit_settings_text_to_card(self, card, label, horizontal_padding=18):
        """Utilise toute la largeur réelle d'une carte, à toute échelle."""
        def update_wrap(event=None):
            try:
                if not card.winfo_exists() or not label.winfo_exists():
                    return
                physical_width = int(getattr(event, "width", 0) or card.winfo_width())
                widget_scale = max(0.1, float(label._get_widget_scaling()))
                logical_width = physical_width / widget_scale
                label.configure(
                    wraplength=max(180, int(logical_width - 2 * horizontal_padding - 4))
                )
            except Exception:
                pass

        card.bind("<Configure>", update_wrap, add="+")
        self.after_idle(update_wrap)

    def settings_card(self, parent, row, column, title, columnspan=1):
        card = self.card(parent)
        card.grid(
            row=row, column=column, columnspan=columnspan,
            sticky="nsew", padx=8, pady=8,
        )
        title_bar = ctk.CTkFrame(card, fg_color="#EEF4FF", corner_radius=9)
        title_bar.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(
            title_bar, text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#183765", anchor="center", justify="center",
        ).pack(fill="x", padx=14, pady=6)
        return card

    def add_switch(self, parent, text, key):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=5)
        ctk.CTkLabel(row, text=text, anchor="w", wraplength=390, justify="left").pack(side="left", fill="x", expand=True)
        var = ctk.BooleanVar(value=bool(self.settings.get(key)))
        ctk.CTkSwitch(row, text="", variable=var, command=lambda: self.set_setting(key, var.get())).pack(side="right")

    def set_setting(self, key, value):
        self.settings[key] = value
        self.save_settings()
        if key == "show_composition_grid" and self.current_page == "review":
            self.show_current_pair()

    def set_ui_scale(self, value):
        self.settings["ui_scale"] = value
        self.save_settings()
        self._schedule_responsive_layout(force=True)

    def set_format(self, name, value):
        self.settings["formats"][name] = value
        self.save_settings()

    def save_settings(self):
        atomic_write_text(
            self.settings_path,
            json.dumps(self.settings, ensure_ascii=False, indent=2)
        )

    def show_about(self):
        self.set_active_nav("about")
        self.clear_body()
        card = self.card(self.body)
        card.grid(row=0, column=0, sticky="nsew", padx=220, pady=100)
        ctk.CTkLabel(card, text="Tri de photos — 14.17", font=ctk.CTkFont(size=32, weight="bold")).pack(pady=(60, 8))
        ctk.CTkLabel(card, text="Tri local et validation visuelle de séries photographiques.", text_color=C["muted"]).pack()
        ctk.CTkLabel(
            card,
            text="Le logiciel ne modifie jamais les fichiers originaux. Les résultats sont créés sous forme de copies dans le dossier choisi à la fin du tri.",
            wraplength=650, justify="center", text_color=C["muted"]
        ).pack(padx=50, pady=28)
        ctk.CTkLabel(card, text="Raccourcis : ← garder gauche · → garder droite · ↑ garder les deux · Suppr écarter les deux · Ctrl+Z annuler", text_color=C["blue2"]).pack(pady=(0, 60))

if __name__ == "__main__":
    TriPhotosApp().mainloop()
