"""Projeye ozel hata siniflari."""

class BrowserStateError(Exception):
    def __init__(self, message: str, code: str, status: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

class BrowserAuthError(BrowserStateError):
    pass
