"""Export helpers for the Telegram MCP (read-only) server."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Union

from datetime import datetime, timezone

from telethon.tl.types import PeerChannel, PeerChat
from telethon.tl import types as tl_types
from telethon.tl.functions.channels import GetForumTopicsRequest

from toon_format import encode as toon_encode
from toon_format.primitives import encode_primitive, join_encoded_values

from mcp.types import CallToolResult, ResourceLink, ToolAnnotations

# Import the main module so globals (client, mcp) are initialised once.
import main as telegram_main

mcp = telegram_main.mcp
list_chats = getattr(telegram_main, "list_chats", None)
get_sender_name = getattr(telegram_main, "get_sender_name", None)

_TOON_NULL_SENTINEL = "__TOON_NULL__:__"
_TOON_NULL_SENTINEL_ENCODED = f"\"{_TOON_NULL_SENTINEL}\""


def _llm_meta_comments() -> list[str]:
    # Legacy helper; kept for compatibility with older code paths.
    return [
        "migrated_to_chat_id: present only when this chat_id is a legacy group migrated to a supergroup (new chat_id).",
        "migrated_from_chat_id: present only when this chat_id is a supergroup migrated from a legacy group (old chat_id).",
        "threads: in forum chats, messages use `topic` (topics[].id).",
        "reply_to_id: message id being replied to. In forum chats it is within the same `topic`.",
    ]


def _drop_none_fields(d: dict) -> dict:
    # Keep insertion order of the original dict.
    return {k: v for k, v in d.items() if v is not None}


def _practicants_for_toon(practicants: list[dict]) -> list[dict]:
    out: list[dict] = []
    for p in practicants or []:
        pp = dict(p)
        uname = pp.get("username")
        if uname:
            su = str(uname)
            if not su.startswith("@"):
                pp["username"] = f"@{su}"
        for k, v in pp.items():
            if v is None:
                pp[k] = _TOON_NULL_SENTINEL
        out.append(pp)
    return out


def _render_toon_meta(meta: dict) -> str:
    meta_filtered = _drop_none_fields(meta)
    llm_notes = meta_filtered.pop("llm_notes", None)

    rendered = toon_encode(meta_filtered).rstrip()
    # Replace the quoted sentinel with an empty field (keeps delimiters in tabular rows).
    rendered = rendered.replace(_TOON_NULL_SENTINEL_ENCODED, "")
    out = f"{rendered}\n" if rendered else ""

    if llm_notes is not None:
        notes = dict(llm_notes or {})
        if notes:
            out += "llm_notes:\n"
            for k, v in notes.items():
                vv = str(v).replace("\r", "").replace("\n", "\\n")
                out += f"  {k}: {vv}\n"

    return out


def _indent_lines(text: str, prefix: str) -> str:
    # Preserve newlines; indent every non-empty line.
    return "".join((prefix + line if line.strip() else line) for line in text.splitlines(True))


def _encode_toon_row(values: list) -> str:
    encoded_values = [encode_primitive(v) for v in values]
    row = join_encoded_values(encoded_values, ",")
    return row.replace(_TOON_NULL_SENTINEL_ENCODED, "")


def _parse_date_bounds(from_date: str | None, to_date: str | None):
    from_date_obj = None
    to_date_obj = None

    if from_date:
        from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if to_date:
        # Inclusive end-of-day upper bound
        to_date_obj = (
            datetime.strptime(to_date, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .replace(hour=23, minute=59, second=59, microsecond=999999)
        )

    return from_date_obj, to_date_obj


def _safe_int_id(v: Union[int, str]) -> Union[int, str]:
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if s and (s.isdigit() or (s.startswith("-") and s[1:].isdigit())):
        try:
            return int(s)
        except Exception:
            return v
    return v


async def _resolve_entity(chat_id: Union[int, str]):
    """Resolve a chat/channel/user entity as robustly as possible.

    Telethon treats a bare positive integer as a user id by default. For channels and
    basic groups we sometimes need to provide an explicit Peer type, or fall back to
    scanning dialogs when the entity is not in the input-entity cache.
    """

    client = telegram_main.client

    # 1) Direct resolution (works for usernames, or when the ID is in cache).
    try:
        return await client.get_entity(chat_id)
    except Exception as first_err:
        last_err = first_err

    # 2) For numeric IDs, try explicit peer types.
    if isinstance(chat_id, int):
        for peer in (PeerChannel(chat_id), PeerChat(chat_id)):
            try:
                return await client.get_entity(peer)
            except Exception as e:
                last_err = e

        # 3) As a last resort, scan dialogs to find the entity by id.
        # This covers the case where the chat exists but hasn't been cached yet.
        try:
            async for dialog in client.iter_dialogs():
                ent = getattr(dialog, "entity", None)
                ent_id = getattr(ent, "id", None)
                if ent_id == chat_id:
                    return ent
        except Exception as e:
            last_err = e

    raise last_err


def _entity_kind(entity) -> str | None:
    if isinstance(entity, tl_types.Channel):
        return "channel"
    if isinstance(entity, tl_types.Chat):
        return "chat"
    if isinstance(entity, tl_types.User):
        return "user"
    return None


async def _find_legacy_chat_id_for_channel(channel_id: int) -> int | None:
    """Best-effort reverse mapping: Channel(supergroup) -> legacy Chat(basic group) id."""

    client = telegram_main.client
    try:
        async for dialog in client.iter_dialogs():
            ent = getattr(dialog, "entity", None)
            ent_id = getattr(ent, "id", None)
            migrated_to = getattr(ent, "migrated_to", None)
            migrated_channel_id = getattr(migrated_to, "channel_id", None) if migrated_to else None
            if ent_id is not None and migrated_channel_id == channel_id:
                return int(ent_id)
    except Exception:
        return None
    return None


async def _get_forum_topics(channel_entity, limit: int = 200) -> list[dict]:
    """Best-effort forum topics listing for supergroups with topics enabled."""

    if not getattr(channel_entity, "forum", False):
        return []

    client = telegram_main.client
    topics: list[dict] = []

    # Pagination is usually unnecessary (few topics), but keep it in case there are many.
    offset_date = None
    offset_id = 0
    offset_topic = 0

    while len(topics) < max(1, limit):
        batch = min(100, limit - len(topics))
        try:
            res = await client(
                GetForumTopicsRequest(
                    channel=channel_entity,
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=batch,
                    q=None,
                )
            )
        except Exception:
            break

        page = getattr(res, "topics", None) or []
        if not page:
            break

        for t in page:
            dt = getattr(t, "date", None)
            topics.append(
                {
                    "id": getattr(t, "id", None),
                    "title": getattr(t, "title", None),
                    "pinned": getattr(t, "pinned", None),
                    "closed": getattr(t, "closed", None),
                    "date": dt.isoformat() if dt else None,
                    "top_message_id": getattr(t, "top_message", None),
                }
            )

        last = page[-1]
        offset_date = getattr(last, "date", None)
        offset_id = getattr(last, "top_message", 0) or 0
        offset_topic = getattr(last, "id", 0) or 0

        if len(page) < batch:
            break

    return topics


async def _maybe_expand_migrated_chat_ids(chat_ids: List[Union[int, str]]):
    """Expand input chat_ids with migrated counterparts when possible.

    Ordering rule:
    - If a basic group was migrated to a supergroup, export the legacy group first,
      then the migrated supergroup.
    - For unrelated chats, keep the relative order of first appearance.
    """

    families: dict[Union[int, str], dict] = {}
    family_order: List[Union[int, str]] = []

    def _ensure_family(key: Union[int, str]) -> dict:
        if key not in families:
            families[key] = {
                "channel_id": None,
                "legacy_chat_id": None,
                "fallback_id": key,
            }
            family_order.append(key)
        return families[key]

    for raw in chat_ids or []:
        cid = _safe_int_id(raw)

        # Non-numeric ids (usernames etc): treat as standalone.
        if not isinstance(cid, int):
            _ensure_family(cid)
            continue

        try:
            ent = await _resolve_entity(cid)
        except Exception:
            _ensure_family(cid)
            continue

        kind = _entity_kind(ent)
        ent_id = getattr(ent, "id", None)

        if kind == "chat":
            migrated_to = getattr(ent, "migrated_to", None)
            migrated_channel_id = getattr(migrated_to, "channel_id", None) if migrated_to else None
            if migrated_channel_id:
                key = int(migrated_channel_id)
                fam = _ensure_family(key)
                fam["channel_id"] = int(migrated_channel_id)
                fam["legacy_chat_id"] = int(ent_id) if ent_id is not None else int(cid)
            else:
                key = int(ent_id) if ent_id is not None else int(cid)
                fam = _ensure_family(key)
                fam["legacy_chat_id"] = int(ent_id) if ent_id is not None else int(cid)
        elif kind == "channel":
            channel_id = int(ent_id) if ent_id is not None else int(cid)
            fam = _ensure_family(channel_id)
            fam["channel_id"] = channel_id
            legacy = await _find_legacy_chat_id_for_channel(channel_id)
            if legacy is not None:
                fam["legacy_chat_id"] = int(legacy)
        else:
            key = int(ent_id) if ent_id is not None else int(cid)
            _ensure_family(key)

    expanded: List[Union[int, str]] = []
    seen: set[Union[int, str]] = set()

    def _add(v: Union[int, str]):
        if v in seen:
            return
        seen.add(v)
        expanded.append(v)

    for key in family_order:
        fam = families[key]
        channel_id = fam.get("channel_id")
        legacy_chat_id = fam.get("legacy_chat_id")
        fallback_id = fam.get("fallback_id", key)

        if legacy_chat_id is not None and legacy_chat_id != channel_id:
            _add(legacy_chat_id)
        if channel_id is not None:
            _add(channel_id)
        if channel_id is None and legacy_chat_id is None:
            _add(fallback_id)

    return expanded


@mcp.tool(annotations=ToolAnnotations(openWorldHint=True, readOnlyHint=True))
async def export_messages(
    chat_ids: List[Union[int, str]],
    limit: int = 10000,
    search_query: str = None,
    from_date: str = None,
    to_date: str = None,
    chat_names: List[str] = None,
) -> CallToolResult:
    """Export chat messages to ./output/{chat_ids}-telegram.md.

    Notes:
    - Before exporting any specific chat, this tool calls `list_chats` once to warm up
      the Telethon entity cache (so `get_entity(...)` can resolve IDs reliably).
    - `limit=0` means "export full depth" (no limit).
    """

    # Tool warm-up: populate dialog/entity cache so get_entity works reliably.
    if list_chats:
        try:
            await list_chats(limit=1000)
        except Exception:
            # Best-effort warm-up; export should still proceed if possible.
            pass

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    from_date_obj, to_date_obj = _parse_date_bounds(from_date, to_date)

    expanded_chat_ids: List[Union[int, str]] = []
    if chat_ids:
        # If caller passes a migrated basic-group id, automatically export both the
        # legacy group and the migrated supergroup (and vice versa when discoverable).
        expanded_chat_ids = await _maybe_expand_migrated_chat_ids(chat_ids)

    # Output file name should reflect what we actually exported (including migration expansion),
    # so `chat_ids=[489]` and `chat_ids=[489,361]` produce the same output path.
    chat_ids_slug = "_".join(str(cid) for cid in expanded_chat_ids) if expanded_chat_ids else "none"
    if len(chat_ids_slug) > 100:
        chat_ids_slug = f"{chat_ids_slug[:100]}_etc"
    out_path = out_dir / f"{chat_ids_slug}-telegram.md"

    with out_path.open("w", encoding="utf-8") as f:
        # Root array of chat blocks (valid TOON).
        total = len(expanded_chat_ids or [])
        f.write(f"[{total}]:\n")

        if expanded_chat_ids:
            original_chat_names = list(chat_names or [])

            # If a single name was provided but we expanded to multiple chat_ids,
            # keep it for all blocks rather than shifting by index.
            if original_chat_names and len(original_chat_names) == 1 and len(expanded_chat_ids) > 1:
                chat_names = [original_chat_names[0]] * len(expanded_chat_ids)
            elif original_chat_names and len(original_chat_names) == len(expanded_chat_ids):
                chat_names = original_chat_names
            else:
                chat_names = None

            for idx, raw_chat_id in enumerate(expanded_chat_ids):
                chat_id = _safe_int_id(raw_chat_id)
                name_override = None
                if chat_names and idx < len(chat_names):
                    name_override = chat_names[idx] or None

                # Each chat block is a list item object; `chat_id` is its first field.
                f.write(f"  - chat_id: {encode_primitive(chat_id)}\n")

                try:
                    entity = await _resolve_entity(chat_id)

                    # Chat name
                    name = getattr(entity, "title", None)
                    if not name and hasattr(entity, "first_name"):
                        first = getattr(entity, "first_name", None) or ""
                        last = getattr(entity, "last_name", None) or ""
                        name = f"{first} {last}".strip() or None
                    if not name and name_override:
                        name = name_override

                    # Participants (best-effort; may require permissions for large groups/channels)
                    practicants = []
                    practicants_by_id = {}
                    practicants_info_by_id = {}

                    try:
                        if hasattr(entity, "title"):
                            parts = await telegram_main.client.get_participants(entity)
                        else:
                            parts = [entity]

                        for p in parts:
                            pid = getattr(p, "id", None)
                            uname = getattr(p, "username", None)
                            first = getattr(p, "first_name", None)
                            last = getattr(p, "last_name", None)
                            practicants.append(
                                {
                                    "id": pid,
                                    "username": uname,
                                    "firtsName": first,
                                    "lastName": last,
                                }
                            )
                            display = (f"{first or ''} {last or ''}").strip() or (uname or None)
                            if pid is not None and display:
                                practicants_by_id[int(pid)] = display
                            if pid is not None:
                                practicants_info_by_id[int(pid)] = {
                                    "username": uname,
                                    "firtsName": first,
                                    "lastName": last,
                                }
                    except Exception:
                        practicants = []
                        practicants_by_id = {}
                        practicants_info_by_id = {}


                    migrated_to = getattr(entity, "migrated_to", None)
                    migrated_to_channel_id = (
                        getattr(migrated_to, "channel_id", None) if migrated_to else None
                    )
                    kind = _entity_kind(entity)
                    migrated_from_chat_id = None
                    canonical_chat_id = getattr(entity, "id", None)
                    topics = None

                    if kind == "chat" and migrated_to_channel_id:
                        canonical_chat_id = int(migrated_to_channel_id)
                    elif kind == "channel":
                        migrated_from_chat_id = await _find_legacy_chat_id_for_channel(int(entity.id))
                        topics_list = await _get_forum_topics(entity)
                        topics = topics_list if topics_list else None

                    include_topic = bool(getattr(entity, "forum", False))

                    # Field notes for LLMs (TOON does not support comments).
                    llm_notes: dict[str, str] = {}
                    if migrated_from_chat_id:
                        llm_notes["migrated_from_chat_id"] = (
                            "Only present when this chat_id is a supergroup migrated from a legacy group (old chat_id)."
                        )
                    if migrated_to_channel_id:
                        llm_notes["migrated_to_chat_id"] = (
                            "Only present when this chat_id is a legacy group migrated to a supergroup (new chat_id)."
                        )
                    if include_topic:
                        llm_notes["threads"] = "In forum chats, messages use `topic` (topics[].id) to identify threads."
                    llm_notes["reply_to_id"] = (
                        "For replies, this is the replied message id. In forum chats it is within the same `topic`."
                    )

                    meta = {
                        "kind": kind,
                        "type": "Telegram chat",
                        "name": name,
                        "topics": topics,
                        "practicants": _practicants_for_toon(practicants),
                        "canonical_chat_id": canonical_chat_id,
                        "migrated_from_chat_id": int(migrated_from_chat_id)
                        if migrated_from_chat_id
                        else None,
                        "migrated_to_chat_id": int(migrated_to_channel_id)
                        if migrated_to_channel_id
                        else None,
                        "llm_notes": llm_notes or None,
                    }
                    f.write(_indent_lines(_render_toon_meta(meta), "    "))

                    # Messages export (TOON tabular).
                    #
                    # Only include `topic` column for forum chats (supergroups with topics).
                    # For regular chats/groups it is always empty and adds noise.
                    msg_fields = [
                        "id",
                        "date",
                        *(
                            ["topic"]
                            if include_topic
                            else []
                        ),
                        "user_id",
                        "username",
                        "firtsName",
                        "lastName",
                        "reply_to_id",
                        "message",
                    ]

                    msg_count = 0
                    tmp_path = None
                    sender_cache: dict[int, dict] = {}

                    iter_kwargs = {}
                    if search_query:
                        # Do not combine offset_date with search; filter date bounds client-side.
                        iter_kwargs["search"] = search_query

                    full_depth = limit == 0
                    reverse_rows = not full_depth

                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w",
                            encoding="utf-8",
                            delete=False,
                            dir=out_dir,
                            prefix=f"tmp-messages-{chat_id}-",
                            suffix=".txt",
                        ) as tf:
                            tmp_path = tf.name

                            iter_args = dict(iter_kwargs)
                            if full_depth:
                                iter_args["reverse"] = True  # oldest -> newest streaming

                            async for msg in telegram_main.client.iter_messages(entity, **iter_args):
                                if full_depth:
                                    if from_date_obj and msg.date < from_date_obj:
                                        continue
                                    if to_date_obj and msg.date > to_date_obj:
                                        break
                                else:
                                    if to_date_obj and msg.date > to_date_obj:
                                        continue
                                    if from_date_obj and msg.date < from_date_obj:
                                        break

                                # Thread/topic extraction (forums).
                                topic_id = None
                                reply_to_id = None
                                if msg.reply_to:
                                    r = msg.reply_to
                                    forum = include_topic and bool(getattr(r, "forum_topic", False))
                                    top_id = getattr(r, "reply_to_top_id", None)
                                    reply_to_msg_id = getattr(r, "reply_to_msg_id", None)

                                    if forum:
                                        # In forums, reply_to_top_id is the topic id for replies in a topic.
                                        # For non-reply messages inside a topic, reply_to_msg_id is the topic id.
                                        topic_id = top_id if top_id is not None else reply_to_msg_id
                                        if reply_to_msg_id and top_id is not None:
                                            reply_to_id = reply_to_msg_id
                                    else:
                                        if reply_to_msg_id:
                                            reply_to_id = reply_to_msg_id

                                # Sender info (best-effort).
                                sender_id = getattr(msg, "sender_id", None)
                                if sender_id is None and getattr(msg, "from_id", None) is not None:
                                    try:
                                        sender_id = telegram_main.utils.get_peer_id(msg.from_id)
                                    except Exception:
                                        sender_id = None

                                sender_username = None
                                sender_first = None
                                sender_last = None
                                sender_user_id = None

                                if sender_id is not None:
                                    sid = int(sender_id)
                                    sender_user_id = sid
                                    info = practicants_info_by_id.get(sid) or sender_cache.get(sid)
                                    if info is None:
                                        sender_ent = None
                                        try:
                                            sender_ent = await msg.get_sender()
                                        except Exception:
                                            sender_ent = None
                                        if sender_ent is None:
                                            try:
                                                sender_ent = await telegram_main.client.get_entity(sid)
                                            except Exception:
                                                sender_ent = None
                                        if sender_ent is not None:
                                            info = {
                                                "username": getattr(sender_ent, "username", None),
                                                "firtsName": getattr(sender_ent, "first_name", None),
                                                "lastName": getattr(sender_ent, "last_name", None),
                                            }
                                            sender_cache[sid] = info

                                    if info:
                                        sender_username = info.get("username")
                                        sender_first = info.get("firtsName")
                                        sender_last = info.get("lastName")

                                if sender_username:
                                    su = str(sender_username)
                                    sender_username = su if su.startswith("@") else f"@{su}"

                                message_text = msg.message or "[Media/No text]"
                                msg_date = msg.date.isoformat() if msg.date else _TOON_NULL_SENTINEL

                                row_values = [
                                    msg.id,
                                    msg_date,
                                    *(
                                        [topic_id if topic_id is not None else _TOON_NULL_SENTINEL]
                                        if include_topic
                                        else []
                                    ),
                                    sender_user_id if sender_user_id is not None else _TOON_NULL_SENTINEL,
                                    sender_username if sender_username else _TOON_NULL_SENTINEL,
                                    sender_first if sender_first else _TOON_NULL_SENTINEL,
                                    sender_last if sender_last else _TOON_NULL_SENTINEL,
                                    reply_to_id if reply_to_id is not None else _TOON_NULL_SENTINEL,
                                    message_text,
                                ]
                                row = _encode_toon_row(row_values)
                                tf.write(f"{row}\n")

                                msg_count += 1
                                if limit and limit > 0 and msg_count >= limit:
                                    break
                    finally:
                        f.write(f"    messages[{msg_count}]{{{','.join(msg_fields)}}}:\n")
                        if tmp_path and msg_count > 0:
                            with open(tmp_path, "r", encoding="utf-8") as tf2:
                                lines = tf2.readlines()
                            if reverse_rows:
                                lines.reverse()
                            for line in lines:
                                f.write(f"      {line}")
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass

                except Exception as e:
                    # Keep output machine-readable even on errors.
                    meta = {
                        "kind": None,
                        "type": "Telegram chat",
                        "name": name_override,
                        "topics": None,
                        "practicants": [],
                        "error": str(e),
                        "llm_notes": {
                            "migrated_from_chat_id": "Only present when this chat_id is a supergroup migrated from a legacy group (old chat_id).",
                            "migrated_to_chat_id": "Only present when this chat_id is a legacy group migrated to a supergroup (new chat_id).",
                            "threads": "In forum chats, messages use `topic` (topics[].id) to identify threads.",
                            "reply_to_id": "For replies, this is the replied message id. In forum chats it is within the same `topic`.",
                        },
                    }
                    f.write(_indent_lines(_render_toon_meta(meta), "    "))
                    # Keep block structurally similar even on errors.
                    f.write(
                        "    messages[0]{id,date,user_id,username,firtsName,lastName,reply_to_id,message}:\n"
                    )

    uri = out_path.resolve().as_uri()

    return CallToolResult(
        content=[
            ResourceLink(
                type="resource_link",
                uri=uri,
                name=out_path.name,
                mimeType="text/markdown",
            )
        ],
        structuredContent={"path": str(out_path)},
    )
