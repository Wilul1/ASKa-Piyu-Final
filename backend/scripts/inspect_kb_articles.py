"""Print draft / RAG-stale / audience breakdown for published_articles (read-only)."""

from __future__ import annotations

from sqlalchemy import func

from app.config import settings
from app.db.session import get_session_factory
from app.models.db_models import PublishedArticle


def main() -> None:
    print("db configured:", bool(settings.database_url))
    print("database:", (settings.database_url or "").split("@")[-1])
    session = get_session_factory()()
    try:
        total = session.query(func.count(PublishedArticle.id)).scalar() or 0
        pub = (
            session.query(func.count(PublishedArticle.id))
            .filter(PublishedArticle.published.is_(True))
            .scalar()
            or 0
        )
        draft = (
            session.query(func.count(PublishedArticle.id))
            .filter(PublishedArticle.published.is_(False))
            .scalar()
            or 0
        )
        stale = (
            session.query(func.count(PublishedArticle.id))
            .filter(
                PublishedArticle.published.is_(True),
                PublishedArticle.rag_indexed.is_(False),
            )
            .scalar()
            or 0
        )
        print(f"total={total} published={pub} drafts={draft} published_rag_stale={stale}")
        print("--- all articles ---")
        for art in session.query(PublishedArticle).order_by(PublishedArticle.title.asc()):
            title = (art.title or "")[:70]
            print(
                f"  pub={art.published} rag={art.rag_indexed} aud={art.audience!r} "
                f"origin={art.kb_origin!r} | {title}"
            )

        try:
            from app.services.chroma_store import get_knowledge_base_store

            store = get_knowledge_base_store()
            print(f"chroma chunk_count={store.chunk_count}")
        except Exception as exc:
            print(f"chroma unavailable: {exc}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
