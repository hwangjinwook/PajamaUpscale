"""파자마업스케일(PajamaUpscale) — 이미지를 AI 로 2·3·4배 고화질 확대.

화면은 tkinter. 확대는 별도 스레드에서 upscale_core 가 하고, 그 스레드는 tk 를 절대 부르지 않는다
— 할 일은 큐에 넣고 _poll() 이 화면에 옮긴다. 끌어 놓기(tkinterdnd2)도 콜백에서 큐에만 넣는다.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import upscale_core as core  # noqa: E402

from PIL import Image, ImageTk  # noqa: E402

try:  # 끌어 놓기 — 없으면 단추로만 추가
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # noqa: BLE001
    DND_FILES = None
    TkinterDnD = None

APP_TITLE = core.APP_NAME
APP_ID = "PajamaCompany.PajamaUpscale"
ICON_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "icon.ico"

# 파자마 공용 핑크 팔레트(파자마캘린더 기준)
PINK_TITLE = "#ff8fa3"
PINK_ACCENT = "#ff6f8a"
PINK_ACCENT_DARK = "#e85574"
PINK_LIGHT = "#ffe3e9"
PINK_SOFT = "#fff1f4"
BG = "#fdfaf5"
TEXT = "#4a3b40"
SUBTLE = "#8c7a80"
OK_GREEN = "#3a9a6a"
ERR_RED = "#d9415e"
FONT = "맑은 고딕"

STATE_TEXT = {"wait": "대기", "run": "확대 중", "done": "✅ 완료", "error": "⚠ 실패", "cancel": "멈춤"}


class Item:
    def __init__(self, path: Path):
        self.path = path
        self.size = core.image_size(path)
        self.state = "wait"
        self.result: Path | None = None
        self.error = ""
        self.iid = ""


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.s = core.load_settings()
        self.items: list[Item] = []
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.last_result: Path | None = None

        root.title(APP_TITLE)
        root.configure(bg=BG)
        root.geometry("860x640")
        root.minsize(760, 540)
        if ICON_PATH.exists():
            try:
                root.iconbitmap(default=str(ICON_PATH))
            except tk.TclError:
                pass
        self._style()
        self._build()
        self._refresh_list()
        self._update_buttons()
        ok, why = core.engine_ready()
        self.set_status("이미지를 끌어 놓거나 「＋ 이미지 추가」를 눌러 주세요." if ok else why, SUBTLE if ok else ERR_RED)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)

    # ── 모양 ──────────────────────────────────────────
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=TEXT, font=(FONT, 10))
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Sub.TLabel", foreground=SUBTLE, font=(FONT, 9))
        st.configure("Head.TLabel", font=(FONT, 10, "bold"))
        st.configure("TRadiobutton", background=BG, foreground=TEXT)
        st.map("TRadiobutton", background=[("active", BG)])
        st.configure("TCheckbutton", background=BG, foreground=TEXT)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TLabelframe", background=BG, bordercolor=PINK_TITLE)
        st.configure("TLabelframe.Label", background=BG, foreground=PINK_ACCENT_DARK, font=(FONT, 10, "bold"))
        st.configure("TEntry", fieldbackground="white", bordercolor=PINK_TITLE, lightcolor=PINK_LIGHT)
        st.configure("TButton", background=PINK_LIGHT, foreground=TEXT, bordercolor=PINK_TITLE, padding=(10, 4))
        st.map("TButton", background=[("disabled", "#f3eef0"), ("active", "#ffd0da")],
               foreground=[("disabled", "#b9a9ae")])
        st.configure("Big.TButton", background=PINK_ACCENT, foreground="white", font=(FONT, 12, "bold"),
                     padding=(18, 8), bordercolor=PINK_ACCENT_DARK)
        st.map("Big.TButton", background=[("disabled", "#f2b8c4"), ("active", PINK_ACCENT_DARK)],
               foreground=[("disabled", "white")])
        st.configure("Pink.Horizontal.TProgressbar", troughcolor=PINK_LIGHT, background=PINK_ACCENT,
                     bordercolor=PINK_LIGHT, lightcolor=PINK_ACCENT, darkcolor=PINK_ACCENT, thickness=16)
        st.configure("Treeview", background="white", fieldbackground="white", foreground=TEXT, rowheight=26,
                     bordercolor=PINK_LIGHT, font=(FONT, 10))
        st.configure("Treeview.Heading", background=PINK_LIGHT, foreground=TEXT, font=(FONT, 9, "bold"),
                     bordercolor=PINK_LIGHT)
        st.map("Treeview", background=[("selected", "#ffd0da")], foreground=[("selected", TEXT)])

    def _build(self):
        r = self.root
        head = tk.Frame(r, bg=PINK_TITLE)
        head.pack(fill="x")
        tk.Label(head, text="🔍  " + APP_TITLE, bg=PINK_TITLE, fg="white",
                 font=(FONT, 15, "bold")).pack(side="left", padx=16, pady=10)
        tk.Label(head, text="AI 로 이미지를 2·3·4배 고화질 확대", bg=PINK_TITLE, fg="white",
                 font=(FONT, 10)).pack(side="left", pady=10)

        body = ttk.Frame(r, padding=(14, 10, 14, 6))
        body.pack(fill="both", expand=True)

        # 추가 단추 줄
        bar = ttk.Frame(body)
        bar.pack(fill="x")
        self.btn_add = ttk.Button(bar, text="＋ 이미지 추가", command=self.add_files)
        self.btn_add.pack(side="left")
        self.btn_add_dir = ttk.Button(bar, text="📁 폴더 추가", command=self.add_folder)
        self.btn_add_dir.pack(side="left", padx=6)
        self.btn_remove = ttk.Button(bar, text="빼기", command=self.remove_selected)
        self.btn_remove.pack(side="left")
        self.btn_clear = ttk.Button(bar, text="목록 비우기", command=self.clear)
        self.btn_clear.pack(side="left", padx=6)
        self.count_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.count_var, style="Sub.TLabel").pack(side="right")

        # 목록
        lst = ttk.Frame(body)
        lst.pack(fill="both", expand=True, pady=(8, 8))
        cols = ("name", "size", "out", "state")
        self.tree = ttk.Treeview(lst, columns=cols, show="headings", selectmode="extended")
        for c, t, w, a in (("name", "파일", 330, "w"), ("size", "원본 크기", 110, "center"),
                           ("out", "결과 크기", 120, "center"), ("state", "상태", 150, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=(c == "name"))
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("done", foreground=OK_GREEN)
        self.tree.tag_configure("error", foreground=ERR_RED)
        self.tree.tag_configure("run", foreground=PINK_ACCENT_DARK)
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-3>", self.on_menu)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.empty = tk.Label(self.tree, text="여기에 이미지나 폴더를 끌어다 놓으세요\n(PNG · JPG · WebP · BMP · TIFF · GIF)",
                              bg="white", fg=SUBTLE, font=(FONT, 11), justify="center")
        if DND_FILES:
            for w in (self.tree, self.empty, r):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self.on_drop)
                except Exception:  # noqa: BLE001
                    pass

        # 설정
        opt = ttk.Frame(body)
        opt.pack(fill="x")
        kind = ttk.LabelFrame(opt, text=" 이미지 종류 ", padding=(10, 4))
        kind.pack(side="left", fill="y")
        self.model_var = tk.StringVar(value=self.s["model"])
        for m in core.MODELS:
            ttk.Radiobutton(kind, text=f"{m.label}", value=m.key, variable=self.model_var,
                            command=self._on_option).pack(anchor="w")
        self.model_hint = ttk.Label(kind, style="Sub.TLabel", wraplength=230)
        self.model_hint.pack(anchor="w", pady=(2, 0))

        mid = ttk.LabelFrame(opt, text=" 배율 · 형식 ", padding=(10, 4))
        mid.pack(side="left", fill="y", padx=10)
        self.scale_var = tk.IntVar(value=self.s["scale"])
        row = ttk.Frame(mid)
        row.pack(anchor="w")
        ttk.Label(row, text="배율").pack(side="left", padx=(0, 6))
        for sc in core.SCALES:
            ttk.Radiobutton(row, text=f"{sc}배", value=sc, variable=self.scale_var, command=self._on_option).pack(side="left")
        self.fmt_var = tk.StringVar(value=self.s["format"])
        row = ttk.Frame(mid)
        row.pack(anchor="w", pady=(6, 0))
        ttk.Label(row, text="형식").pack(side="left", padx=(0, 6))
        for f, t in (("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")):
            ttk.Radiobutton(row, text=t, value=f, variable=self.fmt_var, command=self._on_option).pack(side="left")
        self.cpu_var = tk.BooleanVar(value=self.s["use_cpu"])
        ttk.Checkbutton(mid, text="그래픽카드 대신 CPU 로(느림, 오류 날 때만)", variable=self.cpu_var,
                        command=self._on_option).pack(anchor="w", pady=(6, 0))

        out = ttk.LabelFrame(opt, text=" 저장 위치 ", padding=(10, 4))
        out.pack(side="left", fill="both", expand=True)
        self.out_var = tk.StringVar(value=self.s["out_mode"])
        ttk.Radiobutton(out, text="원본 옆 「업스케일」 폴더", value="beside", variable=self.out_var,
                        command=self._on_option).pack(anchor="w")
        ttk.Radiobutton(out, text="원본과 같은 폴더", value="same", variable=self.out_var,
                        command=self._on_option).pack(anchor="w")
        row = ttk.Frame(out)
        row.pack(fill="x", anchor="w")
        ttk.Radiobutton(row, text="직접 고르기", value="custom", variable=self.out_var,
                        command=self._on_option).pack(side="left")
        ttk.Button(row, text="찾아보기…", command=self.pick_out_dir).pack(side="left", padx=6)
        self.out_dir_var = tk.StringVar(value=self.s["out_dir"])
        ttk.Label(out, textvariable=self.out_dir_var, style="Sub.TLabel", wraplength=230).pack(anchor="w")

        # 진행
        run = ttk.Frame(body)
        run.pack(fill="x", pady=(10, 0))
        self.btn_go = ttk.Button(run, text="✨ 업스케일 시작", style="Big.TButton", command=self.start_or_stop)
        self.btn_go.pack(side="left")
        self.btn_open = ttk.Button(run, text="📂 결과 폴더 열기", command=self.open_result_folder)
        self.btn_open.pack(side="left", padx=8)
        right = ttk.Frame(run)
        right.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.prog = ttk.Progressbar(right, style="Pink.Horizontal.TProgressbar", maximum=100)
        self.prog.pack(fill="x")
        self.status_lbl = tk.Label(right, text="", bg=BG, fg=SUBTLE, font=(FONT, 9), anchor="w", justify="left",
                                   wraplength=480)
        self.status_lbl.pack(fill="x", pady=(4, 0))

        foot = tk.Frame(r, bg=PINK_LIGHT)
        foot.pack(fill="x", side="bottom")
        tk.Label(foot, text=f"v{core.VERSION} · AI 엔진: Real-ESRGAN(ncnn-vulkan) · 결과를 두 번 누르면 열리고, 오른쪽 클릭하면 원본과 비교할 수 있어요",
                 bg=PINK_LIGHT, fg=TEXT, font=(FONT, 9)).pack(side="left", padx=12, pady=4)
        self._on_option(save=False)

    # ── 설정 ──────────────────────────────────────────
    def _on_option(self, save: bool = True):
        m = core.MODEL_BY_KEY[self.model_var.get()]
        hint = m.hint
        if self.scale_var.get() not in m.scales:
            hint += f" · {self.scale_var.get()}배는 4배로 키운 뒤 고품질로 줄여요"
        self.model_hint.configure(text=hint)
        self.s.update(model=self.model_var.get(), scale=self.scale_var.get(), format=self.fmt_var.get(),
                      out_mode=self.out_var.get(), out_dir=self.out_dir_var.get(), use_cpu=self.cpu_var.get())
        if self.s["out_mode"] == "custom" and not self.s["out_dir"] and save:
            self.pick_out_dir()
            return
        if save:
            core.save_settings(self.s)
        self._refresh_list()

    def pick_out_dir(self):
        d = filedialog.askdirectory(title="결과를 저장할 폴더", initialdir=self.out_dir_var.get() or None)
        if d:
            self.out_dir_var.set(d)
            self.out_var.set("custom")
        elif not self.out_dir_var.get():
            self.out_var.set("beside")
        self._on_option()

    # ── 목록 ──────────────────────────────────────────
    def add_paths(self, paths):
        have = {str(i.path.resolve()).lower() for i in self.items}
        added = 0
        for p in core.collect_images(paths):
            if str(p.resolve()).lower() in have:
                continue
            self.items.append(Item(p))
            added += 1
        self._refresh_list()
        if added:
            self.set_status(f"{added}장 추가했어요. 「✨ 업스케일 시작」을 누르면 확대해요.", SUBTLE)
        elif paths:
            self.set_status("추가할 이미지가 없어요(이미 있거나 이미지가 아니에요).", ERR_RED)

    def add_files(self):
        fs = filedialog.askopenfilenames(title="확대할 이미지 고르기", filetypes=[
            ("이미지", " ".join("*" + e for e in sorted(core.IMAGE_EXTS))), ("모든 파일", "*.*")])
        if fs:
            self.add_paths(fs)

    def add_folder(self):
        d = filedialog.askdirectory(title="이미지가 든 폴더 고르기(하위 폴더 포함)")
        if d:
            self.add_paths([d])

    def on_drop(self, event):
        # 끌어 놓기 콜백 — 바로 화면을 바꾸지 않고 큐로 넘긴다(콜백 안 tk 호출로 앱이 꺼진 적이 있어서)
        try:
            paths = list(self.root.tk.splitlist(event.data))
        except Exception:  # noqa: BLE001
            paths = []
        self.q.put(("add", paths))
        return getattr(event, "action", None)

    def remove_selected(self):
        if self.busy:
            return
        sel = set(self.tree.selection())
        self.items = [i for i in self.items if i.iid not in sel]
        self._refresh_list()

    def clear(self):
        if self.busy:
            return
        self.items = []
        self._refresh_list()

    def _out_size(self, it: Item) -> str:
        if not it.size:
            return "?"
        sc = self.scale_var.get()
        return f"{it.size[0] * sc}×{it.size[1] * sc}"

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for it in self.items:
            st = STATE_TEXT[it.state]
            if it.state == "error":
                st = "⚠ " + it.error[:60]
            it.iid = self.tree.insert("", "end", values=(
                it.path.name, f"{it.size[0]}×{it.size[1]}" if it.size else "?", self._out_size(it), st),
                tags=(it.state,))
        if self.items:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        done = sum(1 for i in self.items if i.state == "done")
        self.count_var.set(f"{len(self.items)}장" + (f" · 완료 {done}" if done else ""))
        self._update_buttons()

    def _set_row(self, idx: int, pct: float | None = None):
        it = self.items[idx]
        st = STATE_TEXT[it.state]
        if it.state == "run" and pct is not None:
            st = f"확대 중 {pct:.0f}%"
        elif it.state == "error":
            st = "⚠ " + it.error[:60]
        out = self._out_size(it)
        if it.state == "done" and it.result:
            real = core.image_size(it.result)
            if real:
                out = f"{real[0]}×{real[1]}"
        try:
            self.tree.item(it.iid, values=(it.path.name, f"{it.size[0]}×{it.size[1]}" if it.size else "?", out, st),
                           tags=(it.state,))
        except tk.TclError:
            pass

    def _item_of(self, iid: str) -> Item | None:
        return next((i for i in self.items if i.iid == iid), None)

    def on_double(self, event):
        it = self._item_of(self.tree.identify_row(event.y))
        if it and it.result and it.result.exists():
            self._open_file(it.result)
        elif it:
            self._open_file(it.path)

    def on_menu(self, event):
        iid = self.tree.identify_row(event.y)
        it = self._item_of(iid)
        if not it:
            return
        self.tree.selection_set(iid)
        m = tk.Menu(self.root, tearoff=0)
        has = bool(it.result and it.result.exists())
        m.add_command(label="🔍 원본과 비교하기", command=lambda: CompareWindow(self.root, it.path, it.result),
                      state="normal" if has else "disabled")
        m.add_command(label="결과 열기", command=lambda: self._open_file(it.result), state="normal" if has else "disabled")
        m.add_command(label="결과 폴더에서 보기", command=lambda: core.open_in_explorer(it.result),
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="원본 열기", command=lambda: self._open_file(it.path))
        m.add_command(label="목록에서 빼기", command=self.remove_selected, state="disabled" if self.busy else "normal")
        m.tk_popup(event.x_root, event.y_root)

    def _open_file(self, p: Path | None):
        if p and p.exists():
            import os
            try:
                os.startfile(str(p))  # type: ignore[attr-defined]
            except OSError:
                pass

    def open_result_folder(self):
        if self.last_result and self.last_result.exists():
            core.open_in_explorer(self.last_result)

    # ── 실행 ──────────────────────────────────────────
    @property
    def busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _update_buttons(self):
        busy = self.busy
        todo = any(i.state != "done" for i in self.items)
        self.btn_go.configure(text="■ 멈추기" if busy else "✨ 업스케일 시작",
                              state="normal" if busy or (self.items and todo) else "disabled")
        for b in (self.btn_add, self.btn_add_dir, self.btn_remove, self.btn_clear):
            b.configure(state="disabled" if busy else "normal")
        self.btn_open.configure(state="normal" if self.last_result and not busy else "disabled")

    def start_or_stop(self):
        if self.busy:
            self.cancel.set()
            self.set_status("멈추는 중…", PINK_ACCENT_DARK)
            return
        ok, why = core.engine_ready()
        if not ok:
            messagebox.showerror(APP_TITLE, why)
            return
        if self.s["out_mode"] == "custom" and not Path(self.s["out_dir"]).is_dir():
            messagebox.showerror(APP_TITLE, "저장할 폴더를 찾을 수 없어요. 「찾아보기…」로 다시 골라 주세요.")
            return
        todo = [n for n, i in enumerate(self.items) if i.state != "done"]
        if not todo:
            return
        for n in todo:
            self.items[n].state = "wait"
            self.items[n].error = ""
        self._refresh_list()
        self.cancel = threading.Event()
        opts = dict(model=self.s["model"], scale=self.s["scale"], fmt=self.s["format"], jpg_quality=self.s["jpg_quality"],
                    out_mode=self.s["out_mode"], out_dir=self.s["out_dir"], use_cpu=self.s["use_cpu"])
        jobs = [(n, self.items[n].path) for n in todo]
        self.worker = threading.Thread(target=self._work, args=(jobs, opts, self.cancel), daemon=True)
        self.worker.start()
        self._update_buttons()

    def _work(self, jobs, opts, cancel: threading.Event):
        """작업 스레드 — tk 를 부르지 않고 큐에만 넣는다."""
        total = len(jobs)
        ok = fail = 0
        for k, (n, path) in enumerate(jobs):
            if cancel.is_set():
                break
            self.q.put(("start", n, k, total))
            job = core.Job(src=path, cancel=cancel, **opts)
            try:
                dest = core.upscale(job, lambda p, n=n, k=k: self.q.put(("pct", n, k, total, p)))
                ok += 1
                self.q.put(("done", n, dest))
            except core.Cancelled:
                self.q.put(("cancel", n))
                break
            except core.UpscaleError as e:
                fail += 1
                self.q.put(("error", n, str(e)))
            except Exception as e:  # noqa: BLE001 — 한 장 실패로 전체가 멈추지 않게
                fail += 1
                self.q.put(("error", n, f"알 수 없는 오류: {e}"))
        self.q.put(("finished", ok, fail, cancel.is_set()))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "add":
                    if not self.busy:
                        self.add_paths(msg[1])
                elif kind == "start":
                    _, n, k, total = msg
                    self.items[n].state = "run"
                    self._set_row(n, 0)
                    self.tree.see(self.items[n].iid)
                    self.prog["value"] = k / total * 100
                    self.set_status(f"{k + 1}/{total} · {self.items[n].path.name} 확대 중…", PINK_ACCENT_DARK)
                elif kind == "pct":
                    _, n, k, total, p = msg
                    self._set_row(n, p)
                    self.prog["value"] = (k + p / 100) / total * 100
                    self.set_status(f"{k + 1}/{total} · {self.items[n].path.name} · {p:.0f}%", PINK_ACCENT_DARK)
                elif kind == "done":
                    _, n, dest = msg
                    self.items[n].state, self.items[n].result = "done", dest
                    self.last_result = dest
                    self._set_row(n)
                elif kind == "error":
                    _, n, err = msg
                    self.items[n].state, self.items[n].error = "error", err
                    self._set_row(n)
                elif kind == "cancel":
                    self.items[msg[1]].state = "cancel"
                    self._set_row(msg[1])
                elif kind == "finished":
                    _, ok, fail, stopped = msg
                    self.worker = None
                    self.prog["value"] = 100 if not stopped else self.prog["value"]
                    self._refresh_list()
                    if stopped:
                        self.set_status(f"멈췄어요. 완료 {ok}장" + (f", 실패 {fail}장" if fail else ""), PINK_ACCENT_DARK)
                    elif fail:
                        first = next((i.error for i in self.items if i.state == "error"), "")
                        self.set_status(f"완료 {ok}장, 실패 {fail}장 — {first}", ERR_RED)
                    else:
                        self.set_status(f"다 했어요! {ok}장을 확대했어요. 「📂 결과 폴더 열기」로 볼 수 있어요.", OK_GREEN)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def set_status(self, text: str, color: str = SUBTLE):
        self.status_lbl.configure(text=text, fg=color)

    def on_close(self):
        if self.busy and not messagebox.askyesno(APP_TITLE, "아직 확대 중이에요. 멈추고 닫을까요?"):
            return
        self.cancel.set()
        core.save_settings(self.s)
        self.root.destroy()


class CompareWindow:
    """원본과 결과를 같은 크기로 겹쳐 놓고, 가운데 선을 끌어 왼쪽(원본)·오른쪽(결과)을 비교한다.
    원본은 결과 크기로 단순 확대(가장 가까운 화소)해서 차이가 잘 보이게 한다. 휠로 확대, 끌어서 이동."""

    def __init__(self, master, src: Path, result: Path):
        self.win = tk.Toplevel(master, bg=BG)
        self.win.title(f"원본 ↔ 결과 비교 — {result.name}")
        self.win.geometry("980x720")
        self.after = Image.open(result).convert("RGBA")
        with Image.open(src) as s:
            from PIL import ImageOps
            s = ImageOps.exif_transpose(s).convert("RGBA")
            self.before = s.resize(self.after.size, Image.Resampling.NEAREST)
        self.cv = tk.Canvas(self.win, bg="#2b2326", highlightthickness=0, cursor="sb_h_double_arrow")
        self.cv.pack(fill="both", expand=True)
        tk.Label(self.win, text="선을 끌어 비교 · 휠로 확대/축소 · 오른쪽 버튼으로 끌어 이동 · 왼쪽 = 원본, 오른쪽 = 결과",
                 bg=PINK_LIGHT, fg=TEXT, font=(FONT, 9)).pack(fill="x")
        self.split = 0.5
        self.zoom = None   # 처음엔 창에 맞춤
        self.cx = self.cy = 0.5  # 보는 중심(그림 비율 좌표)
        self.photo = None
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<Button-1>", self.on_drag)
        self.cv.bind("<MouseWheel>", self.on_wheel)
        self.cv.bind("<ButtonPress-3>", self.on_pan_start)
        self.cv.bind("<B3-Motion>", self.on_pan)

    def _fit(self):
        W, H = max(1, self.cv.winfo_width()), max(1, self.cv.winfo_height())
        return min(W / self.after.width, H / self.after.height)

    def draw(self):
        W, H = max(1, self.cv.winfo_width()), max(1, self.cv.winfo_height())
        z = self.zoom or self._fit()
        vw, vh = W / z, H / z  # 보이는 그림 영역(그림 화소)
        x0 = min(max(0, self.cx * self.after.width - vw / 2), max(0, self.after.width - vw))
        y0 = min(max(0, self.cy * self.after.height - vh / 2), max(0, self.after.height - vh))
        box = (int(x0), int(y0), int(min(self.after.width, x0 + vw)), int(min(self.after.height, y0 + vh)))
        a = self.after.crop(box)
        b = self.before.crop(box)
        size = (max(1, int(a.width * z)), max(1, int(a.height * z)))
        rs = Image.Resampling.NEAREST if z >= 1 else Image.Resampling.LANCZOS
        a, b = a.resize(size, rs), b.resize(size, rs)
        cut = int(size[0] * self.split)
        out = a.copy()
        out.paste(b.crop((0, 0, cut, size[1])), (0, 0))
        self.photo = ImageTk.PhotoImage(out)
        self.cv.delete("all")
        ox, oy = (W - size[0]) // 2, (H - size[1]) // 2
        self.cv.create_image(ox, oy, image=self.photo, anchor="nw")
        self.cv.create_line(ox + cut, oy, ox + cut, oy + size[1], fill=PINK_TITLE, width=3)
        # 밝은 그림 위에서도 보이게 진한 바탕 위에 글자
        for x, text, anchor in ((ox + 8, "원본", "nw"), (ox + size[0] - 8, "결과", "ne")):
            t = self.cv.create_text(x + (4 if anchor == "nw" else -4), oy + 10, text=text, fill="white", anchor=anchor,
                                    font=(FONT, 11, "bold"))
            x1, y1, x2, y2 = self.cv.bbox(t)
            bg = self.cv.create_rectangle(x1 - 6, y1 - 3, x2 + 6, y2 + 3, fill=PINK_ACCENT_DARK, outline="")
            self.cv.tag_lower(bg, t)
        self._geom = (ox, size[0])

    def on_drag(self, e):
        ox, w = getattr(self, "_geom", (0, 1))
        self.split = min(1.0, max(0.0, (e.x - ox) / max(1, w)))
        self.draw()

    def on_wheel(self, e):
        z = self.zoom or self._fit()
        z = z * (1.25 if e.delta > 0 else 0.8)
        self.zoom = max(self._fit(), min(8.0, z))
        self.draw()

    def on_pan_start(self, e):
        self._pan = (e.x, e.y, self.cx, self.cy)

    def on_pan(self, e):
        x, y, cx, cy = self._pan
        z = self.zoom or self._fit()
        self.cx = min(1, max(0, cx - (e.x - x) / z / self.after.width))
        self.cy = min(1, max(0, cy - (e.y - y) / z / self.after.height))
        self.draw()


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
