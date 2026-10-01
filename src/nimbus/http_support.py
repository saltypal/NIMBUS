"""Shared transport errors. Domain modules do not depend on FastAPI."""

from fastapi import Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from .errors import NimbusError


def install_handlers(app):
    @app.exception_handler(NimbusError)
    async def domain_error(request: Request, error: NimbusError):
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {"code": error.code, "message": error.message, "details": error.details}
            },
        )

    @app.exception_handler(PyMongoError)
    async def database_error(request: Request, error: PyMongoError):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "MongoDB is unavailable. Start the database and retry.",
                }
            },
        )
