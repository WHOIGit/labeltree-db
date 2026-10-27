from ninja import NinjaAPI

api = NinjaAPI(title="labeltree-db", version="1")


@api.get("/health")
def health(request):
    return {"status": "ok"}
