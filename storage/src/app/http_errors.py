from __future__ import annotations

from fastapi import HTTPException, status


def not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")
