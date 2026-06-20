import { useCallback, useEffect, useState } from "react";
import { api, type Favorite, type Folder } from "../api";
import { useToasts } from "../state/toasts";

export function Favorites() {
  const push = useToasts((s) => s.push);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [active, setActive] = useState<string>("");
  const [items, setItems] = useState<Favorite[] | null>(null);
  const [newName, setNewName] = useState("");

  const loadFolders = useCallback(async () => {
    try {
      const fs = await api.favoriteFolders();
      setFolders(fs);
      setActive((cur) => cur || (fs[0]?.id ?? ""));
    } catch (e) {
      push(String(e), "error");
    }
  }, [push]);

  useEffect(() => {
    loadFolders();
  }, [loadFolders]);

  useEffect(() => {
    if (!active) return;
    setItems(null);
    api
      .favoriteItems(active)
      .then((d) => setItems(d.items))
      .catch((e) => {
        push(String(e), "error");
        setItems([]);
      });
  }, [active, push]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    try {
      const f = await api.createFolder(name);
      push(`Created folder ${name}`, "success");
      setNewName("");
      await loadFolders();
      setActive(f.id);
    } catch (err) {
      push(String(err), "error");
    }
  };

  const remove = async (fav: Favorite) => {
    try {
      await api.removeFavorite(fav.id);
      setItems((prev) => (prev ? prev.filter((x) => x.id !== fav.id) : prev));
      setFolders((prev) =>
        prev.map((f) =>
          f.id === active ? { ...f, count: Math.max(0, f.count - 1) } : f,
        ),
      );
    } catch (e) {
      push(String(e), "error");
    }
  };

  return (
    <div className="page">
      <h1 className="page-title">Favorites</h1>

      <div className="tabs">
        {folders.map((f) => (
          <button
            key={f.id}
            className={`tab${active === f.id ? " active" : ""}`}
            onClick={() => setActive(f.id)}
          >
            {f.name} ({f.count})
          </button>
        ))}
      </div>

      <form className="row-form" onSubmit={create}>
        <input
          placeholder="New folder name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button className="btn" type="submit">
          Add folder
        </button>
      </form>

      {items === null ? (
        <div className="muted pad">Loading…</div>
      ) : items.length === 0 ? (
        <div className="empty">
          <h2>Empty folder</h2>
          <p className="muted">
            Star a story on Stories or Headlines to save it here.
          </p>
        </div>
      ) : (
        <ul className="list">
          {items.map((fav) => (
            <li key={fav.id} className="list-row">
              <div className="src-info">
                <a
                  href={fav.url}
                  target="_blank"
                  rel="noreferrer"
                  className="list-title link"
                >
                  {fav.title}
                </a>
                <div className="muted small">{fav.url}</div>
              </div>
              <button
                className="btn ghost"
                onClick={() => remove(fav)}
                aria-label="Remove from folder"
                title="Remove"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
