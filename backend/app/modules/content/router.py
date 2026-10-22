from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from slugify import slugify
from sqlalchemy import select

from app.core.errors import Conflict, NotFound
from app.modules.auth.deps import AdminUser, SessionDep
from app.modules.content.models import Post
from app.modules.content.schemas import PostIn, PostOut, PostSummary

router = APIRouter(prefix="/posts", tags=["content"])


def _published():
    return select(Post).where(
        Post.published_at.is_not(None), Post.published_at <= datetime.now(UTC)
    )


@router.get("", response_model=list[PostSummary])
async def list_posts(
    session: SessionDep,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
):
    stmt = _published().order_by(Post.published_at.desc()).limit(limit).offset(offset)
    return (await session.scalars(stmt)).all()


@router.get("/{slug}", response_model=PostOut)
async def get_post(slug: str, session: SessionDep):
    post = await session.scalar(_published().where(Post.slug == slug))
    if not post:
        raise NotFound("Không tìm thấy bài viết")
    return post


# --- Admin ---
admin_router = APIRouter(prefix="/admin/posts", tags=["admin: content"])


async def _save(session: SessionDep, data: PostIn, post: Post | None = None) -> Post:
    values = data.model_dump()
    values["slug"] = slugify(data.slug or data.title)
    clash = await session.scalar(select(Post).where(Post.slug == values["slug"]))
    if clash and (post is None or clash.id != post.id):
        raise Conflict("Slug đã tồn tại")
    if post is None:
        post = Post(**values)
        session.add(post)
    else:
        for k, v in values.items():
            setattr(post, k, v)
    await session.commit()
    await session.refresh(post)
    return post


@admin_router.get("", response_model=list[PostSummary])
async def admin_list_posts(_: AdminUser, session: SessionDep):
    return (await session.scalars(select(Post).order_by(Post.id.desc()))).all()


@admin_router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED)
async def create_post(data: PostIn, _: AdminUser, session: SessionDep):
    return await _save(session, data)


@admin_router.put("/{post_id}", response_model=PostOut)
async def update_post(post_id: int, data: PostIn, _: AdminUser, session: SessionDep):
    post = await session.get(Post, post_id)
    if not post:
        raise NotFound("Không tìm thấy bài viết")
    return await _save(session, data, post)
