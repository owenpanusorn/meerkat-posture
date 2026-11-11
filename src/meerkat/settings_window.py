"""Settings window: ``meerkat --settings`` (tray menu "ตั้งค่า...").

Runs as its own process (Tk), so it never shares a Tk interpreter with the buddy and
cannot freeze the tray. It edits ``config.toml``; the running app notices the file
changed and applies it within a few seconds.

Only the fields shown here are written. On save the file is re-read and these values
are put on top, so calibration zones or menu choices made meanwhile are kept.

``FIELDS``, ``values_from``, ``apply`` and ``save_values`` are pure / file-only and tested
without a display.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meerkat import config
from meerkat.storage import RULE_LABELS

log = logging.getLogger(__name__)

TITLE = "ตั้งค่า Meerkat"
MUTEX_NAME = "Local\\MeerkatSettingsWindow"


def _same(v: Any) -> Any:
    return v


@dataclass(frozen=True)
class Field:
    path: str  # "sitting.break_after_min", "rules.head_down.threshold", ...
    label: str
    kind: str = "int"  # int | float | bool | choice
    lo: float = 0
    hi: float = 0
    unit: str = ""
    to_ui: Callable[[Any], Any] = _same
    from_ui: Callable[[Any], Any] = _same
    choices: tuple[tuple[str, str], ...] = ()  # (value, label) for kind="choice"
    hint: str = ""


def _min_from_s(v: float) -> float:
    return v / 60


def _s_from_min(v: float) -> float:
    return v * 60


def _pct_above(t: float) -> float:  # lean_in 1.15 -> 15 %
    return (t - 1) * 100


def _ratio_above(p: float) -> float:
    return 1 + p / 100


def _pct_below(t: float) -> float:  # twist / slouch 0.85 -> 15 %
    return (1 - t) * 100


def _ratio_below(p: float) -> float:
    return 1 - p / 100


# rule -> (threshold unit, lo, hi, to_ui, from_ui)
_RULE_UI: dict[str, tuple[str, float, float, Callable, Callable]] = {
    "head_down": ("องศา", 3, 45, _same, _same),
    "head_up": ("องศา", 3, 45, _same, _same),
    "yaw_out": ("องศา", 5, 60, _same, _same),
    "roll": ("องศา", 3, 45, _same, _same),
    "lean_in": ("% หน้าใหญ่ขึ้น", 5, 60, _pct_above, _ratio_above),
    "shoulder_tilt": ("องศา", 2, 30, _same, _same),
    "twist": ("% ไหล่แคบลง", 5, 50, _pct_below, _ratio_below),
    "slouch": ("% คอสั้นลง", 5, 50, _pct_below, _ratio_below),
}
RULE_NAMES = tuple(_RULE_UI)


def _rule_fields() -> list[Field]:
    out = []
    for name, (unit, lo, hi, to_ui, from_ui) in _RULE_UI.items():
        label = RULE_LABELS.get(name, name)
        out += [
            Field(f"rules.{name}.enabled", label, "bool"),
            Field(f"rules.{name}.threshold", label, "int", lo, hi, unit, to_ui, from_ui),
            Field(f"rules.{name}.hold_s", label, "int", 5, 600, "วินาที"),
        ]
    return out


PAGES: list[tuple[str, list[Field]]] = [
    (
        "เตือนลุก",
        [
            Field("sitting.break_after_min", "เตือนเมื่อนั่งครบ", "int", 5, 180, "นาที"),
            Field("sitting.repeat_min", "ถ้ายังไม่ลุก เตือนซ้ำทุก", "int", 1, 60, "นาที"),
            Field("sitting.snooze_min", "ปุ่มเลื่อนเตือน เลื่อนครั้งละ", "int", 1, 60, "นาที"),
            Field(
                "sitting.away_s",
                "ลุกไปนานเท่าไหร่ถึงนับว่าได้พัก",
                "int",
                10,
                900,
                "วินาที",
            ),
        ],
    ),
    (
        "เมียร์แคท",
        [
            Field("buddy.enabled", "ให้เมียร์แคทโผล่มาเตือนลุก", "bool"),
            Field("buddy.escalate_after_min", "ถ้ายังไม่ลุก เริ่มกระโดดหลัง", "int", 1, 60, "นาที"),
            Field("buddy.center", "เดินมากลางจอถ้ายังไม่ลุกอีก", "bool"),
            Field("buddy.center_after_min", "เดินมากลางจอหลัง", "int", 1, 120, "นาที"),
        ],
    ),
    (
        "แจ้งเตือน",
        [
            Field("alerts.notifications", "แสดงการแจ้งเตือน", "bool"),
            Field("alerts.sticky", "ค้างไว้จนกว่าจะกดปิด", "bool"),
            Field("alerts.sound_posture", "มีเสียงตอนเตือนท่านั่ง", "bool"),
            Field("alerts.sound_break", "มีเสียงตอนเตือนลุก", "bool"),
            Field(
                "alerts.sound_style",
                "เสียง",
                "choice",
                choices=(("meerkat", "เสียงเมียร์แคท"), ("system", "เสียงของระบบ")),
            ),
            Field(
                "alerts.rule_cooldown_s",
                "เตือนท่าเดิมซ้ำได้ไม่ถี่กว่าทุก",
                "int",
                1,
                60,
                "นาที",
                _min_from_s,
                _s_from_min,
            ),
            Field(
                "alerts.phone_pitch_deg",
                "นับว่าก้มเล่นโทรศัพท์เมื่อก้มเกิน",
                "int",
                10,
                60,
                "องศา",
            ),
        ],
    ),
    ("ท่านั่ง", _rule_fields()),
    (
        "กล้องและข้อมูล",
        [
            Field(
                "camera.fps",
                "ความถี่ภาพจากกล้อง",
                "int",
                1,
                15,
                "ภาพ/วินาที",
                hint="น้อย = กินเครื่องน้อยลง",
            ),
            Field("storage.enabled", "เก็บสถิติ (ตัวเลขเท่านั้น ไม่มีภาพ)", "bool"),
            Field("storage.record_sessions", "บันทึก session สำหรับปรับเกณฑ์", "bool"),
        ],
    ),
]
FIELDS: list[Field] = [f for _, fields in PAGES for f in fields]


# ------------------------------------------------------------------ model


def _get(cfg: config.Config, path: str) -> Any:
    parts = path.split(".")
    if parts[0] == "rules":
        return getattr(cfg.rules[parts[1]], parts[2])
    return getattr(getattr(cfg, parts[0]), parts[1])


def _set(cfg: config.Config, path: str, value: Any) -> None:
    parts = path.split(".")
    if parts[0] == "rules":
        setattr(cfg.rules[parts[1]], parts[2], value)
    else:
        setattr(getattr(cfg, parts[0]), parts[1], value)


def to_ui_value(f: Field, raw: Any) -> Any:
    if f.kind in ("bool", "choice"):
        return raw
    v = f.to_ui(raw)
    return round(v) if f.kind == "int" else round(v, 2)


def values_from(cfg: config.Config) -> dict[str, Any]:
    """Config -> what the window shows (minutes, percent, ...)."""
    return {f.path: to_ui_value(f, _get(cfg, f.path)) for f in FIELDS}


def parse(f: Field, text: Any) -> Any:
    """UI value -> clamped UI value. Raises ValueError for text that isn't a number."""
    if f.kind == "bool":
        return bool(text)
    if f.kind == "choice":
        allowed = [c for c, _ in f.choices]
        return text if text in allowed else allowed[0]
    v = float(str(text).strip().replace(",", "."))
    v = min(max(v, f.lo), f.hi)
    return round(v) if f.kind == "int" else v


