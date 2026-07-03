from logging_config import get_logger

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from services.qdrant_services import get_qdrant_client_instance

logger = get_logger()


def _dict_filter_to_qdrant_filter(filters: dict | None) -> Filter | None:
    """Convert REST-style Qdrant filter dicts to qdrant_client Filter models."""
    if not filters:
        return None

    must_conditions: list[FieldCondition] = []
    for condition in filters.get("must", []):
        key = condition.get("key")
        match = condition.get("match") or {}
        if not key:
            continue
        if "value" in match:
            must_conditions.append(FieldCondition(key=key, match=MatchValue(value=match["value"])))
        elif "any" in match:
            must_conditions.append(FieldCondition(key=key, match=MatchAny(any=match["any"])))

    return Filter(must=must_conditions) if must_conditions else None


def _scored_points_to_results(points: list) -> list[dict]:
    """Normalize AsyncQdrantClient search hits to the legacy REST response shape."""
    results = []
    for point in points:
        payload = dict(point.payload) if point.payload else {}
        results.append({
            "id": point.id,
            "score": point.score,
            "payload": payload,
        })
    return results


async def search_qdrant_collection(
    collection_name: str,
    vector: list,
    filters: dict = None,
    limit: int = 10,
    with_payload: bool = True,
):
    """
    Search for similar points in a Qdrant collection using the shared AsyncQdrantClient.

    Reuses the singleton client initialized at startup (no per-request httpx client).
    """
    try:
        client = get_qdrant_client_instance()
        response = await client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=_dict_filter_to_qdrant_filter(filters),
            limit=limit,
            with_payload=with_payload,
        )
        search_results = _scored_points_to_results(response.points)
        logger.info(f"Found {len(search_results)} results in collection '{collection_name}'")
        return search_results

    except Exception as e:
        logger.error(f"Error searching collection '{collection_name}': {e}")
        return []


async def delete_qdrant_points_by_filter(collection_name: str, filters: dict):
    """
    Delete all points in a Qdrant collection that match the given filters.

    Uses the shared AsyncQdrantClient (same connection pool as search).
    """
    try:
        qdrant_filter = _dict_filter_to_qdrant_filter(filters)
        if qdrant_filter is None:
            return {"success": False, "message": "No valid filters provided for delete."}

        client = get_qdrant_client_instance()
        result = await client.delete(
            collection_name=collection_name,
            points_selector=qdrant_filter,
        )

        logger.info(f"Successfully deleted points from collection '{collection_name}' with filters: {filters}")
        return {
            "success": True,
            "message": f"Points deleted successfully from collection '{collection_name}'",
            "result": result,
        }

    except Exception as e:
        error_msg = f"Error deleting points from collection '{collection_name}': {e}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg,
        }
