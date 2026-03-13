def list_response(
    items: list, limit: int, offset: int, *, total: int | None = None
) -> dict:
    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "total": total if total is not None else len(items),
    }


class ListResponseMixin:
    def list(self, db, *args, **kwargs):
        raise NotImplementedError

    def list_response(self, db, *args, **kwargs):
        if "limit" in kwargs and "offset" in kwargs:
            limit = kwargs["limit"]
            offset = kwargs["offset"]
            result = self.list(db, *args, **kwargs)
        else:
            if len(args) < 2:
                raise ValueError("limit and offset are required for list responses")
            *list_args, limit, offset = args
            result = self.list(db, *list_args, limit=limit, offset=offset, **kwargs)

        if isinstance(result, tuple):
            items, total = result
        else:
            items = result
            total = len(items)
        return list_response(items, limit, offset, total=total)