def apply(cfg: config.Config, values: dict[str, Any]) -> config.Config:
    """Put UI values into ``cfg`` (in place) and return it."""
    for f in FIELDS:
        if f.path not in values:
            continue
        v = parse(f, values[f.path])
        if f.kind not in ("bool", "choice"):
            current = _get(cfg, f.path)
            v = f.from_ui(v)
            v = round(v, 4) if isinstance(current, float) else round(v)
            if isinstance(current, float):
                v = float(v)
        _set(cfg, f.path, v)
    s = cfg.sitting
    minutes = round(s.break_after_min)
    if minutes not in s.break_after_options_min:  # keep the tray's radio menu in sync
        s.break_after_options_min = sorted({*s.break_after_options_min, minutes})
    return cfg


def save_values(values: dict[str, Any], path: Path | None = None) -> Path:
    """Re-read the file (keeps zones etc. changed meanwhile), apply, save."""
    cfg = config.load(path)
    return config.save(apply(cfg, values), path)


def defaults() -> dict[str, Any]:
    return values_from(config.Config())


# ------------------------------------------------------------------ window


def run(config_path: Path | None = None) -> int:
    from meerkat import autostart

    if not autostart.acquire_single_instance(MUTEX_NAME):
        _focus_existing()
        return 0
    _dpi_aware()
    import tkinter as tk

    _Window(tk, config_path).root.mainloop()
    return 0


