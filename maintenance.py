"""Integrity checking, automatic daily backup, offline restore and admin recovery."""
import argparse, getpass, os, secrets, sqlite3
from datetime import datetime
from pathlib import Path
import core as db
from app_lock import workspace_lock

REQUIRED={'settings','users','products','customers','suppliers','sales','sale_items','purchases','purchase_items','returns','return_items','payments','movements','audit','warranty_claims'}

def validate(path):
    if not path.is_file():raise RuntimeError('Backup file does not exist.')
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,factory=db.ClosingConnection) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity check failed.')
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED.issubset(tables):raise RuntimeError('This is not a AutoParts Pro backup.')
        if c.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Backup has invalid record links.')
        row=c.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
        if not row or row[0] not in ('2','3'):raise RuntimeError('Backup schema version is incompatible.')
        if row[0]=='3' and not {'vehicles','service_visits'}.issubset(tables):raise RuntimeError('Workshop backup is missing vehicle or visit records.')
        columns={r[1] for r in c.execute('PRAGMA table_info(returns)')}
        if 'tax_refund' not in columns:raise RuntimeError('Backup is missing the return tax field.')
    return True

def snapshot(prefix='auto'):
    if not db.DB.exists():return None
    validate(db.DB.resolve())
    folder=db.DATA/'backups';folder.mkdir(exist_ok=True)
    day=datetime.now().strftime('%Y%m%d')
    if prefix=='auto' and any(folder.glob(f'auto-{day}-*.sqlite3')):return None
    dest=folder/f'{prefix}-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(3)}.sqlite3'
    with db.connect() as source,sqlite3.connect(dest,factory=db.ClosingConnection) as target:source.backup(target)
    validate(dest.resolve());return dest

def restore(path):
    source=path.expanduser().resolve()
    if source==db.DB.resolve():raise RuntimeError('Select a backup file, not the currently active database.')
    validate(source)
    safety=snapshot('before-restore')
    staged=db.DATA/f'restore-{secrets.token_hex(5)}.tmp'
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,factory=db.ClosingConnection) as c,sqlite3.connect(staged,factory=db.ClosingConnection) as target:c.backup(target)
        validate(staged.resolve())
        for suffix in ('-wal','-shm'):Path(str(db.DB)+suffix).unlink(missing_ok=True)
        os.replace(staged,db.DB)
    finally:staged.unlink(missing_ok=True)
    print('Restore complete. Start AutoParts again. Use the accounts from the restored backup.')
    if safety:print('Safety copy:',safety)

def recover():
    if not db.DB.exists():raise RuntimeError('No store database yet. Start the app to create your account.')
    print('Local admin recovery. Close the app first. Physical access to store data allows password recovery.')
    username=input('Admin username: ').strip()
    password=getpass.getpass('New password (10+ characters; typing is hidden): ')
    if password!=getpass.getpass('Confirm new password: '):raise RuntimeError('Passwords do not match.')
    hashed=db.password_hash(password)
    with db.transaction() as c:
        u=c.execute("SELECT id FROM users WHERE username=? AND role='admin'",(username,)).fetchone()
        if not u:raise RuntimeError('Admin username not found.')
        c.execute('UPDATE users SET password=?,active=1 WHERE id=?',(hashed,u['id']))
        db.audit(c,{'id':u['id']},'offline_password_recovery',{})
    print('Admin password updated. Start the app and sign in.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['startup','restore','recover']);parser.add_argument('file',nargs='?');args=parser.parse_args()
    try:
        with workspace_lock():
            if args.action=='startup':
                path=snapshot()
                if path:print('Daily backup saved:',path.name)
                else:print('Startup checks complete.')
            elif args.action=='restore':
                value=args.file or input('Paste backup file path (or drag the file here), then Enter: ').strip().strip('"')
                source=Path(value)
                validate(source.expanduser().resolve())
                if input('Restore replaces current records. Type RESTORE to continue: ').strip()!='RESTORE':print('Cancelled.');return 0
                restore(source)
            else:recover()
        return 0
    except (RuntimeError,db.BusinessError,sqlite3.Error,OSError) as e:print('ERROR:',e);return 1
if __name__=='__main__':raise SystemExit(main())
