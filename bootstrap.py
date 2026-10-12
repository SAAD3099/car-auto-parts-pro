"""Windowed first-run setup. Installs the pinned desktop runtime without a CMD window."""
from __future__ import annotations
import ctypes, json, os, queue, subprocess, sys, threading, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ENV=ROOT/'.desktop-runtime'
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
PYTHON=ENV/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
PYTHONW=ENV/('Scripts/pythonw.exe' if os.name=='nt' else 'bin/python')
VERSION='6.10.2'

def run(args,log):
    p=subprocess.run([str(a) for a in args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=FLAGS)
    if p.returncode:raise RuntimeError('Setup could not complete. Check your internet connection and open data/setup.log for the error.')

def ready():
    if not PYTHON.exists():return False
    try:
        p=subprocess.run([str(PYTHON),'-c',f"import PySide6; from PySide6.QtWebEngineWidgets import QWebEngineView; assert PySide6.__version__=='{VERSION}'"],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=FLAGS,timeout=25)
        return p.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def launch():
    executable=PYTHONW if PYTHONW.exists() else PYTHON
    (ROOT/'data').mkdir(exist_ok=True)
    with (ROOT/'data'/'desktop-startup.log').open('a',encoding='utf-8') as log:
        subprocess.Popen([str(executable),str(ROOT/'desktop.py')],cwd=ROOT,stdout=log,stderr=log,creationflags=FLAGS,close_fds=True)

def shortcut():
    if os.name!='nt':return None
    # PowerShell reads paths from a JSON manifest, not interpolated executable code.
    if not PYTHONW.exists():return False
    info={'root':str(ROOT),'pythonw':str(PYTHONW),'bootstrap':str(ROOT/'bootstrap.py'),'icon':str(ROOT/'assets'/'autoparts.ico')}
    manifest=ROOT/'data'/'shortcut.json';manifest.write_text(json.dumps(info),encoding='utf-8')
    ps=ROOT/'create_shortcut.ps1'
    with (ROOT/'data'/'setup.log').open('a',encoding='utf-8') as log:
        p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ps),'-Manifest',str(manifest)],cwd=ROOT,stdout=log,stderr=log,creationflags=FLAGS)
    return p.returncode==0

def main():
    try:
        import tkinter as tk
        from tkinter import messagebox,ttk
    except ImportError:
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(0,'Install Python 3.11+ with Tcl/Tk and pip enabled, then open AutoParts Pro.vbs again.','AutoParts Pro',16)
        return 1
    if not (3,11)<=sys.version_info[:2]<(3,15) or sys.maxsize<2**32:
        win=tk.Tk();win.withdraw();messagebox.showerror('Python required','Install 64-bit Python 3.11–3.14, then open AutoParts Pro.vbs again.');win.destroy();return 1
    (ROOT/'data').mkdir(exist_ok=True)
    if '--shortcut-only' in sys.argv:
        win=tk.Tk();win.withdraw()
        if shortcut():messagebox.showinfo('AutoParts Pro','Desktop icon created. Keep the extracted folder in this location.')
        else:messagebox.showerror('Shortcut could not be created','Open AutoParts Pro.vbs from this folder. See data/setup.log.')
        win.destroy();return 0
    if ready():
        launch();return 0
    win=tk.Tk();win.title('AutoParts Pro · Setup');win.geometry('570x410');win.resizable(False,False);win.configure(bg='#101a2d')
    try:win.iconbitmap(str(ROOT/'assets'/'autoparts.ico'))
    except Exception:pass
    frame=tk.Frame(win,bg='#101a2d',padx=36,pady=30);frame.pack(fill='both',expand=True)
    tk.Label(frame,text='AUTOPARTS  PRO',font=('Segoe UI',12,'bold'),fg='#60a5fa',bg='#101a2d').pack(anchor='w')
    tk.Label(frame,text='Your parts. One desktop.',font=('Segoe UI',25,'bold'),fg='#f3f7ff',bg='#101a2d').pack(anchor='w',pady=(12,8))
    tk.Label(frame,text='First setup downloads the desktop engine.\nKeep internet connected. Billing works offline afterwards.\nNo Chrome or command window is needed.',justify='left',font=('Segoe UI',11),fg='#9cadc9',bg='#101a2d').pack(anchor='w',pady=(0,15))
    status=tk.StringVar(value='Ready to install · May take a few minutes')
    tk.Label(frame,textvariable=status,wraplength=490,justify='left',fg='#d5e2f6',bg='#101a2d',font=('Segoe UI',10)).pack(anchor='w',pady=8)
    progress=ttk.Progressbar(frame,mode='indeterminate');progress.pack(fill='x',pady=(8,18))
    messages=queue.Queue();busy=False
    def worker():
        try:
            with (ROOT/'data'/'setup.log').open('a',encoding='utf-8') as log:
                messages.put(('status','Creating a private desktop runtime…'))
                if not PYTHON.exists():run([sys.executable,'-m','venv',str(ENV)],log)
                messages.put(('status','Downloading and installing desktop engine…'))
                run([PYTHON,'-m','pip','install','--disable-pip-version-check',f'PySide6=={VERSION}'],log)
            if not ready():raise RuntimeError('Desktop engine check failed. See data/setup.log.')
            messages.put(('status','Creating your desktop icon…'))
            created=shortcut();launch();messages.put(('done',created))
        except Exception as e:messages.put(('error',str(e)))
    def begin():
        nonlocal busy
        busy=True;button.config(state='disabled');progress.start(12);threading.Thread(target=worker,daemon=True).start()
    def poll():
        nonlocal busy
        while True:
            try:kind,value=messages.get_nowait()
            except queue.Empty:break
            if kind=='status':status.set(value)
            elif kind=='done':
                progress.stop();busy=False
                if value is False:messagebox.showwarning('App installed','The desktop shortcut could not be created. Open AutoParts Pro.vbs from this folder; see data/setup.log.')
                win.destroy();return
            else:
                progress.stop();busy=False;button.config(state='normal',text='Retry setup');status.set('Setup needs attention');messagebox.showerror('Setup could not finish',value)
        win.after(150,poll)
    def close():
        if busy:messagebox.showinfo('Setup is running','Wait for setup to finish. Do not move the folder during installation.')
        else:win.destroy()
    button=tk.Button(frame,text='Install & open AutoParts Pro',command=begin,bg='#c97f22',fg='white',activebackground='#a96317',activeforeground='white',font=('Segoe UI',11,'bold'),relief='flat',padx=14,pady=11,cursor='hand2');button.pack(fill='x')
    win.protocol('WM_DELETE_WINDOW',close);win.after(150,poll);win.mainloop();return 0

if __name__=='__main__':raise SystemExit(main())
