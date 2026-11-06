import uuid
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm
from contracts.errors import IndexUnavailable

ALLOWED = {"user_id", "workspace_id", "project_id", "session_id", "agent_id",
           "tier", "memory_class", "entity_key", "trust", "is_deleted", "is_archived"}

def point_id(memory_id):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, "dxos:" + str(memory_id)))

class QdrantVectorStore:
    def __init__(self, url="http://localhost:6333", collection="gateway_memory_vector", dim=1024):
        self._c = AsyncQdrantClient(url=url)
        self.coll, self.dim = collection, dim

    async def ensure(self):
        if not await self._c.collection_exists(self.coll):
            await self._c.create_collection(
                self.coll,
                vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE),
                on_disk_payload=True,
                hnsw_config=qm.HnswConfigDiff(m=16, ef_construct=200))
            for f in ("workspace_id", "user_id", "entity_key", "memory_class", "trust"):
                await self._c.create_payload_index(
                    self.coll, field_name=f, field_schema=qm.PayloadSchemaType.KEYWORD)

    @staticmethod
    def _filter(f):
        unknown = set(f) - ALLOWED
        if unknown:
            raise IndexUnavailable("未知过滤键，拒绝执行以免越权: %s" % sorted(unknown))
        must = [qm.FieldCondition(key=k, match=qm.MatchValue(value=v))
                for k, v in f.items() if v is not None]
        if "is_deleted" not in f:
            must.append(qm.FieldCondition(key="is_deleted", match=qm.MatchValue(value=False)))
        return qm.Filter(must=must)

    async def upsert(self, memory_id, vector, payload):
        await self._c.upsert(self.coll, points=[
            qm.PointStruct(id=point_id(memory_id), vector=vector, payload=payload)])

    async def search(self, vector, top_k, flt):
        try:
            r = await self._c.query_points(self.coll, query=vector, limit=top_k,
                                           query_filter=self._filter(flt))
        except Exception as e:
            raise IndexUnavailable("向量检索失败: %s" % str(e)[:120])
        return [{"id": h.payload.get("memory_id", str(h.id)), "score": h.score,
                 "payload": h.payload} for h in r.points]

    async def delete(self, memory_id):
        await self._c.delete(self.coll, points_selector=qm.PointIdsList(points=[point_id(memory_id)]))
