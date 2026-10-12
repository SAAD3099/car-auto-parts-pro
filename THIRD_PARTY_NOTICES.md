# Third-party components

The application's original Python/HTML/CSS/JavaScript and icon assets use the included MIT license. The first-run installer downloads **PySide6 6.10.2**, including its Qt Essentials, Qt Addons and Shiboken dependencies, from the Python package registry. Those dependencies and Qt WebEngine/Chromium components are governed by their own licenses and notices, not this project's MIT license.

The project ZIP does not contain the downloaded Qt runtime. Its installed package metadata, licenses and notices are retained in `.desktop-runtime`. Review the dependency licenses before repackaging or distributing a compiled binary.

Official package/documentation:

- https://pypi.org/project/PySide6/6.10.2/
- https://doc.qt.io/qtforpython-6/gettingstarted.html
- https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineWidgets/QWebEngineView.html
