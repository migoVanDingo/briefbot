import { useCallback, useEffect, useState } from "react";
import StarIcon from "@mui/icons-material/StarBorder";
import SearchIcon from "@mui/icons-material/Search";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolderOutlined";
import CloseIcon from "@mui/icons-material/Close";
import { api, type Favorite, type Folder } from "../api";
import { useToasts } from "../state/toasts";
import { PageTour } from "../components/PageTour";

export function Favorites() {
  const push = useToasts((s) => s.push);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [active, setActive] = useState<string>("");
  const [items, setItems] = useState<Favorite[] | null>(null);
  const [newName, setNewName] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Favorite[] | null>(null);

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
      push(`Created folder ${f.name}`, "success");
      setNewName("");
      await loadFolders();
      setActive(f.id);
    } catch (err) {
      push(String(err), "error");
    }
  };

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    try {
      setResults(await api.searchFavorites(q));
    } catch (err) {
      push(String(err), "error");
    }
  };

  const remove = async (fav: Favorite) => {
    try {
      await api.removeFavorite(fav.id);
      setItems((prev) => (prev ? prev.filter((x) => x.id !== fav.id) : prev));
      setResults((prev) => (prev ? prev.filter((x) => x.id !== fav.id) : prev));
      loadFolders();
    } catch (e) {
      push(String(e), "error");
    }
  };

  const Row = (fav: Favorite) => (
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
        className="icon-act"
        onClick={() => remove(fav)}
        aria-label="Remove"
        title="Remove"
      >
        <CloseIcon fontSize="small" />
      </button>
    </li>
  );

  return (
    <div className="page">
      <h1 className="page-title">
        <StarIcon className="title-ico" /> Favorites
        <PageTour page="favorites" />
      </h1>

      <form className="filters card" onSubmit={search}>
        <div className="filter-search" data-tour="fav-search">
          <SearchIcon fontSize="small" className="filter-ico" />
          <input
            placeholder="Search all favorites…"
            value={query}
            maxLength={100}
            onChange={(e) => {
              const v = e.target.value;
              setQuery(v);
              if (!v.trim()) setResults(null);
            }}
          />
        </div>
        <div className="filter-controls">
          <button className="btn nowrap" type="submit">
            Search
          </button>
        </div>
      </form>

      {results !== null ? (
        results.length === 0 ? (
          <div className="empty">
            <h2>No matches</h2>
            <p className="muted">Nothing saved matches “{query}”.</p>
          </div>
        ) : (
          <ul className="list">{results.map(Row)}</ul>
        )
      ) : (
        <>
          <div className="tabs" data-tour="fav-folders">
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
              maxLength={60}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button className="btn icon-btn-text" type="submit">
              <CreateNewFolderIcon fontSize="small" />
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
            <ul className="list">{items.map(Row)}</ul>
          )}
        </>
      )}
    </div>
  );
}
