#!/usr/bin/env python3
import os
import sys
import csv
import time
import stat
import shlex
import atexit
import tempfile
import datetime
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.font import Font
import tkinter.font as tkfont

import paramiko
import pexpect

# Credentials
CREDENTIAL_FILE = os.path.join(os.path.expanduser("~"), "remote_server_data.txt")
_REQUIRED_KEYS = ("SSH_USER", "SSH_PASS", "SSH_HOST")


def _load_server_data(path: str = CREDENTIAL_FILE) -> dict:
    creds: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    print(f"[WARNING] Ignoring malformed line in {path!s}: {raw!r}")
                    continue
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    except FileNotFoundError:
        print(
            f"[FATAL] Credentials file not found: {path}\n"
            f"Create it with these three lines (no extra spaces):\n"
            f"    SSH_USER=<user>\n    SSH_PASS=<pass>\n    SSH_HOST=<host>\n"
        )
        sys.exit(1)

    missing = [k for k in _REQUIRED_KEYS if k not in creds]
    if missing:
        print(f"[FATAL] {path} is missing keys: {', '.join(missing)}")
        sys.exit(1)

    return creds


_creds = _load_server_data()
SSH_USER = _creds["SSH_USER"]
SSH_PASS = _creds["SSH_PASS"]
SSH_HOST = _creds["SSH_HOST"]

# Static Settings
REMOTE_DB_PATH = "/var/log/kiosk/info_v1.db"

# OTA File-uploader credentials
OTA_SSH_USER = "mirek190"
OTA_SSH_PASS = "qwerty"
OTA_SSH_HOST = "31.220.111.15"
REMOTE_DIR = "/var/www/html/sh/kiosk/"
# Note: OTA credentials are kept hard-coded in this script.


# OTA File-Uploader Functions
def get_sftp_client():
    try:
        transport = paramiko.Transport((OTA_SSH_HOST, 22))
        transport.connect(username=OTA_SSH_USER, password=OTA_SSH_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        return sftp, transport
    except Exception as e:
        messagebox.showerror("Error", f"Failed to connect to server:\n{e}")
        return None, None


def upload_file_ota(file_path: str):
    sftp, transport = get_sftp_client()
    if sftp is None:
        return
    try:
        filename = os.path.basename(file_path)
        remote_path = os.path.join(REMOTE_DIR, filename)
        sftp.put(file_path, remote_path)
        sftp.chmod(remote_path, 0o644)
        messagebox.showinfo(
            "Success",
            f"File '{filename}' uploaded successfully with permissions 644."
        )
    except Exception as e:
        messagebox.showerror("Error", f"Failed to upload file:\n{e}")
    finally:
        sftp.close()
        transport.close()


def list_files():
    sftp, transport = get_sftp_client()
    files_info = []
    if sftp is None:
        return files_info
    try:
        for attr in sftp.listdir_attr(REMOTE_DIR):
            permissions = stat.filemode(attr.st_mode)
            filename = attr.filename
            size = attr.st_size
            date_created = datetime.datetime.fromtimestamp(
                attr.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            files_info.append((filename, permissions, size, date_created))
        return files_info
    except Exception as e:
        messagebox.showerror("Error", f"Failed to list files:\n{e}")
        return files_info
    finally:
        sftp.close()
        transport.close()


def remove_remote_file(filename: str) -> bool:
    sftp, transport = get_sftp_client()
    if sftp is None:
        return False
    try:
        sftp.remove(os.path.join(REMOTE_DIR, filename))
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to remove file:\n{e}")
        return False
    finally:
        sftp.close()
        transport.close()


# GUI – OTA File-Uploader
class FileUploaderApp:
    def __init__(self, master):
        self.master = master
        master.title("KIOSK Server – OTA file uploader")
        master.geometry("800x400")

        btn_frame = tk.Frame(master)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Refresh File List",
                  command=self.refresh_file_list).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Upload File",
                  command=self.upload_file).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Download File",
                  command=self.download_file).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Remove File", bg="red", fg="white",
                  command=self.remove_file).pack(side=tk.LEFT, padx=10)

        self.tree = ttk.Treeview(
            master,
            columns=("Filename", "Permissions", "Size", "Date Created"),
            show="headings"
        )
        for col in ("Filename", "Permissions", "Size", "Date Created"):
            self.tree.heading(col, text=col)

        style = ttk.Style()
        heading_font = tkfont.Font(font=style.configure("Treeview.Heading", "font"))
        for col in ("Filename", "Permissions", "Size", "Date Created"):
            self.tree.column(col, width=heading_font.measure(col) + 40)

        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.tree.bind("<Double-1>", self.on_double_click)

        self.refresh_file_list()

    def upload_file(self):
        path = filedialog.askopenfilename(title="Select a file to upload")
        if path:
            upload_file_ota(path)
            self.refresh_file_list()

    def refresh_file_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in list_files():
            self.tree.insert("", tk.END, values=row)

    def remove_file(self):
        sel = self.tree.focus()
        if not sel:
            messagebox.showerror("Error", "No file selected.")
            return
        filename = self.tree.item(sel, "values")[0]
        if (messagebox.askyesno("Confirm",
                                f"Are you sure you want to remove '{filename}'?") and
                remove_remote_file(filename)):
            messagebox.showinfo("Success", f"File '{filename}' removed successfully.")
            self.refresh_file_list()

    def download_file(self):
        sel = self.tree.focus()
        if not sel:
            messagebox.showerror("Error", "No file selected.")
            return
        filename = self.tree.item(sel, "values")[0]
        save_as = filedialog.asksaveasfilename(
            title="Save File As", initialfile=filename)
        if not save_as:
            return
        sftp, transport = get_sftp_client()
        if sftp is None:
            return
        try:
            sftp.get(os.path.join(REMOTE_DIR, filename), save_as)
            messagebox.showinfo("Success", f"Downloaded '{filename}'.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download file:\n{e}")
        finally:
            sftp.close()
            transport.close()

    def on_double_click(self, _event):
        sel = self.tree.focus()
        if not sel:
            return
        filename = self.tree.item(sel, "values")[0]
        if os.path.splitext(filename)[1].lower() in {".sh", ".py", ".txt"}:
            self.view_file(filename)

    def view_file(self, filename):
        sftp, transport = get_sftp_client()
        if sftp is None:
            return
        try:
            with sftp.open(os.path.join(REMOTE_DIR, filename), "r") as fh:
                content = fh.read().decode()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{e}")
            return
        finally:
            sftp.close()
            transport.close()

        viewer = tk.Toplevel(self.master)
        viewer.title(filename)
        txt = tk.Text(viewer, wrap="none")
        txt.insert("1.0", content)
        txt.config(state="disabled")
        sx = tk.Scrollbar(viewer, orient="horizontal", command=txt.xview)
        sy = tk.Scrollbar(viewer, orient="vertical", command=txt.yview)
        txt.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        txt.pack(expand=True, fill="both")


