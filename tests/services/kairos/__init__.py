"""Test package for the kairos / brief scheduling service layer.

Kept empty on purpose — the package marker exists so pytest's rootdir
collection does not pull sibling ``tests/services/*/test_models.py``
modules into this package's test_models collection (we hit a name
collision with templates / pipe_ipc / context_collapse / computer_use
earlier). Putting a real import here would defeat the namespace
isolation, so leave it bare.
"""
