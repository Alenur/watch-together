class AppError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def unauthenticated() -> AppError:
    return AppError(401, "unauthenticated", "Войдите в аккаунт.")