# GUI – Main Application
class App:
    def __init__(self, root):
        print("[DEBUG] Initialising the App...")
        self.root = root
        self.root.title("Remote SQLite Database Viewer")
        self.changes = {}
        self.removals = set()
        self.sort_column = "ID"
        self.sort_reverse = False
        self.display_to_db = {
            "ID": "id",
            "Hostname": "openkiosk_installed_ver",
            "Browser version": "sec_screen_wallpaper",
            "Second display": "hostname",
            "IP Address": "ip_address",
            "Ext IP Address": "ext_ip_address",
            "MAC Address": "mac_address",
            "Account Name": "account_name",
            "Password": "password",
            "Timestamp UTC": "timestamp_utc",
            "Status": "status",
            "Customer Name": "customer_name",
            "Country": "country",
            "Point of Sale": "point_of_sale",
            "SSH Port": "ssh_port",
        }

        # Button Bar
        self.button_frame = ttk.Frame(self.root)
        self.button_frame.pack(fill="x")

        self.refresh_button = ttk.Button(
            self.button_frame, text="Refresh Table", command=self.refresh_table)
        self.import_button = ttk.Button(
            self.button_frame, text="Import Table", command=self.import_table)
        self.save_button = ttk.Button(
            self.button_frame, text="Save Table", command=self.save_table)
        self.report_button = ttk.Button(
            self.button_frame, text="Generate Report", command=self.generate_report)
        self.quit_button = ttk.Button(
            self.button_frame, text="Quit", command=self.quit_application)

        self.refresh_button.pack(side="left", padx=5, pady=5)
        self.import_button.pack(side="left", padx=5, pady=5)
        self.save_button.pack(side="left", padx=5, pady=5)
        self.report_button.pack(side="left", padx=5, pady=5)
        self.quit_button.pack(side="left", padx=5, pady=5)

        # Server credentials input fields
        self.ip_frame = ttk.Frame(self.button_frame)
        self.ip_frame.pack(side="left", padx=10)

        ttk.Label(self.ip_frame, text="Server IP:").pack(side="left")
        self.ip_var = tk.StringVar(value=SSH_HOST)
        self.ip_entry = ttk.Entry(self.ip_frame, textvariable=self.ip_var, width=15)
        self.ip_entry.pack(side="left", padx=5)

        ttk.Label(self.ip_frame, text="User:").pack(side="left")
        self.user_var = tk.StringVar(value=SSH_USER)
        self.user_entry = ttk.Entry(self.ip_frame, textvariable=self.user_var, width=15)
        self.user_entry.pack(side="left", padx=5)

        ttk.Label(self.ip_frame, text="Pass:").pack(side="left")
        self.pass_var = tk.StringVar(value=SSH_PASS)
        self.pass_entry = ttk.Entry(self.ip_frame, textvariable=self.pass_var, width=15, show="*")
        self.pass_entry.pack(side="left", padx=5)

        self.ota_button = tk.Button(
            self.button_frame, text="OTA kiosk manager",
            command=self.launch_ota_manager, bg="red", fg="white")
        self.ota_button.pack(side="right", padx=5, pady=5)

        # Treeview + Scrollbar
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)

        self.columns = (
            "ID", "Hostname", "Browser version", "Second display", "IP Address",
            "Ext IP Address", "MAC Address", "Account Name", "Password",
            "Timestamp UTC", "Status", "Customer Name", "Country",
            "Point of Sale", "SSH Port",
        )
        self.editable_columns = ("Customer Name", "Country", "Point of Sale")

        self.tree = ttk.Treeview(self.frame, columns=self.columns, show="headings")
        for col in self.columns:
            self.tree.heading(col, text=col,
                              command=lambda _c=col: self.treeview_sort_column(_c))

        style = ttk.Style()
        heading_font = Font(font=style.configure("Treeview.Heading", "font"))
        for col in self.columns:
            width = heading_font.measure(col) + 15
            self.tree.column(col, width=width, anchor="center")

        self.vsb = ttk.Scrollbar(self.frame, orient="vertical",
                                 command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)

        self.frame.bind("<Configure>", self.adjust_treeview_height)
        self.tree.bind("<Configure>", lambda _: self.root.after(100, self.toggle_scrollbar))
        self.tree.bind("<Double-1>", self.on_double_click)

        # Context menu
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Reboot a device", command=self.reboot_device_dialog)
        self.menu.add_command(label="Connect via SSH", command=self.connect_ssh_dialog)
        self.menu.add_command(label="Connect via VNC", command=self.connect_vnc_dialog)
        self.menu.add_command(label="Remove Device", command=self.remove_device_dialog)
        self.menu.add_command(label="Sec screen - change a vid / pic",
                              command=self.change_sec_screen_media_dialog)

        self.tree.bind("<Button-3>", self.on_right_click)
        self.tree.tag_configure("online", background="#f2fff2")

        # Start with an empty table (no server connection yet)
        self.data = []
        self.update_treeview()

    def launch_ota_manager(self):
        ota_window = tk.Toplevel(self.root)
        FileUploaderApp(ota_window)

    def treeview_sort_column(self, col):
        self.sort_reverse = (self.sort_column == col and not self.sort_reverse)
        self.sort_column = col
        self.update_treeview()

    def adjust_treeview_height(self, event):
        style = ttk.Style()
        tree_font = style.lookup("Treeview", "font")
        default_font = Font(font=tree_font)
        frame_height = event.height
        row_height = default_font.metrics("linespace") + 2
        if self.tree.size()[1]:
            row_height = self.tree.winfo_reqheight() // self.tree.size()[1]
        max_rows = frame_height // row_height
        self.tree.configure(height=max_rows)

    def toggle_scrollbar(self):
        self.vsb.grid_remove() if self.tree.yview() == (0.0, 1.0) else self.vsb.grid()

    # Import / Export
    def import_table(self):
        file_path = filedialog.askopenfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = list(csv.reader(f))
        if not reader or tuple(reader[0]) != self.columns:
            messagebox.showerror(
                "Error", "CSV file format does not match expected columns.")
            return
        self.data = reader[1:]
        self.sort_column, self.sort_reverse = "ID", False
        self.update_treeview()

    def save_table(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not file_path:
            return
        rows = [self.columns]
        for item_id in self.tree.get_children():
            rows.append([self.tree.set(item_id, col) for col in self.columns])
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        messagebox.showinfo("Success", f"Table saved to {file_path}")

    # Refresh / Persist
    def refresh_table(self):
        print("[DEBUG] Refresh Table clicked – connecting to server.")

        # Get current values from UI fields
        _current_ui_ip = self.ip_var.get().strip()
        _current_ui_user = self.user_var.get().strip()
        _current_ui_pass = self.pass_var.get().strip()

        global SSH_HOST, SSH_USER, SSH_PASS

        # Update global credentials if they have changed in the UI
        if _current_ui_ip != SSH_HOST:
            SSH_HOST = _current_ui_ip
            print(f"[INFO] Updated server IP to: {SSH_HOST}")
        if _current_ui_user != SSH_USER:
            SSH_USER = _current_ui_user
            print(f"[INFO] Updated server user to: {SSH_USER}")
        if _current_ui_pass != SSH_PASS:
            SSH_PASS = _current_ui_pass
            print(f"[INFO] Updated server password.")

        try:
            # First, apply any pending local changes to the server.
            self.apply_changes_to_server()
            self.apply_removals_to_server()

            # Then, fetch the latest data from the database.
            self.data = self.fetch_data()
            self.sort_column, self.sort_reverse = "ID", False
            self.update_treeview()
        except paramiko.AuthenticationException:
            messagebox.showerror("Authentication Failed",
                                 "Authentication failed. Please check your username and password.")
            self.data = []
            self.update_treeview()
        except (paramiko.SSHException, ConnectionRefusedError, TimeoutError, OSError) as e:
            messagebox.showerror("Connection Failed",
                                 f"Failed to connect to server '{SSH_HOST}'.\n"
                                 f"Please check the server IP address and ensure it is reachable.\n\n"
                                 f"Error: {type(e).__name__}: {e}")
            self.data = []
            self.update_treeview()
        except Exception as e:
            messagebox.showerror("Error",
                                 f"An unexpected error occurred during refresh:\n{type(e).__name__}: {e}")
            self.data = []
            self.update_treeview()

    # CRUD Helper Methods
    def fetch_data(self):
        query = "SELECT * FROM info;"
        # execute_sql_query uses global SSH credentials and can raise connection/auth exceptions.
        output = self.execute_sql_query(query)
        return [line.split("|") for line in output.strip().split("\n") if line]

    def execute_sql_query(self, query):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # The connect call uses global SSH credentials. It can raise
        # paramiko.AuthenticationException, paramiko.SSHException, and socket errors.
        client.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=10)
        stdin, stdout, _ = client.exec_command(
            f'sqlite3 {REMOTE_DB_PATH} "{query}"')
        output = stdout.read().decode()
        client.close()
        return output

    def apply_changes_to_server(self):
        if not self.changes:
            return
        try:
            for row_id, changes in self.changes.items():
                for column_name, new_value in changes.items():
                    self.update_database(row_id, column_name, new_value)
            messagebox.showinfo("Success", "Local edits have been saved to the server.")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while updating:\n{e}")
        finally:
            self.changes.clear()

    def apply_removals_to_server(self):
        if not self.removals:
            return
        try:
            for row_id in self.removals:
                self.execute_sql_query(f"DELETE FROM info WHERE ID = {row_id};")
            self.removals.clear()
        except Exception as e:
            messagebox.showerror("Error", f"Error removing rows:\n{e}")

    def update_database(self, row_id, column_name, new_value):
        db_col = self.display_to_db.get(column_name,
                                        column_name.replace(" ", "_"))
        new_value = new_value.replace("'", "''")
        # This call can also raise SSH exceptions if execute_sql_query fails.
        self.execute_sql_query(
            f"UPDATE info SET \"{db_col}\" = '{new_value}' WHERE ID = {row_id};")

    # Sort & Display
    def sort_data(self):
        if not self.data:
            return
        idx = self.columns.index(self.sort_column)
        numeric = {"ID", "SSH Port"}
        keyfn = (lambda x: int(x[idx] or 0)
                 if self.sort_column in numeric
                 else (x[idx] or "").lower())
        self.data.sort(key=keyfn, reverse=self.sort_reverse)

    def update_treeview(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.sort_data()
        status_idx = self.columns.index("Status")
        for row in self.data:
            tag = ("online" if len(row) > status_idx and
                   row[status_idx].lower() == "online" else "")
            self.tree.insert("", "end", values=row, tags=(tag,))
        self.toggle_scrollbar()

    # Cell Editing
    def on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        column = self.tree.identify_column(event.x)
        col_idx = int(column.lstrip("#")) - 1
        col_name = self.columns[col_idx]
        if col_name not in self.editable_columns:
            return
        self.edit_cell(event, col_name)

    def edit_cell(self, event, col_name):
        row_id = self.tree.identify_row(event.y)
        x, y, w, h = self.tree.bbox(row_id, self.tree.identify_column(event.x))
        entry = tk.Entry(self.tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, self.tree.set(row_id, col_name))
        entry.focus_set()

        def save(_=None):
            new_val = entry.get()
            entry.destroy()
            self.tree.set(row_id, col_name, new_val)
            db_row_id = self.tree.set(row_id, "ID")
            self.changes.setdefault(db_row_id, {})[col_name] = new_val
            for r in self.data:
                if r[self.columns.index("ID")] == db_row_id:
                    r[self.columns.index(col_name)] = new_val
                    break

        entry.bind("<Return>", save)
        entry.bind("<FocusOut>", save)

    # Context Menu
    def on_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self.selected_item = row_id

        if not self.tree.item(row_id, "values"):
            return

        values = self.tree.item(row_id, "values")
        status = values[self.columns.index("Status")].lower() if len(values) > 0 else ""
        second_display = values[self.columns.index("Second display")]

        enable = (status == "online")
        for label in ("Reboot a device", "Connect via SSH",
                      "Connect via VNC", "Sec screen - change a vid / pic"):
            self.menu.entryconfig(label, state=("normal" if enable else "disabled"))
        if second_display == "-----":
            self.menu.entryconfig("Sec screen - change a vid / pic", state="disabled")

        self.menu.tk_popup(event.x_root, event.y_root)

    # Context-Menu Actions
    def reboot_device_dialog(self):
        self.confirm_action(
            "Reboot a device",
            "Are you sure you want to reboot the device?",
            self._reboot_device_action)

    def connect_ssh_dialog(self):
        self.confirm_action(
            "Connect via SSH",
            "Are you sure you want to connect via SSH?",
            self._connect_ssh_action)

    def connect_vnc_dialog(self):
        self.confirm_action(
            "Connect via VNC",
            "Are you sure you want to connect via VNC?",
            self._connect_vnc_action)

    def remove_device_dialog(self):
        self.confirm_action(
            "Remove Device",
            "Are you sure you want to remove this device from the table?",
            self._remove_device_action)

    def change_sec_screen_media_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Select media file",
            filetypes=[("Media files", "*.mp4 *.avi *.mov *.mkv "
                        "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if not file_path:
            return
        if not messagebox.askyesno(
                "Confirm",
                f"Update secondary screen media with:\n{os.path.basename(file_path)}?"):
            return
        threading.Thread(
            target=self._change_sec_screen_media_action, args=(file_path,)).start()

    def confirm_action(self, title, message, on_continue):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("410x90")
        dlg.grab_set()

        tk.Label(dlg, text=message).pack(pady=10)
        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=5)

        ttk.Button(btn_frame, text="Continue",
                   command=lambda: (dlg.destroy(), on_continue())).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel",
                   command=lambda: dlg.destroy()).pack(side="left", padx=5)

        dlg.focus_force()
        dlg.wait_window()

    def _reboot_device_action(self):
        values = self.tree.item(self.selected_item, "values")
        account_name = values[self.columns.index("Account Name")]
        password = values[self.columns.index("Password")]
        ssh_port = values[self.columns.index("SSH Port")]

        reboot_cmd = f'echo "{password}" | sudo -S reboot'
        kiosk_cmd = (
            f"sshpass -p '{password}' ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null -p {ssh_port} "
            f"{account_name}@localhost '{reboot_cmd}'")
        server_cmd = (
            f"sshpass -p '{SSH_PASS}' ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null {SSH_USER}@{SSH_HOST} "
            f"\"{kiosk_cmd}\"")

        def run():
            res = subprocess.run(server_cmd, shell=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                messagebox.showinfo("Success", "Device rebooted successfully.")
            else:
                messagebox.showerror("Error", f"Reboot failed:\n{res.stderr.strip()}")

        threading.Thread(target=run).start()

    def _connect_ssh_action(self):
        import platform
        values = self.tree.item(self.selected_item, "values")
        account_name = values[self.columns.index("Account Name")]
        password = values[self.columns.index("Password")]
        ssh_port = values[self.columns.index("SSH Port")]

        kiosk_cmd = (
            f"sshpass -p {shlex.quote(password)} ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null -p {ssh_port} "
            f"{shlex.quote(account_name)}@localhost")
        server_cmd = (
            f"sshpass -p {shlex.quote(SSH_PASS)} ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null {SSH_USER}@{SSH_HOST} -t '{kiosk_cmd}'")

        system = platform.system()
        try:
            if system == "Linux":
                subprocess.Popen(["xterm", "-hold", "-e", server_cmd])
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", "Terminal.app", server_cmd])
            elif system == "Windows":
                subprocess.Popen(["cmd.exe", "/k", server_cmd])
            else:
                messagebox.showerror("Error", "Unsupported OS for opening terminal.")
        except FileNotFoundError:
            if system == "Linux":
                subprocess.Popen(["gnome-terminal", "--", "bash", "-c", server_cmd])

    def _connect_vnc_action(self):
        values = self.tree.item(self.selected_item, "values")
        kiosk_user = values[self.columns.index("Account Name")]
        kiosk_password = values[self.columns.index("Password")]
        kiosk_port = int(values[self.columns.index("SSH Port")])
        threading.Thread(target=do_vnc_connection,
                         args=(kiosk_user, kiosk_password, kiosk_port)).start()

    def _remove_device_action(self):
        item = self.selected_item
        row_id = self.tree.item(item, "values")[self.columns.index("ID")]
        self.removals.add(row_id)
        self.tree.delete(item)
        self.data = [r for r in self.data if r[self.columns.index("ID")] != row_id]
        messagebox.showinfo(
            "Info",
            f"Device (ID={row_id}) removed locally.\nClick 'Refresh Table' to apply changes.")

    def _change_sec_screen_media_action(self, file_path):
        values = self.tree.item(self.selected_item, "values")
        kiosk_user = values[self.columns.index("Account Name")]
        kiosk_password = values[self.columns.index("Password")]
        ssh_port = values[self.columns.index("SSH Port")]
        filename = os.path.basename(file_path)

        upload_cmd = (
            f"sshpass -p {shlex.quote(SSH_PASS)} scp -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null {shlex.quote(file_path)} "
            f"{SSH_USER}@{SSH_HOST}:/tmp/")
        res = subprocess.run(upload_cmd, shell=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            messagebox.showerror("Error", f"Upload failed:\n{res.stderr}")
            return

        scp_cmd = (
            f"sshpass -p {shlex.quote(kiosk_password)} scp -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null -P {ssh_port} /tmp/{filename} "
            f"{kiosk_user}@localhost:/usr/ota/DATA/")
        rm_cmd = f"rm /tmp/{filename}"
        inner_cmd = (
            "killall mpv || true; "
            f"sed -i \"s|^media=\\\"/usr/ota/DATA/.*\\\"|media=\\\"/usr/ota/DATA/{filename}\\\"|\" "
            "/usr/ota/DATA/touch_fix.sh && "
            "DISPLAY=:0 nohup bash /usr/ota/DATA/touch_fix.sh > /dev/null 2>&1 &")
        ssh_inner_cmd = (
            f"sshpass -p {shlex.quote(kiosk_password)} ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null -p {ssh_port} {kiosk_user}@localhost "
            f"{shlex.quote(inner_cmd)}")
        compound_cmd = f"{scp_cmd}; {rm_cmd}; {ssh_inner_cmd}"
        server_cmd = (
            f"sshpass -p {shlex.quote(SSH_PASS)} ssh -oStrictHostKeyChecking=no "
            f"-oUserKnownHostsFile=/dev/null {SSH_USER}@{SSH_HOST} "
            f"{shlex.quote(compound_cmd)}")

        res = subprocess.run(server_cmd, shell=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            messagebox.showinfo("Success", "Secondary screen media updated.")
        else:
            messagebox.showerror("Error", f"Failed to update media:\n{res.stderr}")

    # Report Generation
    def generate_report(self):
        if not self.data:
            messagebox.showinfo("Info", "Table is empty.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return

        now_utc = datetime.datetime.utcnow()
        offline_lines, online_lines = [], []
        single_lines, dual_lines = [], []

        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            account_name = vals[self.columns.index("Account Name")]
            status = vals[self.columns.index("Status")].lower()
            ts_str = vals[self.columns.index("Timestamp UTC")]
            second_display = vals[self.columns.index("Second display")]

            if status == "online":
                online_lines.append(f"Device {account_name} - device online")
            else:
                try:
                    last_seen = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    delta = now_utc - last_seen
                    offline_lines.append(
                        f"Device {account_name} - inactive since "
                        f"{delta.days} days and {delta.seconds // 3600} hours")
                except Exception:
                    offline_lines.append(
                        f"Device {account_name} - inactive (timestamp format unknown)")

            if second_display == "-----":
                single_lines.append(f"Device {account_name} - single screen")
            else:
                dual_lines.append(f"Device {account_name} - dual screen")

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Device Uptime:"])
                w.writerow([])
                w.writerows([[l] for l in offline_lines])
                w.writerow([])
                w.writerows([[l] for l in online_lines])
                w.writerow([])
                w.writerow(["================================================"])
                w.writerow([])
                w.writerow(["Device screen type:"])
                w.writerow([])
                w.writerows([[l] for l in single_lines])
                w.writerow([])
                w.writerows([[l] for l in dual_lines])
            messagebox.showinfo("Success", f"Report saved to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate report:\n{e}")

    # Quit
    def quit_application(self):
        self.root.destroy()


# VNC Connection Helper
def do_vnc_connection(kiosk_user, kiosk_password, kiosk_port):
    SERVER_USER = SSH_USER
    SERVER_HOST = SSH_HOST
    SERVER_PASSWORD = SSH_PASS

    processes, temp_files = [], []

    def cleanup():
        for p in processes:
            if p.isalive():
                p.terminate(force=True)
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError as e:
                    print(f"[VNC Cleanup Error] Could not remove {f}: {e}")

    atexit.register(cleanup)

    # 1. SSH from home to the intermediate server
    child = pexpect.spawn(
        f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null "
        f"{SERVER_USER}@{SERVER_HOST}",
        encoding="utf-8", timeout=30)
    processes.append(child)
    child.expect("password:")
    child.sendline(SERVER_PASSWORD)
    child.expect(f"{SERVER_USER}@")

    # 2. From server, SSH to the target kiosk (at localhost)
    child.sendline(
        f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null "
        f"-p {kiosk_port} {kiosk_user}@localhost")
    i = child.expect(["password:", "continue connecting (yes/no)?"])
    if i == 1:
        child.sendline("yes")
        child.expect("password:")
    child.sendline(kiosk_password)
    child.expect(f"{kiosk_user}@")

    # 3. From kiosk, create a reverse tunnel back to the server
    child.sendline(
        f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null "
        f"-R 5900:localhost:5900 {SERVER_USER}@{SERVER_HOST}")
    i = child.expect(["password:", "continue connecting (yes/no)?"])
    if i == 1:
        child.sendline("yes")
        child.expect("password:")
    child.sendline(SERVER_PASSWORD)

    # 4. From home, create a forward tunnel to the server
    forward = pexpect.spawn(
        f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null "
        f"-L 5900:localhost:5900 {SERVER_USER}@{SERVER_HOST}",
        encoding="utf-8", timeout=30)
    processes.append(forward)
    forward.expect("password:")
    forward.sendline(SERVER_PASSWORD)

    time.sleep(3)

    # 5. Launch the VNC viewer to connect to the local end of the tunnel
    fd, pwdfile = tempfile.mkstemp()
    os.close(fd)
    temp_files.append(pwdfile)
    # The kiosk's user password is used as the VNC password
    encoded_pwd = subprocess.check_output(["vncpasswd", "-f"],
                                          input=kiosk_password.encode())
    with open(pwdfile, "wb") as f:
        f.write(encoded_pwd)

    viewer = pexpect.spawn(
        f"vncviewer localhost:5900 -passwd {pwdfile}", encoding="utf-8")
    processes.append(viewer)

    try:
        viewer.wait()
    except pexpect.exceptions.TIMEOUT:
        print("[VNC] Viewer wait apparently timed out or interrupted.")
    except Exception as e_vnc_wait:
        print(f"[VNC] Error during viewer.wait(): {e_vnc_wait}")
    finally:
        cleanup()


# Main
def main():
    root = tk.Tk()
    root.title("Remote SQLite Database Viewer")
    root.geometry("1650x600")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
