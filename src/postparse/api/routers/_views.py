"""Convert :mod:`postparse.services.query` views into API response schemas."""

from __future__ import annotations

import dataclasses
from typing import Any

from postparse.api.schemas import InstagramPostSchema, TelegramMessageSchema
from postparse.api.schemas.items import (
    ClassificationSchema,
    ItemDetailResponse,
    ItemSchema,
    LinkSchema,
    MediaSchema,
    SummaryResponse,
    TranscriptMediaSchema,
    TranscriptResponse,
    TranscriptSchema,
)
from postparse.core.db.models import InstagramDetail, Media, Summary, TelegramDetail, Transcript
from postparse.services.query import ItemDetail, ItemView
from postparse.summarization.schemas import parse_summary_text

__all__ = [
    "instagram_post",
    "item_detail",
    "item_schema",
    "summary_response",
    "telegram_message",
    "transcript_response",
]


def item_schema(view: ItemView) -> ItemSchema:
    """List representation of an item."""
    return ItemSchema(
        id=view.id,
        source=view.source,
        external_id=view.external_id,
        kind=view.kind,
        text=view.text,
        author=view.author,
        url=view.url,
        created_at=view.created_at,
        collected_at=view.collected_at,
        sort_at=view.sort_at,
        tags=list(view.tags),
        labels={name: list(labels) for name, labels in view.labels.items()},
        snippet=view.snippet,
    )


def _transcript(t: Transcript) -> TranscriptSchema:
    return TranscriptSchema(
        id=t.id, backend=t.backend, model=t.model, language=t.language, text=t.text,
        segments=t.segments, duration_s=t.duration_s, created_at=t.created_at,
    )


def summary_response(summary: Summary) -> SummaryResponse:
    """Split a stored summary into summary text and key points."""
    text, points = parse_summary_text(summary.text)
    return SummaryResponse(
        item_id=summary.item_id, summary=text, key_points=points,
        provider=summary.provider, model=summary.model, created_at=summary.created_at,
    )


def item_detail(detail: ItemDetail) -> ItemDetailResponse:
    """Full representation of one item."""
    base = item_schema(detail.item).model_dump()
    extra: dict[str, Any] | None = None
    if detail.instagram is not None:
        extra = {"instagram": dataclasses.asdict(detail.instagram)}
    elif detail.telegram is not None:
        extra = {"telegram": dataclasses.asdict(detail.telegram)}
    segments: list[Any] = []
    for view in detail.media:
        if view.transcript is not None and isinstance(view.transcript.segments, list):
            segments.extend(view.transcript.segments)
    return ItemDetailResponse(
        **base,
        detail=extra,
        media=[
            MediaSchema(
                id=v.media.id, position=v.media.position, media_type=v.media.media_type,
                local_path=v.media.local_path, remote_url=v.media.remote_url,
                mime=v.media.mime, duration_s=v.media.duration_s,
                transcript_status=v.media.transcript_status, attempts=v.media.attempts,
                last_error=v.media.last_error, has_transcript=v.transcript is not None,
            )
            for v in detail.media
        ],
        transcript=detail.transcript_text,
        transcript_segments=segments,
        summary=summary_response(detail.summary) if detail.summary else None,
        links=[
            LinkSchema(
                id=lv.link.id, url=lv.link.url, domain=lv.link.domain,
                fetcher=lv.fetch.fetcher if lv.fetch else None,
                status=lv.fetch.status if lv.fetch else None,
                title=lv.fetch.title if lv.fetch else None,
                text=lv.fetch.text if lv.fetch else None,
                fetched_at=lv.fetch.fetched_at if lv.fetch else None,
            )
            for lv in detail.links
        ],
        classifications=[
            ClassificationSchema(
                taxonomy=c.taxonomy, status=c.status, labels=list(c.labels),
                confidence=c.confidence, reasoning=c.reasoning, provider=c.provider,
                model=c.model, run_id=c.run_id, result_id=c.result_id,
                created_at=c.created_at,
            )
            for c in detail.classifications
        ],
    )


def transcript_response(detail: ItemDetail) -> TranscriptResponse:
    """Transcripts of all media of an item."""
    return TranscriptResponse(
        item_id=detail.item.id,
        text=detail.transcript_text,
        media=[
            TranscriptMediaSchema(
                media_id=v.media.id, position=v.media.position, media_type=v.media.media_type,
                transcript_status=v.media.transcript_status,
                transcript=_transcript(v.transcript) if v.transcript else None,
            )
            for v in detail.media
        ],
    )


def _split_tags(tags: tuple[str, ...] | list[str]) -> tuple[list[str], list[str]]:
    """``#a``/``@b`` display names -> (hashtags, mentions) without prefixes."""
    hashtags = [t[1:] for t in tags if t.startswith("#")]
    mentions = [t[1:] for t in tags if t.startswith("@")]
    return hashtags, mentions


def instagram_post(
    view: ItemView, ig: InstagramDetail | None, media: list[Media]
) -> InstagramPostSchema:
    """Legacy Instagram post representation of a schema v2 item."""
    hashtags, mentions = _split_tags(view.tags)
    first = media[0] if media else None
    return InstagramPostSchema(
        shortcode=ig.shortcode if ig else view.external_id,
        owner_username=view.author,
        caption=view.text,
        is_video=view.kind == "video" or any(m.media_type == "video" for m in media),
        media_url=(first.remote_url if first else None),
        likes=max(0, (ig.likes if ig else 0) or 0),
        comments=max(0, (ig.comments if ig else 0) or 0),
        hashtags=hashtags,
        mentions=mentions,
        created_at=view.created_at,
        extracted_at=view.collected_at,
        metadata={
            "item_id": view.id,
            "kind": view.kind,
            "url": view.url,
            "typename": ig.typename if ig else None,
            "date_status": ig.date_status if ig else None,
            "labels": {k: list(v) for k, v in view.labels.items()},
            "media_count": len(media),
        },
    )


def _message_id(view: ItemView, tg: TelegramDetail | None) -> int:
    if tg is not None:
        return tg.message_id
    _, _, tail = view.external_id.rpartition(":")
    return int(tail) if tail.lstrip("-").isdigit() else 0


def telegram_message(
    view: ItemView, tg: TelegramDetail | None, media: list[Media]
) -> TelegramMessageSchema:
    """Legacy Telegram message representation of a schema v2 item."""
    hashtags, mentions = _split_tags(view.tags)
    return TelegramMessageSchema(
        message_id=_message_id(view, tg),
        channel_username=view.author,
        content=view.text,
        content_type=view.kind,
        media_urls=[m.remote_url or m.local_path for m in media if m.remote_url or m.local_path],
        hashtags=hashtags,
        mentions=mentions,
        created_at=view.created_at,
        extracted_at=view.collected_at,
        metadata={
            "item_id": view.id,
            "chat_id": tg.chat_id if tg else None,
            "views": tg.views if tg else None,
            "forwards": tg.forwards if tg else None,
            "url": view.url,
            "labels": {k: list(v) for k, v in view.labels.items()},
        },
    )
