from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from tkinter import filedialog, messagebox, ttk

from nox_csv_extractor.nox import extract_nox_numeric_table, write_nox_table_csv

ExistingPolicy = Literal["rename", "overwrite", "skip"]
POLICY_LABELS: dict[str, ExistingPolicy] = {
    "Keep both": "rename",
    "Replace": "overwrite",
    "Skip": "skip",
}


@dataclass
class NoxCsvResult:
    source: str
    status: str
    output: str = ""
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    message: str = ""


def extract_target(target: str | Path, on_existing: ExistingPolicy = "rename") -> list[NoxCsvResult]:
    source = Path(target)
    paths = collect_nox_paths(source)
    if not paths:
        raise ValueError(f"No .nox files found: {source}")
    return [extract_one(path, on_existing=on_existing) for path in paths]


def collect_nox_paths(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() == ".nox" else []
    if target.is_dir():
        return sorted(target.rglob("*.nox"))
    return []


def extract_one(source: Path, on_existing: ExistingPolicy = "rename") -> NoxCsvResult:
    output = resolve_output_csv_path(source, on_existing=on_existing)
    if output is None:
        return NoxCsvResult(source=str(source), status="skipped", message="CSV already exists.")
    try:
        table = extract_nox_numeric_table(source)
        written = write_nox_table_csv(table, output)
    except Exception as exc:
        return NoxCsvResult(source=str(source), status="error", output=str(output), message=str(exc))
    return NoxCsvResult(
        source=str(source),
        status="ok",
        output=str(written),
        rows=len(table.rows),
        columns=table.columns,
    )


def resolve_output_csv_path(source: Path, on_existing: ExistingPolicy = "rename") -> Path | None:
    target = source.with_suffix(".csv")
    if on_existing == "overwrite" or not target.exists():
        return target
    if on_existing == "skip":
        return None
    index = 2
    while True:
        candidate = source.with_name(f"{source.stem}_{index}.csv")
        if not candidate.exists():
            return candidate
        index += 1


class NoxToCsvApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NOX to CSV")
        self.geometry("720x460")
        self.minsize(620, 380)
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None

        self.target_var = tk.StringVar()
        self.policy_var = tk.StringVar(value="Keep both")
        self.status_var = tk.StringVar(value="Choose a file or folder.")

        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ttk.Frame(self, padding=(14, 12, 14, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="NOX to CSV", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")

        target = ttk.Frame(self, padding=(14, 6))
        target.grid(row=1, column=0, sticky="ew")
        target.columnconfigure(0, weight=1)
        self.target_entry = ttk.Entry(target, textvariable=self.target_var)
        self.target_entry.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 8))
        ttk.Button(target, text="Choose File", command=self._choose_file).grid(row=1, column=0, sticky="w")
        ttk.Button(target, text="Choose Folder", command=self._choose_folder).grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(target, text="If CSV exists:").grid(row=1, column=2, sticky="w", padx=(14, 0))
        self.policy_combo = ttk.Combobox(
            target,
            textvariable=self.policy_var,
            values=tuple(POLICY_LABELS),
            state="readonly",
            width=10,
        )
        self.policy_combo.grid(row=1, column=3, sticky="w", padx=(6, 0))
        self.convert_button = ttk.Button(target, text="Convert", command=self._convert)
        self.convert_button.grid(row=1, column=4, sticky="w", padx=(8, 0))

        status = ttk.Frame(self, padding=(14, 4))
        status.grid(row=2, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var, foreground="#555555").grid(row=0, column=0, sticky="w")

        log_frame = ttk.Frame(self, padding=(14, 8, 14, 14))
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(title="Choose NOVA .nox file", filetypes=[("NOVA files", "*.nox"), ("All files", "*.*")])
        if path:
            self.target_var.set(path)

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose folder containing .nox files")
        if path:
            self.target_var.set(path)

    def _convert(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        target = self.target_var.get().strip().strip('"')
        if not target:
            messagebox.showwarning("NOX to CSV", "Choose a .nox file or a folder first.")
            return
        path = Path(target)
        if not path.exists():
            messagebox.showerror("NOX to CSV", f"Target does not exist:\n{path}")
            return
        policy = POLICY_LABELS[self.policy_var.get()]
        self._set_log("")
        self._append_log(f"Target: {path}\nExisting CSV: {self.policy_var.get()}\n\n")
        self.status_var.set("Converting...")
        self.convert_button.configure(state="disabled")
        self._worker = threading.Thread(target=self._run_conversion, args=(path, policy), daemon=True)
        self._worker.start()

    def _run_conversion(self, target: Path, policy: ExistingPolicy) -> None:
        try:
            results = extract_target(target, on_existing=policy)
        except Exception as exc:
            self._queue.put(("error", str(exc)))
            return
        self._queue.put(("results", results))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "error":
                    self.status_var.set("Failed")
                    self.convert_button.configure(state="normal")
                    self._append_log(f"ERROR: {payload}\n")
                    messagebox.showerror("NOX to CSV", str(payload))
                elif kind == "results":
                    self._show_results(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _show_results(self, results: object) -> None:
        items = list(results)  # type: ignore[arg-type]
        ok_count = sum(1 for item in items if item.status == "ok")
        skipped_count = sum(1 for item in items if item.status == "skipped")
        error_count = sum(1 for item in items if item.status == "error")
        for item in items:
            if item.status == "ok":
                self._append_log(f"OK      {item.source}\n        -> {item.output} ({item.rows} rows)\n")
            elif item.status == "skipped":
                self._append_log(f"SKIP    {item.source}\n        {item.message}\n")
            else:
                self._append_log(f"ERROR   {item.source}\n        {item.message}\n")
        summary = f"Converted {ok_count}/{len(items)} files; skipped={skipped_count}; errors={error_count}"
        self._append_log(f"\n{summary}\n")
        self.status_var.set(summary)
        self.convert_button.configure(state="normal")
        if error_count:
            messagebox.showwarning("NOX to CSV", summary)
        else:
            messagebox.showinfo("NOX to CSV", summary)

    def _set_log(self, value: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        if value:
            self.log.insert(tk.END, value)
        self.log.configure(state="disabled")

    def _append_log(self, value: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, value)
        self.log.see(tk.END)
        self.log.configure(state="disabled")


def main() -> int:
    app = NoxToCsvApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