class _Window:
    PAD = 10

    def __init__(self, tk, config_path: Path | None) -> None:
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.config_path = config_path
        self.root = root = tk.Tk()
        root.title(TITLE)
        root.resizable(False, False)
        self._set_icon()
        font = ("Leelawadee UI", 10) if sys.platform == "win32" else None
        if font:
            root.option_add("*Font", font)
            style = ttk.Style(root)
            for name in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TNotebook.Tab"):
                style.configure(name, font=font)
            style.configure("TNotebook.Tab", padding=(12, 5))
            style.configure("Hint.TLabel", foreground="#6b5a48", font=(font[0], 9))
            style.configure("Head.TLabel", font=(font[0], 10, "bold"))

        self.vars: dict[str, Any] = {}
        self.widgets: dict[str, Any] = {}
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=self.PAD, pady=(self.PAD, 0))
        for title, fields in PAGES:
            page = ttk.Frame(nb, padding=self.PAD)
            nb.add(page, text=title)
            if title == "ท่านั่ง":
                self._rules_page(page)
            else:
                self._form_page(page, fields)

        bar = ttk.Frame(root, padding=self.PAD)
        bar.pack(fill="x")
        ttk.Button(bar, text="ค่าเริ่มต้น", command=self._defaults).pack(side="left")
        ttk.Button(bar, text="บันทึก", command=self._save).pack(side="right")
        ttk.Button(bar, text="ยกเลิก", command=root.destroy).pack(side="right", padx=(0, 6))
        self.status = ttk.Label(bar, text="", style="Hint.TLabel")
        self.status.pack(side="left", padx=self.PAD)
        root.bind("<Escape>", lambda e: root.destroy())

        self._fill(values_from(config.load(config_path)))
        self._update_enabled()
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        x = (root.winfo_screenwidth() - w) // 2
        y = (root.winfo_screenheight() - h) // 3
        root.geometry(f"+{x}+{y}")
        root.lift()
        root.focus_force()

    # ---- building

    def _var(self, f: Field):
        tk = self.tk
        if f.kind == "bool":
            v = tk.BooleanVar(self.root)
        elif f.kind == "choice":
            v = tk.StringVar(self.root)
        else:
            v = tk.StringVar(self.root)
        self.vars[f.path] = v
        return v

    def _spin(self, parent, f: Field):
        w = self.ttk.Spinbox(
            parent, from_=f.lo, to=f.hi, increment=1, width=6, textvariable=self._var(f)
        )
        self.widgets[f.path] = w
        return w

    def _form_page(self, page, fields: list[Field]) -> None:
        ttk = self.ttk
        for row, f in enumerate(fields):
            if f.kind == "bool":
                w = ttk.Checkbutton(
                    page, text=f.label, variable=self._var(f), command=self._update_enabled
                )
                w.grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
                self.widgets[f.path] = w
                continue
            ttk.Label(page, text=f.label).grid(row=row, column=0, sticky="w", pady=3)
            if f.kind == "choice":
                box = ttk.Frame(page)
                box.grid(row=row, column=1, columnspan=2, sticky="w")
                var = self._var(f)
                for value, text in f.choices:
                    ttk.Radiobutton(box, text=text, value=value, variable=var).pack(
                        side="left", padx=(0, 10)
                    )
                continue
            self._spin(page, f).grid(row=row, column=1, sticky="w", padx=8)
            unit = f.unit + (f"  ({f.hint})" if f.hint else "")
            ttk.Label(page, text=unit).grid(row=row, column=2, sticky="w")

    def _rules_page(self, page) -> None:
        ttk = self.ttk
        heads = ("ท่า", "เตือน", "เตือนเมื่อเกิน", "", "ค้างนาน")
        for col, text in enumerate(heads):
            ttk.Label(page, text=text, style="Head.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 8), pady=(0, 4)
            )
        by_path = {f.path: f for f in FIELDS}
        for row, name in enumerate(RULE_NAMES, start=1):
            en = by_path[f"rules.{name}.enabled"]
            th = by_path[f"rules.{name}.threshold"]
            hold = by_path[f"rules.{name}.hold_s"]
            ttk.Label(page, text=en.label).grid(row=row, column=0, sticky="w", padx=(0, 8))
            cb = ttk.Checkbutton(page, variable=self._var(en), command=self._update_enabled)
            cb.grid(row=row, column=1)
            self._spin(page, th).grid(row=row, column=2, sticky="w", pady=2)
            ttk.Label(page, text=th.unit).grid(row=row, column=3, sticky="w", padx=(4, 12))
            box = ttk.Frame(page)
            box.grid(row=row, column=4, sticky="w")
            self._spin(box, hold).pack(side="left")
            ttk.Label(box, text=" วินาที").pack(side="left")
        ttk.Label(
            page,
            text="ตัวเลขน้อย = เตือนง่ายขึ้น · ค้างนาน = อยู่ในท่านั้นนานเท่าไหร่ถึงเตือน",
            style="Hint.TLabel",
        ).grid(row=len(RULE_NAMES) + 1, column=0, columnspan=5, sticky="w", pady=(10, 0))

    def _set_icon(self) -> None:
        try:
            from PIL import ImageTk

            from meerkat.tray import load_icon

            self._icon = ImageTk.PhotoImage(load_icon("green").resize((32, 32)), master=self.root)
            self.root.iconphoto(True, self._icon)
        except Exception:
            log.debug("no window icon", exc_info=True)

    # ---- values

    def _fill(self, values: dict[str, Any]) -> None:
        for path, v in values.items():
            self.vars[path].set(v)

    def _collect(self) -> dict[str, Any] | None:
        by_path = {f.path: f for f in FIELDS}
        out = {}
        for path, var in self.vars.items():
            f = by_path[path]
            try:
                out[path] = parse(f, var.get())
            except ValueError:
                self.status.configure(text=f"ใส่ตัวเลข: {f.label}", foreground="#b03030")
                w = self.widgets.get(path)
                if w is not None:
                    w.focus_set()
                return None
        return out

    def _update_enabled(self) -> None:
        """Grey out fields that do nothing because their switch is off."""

        def link(switch: str, *paths: str) -> None:
            on = bool(self.vars[switch].get())
            for p in paths:
                w = self.widgets.get(p)
                if w is not None:
                    w.state(["!disabled"] if on else ["disabled"])

        link("buddy.enabled", "buddy.escalate_after_min", "buddy.center", "buddy.center_after_min")
        if self.vars["buddy.enabled"].get():
            link("buddy.center", "buddy.center_after_min")
        for name in RULE_NAMES:
            link(f"rules.{name}.enabled", f"rules.{name}.threshold", f"rules.{name}.hold_s")

    def _defaults(self) -> None:
        self._fill(defaults())
        self._update_enabled()
        self.status.configure(text="ใส่ค่าเริ่มต้นแล้ว กดบันทึกเพื่อใช้", foreground="#6b5a48")

    def _save(self) -> None:
        values = self._collect()
        if values is None:
            return
        try:
            save_values(values, self.config_path)
        except Exception as e:
            log.exception("cannot save settings")
            self.status.configure(text=f"บันทึกไม่ได้: {e}", foreground="#b03030")
            return
        self._fill({p: v for p, v in values.items()})
        self.status.configure(text="บันทึกแล้ว ใช้ค่าใหม่ในไม่กี่วินาที", foreground="#2e7d32")
        self.root.after(900, self.root.destroy)


def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _focus_existing() -> None:
    """Another settings window is open: bring it to the front."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, TITLE)
        if hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
