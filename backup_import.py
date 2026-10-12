"""Windowed upgrade import into an empty shop; existing records are never overwritten."""
import os,secrets,sqlite3,tempfile
from datetime import datetime
from pathlib import Path
import core as db
from maintenance import validate
from app_lock import workspace_lock

def import_backup(value):
    source=Path(value).expanduser().resolve();validate(source)
    target=db.DB.resolve();target_data=db.DATA.resolve()
    if source==target:raise RuntimeError('Select the downloaded backup from your old app, not this folder’s active database.')
    with workspace_lock():
        if target.exists():
            validate(target)
            with db.connect() as c:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('users','customers','products','suppliers','sales','purchases','vehicles','service_visits'):
                    if table in tables and c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
                        raise RuntimeError('This shop already contains accounts or records. Import is only allowed into a fresh extracted folder. Existing data was not changed.')
        with tempfile.TemporaryDirectory(prefix='upgrade-',dir=target_data) as folder:
            staged=Path(folder)/'autoparts.sqlite3'
            with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,factory=db.ClosingConnection) as src,sqlite3.connect(staged,factory=db.ClosingConnection) as dest:src.backup(dest)
            old=db.DATA,db.DB
            try:
                db.DATA=Path(folder);db.DB=staged;db.initialize();validate(staged.resolve())
            finally:db.DATA,db.DB=old
            backups=target_data/'backups';backups.mkdir(exist_ok=True)
            safety=backups/f'import-source-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(3)}.sqlite3'
            with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,factory=db.ClosingConnection) as src,sqlite3.connect(safety,factory=db.ClosingConnection) as dest:src.backup(dest)
            for suffix in ('-wal','-shm'):Path(str(target)+suffix).unlink(missing_ok=True)
            os.replace(staged,target)
        return target

def main():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    win=tk.Tk();win.withdraw()
    try:
        messagebox.showinfo('Import old AutoParts backup','Use a fresh extracted folder. Close this folder’s app. Select the verified .sqlite3 backup downloaded from the old AutoParts app. Existing shop records will never be overwritten.')
        source=filedialog.askopenfilename(title='Select old AutoParts backup',filetypes=[('AutoParts backup','*.sqlite3'),('All files','*.*')])
        if not source:return 0
        if not messagebox.askyesno('Import and upgrade backup','Import this backup into this empty shop? Your old folder and original backup stay available. Use the old account password after import.'):return 0
        import_backup(source)
        messagebox.showinfo('Import complete','Backup upgraded successfully. Open AutoParts Pro.vbs. Sign in with your old username/password. Old customers, parts, bills and recovery codes are preserved.')
        return 0
    except Exception as e:messagebox.showerror('Import could not complete',str(e));return 1
    finally:win.destroy()

if __name__=='__main__':raise SystemExit(main())
