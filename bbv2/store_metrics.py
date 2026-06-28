"""Admin metrics queries for the bbv2 `Store` (0021).

LLM usage rollups (with estimated cost) + per-user engagement, plus the story
click recorder. Cost is computed via `usage.estimate_cost` (lazy-imported to
avoid an import cycle) — a ballpark from token volume, not a billed amount.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .util import utc_now_iso


class MetricsQueriesMixin:
    conn: sqlite3.Connection  # provided by Store

    # ---- story clicks (engagement signal) ----
    def record_click(self, user_id: int, item_id: str) -> None:
        self.conn.execute(
            "INSERT INTO story_clicks (user_id, item_id, created_at) VALUES (?, ?, ?)",
            (user_id, item_id, utc_now_iso()),
        )
        self.conn.commit()

    # ---- LLM usage rollups ----
    def usage_summary(self, since_iso: str, until_iso: str | None = None) -> dict[str, Any]:
        """Token + estimated-cost rollups over [since, until). Folds cost per
        (dimension × model) so each model's price applies correctly. Image
        generation is priced per-image (0 tokens) and merged in separately."""
        from . import config
        from .metrics_labels import purpose_description, purpose_label
        from .usage import estimate_cost  # lazy: avoids store↔usage import cycle

        where = "created_at >= ?"
        base: list[Any] = [since_iso]
        if until_iso:
            where += " AND created_at < ?"
            base.append(until_iso)

        def grouped(extra_cols: str, group_by: str) -> list[sqlite3.Row]:
            return self.conn.execute(
                f"""SELECT {extra_cols} model,
                          COALESCE(SUM(input_tokens),0)  AS input,
                          COALESCE(SUM(output_tokens),0) AS output,
                          SUM(CASE WHEN input_tokens+output_tokens>0 THEN 1 ELSE 0 END) AS calls
                   FROM token_usage WHERE {where}
                   GROUP BY {group_by}""",
                base,
            ).fetchall()

        def fold(rows: list[sqlite3.Row], key: str | None) -> dict[Any, dict[str, Any]]:
            acc: dict[Any, dict[str, Any]] = {}
            for r in rows:
                k = r[key] if key else "_all"
                a = acc.setdefault(k, {"input": 0, "output": 0, "cost": 0.0, "calls": 0})
                inp, out = int(r["input"]), int(r["output"])
                a["input"] += inp
                a["output"] += out
                a["calls"] += int(r["calls"] or 0)
                a["cost"] += estimate_cost(r["model"], inp, out)
            return acc

        # --- image generation: priced per image, not per token. Count rows + cost. ---
        img_price = config.image_price()
        img_total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM token_usage WHERE purpose='image' AND {where}", base
            ).fetchone()[0]
        )
        img_cost = img_total * img_price
        img_by_topic = {
            r["tid"]: int(r["n"])
            for r in self.conn.execute(
                f"SELECT topic_id AS tid, COUNT(*) AS n FROM token_usage "
                f"WHERE purpose='image' AND {where} GROUP BY topic_id",
                base,
            ).fetchall()
        }

        overall = fold(grouped("", "model"), None).get(
            "_all", {"input": 0, "output": 0, "cost": 0.0, "calls": 0}
        )
        overall["cost"] += img_cost
        overall["calls"] += img_total
        overall["images"] = img_total

        by_model = [
            {"model": m or "?", **v}
            for m, v in fold(grouped("model AS k1,", "model"), "k1").items()
        ]
        if img_total:  # so the model breakdown reconciles with overall (images are 0-token)
            by_model.append({
                "model": config.grok_image_model(),
                "input": 0, "output": 0, "cost": img_cost, "calls": img_total,
            })
        # by_purpose with friendly labels; the image row's count/cost come from the
        # per-image accounting above (token-based fold sees it as 0/0).
        purpose_acc = fold(grouped("purpose AS k1, ", "purpose, model"), "k1")
        if img_total:
            img_row = purpose_acc.setdefault(
                "image", {"input": 0, "output": 0, "cost": 0.0, "calls": 0}
            )
            img_row["calls"] = img_total
            img_row["cost"] = img_cost
        by_purpose = sorted(
            (
                {
                    "purpose": p,
                    "label": purpose_label(p),
                    "description": purpose_description(p),
                    **v,
                }
                for p, v in purpose_acc.items()
            ),
            key=lambda x: x["cost"],
            reverse=True,
        )
        by_day = [
            {"date": d, **v}
            for d, v in sorted(
                fold(grouped("substr(created_at,1,10) AS k1, ", "substr(created_at,1,10), model"), "k1").items()
            )
        ]
        # topics need names joined; NULL topic_id → not-topic-specific (chat,
        # moderation, system) spend, flagged `kind` so the UI can mark it.
        trows = self.conn.execute(
            f"""SELECT tu.topic_id AS tid, t.name AS name, t.slug AS slug, tu.model AS model,
                      COALESCE(SUM(tu.input_tokens),0) AS input,
                      COALESCE(SUM(tu.output_tokens),0) AS output,
                      SUM(CASE WHEN tu.input_tokens+tu.output_tokens>0 THEN 1 ELSE 0 END) AS calls
               FROM token_usage tu LEFT JOIN topics t ON t.id = tu.topic_id
               WHERE {where.replace('created_at', 'tu.created_at')}
               GROUP BY tu.topic_id, tu.model""",
            base,
        ).fetchall()
        topic_acc: dict[Any, dict[str, Any]] = {}
        for r in trows:
            k = r["tid"]
            a = topic_acc.setdefault(
                k,
                {
                    "name": r["name"] or "Not topic-specific",
                    "slug": r["slug"],
                    "kind": "topic" if r["tid"] else "background",
                    "input": 0,
                    "output": 0,
                    "cost": 0.0,
                    "calls": 0,
                },
            )
            inp, out = int(r["input"]), int(r["output"])
            a["input"] += inp
            a["output"] += out
            a["calls"] += int(r["calls"] or 0)
            a["cost"] += estimate_cost(r["model"], inp, out)
        # Names for image-only topics (image spend but no token spend, so absent from
        # topic_acc) — one batched query instead of a per-topic SELECT in the loop.
        missing = [tid for tid in img_by_topic if tid and tid not in topic_acc]
        names: dict[Any, sqlite3.Row] = {}
        if missing:
            ph = ",".join("?" for _ in missing)
            names = {
                r["id"]: r
                for r in self.conn.execute(
                    f"SELECT id, name, slug FROM topics WHERE id IN ({ph})", missing
                ).fetchall()
            }
        # fold per-image cost into the matching topic bucket (or background for NULL)
        for tid, n in img_by_topic.items():
            a = topic_acc.get(tid)
            if a is None:
                row = names.get(tid)
                a = topic_acc[tid] = {
                    "name": (row["name"] if row else None) or "Not topic-specific",
                    "slug": row["slug"] if row else None,
                    "kind": "topic" if tid else "background",
                    "input": 0, "output": 0, "cost": 0.0, "calls": 0,
                }
            a["cost"] += n * img_price
            a["calls"] += n
        by_topic = sorted(topic_acc.values(), key=lambda x: x["cost"], reverse=True)

        return {
            "overall": overall,
            "by_model": by_model,
            "by_purpose": by_purpose,
            "by_topic": by_topic,
            "by_day": by_day,
            "images": {"count": img_total, "cost": img_cost, "unit_price": img_price},
        }

    # ---- profile stats (0028) ----
    def _user_usage(self, user_id: int, since_iso: str | None) -> dict[str, Any]:
        """Token total + estimated cost for one user (all-time if since is None)."""
        from .usage import estimate_cost

        where = "user_id = ?"
        params: list[Any] = [user_id]
        if since_iso:
            where += " AND created_at >= ?"
            params.append(since_iso)
        rows = self.conn.execute(
            f"SELECT model, COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o "
            f"FROM token_usage WHERE {where} GROUP BY model",
            params,
        ).fetchall()
        tokens = 0
        cost = 0.0
        for r in rows:
            i, o = int(r["i"]), int(r["o"])
            tokens += i + o
            cost += estimate_cost(r["model"], i, o)
        return {"tokens": tokens, "cost": cost}

    def user_profile_stats(self, user_id: int, now_iso: str) -> dict[str, Any]:
        """Personal profile metrics: subscriptions + tokens/cost across rolling
        day/week/month/year/all windows. `now_iso` is injectable for tests."""
        from datetime import datetime, timedelta

        now = datetime.fromisoformat(now_iso)
        windows = {"day": 1, "week": 7, "month": 30, "year": 365}
        usage = {
            name: self._user_usage(user_id, (now - timedelta(days=days)).isoformat())
            for name, days in windows.items()
        }
        usage["all"] = self._user_usage(user_id, None)
        subs = [
            {"slug": r["slug"], "name": r["name"]}
            for r in self.conn.execute(
                "SELECT t.slug, t.name FROM subscriptions s JOIN topics t ON t.id = s.topic_id "
                "WHERE s.user_id = ? ORDER BY t.name",
                (user_id,),
            ).fetchall()
        ]
        return {"subscriptions": subs, "usage": usage}

    # ---- per-user drill-down (0027) ----
    def user_detail(
        self, user_id: int, since_iso: str, until_iso: str | None = None
    ) -> dict[str, Any] | None:
        """One user's activity over [since, until): token usage by purpose (+cost),
        access frequency, subscriptions, and 👍/👎. Powers the metrics drill-down."""
        from .metrics_labels import purpose_label
        from .usage import estimate_cost

        u = self.conn.execute(
            "SELECT id, name, email, role, status, last_login_at, created_at "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not u:
            return None

        where = "created_at >= ?"
        tparams: list[Any] = [user_id, since_iso]
        if until_iso:
            where += " AND created_at < ?"
            tparams.append(until_iso)

        # token usage by purpose (fold cost per model so prices apply correctly)
        rows = self.conn.execute(
            f"""SELECT purpose, model,
                       COALESCE(SUM(input_tokens),0)  AS input,
                       COALESCE(SUM(output_tokens),0) AS output,
                       SUM(CASE WHEN input_tokens+output_tokens>0 THEN 1 ELSE 0 END) AS calls
                FROM token_usage WHERE user_id = ? AND {where}
                GROUP BY purpose, model""",
            tparams,
        ).fetchall()
        pacc: dict[str, dict[str, Any]] = {}
        tot_tokens = 0
        tot_cost = 0.0
        for r in rows:
            inp, out = int(r["input"]), int(r["output"])
            a = pacc.setdefault(
                r["purpose"],
                {"purpose": r["purpose"], "label": purpose_label(r["purpose"]),
                 "tokens": 0, "cost": 0.0, "calls": 0},
            )
            a["tokens"] += inp + out
            a["calls"] += int(r["calls"] or 0)
            c = estimate_cost(r["model"], inp, out)
            a["cost"] += c
            tot_tokens += inp + out
            tot_cost += c
        by_purpose = sorted(pacc.values(), key=lambda x: x["cost"], reverse=True)

        logins = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM auth_events WHERE user_id = ? AND event = 'login' AND {where}",
                tparams,
            ).fetchone()[0]
        )
        active_days = int(
            self.conn.execute(
                f"SELECT COUNT(DISTINCT substr(created_at,1,10)) FROM auth_events "
                f"WHERE user_id = ? AND event IN ('login','refresh') AND {where}",
                tparams,
            ).fetchone()[0]
        )
        subs = [
            {"slug": r["slug"], "name": r["name"]}
            for r in self.conn.execute(
                "SELECT t.slug, t.name FROM subscriptions s JOIN topics t ON t.id = s.topic_id "
                "WHERE s.user_id = ? ORDER BY t.name",
                (user_id,),
            ).fetchall()
        ]
        # Scope feedback to the same window as tokens/logins (story_feedback's time
        # column is updated_at) — else the drawer overstates engagement for the range.
        frange = "AND f.updated_at >= ?"
        fparams: list[Any] = [user_id, since_iso]
        if until_iso:
            frange += " AND f.updated_at < ?"
            fparams.append(until_iso)
        votes = {r["vote"]: int(r["n"]) for r in self.conn.execute(
            f"SELECT f.vote, COUNT(*) AS n FROM story_feedback f "
            f"WHERE f.user_id = ? AND f.vote != 0 {frange} GROUP BY f.vote",
            fparams,
        ).fetchall()}
        recent_votes = [
            {"item_id": r["item_id"], "title": r["title"], "vote": int(r["vote"]),
             "source_name": r["source_name"], "url": r["url"]}
            for r in self.conn.execute(
                f"SELECT f.item_id, f.vote, i.title, i.source_name, i.url "
                f"FROM story_feedback f LEFT JOIN items i ON i.item_id = f.item_id "
                f"WHERE f.user_id = ? AND f.vote != 0 {frange} "
                f"ORDER BY f.updated_at DESC LIMIT 15",
                fparams,
            ).fetchall()
        ]

        return {
            "user": {
                "id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"],
                "status": (u["status"] if "status" in u.keys() else "active") or "active",
                "last_login_at": u["last_login_at"], "created_at": u["created_at"],
            },
            "usage": {"tokens": tot_tokens, "cost": tot_cost, "by_purpose": by_purpose},
            "access": {"logins": logins, "active_days": active_days},
            "subscriptions": subs,
            "feedback": {
                "up": votes.get(1, 0),
                "down": votes.get(-1, 0),
                "recent": recent_votes,
            },
        }

    # ---- per-user engagement ----
    def user_engagement(self) -> list[sqlite3.Row]:
        """Per-user activity counts (excludes the system bucket, user_id 0)."""
        return self.conn.execute(
            """SELECT u.id, u.name, u.email, u.role, u.status, u.last_login_at,
                 (SELECT COALESCE(SUM(input_tokens+output_tokens),0)
                    FROM token_usage tu WHERE tu.user_id=u.id) AS tokens,
                 (SELECT COUNT(*) FROM subscriptions s WHERE s.user_id=u.id) AS topics,
                 (SELECT COUNT(*) FROM story_clicks c WHERE c.user_id=u.id) AS clicks,
                 (SELECT COUNT(*) FROM story_feedback f WHERE f.user_id=u.id AND f.vote!=0) AS votes,
                 (SELECT COUNT(*) FROM favorite_links fl WHERE fl.user_id=u.id) AS saves,
                 (SELECT COUNT(*) FROM conversation_messages m
                    WHERE m.user_id=u.id AND m.role='user') AS chats
               FROM users u WHERE u.id != 0
               ORDER BY (u.last_login_at IS NULL), u.last_login_at DESC, u.id""",
        ).fetchall()
