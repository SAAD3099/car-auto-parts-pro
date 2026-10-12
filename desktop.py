"""AutoParts Pro native window: Qt WebEngine, no browser tab and no console."""
from __future__ import annotations
import ctypes, hashlib, logging, os, sys, threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main(test_hook=None):
    from PySide6.QtCore import QMarginsF, QSizeF, Qt, QUrl
    from PySide6.QtGui import QAction,QIcon,QKeySequence,QPageLayout,QPageSize
    from PySide6.QtNetwork import QLocalServer,QLocalSocket
    from PySide6.QtPrintSupport import QPrinter,QPrintDialog
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineDownloadRequest
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication,QFileDialog,QMainWindow,QMessageBox
    import core as db
    from app_lock import workspace_lock
    from maintenance import snapshot
    from server import Handler,ThreadingHTTPServer

    db.DATA.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=db.DATA/'desktop.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',force=True)
    if os.name=='nt':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AutoParts.Pro.Desktop.2')
    app=QApplication(sys.argv)
    app.setApplicationName('AutoParts Pro');app.setApplicationVersion('4.0');app.setOrganizationName('AutoParts')
    app.setWindowIcon(QIcon(str(ROOT/'assets'/'autoparts.ico')))
    app.setStyle('Fusion')
    app.setStyleSheet('QMenuBar,QMenu,QStatusBar {font-family: Segoe UI; background:#101a2d;color:#c7d4ea;} QMenuBar::item:selected,QMenu::item:selected {background:#2563eb;} QMenu {padding:6px;} QStatusBar {font-size:11px;}')
    name='AutoParts-'+hashlib.sha256(str(db.DATA.resolve()).encode()).hexdigest()[:20]
    activation=QLocalSocket();activation.connectToServer(name)
    if activation.waitForConnected(500):
        activation.write(b'activate');activation.waitForBytesWritten(500);activation.disconnectFromServer();return 0
    QLocalServer.removeServer(name)
    local=QLocalServer()
    if not local.listen(name):
        logging.warning('Activation channel unavailable: %s. Workspace lock still protects records.',local.errorString())

    class StorePage(QWebEnginePage):
        def acceptNavigationRequest(self,url,nav_type,is_main_frame):
            # Keep this private app in its own workspace. No arbitrary sites.
            return url.scheme()=='about' or (url.scheme()=='http' and url.host()=='127.0.0.1' and url.port()==self.local_port)
        def createWindow(self,window_type):return None

    class Window(QMainWindow):
        def __init__(self,server):
            super().__init__();self.setWindowTitle('AutoParts Pro — Automotive Command Center')
            self.setWindowIcon(app.windowIcon());self.resize(1440,960);self.setMinimumSize(1000,700)
            self.profile=QWebEngineProfile('AutoPartsDesktop',app)
            self.profile.setPersistentStoragePath(str(db.DATA/'desktop-profile'))
            self.profile.setCachePath(str(db.DATA/'desktop-cache'))
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            self.view=QWebEngineView(self)
            self.page=StorePage(self.profile,self.view);self.page.local_port=server.server_port
            self.view.setPage(self.page);self.setCentralWidget(self.view)
            self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.profile.downloadRequested.connect(self.download)
            self.view.printRequested.connect(self.print_document)
            self.view.printFinished.connect(self.print_finished)
            self.view.loadFinished.connect(self.loaded)
            self.printer=None;self.downloads=[]
            view_menu=self.menuBar().addMenu('View')
            refresh=QAction('Refresh workspace',self);refresh.setShortcut(QKeySequence('Ctrl+R'));refresh.triggered.connect(self.view.reload);view_menu.addAction(refresh)
            fullscreen=QAction('Full screen',self);fullscreen.setShortcut(QKeySequence('F11'));fullscreen.triggered.connect(lambda:self.showNormal() if self.isFullScreen() else self.showFullScreen());view_menu.addAction(fullscreen)
            zoomin=QAction('Larger text',self);zoomin.setShortcut(QKeySequence('Ctrl+='));zoomin.triggered.connect(lambda:self.view.setZoomFactor(min(1.5,self.view.zoomFactor()+.1)));view_menu.addAction(zoomin)
            zoomout=QAction('Smaller text',self);zoomout.setShortcut(QKeySequence('Ctrl+-'));zoomout.triggered.connect(lambda:self.view.setZoomFactor(max(.75,self.view.zoomFactor()-.1)));view_menu.addAction(zoomout)
            help_menu=self.menuBar().addMenu('Help')
            about=QAction('About AutoParts Pro',self);about.triggered.connect(lambda:QMessageBox.information(self,'AutoParts Pro','AutoParts Pro · Desktop Edition v4.0\nAutomotive command center for parts, vehicle fitment, customers and warranties.\n\nSingle local store · Source project\nCloud AI is optional and needs your own API key.\nHardware must be tested before a live shop pilot.'));help_menu.addAction(about)
            self.statusBar().showMessage('DESKTOP EDITION  •  Offline billing  •  F2 Scan  •  F4 Checkout  •  F11 Full screen')
            self.view.load(QUrl(f'http://127.0.0.1:{server.server_port}'))
        def loaded(self,success):
            if not success:QMessageBox.warning(self,'Workspace could not load','Try View → Refresh workspace. If it still fails, close the app and reopen. See data/desktop.log.')
        def download(self,request):
            suggested=request.suggestedFileName() or 'autoparts-export'
            target,_=QFileDialog.getSaveFileName(self,'Save AutoParts export',str(Path.home()/'Downloads'/suggested))
            if not target:request.cancel();return
            p=Path(target);request.setDownloadDirectory(str(p.parent));request.setDownloadFileName(p.name)
            self.downloads.append(request)
            request.isFinishedChanged.connect(lambda:self.download_finished(request))
            request.accept()
        def download_finished(self,request):
            if request.isFinished():
                message='Saved: '+request.downloadFileName() if request.state()==QWebEngineDownloadRequest.DownloadState.DownloadCompleted else 'Download did not complete: '+request.interruptReasonString()
                self.statusBar().showMessage(message,10000)
                if request in self.downloads:self.downloads.remove(request)
        def print_document(self):
            if self.printer is not None:return
            printer=QPrinter(QPrinter.PrinterMode.HighResolution)
            page_size=QPageSize(QSizeF(80,240),QPageSize.Unit.Millimeter,'80 mm receipt')
            printer.setPageLayout(QPageLayout(page_size,QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter))
            dialog=QPrintDialog(printer,self);dialog.setWindowTitle('AutoParts Pro — Print receipt / labels')
            if dialog.exec()==QPrintDialog.DialogCode.Accepted:
                self.printer=printer;self.view.print(printer)
        def print_finished(self,success):
            self.printer=None
            if not success:QMessageBox.warning(self,'Print did not finish','Check the selected printer, driver and paper size. Try printing again.')
        def closeEvent(self,event):
            if self.printer is not None:
                QMessageBox.information(self,'Printing in progress','Wait for printing to finish before closing.');event.ignore();return
            answer=QMessageBox.question(self,'Close AutoParts Pro?','Close the store workspace? Saved records remain safe. Unsaved bills are kept on this device.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:event.accept()
            else:event.ignore()

    server=None;window=None
    try:
        with workspace_lock():
            if db.DB.exists():
                with db.connect() as c: previous=c.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
                if previous and previous[0]=='2':snapshot('before-upgrade')
            snapshot();db.initialize()
            logging.basicConfig(filename=db.DATA/'desktop.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
            try:server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
            except OSError:server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.daemon_threads=True
            worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.2},daemon=True);worker.start()
            window=Window(server)
            def activate():
                connection=local.nextPendingConnection()
                if connection:connection.close();connection.deleteLater()
                window.showNormal();window.raise_();window.activateWindow()
            local.newConnection.connect(activate)
            window.show()
            if test_hook:test_hook(window,app)
            result=app.exec()
            server.shutdown();server.server_close();worker.join(timeout=2)
            return result
    except Exception as e:
        logging.exception('Desktop startup failed')
        QMessageBox.critical(window,'AutoParts Pro',str(e)+'\n\nSee data/desktop.log. If another copy is running, close it first.');return 1
    finally:
        local.close()
        if server:
            try:server.shutdown();server.server_close()
            except Exception:pass

if __name__=='__main__':raise SystemExit(main())
