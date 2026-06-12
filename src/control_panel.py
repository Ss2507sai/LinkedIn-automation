"""macOS desktop control panel (tkinter)."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Callable

from src.control import AutomationControl, ControlState


class ControlPanel:
    def __init__(
        self,
        control: AutomationControl,
        on_start: Callable[[], None] | None = None,
    ) -> None:
        self.control = control
        self.on_start = on_start
        self.root = tk.Tk()
        self.root.title("Wavity LinkedIn Automation")
        self.root.geometry("780x760")
        self._approval_editable = False
        self._build()
        self.root.after(400, self._refresh)
        if on_start:
            threading.Thread(target=on_start, daemon=True).start()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        stats = ttk.LabelFrame(frame, text="Status", padding=8)
        stats.pack(fill=tk.X, pady=4)
        self.lbl_profile = ttk.Label(stats, text="Profile #: 0")
        self.lbl_profile.grid(row=0, column=0, sticky=tk.W, padx=4)
        self.lbl_name = ttk.Label(stats, text="Name: -")
        self.lbl_name.grid(row=0, column=1, sticky=tk.W, padx=4)
        self.lbl_company = ttk.Label(stats, text="Company: -")
        self.lbl_company.grid(row=1, column=0, sticky=tk.W, padx=4)
        self.lbl_step = ttk.Label(stats, text="Step: Idle")
        self.lbl_step.grid(row=1, column=1, sticky=tk.W, padx=4)
        self.lbl_counts = ttk.Label(stats, text="Success: 0 | Failure: 0 | Page: 1")
        self.lbl_counts.grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=4)
        self.lbl_mode = ttk.Label(stats, text="Mode: APPROVAL")
        self.lbl_mode.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=4)

        btns = ttk.LabelFrame(frame, text="Controls", padding=8)
        btns.pack(fill=tk.X, pady=4)
        for i, (label, cmd) in enumerate(
            [
                ("Pause", self.control.button_pause),
                ("Resume", self.control.button_resume),
                ("Stop", self.control.button_stop),
                ("Skip Prospect", self.control.button_skip),
                ("Retry Prospect", self.control.button_retry),
                ("Open Current Profile", self.control.button_open_profile),
                ("Save and Stop", self.control.button_save_and_stop),
            ]
        ):
            ttk.Button(btns, text=label, command=cmd).grid(
                row=i // 4, column=i % 4, padx=3, pady=3, sticky=tk.EW
            )

        cmd_frame = ttk.LabelFrame(frame, text="Command Box", padding=8)
        cmd_frame.pack(fill=tk.X, pady=4)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.cmd_entry.bind("<Return>", self._send_command)
        ttk.Button(cmd_frame, text="Send", command=self._send_command).pack(side=tk.RIGHT)
        self.cmd_log = scrolledtext.ScrolledText(frame, height=3, wrap=tk.WORD)
        self.cmd_log.pack(fill=tk.X, pady=4)

        self.approval_frame = ttk.LabelFrame(frame, text="Connection Approval", padding=8)
        self.approval_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        self.lbl_approval_name = ttk.Label(self.approval_frame, text="Prospect: -")
        self.lbl_approval_name.pack(anchor=tk.W)
        self.lbl_approval_company = ttk.Label(self.approval_frame, text="Company: -")
        self.lbl_approval_company.pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(self.approval_frame, text="Connection Request (editable):").pack(anchor=tk.W)
        self.approval_text = scrolledtext.ScrolledText(
            self.approval_frame, height=10, wrap=tk.WORD
        )
        self.approval_text.pack(fill=tk.BOTH, expand=True, pady=4)
        approval_btns = ttk.Frame(self.approval_frame)
        approval_btns.pack(fill=tk.X, pady=6)
        ttk.Button(
            approval_btns, text="Approve & Send", command=self._approve_send
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(approval_btns, text="Edit", command=self._save_edit).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            approval_btns, text="Regenerate", command=self.control.button_regenerate
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            approval_btns, text="Skip", command=self.control.button_approval_skip
        ).pack(side=tk.LEFT, padx=4)

    def _approve_send(self) -> None:
        text = self.approval_text.get("1.0", tk.END).strip()
        if text:
            self.control.set_edited_connection_request(text)
        self.control.button_approve_send()

    def _save_edit(self) -> None:
        text = self.approval_text.get("1.0", tk.END).strip()
        self.control.set_edited_connection_request(text)
        self.cmd_log.insert(tk.END, f"> Edit saved ({len(text)} chars)\n")
        self.cmd_log.see(tk.END)

    def _send_command(self, _event=None) -> None:
        text = self.cmd_entry.get().strip()
        if not text:
            return
        result = self.control.submit_command(text)
        self.cmd_log.insert(tk.END, f"> {text}\n  {result}\n")
        self.cmd_log.see(tk.END)
        self.cmd_entry.delete(0, tk.END)

    def _refresh(self) -> None:
        state = self.control.snapshot()
        self._apply_state(state)
        self.root.after(400, self._refresh)

    def _apply_state(self, state: ControlState) -> None:
        self.lbl_profile.config(text=f"Profile #: {state.profile_number}")
        self.lbl_name.config(text=f"Name: {state.prospect_name or '-'}")
        self.lbl_company.config(text=f"Company: {state.company or '-'}")
        self.lbl_step.config(text=f"Step: {state.step}")
        self.lbl_counts.config(
            text=(
                f"Success: {state.success_count} | Failure: {state.failure_count} | "
                f"Page: {state.page_number}"
            )
        )
        self.lbl_mode.config(text=f"Mode: {state.mode}")

        self.lbl_approval_name.config(text=f"Prospect: {state.prospect_name or '-'}")
        self.lbl_approval_company.config(text=f"Company: {state.company or '-'}")

        if state.approval_pending:
            if not self._approval_editable:
                self.approval_text.delete("1.0", tk.END)
                self.approval_text.insert(tk.END, state.pending_connection_request)
                self._approval_editable = True
        else:
            if self._approval_editable:
                self.approval_text.delete("1.0", tk.END)
                self.approval_text.insert(
                    tk.END, "Waiting for connection request to review..."
                )
                self._approval_editable = False

    def run(self) -> None:
        self.root.mainloop()
